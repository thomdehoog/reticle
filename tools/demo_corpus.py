"""Fill a Reticle instance with a corpus shaped like a real facility's.

Reticle's first-run seed creates one example guide, which is enough to prove the
software starts and not enough to see whether it works. Half of what has been
built — sub-categories, quick links, staff-only procedures, pinned and info
blocks, video steps, instrument groupings, embedded guide lists — has no
demonstration in a one-guide library, so the only way to look at it is to make
it. This writes about a dozen documents that between them use every one.

It is not the ZMB corpus and does not pretend to be. The instrument names are
ZMB's because the shape of the material matters — a facility's guides cluster
per instrument and are found by tag rather than by browsing — but every word and
every picture here was written for this script.

It goes through the HTTP API, signed in as an ordinary author, rather than
writing to the database. That is the point of it: the Dozuki migration will push
257 guides through these same endpoints, and a corpus built any other way would
prove nothing about whether they can take it. Everything it does, a person could
do by clicking.

    python tools/demo_corpus.py --base-url http://localhost:8000 \\
        --email thom@zmb.uzh.ch --password …

Running it twice is safe. A guide that is already there is left alone — its
pictures are already uploaded and re-running would only duplicate them — while
the wiki pages are rewritten from this file, since they are text and the wording
is still being worked out.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import argparse
import io
import sys
from dataclasses import dataclass, field
from typing import Any

import httpx
from PIL import Image, ImageDraw

# Named here rather than imported from the backend package: this script talks to
# a Reticle over HTTP and should run against a deployment it shares no code
# with. They are part of the published API contract — see docs/API.md.
CSRF_COOKIE = "reticle_csrf"
CSRF_HEADER = "X-CSRF-Token"


# --------------------------------------------------------------- the pictures

# Drawn here rather than shipped as files. A repository of a documentation tool
# should not carry a folder of stock photographs, and a script that invents its
# own pictures can be read and re-run by anyone without hunting for assets.
# These are flat panels — a screen, some rows of controls, a few dials — which
# is what most of a microscopy screenshot looks like from across a room.

PANEL_INK = (18, 22, 30)
PANEL_EDGE = (78, 88, 104)


def panel(tint: tuple[int, int, int], screen: str = "wide", dials: int = 4) -> bytes:
    """One instrument panel, as PNG bytes.

    ``tint`` separates one picture from another at a glance, which is all a
    demonstration corpus needs: the point of these is to show that four pictures
    on a step are four distinguishable pictures, not to teach anyone the
    instrument.
    """
    image = Image.new("RGB", (1120, 700), PANEL_INK)
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle([60, 60, 1060, 640], radius=22, outline=PANEL_EDGE, width=3)

    if screen == "wide":
        draw.rounded_rectangle([110, 120, 640, 400], radius=12, fill=_shade(tint, 0.42))
    else:
        draw.rounded_rectangle([110, 120, 380, 400], radius=12, fill=_shade(tint, 0.42))

    for row in range(4):
        top = 130 + row * 66
        draw.rounded_rectangle([700, top, 1010, top + 44], radius=8, fill=(56, 64, 78))

    for index in range(dials):
        left = 140 + index * 170
        radius = 34 if index % 2 == 0 else 24
        draw.ellipse([left, 470, left + radius * 2, 470 + radius * 2], outline=tint, width=5)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _shade(colour: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(channel * factor))) for channel in colour)  # type: ignore[return-value]


def cover(tint: tuple[int, int, int]) -> bytes:
    """A wider, quieter picture, for the banner across a section."""
    image = Image.new("RGB", (1600, 900), _shade(tint, 0.22))
    draw = ImageDraw.Draw(image)
    for index in range(26):
        x = 60 + (index * 137) % 1500
        y = 80 + (index * 313) % 760
        radius = 26 + (index * 37) % 120
        draw.ellipse([x, y, x + radius, y + radius], outline=_shade(tint, 0.85), width=3)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


# ------------------------------------------------------------------ the client


class Reticle:
    """The API, as an author uses it.

    Thin on purpose. Every method here maps to one endpoint, so what this script
    demonstrates about the API is what the API actually offers rather than what
    a helper layer papered over.
    """

    def __init__(self, base_url: str, email: str, password: str) -> None:
        self.http = httpx.Client(base_url=base_url.rstrip("/"), timeout=60.0)
        response = self.http.post("/api/auth/login", json={"email": email, "password": password})
        if response.status_code != 200:
            raise SystemExit(
                f"Could not sign in as {email}: {response.status_code} {response.text[:200]}"
            )
        self.me = response.json()

        # Signing in sets two cookies: the session, and a CSRF token that every
        # write has to echo back in a header. A script is not a browser and gets
        # no free pass — which is the correct answer, and worth a script
        # demonstrating rather than an exemption nobody notices until it is
        # abused.
        token = self.http.cookies.get(CSRF_COOKIE)
        if not token:
            raise SystemExit(
                f"Signed in, but no {CSRF_COOKIE} cookie came back — nothing can be written."
            )
        self.http.headers[CSRF_HEADER] = token

    def _json(self, response: httpx.Response) -> Any:
        if response.status_code >= 400:
            raise SystemExit(
                f"{response.request.method} {response.request.url.path} "
                f"→ {response.status_code} {response.text[:400]}"
            )
        return response.json()

    # categories ------------------------------------------------------------

    def categories(self) -> list[dict[str, Any]]:
        return self._json(self.http.get("/api/categories"))

    def create_category(self, **body: Any) -> dict[str, Any]:
        return self._json(self.http.post("/api/categories", json=body))

    def patch_category(self, category_id: str, **body: Any) -> dict[str, Any]:
        return self._json(self.http.patch(f"/api/categories/{category_id}", json=body))

    # media -----------------------------------------------------------------

    def upload(self, name: str, data: bytes, alt: str) -> dict[str, Any]:
        return self._json(
            self.http.post(
                "/api/media",
                files={"file": (name, data, "image/png")},
                data={"alt": alt},
            )
        )

    # guides ----------------------------------------------------------------

    def guides(self, **params: Any) -> list[dict[str, Any]]:
        return self._json(self.http.get("/api/guides", params=params))

    def guide(self, id_or_slug: str) -> dict[str, Any]:
        return self._json(self.http.get(f"/api/guides/{id_or_slug}"))

    def create_guide(self, title: str, category_id: str) -> dict[str, Any]:
        return self._json(
            self.http.post("/api/guides", json={"title": title, "categoryId": category_id})
        )

    def save_guide(self, guide: dict[str, Any]) -> dict[str, Any]:
        return self._json(self.http.put(f"/api/guides/{guide['id']}", json=guide))

    def publish_guide(self, guide_id: str) -> dict[str, Any]:
        return self._json(self.http.post(f"/api/guides/{guide_id}/publish"))

    # pages -----------------------------------------------------------------

    def pages(self, **params: Any) -> list[dict[str, Any]]:
        return self._json(self.http.get("/api/pages", params=params))

    def page(self, id_or_slug: str) -> dict[str, Any]:
        return self._json(self.http.get(f"/api/pages/{id_or_slug}"))

    def create_page(self, **body: Any) -> dict[str, Any]:
        return self._json(self.http.post("/api/pages", json=body))

    def save_page(self, page: dict[str, Any]) -> dict[str, Any]:
        return self._json(self.http.put(f"/api/pages/{page['id']}", json=page))

    def publish_page(self, page_id: str) -> dict[str, Any]:
        return self._json(self.http.post(f"/api/pages/{page_id}/publish"))


# ------------------------------------------------------------------- the shape


@dataclass
class Point:
    """One coloured point beside a step."""

    text: str
    color: str = "black"
    icon: str | None = None
    level: int = 0


@dataclass
class Mark:
    """A shape drawn on a step's picture, in the colour of the point it belongs to."""

    shape: str
    color: str
    box: tuple[float, float, float, float]


