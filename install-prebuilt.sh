#!/usr/bin/env bash

# Convenience launcher that fetches installer-core.sh and forces METUBE_PULL_IMAGES=1.
# Usage:
#   bash <(curl -fsSL https://raw.githubusercontent.com/NaxonM/metube-extended/master/install-prebuilt.sh)

set -euo pipefail

: "${METUBE_INSTALL_BRANCH:=master}"
SCRIPT_URL="https://raw.githubusercontent.com/NaxonM/metube-extended/${METUBE_INSTALL_BRANCH}/installer-core.sh"

usage() {
  cat <<'EOF'
Usage: install-prebuilt.sh [install|uninstall]

Defaults to install when no command is provided. The script forwards commands
to the core installer with METUBE_PULL_IMAGES=1 to reuse prebuilt Docker images.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

echo "[metube] Launching installer from ${SCRIPT_URL} (prebuilt images)" >&2

export METUBE_PULL_IMAGES=${METUBE_PULL_IMAGES:-1}

tmp_script="$(mktemp)"
trap 'rm -f "$tmp_script"' EXIT

curl -fsSL "$SCRIPT_URL" -o "$tmp_script"

bash "$tmp_script" "$@"
