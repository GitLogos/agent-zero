"""OpenAI-compatible audio transport for explicitly configured speech backends."""

import asyncio
import base64
import binascii
from dataclasses import dataclass, field
import io
import json
import math
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit, urlunsplit
import wave

import httpx


DEFAULT_CONFIG = {
    "backend": "local",
    "external_base_url": "",
    "external_api_key": "",
    "external_model": "",
    "request_timeout": 120.0,
}
MAX_AUDIO_BYTES = 50 * 1024 * 1024
MAX_STT_SECONDS = 600
STT_SAMPLE_RATE = 16000
STT_CONVERSION_TIMEOUT = 30


@dataclass(frozen=True)
class Connection:
    base_url: str
    model: str
    timeout: float
    api_key: str = field(repr=False)


def normalize_config(config: dict) -> dict:
    return {
        **{key: str(config.get(key, default) or "").strip()
           for key, default in DEFAULT_CONFIG.items() if key != "request_timeout"},
        "backend": str(config.get("backend", "local")).strip().lower(),
        "request_timeout": config.get("request_timeout", 120.0),
    }


def public_config(config: dict) -> dict:
    return {
        key: value for key, value in config.items()
        if key not in ("external_api_key", "external_base_url", "request_timeout")
    }


def is_external(config: dict) -> bool:
    if config["backend"] not in ("local", "openai"):
        raise ValueError("Speech backend must be local or openai.")
    return config["backend"] == "openai"


def connection(config: dict) -> Connection:
    if any(char.isspace() or ord(char) < 32 for char in config["external_base_url"]):
        raise ValueError("External speech base URL must not contain whitespace.")
    try:
        url = urlsplit(config["external_base_url"])
        port = url.port
    except ValueError:
        raise ValueError("External speech base URL is invalid.") from None
    if (
        url.scheme not in ("http", "https") or not url.hostname
        or url.username is not None or url.password is not None
        or url.query or url.fragment or port == 0
    ):
        raise ValueError("Use an HTTP(S) speech base URL without credentials, query, or fragment.")
    model = config["external_model"]
    if not model:
        raise ValueError("External speech model is required.")
    try:
        timeout = float(config["request_timeout"])
    except (TypeError, ValueError):
        raise ValueError("Speech request timeout must be a positive finite number.") from None
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Speech request timeout must be a positive finite number.")
    key = config["external_api_key"]
    if any(ord(char) < 32 or ord(char) > 126 for char in key):
        raise ValueError("Speech API key must contain printable ASCII characters.")
    path = url.path.rstrip("/") or "/v1"
    base_url = urlunsplit((url.scheme, url.netloc, path, "", ""))
    try:
        httpx.URL(base_url)
    except httpx.InvalidURL:
        raise ValueError("External speech base URL is invalid.") from None
    return Connection(base_url, model, timeout, key)


def tts_options(config: dict) -> tuple[str, float]:
    voice = str(config.get("external_voice", "") or "").strip()
    if not voice:
        raise ValueError("External TTS voice is required.")
    try:
        speed = float(config.get("speed", 1.1))
    except (TypeError, ValueError):
        raise ValueError("OpenAI-compatible TTS speed must be between 0.25 and 4.") from None
    if not math.isfinite(speed) or not 0.25 <= speed <= 4:
        raise ValueError("OpenAI-compatible TTS speed must be between 0.25 and 4.")
    return voice, speed


def configuration_error(config: dict, *, tts: bool = False) -> str:
    try:
        if is_external(config):
            connection(config)
            if tts:
                tts_options(config)
    except ValueError as exc:
        return str(exc)
    return ""


async def _request(settings: Connection, endpoint: str, **kwargs) -> bytes:
    headers = {"Authorization": f"Bearer {settings.api_key}"} if settings.api_key else {}
    try:
        async with asyncio.timeout(settings.timeout):
            try:
                client = httpx.AsyncClient(timeout=settings.timeout, follow_redirects=False)
            except (httpx.InvalidURL, ValueError, OSError):
                raise ValueError("External speech HTTP client configuration failed; check TLS/proxy settings.") from None
            async with client:
                async with client.stream(
                    "POST", f"{settings.base_url}/audio/{endpoint}", headers=headers, **kwargs
                ) as response:
                    if not 200 <= response.status_code < 300:
                        raise ValueError(
                            f"External speech service returned HTTP {response.status_code}; "
                            "check its URL, authentication, model, and supported options."
                        )
                    chunks = []
                    size = 0
                    async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                        size += len(chunk)
                        if size > MAX_AUDIO_BYTES:
                            raise ValueError("External speech response exceeds the 50 MiB limit.")
                        chunks.append(chunk)
                    return b"".join(chunks)
    except (TimeoutError, httpx.TimeoutException):
        raise ValueError("External speech request timed out.") from None
    except httpx.HTTPError:
        raise ValueError("External speech connection failed; check the URL and TLS/proxy settings.") from None


