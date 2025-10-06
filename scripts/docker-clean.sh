#!/usr/bin/env bash
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required" >&2
  exit 1
fi

if command -v docker compose >/dev/null 2>&1; then
  compose_cmd=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  compose_cmd=(docker-compose)
else
  echo "docker compose is required" >&2
  exit 1
fi

project_name="${COMPOSE_PROJECT_NAME:-metube}"
deep=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --deep)
      deep=1
      shift
      ;;
    -p|--project)
      if [[ $# -lt 2 ]]; then
        echo "--project requires a value" >&2
        exit 1
      fi
      project_name="$2"
      shift 2
      ;;
    *)
      echo "Usage: $(basename "$0") [--deep] [--project name]" >&2
      exit 1
      ;;
  esac
done

echo "Stopping containers for project '${project_name}' and removing local images..."
"${compose_cmd[@]}" -p "$project_name" down --remove-orphans --rmi local ${deep:+--volumes}

echo "Pruning dangling images and build cache layers..."
docker image prune -f >/dev/null
docker builder prune -f >/dev/null

if [[ $deep -eq 1 ]]; then
  echo "Performing deep prune (including volumes and build cache)..."
  docker system prune -af --volumes >/dev/null
fi

echo "Docker cleanup complete."
