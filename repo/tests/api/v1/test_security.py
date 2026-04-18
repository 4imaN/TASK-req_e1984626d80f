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


async def _setup_published_product(client: AsyncClient, admin_token: str) -> dict:
    wh_resp = await client.post("/api/v1/warehouses", headers=auth_header(admin_token), json={
        "code": f"WH-{uuid.uuid4().hex[:6].upper()}", "name": "WH",
    })
    wh = wh_resp.json()["data"]

    cat_resp = await client.post("/api/v1/categories", headers=auth_header(admin_token), json={
        "name": "Cat", "slug": f"cat-{uuid.uuid4().hex[:6]}",
    })
    cat = cat_resp.json()["data"]

    asset = await upload_test_asset(client, admin_token)

    item_resp = await client.post("/api/v1/items", headers=auth_header(admin_token), json={
        "item_type": "PRODUCT", "title": "Test Product", "description": "desc.",
        "category_id": cat["id"],
    })
    item = item_resp.json()["data"]

    await client.post(f"/api/v1/items/{item['id']}/media", headers=auth_header(admin_token), json={
        "asset_id": asset["asset_id"], "scope": "ITEM",
    })

    spu_resp = await client.post("/api/v1/spus", headers=auth_header(admin_token), json={
        "item_id": item["id"], "spu_code": f"SPU-{uuid.uuid4().hex[:6]}",
    })
    spu = spu_resp.json()["data"]

    sku_resp = await client.post(f"/api/v1/spus/{spu['id']}/skus", headers=auth_header(admin_token), json={
        "sku_code": f"SKU-{uuid.uuid4().hex[:6]}",
    })
    sku = sku_resp.json()["data"]

    pb_resp = await client.post("/api/v1/price-books", headers=auth_header(admin_token), json={
        "name": f"PB-{uuid.uuid4().hex[:6]}", "is_default": True,
    })
    if pb_resp.status_code == 201:
        pb_id = pb_resp.json()["data"]["id"]
    else:
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        import os
        engine = create_async_engine(os.environ["DATABASE_URL"])
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as db:
            from sqlalchemy import select
            from src.trailgoods.models.catalog import PriceBook
            r = await db.execute(select(PriceBook).where(PriceBook.is_default == True))
            pb_id = str(r.scalar_one().id)
        await engine.dispose()

    await client.post(f"/api/v1/price-books/{pb_id}/entries", headers=auth_header(admin_token), json={
        "target_type": "SKU", "target_id": sku["id"], "amount_cents": 500,
    })

    await client.post(f"/api/v1/items/{item['id']}/publish", headers=auth_header(admin_token))

    doc_resp = await client.post("/api/v1/inbound-docs", headers=auth_header(admin_token), json={
        "warehouse_id": wh["id"], "source_type": "PURCHASE",
    })
    doc = doc_resp.json()["data"]
    await client.post(f"/api/v1/inbound-docs/{doc['id']}/lines", headers=auth_header(admin_token), json={
        "sku_id": sku["id"], "quantity": 100,
    })
    await client.post(f"/api/v1/inbound-docs/{doc['id']}/post", headers=auth_header(admin_token))

    return {"warehouse": wh, "item": item, "sku": sku}


