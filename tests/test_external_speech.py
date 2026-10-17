import asyncio
import base64
import io
import json
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
import shutil
import struct
import subprocess
import wave

import httpx
import pytest

from helpers import external_speech as speech


def config(**overrides):
    return {
        **speech.DEFAULT_CONFIG,
        "backend": "openai",
        "external_base_url": "http://speech.example/v1",
        "external_model": "test-model",
        "external_voice": "test-voice",
        **overrides,
    }


def wav_bytes():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b"\x00\x01" * 48)
    return buffer.getvalue()


def transport(monkeypatch, handler):
    client = httpx.AsyncClient
    mock = httpx.MockTransport(handler)
    monkeypatch.setattr(speech.httpx, "AsyncClient", lambda **kwargs: client(transport=mock, **kwargs))


def assert_pcm_wav(audio):
    assert audio[:4] == b"RIFF" and audio[8:12] == b"WAVE"
    assert struct.unpack_from("<I", audio, 4)[0] == len(audio) - 8
    assert audio[36:40] == b"data"
    assert struct.unpack_from("<I", audio, 40)[0] == len(audio) - 44
    with wave.open(io.BytesIO(audio), "rb") as wav:
        assert (wav.getnchannels(), wav.getframerate(), wav.getsampwidth()) == (1, 16000, 2)
        frames = wav.readframes(wav.getnframes())
        assert len(frames) == wav.getnframes() * 2 > 0
        assert any(frames)
    return frames


@pytest.fixture
def ffmpeg():
    binary = shutil.which("ffmpeg")
    if not binary:
        pytest.skip("Real codec tests require ffmpeg; mandatory in Linux speech compatibility CI.")
    return binary


@pytest.fixture(params=["wav", "webm", "mp4", "ogg", "flac", "mp3"])
def encoded_audio(request, tmp_path, ffmpeg):
    path = tmp_path / ("tone." + request.param)
    codec = {"webm": "libopus", "mp4": "aac", "ogg": "libopus", "flac": "flac", "mp3": "libmp3lame"}
    subprocess.run([
        ffmpeg, "-nostdin", "-v", "error", "-f", "lavfi",
        "-i", "sine=frequency=440:sample_rate=48000:duration=0.2", "-ac", "2",
        "-c:a", codec.get(request.param, "pcm_s16le"), str(path),
    ], check=True, capture_output=True, timeout=20)
    return path.read_bytes()


@pytest.mark.parametrize("key", ["", "test-only-key"])
@pytest.mark.parametrize("language", [None, "en"])
def test_transcription_maps_browser_audio_model_auth_and_language(monkeypatch, key, language, encoded_audio):
    def handler(request):
        assert str(request.url) == "http://speech.example/v1/audio/transcriptions"
        assert request.headers.get("Authorization", "") == ("Bearer " + key if key else "")
        assert b'name="model"' in request.content
        assert b"test-model" in request.content
        multipart = BytesParser(policy=default).parsebytes(
            b"Content-Type: " + request.headers["Content-Type"].encode() + b"\r\n\r\n" + request.content
        )
        file = next(part for part in multipart.iter_parts() if part.get_filename())
        assert file.get_filename() == "microphone.wav"
        assert file.get_content_type() == "audio/wav"
        frames = assert_pcm_wav(file.get_payload(decode=True))
        assert 3000 <= len(frames) // 2 <= 4000
        assert (b'name="language"' in request.content) == bool(language)
        return httpx.Response(200, json={"text": "Fixture transcript", "language": language or "en"})
    transport(monkeypatch, handler)
    result = asyncio.run(speech.transcribe(base64.b64encode(encoded_audio).decode(), config(external_api_key=key), language))
    assert result == {"text": "Fixture transcript", "language": language or "en"}


def test_tts_maps_voice_speed_and_returns_valid_wav(monkeypatch):
    audio = wav_bytes()
    def handler(request):
        assert request.url.path == "/prefix/audio/speech"
        assert "Authorization" not in request.headers
        assert json.loads(request.content) == {
            "model": "test-model", "voice": "test-voice", "input": "First.\nSecond.",
            "speed": 1.4, "response_format": "wav",
        }
        return httpx.Response(200, content=audio, headers={"Content-Type": "application/octet-stream"})
    transport(monkeypatch, handler)
    result = asyncio.run(speech.synthesize(["First.", "Second."], config(external_base_url="http://speech.example/prefix/"), 1.4))
    assert base64.b64decode(result) == audio


