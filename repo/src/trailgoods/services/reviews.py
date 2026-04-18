import re
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.trailgoods.models.catalog import Item

_EMAIL_PATTERN = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
_PHONE_PATTERN = re.compile(r'(?:\+?\d{1,3}[\s\-]?)?\(?\d{2,4}\)?[\s\-]?\d{3,4}[\s\-]?\d{3,4}')


def _strip_pii(text: str) -> str:
    text = _EMAIL_PATTERN.sub("[email redacted]", text)
    text = _PHONE_PATTERN.sub("[phone redacted]", text)
    return text
from src.trailgoods.models.reviews import (
    Appeal,
    AppealEvent,
    Report,
    ReportEvent,
    Review,
    ReviewRevision,
    SensitiveWordTerm,
)
from src.trailgoods.services.audit import write_audit


async def filter_sensitive_words(db: AsyncSession, text: str) -> tuple[str, list[str]]:
    result = await db.execute(
        select(SensitiveWordTerm).where(SensitiveWordTerm.is_active == True)
    )
    terms = list(result.scalars().all())

    normalized = unicodedata.normalize("NFKC", text).lower()
    normalized = " ".join(normalized.split())

    matched_terms: list[str] = []
    filtered = normalized

    for term_row in terms:
        term_lower = unicodedata.normalize("NFKC", term_row.term).lower().strip()
        if term_lower and term_lower in filtered:
            if term_row.term not in matched_terms:
                matched_terms.append(term_row.term)
            filtered = filtered.replace(term_lower, "*" * len(term_lower))

    return filtered, matched_terms


async def create_review(
    db: AsyncSession,
    *,
    item_id: uuid.UUID,
    user_id: uuid.UUID,
    rating: int,
    body_raw: str,
    structured_tags_json: str | None = None,
    ip_address: str | None = None,
) -> Review:
    if rating < 1 or rating > 5:
        raise ValueError("rating must be between 1 and 5")

    item_result = await db.execute(select(Item).where(Item.id == item_id))
    item = item_result.scalar_one_or_none()
    if not item:
        raise ValueError("Item not found")
    if item.status != "PUBLISHED" or not item.is_public:
        raise ValueError("Only published items can be reviewed")

    existing_review = await db.execute(
        select(Review).where(Review.item_id == item_id, Review.user_id == user_id)
    )
    if existing_review.scalar_one_or_none():
        raise ValueError("You have already reviewed this item")

    body_public, matched_terms = await filter_sensitive_words(db, body_raw)
    body_public = _strip_pii(body_public)
    status = "PENDING_REVIEW" if matched_terms else "PUBLISHED"

    review = Review(
        item_id=item_id,
        user_id=user_id,
        rating=rating,
        status=status,
        body_raw=body_raw,
        body_public=body_public,
        structured_tags_json=structured_tags_json,
        latest_revision_no=1,
    )
    db.add(review)
    await db.flush()

    revision = ReviewRevision(
        review_id=review.id,
        revision_number=1,
        body_raw=body_raw,
        body_public=body_public,
        structured_tags_json=structured_tags_json,
    )
    db.add(revision)
    await db.flush()

    await write_audit(
        db,
        action="reviews.review.create",
        resource_type="review",
        resource_id=str(review.id),
        actor_user_id=user_id,
        after_json=f'{{"status": "{status}", "rating": {rating}}}',
        ip_address=ip_address,
    )
    await db.flush()
    return review


