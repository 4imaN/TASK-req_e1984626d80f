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
    cat_resp = await client.post(
        "/api/v1/categories",
        headers=auth_header(admin_token),
        json={"name": f"Cat-{uuid.uuid4().hex[:6]}", "slug": f"cat-{uuid.uuid4().hex[:6]}"},
    )
    cat = cat_resp.json()["data"]

    asset = await upload_test_asset(client, admin_token)

    item_resp = await client.post(
        "/api/v1/items",
        headers=auth_header(admin_token),
        json={
            "item_type": "SERVICE",
            "title": f"Item {uuid.uuid4().hex[:6]}",
            "description": "Test item",
            "category_id": cat["id"],
        },
    )
    item = item_resp.json()["data"]

    await client.post(
        f"/api/v1/items/{item['id']}/media",
        headers=auth_header(admin_token),
        json={"asset_id": asset["asset_id"], "scope": "ITEM"},
    )

    pb_resp = await client.post(
        "/api/v1/price-books",
        headers=auth_header(admin_token),
        json={"name": f"PB-{uuid.uuid4().hex[:6]}", "is_default": True},
    )
    pb = pb_resp.json()["data"]

    await client.post(
        f"/api/v1/price-books/{pb['id']}/entries",
        headers=auth_header(admin_token),
        json={"target_type": "ITEM", "target_id": item["id"], "amount_cents": 9999},
    )

    await client.post(f"/api/v1/items/{item['id']}/publish", headers=auth_header(admin_token))

    return item


