import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.trailgoods.core.config import get_settings


CRITICAL_TABLES = [
    "users",
    "sessions",
    "verification_cases",
    "orders",
    "reservations",
    "inventory_movements",
    "inventory_balances",
    "audit_logs",
]


async def run_integrity_check(db: AsyncSession) -> dict:
    settings = get_settings()
    asset_root = Path(settings.ASSET_STORAGE_ROOT)
    results = {"timestamp": datetime.now(timezone.utc).isoformat(), "errors": [], "checks": []}

    from src.trailgoods.models.assets import AssetBlob
    blobs_result = await db.execute(select(AssetBlob))
    blobs = blobs_result.scalars().all()

    for blob in blobs:
        full_path = Path(blob.storage_path)
        if not full_path.is_absolute():
            full_path = asset_root / blob.storage_path

        if not full_path.exists():
            results["errors"].append(f"Missing file for blob {blob.id}: {blob.storage_path}")
            continue

        sha256 = hashlib.sha256()
        with open(full_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)

        if sha256.hexdigest() != blob.asset_hash:
            results["errors"].append(
                f"Hash mismatch for blob {blob.id}: expected {blob.asset_hash}, got {sha256.hexdigest()}"
            )
        else:
            results["checks"].append(f"Blob {blob.id}: OK")

    results["total_blobs"] = len(blobs)
    results["errors_count"] = len(results["errors"])
    return results


async def generate_manifest(db: AsyncSession) -> str:
    settings = get_settings()
    backup_root = Path(settings.BACKUP_STORAGE_ROOT)
    backup_root.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    manifest = {
        "timestamp": timestamp,
        "tables": {},
    }

    for table in CRITICAL_TABLES:
        try:
            count_result = await db.execute(text(f"SELECT count(*) FROM {table}"))
            count = count_result.scalar()

            checksum_result = await db.execute(
                text(f"SELECT md5(string_agg(t::text, '')) FROM (SELECT * FROM {table} ORDER BY 1) t")
            )
            checksum = checksum_result.scalar() or "empty"

            manifest["tables"][table] = {
                "row_count": count,
                "checksum": checksum,
            }
        except Exception as e:
            manifest["tables"][table] = {"error": str(e)}

    manifest_path = backup_root / f"manifest_{timestamp}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return str(manifest_path)