async def edit_review(
    db: AsyncSession,
    *,
    review_id: uuid.UUID,
    user_id: uuid.UUID,
    body_raw: str,
    rating: int | None = None,
    structured_tags_json: str | None = None,
) -> Review:
    result = await db.execute(select(Review).where(Review.id == review_id))
    review = result.scalar_one_or_none()
    if not review:
        raise ValueError("Review not found")

    if review.user_id != user_id:
        raise ValueError("Only the review owner can edit this review")

    if rating is not None:
        if rating < 1 or rating > 5:
            raise ValueError("rating must be between 1 and 5")
        review.rating = rating

    body_public, matched_terms = await filter_sensitive_words(db, body_raw)
    body_public = _strip_pii(body_public)
    status = "PENDING_REVIEW" if matched_terms else "PUBLISHED"

    before_status = review.status
    review.body_raw = body_raw
    review.body_public = body_public
    review.structured_tags_json = structured_tags_json
    review.status = status
    review.latest_revision_no = review.latest_revision_no + 1
    review.updated_at = datetime.now(timezone.utc)

    new_revision_no = review.latest_revision_no
    await db.flush()

    revision = ReviewRevision(
        review_id=review.id,
        revision_number=new_revision_no,
        body_raw=body_raw,
        body_public=body_public,
        structured_tags_json=structured_tags_json,
    )
    db.add(revision)
    await db.flush()

    await write_audit(
        db,
        action="reviews.review.edit",
        resource_type="review",
        resource_id=str(review_id),
        actor_user_id=user_id,
        before_json=f'{{"status": "{before_status}"}}',
        after_json=f'{{"status": "{status}", "revision_no": {new_revision_no}}}',
    )
    await db.flush()
    return review


