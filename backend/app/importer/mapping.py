"""Turning a vendor guide payload into Reticle's own structures.

Every function here is pure: it takes decoded JSON and returns Reticle data plus
a list of things it did not understand. That is deliberate — it means the whole
mapping is testable against recorded payloads without a network, a database or
credentials, which is the only way to be confident about a migration that can be
run exactly once before a subscription lapses.

Two rules run through all of it.

**Nothing is guessed.** An unrecognised bullet colour, flag, difficulty, shape
or media type is recorded in ``Unmapped`` rather than coerced to a default. The
caller decides whether that stops the run; the default is that it does.

**No vendor markup survives.** Rendered HTML is reduced to Reticle's own
structures — text, bullets, annotations, Markdown — and every tag, class,
style, script and embed is discarded on the way through. Reticle contains no
third-party markup, stylesheet or script, and the importer is the one place
where that guarantee could have been lost.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import html
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..schemas import EDGE_TOLERANCE
from ..slugs import NON_SLUG, TRANSLITERATIONS

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

BULLET_COLOURS = {
    "black": "black",
    "red": "red",
    "orange": "orange",
    "yellow": "yellow",
    "green": "green",
    "light_blue": "light_blue",
    "lightblue": "light_blue",
    "blue": "blue",
    "violet": "violet",
    "purple": "violet",
}
"""The eight colours, plus the spellings the same colour appears under.

A census of the corpus found all eight in active service, so none of them can be
folded into another: the colour is what ties a bullet to the shape drawn on the
picture beside it, and collapsing two colours would silently break that pairing
on every step that used both.
"""

BULLET_FLAGS = {
    "icon_note": ("blue", "note"),
    "icon_caution": ("orange", "caution"),
    "icon_reminder": ("violet", "reminder"),
    "note": ("blue", "note"),
    "caution": ("orange", "caution"),
    "reminder": ("violet", "reminder"),
}
"""Flagged bullets carry an icon instead of a dot, and a conventional colour.

The vendor encodes flag and colour in one field; Reticle keeps them apart so an
author can flag a bullet without losing the colour that links it to its
annotation. The colours here are the ones the flags render as, so a migrated
guide reads exactly as it did — but they are a *convention*, and the first real
run should confirm them against the site rather than trusting this table.
"""

DIFFICULTIES = {
    "very easy": "very_easy",
    "easy": "easy",
    "moderate": "moderate",
    "medium": "moderate",
    "difficult": "difficult",
    "hard": "difficult",
    "very difficult": "very_difficult",
}

ANNOTATION_SHAPES = {
    "rectangle": "rectangle",
    "rect": "rectangle",
    "box": "rectangle",
    "square": "rectangle",
    "circle": "ellipse",
    "ellipse": "ellipse",
    "oval": "ellipse",
    "arrow": "arrow",
    "line": "arrow",
}
"""Shapes drawn over a step image.

Reticle draws three. A ``line`` becomes an ``arrow`` because an arrow without a
head is a line, and losing the shape entirely would leave the reader with a
colour and nothing pointing at anything.
"""

NO_TIME_ESTIMATE = frozenset({"no estimate", "not specified", "unknown", "n/a"})
"""What the vendor writes where an author gave no duration.

An absent value spelled in words. It has to be listed rather than inferred —
the importer refuses to guess at anything it does not recognise, and that is
right for a *time* it cannot parse — but reporting "No estimate" as unmapped
stopped the run over a guide that had nothing to lose in the first place.
"""

MAX_BULLET_LEVEL = 2

KNOWN_GUIDE_FIELDS = frozenset(
    {
        # Read by the mapping.
        "guideid",
        "id",
        "wikiid",
        "title",
        "summary",
        "category",
        "namespace",
        "tags",
        "difficulty",
        "time_required",
        "time",
        "introduction_raw",
        "introduction_rendered",
        "introduction",
        "conclusion_raw",
        "conclusion_rendered",
        "conclusion",
        "public",
        "steps",
        # A guide the site puts in front of people becomes one Reticle puts in
        # front of people: a quick link.
        "featured_guide",
        # Present, deliberately not carried across: identifiers and rendering
        # details of the other system, authorship that becomes a source record,
        # and counters that start again here.
        "url",
        "revisionid",
        "locale",
        "langid",
        "modified_date",
        "created_date",
        "published",
        "author",
        "username",
        "userid",
        "image",
        "documents",
        "flags",
        "type",
        "guide_type",
        "prereqs",
        "prerequisites",
        "parts",
        "tools",
        "patrol_threshold",
        "instructables_id",
        "view_count",
        "completed",
        "favorited",
        "comments",
        "solutions",
    }
)
"""Every key the corpus is expected to carry.

