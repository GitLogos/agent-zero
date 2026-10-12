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
and `response_format=json`. Browser WAV/WebM/MP4 recordings are uploaded with
their actual container MIME type. `language: auto` omits the language; an external
language hint must be a two-letter ISO code such as `en`. Language names remain
local-only. Message delivery and silence controls apply to both backends.

Blank API keys support keyless LAN/loopback services. Keys use existing private
server-side plugin settings and are omitted from status, errors and logs. Use
HTTPS except for trusted local services. URLs cannot contain credentials,
query parameters or fragments; redirects are not followed. Audio uploads and
responses are capped at 50 MiB; a provider can impose a smaller limit.

Selecting external authorizes sending recordings to that configured service.
Status says **Configured**, not connection-tested. Failures are explicit and
never start local transcription. Stop aborts the browser request and suppresses
stale transcripts; a server/provider request already admitted may finish before
its timeout. It cannot retract an uploaded recording.

## API

- `POST /api/plugins/_whisper_stt/transcribe`
- `POST /api/plugins/_whisper_stt/status`