@pytest.mark.asyncio
class TestAdminClearChallenge:
    async def test_admin_clear_challenge_success(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        reg = await register_user(client)

        for _ in range(5):
            await client.post(
                "/api/v1/auth/login",
                json={"username": reg["username"], "password": "WrongPassword1!"},
            )

        locked_resp = await client.post(
            "/api/v1/auth/login",
            json={"username": reg["username"], "password": reg["password"]},
        )
        assert locked_resp.status_code == 401
        detail = locked_resp.json()["detail"].lower()
        assert "locked" in detail or "challenge" in detail

        clear_resp = await client.post(
            "/api/v1/admin/clear-challenge",
            headers=auth_header(admin_token),
            json={"user_id": reg["user"]["id"]},
        )
        assert clear_resp.status_code == 200, clear_resp.text
        assert clear_resp.json()["data"]["message"] == "Challenge cleared"

        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"username": reg["username"], "password": reg["password"]},
        )
        assert login_resp.status_code == 200, login_resp.text

    async def test_non_admin_cannot_clear_challenge(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        target = await register_user(client)

        resp = await client.post(
            "/api/v1/admin/clear-challenge",
            headers=auth_header(login["token"]),
            json={"user_id": target["user"]["id"]},
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
class TestDisableShareLink:
    async def test_owner_disable_share_link(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        asset = await upload_test_asset(client, login["token"])
        asset_id = asset["asset_id"]

        sl_resp = await client.post(
            f"/api/v1/assets/{asset_id}/share-links",
            headers=auth_header(login["token"]),
            json={"expires_in_days": 7, "max_downloads": 10},
        )
        assert sl_resp.status_code == 201, sl_resp.text
        sl_id = sl_resp.json()["data"]["id"]

        disable_resp = await client.delete(
            f"/api/v1/share-links/{sl_id}",
            headers=auth_header(login["token"]),
        )
        assert disable_resp.status_code == 200, disable_resp.text
        assert disable_resp.json()["data"]["message"] == "Share link disabled"

    async def test_disable_already_disabled_returns_409(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        asset = await upload_test_asset(client, login["token"])
        asset_id = asset["asset_id"]

        sl_resp = await client.post(
            f"/api/v1/assets/{asset_id}/share-links",
            headers=auth_header(login["token"]),
            json={"expires_in_days": 7, "max_downloads": 10},
        )
        sl_id = sl_resp.json()["data"]["id"]

        await client.delete(
            f"/api/v1/share-links/{sl_id}",
            headers=auth_header(login["token"]),
        )

        second_resp = await client.delete(
            f"/api/v1/share-links/{sl_id}",
            headers=auth_header(login["token"]),
        )
        assert second_resp.status_code == 409

    async def test_non_owner_cannot_disable(self, client: AsyncClient):
        owner = await register_user(client)
        owner_login = await login_user(client, owner["username"], owner["password"])

        other = await register_user(client)
        other_login = await login_user(client, other["username"], other["password"])

        asset = await upload_test_asset(client, owner_login["token"])
        asset_id = asset["asset_id"]

        sl_resp = await client.post(
            f"/api/v1/assets/{asset_id}/share-links",
            headers=auth_header(owner_login["token"]),
            json={"expires_in_days": 7, "max_downloads": 10},
        )
        sl_id = sl_resp.json()["data"]["id"]

        resp = await client.delete(
            f"/api/v1/share-links/{sl_id}",
            headers=auth_header(other_login["token"]),
        )
        assert resp.status_code == 403

    async def test_disable_nonexistent_returns_404(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        random_id = str(uuid.uuid4())
        resp = await client.delete(
            f"/api/v1/share-links/{random_id}",
            headers=auth_header(login["token"]),
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestListReports:
    async def test_reviewer_list_reports(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        reviewer_token = await get_reviewer_token(client)
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
                "details_raw": "Test report detail",
            },
        )
        assert report_resp.status_code == 201, report_resp.text
        report_id = report_resp.json()["data"]["id"]

        list_resp = await client.get("/api/v1/reports", headers=auth_header(reviewer_token))
        assert list_resp.status_code == 200, list_resp.text
        data = list_resp.json()["data"]
        ids = [r["id"] for r in data]
        assert report_id in ids

    async def test_list_reports_with_status_filter(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        reviewer_token = await get_reviewer_token(client)
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
            },
        )
        assert report_resp.status_code == 201, report_resp.text
        report_id = report_resp.json()["data"]["id"]

        list_resp = await client.get(
            "/api/v1/reports?status=SUBMITTED",
            headers=auth_header(reviewer_token),
        )
        assert list_resp.status_code == 200, list_resp.text
        data = list_resp.json()["data"]
        assert all(r["status"] == "SUBMITTED" for r in data)
        ids = [r["id"] for r in data]
        assert report_id in ids

    async def test_non_reviewer_forbidden(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        resp = await client.get("/api/v1/reports", headers=auth_header(login["token"]))
        assert resp.status_code == 403


@pytest.mark.asyncio
class TestDeleteSensitiveWord:
    async def test_deactivate_sensitive_word(self, client: AsyncClient):
        admin_token = await get_admin_token(client)

        create_resp = await client.post(
            "/api/v1/admin/sensitive-words",
            headers=auth_header(admin_token),
            json={"term": f"badterm_{uuid.uuid4().hex[:6]}", "category": "profanity"},
        )
        assert create_resp.status_code == 201, create_resp.text
        term_id = create_resp.json()["data"]["id"]

        delete_resp = await client.delete(
            f"/api/v1/admin/sensitive-words/{term_id}",
            headers=auth_header(admin_token),
        )
        assert delete_resp.status_code == 200, delete_resp.text
        assert delete_resp.json()["data"]["message"] == "Sensitive word term deactivated"

    async def test_deactivate_nonexistent_returns_404(self, client: AsyncClient):
        admin_token = await get_admin_token(client)

        random_id = str(uuid.uuid4())
        resp = await client.delete(
            f"/api/v1/admin/sensitive-words/{random_id}",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestListSensitiveWords:
    async def test_list_sensitive_words(self, client: AsyncClient):
        admin_token = await get_admin_token(client)

        terms_to_create = [f"listterm_{uuid.uuid4().hex[:6]}" for _ in range(3)]
        for term in terms_to_create:
            resp = await client.post(
                "/api/v1/admin/sensitive-words",
                headers=auth_header(admin_token),
                json={"term": term, "category": "test"},
            )
            assert resp.status_code == 201

        list_resp = await client.get(
            "/api/v1/admin/sensitive-words",
            headers=auth_header(admin_token),
        )
        assert list_resp.status_code == 200, list_resp.text
        body = list_resp.json()
        assert len(body["data"]) >= 3

    async def test_list_sensitive_words_pagination(self, client: AsyncClient):
        admin_token = await get_admin_token(client)

        for _ in range(2):
            await client.post(
                "/api/v1/admin/sensitive-words",
                headers=auth_header(admin_token),
                json={"term": f"pagterm_{uuid.uuid4().hex[:6]}", "category": "test"},
            )

        resp = await client.get(
            "/api/v1/admin/sensitive-words?limit=1&offset=0",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "pagination" in body["meta"]
        assert body["meta"]["pagination"]["limit"] == 1
        assert body["meta"]["pagination"]["total"] >= 2
        assert len(body["data"]) == 1


@pytest.mark.asyncio
class TestListAppeals:
    async def _create_dismissed_report_and_appeal(
        self, client: AsyncClient, admin_token: str, reporter_token: str, reporter_user_id: str
    ) -> dict:
        item = await _setup_published_item(client, admin_token)
        reviewer_token = await get_reviewer_token(client)

        report_resp = await client.post(
            "/api/v1/reports",
            headers=auth_header(reporter_token),
            json={
                "target_type": "ITEM",
                "target_id": item["id"],
                "reason_code": "spam",
            },
        )
        assert report_resp.status_code == 201, report_resp.text
        report = report_resp.json()["data"]

        await client.post(
            f"/api/v1/reports/{report['id']}/triage",
            headers=auth_header(reviewer_token),
            json={"action": "DISMISSED", "comment": "Not spam"},
        )

        appeal_resp = await client.post(
            "/api/v1/appeals",
            headers=auth_header(reporter_token),
            json={"report_id": report["id"]},
        )
        assert appeal_resp.status_code == 201, appeal_resp.text
        return appeal_resp.json()["data"]

    async def test_reviewer_list_appeals(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        reviewer_token = await get_reviewer_token(client)

        reg = await register_user(client)
        reporter_login = await login_user(client, reg["username"], reg["password"])

        appeal = await self._create_dismissed_report_and_appeal(
            client, admin_token, reporter_login["token"], reg["user"]["id"]
        )

        list_resp = await client.get("/api/v1/appeals", headers=auth_header(reviewer_token))
        assert list_resp.status_code == 200, list_resp.text
        body = list_resp.json()
        ids = [a["id"] for a in body["data"]]
        assert appeal["id"] in ids
        assert "pagination" in body["meta"]

    async def test_list_appeals_non_reviewer_forbidden(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        resp = await client.get("/api/v1/appeals", headers=auth_header(login["token"]))
        assert resp.status_code == 403


@pytest.mark.asyncio
class TestListVerificationCases:
    async def test_reviewer_list_verification_cases(self, client: AsyncClient):
        reviewer_token = await get_reviewer_token(client)

        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        create_resp = await client.post(
            "/api/v1/verification-cases",
            headers=auth_header(login["token"]),
            json={"profile_type": "PERSONAL"},
        )
        assert create_resp.status_code == 201, create_resp.text
        case_id = create_resp.json()["data"]["case_id"]

        list_resp = await client.get(
            "/api/v1/verification-cases",
            headers=auth_header(reviewer_token),
        )
        assert list_resp.status_code == 200, list_resp.text
        body = list_resp.json()
        case_ids = [c["case_id"] for c in body["data"]]
        assert case_id in case_ids
        assert "pagination" in body["meta"]

    async def test_list_cases_with_status_filter(self, client: AsyncClient):
        reviewer_token = await get_reviewer_token(client)

        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        create_resp = await client.post(
            "/api/v1/verification-cases",
            headers=auth_header(login["token"]),
            json={"profile_type": "PERSONAL"},
        )
        assert create_resp.status_code == 201, create_resp.text

        list_resp = await client.get(
            "/api/v1/verification-cases?status=DRAFT",
            headers=auth_header(reviewer_token),
        )
        assert list_resp.status_code == 200, list_resp.text
        body = list_resp.json()
        assert all(c["status"] == "DRAFT" for c in body["data"])

    async def test_non_reviewer_forbidden(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        resp = await client.get(
            "/api/v1/verification-cases",
            headers=auth_header(login["token"]),
        )
        assert resp.status_code == 403
