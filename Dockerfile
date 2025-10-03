# syntax=docker/dockerfile:1.6
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

ARG TARGETOS
ARG TARGETARCH
ARG CODEX_VERSION=latest

# Install system dependencies and Codex CLI binary
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        passwd; \
    rm -rf /var/lib/apt/lists/*; \
    case "${TARGETOS:-linux}-${TARGETARCH:-amd64}" in \
        linux-amd64) codex_arch="x86_64-unknown-linux-musl" ;; \
        linux-arm64) codex_arch="aarch64-unknown-linux-musl" ;; \
        *) echo "Unsupported architecture: ${TARGETOS:-linux}-${TARGETARCH:-amd64}" >&2; exit 1 ;; \
    esac; \
    if [ "${CODEX_VERSION}" = "latest" ]; then \
        codex_url="https://github.com/openai/codex/releases/latest/download/codex-${codex_arch}.tar.gz"; \
    else \
        codex_url="https://github.com/openai/codex/releases/download/${CODEX_VERSION}/codex-${codex_arch}.tar.gz"; \
    fi; \
    curl -fsSL "$codex_url" -o /tmp/codex.tar.gz; \
    tar -xzf /tmp/codex.tar.gz -C /usr/local/bin; \
    mv /usr/local/bin/codex-${codex_arch} /usr/local/bin/codex; \
    chmod +x /usr/local/bin/codex; \
    rm /tmp/codex.tar.gz

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN set -eux; \
    mkdir -p /workspace /home/appuser/.codex; \
    if ! id appuser >/dev/null 2>&1; then useradd --create-home --shell /bin/bash appuser; fi; \
    chown -R appuser:appuser /app /workspace /home/appuser/.codex

USER appuser

ENV CODEX_WORKDIR=/workspace \
    PATH="/home/appuser/.local/bin:${PATH}"

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
