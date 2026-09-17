FROM python:3.11-slim AS base

# Optional regional build acceleration (opt-in; defaults to official sources). See the agent
# Dockerfile for usage. Debian 13/trixie apt sources live in /etc/apt/sources.list.d/debian.sources.
ARG APT_MIRROR=""
ARG PIP_INDEX_URL=""
ARG PIP_TRUSTED_HOST=""
ARG NODE_VERSION=22.16.0
ARG HYPERFRAMES_VERSION=0.7.106

RUN if [ -n "$APT_MIRROR" ]; then \
        sed -i "s|deb.debian.org|$APT_MIRROR|g; s|security.debian.org|$APT_MIRROR|g" /etc/apt/sources.list.d/debian.sources; \
    fi && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg fontconfig fonts-dejavu-core fonts-noto-cjk \
        ca-certificates curl xz-utils chromium \
        libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
        libdrm2 libgbm1 libgtk-3-0 libasound2 libxcomposite1 \
        libxdamage1 libxrandr2 libxshmfence1 fonts-liberation && \
    fc-cache -f && \
    rm -rf /var/lib/apt/lists/*

# Node 22+ is required by the HyperFrames CLI (dest media image).
RUN ARCH="$(uname -m)" && \
    case "$ARCH" in \
      x86_64) NODE_ARCH=x64 ;; \
      aarch64) NODE_ARCH=arm64 ;; \
      *) echo "unsupported arch: $ARCH" >&2; exit 1 ;; \
    esac && \
    curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz" \
      | tar -xJ -C /usr/local --strip-components=1 && \
    node -v && npm -v

# CLI + GSAP share one node_modules so gsap.min.js sits beside the binary.
WORKDIR /opt/hyperframes
ENV HOME=/opt/hyperframes \
    NPM_CONFIG_UPDATE_NOTIFIER=false \
    NPM_CONFIG_FUND=false \
    CI=true
RUN npm init -y >/dev/null && \
    npm install --omit=dev --no-audit --no-fund \
      "hyperframes@${HYPERFRAMES_VERSION}" gsap && \
    test -x /opt/hyperframes/node_modules/.bin/hyperframes && \
    test -f /opt/hyperframes/node_modules/gsap/dist/gsap.min.js && \
    CHROME="$(command -v chromium || command -v chromium-browser)" && \
    test -x "$CHROME" && \
    printf '%s\n' "$CHROME" > /opt/hyperframes/browser.path

# TTF for @font-face. Debian fonts-noto-cjk is TTC, which Chrome will not load as cuti-cjk.ttf.
RUN mkdir -p /usr/share/fonts/truetype/cuti && \
    curl -fsSL -o /usr/share/fonts/truetype/cuti/NotoSansSC-VF.ttf \
      "https://raw.githubusercontent.com/google/fonts/main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf" && \
    fc-cache -f

ENV HYPERFRAMES_CLI=/opt/hyperframes/node_modules/.bin/hyperframes \
    HYPERFRAMES_NODE_BIN=/usr/local/bin \
    HYPERFRAMES_CJK_FONT=/usr/share/fonts/truetype/cuti/NotoSansSC-VF.ttf \
    HYPERFRAMES_DOCKER=false \
    CI=true

WORKDIR /app

COPY requirements.txt .
RUN if [ -n "$PIP_INDEX_URL" ]; then pip config set global.index-url "$PIP_INDEX_URL"; fi && \
    if [ -n "$PIP_TRUSTED_HOST" ]; then pip config set global.trusted-host "$PIP_TRUSTED_HOST"; fi && \
    pip config set global.timeout 120 && \
    pip config set global.retries 8 && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /workspace /dev/shm

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/healthz')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2", "--log-level", "info"]