async def _pcm_wav(audio: bytes) -> bytes:
    """Decode locally; only finalized PCM WAV is sent to external STT."""
    max_pcm_bytes = MAX_STT_SECONDS * STT_SAMPLE_RATE * 2
    with tempfile.TemporaryDirectory(prefix="a0-stt-") as directory:
        source = Path(directory, "recording")
        # Shield the owned write so cancellation cannot race temporary cleanup.
        write = asyncio.create_task(asyncio.to_thread(source.write_bytes, audio))
        try:
            await asyncio.shield(write)
        finally:
            await write
        process = None
        try:
            async with asyncio.timeout(STT_CONVERSION_TIMEOUT):
                try:
                    launch = asyncio.create_task(asyncio.create_subprocess_exec(
                        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                        "-xerror", "-max_alloc", "67108864",
                        "-protocol_whitelist", "file,pipe", "-threads", "1",
                        "-i", str(source), "-map", "0:a:0", "-vn", "-sn", "-dn",
                        "-t", str(MAX_STT_SECONDS + 1), "-ac", "1", "-ar", str(STT_SAMPLE_RATE),
                        "-c:a", "pcm_s16le", "-threads", "1", "-f", "s16le", "pipe:1",
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                        stdin=asyncio.subprocess.DEVNULL,
                    ))
                    try:
                        process = await asyncio.shield(launch)
                    finally:
                        if process is None:
                            process = await launch
                except FileNotFoundError:
                    raise ValueError(
                        "External STT audio conversion requires ffmpeg on the Agent Zero server."
                    ) from None
                except (OSError, NotImplementedError):
                    raise ValueError("External STT could not start the ffmpeg audio converter.") from None
                pcm = bytearray()
                assert process.stdout is not None
                while chunk := await process.stdout.read(64 * 1024):
                    if len(pcm) + len(chunk) > max_pcm_bytes:
                        raise ValueError("External STT recordings must not exceed 10 minutes.")
                    pcm.extend(chunk)
                if await process.wait() != 0:
                    raise ValueError(
                        "External STT could not decode the recording. Send a complete, "
                        "valid audio file; incomplete or unsupported codecs cannot be uploaded."
                    )
                if not pcm or len(pcm) % 2:
                    raise ValueError("External STT recording contains no decodable audio samples.")
        except TimeoutError:
            raise ValueError("External STT audio conversion timed out.") from None
        finally:
            if process is not None and process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass  # The owned converter can exit between returncode and kill.
                await process.communicate()
    # ffmpeg WAV on stdout has unknown RIFF/data lengths. Finalize a seekable
    # in-memory WAV instead, including exact lengths for whisper.cpp's decoder.
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(STT_SAMPLE_RATE)
        wav.writeframes(pcm)
    return output.getvalue()


async def transcribe(audio_base64: str, config: dict, language: str | None) -> dict:
    settings = connection(config)
    if len(audio_base64) > (MAX_AUDIO_BYTES + 2) // 3 * 4:
        raise ValueError("Audio upload exceeds the 50 MiB limit.")
    try:
        audio = base64.b64decode(audio_base64, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("Audio must be valid base64.") from None
    if not audio:
        raise ValueError("Audio upload is empty.")
    if len(audio) > MAX_AUDIO_BYTES:
        raise ValueError("Audio upload exceeds the 50 MiB limit.")
    if not (
        (audio.startswith(b"RIFF") and audio[8:12] == b"WAVE")
        or audio.startswith((b"\x1a\x45\xdf\xa3", b"OggS", b"fLaC", b"ID3"))
        or audio[4:8] == b"ftyp"
        or (len(audio) >= 2 and audio[0] == 255 and audio[1] & 224 == 224)
    ):
        raise ValueError("Audio format is unsupported; use WAV, WebM, MP4, Ogg, FLAC, or MP3.")
    data = {"model": settings.model, "response_format": "json"}
    if language:
        if not re.fullmatch(r"[a-z]{2}", language):
            raise ValueError("External STT language must be a two-letter ISO code or auto.")
        data["language"] = language
    try:
        audio = await _pcm_wav(audio)
    except OSError:
        raise ValueError("External STT audio conversion failed; check FFmpeg and temporary storage.") from None
    body = await _request(
        settings, "transcriptions", data=data,
        files={"file": ("microphone.wav", audio, "audio/wav")},
    )
    try:
        result = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("External STT returned invalid JSON.") from None
    if not isinstance(result, dict) or not isinstance(result.get("text"), str):
        raise ValueError("External STT response must contain a text string.")
    if "language" in result and not isinstance(result["language"], str):
        raise ValueError("External STT response language must be a string.")
    return {"text": result["text"], "language": result.get("language", language or "")}


async def synthesize(sentences: list[str], config: dict, speed: float) -> str:
    settings = connection(config)
    voice, speed = tts_options({**config, "speed": speed})
    text = "\n".join(sentences).strip()
    if not text:
        raise ValueError("Speech text is empty.")
    body = await _request(settings, "speech", json={
        "model": settings.model, "input": text, "voice": voice,
        "speed": speed, "response_format": "wav",
    })
    if len(body) < 44 or not body.startswith(b"RIFF") or body[8:12] != b"WAVE":
        raise ValueError("External TTS did not return the requested WAV audio.")
    import soundfile

    try:
        with soundfile.SoundFile(io.BytesIO(body)) as audio:
            if audio.frames <= 0 or not audio.read(1).size:
                raise ValueError("External TTS returned empty WAV audio.")
    except (RuntimeError, OSError):
        raise ValueError("External TTS returned invalid WAV audio.") from None
    return base64.b64encode(body).decode("ascii")
