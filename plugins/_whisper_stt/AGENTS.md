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
- Only local model changes trigger local preload; microphone cancellation must suppress stale transcripts without changing send/draft behavior.
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