@dataclass
class Block:
    """A step, an info block or the pinned block at the top of a guide."""

    title: str
    points: list[Point]
    kind: str = "step"
    pictures: int = 0
    tint: tuple[int, int, int] = (86, 150, 226)
    marks: list[Mark] = field(default_factory=list)


@dataclass
class GuideSpec:
    slug_hint: str
    title: str
    category: str
    summary: str
    introduction: str
    tags: list[str]
    blocks: list[Block]
    difficulty: str = "easy"
    minutes: tuple[int | None, int | None] = (None, None)
    quick_link: bool = False
    visibility: str = "everyone"
    publish: bool = True


BLUE = (86, 150, 226)
GREEN = (110, 196, 140)
AMBER = (226, 156, 74)
VIOLET = (160, 130, 226)
TEAL = (86, 190, 196)


# The corpus. Written out rather than generated, because a demonstration that
# reads like a facility's own guides is worth more than a hundred of "Step 3".

CATEGORIES = [
    ("Confocal", "Light Microscopy", "Point-scanning systems: Stellaris, SP8.", BLUE),
    ("Widefield", "Light Microscopy", "Camera-based systems for fixed and live samples.", GREEN),
    ("Superresolution", "Light Microscopy", "STED and single-molecule methods.", VIOLET),
    ("Live-cell Imaging", "Light Microscopy", "Incubation, perfusion and long time-lapse.", TEAL),
]


