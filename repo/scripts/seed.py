"""Seed roles and permissions into the database."""
import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.trailgoods.core.database import get_session_factory
from src.trailgoods.models.auth import Permission, Role, RolePermission, User, UserRole

ROLES = [
    ("Guest", "Read-only public catalog access"),
    ("RegisteredUser", "Authenticated user with purchase intent and own-resource access"),
    ("Instructor", "Content author for trips/services"),
    ("Reviewer", "Verification and moderation authority"),
    ("Admin", "Full system control"),
]

PERMISSIONS = [
    "auth.register",
    "auth.login",
    "auth.logout",
    "auth.password_rotate",
    "session.read_own",
    "session.revoke_own",
    "identity_binding.create",
    "identity_binding.read_own",
    "identity_binding.read_sensitive",
    "verification.create",
    "verification.read_own",
    "verification.submit",
    "verification.withdraw",
    "verification.renew",
    "verification.review",
    "verification.sensitive.read",
    "catalog.item.read",
    "catalog.item.create_service",
    "catalog.item.create_product",
    "catalog.item.create_live_pet",
    "catalog.item.update_own",
    "catalog.item.publish_own",
    "catalog.item.manage_all",
    "catalog.spu.create",
    "catalog.spu.update",
    "catalog.sku.create",
    "catalog.sku.update",
    "catalog.price.create",
    "catalog.price.update",
    "asset.create",
    "asset.read_own",
    "asset.delete_own",
    "share_link.create",
    "share_link.read_own",
    "share_link.delete_own",
    "warehouse.create",
    "warehouse.read",
    "warehouse.update",
    "inventory.read",
    "inventory.inbound.create",
    "inventory.inbound.post",
    "inventory.outbound.create",
    "inventory.outbound.post",
    "inventory.stocktake.create",
    "inventory.stocktake.post",
    "reservation.create",
    "reservation.read",
    "order.create",
    "order.read_own",
    "order.cancel_own",
    "order.manage_all",
    "review.create",
    "review.edit_own",
    "review.read",
    "review.moderate",
    "sensitive_word.manage",
    "report.create",
    "report.triage",
    "report.close",
    "appeal.create",
    "appeal.decide",
    "rbac.assign",
    "rbac.read",
    "audit.read",
    "backup.run",
    "backup.read",
    "admin.force_logout",
    "admin.clear_challenge",
]

ROLE_PERMISSIONS = {
    "Guest": [
        "catalog.item.read",
        "review.read",
    ],
    "RegisteredUser": [
        "auth.logout",
        "auth.password_rotate",
        "session.read_own",
        "session.revoke_own",
        "identity_binding.create",
        "identity_binding.read_own",
        "verification.create",
        "verification.read_own",
        "verification.submit",
        "verification.withdraw",
        "verification.renew",
        "catalog.item.read",
        "asset.create",
        "asset.read_own",
        "asset.delete_own",
        "share_link.create",
        "share_link.read_own",
        "share_link.delete_own",
        "order.create",
        "order.read_own",
        "order.cancel_own",
        "review.create",
        "review.edit_own",
        "review.read",
        "report.create",
        "appeal.create",
    ],
    "Instructor": [
        "catalog.item.create_service",
        "catalog.item.update_own",
        "catalog.item.publish_own",
        "catalog.spu.create",
        "catalog.sku.create",
        "catalog.price.create",
    ],
    "Reviewer": [
        "verification.read_own",
        "verification.create",
        "verification.submit",
        "verification.review",
        "verification.sensitive.read",
        "identity_binding.read_sensitive",
        "review.moderate",
        "sensitive_word.manage",
        "report.triage",
        "report.close",
        "appeal.decide",
        "audit.read",
    ],
    "Admin": [
        "auth.register",
        "auth.login",
        "auth.logout",
        "auth.password_rotate",
        "session.read_own",
        "session.revoke_own",
        "identity_binding.create",
        "identity_binding.read_own",
        "identity_binding.read_sensitive",
        "verification.create",
        "verification.read_own",
        "verification.submit",
        "verification.withdraw",
        "verification.renew",
        "verification.review",
        "verification.sensitive.read",
        "catalog.item.read",
        "catalog.item.create_service",
        "catalog.item.create_product",
        "catalog.item.create_live_pet",
        "catalog.item.update_own",
        "catalog.item.publish_own",
        "catalog.item.manage_all",
        "catalog.spu.create",
        "catalog.spu.update",
        "catalog.sku.create",
        "catalog.sku.update",
        "catalog.price.create",
        "catalog.price.update",
        "asset.create",
        "asset.read_own",
        "asset.delete_own",
        "share_link.create",
        "share_link.read_own",
        "share_link.delete_own",
        "warehouse.create",
        "warehouse.read",
        "warehouse.update",
        "inventory.read",
        "inventory.inbound.create",
        "inventory.inbound.post",
        "inventory.outbound.create",
        "inventory.outbound.post",
        "inventory.stocktake.create",
        "inventory.stocktake.post",
        "reservation.create",
        "reservation.read",
        "order.create",
        "order.read_own",
        "order.cancel_own",
        "order.manage_all",
        "review.create",
        "review.edit_own",
        "review.read",
        "review.moderate",
        "sensitive_word.manage",
        "report.create",
        "report.triage",
        "report.close",
        "appeal.create",
        "appeal.decide",
        "rbac.assign",
        "rbac.read",
        "audit.read",
        "backup.run",
        "backup.read",
        "admin.force_logout",
        "admin.clear_challenge",
    ],
}


