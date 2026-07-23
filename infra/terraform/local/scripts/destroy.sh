#!/usr/bin/env bash
set -Eeuo pipefail

: "${REPOSITORY_ROOT:?REPOSITORY_ROOT is required}"
: "${ENV_FILE:?ENV_FILE is required}"
: "${ENABLE_OBSERVABILITY:=true}"
: "${DESTROY_VOLUMES:=false}"
: "${APP_PORT:=8000}"
: "${PROMETHEUS_PORT:=9090}"
: "${GRAFANA_PORT:=3000}"

cd "$REPOSITORY_ROOT"

compose_args=(
  --env-file "$ENV_FILE"
  -f compose.yaml
)

if [[ "$ENABLE_OBSERVABILITY" == "true" ]]; then
  compose_args+=(-f deploy/compose.observability.yaml)
fi

export APP_IMAGE="dom-xss-pipeline:local"
export APP_PORT PROMETHEUS_PORT GRAFANA_PORT

down_args=(down --remove-orphans)
if [[ "$DESTROY_VOLUMES" == "true" ]]; then
  down_args+=(--volumes)
fi

docker compose "${compose_args[@]}" "${down_args[@]}"