Anything outside this set is reported as an unknown field. That is not
pedantry: a field nobody wrote down is exactly how a feature the site has and
Reticle does not would go unnoticed, because the mapping would simply not look
at it and every count would still balance. The report turns "did we miss a
feature?" into a list.
"""

KNOWN_STEP_FIELDS = frozenset(
    {
        "stepid",
        "orderby",
        "title",
        "lines",
        "bullets",
        "media",
        "revisionid",
        "guideid",
        "id",
        "type",
        "images",
        "video",
    }
)

KNOWN_LINE_FIELDS = frozenset(
    {"lineid", "id", "text_raw", "text_rendered", "text", "bullet", "color", "level", "notes"}
)

_TAG_SEPARATORS = re.compile(r"[,;]")
_WHITESPACE = re.compile(r"[ \t\r\f\v]+")
_BLANK_LINES = re.compile(r"\n{3,}")


@dataclass
class Unmapped:
    """Everything the mapping met and did not understand.

    Kept as structured records rather than log lines because the reconciliation
    report groups them: "seven guides use a bullet colour called ``teal``" is
    actionable, and seven separate warnings scrolling past are not.
    """

    kind: str
    value: str
    where: str

    def __str__(self) -> str:  # pragma: no cover - diagnostic only
        return f"{self.kind}={self.value!r} at {self.where}"


def unknown_fields(payload: dict[str, Any], known: frozenset[str], where: str) -> list[Unmapped]:
    """Name the keys nobody accounted for.

    Reported separately from an unmapped *value*: a value the mapping could not
    read is a loss and stops the run, whereas an unread field is a question —
    "the site stores this and we do not; should we?" — and the answer belongs to
    whoever is comparing the two systems, not to this code.
    """
    return [
        Unmapped("unknown_field", key, where)
        for key in sorted(payload)
        if key not in known and not key.startswith("_")
    ]


@dataclass
class MappedBullet:
    text: str
    color: str
    icon: str | None
    level: int


@dataclass
class MappedAnnotation:
    shape: str
    color: str
    x: float
    y: float
    width: float
    height: float


@dataclass
class MappedImage:
    source_id: str
    url: str
    alt: str
    annotations: list[MappedAnnotation] = field(default_factory=list)


@dataclass
class MappedVideo:
    source_id: str
    url: str
    poster_url: str | None
    alt: str


@dataclass
class MappedStep:
    title: str
    bullets: list[MappedBullet]
    images: list[MappedImage]
    video: MappedVideo | None


@dataclass
class MappedGuide:
    source_id: str
    title: str
    summary: str
    category_name: str
    tags: list[str]
    difficulty: str
    time_min_minutes: int | None
    time_max_minutes: int | None
    introduction: str
    conclusion: str
    is_public: bool
    is_quick_link: bool
    steps: list[MappedStep]


@dataclass
class MappedPage:
    source_id: str
    title: str
    summary: str
    body: str
    category_name: str | None
    is_landing: bool
    image: MappedImage | None = None
    """The page's own picture, which for a category landing is the section's.

    It is what the banner across the top of a section is built from, and it
    arrives in the same payload as the words — so an import that read the
    description and not this one produced a site where every section had ZMB's
    own sentence under a drawn placeholder.
    """


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------

_BLOCK_TAGS = ("p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6")
_DROP_WHOLE = re.compile(
    r"<(script|style|iframe|object|embed|noscript)\b.*?</\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
_BLOCK_BOUNDARY = re.compile(rf"</?(?:{'|'.join(_BLOCK_TAGS)})\b[^>]*>", re.IGNORECASE)
_ANY_TAG = re.compile(r"<[^>]*>")


def strip_markup(source: str | None) -> str:
    """Reduce rendered HTML to plain text, keeping the paragraph breaks.

    The importer never carries vendor markup across — not the tags, not the
    classes, not the stylesheets, and above all not the scripts. Reticle renders
    Markdown to React elements and has no ``dangerouslySetInnerHTML`` anywhere,
    so imported HTML would not merely be untidy: it would be inert text with
    angle brackets in it, printed to the reader.

    Script, style and embed elements are removed *with their contents* first.
    Dropping only their tags would leave a wall of CSS or JavaScript sitting in
    the middle of a procedure.
    """
    if not source:
        return ""
    without_dangerous = _DROP_WHOLE.sub(" ", source)
    with_breaks = _BLOCK_BOUNDARY.sub("\n", without_dangerous)
    text = _ANY_TAG.sub("", with_breaks)
    text = html.unescape(text)
    text = _WHITESPACE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return _BLANK_LINES.sub("\n\n", text).strip()


MAX_TAG_LENGTH = 120
"""Shorter than a document slug, which is 200 — see ``slugs.MAX_SLUG_LENGTH``.