async def list_item_reviews(
    db: AsyncSession,
    *,
    item_id: uuid.UUID,
    public_only: bool = True,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict], int]:
    conditions = [Review.item_id == item_id]
    if public_only:
        conditions.append(Review.status == "PUBLISHED")

    count_result = await db.execute(
        select(func.count(Review.id)).where(and_(*conditions))
    )
    total = count_result.scalar_one()

    rows_result = await db.execute(
        select(Review)
        .where(and_(*conditions))
        .order_by(Review.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    reviews = list(rows_result.scalars().all())

    items_out = []
    for r in reviews:
        items_out.append({
            "id": r.id,
            "item_id": r.item_id,
            "rating": r.rating,
            "status": r.status,
            "body_public": r.body_public,
            "structured_tags_json": r.structured_tags_json,
            "latest_revision_no": r.latest_revision_no,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
        })

    return items_out, total


async def moderate_review(
    db: AsyncSession,
    *,
    review_id: uuid.UUID,
    action: str,
    reviewer_user_id: uuid.UUID,
    comment: str | None = None,
) -> Review:
    valid_actions = {"PUBLISHED", "SUPPRESSED", "REMOVED"}
    if action not in valid_actions:
        raise ValueError(f"action must be one of {sorted(valid_actions)}")

    result = await db.execute(select(Review).where(Review.id == review_id))
    review = result.scalar_one_or_none()
    if not review:
        raise ValueError("Review not found")

    valid_transitions: dict[str, set[str]] = {
        "PUBLISHED": {"PENDING_REVIEW", "SUPPRESSED"},
        "SUPPRESSED": {"PUBLISHED", "PENDING_REVIEW"},
        "REMOVED": {"PUBLISHED", "PENDING_REVIEW", "SUPPRESSED"},
    }
    if review.status not in valid_transitions.get(action, set()):
        raise ValueError(
            f"Cannot transition review from status '{review.status}' to '{action}'"
        )

    before_status = review.status
    review.status = action
    review.updated_at = datetime.now(timezone.utc)
    await db.flush()

    from src.trailgoods.models.reviews import ReviewModerationEvent
    db.add(ReviewModerationEvent(
        review_id=review_id,
        event_type="moderation",
        from_status=before_status,
        to_status=action,
        actor_user_id=reviewer_user_id,
        comment=comment,
    ))

    await write_audit(
        db,
        action="reviews.review.moderate",
        resource_type="review",
        resource_id=str(review_id),
        actor_user_id=reviewer_user_id,
        before_json=f'{{"status": "{before_status}"}}',
        after_json=f'{{"status": "{action}"}}',
    )
    await db.flush()
    return review


async def create_report(
    db: AsyncSession,
    *,
    target_type: str,
    target_id: uuid.UUID,
    reporter_user_id: uuid.UUID,
    reason_code: str,
    details_raw: str | None = None,
) -> Report:
    valid_types = {"REVIEW", "ITEM", "ASSET", "USER"}
    if target_type not in valid_types:
        raise ValueError(f"target_type must be one of {sorted(valid_types)}")

    from src.trailgoods.models.assets import Asset
    from src.trailgoods.models.auth import User

    target_models = {"REVIEW": Review, "ITEM": Item, "ASSET": Asset, "USER": User}
    model = target_models[target_type]
    target_result = await db.execute(select(model).where(model.id == target_id))
    if not target_result.scalar_one_or_none():
        raise ValueError(f"{target_type} with id {target_id} not found")

    now = datetime.now(timezone.utc)
    triage_due_at = now + timedelta(hours=48)

    report = Report(
        target_type=target_type,
        target_id=target_id,
        reporter_user_id=reporter_user_id,
        reason_code=reason_code,
        details_raw=details_raw,
        status="SUBMITTED",
        triage_due_at=triage_due_at,
    )
    db.add(report)
    await db.flush()

    await write_audit(
        db,
        action="reviews.report.create",
        resource_type="report",
        resource_id=str(report.id),
        actor_user_id=reporter_user_id,
        after_json=f'{{"target_type": "{target_type}", "reason_code": "{reason_code}"}}',
    )
    await db.flush()
    return report


async def triage_report(
    db: AsyncSession,
    *,
    report_id: uuid.UUID,
    reviewer_user_id: uuid.UUID,
    action: str,
    comment: str | None = None,
) -> Report:
    valid_actions = {"TRIAGED", "DISMISSED"}
    if action not in valid_actions:
        raise ValueError(f"action must be one of {sorted(valid_actions)}")

    result = await db.execute(select(Report).where(Report.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise ValueError("Report not found")

    if report.status != "SUBMITTED":
        raise ValueError(
            f"Cannot triage report in status '{report.status}'; expected SUBMITTED"
        )

    before_status = report.status
    now = datetime.now(timezone.utc)
    report.status = action
    report.triaged_at = now
    await db.flush()

    event = ReportEvent(
        report_id=report.id,
        event_type=action,
        from_status=before_status,
        to_status=action,
        actor_user_id=reviewer_user_id,
        comment=comment,
    )
    db.add(event)
    await db.flush()

    await write_audit(
        db,
        action="reviews.report.triage",
        resource_type="report",
        resource_id=str(report_id),
        actor_user_id=reviewer_user_id,
        before_json=f'{{"status": "{before_status}"}}',
        after_json=f'{{"status": "{action}"}}',
    )
    await db.flush()
    return report


async def close_report(
    db: AsyncSession,
    *,
    report_id: uuid.UUID,
    reviewer_user_id: uuid.UUID,
    comment: str | None = None,
) -> Report:
    result = await db.execute(select(Report).where(Report.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise ValueError("Report not found")

    closable = {"TRIAGED", "ACTIONED", "DISMISSED"}
    if report.status not in closable:
        raise ValueError(
            f"Cannot close report in status '{report.status}'. Must be triaged first."
        )

    before_status = report.status
    now = datetime.now(timezone.utc)
    report.status = "CLOSED"
    report.closed_at = now
    await db.flush()

    event = ReportEvent(
        report_id=report.id,
        event_type="CLOSED",
        from_status=before_status,
        to_status="CLOSED",
        actor_user_id=reviewer_user_id,
        comment=comment,
    )
    db.add(event)
    await db.flush()

    await write_audit(
        db,
        action="reviews.report.close",
        resource_type="report",
        resource_id=str(report_id),
        actor_user_id=reviewer_user_id,
        before_json=f'{{"status": "{before_status}"}}',
        after_json='{"status": "CLOSED"}',
    )
    await db.flush()
    return report


async def create_appeal(
    db: AsyncSession,
    *,
    report_id: uuid.UUID | None = None,
    review_id: uuid.UUID | None = None,
    appellant_user_id: uuid.UUID,
    ip_address: str | None = None,
) -> Appeal:
    if report_id is None and review_id is None:
        raise ValueError("Either report_id or review_id must be provided")

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=14)

    if report_id is not None:
        report_result = await db.execute(select(Report).where(Report.id == report_id))
        report = report_result.scalar_one_or_none()
        if not report:
            raise ValueError("Report not found")

        if report.reporter_user_id != appellant_user_id:
            raise PermissionError("Only the reporter can appeal this report")

        appealable_states = {"TRIAGED", "ACTIONED", "DISMISSED", "CLOSED"}
        if report.status not in appealable_states:
            raise ValueError(
                f"Report must be in an appealable state ({', '.join(sorted(appealable_states))}), "
                f"not {report.status}"
            )

        decision_time = report.closed_at or report.triaged_at
        if not decision_time:
            raise ValueError("No decision timestamp found on this report")
        if decision_time < cutoff:
            raise ValueError("Appeal window has expired; must appeal within 14 days of the decision")

        existing_result = await db.execute(
            select(Appeal).where(Appeal.report_id == report_id)
        )
        if existing_result.scalar_one_or_none():
            raise ValueError("An appeal for this report already exists")

    if review_id is not None:
        review_result = await db.execute(select(Review).where(Review.id == review_id))
        review = review_result.scalar_one_or_none()
        if not review:
            raise ValueError("Review not found")

        if review.user_id != appellant_user_id:
            raise PermissionError("Only the review author can appeal a moderation decision")

        moderated_states = {"SUPPRESSED", "REMOVED"}
        if review.status not in moderated_states:
            raise ValueError(
                f"Review must be in a moderated state ({', '.join(sorted(moderated_states))}), "
                f"not {review.status}"
            )

        decision_time = review.updated_at or review.created_at
        if decision_time < cutoff:
            raise ValueError("Appeal window has expired; must appeal within 14 days of the decision")

        existing_result = await db.execute(
            select(Appeal).where(Appeal.review_id == review_id)
        )
        if existing_result.scalar_one_or_none():
            raise ValueError("An appeal for this review already exists")

    due_at = now + timedelta(days=14)

    appeal = Appeal(
        report_id=report_id,
        review_id=review_id,
        appellant_user_id=appellant_user_id,
        status="SUBMITTED",
        due_at=due_at,
    )
    db.add(appeal)
    await db.flush()

    await write_audit(
        db,
        action="reviews.appeal.create",
        resource_type="appeal",
        resource_id=str(appeal.id),
        actor_user_id=appellant_user_id,
        after_json=f'{{"report_id": "{report_id}", "review_id": "{review_id}"}}',
        ip_address=ip_address,
    )
    await db.flush()
    return appeal


async def decide_appeal(
    db: AsyncSession,
    *,
    appeal_id: uuid.UUID,
    reviewer_user_id: uuid.UUID,
    decision_summary: str,
    action: str,
    comment: str | None = None,
) -> Appeal:
    valid_actions = {"DECIDED", "CLOSED"}
    if action not in valid_actions:
        raise ValueError(f"action must be one of {sorted(valid_actions)}")

    result = await db.execute(select(Appeal).where(Appeal.id == appeal_id))
    appeal = result.scalar_one_or_none()
    if not appeal:
        raise ValueError("Appeal not found")

    if appeal.status not in ("SUBMITTED",):
        raise ValueError(
            f"Cannot decide appeal in status '{appeal.status}'; expected SUBMITTED"
        )

    before_status = appeal.status
    now = datetime.now(timezone.utc)
    appeal.status = action
    appeal.decision_summary = decision_summary
    appeal.decided_at = now
    await db.flush()

    event = AppealEvent(
        appeal_id=appeal.id,
        event_type=action,
        from_status=before_status,
        to_status=action,
        actor_user_id=reviewer_user_id,
        comment=comment,
    )
    db.add(event)
    await db.flush()

    await write_audit(
        db,
        action="reviews.appeal.decide",
        resource_type="appeal",
        resource_id=str(appeal_id),
        actor_user_id=reviewer_user_id,
        before_json=f'{{"status": "{before_status}"}}',
        after_json=f'{{"status": "{action}"}}',
    )
    await db.flush()
    return appeal
