#!/bin/sh
set -e

export DATABASE_URL="postgresql+asyncpg://trailgoods:trailgoods@postgres-test:5432/trailgoods_test"
export DATABASE_URL_SYNC="postgresql+psycopg://trailgoods:trailgoods@postgres-test:5432/trailgoods_test"
export SECRET_KEY="test-secret-key-for-ci-only"
export ENCRYPTION_MASTER_KEY="0000000000000000000000000000000000000000000000000000000000000000"
export ASSET_STORAGE_ROOT="/tmp/trailgoods_test_assets"
export BACKUP_STORAGE_ROOT="/tmp/trailgoods_test_backups"
export PREVIEW_STORAGE_ROOT="/tmp/trailgoods_test_previews"
export PYTHONPATH="/app"
export COVERAGE_CORE="sysmon"

echo "[test-entrypoint] Waiting for test PostgreSQL..."
python - <<'PY'
import os, time
import psycopg

url = os.environ["DATABASE_URL_SYNC"].replace("postgresql+psycopg://", "postgresql://")
deadline = time.time() + 60
while time.time() < deadline:
    try:
        with psycopg.connect(url, connect_timeout=3) as c:
            c.execute("SELECT 1")
        print("[test-entrypoint] PG ready")
        break
    except Exception:
        time.sleep(1)
else:
    raise SystemExit("PG did not become ready")
PY

mkdir -p "$ASSET_STORAGE_ROOT" "$BACKUP_STORAGE_ROOT" "$PREVIEW_STORAGE_ROOT"

echo "[test-entrypoint] Running tests: $@"
if [ "$#" -eq 0 ]; then
    exec python -m pytest tests/ --cov=src/trailgoods -v
else
    exec python -m pytest "$@"
fi