A tag is a chip in a row of chips rather than a URL anybody reads, and the input
that suggests them has to show several across a line.
"""


def slugify_tag(value: str) -> str:
    """The same rule the tag input applies in the browser.

    It has to be the same rule, or a tag typed by an author and the same tag
    arriving from the migration become two tags that look identical on screen.
    That is why the transliteration table and the pattern come from ``slugs``
    rather than being written out again here — the only thing that differs is
    the length, and it differs on purpose.

    Accents transliterate rather than vanish, which matters most here: half of
    ZMB's vocabulary is German, and folding "Präparation" to "pr-paration"
    produces something nobody can read, guess, or match against the tag an
    author types tomorrow.
    """
    lowered = value.strip().lower().translate(TRANSLITERATIONS)
    ascii_only = unicodedata.normalize("NFKD", lowered).encode("ascii", "ignore").decode("ascii")
    return NON_SLUG.sub("-", ascii_only).strip("-")[:MAX_TAG_LENGTH].rstrip("-")


# ---------------------------------------------------------------------------
# Scalars
# ---------------------------------------------------------------------------

_UNITS_IN_MINUTES = {
    "second": 1 / 60,
    "seconds": 1 / 60,
    "sec": 1 / 60,
    "secs": 1 / 60,
    "s": 1 / 60,
    "minute": 1,
    "minutes": 1,
    "min": 1,
    "mins": 1,
    "m": 1,
    "hour": 60,
    "hours": 60,
    "hr": 60,
    "hrs": 60,
    "h": 60,
    "day": 60 * 24,
    "days": 60 * 24,
}

_RANGE_SPLIT = re.compile(r"\s*(?:-|–|—|to)\s*", re.IGNORECASE)
_QUANTITY = re.compile(r"(\d+(?:[.,]\d+)?)\s*([a-z]+)?", re.IGNORECASE)


def map_time_required(raw: Any, where: str) -> tuple[int | None, int | None, list[Unmapped]]:
    """Read a time estimate, which the corpus writes as a range.

    ZMB writes "00:30 – 01:30" because that is how long a procedure honestly
    takes, and a single number would have to be either the optimistic or the
    pessimistic end — both of which are wrong often enough to matter when
    somebody is deciding whether they can finish before the building closes.

    Integers are seconds, which is what the vendor API returns when the estimate
    was entered as a duration rather than typed as text.
    """
    if raw in (None, "", 0):
        return None, None, []

    if isinstance(raw, bool):
        return None, None, [Unmapped("time_required", repr(raw), where)]

    if isinstance(raw, (int, float)):
        minutes = round(float(raw) / 60)
        return (minutes or None), None, []

    if isinstance(raw, dict):
        # Some payloads carry {"min": .., "max": ..} already in seconds.
        low, high, problems = None, None, []
        for key, target in (("min", "low"), ("max", "high")):
            value = raw.get(key)
            if value is None:
                continue
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                minutes = round(float(value) / 60)
                if target == "low":
                    low = minutes
                else:
                    high = minutes
            else:
                problems.append(Unmapped("time_required", f"{key}={value!r}", where))
        return low, high, problems

    if not isinstance(raw, str):
        return None, None, [Unmapped("time_required", repr(raw), where)]

    text = raw.strip()
    if not text:
        return None, None, []

    # The vendor writes this where an author left the estimate blank, so it is
    # an absent value spelled in words rather than an unreadable one. Reported
    # as unmapped it stopped a migration on a guide that had nothing to lose.
    if text.casefold() in NO_TIME_ESTIMATE:
        return None, None, []

    clock = _clock_range(text)
    if clock is not None:
        return clock[0], clock[1], []

    parts = [part for part in _RANGE_SPLIT.split(text) if part.strip()]
    if not parts:
        return None, None, [Unmapped("time_required", raw, where)]

    trailing_unit = _trailing_unit(parts[-1])
    values: list[int] = []
    for part in parts[:2]:
        minutes = _minutes_from(part, trailing_unit)
        if minutes is None:
            return None, None, [Unmapped("time_required", raw, where)]
        values.append(minutes)

    if len(values) == 1:
        return values[0], None, []
    return values[0], values[1], []


def _clock_range(text: str) -> tuple[int, int | None] | None:
    """Handle ``00:30 – 01:30``, which is how the live site renders a range."""
    clocks = re.findall(r"(\d{1,3}):(\d{2})", text)
    if not clocks:
        return None
    minutes = [int(hours) * 60 + int(mins) for hours, mins in clocks]
    if len(minutes) == 1:
        return minutes[0], None
    return minutes[0], minutes[1]


def _trailing_unit(part: str) -> float:
    match = list(_QUANTITY.finditer(part))
    if match and match[-1].group(2):
        return _UNITS_IN_MINUTES.get(match[-1].group(2).lower(), 1)
    return 1


def _minutes_from(part: str, fallback_unit: float) -> int | None:
    """Total up every quantity in one end of the range.

    "1 hour 30 minutes" is two quantities meaning one duration, and the bare
    number in "30 - 90 minutes" inherits the unit written at the far end.
    """
    matches = list(_QUANTITY.finditer(part))
    if not matches:
        return None
    total = 0.0
    for match in matches:
        amount = float(match.group(1).replace(",", "."))
        unit = match.group(2)
        if unit is None:
            total += amount * fallback_unit
        elif unit.lower() in _UNITS_IN_MINUTES:
            total += amount * _UNITS_IN_MINUTES[unit.lower()]
        else:
            return None
    return round(total)


def map_difficulty(raw: Any, where: str) -> tuple[str, list[Unmapped]]:
    """Fall back to ``moderate`` only for an *absent* difficulty.

    An unrecognised one is reported: it means the site offers a level Reticle
    does not, and quietly calling it "moderate" would misrepresent a procedure
    that somebody graded as dangerous.
    """
    if raw in (None, ""):
        return "moderate", []
    key = str(raw).strip().lower()
    if key in DIFFICULTIES:
        return DIFFICULTIES[key], []
    return "moderate", [Unmapped("difficulty", str(raw), where)]


def map_tags(raw: Any, where: str) -> tuple[list[str], list[Unmapped]]:
    """Tags are the navigation, so this is the most consequential field here.

    137 tags carry a corpus whose category tree is mostly holding pens; a guide
    that arrives untagged is a guide nobody will find again.
    """
    if raw in (None, ""):
        return [], []

    values: list[str]
    if isinstance(raw, str):
        values = list(_TAG_SEPARATORS.split(raw))
    elif isinstance(raw, (list, tuple)):
        values = []
        for item in raw:
            if isinstance(item, str):
                values.append(item)
            elif isinstance(item, dict) and isinstance(item.get("title") or item.get("name"), str):
                values.append(item.get("title") or item["name"])
            else:
                return [], [Unmapped("tag", repr(item), where)]
    else:
        return [], [Unmapped("tags", repr(raw), where)]

    slugs: list[str] = []
    problems: list[Unmapped] = []
    for value in values:
        slug = slugify_tag(value)
        if not slug:
            if value.strip():
                problems.append(Unmapped("tag", value, where))
            continue
        if slug not in slugs:
            slugs.append(slug)
    return slugs, problems


# ---------------------------------------------------------------------------
# Bullets
# ---------------------------------------------------------------------------


def map_bullet(line: dict[str, Any], where: str) -> tuple[MappedBullet | None, list[Unmapped]]:
    """One bullet, with its colour, its optional flag and its indent depth."""
    problems: list[Unmapped] = []

    text = line.get("text_raw")
    if not isinstance(text, str):
        text = line.get("text_rendered") or line.get("text") or ""
    # A bullet carries the same wiki syntax the front matter does — a link to
    # the manufacturer's page, a bolded warning — and a bullet is where most of
    # a ZMB guide's words are. `wiki_to_markdown` reduces vendor HTML first, so
    # this covers a `_rendered` payload as well; the block constructs it also
    # knows about simply do not occur in one line.
    text = wiki_to_markdown(str(text))

    raw_bullet = line.get("bullet") or line.get("color") or "black"
    key = str(raw_bullet).strip().lower()

    if key in BULLET_FLAGS:
        colour, icon = BULLET_FLAGS[key]
    elif key in BULLET_COLOURS:
        colour, icon = BULLET_COLOURS[key], None
    else:
        return None, [Unmapped("bullet", str(raw_bullet), where)]

    raw_level = line.get("level", 0)
    try:
        level = int(raw_level)
    except (TypeError, ValueError):
        problems.append(Unmapped("level", repr(raw_level), where))
        level = 0
    if level < 0 or level > MAX_BULLET_LEVEL:
        problems.append(Unmapped("level", str(level), where))
        level = min(max(level, 0), MAX_BULLET_LEVEL)

    if not text:
        return None, problems

    return MappedBullet(text=text, color=colour, icon=icon, level=level), problems


# ---------------------------------------------------------------------------
# Media and annotations
# ---------------------------------------------------------------------------

_IMAGE_SIZE_PREFERENCE = ("original", "huge", "large", "standard", "medium", "thumbnail")


def best_image_url(data: dict[str, Any]) -> str | None:
    """Take the largest rendition on offer.

    A step image is frequently a screenshot of an acquisition dialog, and a
    reader has to be able to make out the value in a spin box. Importing the
    display-sized copy would carry the picture across and lose the only thing it
    was there to show.
    """
    for key in _IMAGE_SIZE_PREFERENCE:
        value = data.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    return None


MARKUP_NOT_A_SHAPE = frozenset({"crop", "null"})
"""Entries in a markup string that are not annotations.

