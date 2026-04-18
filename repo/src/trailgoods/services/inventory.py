import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.trailgoods.models.catalog import SKU
from src.trailgoods.models.inventory import (
    InventoryBalance,
    InventoryLot,
    InventoryMovement,
    InboundDoc,
    InboundDocLine,
    OutboundDoc,
    OutboundDocLine,
    ReorderAlert,
    Reservation,
    Stocktake,
    StocktakeLine,
    Warehouse,
)
from src.trailgoods.models.orders import Order, OrderLine
from src.trailgoods.services.audit import write_audit


async def create_warehouse(
    db: AsyncSession,
    *,
    code: str,
    name: str,
    location_text: str | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> Warehouse:
    existing = await db.execute(select(Warehouse).where(Warehouse.code == code))
    if existing.scalar_one_or_none():
        raise ValueError(f"Warehouse code '{code}' already exists")
    warehouse = Warehouse(code=code, name=name, location_text=location_text)
    db.add(warehouse)
    await db.flush()
    await write_audit(
        db, action="warehouse.create", resource_type="warehouse", resource_id=str(warehouse.id),
        actor_user_id=actor_user_id,
    )
    return warehouse


async def list_warehouses(db: AsyncSession) -> list[Warehouse]:
    result = await db.execute(select(Warehouse).order_by(Warehouse.created_at))
    return list(result.scalars().all())


async def create_inbound_doc(
    db: AsyncSession,
    *,
    warehouse_id: uuid.UUID,
    source_type: str,
    user_id: uuid.UUID,
) -> InboundDoc:
    valid_inbound_types = {"PURCHASE", "RETURN", "TRANSFER_IN", "ROLLBACK", "MANUAL_ADJUSTMENT"}
    if source_type not in valid_inbound_types:
        raise ValueError(f"source_type must be one of {sorted(valid_inbound_types)}")
    wh_check = await db.execute(select(Warehouse).where(Warehouse.id == warehouse_id))
    if not wh_check.scalar_one_or_none():
        raise ValueError(f"Warehouse {warehouse_id} not found")
    doc_no = f"IB-{secrets.token_hex(8)}"
    doc = InboundDoc(
        doc_no=doc_no,
        warehouse_id=warehouse_id,
        source_type=source_type,
        status="DRAFT",
    )
    db.add(doc)
    await db.flush()
    await write_audit(
        db, action="inventory.inbound.create", resource_type="inbound_doc",
        resource_id=str(doc.id), actor_user_id=user_id,
    )
    return doc


async def add_inbound_line(
    db: AsyncSession,
    *,
    doc_id: uuid.UUID,
    sku_id: uuid.UUID,
    quantity: int,
    lot_code: str | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> InboundDocLine:
    result = await db.execute(select(InboundDoc).where(InboundDoc.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise ValueError("Inbound document not found")
    if doc.status == "POSTED":
        raise ValueError("Cannot add lines to a posted inbound document")
    if quantity is None or quantity <= 0:
        raise ValueError("Line quantity must be a positive integer")

    from src.trailgoods.models.catalog import SKU
    sku_check = await db.execute(select(SKU).where(SKU.id == sku_id))
    if not sku_check.scalar_one_or_none():
        raise ValueError(f"SKU {sku_id} not found")

    line = InboundDocLine(
        doc_id=doc_id,
        sku_id=sku_id,
        quantity=quantity,
        lot_code=lot_code,
    )
    db.add(line)
    await db.flush()
    await write_audit(
        db, action="inventory.inbound.add_line", resource_type="inbound_doc_line",
        resource_id=str(line.id), actor_user_id=actor_user_id,
    )
    return line


async def _get_or_create_balance(
    db: AsyncSession,
    *,
    warehouse_id: uuid.UUID,
    sku_id: uuid.UUID,
) -> InventoryBalance:
    result = await db.execute(
        select(InventoryBalance)
        .where(
            InventoryBalance.warehouse_id == warehouse_id,
            InventoryBalance.sku_id == sku_id,
        )
        .with_for_update()
    )
    balance = result.scalar_one_or_none()
    if not balance:
        now = datetime.now(timezone.utc)
        balance = InventoryBalance(
            warehouse_id=warehouse_id,
            sku_id=sku_id,
            on_hand_qty=0,
            reserved_qty=0,
            sellable_qty=0,
            updated_at=now,
        )
        db.add(balance)
        await db.flush()
    return balance


async def _allocate_from_lots(
    db: AsyncSession,
    *,
    warehouse_id: uuid.UUID,
    sku_id: uuid.UUID,
    quantity: int,
    explicit_lot_id: uuid.UUID | None = None,
) -> list[tuple]:
    if explicit_lot_id:
        lot_result = await db.execute(
            select(InventoryLot).where(
                InventoryLot.id == explicit_lot_id,
                InventoryLot.status == "OPEN",
            ).with_for_update()
        )
        lot = lot_result.scalar_one_or_none()
        if not lot:
            raise ValueError(f"Lot {explicit_lot_id} not found or not open")
        if lot.quantity_remaining < quantity:
            raise ValueError(
                f"Lot {explicit_lot_id} has insufficient remaining quantity: "
                f"remaining={lot.quantity_remaining}, requested={quantity}"
            )
        lot.quantity_remaining -= quantity
        if lot.quantity_remaining == 0:
            lot.status = "DEPLETED"
        return [(lot, quantity)]

    lots_result = await db.execute(
        select(InventoryLot)
        .where(
            InventoryLot.warehouse_id == warehouse_id,
            InventoryLot.sku_id == sku_id,
            InventoryLot.status == "OPEN",
            InventoryLot.quantity_remaining > 0,
        )
        .order_by(
            InventoryLot.expires_at.asc().nulls_last(),
            InventoryLot.received_at.asc(),
        )
        .with_for_update()
    )
    lots = list(lots_result.scalars().all())

    allocations: list[tuple] = []
    remaining = quantity

    for lot in lots:
        if remaining <= 0:
            break
        alloc = min(remaining, lot.quantity_remaining)
        lot.quantity_remaining -= alloc
        if lot.quantity_remaining == 0:
            lot.status = "DEPLETED"
        allocations.append((lot, alloc))
        remaining -= alloc

    if remaining > 0 and lots:
        raise ValueError(
            f"Lot allocation incomplete: requested {quantity}, "
            f"allocated {quantity - remaining} from {len(lots)} lots, "
            f"{remaining} units unaccounted"
        )

    return allocations


async def post_inbound_doc(
    db: AsyncSession,
    *,
    doc_id: uuid.UUID,
    user_id: uuid.UUID,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> InboundDoc:
    result = await db.execute(select(InboundDoc).where(InboundDoc.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise ValueError("Inbound document not found")
    if doc.status == "POSTED":
        raise ValueError("Inbound document is already posted")

    lines_result = await db.execute(
        select(InboundDocLine).where(InboundDocLine.doc_id == doc_id)
    )
    lines = list(lines_result.scalars().all())
    if not lines:
        raise ValueError("Cannot post an inbound document with no lines")

    now = datetime.now(timezone.utc)

    for line in lines:
        balance = await _get_or_create_balance(
            db, warehouse_id=doc.warehouse_id, sku_id=line.sku_id
        )
        balance.on_hand_qty += line.quantity
        balance.sellable_qty = balance.on_hand_qty - balance.reserved_qty
        balance.updated_at = now

        movement = InventoryMovement(
            warehouse_id=doc.warehouse_id,
            sku_id=line.sku_id,
            movement_type="INBOUND",
            quantity_delta=line.quantity,
            reference_type="inbound_doc",
            reference_id=str(doc_id),
            created_by_user_id=user_id,
        )
        db.add(movement)

        if line.lot_code:
            lot = InventoryLot(
                warehouse_id=doc.warehouse_id,
                sku_id=line.sku_id,
                lot_code=line.lot_code,
                received_at=now,
                quantity_received=line.quantity,
                quantity_remaining=line.quantity,
                source_inbound_doc_id=doc_id,
                status="OPEN",
            )
            db.add(lot)
            await db.flush()
            movement.lot_id = lot.id

        await db.flush()

    doc.status = "POSTED"
    doc.posted_at = now
    doc.posted_by_user_id = user_id

    await write_audit(
        db,
        action="inventory.inbound_doc.post",
        resource_type="inbound_doc",
        resource_id=str(doc_id),
        actor_user_id=user_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.flush()
    return doc


async def create_outbound_doc(
    db: AsyncSession,
    *,
    warehouse_id: uuid.UUID,
    source_type: str,
    linked_order_id: uuid.UUID | None = None,
    user_id: uuid.UUID,
) -> OutboundDoc:
    valid_outbound_types = {"SALE", "TRANSFER_OUT", "DAMAGE", "WRITE_OFF", "ORDER_DEDUCTION"}
    if source_type not in valid_outbound_types:
        raise ValueError(f"source_type must be one of {sorted(valid_outbound_types)}")
    wh_check = await db.execute(select(Warehouse).where(Warehouse.id == warehouse_id))
    if not wh_check.scalar_one_or_none():
        raise ValueError(f"Warehouse {warehouse_id} not found")
    doc_no = f"OB-{secrets.token_hex(8)}"
    doc = OutboundDoc(
        doc_no=doc_no,
        warehouse_id=warehouse_id,
        source_type=source_type,
        linked_order_id=linked_order_id,
        status="DRAFT",
    )
    db.add(doc)
    await db.flush()
    await write_audit(
        db, action="inventory.outbound.create", resource_type="outbound_doc",
        resource_id=str(doc.id), actor_user_id=user_id,
    )
    return doc


async def add_outbound_line(
    db: AsyncSession,
    *,
    doc_id: uuid.UUID,
    sku_id: uuid.UUID,
    quantity: int,
    lot_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> OutboundDocLine:
    result = await db.execute(select(OutboundDoc).where(OutboundDoc.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise ValueError("Outbound document not found")
    if doc.status == "POSTED":
        raise ValueError("Cannot add lines to a posted outbound document")
    if quantity is None or quantity <= 0:
        raise ValueError("Line quantity must be a positive integer")

    line = OutboundDocLine(
        doc_id=doc_id,
        sku_id=sku_id,
        quantity=quantity,
        lot_id=lot_id,
    )
    db.add(line)
    await db.flush()
    await write_audit(
        db, action="inventory.outbound.add_line", resource_type="outbound_doc_line",
        resource_id=str(line.id), actor_user_id=actor_user_id,
    )
    return line


async def post_outbound_doc(
    db: AsyncSession,
    *,
    doc_id: uuid.UUID,
    user_id: uuid.UUID,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> OutboundDoc:
    result = await db.execute(select(OutboundDoc).where(OutboundDoc.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise ValueError("Outbound document not found")
    if doc.status == "POSTED":
        raise ValueError("Outbound document is already posted")

    lines_result = await db.execute(
        select(OutboundDocLine).where(OutboundDocLine.doc_id == doc_id)
    )
    lines = list(lines_result.scalars().all())
    if not lines:
        raise ValueError("Cannot post an outbound document with no lines")

    now = datetime.now(timezone.utc)

    for line in lines:
        balance_result = await db.execute(
            select(InventoryBalance)
            .where(
                InventoryBalance.warehouse_id == doc.warehouse_id,
                InventoryBalance.sku_id == line.sku_id,
            )
            .with_for_update()
        )
        balance = balance_result.scalar_one_or_none()
        if not balance:
            raise ValueError(
                f"No inventory balance found for SKU {line.sku_id} in warehouse {doc.warehouse_id}"
            )
        if balance.on_hand_qty - line.quantity < 0:
            raise ValueError(
                f"Insufficient stock for SKU {line.sku_id}: "
                f"on_hand={balance.on_hand_qty}, requested={line.quantity}"
            )
        new_sellable = (balance.on_hand_qty - line.quantity) - balance.reserved_qty
        if new_sellable < 0:
            raise ValueError(
                f"Cannot post: would make sellable stock negative for SKU {line.sku_id}. "
                f"on_hand={balance.on_hand_qty}, reserved={balance.reserved_qty}, "
                f"outbound={line.quantity}"
            )

        balance.on_hand_qty -= line.quantity
        balance.sellable_qty = new_sellable
        balance.updated_at = now

        lot_allocations = await _allocate_from_lots(
            db, warehouse_id=doc.warehouse_id, sku_id=line.sku_id,
            quantity=line.quantity, explicit_lot_id=line.lot_id,
        )
        for lot, alloc_qty in lot_allocations:
            movement = InventoryMovement(
                warehouse_id=doc.warehouse_id,
                sku_id=line.sku_id,
                lot_id=lot.id,
                movement_type="OUTBOUND",
                quantity_delta=-alloc_qty,
                reference_type="outbound_doc",
                reference_id=str(doc_id),
                created_by_user_id=user_id,
            )
            db.add(movement)
        if not lot_allocations:
            movement = InventoryMovement(
                warehouse_id=doc.warehouse_id,
                sku_id=line.sku_id,
                lot_id=None,
                movement_type="OUTBOUND",
                quantity_delta=-line.quantity,
                reference_type="outbound_doc",
                reference_id=str(doc_id),
                created_by_user_id=user_id,
            )
            db.add(movement)

    doc.status = "POSTED"
    doc.posted_at = now
    doc.posted_by_user_id = user_id

    await write_audit(
        db,
        action="inventory.outbound_doc.post",
        resource_type="outbound_doc",
        resource_id=str(doc_id),
        actor_user_id=user_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.flush()
    return doc


async def get_inventory_balances(
    db: AsyncSession,
    *,
    warehouse_id: uuid.UUID | None = None,
    sku_id: uuid.UUID | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[InventoryBalance], int]:
    query = select(InventoryBalance)
    count_query = select(func.count()).select_from(InventoryBalance)

    if warehouse_id is not None:
        query = query.where(InventoryBalance.warehouse_id == warehouse_id)
        count_query = count_query.where(InventoryBalance.warehouse_id == warehouse_id)
    if sku_id is not None:
        query = query.where(InventoryBalance.sku_id == sku_id)
        count_query = count_query.where(InventoryBalance.sku_id == sku_id)

    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    result = await db.execute(query.limit(limit).offset(offset))
    balances = list(result.scalars().all())
    return balances, total


async def create_order(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    idempotency_key: str,
    lines: list[dict],
    allow_admin: bool = False,
) -> Order:
    from src.trailgoods.models.catalog import (
        Item,
        PriceBook,
        PriceBookEntry,
        SKU,
        SPU,
    )
    from src.trailgoods.models.inventory import Warehouse

    if not lines:
        raise ValueError("Order must have at least one line")

    existing_result = await db.execute(
        select(Order).where(Order.idempotency_key == idempotency_key)
    )
    existing = existing_result.scalar_one_or_none()
    if existing:
        raise ValueError("Order with this idempotency key already exists")

    now = datetime.now(timezone.utc)
    validated_lines: list[dict] = []

    for line_data in lines:
        quantity = line_data.get("quantity")
        if quantity is None or quantity <= 0:
            raise ValueError("Line quantity must be a positive integer")

        item_id = line_data.get("item_id")
        if not item_id:
            raise ValueError("Line item_id is required")

        item_result = await db.execute(select(Item).where(Item.id == item_id))
        item_obj = item_result.scalar_one_or_none()
        if not item_obj:
            raise ValueError(f"Item {item_id} not found")
        if not allow_admin and (item_obj.status != "PUBLISHED" or not item_obj.is_public):
            raise ValueError(f"Item {item_id} is not available for purchase")

        sku_id = line_data.get("sku_id")
        warehouse_id = line_data.get("warehouse_id")

        if sku_id is not None:
            sku_result = await db.execute(
                select(SKU, SPU).join(SPU, SPU.id == SKU.spu_id).where(SKU.id == sku_id)
            )
            sku_row = sku_result.one_or_none()
            if not sku_row:
                raise ValueError(f"SKU {sku_id} not found")
            sku_obj, spu_obj = sku_row
            if spu_obj.item_id != item_id:
                raise ValueError(f"SKU {sku_id} does not belong to item {item_id}")
            if not sku_obj.is_sellable or sku_obj.status != "ACTIVE":
                raise ValueError(f"SKU {sku_id} is not sellable")

        if warehouse_id is not None:
            wh_result = await db.execute(select(Warehouse).where(Warehouse.id == warehouse_id))
            wh = wh_result.scalar_one_or_none()
            if not wh:
                raise ValueError(f"Warehouse {warehouse_id} not found")
            if wh.status != "ACTIVE":
                raise ValueError(f"Warehouse {warehouse_id} is not active")

        target_type = "SKU" if sku_id is not None else "ITEM"
        target_id = sku_id if sku_id is not None else item_id

        price_result = await db.execute(
            select(PriceBookEntry)
            .join(PriceBook, PriceBook.id == PriceBookEntry.price_book_id)
            .where(
                PriceBook.is_default == True,  # noqa: E712
                PriceBook.status == "ACTIVE",
                PriceBook.currency == "USD",
                PriceBookEntry.target_type == target_type,
                PriceBookEntry.target_id == target_id,
            )
            .order_by(PriceBookEntry.created_at.desc())
        )
        price_entries = list(price_result.scalars().all())
        authoritative_price = None
        for entry in price_entries:
            starts_ok = entry.starts_at is None or entry.starts_at <= now
            ends_ok = entry.ends_at is None or entry.ends_at > now
            if starts_ok and ends_ok:
                authoritative_price = entry.amount_cents
                break

        if authoritative_price is None:
            raise ValueError(
                f"No active USD price found for {'SKU' if sku_id else 'ITEM'} {target_id}"
            )

        validated_lines.append({
            "sku_id": sku_id,
            "item_id": item_id,
            "warehouse_id": warehouse_id,
            "quantity": quantity,
            "unit_price_cents": authoritative_price,
        })

    order_no = f"ORD-{secrets.token_hex(8)}"
    order = Order(
        order_no=order_no,
        user_id=user_id,
        status="CREATED",
        idempotency_key=idempotency_key,
    )
    db.add(order)
    await db.flush()

    for vl in validated_lines:
        order_line = OrderLine(
            order_id=order.id,
            sku_id=vl["sku_id"],
            item_id=vl["item_id"],
            warehouse_id=vl["warehouse_id"],
            quantity=vl["quantity"],
            unit_price_cents=vl["unit_price_cents"],
        )
        db.add(order_line)

    await db.flush()
    await write_audit(
        db, action="order.create", resource_type="order",
        resource_id=str(order.id), actor_user_id=user_id,
    )
    return order


async def reserve_stock(
    db: AsyncSession,
    *,
    order_id: uuid.UUID,
    user_id: uuid.UUID,
    idempotency_key: str,
    ip_address: str | None = None,
    allow_admin: bool = False,
) -> list[Reservation]:
    order_result = await db.execute(select(Order).where(Order.id == order_id))
    order = order_result.scalar_one_or_none()
    if not order:
        raise ValueError("Order not found")

    if not allow_admin and order.user_id != user_id:
        raise PermissionError("Not authorized to reserve stock for this order")

    if order.status != "CREATED":
        existing_result = await db.execute(
            select(Reservation).where(
                Reservation.order_id == order_id,
                Reservation.idempotency_key == idempotency_key,
            )
        )
        existing = list(existing_result.scalars().all())
        if existing:
            return existing
        raise ValueError(
            f"Order is in status '{order.status}' and cannot be reserved again"
        )

    existing_result = await db.execute(
        select(Reservation).where(
            Reservation.order_id == order_id,
            Reservation.idempotency_key == idempotency_key,
        )
    )
    existing = list(existing_result.scalars().all())
    if existing:
        return existing

    lines_result = await db.execute(
        select(OrderLine).where(
            OrderLine.order_id == order_id,
            OrderLine.sku_id.isnot(None),
            OrderLine.warehouse_id.isnot(None),
        )
    )
    lines = list(lines_result.scalars().all())

    if not lines:
        raise ValueError(
            "No reservable order lines found (lines must have sku_id and warehouse_id)"
        )

    now = datetime.now(timezone.utc)
    reservations: list[Reservation] = []

    for line in lines:
        balance_result = await db.execute(
            select(InventoryBalance)
            .where(
                InventoryBalance.warehouse_id == line.warehouse_id,
                InventoryBalance.sku_id == line.sku_id,
            )
            .with_for_update()
        )
        balance = balance_result.scalar_one_or_none()
        if not balance:
            raise ValueError(
                f"No inventory balance for SKU {line.sku_id} in warehouse {line.warehouse_id}"
            )
        if balance.sellable_qty < line.quantity:
            raise ValueError(
                f"Insufficient sellable stock for SKU {line.sku_id}: "
                f"sellable={balance.sellable_qty}, requested={line.quantity}"
            )

        balance.reserved_qty += line.quantity
        balance.sellable_qty = balance.on_hand_qty - balance.reserved_qty
        balance.updated_at = now

        reservation_no = f"RES-{secrets.token_hex(8)}"
        reservation = Reservation(
            reservation_no=reservation_no,
            order_id=order_id,
            warehouse_id=line.warehouse_id,
            sku_id=line.sku_id,
            quantity=line.quantity,
            status="ACTIVE",
            idempotency_key=idempotency_key,
        )
        db.add(reservation)
        await db.flush()

        movement = InventoryMovement(
            warehouse_id=line.warehouse_id,
            sku_id=line.sku_id,
            movement_type="RESERVE",
            quantity_delta=-line.quantity,
            reference_type="reservation",
            reference_id=str(reservation.id),
            created_by_user_id=user_id,
        )
        db.add(movement)
        reservations.append(reservation)

    order.status = "RESERVED"

    await write_audit(
        db,
        action="inventory.reserve_stock",
        resource_type="order",
        resource_id=str(order_id),
        actor_user_id=user_id,
        ip_address=ip_address,
    )
    await db.flush()
    return reservations


async def deduct_stock(
    db: AsyncSession,
    *,
    order_id: uuid.UUID,
    user_id: uuid.UUID,
    idempotency_key: str,
    ip_address: str | None = None,
    allow_admin: bool = False,
) -> list[OutboundDoc]:
    order_result = await db.execute(select(Order).where(Order.id == order_id))
    order = order_result.scalar_one_or_none()
    if not order:
        raise ValueError("Order not found")

    if not allow_admin and order.user_id != user_id:
        raise PermissionError("Not authorized to deduct stock for this order")

    from src.trailgoods.models.jobs import IdempotencyKey
    import hashlib as _hashlib

    idem_result = await db.execute(
        select(IdempotencyKey).where(IdempotencyKey.key == idempotency_key)
    )
    idem_existing = idem_result.scalar_one_or_none()
    if idem_existing:
        existing_result = await db.execute(
            select(OutboundDoc).where(
                OutboundDoc.linked_order_id == order_id,
                OutboundDoc.source_type == "ORDER_DEDUCTION",
                OutboundDoc.status == "POSTED",
            )
        )
        existing = list(existing_result.scalars().all())
        if existing:
            return existing
        raise ValueError("Idempotency key already used for a different operation")

    existing_deductions = await db.execute(
        select(OutboundDoc).where(
            OutboundDoc.linked_order_id == order_id,
            OutboundDoc.source_type == "ORDER_DEDUCTION",
            OutboundDoc.status == "POSTED",
        )
    )
    if list(existing_deductions.scalars().all()):
        raise ValueError("Order has already been deducted")

    reservations_result = await db.execute(
        select(Reservation).where(
            Reservation.order_id == order_id,
            Reservation.status == "ACTIVE",
        )
    )
    reservations = list(reservations_result.scalars().all())
    if not reservations:
        raise ValueError("No active reservations found for this order")

    now = datetime.now(timezone.utc)

    by_warehouse: dict[uuid.UUID, list] = {}
    for r in reservations:
        by_warehouse.setdefault(r.warehouse_id, []).append(r)

    outbound_docs: list[OutboundDoc] = []
    for wh_id, wh_reservations in by_warehouse.items():
        doc_no = f"OB-{secrets.token_hex(8)}"
        outbound_doc = OutboundDoc(
            doc_no=doc_no,
            warehouse_id=wh_id,
            source_type="ORDER_DEDUCTION",
            linked_order_id=order_id,
            status="DRAFT",
        )
        db.add(outbound_doc)
        await db.flush()

        for reservation in wh_reservations:
            balance_result = await db.execute(
                select(InventoryBalance)
                .where(
                    InventoryBalance.warehouse_id == reservation.warehouse_id,
                    InventoryBalance.sku_id == reservation.sku_id,
                )
                .with_for_update()
            )
            balance = balance_result.scalar_one_or_none()
            if not balance:
                raise ValueError(
                    f"No inventory balance for SKU {reservation.sku_id} "
                    f"in warehouse {reservation.warehouse_id}"
                )
            if balance.on_hand_qty - reservation.quantity < 0:
                raise ValueError(
                    f"Insufficient on-hand stock for SKU {reservation.sku_id}: "
                    f"on_hand={balance.on_hand_qty}, required={reservation.quantity}"
                )

            balance.on_hand_qty -= reservation.quantity
            balance.reserved_qty -= reservation.quantity
            balance.sellable_qty = balance.on_hand_qty - balance.reserved_qty
            balance.updated_at = now

            reservation.status = "CONSUMED"
            reservation.consumed_at = now

            outbound_line = OutboundDocLine(
                doc_id=outbound_doc.id,
                sku_id=reservation.sku_id,
                quantity=reservation.quantity,
            )
            db.add(outbound_line)

            lot_allocations = await _allocate_from_lots(
                db, warehouse_id=reservation.warehouse_id, sku_id=reservation.sku_id,
                quantity=reservation.quantity,
            )
            for lot, alloc_qty in lot_allocations:
                movement = InventoryMovement(
                    warehouse_id=reservation.warehouse_id,
                    sku_id=reservation.sku_id,
                    lot_id=lot.id,
                    movement_type="OUTBOUND",
                    quantity_delta=-alloc_qty,
                    reference_type="outbound_doc",
                    reference_id=str(outbound_doc.id),
                    created_by_user_id=user_id,
                )
                db.add(movement)
            if not lot_allocations:
                movement = InventoryMovement(
                    warehouse_id=reservation.warehouse_id,
                    sku_id=reservation.sku_id,
                    lot_id=None,
                    movement_type="OUTBOUND",
                    quantity_delta=-reservation.quantity,
                    reference_type="outbound_doc",
                    reference_id=str(outbound_doc.id),
                    created_by_user_id=user_id,
                )
                db.add(movement)

        outbound_doc.status = "POSTED"
        outbound_doc.posted_at = now
        outbound_doc.posted_by_user_id = user_id
        outbound_docs.append(outbound_doc)
    order.status = "DEDUCTED"

    await write_audit(
        db,
        action="inventory.deduct_stock",
        resource_type="order",
        resource_id=str(order_id),
        actor_user_id=user_id,
        ip_address=ip_address,
    )

    req_hash = _hashlib.sha256(f"deduct:{order_id}:{idempotency_key}".encode()).hexdigest()
    db.add(IdempotencyKey(key=idempotency_key, request_hash=req_hash, status_code=200))

    await db.flush()
    return outbound_docs


async def cancel_order(
    db: AsyncSession,
    *,
    order_id: uuid.UUID,
    user_id: uuid.UUID,
    cancel_reason: str | None = None,
    ip_address: str | None = None,
    allow_admin: bool = False,
) -> Order:
    order_result = await db.execute(select(Order).where(Order.id == order_id))
    order = order_result.scalar_one_or_none()
    if not order:
        raise ValueError("Order not found")
    if not allow_admin and order.user_id != user_id:
        raise PermissionError("Not authorized to cancel this order")
    if order.status == "CANCELED":
        raise ValueError("Order is already canceled")

    now = datetime.now(timezone.utc)
    order_age = now - order.created_at.replace(tzinfo=timezone.utc) if order.created_at.tzinfo is None else now - order.created_at

    if order_age > timedelta(minutes=30):
        raise ValueError("Manual adjustment required for orders older than 30 minutes")

    reservations_result = await db.execute(
        select(Reservation).where(
            Reservation.order_id == order_id,
            Reservation.status == "ACTIVE",
        )
    )
    active_reservations = list(reservations_result.scalars().all())

    for reservation in active_reservations:
        balance_result = await db.execute(
            select(InventoryBalance)
            .where(
                InventoryBalance.warehouse_id == reservation.warehouse_id,
                InventoryBalance.sku_id == reservation.sku_id,
            )
            .with_for_update()
        )
        balance = balance_result.scalar_one_or_none()
        if balance:
            balance.reserved_qty -= reservation.quantity
            balance.sellable_qty = balance.on_hand_qty - balance.reserved_qty
            balance.updated_at = now

        reservation.status = "RELEASED"
        reservation.released_at = now

        movement = InventoryMovement(
            warehouse_id=reservation.warehouse_id,
            sku_id=reservation.sku_id,
            movement_type="RELEASE",
            quantity_delta=reservation.quantity,
            reference_type="reservation",
            reference_id=str(reservation.id),
            created_by_user_id=user_id,
        )
        db.add(movement)

    if order.status == "DEDUCTED":
        consumed_result = await db.execute(
            select(Reservation).where(
                Reservation.order_id == order_id,
                Reservation.status == "CONSUMED",
            )
        )
        consumed_reservations = list(consumed_result.scalars().all())

        if consumed_reservations:
            by_wh: dict[uuid.UUID, list] = {}
            for r in consumed_reservations:
                by_wh.setdefault(r.warehouse_id, []).append(r)

            order_docs_result = await db.execute(
                select(OutboundDoc.id).where(
                    OutboundDoc.linked_order_id == order_id,
                    OutboundDoc.source_type == "ORDER_DEDUCTION",
                )
            )
            order_doc_id_strs = [str(did) for did in order_docs_result.scalars().all()]

            restored_movement_ids: set[uuid.UUID] = set()
            if order_doc_id_strs:
                lot_movements_result = await db.execute(
                    select(InventoryMovement).where(
                        InventoryMovement.movement_type == "OUTBOUND",
                        InventoryMovement.quantity_delta < 0,
                        InventoryMovement.lot_id.isnot(None),
                        InventoryMovement.reference_type == "outbound_doc",
                        InventoryMovement.reference_id.in_(order_doc_id_strs),
                    )
                )
                for om in lot_movements_result.scalars().all():
                    if om.id in restored_movement_ids:
                        continue
                    restored_movement_ids.add(om.id)
                    lot_result = await db.execute(
                        select(InventoryLot).where(InventoryLot.id == om.lot_id).with_for_update()
                    )
                    lot = lot_result.scalar_one_or_none()
                    if lot:
                        lot.quantity_remaining += abs(om.quantity_delta)
                        if lot.status == "DEPLETED":
                            lot.status = "OPEN"

            for wh_id, wh_consumed in by_wh.items():
                rollback_doc_no = f"IB-{secrets.token_hex(8)}"
                rollback_doc = InboundDoc(
                    doc_no=rollback_doc_no,
                    warehouse_id=wh_id,
                    source_type="ROLLBACK",
                    status="POSTED",
                    posted_at=now,
                    posted_by_user_id=user_id,
                )
                db.add(rollback_doc)
                await db.flush()

                for reservation in wh_consumed:
                    balance_result = await db.execute(
                        select(InventoryBalance)
                        .where(
                            InventoryBalance.warehouse_id == reservation.warehouse_id,
                            InventoryBalance.sku_id == reservation.sku_id,
                        )
                        .with_for_update()
                    )
                    balance = balance_result.scalar_one_or_none()
                    if not balance:
                        balance = await _get_or_create_balance(
                            db,
                            warehouse_id=reservation.warehouse_id,
                            sku_id=reservation.sku_id,
                        )

                    balance.on_hand_qty += reservation.quantity
                    balance.sellable_qty = balance.on_hand_qty - balance.reserved_qty
                    balance.updated_at = now

                    inbound_line = InboundDocLine(
                        doc_id=rollback_doc.id,
                        sku_id=reservation.sku_id,
                        quantity=reservation.quantity,
                    )
                    db.add(inbound_line)

                    rollback_movement = InventoryMovement(
                        warehouse_id=reservation.warehouse_id,
                        sku_id=reservation.sku_id,
                        movement_type="ROLLBACK",
                        quantity_delta=reservation.quantity,
                        reference_type="inbound_doc",
                        reference_id=str(rollback_doc.id),
                        created_by_user_id=user_id,
                    )
                    db.add(rollback_movement)

    order.status = "CANCELED"
    order.canceled_at = now
    order.cancel_reason = cancel_reason

    await write_audit(
        db,
        action="inventory.cancel_order",
        resource_type="order",
        resource_id=str(order_id),
        actor_user_id=user_id,
        ip_address=ip_address,
    )
    await db.flush()
    return order


async def create_stocktake(
    db: AsyncSession,
    *,
    warehouse_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Stocktake:
    wh_check = await db.execute(select(Warehouse).where(Warehouse.id == warehouse_id))
    if not wh_check.scalar_one_or_none():
        raise ValueError(f"Warehouse {warehouse_id} not found")
    now = datetime.now(timezone.utc)
    stocktake = Stocktake(
        warehouse_id=warehouse_id,
        status="DRAFT",
        started_at=now,
        created_by_user_id=user_id,
    )
    db.add(stocktake)
    await db.flush()
    await write_audit(
        db, action="inventory.stocktake.create", resource_type="stocktake",
        resource_id=str(stocktake.id), actor_user_id=user_id,
    )
    return stocktake


async def add_stocktake_line(
    db: AsyncSession,
    *,
    stocktake_id: uuid.UUID,
    sku_id: uuid.UUID,
    counted_qty: int,
    variance_reason: str | None = None,
    note: str | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> StocktakeLine:
    stocktake_result = await db.execute(
        select(Stocktake).where(Stocktake.id == stocktake_id)
    )
    stocktake = stocktake_result.scalar_one_or_none()
    if not stocktake:
        raise ValueError("Stocktake not found")
    if stocktake.status == "POSTED":
        raise ValueError("Cannot add lines to a posted stocktake")

    balance_result = await db.execute(
        select(InventoryBalance).where(
            InventoryBalance.warehouse_id == stocktake.warehouse_id,
            InventoryBalance.sku_id == sku_id,
        )
    )
    balance = balance_result.scalar_one_or_none()
    expected_qty = balance.on_hand_qty if balance else 0

    variance_qty = counted_qty - expected_qty

    if variance_qty != 0 and not variance_reason:
        raise ValueError("variance_reason is required when variance_qty is non-zero")
    if variance_reason == "OTHER" and not note:
        raise ValueError("note is required when variance_reason is 'OTHER'")

    line = StocktakeLine(
        stocktake_id=stocktake_id,
        sku_id=sku_id,
        expected_qty=expected_qty,
        counted_qty=counted_qty,
        variance_qty=variance_qty,
        variance_reason=variance_reason,
        note=note,
    )
    db.add(line)
    await db.flush()
    await write_audit(
        db, action="inventory.stocktake.add_line", resource_type="stocktake_line",
        resource_id=str(line.id), actor_user_id=actor_user_id,
    )
    return line


async def post_stocktake(
    db: AsyncSession,
    *,
    stocktake_id: uuid.UUID,
    user_id: uuid.UUID,
    ip_address: str | None = None,
) -> Stocktake:
    stocktake_result = await db.execute(
        select(Stocktake).where(Stocktake.id == stocktake_id)
    )
    stocktake = stocktake_result.scalar_one_or_none()
    if not stocktake:
        raise ValueError("Stocktake not found")
    if stocktake.status == "POSTED":
        raise ValueError("Stocktake is already posted")

    lines_result = await db.execute(
        select(StocktakeLine).where(StocktakeLine.stocktake_id == stocktake_id)
    )
    lines = list(lines_result.scalars().all())

    now = datetime.now(timezone.utc)

    for line in lines:
        if line.variance_qty == 0:
            continue

        balance_result = await db.execute(
            select(InventoryBalance)
            .where(
                InventoryBalance.warehouse_id == stocktake.warehouse_id,
                InventoryBalance.sku_id == line.sku_id,
            )
            .with_for_update()
        )
        balance = balance_result.scalar_one_or_none()

        if not balance:
            balance = await _get_or_create_balance(
                db,
                warehouse_id=stocktake.warehouse_id,
                sku_id=line.sku_id,
            )

        new_on_hand = balance.on_hand_qty + line.variance_qty
        if new_on_hand < 0:
            raise ValueError(
                f"Stocktake adjustment would result in negative inventory for SKU {line.sku_id}"
            )
        new_sellable = new_on_hand - balance.reserved_qty
        if new_sellable < 0:
            raise ValueError(
                f"Stocktake adjustment would make sellable stock negative for SKU {line.sku_id}. "
                f"new_on_hand={new_on_hand}, reserved={balance.reserved_qty}"
            )

        balance.on_hand_qty = new_on_hand
        balance.sellable_qty = new_sellable
        balance.updated_at = now

        adj_type = "ADJUSTMENT_POSITIVE" if line.variance_qty > 0 else "ADJUSTMENT_NEGATIVE"
        movement = InventoryMovement(
            warehouse_id=stocktake.warehouse_id,
            sku_id=line.sku_id,
            movement_type=adj_type,
            quantity_delta=line.variance_qty,
            reference_type="stocktake",
            reference_id=str(stocktake_id),
            created_by_user_id=user_id,
        )
        db.add(movement)

    stocktake.status = "POSTED"
    stocktake.posted_at = now
    stocktake.reconciled_at = now

    await write_audit(
        db,
        action="inventory.stocktake.post",
        resource_type="stocktake",
        resource_id=str(stocktake_id),
        actor_user_id=user_id,
        ip_address=ip_address,
    )
    await db.flush()
    return stocktake


async def check_reorder_alerts(db: AsyncSession) -> int:
    now = datetime.now(timezone.utc)
    balances_result = await db.execute(
        select(InventoryBalance, SKU).join(SKU, SKU.id == InventoryBalance.sku_id)
    )
    rows = balances_result.all()

    count = 0
    for balance, sku in rows:
        threshold = sku.reorder_threshold if sku.reorder_threshold is not None else 10
        if balance.sellable_qty < threshold:
            existing = await db.execute(
                select(ReorderAlert).where(
                    ReorderAlert.warehouse_id == balance.warehouse_id,
                    ReorderAlert.sku_id == balance.sku_id,
                    ReorderAlert.threshold == threshold,
                    ReorderAlert.resolved_at == None,
                )
            )
            if existing.scalar_one_or_none():
                continue
            alert = ReorderAlert(
                warehouse_id=balance.warehouse_id,
                sku_id=balance.sku_id,
                sellable_qty=balance.sellable_qty,
                threshold=threshold,
            )
            db.add(alert)
            count += 1
        else:
            # Resolve any active alerts for this key since condition is no longer active
            active_alerts = await db.execute(
                select(ReorderAlert).where(
                    ReorderAlert.warehouse_id == balance.warehouse_id,
                    ReorderAlert.sku_id == balance.sku_id,
                    ReorderAlert.threshold == threshold,
                    ReorderAlert.resolved_at == None,
                )
            )
            for alert in active_alerts.scalars().all():
                alert.resolved_at = now

    if count:
        await db.flush()
    return count
