# GitHub Automation DOX

## Purpose

- Own repository automation that runs on GitHub, including workflows and release-planning scripts.
- Keep CI, Docker publishing, stale issue handling, and release-note generation aligned with repository release rules.

## Ownership

- `workflows/` contains GitHub Actions workflow definitions.
- `scripts/` contains Python helpers called by workflows.
- This file owns release automation rules; user-facing release documentation belongs under `docs/`.

## Local Contracts

- Docker publishing lives in `workflows/docker-publish.yml` and delegates planning to `scripts/docker_release_plan.py`.
- Releasable tags are `vX.Y` tags at or above `v1.0`, matching the workflow environment.
- On `main`, the newest eligible tag publishes both the version tag and `latest`, then creates or updates its GitHub release after the image push succeeds; other allowed branches publish only their branch tag.
- Manual dispatch without a tag backfills missing Docker Hub tags. Manual dispatch with a tag rebuilds that target and refreshes `latest` and the GitHub release only when it remains the newest eligible tag on `main`.
- Release-note generation reads `scripts/openrouter_release_notes_system_prompt.md` from the repository root and requires OpenRouter credentials from workflow environment variables.
- Release notes compare against the previous published GitHub release tag and fall back to `No release notes.` when no meaningful summary is generated.
- Keep workflow secrets in GitHub Actions secrets or environment variables. Do not commit credentials, tokens, or generated release bodies containing private data.
- Workflow scripts must fail loudly with actionable messages when required environment variables or git refs are missing.
- `workflows/image-footprint.yml` records GHCR baseline/candidate footprints, builds native amd64/arm64 profiles at the exact checkout SHA, and publishes experimental commit/profile tags after real retained-feature and omission checks; original stable tags are unchanged.
- Footprint builds use only the neutral `image-rebuild` ref and enforce CPU-Whisper provenance/Triton absence, targeted speech tests, and local/external speech feature gates before experimental publication.
- Six manual boolean inclusion inputs default true; event-aware expressions preserve explicit false, while pushes use all-on. `docker/slim/image_profile.py` prevents same-commit profile-tag collisions. Publishing still requires manual opt-in.
- Startup, targeted regressions and native feature checks have independent outcomes: after successful startup, feature checks still run on regression-test failure for diagnostics. Any failed gate prevents publication.
- Default `main` carries only the manual `image-footprint.yml` launcher: six default-true inclusion inputs and a default-false publication input are forwarded unchanged with the builtin token to the full workflow on `image-rebuild`. It links the separate build run and has no push trigger or application checkout; source/commit races cancel only its own forwarded run.
- Successful opted-in publications maintain the mutable GHCR `image-rebuild` alias for the selected profile, not implicitly all-on. Alias jobs serialize without cancelling builds and reconcile the newest successful index publication even when an older build triggered the job.
- Retag-only dispatch requires both a checked source run ID and its exact index digest plus publication opt-in. `docker/slim/promote_image.py` verifies native gates, publication logs, both platform configurations and capability labels, then copies exact index bytes without rebuilding; no other stable alias is writable.

## Work Guidance

- Prefer deterministic, testable Python for workflow planning logic instead of complex inline shell in YAML.
- Preserve manual dispatch behavior when changing Docker publishing.
- Keep branch, tag, and release behavior synchronized between workflow YAML, release scripts, tests, and user-facing release documentation.

## Verification

- Run `pytest tests/test_docker_release_plan.py` after changing Docker publish planning or release workflow behavior.
- Run targeted tests for any changed script that already has coverage.

## Child DOX Index

No child DOX files.
