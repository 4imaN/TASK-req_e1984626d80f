#!/bin/sh
set -e

KEY_FILE="${ENCRYPTION_MASTER_KEY_FILE:-/run/secrets/master.key}"
KEY_DIR="$(dirname "$KEY_FILE")"

if [ ! -s "$KEY_FILE" ]; then
    echo "[entrypoint] Generating encryption master key at $KEY_FILE"
    mkdir -p "$KEY_DIR"
    python -c "import secrets; print(secrets.token_hex(32))" > "$KEY_FILE"
    chmod 600 "$KEY_FILE" || true
fi

echo "[entrypoint] Waiting for PostgreSQL..."
python - <<'PY'
import os, time
import psycopg

url = os.environ["DATABASE_URL_SYNC"].replace("postgresql+psycopg://", "postgresql://")
deadline = time.time() + 60
while time.time() < deadline:
    try:
        with psycopg.connect(url, connect_timeout=3) as c:
            c.execute("SELECT 1")
        print("[entrypoint] PostgreSQL is ready")
        break
    except Exception as e:
        print(f"[entrypoint] PG not ready: {e}")
        time.sleep(1)
else:
    raise SystemExit("PostgreSQL did not become ready in 60s")
PY

echo "[entrypoint] Running Alembic migrations..."
alembic upgrade head

echo "[entrypoint] Seeding roles/permissions..."
python -m scripts.seed

echo "[entrypoint] Bootstrapping recurring background jobs..."
python -m scripts.bootstrap_jobs

echo "[entrypoint] Starting: $@"
exec "$@"
