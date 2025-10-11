#!/usr/bin/env bash

# Convenience launcher that fetches installer-core.sh for local builds.
# Usage:
#   bash <(curl -fsSL https://raw.githubusercontent.com/NaxonM/metube-extended/master/install-local.sh)

set -euo pipefail

: "${METUBE_INSTALL_BRANCH:=master}"
SCRIPT_URL="https://raw.githubusercontent.com/NaxonM/metube-extended/${METUBE_INSTALL_BRANCH}/installer-core.sh"

usage() {
  cat <<'EOF'
Usage: install-local.sh [install|uninstall|<branch>]

Defaults to install when no command is provided. This wrapper forces
METUBE_PULL_IMAGES=0 so the installer performs a full local build.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

echo "[metube] Launching installer from ${SCRIPT_URL} (local build)" >&2

export METUBE_PULL_IMAGES=${METUBE_PULL_IMAGES:-0}

curl -fsSL "$SCRIPT_URL" | bash -s -- "$@"
