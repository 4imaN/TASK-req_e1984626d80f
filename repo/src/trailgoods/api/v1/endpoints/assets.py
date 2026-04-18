import uuid
from typing import Annotated

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.trailgoods.api.deps import (
    get_role_snapshot,
    get_user_role_names,
    require_permission,
)
from src.trailgoods.core.database import get_db
from src.trailgoods.middleware.request_id import request_id_ctx
from src.trailgoods.services.audit import write_audit
from src.trailgoods.models.assets import Asset, AssetBlob, ShareLink
from src.trailgoods.models.auth import Session as SessionModel, User
from src.trailgoods.models.enums import AssetStatus, ShareLinkStatus
from src.trailgoods.schemas.envelope import ApiResponse, ResponseMeta
from src.trailgoods.services.assets import (
    batch_complete_uploads,
    complete_upload,
    consume_share_link_download,
    create_share_link,
    create_upload_session,
    delete_asset,
    get_asset,
    upload_part,
    validate_share_link,
)

router = APIRouter(prefix="/api/v1", tags=["assets"])


def _meta() -> ResponseMeta:
    return ResponseMeta(request_id=request_id_ctx.get(""))


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


class CreateUploadSessionRequest(BaseModel):
    filename: str
    mime_type: str
    total_size: int
    total_parts: int = 1
    kind: str
    purpose: str


class BatchCompleteRequest(BaseModel):
    upload_session_ids: list[uuid.UUID]


class CreateShareLinkRequest(BaseModel):
    password: str | None = None
    expires_in_days: int = 7
    max_downloads: int = 20