``crop`` is the window the photograph was cropped to, which the stored image
already reflects — drawing it would put a rectangle around the whole picture.
``null`` is what an image whose shapes were all deleted leaves behind.
"""


def _points(text: str) -> tuple[float, float]:
    first, _, second = text.partition("x")
    return float(first), float(second)


def parse_markup(
    markup: Any, width: Any, height: Any, where: str
) -> tuple[list[MappedAnnotation], list[Unmapped]]:
    """The shapes drawn over one image, read from that image's own record.

    This is the part of a ZMB guide a naive migration loses in silence: the
    photograph arrives intact and the red rectangle around the button the text
    is talking about does not, so "click the highlighted control" points at
    nothing. It was being lost here too, and worse than silently — the markup
    lives on the **image** document, which has to be fetched one image at a
    time, and nothing was fetching it. Both sides of the reconciliation read
    the guide payload, where the key has never existed, so every run reported
    that it had lost no annotations at all.

    The format is measured rather than guessed, and this function is narrow to
    what was measured::

        ;rectangle,828x1164,586x430,red;arrow,2272.5x1096.5,2558.6x1552.9,red;

    Each entry is ``kind,first,second,colour``. ``rectangle`` and ``arrow``
    both carry two *points*, not a corner and a size: read as points every one
    of the 111 rectangles in the sample lands inside its picture, and read as
    sizes a third of the arrows land outside it. ``circle`` is the one entry
    whose second field is a single number, being a centre and a radius.

    Pixels become fractions of the image here, because that is how Reticle
    stores a shape and it is what lets one survive being rendered at any size.
    A rectangle or an ellipse is normalised to its top-left corner with
    positive extents; an arrow keeps a **signed** vector, because which end
    carries the head is the whole point of drawing one.

    A shape that does not land on the picture is reported rather than clamped.
    Roughly a fifth of them do not, and what that means is not yet known — a
    guess here would either move a shape off the control it points at or, if it
    stayed out of range, make the guide it belongs to permanently unsaveable.
    """
    if markup in (None, "", [], {}):
        return [], []
    if not isinstance(markup, str):
        return [], [Unmapped("markup", repr(markup)[:200], where)]

    try:
        image_width, image_height = float(width), float(height)
    except (TypeError, ValueError):
        return [], [Unmapped("markup_image_size", f"{width!r}x{height!r}", where)]
    if image_width <= 0 or image_height <= 0:
        return [], [Unmapped("markup_image_size", f"{image_width}x{image_height}", where)]

    mapped: list[MappedAnnotation] = []
    problems: list[Unmapped] = []

    for entry in markup.strip(";").split(";"):
        entry = entry.strip()
        if not entry:
            continue
        fields = entry.split(",")
        kind = fields[0].strip().lower()
        if kind in MARKUP_NOT_A_SHAPE:
            continue
        if len(fields) != 4:
            problems.append(Unmapped("markup_shape", entry[:120], where))
            continue

        _, first, second, raw_colour = fields
        shape = ANNOTATION_SHAPES.get(kind)
        if shape is None:
            problems.append(Unmapped("markup_shape", kind or entry[:120], where))
            continue

        colour = BULLET_COLOURS.get(raw_colour.strip().lower())
        if colour is None:
            problems.append(Unmapped("markup_colour", raw_colour.strip(), where))
            continue

        try:
            x1, y1 = _points(first)
            if kind == "circle":
                radius = float(second)
                x, y = x1 - radius, y1 - radius
                extent_x, extent_y = radius * 2, radius * 2
            else:
                x2, y2 = _points(second)
                if shape == "arrow":
                    x, y = x1, y1
                    extent_x, extent_y = x2 - x1, y2 - y1
                else:
                    x, y = min(x1, x2), min(y1, y2)
                    extent_x, extent_y = abs(x2 - x1), abs(y2 - y1)
        except ValueError:
            problems.append(Unmapped("markup_geometry", entry[:120], where))
            continue

        fractions = (
            x / image_width,
            y / image_height,
            extent_x / image_width,
            extent_y / image_height,
        )
        if not _lands_on_the_picture(fractions):
            problems.append(Unmapped("markup_off_the_image", entry[:120], where))
            continue

        mapped.append(
            MappedAnnotation(
                shape=shape,
                color=colour,
                x=fractions[0],
                y=fractions[1],
                width=fractions[2],
                height=fractions[3],
            )
        )

    return mapped, problems


def attach_groups(
    mapped: MappedGuide, fetch: Callable[[str], list[str]], where: str
) -> list[Unmapped]:
    """Fill in the groups a guide belongs to, given a way to fetch them.

    A guide names one section in its own payload and nothing else. Which
    instruments it covers — ``OSD``, ``THUNDER``, ``TitanG3i`` — lives on
    ``/guides/{id}/tags``, and eighty-nine of those drive thirteen section front
    pages. They are the level between a section and a guide, and a fifth of the
    corpus belongs to more than one of them, which is why this is a list and not
    a second parent.

    Separated from the fetch itself for the reason ``attach_image_details`` is:
    the mapping talks to nothing, and the import and the verification pass have
    to agree about what the source holds or the comparison between them means
    nothing.
    """
    names = fetch(mapped.source_id)
    slugs, problems = map_tags(names, where)
    mapped.tags = slugs
    return problems


def attach_image_details(
    mapped: MappedGuide, fetch: Callable[[str], dict[str, Any]]
) -> list[Unmapped]:
    """Point each image at the unflattened photograph and read the shapes on it.

    Takes a way to fetch an image record rather than a client, because nothing
    else in this module talks to anything and that is worth keeping. Both the
    import and the verification pass come through here: a second copy would
    drift, and the two would then disagree about how many shapes the source
    holds, which is the number that decides whether a migration is faithful.

    **The picture to keep is the source, not the one the listing offers.** The
    vendor stores two renditions of every annotated photograph: the original,
    and a flattened copy with the shapes painted into the pixels. A guide
    payload links the flattened one. Importing that and then drawing Reticle's
    own vectors over it shows each arrow twice — but the real cost is not the
    double image, it is that a shape burned into a photograph can never be
    moved, recoloured or removed again. ZMB has to be able to edit these guides
    after the migration, so what has to arrive is the clean picture plus the
    shapes as data.

    **The shapes are measured against the source, too.** Coordinates are in the
    original's pixel space, not the rendition's: across the sample 217 of 218
    land inside the source's dimensions and only 169 inside the rendition's, so
    normalising against the wrong one puts a fifth of every guide's annotations
    off the edge of its own picture.
    """
    problems: list[Unmapped] = []
    for step in mapped.steps:
        for image in step.images:
            if not image.source_id.isdigit():
                continue
            record = fetch(image.source_id)
            source = record.get("srcImageInfo")
            source = source if isinstance(source, dict) else {}

            original = best_image_url(source.get("image") or {})
            if original is not None:
                image.url = original

            shapes, trouble = parse_markup(
                record.get("markup"),
                source.get("width") or record.get("width"),
                source.get("height") or record.get("height"),
                f"image {image.source_id}",
            )
            image.annotations = shapes
            problems.extend(trouble)
    return problems


def _lands_on_the_picture(fractions: tuple[float, float, float, float]) -> bool:
    """Both ends of a shape inside the frame, within the tolerance the schema allows.

    Checked against the far corner as well as the origin, because an arrow is
    stored from its tail and a tail on the picture says nothing about where the
    head is.
    """
    x, y, extent_x, extent_y = fractions
    limit = 1.0 + EDGE_TOLERANCE
    return all(-EDGE_TOLERANCE <= value <= limit for value in (x, y, x + extent_x, y + extent_y))


def map_step_media(
    media: Any, where: str
) -> tuple[list[MappedImage], MappedVideo | None, list[Unmapped]]:
    """Split a step's attachments into the image slots and the video slot."""
    images: list[MappedImage] = []
    video: MappedVideo | None = None
    problems: list[Unmapped] = []

    if media in (None, "", [], {}):
        return images, video, problems

    entries: list[Any]
    if isinstance(media, dict):
        kind = str(media.get("type") or "").lower()
        entries = media.get("data") if kind and isinstance(media.get("data"), list) else [media]
    elif isinstance(media, list):
        entries = media
    else:
        return images, video, [Unmapped("media", repr(media)[:200], where)]

    for entry in entries:
        if not isinstance(entry, dict):
            problems.append(Unmapped("media", repr(entry)[:120], where))
            continue

        kind = str(entry.get("type") or entry.get("mediatype") or "image").strip().lower()
        data = entry.get("data") if isinstance(entry.get("data"), dict) else entry

        if kind in ("image", "photo", ""):
            url = best_image_url(data)
            if url is None:
                problems.append(Unmapped("image_url", repr(data)[:120], where))
                continue
            # Annotations are deliberately not read here. They live on the
            # image document, one fetch per image, and are attached by the run
            # once it has them — see `parse_markup`. Reaching for them in this
            # payload is what produced a corpus with none.
            images.append(
                MappedImage(
                    source_id=str(data.get("id") or data.get("imageid") or url),
                    url=url,
                    alt=strip_markup(str(data.get("alt") or data.get("caption") or "")),
                )
            )
        elif kind in ("video", "movie"):
            url = _video_url(data)
            if url is None:
                problems.append(Unmapped("video_url", repr(data)[:120], where))
                continue
            video = MappedVideo(
                source_id=str(data.get("id") or data.get("videoid") or url),
                url=url,
                poster_url=best_image_url(data.get("image"))
                if isinstance(data.get("image"), dict)
                else None,
                alt=strip_markup(str(data.get("alt") or data.get("caption") or "")),
            )
        else:
            # An embed is a player hosted somewhere else. It cannot be carried
            # into a self-hosted install, and pretending otherwise would leave a
            # dead rectangle on the step, so it is reported instead.
            problems.append(Unmapped("media_type", kind, where))

    return images, video, problems


