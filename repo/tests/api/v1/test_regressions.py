import json
import os
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests.conftest import (
    auth_header,
    get_admin_token,
    get_reviewer_token,
    login_user,
    register_user,
    upload_test_asset,
)


async def _get_or_create_default_pb(client, admin_token) -> str:
    resp = await client.post("/api/v1/price-books", headers=auth_header(admin_token), json={
        "name": f"PB-{uuid.uuid4().hex[:6]}", "is_default": True,
    })
    if resp.status_code == 201:
        return resp.json()["data"]["id"]
    engine = create_async_engine(os.environ["DATABASE_URL"])
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        from src.trailgoods.models.catalog import PriceBook
        r = await db.execute(select(PriceBook).where(PriceBook.is_default == True))
        pb_id = str(r.scalar_one().id)
    await engine.dispose()
    return pb_id


@pytest.mark.asyncio
class TestLivePetLifecycle:
    async def test_live_pet_create_publish_flow(self, client: AsyncClient):
        admin_token = await get_admin_token(client)

        cat_r = await client.post("/api/v1/categories", headers=auth_header(admin_token), json={
            "name": "Pets", "slug": f"pets-{uuid.uuid4().hex[:6]}",
        })
        cat = cat_r.json()["data"]

        item_r = await client.post("/api/v1/items", headers=auth_header(admin_token), json={
            "item_type": "LIVE_PET", "title": "Baby Gecko", "description": "A lovely gecko.",
            "category_id": cat["id"],
        })
        assert item_r.status_code == 201
        item = item_r.json()["data"]
        assert item["type"] == "LIVE_PET"

        spu_r = await client.post("/api/v1/spus", headers=auth_header(admin_token), json={
            "item_id": item["id"], "spu_code": f"PET-{uuid.uuid4().hex[:6]}",
        })
        assert spu_r.status_code == 201, spu_r.text
        spu = spu_r.json()["data"]

        sku_r = await client.post(f"/api/v1/spus/{spu['id']}/skus", headers=auth_header(admin_token), json={
            "sku_code": f"GECKO-{uuid.uuid4().hex[:6]}",
        })
        assert sku_r.status_code == 201
        sku = sku_r.json()["data"]

        asset = await upload_test_asset(client, admin_token)
        await client.post(f"/api/v1/items/{item['id']}/media", headers=auth_header(admin_token), json={
            "asset_id": asset["asset_id"], "scope": "ITEM",
        })

        pb_id = await _get_or_create_default_pb(client, admin_token)
        await client.post(f"/api/v1/price-books/{pb_id}/entries", headers=auth_header(admin_token), json={
            "target_type": "ITEM", "target_id": item["id"], "amount_cents": 29900,
        })

        pub_r = await client.post(f"/api/v1/items/{item['id']}/publish", headers=auth_header(admin_token))
        assert pub_r.status_code == 200, pub_r.text
        assert pub_r.json()["data"]["status"] == "PUBLISHED"


@pytest.mark.asyncio
class TestAdminUploadOwnership:
    async def test_admin_completing_upload_preserves_original_owner(self, client: AsyncClient):
        owner_reg = await register_user(client)
        owner = await login_user(client, owner_reg["username"], owner_reg["password"])

        content = b"owned content " * 100
        resp = await client.post("/api/v1/assets/uploads", headers=auth_header(owner["token"]), json={
            "filename": "mine.txt", "mime_type": "text/plain",
            "total_size": len(content), "total_parts": 1, "kind": "ATTACHMENT", "purpose": "GENERAL",
        })
        upload_id = resp.json()["data"]["upload_session_id"]

        await client.put(
            f"/api/v1/assets/uploads/{upload_id}/parts/1",
            headers={**auth_header(owner["token"]), "content-type": "application/octet-stream"},
            content=content,
        )

        admin_token = await get_admin_token(client)
        complete_r = await client.post(
            f"/api/v1/assets/uploads/{upload_id}/complete",
            headers=auth_header(admin_token),
        )
        assert complete_r.status_code == 200
        asset_id = complete_r.json()["data"]["asset_id"]

        asset_r = await client.get(f"/api/v1/assets/{asset_id}", headers=auth_header(admin_token))
        assert asset_r.json()["data"]["owner_user_id"] == owner_reg["user"]["id"]


