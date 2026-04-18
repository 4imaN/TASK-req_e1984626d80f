import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.trailgoods.middleware.request_id import request_id_ctx
from src.trailgoods.models.auth import AuditLog


async def write_audit(
    db: AsyncSession,
    *,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    result: str = "SUCCESS",
    actor_user_id: uuid.UUID | None = None,
    actor_role_snapshot: str | None = None,
    before_json: str | None = None,
    after_json: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        request_id=request_id_ctx.get(""),
        actor_user_id=actor_user_id,
        actor_role_snapshot=actor_role_snapshot,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        result=result,
        before_json=before_json,
        after_json=after_json,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(entry)
    await db.flush()
    return entry
