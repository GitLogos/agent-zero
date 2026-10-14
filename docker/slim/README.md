# Agent Zero slim image

This experimental image reconstructs the cleaned merged filesystem of an
immutable, verified Kali-based vendor image into a fresh final stage. The vendor
base is an intermediate only; none of its deleted/overwritten lower-layer payload
is inherited by the final image. It retains both Python runtimes,
native compilation tools, installed libraries, Git history, and preloaded models.
Installation caches and overwritten/deleted lower-layer files are not exported.

The approved speech packaging variant additionally omits mandatory Triton on the
already CPU-only framework runtime. It retains local Whisper/Kokoro defaults and
adds opt-in OpenAI-compatible external audio services. External Ollama/vLLM and
other GPU-backed provider connections are unchanged; no local CUDA runtime is
installed. Full-functionality builds retain all other components; explicitly
selected component profiles can omit the six groups described below.

`prepare_cpu_whisper.py` verifies the immutable upstream Whisper 20250625 source
SHA-256, builds in a temporary isolated environment, and produces
`20250625+a0cpu.1`. Only dependency metadata changes: Triton moves to an optional
`cuda` extra. All upstream code/model assets and CLI entry points remain; the
local version satisfies the existing `==20250625` requirement. Runtime
installation uses the normal resolver and must pass `uv pip check`, not broad
dependency skipping. The retained wheel under `/opt/a0-wheels` and installed
`a0-cpu-provenance.json` record source/recipe/payload digests and valid wheel
RECORD hashes. A separately installed local CUDA runtime would also need that
optional extra; this image's local speech is CPU, as before.

The pinned vendor digest matches the measured baseline's base layers. Its system
Python and libraries are compatible with the pinned Xpra/UNO desktop stack;
current rolling system Python 3.14 and newer version-coupled GLib packages are
not. Updating this digest requires rebuilding and running the full feature gate.

Included in the default all-enabled profile:

- Web UI, API, supervisor, OpenSSH, ffmpeg, Node.js/npm, SearXNG,
  Tesseract/Poppler, local embeddings/FAISS memory, speech libraries and document parsers.
- Python 3.12 framework (`/opt/venv-a0`) and Python 3.13 execution (`/opt/venv`).
- Patchright Chromium automation and interactive browser viewer.
- Xpra/Xfce Desktop and LibreOffice Writer, Calc and Impress, including live
  document windows and headless creation/export.

The earlier `sha-67512fa` image omitted Xpra/Xfce. That omission also removed the
primary interactive Browser viewer, not just the Desktop panel. Full-functionality
candidates restore this stack; their measurements include its cost.

Build locally:

```bash
docker build -f docker/slim/Dockerfile \
  --build-arg BRANCH=image-rebuild \
  --build-arg A0_REPOSITORY_URL=https://github.com/GitLogos/agent-zero.git \
  --build-arg A0_BUILD_COMMIT="$(git rev-parse HEAD)" \
  -t ghcr.io/gitlogos/agent-zero-slim:local .
```

Run:

```bash
docker run -p 5080:80 -v a0_usr:/a0/usr ghcr.io/gitlogos/agent-zero-slim:local
```

For an exact source build, pass `--build-arg A0_BUILD_COMMIT=<full-commit-sha>`
with a branch that contains that commit. The image retains that named Git branch
and history for versioning, self-update and rollback. Installation-time cache
controls do not change the user's runtime cache behavior.

## Measurements and functional checks

`image-footprint.yml` profiles the immutable published `sha-67512fa` baseline and
builds native amd64/arm64 candidates. Artifacts contain Docker image inspection,
layer history, filesystem allocation, APT installed-size metadata, Python package
inventories, UV hardlink accounting, ELF section sizes, and smoke/startup logs.
Baseline memory/Office checks distinguish existing failures from candidate
regressions; they never waive a failing candidate publication gate.
Office export, document parsing, OCR, and ffmpeg run independently, so an import
or conversion failure cannot prevent the other features from being exercised.
After successful startup, native feature checks also run independently of targeted
pytest results, preserving diagnostics; any failed gate still blocks publication.

Compare **uncompressed Docker image `Size`**, not compressed registry transfer
size. Merged `du` allocation excludes deleted lower-layer bytes and includes
filesystem block overhead; separate nested/hardlinked directory totals overlap.
UV's apparent cache size is not its exclusive reclaimable size. ELF section
inventories are measurements only; binaries are not stripped.

