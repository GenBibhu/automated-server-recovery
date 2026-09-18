#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_FILE="${ROOT}/deployment_state.txt"

echo "Rollback started"

printf 'v1\n' > "${STATE_FILE}"
echo "Wrote v1 to deployment_state.txt"

echo "Health verification: calling GET /health ..."
HEALTH="$(curl -fsS http://localhost:8000/health)"
echo "Health verification passed: ${HEALTH}"

echo "Rollback completed"
