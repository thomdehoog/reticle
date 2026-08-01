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
from .models import (
    Annotation,
    Bullet,
    Category,
    Guide,
    GuideContributor,
    GuideRevision,
    GuideTag,
    Media,
    Page,
    PageContributor,
    PageRevision,
    Step,
    StepMedia,
    Tag,
    User,
    new_id,
)
from .schemas import guide_document, page_document
from .security import hash_password
from .settings import Settings, get_settings
from .slugs import slugify
from .storage import build_storage

ZMB_CATEGORIES: list[tuple[str, str, bool]] = [
    ("Basics, Access and IT", "Accounts, building access, booking, storage and the ZMB network.", False),
    ("Sample Preparation", "Preparing samples for light microscopy: fixation, labelling and mounting.", False),
    ("Light Microscopy", "Widefield, confocal, superresolution and live-cell systems.", False),
    ("Electron Microscopy", "Transmission and scanning electron microscopy, from resin to image.", False),
    ("Image Analysis", "Segmentation, quantification, batch processing and reproducible pipelines.", False),
    ("Internal Guides", "Procedures for ZMB staff: maintenance, handover and instrument checks.", False),
    ("CryoEM", "Vitrification, screening and single-particle data collection.", False),
    ("Spatial Biology", "Spatial transcriptomics and multiplexed imaging workflows.", False),
    (
        "Confocal - hidden guides",
        "A holding category. Its guides are reached through tags and through the wiki "
        "pages that embed them, never by browsing to it.",
        True,
    ),
]
"""The sections, plus one holding category.

The hidden one is not decoration: on ZMB's live site the largest single category
is a hidden holding pen of 86 confocal guides that readers only ever reach
through tags. Seeding one means a fresh install demonstrates the arrangement the
real corpus uses rather than a tree that the imported content will immediately
contradict.
"""

EXAMPLE_TAGS = ["confocal", "stellaris", "startup"]

LANDING_PAGE_TITLE = "Light Microscopy"