`smoke.py` runs in a disposable started container with the framework runtime. It
checks both Python runtimes, native compilation, Node/npm, offline local memory,
ODF-to-OOXML/PDF exports, parsing/OCR, ffmpeg, normal plugin hooks, headless and
interactive Chromium, a real live LibreOffice window, search/SSH/supervisor, and
speech synthesis followed by transcription. Speech checks use the existing
model-download behavior in the test container; downloaded test assets are not
added to the image.
Additional gates check Triton absence, CPU-wheel metadata/provenance, preserved
Whisper model choices, and actual authenticated/CSRF-protected STT/TTS routes
against a loopback-only fake OpenAI-compatible service. Synthetic audio/text and
ephemeral test keys are used, never user data or real providers. Pytest is
installed only into the disposable test container when missing, after image
measurement, and is not bundled into the published image.

Keep `inventory.py` named distinctly from Python's standard-library `profile`
module: placing a `profile.py` beside the smoke runner breaks imports that use
`cProfile`, including model libraries.

Push-triggered builds and default manual runs do not publish. Explicit manual
dispatch with `publish_experimental=true` publishes only candidates passing all
checks. All-on builds retain `experimental-<full-commit-sha>-<architecture>` tags.
Other profiles append `-d<0|1>-o<0|1>-w<0|1>-k<0|1>-c<0|1>-s<0|1>` before the
architecture, in Desktop/Office/Whisper/Kokoro/Chromium/SearXNG order.
The corresponding architecture-free index tag requires both architectures to pass.
Successful opted-in publications also update
`ghcr.io/gitlogos/agent-zero-slim:image-rebuild` to that exact multi-architecture
index. **This is a mutable selected-profile alias, not always the all-on image.**
The run summary lists every included capability, the validated build and the
retained experimental tag/digest. Its initial selection is Desktop only:
Desktop enabled; Office, local Whisper, local Kokoro, Chromium and SearXNG disabled.
Choose the immutable SHA/profile tag or digest to pin a particular selection.
Alias updates serialize without cancelling builds and reconcile the newest
successfully published selection even if an older build triggered the alias job.

This workflow never replaces `latest`, `main`, `slim-image-ghcr` or `sha-67512fa`, and does not
claim a 3 GB reduction unless the measured amd64 difference reaches that value.

To promote an already checked image without rebuilding, dispatch the full source
workflow on `image-rebuild` with `publish_experimental=true`, `promote_run_id`
and `promote_digest` (the exact `sha256:` multi-architecture index digest).
Both promotion fields are required together. This mode skips all image builds
and verifies the prior manual run's native checks, published digest, source and
capability labels before copying the index bytes. The six inclusion checkboxes
do not change an existing image in retag-only mode; its recorded profile applies.
Normal main-launcher runs leave these source-only promotion fields empty.

## Optional component profiles

The workflow has six independent boolean checkboxes, **all default true**.
Push/non-dispatch builds always use all-on; false is honored only when explicitly
selected. Local Docker builds use the matching `A0_INCLUDE_*` build arguments.

| Workflow input | Docker argument | Consequence when false |
| --- | --- | --- |
| `include_desktop` | `A0_INCLUDE_DESKTOP` | No Xfce/file manager or live Desktop/Office sessions; shared Browser Xpra/Xvfb remains. |
| `include_office` | `A0_INCLUDE_OFFICE` | No LibreOffice/UNO editing, conversion or export; pure document parsers/creation libraries remain. |
| `include_whisper` | `A0_INCLUDE_WHISPER` | External STT only; no local/offline transcription or model download. |
| `include_kokoro` | `A0_INCLUDE_KOKORO` | External TTS, or browser speech after explicit plugin disable; no local voices/blends. |
| `include_chromium` | `A0_INCLUDE_CHROMIUM` | No internal automation/viewer or Chromium download; explicitly configure Host browser integration. |
| `include_searxng` | `A0_INCLUDE_SEARXNG` | No bundled search server; set `A0_SEARXNG_URL` to a full external HTTP(S) `/search` endpoint with JSON enabled. |

Office without Desktop retains headless document creation/export, not live Office.
Desktop without Office retains its viewer/file manager and uses Agent Zero Editor
for text files; Office launchers/actions are hidden. Local speech libraries are
selected using normal dependency resolution, not blanket transitive removal.
Shared Torch, embeddings, document parsing, both Python runtimes, native compilers,
SSH, supervisor, ffmpeg, fonts and OCR remain in every profile.

The read-only `/etc/a0-image-features.json` lives outside source/user mounts.
Labels `io.agent-zero.include-*`, `/api/health` and plugin status expose the profile.
Startup, normal prepare hooks and self-update reconciliation cannot re-enable
excluded assets. A mounted profile still selecting an unavailable local/internal
backend gets an explicit error: **provider choices are never switched silently**.
Lean-profile updates to releases without the six-feature contract are rejected
before preparation (using normal update rollback). Use a compatible fork/release
or rebuild all-enabled. The installed manager also checks the target's updater
guard, so startup synchronization cannot replace it with an unguarded older manager.
Legacy/all-enabled images keep their existing update behavior.
Configure external STT/TTS in their existing plugin settings using base URL,
model, optional API key, and TTS voice; see the plugin READMEs for upload/privacy
semantics. External GPU-provider connectivity is unchanged.

