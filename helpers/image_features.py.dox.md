# image_features.py DOX

## Purpose

- Own six build capabilities (Desktop, Office, local Whisper/Kokoro, Chromium, SearXNG) from `/etc/a0-image-features.json`.

## Contracts

- `get_features` reads/caches a strict boolean manifest; missing manifests preserve legacy full functionality. Malformed manifests raise rather than silently enabling omitted features.
- `available`, `require`, `missing_reason`, and `unavailable_reason` share checks for discovery, toggles, APIs, preparation hooks and direct runtime calls.
- The manifest is outside `/a0` and mounted `usr/`, so repository self-update and scoped `.toggle-1` files cannot re-enable omitted components.
- This is packaging metadata, not an authentication boundary. Existing route security remains required.
- Desktop exclusions do not exclude Browser's shared Xpra/Xvfb runtime; Office exclusions do not remove pure document storage/parsing libraries.
- Speech exclusions leave external backends available without importing local libraries. Excluded Chromium cannot be reconciled/downloaded; excluded search requires an explicit external endpoint.
- Health/status reports only public capability booleans/reasons, never private configuration.

## Verification

- Run `tests/test_image_features.py`, `tests/test_image_feature_runtime.py`, and native all-on/all-off/mixed profile gates.
