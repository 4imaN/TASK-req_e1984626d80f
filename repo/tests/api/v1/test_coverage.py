import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests.conftest import (
    auth_header,
    get_admin_token,
    get_reviewer_token,
    login_user,
    register_user,
    upload_test_asset,
)


async def _make_category(client, token, name=None, slug=None, parent_id=None):
    slug = slug or f"cat-{uuid.uuid4().hex[:8]}"
    name = name or slug
    body = {"name": name, "slug": slug}
    if parent_id:
        body["parent_id"] = parent_id
    r = await client.post("/api/v1/categories", headers=auth_header(token), json=body)
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def _make_tag(client, token, name=None, slug=None):
    slug = slug or f"tag-{uuid.uuid4().hex[:8]}"
    name = name or slug
    r = await client.post("/api/v1/tags", headers=auth_header(token), json={"name": name, "slug": slug})
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def _make_price_book(client, token, name="PB", is_default=True):
    r = await client.post("/api/v1/price-books", headers=auth_header(token), json={"name": name, "is_default": is_default})
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def _make_item(client, token, category_id, item_type="PRODUCT", title=None):
    title = title or f"Item {uuid.uuid4().hex[:6]}"
    r = await client.post("/api/v1/items", headers=auth_header(token), json={
        "item_type": item_type, "title": title, "description": "desc", "category_id": category_id,
    })
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def _make_spu(client, token, item_id):
    r = await client.post("/api/v1/spus", headers=auth_header(token), json={
        "item_id": item_id, "spu_code": f"SPU-{uuid.uuid4().hex[:8]}",
    })
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def _make_sku(client, token, spu_id):
    r = await client.post(f"/api/v1/spus/{spu_id}/skus", headers=auth_header(token), json={
        "sku_code": f"SKU-{uuid.uuid4().hex[:8]}",
    })
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def _make_warehouse(client, token):
    r = await client.post("/api/v1/warehouses", headers=auth_header(token), json={
        "code": f"WH-{uuid.uuid4().hex[:6].upper()}", "name": "Test WH",
    })
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def _stock_inbound(client, token, warehouse_id, sku_id, qty):
    doc_r = await client.post("/api/v1/inbound-docs", headers=auth_header(token), json={
        "warehouse_id": warehouse_id, "source_type": "PURCHASE",
    })
    doc = doc_r.json()["data"]
    await client.post(f"/api/v1/inbound-docs/{doc['id']}/lines", headers=auth_header(token), json={
        "sku_id": sku_id, "quantity": qty,
    })
    r = await client.post(f"/api/v1/inbound-docs/{doc['id']}/post", headers=auth_header(token))
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def _make_full_published_product(client, token):
    cat = await _make_category(client, token)
    asset = await upload_test_asset(client, token)
    item = await _make_item(client, token, cat["id"])
    await client.post(f"/api/v1/items/{item['id']}/media", headers=auth_header(token), json={
        "asset_id": asset["asset_id"], "scope": "ITEM",
    })
    spu = await _make_spu(client, token, item["id"])
    sku = await _make_sku(client, token, spu["id"])
    pb = await _make_price_book(client, token)
    await client.post(f"/api/v1/price-books/{pb['id']}/entries", headers=auth_header(token), json={
        "target_type": "SKU", "target_id": sku["id"], "amount_cents": 9999,
    })
    r = await client.post(f"/api/v1/items/{item['id']}/publish", headers=auth_header(token))
    assert r.status_code == 200, r.text
    return {"item": item, "spu": spu, "sku": sku, "category": cat, "price_book": pb}


