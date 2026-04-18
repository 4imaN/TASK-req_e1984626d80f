import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.trailgoods.core.database import get_session_factory
from src.trailgoods.models.jobs import Job

logger = logging.getLogger("trailgoods.bootstrap")


RECURRING_JOBS = [
    ("verification_expiry_scan", 3600),
    ("share_link_expiry_scan", 600),
    ("reorder_alert_scan", 1800),
    ("report_triage_sla_scan", 1800),
    ("appeal_due_scan", 1800),
    ("share_link_access_log_retention", 86400),
    ("asset_integrity_check", 86400),
    ("critical_table_manifest_checksum", 86400),
    ("nightly_backup", 86400),
    ("asset_preview_generation", 300),
]


async def bootstrap(db: AsyncSession) -> int:
    now = datetime.now(timezone.utc)
    created = 0

    for job_type, interval_seconds in RECURRING_JOBS:
        result = await db.execute(
            select(Job).where(
                Job.job_type == job_type,
                Job.status.in_(["PENDING", "RUNNING", "RETRY_SCHEDULED"]),
            )
        )
        if result.scalar_one_or_none():
            continue

        job = Job(
            job_type=job_type,
            status="PENDING",
            payload_json=json.dumps({"interval_seconds": interval_seconds, "recurring": True}),
            scheduled_at=now + timedelta(seconds=10),
            max_attempts=5,
        )
        db.add(job)
        created += 1

    await db.commit()
    logger.info(json.dumps({"event": "bootstrap_jobs_complete", "created": created}))
    return created


async def main():
    factory = get_session_factory()
    async with factory() as session:
        await bootstrap(session)


if __name__ == "__main__":
    asyncio.run(main())
