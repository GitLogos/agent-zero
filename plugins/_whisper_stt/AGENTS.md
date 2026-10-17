# Whisper STT Plugin DOX

## Purpose

- Own built-in Whisper speech-to-text integration, microphone runtime settings, and transcription delivery behavior.

## Ownership

- `api/` owns transcribe and status endpoints.
- `helpers/` owns runtime and migration behavior.
- `hooks.py` owns provider registration/lifecycle behavior.
- `webui/` owns settings, main speech UI, store, and styling.
- `default_config.yaml`, `plugin.yaml`, and `README.md` own defaults, metadata, and behavior notes.

## Local Contracts

- Keep dependency installation and model bootstrap on Docker/bootstrap paths.
- Preserve configured message mode, language, silence threshold, silence duration, and waiting timeout behavior.
- Local CPU Whisper remains the default; explicit `openai` configuration uses `helpers.external_speech` and never falls back on remote failure.
- Keep connection secrets out of status; external readiness means configured, not connection-tested. External model IDs are not local model-size choices.
- Settings initialize absent connection fields only; explicit invalid external settings must not silently become local/default settings.
- Only local model changes trigger local preload; microphone cancellation must suppress stale transcripts without changing send/draft behavior.
- Every utterance retains one complete MediaRecorder container, from listening preroll through the final dataavailable queued by stop. VAD states never selectively discard chunks. Idle captures rotate with a bounded one-second overlap, retaining at least one second of preroll after warmup; discarded idle captures are never uploaded. Dispose/error/stop releases pending encoders/timers/streams and suppresses late initialization, conversion and request results.
- Recorder Blob MIME follows the actual codec; external transport normalizes real bytes to finalized mono16k signed16 WAV before upload. Do not relabel encoded browser media as WAV or require whisper.cpp's optional server-side FFmpeg conversion.
- Images may omit local Whisper; imports remain lazy, preload/model changes cannot download it, and selected local mode reports an explicit configuration error. Status/settings expose local availability; external STT still works without the local library and saved backend choices remain unchanged.
- Keep all `data-whisper-microphone` controls synchronized with the same microphone status.
- Optional final-transcript handlers must receive the configured draft/send mode without changing the main chat microphone's delivery behavior.
- Do not expose raw audio or transcriptions beyond intended UI/API paths.

## Work Guidance

- Coordinate status endpoint behavior with frontend microphone and transcription state.

## Verification

- Smoke-test status, transcription, model/language settings, send/draft modes, and silence handling after changes.
- Run external transport/frontend tests and the loopback-only live API image gate; never test with user recordings or real provider credentials.

## Child DOX Index

No child DOX files.
