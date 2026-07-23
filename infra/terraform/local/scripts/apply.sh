#!/usr/bin/env bash
set -Eeuo pipefail

: "${REPOSITORY_ROOT:?REPOSITORY_ROOT is required}"
: "${ENV_FILE:?ENV_FILE is required}"
: "${ENABLE_OBSERVABILITY:=true}"
: "${BUILD_IMAGES:=true}"
: "${APP_PORT:=8000}"
: "${PROMETHEUS_PORT:=9090}"
: "${GRAFANA_PORT:=3000}"

cd "$REPOSITORY_ROOT"

for command_name in docker openssl; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf 'Required command is unavailable: %s\n' "$command_name" >&2
    exit 1
  fi
done

if ! docker info >/dev/null 2>&1; then
  echo "Docker is unavailable or the current user cannot access its daemon." >&2
  exit 1
fi

docker compose version >/dev/null

if [[ ! -f "$ENV_FILE" ]]; then
  cp .env.example "$ENV_FILE"
  echo "Created $ENV_FILE from .env.example."
fi

chmod 600 "$ENV_FILE"

upsert_secret() {
  local key="$1"
  local placeholder="$2"
  local value
  local current=""

  if grep -q "^${key}=" "$ENV_FILE"; then
    current="$(grep -m1 "^${key}=" "$ENV_FILE" | cut -d= -f2-)"
  fi

  if [[ -z "$current" || "$current" == "$placeholder" ]]; then
    value="$(openssl rand -hex 32)"
    if grep -q "^${key}=" "$ENV_FILE"; then
      sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
    else
      printf '\n%s=%s\n' "$key" "$value" >>"$ENV_FILE"
    fi
    echo "Generated local secret: $key"
  fi
}

upsert_secret "ZAP_API_KEY" "replace-with-a-long-random-value"
upsert_secret "GRAFANA_ADMIN_PASSWORD" "replace-with-a-long-random-value"

compose_args=(
  --env-file "$ENV_FILE"
  -f compose.yaml
)

if [[ "$ENABLE_OBSERVABILITY" == "true" ]]; then
  compose_args+=(-f deploy/compose.observability.yaml)
fi

export APP_IMAGE="dom-xss-pipeline:local"
export APP_PORT PROMETHEUS_PORT GRAFANA_PORT

up_args=(up -d --wait --remove-orphans)
if [[ "$BUILD_IMAGES" == "true" ]]; then
  up_args+=(--build)
fi

docker compose "${compose_args[@]}" "${up_args[@]}"

printf '\nDOM XSS:    http://127.0.0.1:%s\n' "$APP_PORT"
if [[ "$ENABLE_OBSERVABILITY" == "true" ]]; then
  printf 'Prometheus: http://127.0.0.1:%s\n' "$PROMETHEUS_PORT"
  printf 'Grafana:    http://127.0.0.1:%s\n' "$GRAFANA_PORT"
  printf 'Grafana credentials are stored in %s\n' "$ENV_FILE"
fi