@pytest.mark.asyncio
class TestEnterpriseVerificationFields:
    async def test_enterprise_registration_number_is_optional(self, client: AsyncClient):
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
                "enterprise_legal_name": "NoReg Corp",
                "responsible_person_legal_name": "Jane",
                "responsible_person_dob": "05/10/1985",
                "responsible_person_id_number": "RP999",
                "responsible_person_id_image_asset_id": asset["asset_id"],
            },
        )

        submit_r = await client.post(
            f"/api/v1/verification-cases/{case['case_id']}/submit",
            headers=auth_header(login["token"]),
        )
        assert submit_r.status_code == 200

    async def test_enterprise_missing_responsible_person_rejected(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        case_r = await client.post("/api/v1/verification-cases", headers=auth_header(login["token"]), json={
            "profile_type": "ENTERPRISE",
        })
        case = case_r.json()["data"]

        await client.patch(
            f"/api/v1/verification-cases/{case['case_id']}",
            headers=auth_header(login["token"]),
            json={
                "row_version": case["row_version"],
                "enterprise_legal_name": "Corp Only",
            },
        )

        submit_r = await client.post(
            f"/api/v1/verification-cases/{case['case_id']}/submit",
            headers=auth_header(login["token"]),
        )
        assert submit_r.status_code == 400


@pytest.mark.asyncio
class TestVerificationRevisionOnUpdate:
    async def test_revision_created_on_each_update(self, client: AsyncClient):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy import select, func
        import os

        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        case_r = await client.post("/api/v1/verification-cases", headers=auth_header(login["token"]), json={
            "profile_type": "PERSONAL",
        })
        case = case_r.json()["data"]

        await client.patch(
            f"/api/v1/verification-cases/{case['case_id']}",
            headers=auth_header(login["token"]),
            json={"row_version": case["row_version"], "legal_name": "First Name"},
        )

        engine = create_async_engine(os.environ["DATABASE_URL"])
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as db:
            from src.trailgoods.models.verification import VerificationCase, VerificationCaseRevision
            vc_result = await db.execute(
                select(VerificationCase).where(VerificationCase.case_id == case["case_id"])
            )
            vc = vc_result.scalar_one()
            rev_count = await db.execute(
                select(func.count()).where(VerificationCaseRevision.case_id == vc.id)
            )
            assert rev_count.scalar() >= 1
        await engine.dispose()


@pytest.mark.asyncio
class TestItemAttributes:
    async def test_create_and_list_attributes(self, client: AsyncClient):
        admin_token = await get_admin_token(client)

        cat_r = await client.post("/api/v1/categories", headers=auth_header(admin_token), json={
            "name": "AttrCat", "slug": f"attr-{uuid.uuid4().hex[:6]}",
        })
        cat = cat_r.json()["data"]

        item_r = await client.post("/api/v1/items", headers=auth_header(admin_token), json={
            "item_type": "PRODUCT", "title": "Boots", "description": "Hiking boots.",
            "category_id": cat["id"],
        })
        item = item_r.json()["data"]

        attr_r = await client.post(
            f"/api/v1/items/{item['id']}/attributes",
            headers=auth_header(admin_token),
            json={"scope": "ITEM", "key": "weight_grams", "value_number": 850.0},
        )
        assert attr_r.status_code == 201
        attr = attr_r.json()["data"]
        assert attr["key"] == "weight_grams"

        list_r = await client.get(f"/api/v1/items/{item['id']}/attributes", headers=auth_header(admin_token))
        assert list_r.status_code == 200
        assert len(list_r.json()["data"]) >= 1

        del_r = await client.delete(
            f"/api/v1/items/{item['id']}/attributes/{attr['id']}",
            headers=auth_header(admin_token),
        )
        assert del_r.status_code == 200


@pytest.mark.asyncio
class TestAuditAttribution:
    async def test_privileged_audit_has_actor(self, client: AsyncClient):
        admin_token = await get_admin_token(client)

        cat_r = await client.post("/api/v1/categories", headers=auth_header(admin_token), json={
            "name": "AuditCat", "slug": f"audit-{uuid.uuid4().hex[:6]}",
        })
        assert cat_r.status_code == 201

        logs_r = await client.get("/api/v1/admin/audit-logs", headers=auth_header(admin_token), params={"limit": 5})
        logs = logs_r.json()["data"]
        cat_logs = [l for l in logs if l["action"] == "catalog.category.create"]
        assert len(cat_logs) >= 1
        assert cat_logs[0]["actor_user_id"] is not None


async def _make_sku_priced_published_product(client, admin_token, amount_cents=9999):
    """Helper: creates a published PRODUCT with SKU-targeted pricing (no ITEM price)."""
    cat_r = await client.post("/api/v1/categories", headers=auth_header(admin_token), json={
        "name": f"Cat-{uuid.uuid4().hex[:6]}", "slug": f"cat-{uuid.uuid4().hex[:6]}",
    })
    cat = cat_r.json()["data"]
    item_r = await client.post("/api/v1/items", headers=auth_header(admin_token), json={
        "item_type": "PRODUCT", "title": f"SKU-Priced-{uuid.uuid4().hex[:6]}",
        "description": "desc", "category_id": cat["id"],
    })
    item = item_r.json()["data"]
    asset = await upload_test_asset(client, admin_token)
    await client.post(f"/api/v1/items/{item['id']}/media", headers=auth_header(admin_token), json={
        "asset_id": asset["asset_id"], "scope": "ITEM",
    })
    spu_r = await client.post("/api/v1/spus", headers=auth_header(admin_token), json={
        "item_id": item["id"], "spu_code": f"SPU-{uuid.uuid4().hex[:8]}",
    })
    spu = spu_r.json()["data"]
    sku_r = await client.post(f"/api/v1/spus/{spu['id']}/skus", headers=auth_header(admin_token), json={
        "sku_code": f"SKU-{uuid.uuid4().hex[:8]}",
    })
    sku = sku_r.json()["data"]
    pb_id = await _get_or_create_default_pb(client, admin_token)
    await client.post(f"/api/v1/price-books/{pb_id}/entries", headers=auth_header(admin_token), json={
        "target_type": "SKU", "target_id": sku["id"], "amount_cents": amount_cents,
    })
    pub_r = await client.post(f"/api/v1/items/{item['id']}/publish", headers=auth_header(admin_token))
    assert pub_r.status_code == 200, pub_r.text
    return {"item": item, "spu": spu, "sku": sku, "category": cat, "price_book_id": pb_id}


@pytest.mark.asyncio
class TestSKUPriceReadCorrectness:
    """Issues 1 & 7: SKU-priced items must show correct price in list/detail and sort correctly."""

    async def test_sku_priced_item_shows_price_in_list(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        prod = await _make_sku_priced_published_product(client, admin_token, amount_cents=4500)
        r = await client.get("/api/v1/catalog/items")
        assert r.status_code == 200
        items = r.json()["data"]
        match = [i for i in items if i["id"] == prod["item"]["id"]]
        assert len(match) == 1
        assert match[0]["price_cents"] == 4500

    async def test_sku_priced_item_shows_price_in_detail(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        prod = await _make_sku_priced_published_product(client, admin_token, amount_cents=7700)
        r = await client.get(f"/api/v1/items/{prod['item']['id']}")
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data["prices"]) >= 1
        sku_prices = [p for p in data["prices"] if p["target_type"] == "SKU"]
        assert len(sku_prices) >= 1
        assert sku_prices[0]["amount_cents"] == 7700

    async def test_sku_price_sort_asc(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cheap = await _make_sku_priced_published_product(client, admin_token, amount_cents=1000)
        expensive = await _make_sku_priced_published_product(client, admin_token, amount_cents=99000)
        r = await client.get("/api/v1/catalog/items", params={"sort_by": "price_asc"})
        assert r.status_code == 200
        items = r.json()["data"]
        ids = [i["id"] for i in items]
        cheap_idx = ids.index(cheap["item"]["id"])
        expensive_idx = ids.index(expensive["item"]["id"])
        assert cheap_idx < expensive_idx

    async def test_sku_price_sort_desc(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        cheap = await _make_sku_priced_published_product(client, admin_token, amount_cents=1000)
        expensive = await _make_sku_priced_published_product(client, admin_token, amount_cents=99000)
        r = await client.get("/api/v1/catalog/items", params={"sort_by": "price_desc"})
        assert r.status_code == 200
        items = r.json()["data"]
        ids = [i["id"] for i in items]
        cheap_idx = ids.index(cheap["item"]["id"])
        expensive_idx = ids.index(expensive["item"]["id"])
        assert expensive_idx < cheap_idx


@pytest.mark.asyncio
class TestPriceCreateAuditAttribution:
    """Issue 2 & 8: catalog.price.create audit log must include actor_user_id."""

    async def test_price_create_audit_has_actor(self, client: AsyncClient):
        admin_token = await get_admin_token(client)
        pb_id = await _get_or_create_default_pb(client, admin_token)
        cat_r = await client.post("/api/v1/categories", headers=auth_header(admin_token), json={
            "name": f"AuditPriceCat-{uuid.uuid4().hex[:6]}", "slug": f"apc-{uuid.uuid4().hex[:6]}",
        })
        cat = cat_r.json()["data"]
        item_r = await client.post("/api/v1/items", headers=auth_header(admin_token), json={
            "item_type": "SERVICE", "title": f"PriceAudit-{uuid.uuid4().hex[:6]}",
            "description": "d", "category_id": cat["id"],
        })
        item = item_r.json()["data"]
        entry_r = await client.post(f"/api/v1/price-books/{pb_id}/entries", headers=auth_header(admin_token), json={
            "target_type": "ITEM", "target_id": item["id"], "amount_cents": 5000,
        })
        assert entry_r.status_code == 201

        logs_r = await client.get("/api/v1/admin/audit-logs", headers=auth_header(admin_token), params={"limit": 20})
        logs = logs_r.json()["data"]
        price_logs = [l for l in logs if l["action"] == "catalog.price.create"]
        assert len(price_logs) >= 1
        assert price_logs[0]["actor_user_id"] is not None


@pytest.mark.asyncio
class TestLivePetDetailSPUSKU:
    """Issue 3: LIVE_PET detail must include spu/skus."""

    async def test_published_live_pet_detail_has_spu_skus(self, client: AsyncClient):
        admin_token = await get_admin_token(client)

        cat_r = await client.post("/api/v1/categories", headers=auth_header(admin_token), json={
            "name": f"PetCat-{uuid.uuid4().hex[:6]}", "slug": f"petcat-{uuid.uuid4().hex[:6]}",
        })
        cat = cat_r.json()["data"]

        item_r = await client.post("/api/v1/items", headers=auth_header(admin_token), json={
            "item_type": "LIVE_PET", "title": f"Parrot-{uuid.uuid4().hex[:6]}",
            "description": "A beautiful parrot.", "category_id": cat["id"],
        })
        item = item_r.json()["data"]

        spu_r = await client.post("/api/v1/spus", headers=auth_header(admin_token), json={
            "item_id": item["id"], "spu_code": f"PET-{uuid.uuid4().hex[:8]}",
        })
        spu = spu_r.json()["data"]

        sku_r = await client.post(f"/api/v1/spus/{spu['id']}/skus", headers=auth_header(admin_token), json={
            "sku_code": f"PARROT-{uuid.uuid4().hex[:6]}",
        })
        sku = sku_r.json()["data"]

        asset = await upload_test_asset(client, admin_token)
        await client.post(f"/api/v1/items/{item['id']}/media", headers=auth_header(admin_token), json={
            "asset_id": asset["asset_id"], "scope": "ITEM",
        })

        pb_id = await _get_or_create_default_pb(client, admin_token)
        await client.post(f"/api/v1/price-books/{pb_id}/entries", headers=auth_header(admin_token), json={
            "target_type": "ITEM", "target_id": item["id"], "amount_cents": 35000,
        })

        pub_r = await client.post(f"/api/v1/items/{item['id']}/publish", headers=auth_header(admin_token))
        assert pub_r.status_code == 200

        detail_r = await client.get(f"/api/v1/items/{item['id']}")
        assert detail_r.status_code == 200
        data = detail_r.json()["data"]
        assert data["type"] == "LIVE_PET"
        assert data["spu"] is not None
        assert data["spu"]["spu_code"] == spu["spu_code"]
        assert len(data["skus"]) == 1
        assert data["skus"][0]["sku_code"] == sku["sku_code"]


@pytest.mark.asyncio
class TestVerificationSnapshotCompleteness:
    """Issues 4 & 9: Verification snapshot must include all mutable fields."""

    async def test_enterprise_snapshot_includes_all_fields(self, client: AsyncClient):
        reg = await register_user(client)
        login = await login_user(client, reg["username"], reg["password"])

        case_r = await client.post("/api/v1/verification-cases", headers=auth_header(login["token"]), json={
            "profile_type": "ENTERPRISE",
        })
        case = case_r.json()["data"]

        import io
        from PIL import Image as _PILImg
        buf1 = io.BytesIO()
        _PILImg.new("RGB", (50, 50), color="red").save(buf1, "JPEG")
        buf2 = io.BytesIO()
        _PILImg.new("RGB", (50, 50), color="green").save(buf2, "JPEG")
        reg_asset = await upload_test_asset(client, login["token"], content=buf1.getvalue(), purpose="VERIFICATION", kind="VERIFICATION_ID")
        rp_asset = await upload_test_asset(client, login["token"], content=buf2.getvalue(), purpose="VERIFICATION", kind="VERIFICATION_ID")

        await client.patch(
            f"/api/v1/verification-cases/{case['case_id']}",
            headers=auth_header(login["token"]),
            json={
                "row_version": case["row_version"],
                "enterprise_legal_name": "Snapshot Corp",
                "enterprise_registration_number": "SNP-12345",
                "enterprise_registration_asset_id": reg_asset["asset_id"],
                "responsible_person_legal_name": "Snap Person",
                "responsible_person_dob": "06/15/1980",
                "responsible_person_id_number": "RPSNP-999",
                "responsible_person_id_image_asset_id": rp_asset["asset_id"],
            },
        )

        engine = create_async_engine(os.environ["DATABASE_URL"])
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as db:
            from src.trailgoods.models.verification import VerificationCase, VerificationCaseRevision
            vc_result = await db.execute(
                select(VerificationCase).where(VerificationCase.case_id == case["case_id"])
            )
            vc = vc_result.scalar_one()
            rev_result = await db.execute(
                select(VerificationCaseRevision)
                .where(VerificationCaseRevision.case_id == vc.id)
                .order_by(VerificationCaseRevision.revision_number.desc())
            )
            latest_rev = rev_result.scalars().first()
            assert latest_rev is not None
            snapshot = json.loads(latest_rev.snapshot_json)

            assert "enterprise_legal_name_encrypted" in snapshot
            assert snapshot["enterprise_legal_name_encrypted"] is not None
            assert "enterprise_registration_number_encrypted" in snapshot
            assert snapshot["enterprise_registration_number_encrypted"] is not None
            assert "enterprise_registration_asset_id" in snapshot
            assert snapshot["enterprise_registration_asset_id"] is not None
            assert "responsible_person_legal_name_encrypted" in snapshot
            assert snapshot["responsible_person_legal_name_encrypted"] is not None
            assert "responsible_person_dob_encrypted" in snapshot
            assert snapshot["responsible_person_dob_encrypted"] is not None
            assert "responsible_person_id_number_encrypted" in snapshot
            assert snapshot["responsible_person_id_number_encrypted"] is not None
            assert "responsible_person_id_image_asset_id" in snapshot
            assert snapshot["responsible_person_id_image_asset_id"] is not None
        await engine.dispose()


@pytest.mark.asyncio
class TestReorderAlertDedup:
    """Issues 5 & 10: Repeated scans must not create duplicate active alerts."""

    async def test_repeated_scan_no_duplicate_alerts(self, client: AsyncClient):
        admin_token = await get_admin_token(client)

        cat_r = await client.post("/api/v1/categories", headers=auth_header(admin_token), json={
            "name": f"AlertCat-{uuid.uuid4().hex[:6]}", "slug": f"alertcat-{uuid.uuid4().hex[:6]}",
        })
        cat = cat_r.json()["data"]
        item_r = await client.post("/api/v1/items", headers=auth_header(admin_token), json={
            "item_type": "PRODUCT", "title": f"AlertItem-{uuid.uuid4().hex[:6]}",
            "description": "d", "category_id": cat["id"],
        })
        item = item_r.json()["data"]
        spu_r = await client.post("/api/v1/spus", headers=auth_header(admin_token), json={
            "item_id": item["id"], "spu_code": f"SPU-{uuid.uuid4().hex[:8]}",
        })
        spu = spu_r.json()["data"]
        sku_r = await client.post(f"/api/v1/spus/{spu['id']}/skus", headers=auth_header(admin_token), json={
            "sku_code": f"SKU-{uuid.uuid4().hex[:8]}",
        })
        sku = sku_r.json()["data"]

        wh_r = await client.post("/api/v1/warehouses", headers=auth_header(admin_token), json={
            "code": f"WH-{uuid.uuid4().hex[:6].upper()}", "name": "Alert WH",
        })
        wh = wh_r.json()["data"]

        doc_r = await client.post("/api/v1/inbound-docs", headers=auth_header(admin_token), json={
            "warehouse_id": wh["id"], "source_type": "PURCHASE",
        })
        doc = doc_r.json()["data"]
        await client.post(f"/api/v1/inbound-docs/{doc['id']}/lines", headers=auth_header(admin_token), json={
            "sku_id": sku["id"], "quantity": 2,
        })
        await client.post(f"/api/v1/inbound-docs/{doc['id']}/post", headers=auth_header(admin_token))

        engine = create_async_engine(os.environ["DATABASE_URL"])
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with factory() as session:
            from src.trailgoods.services.inventory import check_reorder_alerts
            count1 = await check_reorder_alerts(session)
            await session.commit()
            assert count1 >= 1

        async with factory() as session:
            from src.trailgoods.services.inventory import check_reorder_alerts
            count2 = await check_reorder_alerts(session)
            await session.commit()
            assert count2 == 0, "Repeated scan should not create duplicate alerts"

        async with factory() as session:
            from src.trailgoods.models.inventory import ReorderAlert
            alerts_result = await session.execute(
                select(ReorderAlert).where(
                    ReorderAlert.warehouse_id == uuid.UUID(wh["id"]),
                    ReorderAlert.sku_id == uuid.UUID(sku["id"]),
                    ReorderAlert.resolved_at == None,
                )
            )
            active_alerts = alerts_result.scalars().all()
            assert len(active_alerts) == 1, "Only one active alert should exist"

        await engine.dispose()


@pytest.mark.asyncio
class TestSensitiveVerificationPermission:
    """Issue 6: Admin sensitive verification reads must require explicit permission."""

    async def test_admin_with_permission_sees_sensitive(self, client: AsyncClient):
        """Admin (with verification.sensitive.read via seed) can see sensitive data."""
        admin_token = await get_admin_token(client)
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
                "legal_name": "Sensitive Test User",
                "dob": "01/15/1990",
                "government_id_number": "SENS12345",
                "government_id_image_asset_id": asset["asset_id"],
            },
        )

        r = await client.get(
            f"/api/v1/verification-cases/{case['case_id']}",
            headers=auth_header(admin_token),
        )
        assert r.status_code == 200
        data = r.json()["data"]
        # Admin should see unmasked data because seed grants verification.sensitive.read
        assert data.get("legal_name") == "Sensitive Test User"

    async def test_user_without_permission_sees_masked(self, client: AsyncClient):
        """Regular user sees masked sensitive data."""
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
                "legal_name": "Masked User Name",
                "dob": "01/15/1990",
                "government_id_number": "MASK12345",
                "government_id_image_asset_id": asset["asset_id"],
            },
        )

        r = await client.get(
            f"/api/v1/verification-cases/{case['case_id']}",
            headers=auth_header(login["token"]),
        )
        assert r.status_code == 200
        data = r.json()["data"]
        # Regular user should NOT see full legal_name
        assert data.get("legal_name") != "Masked User Name"
