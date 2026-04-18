import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.trailgoods.api.deps import (
    get_current_user_and_session,
    get_user_role_names,
    require_permission,
)
from src.trailgoods.core.database import get_db
from src.trailgoods.middleware.request_id import request_id_ctx
from src.trailgoods.models.auth import Session as SessionModel, User
from src.trailgoods.schemas.envelope import ApiResponse, PaginationMeta, ResponseMeta
from src.trailgoods.services.catalog import (
    add_item_media,
    add_item_tag,
    create_category,
    create_item,
    create_item_attribute,
    create_price_book,
    create_price_book_entry,
    create_sku,
    create_spu,
    create_tag,
    delete_item_attribute,
    get_catalog_item_detail,
    list_catalog_items,
    list_categories,
    list_item_attributes,
    list_tags,
    publish_item,
    remove_item_tag,
    unpublish_item,
    update_item,
    update_sku,
)

router = APIRouter(prefix="/api/v1", tags=["catalog"])


def _meta() -> ResponseMeta:
    return ResponseMeta(request_id=request_id_ctx.get(""))


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


class CreateCategoryRequest(BaseModel):
    name: str
    slug: str
    parent_id: uuid.UUID | None = None


class CreateTagRequest(BaseModel):
    name: str
    slug: str


class CreateItemRequest(BaseModel):
    item_type: str
    title: str
    description: str
    category_id: uuid.UUID
    public_summary: str | None = None


class UpdateItemRequest(BaseModel):
    row_version: int
    title: str | None = None
    description: str | None = None
    public_summary: str | None = None
    category_id: uuid.UUID | None = None


class CreateSPURequest(BaseModel):
    item_id: uuid.UUID
    spu_code: str
    brand: str | None = None


class CreateSKURequest(BaseModel):
    sku_code: str


class UpdateSKURequest(BaseModel):
    status: str | None = None
    is_sellable: bool | None = None
    reorder_threshold: int | None = None


class AddItemMediaRequest(BaseModel):
    asset_id: uuid.UUID
    scope: str
    scope_ref_id: uuid.UUID | None = None
    sort_order: int = 0


class CreatePriceBookRequest(BaseModel):
    name: str
    is_default: bool = False


class CreatePriceBookEntryRequest(BaseModel):
    target_type: str
    target_id: uuid.UUID
    amount_cents: int
    compare_at_cents: int | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None


