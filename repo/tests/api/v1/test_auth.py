import asyncio
import time
import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import auth_header, get_admin_token, login_user, register_user


@pytest.mark.asyncio
class TestRegistration:
    async def test_register_success(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/register", json={
            "username": "newuser1",
            "password": "ValidP@ssw0rd!",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["data"]["username"] == "newuser1"
        assert data["meta"]["request_id"]

    async def test_register_duplicate_username(self, client: AsyncClient):
        await client.post("/api/v1/auth/register", json={
            "username": "dupuser",
            "password": "ValidP@ssw0rd!",
        })
        resp = await client.post("/api/v1/auth/register", json={
            "username": "dupuser",
            "password": "ValidP@ssw0rd!",
        })
        assert resp.status_code == 409

    async def test_register_case_insensitive_duplicate(self, client: AsyncClient):
        await client.post("/api/v1/auth/register", json={
            "username": "CaseUser",
            "password": "ValidP@ssw0rd!",
        })
        resp = await client.post("/api/v1/auth/register", json={
            "username": "caseuser",
            "password": "ValidP@ssw0rd!",
        })
        assert resp.status_code == 409

    async def test_register_invalid_username_too_short(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/register", json={
            "username": "ab",
            "password": "ValidP@ssw0rd!",
        })
        assert resp.status_code == 422

    async def test_register_invalid_username_special_chars(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/register", json={
            "username": "bad user!",
            "password": "ValidP@ssw0rd!",
        })
        assert resp.status_code == 422

    async def test_register_password_too_short(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/register", json={
            "username": "shortpwuser",
            "password": "Short1!",
        })
        assert resp.status_code == 422

    async def test_register_password_no_digit(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/register", json={
            "username": "nodigituser",
            "password": "NoDigitsHere!!!",
        })
        assert resp.status_code == 422

    async def test_register_password_no_symbol(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/register", json={
            "username": "nosymboluser",
            "password": "NoSymbolsHere123",
        })
        assert resp.status_code == 422

    async def test_register_with_email(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/register", json={
            "username": "emailuser",
            "password": "ValidP@ssw0rd!",
            "email": "test@example.com",
        })
        assert resp.status_code == 201
        assert resp.json()["data"]["email"] == "test@example.com"


