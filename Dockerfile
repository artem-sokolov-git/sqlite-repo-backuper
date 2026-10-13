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

FROM python:3.13-slim
COPY --from=gh /gh /usr/local/bin/gh
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