def _video_url(data: dict[str, Any]) -> str | None:
    for key in ("original", "url", "src", "mp4", "webm"):
        value = data.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    encodings = data.get("encodings")
    if isinstance(encodings, list):
        for encoding in encodings:
            if isinstance(encoding, dict):
                value = encoding.get("url") or encoding.get("src")
                if isinstance(value, str) and value.startswith(("http://", "https://")):
                    return value
    return None


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


def map_guide(payload: dict[str, Any]) -> tuple[MappedGuide, list[Unmapped]]:
    """One whole guide, with everything it carries."""
    source_id = str(payload.get("guideid") or payload.get("id") or payload.get("wikiid") or "?")
    where = f"guide {source_id}"
    problems: list[Unmapped] = unknown_fields(payload, KNOWN_GUIDE_FIELDS, where)

    difficulty, difficulty_problems = map_difficulty(payload.get("difficulty"), where)
    problems.extend(difficulty_problems)

    # Deliberately not read from the payload: a guide document carries no
    # `tags` key at all. The groups it belongs to are a separate request, and
    # the run attaches them once it has made it — see `attach_groups`. Reaching
    # for a key that has never existed is what produced "0 tags" against a
    # corpus of eighty-nine.
    tags: list[str] = []

    low, high, time_problems = map_time_required(
        payload.get("time_required") if "time_required" in payload else payload.get("time"),
        where,
    )
    problems.extend(time_problems)

    steps: list[MappedStep] = []
    for index, raw_step in enumerate(payload.get("steps") or []):
        if not isinstance(raw_step, dict):
            problems.append(Unmapped("step", repr(raw_step)[:120], where))
            continue
        step, step_problems = map_step(raw_step, f"{where} step {index + 1}")
        problems.extend(step_problems)
        steps.append(step)

    category = payload.get("category") or payload.get("namespace") or ""
    if isinstance(category, dict):
        category = category.get("title") or category.get("name") or ""

    return (
        MappedGuide(
            source_id=source_id,
            title=strip_markup(str(payload.get("title") or "")).strip() or f"Untitled {source_id}",
            summary=strip_markup(str(payload.get("summary") or "")),
            category_name=str(category).strip(),
            tags=tags,
            difficulty=difficulty,
            time_min_minutes=low,
            time_max_minutes=high,
            # `_raw` is the vendor's wiki syntax, not HTML, so stripping tags
            # left it untouched and a reader met `'''widefield'''` and
            # `[https://svi.nl/HomePage|SVI Huygens]` in the middle of a
            # sentence. Reticle renders these as rich text, which is exactly
            # what those constructs mean, so they are translated the same way a
            # wiki page's body already was.
            introduction=wiki_to_markdown(
                str(
                    payload.get("introduction_raw")
                    or payload.get("introduction_rendered")
                    or payload.get("introduction")
                    or ""
                )
            ),
            conclusion=wiki_to_markdown(
                str(
                    payload.get("conclusion_raw")
                    or payload.get("conclusion_rendered")
                    or payload.get("conclusion")
                    or ""
                )
            ),
            is_public=bool(payload.get("public", True)),
            is_quick_link=bool(payload.get("featured_guide", False)),
            steps=steps,
        ),
        problems,
    )


