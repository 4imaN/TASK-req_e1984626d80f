import uuid
from datetime import datetime, timedelta, timezone

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
class TestItemTagEndpoints:
    async def test_add_and_remove_tag_on_item(self, client: AsyncClient):
        admin_token = await get_admin_token(client)

        cat_resp = await client.post("/api/v1/categories", headers=auth_header(admin_token), json={
            "name": "C", "slug": f"c-{uuid.uuid4().hex[:6]}",
        })
        cat = cat_resp.json()["data"]

        tag_resp = await client.post("/api/v1/tags", headers=auth_header(admin_token), json={
            "name": "hiking", "slug": f"hiking-{uuid.uuid4().hex[:6]}",
        })
        tag = tag_resp.json()["data"]

        item_resp = await client.post("/api/v1/items", headers=auth_header(admin_token), json={
            "item_type": "SERVICE", "title": "Trip", "description": "A trip.",
            "category_id": cat["id"],
        })
        item = item_resp.json()["data"]

        add_resp = await client.post(
            f"/api/v1/items/{item['id']}/tags/{tag['id']}",
            headers=auth_header(admin_token),
        )
        assert add_resp.status_code == 201, add_resp.text
        assert add_resp.json()["data"]["tag_id"] == tag["id"]

        dup_resp = await client.post(
            f"/api/v1/items/{item['id']}/tags/{tag['id']}",
            headers=auth_header(admin_token),
        )
        assert dup_resp.status_code == 409

        del_resp = await client.delete(
            f"/api/v1/items/{item['id']}/tags/{tag['id']}",
            headers=auth_header(admin_token),
        )
        assert del_resp.status_code == 200

    async def test_non_owner_cannot_tag(self, client: AsyncClient):
        admin_token = await get_admin_token(client)

        cat_resp = await client.post("/api/v1/categories", headers=auth_header(admin_token), json={
            "name": "X", "slug": f"x-{uuid.uuid4().hex[:6]}",
        })
        cat = cat_resp.json()["data"]

        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        await client.post("/api/v1/admin/roles/assign", headers=auth_header(admin_token), json={
            "user_id": reg["user"]["id"], "role_name": "Instructor",
        })
        instructor = await login_user(client, reg["username"], reg["password"])

        item_resp = await client.post("/api/v1/items", headers=auth_header(instructor["token"]), json={
            "item_type": "SERVICE", "title": "Mine", "description": "Owned.",
            "category_id": cat["id"],
        })
        item = item_resp.json()["data"]

        tag_resp = await client.post("/api/v1/tags", headers=auth_header(admin_token), json={
            "name": "t", "slug": f"t-{uuid.uuid4().hex[:6]}",
        })
        tag = tag_resp.json()["data"]

        other_reg = await register_user(client)
        other = await login_user(client, other_reg["username"], other_reg["password"])

        resp = await client.post(
            f"/api/v1/items/{item['id']}/tags/{tag['id']}",
            headers=auth_header(other["token"]),
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
class TestBootstrapJobs:
    async def test_bootstrap_creates_recurring_jobs(self, client: AsyncClient):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        import os
        engine = create_async_engine(os.environ["DATABASE_URL"])
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as db:
            from scripts.bootstrap_jobs import bootstrap
            count = await bootstrap(db)
            assert count > 0
        await engine.dispose()

        async with factory() as db:
            from scripts.bootstrap_jobs import bootstrap
            count = await bootstrap(db)
            assert count == 0


@pytest.mark.asyncio
class TestShareLinkLogRetention:
    async def test_purges_old_access_logs(self, client: AsyncClient):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy import select
        import os
        engine = create_async_engine(os.environ["DATABASE_URL"])
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])
        asset = await upload_test_asset(client, login["token"])

        resp = await client.post(
            f"/api/v1/assets/{asset['asset_id']}/share-links",
            headers=auth_header(login["token"]),
            json={},
        )
        token = resp.json()["data"]["token"]
        await client.get(f"/api/v1/share-links/{token}/download")

        async with factory() as db:
            from src.trailgoods.models.assets import ShareLinkAccessLog
            result = await db.execute(select(ShareLinkAccessLog))
            logs = list(result.scalars().all())
            assert len(logs) >= 1
            old_time = datetime.now(timezone.utc) - timedelta(days=200)
            for log in logs:
                log.accessed_at = old_time
            await db.commit()

        async with factory() as db:
            from src.trailgoods.worker import handle_access_log_retention
            from src.trailgoods.models.jobs import Job
            dummy = Job(job_type="share_link_access_log_retention", status="RUNNING")
            db.add(dummy)
            await db.flush()
            await handle_access_log_retention(db, dummy)
            await db.commit()

        async with factory() as db:
            from src.trailgoods.models.assets import ShareLinkAccessLog
            result = await db.execute(select(ShareLinkAccessLog))
            remaining = list(result.scalars().all())
            assert len(remaining) == 0

        await engine.dispose()


@pytest.mark.asyncio
class TestThumbnailGeneration:
    async def test_jpeg_thumbnail_generated_on_upload(self, client: AsyncClient):
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (800, 600), color="red").save(buf, "JPEG")
        jpeg_bytes = buf.getvalue()

        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        asset = await upload_test_asset(
            client, login["token"], content=jpeg_bytes, filename="photo.jpg",
            mime_type="image/jpeg", kind="IMAGE", purpose="CATALOG",
        )

        resp = await client.get(
            f"/api/v1/assets/{asset['asset_id']}",
            headers=auth_header(login["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["has_thumbnail"] is True

    async def test_non_image_does_not_generate_thumbnail(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        asset = await upload_test_asset(
            client, login["token"], content=b"hello world" * 50,
            filename="doc.txt", mime_type="text/plain", kind="ATTACHMENT", purpose="GENERAL",
        )

        resp = await client.get(
            f"/api/v1/assets/{asset['asset_id']}",
            headers=auth_header(login["token"]),
        )
        data = resp.json()["data"]
        assert data["has_thumbnail"] is False


@pytest.mark.asyncio
class TestWorkerHandlers:
    async def test_recurring_job_reschedules_on_success(self, client: AsyncClient):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy import select
        import os
        import json as _json
        engine = create_async_engine(os.environ["DATABASE_URL"])
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with factory() as db:
            from src.trailgoods.models.jobs import Job
            job = Job(
                job_type="share_link_expiry_scan",
                status="PENDING",
                payload_json=_json.dumps({"recurring": True, "interval_seconds": 60}),
            )
            db.add(job)
            await db.commit()

        async with factory() as db:
            from src.trailgoods.worker import poll_and_execute
            executed = await poll_and_execute(db)
            assert executed >= 1

        async with factory() as db:
            from src.trailgoods.models.jobs import Job
            result = await db.execute(
                select(Job).where(
                    Job.job_type == "share_link_expiry_scan",
                    Job.status == "PENDING",
                )
            )
            pending = list(result.scalars().all())
            assert len(pending) >= 1

        await engine.dispose()
