FROM python:3.13-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM alpine:3.22 AS gh
ARG GH_VERSION=2.96.0
ARG TARGETARCH
RUN set -eux; \
    base="https://github.com/cli/cli/releases/download/v${GH_VERSION}"; \
    tarball="gh_${GH_VERSION}_linux_${TARGETARCH}.tar.gz"; \
    wget -q "$base/$tarball" "$base/gh_${GH_VERSION}_checksums.txt"; \
    grep " $tarball\$" "gh_${GH_VERSION}_checksums.txt" | sha256sum -c -; \
    tar -xzf "$tarball"; \
    mv "gh_${GH_VERSION}_linux_${TARGETARCH}/bin/gh" /gh

FROM alpine:3.22 AS age
ARG AGE_VERSION=1.3.2
ARG TARGETARCH
# age publishes no checksum file, so the release tarballs are pinned here
RUN set -eux; \
    case "$TARGETARCH" in \
        amd64) sha=cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10 ;; \
        arm64) sha=6b8dc4333c53a5a57c9e5834e3a48f92605d7154014cd07269ff3327db5d37f4 ;; \
        *) echo "unsupported arch $TARGETARCH"; exit 1 ;; \
    esac; \
    tarball="age-v${AGE_VERSION}-linux-${TARGETARCH}.tar.gz"; \
    wget -q "https://github.com/FiloSottile/age/releases/download/v${AGE_VERSION}/$tarball"; \
    echo "$sha  $tarball" | sha256sum -c -; \
    tar -xzf "$tarball"

FROM python:3.13-slim
COPY --from=gh /gh /usr/local/bin/gh
COPY --from=age /age/age /age/age-keygen /usr/local/bin/
COPY --from=builder /app/.venv /app/.venv
RUN useradd --create-home --uid 1000 backuper

ENV PATH="/app/.venv/bin:$PATH" \
    GH_CONFIG_DIR=/tmp/gh \
    GH_NO_UPDATE_NOTIFIER=1
USER backuper

HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=2 \
    CMD ["sqlite-repo-backuper", "healthcheck"]
ENTRYPOINT ["sqlite-repo-backuper"]
CMD ["run"]
