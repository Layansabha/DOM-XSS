#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [[ ! -f .env ]]; then
  echo "Missing .env. Copy .env.example and configure it before deploying." >&2
  exit 1
fi

chmod 600 .env

if ! docker info >/dev/null 2>&1; then
  echo "Docker is unavailable or the current user cannot access its daemon." >&2
  exit 1
fi

compose=(docker compose --env-file .env -f compose.yaml -f deploy/compose.prod.yaml)

"${compose[@]}" pull
"${compose[@]}" up -d --no-build --remove-orphans

for _ in {1..60}; do
  if "${compose[@]}" exec -T api python -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=3)" \
    >/dev/null 2>&1; then
    echo "Deployment is ready."
    exit 0
  fi
  sleep 3
done

"${compose[@]}" ps
"${compose[@]}" logs --tail=120 api worker zap caddy
echo "Deployment did not become ready before the timeout." >&2
exit 1
