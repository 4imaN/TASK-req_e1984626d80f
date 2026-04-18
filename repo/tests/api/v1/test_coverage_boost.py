import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import (
    auth_header,
    get_admin_token,
    get_reviewer_token,
    login_user,
    register_user,
    upload_test_asset,
)


async def _setup_published_item(client: AsyncClient, admin_token: str) -> dict:
    cat_resp = await client.post("/api/v1/categories", headers=auth_header(admin_token), json={
        "name": f"Cat-{uuid.uuid4().hex[:6]}", "slug": f"cat-{uuid.uuid4().hex[:6]}",
    })
    cat = cat_resp.json()["data"]

    asset = await upload_test_asset(client, admin_token)

    item_resp = await client.post("/api/v1/items", headers=auth_header(admin_token), json={
        "item_type": "SERVICE", "title": f"Item-{uuid.uuid4().hex[:6]}", "description": "desc",
        "category_id": cat["id"],
    })
    item = item_resp.json()["data"]

    await client.post(f"/api/v1/items/{item['id']}/media", headers=auth_header(admin_token), json={
        "asset_id": asset["asset_id"], "scope": "ITEM",
    })

    pb_resp = await client.post("/api/v1/price-books", headers=auth_header(admin_token), json={
        "name": f"PB-{uuid.uuid4().hex[:6]}", "is_default": True,
    })
    pb = pb_resp.json()["data"]

    await client.post(f"/api/v1/price-books/{pb['id']}/entries", headers=auth_header(admin_token), json={
        "target_type": "ITEM", "target_id": item["id"], "amount_cents": 9999,
    })

    await client.post(f"/api/v1/items/{item['id']}/publish", headers=auth_header(admin_token))
    return item


