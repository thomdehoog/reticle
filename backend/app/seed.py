"""Bring a fresh installation up to a usable state.

Seeding is idempotent and never overwrites something an operator has already
changed, so it is safe to run on every deployment rather than once by hand. The
bootstrap password is read from the environment and has no fallback: a default
here would be published in this repository and would then exist on every
installation that skipped the first-run checklist.

Run it with ``python -m app.seed``.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from .db import SessionLocal, init_db, utcnow
from .models import Bullet, Category, Guide, GuideRevision, Step, User
from .schemas import guide_document
from .security import hash_password
from .settings import Settings, get_settings
from .slugs import slugify

ZMB_CATEGORIES: list[tuple[str, str]] = [
    ("Basics, Access and IT", "Accounts, building access, booking, storage and the ZMB network."),
    ("Sample Preparation", "Preparing samples for light microscopy: fixation, labelling and mounting."),
    ("Light Microscopy", "Widefield, confocal, superresolution and live-cell systems."),
    ("Electron Microscopy", "Transmission and scanning electron microscopy, from resin to image."),
    ("Image Analysis", "Segmentation, quantification, batch processing and reproducible pipelines."),
    ("Internal Guides", "Procedures for ZMB staff: maintenance, handover and instrument checks."),
    ("CryoEM", "Vitrification, screening and single-particle data collection."),
    ("Spatial Biology", "Spatial transcriptomics and multiplexed imaging workflows."),
]

EXAMPLE_GUIDE_TITLE = "Starting a Session on the Confocal"

EXAMPLE_STEPS: list[tuple[str, list[tuple[str, str, str | None, int]]]] = [
    (
        "Book the system and check the room",
        [
            ("Confirm your booking in the ZMB calendar before you enter the room.", "black", None, 0),
            ("The previous user has 10 minutes to finish; do not interrupt an acquisition.", "blue", "note", 0),
            ("If the room is dark and the door sign says LIVE CELL, knock before entering.", "orange", "caution", 1),
        ],
    ),
    (
        "Power up in order",
        [
            ("Switch on the mains strip, then the scanner, then the PC. Wait for each to settle.", "black", None, 0),
            ("Never switch the lasers on before the scanner has finished its self-test.", "red", "warning", 0),
            ("The 405 nm laser needs about 10 minutes to reach a stable output.", "black", None, 1),
            ("Log in with your ZMB account, not with the local Administrator account.", "violet", "reminder", 0),
        ],
    ),
    (
        "Choose and clean the objective",
        [
            ("Select the objective in the software first so the turret moves under control.", "black", None, 0),
            ("Clean the front lens with lens tissue and a single drop of solvent, one pass only.", "orange", "caution", 0),
            ("Never let solvent run down the barrel; it dissolves the cement inside.", "red", "warning", 1),
            ("Use the immersion medium printed on the objective, not the one already on the bench.", "black", None, 1),
        ],
    ),
    (
        "Mount the sample and find focus",
        [
            ("Place the slide coverslip-down and clamp it before adding immersion medium.", "black", None, 0),
            ("Find focus in widefield at low magnification, then switch to scanning.", "green", None, 0),
            ("Start with the lowest laser power that gives a visible signal.", "yellow", "note", 0),
        ],
    ),
    (
        "Acquire, save and shut down",
        [
            ("Save to your group folder on the server, never to the local desktop.", "black", None, 0),
            ("Local disks are wiped without warning during maintenance.", "red", "warning", 1),
            ("Export the acquisition settings alongside the images so the run is reproducible.", "blue", "note", 0),
            ("Log the session in the booking system, including any fault you noticed.", "violet", "reminder", 0),
        ],
    ),
]


class SeedError(RuntimeError):
    """Raised when the environment cannot support a safe first run."""


def seed(db: DbSession, settings: Settings) -> None:
    admin = _seed_admin(db, settings)
    categories = _seed_categories(db)
    _seed_example_guide(db, admin, categories["Light Microscopy"])
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


def _seed_categories(db: DbSession) -> dict[str, Category]:
    seeded: dict[str, Category] = {}
    for order_index, (name, description) in enumerate(ZMB_CATEGORIES):
        existing = db.scalars(select(Category).where(Category.name == name)).one_or_none()
        if existing is None:
            existing = Category(
                slug=slugify(name),
                name=name,
                description=description,
                parent_id=None,
                order_index=order_index,
            )
            db.add(existing)
        seeded[name] = existing
    db.flush()
    return seeded


def _seed_example_guide(db: DbSession, author: User, category: Category) -> None:
    """One worked guide, so a fresh install shows the annotation vocabulary.

    It is published rather than left in draft, because the first thing anyone
    checks after installing is whether a reader account sees anything at all.
    """
    if db.scalar(select(func.count()).select_from(Guide)):
        return

    now = utcnow()
    guide = Guide(
        slug=slugify(EXAMPLE_GUIDE_TITLE),
        title=EXAMPLE_GUIDE_TITLE,
        summary="From booking to shutdown: the routine every confocal session at ZMB follows.",
        category_id=category.id,
        difficulty="easy",
        time_required_minutes=25,
        introduction=(
            "This guide covers the standard start-up routine for the confocal systems in the ZMB "
            "light microscopy suite. It assumes you have completed the introductory training and "
            "hold a valid booking."
        ),
        conclusion=(
            "If anything behaved unexpectedly, note it in the booking system and tell the "
            "responsible staff member. A fault reported the same day is usually a ten-minute fix."
        ),
        status="published",
        version=1,
        author_id=author.id,
        last_edited_by_id=author.id,
        published_at=now,
    )
    db.add(guide)
    db.flush()

    for order_index, (title, bullets) in enumerate(EXAMPLE_STEPS):
        step = Step(guide_id=guide.id, order_index=order_index, title=title)
        db.add(step)
        db.flush()
        for position, (text, color, icon, level) in enumerate(bullets):
            db.add(
                Bullet(
                    step_id=step.id,
                    order_index=position,
                    text=text,
                    color=color,
                    icon=icon,
                    level=level,
                )
            )
    db.flush()
    db.refresh(guide)

    db.add(
        GuideRevision(
            guide_id=guide.id,
            version=guide.version,
            published_at=now,
            published_by_id=author.id,
            document=guide_document(guide),
        )
    )


def main() -> None:
    init_db()
    session = SessionLocal()
    try:
        seed(session, get_settings())
    finally:
        session.close()


if __name__ == "__main__":
    main()
