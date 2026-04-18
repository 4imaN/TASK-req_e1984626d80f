import json
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.trailgoods.core.config import get_settings
from src.trailgoods.core.encryption import decrypt_value, encrypt_value, mask_dob, mask_id_number, mask_legal_name
from src.trailgoods.models.enums import VerificationStatus
from src.trailgoods.models.verification import VerificationCase, VerificationCaseEvent, VerificationCaseRevision
from src.trailgoods.services.audit import write_audit

VALID_TRANSITIONS = {
    VerificationStatus.DRAFT: {VerificationStatus.SUBMITTED, VerificationStatus.WITHDRAWN},
    VerificationStatus.SUBMITTED: {VerificationStatus.UNDER_REVIEW, VerificationStatus.WITHDRAWN},
    VerificationStatus.UNDER_REVIEW: {VerificationStatus.NEEDS_INFO, VerificationStatus.APPROVED, VerificationStatus.REJECTED},
    VerificationStatus.NEEDS_INFO: {VerificationStatus.SUBMITTED, VerificationStatus.WITHDRAWN},
    VerificationStatus.APPROVED: {VerificationStatus.EXPIRED},
    VerificationStatus.REJECTED: set(),
    VerificationStatus.EXPIRED: {VerificationStatus.SUBMITTED},
    VerificationStatus.WITHDRAWN: set(),
}

ACTIVE_STATUSES = {
    VerificationStatus.DRAFT,
    VerificationStatus.SUBMITTED,
    VerificationStatus.UNDER_REVIEW,
    VerificationStatus.NEEDS_INFO,
}


def _generate_case_id() -> str:
    return f"VC-{secrets.token_hex(12).upper()}"


def _validate_dob(dob_str: str) -> datetime:
    parts = dob_str.split("/")
    if len(parts) != 3:
        raise ValueError("DOB must be in MM/DD/YYYY format")
    try:
        month, day, year = int(parts[0]), int(parts[1]), int(parts[2])
        dob = datetime(year, month, day)
    except (ValueError, OverflowError):
        raise ValueError("DOB must be a valid date in MM/DD/YYYY format")
    age = (datetime.now() - dob).days / 365.25
    if age < 18:
        raise ValueError("Applicant must be at least 18 years old")
    return dob