@pytest.mark.asyncio
class TestLogin:
    async def test_login_success(self, client: AsyncClient):
        reg = await register_user(client, "loginuser1")
        login = await login_user(client, reg["username"], reg["password"])
        assert login["token"]
        assert login["session"]["status"] == "ACTIVE"
        assert login["user"]["username"] == reg["username"]

    async def test_login_case_insensitive(self, client: AsyncClient):
        reg = await register_user(client, "LoginCase")
        login = await login_user(client, "logincase", reg["password"])
        assert login["token"]

    async def test_login_invalid_password(self, client: AsyncClient):
        reg = await register_user(client, "badpwuser")
        resp = await client.post("/api/v1/auth/login", json={
            "username": reg["username"],
            "password": "WrongPassword1!",
        })
        assert resp.status_code == 401

    async def test_login_nonexistent_user(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/login", json={
            "username": "doesnotexist",
            "password": "ValidP@ssw0rd!",
        })
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestLogout:
    async def test_logout_success(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        resp = await client.post(
            "/api/v1/auth/logout",
            headers=auth_header(login["token"]),
        )
        assert resp.status_code == 200

        resp2 = await client.get(
            "/api/v1/sessions/me",
            headers=auth_header(login["token"]),
        )
        assert resp2.status_code == 401

    async def test_logout_all(self, client: AsyncClient):
        reg = await register_user(client)
        login1 = await login_user(client, reg["username"], reg["password"])
        login2 = await login_user(client, reg["username"], reg["password"])

        resp = await client.post(
            "/api/v1/auth/logout-all",
            headers=auth_header(login1["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["revoked_sessions"] >= 2

        resp2 = await client.get(
            "/api/v1/sessions/me",
            headers=auth_header(login2["token"]),
        )
        assert resp2.status_code == 401

    async def test_logout_without_auth(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/logout")
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestPasswordRotation:
    async def test_password_rotate_success(self, client: AsyncClient):
        reg = await register_user(client, password="OldP@ssword123!")
        login = await login_user(client, reg["username"], "OldP@ssword123!")

        resp = await client.post(
            "/api/v1/auth/password-rotate",
            headers=auth_header(login["token"]),
            json={
                "current_password": "OldP@ssword123!",
                "new_password": "NewP@ssword456!",
            },
        )
        assert resp.status_code == 200

        resp2 = await client.get(
            "/api/v1/sessions/me",
            headers=auth_header(login["token"]),
        )
        assert resp2.status_code == 401

        login2 = await login_user(client, reg["username"], "NewP@ssword456!")
        assert login2["token"]

    async def test_password_rotate_wrong_current(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        resp = await client.post(
            "/api/v1/auth/password-rotate",
            headers=auth_header(login["token"]),
            json={
                "current_password": "WrongCurrent1!",
                "new_password": "NewP@ssword456!",
            },
        )
        assert resp.status_code == 400

    async def test_password_rotate_reuse_blocked(self, client: AsyncClient):
        reg = await register_user(client, password="Original@Pass1!")
        login = await login_user(client, reg["username"], "Original@Pass1!")

        resp = await client.post(
            "/api/v1/auth/password-rotate",
            headers=auth_header(login["token"]),
            json={
                "current_password": "Original@Pass1!",
                "new_password": "Original@Pass1!",
            },
        )
        assert resp.status_code == 400


@pytest.mark.asyncio
class TestSessionManagement:
    async def test_get_my_sessions(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        resp = await client.get(
            "/api/v1/sessions/me",
            headers=auth_header(login["token"]),
        )
        assert resp.status_code == 200
        sessions = resp.json()["data"]
        assert len(sessions) >= 1

    async def test_revoke_specific_session(self, client: AsyncClient):
        reg = await register_user(client)
        login1 = await login_user(client, reg["username"], reg["password"])
        login2 = await login_user(client, reg["username"], reg["password"])

        session_id = login1["session"]["id"]
        resp = await client.delete(
            f"/api/v1/sessions/{session_id}",
            headers=auth_header(login2["token"]),
        )
        assert resp.status_code == 200

        resp2 = await client.get(
            "/api/v1/sessions/me",
            headers=auth_header(login1["token"]),
        )
        assert resp2.status_code == 401

    async def test_invalid_token(self, client: AsyncClient):
        resp = await client.get(
            "/api/v1/sessions/me",
            headers={"Authorization": "Bearer invalidtoken"},
        )
        assert resp.status_code == 401

    async def test_missing_auth_header(self, client: AsyncClient):
        resp = await client.get("/api/v1/sessions/me")
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestFailedLoginLockout:
    async def test_lockout_after_5_failures(self, client: AsyncClient):
        reg = await register_user(client, "lockoutuser")
        login_data = await login_user(client, reg["username"], reg["password"])
        token = login_data["token"]

        for i in range(5):
            resp = await client.post("/api/v1/auth/login", json={
                "username": reg["username"],
                "password": "WrongPassword1!",
            })
            assert resp.status_code == 401

        resp = await client.post("/api/v1/auth/login", json={
            "username": reg["username"],
            "password": reg["password"],
        })
        assert resp.status_code == 401, f"Expected 401 but got {resp.status_code}: {resp.text}"
        detail = resp.json()["detail"].lower()
        assert "locked" in detail or "challenge" in detail

        resp2 = await client.get(
            "/api/v1/sessions/me",
            headers=auth_header(token),
        )
        assert resp2.status_code == 401


@pytest.mark.asyncio
class TestSessionIdleTimeout:
    async def test_idle_timeout_enforcement(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        from datetime import datetime, timedelta, timezone
        from sqlalchemy import text, update
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.trailgoods.core.database import get_session_factory
        from src.trailgoods.models.auth import Session as SessionModel
        from src.trailgoods.services.auth import hash_token

        token_h = hash_token(login["token"])
        past = datetime.now(timezone.utc) - timedelta(minutes=31)

        factory = get_session_factory()
        async with factory() as db:
            await db.execute(
                update(SessionModel)
                .where(SessionModel.token_hash == token_h)
                .values(last_activity_at=past)
            )
            await db.commit()

        resp = await client.get(
            "/api/v1/sessions/me",
            headers=auth_header(login["token"]),
        )
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestIdentityBindings:
    async def test_create_binding(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        resp = await client.post(
            "/api/v1/identity-bindings",
            headers=auth_header(login["token"]),
            json={
                "binding_type": "STAFF_ID",
                "institution_code": "MIT",
                "external_id": "S12345",
            },
        )
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["binding_type"] == "STAFF_ID"
        assert data["institution_code"] == "MIT"
        assert "2345" in data["external_id"]
        assert data["status"] == "ACTIVE"

    async def test_list_bindings(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        await client.post(
            "/api/v1/identity-bindings",
            headers=auth_header(login["token"]),
            json={
                "binding_type": "STUDENT_ID",
                "institution_code": "STANFORD",
                "external_id": "STU001",
            },
        )

        resp = await client.get(
            "/api/v1/identity-bindings",
            headers=auth_header(login["token"]),
        )
        assert resp.status_code == 200
        assert len(resp.json()["data"]) >= 1

    async def test_rebinding_revokes_old(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        await client.post(
            "/api/v1/identity-bindings",
            headers=auth_header(login["token"]),
            json={
                "binding_type": "STAFF_ID",
                "institution_code": "CALTECH",
                "external_id": "OLD001",
            },
        )

        await client.post(
            "/api/v1/identity-bindings",
            headers=auth_header(login["token"]),
            json={
                "binding_type": "STAFF_ID",
                "institution_code": "CALTECH",
                "external_id": "NEW001",
            },
        )

        resp = await client.get(
            "/api/v1/identity-bindings",
            headers=auth_header(login["token"]),
        )
        data = resp.json()["data"]
        caltech = [b for b in data if b["institution_code"] == "CALTECH"]
        active = [b for b in caltech if b["status"] == "ACTIVE"]
        revoked = [b for b in caltech if b["status"] == "REVOKED"]
        assert len(active) == 1
        assert "W001" in active[0]["external_id"]
        assert len(revoked) == 1

    async def test_invalid_institution_code(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        resp = await client.post(
            "/api/v1/identity-bindings",
            headers=auth_header(login["token"]),
            json={
                "binding_type": "STAFF_ID",
                "institution_code": "invalid!",
                "external_id": "S12345",
            },
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
class TestRBACAndAdmin:
    async def test_admin_assign_role(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        user_reg = await register_user(client)

        resp = await client.post(
            "/api/v1/admin/roles/assign",
            headers=auth_header(admin_token),
            json={
                "user_id": user_reg["user"]["id"],
                "role_name": "Instructor",
            },
        )
        assert resp.status_code == 200

    async def test_non_admin_cannot_assign_role(self, client: AsyncClient):
        reg = await register_user(client)
        login_data = await login_user(client, reg["username"], reg["password"])

        resp = await client.post(
            "/api/v1/admin/roles/assign",
            headers=auth_header(login_data["token"]),
            json={
                "user_id": reg["user"]["id"],
                "role_name": "Admin",
            },
        )
        assert resp.status_code == 403

    async def test_admin_force_logout(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        user_reg = await register_user(client)
        user_login = await login_user(client, user_reg["username"], user_reg["password"])

        resp = await client.post(
            "/api/v1/admin/force-logout",
            headers=auth_header(admin_token),
            json={"user_id": user_reg["user"]["id"]},
        )
        assert resp.status_code == 200

        resp2 = await client.get(
            "/api/v1/sessions/me",
            headers=auth_header(user_login["token"]),
        )
        assert resp2.status_code == 401

    async def test_admin_audit_logs(self, client: AsyncClient):
        admin_token = await get_admin_token(client)

        resp = await client.get(
            "/api/v1/admin/audit-logs",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert len(resp.json()["data"]) > 0
        assert resp.json()["meta"]["pagination"]["total"] > 0

    async def test_non_admin_cannot_view_audit_logs(self, client: AsyncClient):
        reg = await register_user(client)
        login_data = await login_user(client, reg["username"], reg["password"])

        resp = await client.get(
            "/api/v1/admin/audit-logs",
            headers=auth_header(login_data["token"]),
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
class TestRequestCorrelation:
    async def test_request_id_echoed(self, client: AsyncClient):
        custom_id = str(uuid.uuid4())
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "username": "reqiduser",
                "password": "ValidP@ssw0rd!",
            },
            headers={"X-Request-ID": custom_id},
        )
        assert resp.headers.get("x-request-id") == custom_id
        assert resp.json()["meta"]["request_id"] == custom_id

    async def test_request_id_generated_when_missing(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "username": "noreqiduser",
                "password": "ValidP@ssw0rd!",
            },
        )
        assert resp.headers.get("x-request-id")
        assert resp.json()["meta"]["request_id"]
