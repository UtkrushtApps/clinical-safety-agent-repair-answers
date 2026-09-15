#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m pip install -q -r requirements.txt

echo "Starting PostgreSQL"
docker compose up -d

container_id="$(docker compose ps -q postgres)"
for attempt in $(seq 1 60); do
  status="$(docker inspect --format='{{.State.Health.Status}}' "$container_id" 2>/dev/null || true)"
  if [[ "$status" == "healthy" ]]; then
    echo "PostgreSQL is healthy"
    break
  fi
  if [[ "$attempt" -eq 60 ]]; then
    echo "PostgreSQL did not become healthy"
    docker compose logs postgres || true
    exit 1
  fi
  echo "Waiting for PostgreSQL ($attempt/60)"
  sleep 2
done

python3 - <<'PY'
import psycopg

url = "postgresql://clinical_agent:clinical_dev_password@127.0.0.1:5432/clinical_trials"
with psycopg.connect(url) as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM protocols")
        if cur.fetchone()[0] < 1:
            raise SystemExit("Clinical seed data is missing")
print("Clinical seed data is readable")
PY

python3 -m agent --selfcheck
python3 -m pytest -q invariants

echo "Clinical-trials agent scaffold ready"
