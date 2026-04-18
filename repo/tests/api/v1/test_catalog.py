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


async def _create_category(client: AsyncClient, token: str, name: str = "Outdoor Gear", slug: str = None) -> dict:
    slug = slug or f"cat-{uuid.uuid4().hex[:8]}"
    resp = await client.post("/api/v1/categories", headers=auth_header(token), json={
        "name": name, "slug": slug,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


async def _create_tag(client: AsyncClient, token: str, name: str = "hiking", slug: str = None) -> dict:
    slug = slug or f"tag-{uuid.uuid4().hex[:8]}"
    resp = await client.post("/api/v1/tags", headers=auth_header(token), json={
        "name": name, "slug": slug,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


async def _create_price_book(client: AsyncClient, token: str, name: str = "Default", is_default: bool = True) -> dict:
    resp = await client.post("/api/v1/price-books", headers=auth_header(token), json={
        "name": name, "is_default": is_default,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


async def _create_full_product(client: AsyncClient, admin_token: str) -> dict:
    cat = await _create_category(client, admin_token)
    asset = await upload_test_asset(client, admin_token)

    resp = await client.post("/api/v1/items", headers=auth_header(admin_token), json={
        "item_type": "PRODUCT",
        "title": "Trail Running Shoes",
        "description": "High-performance trail running shoes for rough terrain.",
        "category_id": cat["id"],
    })
    assert resp.status_code == 201, resp.text
    item = resp.json()["data"]

    await client.post("/api/v1/items/{}/media".format(item["id"]), headers=auth_header(admin_token), json={
        "asset_id": asset["asset_id"],
        "scope": "ITEM",
    })

    spu_resp = await client.post("/api/v1/spus", headers=auth_header(admin_token), json={
        "item_id": item["id"],
        "spu_code": f"SPU-{uuid.uuid4().hex[:8]}",
    })
    assert spu_resp.status_code == 201, spu_resp.text
    spu = spu_resp.json()["data"]

    sku_resp = await client.post(f"/api/v1/spus/{spu['id']}/skus", headers=auth_header(admin_token), json={
        "sku_code": f"SKU-{uuid.uuid4().hex[:8]}",
    })
    assert sku_resp.status_code == 201, sku_resp.text
    sku = sku_resp.json()["data"]

    pb = await _create_price_book(client, admin_token)
    entry_resp = await client.post(f"/api/v1/price-books/{pb['id']}/entries", headers=auth_header(admin_token), json={
        "target_type": "SKU",
        "target_id": sku["id"],
        "amount_cents": 12999,
    })
    assert entry_resp.status_code == 201, entry_resp.text

    return {"item": item, "spu": spu, "sku": sku, "category": cat, "price_book": pb}


@pytest.mark.asyncio
class TestCategories:
    async def test_create_category(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _create_category(client, admin_token, "Camping", "camping")
        assert cat["name"] == "Camping"
        assert cat["slug"] == "camping"

    async def test_list_categories(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        await _create_category(client, admin_token, "Hiking", "hiking-cat")
        resp = await client.get("/api/v1/categories")
        assert resp.status_code == 200
        assert len(resp.json()["data"]) >= 1

    async def test_non_admin_cannot_create_category(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        resp = await client.post("/api/v1/categories", headers=auth_header(login["token"]), json={
            "name": "Forbidden", "slug": "forbidden",
        })
        assert resp.status_code == 403


@pytest.mark.asyncio
class TestTags:
    async def test_create_and_list_tags(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        await _create_tag(client, admin_token, "waterproof", "waterproof")
        resp = await client.get("/api/v1/tags")
        assert resp.status_code == 200
        assert len(resp.json()["data"]) >= 1


@pytest.mark.asyncio
class TestItemCRUD:
    async def test_admin_create_product(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _create_category(client, admin_token)

        resp = await client.post("/api/v1/items", headers=auth_header(admin_token), json={
            "item_type": "PRODUCT",
            "title": "Hiking Boots",
            "description": "Durable waterproof hiking boots.",
            "category_id": cat["id"],
        })
        assert resp.status_code == 201
        item = resp.json()["data"]
        assert item["type"] == "PRODUCT"
        assert item["status"] == "DRAFT"

    async def test_instructor_create_service(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _create_category(client, admin_token)

        reg = await register_user(client, "instructor1")
        login = await login_user(client, reg["username"], reg["password"])

        await client.post("/api/v1/admin/roles/assign", headers=auth_header(admin_token), json={
            "user_id": reg["user"]["id"],
            "role_name": "Instructor",
        })

        login2 = await login_user(client, reg["username"], reg["password"])

        resp = await client.post("/api/v1/items", headers=auth_header(login2["token"]), json={
            "item_type": "SERVICE",
            "title": "Guided Mountain Hike",
            "description": "A 3-day guided hike through the Rockies.",
            "category_id": cat["id"],
        })
        assert resp.status_code == 201
        assert resp.json()["data"]["type"] == "SERVICE"

    async def test_instructor_cannot_create_product(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _create_category(client, admin_token)

        reg = await register_user(client, "instructor2")
        login = await login_user(client, reg["username"], reg["password"])

        await client.post("/api/v1/admin/roles/assign", headers=auth_header(admin_token), json={
            "user_id": reg["user"]["id"],
            "role_name": "Instructor",
        })

        login2 = await login_user(client, reg["username"], reg["password"])

        resp = await client.post("/api/v1/items", headers=auth_header(login2["token"]), json={
            "item_type": "PRODUCT",
            "title": "Not Allowed",
            "description": "Should fail.",
            "category_id": cat["id"],
        })
        assert resp.status_code == 403

    async def test_regular_user_cannot_create_item(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _create_category(client, admin_token)

        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        resp = await client.post("/api/v1/items", headers=auth_header(login["token"]), json={
            "item_type": "SERVICE",
            "title": "Nope",
            "description": "Should fail too.",
            "category_id": cat["id"],
        })
        assert resp.status_code == 403

    async def test_update_item(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _create_category(client, admin_token)

        resp = await client.post("/api/v1/items", headers=auth_header(admin_token), json={
            "item_type": "PRODUCT", "title": "Original", "description": "Desc.", "category_id": cat["id"],
        })
        item = resp.json()["data"]

        resp2 = await client.patch(f"/api/v1/items/{item['id']}", headers=auth_header(admin_token), json={
            "row_version": item["row_version"],
            "title": "Updated Title",
        })
        assert resp2.status_code == 200
        assert resp2.json()["data"]["title"] == "Updated Title"


@pytest.mark.asyncio
class TestSPUAndSKU:
    async def test_create_spu_and_sku(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _create_category(client, admin_token)

        resp = await client.post("/api/v1/items", headers=auth_header(admin_token), json={
            "item_type": "PRODUCT", "title": "Jacket", "description": "Warm jacket.", "category_id": cat["id"],
        })
        item = resp.json()["data"]

        spu_resp = await client.post("/api/v1/spus", headers=auth_header(admin_token), json={
            "item_id": item["id"], "spu_code": "SPU-JACKET-001",
        })
        assert spu_resp.status_code == 201
        spu = spu_resp.json()["data"]

        sku_resp = await client.post(f"/api/v1/spus/{spu['id']}/skus", headers=auth_header(admin_token), json={
            "sku_code": "SKU-JACKET-S",
        })
        assert sku_resp.status_code == 201
        sku = sku_resp.json()["data"]
        assert sku["sku_code"] == "SKU-JACKET-S"

    async def test_duplicate_sku_code_rejected(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _create_category(client, admin_token)

        resp = await client.post("/api/v1/items", headers=auth_header(admin_token), json={
            "item_type": "PRODUCT", "title": "Tent", "description": "Camping tent.", "category_id": cat["id"],
        })
        item = resp.json()["data"]

        spu_resp = await client.post("/api/v1/spus", headers=auth_header(admin_token), json={
            "item_id": item["id"], "spu_code": "SPU-TENT-001",
        })
        spu = spu_resp.json()["data"]

        await client.post(f"/api/v1/spus/{spu['id']}/skus", headers=auth_header(admin_token), json={
            "sku_code": "DUP-CODE",
        })
        resp2 = await client.post(f"/api/v1/spus/{spu['id']}/skus", headers=auth_header(admin_token), json={
            "sku_code": "DUP-CODE",
        })
        assert resp2.status_code == 409


@pytest.mark.asyncio
class TestPublishing:
    async def test_publish_complete_product(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        data = await _create_full_product(client, admin_token)

        resp = await client.post(
            f"/api/v1/items/{data['item']['id']}/publish",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200, f"Publish failed: {resp.text}"
        assert resp.json()["data"]["status"] == "PUBLISHED"

    async def test_publish_without_price_fails(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _create_category(client, admin_token)
        asset = await upload_test_asset(client, admin_token)

        resp = await client.post("/api/v1/items", headers=auth_header(admin_token), json={
            "item_type": "PRODUCT", "title": "No Price", "description": "Missing price.", "category_id": cat["id"],
        })
        item = resp.json()["data"]

        await client.post(f"/api/v1/items/{item['id']}/media", headers=auth_header(admin_token), json={
            "asset_id": asset["asset_id"], "scope": "ITEM",
        })

        spu_r = await client.post("/api/v1/spus", headers=auth_header(admin_token), json={
            "item_id": item["id"], "spu_code": f"SPU-NP-{uuid.uuid4().hex[:6]}",
        })
        spu = spu_r.json()["data"]
        await client.post(f"/api/v1/spus/{spu['id']}/skus", headers=auth_header(admin_token), json={
            "sku_code": "SKU-NP",
        })

        resp2 = await client.post(
            f"/api/v1/items/{item['id']}/publish",
            headers=auth_header(admin_token),
        )
        assert resp2.status_code == 400

    async def test_publish_without_image_fails(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _create_category(client, admin_token)

        resp = await client.post("/api/v1/items", headers=auth_header(admin_token), json={
            "item_type": "SERVICE", "title": "No Image", "description": "No media.", "category_id": cat["id"],
        })
        item = resp.json()["data"]

        resp2 = await client.post(
            f"/api/v1/items/{item['id']}/publish",
            headers=auth_header(admin_token),
        )
        assert resp2.status_code == 400

    async def test_unpublish(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        data = await _create_full_product(client, admin_token)

        await client.post(
            f"/api/v1/items/{data['item']['id']}/publish",
            headers=auth_header(admin_token),
        )
        resp = await client.post(
            f"/api/v1/items/{data['item']['id']}/unpublish",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "UNPUBLISHED"


@pytest.mark.asyncio
class TestPublicCatalog:
    async def test_public_catalog_list(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        data = await _create_full_product(client, admin_token)
        await client.post(
            f"/api/v1/items/{data['item']['id']}/publish",
            headers=auth_header(admin_token),
        )

        resp = await client.get("/api/v1/catalog/items")
        assert resp.status_code == 200
        items = resp.json()["data"]
        assert len(items) >= 1

    async def test_unpublished_not_visible_to_guest(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cat = await _create_category(client, admin_token)

        resp = await client.post("/api/v1/items", headers=auth_header(admin_token), json={
            "item_type": "SERVICE", "title": "Draft Item", "description": "Not published.", "category_id": cat["id"],
        })
        item = resp.json()["data"]

        resp2 = await client.get(f"/api/v1/items/{item['id']}")
        assert resp2.status_code in (401, 404)

    async def test_catalog_search(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        data = await _create_full_product(client, admin_token)
        await client.post(
            f"/api/v1/items/{data['item']['id']}/publish",
            headers=auth_header(admin_token),
        )

        resp = await client.get("/api/v1/catalog/items", params={"search": "Trail Running"})
        assert resp.status_code == 200
        items = resp.json()["data"]
        assert any("Trail" in i.get("title", "") for i in items)


@pytest.mark.asyncio
class TestPricing:
    async def test_create_price_book_and_entry(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        pb = await _create_price_book(client, admin_token, "Retail Prices")

        cat = await _create_category(client, admin_token)
        resp = await client.post("/api/v1/items", headers=auth_header(admin_token), json={
            "item_type": "SERVICE", "title": "Service Item", "description": "A service.", "category_id": cat["id"],
        })
        item = resp.json()["data"]

        entry_resp = await client.post(f"/api/v1/price-books/{pb['id']}/entries", headers=auth_header(admin_token), json={
            "target_type": "ITEM",
            "target_id": item["id"],
            "amount_cents": 4999,
        })
        assert entry_resp.status_code == 201
        assert entry_resp.json()["data"]["amount_cents"] == 4999

    async def test_price_entry_zero_rejected(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        pb = await _create_price_book(client, admin_token, "Zero Test")
        cat = await _create_category(client, admin_token, slug=f"zp-{uuid.uuid4().hex[:6]}")

        item_resp = await client.post("/api/v1/items", headers=auth_header(admin_token), json={
            "item_type": "SERVICE", "title": "ZP", "description": "d.", "category_id": cat["id"],
        })
        item = item_resp.json()["data"]

        resp = await client.post(f"/api/v1/price-books/{pb['id']}/entries", headers=auth_header(admin_token), json={
            "target_type": "ITEM",
            "target_id": item["id"],
            "amount_cents": 0,
        })
        assert resp.status_code == 400
