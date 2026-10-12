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
installed. No other bundled component is removed.

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

Included:

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
checks as `experimental-<full-commit-sha>-<architecture>` tags. The multi-architecture
`experimental-<full-commit-sha>` tag requires both architectures to pass. This
workflow never replaces `latest` or the existing stable branch tag, and does not
claim a 3 GB reduction unless the measured amd64 difference reaches that value.

### Verified speech-enabled candidate

[Native validation run](https://github.com/GitLogos/agent-zero/actions/runs/38264132149)
for source `7fcc30f4a411e17db9c9a165e8fb9de4d344e79a` passed 76 targeted tests
and all 12 feature groups on each architecture, including real local speech and
synthetic loopback external speech APIs. The published multi-architecture tag is
`ghcr.io/gitlogos/agent-zero-slim:experimental-7fcc30f4a411e17db9c9a165e8fb9de4d344e79a`.
Its registry index digest is
`sha256:65dc6ae419e3ff66ab95daa31ef5396747214e9a7d8d082d23b144b95d52c454`.
Stable tags remain unchanged.

| Measurement | Uncompressed bytes |
| --- | ---: |
| Published amd64 baseline (`sha-67512fa`) | 7,940,191,238 |
| Full-functionality amd64 candidate | 6,716,780,224 |
| Additional amd64 saving | 1,223,411,014 |
| Remaining saving needed for the additional 3 GB goal | 1,776,588,986 |
| Full-functionality arm64 candidate | 6,406,718,409 |

These measurements include restored Desktop/live Office/interactive Browser
dependencies. **The additional 3 GB goal is not met.** The user-reported original
size of about 8.5 GB is not an independently measured baseline, and there is no
same-architecture baseline measurement for arm64. No further component removals
were applied to close the gap.
