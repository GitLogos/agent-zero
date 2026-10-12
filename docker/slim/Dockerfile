# Slim Agent Zero image for GHCR.
#
# Keeps the core web app, SSH, ffmpeg, supervisor, SearXNG, browser automation,
# document/OCR tooling, and LibreOffice. Omits the bundled Xpra/Xfce Linux
# desktop stack to reduce image size.
FROM agent0ai/agent-zero-base:latest

ARG BRANCH=main
ARG A0_REPOSITORY_URL=https://github.com/agent0ai/agent-zero.git
ENV BRANCH=$BRANCH
ENV A0_REPOSITORY_URL=$A0_REPOSITORY_URL
ENV A0_SELF_UPDATE_REMOTE_URL=$A0_REPOSITORY_URL

COPY ./docker/run/fs/ /

RUN bash -lc 'set -e; \
    bash /ins/pre_install.sh "$BRANCH"; \
    bash /ins/install_A0.sh "$BRANCH"; \
    bash /ins/install_office.sh "$BRANCH"; \
    . /ins/setup_venv.sh "$BRANCH"; \
    pip cache purge || true; \
    uv cache prune || true; \
    bash /ins/post_install.sh "$BRANCH"; \
    rm -rf /tmp/* /var/tmp/*'

EXPOSE 22 80 9000-9009

RUN chmod +x /exe/initialize.sh /exe/run_A0.sh /exe/run_searxng.sh /exe/run_tunnel_api.sh /exe/trigger_self_update.sh

CMD ["/exe/initialize.sh", "$BRANCH"]
