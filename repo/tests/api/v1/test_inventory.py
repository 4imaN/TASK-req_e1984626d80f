import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import (
    auth_header,
    get_admin_token,
    login_user,
    register_user,
    upload_test_asset,
)


async def _setup_warehouse_and_sku(client: AsyncClient, admin_token: str, publish: bool = True) -> dict:
    wh_resp = await client.post("/api/v1/warehouses", headers=auth_header(admin_token), json={
        "code": f"WH-{uuid.uuid4().hex[:6].upper()}", "name": "Main Warehouse",
    })
    assert wh_resp.status_code == 201, wh_resp.text
    wh = wh_resp.json()["data"]

    cat_resp = await client.post("/api/v1/categories", headers=auth_header(admin_token), json={
        "name": "Gear", "slug": f"gear-{uuid.uuid4().hex[:6]}",
    })
    cat = cat_resp.json()["data"]

    item_resp = await client.post("/api/v1/items", headers=auth_header(admin_token), json={
        "item_type": "PRODUCT", "title": "Test Product", "description": "A test product.",
        "category_id": cat["id"],
    })
    item = item_resp.json()["data"]

    spu_resp = await client.post("/api/v1/spus", headers=auth_header(admin_token), json={
        "item_id": item["id"], "spu_code": f"SPU-{uuid.uuid4().hex[:6]}",
    })
    spu = spu_resp.json()["data"]

    sku_resp = await client.post(f"/api/v1/spus/{spu['id']}/skus", headers=auth_header(admin_token), json={
        "sku_code": f"SKU-{uuid.uuid4().hex[:6]}",
    })
    sku = sku_resp.json()["data"]

    if publish:
        asset = await upload_test_asset(client, admin_token)
        await client.post(f"/api/v1/items/{item['id']}/media", headers=auth_header(admin_token), json={
            "asset_id": asset["asset_id"], "scope": "ITEM",
        })

        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        import os
        engine = create_async_engine(os.environ["DATABASE_URL"])
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as db:
            from sqlalchemy import select
            from src.trailgoods.models.catalog import PriceBook
            pb_result = await db.execute(select(PriceBook).where(PriceBook.is_default == True))
            pb = pb_result.scalar_one_or_none()
        await engine.dispose()

        if pb is None:
            pb_resp = await client.post("/api/v1/price-books", headers=auth_header(admin_token), json={
                "name": f"Default-{uuid.uuid4().hex[:6]}", "is_default": True,
            })
            pb_id = pb_resp.json()["data"]["id"]
        else:
            pb_id = str(pb.id)

        await client.post(f"/api/v1/price-books/{pb_id}/entries", headers=auth_header(admin_token), json={
            "target_type": "SKU", "target_id": sku["id"], "amount_cents": 500,
        })

        await client.post(f"/api/v1/items/{item['id']}/publish", headers=auth_header(admin_token))

    return {"warehouse": wh, "item": item, "spu": spu, "sku": sku}


async def _stock_inbound(client: AsyncClient, admin_token: str, warehouse_id: str, sku_id: str, qty: int) -> dict:
    doc_resp = await client.post("/api/v1/inbound-docs", headers=auth_header(admin_token), json={
        "warehouse_id": warehouse_id, "source_type": "PURCHASE",
    })
    assert doc_resp.status_code == 201, doc_resp.text
    doc = doc_resp.json()["data"]

    line_resp = await client.post(f"/api/v1/inbound-docs/{doc['id']}/lines", headers=auth_header(admin_token), json={
        "sku_id": sku_id, "quantity": qty,
    })
    assert line_resp.status_code == 201, line_resp.text

    post_resp = await client.post(f"/api/v1/inbound-docs/{doc['id']}/post", headers=auth_header(admin_token))
    assert post_resp.status_code == 200, post_resp.text
    return post_resp.json()["data"]


