import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.trailgoods.api.deps import (
    get_current_user_and_session,
    get_role_snapshot,
    require_permission,
)
from src.trailgoods.core.database import get_db
from src.trailgoods.middleware.request_id import request_id_ctx
from src.trailgoods.models.auth import Session as SessionModel, User
from src.trailgoods.schemas.auth import (
    ForceLogoutRequest,
    IdentityBindingRequest,
    IdentityBindingResponse,
    LoginRequest,
    LoginResponse,
    PasswordRotateRequest,
    RegisterRequest,
    RoleAssignRequest,
    SessionResponse,
    UserResponse,
)
from src.trailgoods.schemas.envelope import ApiResponse, ResponseMeta
from src.trailgoods.services.auth import (
    assign_role,
    clear_challenge,
    create_identity_binding,
    force_logout_user,
    get_user_bindings,
    login_user,
    logout_all_sessions,
    logout_session,
    register_user,
    rotate_password,
)

router = APIRouter(prefix="/api/v1", tags=["auth"])


def _meta() -> ResponseMeta:
    return ResponseMeta(request_id=request_id_ctx.get(""))


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/auth/register", status_code=201)
async def register(
    body: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[UserResponse]:
    try:
        user = await register_user(
            db,
            username=body.username,
            password=body.password,
            email=body.email,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return ApiResponse(data=UserResponse.model_validate(user), meta=_meta())


@router.post("/auth/login")
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[LoginResponse]:
    try:
        user, session, raw_token = await login_user(
            db,
            username=body.username,
            password=body.password,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    return ApiResponse(
        data=LoginResponse(
            token=raw_token,
            session=SessionResponse.model_validate(session),
            user=UserResponse.model_validate(user),
        ),
        meta=_meta(),
    )


@router.post("/auth/logout")
async def logout(
    request: Request,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(get_current_user_and_session)
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, session = user_session
    await logout_session(
        db,
        session=session,
        user=user,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return ApiResponse(data={"message": "Logged out"}, meta=_meta())


@router.post("/auth/logout-all")
async def logout_all(
    request: Request,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(get_current_user_and_session)
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    count = await logout_all_sessions(
        db,
        user=user,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return ApiResponse(data={"revoked_sessions": count}, meta=_meta())


@router.post("/auth/password-rotate")
async def password_rotate(
    body: PasswordRotateRequest,
    request: Request,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(get_current_user_and_session)
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    try:
        await rotate_password(
            db,
            user=user,
            current_password=body.current_password,
            new_password=body.new_password,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ApiResponse(data={"message": "Password rotated. All sessions revoked."}, meta=_meta())


@router.get("/sessions/me")
async def get_my_sessions(
    user_session: Annotated[tuple[User, SessionModel], Depends(require_permission("session.read_own"))],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[SessionResponse]]:
    user, _ = user_session
    result = await db.execute(
        select(SessionModel)
        .where(SessionModel.user_id == user.id)
        .order_by(SessionModel.issued_at.desc())
    )
    sessions = result.scalars().all()
    return ApiResponse(
        data=[SessionResponse.model_validate(s) for s in sessions],
        meta=_meta(),
    )


@router.delete("/sessions/{session_id}")
async def revoke_session(
    session_id: uuid.UUID,
    request: Request,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("session.revoke_own"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    result = await db.execute(
        select(SessionModel).where(
            SessionModel.id == session_id,
            SessionModel.user_id == user.id,
        )
    )
    target_session = result.scalar_one_or_none()
    if not target_session:
        raise HTTPException(status_code=404, detail="Session not found")
    if target_session.status != "ACTIVE":
        raise HTTPException(status_code=409, detail="Session is not active")

    await logout_session(
        db,
        session=target_session,
        user=user,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return ApiResponse(data={"message": "Session revoked"}, meta=_meta())


@router.post("/identity-bindings", status_code=201)
async def create_binding(
    body: IdentityBindingRequest,
    request: Request,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("identity_binding.create"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[IdentityBindingResponse]:
    user, _ = user_session
    try:
        binding = await create_identity_binding(
            db,
            user=user,
            binding_type=body.binding_type,
            institution_code=body.institution_code,
            external_id=body.external_id,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except Exception as e:
        raise HTTPException(status_code=409, detail=str(e))
    return ApiResponse(
        data=_format_binding(binding),
        meta=_meta(),
    )


def _format_binding(b, *, unmask: bool = False) -> dict:
    from src.trailgoods.core.config import get_settings
    from src.trailgoods.core.encryption import decrypt_value, mask_id_number

    ext_id_display = "****"
    if b.external_id_encrypted:
        try:
            settings = get_settings()
            key = settings.get_encryption_key()
            plain = decrypt_value(b.external_id_encrypted, key)[0]
            ext_id_display = plain if unmask else mask_id_number(plain)
        except Exception:
            ext_id_display = "****"

    return {
        "id": str(b.id),
        "user_id": str(b.user_id),
        "binding_type": b.binding_type,
        "institution_code": b.institution_code,
        "external_id": ext_id_display,
        "status": b.status,
        "created_at": b.created_at.isoformat() if b.created_at else None,
    }


@router.get("/identity-bindings")
async def list_bindings(
    request: Request,
    user_session: Annotated[tuple[User, SessionModel], Depends(require_permission("identity_binding.read_own"))],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[dict]]:
    user, _ = user_session
    from src.trailgoods.services.audit import write_audit
    await write_audit(
        db,
        action="identity_binding.read",
        resource_type="identity_binding",
        actor_user_id=user.id,
        actor_role_snapshot=get_role_snapshot(user),
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    bindings = await get_user_bindings(db, user.id)
    return ApiResponse(
        data=[_format_binding(b) for b in bindings],
        meta=_meta(),
    )


@router.get("/admin/identity-bindings/{target_user_id}")
async def admin_read_bindings(
    target_user_id: uuid.UUID,
    request: Request,
    user_session: Annotated[
        tuple[User, SessionModel],
        Depends(require_permission("identity_binding.read_sensitive")),
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[dict]]:
    user, _ = user_session
    from src.trailgoods.services.audit import write_audit
    await write_audit(
        db,
        action="identity_binding.read_sensitive",
        resource_type="identity_binding",
        resource_id=str(target_user_id),
        actor_user_id=user.id,
        actor_role_snapshot=get_role_snapshot(user),
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    bindings = await get_user_bindings(db, target_user_id)
    return ApiResponse(
        data=[_format_binding(b, unmask=True) for b in bindings],
        meta=_meta(),
    )


@router.post("/admin/roles/assign", status_code=200)
async def admin_assign_role(
    body: RoleAssignRequest,
    request: Request,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("rbac.assign"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    try:
        await assign_role(
            db,
            target_user_id=body.user_id,
            role_name=body.role_name,
            actor_user_id=user.id,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ApiResponse(data={"message": f"Role '{body.role_name}' assigned"}, meta=_meta())


@router.post("/admin/force-logout")
async def admin_force_logout(
    body: ForceLogoutRequest,
    request: Request,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("admin.force_logout"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    count = await force_logout_user(
        db,
        target_user_id=body.user_id,
        actor_user_id=user.id,
        reason=body.reason,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return ApiResponse(data={"revoked_sessions": count}, meta=_meta())


@router.post("/admin/clear-challenge")
async def admin_clear_challenge(
    body: ForceLogoutRequest,
    request: Request,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("admin.clear_challenge"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    try:
        await clear_challenge(
            db,
            target_user_id=body.user_id,
            actor_user_id=user.id,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ApiResponse(data={"message": "Challenge cleared"}, meta=_meta())


@router.get("/admin/audit-logs")
async def list_audit_logs(
    request: Request,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("audit.read"))
    ],
    db: AsyncSession = Depends(get_db),
    limit: int = 20,
    offset: int = 0,
) -> ApiResponse[list[dict]]:
    user, _ = user_session
    from sqlalchemy import func as sqlfunc
    from src.trailgoods.models.auth import AuditLog
    from src.trailgoods.services.audit import write_audit

    await write_audit(
        db, action="audit.read", resource_type="audit_logs",
        actor_user_id=user.id,
        ip_address=_client_ip(request),
    )

    limit = min(limit, 100)
    count_q = await db.execute(select(sqlfunc.count()).select_from(AuditLog))
    total = count_q.scalar() or 0

    result = await db.execute(
        select(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    logs = result.scalars().all()
    from src.trailgoods.schemas.envelope import PaginationMeta

    return ApiResponse(
        data=[
            {
                "id": str(log.id),
                "request_id": log.request_id,
                "actor_user_id": str(log.actor_user_id) if log.actor_user_id else None,
                "action": log.action,
                "resource_type": log.resource_type,
                "resource_id": log.resource_id,
                "result": log.result,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
        meta=ResponseMeta(
            request_id=request_id_ctx.get(""),
            pagination=PaginationMeta(total=total, limit=limit, offset=offset),
        ),
    )