async def _make_warehouse(client: AsyncClient, token: str) -> dict:
    resp = await client.post("/api/v1/warehouses", headers=auth_header(token), json={
        "code": f"WH-{uuid.uuid4().hex[:6].upper()}", "name": "Test Warehouse",
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


@pytest.mark.asyncio
class TestAssetKindMimeConstraint:
    async def test_image_kind_with_text_plain_mime_rejected(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        headers = auth_header(login["token"])

        resp = await client.post("/api/v1/assets/uploads", headers=headers, json={
            "filename": "notes.txt",
            "mime_type": "text/plain",
            "total_size": 1024,
            "total_parts": 1,
            "kind": "IMAGE",
            "purpose": "GENERAL",
        })
        assert resp.status_code == 400
        assert "kind" in resp.json()["detail"].lower() or "mime" in resp.json()["detail"].lower()

    async def test_video_kind_with_pdf_mime_rejected(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        headers = auth_header(login["token"])

        resp = await client.post("/api/v1/assets/uploads", headers=headers, json={
            "filename": "doc.pdf",
            "mime_type": "application/pdf",
            "total_size": 1024,
            "total_parts": 1,
            "kind": "VIDEO",
            "purpose": "GENERAL",
        })
        assert resp.status_code == 400

    async def test_invalid_kind_rejected(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        headers = auth_header(login["token"])

        resp = await client.post("/api/v1/assets/uploads", headers=headers, json={
            "filename": "file.jpg",
            "mime_type": "image/jpeg",
            "total_size": 1024,
            "total_parts": 1,
            "kind": "INVALID_KIND",
            "purpose": "GENERAL",
        })
        assert resp.status_code == 400

    async def test_invalid_purpose_rejected(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        headers = auth_header(login["token"])

        resp = await client.post("/api/v1/assets/uploads", headers=headers, json={
            "filename": "file.jpg",
            "mime_type": "image/jpeg",
            "total_size": 1024,
            "total_parts": 1,
            "kind": "IMAGE",
            "purpose": "NOT_A_PURPOSE",
        })
        assert resp.status_code == 400


@pytest.mark.asyncio
class TestShareLinkValidation:
    async def test_share_link_expires_in_days_zero_rejected(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        token = login["token"]

        asset = await upload_test_asset(client, token)
        asset_id = asset["asset_id"]

        resp = await client.post(
            f"/api/v1/assets/{asset_id}/share-links",
            headers=auth_header(token),
            json={"expires_in_days": 0, "max_downloads": 10},
        )
        assert resp.status_code == 400
        assert "expires_in_days" in resp.json()["detail"].lower()

    async def test_share_link_max_downloads_zero_rejected(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        token = login["token"]

        asset = await upload_test_asset(client, token)
        asset_id = asset["asset_id"]

        resp = await client.post(
            f"/api/v1/assets/{asset_id}/share-links",
            headers=auth_header(token),
            json={"expires_in_days": 7, "max_downloads": 0},
        )
        assert resp.status_code == 400
        assert "max_downloads" in resp.json()["detail"].lower()

    async def test_share_link_negative_expires_rejected(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        token = login["token"]

        asset = await upload_test_asset(client, token)
        asset_id = asset["asset_id"]

        resp = await client.post(
            f"/api/v1/assets/{asset_id}/share-links",
            headers=auth_header(token),
            json={"expires_in_days": -5, "max_downloads": 10},
        )
        assert resp.status_code == 400


@pytest.mark.asyncio
class TestAssetDeletion:
    async def test_delete_asset_attached_to_published_item_rejected(self, client: AsyncClient):
        admin_token = await get_admin_token(client)

        cat_resp = await client.post("/api/v1/categories", headers=auth_header(admin_token), json={
            "name": f"Cat-{uuid.uuid4().hex[:6]}", "slug": f"cat-{uuid.uuid4().hex[:6]}",
        })
        cat = cat_resp.json()["data"]

        asset = await upload_test_asset(client, admin_token)
        asset_id = asset["asset_id"]

        item_resp = await client.post("/api/v1/items", headers=auth_header(admin_token), json={
            "item_type": "SERVICE",
            "title": f"Item-{uuid.uuid4().hex[:6]}",
            "description": "test",
            "category_id": cat["id"],
        })
        item = item_resp.json()["data"]

        await client.post(f"/api/v1/items/{item['id']}/media", headers=auth_header(admin_token), json={
            "asset_id": asset_id, "scope": "ITEM",
        })

        pb_resp = await client.post("/api/v1/price-books", headers=auth_header(admin_token), json={
            "name": f"PB-{uuid.uuid4().hex[:6]}", "is_default": True,
        })
        pb = pb_resp.json()["data"]

        await client.post(f"/api/v1/price-books/{pb['id']}/entries", headers=auth_header(admin_token), json={
            "target_type": "ITEM", "target_id": item["id"], "amount_cents": 1000,
        })

        await client.post(f"/api/v1/items/{item['id']}/publish", headers=auth_header(admin_token))

        resp = await client.delete(f"/api/v1/assets/{asset_id}", headers=auth_header(admin_token))
        assert resp.status_code == 400
        detail = resp.json()["detail"].lower()
        assert "published" in detail or "referenced" in detail or "cannot" in detail

    async def test_delete_nonexistent_asset_returns_404(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        fake_id = str(uuid.uuid4())
        resp = await client.delete(f"/api/v1/assets/{fake_id}", headers=auth_header(admin_token))
        assert resp.status_code in (400, 404)

    async def test_delete_already_deleted_asset_returns_409(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        token = login["token"]

        asset = await upload_test_asset(client, token)
        asset_id = asset["asset_id"]

        resp1 = await client.delete(f"/api/v1/assets/{asset_id}", headers=auth_header(token))
        assert resp1.status_code == 200

        resp2 = await client.delete(f"/api/v1/assets/{asset_id}", headers=auth_header(token))
        assert resp2.status_code == 409


@pytest.mark.asyncio
class TestWarehouseDuplicateCode:
    async def test_create_warehouse_duplicate_code_returns_409(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        code = f"WH-{uuid.uuid4().hex[:6].upper()}"

        resp1 = await client.post("/api/v1/warehouses", headers=auth_header(admin_token), json={
            "code": code, "name": "First Warehouse",
        })
        assert resp1.status_code == 201, resp1.text

        resp2 = await client.post("/api/v1/warehouses", headers=auth_header(admin_token), json={
            "code": code, "name": "Duplicate Warehouse",
        })
        assert resp2.status_code == 409


@pytest.mark.asyncio
class TestInboundDocErrors:
    async def test_create_inbound_doc_invalid_source_type_returns_400(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        wh = await _make_warehouse(client, admin_token)

        resp = await client.post("/api/v1/inbound-docs", headers=auth_header(admin_token), json={
            "warehouse_id": wh["id"], "source_type": "INVALID_TYPE",
        })
        assert resp.status_code == 400

    async def test_create_inbound_doc_nonexistent_warehouse_returns_400(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        fake_id = str(uuid.uuid4())

        resp = await client.post("/api/v1/inbound-docs", headers=auth_header(admin_token), json={
            "warehouse_id": fake_id, "source_type": "PURCHASE",
        })
        assert resp.status_code == 400

    async def test_add_inbound_line_nonexistent_sku_returns_404(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        wh = await _make_warehouse(client, admin_token)

        doc_resp = await client.post("/api/v1/inbound-docs", headers=auth_header(admin_token), json={
            "warehouse_id": wh["id"], "source_type": "PURCHASE",
        })
        assert doc_resp.status_code == 201, doc_resp.text
        doc = doc_resp.json()["data"]

        fake_sku_id = str(uuid.uuid4())
        resp = await client.post(f"/api/v1/inbound-docs/{doc['id']}/lines", headers=auth_header(admin_token), json={
            "sku_id": fake_sku_id, "quantity": 10,
        })
        assert resp.status_code in (400, 404)


@pytest.mark.asyncio
class TestOutboundDocErrors:
    async def test_create_outbound_doc_invalid_source_type_returns_400(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        wh = await _make_warehouse(client, admin_token)

        resp = await client.post("/api/v1/outbound-docs", headers=auth_header(admin_token), json={
            "warehouse_id": wh["id"], "source_type": "INVALID_OUTBOUND",
        })
        assert resp.status_code == 400

    async def test_create_outbound_doc_nonexistent_warehouse_returns_400(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        fake_id = str(uuid.uuid4())

        resp = await client.post("/api/v1/outbound-docs", headers=auth_header(admin_token), json={
            "warehouse_id": fake_id, "source_type": "SALE",
        })
        assert resp.status_code == 400

    async def test_create_outbound_doc_valid_source_types(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        wh = await _make_warehouse(client, admin_token)

        for source_type in ("SALE", "TRANSFER_OUT", "DAMAGE", "WRITE_OFF"):
            resp = await client.post("/api/v1/outbound-docs", headers=auth_header(admin_token), json={
                "warehouse_id": wh["id"], "source_type": source_type,
            })
            assert resp.status_code == 201, f"Expected 201 for {source_type}, got {resp.status_code}: {resp.text}"


@pytest.mark.asyncio
class TestReviewAppeal:
    async def test_appeal_published_review_rejected(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        item = await _setup_published_item(client, admin_token)

        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        review_resp = await client.post(
            f"/api/v1/items/{item['id']}/reviews",
            headers=auth_header(login["token"]),
            json={"rating": 4, "body_raw": "Great experience with this item."},
        )
        assert review_resp.status_code == 201, review_resp.text
        review = review_resp.json()["data"]

        if review["status"] != "PUBLISHED":
            reviewer_token = await get_reviewer_token(client)
            await client.post(
                f"/api/v1/reviews/{review['id']}/moderate",
                headers=auth_header(reviewer_token),
                json={"action": "PUBLISHED"},
            )

        appeal_resp = await client.post(
            "/api/v1/appeals",
            headers=auth_header(login["token"]),
            json={"review_id": review["id"]},
        )
        assert appeal_resp.status_code == 400
        detail = appeal_resp.json()["detail"].lower()
        assert "moderated" in detail or "suppressed" in detail or "removed" in detail or "state" in detail

    async def test_appeal_suppressed_review_succeeds(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        item = await _setup_published_item(client, admin_token)

        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        review_resp = await client.post(
            f"/api/v1/items/{item['id']}/reviews",
            headers=auth_header(login["token"]),
            json={"rating": 3, "body_raw": "Decent product overall."},
        )
        assert review_resp.status_code == 201, review_resp.text
        review = review_resp.json()["data"]

        reviewer_token = await get_reviewer_token(client)

        if review["status"] == "PENDING_REVIEW":
            await client.post(
                f"/api/v1/reviews/{review['id']}/moderate",
                headers=auth_header(reviewer_token),
                json={"action": "PUBLISHED"},
            )

        suppress_resp = await client.post(
            f"/api/v1/reviews/{review['id']}/moderate",
            headers=auth_header(reviewer_token),
            json={"action": "SUPPRESSED", "comment": "Policy violation"},
        )
        assert suppress_resp.status_code == 200

        appeal_resp = await client.post(
            "/api/v1/appeals",
            headers=auth_header(login["token"]),
            json={"review_id": review["id"]},
        )
        assert appeal_resp.status_code == 201, appeal_resp.text


@pytest.mark.asyncio
class TestReportClose:
    async def test_close_submitted_report_rejected(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        item = await _setup_published_item(client, admin_token)

        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        report_resp = await client.post(
            "/api/v1/reports",
            headers=auth_header(login["token"]),
            json={
                "target_type": "ITEM",
                "target_id": item["id"],
                "reason_code": "spam",
                "details_raw": "This looks like spam.",
            },
        )
        assert report_resp.status_code == 201, report_resp.text
        report = report_resp.json()["data"]
        assert report["status"] == "SUBMITTED"

        reviewer_token = await get_reviewer_token(client)
        close_resp = await client.post(
            f"/api/v1/reports/{report['id']}/close",
            headers=auth_header(reviewer_token),
            json={"comment": "Premature close attempt"},
        )
        assert close_resp.status_code == 400
        detail = close_resp.json()["detail"].lower()
        assert "triage" in detail or "submitted" in detail or "cannot" in detail


@pytest.mark.asyncio
class TestReviewEditReFilter:
    async def test_edit_review_with_sensitive_word_moves_to_pending(self, client: AsyncClient):
        admin_token = await get_admin_token(client)

        sw_resp = await client.post(
            "/api/v1/admin/sensitive-words",
            headers=auth_header(admin_token),
            json={"term": "badword_edit_test", "category": "profanity"},
        )
        assert sw_resp.status_code == 201, sw_resp.text

        item = await _setup_published_item(client, admin_token)

        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        create_resp = await client.post(
            f"/api/v1/items/{item['id']}/reviews",
            headers=auth_header(login["token"]),
            json={"rating": 5, "body_raw": "Great product!"},
        )
        assert create_resp.status_code == 201, create_resp.text
        review = create_resp.json()["data"]

        edit_resp = await client.patch(
            f"/api/v1/reviews/{review['id']}",
            headers=auth_header(login["token"]),
            json={"body_raw": "This product has badword_edit_test content.", "rating": 2},
        )
        assert edit_resp.status_code == 200, edit_resp.text
        updated = edit_resp.json()["data"]
        assert updated["status"] == "PENDING_REVIEW"
        assert updated["latest_revision_no"] == 2

    async def test_edit_review_without_sensitive_word_stays_published(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        item = await _setup_published_item(client, admin_token)

        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        create_resp = await client.post(
            f"/api/v1/items/{item['id']}/reviews",
            headers=auth_header(login["token"]),
            json={"rating": 4, "body_raw": "Good product, worth buying."},
        )
        assert create_resp.status_code == 201, create_resp.text
        review = create_resp.json()["data"]

        edit_resp = await client.patch(
            f"/api/v1/reviews/{review['id']}",
            headers=auth_header(login["token"]),
            json={"body_raw": "Still a good product, highly recommend.", "rating": 5},
        )
        assert edit_resp.status_code == 200, edit_resp.text
        updated = edit_resp.json()["data"]
        assert updated["status"] == "PUBLISHED"
        assert updated["latest_revision_no"] == 2


@pytest.mark.asyncio
class TestInboundDocValidSourceTypes:
    async def test_valid_inbound_source_types_accepted(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        wh = await _make_warehouse(client, admin_token)

        for source_type in ("PURCHASE", "RETURN", "TRANSFER_IN", "MANUAL_ADJUSTMENT"):
            resp = await client.post("/api/v1/inbound-docs", headers=auth_header(admin_token), json={
                "warehouse_id": wh["id"], "source_type": source_type,
            })
            assert resp.status_code == 201, f"Expected 201 for {source_type}: {resp.text}"


@pytest.mark.asyncio
class TestShareLinkOnNonexistentAsset:
    async def test_share_link_nonexistent_asset_rejected(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        token = login["token"]
        fake_id = str(uuid.uuid4())

        resp = await client.post(
            f"/api/v1/assets/{fake_id}/share-links",
            headers=auth_header(token),
            json={"expires_in_days": 7, "max_downloads": 5},
        )
        assert resp.status_code in (400, 404)
