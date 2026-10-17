# Whisper STT

Speech-to-text plugin with local CPU Whisper (default) and an explicit external OpenAI-compatible backend.

## Responsibilities

- Registers Whisper as the active STT provider when the plugin is enabled.
- Owns the microphone runtime, device selector UI, message delivery mode, and plugin APIs.
- Keeps dependency installation and model bootstrap on the Docker/bootstrap path.
- With `A0_INCLUDE_WHISPER=false`, local transcription/model downloads are unavailable.
  Select and configure the external backend explicitly; saved local settings are not switched automatically.

## Config

- `model_size`: Whisper model name
- `language`: language hint or `auto`
- `message_mode`: `send` to send final transcriptions immediately, or `draft` to leave them in the composer
- `silence_threshold`: frontend threshold before recording starts
- `silence_duration`: silence window before waiting state
- `waiting_timeout`: delay before transcription dispatch

### External OpenAI-compatible backend

Set `backend: openai`, `external_base_url`, `external_model`, and optionally
`external_api_key`. Local remains `backend: local`; the saved local `model_size`
is retained but never sent to an external service. `request_timeout` defaults to
120 seconds and bounds the complete external request.

An origin-only base URL uses `/v1`. Explicit API prefixes are retained, including
`/v1` or a custom proxy prefix; do not enter the complete audio endpoint.
The runtime calls `POST <base>/audio/transcriptions` with multipart model, file,
and `response_format=json`. Browser recordings are decoded **on the Agent Zero
server** using bundled FFmpeg, then uploaded as actual mono 16 kHz signed-16 PCM
WAV (`microphone.wav`, `audio/wav`) with finalized RIFF/data lengths. This works
with whisper.cpp's default audio decoder without enabling its optional server
converters. WAV, WebM/Opus, MP4/AAC, Ogg, FLAC and MP3 input remain supported;
relabeling a WebM Blob as WAV is not conversion.
`language: auto` omits the language; an external
language hint must be a two-letter ISO code such as `en`. Language names remain
local-only. Message delivery and silence controls apply to both backends.

Blank API keys support keyless LAN/loopback services. Keys use existing private
server-side plugin settings and are omitted from status, errors and logs. Use
HTTPS except for trusted local services. URLs cannot contain credentials,
query parameters or fragments; redirects are not followed. Audio uploads and
responses are capped at 50 MiB; recordings are limited to ten minutes and local
conversion to 30 seconds. A provider can impose a smaller limit. Direct
non-Docker installs also need `ffmpeg` on PATH. Decode failures are explicit and
no malformed/raw fallback recording is sent.

The microphone retains each complete encoded recording, including bounded
pre-speech audio and the encoder's final stop chunk, before dispatch. While
listening, complete idle recordings rotate with a one-second overlap to retain
first syllables without unbounded idle history. Idle-only buffers are discarded,
not uploaded. Speech/silence/waiting controls still determine when to transcribe.

Selecting external authorizes sending recordings to that configured service.
Status says **Configured**, not connection-tested. Failures are explicit and
never start local transcription. Stop aborts the browser request and suppresses
stale transcripts; a server/provider request already admitted may finish before
its timeout. It cannot retract an uploaded recording.

## API

- `POST /api/plugins/_whisper_stt/transcribe`
- `POST /api/plugins/_whisper_stt/status`