Open [Build Agent Zero Image Profiles](https://github.com/GitLogos/agent-zero/actions/workflows/image-footprint.yml)
and choose **Run workflow**, leaving the branch selector on **main**. Its small
workflow-only launcher exposes all six default-on checkboxes and the default-off
experimental publication checkbox, then forwards their exact true/false values
to the full build on `image-rebuild`. The launcher summary links the separate
build run and exact source commit; launcher success means dispatch succeeded,
not that the image has finished building.

Only this launcher was added to `main`, not the application/image changes. It
has no push trigger, uses the builtin token with `actions: write` and
`contents: read`, and cannot build from the older application source on main.
The existing direct branch-specific CLI dispatch remains available:

```bash
gh workflow run image-footprint.yml --repo GitLogos/agent-zero --ref image-rebuild \
  -f include_desktop=false -f include_office=false \
  -f include_whisper=false -f include_kokoro=false \
  -f include_chromium=false -f include_searxng=false \
  -f publish_experimental=true
```

Profile measurements are real Docker uncompressed bytes, not the sum of component
estimates; shared dependencies and filesystem allocation overlap. Native gates
run included features, loopback external speech/search and exclusion checks
after startup/hooks/dependency reconciliation. Unavailable capabilities are not
presented as successfully exercised features.

### Verified six-feature profiles

Source `cd56028aaf74b9a83d590440a509349746215a02` passed **163 targeted
regressions per profile per architecture**, real startup, retained-feature
checks and omission checks on native amd64/arm64 runners. All-on exercises local
speech, Desktop, live Office and interactive Browser. Mixed profiles verify
Desktop without Office/Chromium and headless Office/interactive Browser without
Desktop. All-off speech checks verify explicit local-unavailability errors and
working external APIs, not local speech execution. No real provider uploads were
used.

All sizes below are **bytes**. Compressed columns are registry layer sums, not
the basis for savings. Published configuration digests match the measured images;
source/capability labels match startup status on both architectures.

| Profile / validation run | amd64 uncompressed | amd64 compressed | arm64 uncompressed | arm64 compressed |
| --- | ---: | ---: | ---: | ---: |
| [All six included](https://github.com/GitLogos/agent-zero/actions/runs/38291129656) | 6,712,844,974 | 2,544,765,679 | 6,402,840,130 | 2,382,743,942 |
| [All six excluded](https://github.com/GitLogos/agent-zero/actions/runs/38291139523) | 4,961,358,766 | 1,830,919,007 | 4,422,405,149 | 1,661,112,033 |
| [Desktop + Whisper only](https://github.com/GitLogos/agent-zero/actions/runs/38291148749) | 5,296,736,669 | 1,943,007,168 | 4,760,145,512 | 1,771,498,763 |
| [Office + Kokoro + Chromium + SearXNG](https://github.com/GitLogos/agent-zero/actions/runs/38291157741) | 6,417,190,747 | 2,448,790,114 | 6,104,808,920 | 2,288,334,805 |

Multi-architecture tags, in the same profile order:

```text
ghcr.io/gitlogos/agent-zero-slim:experimental-cd56028aaf74b9a83d590440a509349746215a02
ghcr.io/gitlogos/agent-zero-slim:experimental-cd56028aaf74b9a83d590440a509349746215a02-d0-o0-w0-k0-c0-s0
ghcr.io/gitlogos/agent-zero-slim:experimental-cd56028aaf74b9a83d590440a509349746215a02-d1-o0-w1-k0-c0-s0
ghcr.io/gitlogos/agent-zero-slim:experimental-cd56028aaf74b9a83d590440a509349746215a02-d0-o1-w0-k1-c1-s1
```

The all-off index is
`sha256:4018382cceb50912903e0d3db841d18fb320d43c64729ea18459619f53fb27c0`.
The stable `slim-image-ghcr` index remains
`sha256:e78fdbe83b02f78d6cd4f1681df72b6712d2c79354a751dff6898133586d58df`;
no stable promotion or default-branch merge was performed.

Against the measured **7,940,191,238-byte amd64 baseline**, all-on saves
**1,227,346,264 bytes** and all-off saves **2,978,832,472 bytes**.
**The additional decimal 3 GB goal is still short by 21,167,528 bytes**, even
with all six approved exclusions. No other component removal or binary stripping
was applied to close the gap. The user-reported original size of about 8.5 GB is
not independently measured; there is no same-architecture arm64 baseline.
