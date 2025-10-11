#!/usr/bin/env bash

set -euo pipefail

REPOSITORY="${METUBE_RELEASE_REPOSITORY:-NaxonM/metube-extended}"
VERSION="${1:-${METUBE_UI_VERSION:-latest}}"
TARGET_DIR="${2:-ui/dist/metube}"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Error: required command '$1' not found" >&2
    exit 1
  fi
}

require_cmd curl
require_cmd unzip

if [ "$VERSION" = "latest" ]; then
  latest_url=$(curl -fsSL -o /dev/null -w '%{url_effective}' "https://github.com/${REPOSITORY}/releases/latest")
  if [ -z "$latest_url" ]; then
    echo "Error: unable to determine latest release tag" >&2
    exit 1
  fi
  VERSION="${latest_url##*/}"
fi

ASSET="metube-ui-${VERSION}.zip"
DOWNLOAD_URL="https://github.com/${REPOSITORY}/releases/download/${VERSION}/${ASSET}"

echo "Fetching UI bundle: ${DOWNLOAD_URL}" >&2

TMP_DIR=$(mktemp -d)
cleanup() { rm -rf "$TMP_DIR"; }
trap cleanup EXIT

ARCHIVE_PATH="${TMP_DIR}/${ASSET}"

curl -fL --retry 3 --retry-delay 2 "$DOWNLOAD_URL" -o "$ARCHIVE_PATH"

unzip -qo "$ARCHIVE_PATH" -d "$TMP_DIR/extracted"

SOURCE_DIR="$TMP_DIR/extracted/metube"
if [ ! -d "$SOURCE_DIR" ]; then
  echo "Error: extracted archive does not contain 'metube' directory" >&2
  exit 1
fi

mkdir -p "$TARGET_DIR"
rm -rf "${TARGET_DIR:?}"/*
cp -R "$SOURCE_DIR/." "$TARGET_DIR/"

echo "UI bundle extracted to $TARGET_DIR" >&2