@pytest.mark.asyncio
class TestWarehouses:
    async def test_create_warehouse(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        resp = await client.post("/api/v1/warehouses", headers=auth_header(admin_token), json={
            "code": "WH-MAIN", "name": "Main Warehouse", "location_text": "Building A",
        })
        assert resp.status_code == 201
        assert resp.json()["data"]["code"] == "WH-MAIN"

    async def test_list_warehouses(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        await client.post("/api/v1/warehouses", headers=auth_header(admin_token), json={
            "code": f"WH-{uuid.uuid4().hex[:6].upper()}", "name": "Test WH",
        })
        resp = await client.get("/api/v1/warehouses", headers=auth_header(admin_token))
        assert resp.status_code == 200
        assert len(resp.json()["data"]) >= 1

    async def test_non_admin_cannot_create_warehouse(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        resp = await client.post("/api/v1/warehouses", headers=auth_header(login["token"]), json={
            "code": "WH-NOPE", "name": "Nope",
        })
        assert resp.status_code == 403


@pytest.mark.asyncio
class TestInboundDocs:
    async def test_inbound_flow(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        setup = await _setup_warehouse_and_sku(client, admin_token)

        await _stock_inbound(client, admin_token, setup["warehouse"]["id"], setup["sku"]["id"], 50)

        bal_resp = await client.get("/api/v1/inventory/balances", headers=auth_header(admin_token), params={
            "warehouse_id": setup["warehouse"]["id"],
        })
        assert bal_resp.status_code == 200
        balances = bal_resp.json()["data"]
        assert len(balances) >= 1
        b = balances[0]
        assert b["on_hand_qty"] == 50
        assert b["sellable_qty"] == 50
        assert b["reserved_qty"] == 0

    async def test_cannot_add_line_after_post(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        setup = await _setup_warehouse_and_sku(client, admin_token)

        doc_resp = await client.post("/api/v1/inbound-docs", headers=auth_header(admin_token), json={
            "warehouse_id": setup["warehouse"]["id"], "source_type": "PURCHASE",
        })
        doc = doc_resp.json()["data"]

        await client.post(f"/api/v1/inbound-docs/{doc['id']}/lines", headers=auth_header(admin_token), json={
            "sku_id": setup["sku"]["id"], "quantity": 10,
        })
        await client.post(f"/api/v1/inbound-docs/{doc['id']}/post", headers=auth_header(admin_token))

        resp = await client.post(f"/api/v1/inbound-docs/{doc['id']}/lines", headers=auth_header(admin_token), json={
            "sku_id": setup["sku"]["id"], "quantity": 5,
        })
        assert resp.status_code == 400 or resp.status_code == 409


@pytest.mark.asyncio
class TestOrderReservationDeduction:
    async def test_full_order_flow(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        setup = await _setup_warehouse_and_sku(client, admin_token)
        await _stock_inbound(client, admin_token, setup["warehouse"]["id"], setup["sku"]["id"], 100)

        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        user_token = login["token"]

        order_key = f"order-{uuid.uuid4().hex}"
        order_resp = await client.post("/api/v1/orders", headers=auth_header(user_token), json={
            "idempotency_key": order_key,
            "lines": [{
                "sku_id": setup["sku"]["id"],
                "item_id": setup["item"]["id"],
                "warehouse_id": setup["warehouse"]["id"],
                "quantity": 5,
                "unit_price_cents": 1000,
            }],
        })
        assert order_resp.status_code == 201, order_resp.text
        order = order_resp.json()["data"]
        assert order["status"] == "CREATED"

        reserve_key = f"reserve-{uuid.uuid4().hex}"
        reserve_resp = await client.post(
            f"/api/v1/orders/{order['id']}/reserve",
            headers={**auth_header(user_token), "Idempotency-Key": reserve_key},
        )
        assert reserve_resp.status_code == 200, reserve_resp.text

        bal_resp = await client.get("/api/v1/inventory/balances", headers=auth_header(admin_token), params={
            "warehouse_id": setup["warehouse"]["id"],
        })
        b = bal_resp.json()["data"][0]
        assert b["on_hand_qty"] == 100
        assert b["reserved_qty"] == 5
        assert b["sellable_qty"] == 95

        deduct_key = f"deduct-{uuid.uuid4().hex}"
        deduct_resp = await client.post(
            f"/api/v1/orders/{order['id']}/deduct",
            headers={**auth_header(user_token), "Idempotency-Key": deduct_key},
        )
        assert deduct_resp.status_code == 200, deduct_resp.text

        bal_resp2 = await client.get("/api/v1/inventory/balances", headers=auth_header(admin_token), params={
            "warehouse_id": setup["warehouse"]["id"],
        })
        b2 = bal_resp2.json()["data"][0]
        assert b2["on_hand_qty"] == 95
        assert b2["reserved_qty"] == 0
        assert b2["sellable_qty"] == 95

    async def test_reservation_idempotency(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        setup = await _setup_warehouse_and_sku(client, admin_token)
        await _stock_inbound(client, admin_token, setup["warehouse"]["id"], setup["sku"]["id"], 50)

        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        order_resp = await client.post("/api/v1/orders", headers=auth_header(login["token"]), json={
            "idempotency_key": f"idem-{uuid.uuid4().hex}",
            "lines": [{
                "sku_id": setup["sku"]["id"], "item_id": setup["item"]["id"],
                "warehouse_id": setup["warehouse"]["id"], "quantity": 3, "unit_price_cents": 500,
            }],
        })
        order = order_resp.json()["data"]

        reserve_key = f"rsv-{uuid.uuid4().hex}"
        r1 = await client.post(
            f"/api/v1/orders/{order['id']}/reserve",
            headers={**auth_header(login["token"]), "Idempotency-Key": reserve_key},
        )
        assert r1.status_code == 200

        r2 = await client.post(
            f"/api/v1/orders/{order['id']}/reserve",
            headers={**auth_header(login["token"]), "Idempotency-Key": reserve_key},
        )
        assert r2.status_code == 200

        bal_resp = await client.get("/api/v1/inventory/balances", headers=auth_header(admin_token), params={
            "warehouse_id": setup["warehouse"]["id"],
        })
        b = bal_resp.json()["data"][0]
        assert b["reserved_qty"] == 3

    async def test_insufficient_stock_rejected(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        setup = await _setup_warehouse_and_sku(client, admin_token)
        await _stock_inbound(client, admin_token, setup["warehouse"]["id"], setup["sku"]["id"], 5)

        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        order_resp = await client.post("/api/v1/orders", headers=auth_header(login["token"]), json={
            "idempotency_key": f"oos-{uuid.uuid4().hex}",
            "lines": [{
                "sku_id": setup["sku"]["id"], "item_id": setup["item"]["id"],
                "warehouse_id": setup["warehouse"]["id"], "quantity": 100, "unit_price_cents": 500,
            }],
        })
        order = order_resp.json()["data"]

        r = await client.post(
            f"/api/v1/orders/{order['id']}/reserve",
            headers={**auth_header(login["token"]), "Idempotency-Key": f"rsv-{uuid.uuid4().hex}"},
        )
        assert r.status_code in (400, 409), r.text

    async def test_cancel_within_30_minutes_rollback(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        setup = await _setup_warehouse_and_sku(client, admin_token)
        await _stock_inbound(client, admin_token, setup["warehouse"]["id"], setup["sku"]["id"], 100)

        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        order_resp = await client.post("/api/v1/orders", headers=auth_header(login["token"]), json={
            "idempotency_key": f"cancel-{uuid.uuid4().hex}",
            "lines": [{
                "sku_id": setup["sku"]["id"], "item_id": setup["item"]["id"],
                "warehouse_id": setup["warehouse"]["id"], "quantity": 10, "unit_price_cents": 500,
            }],
        })
        order = order_resp.json()["data"]

        await client.post(
            f"/api/v1/orders/{order['id']}/reserve",
            headers={**auth_header(login["token"]), "Idempotency-Key": f"rsv-{uuid.uuid4().hex}"},
        )

        cancel_resp = await client.post(
            f"/api/v1/orders/{order['id']}/cancel",
            headers=auth_header(login["token"]),
            json={"cancel_reason": "Changed my mind"},
        )
        assert cancel_resp.status_code == 200, cancel_resp.text
        assert cancel_resp.json()["data"]["status"] == "CANCELED"

        bal_resp = await client.get("/api/v1/inventory/balances", headers=auth_header(admin_token), params={
            "warehouse_id": setup["warehouse"]["id"],
        })
        b = bal_resp.json()["data"][0]
        assert b["on_hand_qty"] == 100
        assert b["reserved_qty"] == 0
        assert b["sellable_qty"] == 100


@pytest.mark.asyncio
class TestStocktakes:
    async def test_stocktake_with_variance(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        setup = await _setup_warehouse_and_sku(client, admin_token)
        await _stock_inbound(client, admin_token, setup["warehouse"]["id"], setup["sku"]["id"], 50)

        st_resp = await client.post("/api/v1/stocktakes", headers=auth_header(admin_token), json={
            "warehouse_id": setup["warehouse"]["id"],
        })
        assert st_resp.status_code == 201, st_resp.text
        st = st_resp.json()["data"]

        line_resp = await client.post(f"/api/v1/stocktakes/{st['id']}/lines", headers=auth_header(admin_token), json={
            "sku_id": setup["sku"]["id"],
            "counted_qty": 48,
            "variance_reason": "DAMAGE",
        })
        assert line_resp.status_code == 201, line_resp.text
        line = line_resp.json()["data"]
        assert line["variance_qty"] == -2

        post_resp = await client.post(f"/api/v1/stocktakes/{st['id']}/post", headers=auth_header(admin_token))
        assert post_resp.status_code == 200, post_resp.text

        bal_resp = await client.get("/api/v1/inventory/balances", headers=auth_header(admin_token), params={
            "warehouse_id": setup["warehouse"]["id"],
        })
        b = bal_resp.json()["data"][0]
        assert b["on_hand_qty"] == 48

    async def test_variance_without_reason_rejected(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        setup = await _setup_warehouse_and_sku(client, admin_token)
        await _stock_inbound(client, admin_token, setup["warehouse"]["id"], setup["sku"]["id"], 20)

        st_resp = await client.post("/api/v1/stocktakes", headers=auth_header(admin_token), json={
            "warehouse_id": setup["warehouse"]["id"],
        })
        st = st_resp.json()["data"]

        resp = await client.post(f"/api/v1/stocktakes/{st['id']}/lines", headers=auth_header(admin_token), json={
            "sku_id": setup["sku"]["id"],
            "counted_qty": 18,
        })
        assert resp.status_code == 400


@pytest.mark.asyncio
class TestReorderAlerts:
    async def test_reorder_alert_report(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        resp = await client.get("/api/v1/admin/reorder-alerts", headers=auth_header(admin_token))
        assert resp.status_code == 200