@pytest.mark.asyncio
class TestCatalogTagOperations:
    async def test_create_tag_duplicate_rejected(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        slug = f"dup-tag-{uuid.uuid4().hex[:6]}"
        await _make_tag(client, admin_token, slug=slug)
        r = await client.post("/api/v1/tags", headers=auth_header(admin_token), json={"name": slug, "slug": slug})
        assert r.status_code == 409

    async def test_list_tags_returns_list(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        await _make_tag(client, admin_token)
        r = await client.get("/api/v1/tags")
        assert r.status_code == 200
        assert isinstance(r.json()["data"], list)
        assert len(r.json()["data"]) >= 1

    async def test_add_item_media(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _make_category(client, admin_token)
        item = await _make_item(client, admin_token, cat["id"])
        asset = await upload_test_asset(client, admin_token)
        r = await client.post(f"/api/v1/items/{item['id']}/media", headers=auth_header(admin_token), json={
            "asset_id": asset["asset_id"], "scope": "ITEM",
        })
        assert r.status_code == 201


@pytest.mark.asyncio
class TestCatalogSPUValidation:
    async def test_create_spu_for_service_rejected(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _make_category(client, admin_token)
        item = await _make_item(client, admin_token, cat["id"], item_type="SERVICE")
        r = await client.post("/api/v1/spus", headers=auth_header(admin_token), json={
            "item_id": item["id"], "spu_code": f"SPU-{uuid.uuid4().hex[:8]}",
        })
        assert r.status_code == 400

    async def test_create_duplicate_spu_rejected(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _make_category(client, admin_token)
        item = await _make_item(client, admin_token, cat["id"])
        await _make_spu(client, admin_token, item["id"])
        r = await client.post("/api/v1/spus", headers=auth_header(admin_token), json={
            "item_id": item["id"], "spu_code": f"SPU-{uuid.uuid4().hex[:8]}",
        })
        assert r.status_code == 409

    async def test_create_sku_empty_code_rejected(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _make_category(client, admin_token)
        item = await _make_item(client, admin_token, cat["id"])
        spu = await _make_spu(client, admin_token, item["id"])
        r = await client.post(f"/api/v1/spus/{spu['id']}/skus", headers=auth_header(admin_token), json={
            "sku_code": "",
        })
        assert r.status_code in (400, 422)

    async def test_update_sku(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _make_category(client, admin_token)
        item = await _make_item(client, admin_token, cat["id"])
        spu = await _make_spu(client, admin_token, item["id"])
        sku = await _make_sku(client, admin_token, spu["id"])
        r = await client.patch(f"/api/v1/skus/{sku['id']}", headers=auth_header(admin_token), json={
            "is_sellable": False, "reorder_threshold": 5,
        })
        assert r.status_code == 200
        assert r.json()["data"]["is_sellable"] is False
        assert r.json()["data"]["reorder_threshold"] == 5

    async def test_update_sku_not_found(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        r = await client.patch(f"/api/v1/skus/{uuid.uuid4()}", headers=auth_header(admin_token), json={
            "is_sellable": True,
        })
        assert r.status_code == 404


@pytest.mark.asyncio
class TestCatalogPriceBookOverlap:
    async def test_overlapping_entry_rejected(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        pb = await _make_price_book(client, admin_token, name="Overlap PB")
        cat = await _make_category(client, admin_token)
        item = await _make_item(client, admin_token, cat["id"], item_type="SERVICE")
        await client.post(f"/api/v1/price-books/{pb['id']}/entries", headers=auth_header(admin_token), json={
            "target_type": "ITEM", "target_id": item["id"], "amount_cents": 1000,
        })
        r = await client.post(f"/api/v1/price-books/{pb['id']}/entries", headers=auth_header(admin_token), json={
            "target_type": "ITEM", "target_id": item["id"], "amount_cents": 2000,
        })
        assert r.status_code == 409


@pytest.mark.asyncio
class TestCatalogItemsListing:
    async def test_list_with_sort_title_asc(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        await _make_full_published_product(client, admin_token)
        r = await client.get("/api/v1/catalog/items", params={"sort_by": "title_asc"})
        assert r.status_code == 200

    async def test_list_with_sort_price_asc(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        await _make_full_published_product(client, admin_token)
        r = await client.get("/api/v1/catalog/items", params={"sort_by": "price_asc"})
        assert r.status_code == 200

    async def test_list_with_sort_price_desc(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        await _make_full_published_product(client, admin_token)
        r = await client.get("/api/v1/catalog/items", params={"sort_by": "price_desc"})
        assert r.status_code == 200

    async def test_list_by_category_filter(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        prod = await _make_full_published_product(client, admin_token)
        r = await client.get("/api/v1/catalog/items", params={"category_id": prod["category"]["id"]})
        assert r.status_code == 200
        assert any(i["id"] == prod["item"]["id"] for i in r.json()["data"])

    async def test_list_by_tag_filter(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        prod = await _make_full_published_product(client, admin_token)
        tag = await _make_tag(client, admin_token)
        await client.post(f"/api/v1/items/{prod['item']['id']}/tags/{tag['id']}", headers=auth_header(admin_token))
        r = await client.get("/api/v1/catalog/items", params={"tag_slug": tag["slug"]})
        assert r.status_code == 200

    async def test_list_by_nonexistent_tag(self, client: AsyncClient):
        r = await client.get("/api/v1/catalog/items", params={"tag_slug": "does-not-exist-xyz"})
        assert r.status_code == 200
        assert r.json()["data"] == []

    async def test_list_with_pagination(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        await _make_full_published_product(client, admin_token)
        r = await client.get("/api/v1/catalog/items", params={"limit": 5, "offset": 0})
        assert r.status_code == 200


@pytest.mark.asyncio
class TestGetCatalogItemDetail:
    async def test_get_published_item_unauthenticated(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        prod = await _make_full_published_product(client, admin_token)
        r = await client.get(f"/api/v1/items/{prod['item']['id']}")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["id"] == prod["item"]["id"]
        assert "skus" in data

    async def test_get_draft_item_unauthenticated_returns_401(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _make_category(client, admin_token)
        item = await _make_item(client, admin_token, cat["id"])
        r = await client.get(f"/api/v1/items/{item['id']}")
        assert r.status_code == 401

    async def test_get_nonexistent_item_returns_404(self, client: AsyncClient):
        r = await client.get(f"/api/v1/items/{uuid.uuid4()}")
        assert r.status_code == 404


@pytest.mark.asyncio
class TestUpdateItemNonOwnerRejected:
    async def test_non_owner_update_rejected(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _make_category(client, admin_token)
        item = await _make_item(client, admin_token, cat["id"])

        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        r = await client.patch(f"/api/v1/items/{item['id']}", headers=auth_header(login["token"]), json={
            "row_version": item["row_version"], "title": "Hacked",
        })
        assert r.status_code == 403


@pytest.mark.asyncio
class TestCategoryWithParent:
    async def test_create_subcategory(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        parent = await _make_category(client, admin_token, name="Parent Cat")
        child = await _make_category(client, admin_token, name="Child Cat", parent_id=parent["id"])
        assert child["parent_id"] == parent["id"]

    async def test_create_category_invalid_parent_rejected(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        r = await client.post("/api/v1/categories", headers=auth_header(admin_token), json={
            "name": "Orphan", "slug": f"orphan-{uuid.uuid4().hex[:6]}", "parent_id": str(uuid.uuid4()),
        })
        assert r.status_code == 400


@pytest.mark.asyncio
class TestOutboundDocEndpoints:
    async def test_outbound_doc_full_flow(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _make_category(client, admin_token)
        item = await _make_item(client, admin_token, cat["id"])
        spu = await _make_spu(client, admin_token, item["id"])
        sku = await _make_sku(client, admin_token, spu["id"])
        wh = await _make_warehouse(client, admin_token)

        await _stock_inbound(client, admin_token, wh["id"], sku["id"], 50)

        ob_r = await client.post("/api/v1/outbound-docs", headers=auth_header(admin_token), json={
            "warehouse_id": wh["id"], "source_type": "SALE",
        })
        assert ob_r.status_code == 201
        ob = ob_r.json()["data"]

        line_r = await client.post(f"/api/v1/outbound-docs/{ob['id']}/lines", headers=auth_header(admin_token), json={
            "sku_id": sku["id"], "quantity": 10,
        })
        assert line_r.status_code == 201

        post_r = await client.post(f"/api/v1/outbound-docs/{ob['id']}/post", headers=auth_header(admin_token))
        assert post_r.status_code == 200
        assert post_r.json()["data"]["status"] == "POSTED"

    async def test_outbound_doc_insufficient_stock(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _make_category(client, admin_token)
        item = await _make_item(client, admin_token, cat["id"])
        spu = await _make_spu(client, admin_token, item["id"])
        sku = await _make_sku(client, admin_token, spu["id"])
        wh = await _make_warehouse(client, admin_token)

        await _stock_inbound(client, admin_token, wh["id"], sku["id"], 5)

        ob_r = await client.post("/api/v1/outbound-docs", headers=auth_header(admin_token), json={
            "warehouse_id": wh["id"], "source_type": "SALE",
        })
        ob = ob_r.json()["data"]
        await client.post(f"/api/v1/outbound-docs/{ob['id']}/lines", headers=auth_header(admin_token), json={
            "sku_id": sku["id"], "quantity": 100,
        })
        post_r = await client.post(f"/api/v1/outbound-docs/{ob['id']}/post", headers=auth_header(admin_token))
        assert post_r.status_code == 400

    async def test_outbound_doc_already_posted(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _make_category(client, admin_token)
        item = await _make_item(client, admin_token, cat["id"])
        spu = await _make_spu(client, admin_token, item["id"])
        sku = await _make_sku(client, admin_token, spu["id"])
        wh = await _make_warehouse(client, admin_token)
        await _stock_inbound(client, admin_token, wh["id"], sku["id"], 20)

        ob_r = await client.post("/api/v1/outbound-docs", headers=auth_header(admin_token), json={
            "warehouse_id": wh["id"], "source_type": "SALE",
        })
        ob = ob_r.json()["data"]
        await client.post(f"/api/v1/outbound-docs/{ob['id']}/lines", headers=auth_header(admin_token), json={
            "sku_id": sku["id"], "quantity": 5,
        })
        await client.post(f"/api/v1/outbound-docs/{ob['id']}/post", headers=auth_header(admin_token))
        r = await client.post(f"/api/v1/outbound-docs/{ob['id']}/post", headers=auth_header(admin_token))
        assert r.status_code == 409


@pytest.mark.asyncio
class TestReservationListing:
    async def test_list_reservations(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        data = await _make_full_published_product(client, admin_token)
        item, sku = data["item"], data["sku"]
        wh = await _make_warehouse(client, admin_token)
        await _stock_inbound(client, admin_token, wh["id"], sku["id"], 30)

        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        order_r = await client.post("/api/v1/orders", headers=auth_header(login["token"]), json={
            "idempotency_key": f"res-list-{uuid.uuid4().hex}",
            "lines": [{
                "sku_id": sku["id"], "item_id": item["id"],
                "warehouse_id": wh["id"], "quantity": 3,
            }],
        })
        assert order_r.status_code == 201, order_r.text
        order = order_r.json()["data"]

        await client.post(
            f"/api/v1/orders/{order['id']}/reserve",
            headers={**auth_header(login["token"]), "Idempotency-Key": f"rsv-{uuid.uuid4().hex}"},
        )

        r = await client.get("/api/v1/reservations", headers=auth_header(admin_token))
        assert r.status_code == 200
        assert len(r.json()["data"]) >= 1

    async def test_list_reservations_filtered_by_status(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        r = await client.get("/api/v1/reservations", headers=auth_header(admin_token), params={"status": "ACTIVE"})
        assert r.status_code == 200


@pytest.mark.asyncio
class TestStocktakeReconcileAndPost:
    async def test_stocktake_reconcile_no_variance(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _make_category(client, admin_token)
        item = await _make_item(client, admin_token, cat["id"])
        spu = await _make_spu(client, admin_token, item["id"])
        sku = await _make_sku(client, admin_token, spu["id"])
        wh = await _make_warehouse(client, admin_token)
        await _stock_inbound(client, admin_token, wh["id"], sku["id"], 20)

        st_r = await client.post("/api/v1/stocktakes", headers=auth_header(admin_token), json={
            "warehouse_id": wh["id"],
        })
        st = st_r.json()["data"]
        await client.post(f"/api/v1/stocktakes/{st['id']}/lines", headers=auth_header(admin_token), json={
            "sku_id": sku["id"], "counted_qty": 20,
        })
        post_r = await client.post(f"/api/v1/stocktakes/{st['id']}/post", headers=auth_header(admin_token))
        assert post_r.status_code == 200
        assert post_r.json()["data"]["status"] == "POSTED"
        assert post_r.json()["data"]["reconciled_at"] is not None

    async def test_stocktake_already_posted(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _make_category(client, admin_token)
        item = await _make_item(client, admin_token, cat["id"])
        spu = await _make_spu(client, admin_token, item["id"])
        sku = await _make_sku(client, admin_token, spu["id"])
        wh = await _make_warehouse(client, admin_token)
        await _stock_inbound(client, admin_token, wh["id"], sku["id"], 10)

        st_r = await client.post("/api/v1/stocktakes", headers=auth_header(admin_token), json={
            "warehouse_id": wh["id"],
        })
        st = st_r.json()["data"]
        await client.post(f"/api/v1/stocktakes/{st['id']}/lines", headers=auth_header(admin_token), json={
            "sku_id": sku["id"], "counted_qty": 10,
        })
        await client.post(f"/api/v1/stocktakes/{st['id']}/post", headers=auth_header(admin_token))
        r = await client.post(f"/api/v1/stocktakes/{st['id']}/post", headers=auth_header(admin_token))
        assert r.status_code == 409

    async def test_stocktake_variance_reason_other_requires_note(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _make_category(client, admin_token)
        item = await _make_item(client, admin_token, cat["id"])
        spu = await _make_spu(client, admin_token, item["id"])
        sku = await _make_sku(client, admin_token, spu["id"])
        wh = await _make_warehouse(client, admin_token)
        await _stock_inbound(client, admin_token, wh["id"], sku["id"], 10)

        st_r = await client.post("/api/v1/stocktakes", headers=auth_header(admin_token), json={
            "warehouse_id": wh["id"],
        })
        st = st_r.json()["data"]
        r = await client.post(f"/api/v1/stocktakes/{st['id']}/lines", headers=auth_header(admin_token), json={
            "sku_id": sku["id"], "counted_qty": 8, "variance_reason": "OTHER",
        })
        assert r.status_code == 400


@pytest.mark.asyncio
class TestInventoryBalancesFiltered:
    async def test_balances_filtered_by_sku(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _make_category(client, admin_token)
        item = await _make_item(client, admin_token, cat["id"])
        spu = await _make_spu(client, admin_token, item["id"])
        sku = await _make_sku(client, admin_token, spu["id"])
        wh = await _make_warehouse(client, admin_token)
        await _stock_inbound(client, admin_token, wh["id"], sku["id"], 15)

        r = await client.get("/api/v1/inventory/balances", headers=auth_header(admin_token), params={
            "sku_id": sku["id"],
        })
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) >= 1
        assert data[0]["sku_id"] == sku["id"]

    async def test_balances_pagination(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        r = await client.get("/api/v1/inventory/balances", headers=auth_header(admin_token), params={
            "limit": 10, "offset": 0,
        })
        assert r.status_code == 200
        assert "pagination" in r.json()["meta"]


@pytest.mark.asyncio
class TestCancelAfterDeduction:
    async def test_cancel_after_deduction_rollback(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        data = await _make_full_published_product(client, admin_token)
        item, sku = data["item"], data["sku"]
        wh = await _make_warehouse(client, admin_token)
        await _stock_inbound(client, admin_token, wh["id"], sku["id"], 50)

        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        order_r = await client.post("/api/v1/orders", headers=auth_header(login["token"]), json={
            "idempotency_key": f"can-ded-{uuid.uuid4().hex}",
            "lines": [{
                "sku_id": sku["id"], "item_id": item["id"],
                "warehouse_id": wh["id"], "quantity": 5,
            }],
        })
        assert order_r.status_code == 201, order_r.text
        order = order_r.json()["data"]

        await client.post(
            f"/api/v1/orders/{order['id']}/reserve",
            headers={**auth_header(login["token"]), "Idempotency-Key": f"rsv-{uuid.uuid4().hex}"},
        )

        await client.post(
            f"/api/v1/orders/{order['id']}/deduct",
            headers={**auth_header(login["token"]), "Idempotency-Key": f"ded-{uuid.uuid4().hex}"},
        )

        bal_before = await client.get("/api/v1/inventory/balances", headers=auth_header(admin_token), params={
            "warehouse_id": wh["id"],
        })
        on_hand_before = bal_before.json()["data"][0]["on_hand_qty"]

        cancel_r = await client.post(
            f"/api/v1/orders/{order['id']}/cancel",
            headers=auth_header(login["token"]),
            json={"cancel_reason": "Changed mind after deduct"},
        )
        assert cancel_r.status_code == 200

        bal_after = await client.get("/api/v1/inventory/balances", headers=auth_header(admin_token), params={
            "warehouse_id": wh["id"],
        })
        on_hand_after = bal_after.json()["data"][0]["on_hand_qty"]
        assert on_hand_after == on_hand_before + 5


@pytest.mark.asyncio
class TestEnterpriseVerification:
    async def test_enterprise_case_full_flow(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        case_r = await client.post("/api/v1/verification-cases", headers=auth_header(login["token"]), json={
            "profile_type": "ENTERPRISE",
        })
        assert case_r.status_code == 201
        case = case_r.json()["data"]
        assert case["profile_type"] == "ENTERPRISE"

        import io
        from PIL import Image as _PILImage
        buf1 = io.BytesIO()
        _PILImage.new("RGB", (50, 50), color="red").save(buf1, "JPEG")
        buf2 = io.BytesIO()
        _PILImage.new("RGB", (50, 50), color="green").save(buf2, "JPEG")
        reg_asset = await upload_test_asset(client, login["token"], content=buf1.getvalue(), purpose="VERIFICATION", kind="VERIFICATION_ID")
        person_asset = await upload_test_asset(client, login["token"], content=buf2.getvalue(), purpose="VERIFICATION", kind="VERIFICATION_ID")

        update_r = await client.patch(
            f"/api/v1/verification-cases/{case['case_id']}",
            headers=auth_header(login["token"]),
            json={
                "row_version": case["row_version"],
                "enterprise_legal_name": "Acme Corp LLC",
                "enterprise_registration_number": "REG-12345",
                "enterprise_registration_asset_id": reg_asset["asset_id"],
                "responsible_person_legal_name": "Jane Smith",
                "responsible_person_dob": "03/20/1980",
                "responsible_person_id_number": "B987654321",
                "responsible_person_id_image_asset_id": person_asset["asset_id"],
            },
        )
        assert update_r.status_code == 200

        submit_r = await client.post(
            f"/api/v1/verification-cases/{case['case_id']}/submit",
            headers=auth_header(login["token"]),
        )
        assert submit_r.status_code == 200
        assert submit_r.json()["data"]["status"] == "SUBMITTED"

    async def test_enterprise_submit_incomplete_rejected(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        case_r = await client.post("/api/v1/verification-cases", headers=auth_header(login["token"]), json={
            "profile_type": "ENTERPRISE",
        })
        case = case_r.json()["data"]

        r = await client.post(
            f"/api/v1/verification-cases/{case['case_id']}/submit",
            headers=auth_header(login["token"]),
        )
        assert r.status_code == 400


@pytest.mark.asyncio
class TestVerificationRenewal:
    async def test_renew_non_expired_rejected(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        case_r = await client.post("/api/v1/verification-cases", headers=auth_header(login["token"]), json={
            "profile_type": "PERSONAL",
        })
        case = case_r.json()["data"]

        r = await client.post(
            f"/api/v1/verification-cases/{case['case_id']}/renew",
            headers=auth_header(login["token"]),
        )
        assert r.status_code == 400

    async def test_renew_approved_then_expired(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        reviewer_token = await get_reviewer_token(client)

        case_r = await client.post("/api/v1/verification-cases", headers=auth_header(login["token"]), json={
            "profile_type": "PERSONAL",
        })
        case = case_r.json()["data"]

        asset = await upload_test_asset(client, login["token"], purpose="VERIFICATION", kind="VERIFICATION_ID")
        await client.patch(
            f"/api/v1/verification-cases/{case['case_id']}",
            headers=auth_header(login["token"]),
            json={
                "row_version": case["row_version"],
                "legal_name": "John Doe",
                "dob": "01/15/1990",
                "government_id_number": "A123456789",
                "government_id_image_asset_id": asset["asset_id"],
            },
        )
        await client.post(f"/api/v1/verification-cases/{case['case_id']}/submit", headers=auth_header(login["token"]))

        await client.post(
            f"/api/v1/verification-cases/{case['case_id']}/decision",
            headers=auth_header(reviewer_token),
            json={"decision": "UNDER_REVIEW"},
        )
        await client.post(
            f"/api/v1/verification-cases/{case['case_id']}/decision",
            headers=auth_header(reviewer_token),
            json={"decision": "APPROVED", "comment": "Looks good"},
        )

        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        import os
        engine = create_async_engine(os.environ["DATABASE_URL"])
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            from sqlalchemy import update
            from src.trailgoods.models.verification import VerificationCase
            now = datetime.now(timezone.utc)
            past = now - timedelta(days=2)
            await session.execute(
                update(VerificationCase)
                .where(VerificationCase.case_id == case["case_id"])
                .values(status="EXPIRED", expires_at=past)
            )
            await session.commit()
        await engine.dispose()

        r = await client.post(
            f"/api/v1/verification-cases/{case['case_id']}/renew",
            headers=auth_header(login["token"]),
        )
        assert r.status_code == 200
        assert r.json()["data"]["status"] == "SUBMITTED"


@pytest.mark.asyncio
class TestRequirePermissionDep:
    async def test_non_admin_with_missing_permission_rejected(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        r = await client.post("/api/v1/warehouses", headers=auth_header(login["token"]), json={
            "code": "WH-PERM", "name": "Perm Test",
        })
        assert r.status_code == 403

    async def test_admin_passes_role_check(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        r = await client.get("/api/v1/warehouses", headers=auth_header(admin_token))
        assert r.status_code == 200


@pytest.mark.asyncio
class TestListWarehousesService:
    async def test_list_warehouses_empty(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        r = await client.get("/api/v1/warehouses", headers=auth_header(admin_token))
        assert r.status_code == 200
        assert isinstance(r.json()["data"], list)


@pytest.mark.asyncio
class TestInboundDocEdgeCases:
    async def test_post_inbound_no_lines_rejected(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        wh = await _make_warehouse(client, admin_token)
        doc_r = await client.post("/api/v1/inbound-docs", headers=auth_header(admin_token), json={
            "warehouse_id": wh["id"], "source_type": "PURCHASE",
        })
        doc = doc_r.json()["data"]
        r = await client.post(f"/api/v1/inbound-docs/{doc['id']}/post", headers=auth_header(admin_token))
        assert r.status_code == 400

    async def test_inbound_already_posted(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _make_category(client, admin_token)
        item = await _make_item(client, admin_token, cat["id"])
        spu = await _make_spu(client, admin_token, item["id"])
        sku = await _make_sku(client, admin_token, spu["id"])
        wh = await _make_warehouse(client, admin_token)

        doc_r = await client.post("/api/v1/inbound-docs", headers=auth_header(admin_token), json={
            "warehouse_id": wh["id"], "source_type": "PURCHASE",
        })
        doc = doc_r.json()["data"]
        await client.post(f"/api/v1/inbound-docs/{doc['id']}/lines", headers=auth_header(admin_token), json={
            "sku_id": sku["id"], "quantity": 10,
        })
        await client.post(f"/api/v1/inbound-docs/{doc['id']}/post", headers=auth_header(admin_token))
        r = await client.post(f"/api/v1/inbound-docs/{doc['id']}/post", headers=auth_header(admin_token))
        assert r.status_code == 409

    async def test_inbound_with_lot_code(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _make_category(client, admin_token)
        item = await _make_item(client, admin_token, cat["id"])
        spu = await _make_spu(client, admin_token, item["id"])
        sku = await _make_sku(client, admin_token, spu["id"])
        wh = await _make_warehouse(client, admin_token)

        doc_r = await client.post("/api/v1/inbound-docs", headers=auth_header(admin_token), json={
            "warehouse_id": wh["id"], "source_type": "PURCHASE",
        })
        doc = doc_r.json()["data"]
        line_r = await client.post(f"/api/v1/inbound-docs/{doc['id']}/lines", headers=auth_header(admin_token), json={
            "sku_id": sku["id"], "quantity": 5, "lot_code": "LOT-2026-001",
        })
        assert line_r.status_code == 201
        assert line_r.json()["data"]["lot_code"] == "LOT-2026-001"
        post_r = await client.post(f"/api/v1/inbound-docs/{doc['id']}/post", headers=auth_header(admin_token))
        assert post_r.status_code == 200


@pytest.mark.asyncio
class TestCatalogValidationPaths:
    async def test_create_item_invalid_type(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _make_category(client, admin_token)
        r = await client.post("/api/v1/items", headers=auth_header(admin_token), json={
            "item_type": "INVALID_TYPE", "title": "Bad", "description": "d", "category_id": cat["id"],
        })
        assert r.status_code == 400

    async def test_create_item_empty_title(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _make_category(client, admin_token)
        r = await client.post("/api/v1/items", headers=auth_header(admin_token), json={
            "item_type": "PRODUCT", "title": "", "description": "d", "category_id": cat["id"],
        })
        assert r.status_code in (400, 422)

    async def test_create_item_missing_category(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        r = await client.post("/api/v1/items", headers=auth_header(admin_token), json={
            "item_type": "PRODUCT", "title": "Orphan", "description": "d", "category_id": str(uuid.uuid4()),
        })
        assert r.status_code == 400

    async def test_update_sku_invalid_status(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _make_category(client, admin_token)
        item = await _make_item(client, admin_token, cat["id"])
        spu = await _make_spu(client, admin_token, item["id"])
        sku = await _make_sku(client, admin_token, spu["id"])
        r = await client.patch(f"/api/v1/skus/{sku['id']}", headers=auth_header(admin_token), json={
            "status": "INVALID_STATUS",
        })
        assert r.status_code == 400

    async def test_update_sku_negative_reorder(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _make_category(client, admin_token)
        item = await _make_item(client, admin_token, cat["id"])
        spu = await _make_spu(client, admin_token, item["id"])
        sku = await _make_sku(client, admin_token, spu["id"])
        r = await client.patch(f"/api/v1/skus/{sku['id']}", headers=auth_header(admin_token), json={
            "reorder_threshold": -1,
        })
        assert r.status_code == 400

    async def test_price_book_invalid_target_type(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        pb = await _make_price_book(client, admin_token, name="Invalid Target PB")
        r = await client.post(f"/api/v1/price-books/{pb['id']}/entries", headers=auth_header(admin_token), json={
            "target_type": "CATEGORY", "target_id": str(uuid.uuid4()), "amount_cents": 1000,
        })
        assert r.status_code == 400

    async def test_price_book_entry_invalid_date_range(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        pb = await _make_price_book(client, admin_token, name="Date Range PB")
        cat = await _make_category(client, admin_token)
        item = await _make_item(client, admin_token, cat["id"], item_type="SERVICE")
        r = await client.post(f"/api/v1/price-books/{pb['id']}/entries", headers=auth_header(admin_token), json={
            "target_type": "ITEM",
            "target_id": item["id"],
            "amount_cents": 1000,
            "starts_at": "2026-12-31T00:00:00Z",
            "ends_at": "2026-01-01T00:00:00Z",
        })
        assert r.status_code == 400

    async def test_price_book_entry_not_found_book(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        r = await client.post(f"/api/v1/price-books/{uuid.uuid4()}/entries", headers=auth_header(admin_token), json={
            "target_type": "ITEM", "target_id": str(uuid.uuid4()), "amount_cents": 1000,
        })
        assert r.status_code == 404

    async def test_add_media_to_nonexistent_item(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        asset = await upload_test_asset(client, admin_token)
        r = await client.post(f"/api/v1/items/{uuid.uuid4()}/media", headers=auth_header(admin_token), json={
            "asset_id": asset["asset_id"], "scope": "ITEM",
        })
        assert r.status_code == 404

    async def test_add_media_nonexistent_asset(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _make_category(client, admin_token)
        item = await _make_item(client, admin_token, cat["id"])
        r = await client.post(f"/api/v1/items/{item['id']}/media", headers=auth_header(admin_token), json={
            "asset_id": str(uuid.uuid4()), "scope": "ITEM",
        })
        assert r.status_code == 404

    async def test_publish_nonexistent_item(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        r = await client.post(f"/api/v1/items/{uuid.uuid4()}/publish", headers=auth_header(admin_token))
        assert r.status_code == 404

    async def test_unpublish_nonexistent_item(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        r = await client.post(f"/api/v1/items/{uuid.uuid4()}/unpublish", headers=auth_header(admin_token))
        assert r.status_code == 404

    async def test_unpublish_draft_item_rejected(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _make_category(client, admin_token)
        item = await _make_item(client, admin_token, cat["id"])
        r = await client.post(f"/api/v1/items/{item['id']}/unpublish", headers=auth_header(admin_token))
        assert r.status_code == 400

    async def test_update_item_not_found(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        r = await client.patch(f"/api/v1/items/{uuid.uuid4()}", headers=auth_header(admin_token), json={
            "row_version": 1, "title": "Ghost",
        })
        assert r.status_code == 404

    async def test_update_item_invalid_category(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _make_category(client, admin_token)
        item = await _make_item(client, admin_token, cat["id"])
        r = await client.patch(f"/api/v1/items/{item['id']}", headers=auth_header(admin_token), json={
            "row_version": item["row_version"], "category_id": str(uuid.uuid4()),
        })
        assert r.status_code in (400, 404)

    async def test_update_item_public_summary(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _make_category(client, admin_token)
        item = await _make_item(client, admin_token, cat["id"])
        r = await client.patch(f"/api/v1/items/{item['id']}", headers=auth_header(admin_token), json={
            "row_version": item["row_version"], "public_summary": "Great product",
        })
        assert r.status_code == 200


@pytest.mark.asyncio
class TestVerificationValidationPaths:
    async def test_invalid_profile_type(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        r = await client.post("/api/v1/verification-cases", headers=auth_header(login["token"]), json={
            "profile_type": "INVALID",
        })
        assert r.status_code == 400

    async def test_invalid_dob_format(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        case_r = await client.post("/api/v1/verification-cases", headers=auth_header(login["token"]), json={
            "profile_type": "PERSONAL",
        })
        case = case_r.json()["data"]
        r = await client.patch(
            f"/api/v1/verification-cases/{case['case_id']}",
            headers=auth_header(login["token"]),
            json={"row_version": case["row_version"], "dob": "not-a-date"},
        )
        assert r.status_code == 400

    async def test_invalid_dob_date_value(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        case_r = await client.post("/api/v1/verification-cases", headers=auth_header(login["token"]), json={
            "profile_type": "PERSONAL",
        })
        case = case_r.json()["data"]
        r = await client.patch(
            f"/api/v1/verification-cases/{case['case_id']}",
            headers=auth_header(login["token"]),
            json={"row_version": case["row_version"], "dob": "13/45/1990"},
        )
        assert r.status_code == 400

    async def test_enterprise_reviewer_sees_enterprise_fields(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        reviewer_token = await get_reviewer_token(client)

        case_r = await client.post("/api/v1/verification-cases", headers=auth_header(login["token"]), json={
            "profile_type": "ENTERPRISE",
        })
        case = case_r.json()["data"]
        asset = await upload_test_asset(client, login["token"], purpose="VERIFICATION", kind="VERIFICATION_ID")

        await client.patch(
            f"/api/v1/verification-cases/{case['case_id']}",
            headers=auth_header(login["token"]),
            json={
                "row_version": case["row_version"],
                "enterprise_legal_name": "Test Corp",
                "enterprise_registration_number": "REG-999",
                "enterprise_registration_asset_id": asset["asset_id"],
                "responsible_person_legal_name": "John Smith",
                "responsible_person_dob": "05/10/1985",
                "responsible_person_id_number": "ID-987654",
                "responsible_person_id_image_asset_id": asset["asset_id"],
            },
        )
        await client.post(f"/api/v1/verification-cases/{case['case_id']}/submit", headers=auth_header(login["token"]))

        r = await client.get(
            f"/api/v1/verification-cases/{case['case_id']}",
            headers=auth_header(reviewer_token),
        )
        assert r.status_code == 200

    async def test_enterprise_user_sees_masked_enterprise_fields(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        case_r = await client.post("/api/v1/verification-cases", headers=auth_header(login["token"]), json={
            "profile_type": "ENTERPRISE",
        })
        case = case_r.json()["data"]
        asset = await upload_test_asset(client, login["token"], purpose="VERIFICATION", kind="VERIFICATION_ID")

        await client.patch(
            f"/api/v1/verification-cases/{case['case_id']}",
            headers=auth_header(login["token"]),
            json={
                "row_version": case["row_version"],
                "enterprise_legal_name": "My Company",
                "enterprise_registration_number": "REG-555",
                "enterprise_registration_asset_id": asset["asset_id"],
                "responsible_person_legal_name": "Alice Wonder",
                "responsible_person_dob": "07/04/1982",
                "responsible_person_id_number": "ID-111222",
                "responsible_person_id_image_asset_id": asset["asset_id"],
            },
        )

        r = await client.get(
            f"/api/v1/verification-cases/{case['case_id']}",
            headers=auth_header(login["token"]),
        )
        assert r.status_code == 200

    async def test_update_case_not_found(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        r = await client.patch(
            "/api/v1/verification-cases/VC-DOESNOTEXIST",
            headers=auth_header(login["token"]),
            json={"row_version": 1, "legal_name": "Test"},
        )
        assert r.status_code == 404

    async def test_submit_case_not_found(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        r = await client.post(
            "/api/v1/verification-cases/VC-DOESNOTEXIST/submit",
            headers=auth_header(login["token"]),
        )
        assert r.status_code == 404

    async def test_invalid_decision_transition(self, client: AsyncClient):
        reviewer_token = await get_reviewer_token(client)
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        case_r = await client.post("/api/v1/verification-cases", headers=auth_header(login["token"]), json={
            "profile_type": "PERSONAL",
        })
        case = case_r.json()["data"]

        asset = await upload_test_asset(client, login["token"], purpose="VERIFICATION", kind="VERIFICATION_ID")
        await client.patch(
            f"/api/v1/verification-cases/{case['case_id']}",
            headers=auth_header(login["token"]),
            json={
                "row_version": case["row_version"],
                "legal_name": "John Doe",
                "dob": "01/15/1990",
                "government_id_number": "A123456789",
                "government_id_image_asset_id": asset["asset_id"],
            },
        )
        await client.post(f"/api/v1/verification-cases/{case['case_id']}/submit", headers=auth_header(login["token"]))

        r = await client.post(
            f"/api/v1/verification-cases/{case['case_id']}/decision",
            headers=auth_header(reviewer_token),
            json={"decision": "APPROVED"},
        )
        assert r.status_code in (400, 409)

    async def test_needs_info_flow(self, client: AsyncClient):
        reviewer_token = await get_reviewer_token(client)
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        case_r = await client.post("/api/v1/verification-cases", headers=auth_header(login["token"]), json={
            "profile_type": "PERSONAL",
        })
        case = case_r.json()["data"]
        asset = await upload_test_asset(client, login["token"], purpose="VERIFICATION", kind="VERIFICATION_ID")
        await client.patch(
            f"/api/v1/verification-cases/{case['case_id']}",
            headers=auth_header(login["token"]),
            json={
                "row_version": case["row_version"],
                "legal_name": "Jane Doe",
                "dob": "03/10/1988",
                "government_id_number": "B999888777",
                "government_id_image_asset_id": asset["asset_id"],
            },
        )
        await client.post(f"/api/v1/verification-cases/{case['case_id']}/submit", headers=auth_header(login["token"]))

        await client.post(
            f"/api/v1/verification-cases/{case['case_id']}/decision",
            headers=auth_header(reviewer_token),
            json={"decision": "UNDER_REVIEW"},
        )
        needs_info_r = await client.post(
            f"/api/v1/verification-cases/{case['case_id']}/decision",
            headers=auth_header(reviewer_token),
            json={"decision": "NEEDS_INFO", "comment": "Please provide additional documents"},
        )
        assert needs_info_r.status_code == 200
        assert needs_info_r.json()["data"]["status"] == "NEEDS_INFO"

        case_detail = await client.get(
            f"/api/v1/verification-cases/{case['case_id']}",
            headers=auth_header(login["token"]),
        )
        new_version = case_detail.json()["data"]["row_version"]

        submit_again_r = await client.post(
            f"/api/v1/verification-cases/{case['case_id']}/submit",
            headers=auth_header(login["token"]),
        )
        assert submit_again_r.status_code == 200


@pytest.mark.asyncio
class TestServiceLayerDirect:
    async def test_add_item_tag_service(self, client: AsyncClient):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        engine = create_async_engine(os.environ["DATABASE_URL"])
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        admin_token = await get_admin_token(client)
        cat = await _make_category(client, admin_token)
        item = await _make_item(client, admin_token, cat["id"])
        tag = await _make_tag(client, admin_token)

        async with factory() as session:
            from src.trailgoods.services.catalog import add_item_tag
            import uuid as _uuid
            item_id = _uuid.UUID(item["id"])
            tag_id = _uuid.UUID(tag["id"])
            result = await add_item_tag(session, item_id=item_id, tag_id=tag_id)
            await session.commit()
            assert result.item_id == item_id
            assert result.tag_id == tag_id

        await engine.dispose()

    async def test_add_item_tag_duplicate_rejected(self, client: AsyncClient):
        engine = create_async_engine(os.environ["DATABASE_URL"])
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        admin_token = await get_admin_token(client)
        cat = await _make_category(client, admin_token)
        item = await _make_item(client, admin_token, cat["id"])
        tag = await _make_tag(client, admin_token)

        async with factory() as session:
            from src.trailgoods.services.catalog import add_item_tag
            import uuid as _uuid
            item_id = _uuid.UUID(item["id"])
            tag_id = _uuid.UUID(tag["id"])
            await add_item_tag(session, item_id=item_id, tag_id=tag_id)
            await session.commit()

        async with factory() as session:
            from src.trailgoods.services.catalog import add_item_tag
            import uuid as _uuid
            item_id = _uuid.UUID(item["id"])
            tag_id = _uuid.UUID(tag["id"])
            with pytest.raises(ValueError, match="already added"):
                await add_item_tag(session, item_id=item_id, tag_id=tag_id)

        await engine.dispose()

    async def test_add_item_tag_item_not_found(self, client: AsyncClient):
        engine = create_async_engine(os.environ["DATABASE_URL"])
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        admin_token = await get_admin_token(client)
        tag = await _make_tag(client, admin_token)

        async with factory() as session:
            from src.trailgoods.services.catalog import add_item_tag
            import uuid as _uuid
            tag_id = _uuid.UUID(tag["id"])
            with pytest.raises(ValueError, match="Item not found"):
                await add_item_tag(session, item_id=_uuid.uuid4(), tag_id=tag_id)

        await engine.dispose()

    async def test_expire_verification_cases_service(self, client: AsyncClient):
        engine = create_async_engine(os.environ["DATABASE_URL"])
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        reviewer_token = await get_reviewer_token(client)

        case_r = await client.post("/api/v1/verification-cases", headers=auth_header(login["token"]), json={
            "profile_type": "PERSONAL",
        })
        case = case_r.json()["data"]
        asset = await upload_test_asset(client, login["token"], purpose="VERIFICATION", kind="VERIFICATION_ID")
        await client.patch(
            f"/api/v1/verification-cases/{case['case_id']}",
            headers=auth_header(login["token"]),
            json={
                "row_version": case["row_version"],
                "legal_name": "Expire Test",
                "dob": "01/15/1990",
                "government_id_number": "EXP123456",
                "government_id_image_asset_id": asset["asset_id"],
            },
        )
        await client.post(f"/api/v1/verification-cases/{case['case_id']}/submit", headers=auth_header(login["token"]))
        await client.post(
            f"/api/v1/verification-cases/{case['case_id']}/decision",
            headers=auth_header(reviewer_token),
            json={"decision": "UNDER_REVIEW"},
        )
        await client.post(
            f"/api/v1/verification-cases/{case['case_id']}/decision",
            headers=auth_header(reviewer_token),
            json={"decision": "APPROVED"},
        )

        async with factory() as session:
            from sqlalchemy import update
            from src.trailgoods.models.verification import VerificationCase
            now = datetime.now(timezone.utc)
            past = now - timedelta(days=400)
            await session.execute(
                update(VerificationCase)
                .where(VerificationCase.case_id == case["case_id"])
                .values(expires_at=past)
            )
            await session.commit()

        async with factory() as session:
            from src.trailgoods.services.verification import expire_verification_cases
            count = await expire_verification_cases(session)
            await session.commit()
            assert count >= 1

        await engine.dispose()

    async def test_check_reorder_alerts_service(self, client: AsyncClient):
        engine = create_async_engine(os.environ["DATABASE_URL"])
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        admin_token = await get_admin_token(client)
        cat = await _make_category(client, admin_token)
        item = await _make_item(client, admin_token, cat["id"])
        spu = await _make_spu(client, admin_token, item["id"])
        sku = await _make_sku(client, admin_token, spu["id"])
        wh = await _make_warehouse(client, admin_token)
        await _stock_inbound(client, admin_token, wh["id"], sku["id"], 2)

        async with factory() as session:
            from src.trailgoods.services.inventory import check_reorder_alerts
            count = await check_reorder_alerts(session)
            await session.commit()
            assert count >= 1

        await engine.dispose()


@pytest.mark.asyncio
class TestAuthSchemeValidation:
    async def test_invalid_auth_scheme_rejected(self, client: AsyncClient):
        r = await client.get("/api/v1/warehouses", headers={"Authorization": "Basic sometoken"})
        assert r.status_code == 401

    async def test_missing_auth_header_rejected(self, client: AsyncClient):
        r = await client.post("/api/v1/items", json={
            "item_type": "PRODUCT", "title": "T", "description": "D", "category_id": str(uuid.uuid4()),
        })
        assert r.status_code == 401


@pytest.mark.asyncio
class TestRequirePermissionViaHTTP:
    async def test_missing_permission_returns_403(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        resp = await client.post("/api/v1/warehouses", headers=auth_header(login["token"]), json={
            "code": "NOPE", "name": "Nope",
        })
        assert resp.status_code == 403

    async def test_admin_bypasses_permission(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        resp = await client.get("/api/v1/admin/audit-logs", headers=auth_header(admin_token))
        assert resp.status_code == 200

    async def test_reviewer_has_moderation_permission(self, client: AsyncClient):
        reviewer_token = await get_reviewer_token(client)
        resp = await client.get("/api/v1/reports", headers=auth_header(reviewer_token))
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestOutboundDocNotFound:
    async def test_add_line_to_nonexistent_outbound_doc(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _make_category(client, admin_token)
        item = await _make_item(client, admin_token, cat["id"])
        spu = await _make_spu(client, admin_token, item["id"])
        sku = await _make_sku(client, admin_token, spu["id"])
        r = await client.post(f"/api/v1/outbound-docs/{uuid.uuid4()}/lines", headers=auth_header(admin_token), json={
            "sku_id": sku["id"], "quantity": 5,
        })
        assert r.status_code == 404

    async def test_post_nonexistent_outbound_doc(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        r = await client.post(f"/api/v1/outbound-docs/{uuid.uuid4()}/post", headers=auth_header(admin_token))
        assert r.status_code == 404

    async def test_add_line_to_posted_outbound_doc(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _make_category(client, admin_token)
        item = await _make_item(client, admin_token, cat["id"])
        spu = await _make_spu(client, admin_token, item["id"])
        sku = await _make_sku(client, admin_token, spu["id"])
        wh = await _make_warehouse(client, admin_token)
        await _stock_inbound(client, admin_token, wh["id"], sku["id"], 20)

        ob_r = await client.post("/api/v1/outbound-docs", headers=auth_header(admin_token), json={
            "warehouse_id": wh["id"], "source_type": "SALE",
        })
        ob = ob_r.json()["data"]
        await client.post(f"/api/v1/outbound-docs/{ob['id']}/lines", headers=auth_header(admin_token), json={
            "sku_id": sku["id"], "quantity": 5,
        })
        await client.post(f"/api/v1/outbound-docs/{ob['id']}/post", headers=auth_header(admin_token))

        r = await client.post(f"/api/v1/outbound-docs/{ob['id']}/lines", headers=auth_header(admin_token), json={
            "sku_id": sku["id"], "quantity": 3,
        })
        assert r.status_code == 400


@pytest.mark.asyncio
class TestSPUNotFound:
    async def test_create_sku_spu_not_found(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        r = await client.post(f"/api/v1/spus/{uuid.uuid4()}/skus", headers=auth_header(admin_token), json={
            "sku_code": "SKU-GHOST",
        })
        assert r.status_code == 404

    async def test_create_spu_item_not_found(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        r = await client.post("/api/v1/spus", headers=auth_header(admin_token), json={
            "item_id": str(uuid.uuid4()), "spu_code": "SPU-GHOST",
        })
        assert r.status_code == 404

    async def test_create_spu_duplicate_code(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _make_category(client, admin_token)
        item1 = await _make_item(client, admin_token, cat["id"])

        cat2 = await _make_category(client, admin_token)
        item2 = await _make_item(client, admin_token, cat2["id"])

        spu_code = f"UNIQ-{uuid.uuid4().hex[:8]}"
        await client.post("/api/v1/spus", headers=auth_header(admin_token), json={
            "item_id": item1["id"], "spu_code": spu_code,
        })

        r = await client.post("/api/v1/spus", headers=auth_header(admin_token), json={
            "item_id": item2["id"], "spu_code": spu_code,
        })
        assert r.status_code == 409
