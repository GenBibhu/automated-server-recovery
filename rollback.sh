#!/usr/bin/env bash
# Verify recovery after rolling back to APP_VERSION=v1 (new process).
set -euo pipefail

echo "Rollback started"
echo "Start or replace the server with: APP_VERSION=v1 ./uvw run uvicorn app.main:app --host 0.0.0.0 --port 8000"

echo "Health verification: calling GET /health ..."
HEALTH="$(curl -fsS http://localhost:8000/health)"
echo "Health verification passed: ${HEALTH}"

echo "Rollback completed"