GUIDES = [
    GuideSpec(
        slug_hint="booking-an-instrument",
        title="Booking an instrument",
        category="Basics, Access and IT",
        summary="How to reserve time, and what happens if you do not turn up.",
        introduction=(
            "Every instrument at the centre is booked through the calendar. "
            "Read this once; it answers most of what people ask at the door."
        ),
        tags=["booking", "access"],
        quick_link=True,
        minutes=(5, 10),
        blocks=[
            Block(
                kind="info",
                title="Before you can book anything",
                points=[
                    Point("You need an account and the introductory training for that instrument."),
                    Point(
                        "Training is arranged per instrument, not per person — being trained on "
                        "the Stellaris does not open the SP8.",
                        icon="note",
                        color="light_blue",
                    ),
                ],
            ),
            Block(
                title="Find the instrument in the calendar",
                pictures=2,
                tint=BLUE,
                points=[
                    Point("Open the calendar and choose the instrument by name, not by room."),
                    Point(
                        "Two systems share room G14. Booking the room books nothing.",
                        icon="caution",
                        color="red",
                    ),
                ],
                marks=[Mark("rectangle", "red", (0.08, 0.14, 0.42, 0.28))],
            ),
            Block(
                title="Book the block you will actually use",
                pictures=1,
                tint=BLUE,
                points=[
                    Point("Sessions run in half-hour blocks from 08:00."),
                    Point(
                        "A booking nobody arrives for is charged after 30 minutes. Cancel it "
                        "instead — somebody else is waiting.",
                        icon="reminder",
                        color="orange",
                    ),
                ],
            ),
        ],
    ),
    GuideSpec(
        slug_hint="getting-in-out-of-hours",
        title="Getting in out of hours",
        category="Basics, Access and IT",
        summary="Evenings, weekends, and the door that needs a card and a code.",
        introduction="Out-of-hours access is granted per person and is not automatic.",
        tags=["access"],
        quick_link=True,
        minutes=(5, None),
        blocks=[
            Block(
                title="Ask for out-of-hours access first",
                pictures=1,
                tint=AMBER,
                points=[
                    Point("Send the request from your institutional address, not a private one."),
                    Point(
                        "Never prop the outer door. It is alarmed, and the alarm names the "
                        "person whose card opened it last.",
                        icon="caution",
                        color="red",
                    ),
                ],
            ),
            Block(
                title="Sign the logbook by the lift",
                pictures=1,
                tint=AMBER,
                points=[
                    Point("Name, instrument, time in. Time out on the way past."),
                    Point("This is what tells the fire warden a floor is occupied.", icon="note"),
                ],
            ),
        ],
    ),
    GuideSpec(
        slug_hint="where-your-data-goes",
        title="Where your data goes",
        category="Basics, Access and IT",
        summary="Group storage, what is backed up, and what is wiped.",
        introduction=(
            "Acquisition machines are not storage. Anything left on one is deleted "
            "without warning during maintenance."
        ),
        tags=["storage", "it"],
        quick_link=True,
        minutes=(10, None),
        blocks=[
            Block(
                title="Save to your group folder",
                pictures=2,
                tint=GREEN,
                points=[
                    Point("The group share is mounted on every acquisition machine."),
                    Point(
                        "The desktop and D:\\ are wiped during maintenance, without notice.",
                        icon="caution",
                        color="red",
                    ),
                    Point("Backups run nightly and keep 30 days.", icon="note", color="light_blue"),
                ],
                marks=[
                    Mark("rectangle", "green", (0.09, 0.16, 0.40, 0.24)),
                    Mark("arrow", "red", (0.62, 0.62, -0.18, -0.26)),
                ],
            ),
        ],
    ),
    GuideSpec(
        slug_hint="starting-a-session-on-the-stellaris",
        title="Starting a session on the Stellaris 5",
        category="Confocal",
        summary="From the mains switch to a focused sample.",
        introduction=(
            "The order matters on this system: the scanner has to finish its self-test "
            "before the lasers are switched on."
        ),
        tags=["stellaris", "confocal", "startup"],
        difficulty="moderate",
        minutes=(20, 40),
        blocks=[
            Block(
                kind="pinned",
                title="Read before you switch anything on",
                points=[
                    Point(
                        "If the sign on the door says LIVE CELL, knock and wait. Opening the "
                        "door mid-acquisition ruins somebody's experiment.",
                        icon="caution",
                        color="red",
                    ),
                ],
            ),
            Block(
                title="Power up in order",
                pictures=3,
                tint=BLUE,
                points=[
                    Point("Mains strip, then scanner, then PC. Wait for each before the next."),
                    Point(
                        "Never switch the lasers on before the scanner has finished its self-test.",
                        icon="caution",
                        color="red",
                    ),
                    Point(
                        "The 405 nm line needs about ten minutes to reach a stable output.",
                        color="light_blue",
                        level=1,
                    ),
                ],
                marks=[
                    Mark("rectangle", "red", (0.09, 0.15, 0.38, 0.26)),
                    Mark("ellipse", "light_blue", (0.60, 0.62, 0.16, 0.20)),
                ],
            ),
            Block(
                title="Choose and clean the objective",
                pictures=3,
                tint=BLUE,
                points=[
                    Point("Select the objective in software first, so the turret moves under control."),
                    Point(
                        "Clean the front lens with lens tissue and one drop of solvent, one pass.",
                        icon="caution",
                        color="red",
                    ),
                    Point(
                        "Never let solvent run down the barrel; it dissolves the cement inside.",
                        icon="caution",
                        color="red",
                        level=1,
                    ),
                    Point("Use the immersion medium printed on the objective.", color="green"),
                ],
                marks=[Mark("ellipse", "green", (0.55, 0.30, 0.22, 0.26))],
            ),
            Block(
                title="Mount the sample and find focus",
                pictures=2,
                tint=BLUE,
                points=[
                    Point("Coverslip down, clamped, then add immersion medium."),
                    Point("Find focus in widefield at low magnification first.", color="green"),
                    Point("Start at the lowest laser power that gives a signal.", icon="note"),
                ],
                marks=[Mark("arrow", "green", (0.24, 0.70, 0.26, -0.30))],
            ),
        ],
    ),
    GuideSpec(
        slug_hint="shutting-down-the-stellaris",
        title="Shutting down the Stellaris 5",
        category="Confocal",
        summary="The reverse order, and the two things people forget.",
        introduction="Leaving the system half-off is worse than leaving it on.",
        tags=["stellaris", "confocal", "shutdown"],
        minutes=(10, 15),
        blocks=[
            Block(
                title="Save and copy your data off",
                points=[
                    Point("Copy to the group share before you close the software."),
                    Point("Export the acquisition settings alongside the images.", icon="note"),
                ],
            ),
            Block(
                title="Clean the objective you used",
                pictures=1,
                tint=BLUE,
                points=[
                    Point("Lens tissue, one pass, no solvent unless it was an oil objective."),
                    Point(
                        "Leaving oil on a lens overnight is the single most common cause of "
                        "damage on this system.",
                        icon="caution",
                        color="red",
                    ),
                ],
            ),
            Block(
                title="Power down in reverse",
                pictures=1,
                tint=BLUE,
                points=[
                    Point("Lasers off, wait for the fan to stop, then PC, scanner, mains."),
                    Point(
                        "If the next booking is within an hour, leave it on and say so in the "
                        "logbook.",
                        icon="reminder",
                        color="orange",
                    ),
                ],
            ),
        ],
    ),
    GuideSpec(
        slug_hint="starting-a-session-on-the-sp8",
        title="Starting a session on the SP8",
        category="Confocal",
        summary="Similar to the Stellaris, with three differences that matter.",
        introduction="If you know the Stellaris, read only the points marked in red.",
        tags=["sp8", "confocal", "startup"],
        difficulty="moderate",
        minutes=(20, 30),
        blocks=[
            Block(
                title="Power up",
                pictures=2,
                tint=TEAL,
                points=[
                    Point("Mains, scanner, PC — the same order as the Stellaris."),
                    Point(
                        "The white-light laser has its own key, and it is not the same key.",
                        icon="caution",
                        color="red",
                    ),
                ],
                marks=[Mark("rectangle", "red", (0.10, 0.60, 0.24, 0.18))],
            ),
            Block(
                title="Set up the detectors",
                pictures=2,
                tint=TEAL,
                points=[
                    Point("HyD detectors are gated; check the gate before you blame the sample."),
                    Point("Do not exceed 1 MHz on a HyD.", icon="caution", color="red"),
                ],
            ),
        ],
    ),
    GuideSpec(
        slug_hint="tile-scans-on-the-thunder",
        title="Tile scans on the Thunder",
        category="Widefield",
        summary="Stitching a whole section without spending the afternoon on it.",
        introduction="Set the overlap before the tiles, not after.",
        tags=["thunder", "widefield", "tilescan"],
        difficulty="moderate",
        minutes=(30, 90),
        blocks=[
            Block(
                title="Define the region",
                pictures=2,
                tint=GREEN,
                points=[
                    Point("Mark the corners on the overview, not on the live view."),
                    Point("10% overlap is the usual starting point.", color="green"),
                ],
                marks=[Mark("rectangle", "green", (0.12, 0.18, 0.44, 0.30))],
            ),
            Block(
                title="Set focus points across the region",
                pictures=1,
                tint=GREEN,
                points=[
                    Point("Three points minimum, spread across the section."),
                    Point(
                        "A section that is not flat needs more, or the middle tiles go soft.",
                        icon="note",
                    ),
                ],
            ),
        ],
    ),
    GuideSpec(
        slug_hint="sted-alignment-check",
        title="STED alignment check",
        category="Superresolution",
        summary="The weekly bead check, and what to do when it fails.",
        introduction=(
            "This is a staff procedure. It is on the site so that it is written down "
            "and versioned, not because users run it."
        ),
        tags=["sted", "superresolution", "maintenance"],
        visibility="staff",
        difficulty="difficult",
        minutes=(45, 90),
        blocks=[
            Block(
                title="Mount the bead slide",
                pictures=1,
                tint=VIOLET,
                points=[
                    Point("Use the 80 nm gold beads, not the fluorescent ones."),
                    Point("The slide lives in the drawer under the console.", icon="note"),
                ],
            ),
            Block(
                title="Check the doughnut",
                pictures=2,
                tint=VIOLET,
                points=[
                    Point("Scan in reflection and look at the depletion profile."),
                    Point(
                        "If the centre is not dark, stop and log it. Do not re-align without "
                        "the service manual.",
                        icon="caution",
                        color="red",
                    ),
                ],
                marks=[Mark("ellipse", "violet", (0.40, 0.28, 0.22, 0.28))],
            ),
        ],
    ),
    GuideSpec(
        slug_hint="setting-up-the-incubation-chamber",
        title="Setting up the incubation chamber",
        category="Live-cell Imaging",
        summary="Temperature, CO₂ and humidity, in the order they stabilise.",
        introduction="Give the chamber an hour before the first time point. It is not optional.",
        tags=["live-cell", "incubation"],
        difficulty="moderate",
        minutes=(60, 90),
        blocks=[
            Block(
                title="Warm the stage first",
                pictures=2,
                tint=TEAL,
                points=[
                    Point("Stage and objective heater to 37 °C, an hour before you need them."),
                    Point(
                        "A cold objective touching a warm dish drifts for twenty minutes.",
                        icon="note",
                        color="light_blue",
                    ),
                ],
                marks=[Mark("rectangle", "light_blue", (0.10, 0.62, 0.26, 0.18))],
            ),
            Block(
                title="Set the gas mixer",
                pictures=1,
                tint=TEAL,
                points=[
                    Point("5% CO₂, and check the bottle pressure before a long run."),
                    Point(
                        "An empty bottle at 03:00 costs the whole experiment.",
                        icon="reminder",
                        color="orange",
                    ),
                ],
            ),
            Block(
                kind="info",
                title="If your cells look unhappy",
                points=[
                    Point("Nine times in ten it is evaporation, not phototoxicity."),
                    Point("Check the water reservoir before you lower the laser power.", icon="note"),
                ],
            ),
        ],
    ),
    GuideSpec(
        slug_hint="cleaning-the-objective-turret",
        title="Cleaning the objective turret",
        category="Confocal",
        summary="Draft — not finished, and deliberately left that way.",
        introduction="",
        tags=["maintenance"],
        publish=False,
        blocks=[
            Block(
                title="Remove each objective",
                points=[Point("Hold the barrel, not the front element.")],
            ),
        ],
    ),
]