@router.post("/assets/uploads", status_code=201)
async def create_upload(
    body: CreateUploadSessionRequest,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("asset.create"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    try:
        session = await create_upload_session(
            db,
            user_id=user.id,
            filename=body.filename,
            mime_type=body.mime_type,
            total_size=body.total_size,
            total_parts=body.total_parts,
            kind=body.kind,
            purpose=body.purpose,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return ApiResponse(
        data={
            "upload_session_id": str(session.id),
            "status": session.status,
            "total_parts": session.total_parts,
        },
        meta=_meta(),
    )


@router.put("/assets/uploads/{upload_id}/parts/{part_no}")
async def upload_part_endpoint(
    upload_id: uuid.UUID,
    part_no: int,
    request: Request,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("asset.create"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    data = await request.body()
    user, _ = user_session
    is_admin = "Admin" in get_user_role_names(user)
    try:
        part = await upload_part(
            db,
            upload_session_id=upload_id,
            part_number=part_no,
            data=data,
            user_id=user.id,
            allow_admin=is_admin,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await write_audit(
        db,
        action="asset.upload_part",
        resource_type="upload_session",
        resource_id=str(upload_id),
        actor_user_id=user.id,
        actor_role_snapshot=get_role_snapshot(user),
        after_json=f'{{"part_number": {part.part_number}, "size_bytes": {part.size_bytes}}}',
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return ApiResponse(
        data={
            "part_number": part.part_number,
            "size_bytes": part.size_bytes,
        },
        meta=_meta(),
    )


class CompleteUploadRequest(BaseModel):
    watermark_policy: str = "NONE"


@router.post("/assets/uploads/{upload_id}/complete")
async def complete_upload_endpoint(
    upload_id: uuid.UUID,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("asset.create"))
    ],
    body: CompleteUploadRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    is_admin = "Admin" in get_user_role_names(user)
    watermark = (body.watermark_policy if body else "NONE")
    try:
        asset = await complete_upload(
            db,
            upload_session_id=upload_id,
            user_id=user.id,
            allow_admin=is_admin,
            watermark_policy=watermark,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        detail = str(e)
        if "already completed" in detail:
            raise HTTPException(status_code=409, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    return ApiResponse(
        data={
            "asset_id": str(asset.id),
            "filename": asset.filename,
            "status": asset.status,
            "asset_hash": asset.asset_hash,
        },
        meta=_meta(),
    )


@router.post("/assets/uploads/batch-complete")
async def batch_complete_endpoint(
    body: BatchCompleteRequest,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("asset.create"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[dict]]:
    user, _ = user_session
    is_admin = "Admin" in get_user_role_names(user)
    results = await batch_complete_uploads(
        db,
        upload_session_ids=body.upload_session_ids,
        user_id=user.id,
        allow_admin=is_admin,
    )
    await db.commit()
    return ApiResponse(data=results, meta=_meta())


@router.get("/assets/{asset_id}")
async def get_asset_endpoint(
    asset_id: uuid.UUID,
    request: Request,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("asset.read_own"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    asset = await get_asset(db, asset_id=asset_id)
    if not asset or asset.status == AssetStatus.SOFT_DELETED.value:
        raise HTTPException(status_code=404, detail="Asset not found")

    role_names = get_user_role_names(user)
    is_admin = "Admin" in role_names
    if asset.owner_user_id != user.id and not is_admin:
        raise HTTPException(status_code=403, detail="Access denied")

    blob_result = await db.execute(
        select(AssetBlob).where(AssetBlob.id == asset.blob_id)
    )
    blob = blob_result.scalar_one_or_none()

    await write_audit(
        db,
        action="asset.read",
        resource_type="asset",
        resource_id=str(asset_id),
        actor_user_id=user.id,
        actor_role_snapshot=get_role_snapshot(user),
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    return ApiResponse(
        data={
            "id": str(asset.id),
            "owner_user_id": str(asset.owner_user_id),
            "kind": asset.kind,
            "status": asset.status,
            "filename": asset.filename,
            "asset_hash": asset.asset_hash,
            "purpose": asset.purpose,
            "watermark_policy": asset.watermark_policy,
            "mime_type": blob.mime_type if blob else None,
            "size_bytes": blob.size_bytes if blob else None,
            "has_thumbnail": bool(blob and blob.thumbnail_path),
            "created_at": asset.created_at.isoformat() if asset.created_at else None,
            "deleted_at": asset.deleted_at.isoformat() if asset.deleted_at else None,
        },
        meta=_meta(),
    )


@router.delete("/assets/{asset_id}")
async def delete_asset_endpoint(
    asset_id: uuid.UUID,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("asset.delete_own"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    asset = await get_asset(db, asset_id=asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    role_names = get_user_role_names(user)
    is_admin = "Admin" in role_names
    if asset.owner_user_id != user.id and not is_admin:
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        await delete_asset(db, asset_id=asset_id, user_id=user.id)
    except ValueError as e:
        detail = str(e)
        if "already deleted" in detail:
            raise HTTPException(status_code=409, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    return ApiResponse(data={"message": "Asset deleted"}, meta=_meta())


@router.post("/assets/{asset_id}/share-links", status_code=201)
async def create_share_link_endpoint(
    asset_id: uuid.UUID,
    body: CreateShareLinkRequest,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("share_link.create"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    is_admin = "Admin" in get_user_role_names(user)
    try:
        link = await create_share_link(
            db,
            asset_id=asset_id,
            user_id=user.id,
            password=body.password,
            expires_in_days=body.expires_in_days,
            max_downloads=body.max_downloads,
            allow_admin=is_admin,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        detail = str(e)
        if "not found" in detail:
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    return ApiResponse(
        data={
            "id": str(link.id),
            "token": link.token,
            "expires_at": link.expires_at.isoformat(),
            "max_downloads": link.max_downloads,
            "status": link.status,
        },
        meta=_meta(),
    )


@router.delete("/share-links/{share_link_id}")
async def disable_share_link_endpoint(
    share_link_id: uuid.UUID,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("share_link.delete_own"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    result = await db.execute(
        select(ShareLink).where(ShareLink.id == share_link_id)
    )
    link = result.scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Share link not found")

    role_names = get_user_role_names(user)
    is_admin = "Admin" in role_names

    asset_result = await db.execute(
        select(Asset).where(Asset.id == link.asset_id)
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Associated asset not found")

    if asset.owner_user_id != user.id and not is_admin:
        raise HTTPException(status_code=403, detail="Access denied")

    if link.status == ShareLinkStatus.DISABLED.value:
        raise HTTPException(status_code=409, detail="Share link is already disabled")

    link.status = ShareLinkStatus.DISABLED.value
    from src.trailgoods.services.audit import write_audit
    await write_audit(
        db,
        action="share_link.disable",
        resource_type="share_link",
        resource_id=str(share_link_id),
        actor_user_id=user.id,
    )
    await db.commit()
    return ApiResponse(data={"message": "Share link disabled"}, meta=_meta())


@router.get("/share-links/{token}")
async def get_share_link_endpoint(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    password = request.headers.get("X-Share-Password")
    try:
        link, asset, blob = await validate_share_link(
            db,
            token=token,
            password=password,
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
            "share_link_id": str(link.id),
            "asset_id": str(asset.id),
            "filename": asset.filename,
            "mime_type": blob.mime_type,
            "size_bytes": blob.size_bytes,
            "download_count": link.download_count,
            "max_downloads": link.max_downloads,
            "expires_at": link.expires_at.isoformat(),
            "status": link.status,
            "download_url": f"/api/v1/share-links/{token}/download",
        },
        meta=_meta(),
    )


@router.get("/share-links/{token}/download")
async def download_share_link_endpoint(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    password = request.headers.get("X-Share-Password")
    try:
        link, asset, blob = await consume_share_link_download(
            db,
            token=token,
            password=password,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except ValueError as e:
        detail = str(e)
        if "not found" in detail:
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()

    file_path = Path(blob.storage_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Asset file not found on disk")

    def file_iterator():
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                yield chunk

    return StreamingResponse(
        file_iterator(),
        media_type=blob.mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{asset.filename}"',
            "Content-Length": str(blob.size_bytes),
        },
    )