@pytest.mark.parametrize("override", [
    {"external_base_url": "ftp://speech.example"},
    {"external_base_url": "http://user:password@speech.example"},
    {"external_base_url": "http://speech.example?key=not-for-status"},
    {"external_base_url": "http://speech.example/#fragment"},
    {"external_base_url": "http://speech.example:bad"},
    {"external_base_url": "http://speech.example/\n"},
    {"external_model": ""},
    {"external_api_key": "test\r\nheader"},
    {"external_api_key": "non-ascii-\u00e9"},
    {"request_timeout": 0},
    {"request_timeout": float("inf")},
    {"request_timeout": "bad"},
])
def test_invalid_configuration_is_explicit_and_safe(override):
    error = speech.configuration_error(config(**override))
    assert error
    assert "password" not in error
    assert "not-for-status" not in error
    assert "test\r\nheader" not in error


def test_status_redacts_key_and_url_and_unknown_backend_never_becomes_local():
    visible = speech.public_config(config(external_api_key="test-only-secret"))
    assert "external_api_key" not in visible and "external_base_url" not in visible
    assert speech.connection(config(external_base_url="http://speech.example")).base_url.endswith("/v1")
    for backend in ("unknown", "", None):
        normalized = speech.normalize_config({"backend": backend})
        with pytest.raises(ValueError, match="backend"):
            speech.is_external(normalized)
    assert not speech.is_external(speech.normalize_config({}))
    assert "test-only-secret" not in repr(speech.connection(config(external_api_key="test-only-secret")))


@pytest.mark.parametrize("status", [302, 400, 401, 429, 500])
def test_provider_errors_do_not_redirect_or_disclose_response_bodies(monkeypatch, status):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, text="private provider detail", headers={"Location": "http://elsewhere.example"})
    transport(monkeypatch, handler)
    with pytest.raises(ValueError, match=f"HTTP {status}") as raised:
        asyncio.run(speech.synthesize(["Fixture"], config(), 1.0))
    assert len(requests) == 1
    assert "private provider detail" not in str(raised.value)


@pytest.mark.parametrize("payload", [b"not JSON", b"[]", b'{"text":42}', b'{"text":"ok","language":42}'])
def test_bad_transcription_responses_are_rejected(monkeypatch, payload, ffmpeg):
    transport(monkeypatch, lambda request: httpx.Response(200, content=payload))
    with pytest.raises(ValueError, match="External STT"):
        asyncio.run(speech.transcribe(base64.b64encode(wav_bytes()).decode(), config(), None))


@pytest.mark.parametrize("payload", [b"", b"ID3-not-wav", b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 40])
def test_bad_speech_audio_is_rejected(monkeypatch, payload):
    transport(monkeypatch, lambda request: httpx.Response(200, content=payload))
    with pytest.raises(ValueError, match="External TTS"):
        asyncio.run(speech.synthesize(["Fixture"], config(), 1.0))


@pytest.mark.parametrize("speed", [0.1, 4.1, float("inf"), -1, None, "invalid"])
def test_unsupported_remote_speed_is_explicit(speed):
    with pytest.raises(ValueError, match="speed"):
        asyncio.run(speech.synthesize(["Fixture"], config(), speed))


def test_status_checks_remote_voice_and_speed_without_a_request():
    assert "voice" in speech.configuration_error(config(external_voice=""), tts=True)
    assert "speed" in speech.configuration_error(config(speed=-1), tts=True)
    assert "speed" in speech.configuration_error(config(speed="inf"), tts=True)


def test_limits_and_timeout_errors_are_bounded(monkeypatch):
    monkeypatch.setattr(speech, "MAX_AUDIO_BYTES", 16)
    with pytest.raises(ValueError, match="upload exceeds"):
        asyncio.run(speech.transcribe(base64.b64encode(wav_bytes()).decode(), config(), None))
    transport(monkeypatch, lambda request: httpx.Response(200, content=b"x" * 17))
    with pytest.raises(ValueError, match="response exceeds"):
        asyncio.run(speech.synthesize(["Fixture"], config(), 1))


def test_total_timeout_and_cancellation_propagate(monkeypatch):
    async def handler(request):
        await asyncio.Event().wait()
    transport(monkeypatch, handler)
    with pytest.raises(ValueError, match="timed out"):
        asyncio.run(speech.synthesize(["Fixture"], config(request_timeout=0.01), 1))
    async def cancel():
        task = asyncio.create_task(speech.synthesize(["Fixture"], config(), 1))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(cancel())