async def seed(db: AsyncSession) -> None:
    perm_map: dict[str, uuid.UUID] = {}
    for code in PERMISSIONS:
        existing = await db.execute(select(Permission).where(Permission.code == code))
        p = existing.scalar_one_or_none()
        if not p:
            p = Permission(code=code)
            db.add(p)
            await db.flush()
        perm_map[code] = p.id

    role_map: dict[str, uuid.UUID] = {}
    for name, desc in ROLES:
        existing = await db.execute(select(Role).where(Role.name == name))
        r = existing.scalar_one_or_none()
        if not r:
            r = Role(name=name, description=desc)
            db.add(r)
            await db.flush()
        role_map[name] = r.id

    for role_name, perm_codes in ROLE_PERMISSIONS.items():
        rid = role_map[role_name]
        for code in perm_codes:
            pid = perm_map[code]
            existing = await db.execute(
                select(RolePermission).where(
                    RolePermission.role_id == rid,
                    RolePermission.permission_id == pid,
                )
            )
            if not existing.scalar_one_or_none():
                db.add(RolePermission(role_id=rid, permission_id=pid))

    from argon2 import PasswordHasher

    ph = PasswordHasher()

    DEMO_USERS = [
        ("admin", "AdminP@ssw0rd1!", ["Admin", "RegisteredUser"]),
        ("reviewer", "ReviewP@ssw0rd1!", ["Reviewer", "RegisteredUser"]),
        ("instructor", "InstructorP@ss1!", ["Instructor", "RegisteredUser"]),
    ]

    for username, password, roles in DEMO_USERS:
        existing = await db.execute(
            select(User).where(User.username_canonical == username)
        )
        if existing.scalar_one_or_none():
            continue
        pw_hash = ph.hash(password)
        user = User(
            username=username,
            username_canonical=username,
            password_hash=pw_hash,
            status="ACTIVE",
        )
        db.add(user)
        await db.flush()
        from src.trailgoods.models.auth import PasswordHistory
        db.add(PasswordHistory(user_id=user.id, password_hash=pw_hash))
        for rname in roles:
            rid = role_map.get(rname)
            if rid:
                db.add(UserRole(user_id=user.id, role_id=rid))

    await db.commit()
    print("Seed complete.")


async def main():
    factory = get_session_factory()
    async with factory() as session:
        await seed(session)


if __name__ == "__main__":
    asyncio.run(main())
