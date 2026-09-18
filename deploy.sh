#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_FILE="${ROOT}/deployment_state.txt"

usage() {
  echo "Usage: $0 <v1|v2>" >&2
  exit 1
}

if [[ "${#}" -ne 1 ]]; then
  echo "Error: expected exactly one argument (v1 or v2)." >&2
  usage
fi

VERSION="${1}"

case "${VERSION}" in
  v1|v2) ;;
  *)
    echo "Error: invalid version '${VERSION}'. Use v1 or v2." >&2
    usage
    ;;
esac

printf '%s\n' "${VERSION}" > "${STATE_FILE}"
echo "Deployed version: ${VERSION}"

echo "Checking running version via /version ..."
RUNNING="$(curl -fsS http://localhost:8000/version)"
echo "Current running version response: ${RUNNING}"
