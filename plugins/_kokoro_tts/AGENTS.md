# Kokoro TTS Plugin DOX

## Purpose

- Own built-in Kokoro text-to-speech integration and browser TTS fallback coordination.

## Ownership

- `api/` owns synthesize and status endpoints.
- `helpers/` owns runtime and migration behavior.
- `hooks.py` owns provider registration/lifecycle behavior.
- `webui/` owns settings and speech UI integration.
- `default_config.yaml`, `plugin.yaml`, and `README.md` own defaults, metadata, and behavior notes.

## Local Contracts

- Keep Kokoro dependencies on Docker/bootstrap paths, not opportunistic runtime installs.
- Preserve browser-native fallback when disabled or when the local backend fails; explicit external failures must not use local/browser fallback.
- Local CPU Kokoro remains the default; external model/voice settings are distinct from local voices/blends and use `helpers.external_speech`.
- Never expose connection keys in status; external readiness validates configuration without a provider probe. Return truthful WAV audio/MIME and the backend on synthesis responses so stale frontend status cannot cause remote-error fallback.
- Do not expose generated speech artifacts outside intended response paths.
- Preserve `voice` and `speed` configuration compatibility; weighted blends stay in memory and use positive finite weights.

## Work Guidance

- Coordinate status endpoint behavior with frontend fallback decisions.

## Verification

- Smoke-test status, synthesis, configured voice/speed, and disabled fallback behavior after changes.
- Run external transport/frontend tests and the loopback-only live API gate without real credentials or user text.

## Child DOX Index

No child DOX files.
