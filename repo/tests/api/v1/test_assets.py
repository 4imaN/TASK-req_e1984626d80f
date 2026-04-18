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


@pytest.mark.asyncio
class TestUploadSession:
    async def test_create_upload_session(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        headers = auth_header(login["token"])

        resp = await client.post("/api/v1/assets/uploads", headers=headers, json={
            "filename": "photo.jpg",
            "mime_type": "image/jpeg",
            "total_size": 5000,
            "total_parts": 1,
            "kind": "IMAGE",
            "purpose": "GENERAL",
        })
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["upload_session_id"]
        assert data["status"] == "INITIATED"

    async def test_upload_invalid_mime(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        headers = auth_header(login["token"])

        resp = await client.post("/api/v1/assets/uploads", headers=headers, json={
            "filename": "malware.exe",
            "mime_type": "application/x-executable",
            "total_size": 5000,
            "total_parts": 1,
            "kind": "ATTACHMENT",
            "purpose": "GENERAL",
        })
        assert resp.status_code == 400

    async def test_upload_too_large(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        headers = auth_header(login["token"])

        resp = await client.post("/api/v1/assets/uploads", headers=headers, json={
            "filename": "huge.jpg",
            "mime_type": "image/jpeg",
            "total_size": 11 * 1024 * 1024,
            "total_parts": 1,
            "kind": "IMAGE",
            "purpose": "GENERAL",
        })
        assert resp.status_code == 400


@pytest.mark.asyncio
class TestUploadComplete:
    async def test_full_upload_flow(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        asset = await upload_test_asset(client, login["token"])
        assert asset["asset_id"]
        assert asset["asset_hash"]

    async def test_resumable_multipart_upload(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        headers = auth_header(login["token"])

        full_data = b"first chunk data " * 50 + b"second chunk data " * 50
        midpoint = len(full_data) // 2
        part1 = full_data[:midpoint]
        part2 = full_data[midpoint:]
        total = len(full_data)

        resp = await client.post("/api/v1/assets/uploads", headers=headers, json={
            "filename": "multi.txt",
            "mime_type": "text/plain",
            "total_size": total,
            "total_parts": 2,
            "kind": "ATTACHMENT",
            "purpose": "GENERAL",
        })
        assert resp.status_code == 201
        upload_id = resp.json()["data"]["upload_session_id"]

        resp2 = await client.put(
            f"/api/v1/assets/uploads/{upload_id}/parts/1",
            headers={**headers, "content-type": "application/octet-stream"},
            content=part1,
        )
        assert resp2.status_code == 200

        resp3 = await client.put(
            f"/api/v1/assets/uploads/{upload_id}/parts/2",
            headers={**headers, "content-type": "application/octet-stream"},
            content=part2,
        )
        assert resp3.status_code == 200

        resp4 = await client.post(
            f"/api/v1/assets/uploads/{upload_id}/complete",
            headers=headers,
        )
        assert resp4.status_code == 200
        assert resp4.json()["data"]["asset_hash"]

    async def test_sha256_dedup(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        content = b"identical content for dedup " * 100

        asset1 = await upload_test_asset(client, login["token"], content=content, filename="file1.txt", mime_type="text/plain", kind="ATTACHMENT")
        asset2 = await upload_test_asset(client, login["token"], content=content, filename="file2.txt", mime_type="text/plain", kind="ATTACHMENT")

        assert asset1["asset_hash"] == asset2["asset_hash"]
        assert asset1["asset_id"] != asset2["asset_id"]

    async def test_batch_complete(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        headers = auth_header(login["token"])

        session_ids = []
        for i in range(2):
            content = f"batch content {i}".encode() * 100
            resp = await client.post("/api/v1/assets/uploads", headers=headers, json={
                "filename": f"batch{i}.txt",
                "mime_type": "text/plain",
                "total_size": len(content),
                "total_parts": 1,
                "kind": "ATTACHMENT",
                "purpose": "GENERAL",
            })
            upload_id = resp.json()["data"]["upload_session_id"]

            await client.put(
                f"/api/v1/assets/uploads/{upload_id}/parts/1",
                headers={**headers, "content-type": "application/octet-stream"},
                content=content,
            )
            session_ids.append(upload_id)

        resp = await client.post("/api/v1/assets/uploads/batch-complete", headers=headers, json={
            "upload_session_ids": session_ids,
        })
        assert resp.status_code == 200
        results = resp.json()["data"]
        assert len(results) == 2
        for r in results:
            assert r["success"] is True


@pytest.mark.asyncio
class TestAssetAccess:
    async def test_get_own_asset(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        asset = await upload_test_asset(client, login["token"])

        resp = await client.get(
            f"/api/v1/assets/{asset['asset_id']}",
            headers=auth_header(login["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == asset["asset_id"]

    async def test_cannot_access_other_user_asset(self, client: AsyncClient):
        reg1 = await register_user(client)
        login1 = await login_user(client, reg1["username"], reg1["password"])
        asset = await upload_test_asset(client, login1["token"])

        reg2 = await register_user(client)
        login2 = await login_user(client, reg2["username"], reg2["password"])

        resp = await client.get(
            f"/api/v1/assets/{asset['asset_id']}",
            headers=auth_header(login2["token"]),
        )
        assert resp.status_code == 403

    async def test_admin_can_access_any_asset(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        asset = await upload_test_asset(client, login["token"])

        admin_token = await get_admin_token(client)
        resp = await client.get(
            f"/api/v1/assets/{asset['asset_id']}",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200

    async def test_delete_asset(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        asset = await upload_test_asset(client, login["token"])

        resp = await client.delete(
            f"/api/v1/assets/{asset['asset_id']}",
            headers=auth_header(login["token"]),
        )
        assert resp.status_code == 200

        resp2 = await client.get(
            f"/api/v1/assets/{asset['asset_id']}",
            headers=auth_header(login["token"]),
        )
        assert resp2.status_code == 404


@pytest.mark.asyncio
class TestShareLinks:
    async def test_create_share_link(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        asset = await upload_test_asset(client, login["token"])

        resp = await client.post(
            f"/api/v1/assets/{asset['asset_id']}/share-links",
            headers=auth_header(login["token"]),
            json={"expires_in_days": 7, "max_downloads": 10},
        )
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["token"]
        assert data["max_downloads"] == 10

    async def test_access_share_link(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        asset = await upload_test_asset(client, login["token"])

        resp = await client.post(
            f"/api/v1/assets/{asset['asset_id']}/share-links",
            headers=auth_header(login["token"]),
            json={},
        )
        token = resp.json()["data"]["token"]

        resp2 = await client.get(f"/api/v1/share-links/{token}")
        assert resp2.status_code == 200
        data = resp2.json()["data"]
        assert data["asset_id"] == asset["asset_id"]

    async def test_share_link_with_password(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        asset = await upload_test_asset(client, login["token"])

        resp = await client.post(
            f"/api/v1/assets/{asset['asset_id']}/share-links",
            headers=auth_header(login["token"]),
            json={"password": "Str0ngP@ss"},
        )
        token = resp.json()["data"]["token"]

        resp_no_pw = await client.get(f"/api/v1/share-links/{token}")
        assert resp_no_pw.status_code == 400

        resp_wrong = await client.get(
            f"/api/v1/share-links/{token}",
            headers={"X-Share-Password": "wrong"},
        )
        assert resp_wrong.status_code == 400

        resp_correct = await client.get(
            f"/api/v1/share-links/{token}",
            headers={"X-Share-Password": "Str0ngP@ss"},
        )
        assert resp_correct.status_code == 200

    async def test_share_link_max_downloads(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        asset = await upload_test_asset(client, login["token"])

        resp = await client.post(
            f"/api/v1/assets/{asset['asset_id']}/share-links",
            headers=auth_header(login["token"]),
            json={"max_downloads": 2},
        )
        token = resp.json()["data"]["token"]

        meta = await client.get(f"/api/v1/share-links/{token}")
        assert meta.status_code == 200

        r1 = await client.get(f"/api/v1/share-links/{token}/download")
        assert r1.status_code == 200
        r2 = await client.get(f"/api/v1/share-links/{token}/download")
        assert r2.status_code == 200
        r3 = await client.get(f"/api/v1/share-links/{token}/download")
        assert r3.status_code == 400

    async def test_verification_asset_cannot_be_shared(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        asset = await upload_test_asset(
            client, login["token"], purpose="VERIFICATION", kind="VERIFICATION_ID",
        )

        resp = await client.post(
            f"/api/v1/assets/{asset['asset_id']}/share-links",
            headers=auth_header(login["token"]),
            json={},
        )
        assert resp.status_code == 400

    async def test_share_link_password_too_short(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        asset = await upload_test_asset(client, login["token"])

        resp = await client.post(
            f"/api/v1/assets/{asset['asset_id']}/share-links",
            headers=auth_header(login["token"]),
            json={"password": "short"},
        )
        assert resp.status_code == 400
