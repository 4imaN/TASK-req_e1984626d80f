import os
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://trailgoods:trailgoods@localhost:5433/trailgoods_test")
os.environ.setdefault("DATABASE_URL_SYNC", "postgresql+psycopg://trailgoods:trailgoods@localhost:5433/trailgoods_test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only-not-production")
os.environ.setdefault("ENCRYPTION_MASTER_KEY", "0" * 64)
os.environ.setdefault("ASSET_STORAGE_ROOT", "/tmp/trailgoods_test_assets")
os.environ.setdefault("BACKUP_STORAGE_ROOT", "/tmp/trailgoods_test_backups")
os.environ.setdefault("PREVIEW_STORAGE_ROOT", "/tmp/trailgoods_test_previews")

from src.trailgoods.core.config import Settings, override_settings
from src.trailgoods.core.database import Base, reset_engine

override_settings(Settings(
    DATABASE_URL=os.environ["DATABASE_URL"],
    DATABASE_URL_SYNC=os.environ["DATABASE_URL_SYNC"],
))

import src.trailgoods.models.auth  # noqa: F401
import src.trailgoods.models.assets  # noqa: F401
import src.trailgoods.models.verification  # noqa: F401
import src.trailgoods.models.jobs  # noqa: F401
import src.trailgoods.models.catalog  # noqa: F401
import src.trailgoods.models.inventory  # noqa: F401
import src.trailgoods.models.orders  # noqa: F401
import src.trailgoods.models.reviews  # noqa: F401


def _run_alembic(command: str):
    from alembic.config import Config
    from alembic import command as alembic_cmd

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL_SYNC"])
    if command == "upgrade":
        alembic_cmd.upgrade(cfg, "head")
    elif command == "downgrade":
        alembic_cmd.downgrade(cfg, "base")


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    reset_engine()
    _run_alembic("downgrade")
    _run_alembic("upgrade")

    from src.trailgoods.core.database import get_session_factory
    factory = get_session_factory()

    from scripts.seed import seed
    async with factory() as session:
        await seed(session)

    from src.trailgoods.services.auth import hash_password
    from src.trailgoods.models.auth import User, Role, UserRole, PasswordHistory
    from sqlalchemy import select

    async with factory() as session:
        admin_user = User(
            username="testadmin",
            username_canonical="testadmin",
            password_hash=hash_password("AdminP@ssw0rd!"),
            status="ACTIVE",
        )
        session.add(admin_user)
        await session.flush()
        session.add(PasswordHistory(user_id=admin_user.id, password_hash=admin_user.password_hash))
        role_result = await session.execute(select(Role).where(Role.name == "Admin"))
        admin_role = role_result.scalar_one()
        session.add(UserRole(user_id=admin_user.id, role_id=admin_role.id))
        reg_role_result = await session.execute(select(Role).where(Role.name == "RegisteredUser"))
        reg_role = reg_role_result.scalar_one()
        session.add(UserRole(user_id=admin_user.id, role_id=reg_role.id))
        reviewer_user = User(
            username="testreviewer",
            username_canonical="testreviewer",
            password_hash=hash_password("ReviewP@ssw0rd!"),
            status="ACTIVE",
        )
        session.add(reviewer_user)
        await session.flush()
        session.add(PasswordHistory(user_id=reviewer_user.id, password_hash=reviewer_user.password_hash))
        reviewer_role_result = await session.execute(select(Role).where(Role.name == "Reviewer"))
        reviewer_role = reviewer_role_result.scalar_one()
        session.add(UserRole(user_id=reviewer_user.id, role_id=reviewer_role.id))
        session.add(UserRole(user_id=reviewer_user.id, role_id=reg_role.id))

        await session.commit()

    import shutil
    asset_root = os.environ["ASSET_STORAGE_ROOT"]
    if os.path.exists(asset_root):
        shutil.rmtree(asset_root)
    os.makedirs(asset_root, exist_ok=True)

    from src.trailgoods.main import create_app
    app = create_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    from src.trailgoods.core.database import get_engine
    await get_engine().dispose()
    reset_engine()
    _run_alembic("downgrade")


def _make_test_jpeg(size: int = 2000) -> bytes:
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), color="blue").save(buf, "JPEG")
    return buf.getvalue()


_DEFAULT_JPEG = None


def _get_default_jpeg() -> bytes:
    global _DEFAULT_JPEG
    if _DEFAULT_JPEG is None:
        _DEFAULT_JPEG = _make_test_jpeg()
    return _DEFAULT_JPEG


async def register_user(client: AsyncClient, username: str = None, password: str = None) -> dict:
    username = username or f"testuser_{uuid.uuid4().hex[:8]}"
    password = password or "SecureP@ss123!"
    resp = await client.post("/api/v1/auth/register", json={
        "username": username,
        "password": password,
    })
    assert resp.status_code == 201, resp.text
    return {"username": username, "password": password, "user": resp.json()["data"]}


async def login_user(client: AsyncClient, username: str, password: str) -> dict:
    resp = await client.post("/api/v1/auth/login", json={
        "username": username,
        "password": password,
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    return {"token": data["token"], "session": data["session"], "user": data["user"]}


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def get_admin_token(client: AsyncClient) -> str:
    data = await login_user(client, "testadmin", "AdminP@ssw0rd!")
    return data["token"]


async def get_reviewer_token(client: AsyncClient) -> str:
    data = await login_user(client, "testreviewer", "ReviewP@ssw0rd!")
    return data["token"]


async def upload_test_asset(
    client: AsyncClient,
    token: str,
    content: bytes | None = None,
    filename: str = "test.jpg",
    mime_type: str = "image/jpeg",
    kind: str = "IMAGE",
    purpose: str = "GENERAL",
) -> dict:
    if content is None:
        content = _get_default_jpeg()
    headers = auth_header(token)
    resp = await client.post("/api/v1/assets/uploads", headers=headers, json={
        "filename": filename,
        "mime_type": mime_type,
        "total_size": len(content),
        "total_parts": 1,
        "kind": kind,
        "purpose": purpose,
    })
    assert resp.status_code == 201, resp.text
    upload_id = resp.json()["data"]["upload_session_id"]

    resp2 = await client.put(
        f"/api/v1/assets/uploads/{upload_id}/parts/1",
        headers={**headers, "content-type": "application/octet-stream"},
        content=content,
    )
    assert resp2.status_code == 200, resp2.text

    resp3 = await client.post(
        f"/api/v1/assets/uploads/{upload_id}/complete",
        headers=headers,
    )
    assert resp3.status_code == 200, resp3.text
    return resp3.json()["data"]
