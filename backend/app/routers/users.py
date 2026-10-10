"""User administration and password changes.

Password changes revoke the account's other sessions. If a password is being
changed because it leaked, leaving the sessions it created alive would defeat
the point of changing it. The same goes for the device cookies that mark a
browser as one the account has signed in from: a password change, an
administrator's reset and a deactivation each raise the account's epoch, and
every such cookie issued before stops counting (``security.end_credentials``).

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from .. import audit, errors
from ..auth import AdminUser, CurrentSession, DbDep, client_address
from ..models import User
from ..schemas import PasswordChangeIn, UserCreateIn, UserOut, UserPatchIn, user_out
from ..security import end_credentials, hash_password, new_device_token, verify_password
from ..settings import get_settings
from .auth import set_device_cookie

router = APIRouter(prefix="/api/users", tags=["users"])


def assert_password_acceptable(candidate: str) -> None:
    """One length rule, no composition rules.

    Character-class requirements push people towards predictable substitutions;
    length is the property that actually costs an attacker work.
    """
    minimum = get_settings().min_password_length
    if len(candidate) < minimum:
        raise errors.validation_failed(f"Passwords must be at least {minimum} characters long.")


def _load(db: DbSession, user_id: str) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise errors.not_found("That user does not exist.")
    return user


@router.get("", response_model=list[UserOut])
def list_users(db: DbDep, actor: AdminUser) -> list[UserOut]:
    users = db.scalars(select(User).order_by(User.display_name, User.email)).all()
    return [user_out(user) for user in users]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreateIn, request: Request, db: DbDep, actor: AdminUser) -> UserOut:
    email = payload.email.strip().lower()
    assert_password_acceptable(payload.password)

    taken = db.scalar(select(func.count()).select_from(User).where(User.email == email))
    if taken:
        raise errors.conflict("Somebody already has that email address.")

    user = User(
        email=email,
        display_name=(payload.display_name or email.split("@")[0]).strip(),
        role=payload.role,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.flush()
    audit.record(
        db,
        action="user.create",
        entity_type="user",
        entity_id=user.id,
        actor=actor,
        ip_address=client_address(request),
        detail={"email": user.email, "role": user.role},
    )
    db.commit()
    return user_out(user)


@router.patch("/{user_id}", response_model=UserOut)
def patch_user(user_id: str, payload: UserPatchIn, request: Request, db: DbDep, actor: AdminUser) -> UserOut:
    user = _load(db, user_id)
    changed = payload.model_fields_set

    if user.id == actor.id:
        if payload.role is not None and payload.role != "admin":
            raise errors.validation_failed("You cannot remove your own admin role.")
        if payload.is_active is False:
            raise errors.validation_failed("You cannot deactivate your own account.")

    if "display_name" in changed and payload.display_name is not None:
        user.display_name = payload.display_name.strip()
    if "role" in changed and payload.role is not None:
        user.role = payload.role
    if "is_active" in changed and payload.is_active is not None:
        if user.is_active and not payload.is_active:
            end_credentials(db, user)
        user.is_active = payload.is_active

    audit.record(
        db,
        action="user.update",
        entity_type="user",
        entity_id=user.id,
        actor=actor,
        ip_address=client_address(request),
        detail={"fields": sorted(changed)},
    )
    db.commit()
    return user_out(user)


@router.post("/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def change_password(
    user_id: str,
    payload: PasswordChangeIn,
    request: Request,
    db: DbDep,
    session_row: CurrentSession,
) -> Response:
    actor = session_row.user
    is_self = actor.id == user_id
    if not is_self and actor.role != "admin":
        raise errors.forbidden("Only an administrator can change somebody else's password.")

    user = _load(db, user_id)
    assert_password_acceptable(payload.new_password)

    if is_self:
        if payload.current_password is None:
            raise errors.validation_failed("Confirm your current password to change it.")
        if not verify_password(user.password_hash, payload.current_password):
            raise errors.invalid_credentials("That is not your current password.")

    user.password_hash = hash_password(payload.new_password)
    end_credentials(db, user, except_session_id=session_row.id if is_self else None)
    audit.record(
        db,
        action="user.password_change",
        entity_type="user",
        entity_id=user.id,
        actor=actor,
        ip_address=client_address(request),
        detail={"self": is_self},
    )
    email, epoch = user.email, user.auth_epoch
    db.commit()

    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    if is_self:
        # The browser that just proved the old password and chose the new one
        # keeps its standing; every other browser has to earn it again.
        set_device_cookie(response, new_device_token(email, epoch), get_settings())
    return response