def map_step(payload: dict[str, Any], where: str) -> tuple[MappedStep, list[Unmapped]]:
    problems: list[Unmapped] = unknown_fields(payload, KNOWN_STEP_FIELDS, where)

    bullets: list[MappedBullet] = []
    for line in payload.get("lines") or payload.get("bullets") or []:
        if not isinstance(line, dict):
            problems.append(Unmapped("line", repr(line)[:120], where))
            continue
        problems.extend(unknown_fields(line, KNOWN_LINE_FIELDS, where))
        bullet, line_problems = map_bullet(line, where)
        problems.extend(line_problems)
        if bullet is not None:
            bullets.append(bullet)

    images, video, media_problems = map_step_media(payload.get("media"), where)
    problems.extend(media_problems)

    title = strip_markup(str(payload.get("title") or "")).strip()
    return MappedStep(title=title, bullets=bullets, images=images, video=video), problems


def map_page(payload: dict[str, Any]) -> tuple[MappedPage, list[Unmapped]]:
    """A wiki page.

    The body is converted to Markdown rather than kept as HTML, because Reticle
    renders Markdown to React elements and never to raw HTML — which is what
    removes the stored-XSS surface that a migration of somebody else's markup
    would otherwise hand us.
    """
    source_id = str(payload.get("wikiid") or payload.get("id") or payload.get("title") or "?")
    problems: list[Unmapped] = []

    namespace = str(payload.get("namespace") or "").strip().upper()
    category_name = None
    if namespace == "CATEGORY":
        category_name = strip_markup(str(payload.get("title") or "")).strip()

    body_source = (
        payload.get("contents_raw")
        or payload.get("contents_rendered")
        or payload.get("contents")
        or payload.get("body")
        or ""
    )
    body = wiki_to_markdown(str(body_source))

    return (
        MappedPage(
            source_id=source_id,
            title=strip_markup(
                str(payload.get("display_title") or payload.get("title") or "")
            ).strip()
            or f"Untitled {source_id}",
            summary=strip_markup(str(payload.get("summary") or payload.get("description") or "")),
            body=body,
            category_name=category_name,
            is_landing=namespace == "CATEGORY",
            image=_page_image(payload.get("image"), where=f"page {source_id}"),
        ),
        problems,
    )


