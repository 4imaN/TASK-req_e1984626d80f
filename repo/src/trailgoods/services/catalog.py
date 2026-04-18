import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.trailgoods.models.assets import Asset
from src.trailgoods.models.catalog import (
    Category,
    Item,
    ItemAttribute,
    ItemMedia,
    ItemTag,
    PriceBook,
    PriceBookEntry,
    SKU,
    SPU,
    Tag,
)
from src.trailgoods.models.enums import (
    AssetKind,
    AssetStatus,
    ItemStatus,
    ItemType,
    PriceBookStatus,
    PriceTargetType,
    SKUStatus,
)
from src.trailgoods.services.audit import write_audit


async def create_category(
    db: AsyncSession,
    *,
    name: str,
    slug: str,
    parent_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> Category:
    existing = await db.execute(select(Category).where(Category.slug == slug))
    if existing.scalar_one_or_none():
        raise ValueError(f"Category slug '{slug}' already exists")

    if parent_id is not None:
        parent = await db.execute(select(Category).where(Category.id == parent_id))
        if not parent.scalar_one_or_none():
            raise ValueError("Parent category not found")

    category = Category(name=name, slug=slug, parent_id=parent_id)
    db.add(category)
    await db.flush()
    await write_audit(
        db,
        action="catalog.category.create",
        resource_type="category",
        resource_id=str(category.id),
        actor_user_id=actor_user_id,
    )
    return category


async def list_categories(db: AsyncSession) -> list[Category]:
    result = await db.execute(select(Category).order_by(Category.name))
    return list(result.scalars().all())


async def create_tag(
    db: AsyncSession,
    *,
    name: str,
    slug: str,
    actor_user_id: uuid.UUID | None = None,
) -> Tag:
    existing = await db.execute(select(Tag).where(Tag.slug == slug))
    if existing.scalar_one_or_none():
        raise ValueError(f"Tag slug '{slug}' already exists")

    tag = Tag(name=name, slug=slug)
    db.add(tag)
    await db.flush()
    await write_audit(
        db,
        action="catalog.tag.create",
        resource_type="tag",
        resource_id=str(tag.id),
        actor_user_id=actor_user_id,
    )
    return tag


async def list_tags(db: AsyncSession) -> list[Tag]:
    result = await db.execute(select(Tag).order_by(Tag.name))
    return list(result.scalars().all())


async def create_item(
    db: AsyncSession,
    *,
    owner_user_id: uuid.UUID,
    created_by_user_id: uuid.UUID,
    item_type: str,
    title: str,
    description: str,
    category_id: uuid.UUID,
    public_summary: str | None = None,
) -> Item:
    valid_types = {ItemType.PRODUCT.value, ItemType.SERVICE.value, ItemType.LIVE_PET.value}
    if item_type not in valid_types:
        raise ValueError(f"item_type must be one of {sorted(valid_types)}")

    if not title or len(title) > 200:
        raise ValueError("title must be between 1 and 200 characters")

    if description and len(description) > 20000:
        raise ValueError("description must not exceed 20000 characters")

    category = await db.execute(select(Category).where(Category.id == category_id))
    if not category.scalar_one_or_none():
        raise ValueError("Category not found")

    item = Item(
        owner_user_id=owner_user_id,
        created_by_user_id=created_by_user_id,
        type=item_type,
        title=title,
        description=description,
        public_summary=public_summary,
        category_id=category_id,
        status=ItemStatus.DRAFT.value,
        is_public=False,
        row_version=1,
    )
    db.add(item)
    await db.flush()
    await write_audit(
        db,
        action="catalog.item.create",
        resource_type="item",
        resource_id=str(item.id),
        actor_user_id=created_by_user_id,
    )
    return item


async def update_item(
    db: AsyncSession,
    *,
    item_id: uuid.UUID,
    user_id: uuid.UUID,
    row_version: int,
    title: str | None = None,
    description: str | None = None,
    public_summary: str | None = None,
    category_id: uuid.UUID | None = None,
) -> Item:
    result = await db.execute(select(Item).where(Item.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise ValueError("Item not found")

    if item.owner_user_id != user_id:
        raise ValueError("Not authorized to update this item")

    if item.row_version != row_version:
        raise ValueError("Row version mismatch; item has been modified by another request")

    if title is not None:
        if not title or len(title) > 200:
            raise ValueError("title must be between 1 and 200 characters")
        item.title = title

    if description is not None:
        if len(description) > 20000:
            raise ValueError("description must not exceed 20000 characters")
        item.description = description

    if public_summary is not None:
        item.public_summary = public_summary

    if category_id is not None:
        cat = await db.execute(select(Category).where(Category.id == category_id))
        if not cat.scalar_one_or_none():
            raise ValueError("Category not found")
        item.category_id = category_id

    item.row_version = item.row_version + 1
    item.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await write_audit(
        db,
        action="catalog.item.update",
        resource_type="item",
        resource_id=str(item_id),
        actor_user_id=user_id,
    )
    return item


async def add_item_tag(
    db: AsyncSession,
    *,
    item_id: uuid.UUID,
    tag_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    allow_admin: bool = False,
) -> ItemTag:
    item_result = await db.execute(select(Item).where(Item.id == item_id))
    item_obj = item_result.scalar_one_or_none()
    if not item_obj:
        raise ValueError("Item not found")

    if user_id is not None and not allow_admin and item_obj.owner_user_id != user_id:
        raise PermissionError("Not authorized to tag this item")

    tag = await db.execute(select(Tag).where(Tag.id == tag_id))
    if not tag.scalar_one_or_none():
        raise ValueError("Tag not found")

    existing = await db.execute(
        select(ItemTag).where(ItemTag.item_id == item_id, ItemTag.tag_id == tag_id)
    )
    if existing.scalar_one_or_none():
        raise ValueError("Tag already added to this item")

    item_tag = ItemTag(item_id=item_id, tag_id=tag_id)
    db.add(item_tag)
    await db.flush()
    await write_audit(
        db,
        action="catalog.item.tag_add",
        resource_type="item",
        resource_id=str(item_id),
        actor_user_id=user_id,
    )
    return item_tag


async def remove_item_tag(
    db: AsyncSession,
    *,
    item_id: uuid.UUID,
    tag_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    allow_admin: bool = False,
) -> None:
    item_result = await db.execute(select(Item).where(Item.id == item_id))
    item_obj = item_result.scalar_one_or_none()
    if not item_obj:
        raise ValueError("Item not found")

    if user_id is not None and not allow_admin and item_obj.owner_user_id != user_id:
        raise PermissionError("Not authorized to modify this item's tags")

    result = await db.execute(
        select(ItemTag).where(ItemTag.item_id == item_id, ItemTag.tag_id == tag_id)
    )
    existing = result.scalar_one_or_none()
    if not existing:
        raise ValueError("Item tag association not found")

    await db.delete(existing)
    await db.flush()
    await write_audit(
        db,
        action="catalog.item.tag_remove",
        resource_type="item",
        resource_id=str(item_id),
        actor_user_id=user_id,
    )


async def add_item_media(
    db: AsyncSession,
    *,
    item_id: uuid.UUID,
    asset_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    scope: str = "ITEM",
    scope_ref_id: uuid.UUID | None = None,
    sort_order: int = 0,
    allow_admin: bool = False,
) -> ItemMedia:
    item_result = await db.execute(select(Item).where(Item.id == item_id))
    item_obj = item_result.scalar_one_or_none()
    if not item_obj:
        raise ValueError("Item not found")

    asset_result = await db.execute(select(Asset).where(Asset.id == asset_id))
    asset_obj = asset_result.scalar_one_or_none()
    if not asset_obj:
        raise ValueError("Asset not found")
    if asset_obj.status != "ACTIVE":
        raise ValueError("Asset is not active")
    if asset_obj.purpose == "VERIFICATION":
        raise ValueError("Verification assets cannot be attached to catalog items")

    if user_id is not None and not allow_admin and asset_obj.owner_user_id != user_id:
        raise PermissionError("Not authorized to attach this asset")

    media = ItemMedia(
        item_id=item_id,
        asset_id=asset_id,
        scope=scope,
        scope_ref_id=scope_ref_id,
        sort_order=sort_order,
    )
    db.add(media)
    await db.flush()
    await write_audit(
        db, action="catalog.item.media_add", resource_type="item",
        resource_id=str(item_id), actor_user_id=user_id,
    )
    return media


async def create_spu(
    db: AsyncSession,
    *,
    item_id: uuid.UUID,
    spu_code: str,
    brand: str | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> SPU:
    result = await db.execute(select(Item).where(Item.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise ValueError("Item not found")

    allowed_spu_types = {ItemType.PRODUCT.value, ItemType.LIVE_PET.value}
    if item.type not in allowed_spu_types:
        raise ValueError("SPU can only be created for PRODUCT or LIVE_PET items")

    existing_spu = await db.execute(select(SPU).where(SPU.item_id == item_id))
    if existing_spu.scalar_one_or_none():
        raise ValueError("An SPU already exists for this item")

    existing_code = await db.execute(select(SPU).where(SPU.spu_code == spu_code))
    if existing_code.scalar_one_or_none():
        raise ValueError(f"SPU code '{spu_code}' already exists")

    spu = SPU(item_id=item_id, spu_code=spu_code, brand=brand)
    db.add(spu)
    await db.flush()
    await write_audit(
        db, action="catalog.spu.create", resource_type="spu", resource_id=str(spu.id),
        actor_user_id=actor_user_id,
    )
    return spu


async def create_sku(
    db: AsyncSession,
    *,
    spu_id: uuid.UUID,
    sku_code: str,
    actor_user_id: uuid.UUID | None = None,
) -> SKU:
    spu = await db.execute(select(SPU).where(SPU.id == spu_id))
    if not spu.scalar_one_or_none():
        raise ValueError("SPU not found")

    if not sku_code or len(sku_code) > 64:
        raise ValueError("sku_code must be between 1 and 64 characters")

    existing = await db.execute(
        select(SKU).where(SKU.spu_id == spu_id, SKU.sku_code == sku_code)
    )
    if existing.scalar_one_or_none():
        raise ValueError(f"SKU code '{sku_code}' already exists within this SPU")

    sku = SKU(
        spu_id=spu_id,
        sku_code=sku_code,
        status=SKUStatus.ACTIVE.value,
        is_sellable=True,
    )
    db.add(sku)
    await db.flush()
    await write_audit(
        db, action="catalog.sku.create", resource_type="sku", resource_id=str(sku.id),
        actor_user_id=actor_user_id,
    )
    return sku


async def update_sku(
    db: AsyncSession,
    *,
    sku_id: uuid.UUID,
    status: str | None = None,
    is_sellable: bool | None = None,
    reorder_threshold: int | None = None,
    actor_user_id: uuid.UUID | None = None,
    allow_admin: bool = False,
) -> SKU:
    result = await db.execute(
        select(SKU, SPU, Item)
        .join(SPU, SPU.id == SKU.spu_id)
        .join(Item, Item.id == SPU.item_id)
        .where(SKU.id == sku_id)
    )
    row = result.one_or_none()
    if not row:
        raise ValueError("SKU not found")
    sku, spu, item = row
    if actor_user_id and not allow_admin and item.owner_user_id != actor_user_id:
        raise PermissionError("Not authorized to update this SKU")

    valid_statuses = {s.value for s in SKUStatus}
    if status is not None:
        if status not in valid_statuses:
            raise ValueError(f"status must be one of {sorted(valid_statuses)}")
        sku.status = status

    if is_sellable is not None:
        sku.is_sellable = is_sellable

    if reorder_threshold is not None:
        if reorder_threshold < 0:
            raise ValueError("reorder_threshold must be non-negative")
        sku.reorder_threshold = reorder_threshold

    await db.flush()
    await write_audit(
        db, action="catalog.sku.update", resource_type="sku", resource_id=str(sku_id),
        actor_user_id=actor_user_id,
    )
    return sku


async def create_price_book(
    db: AsyncSession,
    *,
    name: str,
    is_default: bool = False,
    actor_user_id: uuid.UUID | None = None,
) -> PriceBook:
    if is_default:
        existing_default = await db.execute(
            select(PriceBook).where(
                PriceBook.is_default == True,
                PriceBook.status == PriceBookStatus.ACTIVE.value,
            )
        )
        if existing_default.scalar_one_or_none():
            raise ValueError("An active default price book already exists")
    price_book = PriceBook(
        name=name,
        is_default=is_default,
        status=PriceBookStatus.ACTIVE.value,
    )
    db.add(price_book)
    await db.flush()
    await write_audit(
        db, action="catalog.price_book.create", resource_type="price_book",
        resource_id=str(price_book.id), actor_user_id=actor_user_id,
    )
    return price_book


async def create_price_book_entry(
    db: AsyncSession,
    *,
    price_book_id: uuid.UUID,
    target_type: str,
    target_id: uuid.UUID,
    amount_cents: int,
    compare_at_cents: int | None = None,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    actor_user_id: uuid.UUID | None = None,
    allow_admin: bool = False,
) -> PriceBookEntry:
    pb = await db.execute(select(PriceBook).where(PriceBook.id == price_book_id))
    if not pb.scalar_one_or_none():
        raise ValueError("Price book not found")

    valid_target_types = {PriceTargetType.ITEM.value, PriceTargetType.SKU.value}
    if target_type not in valid_target_types:
        raise ValueError(f"target_type must be one of {sorted(valid_target_types)}")

    if target_type == PriceTargetType.ITEM.value:
        item_r = await db.execute(select(Item).where(Item.id == target_id))
        target_item = item_r.scalar_one_or_none()
        if not target_item:
            raise ValueError(f"Item {target_id} not found")
        if actor_user_id and not allow_admin and target_item.owner_user_id != actor_user_id:
            raise PermissionError("Not authorized to set pricing for this item")
    elif target_type == PriceTargetType.SKU.value:
        sku_r = await db.execute(
            select(SKU, SPU).join(SPU, SPU.id == SKU.spu_id).where(SKU.id == target_id)
        )
        row = sku_r.one_or_none()
        if not row:
            raise ValueError(f"SKU {target_id} not found")
        sku_obj, spu_obj = row
        item_r = await db.execute(select(Item).where(Item.id == spu_obj.item_id))
        target_item = item_r.scalar_one_or_none()
        if actor_user_id and not allow_admin and target_item and target_item.owner_user_id != actor_user_id:
            raise PermissionError("Not authorized to set pricing for this SKU")

    if amount_cents <= 0:
        raise ValueError("amount_cents must be greater than 0")

    if starts_at and ends_at and starts_at >= ends_at:
        raise ValueError("starts_at must be before ends_at")

    overlap_conditions = [
        PriceBookEntry.price_book_id == price_book_id,
        PriceBookEntry.target_type == target_type,
        PriceBookEntry.target_id == target_id,
    ]

    now = datetime.now(timezone.utc)

    existing_entries = await db.execute(
        select(PriceBookEntry).where(and_(*overlap_conditions))
    )
    for entry in existing_entries.scalars().all():
        entry_starts = entry.starts_at or datetime.min.replace(tzinfo=timezone.utc)
        entry_ends = entry.ends_at or datetime.max.replace(tzinfo=timezone.utc)
        new_starts = starts_at or datetime.min.replace(tzinfo=timezone.utc)
        new_ends = ends_at or datetime.max.replace(tzinfo=timezone.utc)

        if entry_starts < new_ends and entry_ends > new_starts:
            raise ValueError(
                "An overlapping price book entry already exists for this target and time range"
            )

    entry = PriceBookEntry(
        price_book_id=price_book_id,
        target_type=target_type,
        target_id=target_id,
        amount_cents=amount_cents,
        compare_at_cents=compare_at_cents,
        starts_at=starts_at,
        ends_at=ends_at,
    )
    db.add(entry)
    await db.flush()
    await write_audit(
        db, action="catalog.price.create", resource_type="price_book_entry",
        resource_id=str(entry.id),
        actor_user_id=actor_user_id,
    )
    return entry


async def _check_active_image_media(db: AsyncSession, item_id: uuid.UUID) -> bool:
    from src.trailgoods.models.assets import AssetBlob

    _IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp"}
    result = await db.execute(
        select(func.count(ItemMedia.id))
        .join(Asset, Asset.id == ItemMedia.asset_id)
        .join(AssetBlob, AssetBlob.id == Asset.blob_id)
        .where(
            ItemMedia.item_id == item_id,
            Asset.kind == AssetKind.IMAGE.value,
            Asset.status == AssetStatus.ACTIVE.value,
            AssetBlob.mime_type.in_(list(_IMAGE_MIMES)),
        )
    )
    count = result.scalar_one()
    return count > 0


async def _check_active_usd_price(db: AsyncSession, item_id: uuid.UUID) -> bool:
    now = datetime.now(timezone.utc)

    item_price = await db.execute(
        select(func.count(PriceBookEntry.id))
        .join(PriceBook, PriceBook.id == PriceBookEntry.price_book_id)
        .where(
            PriceBook.is_default == True,
            PriceBook.status == PriceBookStatus.ACTIVE.value,
            PriceBook.currency == "USD",
            PriceBookEntry.target_type == PriceTargetType.ITEM.value,
            PriceBookEntry.target_id == item_id,
            or_(PriceBookEntry.starts_at == None, PriceBookEntry.starts_at <= now),
            or_(PriceBookEntry.ends_at == None, PriceBookEntry.ends_at > now),
        )
    )
    if item_price.scalar_one() > 0:
        return True

    sku_ids_q = select(SKU.id).join(SPU, SPU.id == SKU.spu_id).where(SPU.item_id == item_id)
    sku_price = await db.execute(
        select(func.count(PriceBookEntry.id))
        .join(PriceBook, PriceBook.id == PriceBookEntry.price_book_id)
        .where(
            PriceBook.is_default == True,
            PriceBook.status == PriceBookStatus.ACTIVE.value,
            PriceBook.currency == "USD",
            PriceBookEntry.target_type == PriceTargetType.SKU.value,
            PriceBookEntry.target_id.in_(sku_ids_q),
            or_(PriceBookEntry.starts_at == None, PriceBookEntry.starts_at <= now),
            or_(PriceBookEntry.ends_at == None, PriceBookEntry.ends_at > now),
        )
    )
    return sku_price.scalar_one() > 0


async def _check_sellable_skus(db: AsyncSession, item_id: uuid.UUID) -> bool:
    result = await db.execute(
        select(func.count(SKU.id))
        .join(SPU, SPU.id == SKU.spu_id)
        .where(
            SPU.item_id == item_id,
            SKU.is_sellable == True,
            SKU.status == SKUStatus.ACTIVE.value,
        )
    )
    count = result.scalar_one()
    return count > 0


async def _count_active_skus(db: AsyncSession, item_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count(SKU.id))
        .join(SPU, SPU.id == SKU.spu_id)
        .where(
            SPU.item_id == item_id,
            SKU.status == SKUStatus.ACTIVE.value,
        )
    )
    return result.scalar_one()


async def publish_item(
    db: AsyncSession,
    *,
    item_id: uuid.UUID,
    user_id: uuid.UUID,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> Item:
    result = await db.execute(select(Item).where(Item.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise ValueError("Item not found")

    if item.owner_user_id != user_id:
        raise ValueError("Not authorized to publish this item")

    if item.status not in (ItemStatus.DRAFT.value, ItemStatus.UNPUBLISHED.value):
        raise ValueError(
            f"Item must be in DRAFT or UNPUBLISHED status to publish; current status: {item.status}"
        )

    if not item.title or not item.description or not item.category_id:
        raise ValueError("Item must have title, description, and category before publishing")

    has_image = await _check_active_image_media(db, item_id)
    if not has_image:
        raise ValueError("Item must have at least one active image media before publishing")

    has_price = await _check_active_usd_price(db, item_id)
    if not has_price:
        raise ValueError(
            "Item must have at least one active USD price in the default price book before publishing"
        )

    if item.type == ItemType.PRODUCT.value:
        has_sellable_sku = await _check_sellable_skus(db, item_id)
        if not has_sellable_sku:
            raise ValueError(
                "PRODUCT items must have at least one sellable active SKU before publishing"
            )

    if item.type == ItemType.LIVE_PET.value:
        sku_count = await _count_active_skus(db, item_id)
        if sku_count != 1:
            raise ValueError("LIVE_PET items must have exactly one active SKU before publishing")

    now = datetime.now(timezone.utc)
    before_status = item.status

    item.status = ItemStatus.PUBLISHED.value
    item.is_public = True
    item.published_at = now
    item.row_version = item.row_version + 1

    await write_audit(
        db,
        action="catalog.item.publish",
        resource_type="item",
        resource_id=str(item_id),
        actor_user_id=user_id,
        before_json=f'{{"status": "{before_status}"}}',
        after_json=f'{{"status": "{ItemStatus.PUBLISHED.value}"}}',
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.flush()
    return item


async def unpublish_item(
    db: AsyncSession,
    *,
    item_id: uuid.UUID,
    user_id: uuid.UUID,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> Item:
    result = await db.execute(select(Item).where(Item.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise ValueError("Item not found")

    if item.owner_user_id != user_id:
        raise ValueError("Not authorized to unpublish this item")

    if item.status != ItemStatus.PUBLISHED.value:
        raise ValueError(
            f"Item must be PUBLISHED to unpublish; current status: {item.status}"
        )

    now = datetime.now(timezone.utc)

    item.status = ItemStatus.UNPUBLISHED.value
    item.is_public = False
    item.unpublished_at = now
    item.row_version = item.row_version + 1

    await write_audit(
        db,
        action="catalog.item.unpublish",
        resource_type="item",
        resource_id=str(item_id),
        actor_user_id=user_id,
        before_json=f'{{"status": "{ItemStatus.PUBLISHED.value}"}}',
        after_json=f'{{"status": "{ItemStatus.UNPUBLISHED.value}"}}',
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.flush()
    return item


async def list_catalog_items(
    db: AsyncSession,
    *,
    status: str | None = None,
    item_type: str | None = None,
    category_id: uuid.UUID | None = None,
    tag_slug: str | None = None,
    search: str | None = None,
    sort_by: str = "newest",
    limit: int = 20,
    offset: int = 0,
    public_only: bool = True,
) -> tuple[list[dict], int]:
    now = datetime.now(timezone.utc)

    conditions = []

    if public_only:
        conditions.append(Item.status == ItemStatus.PUBLISHED.value)
        conditions.append(Item.is_public == True)
    elif status is not None:
        conditions.append(Item.status == status)

    if item_type is not None:
        conditions.append(Item.type == item_type)

    if category_id is not None:
        conditions.append(Item.category_id == category_id)

    if tag_slug is not None:
        tag_result = await db.execute(select(Tag).where(Tag.slug == tag_slug))
        tag = tag_result.scalar_one_or_none()
        if tag:
            conditions.append(
                Item.id.in_(
                    select(ItemTag.item_id).where(ItemTag.tag_id == tag.id)
                )
            )
        else:
            return [], 0

    if search is not None:
        search_term = f"%{search}%"
        conditions.append(
            or_(
                Item.title.ilike(search_term),
                Item.public_summary.ilike(search_term),
            )
        )

    base_query = select(Item)
    if conditions:
        base_query = base_query.where(and_(*conditions))

    count_query = select(func.count(Item.id))
    if conditions:
        count_query = count_query.where(and_(*conditions))

    total_result = await db.execute(count_query)
    total_count = total_result.scalar_one()

    from sqlalchemy import literal_column
    from sqlalchemy.orm import aliased

    item_price_q = (
        select(
            PriceBookEntry.target_id.label("resolved_item_id"),
            PriceBookEntry.amount_cents.label("entry_price"),
        )
        .join(PriceBook, PriceBook.id == PriceBookEntry.price_book_id)
        .where(
            PriceBook.is_default == True,
            PriceBook.status == PriceBookStatus.ACTIVE.value,
            PriceBook.currency == "USD",
            PriceBookEntry.target_type == PriceTargetType.ITEM.value,
            or_(PriceBookEntry.starts_at == None, PriceBookEntry.starts_at <= now),
            or_(PriceBookEntry.ends_at == None, PriceBookEntry.ends_at > now),
        )
    )

    sku_price_q = (
        select(
            SPU.item_id.label("resolved_item_id"),
            PriceBookEntry.amount_cents.label("entry_price"),
        )
        .join(PriceBook, PriceBook.id == PriceBookEntry.price_book_id)
        .join(SKU, SKU.id == PriceBookEntry.target_id)
        .join(SPU, SPU.id == SKU.spu_id)
        .where(
            PriceBook.is_default == True,
            PriceBook.status == PriceBookStatus.ACTIVE.value,
            PriceBook.currency == "USD",
            PriceBookEntry.target_type == PriceTargetType.SKU.value,
            or_(PriceBookEntry.starts_at == None, PriceBookEntry.starts_at <= now),
            or_(PriceBookEntry.ends_at == None, PriceBookEntry.ends_at > now),
        )
    )

    combined_prices = item_price_q.union_all(sku_price_q).subquery("all_prices")

    price_subq = (
        select(
            combined_prices.c.resolved_item_id.label("price_item_id"),
            func.min(combined_prices.c.entry_price).label("min_price"),
        )
        .group_by(combined_prices.c.resolved_item_id)
    ).subquery("item_prices")

    base_query = base_query.outerjoin(price_subq, Item.id == price_subq.c.price_item_id)
    base_query = base_query.add_columns(price_subq.c.min_price)

    if sort_by == "title_asc":
        base_query = base_query.order_by(Item.title.asc())
    elif sort_by == "price_asc":
        base_query = base_query.order_by(price_subq.c.min_price.asc().nulls_last(), Item.created_at.desc())
    elif sort_by == "price_desc":
        base_query = base_query.order_by(price_subq.c.min_price.desc().nulls_last(), Item.created_at.desc())
    else:
        base_query = base_query.order_by(Item.created_at.desc())

    base_query = base_query.limit(limit).offset(offset)
    items_result = await db.execute(base_query)
    rows = items_result.all()

    result_items = []
    for row in rows:
        item = row[0]
        price = row[1] if len(row) > 1 else None
        result_items.append({
            "id": item.id,
            "type": item.type,
            "status": item.status,
            "title": item.title,
            "public_summary": item.public_summary,
            "category_id": item.category_id,
            "is_public": item.is_public,
            "published_at": item.published_at,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "price_cents": price,
        })

    return result_items, total_count


async def get_catalog_item_detail(
    db: AsyncSession,
    *,
    item_id: uuid.UUID,
    public_only: bool = True,
) -> dict | None:
    now = datetime.now(timezone.utc)

    result = await db.execute(select(Item).where(Item.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        return None

    if public_only and (item.status != ItemStatus.PUBLISHED.value or not item.is_public):
        return None

    category_result = await db.execute(
        select(Category).where(Category.id == item.category_id)
    )
    category = category_result.scalar_one_or_none()

    tags_result = await db.execute(
        select(Tag)
        .join(ItemTag, ItemTag.tag_id == Tag.id)
        .where(ItemTag.item_id == item_id)
        .order_by(Tag.name)
    )
    tags = list(tags_result.scalars().all())

    media_result = await db.execute(
        select(ItemMedia, Asset)
        .join(Asset, Asset.id == ItemMedia.asset_id)
        .where(ItemMedia.item_id == item_id)
        .where(Asset.status == AssetStatus.ACTIVE.value)
        .order_by(ItemMedia.sort_order.asc(), ItemMedia.created_at.asc())
    )
    media_rows = media_result.all()
    media_list = []
    for media, asset in media_rows:
        media_list.append({
            "id": media.id,
            "asset_id": media.asset_id,
            "scope": media.scope,
            "scope_ref_id": media.scope_ref_id,
            "sort_order": media.sort_order,
            "asset_kind": asset.kind,
            "asset_status": asset.status,
            "filename": asset.filename,
            "created_at": media.created_at,
        })

    sku_ids_for_item = select(SKU.id).join(SPU, SPU.id == SKU.spu_id).where(SPU.item_id == item_id)

    prices_result = await db.execute(
        select(PriceBookEntry, PriceBook)
        .join(PriceBook, PriceBook.id == PriceBookEntry.price_book_id)
        .where(
            or_(
                and_(
                    PriceBookEntry.target_type == PriceTargetType.ITEM.value,
                    PriceBookEntry.target_id == item_id,
                ),
                and_(
                    PriceBookEntry.target_type == PriceTargetType.SKU.value,
                    PriceBookEntry.target_id.in_(sku_ids_for_item),
                ),
            ),
            PriceBook.status == PriceBookStatus.ACTIVE.value,
            or_(PriceBookEntry.starts_at == None, PriceBookEntry.starts_at <= now),
            or_(PriceBookEntry.ends_at == None, PriceBookEntry.ends_at > now),
        )
        .order_by(PriceBook.is_default.desc(), PriceBookEntry.created_at.asc())
    )
    prices_rows = prices_result.all()
    prices_list = []
    for entry, pb in prices_rows:
        prices_list.append({
            "id": entry.id,
            "price_book_id": entry.price_book_id,
            "price_book_name": pb.name,
            "price_book_is_default": pb.is_default,
            "currency": pb.currency,
            "target_type": entry.target_type,
            "target_id": entry.target_id,
            "amount_cents": entry.amount_cents,
            "compare_at_cents": entry.compare_at_cents,
            "starts_at": entry.starts_at,
            "ends_at": entry.ends_at,
        })

    spu_data = None
    skus_list = []

    if item.type in (ItemType.PRODUCT.value, ItemType.LIVE_PET.value):
        spu_result = await db.execute(select(SPU).where(SPU.item_id == item_id))
        spu = spu_result.scalar_one_or_none()
        if spu:
            spu_data = {
                "id": spu.id,
                "spu_code": spu.spu_code,
                "brand": spu.brand,
                "created_at": spu.created_at,
            }
            skus_result = await db.execute(
                select(SKU).where(SKU.spu_id == spu.id).order_by(SKU.sku_code.asc())
            )
            for sku in skus_result.scalars().all():
                skus_list.append({
                    "id": sku.id,
                    "sku_code": sku.sku_code,
                    "status": sku.status,
                    "is_sellable": sku.is_sellable,
                    "reorder_threshold": sku.reorder_threshold,
                    "created_at": sku.created_at,
                    "updated_at": sku.updated_at,
                })

    return {
        "id": item.id,
        "type": item.type,
        "status": item.status,
        "title": item.title,
        "description": item.description,
        "public_summary": item.public_summary,
        "owner_user_id": item.owner_user_id,
        "is_public": item.is_public,
        "published_at": item.published_at,
        "unpublished_at": item.unpublished_at,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "row_version": item.row_version,
        "category": {
            "id": category.id,
            "name": category.name,
            "slug": category.slug,
            "parent_id": category.parent_id,
        } if category else None,
        "tags": [{"id": t.id, "name": t.name, "slug": t.slug} for t in tags],
        "media": media_list,
        "prices": prices_list,
        "spu": spu_data,
        "skus": skus_list,
        "attributes": await _get_item_attributes(db, item_id),
    }


async def _get_item_attributes(db: AsyncSession, item_id: uuid.UUID) -> list[dict]:
    result = await db.execute(
        select(ItemAttribute).where(ItemAttribute.item_id == item_id).order_by(ItemAttribute.key)
    )
    return [
        {
            "id": str(a.id), "scope": a.scope,
            "scope_ref_id": str(a.scope_ref_id) if a.scope_ref_id else None,
            "key": a.key,
            "value_text": a.value_text, "value_number": a.value_number,
            "value_json": a.value_json,
        }
        for a in result.scalars().all()
    ]


async def create_item_attribute(
    db: AsyncSession,
    *,
    item_id: uuid.UUID,
    scope: str,
    key: str,
    scope_ref_id: uuid.UUID | None = None,
    value_text: str | None = None,
    value_number: float | None = None,
    value_json: str | None = None,
    user_id: uuid.UUID | None = None,
    allow_admin: bool = False,
) -> ItemAttribute:
    valid_scopes = {"ITEM", "SPU", "SKU"}
    if scope not in valid_scopes:
        raise ValueError(f"scope must be one of {sorted(valid_scopes)}")
    if not key or len(key) > 100:
        raise ValueError("key must be 1-100 characters")

    item_r = await db.execute(select(Item).where(Item.id == item_id))
    item_obj = item_r.scalar_one_or_none()
    if not item_obj:
        raise ValueError("Item not found")
    if user_id and not allow_admin and item_obj.owner_user_id != user_id:
        raise PermissionError("Not authorized to add attributes to this item")

    if scope == "SPU":
        if not scope_ref_id:
            raise ValueError("scope_ref_id is required for SPU-scoped attributes")
        spu_r = await db.execute(select(SPU).where(SPU.id == scope_ref_id, SPU.item_id == item_id))
        if not spu_r.scalar_one_or_none():
            raise ValueError("SPU not found or does not belong to this item")
    elif scope == "SKU":
        if not scope_ref_id:
            raise ValueError("scope_ref_id is required for SKU-scoped attributes")
        sku_r = await db.execute(
            select(SKU).join(SPU, SPU.id == SKU.spu_id).where(SKU.id == scope_ref_id, SPU.item_id == item_id)
        )
        if not sku_r.scalar_one_or_none():
            raise ValueError("SKU not found or does not belong to this item")

    attr = ItemAttribute(
        item_id=item_id, scope=scope, scope_ref_id=scope_ref_id, key=key,
        value_text=value_text, value_number=value_number, value_json=value_json,
    )
    db.add(attr)
    await db.flush()
    await write_audit(
        db, action="catalog.item.attribute_add", resource_type="item_attribute",
        resource_id=str(attr.id), actor_user_id=user_id,
    )
    return attr


async def delete_item_attribute(
    db: AsyncSession, *, attribute_id: uuid.UUID, user_id: uuid.UUID | None = None, allow_admin: bool = False,
) -> None:
    result = await db.execute(select(ItemAttribute).where(ItemAttribute.id == attribute_id))
    attr = result.scalar_one_or_none()
    if not attr:
        raise ValueError("Attribute not found")

    item_r = await db.execute(select(Item).where(Item.id == attr.item_id))
    item_obj = item_r.scalar_one_or_none()
    if user_id and not allow_admin and item_obj and item_obj.owner_user_id != user_id:
        raise PermissionError("Not authorized to delete this attribute")

    await db.delete(attr)
    await db.flush()


async def list_item_attributes(db: AsyncSession, *, item_id: uuid.UUID) -> list[dict]:
    return await _get_item_attributes(db, item_id)
