# Image Footprint DOX

## Purpose

- Own the experimental GHCR image and its feature-preserving footprint work.

## Ownership

- `Dockerfile` assembles the runtime candidate.
- `profile.py` inventories a container filesystem without starting services.
- `smoke.py` exercises real features in a disposable started container.
- `README.md` describes supported features and build/measurement commands.
- `.github/workflows/image-footprint.yml` measures the published amd64 baseline, builds native candidates, and publishes experimental tags only after functional checks.

## Local Contracts

- Measure uncompressed image bytes separately from compressed registry layers and merged filesystem allocation; never claim the reduction from download size.
- Retain both Python runtimes and the complete interactive Browser/Desktop/Office stack in full-functionality candidates.
- Do not remove supported components, fonts, models, formats, compilation tools, or offline capabilities to meet a size target without approval.
- Keep experimental tags separate from stable images until functional checks succeed.
- Preserve Agent Zero Git metadata for versioning, self-update, and rollback.

## Work Guidance

- Eliminate installation caches and build residue in the layer that creates them.
- The candidate uses the immutable, verified Python 3.13-compatible base as an intermediate only, then copies the cleaned merged root into its own final stage; retain original runtime environment defaults. Unpinned current Kali defaults and version-coupled GLib packages are not compatible with the pinned Xpra/UNO stack.
- Use distribution and APT inventories to identify large components before changing dependency resolution.
- Treat separate `du` totals as overlapping; hardlinks and nested paths cannot be added.

## Verification

- Build the image on Linux and run real feature checks before publication.
- Record Docker `Size`, registry compressed layer bytes, and merged filesystem usage.

## Child DOX Index

No child DOX files.
