# Assemble the owned base, then export only its cleaned merged filesystem.
FROM kalilinux/kali-rolling AS assembled

ARG BRANCH=main
ARG A0_REPOSITORY_URL=https://github.com/agent0ai/agent-zero.git
ARG A0_BUILD_COMMIT
ENV BRANCH=$BRANCH
ENV A0_REPOSITORY_URL=$A0_REPOSITORY_URL
ENV LANG=en_US.UTF-8 LANGUAGE=en_US:en LC_ALL=en_US.UTF-8 TZ=UTC
ENV UV_NO_CACHE=1

COPY ./docker/base/fs/ /
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y locales tzdata \
    && sed -i 's/# \(en_US\.UTF-8 .*\)/\1/' /etc/locale.gen \
    && locale-gen \
    && update-locale LANG=en_US.UTF-8 LANGUAGE=en_US:en LC_ALL=en_US.UTF-8 \
    && ln -sf /usr/share/zoneinfo/UTC /etc/localtime \
    && echo UTC > /etc/timezone \
    && bash /ins/install_base_packages1.sh \
    && bash /ins/install_base_packages2.sh \
    && bash /ins/install_base_packages3.sh \
    && bash /ins/install_base_packages4.sh \
    && bash /ins/install_python.sh \
    && bash /ins/install_searxng.sh \
    && bash /ins/configure_ssh.sh \
    && bash /ins/after_install.sh

COPY ./docker/run/fs/ /
RUN bash /ins/pre_install.sh "$BRANCH" \
    && A0_BUILD_COMMIT="$A0_BUILD_COMMIT" bash /ins/install_A0.sh "$BRANCH" \
    && bash /ins/install_additional.sh "$BRANCH" \
    && bash /ins/post_install.sh "$BRANCH" \
    && rm -rf /root/.cache/uv /root/.cache/pip /opt/pyenv/cache \
    && find /tmp /var/tmp -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + \
    && chmod +x /exe/initialize.sh /exe/run_A0.sh /exe/run_searxng.sh \
        /exe/run_tunnel_api.sh /exe/trigger_self_update.sh

# No inherited deleted files, overwritten packages, or installation caches.
# Retain the complete filesystem, including runtimes, tools, models and Git data.
FROM scratch
COPY --from=assembled / /

ARG BRANCH=main
ARG A0_REPOSITORY_URL=https://github.com/agent0ai/agent-zero.git
ENV PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ENV LANG=en_US.UTF-8 LANGUAGE=en_US:en LC_ALL=en_US.UTF-8 TZ=UTC
ENV BRANCH=$BRANCH
ENV A0_REPOSITORY_URL=$A0_REPOSITORY_URL
ENV A0_SELF_UPDATE_REMOTE_URL=$A0_REPOSITORY_URL
WORKDIR /

EXPOSE 22 80 9000-9009

CMD ["/exe/initialize.sh", "$BRANCH"]
