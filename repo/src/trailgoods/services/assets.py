import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.trailgoods.core.config import get_settings
from src.trailgoods.models.assets import (
    Asset,
    AssetBlob,
    ShareLink,
    ShareLinkAccessLog,
    UploadPart,
    UploadSession,
)
from src.trailgoods.models.enums import (
    AssetPurpose,
    AssetStatus,
    ShareLinkStatus,
    UploadSessionStatus,
)
from src.trailgoods.services.audit import write_audit
from src.trailgoods.services.auth import hash_password, verify_password

_MIME_LIMITS: dict[str, int] = {
    "image/jpeg": 10 * 1024 * 1024,
    "image/png": 10 * 1024 * 1024,
    "image/webp": 10 * 1024 * 1024,
    "video/mp4": 500 * 1024 * 1024,
    "video/webm": 500 * 1024 * 1024,
    "application/pdf": 50 * 1024 * 1024,
    "text/plain": 50 * 1024 * 1024,
    "text/csv": 50 * 1024 * 1024,
}


def _validate_mime(mime_type: str, total_size: int) -> None:
    if mime_type not in _MIME_LIMITS:
        raise ValueError(f"MIME type '{mime_type}' is not allowed")
    limit = _MIME_LIMITS[mime_type]
    if total_size > limit:
        raise ValueError(
            f"File size {total_size} bytes exceeds the {limit} byte limit for {mime_type}"
        )


async def create_upload_session(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    filename: str,
    mime_type: str,
    total_size: int,
    total_parts: int,
    kind: str,
    purpose: str,
) -> UploadSession:
    _validate_mime(mime_type, total_size)

    valid_kinds = {"IMAGE", "VIDEO", "ATTACHMENT", "VERIFICATION_ID", "THUMBNAIL"}
    if kind not in valid_kinds:
        raise ValueError(f"kind must be one of {sorted(valid_kinds)}")
    valid_purposes = {"CATALOG", "VERIFICATION", "REVIEW_ATTACHMENT", "GENERAL"}
    if purpose not in valid_purposes:
        raise ValueError(f"purpose must be one of {sorted(valid_purposes)}")

    _KIND_MIME_CONSTRAINTS = {
        "IMAGE": {"image/jpeg", "image/png", "image/webp"},
        "VIDEO": {"video/mp4", "video/webm"},
        "VERIFICATION_ID": {"image/jpeg", "image/png", "image/webp"},
    }
    allowed_mimes = _KIND_MIME_CONSTRAINTS.get(kind)
    if allowed_mimes and mime_type not in allowed_mimes:
        raise ValueError(
            f"kind '{kind}' requires MIME type in {sorted(allowed_mimes)}, got '{mime_type}'"
        )

    if total_parts < 1:
        raise ValueError("total_parts must be at least 1")
    if total_size <= 0:
        raise ValueError("total_size must be positive")
    if not filename or len(filename) > 255:
        raise ValueError("filename must be 1-255 characters")

    settings = get_settings()
    storage_root = Path(settings.ASSET_STORAGE_ROOT)
    session_id = uuid.uuid4()
    temp_dir = storage_root / "tmp" / str(session_id)
    temp_dir.mkdir(parents=True, exist_ok=True)

    session = UploadSession(
        id=session_id,
        user_id=user_id,
        filename=filename,
        mime_type=mime_type,
        total_size=total_size,
        total_parts=total_parts,
        kind=kind,
        purpose=purpose,
        status=UploadSessionStatus.INITIATED.value,
        received_parts=0,
        received_bytes=0,
        storage_temp_dir=str(temp_dir),
    )
    db.add(session)
    await db.flush()

    await write_audit(
        db,
        action="asset.upload_session_created",
        resource_type="upload_session",
        resource_id=str(session.id),
        actor_user_id=user_id,
    )
    return session


