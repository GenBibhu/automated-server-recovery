#!/usr/bin/env bash
# Verify a running deployment. Version is controlled by APP_VERSION when
# the Uvicorn process is started (see README).
set -euo pipefail

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

echo "Deployed version (expected): ${VERSION}"
echo "Start or replace the server with: APP_VERSION=${VERSION} ./uvw run uvicorn app.main:app --host 0.0.0.0 --port 8000"

echo "Checking running version via /version ..."
RUNNING="$(curl -fsS http://localhost:8000/version)"
echo "Current running version response: ${RUNNING}"
