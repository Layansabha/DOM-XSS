#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${ROOT_DIR}/.deploy"
TARGET_IMAGE="${1:-}"

if [[ -z "${TARGET_IMAGE}" ]]; then
  echo "Usage: $0 <immutable-image-reference>" >&2
  echo "Example: $0 ghcr.io/layansabha/dom-xss:sha-abc1234" >&2
  exit 2
fi

if [[ "${TARGET_IMAGE}" == *":latest" ]]; then
  echo "Refusing mutable :latest tag. Deploy a sha-* or version tag." >&2
  exit 2
fi

cd "${ROOT_DIR}"

if [[ ! -f .env ]]; then
  echo "Missing .env. Configure runtime secrets before deploying." >&2
  exit 1
fi

chmod 600 .env
mkdir -p "${STATE_DIR}"
chmod 700 "${STATE_DIR}"

if ! docker info >/dev/null 2>&1; then
  echo "Docker is unavailable or the current user cannot access its daemon." >&2
  exit 1
fi

compose=(docker compose --env-file .env -f compose.yaml -f deploy/compose.prod.yaml)
current_file="${STATE_DIR}/current-image"
previous_file="${STATE_DIR}/previous-image"

if [[ -s "${current_file}" ]]; then
  CURRENT_IMAGE="$(<"${current_file}")"
else
  CURRENT_IMAGE="$(grep -E '^APP_IMAGE=' .env | tail -n1 | cut -d= -f2- || true)"
fi

wait_ready() {
  for _ in {1..60}; do
    if APP_IMAGE="$1" "${compose[@]}" exec -T api python -c \
      "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=3)" \
      >/dev/null 2>&1; then
      return 0
    fi
    sleep 3
  done
  return 1
}

deploy_image() {
  local image="$1"
  APP_IMAGE="${image}" "${compose[@]}" pull api worker
  APP_IMAGE="${image}" "${compose[@]}" up -d --no-build --remove-orphans
}

echo "Deploying ${TARGET_IMAGE}"
deploy_image "${TARGET_IMAGE}"

if wait_ready "${TARGET_IMAGE}"; then
  if [[ -n "${CURRENT_IMAGE}" && "${CURRENT_IMAGE}" != "${TARGET_IMAGE}" ]]; then
    printf '%s\n' "${CURRENT_IMAGE}" >"${previous_file}"
  fi
  printf '%s\n' "${TARGET_IMAGE}" >"${current_file}"
  chmod 600 "${current_file}" "${previous_file}" 2>/dev/null || true
  echo "Release is healthy: ${TARGET_IMAGE}"
  exit 0
fi

"${compose[@]}" ps
"${compose[@]}" logs --tail=120 api worker zap caddy

if [[ -n "${CURRENT_IMAGE}" && "${CURRENT_IMAGE}" != "${TARGET_IMAGE}" ]]; then
  echo "Health check failed. Rolling back to ${CURRENT_IMAGE}." >&2
  deploy_image "${CURRENT_IMAGE}"
  if wait_ready "${CURRENT_IMAGE}"; then
    printf '%s\n' "${CURRENT_IMAGE}" >"${current_file}"
    echo "Rollback succeeded." >&2
  else
    echo "Rollback also failed; manual intervention is required." >&2
  fi
else
  echo "Health check failed and no previous release is recorded." >&2
fi

exit 1