@router.get("/categories")
async def list_categories_endpoint(
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[dict]]:
    categories = await list_categories(db)
    return ApiResponse(
        data=[
            {
                "id": str(c.id),
                "name": c.name,
                "slug": c.slug,
                "parent_id": str(c.parent_id) if c.parent_id else None,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in categories
        ],
        meta=_meta(),
    )


@router.post("/categories", status_code=201)
async def create_category_endpoint(
    body: CreateCategoryRequest,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("catalog.item.manage_all"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    try:
        category = await create_category(
            db,
            name=body.name,
            slug=body.slug,
            parent_id=body.parent_id,
            actor_user_id=user.id,
        )
    except ValueError as e:
        detail = str(e)
        if "already exists" in detail:
            raise HTTPException(status_code=409, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    return ApiResponse(
        data={
            "id": str(category.id),
            "name": category.name,
            "slug": category.slug,
            "parent_id": str(category.parent_id) if category.parent_id else None,
            "created_at": category.created_at.isoformat() if category.created_at else None,
        },
        meta=_meta(),
    )


@router.get("/tags")
async def list_tags_endpoint(
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[dict]]:
    tags = await list_tags(db)
    return ApiResponse(
        data=[
            {
                "id": str(t.id),
                "name": t.name,
                "slug": t.slug,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in tags
        ],
        meta=_meta(),
    )


@router.post("/tags", status_code=201)
async def create_tag_endpoint(
    body: CreateTagRequest,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("catalog.item.manage_all"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    try:
        tag = await create_tag(db, name=body.name, slug=body.slug, actor_user_id=user.id)
    except ValueError as e:
        detail = str(e)
        if "already exists" in detail:
            raise HTTPException(status_code=409, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    return ApiResponse(
        data={
            "id": str(tag.id),
            "name": tag.name,
            "slug": tag.slug,
            "created_at": tag.created_at.isoformat() if tag.created_at else None,
        },
        meta=_meta(),
    )


@router.get("/catalog/items")
async def list_catalog_items_endpoint(
    db: AsyncSession = Depends(get_db),
    status: str | None = None,
    item_type: str | None = None,
    category_id: uuid.UUID | None = None,
    tag_slug: str | None = None,
    search: str | None = None,
    sort_by: str = "newest",
    limit: int = 20,
    offset: int = 0,
) -> ApiResponse[list[dict]]:
    limit = min(limit, 100)
    items, total = await list_catalog_items(
        db,
        status=status,
        item_type=item_type,
        category_id=category_id,
        tag_slug=tag_slug,
        search=search,
        sort_by=sort_by,
        limit=limit,
        offset=offset,
        public_only=True,
    )
    serialized = []
    for item in items:
        serialized.append({
            "id": str(item["id"]),
            "type": item["type"],
            "status": item["status"],
            "title": item["title"],
            "public_summary": item["public_summary"],
            "category_id": str(item["category_id"]) if item["category_id"] else None,
            "is_public": item["is_public"],
            "published_at": item["published_at"].isoformat() if item["published_at"] else None,
            "created_at": item["created_at"].isoformat() if item["created_at"] else None,
            "updated_at": item["updated_at"].isoformat() if item["updated_at"] else None,
            "price_cents": item["price_cents"],
        })
    return ApiResponse(
        data=serialized,
        meta=ResponseMeta(
            request_id=request_id_ctx.get(""),
            pagination=PaginationMeta(total=total, limit=limit, offset=offset),
        ),
    )


@router.post("/items", status_code=201)
async def create_item_endpoint(
    body: CreateItemRequest,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(get_current_user_and_session)
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    from src.trailgoods.api.deps import get_user_permissions
    user, _ = user_session
    role_names = get_user_role_names(user)
    perms = get_user_permissions(user)

    type_perm_map = {
        "SERVICE": "catalog.item.create_service",
        "PRODUCT": "catalog.item.create_product",
        "LIVE_PET": "catalog.item.create_live_pet",
    }
    required_perm = type_perm_map.get(body.item_type)
    if "Admin" not in role_names:
        if not required_perm or required_perm not in perms:
            raise HTTPException(status_code=403, detail="You do not have permission to create this item type")

    try:
        item = await create_item(
            db,
            owner_user_id=user.id,
            created_by_user_id=user.id,
            item_type=body.item_type,
            title=body.title,
            description=body.description,
            category_id=body.category_id,
            public_summary=body.public_summary,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return ApiResponse(
        data={
            "id": str(item.id),
            "type": item.type,
            "status": item.status,
            "title": item.title,
            "description": item.description,
            "public_summary": item.public_summary,
            "category_id": str(item.category_id) if item.category_id else None,
            "owner_user_id": str(item.owner_user_id),
            "is_public": item.is_public,
            "row_version": item.row_version,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        },
        meta=_meta(),
    )


@router.get("/items/{item_id}")
async def get_item_endpoint(
    item_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = None,
) -> ApiResponse[dict]:
    from fastapi import Header

    auth_header = request.headers.get("authorization")
    is_authenticated = False
    current_user: User | None = None

    if auth_header:
        try:
            from src.trailgoods.services.auth import authenticate_session
            scheme, _, token = auth_header.partition(" ")
            if scheme.lower() == "bearer" and token:
                current_user, _ = await authenticate_session(db, token)
                is_authenticated = True
        except Exception:
            pass

    is_admin = False
    if is_authenticated and current_user is not None:
        role_names = get_user_role_names(current_user)
        is_admin = "Admin" in role_names

    if is_admin:
        detail = await get_catalog_item_detail(db, item_id=item_id, public_only=False)
        if detail is None:
            raise HTTPException(status_code=404, detail="Item not found")
    else:
        detail = await get_catalog_item_detail(db, item_id=item_id, public_only=True)
        if detail is None:
            raw = await get_catalog_item_detail(db, item_id=item_id, public_only=False)
            if raw is not None and is_authenticated and current_user is not None:
                owner_id = raw.get("owner_user_id")
                if owner_id and str(owner_id) == str(current_user.id):
                    detail = raw
                else:
                    raise HTTPException(status_code=404, detail="Item not found")
            elif raw is not None and not is_authenticated:
                raise HTTPException(status_code=401, detail="Authentication required to view non-public items")
            else:
                raise HTTPException(status_code=404, detail="Item not found")

    def _serialize_detail(d: dict) -> dict:
        def _s(v):
            if isinstance(v, uuid.UUID):
                return str(v)
            if hasattr(v, "isoformat"):
                return v.isoformat()
            if isinstance(v, dict):
                return {k: _s(val) for k, val in v.items()}
            if isinstance(v, list):
                return [_s(i) for i in v]
            return v
        return {k: _s(v) for k, v in d.items()}

    return ApiResponse(data=_serialize_detail(detail), meta=_meta())


@router.patch("/items/{item_id}")
async def update_item_endpoint(
    item_id: uuid.UUID,
    body: UpdateItemRequest,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("catalog.item.update_own"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    role_names = get_user_role_names(user)
    is_admin = "Admin" in role_names

    from sqlalchemy import select
    from src.trailgoods.models.catalog import Item

    result = await db.execute(select(Item).where(Item.id == item_id))
    existing = result.scalar_one_or_none()
    if not existing:
        raise HTTPException(status_code=404, detail="Item not found")

    if existing.owner_user_id != user.id and not is_admin:
        raise HTTPException(status_code=403, detail="Access denied")

    effective_user_id = existing.owner_user_id if is_admin else user.id

    try:
        item = await update_item(
            db,
            item_id=item_id,
            user_id=effective_user_id,
            row_version=body.row_version,
            title=body.title,
            description=body.description,
            public_summary=body.public_summary,
            category_id=body.category_id,
        )
    except ValueError as e:
        detail = str(e)
        if "mismatch" in detail:
            raise HTTPException(status_code=409, detail=detail)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    return ApiResponse(
        data={
            "id": str(item.id),
            "type": item.type,
            "status": item.status,
            "title": item.title,
            "description": item.description,
            "public_summary": item.public_summary,
            "category_id": str(item.category_id) if item.category_id else None,
            "is_public": item.is_public,
            "row_version": item.row_version,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        },
        meta=_meta(),
    )


@router.post("/items/{item_id}/publish")
async def publish_item_endpoint(
    item_id: uuid.UUID,
    request: Request,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("catalog.item.publish_own"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    role_names = get_user_role_names(user)
    is_admin = "Admin" in role_names

    from sqlalchemy import select
    from src.trailgoods.models.catalog import Item

    result = await db.execute(select(Item).where(Item.id == item_id))
    existing = result.scalar_one_or_none()
    if not existing:
        raise HTTPException(status_code=404, detail="Item not found")

    if existing.owner_user_id != user.id and not is_admin:
        raise HTTPException(status_code=403, detail="Access denied")

    effective_user_id = existing.owner_user_id if is_admin else user.id

    try:
        item = await publish_item(
            db,
            item_id=item_id,
            user_id=effective_user_id,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except ValueError as e:
        detail = str(e)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    return ApiResponse(
        data={
            "id": str(item.id),
            "status": item.status,
            "is_public": item.is_public,
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "row_version": item.row_version,
        },
        meta=_meta(),
    )


@router.post("/items/{item_id}/unpublish")
async def unpublish_item_endpoint(
    item_id: uuid.UUID,
    request: Request,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("catalog.item.publish_own"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    role_names = get_user_role_names(user)
    is_admin = "Admin" in role_names

    from sqlalchemy import select
    from src.trailgoods.models.catalog import Item

    result = await db.execute(select(Item).where(Item.id == item_id))
    existing = result.scalar_one_or_none()
    if not existing:
        raise HTTPException(status_code=404, detail="Item not found")

    if existing.owner_user_id != user.id and not is_admin:
        raise HTTPException(status_code=403, detail="Access denied")

    effective_user_id = existing.owner_user_id if is_admin else user.id

    try:
        item = await unpublish_item(
            db,
            item_id=item_id,
            user_id=effective_user_id,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except ValueError as e:
        detail = str(e)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    return ApiResponse(
        data={
            "id": str(item.id),
            "status": item.status,
            "is_public": item.is_public,
            "unpublished_at": item.unpublished_at.isoformat() if item.unpublished_at else None,
            "row_version": item.row_version,
        },
        meta=_meta(),
    )


@router.post("/spus", status_code=201)
async def create_spu_endpoint(
    body: CreateSPURequest,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("catalog.spu.create"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    role_names = get_user_role_names(user)
    is_admin = "Admin" in role_names

    from sqlalchemy import select
    from src.trailgoods.models.catalog import Item

    result = await db.execute(select(Item).where(Item.id == body.item_id))
    existing = result.scalar_one_or_none()
    if not existing:
        raise HTTPException(status_code=404, detail="Item not found")

    if existing.owner_user_id != user.id and not is_admin:
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        spu = await create_spu(
            db,
            item_id=body.item_id,
            spu_code=body.spu_code,
            brand=body.brand,
            actor_user_id=user.id,
        )
    except ValueError as e:
        detail = str(e)
        if "already exists" in detail:
            raise HTTPException(status_code=409, detail=detail)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    return ApiResponse(
        data={
            "id": str(spu.id),
            "item_id": str(spu.item_id),
            "spu_code": spu.spu_code,
            "brand": spu.brand,
            "created_at": spu.created_at.isoformat() if spu.created_at else None,
        },
        meta=_meta(),
    )


@router.post("/spus/{spu_id}/skus", status_code=201)
async def create_sku_endpoint(
    spu_id: uuid.UUID,
    body: CreateSKURequest,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("catalog.sku.create"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    role_names = get_user_role_names(user)
    is_admin = "Admin" in role_names

    from sqlalchemy import select
    from src.trailgoods.models.catalog import Item, SPU

    spu_result = await db.execute(select(SPU).where(SPU.id == spu_id))
    spu = spu_result.scalar_one_or_none()
    if not spu:
        raise HTTPException(status_code=404, detail="SPU not found")

    item_result = await db.execute(select(Item).where(Item.id == spu.item_id))
    item = item_result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    if item.owner_user_id != user.id and not is_admin:
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        sku = await create_sku(db, spu_id=spu_id, sku_code=body.sku_code, actor_user_id=user.id)
    except ValueError as e:
        detail = str(e)
        if "already exists" in detail:
            raise HTTPException(status_code=409, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    return ApiResponse(
        data={
            "id": str(sku.id),
            "spu_id": str(sku.spu_id),
            "sku_code": sku.sku_code,
            "status": sku.status,
            "is_sellable": sku.is_sellable,
            "reorder_threshold": sku.reorder_threshold,
            "created_at": sku.created_at.isoformat() if sku.created_at else None,
        },
        meta=_meta(),
    )


@router.patch("/skus/{sku_id}")
async def update_sku_endpoint(
    sku_id: uuid.UUID,
    body: UpdateSKURequest,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("catalog.sku.update"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    is_admin = "Admin" in get_user_role_names(user)
    try:
        sku = await update_sku(
            db,
            sku_id=sku_id,
            status=body.status,
            is_sellable=body.is_sellable,
            reorder_threshold=body.reorder_threshold,
            actor_user_id=user.id,
            allow_admin=is_admin,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        detail = str(e)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    await db.refresh(sku)
    return ApiResponse(
        data={
            "id": str(sku.id),
            "spu_id": str(sku.spu_id),
            "sku_code": sku.sku_code,
            "status": sku.status,
            "is_sellable": sku.is_sellable,
            "reorder_threshold": sku.reorder_threshold,
            "updated_at": sku.updated_at.isoformat() if sku.updated_at else None,
        },
        meta=_meta(),
    )


@router.post("/items/{item_id}/media", status_code=201)
async def add_item_media_endpoint(
    item_id: uuid.UUID,
    body: AddItemMediaRequest,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("asset.create"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    role_names = get_user_role_names(user)
    is_admin = "Admin" in role_names

    from sqlalchemy import select
    from src.trailgoods.models.catalog import Item

    result = await db.execute(select(Item).where(Item.id == item_id))
    existing = result.scalar_one_or_none()
    if not existing:
        raise HTTPException(status_code=404, detail="Item not found")

    if existing.owner_user_id != user.id and not is_admin:
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        media = await add_item_media(
            db,
            item_id=item_id,
            asset_id=body.asset_id,
            user_id=user.id,
            scope=body.scope,
            scope_ref_id=body.scope_ref_id,
            sort_order=body.sort_order,
            allow_admin=is_admin,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        detail = str(e)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    return ApiResponse(
        data={
            "id": str(media.id),
            "item_id": str(media.item_id),
            "asset_id": str(media.asset_id),
            "scope": media.scope,
            "scope_ref_id": str(media.scope_ref_id) if media.scope_ref_id else None,
            "sort_order": media.sort_order,
            "created_at": media.created_at.isoformat() if media.created_at else None,
        },
        meta=_meta(),
    )


@router.post("/price-books", status_code=201)
async def create_price_book_endpoint(
    body: CreatePriceBookRequest,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("catalog.price.create"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    try:
        price_book = await create_price_book(
            db,
            name=body.name,
            is_default=body.is_default,
            actor_user_id=user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return ApiResponse(
        data={
            "id": str(price_book.id),
            "name": price_book.name,
            "is_default": price_book.is_default,
            "status": price_book.status,
            "created_at": price_book.created_at.isoformat() if price_book.created_at else None,
        },
        meta=_meta(),
    )


@router.post("/price-books/{price_book_id}/entries", status_code=201)
async def create_price_book_entry_endpoint(
    price_book_id: uuid.UUID,
    body: CreatePriceBookEntryRequest,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("catalog.price.create"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    is_admin = "Admin" in get_user_role_names(user)
    try:
        entry = await create_price_book_entry(
            db,
            price_book_id=price_book_id,
            target_type=body.target_type,
            target_id=body.target_id,
            amount_cents=body.amount_cents,
            compare_at_cents=body.compare_at_cents,
            starts_at=body.starts_at,
            ends_at=body.ends_at,
            actor_user_id=user.id,
            allow_admin=is_admin,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        detail = str(e)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail)
        if "overlap" in detail.lower() or "already exists" in detail.lower():
            raise HTTPException(status_code=409, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    return ApiResponse(
        data={
            "id": str(entry.id),
            "price_book_id": str(entry.price_book_id),
            "target_type": entry.target_type,
            "target_id": str(entry.target_id),
            "amount_cents": entry.amount_cents,
            "compare_at_cents": entry.compare_at_cents,
            "starts_at": entry.starts_at.isoformat() if entry.starts_at else None,
            "ends_at": entry.ends_at.isoformat() if entry.ends_at else None,
            "created_at": entry.created_at.isoformat() if entry.created_at else None,
        },
        meta=_meta(),
    )


@router.post("/items/{item_id}/tags/{tag_id}", status_code=201)
async def add_item_tag_endpoint(
    item_id: uuid.UUID,
    tag_id: uuid.UUID,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("catalog.item.update_own"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    is_admin = "Admin" in get_user_role_names(user)
    try:
        item_tag = await add_item_tag(
            db,
            item_id=item_id,
            tag_id=tag_id,
            user_id=user.id,
            allow_admin=is_admin,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        detail = str(e)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail)
        if "already" in detail.lower():
            raise HTTPException(status_code=409, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    return ApiResponse(
        data={
            "id": str(item_tag.id),
            "item_id": str(item_tag.item_id),
            "tag_id": str(item_tag.tag_id),
        },
        meta=_meta(),
    )


@router.delete("/items/{item_id}/tags/{tag_id}")
async def remove_item_tag_endpoint(
    item_id: uuid.UUID,
    tag_id: uuid.UUID,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("catalog.item.update_own"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    is_admin = "Admin" in get_user_role_names(user)
    try:
        await remove_item_tag(
            db,
            item_id=item_id,
            tag_id=tag_id,
            user_id=user.id,
            allow_admin=is_admin,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        detail = str(e)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    return ApiResponse(
        data={"message": "Tag removed from item"},
        meta=_meta(),
    )


class CreateItemAttributeRequest(BaseModel):
    scope: str
    scope_ref_id: uuid.UUID | None = None
    key: str
    value_text: str | None = None
    value_number: float | None = None
    value_json: str | None = None


@router.post("/items/{item_id}/attributes", status_code=201)
async def create_item_attribute_endpoint(
    item_id: uuid.UUID,
    body: CreateItemAttributeRequest,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("catalog.item.update_own"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    is_admin = "Admin" in get_user_role_names(user)
    try:
        attr = await create_item_attribute(
            db, item_id=item_id, scope=body.scope, scope_ref_id=body.scope_ref_id,
            key=body.key, value_text=body.value_text, value_number=body.value_number,
            value_json=body.value_json, user_id=user.id, allow_admin=is_admin,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        detail = str(e)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    return ApiResponse(
        data={
            "id": str(attr.id), "item_id": str(attr.item_id), "scope": attr.scope,
            "scope_ref_id": str(attr.scope_ref_id) if attr.scope_ref_id else None,
            "key": attr.key, "value_text": attr.value_text,
            "value_number": attr.value_number, "value_json": attr.value_json,
        },
        meta=_meta(),
    )


@router.get("/items/{item_id}/attributes")
async def list_item_attributes_endpoint(
    item_id: uuid.UUID,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("catalog.item.read"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[dict]]:
    user, _ = user_session
    is_admin = "Admin" in get_user_role_names(user)

    from sqlalchemy import select
    from src.trailgoods.models.catalog import Item
    item_r = await db.execute(select(Item).where(Item.id == item_id))
    item_obj = item_r.scalar_one_or_none()
    if not item_obj:
        raise HTTPException(status_code=404, detail="Item not found")
    if not is_admin and item_obj.owner_user_id != user.id:
        if item_obj.status != "PUBLISHED" or not item_obj.is_public:
            raise HTTPException(status_code=404, detail="Item not found")

    attrs = await list_item_attributes(db, item_id=item_id)
    return ApiResponse(data=attrs, meta=_meta())


@router.delete("/items/{item_id}/attributes/{attribute_id}")
async def delete_item_attribute_endpoint(
    item_id: uuid.UUID,
    attribute_id: uuid.UUID,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("catalog.item.update_own"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    is_admin = "Admin" in get_user_role_names(user)
    try:
        await delete_item_attribute(
            db, attribute_id=attribute_id, user_id=user.id, allow_admin=is_admin,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    await db.commit()
    return ApiResponse(data={"message": "Attribute deleted"}, meta=_meta())
