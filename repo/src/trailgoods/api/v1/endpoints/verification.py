import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.trailgoods.api.deps import (
    get_user_permissions,
    get_user_role_names,
    require_permission,
)
from src.trailgoods.core.database import get_db
from src.trailgoods.middleware.request_id import request_id_ctx
from src.trailgoods.models.auth import Session as SessionModel, User
from src.trailgoods.schemas.envelope import ApiResponse, ResponseMeta
from src.trailgoods.services.verification import (
    create_verification_case,
    decide_verification_case,
    get_verification_case,
    get_verification_status,
    renew_verification_case,
    submit_verification_case,
    update_verification_case,
    withdraw_verification_case,
)

router = APIRouter(prefix="/api/v1", tags=["verification"])


def _meta() -> ResponseMeta:
    return ResponseMeta(request_id=request_id_ctx.get(""))


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


class CreateVerificationCaseRequest(BaseModel):
    profile_type: str


class UpdateVerificationCaseRequest(BaseModel):
    row_version: int
    legal_name: str | None = None
    dob: str | None = None
    government_id_number: str | None = None
    government_id_image_asset_id: uuid.UUID | None = None
    enterprise_legal_name: str | None = None
    enterprise_registration_number: str | None = None
    enterprise_registration_asset_id: uuid.UUID | None = None
    responsible_person_legal_name: str | None = None
    responsible_person_dob: str | None = None
    responsible_person_id_number: str | None = None
    responsible_person_id_image_asset_id: uuid.UUID | None = None


class DecisionRequest(BaseModel):
    decision: str
    comment: str | None = None


