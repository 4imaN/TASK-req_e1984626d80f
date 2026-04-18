import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.trailgoods.api.deps import (
    get_current_user,
    get_current_user_and_session,
    require_permission,
)
from src.trailgoods.core.database import get_db
from src.trailgoods.middleware.request_id import request_id_ctx
from src.trailgoods.models.auth import Session as SessionModel, User
from src.trailgoods.models.reviews import Appeal, Report, SensitiveWordTerm
from src.trailgoods.schemas.envelope import ApiResponse, PaginationMeta, ResponseMeta
from src.trailgoods.services.reviews import (
    close_report,
    create_appeal,
    create_report,
    create_review,
    decide_appeal,
    edit_review,
    list_item_reviews,
    moderate_review,
    triage_report,
)

router = APIRouter(prefix="/api/v1", tags=["reviews"])


def _meta() -> ResponseMeta:
    return ResponseMeta(request_id=request_id_ctx.get(""))


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


class CreateReviewRequest(BaseModel):
    rating: int
    body_raw: str
    structured_tags_json: str | None = None


class EditReviewRequest(BaseModel):
    body_raw: str
    rating: int | None = None
    structured_tags_json: str | None = None


class ModerateReviewRequest(BaseModel):
    action: str
    comment: str | None = None


class CreateReportRequest(BaseModel):
    target_type: str
    target_id: uuid.UUID
    reason_code: str
    details_raw: str | None = None


class TriageReportRequest(BaseModel):
    action: str
    comment: str | None = None


class CloseReportRequest(BaseModel):
    comment: str | None = None


class CreateAppealRequest(BaseModel):
    report_id: uuid.UUID | None = None
    review_id: uuid.UUID | None = None


class AppealDecisionRequest(BaseModel):
    action: str
    decision_summary: str
    comment: str | None = None


