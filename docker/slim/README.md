# Agent Zero slim image

This experimental image reconstructs the cleaned merged filesystem of an
immutable, verified Kali-based vendor image into a fresh final stage. The vendor
base is an intermediate only; none of its deleted/overwritten lower-layer payload
is inherited by the final image. It retains both Python runtimes,
native compilation tools, installed libraries, Git history, and preloaded models.
Installation caches and overwritten/deleted lower-layer files are not exported.

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
  --build-arg BRANCH=main \
  --build-arg A0_REPOSITORY_URL=https://github.com/GitLogos/agent-zero.git \
  -t ghcr.io/gitlogos/agent-zero-slim:local .
```

Run:

```bash
docker run -p 5080:80 -v a0_usr:/a0/usr ghcr.io/gitlogos/agent-zero-slim:latest
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

Keep `inventory.py` named distinctly from Python's standard-library `profile`
module: placing a `profile.py` beside the smoke runner breaks imports that use
`cProfile`, including model libraries.

Push-triggered builds and default manual runs do not publish. Explicit manual
dispatch with `publish_experimental=true` publishes only candidates passing all
checks as `experimental-<full-commit-sha>-<architecture>` tags. The multi-architecture
`experimental-<full-commit-sha>` tag requires both architectures to pass. This
workflow never replaces `latest` or the existing stable branch tag, and does not
claim a 3 GB reduction unless the measured amd64 difference reaches that value.