@router.post("/verification-cases", status_code=201)
async def create_case(
    body: CreateVerificationCaseRequest,
    request: Request,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("verification.create"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    try:
        case = await create_verification_case(
            db,
            user_id=user.id,
            profile_type=body.profile_type,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except ValueError as e:
        detail = str(e)
        if "already exists" in detail:
            raise HTTPException(status_code=409, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    return ApiResponse(
        data={
            "case_id": case.case_id,
            "profile_type": case.profile_type,
            "status": case.status,
            "row_version": case.row_version,
        },
        meta=_meta(),
    )


@router.patch("/verification-cases/{case_id}")
async def update_case(
    case_id: str,
    body: UpdateVerificationCaseRequest,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("verification.submit"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    try:
        case = await update_verification_case(
            db,
            case_id=case_id,
            user_id=user.id,
            row_version=body.row_version,
            legal_name=body.legal_name,
            dob=body.dob,
            government_id_number=body.government_id_number,
            government_id_image_asset_id=body.government_id_image_asset_id,
            enterprise_legal_name=body.enterprise_legal_name,
            enterprise_registration_number=body.enterprise_registration_number,
            enterprise_registration_asset_id=body.enterprise_registration_asset_id,
            responsible_person_legal_name=body.responsible_person_legal_name,
            responsible_person_dob=body.responsible_person_dob,
            responsible_person_id_number=body.responsible_person_id_number,
            responsible_person_id_image_asset_id=body.responsible_person_id_image_asset_id,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        detail = str(e)
        if "not found" in detail:
            raise HTTPException(status_code=404, detail=detail)
        if "Conflict" in detail:
            raise HTTPException(status_code=409, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    return ApiResponse(
        data={
            "case_id": case.case_id,
            "status": case.status,
            "row_version": case.row_version,
        },
        meta=_meta(),
    )


@router.post("/verification-cases/{case_id}/submit")
async def submit_case(
    case_id: str,
    request: Request,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("verification.submit"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    try:
        case = await submit_verification_case(
            db,
            case_id=case_id,
            user_id=user.id,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except ValueError as e:
        detail = str(e)
        if "not found" in detail:
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    return ApiResponse(
        data={
            "case_id": case.case_id,
            "status": case.status,
            "row_version": case.row_version,
        },
        meta=_meta(),
    )


@router.get("/verification-cases/{case_id}")
async def get_case(
    case_id: str,
    request: Request,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("verification.read_own"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    role_names = get_user_role_names(user)
    perms = get_user_permissions(user)
    is_admin = "Admin" in role_names
    is_privileged = is_admin or "Reviewer" in role_names
    include_sensitive = "verification.sensitive.read" in perms

    scoped_user_id = None if is_privileged else user.id
    data = await get_verification_case(
        db,
        case_id=case_id,
        user_id=scoped_user_id,
        include_sensitive=include_sensitive,
    )
    if data is None:
        raise HTTPException(status_code=404, detail="Verification case not found")

    if include_sensitive:
        from src.trailgoods.services.audit import write_audit
        await write_audit(
            db,
            action="verification.sensitive.read",
            resource_type="verification_case",
            resource_id=case_id,
            actor_user_id=user.id,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
        await db.commit()

    return ApiResponse(data=data, meta=_meta())


@router.get("/verification-cases/{case_id}/status")
async def get_case_status(
    case_id: str,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("verification.read_own"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    data = await get_verification_status(db, case_id=case_id, user_id=user.id)
    if data is None:
        raise HTTPException(status_code=404, detail="Verification case not found")
    return ApiResponse(data=data, meta=_meta())


@router.post("/verification-cases/{case_id}/withdraw")
async def withdraw_case(
    case_id: str,
    request: Request,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("verification.withdraw"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    try:
        case = await withdraw_verification_case(
            db,
            case_id=case_id,
            user_id=user.id,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except ValueError as e:
        detail = str(e)
        if "not found" in detail:
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    return ApiResponse(
        data={
            "case_id": case.case_id,
            "status": case.status,
            "row_version": case.row_version,
        },
        meta=_meta(),
    )


@router.post("/verification-cases/{case_id}/renew")
async def renew_case(
    case_id: str,
    request: Request,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("verification.renew"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    try:
        case = await renew_verification_case(
            db,
            case_id=case_id,
            user_id=user.id,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except ValueError as e:
        detail = str(e)
        if "not found" in detail:
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    return ApiResponse(
        data={
            "case_id": case.case_id,
            "status": case.status,
            "row_version": case.row_version,
        },
        meta=_meta(),
    )


@router.post("/verification-cases/{case_id}/decision")
async def decision_case(
    case_id: str,
    body: DecisionRequest,
    request: Request,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("verification.review"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    try:
        case = await decide_verification_case(
            db,
            case_id=case_id,
            decision=body.decision,
            reviewer_user_id=user.id,
            comment=body.comment,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except ValueError as e:
        detail = str(e)
        if "not found" in detail:
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    return ApiResponse(
        data={
            "case_id": case.case_id,
            "status": case.status,
            "row_version": case.row_version,
        },
        meta=_meta(),
    )


@router.get("/verification-cases")
async def list_verification_cases(
    request: Request,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("verification.review"))
    ],
    db: AsyncSession = Depends(get_db),
    status: str | None = None,
    profile_type: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> ApiResponse[list[dict]]:
    user, _ = user_session
    from sqlalchemy import and_, func as sqlfunc
    from src.trailgoods.models.verification import VerificationCase
    from src.trailgoods.schemas.envelope import PaginationMeta
    from src.trailgoods.services.audit import write_audit

    await write_audit(
        db, action="verification.cases.list", resource_type="verification_case",
        actor_user_id=user.id, ip_address=_client_ip(request),
    )

    limit = min(limit, 100)
    conditions = []
    if status:
        conditions.append(VerificationCase.status == status)
    if profile_type:
        conditions.append(VerificationCase.profile_type == profile_type)

    base = select(VerificationCase)
    count_q = select(sqlfunc.count()).select_from(VerificationCase)
    if conditions:
        base = base.where(and_(*conditions))
        count_q = count_q.where(and_(*conditions))

    total = (await db.execute(count_q)).scalar() or 0
    result = await db.execute(base.order_by(VerificationCase.created_at.desc()).limit(limit).offset(offset))
    cases = result.scalars().all()

    return ApiResponse(
        data=[
            {
                "id": str(c.id), "case_id": c.case_id, "user_id": str(c.user_id),
                "profile_type": c.profile_type, "status": c.status,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in cases
        ],
        meta=ResponseMeta(
            request_id=request_id_ctx.get(""),
            pagination=PaginationMeta(total=total, limit=limit, offset=offset),
        ),
    )
