import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.trailgoods.core.config import get_settings
from src.trailgoods.core.database import get_session_factory
from src.trailgoods.models.assets import ShareLinkAccessLog
from src.trailgoods.models.jobs import Job

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("trailgoods.worker")

JOB_HANDLERS = {}


def register_handler(job_type: str):
    def decorator(func):
        JOB_HANDLERS[job_type] = func
        return func
    return decorator


BACKOFF_SCHEDULE = [60, 300, 900, 3600, 10800]


async def poll_and_execute(db: AsyncSession) -> int:
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(Job)
        .where(
            Job.status.in_(["PENDING", "RETRY_SCHEDULED"]),
            Job.scheduled_at <= now,
        )
        .order_by(Job.scheduled_at.asc())
        .limit(10)
    )
    jobs = result.scalars().all()

    executed = 0
    for job in jobs:
        handler = JOB_HANDLERS.get(job.job_type)
        if not handler:
            logger.warning(json.dumps({
                "event": "job_no_handler",
                "job_id": str(job.id),
                "job_type": job.job_type,
            }))
            job.status = "FAILED"
            job.last_error = f"No handler registered for job type: {job.job_type}"
            job.finished_at = now
            continue

        job.status = "RUNNING"
        job.started_at = now
        job.attempt_count += 1
        await db.flush()

        try:
            await handler(db, job)
            job.status = "SUCCEEDED"
            job.finished_at = datetime.now(timezone.utc)
            elapsed_ms = (job.finished_at - job.started_at).total_seconds() * 1000
            logger.info(json.dumps({
                "event": "job_succeeded",
                "job_id": str(job.id),
                "job_type": job.job_type,
                "attempt": job.attempt_count,
                "duration_ms": round(elapsed_ms, 1),
            }))
            await _reschedule_if_recurring(db, job)
        except Exception as e:
            logger.error(json.dumps({
                "event": "job_failed",
                "job_id": str(job.id),
                "job_type": job.job_type,
                "attempt": job.attempt_count,
                "error": str(e),
            }))
            job.last_error = str(e)
            if job.attempt_count < job.max_attempts:
                backoff_idx = min(job.attempt_count - 1, len(BACKOFF_SCHEDULE) - 1)
                delay = BACKOFF_SCHEDULE[backoff_idx]
                job.status = "RETRY_SCHEDULED"
                job.scheduled_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
            else:
                job.status = "FAILED"
                job.finished_at = datetime.now(timezone.utc)

        await db.flush()
        executed += 1

    await db.commit()
    return executed


async def _reschedule_if_recurring(db: AsyncSession, job: Job) -> None:
    if not job.payload_json:
        return
    try:
        payload = json.loads(job.payload_json)
    except (ValueError, TypeError):
        return
    if not payload.get("recurring"):
        return
    interval = int(payload.get("interval_seconds", 3600))
    now = datetime.now(timezone.utc)
    existing = await db.execute(
        select(Job).where(
            Job.job_type == job.job_type,
            Job.status.in_(["PENDING", "RUNNING", "RETRY_SCHEDULED"]),
        )
    )
    if existing.scalar_one_or_none():
        return
    next_job = Job(
        job_type=job.job_type,
        status="PENDING",
        payload_json=job.payload_json,
        scheduled_at=now + timedelta(seconds=interval),
        max_attempts=job.max_attempts,
    )
    db.add(next_job)


async def recover_stale_jobs(db: AsyncSession) -> int:
    threshold = datetime.now(timezone.utc) - timedelta(minutes=30)
    result = await db.execute(
        update(Job)
        .where(
            Job.status == "RUNNING",
            Job.started_at < threshold,
        )
        .values(status="RETRY_SCHEDULED", last_error="Recovered from stale RUNNING state")
    )
    count = result.rowcount
    if count:
        await db.commit()
        logger.info(json.dumps({
            "event": "stale_jobs_recovered",
            "count": count,
        }))
    return count


@register_handler("verification_expiry_scan")
async def handle_verification_expiry(db: AsyncSession, job: Job):
    from src.trailgoods.services.verification import expire_verification_cases
    count = await expire_verification_cases(db)
    logger.info(json.dumps({"event": "job_handler_result", "job_type": "verification_expiry_scan", "expired": count}))


@register_handler("share_link_expiry_scan")
async def handle_share_link_expiry(db: AsyncSession, job: Job):
    from src.trailgoods.models.assets import ShareLink
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(ShareLink).where(
            ShareLink.status == "ACTIVE",
            ShareLink.expires_at <= now,
        )
    )
    links = result.scalars().all()
    for link in links:
        link.status = "EXPIRED"
    if links:
        await db.flush()
    logger.info(json.dumps({"event": "job_handler_result", "job_type": "share_link_expiry_scan", "expired": len(links)}))


