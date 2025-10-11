# syntax=docker/dockerfile:1.6

FROM node:lts AS builder

WORKDIR /metube
COPY ui/package*.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci

COPY ui/ ./
RUN npm run build -- --configuration production


FROM python:3.13-slim

ARG GALLERY_DL_VERSION=1.30.9
ARG GALLERY_DL_SHA256=48b168243dcbfbe6e8ddac15714a2f209ec833ad8f88cc3c4ef95ff16936b448
ARG DENO_VERSION=1.46.3

WORKDIR /app

COPY pyproject.toml uv.lock docker-entrypoint.sh ./

# Use sed to strip carriage-return characters from the entrypoint script (in case building on Windows)
# Install dependencies
RUN --mount=type=cache,target=/root/.cache/uv \
    sed -i 's/\r$//g' docker-entrypoint.sh && \
    chmod +x docker-entrypoint.sh && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        aria2 \
        coreutils \
        gosu \
        curl \
        tini \
        ca-certificates \
        build-essential \
        libssl-dev \
        libffi-dev \
        pkg-config \
        unzip \
        xz-utils \
        git \
    && curl -fsSL https://astral.sh/uv/install.sh | sh -s -- --prefix /usr/local \
    && curl -fsSL "https://github.com/denoland/deno/releases/download/v${DENO_VERSION}/deno-x86_64-unknown-linux-gnu.zip" -o /tmp/deno.zip \
    && unzip /tmp/deno.zip -d /usr/local/bin \
    && chmod +x /usr/local/bin/deno \
    && rm /tmp/deno.zip \
    && ln -sf /usr/bin/tini /sbin/tini \
    && UV_PROJECT_ENVIRONMENT=/usr/local uv sync --frozen --no-dev --compile-bytecode \
    && curl -L "https://github.com/mikf/gallery-dl/releases/download/v${GALLERY_DL_VERSION}/gallery-dl.bin" -o /usr/local/bin/gallery-dl \
    && echo "${GALLERY_DL_SHA256}  /usr/local/bin/gallery-dl" | sha256sum -c - \
    && chmod +x /usr/local/bin/gallery-dl \
    && apt-get remove -y build-essential libssl-dev libffi-dev pkg-config git \
    && apt-get autoremove -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /.cache && chmod 777 /.cache

COPY app ./app
COPY --from=builder /metube/dist/metube ./ui/dist/metube

ENV UID=1000
ENV GID=1000
ENV UMASK=022

ENV DOWNLOAD_DIR /downloads
ENV STATE_DIR /downloads/.metube
ENV TEMP_DIR /downloads
VOLUME /downloads
EXPOSE 8081

# Add build-time argument for version
ARG VERSION=dev
ENV METUBE_VERSION=$VERSION

ENTRYPOINT ["/sbin/tini", "-g", "--", "./docker-entrypoint.sh"]
