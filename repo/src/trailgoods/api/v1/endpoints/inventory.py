import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.trailgoods.api.deps import (
    get_current_user,
    get_current_user_and_session,
    get_user_role_names,
    require_permission,
)
from src.trailgoods.core.database import get_db
from src.trailgoods.middleware.request_id import request_id_ctx
from src.trailgoods.models.auth import Session as SessionModel, User
from src.trailgoods.models.inventory import ReorderAlert, Reservation
from src.trailgoods.schemas.envelope import ApiResponse, PaginationMeta, ResponseMeta
from src.trailgoods.services.audit import write_audit
from src.trailgoods.services.inventory import (
    add_inbound_line,
    add_outbound_line,
    add_stocktake_line,
    cancel_order,
    create_inbound_doc,
    create_order,
    create_outbound_doc,
    create_stocktake,
    create_warehouse,
    deduct_stock,
    get_inventory_balances,
    list_warehouses,
    post_inbound_doc,
    post_outbound_doc,
    post_stocktake,
    reserve_stock,
)

router = APIRouter(prefix="/api/v1", tags=["inventory"])


def _meta() -> ResponseMeta:
    return ResponseMeta(request_id=request_id_ctx.get(""))


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


class CreateWarehouseRequest(BaseModel):
    code: str
    name: str
    location_text: str | None = None


class CreateInboundDocRequest(BaseModel):
    warehouse_id: uuid.UUID
    source_type: str


class AddInboundLineRequest(BaseModel):
    sku_id: uuid.UUID
    quantity: int
    lot_code: str | None = None


class CreateOutboundDocRequest(BaseModel):
    warehouse_id: uuid.UUID
    source_type: str
    linked_order_id: uuid.UUID | None = None


class AddOutboundLineRequest(BaseModel):
    sku_id: uuid.UUID
    quantity: int
    lot_id: uuid.UUID | None = None


class OrderLineRequest(BaseModel):
    sku_id: uuid.UUID | None = None
    item_id: uuid.UUID
    warehouse_id: uuid.UUID | None = None
    quantity: int
    unit_price_cents: int | None = None


class CreateOrderRequest(BaseModel):
    idempotency_key: str
    lines: list[OrderLineRequest]


class CancelOrderRequest(BaseModel):
    cancel_reason: str | None = None


class CreateStocktakeRequest(BaseModel):
    warehouse_id: uuid.UUID


class AddStocktakeLineRequest(BaseModel):
    sku_id: uuid.UUID
    counted_qty: int
    variance_reason: str | None = None
    note: str | None = None