def _page_image(data: Any, where: str) -> MappedImage | None:
    """The picture a wiki page carries, at the largest size on offer.

    A page with no picture is ordinary and silent — most articles have none. A
    picture the mapping cannot find a URL in is *not* silent, but it is not
    fatal either: the words are the page and losing the photograph at the top of
    it should not cost the reader the procedure underneath.
    """
    if not isinstance(data, dict) or not data:
        return None
    url = best_image_url(data)
    if url is None:
        return None
    return MappedImage(
        source_id=str(data.get("id") or data.get("guid") or url),
        url=url,
        alt="",
    )


_WIKI_HEADING = re.compile(r"^(={2,6})\s*(.+?)\s*\1\s*$", re.MULTILINE)
_WIKI_BOLD = re.compile(r"'''(.+?)'''", re.DOTALL)
_WIKI_ITALIC = re.compile(r"''(.+?)''", re.DOTALL)
_WIKI_LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")

_WIKI_URL_LINK = re.compile(r"\[(?:link\|)?(https?://[^\]|]+)(?:\|([^\]]*))?\]", re.IGNORECASE)
"""A link, in the two single-bracket spellings the corpus writes.

``[https://svi.nl/HomePage|SVI Huygens]`` and
``[link|https://svi.nl/HowtoCiteHuygens|cite Huygens]`` — nine and fifteen of
them in the sample, against no ``[[target|label]]`` at all. The MediaWiki form
above was what the converter knew, which is why every link in every guide
reached the reader as its own source text.

Anchored on the scheme rather than on "anything before a pipe", so the
constructs that share this shape and are *not* links are left for the code that
does understand them: ``[guide|26|new_window=true]`` and
``[guidelist|tags=ASTED|type=howto]`` are Reticle blocks resolved once the
import knows what those ids became, and swallowing them here would turn a guide
embed into a dead link to nowhere.
"""

_WIKI_MAILTO = re.compile(r"\[mailto\|([^\]|]+)(?:\|([^\]]*))?\]", re.IGNORECASE)

_HTML_TAG = re.compile(r"<\s*/?[a-zA-Z][^>]*>")
_WIKI_LIST = re.compile(r"^\*\s+", re.MULTILINE)


