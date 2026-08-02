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
from dataclasses import dataclass, field
from typing import Any

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
        "featured_guide",
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
    steps: list[MappedStep]


@dataclass
class MappedPage:
    source_id: str
    title: str
    summary: str
    body: str
    category_name: str | None
    is_landing: bool


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
    text = strip_markup(text) if "<" in str(text) else str(text).strip()

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


def _coerce_fraction(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        text = value.strip().rstrip("%")
        try:
            number = float(text)
        except ValueError:
            return None
        if value.strip().endswith("%"):
            number /= 100.0
    else:
        return None
    # Percentages arrive both as 0..1 and as 0..100 depending on the field.
    if number > 1.5:
        number /= 100.0
    return number


def map_annotations(raw: Any, where: str) -> tuple[list[MappedAnnotation], list[Unmapped]]:
    """Shapes drawn over a step image, in the colour of the bullet they belong to.

    This is the part of a ZMB guide that a naive migration loses without anyone
    noticing: the picture arrives intact and the red rectangle around the button
    the text is talking about does not, so the sentence "click the highlighted
    control" now points at nothing.

    Coordinates are normalised to fractions of the image so they survive being
    rendered at any size, which is also how Reticle stores them natively.
    """
    if raw in (None, "", [], {}):
        return [], []

    items: list[Any]
    if isinstance(raw, dict):
        items = raw.get("shapes") or raw.get("annotations") or raw.get("markup") or []
        if not isinstance(items, list):
            return [], [Unmapped("markup", repr(raw)[:200], where)]
    elif isinstance(raw, list):
        items = raw
    else:
        return [], [Unmapped("markup", repr(raw)[:200], where)]

    mapped: list[MappedAnnotation] = []
    problems: list[Unmapped] = []

    for item in items:
        if not isinstance(item, dict):
            problems.append(Unmapped("markup_shape", repr(item)[:120], where))
            continue

        raw_shape = str(item.get("shape") or item.get("type") or "").strip().lower()
        shape = ANNOTATION_SHAPES.get(raw_shape)
        if shape is None:
            problems.append(Unmapped("markup_shape", raw_shape or repr(item)[:120], where))
            continue

        raw_colour = str(item.get("color") or item.get("colour") or "red").strip().lower()
        colour = BULLET_COLOURS.get(raw_colour)
        if colour is None and raw_colour in BULLET_FLAGS:
            colour = BULLET_FLAGS[raw_colour][0]
        if colour is None:
            problems.append(Unmapped("markup_colour", raw_colour, where))
            continue

        coordinates = [
            _coerce_fraction(item.get(key) if item.get(key) is not None else item.get(alias))
            for key, alias in (("x", "x1"), ("y", "y1"), ("width", "w"), ("height", "h"))
        ]
        if any(value is None for value in coordinates):
            # Some shapes are stored as two corners rather than a corner and a size.
            x1, y1 = _coerce_fraction(item.get("x1")), _coerce_fraction(item.get("y1"))
            x2, y2 = _coerce_fraction(item.get("x2")), _coerce_fraction(item.get("y2"))
            if None in (x1, y1, x2, y2):
                problems.append(Unmapped("markup_geometry", repr(item)[:120], where))
                continue
            coordinates = [x1, y1, x2 - x1, y2 - y1]

        x, y, width, height = coordinates
        mapped.append(
            MappedAnnotation(shape=shape, color=colour, x=x, y=y, width=width, height=height)
        )

    return mapped, problems


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
            annotations, shape_problems = map_annotations(
                data.get("markup") or data.get("annotations"), where
            )
            problems.extend(shape_problems)
            images.append(
                MappedImage(
                    source_id=str(data.get("id") or data.get("imageid") or url),
                    url=url,
                    alt=strip_markup(str(data.get("alt") or data.get("caption") or "")),
                    annotations=annotations,
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

    tags, tag_problems = map_tags(payload.get("tags"), where)
    problems.extend(tag_problems)

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
            introduction=strip_markup(
                payload.get("introduction_raw")
                or payload.get("introduction_rendered")
                or payload.get("introduction")
            ),
            conclusion=strip_markup(
                payload.get("conclusion_raw")
                or payload.get("conclusion_rendered")
                or payload.get("conclusion")
            ),
            is_public=bool(payload.get("public", True)),
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
        ),
        problems,
    )


_WIKI_HEADING = re.compile(r"^(={2,6})\s*(.+?)\s*\1\s*$", re.MULTILINE)
_WIKI_BOLD = re.compile(r"'''(.+?)'''", re.DOTALL)
_WIKI_ITALIC = re.compile(r"''(.+?)''", re.DOTALL)
_WIKI_LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
_WIKI_LIST = re.compile(r"^\*\s+", re.MULTILINE)


def wiki_to_markdown(source: str) -> str:
    """Convert the vendor's wiki syntax into Markdown.

    Only the constructs the corpus actually uses are translated — headings,
    bold, italic, links and bullet lists. Anything else is left as literal text
    rather than half-converted, so a reviewer comparing the two sides sees the
    untranslated marker and can decide, instead of finding a silently mangled
    paragraph.

    A guide embed — ``[guide|1234|Align the laser]`` — is one of the things left
    alone, and that is the deliberate choice rather than an omission. Reticle's
    own embed is :func:`guide_list_block`, which selects guides **by tag**; the
    vendor's selects **one guide by its numeric id**. Nothing maps an id to a
    tag, so the closest automatic translation would emit a ``guidelist`` keyed
    on "1234", which renders as an empty list — a reader would see nothing at
    all where the source showed a guide, and the reconciliation counts would not
    notice. Left as text, the marker is visible on the page and whoever reviews
    the migrated category pages can replace it with the embed they meant.
    ``docs/MIGRATION.md`` says the same.
    """
    if not source:
        return ""

    text = source.replace("\r\n", "\n")

    if "<" in text and ">" in text:
        # A rendered payload rather than a source one: reduce it to text first,
        # because vendor HTML must never survive the crossing.
        if re.search(r"<(p|div|ul|ol|h[1-6]|table)\b", text, re.IGNORECASE):
            text = strip_markup(text)

    text = _WIKI_HEADING.sub(lambda m: f"{'#' * len(m.group(1))} {m.group(2)}", text)
    text = _WIKI_BOLD.sub(r"**\1**", text)
    text = _WIKI_ITALIC.sub(r"*\1*", text)
    text = _WIKI_LINK.sub(lambda m: _wiki_link(m.group(1), m.group(2)), text)
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