async def create_verification_case(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    profile_type: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> VerificationCase:
    if profile_type not in ("PERSONAL", "ENTERPRISE"):
        raise ValueError("profile_type must be PERSONAL or ENTERPRISE")

    existing = await db.execute(
        select(VerificationCase).where(
            VerificationCase.user_id == user_id,
            VerificationCase.profile_type == profile_type,
            VerificationCase.status.in_([s.value for s in ACTIVE_STATUSES]),
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError("An active verification case already exists for this profile type")

    case = VerificationCase(
        case_id=_generate_case_id(),
        user_id=user_id,
        profile_type=profile_type,
        status=VerificationStatus.DRAFT.value,
    )
    db.add(case)

    await write_audit(
        db,
        action="verification.create",
        resource_type="verification_case",
        resource_id=case.case_id,
        actor_user_id=user_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.flush()
    return case


async def update_verification_case(
    db: AsyncSession,
    *,
    case_id: str,
    user_id: uuid.UUID,
    row_version: int,
    legal_name: str | None = None,
    dob: str | None = None,
    government_id_number: str | None = None,
    government_id_image_asset_id: uuid.UUID | None = None,
    enterprise_legal_name: str | None = None,
    enterprise_registration_number: str | None = None,
    enterprise_registration_asset_id: uuid.UUID | None = None,
    responsible_person_legal_name: str | None = None,
    responsible_person_dob: str | None = None,
    responsible_person_id_number: str | None = None,
    responsible_person_id_image_asset_id: uuid.UUID | None = None,
) -> VerificationCase:
    result = await db.execute(
        select(VerificationCase).where(
            VerificationCase.case_id == case_id,
            VerificationCase.user_id == user_id,
        )
    )
    case = result.scalar_one_or_none()
    if not case:
        raise ValueError("Verification case not found")
    if case.row_version != row_version:
        raise ValueError("Conflict: case has been modified")
    if case.status not in (VerificationStatus.DRAFT.value, VerificationStatus.NEEDS_INFO.value):
        raise ValueError("Case can only be updated in DRAFT or NEEDS_INFO status")

    settings = get_settings()
    key = settings.get_encryption_key()

    from src.trailgoods.models.assets import Asset, AssetBlob

    _IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp"}

    async def _validate_verification_asset(asset_id: uuid.UUID) -> None:
        asset_result = await db.execute(select(Asset).where(Asset.id == asset_id))
        asset_obj = asset_result.scalar_one_or_none()
        if not asset_obj:
            raise ValueError(f"Asset {asset_id} not found")
        if asset_obj.owner_user_id != user_id:
            raise PermissionError(f"Not authorized to attach asset {asset_id}")
        if asset_obj.status != "ACTIVE":
            raise ValueError(f"Asset {asset_id} is not active")
        if asset_obj.purpose != "VERIFICATION":
            raise ValueError(f"Asset {asset_id} is not flagged for verification use")
        blob_result = await db.execute(select(AssetBlob).where(AssetBlob.id == asset_obj.blob_id))
        blob_obj = blob_result.scalar_one_or_none()
        if blob_obj and blob_obj.mime_type not in _IMAGE_MIMES:
            raise ValueError(
                f"Verification ID image must be an image file (jpeg/png/webp), "
                f"got {blob_obj.mime_type}"
            )

    if legal_name is not None:
        if not (1 <= len(legal_name) <= 200) or re.search(r'\d', legal_name):
            raise ValueError("legal_name must be 1-200 characters and contain no digits")
        case.legal_name_encrypted = encrypt_value(legal_name, key)
    if dob is not None:
        _validate_dob(dob)
        case.dob_encrypted = encrypt_value(dob, key)
    if government_id_number is not None:
        if not re.match(r'^[A-Za-z0-9]{5,20}$', government_id_number):
            raise ValueError("government_id_number must be alphanumeric and 5-20 characters")
        case.government_id_number_encrypted = encrypt_value(government_id_number, key)
    if government_id_image_asset_id is not None:
        await _validate_verification_asset(government_id_image_asset_id)
        case.government_id_image_asset_id = government_id_image_asset_id
    if enterprise_legal_name is not None:
        if not (1 <= len(enterprise_legal_name) <= 300):
            raise ValueError("enterprise_legal_name must be 1-300 characters")
        case.enterprise_legal_name_encrypted = encrypt_value(enterprise_legal_name, key)
    if enterprise_registration_number is not None:
        case.enterprise_registration_number_encrypted = encrypt_value(enterprise_registration_number, key)
    if enterprise_registration_asset_id is not None:
        await _validate_verification_asset(enterprise_registration_asset_id)
        case.enterprise_registration_asset_id = enterprise_registration_asset_id
    if responsible_person_legal_name is not None:
        if not (1 <= len(responsible_person_legal_name) <= 200) or re.search(r'\d', responsible_person_legal_name):
            raise ValueError("responsible_person_legal_name must be 1-200 characters and contain no digits")
        case.responsible_person_legal_name_encrypted = encrypt_value(responsible_person_legal_name, key)
    if responsible_person_dob is not None:
        _validate_dob(responsible_person_dob)
        case.responsible_person_dob_encrypted = encrypt_value(responsible_person_dob, key)
    if responsible_person_id_number is not None:
        case.responsible_person_id_number_encrypted = encrypt_value(responsible_person_id_number, key)
    if responsible_person_id_image_asset_id is not None:
        await _validate_verification_asset(responsible_person_id_image_asset_id)
        case.responsible_person_id_image_asset_id = responsible_person_id_image_asset_id

    case.row_version += 1
    await db.flush()

    snapshot = _build_snapshot(case)
    rev_count = await _get_revision_count(db, case.id)
    db.add(VerificationCaseRevision(
        case_id=case.id,
        revision_number=rev_count + 1,
        snapshot_json=json.dumps(snapshot),
    ))
    await db.flush()
    return case


async def submit_verification_case(
    db: AsyncSession,
    *,
    case_id: str,
    user_id: uuid.UUID,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> VerificationCase:
    result = await db.execute(
        select(VerificationCase).where(
            VerificationCase.case_id == case_id,
            VerificationCase.user_id == user_id,
        )
    )
    case = result.scalar_one_or_none()
    if not case:
        raise ValueError("Verification case not found")

    current = VerificationStatus(case.status)
    if VerificationStatus.SUBMITTED not in VALID_TRANSITIONS.get(current, set()):
        raise ValueError(f"Cannot transition from {case.status} to SUBMITTED")

    if case.profile_type == "PERSONAL":
        if not all([case.legal_name_encrypted, case.dob_encrypted,
                     case.government_id_number_encrypted, case.government_id_image_asset_id]):
            raise ValueError("Personal verification requires legal_name, dob, government_id_number, and government_id_image")
    elif case.profile_type == "ENTERPRISE":
        if not all([case.enterprise_legal_name_encrypted,
                     case.responsible_person_legal_name_encrypted,
                     case.responsible_person_dob_encrypted,
                     case.responsible_person_id_number_encrypted,
                     case.responsible_person_id_image_asset_id]):
            raise ValueError(
                "Enterprise verification requires enterprise_legal_name "
                "and responsible person details (legal_name, dob, id_number, id_image)"
            )

    from src.trailgoods.models.assets import Asset, AssetBlob

    async def _verify_asset_fingerprint(asset_id: uuid.UUID) -> str | None:
        asset_r = await db.execute(select(Asset).where(Asset.id == asset_id))
        asset_obj = asset_r.scalar_one_or_none()
        if not asset_obj:
            raise ValueError(f"Verification asset {asset_id} not found")
        if asset_obj.status != "ACTIVE":
            raise ValueError(f"Verification asset {asset_id} is not active")
        blob_r = await db.execute(select(AssetBlob).where(AssetBlob.id == asset_obj.blob_id))
        blob_obj = blob_r.scalar_one_or_none()
        if not blob_obj or not blob_obj.asset_hash:
            raise ValueError(f"Verification asset {asset_id} has no valid fingerprint")
        return blob_obj.asset_hash

    asset_ids = [
        a for a in [
            case.government_id_image_asset_id,
            case.enterprise_registration_asset_id,
            case.responsible_person_id_image_asset_id,
        ] if a is not None
    ]

    fingerprints = set()
    for aid in asset_ids:
        fp = await _verify_asset_fingerprint(aid)
        if fp in fingerprints:
            raise ValueError("Duplicate document fingerprint detected across verification assets")
        fingerprints.add(fp)

    settings = get_settings()
    key = settings.get_encryption_key()
    if case.dob_encrypted:
        dob_str = decrypt_value(case.dob_encrypted, key)[0]
        _validate_dob(dob_str)

    if case.profile_type == "ENTERPRISE" and case.responsible_person_dob_encrypted:
        rp_dob_str = decrypt_value(case.responsible_person_dob_encrypted, key)[0]
        _validate_dob(rp_dob_str)

    old_status = case.status
    case.status = VerificationStatus.SUBMITTED.value
    case.row_version += 1

    snapshot = _build_snapshot(case)
    rev_count = await _get_revision_count(db, case.id)
    db.add(VerificationCaseRevision(
        case_id=case.id,
        revision_number=rev_count + 1,
        snapshot_json=json.dumps(snapshot),
    ))

    db.add(VerificationCaseEvent(
        case_id=case.id,
        event_type="status_change",
        from_status=old_status,
        to_status=VerificationStatus.SUBMITTED.value,
        actor_user_id=user_id,
    ))

    await write_audit(
        db,
        action="verification.submit",
        resource_type="verification_case",
        resource_id=case.case_id,
        actor_user_id=user_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.flush()
    return case


async def decide_verification_case(
    db: AsyncSession,
    *,
    case_id: str,
    decision: str,
    reviewer_user_id: uuid.UUID,
    comment: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> VerificationCase:
    result = await db.execute(
        select(VerificationCase).where(VerificationCase.case_id == case_id)
    )
    case = result.scalar_one_or_none()
    if not case:
        raise ValueError("Verification case not found")

    current = VerificationStatus(case.status)
    target = VerificationStatus(decision)

    if target not in VALID_TRANSITIONS.get(current, set()):
        raise ValueError(f"Cannot transition from {case.status} to {decision}")

    old_status = case.status
    case.status = target.value
    now = datetime.now(timezone.utc)

    if target == VerificationStatus.APPROVED:
        case.approved_at = now
        case.expires_at = now + timedelta(days=365)
        from src.trailgoods.models.auth import User as UserModel
        user_obj_result = await db.execute(
            select(UserModel).where(UserModel.id == case.user_id)
        )
        user_obj = user_obj_result.scalar_one_or_none()
        if user_obj:
            if case.profile_type == "PERSONAL":
                user_obj.verified_personal_until = case.expires_at
            elif case.profile_type == "ENTERPRISE":
                user_obj.verified_enterprise_until = case.expires_at
    elif target == VerificationStatus.REJECTED:
        case.rejected_at = now
    elif target == VerificationStatus.UNDER_REVIEW:
        case.review_due_at = now + timedelta(hours=48)

    case.row_version += 1

    db.add(VerificationCaseEvent(
        case_id=case.id,
        event_type="decision",
        from_status=old_status,
        to_status=target.value,
        actor_user_id=reviewer_user_id,
        comment=comment,
    ))

    await write_audit(
        db,
        action=f"verification.{decision.lower()}",
        resource_type="verification_case",
        resource_id=case.case_id,
        actor_user_id=reviewer_user_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.flush()
    return case


async def withdraw_verification_case(
    db: AsyncSession,
    *,
    case_id: str,
    user_id: uuid.UUID,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> VerificationCase:
    result = await db.execute(
        select(VerificationCase).where(
            VerificationCase.case_id == case_id,
            VerificationCase.user_id == user_id,
        )
    )
    case = result.scalar_one_or_none()
    if not case:
        raise ValueError("Verification case not found")

    current = VerificationStatus(case.status)
    if VerificationStatus.WITHDRAWN not in VALID_TRANSITIONS.get(current, set()):
        raise ValueError(f"Cannot withdraw case in {case.status} status")

    old_status = case.status
    case.status = VerificationStatus.WITHDRAWN.value
    case.withdrawn_at = datetime.now(timezone.utc)
    case.row_version += 1

    db.add(VerificationCaseEvent(
        case_id=case.id,
        event_type="withdrawal",
        from_status=old_status,
        to_status=VerificationStatus.WITHDRAWN.value,
        actor_user_id=user_id,
    ))

    await write_audit(
        db,
        action="verification.withdraw",
        resource_type="verification_case",
        resource_id=case.case_id,
        actor_user_id=user_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.flush()
    return case


async def get_verification_case(
    db: AsyncSession,
    *,
    case_id: str,
    user_id: uuid.UUID | None = None,
    include_sensitive: bool = False,
) -> dict | None:
    q = select(VerificationCase).where(VerificationCase.case_id == case_id)
    if user_id is not None:
        q = q.where(VerificationCase.user_id == user_id)
    result = await db.execute(q)
    case = result.scalar_one_or_none()
    if not case:
        return None
    return _format_case(case, include_sensitive=include_sensitive)


async def get_verification_status(
    db: AsyncSession,
    *,
    case_id: str,
    user_id: uuid.UUID,
) -> dict | None:
    result = await db.execute(
        select(VerificationCase).where(
            VerificationCase.case_id == case_id,
            VerificationCase.user_id == user_id,
        )
    )
    case = result.scalar_one_or_none()
    if not case:
        return None
    return {
        "case_id": case.case_id,
        "profile_type": case.profile_type,
        "status": case.status,
        "expires_at": case.expires_at.isoformat() if case.expires_at else None,
    }


async def renew_verification_case(
    db: AsyncSession,
    *,
    case_id: str,
    user_id: uuid.UUID,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> VerificationCase:
    result = await db.execute(
        select(VerificationCase).where(
            VerificationCase.case_id == case_id,
            VerificationCase.user_id == user_id,
        )
    )
    case = result.scalar_one_or_none()
    if not case:
        raise ValueError("Verification case not found")
    if case.status != VerificationStatus.EXPIRED.value:
        raise ValueError("Only expired cases can be renewed")

    old_status = case.status
    case.status = VerificationStatus.SUBMITTED.value
    case.row_version += 1

    db.add(VerificationCaseEvent(
        case_id=case.id,
        event_type="renewal",
        from_status=old_status,
        to_status=VerificationStatus.SUBMITTED.value,
        actor_user_id=user_id,
    ))

    await write_audit(
        db,
        action="verification.renew",
        resource_type="verification_case",
        resource_id=case.case_id,
        actor_user_id=user_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.flush()
    return case


async def expire_verification_cases(db: AsyncSession) -> int:
    from src.trailgoods.models.auth import User as UserModel

    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(VerificationCase).where(
            VerificationCase.status == VerificationStatus.APPROVED.value,
            VerificationCase.expires_at <= now,
        )
    )
    cases = result.scalars().all()
    count = 0
    for case in cases:
        old_status = case.status
        case.status = VerificationStatus.EXPIRED.value
        db.add(VerificationCaseEvent(
            case_id=case.id,
            event_type="expiry",
            from_status=old_status,
            to_status=VerificationStatus.EXPIRED.value,
        ))
        user_obj_result = await db.execute(
            select(UserModel).where(UserModel.id == case.user_id)
        )
        user_obj = user_obj_result.scalar_one_or_none()
        if user_obj:
            if case.profile_type == "PERSONAL":
                user_obj.verified_personal_until = None
            elif case.profile_type == "ENTERPRISE":
                user_obj.verified_enterprise_until = None
        count += 1
    if count:
        await db.flush()
    return count


def _format_case(case: VerificationCase, include_sensitive: bool = False) -> dict:
    settings = get_settings()
    key = settings.get_encryption_key()

    data = {
        "id": str(case.id),
        "case_id": case.case_id,
        "user_id": str(case.user_id),
        "profile_type": case.profile_type,
        "status": case.status,
        "row_version": case.row_version,
        "created_at": case.created_at.isoformat() if case.created_at else None,
        "updated_at": case.updated_at.isoformat() if case.updated_at else None,
        "approved_at": case.approved_at.isoformat() if case.approved_at else None,
        "expires_at": case.expires_at.isoformat() if case.expires_at else None,
        "rejected_at": case.rejected_at.isoformat() if case.rejected_at else None,
    }

    encrypted_fields = [
        ("legal_name", case.legal_name_encrypted, mask_legal_name),
        ("dob", case.dob_encrypted, mask_dob),
        ("government_id_number", case.government_id_number_encrypted, mask_id_number),
        ("enterprise_legal_name", case.enterprise_legal_name_encrypted, mask_legal_name),
        ("enterprise_registration_number", case.enterprise_registration_number_encrypted, mask_id_number),
        ("responsible_person_legal_name", case.responsible_person_legal_name_encrypted, mask_legal_name),
        ("responsible_person_dob", case.responsible_person_dob_encrypted, mask_dob),
        ("responsible_person_id_number", case.responsible_person_id_number_encrypted, mask_id_number),
    ]

    for field_name, enc_value, mask_fn in encrypted_fields:
        if enc_value:
            plain = decrypt_value(enc_value, key)[0]
            data[field_name] = plain if include_sensitive else mask_fn(plain)

    data["government_id_image_asset_id"] = str(case.government_id_image_asset_id) if case.government_id_image_asset_id else None
    data["enterprise_registration_asset_id"] = str(case.enterprise_registration_asset_id) if case.enterprise_registration_asset_id else None
    data["responsible_person_id_image_asset_id"] = str(case.responsible_person_id_image_asset_id) if case.responsible_person_id_image_asset_id else None

    return data


def _build_snapshot(case: VerificationCase) -> dict:
    return {
        "status": case.status,
        "legal_name_encrypted": case.legal_name_encrypted,
        "dob_encrypted": case.dob_encrypted,
        "government_id_number_encrypted": case.government_id_number_encrypted,
        "government_id_image_asset_id": str(case.government_id_image_asset_id) if case.government_id_image_asset_id else None,
        "enterprise_legal_name_encrypted": case.enterprise_legal_name_encrypted,
        "enterprise_registration_number_encrypted": case.enterprise_registration_number_encrypted,
        "enterprise_registration_asset_id": str(case.enterprise_registration_asset_id) if case.enterprise_registration_asset_id else None,
        "responsible_person_legal_name_encrypted": case.responsible_person_legal_name_encrypted,
        "responsible_person_dob_encrypted": case.responsible_person_dob_encrypted,
        "responsible_person_id_number_encrypted": case.responsible_person_id_number_encrypted,
        "responsible_person_id_image_asset_id": str(case.responsible_person_id_image_asset_id) if case.responsible_person_id_image_asset_id else None,
        "row_version": case.row_version,
    }


async def _get_revision_count(db: AsyncSession, case_pk: uuid.UUID) -> int:
    from sqlalchemy import func
    result = await db.execute(
        select(func.count()).where(VerificationCaseRevision.case_id == case_pk)
    )
    return result.scalar() or 0