# ------------------------------------------------------------------- the build


def find_category(categories: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    return next((c for c in categories if c["name"] == name), None)


def ensure_categories(api: Reticle) -> dict[str, dict[str, Any]]:
    """Create the sub-categories, and give every section a picture."""
    existing = api.categories()
    by_name = {c["name"]: c for c in existing}

    for name, parent_name, description, tint in CATEGORIES:
        parent = by_name.get(parent_name)
        if parent is None:
            raise SystemExit(f"No category named {parent_name!r} to hang {name!r} under.")
        if name in by_name:
            continue
        created = api.create_category(
            name=name,
            description=description,
            parentId=parent["id"],
        )
        by_name[name] = created
        print(f"  category  {name}")

    # A picture for every top-level section and every sub-category made here,
    # because browsing is meant to be visual and a wall of drawn placeholders
    # demonstrates the fallback rather than the design.
    wanted = {name: tint for name, _parent, _desc, tint in CATEGORIES}
    for top, tint in (
        ("Basics, Access and IT", AMBER),
        ("Light Microscopy", BLUE),
        ("Sample Preparation", GREEN),
    ):
        wanted.setdefault(top, tint)

    for name, tint in wanted.items():
        category = by_name.get(name)
        if category is None or category.get("heroMediaId"):
            continue
        media = api.upload(f"{name}.png", cover(tint), f"{name} at the centre")
        api.patch_category(category["id"], heroMediaId=media["id"])
        print(f"  cover     {name}")

    return by_name


def build_steps(api: Reticle, spec: GuideSpec) -> list[dict[str, Any]]:
    """Turn a spec's blocks into the step documents the API takes."""
    steps: list[dict[str, Any]] = []

    for index, block in enumerate(spec.blocks):
        media = []
        for shot in range(block.pictures):
            alt = f"{block.title} — view {shot + 1}"
            uploaded = api.upload(
                f"{spec.slug_hint}-{index}-{shot}.png",
                panel(block.tint, screen="wide" if shot % 2 == 0 else "narrow", dials=3 + shot),
                alt,
            )
            # Shapes go on the first picture, which is the one a reader sees
            # large — a mark on a thumbnail nobody opens is a mark nobody sees.
            uploaded["annotations"] = (
                [
                    {
                        "id": f"{uploaded['id']}-{n}",
                        "shape": mark.shape,
                        "color": mark.color,
                        "x": mark.box[0],
                        "y": mark.box[1],
                        "width": mark.box[2],
                        "height": mark.box[3],
                    }
                    for n, mark in enumerate(block.marks)
                ]
                if shot == 0
                else []
            )
            media.append(uploaded)

        steps.append(
            {
                "id": None,
                "kind": block.kind,
                "orderIndex": index,
                "title": block.title,
                "bullets": [
                    {
                        "id": None,
                        "text": point.text,
                        "color": point.color,
                        "icon": point.icon,
                        "level": point.level,
                    }
                    for point in block.points
                ],
                "media": media,
                "video": None,
            }
        )

    return steps


def ensure_guide(api: Reticle, spec: GuideSpec, categories: dict[str, dict[str, Any]]) -> dict[str, Any]:
    category = categories.get(spec.category)
    if category is None:
        raise SystemExit(f"No category named {spec.category!r} for {spec.title!r}.")

    # The plain listing, with no status filter: an author sees their drafts in
    # it as well as everything published, which is what "is this already here"
    # has to mean. Asking for `status=""` — which this did — filtered on a value
    # no guide can hold, came back empty, and wrote the whole corpus twice.
    existing = next(
        (g for g in api.guides() if g["slug"].startswith(spec.slug_hint)), None
    )
    if existing:
        print(f"  guide     {spec.title} (already there)")
        return api.guide(existing["id"])

    guide = api.create_guide(spec.title, category["id"])
    guide.update(
        {
            "summary": spec.summary,
            "introduction": spec.introduction,
            "tags": spec.tags,
            "isQuickLink": spec.quick_link,
            "visibility": spec.visibility,
            "difficulty": spec.difficulty,
            "timeRequiredMinMinutes": spec.minutes[0],
            "timeRequiredMaxMinutes": spec.minutes[1],
            "steps": build_steps(api, spec),
        }
    )
    guide = api.save_guide(guide)

    if spec.publish:
        guide = api.publish_guide(guide["id"])

    print(f"  guide     {spec.title}{'' if spec.publish else ' (draft)'}")
    return guide


# Grouped per instrument, which is how a facility's guides are actually looked
# for — somebody arrives knowing which microscope they are booked on, not which
# procedure they need. One list per instrument rather than one list of
# everything: the lists are tag-filtered, so a guide written next year appears
# under its instrument without anybody editing this page.
LANDING_BODY = """\
Point-scanning confocals live here. The Stellaris 5 is the general-purpose
system; the SP8 has the white-light laser and the gated detectors.

Both need instrument-specific training before you can book them.

## Stellaris 5

```guidelist
tags: stellaris
```

## SP8

```guidelist
tags: sp8
```

## Everything confocal

```guidelist
tags: confocal
```
"""

ARTICLE_BODY = """\
Most people arrive knowing what they want to see rather than which instrument
sees it. This is the short version.

## Fixed samples, whole sections

Use widefield. A tile scan on the Thunder covers a slide in the time a confocal
takes to cover a corner of one.

## Fixed samples, thin optical sections

Use a confocal. Start with the Stellaris.

```guide
starting-a-session-on-the-stellaris
```

## Living cells over hours

Widefield if the signal allows it — it is gentler. Book the incubation chamber
with the instrument, not afterwards.

## Below the diffraction limit

Talk to us first. Superresolution is not a setting you switch on, and the sample
preparation decides whether it will work at all.
"""


def ensure_page(
    api: Reticle,
    *,
    title: str,
    slug_hint: str,
    body: str,
    summary: str,
    category_id: str | None,
    is_landing: bool,
) -> dict[str, Any]:
    existing = next((p for p in api.pages() if p["slug"].startswith(slug_hint)), None)
    if existing:
        # Rewritten rather than skipped. A page is text, so rerunning costs one
        # request and keeps the corpus matching this file — which is the whole
        # use of the script while the wording is still being worked out.
        page = api.page(existing["id"])
        page.update({"body": body, "summary": summary})
        page = api.save_page(page)
        if page["status"] != "published":
            page = api.publish_page(page["id"])
        print(f"  page      {title} (rewritten)")
        return page

    page = api.create_page(title=title, categoryId=category_id, isLanding=is_landing)
    page.update({"body": body, "summary": summary})
    page = api.save_page(page)
    page = api.publish_page(page["id"])
    print(f"  page      {title}")
    return page


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()

    api = Reticle(args.base_url, args.email, args.password)
    print(f"Signed in as {api.me.get('displayName', args.email)}")

    categories = ensure_categories(api)

    for spec in GUIDES:
        ensure_guide(api, spec, categories)

    confocal = categories.get("Confocal")
    if confocal:
        ensure_page(
            api,
            title="Confocal",
            slug_hint="confocal",
            body=LANDING_BODY,
            summary="The point-scanning systems, and what each is for.",
            category_id=confocal["id"],
            is_landing=True,
        )

    ensure_page(
        api,
        title="Which microscope should I use?",
        slug_hint="which-microscope",
        body=ARTICLE_BODY,
        summary="A short answer to the question everybody arrives with.",
        category_id=None,
        is_landing=False,
    )

    guides = api.guides()
    print(f"\n{len(guides)} guides now visible to this account.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
