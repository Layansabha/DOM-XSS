#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${ROOT_DIR}/.deploy"
previous_file="${STATE_DIR}/previous-image"
current_file="${STATE_DIR}/current-image"

if [[ ! -s "${previous_file}" ]]; then
  echo "No previous release is recorded in ${previous_file}." >&2
  exit 1
fi

PREVIOUS_IMAGE="$(<"${previous_file}")"
CURRENT_IMAGE=""
if [[ -s "${current_file}" ]]; then
  CURRENT_IMAGE="$(<"${current_file}")"
fi

"${ROOT_DIR}/deploy/release.sh" "${PREVIOUS_IMAGE}"

if [[ -n "${CURRENT_IMAGE}" && "${CURRENT_IMAGE}" != "${PREVIOUS_IMAGE}" ]]; then
  printf '%s\n' "${CURRENT_IMAGE}" >"${previous_file}"
  chmod 600 "${previous_file}"
fi
