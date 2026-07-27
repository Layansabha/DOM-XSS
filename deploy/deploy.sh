#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [[ ! -f .env ]]; then
  echo "Missing .env. Copy .env.example and configure it before deploying." >&2
  exit 1
fi

chmod 600 .env

read_env() {
  sed -n "s/^${1}=//p" .env | head -n1 | tr -d "'\""
}

app_image="$(read_env APP_IMAGE)"
if [[ -z "${app_image}" || "${app_image}" == "dom-xss-pipeline:local" || "${app_image}" == *:latest ]]; then
  echo "APP_IMAGE must use a version tag, commit tag, or digest; local and latest are rejected for VPS deployment." >&2
  exit 1
fi

enable_zap="$(read_env ENABLE_ZAP | tr '[:upper:]' '[:lower:]')"
case "${enable_zap}" in
  "" | false)
    enable_zap=false
    ;;
  true)
    ;;
  *)
    echo "ENABLE_ZAP must be true or false." >&2
    exit 1
    ;;
esac

if [[ "${enable_zap}" == "true" ]]; then
  zap_api_key="$(read_env ZAP_API_KEY)"
  if [[ -z "${zap_api_key}" || "${zap_api_key}" == replace-* ]]; then
    echo "ZAP_API_KEY must be configured when ENABLE_ZAP=true." >&2
    exit 1
  fi
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker is unavailable or the current user cannot access its daemon." >&2
  exit 1
fi

compose=(docker compose --env-file .env -f compose.yaml)
if [[ "${enable_zap}" == "true" ]]; then
  compose+=(-f deploy/compose/zap.yaml)
fi
compose+=(-f deploy/compose/vps.yaml)

"${compose[@]}" pull
"${compose[@]}" up -d --no-build --remove-orphans

for _ in {1..60}; do
  if "${compose[@]}" exec -T api python -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=3)" \
    >/dev/null 2>&1; then
    echo "Deployment is ready using ${app_image}."
    exit 0
  fi
  sleep 3
done

"${compose[@]}" ps
log_services=(api worker redis caddy)
if [[ "${enable_zap}" == "true" ]]; then
  log_services+=(zap)
fi
"${compose[@]}" logs --tail=120 "${log_services[@]}"
echo "Deployment did not become ready before the timeout." >&2
exit 1
