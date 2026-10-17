# External Speech Transport

## Purpose

Provide shared OpenAI-compatible STT/TTS HTTP transport without changing local speech defaults.

## Contracts

- `normalize_config`, `is_external`, `connection`, and `configuration_error` own explicit local/openai selection and connection validation.
- `Connection` holds a validated endpoint/model/timeout and a repr-hidden API key. `public_config` omits connection settings from ordinary runtime status payloads. Secrets use the existing authenticated plugin-settings storage, never status, logs, or error messages.
- Origin-only URLs use `/v1`; explicit base paths are retained. HTTP LAN/loopback services and keyless endpoints are allowed because endpoints are selected through authenticated settings, not transcription request input.
- `transcribe` accepts WAV/WebM/MP4/Ogg/FLAC/MP3, decodes through bundled FFmpeg locally and uploads only finalized mono 16 kHz signed-16 PCM WAV (`microphone.wav`, `audio/wav`). It sends model, JSON response format, and an optional two-letter language. Auto detection omits language. This supports whisper.cpp's default in-memory decoder without requiring its optional server-side converters.
- `_pcm_wav` owns a private temporary input and one async, shell-free FFmpeg process. Input remains capped at 50 MiB, decoded audio at ten minutes, conversion at 30 seconds, and individual FFmpeg allocations at 64 MiB. Output is bounded raw PCM and Python `wave` finalizes exact RIFF/data lengths rather than using streaming WAV's unknown lengths. File-only decoding prevents network fetches. Cancellation/timeouts kill and reap only the owned converter, drain its pipes and remove the input; decoder stderr, paths and audio never enter errors/logs. Malformed/empty recordings never reach the provider and do not fall back.
- `synthesize` sends model/input/voice/speed and validates nonempty WAV output using the existing SoundFile dependency, including PCM/float WAV variants. Local voice blending is not sent to external services; remote voice is a distinct setting.
- Requests have a total configured timeout, propagate cancellation, never follow redirects, and cap audio uploads/responses at 50 MiB. HTTP/provider failures produce sanitized errors without response bodies, credentials, or automatic local fallback.
- Runtime status validates configuration only; it never sends provider probes or user data.
- `tts_options` validates external voice and speed for both synthesis and status; invalid remote speed is not coerced to the local default.
- Browser stop cancels its fetch/playback; the Flask request already admitted by the server or the provider may continue until completion/timeout. This is not an upload retraction or a provider-side cancellation API.

## Verification

Exercise real generated codecs and captured multipart WAV samples/lengths, request fields/authentication, keyless calls, malformed recordings/responses, limits, timeout/cancel cleanup, and redacted status. `docker/slim/verify_whisper_decoder.py` also exercises native browser MediaRecorder and the hash-pinned real whisper.cpp server decoder, without a model or real provider.
