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
        "name": "Reviews Test", "slug": f"rev-{uuid.uuid4().hex[:6]}",
    })
    cat = cat_resp.json()["data"]

    asset = await upload_test_asset(client, admin_token)

    item_resp = await client.post("/api/v1/items", headers=auth_header(admin_token), json={
        "item_type": "SERVICE", "title": "Guided Hike", "description": "A great hike.",
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


@pytest.mark.asyncio
class TestSensitiveWordFiltering:
    async def test_sensitive_word_triggers_pending_review_and_redaction(self, client: AsyncClient):
        admin_token = await get_admin_token(client)

        sw_resp = await client.post(
            "/api/v1/admin/sensitive-words",
            headers=auth_header(admin_token),
            json={"term": "badword", "category": "profanity"},
        )
        assert sw_resp.status_code == 201, sw_resp.text

        item = await _setup_published_item(client, admin_token)

        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        review_resp = await client.post(
            f"/api/v1/items/{item['id']}/reviews",
            headers=auth_header(login["token"]),
            json={"rating": 3, "body_raw": "This product is badword quality."},
        )
        assert review_resp.status_code == 201, review_resp.text
        data = review_resp.json()["data"]
        assert data["status"] == "PENDING_REVIEW"

        body_public = data.get("body_public") or ""
        assert "badword" not in body_public
        assert "*" in body_public


@pytest.mark.asyncio
class TestReviewCreation:
    async def test_create_review(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        item = await _setup_published_item(client, admin_token)

        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        resp = await client.post(
            f"/api/v1/items/{item['id']}/reviews",
            headers=auth_header(login["token"]),
            json={"rating": 5, "body_raw": "Excellent experience, highly recommend!"},
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()["data"]
        assert data["rating"] == 5
        assert data["status"] in ("PUBLISHED", "PENDING_REVIEW")

    async def test_invalid_rating_rejected(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        item = await _setup_published_item(client, admin_token)

        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        resp = await client.post(
            f"/api/v1/items/{item['id']}/reviews",
            headers=auth_header(login["token"]),
            json={"rating": 6, "body_raw": "Too high rating"},
        )
        assert resp.status_code == 400

    async def test_list_public_reviews(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        item = await _setup_published_item(client, admin_token)

        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        await client.post(
            f"/api/v1/items/{item['id']}/reviews",
            headers=auth_header(login["token"]),
            json={"rating": 4, "body_raw": "Good experience overall."},
        )

        resp = await client.get(f"/api/v1/items/{item['id']}/reviews")
        assert resp.status_code == 200
        reviews = resp.json()["data"]
        assert len(reviews) >= 1


@pytest.mark.asyncio
class TestReviewEditing:
    async def test_edit_own_review(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        item = await _setup_published_item(client, admin_token)

        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        create_resp = await client.post(
            f"/api/v1/items/{item['id']}/reviews",
            headers=auth_header(login["token"]),
            json={"rating": 3, "body_raw": "Original review text."},
        )
        review = create_resp.json()["data"]

        edit_resp = await client.patch(
            f"/api/v1/reviews/{review['id']}",
            headers=auth_header(login["token"]),
            json={"body_raw": "Updated review text with more details.", "rating": 4},
        )
        assert edit_resp.status_code == 200, edit_resp.text
        assert edit_resp.json()["data"]["latest_revision_no"] == 2

    async def test_cannot_edit_other_user_review(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        item = await _setup_published_item(client, admin_token)

        reg1 = await register_user(client)
        login1 = await login_user(client, reg1["username"], reg1["password"])

        create_resp = await client.post(
            f"/api/v1/items/{item['id']}/reviews",
            headers=auth_header(login1["token"]),
            json={"rating": 5, "body_raw": "My review."},
        )
        review = create_resp.json()["data"]

        reg2 = await register_user(client)
        login2 = await login_user(client, reg2["username"], reg2["password"])

        edit_resp = await client.patch(
            f"/api/v1/reviews/{review['id']}",
            headers=auth_header(login2["token"]),
            json={"body_raw": "Hijacked!"},
        )
        assert edit_resp.status_code == 403


@pytest.mark.asyncio
class TestReviewModeration:
    async def test_suppress_and_restore_review(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        item = await _setup_published_item(client, admin_token)

        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        create_resp = await client.post(
            f"/api/v1/items/{item['id']}/reviews",
            headers=auth_header(login["token"]),
            json={"rating": 1, "body_raw": "This is a clean review."},
        )
        review = create_resp.json()["data"]

        reviewer_token = await get_reviewer_token(client)

        suppress_resp = await client.post(
            f"/api/v1/reviews/{review['id']}/moderate",
            headers=auth_header(reviewer_token),
            json={"action": "SUPPRESSED", "comment": "Policy violation"},
        )
        assert suppress_resp.status_code == 200
        assert suppress_resp.json()["data"]["status"] == "SUPPRESSED"

        restore_resp = await client.post(
            f"/api/v1/reviews/{review['id']}/moderate",
            headers=auth_header(reviewer_token),
            json={"action": "PUBLISHED"},
        )
        assert restore_resp.status_code == 200
        assert restore_resp.json()["data"]["status"] == "PUBLISHED"

    async def test_non_reviewer_cannot_moderate(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        item = await _setup_published_item(client, admin_token)

        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        create_resp = await client.post(
            f"/api/v1/items/{item['id']}/reviews",
            headers=auth_header(login["token"]),
            json={"rating": 2, "body_raw": "OK review."},
        )
        review = create_resp.json()["data"]

        resp = await client.post(
            f"/api/v1/reviews/{review['id']}/moderate",
            headers=auth_header(login["token"]),
            json={"action": "REMOVED"},
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
class TestReports:
    async def test_create_and_triage_report(self, client: AsyncClient):
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
                "reason_code": "inappropriate_content",
                "details_raw": "This listing seems inappropriate.",
            },
        )
        assert report_resp.status_code == 201, report_resp.text
        report = report_resp.json()["data"]
        assert report["status"] == "SUBMITTED"
        assert report["triage_due_at"] is not None

        reviewer_token = await get_reviewer_token(client)
        triage_resp = await client.post(
            f"/api/v1/reports/{report['id']}/triage",
            headers=auth_header(reviewer_token),
            json={"action": "TRIAGED", "comment": "Investigating"},
        )
        assert triage_resp.status_code == 200

        close_resp = await client.post(
            f"/api/v1/reports/{report['id']}/close",
            headers=auth_header(reviewer_token),
            json={"comment": "Issue resolved"},
        )
        assert close_resp.status_code == 200


@pytest.mark.asyncio
class TestAppeals:
    async def test_create_and_decide_appeal(self, client: AsyncClient):
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
            },
        )
        report = report_resp.json()["data"]

        reviewer_token = await get_reviewer_token(client)
        await client.post(
            f"/api/v1/reports/{report['id']}/triage",
            headers=auth_header(reviewer_token),
            json={"action": "DISMISSED", "comment": "Not spam"},
        )

        appeal_resp = await client.post(
            "/api/v1/appeals",
            headers=auth_header(login["token"]),
            json={"report_id": report["id"]},
        )
        assert appeal_resp.status_code == 201, appeal_resp.text
        appeal = appeal_resp.json()["data"]

        decide_resp = await client.post(
            f"/api/v1/appeals/{appeal['id']}/decision",
            headers=auth_header(reviewer_token),
            json={
                "action": "DECIDED",
                "decision_summary": "Appeal upheld, action reversed.",
                "comment": "Re-reviewed content.",
            },
        )
        assert decide_resp.status_code == 200


@pytest.mark.asyncio
class TestIntegrity:
    async def test_integrity_check(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        await upload_test_asset(client, login["token"])

        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        import os
        engine = create_async_engine(os.environ["DATABASE_URL"])
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as db:
            from scripts.integrity import run_integrity_check
            results = await run_integrity_check(db)
            assert results["errors_count"] == 0
            assert results["total_blobs"] >= 1
        await engine.dispose()
