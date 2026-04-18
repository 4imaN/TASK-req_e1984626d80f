import json
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.trailgoods.core.database import get_db
from src.trailgoods.models.auth import Session as SessionModel, User
from src.trailgoods.services.auth import authenticate_session


async def get_current_user_and_session(
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(None),
) -> tuple[User, SessionModel]:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Invalid authorization scheme")

    try:
        user, session = await authenticate_session(db, token)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    request.state.current_user = user
    request.state.current_session = session
    return user, session


async def get_current_user(
    user_session: Annotated[
        tuple[User, SessionModel], Depends(get_current_user_and_session)
    ],
) -> User:
    return user_session[0]


def get_user_permissions(user: User) -> set[str]:
    perms: set[str] = set()
    for ur in user.roles:
        for rp in ur.role.permissions:
            perms.add(rp.permission.code)
    return perms


def get_user_role_names(user: User) -> list[str]:
    return [ur.role.name for ur in user.roles]


def require_permission(*required: str):
    async def checker(
        user_session: Annotated[
            tuple[User, SessionModel], Depends(get_current_user_and_session)
        ],
    ) -> tuple[User, SessionModel]:
        user = user_session[0]
        perms = get_user_permissions(user)
        role_names = get_user_role_names(user)

        if "Admin" in role_names:
            return user_session

        for perm in required:
            if perm not in perms:
                raise HTTPException(
                    status_code=403,
                    detail=f"Missing required permission: {perm}",
                )
        return user_session
    return checker


def require_role(*roles: str):
    async def checker(
        user_session: Annotated[
            tuple[User, SessionModel], Depends(get_current_user_and_session)
        ],
    ) -> tuple[User, SessionModel]:
        user = user_session[0]
        role_names = get_user_role_names(user)

        if not any(r in role_names for r in roles):
            raise HTTPException(
                status_code=403,
                detail=f"Requires one of roles: {', '.join(roles)}",
            )
        return user_session
    return checker


def get_role_snapshot(user: User) -> str:
    return json.dumps(get_user_role_names(user))
