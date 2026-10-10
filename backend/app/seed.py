"""Bring a fresh installation up to a usable state.

Seeding is idempotent and never overwrites something an operator has already
changed, so it is safe to run on every deployment rather than once by hand. The
bootstrap password is read from the environment and has no fallback: a default
here would be published in this repository and would then exist on every
installation that skipped the first-run checklist.

Run it with ``python -m app.seed``. That creates the administrator, ZMB's
category set and one worked example guide.

``python -m app.seed --demo`` additionally fills the installation with a small,
realistic body of content — tagged guides with annotated screenshots, a hidden
holding category, landing pages that embed tag-filtered guide lists, a
standalone wiki page and a draft or two — so that there is something to click
through. The screenshots are drawn here with Pillow; nothing is downloaded and
no third-party artwork is involved. Demo mode is for a test or evaluation
instance, and is just as idempotent: run it twice and the second run adds
nothing.

Everything is written through the same functions the API uses to save and
publish, so seeded content is held to the same rules as content typed into the
editor and cannot drift into a shape the application would not itself produce.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from . import content, db, images, migrate
from .documents import normalised_tags, resolve_tags
from .models import Bullet, Category, Guide, Media, Page, Step, StepMedia, User, new_id
from .pages import sync_media_references
from .routers.guides import GUIDES
from .routers.pages import PAGES
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

BulletSpec = tuple[str, str, str | None, int]
"""Text, colour, flag and indent level."""


@dataclass(frozen=True)
class ShapeSpec:
    """An annotation, and — for demo screenshots — the thing it is drawn around."""

    shape: str
    color: str
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class ScreenshotSpec:
    caption: str
    alt: str
    shapes: tuple[ShapeSpec, ...] = ()


@dataclass(frozen=True)
class StepSpec:
    title: str
    bullets: tuple[BulletSpec, ...]
    screenshots: tuple[ScreenshotSpec, ...] = ()


@dataclass(frozen=True)
class GuideSpec:
    title: str
    summary: str
    category: str
    tags: tuple[str, ...]
    difficulty: str
    minutes: tuple[int | None, int | None]
    introduction: str
    conclusion: str
    steps: tuple[StepSpec, ...]
    publish: bool = True


@dataclass(frozen=True)
class PageSpec:
    title: str
    summary: str
    body: str
    category: str | None = None
    is_landing: bool = False
    publish: bool = True
    hero_caption: str | None = None
    figure_caption: str | None = None


@dataclass
class SeedReport:
    """What a run actually created, so the command can say so."""

    created: list[str] = field(default_factory=list)

    def add(self, what: str) -> None:
        self.created.append(what)


EXAMPLE_GUIDE = GuideSpec(
    title="Starting a Session on the Confocal",
    summary="From booking to shutdown: the routine every confocal session at ZMB follows.",
    category="Light Microscopy",
    tags=("Confocal", "Getting Started"),
    difficulty="easy",
    minutes=(20, 30),
    introduction=(
        "This guide covers the standard start-up routine for the confocal systems in the ZMB "
        "light microscopy suite. It assumes you have completed the introductory training and "
        "hold a valid booking."
    ),
    conclusion=(
        "If anything behaved unexpectedly, note it in the booking system and tell the "
        "responsible staff member. A fault reported the same day is usually a ten-minute fix."
    ),
    steps=(
        StepSpec(
            "Book the system and check the room",
            (
                ("Confirm your booking in the ZMB calendar before you enter the room.", "black", None, 0),
                ("The previous user has 10 minutes to finish; do not interrupt an acquisition.", "blue", "note", 0),
                ("If the room is dark and the door sign says LIVE CELL, knock before entering.", "orange", "caution", 1),
            ),
        ),
        StepSpec(
            "Power up in order",
            (
                ("Switch on the mains strip, then the scanner, then the PC. Wait for each to settle.", "black", None, 0),
                ("Never switch the lasers on before the scanner has finished its self-test.", "red", "caution", 0),
                ("The 405 nm laser needs about 10 minutes to reach a stable output.", "light_blue", None, 1),
                ("Log in with your ZMB account, not with the local Administrator account.", "violet", "reminder", 0),
            ),
        ),
        StepSpec(
            "Choose and clean the objective",
            (
                ("Select the objective in the software first so the turret moves under control.", "black", None, 0),
                ("Clean the front lens with lens tissue and a single drop of solvent, one pass only.", "orange", "caution", 0),
                ("Never let solvent run down the barrel; it dissolves the cement inside.", "red", "caution", 1),
                ("Use the immersion medium printed on the objective, not the one already on the bench.", "black", None, 2),
            ),
        ),
        StepSpec(
            "Mount the sample and find focus",
            (
                ("Place the slide coverslip-down and clamp it before adding immersion medium.", "black", None, 0),
                ("Find focus in widefield at low magnification, then switch to scanning.", "green", None, 0),
                ("Start with the lowest laser power that gives a visible signal.", "yellow", "note", 0),
            ),
        ),
        StepSpec(
            "Acquire, save and shut down",
            (
                ("Save to your group folder on the server, never to the local desktop.", "black", None, 0),
                ("Local disks are wiped without warning during maintenance.", "red", "caution", 1),
                ("Export the acquisition settings alongside the images so the run is reproducible.", "blue", "note", 0),
                ("Log the session in the booking system, including any fault you noticed.", "violet", "reminder", 0),
            ),
        ),
    ),
)

HOLDING_CATEGORY = ("Confocal – hidden guides", "Holding category: these guides are reached through their tags.")

DEMO_GUIDES: tuple[GuideSpec, ...] = (
    GuideSpec(
        title="Setting Up a Tile Scan in LAS X",
        summary="Define the region, set the overlap and let the stage stitch a whole section.",
        category=HOLDING_CATEGORY[0],
        tags=("Confocal", "Stellaris", "LAS X"),
        difficulty="moderate",
        minutes=(30, 90),
        introduction=(
            "A tile scan images an area larger than one field of view by moving the stage in a grid "
            "and stitching the tiles.\n\nSet it up at low magnification first: it is much quicker to "
            "find the edges of a section with the 10x than with the 63x."
        ),
        conclusion="Check the stitched overview before you unmount the sample; a missing tile cannot be added later.",
        steps=(
            StepSpec(
                "Open the Navigator",
                (
                    ("Click the Navigator button in the top toolbar.", "red", None, 0),
                    ("The live image shrinks into the corner and the stage map takes over the window.", "black", None, 1),
                    ("If the button is greyed out, the stage has not been initialised.", "blue", "note", 0),
                ),
                (
                    ScreenshotSpec(
                        "LAS X  ·  Acquire",
                        "The LAS X toolbar with the Navigator button outlined in red.",
                        (ShapeSpec("rectangle", "red", 0.62, 0.05, 0.16, 0.09),),
                    ),
                ),
            ),
            StepSpec(
                "Mark the region",
                (
                    ("Drag a rectangle round the tissue on the stage map.", "green", None, 0),
                    ("Leave a margin of one tile on every side; sections are rarely square.", "black", None, 1),
                    ("Set the overlap to 10 %.", "orange", None, 0),
                    ("Less than 5 % and the stitching has nothing to align on.", "orange", "caution", 1),
                ),
                (
                    ScreenshotSpec(
                        "Navigator  ·  Stage map",
                        "The stage map with the tissue outlined in green.",
                        (
                            ShapeSpec("ellipse", "green", 0.2, 0.28, 0.42, 0.48),
                            ShapeSpec("arrow", "green", 0.85, 0.9, -0.2, -0.22),
                        ),
                    ),
                    ScreenshotSpec(
                        "Navigator  ·  Tile settings",
                        "The tile settings panel with the overlap field outlined in orange.",
                        (ShapeSpec("rectangle", "orange", 0.08, 0.42, 0.5, 0.12),),
                    ),
                ),
            ),
            StepSpec(
                "Set the focus map and start",
                (
                    ("Add at least four focus points spread across the region.", "light_blue", None, 0),
                    ("Press Start. The estimated duration appears next to the button.", "violet", None, 0),
                    ("Book enough time: a 20 × 20 scan at 63x takes well over an hour.", "violet", "reminder", 1),
                ),
                (
                    ScreenshotSpec(
                        "Navigator  ·  Focus map",
                        "The focus map with four focus points and the Start button outlined.",
                        (
                            ShapeSpec("ellipse", "light_blue", 0.25, 0.3, 0.1, 0.14),
                            ShapeSpec("rectangle", "violet", 0.74, 0.8, 0.2, 0.12),
                        ),
                    ),
                ),
            ),
        ),
    ),
    GuideSpec(
        title="Mounting Fixed Cells on a Coverslip",
        summary="A clean, bubble-free mount that survives a week in the fridge.",
        category="Sample Preparation",
        tags=("Sample Prep", "Getting Started"),
        difficulty="very_easy",
        minutes=(15, None),
        introduction="Work on a clean bench with the coverslips cell-side up until the last moment.",
        conclusion="Label the slide with date, sample and your initials. Unlabelled slides are discarded monthly.",
        steps=(
            StepSpec(
                "Prepare the slide",
                (
                    ("Clean the slide with 70 % ethanol and let it dry.", "black", None, 0),
                    ("Place a 10 µl drop of mounting medium in the centre.", "black", None, 0),
                    ("Hardening media contain solvent — work under the hood.", "red", "caution", 1),
                ),
            ),
            StepSpec(
                "Lower the coverslip",
                (
                    ("Pick the coverslip up with fine forceps and touch one edge to the drop.", "black", None, 0),
                    ("Lower it slowly at an angle so the medium pushes the air out ahead of it.", "green", None, 0),
                    ("Do not press: it shears the cells.", "orange", "caution", 1),
                    ("A single small bubble at the edge is fine.", "blue", "note", 2),
                ),
                (
                    ScreenshotSpec(
                        "Bench camera  ·  Mounting",
                        "A coverslip being lowered at an angle onto a drop of mounting medium.",
                        (ShapeSpec("arrow", "green", 0.75, 0.25, -0.25, 0.3),),
                    ),
                ),
            ),
            StepSpec(
                "Cure and store",
                (
                    ("Leave the slide flat in the dark overnight.", "black", None, 0),
                    ("Seal the edges with nail varnish if you used a non-hardening medium.", "yellow", None, 0),
                    ("Store at 4 °C and image within a week.", "violet", "reminder", 0),
                ),
            ),
        ),
    ),
    GuideSpec(
        title="Batch Deconvolution in Fiji",
        summary="Run the same deconvolution over a folder of stacks, unattended.",
        category="Image Analysis",
        tags=("Fiji", "Confocal"),
        difficulty="difficult",
        minutes=(45, 120),
        introduction="Still being written: the macro works, the screenshots are missing.",
        conclusion="",
        steps=(
            StepSpec(
                "Collect the stacks in one folder",
                (
                    ("Export from LAS X as .lif or as one OME-TIFF per stack.", "black", None, 0),
                    ("Keep the metadata: the pixel size is read from it.", "blue", "note", 1),
                ),
            ),
            StepSpec(
                "Run the macro",
                (("Plugins › Macros › Run… and choose batch_deconvolve.ijm.", "black", None, 0),),
            ),
        ),
        publish=False,
    ),
)

DEMO_PAGES: tuple[PageSpec, ...] = (
    PageSpec(
        title="Light Microscopy",
        summary="Confocal, widefield and live-cell systems, and how to use them.",
        category="Light Microscopy",
        is_landing=True,
        hero_caption="ZMB  ·  Light microscopy suite",
        figure_caption="Stellaris 5  ·  Room 12",
        body=(
            "## Before your first session\n\n"
            "Every user completes an introduction with ZMB staff before booking alone. "
            "After that, the guides below cover the routine.\n\n"
            "```guidelist\ntags: getting-started\nheading: Start here\n```\n\n"
            "## Confocal systems\n\n"
            "{figure}\n\n"
            "The Stellaris systems all run **LAS X**. Guides that apply to any of them are tagged "
            "`confocal`; the ones below are specific to the software.\n\n"
            "```guidelist\ntags: confocal, las-x\nheading: Working in LAS X\n```\n\n"
            "```guidelist\ntags: confocal\nheading: Everything tagged confocal\n```\n\n"
            "| System | Objectives | Best for |\n| --- | --- | --- |\n"
            "| Stellaris 5 | 10x, 20x, 63x oil | Fixed samples |\n"
            "| Stellaris 8 | 20x, 40x water, 63x oil | Live cells, FLIM |\n"
        ),
    ),
    PageSpec(
        title="Sample Preparation",
        summary="Fixation, labelling and mounting for light microscopy.",
        category="Sample Preparation",
        is_landing=True,
        body=(
            "Good images start at the bench. These guides cover the steps between the culture dish "
            "and the microscope stage.\n\n"
            "```guidelist\ntags: sample-prep\n```\n\n"
            "> Mounting media and fixatives are kept in the cabinet in room 14. Take what you need "
            "and note it on the list.\n"
        ),
    ),
    PageSpec(
        title="Booking Rules and Fair Use",
        summary="How instrument time is shared, and what happens when it is not used.",
        body=(
            "## Booking\n\n"
            "1. Book at most **two weeks** ahead.\n"
            "2. Daytime slots are limited to four hours per person per system.\n"
            "3. Cancel at least 24 hours ahead or the slot is charged.\n\n"
            "## No-shows\n\n"
            "A booking not started within 30 minutes is released to whoever is waiting.\n\n"
            "## Questions\n\n"
            "Ask at the ZMB office, or write to the responsible person named on each instrument's page.\n"
        ),
    ),
    PageSpec(
        title="Image Analysis",
        summary="Workstations, licences and pipelines.",
        category="Image Analysis",
        is_landing=True,
        publish=False,
        body="Draft — the workstation list still has to be confirmed.\n\n```guidelist\ntags: fiji\n```\n",
    ),
)

DEMO_ACCOUNTS: tuple[tuple[str, str, str], ...] = (
    ("demo.author", "Demo Author", "author"),
    ("demo.viewer", "Demo Viewer", "viewer"),
)


class SeedError(RuntimeError):
    """Raised when the environment cannot support a safe first run."""


def seed(session: DbSession, settings: Settings, demo: bool = False) -> SeedReport:
    """Seed in one transaction: a run that fails part-way leaves nothing behind."""
    report = SeedReport()
    try:
        admin = _seed_admin(session, settings, report)
        categories = _seed_categories(session, report)
        if not session.scalar(select(func.count()).select_from(Guide)):
            _seed_guide(session, admin, categories, EXAMPLE_GUIDE, report)
        if demo:
            _seed_demo(session, settings, admin, categories, report)
        session.commit()
    except BaseException:
        session.rollback()
        raise
    return report


def _seed_admin(session: DbSession, settings: Settings, report: SeedReport) -> User:
    email = settings.admin_email.strip().lower()
    existing = session.scalars(select(User).where(User.email == email)).one_or_none()
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
    session.add(admin)
    session.flush()
    report.add(f"administrator {email}")
    return admin


def _seed_categories(session: DbSession, report: SeedReport) -> dict[str, Category]:
    seeded: dict[str, Category] = {}
    for order_index, (name, description) in enumerate(ZMB_CATEGORIES):
        seeded[name] = _category(session, name, description, order_index, False, report)
    session.flush()
    return seeded


def _category(
    session: DbSession, name: str, description: str, order_index: int, is_hidden: bool, report: SeedReport
) -> Category:
    existing = session.scalars(select(Category).where(Category.name == name)).first()
    if existing is not None:
        return existing
    category = Category(
        slug=slugify(name),
        name=name,
        description=description,
        parent_id=None,
        order_index=order_index,
        is_hidden=is_hidden,
    )
    session.add(category)
    report.add(f"category {name}")
    return category


def _seed_guide(
    session: DbSession, author: User, categories: dict[str, Category], spec: GuideSpec, report: SeedReport
) -> None:
    """One guide, saved and — unless the spec says otherwise — published.

    The example guide is published rather than left in draft, because the first
    thing anyone checks after installing is whether a reader account sees
    anything at all.
    """
    slug = slugify(spec.title)
    if session.scalar(select(func.count()).select_from(Guide).where(Guide.slug == slug)):
        return

    low, high = spec.minutes
    guide = Guide(
        slug=slug,
        title=spec.title,
        summary=spec.summary,
        category_id=categories[spec.category].id,
        difficulty=spec.difficulty,
        time_required_min_minutes=low,
        time_required_max_minutes=high,
        introduction=spec.introduction,
        conclusion=spec.conclusion,
        author_id=author.id,
        last_edited_by_id=author.id,
    )
    guide.tags = resolve_tags(session, normalised_tags(list(spec.tags)))
    content.add_contributor(session, GUIDES, guide, author)
    session.add(guide)
    session.flush()

    for order_index, step_spec in enumerate(spec.steps):
        step = Step(guide_id=guide.id, order_index=order_index, title=step_spec.title)
        for position, (text, color, icon, level) in enumerate(step_spec.bullets):
            step.bullets.append(Bullet(order_index=position, text=text, color=color, icon=icon, level=level))
        for position, screenshot in enumerate(step_spec.screenshots):
            media = _placeholder_media(session, author, screenshot.caption, screenshot.alt, screenshot.shapes)
            step.media_links.append(
                StepMedia(
                    media_id=media.id,
                    order_index=position,
                    alt=screenshot.alt,
                    annotations=[_annotation(shape) for shape in screenshot.shapes],
                )
            )
        session.add(step)
    session.flush()
    session.refresh(guide)

    if spec.publish:
        content.publish(session, GUIDES, guide, author)
    report.add(f"guide {spec.title}" + ("" if spec.publish else " (draft)"))


def _annotation(shape: ShapeSpec) -> dict:
    return {
        "id": new_id(),
        "shape": shape.shape,
        "color": shape.color,
        "x": shape.x,
        "y": shape.y,
        "width": shape.width,
        "height": shape.height,
    }


SCREENSHOT_SIZE = (960, 600)
PANEL = "#161b22"
PANEL_EDGE = "#30363d"
INK = "#c9d1d9"
FAINT = "#6e7681"
SIGNAL = "#3fb950"


def draw_placeholder(caption: str, shapes: tuple[ShapeSpec, ...]) -> bytes:
    """Draw a stand-in for a screenshot of acquisition software.

    It is dark on purpose. Most of what ZMB annotates is a near-black LAS X or
    ZEN window, and that is the background the annotation colours have to stay
    legible against, so it is the one worth testing with. A control is drawn
    wherever an annotation points, so the shapes visibly outline something
    instead of floating over nothing.
    """
    width, height = SCREENSHOT_SIZE
    image = Image.new("RGB", SCREENSHOT_SIZE, "#0d1117")
    draw = ImageDraw.Draw(image)
    title_font = ImageFont.load_default(size=22)
    small_font = ImageFont.load_default(size=14)

    draw.rectangle((0, 0, width, 44), fill=PANEL)
    draw.line((0, 44, width, 44), fill=PANEL_EDGE, width=2)
    draw.text((18, 10), caption, fill=INK, font=title_font)

    draw.rectangle((16, 60, 250, height - 16), fill=PANEL, outline=PANEL_EDGE)
    for row in range(8):
        top = 78 + row * 58
        draw.text((30, top), f"Channel {row + 1}" if row < 4 else f"Setting {row - 3}", fill=FAINT, font=small_font)
        draw.rectangle((30, top + 22, 236, top + 34), fill="#21262d")
        draw.rectangle((30, top + 22, 60 + row * 22, top + 34), fill="#1f6feb")

    draw.rectangle((266, 60, width - 16, height - 16), fill="#010409", outline=PANEL_EDGE)
    for index in range(40):
        cx = 300 + (index * 137) % (width - 360)
        cy = 90 + (index * 89) % (height - 150)
        radius = 6 + (index * 7) % 16
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=SIGNAL, width=2)

    for shape in shapes:
        if shape.shape != "rectangle":
            continue
        left, top = shape.x * width, shape.y * height
        right, bottom = left + shape.width * width, top + shape.height * height
        draw.rounded_rectangle((left + 8, top + 8, right - 8, bottom - 8), radius=6, fill="#21262d", outline=FAINT)
        draw.text((left + 20, (top + bottom) / 2 - 9), "Control", fill=INK, font=small_font)

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _placeholder_media(
    session: DbSession, author: User, caption: str, alt: str, shapes: tuple[ShapeSpec, ...] = ()
) -> Media:
    """Store a drawn screenshot exactly as an uploaded one would be stored."""
    settings = get_settings()
    normalised = images.normalise(
        draw_placeholder(caption, shapes), settings.max_image_dimension, settings.max_image_pixels
    )
    media_id = new_id()
    storage_path = images.relative_storage_path(media_id, normalised.extension)
    images.write_file(settings.media_root, storage_path, normalised.payload)
    media = Media(
        id=media_id,
        kind="image",
        storage_path=storage_path,
        content_type=normalised.content_type,
        byte_size=len(normalised.payload),
        width=normalised.width,
        height=normalised.height,
        alt=alt,
        original_filename=f"{slugify(caption)}.png",
        uploaded_by_id=author.id,
    )
    session.add(media)
    session.flush()
    return media


def _seed_page(
    session: DbSession, author: User, categories: dict[str, Category], spec: PageSpec, report: SeedReport
) -> None:
    slug = slugify(spec.title)
    if session.scalar(select(func.count()).select_from(Page).where(Page.slug == slug)):
        return
    category = categories[spec.category] if spec.category is not None else None
    if spec.is_landing and session.scalar(
        select(func.count())
        .select_from(Page)
        .where(Page.category_id == category.id, Page.is_landing.is_(True), Page.status != "archived")
    ):
        return

    body = spec.body
    if spec.figure_caption is not None:
        figure = _placeholder_media(session, author, spec.figure_caption, spec.figure_caption)
        body = body.replace("{figure}", f"![{spec.figure_caption}](/api/media/{figure.id})")
    hero = None
    if spec.hero_caption is not None:
        hero = _placeholder_media(session, author, spec.hero_caption, spec.hero_caption)

    page = Page(
        slug=slug,
        title=spec.title,
        summary=spec.summary,
        category_id=category.id if category is not None else None,
        is_landing=spec.is_landing,
        body=body,
        hero_media_id=hero.id if hero is not None else None,
        author_id=author.id,
        last_edited_by_id=author.id,
    )
    content.add_contributor(session, PAGES, page, author)
    sync_media_references(session, page)
    session.add(page)
    session.flush()

    if spec.publish:
        content.publish(session, PAGES, page, author)
    report.add(f"page {spec.title}" + ("" if spec.publish else " (draft)"))


def _seed_demo_accounts(session: DbSession, settings: Settings, report: SeedReport) -> None:
    """An author and a viewer to try the roles with — only if given a password.

    Demo accounts with a published password would be the first thing tried
    against any instance that had ever run this, so the password comes from
    ``RETICLE_DEMO_PASSWORD`` and without it no account is created.
    """
    if not settings.demo_password:
        return
    if len(settings.demo_password) < settings.min_password_length:
        raise SeedError(
            f"RETICLE_DEMO_PASSWORD must be at least {settings.min_password_length} characters long."
        )
    domain = settings.admin_email.strip().lower().rpartition("@")[2]
    for local_part, display_name, role in DEMO_ACCOUNTS:
        email = f"{local_part}@{domain}"
        if session.scalars(select(User).where(User.email == email)).one_or_none() is not None:
            continue
        session.add(
            User(
                email=email,
                display_name=display_name,
                role=role,
                password_hash=hash_password(settings.demo_password),
            )
        )
        report.add(f"{role} account {email}")
    session.flush()


def _seed_demo(
    session: DbSession, settings: Settings, admin: User, categories: dict[str, Category], report: SeedReport
) -> None:
    name, description = HOLDING_CATEGORY
    categories = dict(categories)
    categories[name] = _category(session, name, description, len(ZMB_CATEGORIES), True, report)
    session.flush()

    _seed_demo_accounts(session, settings, report)
    for guide_spec in DEMO_GUIDES:
        _seed_guide(session, admin, categories, guide_spec, report)
    for page_spec in DEMO_PAGES:
        _seed_page(session, admin, categories, page_spec, report)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m app.seed",
        description="Create the administrator, the ZMB categories and an example guide. Safe to re-run.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="also create demonstration content: tagged guides with annotated images, wiki pages, a hidden category",
    )
    arguments = parser.parse_args(argv)

    migrate.upgrade()
    with db.SessionLocal() as session:
        report = seed(session, get_settings(), demo=arguments.demo)

    if report.created:
        print("Created:")
        for line in report.created:
            print(f"  {line}")
    else:
        print("Nothing to do: everything was already in place.")


if __name__ == "__main__":
    main()
