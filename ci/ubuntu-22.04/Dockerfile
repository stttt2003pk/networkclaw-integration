FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
ARG SOURCE_COMMIT=unknown
ARG HARNESS_COMMIT=unknown
ARG INTEGRATION_COMMIT=unknown
ARG BUNDLE_SHA256=unknown
LABEL org.opencontainers.image.title="NetworkClaw combined runtime" \
      org.opencontainers.image.revision="$SOURCE_COMMIT" \
      io.networkclaw.harness.commit="$HARNESS_COMMIT" \
      io.networkclaw.integration.commit="$INTEGRATION_COMMIT" \
      io.networkclaw.bundle.sha256="$BUNDLE_SHA256"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH=/opt/bin:$PATH PYTHONPATH=/opt/networkclaw-harness/src:/opt/networkclaw-harness/vendor/hermes
WORKDIR /opt/networkclaw
COPY harness/requirements.lock harness/requirements.lock
COPY harness/offline/wheels/ /opt/wheels/
RUN python -m pip install --no-index --find-links /opt/wheels --require-hashes -r harness/requirements.lock \
    && groupadd --system --gid 65532 networkclaw \
    && useradd --system --uid 65532 --gid networkclaw --home-dir /nonexistent --shell /usr/sbin/nologin networkclaw
COPY --chown=networkclaw:networkclaw harness/src/ /opt/networkclaw-harness/src/
COPY --chown=networkclaw:networkclaw harness/vendor/hermes/ /opt/networkclaw-harness/vendor/hermes/
COPY --chown=networkclaw:networkclaw harness/upstream/ /opt/networkclaw-harness/upstream/
COPY --chown=networkclaw:networkclaw bin/ /opt/bin/
COPY --chown=networkclaw:networkclaw harness-entrypoint /opt/bin/networkclaw-harness
RUN chmod 0755 /opt/bin/networkclaw-harness
ENV CHATSVC_HARNESS_COMMAND=/opt/bin/networkclaw-harness
USER 65532:65532
ENTRYPOINT ["/opt/bin/chatrtmgr"]
