import asyncio
import base64
import io
import json
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


@pytest.mark.parametrize("key", ["", "test-only-key"])
@pytest.mark.parametrize("language", [None, "en"])
@pytest.mark.parametrize("audio,filename,mime", [
    (wav_bytes(), "microphone.wav", "audio/wav"),
    (b"\x1a\x45\xdf\xa3browser-fixture", "microphone.webm", "audio/webm"),
    (b"\x00\x00\x00\x18ftypbrowser-fixture", "microphone.mp4", "audio/mp4"),
])
def test_transcription_maps_browser_audio_model_auth_and_language(monkeypatch, key, language, audio, filename, mime):
    def handler(request):
        assert str(request.url) == "http://speech.example/v1/audio/transcriptions"
        assert request.headers.get("Authorization", "") == ("Bearer " + key if key else "")
        assert b'name="model"' in request.content
        assert b"test-model" in request.content
        assert f'filename="{filename}"'.encode() in request.content
        assert f"Content-Type: {mime}".encode() in request.content
        assert audio in request.content
        assert (b'name="language"' in request.content) == bool(language)
        return httpx.Response(200, json={"text": "Fixture transcript", "language": language or "en"})
    transport(monkeypatch, handler)
    result = asyncio.run(speech.transcribe(base64.b64encode(audio).decode(), config(external_api_key=key), language))
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
def test_bad_transcription_responses_are_rejected(monkeypatch, payload):
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