@router.post("/warehouses", status_code=201)
async def create_warehouse_endpoint(
    body: CreateWarehouseRequest,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("warehouse.create"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    try:
        warehouse = await create_warehouse(
            db,
            code=body.code,
            name=body.name,
            location_text=body.location_text,
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
            "id": str(warehouse.id),
            "code": warehouse.code,
            "name": warehouse.name,
            "location_text": warehouse.location_text,
            "created_at": warehouse.created_at.isoformat() if warehouse.created_at else None,
        },
        meta=_meta(),
    )


@router.get("/warehouses")
async def list_warehouses_endpoint(
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("warehouse.read"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[dict]]:
    user, _ = user_session
    await write_audit(
        db, action="warehouse.read", resource_type="warehouses",
        actor_user_id=user.id,
    )
    warehouses = await list_warehouses(db)
    return ApiResponse(
        data=[
            {
                "id": str(w.id),
                "code": w.code,
                "name": w.name,
                "location_text": w.location_text,
                "created_at": w.created_at.isoformat() if w.created_at else None,
            }
            for w in warehouses
        ],
        meta=_meta(),
    )


@router.post("/inbound-docs", status_code=201)
async def create_inbound_doc_endpoint(
    body: CreateInboundDocRequest,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("inventory.inbound.create"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    try:
        doc = await create_inbound_doc(
            db,
            warehouse_id=body.warehouse_id,
            source_type=body.source_type,
            user_id=user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return ApiResponse(
        data={
            "id": str(doc.id),
            "doc_no": doc.doc_no,
            "warehouse_id": str(doc.warehouse_id),
            "source_type": doc.source_type,
            "status": doc.status,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
        },
        meta=_meta(),
    )


@router.post("/inbound-docs/{doc_id}/lines", status_code=201)
async def add_inbound_line_endpoint(
    doc_id: uuid.UUID,
    body: AddInboundLineRequest,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("inventory.inbound.create"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    try:
        line = await add_inbound_line(
            db,
            doc_id=doc_id,
            sku_id=body.sku_id,
            quantity=body.quantity,
            lot_code=body.lot_code,
            actor_user_id=user.id,
        )
    except ValueError as e:
        detail = str(e)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    return ApiResponse(
        data={
            "id": str(line.id),
            "doc_id": str(line.doc_id),
            "sku_id": str(line.sku_id),
            "quantity": line.quantity,
            "lot_code": line.lot_code,
        },
        meta=_meta(),
    )


@router.post("/inbound-docs/{doc_id}/post")
async def post_inbound_doc_endpoint(
    doc_id: uuid.UUID,
    request: Request,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("inventory.inbound.post"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    try:
        doc = await post_inbound_doc(
            db,
            doc_id=doc_id,
            user_id=user.id,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except ValueError as e:
        detail = str(e)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail)
        if "already posted" in detail.lower():
            raise HTTPException(status_code=409, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    return ApiResponse(
        data={
            "id": str(doc.id),
            "doc_no": doc.doc_no,
            "status": doc.status,
            "posted_at": doc.posted_at.isoformat() if doc.posted_at else None,
        },
        meta=_meta(),
    )


@router.post("/outbound-docs", status_code=201)
async def create_outbound_doc_endpoint(
    body: CreateOutboundDocRequest,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("inventory.outbound.create"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    try:
        doc = await create_outbound_doc(
            db,
            warehouse_id=body.warehouse_id,
            source_type=body.source_type,
            linked_order_id=body.linked_order_id,
            user_id=user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return ApiResponse(
        data={
            "id": str(doc.id),
            "doc_no": doc.doc_no,
            "warehouse_id": str(doc.warehouse_id),
            "source_type": doc.source_type,
            "linked_order_id": str(doc.linked_order_id) if doc.linked_order_id else None,
            "status": doc.status,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
        },
        meta=_meta(),
    )


@router.post("/outbound-docs/{doc_id}/lines", status_code=201)
async def add_outbound_line_endpoint(
    doc_id: uuid.UUID,
    body: AddOutboundLineRequest,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("inventory.outbound.create"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    try:
        line = await add_outbound_line(
            db,
            doc_id=doc_id,
            sku_id=body.sku_id,
            quantity=body.quantity,
            lot_id=body.lot_id,
            actor_user_id=user.id,
        )
    except ValueError as e:
        detail = str(e)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    return ApiResponse(
        data={
            "id": str(line.id),
            "doc_id": str(line.doc_id),
            "sku_id": str(line.sku_id),
            "quantity": line.quantity,
            "lot_id": str(line.lot_id) if line.lot_id else None,
        },
        meta=_meta(),
    )


@router.post("/outbound-docs/{doc_id}/post")
async def post_outbound_doc_endpoint(
    doc_id: uuid.UUID,
    request: Request,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("inventory.outbound.post"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    try:
        doc = await post_outbound_doc(
            db,
            doc_id=doc_id,
            user_id=user.id,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except ValueError as e:
        detail = str(e)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail)
        if "already posted" in detail.lower():
            raise HTTPException(status_code=409, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    return ApiResponse(
        data={
            "id": str(doc.id),
            "doc_no": doc.doc_no,
            "status": doc.status,
            "posted_at": doc.posted_at.isoformat() if doc.posted_at else None,
        },
        meta=_meta(),
    )


@router.get("/inventory/balances")
async def list_inventory_balances_endpoint(
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("inventory.read"))
    ],
    db: AsyncSession = Depends(get_db),
    warehouse_id: uuid.UUID | None = None,
    sku_id: uuid.UUID | None = None,
    limit: int = 20,
    offset: int = 0,
) -> ApiResponse[list[dict]]:
    user, _ = user_session
    await write_audit(
        db, action="inventory.balances.read", resource_type="inventory_balances",
        actor_user_id=user.id,
    )
    limit = min(limit, 100)
    balances, total = await get_inventory_balances(
        db,
        warehouse_id=warehouse_id,
        sku_id=sku_id,
        limit=limit,
        offset=offset,
    )
    return ApiResponse(
        data=[
            {
                "id": str(b.id),
                "warehouse_id": str(b.warehouse_id),
                "sku_id": str(b.sku_id),
                "on_hand_qty": b.on_hand_qty,
                "reserved_qty": b.reserved_qty,
                "sellable_qty": b.sellable_qty,
                "updated_at": b.updated_at.isoformat() if b.updated_at else None,
            }
            for b in balances
        ],
        meta=ResponseMeta(
            request_id=request_id_ctx.get(""),
            pagination=PaginationMeta(total=total, limit=limit, offset=offset),
        ),
    )


@router.post("/orders", status_code=201)
async def create_order_endpoint(
    body: CreateOrderRequest,
    request: Request,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("order.create"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    idempotency_key = request.headers.get("Idempotency-Key") or body.idempotency_key
    is_admin = "Admin" in get_user_role_names(user)
    try:
        order = await create_order(
            db,
            user_id=user.id,
            idempotency_key=idempotency_key,
            lines=[line.model_dump() for line in body.lines],
            allow_admin=is_admin,
        )
    except ValueError as e:
        detail = str(e)
        if "idempotency" in detail.lower() or "already exists" in detail.lower():
            raise HTTPException(status_code=409, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    return ApiResponse(
        data={
            "id": str(order.id),
            "order_no": order.order_no,
            "user_id": str(order.user_id),
            "status": order.status,
            "idempotency_key": order.idempotency_key,
            "created_at": order.created_at.isoformat() if order.created_at else None,
        },
        meta=_meta(),
    )


@router.post("/orders/{order_id}/reserve")
async def reserve_order_stock_endpoint(
    order_id: uuid.UUID,
    request: Request,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("order.create"))
    ],
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> ApiResponse[list[dict]]:
    user, _ = user_session
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Idempotency-Key header is required")
    is_admin = "Admin" in get_user_role_names(user)
    try:
        reservations = await reserve_stock(
            db,
            order_id=order_id,
            user_id=user.id,
            idempotency_key=idempotency_key,
            ip_address=_client_ip(request),
            allow_admin=is_admin,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        detail = str(e)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=409, detail=detail)
    await db.commit()
    return ApiResponse(
        data=[
            {
                "id": str(r.id),
                "reservation_no": r.reservation_no,
                "order_id": str(r.order_id),
                "warehouse_id": str(r.warehouse_id),
                "sku_id": str(r.sku_id),
                "quantity": r.quantity,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in reservations
        ],
        meta=_meta(),
    )


@router.post("/orders/{order_id}/deduct")
async def deduct_order_stock_endpoint(
    order_id: uuid.UUID,
    request: Request,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("order.create"))
    ],
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> ApiResponse[list[dict]]:
    user, _ = user_session
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Idempotency-Key header is required")
    is_admin = "Admin" in get_user_role_names(user)
    try:
        outbound_docs = await deduct_stock(
            db,
            order_id=order_id,
            user_id=user.id,
            idempotency_key=idempotency_key,
            ip_address=_client_ip(request),
            allow_admin=is_admin,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        detail = str(e)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=409, detail=detail)
    await db.commit()
    return ApiResponse(
        data=[
            {
                "id": str(d.id),
                "doc_no": d.doc_no,
                "warehouse_id": str(d.warehouse_id),
                "source_type": d.source_type,
                "linked_order_id": str(d.linked_order_id) if d.linked_order_id else None,
                "status": d.status,
                "posted_at": d.posted_at.isoformat() if d.posted_at else None,
            }
            for d in outbound_docs
        ],
        meta=_meta(),
    )


@router.post("/orders/{order_id}/cancel")
async def cancel_order_endpoint(
    order_id: uuid.UUID,
    request: Request,
    body: CancelOrderRequest,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("order.cancel_own"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    is_admin = "Admin" in get_user_role_names(user)
    try:
        order = await cancel_order(
            db,
            order_id=order_id,
            user_id=user.id,
            cancel_reason=body.cancel_reason,
            ip_address=_client_ip(request),
            allow_admin=is_admin,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        detail = str(e)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail)
        if "already canceled" in detail.lower():
            raise HTTPException(status_code=409, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    return ApiResponse(
        data={
            "id": str(order.id),
            "order_no": order.order_no,
            "status": order.status,
            "cancel_reason": order.cancel_reason,
            "canceled_at": order.canceled_at.isoformat() if order.canceled_at else None,
        },
        meta=_meta(),
    )


@router.post("/stocktakes", status_code=201)
async def create_stocktake_endpoint(
    body: CreateStocktakeRequest,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("inventory.stocktake.create"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    try:
        stocktake = await create_stocktake(
            db,
            warehouse_id=body.warehouse_id,
            user_id=user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return ApiResponse(
        data={
            "id": str(stocktake.id),
            "warehouse_id": str(stocktake.warehouse_id),
            "status": stocktake.status,
            "started_at": stocktake.started_at.isoformat() if stocktake.started_at else None,
        },
        meta=_meta(),
    )


@router.post("/stocktakes/{stocktake_id}/lines", status_code=201)
async def add_stocktake_line_endpoint(
    stocktake_id: uuid.UUID,
    body: AddStocktakeLineRequest,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("inventory.stocktake.create"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    try:
        line = await add_stocktake_line(
            db,
            stocktake_id=stocktake_id,
            sku_id=body.sku_id,
            counted_qty=body.counted_qty,
            variance_reason=body.variance_reason,
            note=body.note,
            actor_user_id=user.id,
        )
    except ValueError as e:
        detail = str(e)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    return ApiResponse(
        data={
            "id": str(line.id),
            "stocktake_id": str(line.stocktake_id),
            "sku_id": str(line.sku_id),
            "expected_qty": line.expected_qty,
            "counted_qty": line.counted_qty,
            "variance_qty": line.variance_qty,
            "variance_reason": line.variance_reason,
            "note": line.note,
        },
        meta=_meta(),
    )


@router.post("/stocktakes/{stocktake_id}/post")
async def post_stocktake_endpoint(
    stocktake_id: uuid.UUID,
    request: Request,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("inventory.stocktake.post"))
    ],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    user, _ = user_session
    try:
        stocktake = await post_stocktake(
            db,
            stocktake_id=stocktake_id,
            user_id=user.id,
            ip_address=_client_ip(request),
        )
    except ValueError as e:
        detail = str(e)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail)
        if "already posted" in detail.lower():
            raise HTTPException(status_code=409, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    return ApiResponse(
        data={
            "id": str(stocktake.id),
            "warehouse_id": str(stocktake.warehouse_id),
            "status": stocktake.status,
            "posted_at": stocktake.posted_at.isoformat() if stocktake.posted_at else None,
            "reconciled_at": stocktake.reconciled_at.isoformat() if stocktake.reconciled_at else None,
        },
        meta=_meta(),
    )


@router.get("/reservations")
async def list_reservations_endpoint(
    request: Request,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("reservation.read"))
    ],
    db: AsyncSession = Depends(get_db),
    order_id: uuid.UUID | None = None,
    warehouse_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> ApiResponse[list[dict]]:
    user, _ = user_session
    from src.trailgoods.api.deps import get_role_snapshot
    await write_audit(
        db,
        action="reservation.read",
        resource_type="reservation",
        actor_user_id=user.id,
        actor_role_snapshot=get_role_snapshot(user),
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    is_admin = "Admin" in get_user_role_names(user)
    limit = min(limit, 100)
    query = select(Reservation)
    count_query = select(func.count()).select_from(Reservation)

    if not is_admin:
        from src.trailgoods.models.orders import Order
        user_order_ids = select(Order.id).where(Order.user_id == user.id)
        query = query.where(Reservation.order_id.in_(user_order_ids))
        count_query = count_query.where(Reservation.order_id.in_(user_order_ids))

    if order_id is not None:
        query = query.where(Reservation.order_id == order_id)
        count_query = count_query.where(Reservation.order_id == order_id)
    if warehouse_id is not None:
        query = query.where(Reservation.warehouse_id == warehouse_id)
        count_query = count_query.where(Reservation.warehouse_id == warehouse_id)
    if status is not None:
        query = query.where(Reservation.status == status)
        count_query = count_query.where(Reservation.status == status)

    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    result = await db.execute(
        query.order_by(Reservation.created_at.desc()).limit(limit).offset(offset)
    )
    reservations = list(result.scalars().all())
    return ApiResponse(
        data=[
            {
                "id": str(r.id),
                "reservation_no": r.reservation_no,
                "order_id": str(r.order_id),
                "warehouse_id": str(r.warehouse_id),
                "sku_id": str(r.sku_id),
                "quantity": r.quantity,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "released_at": r.released_at.isoformat() if r.released_at else None,
                "consumed_at": r.consumed_at.isoformat() if r.consumed_at else None,
            }
            for r in reservations
        ],
        meta=ResponseMeta(
            request_id=request_id_ctx.get(""),
            pagination=PaginationMeta(total=total, limit=limit, offset=offset),
        ),
    )


@router.get("/admin/reorder-alerts")
async def list_reorder_alerts_endpoint(
    request: Request,
    user_session: Annotated[
        tuple[User, SessionModel], Depends(require_permission("inventory.read"))
    ],
    db: AsyncSession = Depends(get_db),
    limit: int = 20,
    offset: int = 0,
) -> ApiResponse[list[dict]]:
    user, _ = user_session
    from src.trailgoods.services.audit import write_audit
    await write_audit(
        db, action="inventory.reorder_alerts.read", resource_type="reorder_alerts",
        actor_user_id=user.id, ip_address=_client_ip(request),
    )
    limit = min(limit, 100)
    count_result = await db.execute(
        select(func.count()).select_from(ReorderAlert)
    )
    total = count_result.scalar_one()

    result = await db.execute(
        select(ReorderAlert)
        .order_by(ReorderAlert.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    alerts = list(result.scalars().all())
    return ApiResponse(
        data=[
            {
                "id": str(a.id),
                "warehouse_id": str(a.warehouse_id),
                "sku_id": str(a.sku_id),
                "sellable_qty": a.sellable_qty,
                "threshold": a.threshold,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in alerts
        ],
        meta=ResponseMeta(
            request_id=request_id_ctx.get(""),
            pagination=PaginationMeta(total=total, limit=limit, offset=offset),
        ),
    )
