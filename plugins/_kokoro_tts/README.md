# Kokoro TTS

Speech synthesis plugin with local CPU Kokoro (default) and an explicit external OpenAI-compatible backend.

## Behavior

- Registers Kokoro as the active TTS provider when the plugin is enabled.
- Supports single voices, comma-separated equal blends, and optional in-memory weighted blends.
- Keeps browser-native `speechSynthesis` as the fallback path when disabled.
- Keeps Python dependencies on the core Docker/bootstrap path. This plugin does not install packages or binaries on demand.
- Uses Kokoro's existing voice-pack cache and does not create persistent blend files.
- With `A0_INCLUDE_KOKORO=false`, local voices/blends are unavailable. Configure
  external TTS explicitly, or disable this plugin deliberately to use browser speech.
  A selected but excluded local engine reports an error, not an automatic fallback.

## Config

- `voice`: Kokoro voice identifier or comma-separated equal blend
- `voice_weights`: optional mapping of voice identifiers to positive weights; when present, it defines the active blend
- `speed`: Kokoro playback speed multiplier

### External OpenAI-compatible backend

Set `backend: openai`, `external_base_url`, `external_model`, `external_voice`,
and optionally `external_api_key`. `backend: local` retains the current Kokoro
pipeline and local voice settings. External uses its separate voice identifier;
saved local voice expressions/weighted blends are preserved but are not sent or
supported as remote blend controls.

The runtime calls `POST <base>/audio/speech` with model, input, voice, speed, and
`response_format=wav`. An origin-only URL uses `/v1`; explicit API prefixes are
retained. Do not enter the full audio endpoint. Speed is forwarded (OpenAI range
0.25-4; existing UI range 0.5-3), never silently discarded. The provider must
support speed and WAV output; unsupported options and invalid/empty WAV
responses are errors. Playback responses retain base64 audio and `audio/wav`.

Blank keys support keyless LAN/loopback endpoints. Keys use existing private
server-side plugin settings, not status, browser storage or logs. Use HTTPS
except for trusted local services. Embedded URL credentials/query/fragment and
redirects are rejected. `request_timeout` defaults to 120 seconds for the whole
request; responses are capped at 50 MiB.

Selecting external sends spoken text to that service. **Configured** validates
settings without a provider probe. External failures never silently use local
or browser speech. Disabled/local-plugin browser fallback is preserved. Stop
cancels pending browser fetch/playback; a server/provider request already
admitted may finish before its timeout. Uploads cannot be retracted.

## Routes

- `POST /api/plugins/_kokoro_tts/synthesize`
- `POST /api/plugins/_kokoro_tts/status`
