# syntax=docker/dockerfile:1.6

FROM node:lts-alpine AS builder

WORKDIR /metube
COPY ui/package*.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci

COPY ui/ ./
RUN npm run build -- --configuration production


FROM python:3.13-alpine

ARG GALLERY_DL_VERSION=1.30.9
ARG GALLERY_DL_SHA256=48b168243dcbfbe6e8ddac15714a2f209ec833ad8f88cc3c4ef95ff16936b448

WORKDIR /app

COPY pyproject.toml uv.lock docker-entrypoint.sh ./

# Use sed to strip carriage-return characters from the entrypoint script (in case building on Windows)
# Install dependencies
RUN --mount=type=cache,target=/root/.cache/uv \
    sed -i 's/\r$//g' docker-entrypoint.sh && \
    chmod +x docker-entrypoint.sh && \
    apk add --update ffmpeg aria2 coreutils shadow su-exec curl tini deno && \
    apk add --update --virtual .build-deps gcc g++ musl-dev linux-headers uv && \
    UV_PROJECT_ENVIRONMENT=/usr/local uv sync --frozen --no-dev --compile-bytecode && \
    curl -L "https://github.com/mikf/gallery-dl/releases/download/v${GALLERY_DL_VERSION}/gallery-dl.bin" -o /usr/local/bin/gallery-dl && \
    echo "${GALLERY_DL_SHA256}  /usr/local/bin/gallery-dl" | sha256sum -c - && \
    chmod +x /usr/local/bin/gallery-dl && \
    apk del .build-deps && \
    rm -rf /var/cache/apk/* && \
    mkdir /.cache && chmod 777 /.cache

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
