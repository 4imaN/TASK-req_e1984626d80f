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


async def _create_personal_case(client: AsyncClient, token: str) -> dict:
    resp = await client.post(
        "/api/v1/verification-cases",
        headers=auth_header(token),
        json={"profile_type": "PERSONAL"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


async def _fill_and_submit_personal(client: AsyncClient, token: str, case_id: str, row_version: int) -> dict:
    asset = await upload_test_asset(client, token, purpose="VERIFICATION", kind="VERIFICATION_ID")

    resp = await client.patch(
        f"/api/v1/verification-cases/{case_id}",
        headers=auth_header(token),
        json={
            "row_version": row_version,
            "legal_name": "John Doe",
            "dob": "01/15/1990",
            "government_id_number": "A123456789",
            "government_id_image_asset_id": asset["asset_id"],
        },
    )
    assert resp.status_code == 200, resp.text
    new_version = resp.json()["data"]["row_version"]

    resp2 = await client.post(
        f"/api/v1/verification-cases/{case_id}/submit",
        headers=auth_header(token),
    )
    assert resp2.status_code == 200, resp2.text
    return resp2.json()["data"]


@pytest.mark.asyncio
class TestVerificationCreation:
    async def test_create_personal_case(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        case = await _create_personal_case(client, login["token"])
        assert case["case_id"]
        assert case["profile_type"] == "PERSONAL"
        assert case["status"] == "DRAFT"

    async def test_create_enterprise_case(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        resp = await client.post(
            "/api/v1/verification-cases",
            headers=auth_header(login["token"]),
            json={"profile_type": "ENTERPRISE"},
        )
        assert resp.status_code == 201
        assert resp.json()["data"]["profile_type"] == "ENTERPRISE"

    async def test_duplicate_active_case_rejected(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        await _create_personal_case(client, login["token"])

        resp = await client.post(
            "/api/v1/verification-cases",
            headers=auth_header(login["token"]),
            json={"profile_type": "PERSONAL"},
        )
        assert resp.status_code == 409


@pytest.mark.asyncio
class TestVerificationUpdate:
    async def test_update_case_fields(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        case = await _create_personal_case(client, login["token"])

        resp = await client.patch(
            f"/api/v1/verification-cases/{case['case_id']}",
            headers=auth_header(login["token"]),
            json={
                "row_version": case["row_version"],
                "legal_name": "Jane Doe",
                "dob": "06/15/1985",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["row_version"] == case["row_version"] + 1

    async def test_row_version_conflict(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        case = await _create_personal_case(client, login["token"])

        await client.patch(
            f"/api/v1/verification-cases/{case['case_id']}",
            headers=auth_header(login["token"]),
            json={"row_version": case["row_version"], "legal_name": "First"},
        )

        resp = await client.patch(
            f"/api/v1/verification-cases/{case['case_id']}",
            headers=auth_header(login["token"]),
            json={"row_version": case["row_version"], "legal_name": "Second"},
        )
        assert resp.status_code == 409

    async def test_underage_dob_rejected(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        case = await _create_personal_case(client, login["token"])

        resp = await client.patch(
            f"/api/v1/verification-cases/{case['case_id']}",
            headers=auth_header(login["token"]),
            json={"row_version": case["row_version"], "dob": "01/01/2020"},
        )
        assert resp.status_code == 400


@pytest.mark.asyncio
class TestVerificationSubmitAndDecision:
    async def test_submit_personal_case(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        case = await _create_personal_case(client, login["token"])
        submitted = await _fill_and_submit_personal(
            client, login["token"], case["case_id"], case["row_version"]
        )
        assert submitted["status"] == "SUBMITTED"

    async def test_submit_incomplete_case_rejected(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        case = await _create_personal_case(client, login["token"])

        resp = await client.post(
            f"/api/v1/verification-cases/{case['case_id']}/submit",
            headers=auth_header(login["token"]),
        )
        assert resp.status_code == 400

    async def test_reviewer_approve_case(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        case = await _create_personal_case(client, login["token"])
        await _fill_and_submit_personal(
            client, login["token"], case["case_id"], case["row_version"]
        )

        reviewer_token = await get_reviewer_token(client)

        resp = await client.post(
            f"/api/v1/verification-cases/{case['case_id']}/decision",
            headers=auth_header(reviewer_token),
            json={"decision": "UNDER_REVIEW"},
        )
        assert resp.status_code == 200

        resp2 = await client.post(
            f"/api/v1/verification-cases/{case['case_id']}/decision",
            headers=auth_header(reviewer_token),
            json={"decision": "APPROVED", "comment": "All checks passed"},
        )
        assert resp2.status_code == 200
        assert resp2.json()["data"]["status"] == "APPROVED"

    async def test_reviewer_reject_case(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        case = await _create_personal_case(client, login["token"])
        await _fill_and_submit_personal(
            client, login["token"], case["case_id"], case["row_version"]
        )

        reviewer_token = await get_reviewer_token(client)

        await client.post(
            f"/api/v1/verification-cases/{case['case_id']}/decision",
            headers=auth_header(reviewer_token),
            json={"decision": "UNDER_REVIEW"},
        )

        resp = await client.post(
            f"/api/v1/verification-cases/{case['case_id']}/decision",
            headers=auth_header(reviewer_token),
            json={"decision": "REJECTED", "comment": "Inconsistent documents"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "REJECTED"

    async def test_regular_user_cannot_decide(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        case = await _create_personal_case(client, login["token"])
        await _fill_and_submit_personal(
            client, login["token"], case["case_id"], case["row_version"]
        )

        resp = await client.post(
            f"/api/v1/verification-cases/{case['case_id']}/decision",
            headers=auth_header(login["token"]),
            json={"decision": "APPROVED"},
        )
        assert resp.status_code == 403

    async def test_invalid_transition_rejected(self, client: AsyncClient):
        reviewer_token = await get_reviewer_token(client)
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        case = await _create_personal_case(client, login["token"])
        await _fill_and_submit_personal(
            client, login["token"], case["case_id"], case["row_version"]
        )

        resp = await client.post(
            f"/api/v1/verification-cases/{case['case_id']}/decision",
            headers=auth_header(reviewer_token),
            json={"decision": "APPROVED"},
        )
        assert resp.status_code == 400 or resp.status_code == 409


@pytest.mark.asyncio
class TestVerificationMasking:
    async def test_user_sees_masked_data(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        case = await _create_personal_case(client, login["token"])
        await _fill_and_submit_personal(
            client, login["token"], case["case_id"], case["row_version"]
        )

        resp = await client.get(
            f"/api/v1/verification-cases/{case['case_id']}",
            headers=auth_header(login["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "**" in data.get("dob", "")
        assert "****" in data.get("government_id_number", "") or data.get("government_id_number", "").startswith("*")

    async def test_reviewer_sees_unmasked_data(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        case = await _create_personal_case(client, login["token"])
        await _fill_and_submit_personal(
            client, login["token"], case["case_id"], case["row_version"]
        )

        reviewer_token = await get_reviewer_token(client)
        resp = await client.get(
            f"/api/v1/verification-cases/{case['case_id']}",
            headers=auth_header(reviewer_token),
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data.get("dob") == "01/15/1990"
        assert data.get("government_id_number") == "A123456789"


@pytest.mark.asyncio
class TestVerificationWithdrawAndRenew:
    async def test_withdraw_draft_case(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        case = await _create_personal_case(client, login["token"])

        resp = await client.post(
            f"/api/v1/verification-cases/{case['case_id']}/withdraw",
            headers=auth_header(login["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "WITHDRAWN"

    async def test_get_verification_status(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        case = await _create_personal_case(client, login["token"])

        resp = await client.get(
            f"/api/v1/verification-cases/{case['case_id']}/status",
            headers=auth_header(login["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["status"] == "DRAFT"
        assert data["case_id"] == case["case_id"]
