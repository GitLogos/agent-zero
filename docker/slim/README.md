# Agent Zero slim image

This image keeps the Agent Zero web app and core runtime features while omitting the bundled Xpra/Xfce Linux desktop stack.

Included:

- Web UI, API, supervisor, OpenSSH, ffmpeg, Node.js/npm, SearXNG, Tesseract/Poppler, Python runtimes, browser automation, and LibreOffice.
- LibreOffice headless document creation/conversion for Writer, Calc, and Impress artifacts.

Not included:

- Xpra/Xfce desktop packages and related desktop UI tools. The `_desktop` plugin may report the Desktop surface as unavailable in this image.

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