async def upload_part(
    db: AsyncSession,
    *,
    upload_session_id: uuid.UUID,
    part_number: int,
    data: bytes,
    user_id: uuid.UUID | None = None,
    allow_admin: bool = False,
) -> UploadPart:
    result = await db.execute(
        select(UploadSession).where(UploadSession.id == upload_session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise ValueError("Upload session not found")
    if user_id is not None and not allow_admin and session.user_id != user_id:
        raise PermissionError("Not authorized to upload to this session")
    if session.status not in (
        UploadSessionStatus.INITIATED.value,
        UploadSessionStatus.IN_PROGRESS.value,
    ):
        raise ValueError(f"Upload session is not in an active state: {session.status}")

    if part_number < 1 or part_number > session.total_parts:
        raise ValueError(f"part_number must be between 1 and {session.total_parts}")

    dup_check = await db.execute(
        select(UploadPart).where(
            UploadPart.upload_session_id == upload_session_id,
            UploadPart.part_number == part_number,
        )
    )
    if dup_check.scalar_one_or_none():
        raise ValueError(f"Part {part_number} has already been uploaded")

    new_total = session.received_bytes + len(data)
    mime_limit = _MIME_LIMITS.get(session.mime_type)
    if mime_limit and new_total > mime_limit:
        raise ValueError(
            f"Upload would exceed size limit for {session.mime_type}: "
            f"{new_total} bytes > {mime_limit} bytes"
        )

    temp_dir = Path(session.storage_temp_dir)
    part_path = temp_dir / f"part_{part_number:05d}"
    part_path.write_bytes(data)

    part = UploadPart(
        upload_session_id=upload_session_id,
        part_number=part_number,
        size_bytes=len(data),
        storage_path=str(part_path),
    )
    db.add(part)

    session.received_parts += 1
    session.received_bytes += len(data)
    session.status = UploadSessionStatus.IN_PROGRESS.value
    await db.flush()
    return part


async def complete_upload(
    db: AsyncSession,
    *,
    upload_session_id: uuid.UUID,
    user_id: uuid.UUID,
    allow_admin: bool = False,
    watermark_policy: str = "NONE",
) -> Asset:
    result = await db.execute(
        select(UploadSession).where(UploadSession.id == upload_session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise ValueError("Upload session not found")
    if not allow_admin and session.user_id != user_id:
        raise PermissionError("Not authorized to complete this upload session")
    if session.status == UploadSessionStatus.COMPLETED.value:
        raise ValueError("Upload session is already completed")
    if session.status not in (
        UploadSessionStatus.INITIATED.value,
        UploadSessionStatus.IN_PROGRESS.value,
    ):
        raise ValueError(f"Upload session cannot be completed from state: {session.status}")

    parts_result = await db.execute(
        select(UploadPart)
        .where(UploadPart.upload_session_id == upload_session_id)
        .order_by(UploadPart.part_number)
    )
    parts = list(parts_result.scalars().all())

    if len(parts) != session.total_parts:
        raise ValueError(
            f"Expected {session.total_parts} parts, received {len(parts)}"
        )

    settings = get_settings()
    storage_root = Path(settings.ASSET_STORAGE_ROOT)
    blobs_dir = storage_root / "blobs"
    blobs_dir.mkdir(parents=True, exist_ok=True)

    hasher = hashlib.sha256()
    assembled_size = 0
    assembled_chunks: list[bytes] = []
    for part in parts:
        chunk = Path(part.storage_path).read_bytes()
        hasher.update(chunk)
        assembled_size += len(chunk)
        assembled_chunks.append(chunk)

    asset_hash = hasher.hexdigest()

    _MIME_SIGNATURES = {
        "image/jpeg": [b"\xff\xd8\xff"],
        "image/png": [b"\x89PNG"],
        "image/webp": [b"RIFF"],
        "video/mp4": [b"\x00\x00\x00", b"ftyp"],
        "application/pdf": [b"%PDF"],
    }
    sigs = _MIME_SIGNATURES.get(session.mime_type)
    if sigs and assembled_chunks:
        header = assembled_chunks[0][:16]
        if not any(sig in header for sig in sigs):
            raise ValueError(
                f"Content signature mismatch: file does not match declared MIME type {session.mime_type}"
            )

    mime_limit = _MIME_LIMITS.get(session.mime_type)
    if mime_limit and assembled_size > mime_limit:
        raise ValueError(
            f"Assembled file exceeds size limit for {session.mime_type}: "
            f"{assembled_size} bytes > {mime_limit} bytes"
        )

    existing_blob_result = await db.execute(
        select(AssetBlob).where(AssetBlob.asset_hash == asset_hash)
    )
    existing_blob = existing_blob_result.scalar_one_or_none()

    if existing_blob is None:
        blob_path = blobs_dir / asset_hash[:2] / asset_hash[2:4] / asset_hash
        blob_path.parent.mkdir(parents=True, exist_ok=True)
        blob_path.write_bytes(b"".join(assembled_chunks))

        import json as _json
        metadata = {
            "filename": session.filename,
            "mime_type": session.mime_type,
            "size_bytes": assembled_size,
            "total_parts": session.total_parts,
            "sha256": asset_hash,
        }
        if session.mime_type in _THUMBNAIL_IMAGE_MIME_TYPES:
            try:
                from PIL import Image as _Img
                with _Img.open(blob_path) as img:
                    metadata["width"] = img.width
                    metadata["height"] = img.height
                    metadata["format"] = img.format
            except Exception:
                pass

        blob = AssetBlob(
            asset_hash=asset_hash,
            storage_path=str(blob_path),
            size_bytes=assembled_size,
            mime_type=session.mime_type,
            is_encrypted=False,
            metadata_json=_json.dumps(metadata),
        )
        db.add(blob)
        await db.flush()
    else:
        blob = existing_blob

    effective_watermark = watermark_policy if watermark_policy in ("NONE", "OPTIONAL", "REQUIRED") else "NONE"
    asset_owner = session.user_id
    asset = Asset(
        owner_user_id=asset_owner,
        blob_id=blob.id,
        kind=session.kind,
        status=AssetStatus.ACTIVE.value,
        filename=session.filename,
        asset_hash=asset_hash,
        watermark_policy=effective_watermark,
        purpose=session.purpose,
    )
    db.add(asset)

    session.status = UploadSessionStatus.COMPLETED.value
    session.completed_at = datetime.now(timezone.utc)
    await db.flush()

    if blob.mime_type in _THUMBNAIL_IMAGE_MIME_TYPES and blob.thumbnail_path is None:
        try:
            await generate_thumbnail_for_blob(
                db, blob, watermark=effective_watermark in ("REQUIRED", "OPTIONAL"),
            )
        except Exception:
            pass

    temp_dir = Path(session.storage_temp_dir)
    for part in parts:
        try:
            Path(part.storage_path).unlink(missing_ok=True)
        except OSError:
            pass
    try:
        temp_dir.rmdir()
    except OSError:
        pass

    await write_audit(
        db,
        action="asset.upload_complete",
        resource_type="asset",
        resource_id=str(asset.id),
        actor_user_id=user_id,
        after_json=f'{{"asset_hash": "{asset_hash}", "size_bytes": {assembled_size}}}',
    )
    return asset


async def batch_complete_uploads(
    db: AsyncSession,
    *,
    upload_session_ids: list[uuid.UUID],
    user_id: uuid.UUID,
    allow_admin: bool = False,
) -> list[dict]:
    results: list[dict] = []
    for session_id in upload_session_ids:
        try:
            asset = await complete_upload(
                db, upload_session_id=session_id, user_id=user_id, allow_admin=allow_admin,
            )
            results.append(
                {
                    "upload_session_id": str(session_id),
                    "success": True,
                    "asset_id": str(asset.id),
                    "error": None,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "upload_session_id": str(session_id),
                    "success": False,
                    "asset_id": None,
                    "error": str(exc),
                }
            )
    return results


async def create_share_link(
    db: AsyncSession,
    *,
    asset_id: uuid.UUID,
    user_id: uuid.UUID,
    password: str | None = None,
    expires_in_days: int = 7,
    max_downloads: int = 20,
    allow_admin: bool = False,
) -> ShareLink:
    if expires_in_days < 1:
        raise ValueError("expires_in_days must be at least 1")
    if max_downloads < 1:
        raise ValueError("max_downloads must be at least 1")
    asset_result = await db.execute(select(Asset).where(Asset.id == asset_id))
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise ValueError("Asset not found")
    if not allow_admin and asset.owner_user_id != user_id:
        raise PermissionError("Not authorized to create share link for this asset")
    if asset.status != AssetStatus.ACTIVE.value:
        raise ValueError("Asset is not active")
    if asset.purpose == AssetPurpose.VERIFICATION.value:
        raise ValueError("Verification assets cannot be shared publicly")

    password_hash: str | None = None
    if password is not None:
        if len(password) < 8:
            raise ValueError("Share link password must be at least 8 characters")
        password_hash = hash_password(password)

    token = secrets.token_urlsafe(64)
    expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)

    link = ShareLink(
        asset_id=asset_id,
        token=token,
        password_hash=password_hash,
        expires_at=expires_at,
        max_downloads=max_downloads,
        download_count=0,
        status=ShareLinkStatus.ACTIVE.value,
        created_by_user_id=user_id,
    )
    db.add(link)
    await db.flush()

    await write_audit(
        db,
        action="asset.share_link_created",
        resource_type="share_link",
        resource_id=str(link.id),
        actor_user_id=user_id,
        after_json=f'{{"asset_id": "{asset_id}", "expires_at": "{expires_at.isoformat()}"}}',
    )
    return link


async def _resolve_share_link(
    db: AsyncSession,
    *,
    token: str,
    password: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[ShareLink, Asset, AssetBlob]:
    link_result = await db.execute(
        select(ShareLink).where(ShareLink.token == token)
    )
    link = link_result.scalar_one_or_none()

    async def _log_failure(reason: str) -> None:
        if link:
            log = ShareLinkAccessLog(
                share_link_id=link.id,
                ip_address=ip_address,
                user_agent=user_agent,
                success=False,
                failure_reason=reason,
            )
            db.add(log)
            await db.flush()

    if not link:
        raise ValueError("Share link not found")

    now = datetime.now(timezone.utc)

    if link.status == ShareLinkStatus.EXPIRED.value or link.expires_at < now:
        if link.status != ShareLinkStatus.EXPIRED.value:
            link.status = ShareLinkStatus.EXPIRED.value
            await db.flush()
        await _log_failure("expired")
        raise ValueError("Share link has expired")

    if link.status == ShareLinkStatus.EXHAUSTED.value:
        await _log_failure("exhausted")
        raise ValueError("Share link has reached its download limit")

    if link.status == ShareLinkStatus.DISABLED.value:
        await _log_failure("disabled")
        raise ValueError("Share link is disabled")

    if link.status != ShareLinkStatus.ACTIVE.value:
        await _log_failure("inactive")
        raise ValueError("Share link is not active")

    if link.password_hash is not None:
        if password is None or not verify_password(link.password_hash, password):
            await _log_failure("invalid_password")
            raise ValueError("Invalid share link password")

    asset_result = await db.execute(select(Asset).where(Asset.id == link.asset_id))
    asset = asset_result.scalar_one_or_none()
    if not asset or asset.status != AssetStatus.ACTIVE.value:
        await _log_failure("asset_unavailable")
        raise ValueError("Asset is not available")

    blob_result = await db.execute(select(AssetBlob).where(AssetBlob.id == asset.blob_id))
    blob = blob_result.scalar_one_or_none()
    if not blob:
        await _log_failure("blob_missing")
        raise ValueError("Asset blob not found")

    return link, asset, blob


async def validate_share_link(
    db: AsyncSession,
    *,
    token: str,
    password: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[ShareLink, Asset, AssetBlob]:
    return await _resolve_share_link(
        db, token=token, password=password,
        ip_address=ip_address, user_agent=user_agent,
    )


async def consume_share_link_download(
    db: AsyncSession,
    *,
    token: str,
    password: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[ShareLink, Asset, AssetBlob]:
    link, asset, blob = await _resolve_share_link(
        db, token=token, password=password,
        ip_address=ip_address, user_agent=user_agent,
    )

    link.download_count += 1
    if link.download_count >= link.max_downloads:
        link.status = ShareLinkStatus.EXHAUSTED.value

    log = ShareLinkAccessLog(
        share_link_id=link.id,
        ip_address=ip_address,
        user_agent=user_agent,
        success=True,
        failure_reason=None,
    )
    db.add(log)
    await db.flush()
    return link, asset, blob


async def get_asset(
    db: AsyncSession,
    *,
    asset_id: uuid.UUID,
) -> Asset | None:
    result = await db.execute(select(Asset).where(Asset.id == asset_id))
    return result.scalar_one_or_none()


async def delete_asset(
    db: AsyncSession,
    *,
    asset_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    result = await db.execute(select(Asset).where(Asset.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise ValueError("Asset not found")
    if asset.status == AssetStatus.SOFT_DELETED.value:
        raise ValueError("Asset is already deleted")

    from src.trailgoods.models.verification import VerificationCase
    from src.trailgoods.models.catalog import ItemMedia
    from src.trailgoods.models.enums import ItemStatus

    vc_check = await db.execute(
        select(VerificationCase).where(
            (VerificationCase.government_id_image_asset_id == asset_id)
            | (VerificationCase.enterprise_registration_asset_id == asset_id)
            | (VerificationCase.responsible_person_id_image_asset_id == asset_id),
            VerificationCase.status.notin_(["APPROVED", "REJECTED", "WITHDRAWN", "EXPIRED"]),
        ).limit(1)
    )
    if vc_check.scalar_one_or_none():
        raise ValueError("Cannot delete asset: it is referenced by active verification cases or published items")

    from src.trailgoods.models.catalog import Item
    im_check = await db.execute(
        select(ItemMedia).join(Item, Item.id == ItemMedia.item_id).where(
            ItemMedia.asset_id == asset_id,
            Item.status == ItemStatus.PUBLISHED.value,
        ).limit(1)
    )
    if im_check.scalar_one_or_none():
        raise ValueError("Cannot delete asset: it is referenced by active verification cases or published items")

    now = datetime.now(timezone.utc)
    asset.status = AssetStatus.SOFT_DELETED.value
    asset.deleted_at = now
    await db.flush()

    await write_audit(
        db,
        action="asset.delete",
        resource_type="asset",
        resource_id=str(asset_id),
        actor_user_id=user_id,
        before_json=f'{{"status": "ACTIVE"}}',
        after_json=f'{{"status": "SOFT_DELETED"}}',
    )


_THUMBNAIL_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
_THUMBNAIL_SIZE = (256, 256)


def _apply_watermark(img, text: str = "TRAILGOODS"):
    try:
        from PIL import ImageDraw
    except ImportError:
        return img
    draw = ImageDraw.Draw(img)
    w, h = img.size
    draw.text((max(10, w - 150), max(10, h - 30)), text, fill=(200, 200, 200, 160))
    return img


async def generate_thumbnail_for_blob(
    db: AsyncSession,
    blob: AssetBlob,
    *,
    watermark: bool = False,
) -> str | None:
    if blob.mime_type not in _THUMBNAIL_IMAGE_MIME_TYPES:
        return None
    if blob.thumbnail_path:
        return blob.thumbnail_path

    try:
        from PIL import Image
    except ImportError:
        return None

    settings = get_settings()
    preview_root = Path(settings.PREVIEW_STORAGE_ROOT)
    preview_root.mkdir(parents=True, exist_ok=True)

    source = Path(blob.storage_path)
    if not source.exists():
        return None

    target_dir = preview_root / blob.asset_hash[:2] / blob.asset_hash[2:4]
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{blob.asset_hash}_thumb.jpg"

    try:
        with Image.open(source) as img:
            img = img.convert("RGB")
            img.thumbnail(_THUMBNAIL_SIZE)
            if watermark:
                img = _apply_watermark(img)
            img.save(target_path, "JPEG", quality=85)
    except Exception:
        return None

    blob.thumbnail_path = str(target_path)
    await db.flush()
    return str(target_path)


async def generate_pending_thumbnails(db: AsyncSession, limit: int = 50) -> int:
    result = await db.execute(
        select(AssetBlob)
        .where(
            AssetBlob.thumbnail_path.is_(None),
            AssetBlob.mime_type.in_(list(_THUMBNAIL_IMAGE_MIME_TYPES)),
        )
        .limit(limit)
    )
    blobs = list(result.scalars().all())

    asset_lookup = {}
    if blobs:
        blob_ids = [b.id for b in blobs]
        assets_result = await db.execute(
            select(Asset).where(Asset.blob_id.in_(blob_ids))
        )
        for a in assets_result.scalars().all():
            asset_lookup.setdefault(a.blob_id, a)

    count = 0
    for blob in blobs:
        asset = asset_lookup.get(blob.id)
        watermark = bool(asset and asset.watermark_policy in ("REQUIRED", "OPTIONAL"))
        path = await generate_thumbnail_for_blob(db, blob, watermark=watermark)
        if path:
            count += 1
    return count
