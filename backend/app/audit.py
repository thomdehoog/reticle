"""The audit trail.

ZMB shares instruments and shares documentation; when a protocol changes, the
question that follows is always "who changed it and when". Recording that at
the point of the write is cheaper and more reliable than reconstructing it from
backups, and it is what lets a guide be trusted as a procedure record.

Nothing here may be handed a secret. Callers pass a small explicit ``detail``
mapping rather than a request body, so a password or a token cannot arrive by
accident.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session as DbSession

from .models import AuditLog, User

FORBIDDEN_DETAIL_KEYS = frozenset({"password", "newPassword", "currentPassword", "token", "passwordHash"})


def record(
    db: DbSession,
    *,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    actor: User | None = None,
    actor_id: str | None = None,
    ip_address: str | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditLog:
    payload = dict(detail or {})
    leaked = FORBIDDEN_DETAIL_KEYS & payload.keys()
    if leaked:
        raise ValueError(f"refusing to audit secret-bearing keys: {sorted(leaked)}")

    entry = AuditLog(
        actor_id=actor.id if actor is not None else actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        ip_address=ip_address,
        detail=payload,
    )
    db.add(entry)
    return entry