async def _create_order(client, token, item_id, sku_id, warehouse_id, quantity=2):
    resp = await client.post("/api/v1/orders", headers=auth_header(token), json={
        "idempotency_key": f"order-{uuid.uuid4().hex}",
        "lines": [{
            "sku_id": sku_id, "item_id": item_id,
            "warehouse_id": warehouse_id, "quantity": quantity,
        }],
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


@pytest.mark.asyncio
class TestOrderOwnershipEnforcement:
    async def test_cannot_reserve_other_user_order(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        setup = await _setup_published_product(client, admin_token)

        owner_reg = await register_user(client)
        owner = await login_user(client, owner_reg["username"], owner_reg["password"])
        order = await _create_order(
            client, owner["token"], setup["item"]["id"], setup["sku"]["id"], setup["warehouse"]["id"],
        )

        attacker_reg = await register_user(client)
        attacker = await login_user(client, attacker_reg["username"], attacker_reg["password"])

        resp = await client.post(
            f"/api/v1/orders/{order['id']}/reserve",
            headers={**auth_header(attacker["token"]), "Idempotency-Key": f"evil-{uuid.uuid4().hex}"},
        )
        assert resp.status_code == 403

    async def test_cannot_deduct_other_user_order(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        setup = await _setup_published_product(client, admin_token)

        owner_reg = await register_user(client)
        owner = await login_user(client, owner_reg["username"], owner_reg["password"])
        order = await _create_order(
            client, owner["token"], setup["item"]["id"], setup["sku"]["id"], setup["warehouse"]["id"],
        )
        await client.post(
            f"/api/v1/orders/{order['id']}/reserve",
            headers={**auth_header(owner["token"]), "Idempotency-Key": f"rsv-{uuid.uuid4().hex}"},
        )

        attacker_reg = await register_user(client)
        attacker = await login_user(client, attacker_reg["username"], attacker_reg["password"])

        resp = await client.post(
            f"/api/v1/orders/{order['id']}/deduct",
            headers={**auth_header(attacker["token"]), "Idempotency-Key": f"evil-{uuid.uuid4().hex}"},
        )
        assert resp.status_code == 403

    async def test_cannot_cancel_other_user_order(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        setup = await _setup_published_product(client, admin_token)

        owner_reg = await register_user(client)
        owner = await login_user(client, owner_reg["username"], owner_reg["password"])
        order = await _create_order(
            client, owner["token"], setup["item"]["id"], setup["sku"]["id"], setup["warehouse"]["id"],
        )

        attacker_reg = await register_user(client)
        attacker = await login_user(client, attacker_reg["username"], attacker_reg["password"])

        resp = await client.post(
            f"/api/v1/orders/{order['id']}/cancel",
            headers=auth_header(attacker["token"]),
            json={"cancel_reason": "hijack attempt"},
        )
        assert resp.status_code == 403

    async def test_admin_can_cancel_any_order(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        setup = await _setup_published_product(client, admin_token)

        owner_reg = await register_user(client)
        owner = await login_user(client, owner_reg["username"], owner_reg["password"])
        order = await _create_order(
            client, owner["token"], setup["item"]["id"], setup["sku"]["id"], setup["warehouse"]["id"],
        )

        resp = await client.post(
            f"/api/v1/orders/{order['id']}/cancel",
            headers=auth_header(admin_token),
            json={"cancel_reason": "admin intervention"},
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestShareLinkOwnership:
    async def test_cannot_create_share_link_for_other_user_asset(self, client: AsyncClient):
        owner_reg = await register_user(client)
        owner = await login_user(client, owner_reg["username"], owner_reg["password"])
        asset = await upload_test_asset(client, owner["token"])

        attacker_reg = await register_user(client)
        attacker = await login_user(client, attacker_reg["username"], attacker_reg["password"])

        resp = await client.post(
            f"/api/v1/assets/{asset['asset_id']}/share-links",
            headers=auth_header(attacker["token"]),
            json={},
        )
        assert resp.status_code == 403

    async def test_admin_can_share_any_asset(self, client: AsyncClient):
        owner_reg = await register_user(client)
        owner = await login_user(client, owner_reg["username"], owner_reg["password"])
        asset = await upload_test_asset(client, owner["token"])

        admin_token = await get_admin_token(client)
        resp = await client.post(
            f"/api/v1/assets/{asset['asset_id']}/share-links",
            headers=auth_header(admin_token),
            json={},
        )
        assert resp.status_code == 201


@pytest.mark.asyncio
class TestUploadSessionOwnership:
    async def test_cannot_upload_part_to_other_user_session(self, client: AsyncClient):
        owner_reg = await register_user(client)
        owner = await login_user(client, owner_reg["username"], owner_reg["password"])

        content = b"owner content" * 100
        create_resp = await client.post(
            "/api/v1/assets/uploads",
            headers=auth_header(owner["token"]),
            json={
                "filename": "ownerfile.jpg", "mime_type": "image/jpeg",
                "total_size": len(content), "total_parts": 1,
                "kind": "IMAGE", "purpose": "GENERAL",
            },
        )
        upload_id = create_resp.json()["data"]["upload_session_id"]

        attacker_reg = await register_user(client)
        attacker = await login_user(client, attacker_reg["username"], attacker_reg["password"])

        resp = await client.put(
            f"/api/v1/assets/uploads/{upload_id}/parts/1",
            headers={**auth_header(attacker["token"]), "content-type": "application/octet-stream"},
            content=b"hijacked content",
        )
        assert resp.status_code == 403

    async def test_cannot_complete_other_user_session(self, client: AsyncClient):
        owner_reg = await register_user(client)
        owner = await login_user(client, owner_reg["username"], owner_reg["password"])

        content = b"completion test" * 100
        create_resp = await client.post(
            "/api/v1/assets/uploads",
            headers=auth_header(owner["token"]),
            json={
                "filename": "o.jpg", "mime_type": "image/jpeg",
                "total_size": len(content), "total_parts": 1,
                "kind": "IMAGE", "purpose": "GENERAL",
            },
        )
        upload_id = create_resp.json()["data"]["upload_session_id"]

        await client.put(
            f"/api/v1/assets/uploads/{upload_id}/parts/1",
            headers={**auth_header(owner["token"]), "content-type": "application/octet-stream"},
            content=content,
        )

        attacker_reg = await register_user(client)
        attacker = await login_user(client, attacker_reg["username"], attacker_reg["password"])

        resp = await client.post(
            f"/api/v1/assets/uploads/{upload_id}/complete",
            headers=auth_header(attacker["token"]),
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
class TestDraftItemVisibility:
    async def test_draft_item_not_visible_to_other_authenticated_user(self, client: AsyncClient):
        admin_token = await get_admin_token(client)

        cat_resp = await client.post("/api/v1/categories", headers=auth_header(admin_token), json={
            "name": "Draft", "slug": f"draft-{uuid.uuid4().hex[:6]}",
        })
        cat = cat_resp.json()["data"]

        resp = await client.post("/api/v1/items", headers=auth_header(admin_token), json={
            "item_type": "SERVICE", "title": "Hidden Draft", "description": "secret.",
            "category_id": cat["id"],
        })
        item = resp.json()["data"]

        attacker_reg = await register_user(client)
        attacker = await login_user(client, attacker_reg["username"], attacker_reg["password"])

        resp = await client.get(
            f"/api/v1/items/{item['id']}",
            headers=auth_header(attacker["token"]),
        )
        assert resp.status_code == 404

    async def test_draft_item_visible_to_admin(self, client: AsyncClient):
        admin_token = await get_admin_token(client)

        cat_resp = await client.post("/api/v1/categories", headers=auth_header(admin_token), json={
            "name": "Adm", "slug": f"adm-{uuid.uuid4().hex[:6]}",
        })
        cat = cat_resp.json()["data"]

        resp = await client.post("/api/v1/items", headers=auth_header(admin_token), json={
            "item_type": "SERVICE", "title": "Admin Visible Draft", "description": "d.",
            "category_id": cat["id"],
        })
        item = resp.json()["data"]

        resp2 = await client.get(
            f"/api/v1/items/{item['id']}",
            headers=auth_header(admin_token),
        )
        assert resp2.status_code == 200


@pytest.mark.asyncio
class TestAssetOwnershipInAttachments:
    async def test_cannot_attach_other_user_asset_to_item(self, client: AsyncClient):
        admin_token = await get_admin_token(client)

        reg = await register_user(client)
        instructor = await login_user(client, reg["username"], reg["password"])

        await client.post("/api/v1/admin/roles/assign", headers=auth_header(admin_token), json={
            "user_id": reg["user"]["id"], "role_name": "Instructor",
        })
        instructor = await login_user(client, reg["username"], reg["password"])

        other_reg = await register_user(client)
        other = await login_user(client, other_reg["username"], other_reg["password"])
        other_asset = await upload_test_asset(client, other["token"])

        cat_resp = await client.post("/api/v1/categories", headers=auth_header(admin_token), json={
            "name": "S", "slug": f"s-{uuid.uuid4().hex[:6]}",
        })
        cat = cat_resp.json()["data"]

        item_resp = await client.post("/api/v1/items", headers=auth_header(instructor["token"]), json={
            "item_type": "SERVICE", "title": "Service", "description": "desc.",
            "category_id": cat["id"],
        })
        item = item_resp.json()["data"]

        resp = await client.post(
            f"/api/v1/items/{item['id']}/media",
            headers=auth_header(instructor["token"]),
            json={"asset_id": other_asset["asset_id"], "scope": "ITEM"},
        )
        assert resp.status_code == 403

    async def test_cannot_attach_other_user_asset_to_verification(self, client: AsyncClient):
        owner_reg = await register_user(client)
        owner = await login_user(client, owner_reg["username"], owner_reg["password"])
        other_asset = await upload_test_asset(
            client, owner["token"], purpose="VERIFICATION", kind="VERIFICATION_ID",
        )

        victim_reg = await register_user(client)
        victim = await login_user(client, victim_reg["username"], victim_reg["password"])

        case_resp = await client.post("/api/v1/verification-cases", headers=auth_header(victim["token"]), json={
            "profile_type": "PERSONAL",
        })
        case = case_resp.json()["data"]

        resp = await client.patch(
            f"/api/v1/verification-cases/{case['case_id']}",
            headers=auth_header(victim["token"]),
            json={
                "row_version": case["row_version"],
                "government_id_image_asset_id": other_asset["asset_id"],
            },
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
class TestOrderDataValidation:
    async def test_rejects_negative_quantity(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        setup = await _setup_published_product(client, admin_token)

        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        resp = await client.post("/api/v1/orders", headers=auth_header(login["token"]), json={
            "idempotency_key": f"neg-{uuid.uuid4().hex}",
            "lines": [{
                "sku_id": setup["sku"]["id"], "item_id": setup["item"]["id"],
                "warehouse_id": setup["warehouse"]["id"], "quantity": -1,
            }],
        })
        assert resp.status_code == 400

    async def test_rejects_unpublished_item(self, client: AsyncClient):
        admin_token = await get_admin_token(client)

        cat_resp = await client.post("/api/v1/categories", headers=auth_header(admin_token), json={
            "name": "Unp", "slug": f"unp-{uuid.uuid4().hex[:6]}",
        })
        cat = cat_resp.json()["data"]

        item_resp = await client.post("/api/v1/items", headers=auth_header(admin_token), json={
            "item_type": "SERVICE", "title": "Unpublished", "description": "d.",
            "category_id": cat["id"],
        })
        item = item_resp.json()["data"]

        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        resp = await client.post("/api/v1/orders", headers=auth_header(login["token"]), json={
            "idempotency_key": f"unp-{uuid.uuid4().hex}",
            "lines": [{
                "item_id": item["id"], "quantity": 1,
            }],
        })
        assert resp.status_code == 400

    async def test_rejects_sku_not_belonging_to_item(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        s1 = await _setup_published_product(client, admin_token)
        s2 = await _setup_published_product(client, admin_token)

        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        resp = await client.post("/api/v1/orders", headers=auth_header(login["token"]), json={
            "idempotency_key": f"mix-{uuid.uuid4().hex}",
            "lines": [{
                "sku_id": s2["sku"]["id"], "item_id": s1["item"]["id"],
                "warehouse_id": s1["warehouse"]["id"], "quantity": 1,
            }],
        })
        assert resp.status_code == 400

    async def test_authoritative_pricing_ignores_client_price(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        setup = await _setup_published_product(client, admin_token)

        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        resp = await client.post("/api/v1/orders", headers=auth_header(login["token"]), json={
            "idempotency_key": f"price-{uuid.uuid4().hex}",
            "lines": [{
                "sku_id": setup["sku"]["id"], "item_id": setup["item"]["id"],
                "warehouse_id": setup["warehouse"]["id"], "quantity": 1,
                "unit_price_cents": 1,
            }],
        })
        assert resp.status_code == 201

        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy import select
        import os
        engine = create_async_engine(os.environ["DATABASE_URL"])
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as db:
            from src.trailgoods.models.orders import OrderLine
            order_id = uuid.UUID(resp.json()["data"]["id"])
            result = await db.execute(select(OrderLine).where(OrderLine.order_id == order_id))
            line = result.scalar_one()
            assert line.unit_price_cents == 500
        await engine.dispose()


@pytest.mark.asyncio
class TestReviewGovernance:
    async def test_cannot_review_unpublished_item(self, client: AsyncClient):
        admin_token = await get_admin_token(client)

        cat_resp = await client.post("/api/v1/categories", headers=auth_header(admin_token), json={
            "name": "RvwCat", "slug": f"rvwcat-{uuid.uuid4().hex[:6]}",
        })
        cat = cat_resp.json()["data"]

        item_resp = await client.post("/api/v1/items", headers=auth_header(admin_token), json={
            "item_type": "PRODUCT", "title": "Draft Product", "description": "not published.",
            "category_id": cat["id"],
        })
        item = item_resp.json()["data"]

        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        resp = await client.post(
            f"/api/v1/items/{item['id']}/reviews",
            headers=auth_header(login["token"]),
            json={"rating": 5, "body_raw": "Great item!"},
        )
        assert resp.status_code == 400

    async def test_cannot_review_nonexistent_item(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        random_id = str(uuid.uuid4())
        resp = await client.post(
            f"/api/v1/items/{random_id}/reviews",
            headers=auth_header(login["token"]),
            json={"rating": 4, "body_raw": "Does not exist."},
        )
        assert resp.status_code == 400

    async def test_cannot_review_same_item_twice(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        setup = await _setup_published_product(client, admin_token)

        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        first = await client.post(
            f"/api/v1/items/{setup['item']['id']}/reviews",
            headers=auth_header(login["token"]),
            json={"rating": 3, "body_raw": "First review."},
        )
        assert first.status_code == 201

        second = await client.post(
            f"/api/v1/items/{setup['item']['id']}/reviews",
            headers=auth_header(login["token"]),
            json={"rating": 4, "body_raw": "Second review attempt."},
        )
        assert second.status_code in (400, 409)


@pytest.mark.asyncio
class TestReportValidation:
    async def test_report_nonexistent_target(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        random_id = str(uuid.uuid4())
        resp = await client.post(
            "/api/v1/reports",
            headers=auth_header(login["token"]),
            json={
                "target_type": "ITEM",
                "target_id": random_id,
                "reason_code": "SPAM",
            },
        )
        assert resp.status_code in (400, 404)


@pytest.mark.asyncio
class TestAppealOwnership:
    async def test_cannot_appeal_other_users_report(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        setup = await _setup_published_product(client, admin_token)

        reporter_reg = await register_user(client)
        reporter = await login_user(client, reporter_reg["username"], reporter_reg["password"])

        report_resp = await client.post(
            "/api/v1/reports",
            headers=auth_header(reporter["token"]),
            json={
                "target_type": "ITEM",
                "target_id": setup["item"]["id"],
                "reason_code": "SPAM",
            },
        )
        assert report_resp.status_code == 201
        report_id = report_resp.json()["data"]["id"]

        other_reg = await register_user(client)
        other = await login_user(client, other_reg["username"], other_reg["password"])

        resp = await client.post(
            "/api/v1/appeals",
            headers=auth_header(other["token"]),
            json={"report_id": report_id},
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
class TestShareLinkDownload:
    async def test_download_actual_file_content(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        file_content = b"unique binary payload for download test " * 50
        asset = await upload_test_asset(
            client, login["token"], content=file_content,
            filename="test.txt", mime_type="text/plain", kind="ATTACHMENT",
        )

        link_resp = await client.post(
            f"/api/v1/assets/{asset['asset_id']}/share-links",
            headers=auth_header(login["token"]),
            json={},
        )
        assert link_resp.status_code == 201
        token = link_resp.json()["data"]["token"]

        dl_resp = await client.get(f"/api/v1/share-links/{token}/download")
        assert dl_resp.status_code == 200
        assert dl_resp.content == file_content
