"""Bring a fresh installation up to the one state only it can.

Seeding creates the first administrator and nothing else. That is the whole of
it, and the omissions are the point.

It used to create nine sections named for ZMB's — Light Microscopy, CryoEM,
Sample Preparation — each with a sentence describing it, plus a published
landing page and a worked example guide naming ZMB's booking calendar, its
server and its 405 nm laser. None of it was written by anyone who works there.
On a fresh install it read as the facility's own words, and after the migration
ran it was worse than that: the imported tree arrived beside it, so ZMB's real
`Light Micrscopy` stood next to a `Light Microscopy` this file had invented, and
a reader had no way to tell which of the two was theirs.

A facility's sections are the facility's. The migration brings the real ones
across with their own words and pictures; an installation with no site to import
from gets them from whoever runs it. Either way this file has nothing true to
say about them, and content that a facility did not write must not arrive
wearing its name.

Demonstration content lives in ``tools/demo_corpus.py``, which says outright
that it is not ZMB's corpus, builds a richer library than this ever did — video
steps, quick links, staff-only procedures, sub-sections, embedded guide lists —
and does it through the HTTP API, the way a person would.

Seeding is idempotent and never overwrites something an operator has already
changed, so it is safe to run on every deployment rather than once by hand. The
bootstrap password is read from the environment and has no fallback: a default
here would be published in this repository and would then exist on every
installation that skipped the first-run checklist.

Run it with ``python -m app.seed``.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .db import SessionLocal, init_db
from .models import User
from .security import hash_password
from .settings import Settings, get_settings


class SeedError(RuntimeError):
    """Raised when the environment cannot support a safe first run."""


def seed(db: DbSession, settings: Settings) -> None:
    _seed_admin(db, settings)
    db.commit()


def _seed_admin(db: DbSession, settings: Settings) -> User:
    email = settings.admin_email.strip().lower()
    existing = db.scalars(select(User).where(User.email == email)).one_or_none()
    if existing is not None:
        return existing

    if not settings.admin_password:
        raise SeedError(
            "Set RETICLE_ADMIN_PASSWORD before seeding. Reticle will not invent a bootstrap "
            "password, because a default one would be identical on every installation."
        )
    if len(settings.admin_password) < settings.min_password_length:
        raise SeedError(
            f"RETICLE_ADMIN_PASSWORD must be at least {settings.min_password_length} characters long."
        )

    admin = User(
        email=email,
        display_name="ZMB Administrator",
        role="admin",
        password_hash=hash_password(settings.admin_password),
    )
    db.add(admin)
    db.flush()
    return admin


def main() -> None:
    init_db()
    session = SessionLocal()
    try:
        seed(session, get_settings())
    finally:
        session.close()


if __name__ == "__main__":
    main()
