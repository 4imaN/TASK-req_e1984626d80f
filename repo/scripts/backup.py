import asyncio
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from src.trailgoods.core.config import get_settings


async def run_backup() -> str:
    settings = get_settings()
    backup_root = Path(settings.BACKUP_STORAGE_ROOT)
    backup_root.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dump_file = backup_root / f"trailgoods_backup_{timestamp}.dump"
    checksum_file = backup_root / f"trailgoods_backup_{timestamp}.sha256"

    from urllib.parse import unquote, urlparse

    db_url = settings.DATABASE_URL_SYNC
    parsed = urlparse(db_url.replace("+psycopg", ""))
    user = unquote(parsed.username or "trailgoods")
    password = unquote(parsed.password or "")
    host = parsed.hostname or "localhost"
    port = str(parsed.port or 5432)
    dbname = (parsed.path or "/trailgoods").lstrip("/")

    env = os.environ.copy()
    env["PGPASSWORD"] = password

    result = subprocess.run(
        ["pg_dump", "-h", host, "-p", port, "-U", user, "-d", dbname, "-F", "c", "-f", str(dump_file)],
        env=env,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        if dump_file.exists():
            dump_file.unlink()
        raise RuntimeError(f"pg_dump failed: {result.stderr}")

    sha256 = hashlib.sha256()
    with open(dump_file, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)

    checksum = sha256.hexdigest()
    checksum_file.write_text(f"{checksum}  {dump_file.name}\n")

    manifest = {
        "timestamp": timestamp,
        "dump_file": str(dump_file),
        "checksum_file": str(checksum_file),
        "checksum": checksum,
        "size_bytes": dump_file.stat().st_size,
    }

    manifest_file = backup_root / f"trailgoods_backup_{timestamp}.manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2))

    return str(manifest_file)


if __name__ == "__main__":
    asyncio.run(run_backup())