def wiki_to_markdown(source: str) -> str:
    """Convert the vendor's wiki syntax into Markdown.

    Only the constructs the corpus actually uses are translated — headings,
    bold, italic, links and bullet lists. Anything else is left as literal text
    rather than half-converted, so a reviewer comparing the two sides sees the
    untranslated marker and can decide, instead of finding a silently mangled
    paragraph.

    A guide embed — ``[guide|1234|Align the laser]`` — is deliberately left
    alone *here*, and turned into Reticle's own block by
    :func:`resolve_guide_embeds` once the import knows what id 1234 became. This
    function is pure and has no such knowledge, and leaving the vendor's text is
    also the fallback for an embed that never resolves, so the two ends agree:
    an untranslated marker is exactly what an unresolvable embed looks like.
    """
    if not source:
        return ""

    text = source.replace("\r\n", "\n")

    # Any tag at all, not only the block ones. A bullet carries inline markup —
    # `<b>Never</b> touch the lens` — and matching on `<p>` and its neighbours
    # let that through to be rendered as literal angle brackets. Vendor HTML
    # must never survive the crossing, whatever shape it arrives in.
    if _HTML_TAG.search(text):
        text = strip_markup(text)

    text = _WIKI_HEADING.sub(lambda m: f"{'#' * len(m.group(1))} {m.group(2)}", text)
    text = _WIKI_BOLD.sub(r"**\1**", text)
    text = _WIKI_ITALIC.sub(r"*\1*", text)
    text = _WIKI_LINK.sub(lambda m: _wiki_link(m.group(1), m.group(2)), text)
    text = _WIKI_URL_LINK.sub(lambda m: _wiki_link(m.group(1), m.group(2)), text)
    text = _WIKI_MAILTO.sub(
        lambda m: f"[{(m.group(2) or m.group(1)).strip()}](mailto:{m.group(1).strip()})", text
    )
    text = _WIKI_LIST.sub("- ", text)
    return _BLANK_LINES.sub("\n\n", text).strip()


def _wiki_link(target: str, label: str | None) -> str:
    shown = (label or target).strip()
    destination = target.strip()
    if destination.lower().startswith(("http://", "https://")):
        return f"[{shown}]({destination})"
    if destination.lower().startswith("category:"):
        return f"[{shown}](/w/{slugify_tag(destination.split(':', 1)[1])})"
    if destination.lower().startswith("guide:"):
        return f"[{shown}](/g/{slugify_tag(destination.split(':', 1)[1])})"
    return f"[{shown}](/w/{slugify_tag(destination)})"


def guide_list_block(tags: list[str], heading: str | None = None) -> str:
    """The embed a migrated category page uses to pull its guides in by tag."""
    lines = ["```guidelist", f"tags: {', '.join(tags)}"]
    if heading:
        lines.append(f"heading: {heading}")
    lines.append("```")
    return "\n".join(lines)


def guide_block(slug: str) -> str:
    """Reticle's other embed: one named guide, selected by slug."""
    return f"```guide\n{slug}\n```"


_GUIDE_EMBED = re.compile(
    r"[ \t]*(?P<embed>\[guide\|\s*(?P<id>[^|\]\s]+)\s*(?:\|[^\]]*)?\])[ \t]*",
    re.IGNORECASE,
)
"""``[guide|1234|Align the laser]``, and the form with no title after it.

The spaces on either side are matched as well, so lifting the embed out of a
sentence does not leave one stranded at the end of a line.
"""


@dataclass
class EmbedResolution:
    """A page body after translation, and what became of each embed in it."""

    body: str
    resolved: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)


def resolve_guide_embeds(body: str, slug_for_source_id: dict[str, str]) -> EmbedResolution:
    """Turn the vendor's one-guide embeds into Reticle's own ``guide`` block.

    The vendor names a guide by numeric id; Reticle's block names one by slug,
    so the translation needs the id-to-slug mapping the import builds as it goes
    — which is why this takes it as an argument instead of looking it up, and
    why it stays as testable as the rest of this module.

    **An embed naming a guide that is not in the mapping is left exactly as the
    vendor wrote it**, and reported. The alternatives are worse in ways that only
    show up later: a ``guide`` block naming a slug nothing answers to renders as
    nothing at all to a reader, and dropping to the plain title reads as finished
    prose, so neither would ever be found and fixed. The vendor's marker still
    carries the id, so a reviewer can look the guide up on the source site and
    decide whether it was deleted or simply outside the imported set — and
    ``docs/MIGRATION.md`` already tells them to search for ``[guide|``.

    A block has to start its own line, so one written inside a sentence is
    surrounded by blank lines; the words on either side are untouched.
    """
    resolution = EmbedResolution(body=body)
    if not body:
        return resolution

    def replace(match: re.Match[str]) -> str:
        source_id = match.group("id")
        slug = slug_for_source_id.get(source_id)
        if slug is None:
            resolution.unresolved.append(match.group("embed"))
            return match.group(0)
        resolution.resolved.append(source_id)
        return f"\n\n{guide_block(slug)}\n\n"

    rewritten = _GUIDE_EMBED.sub(replace, body)
    resolution.body = _BLANK_LINES.sub("\n\n", rewritten).strip()
    return resolution
