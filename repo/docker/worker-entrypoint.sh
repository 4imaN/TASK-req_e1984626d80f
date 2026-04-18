#!/bin/sh
set -e

KEY_FILE="${ENCRYPTION_MASTER_KEY_FILE:-/run/secrets/master.key}"

echo "[worker-entrypoint] Waiting for master key at $KEY_FILE"
for i in $(seq 1 120); do
    if [ -s "$KEY_FILE" ]; then
        echo "[worker-entrypoint] Master key found"
        break
    fi
    sleep 1
done

echo "[worker-entrypoint] Waiting for database migrations..."
python - <<'PY'
import os, time
import psycopg

url = os.environ["DATABASE_URL_SYNC"].replace("postgresql+psycopg://", "postgresql://")
deadline = time.time() + 120
while time.time() < deadline:
    try:
        with psycopg.connect(url, connect_timeout=3) as c:
            with c.cursor() as cur:
                cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='jobs'")
                if cur.fetchone()[0] >= 1:
                    print("[worker-entrypoint] Migrations applied")
                    break
    except Exception as e:
        pass
    time.sleep(1)
else:
    raise SystemExit("Migrations did not complete in 120s")
PY

echo "[worker-entrypoint] Starting worker..."
exec python -m src.trailgoods.worker
