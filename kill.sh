#!/usr/bin/env bash
set +e

cd "$(dirname "$0")" 2>/dev/null || exit 0
echo "Stopping Docker Compose services"
docker compose down -v || true
echo "Cleanup completed successfully"