@router.post("/items/{item_id}/reviews", status_code=201)
async def create_review_endpoint(
    item_id: uuid.UUID,
    body: CreateReviewRequest,
    request: Request,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("review.create"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    try:
        review = await create_review(
            db,
            item_id=item_id,
            user_id=user.id,
            rating=body.rating,
            body_raw=body.body_raw,
            structured_tags_json=body.structured_tags_json,
            ip_address=_client_ip(request),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return ApiResponse(
        data={
            "id": str(review.id),
            "item_id": str(review.item_id),
            "user_id": str(review.user_id),
            "rating": review.rating,
            "status": review.status,
            "body_public": review.body_public,
            "structured_tags_json": review.structured_tags_json,
            "latest_revision_no": review.latest_revision_no,
            "created_at": review.created_at.isoformat() if review.created_at else None,
        },
        meta=_meta(),
    )


@router.patch("/reviews/{review_id}")
async def edit_review_endpoint(
    review_id: uuid.UUID,
    body: EditReviewRequest,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("review.edit_own"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    try:
        review = await edit_review(
            db,
            review_id=review_id,
            user_id=user.id,
            body_raw=body.body_raw,
            rating=body.rating,
            structured_tags_json=body.structured_tags_json,
        )
    except ValueError as e:
        detail = str(e)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail)
        if "owner" in detail.lower():
            raise HTTPException(status_code=403, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    return ApiResponse(
        data={
            "id": str(review.id),
            "item_id": str(review.item_id),
            "user_id": str(review.user_id),
            "rating": review.rating,
            "status": review.status,
            "body_public": review.body_public,
            "structured_tags_json": review.structured_tags_json,
            "latest_revision_no": review.latest_revision_no,
            "updated_at": review.updated_at.isoformat() if review.updated_at else None,
        },
        meta=_meta(),
    )


@router.get("/items/{item_id}/reviews")
async def list_item_reviews_endpoint(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    limit: int = 20,
    offset: int = 0,
) -> ApiResponse[list[dict]]:
    limit = min(limit, 100)
    reviews, total = await list_item_reviews(
        db,
        item_id=item_id,
        public_only=True,
        limit=limit,
        offset=offset,
    )
    return ApiResponse(
        data=[
            {
                "id": str(r["id"]),
                "item_id": str(r["item_id"]),
                "rating": r["rating"],
                "status": r["status"],
                "body_public": r["body_public"],
                "structured_tags_json": r["structured_tags_json"],
                "latest_revision_no": r["latest_revision_no"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            }
            for r in reviews
        ],
        meta=ResponseMeta(
            request_id=request_id_ctx.get(""),
            pagination=PaginationMeta(total=total, limit=limit, offset=offset),
        ),
    )


@router.post("/reviews/{review_id}/moderate")
async def moderate_review_endpoint(
    review_id: uuid.UUID,
    body: ModerateReviewRequest,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("review.moderate"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    try:
        review = await moderate_review(
            db,
            review_id=review_id,
            action=body.action,
            reviewer_user_id=user.id,
            comment=body.comment,
        )
    except ValueError as e:
        detail = str(e)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    return ApiResponse(
        data={
            "id": str(review.id),
            "item_id": str(review.item_id),
            "status": review.status,
            "updated_at": review.updated_at.isoformat() if review.updated_at else None,
        },
        meta=_meta(),
    )


@router.post("/reports", status_code=201)
async def create_report_endpoint(
    body: CreateReportRequest,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("report.create"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    try:
        report = await create_report(
            db,
            target_type=body.target_type,
            target_id=body.target_id,
            reporter_user_id=user.id,
            reason_code=body.reason_code,
            details_raw=body.details_raw,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return ApiResponse(
        data={
            "id": str(report.id),
            "target_type": report.target_type,
            "target_id": str(report.target_id),
            "reporter_user_id": str(report.reporter_user_id),
            "reason_code": report.reason_code,
            "details_raw": report.details_raw,
            "status": report.status,
            "triage_due_at": report.triage_due_at.isoformat() if report.triage_due_at else None,
            "created_at": report.created_at.isoformat() if report.created_at else None,
        },
        meta=_meta(),
    )


@router.post("/reports/{report_id}/triage")
async def triage_report_endpoint(
    report_id: uuid.UUID,
    body: TriageReportRequest,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("report.triage"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    try:
        report = await triage_report(
            db,
            report_id=report_id,
            reviewer_user_id=user.id,
            action=body.action,
            comment=body.comment,
        )
    except ValueError as e:
        detail = str(e)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    return ApiResponse(
        data={
            "id": str(report.id),
            "status": report.status,
            "triaged_at": report.triaged_at.isoformat() if report.triaged_at else None,
        },
        meta=_meta(),
    )


@router.post("/reports/{report_id}/close")
async def close_report_endpoint(
    report_id: uuid.UUID,
    body: CloseReportRequest,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("report.close"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    try:
        report = await close_report(
            db,
            report_id=report_id,
            reviewer_user_id=user.id,
            comment=body.comment,
        )
    except ValueError as e:
        detail = str(e)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    return ApiResponse(
        data={
            "id": str(report.id),
            "status": report.status,
            "closed_at": report.closed_at.isoformat() if report.closed_at else None,
        },
        meta=_meta(),
    )


@router.post("/appeals", status_code=201)
async def create_appeal_endpoint(
    body: CreateAppealRequest,
    request: Request,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("appeal.create"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    try:
        appeal = await create_appeal(
            db,
            report_id=body.report_id,
            review_id=body.review_id,
            appellant_user_id=user.id,
            ip_address=_client_ip(request),
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        detail = str(e)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail)
        if "already exists" in detail.lower():
            raise HTTPException(status_code=409, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    return ApiResponse(
        data={
            "id": str(appeal.id),
            "report_id": str(appeal.report_id) if appeal.report_id else None,
            "review_id": str(appeal.review_id) if appeal.review_id else None,
            "appellant_user_id": str(appeal.appellant_user_id),
            "status": appeal.status,
            "due_at": appeal.due_at.isoformat() if appeal.due_at else None,
            "created_at": appeal.created_at.isoformat() if appeal.created_at else None,
        },
        meta=_meta(),
    )


@router.post("/appeals/{appeal_id}/decision")
async def decide_appeal_endpoint(
    appeal_id: uuid.UUID,
    body: AppealDecisionRequest,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("appeal.decide"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    try:
        appeal = await decide_appeal(
            db,
            appeal_id=appeal_id,
            reviewer_user_id=user.id,
            decision_summary=body.decision_summary,
            action=body.action,
            comment=body.comment,
        )
    except ValueError as e:
        detail = str(e)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    return ApiResponse(
        data={
            "id": str(appeal.id),
            "status": appeal.status,
            "decision_summary": appeal.decision_summary,
            "decided_at": appeal.decided_at.isoformat() if appeal.decided_at else None,
        },
        meta=_meta(),
    )


@router.get("/reports")
async def list_reports_endpoint(
    request: Request,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("report.triage"))
    ],
    db: AsyncSession = Depends(get_db),
    status: str | None = None,
    target_type: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> ApiResponse[list[dict]]:
    user, _ = user_session
    from sqlalchemy import and_, func as sqlfunc
    from src.trailgoods.schemas.envelope import PaginationMeta
    from src.trailgoods.services.audit import write_audit
    await write_audit(db, action="reports.list", resource_type="reports", actor_user_id=user.id)

    limit = min(limit, 100)
    conditions = []
    if status:
        conditions.append(Report.status == status)
    if target_type:
        conditions.append(Report.target_type == target_type)

    base = select(Report)
    count_q = select(sqlfunc.count()).select_from(Report)
    if conditions:
        base = base.where(and_(*conditions))
        count_q = count_q.where(and_(*conditions))

    total = (await db.execute(count_q)).scalar() or 0
    result = await db.execute(base.order_by(Report.created_at.desc()).limit(limit).offset(offset))
    reports = result.scalars().all()

    return ApiResponse(
        data=[
            {
                "id": str(r.id), "target_type": r.target_type,
                "target_id": str(r.target_id), "reason_code": r.reason_code,
                "status": r.status,
                "triage_due_at": r.triage_due_at.isoformat() if r.triage_due_at else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in reports
        ],
        meta=ResponseMeta(
            request_id=request_id_ctx.get(""),
            pagination=PaginationMeta(total=total, limit=limit, offset=offset),
        ),
    )


class CreateSensitiveWordRequest(BaseModel):
    term: str
    category: str


@router.post("/admin/sensitive-words", status_code=201)
async def create_sensitive_word_endpoint(
    body: CreateSensitiveWordRequest,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("sensitive_word.manage"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    term = SensitiveWordTerm(term=body.term, category=body.category)
    db.add(term)
    await db.flush()
    from src.trailgoods.services.audit import write_audit
    await write_audit(
        db,
        action="sensitive_word.create",
        resource_type="sensitive_word_term",
        resource_id=str(term.id),
        actor_user_id=user.id,
    )
    await db.commit()
    return ApiResponse(
        data={
            "id": str(term.id),
            "term": term.term,
            "category": term.category,
            "is_active": term.is_active,
            "created_at": term.created_at.isoformat() if term.created_at else None,
        },
        meta=_meta(),
    )


@router.delete("/admin/sensitive-words/{term_id}")
async def delete_sensitive_word_endpoint(
    term_id: uuid.UUID,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("sensitive_word.manage"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    result = await db.execute(select(SensitiveWordTerm).where(SensitiveWordTerm.id == term_id))
    term = result.scalar_one_or_none()
    if not term:
        raise HTTPException(status_code=404, detail="Sensitive word term not found")
    term.is_active = False
    from src.trailgoods.services.audit import write_audit
    await write_audit(
        db,
        action="sensitive_word.deactivate",
        resource_type="sensitive_word_term",
        resource_id=str(term_id),
        actor_user_id=user.id,
    )
    await db.commit()
    return ApiResponse(data={"message": "Sensitive word term deactivated"}, meta=_meta())


@router.get("/admin/sensitive-words")
async def list_sensitive_words_endpoint(
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("sensitive_word.manage"))
    ],
    db: AsyncSession = Depends(get_db),
    limit: int = 20,
    offset: int = 0,
) -> ApiResponse[list[dict]]:
    user, _ = user_session
    from sqlalchemy import func as sqlfunc
    from src.trailgoods.services.audit import write_audit
    await write_audit(db, action="sensitive_words.list", resource_type="sensitive_word_terms", actor_user_id=user.id)

    limit = min(limit, 100)
    count_q = select(sqlfunc.count()).select_from(SensitiveWordTerm)
    total = (await db.execute(count_q)).scalar() or 0
    result = await db.execute(
        select(SensitiveWordTerm)
        .order_by(SensitiveWordTerm.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    terms = result.scalars().all()
    return ApiResponse(
        data=[
            {
                "id": str(t.id),
                "term": t.term,
                "category": t.category,
                "is_active": t.is_active,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in terms
        ],
        meta=ResponseMeta(
            request_id=request_id_ctx.get(""),
            pagination=PaginationMeta(total=total, limit=limit, offset=offset),
        ),
    )


@router.get("/appeals")
async def list_appeals_endpoint(
    request: Request,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("appeal.decide"))
    ],
    db: AsyncSession = Depends(get_db),
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> ApiResponse[list[dict]]:
    user, _ = user_session
    from sqlalchemy import and_, func as sqlfunc
    from src.trailgoods.schemas.envelope import PaginationMeta
    from src.trailgoods.services.audit import write_audit
    await write_audit(db, action="appeals.list", resource_type="appeals", actor_user_id=user.id)

    limit = min(limit, 100)
    conditions = []
    if status:
        conditions.append(Appeal.status == status)

    base = select(Appeal)
    count_q = select(sqlfunc.count()).select_from(Appeal)
    if conditions:
        base = base.where(and_(*conditions))
        count_q = count_q.where(and_(*conditions))

    total = (await db.execute(count_q)).scalar() or 0
    result = await db.execute(base.order_by(Appeal.created_at.desc()).limit(limit).offset(offset))
    appeals = result.scalars().all()

    return ApiResponse(
        data=[
            {
                "id": str(a.id),
                "report_id": str(a.report_id) if a.report_id else None,
                "review_id": str(a.review_id) if a.review_id else None,
                "appellant_user_id": str(a.appellant_user_id),
                "status": a.status,
                "due_at": a.due_at.isoformat() if a.due_at else None,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in appeals
        ],
        meta=ResponseMeta(
            request_id=request_id_ctx.get(""),
            pagination=PaginationMeta(total=total, limit=limit, offset=offset),
        ),
    )