@register_handler("reorder_alert_scan")
async def handle_reorder_alerts(db: AsyncSession, job: Job):
    from src.trailgoods.services.inventory import check_reorder_alerts
    count = await check_reorder_alerts(db)
    logger.info(json.dumps({"event": "job_handler_result", "job_type": "reorder_alert_scan", "generated": count}))


@register_handler("report_triage_sla_scan")
async def handle_report_sla(db: AsyncSession, job: Job):
    from src.trailgoods.models.reviews import Report, ReportEvent
    from src.trailgoods.services.audit import write_audit

    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Report).where(
            Report.status == "SUBMITTED",
            Report.triage_due_at <= now,
        )
    )
    overdue = list(result.scalars().all())
    for report in overdue:
        db.add(ReportEvent(
            report_id=report.id,
            event_type="SLA_BREACH",
            from_status="SUBMITTED",
            to_status="SUBMITTED",
            comment="Triage SLA exceeded: awaiting reviewer action",
        ))
        await write_audit(
            db,
            action="report.sla_breach",
            resource_type="report",
            resource_id=str(report.id),
        )
    if overdue:
        await db.flush()
    logger.info(json.dumps({"event": "job_handler_result", "job_type": "report_triage_sla_scan", "flagged": len(overdue)}))


@register_handler("appeal_due_scan")
async def handle_appeal_due(db: AsyncSession, job: Job):
    from src.trailgoods.models.reviews import Appeal
    from src.trailgoods.services.audit import write_audit

    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Appeal).where(
            Appeal.status.in_(["SUBMITTED", "UNDER_REVIEW"]),
            Appeal.due_at <= now,
        )
    )
    overdue = list(result.scalars().all())
    for appeal in overdue:
        await write_audit(
            db,
            action="appeal.due_overdue_flagged",
            resource_type="appeal",
            resource_id=str(appeal.id),
        )
    if overdue:
        await db.flush()
    logger.info(json.dumps({"event": "job_handler_result", "job_type": "appeal_due_scan", "flagged": len(overdue)}))


@register_handler("share_link_access_log_retention")
async def handle_access_log_retention(db: AsyncSession, job: Job):
    cutoff = datetime.now(timezone.utc) - timedelta(days=180)
    result = await db.execute(
        delete(ShareLinkAccessLog).where(ShareLinkAccessLog.accessed_at < cutoff)
    )
    logger.info(json.dumps({"event": "job_handler_result", "job_type": "share_link_access_log_retention", "purged": result.rowcount}))


@register_handler("asset_preview_generation")
async def handle_preview_generation(db: AsyncSession, job: Job):
    from src.trailgoods.services.assets import generate_pending_thumbnails
    count = await generate_pending_thumbnails(db)
    logger.info(json.dumps({"event": "job_handler_result", "job_type": "asset_preview_generation", "generated": count}))


@register_handler("nightly_backup")
async def handle_nightly_backup(db: AsyncSession, job: Job):
    from scripts.backup import run_backup
    await run_backup()


@register_handler("asset_integrity_check")
async def handle_integrity_check(db: AsyncSession, job: Job):
    from scripts.integrity import run_integrity_check
    await run_integrity_check(db)


@register_handler("critical_table_manifest_checksum")
async def handle_manifest_checksum(db: AsyncSession, job: Job):
    from scripts.integrity import generate_manifest
    await generate_manifest(db)


async def create_job(
    db: AsyncSession,
    *,
    job_type: str,
    payload_json: str | None = None,
    scheduled_at: datetime | None = None,
    max_attempts: int = 5,
) -> Job:
    job = Job(
        job_type=job_type,
        payload_json=payload_json,
        scheduled_at=scheduled_at or datetime.now(timezone.utc),
        max_attempts=max_attempts,
    )
    db.add(job)
    await db.flush()
    return job


async def run_worker_loop():
    settings = get_settings()
    poll_interval = settings.WORKER_POLL_INTERVAL_SECONDS
    factory = get_session_factory()

    logger.info(json.dumps({"event": "worker_starting"}))

    async with factory() as db:
        await recover_stale_jobs(db)

    while True:
        try:
            async with factory() as db:
                executed = await poll_and_execute(db)
                if executed:
                    logger.info(json.dumps({"event": "worker_cycle", "executed": executed}))
        except Exception as e:
            logger.error(json.dumps({"event": "worker_cycle_error", "error": str(e)}))

        await asyncio.sleep(poll_interval)


if __name__ == "__main__":
    asyncio.run(run_worker_loop())
