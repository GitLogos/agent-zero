"""OpenAI-compatible audio transport for explicitly configured speech backends."""

import asyncio
import base64
import binascii
from dataclasses import dataclass, field
import io
import json
import math
import re
from urllib.parse import urlsplit, urlunsplit

import httpx


DEFAULT_CONFIG = {
    "backend": "local",
    "external_base_url": "",
    "external_api_key": "",
    "external_model": "",
    "request_timeout": 120.0,
}
MAX_AUDIO_BYTES = 50 * 1024 * 1024


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
    if audio.startswith(b"RIFF") and audio[8:12] == b"WAVE":
        filename, mime = "microphone.wav", "audio/wav"
    elif audio.startswith(b"\x1a\x45\xdf\xa3"):
        filename, mime = "microphone.webm", "audio/webm"
    elif audio[4:8] == b"ftyp":
        filename, mime = "microphone.mp4", "audio/mp4"
    elif audio.startswith(b"OggS"):
        filename, mime = "microphone.ogg", "audio/ogg"
    elif audio.startswith(b"fLaC"):
        filename, mime = "microphone.flac", "audio/flac"
    elif audio.startswith(b"ID3") or (len(audio) >= 2 and audio[0] == 255 and audio[1] & 224 == 224):
        filename, mime = "microphone.mp3", "audio/mpeg"
    else:
        raise ValueError("Audio format is unsupported; use WAV, WebM, MP4, Ogg, FLAC, or MP3.")
    data = {"model": settings.model, "response_format": "json"}
    if language:
        if not re.fullmatch(r"[a-z]{2}", language):
            raise ValueError("External STT language must be a two-letter ISO code or auto.")
        data["language"] = language
    body = await _request(
        settings, "transcriptions", data=data,
        files={"file": (filename, audio, mime)},
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