def test_network_errors_are_sanitized(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("private connection detail", request=request)
    transport(monkeypatch, handler)
    with pytest.raises(ValueError, match="connection failed") as raised:
        asyncio.run(speech.synthesize(["Fixture"], config(), 1))
    assert "private connection detail" not in str(raised.value)


@pytest.mark.parametrize("audio", [
    b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 20,
    b"\x1a\x45\xdf\xa3incomplete",
    b"\x00\x00\x00\x18ftypincomplete",
    wav_bytes()[:-20],
])
def test_real_decoder_rejects_incomplete_recordings_before_upload(monkeypatch, audio, ffmpeg):
    def unexpected(request):
        pytest.fail("Invalid audio must never reach the external service")
    transport(monkeypatch, unexpected)
    with pytest.raises(ValueError, match="decode|samples"):
        asyncio.run(speech.transcribe(base64.b64encode(audio).decode(), config(), None))


@pytest.mark.parametrize("encoded,error", [
    ("", "empty"), ("not valid base64!", "base64"),
    (base64.b64encode(b"invalid").decode(), "unsupported"),
])
def test_invalid_input_never_starts_converter_or_provider(monkeypatch, encoded, error):
    async def unexpected(*args, **kwargs):
        pytest.fail("Invalid input must not start a converter/provider")
    monkeypatch.setattr(speech, "_pcm_wav", unexpected)
    monkeypatch.setattr(speech, "_request", unexpected)
    with pytest.raises(ValueError, match=error):
        asyncio.run(speech.transcribe(encoded, config(), None))


@pytest.mark.parametrize("mode,error", [
    ("failure", "could not decode"), ("empty", "no decodable"),
    ("odd", "no decodable"), ("timeout", "conversion timed out"),
    ("oversize", "10 minutes"), ("missing", "requires ffmpeg"),
])
def test_converter_failure_timeout_and_output_limits_clean_owned_resources(monkeypatch, mode, error):
    processes = []
    paths = []
    monkeypatch.setattr(speech, "STT_CONVERSION_TIMEOUT", 0.01 if mode == "timeout" else 5)
    monkeypatch.setattr(speech, "MAX_STT_SECONDS", 1)

    class Process:
        returncode = None
        killed = False
        stdout = None
        sent = False

        def __init__(self):
            self.stdout = self

        async def read(self, _):
            if mode == "timeout":
                await asyncio.Event().wait()
            if self.sent:
                return b""
            self.sent = True
            return {
                "empty": b"", "odd": b"x", "failure": b"\x00\x01",
                "oversize": b"x" * (speech.STT_SAMPLE_RATE * 2 + 1),
            }[mode]

        async def wait(self):
            self.returncode = -9 if self.killed else 1 if mode == "failure" else 0
            return self.returncode

        async def communicate(self):
            await self.wait()
            return b"", b""

        def kill(self):
            self.killed = True

    async def spawn(*args, **kwargs):
        path = Path(args[args.index("-i") + 1])
        paths.append(path)
        assert path.read_bytes() == b"fixture"
        assert kwargs["stderr"] == asyncio.subprocess.DEVNULL
        assert "-xerror" in args and "-protocol_whitelist" in args
        if mode == "missing":
            raise FileNotFoundError("private local detail")
        process = Process()
        processes.append(process)
        return process

    monkeypatch.setattr(speech.asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(ValueError, match=error):
        asyncio.run(speech._pcm_wav(b"fixture"))
    assert paths and all(not path.parent.exists() for path in paths)
    if processes:
        assert processes[0].returncode is not None
        assert processes[0].killed == (mode in ("oversize", "timeout"))


@pytest.mark.parametrize("during_spawn", [False, True])
def test_converter_cancellation_reaps_owned_process_and_removes_input(monkeypatch, during_spawn):
    async def scenario():
        ready, release = asyncio.Event(), asyncio.Event()
        paths, processes = [], []

        class Process:
            returncode = None
            killed = False

            def __init__(self):
                self.stdout = self

            async def read(self, _):
                ready.set()
                await asyncio.Event().wait()

            def kill(self):
                self.killed = True
                self.returncode = -9

            async def wait(self):
                return self.returncode

            async def communicate(self):
                return b"", b""

        async def spawn(*args, **kwargs):
            paths.append(Path(args[args.index("-i") + 1]))
            if during_spawn:
                ready.set()
                await release.wait()
            process = Process()
            processes.append(process)
            return process

        monkeypatch.setattr(speech.asyncio, "create_subprocess_exec", spawn)
        task = asyncio.create_task(speech._pcm_wav(b"fixture"))
        await ready.wait()
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(processes) == 1 and processes[0].killed
        assert all(not path.parent.exists() for path in paths)
    asyncio.run(scenario())
