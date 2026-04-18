import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.trailgoods.core.config import get_settings
from src.trailgoods.models.auth import (
    IdentityBinding,
    LoginAttempt,
    PasswordHistory,
    Role,
    RolePermission,
    Role,
    Session,
    User,
    UserRole,
)
from src.trailgoods.models.enums import BindingStatus, SessionStatus, UserStatus
from src.trailgoods.services.audit import write_audit

ph = PasswordHasher()


def hash_password(password: str) -> str:
    return ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def register_user(
    db: AsyncSession,
    *,
    username: str,
    password: str,
    email: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> User:
    canonical = username.lower()
    existing = await db.execute(select(User).where(User.username_canonical == canonical))
    if existing.scalar_one_or_none():
        raise ValueError("Username already taken")

    if email:
        existing_email = await db.execute(select(User).where(User.email == email))
        if existing_email.scalar_one_or_none():
            raise ValueError("Email already in use")

    pw_hash = hash_password(password)
    user = User(
        username=username,
        username_canonical=canonical,
        email=email,
        password_hash=pw_hash,
        status=UserStatus.ACTIVE,
    )
    db.add(user)
    await db.flush()

    pw_history = PasswordHistory(user_id=user.id, password_hash=pw_hash)
    db.add(pw_history)

    reg_role = await db.execute(select(Role).where(Role.name == "RegisteredUser"))
    role = reg_role.scalar_one_or_none()
    if role:
        db.add(UserRole(user_id=user.id, role_id=role.id))

    await write_audit(
        db,
        action="user.register",
        resource_type="user",
        resource_id=str(user.id),
        actor_user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.flush()
    return user


async def _record_login_attempt(
    db: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    username_canonical: str,
    ip_address: str | None,
    success: bool,
    failure_reason: str | None = None,
) -> LoginAttempt:
    attempt = LoginAttempt(
        user_id=user_id,
        username_canonical=username_canonical,
        ip_address=ip_address,
        success=success,
        failure_reason=failure_reason,
    )
    db.add(attempt)
    await db.flush()
    return attempt


async def _check_and_enforce_lockout(db: AsyncSession, user: User) -> bool:
    settings = get_settings()
    now = datetime.now(timezone.utc)

    if user.challenge_locked_until and user.challenge_locked_until > now:
        return True

    window_start = now - timedelta(minutes=settings.FAILED_LOGIN_WINDOW_MINUTES)

    if (
        user.failed_login_window_started_at
        and user.failed_login_window_started_at >= window_start
        and user.failed_login_window_count >= settings.FAILED_LOGIN_MAX_ATTEMPTS
    ):
        user.status = UserStatus.CHALLENGE_REQUIRED
        user.challenge_locked_until = now + timedelta(minutes=settings.CHALLENGE_LOCKOUT_MINUTES)
        await db.execute(
            update(Session)
            .where(Session.user_id == user.id, Session.status == SessionStatus.ACTIVE)
            .values(
                status=SessionStatus.FORCED_LOGGED_OUT,
                revoked_at=now,
                revoke_reason="failed_login_lockout",
            )
        )
        await write_audit(
            db,
            action="user.forced_logout",
            resource_type="user",
            resource_id=str(user.id),
            result="SUCCESS",
            actor_user_id=user.id,
        )
        await db.flush()
        return True

    return False


async def _increment_failed_login(db: AsyncSession, user: User) -> None:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=settings.FAILED_LOGIN_WINDOW_MINUTES)

    if (
        user.failed_login_window_started_at is None
        or user.failed_login_window_started_at < window_start
    ):
        user.failed_login_window_started_at = now
        user.failed_login_window_count = 1
    else:
        user.failed_login_window_count += 1

    await db.flush()


async def login_user(
    db: AsyncSession,
    *,
    username: str,
    password: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[User, Session, str]:
    canonical = username.lower()
    result = await db.execute(select(User).where(User.username_canonical == canonical))
    user = result.scalar_one_or_none()

    if not user:
        await _record_login_attempt(
            db, user_id=None, username_canonical=canonical,
            ip_address=ip_address, success=False, failure_reason="user_not_found",
        )
        raise ValueError("Invalid credentials")

    if user.status == UserStatus.DISABLED:
        await _record_login_attempt(
            db, user_id=user.id, username_canonical=canonical,
            ip_address=ip_address, success=False, failure_reason="account_disabled",
        )
        raise ValueError("Account is disabled")

    locked = await _check_and_enforce_lockout(db, user)
    if locked:
        await _record_login_attempt(
            db, user_id=user.id, username_canonical=canonical,
            ip_address=ip_address, success=False, failure_reason="account_locked",
        )
        raise ValueError("Account is temporarily locked due to repeated failed login attempts")

    if not verify_password(user.password_hash, password):
        await _increment_failed_login(db, user)
        await _record_login_attempt(
            db, user_id=user.id, username_canonical=canonical,
            ip_address=ip_address, success=False, failure_reason="invalid_password",
        )
        lockout_triggered = await _check_and_enforce_lockout(db, user)
        await db.commit()
        if lockout_triggered:
            raise ValueError("Account is temporarily locked due to repeated failed login attempts")
        raise ValueError("Invalid credentials")

    user.failed_login_window_count = 0
    user.failed_login_window_started_at = None
    if user.status == UserStatus.CHALLENGE_REQUIRED:
        now = datetime.now(timezone.utc)
        if user.challenge_locked_until and user.challenge_locked_until <= now:
            user.status = UserStatus.ACTIVE
            user.challenge_locked_until = None
        else:
            await _record_login_attempt(
                db, user_id=user.id, username_canonical=canonical,
                ip_address=ip_address, success=False, failure_reason="challenge_active",
            )
            raise ValueError("Account is temporarily locked due to repeated failed login attempts")

    raw_token = secrets.token_urlsafe(48)
    token_h = hash_token(raw_token)

    session = Session(
        user_id=user.id,
        token_hash=token_h,
        status=SessionStatus.ACTIVE,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(session)

    await _record_login_attempt(
        db, user_id=user.id, username_canonical=canonical,
        ip_address=ip_address, success=True,
    )

    await write_audit(
        db,
        action="user.login",
        resource_type="session",
        resource_id=str(session.id),
        actor_user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.flush()
    return user, session, raw_token


async def authenticate_session(
    db: AsyncSession,
    token: str,
) -> tuple[User, Session]:
    token_h = hash_token(token)
    settings = get_settings()
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(Session).where(Session.token_hash == token_h)
    )
    session = result.scalar_one_or_none()
    if not session or session.status != SessionStatus.ACTIVE:
        raise ValueError("Invalid or expired session")

    idle_cutoff = now - timedelta(minutes=settings.SESSION_IDLE_TIMEOUT_MINUTES)
    if session.last_activity_at < idle_cutoff:
        session.status = SessionStatus.EXPIRED
        session.revoked_at = now
        session.revoke_reason = "idle_timeout"
        await db.flush()
        raise ValueError("Session expired due to inactivity")

    session.last_activity_at = now
    await db.flush()

    result = await db.execute(
        select(User)
        .where(User.id == session.user_id)
        .options(
            selectinload(User.roles)
            .selectinload(UserRole.role)
            .selectinload(Role.permissions)
            .selectinload(RolePermission.permission)
        )
    )
    user = result.scalar_one_or_none()
    if not user or user.status == UserStatus.DISABLED:
        raise ValueError("User account is disabled")

    return user, session


async def logout_session(
    db: AsyncSession,
    *,
    session: Session,
    user: User,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    session.status = SessionStatus.REVOKED
    session.revoked_at = now
    session.revoke_reason = "user_logout"

    await write_audit(
        db,
        action="user.logout",
        resource_type="session",
        resource_id=str(session.id),
        actor_user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.flush()


async def logout_all_sessions(
    db: AsyncSession,
    *,
    user: User,
    reason: str = "user_logout_all",
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> int:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(Session)
        .where(Session.user_id == user.id, Session.status == SessionStatus.ACTIVE)
        .values(status=SessionStatus.REVOKED, revoked_at=now, revoke_reason=reason)
    )
    count = result.rowcount

    await write_audit(
        db,
        action="user.logout_all",
        resource_type="user",
        resource_id=str(user.id),
        actor_user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.flush()
    return count


async def force_logout_user(
    db: AsyncSession,
    *,
    target_user_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    reason: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    actor_role_snapshot: str | None = None,
) -> int:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(Session)
        .where(Session.user_id == target_user_id, Session.status == SessionStatus.ACTIVE)
        .values(
            status=SessionStatus.FORCED_LOGGED_OUT,
            revoked_at=now,
            revoke_reason=reason or "admin_force_logout",
        )
    )
    count = result.rowcount

    await write_audit(
        db,
        action="admin.force_logout",
        resource_type="user",
        resource_id=str(target_user_id),
        actor_user_id=actor_user_id,
        actor_role_snapshot=actor_role_snapshot,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.flush()
    return count


async def rotate_password(
    db: AsyncSession,
    *,
    user: User,
    current_password: str,
    new_password: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    if not verify_password(user.password_hash, current_password):
        raise ValueError("Current password is incorrect")

    settings = get_settings()

    history_result = await db.execute(
        select(PasswordHistory)
        .where(PasswordHistory.user_id == user.id)
        .order_by(PasswordHistory.created_at.desc())
        .limit(settings.PASSWORD_HISTORY_COUNT)
    )
    history = history_result.scalars().all()
    for h in history:
        if verify_password(h.password_hash, new_password):
            raise ValueError(
                f"Cannot reuse any of your last {settings.PASSWORD_HISTORY_COUNT} passwords"
            )

    new_hash = hash_password(new_password)
    user.password_hash = new_hash
    db.add(PasswordHistory(user_id=user.id, password_hash=new_hash))

    now = datetime.now(timezone.utc)
    await db.execute(
        update(Session)
        .where(Session.user_id == user.id, Session.status == SessionStatus.ACTIVE)
        .values(status=SessionStatus.REVOKED, revoked_at=now, revoke_reason="password_rotation")
    )

    await write_audit(
        db,
        action="user.password_rotate",
        resource_type="user",
        resource_id=str(user.id),
        actor_user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.flush()


async def create_identity_binding(
    db: AsyncSession,
    *,
    user: User,
    binding_type: str,
    institution_code: str,
    external_id: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> IdentityBinding:
    now = datetime.now(timezone.utc)
    existing = await db.execute(
        select(IdentityBinding).where(
            IdentityBinding.user_id == user.id,
            IdentityBinding.institution_code == institution_code,
            IdentityBinding.binding_type == binding_type,
            IdentityBinding.status == BindingStatus.ACTIVE,
        )
    )
    old = existing.scalar_one_or_none()
    if old:
        old.status = BindingStatus.REVOKED
        old.revoked_at = now

    from src.trailgoods.core.encryption import encrypt_value

    clean_ext_id = external_id.strip()
    settings = get_settings()
    key = settings.get_encryption_key()
    ext_id_hash = hashlib.sha256(f"{institution_code}:{binding_type}:{clean_ext_id}".encode()).hexdigest()[:100]
    ext_id_encrypted = encrypt_value(clean_ext_id, key)

    binding = IdentityBinding(
        user_id=user.id,
        binding_type=binding_type,
        institution_code=institution_code,
        external_id=ext_id_hash,
        external_id_encrypted=ext_id_encrypted,
        status=BindingStatus.ACTIVE,
    )
    db.add(binding)

    await write_audit(
        db,
        action="identity_binding.create",
        resource_type="identity_binding",
        resource_id=str(binding.id),
        actor_user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.flush()
    return binding


async def get_user_bindings(db: AsyncSession, user_id: uuid.UUID) -> list[IdentityBinding]:
    result = await db.execute(
        select(IdentityBinding)
        .where(IdentityBinding.user_id == user_id)
        .order_by(IdentityBinding.created_at.desc())
    )
    return list(result.scalars().all())


async def assign_role(
    db: AsyncSession,
    *,
    target_user_id: uuid.UUID,
    role_name: str,
    actor_user_id: uuid.UUID,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> UserRole:
    role_result = await db.execute(select(Role).where(Role.name == role_name))
    role = role_result.scalar_one_or_none()
    if not role:
        raise ValueError(f"Role '{role_name}' not found")

    existing = await db.execute(
        select(UserRole).where(
            UserRole.user_id == target_user_id,
            UserRole.role_id == role.id,
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError("User already has this role")

    user_role = UserRole(
        user_id=target_user_id,
        role_id=role.id,
        assigned_by_user_id=actor_user_id,
    )
    db.add(user_role)

    await write_audit(
        db,
        action="rbac.role_assign",
        resource_type="user_role",
        resource_id=str(target_user_id),
        actor_user_id=actor_user_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.flush()
    return user_role


async def clear_challenge(
    db: AsyncSession,
    *,
    target_user_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    result = await db.execute(select(User).where(User.id == target_user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise ValueError("User not found")
    if target.status != UserStatus.CHALLENGE_REQUIRED:
        raise ValueError("User is not in CHALLENGE_REQUIRED state")

    target.status = UserStatus.ACTIVE
    target.failed_login_window_count = 0
    target.failed_login_window_started_at = None
    target.challenge_locked_until = None

    await write_audit(
        db,
        action="admin.clear_challenge",
        resource_type="user",
        resource_id=str(target_user_id),
        actor_user_id=actor_user_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.flush()