LANDING_PAGE_BODY = """\
The light microscopy suite runs widefield, confocal, superresolution and
live-cell systems. Everything below is written by the people who maintain the
instruments; if a procedure looks wrong, it probably is — tell us rather than
working around it.

## Before your first session

You need an introduction on the system before you can book it. Bring your sample
to the introduction: a session spent on a test slide teaches you less than one
spent on the thing you actually want to image.

## Starting up

```guidelist
tags: confocal, startup
heading: Confocal start-up
```

## Everything confocal

```guidelist
tags: confocal
heading: All confocal guides
```
"""

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
            ("Never switch the lasers on before the scanner has finished its self-test.", "red", "caution", 0),
            ("The 405 nm laser needs about 10 minutes to reach a stable output.", "light_blue", None, 1),
            ("Log in with your ZMB account, not with the local Administrator account.", "violet", "reminder", 0),
        ],
    ),
    (
        "Choose and clean the objective",
        [
            ("Select the objective in the software first so the turret moves under control.", "black", None, 0),
            ("Clean the front lens with lens tissue and a single drop of solvent, one pass only.", "orange", "caution", 0),
            ("Never let solvent run down the barrel; it dissolves the cement inside.", "red", "caution", 1),
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
            ("Local disks are wiped without warning during maintenance.", "red", "caution", 1),
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
    _seed_landing_page(db, admin, categories["Light Microscopy"])
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
    for order_index, (name, description, is_hidden) in enumerate(ZMB_CATEGORIES):
        existing = db.scalars(select(Category).where(Category.name == name)).one_or_none()
        if existing is None:
            existing = Category(
                slug=slugify(name),
                name=name,
                description=description,
                parent_id=None,
                order_index=order_index,
                is_hidden=is_hidden,
            )
            db.add(existing)
        seeded[name] = existing
    db.flush()
    return seeded


def _seed_example_image(db: DbSession, author: User, step: Step) -> None:
    """A picture with shapes on it, so a fresh install shows what a guide is.

    The example guide claimed to demonstrate the annotation vocabulary and had
    no images at all, which meant the one thing a new installation showed was
    the one thing Reticle does that a text document does not.

    The image is drawn here rather than shipped as a file. A binary in the
    repository is a licence question and a merge conflict waiting to happen,
    and the point is only to give the shapes something to sit on.

    The colours matter and are not decorative: each shape is the colour of the
    bullet that refers to it, which is the pairing the whole reading model
    rests on. Getting that wrong in the example teaches everyone the wrong
    thing on their first day.
    """
    from PIL import Image, ImageDraw

    canvas = Image.new("RGB", (960, 600), (18, 22, 30))
    pen = ImageDraw.Draw(canvas)
    # A suggestion of an instrument panel: a body, a turret and two controls.
    pen.rounded_rectangle((120, 90, 840, 510), radius=18, fill=(38, 46, 60))
    pen.ellipse((360, 170, 600, 410), fill=(24, 30, 40), outline=(90, 104, 126), width=3)
    pen.ellipse((430, 240, 530, 340), fill=(12, 16, 22))
    pen.rounded_rectangle((170, 420, 300, 470), radius=8, fill=(70, 82, 100))
    pen.rounded_rectangle((660, 420, 790, 470), radius=8, fill=(70, 82, 100))

    payload = _png_bytes(canvas)
    media = Media(
        id=new_id(),
        storage_path="",
        content_type="image/png",
        kind="image",
        byte_size=len(payload),
        width=canvas.width,
        height=canvas.height,
        alt="The confocal control panel, with the mains switch and the turret marked.",
        original_filename="",
        uploaded_by_id=author.id,
    )
    media.storage_path = f"{media.id[:2]}/{media.id[2:4]}/{media.id}.png"
    db.add(media)
    db.flush()

    build_storage(get_settings()).write(media.storage_path, payload)
    db.add(StepMedia(step_id=step.id, media_id=media.id, order_index=0))

    # Fractions of the image, so the shapes stay correct at any size the page is
    # viewed or printed at. Colours pair with the bullets on the same step.
    for order_index, (shape, color, box) in enumerate(
        [
            ("rectangle", "black", (0.17, 0.69, 0.15, 0.09)),
            ("ellipse", "blue", (0.36, 0.27, 0.26, 0.41)),
            ("arrow", "orange", (0.86, 0.20, -0.14, 0.22)),
        ]
    ):
        x, y, width, height = box
        db.add(
            Annotation(
                media_id=media.id,
                order_index=order_index,
                shape=shape,
                color=color,
                x=x,
                y=y,
                width=width,
                height=height,
            )
        )


def _png_bytes(image) -> bytes:
    from io import BytesIO

    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


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
        time_required_min_minutes=20,
        time_required_max_minutes=40,
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

    for index, slug in enumerate(EXAMPLE_TAGS):
        tag = db.scalars(select(Tag).where(Tag.slug == slug)).one_or_none()
        if tag is None:
            tag = Tag(slug=slug, name=slug.replace("-", " "))
            db.add(tag)
            db.flush()
        db.add(GuideTag(guide_id=guide.id, tag_id=tag.id, order_index=index))

    db.add(
        GuideContributor(
            guide_id=guide.id, user_id=author.id, first_edited_at=now, last_edited_at=now
        )
    )

    first_step: Step | None = None
    for order_index, (title, bullets) in enumerate(EXAMPLE_STEPS):
        step = Step(guide_id=guide.id, order_index=order_index, title=title)
        db.add(step)
        db.flush()
        if first_step is None:
            first_step = step
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

    if first_step is not None:
        _seed_example_image(db, author, first_step)

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


def _seed_landing_page(db: DbSession, author: User, category: Category) -> None:
    """The category landing, as a wiki page with guide lists embedded in it.

    This is the arrangement the live site uses and the one thing a fresh install
    could not otherwise demonstrate: the page is the navigation, the guide lists
    inside it are filled by tag, and the guides they surface need not live in
    this category at all.
    """
    if db.scalar(select(func.count()).select_from(Page)):
        return

    now = utcnow()
    page = Page(
        slug=slugify(LANDING_PAGE_TITLE),
        title=LANDING_PAGE_TITLE,
        summary="Instruments, access and the procedures for running them.",
        category_id=category.id,
        is_landing=True,
        body=LANDING_PAGE_BODY,
        status="published",
        version=1,
        author_id=author.id,
        last_edited_by_id=author.id,
        published_at=now,
    )
    db.add(page)
    db.flush()
    db.add(
        PageContributor(page_id=page.id, user_id=author.id, first_edited_at=now, last_edited_at=now)
    )
    db.flush()
    db.refresh(page)
    db.add(
        PageRevision(
            page_id=page.id,
            version=page.version,
            published_at=now,
            published_by_id=author.id,
            document=page_document(page),
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
