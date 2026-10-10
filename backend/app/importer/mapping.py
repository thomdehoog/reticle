"""Vendor values to Reticle values: the small, fixed tables of the import.

Everything here is a pure function of one vendor field, kept apart from the
loader so that each table can be read, argued with and tested on its own. Where
a value is not one the vendor is known to produce, the function says so through
its second return value rather than guessing quietly, and the loader turns that
into a line of the import report.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

DIFFICULTY = {
    "very easy": "very_easy",
    "easy": "easy",
    "moderate": "moderate",
    "difficult": "difficult",
    "very difficult": "very_difficult",
}
"""The vendor's five-point scale is Reticle's five-point scale, word for word.

``Very easy``, ``Easy`` and ``Moderate`` were seen on the live site; the two
harder grades are the vendor's standard values and are assumed.
"""

DEFAULT_DIFFICULTY = "moderate"


def difficulty(value: Any) -> tuple[str, bool]:
    key = " ".join(str(value or "").replace("_", " ").replace("-", " ").lower().split())
    if key in DIFFICULTY:
        return DIFFICULTY[key], True
    return DEFAULT_DIFFICULTY, False


MAX_MINUTES = 100_000


def minutes(seconds: Any) -> int | None:
    """Seconds to whole minutes; ``0`` is the vendor's "not set".

    Anything above zero is at least one minute: a 20-second step rounded to
    nothing would read as "no time given", which is a different statement.
    """
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return min(max(1, round(value / 60)), MAX_MINUTES)


def time_range(minimum: Any, maximum: Any) -> tuple[int | None, int | None]:
    """The vendor's min/max seconds as Reticle's ordered range in minutes."""
    low, high = minutes(minimum), minutes(maximum)
    if low is not None and high is not None and low > high:
        low, high = high, low
    return low, high


COLOR_NAMES = {
    "black": "black",
    "red": "red",
    "orange": "orange",
    "yellow": "yellow",
    "green": "green",
    "lightblue": "light_blue",
    "blue": "blue",
    "violet": "violet",
    "purple": "violet",
    "pink": "violet",
}
"""Colour names as the vendor spells them, compared without case, ``_`` or ``-``.

Bullets say ``light_blue`` and image markers say ``lightBlue``; both land on
the same key. ``blue`` and ``violet`` are standard vendor values that were not
seen on the live site.
"""

VENDOR_PALETTE = {
    "black": (0x11, 0x16, 0x1A),
    "red": (0xC1, 0x28, 0x0B),
    "orange": (0xFF, 0x90, 0x24),
    "yellow": (0xF3, 0xE0, 0x0E),
    "green": (0x16, 0xDC, 0x81),
    "light_blue": (0x15, 0xA1, 0xD6),
    "blue": (0x23, 0x43, 0xE8),
    "violet": (0xDC, 0x54, 0xB7),
}
"""Reference colours for matching a hex value to the nearest Reticle colour.

Black, red, orange, green and light blue are the ``bullet_color`` values the
site returned; yellow, blue and violet are the vendor's standard palette.
"""

HEX_COLOR = re.compile(r"^#?([0-9a-f]{3}|[0-9a-f]{6})$", re.IGNORECASE)


def nearest_color(hex_value: Any) -> str | None:
    match = HEX_COLOR.match(str(hex_value or "").strip())
    if match is None:
        return None
    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(character * 2 for character in digits)
    rgb = tuple(int(digits[index : index + 2], 16) for index in (0, 2, 4))
    return min(VENDOR_PALETTE, key=lambda name: sum((a - b) ** 2 for a, b in zip(rgb, VENDOR_PALETTE[name])))


def color(value: Any) -> str | None:
    """A colour given by name or as a hex value, or ``None`` when it is neither."""
    key = re.sub(r"[^a-z]", "", str(value or "").lower())
    if key in COLOR_NAMES:
        return COLOR_NAMES[key]
    return nearest_color(value)


ICONS = {"icon_note": "note", "icon_caution": "caution", "icon_reminder": "reminder"}
"""``icon_note`` and ``icon_caution`` were seen live; ``icon_reminder`` is assumed."""

ICON_BULLET_COLOR = "black"
"""An icon bullet has no colour of its own on the vendor side.

Reticle stores both, but draws a flagged bullet by its kind — "CAUTION" reads as
a caution whatever colour it carries — so the neutral colour is the honest one.
"""


def bullet(line: dict[str, Any]) -> tuple[str, str | None, bool]:
    """A vendor line's ``bullet`` as Reticle's colour and icon.

    The third value is ``False`` when the vendor value was not recognised and a
    fallback was used: first the colour of the line's ``bullet_style``, which is
    how a site-defined custom bullet would arrive, then plain black.
    """
    value = str(line.get("bullet") or "").strip().lower()
    if value in ICONS:
        return ICON_BULLET_COLOR, ICONS[value], True
    key = re.sub(r"[^a-z]", "", value)
    if key in COLOR_NAMES:
        return COLOR_NAMES[key], None, True
    style = line.get("bullet_style")
    fallback = nearest_color(style.get("bullet_color")) if isinstance(style, dict) else None
    return fallback or "black", None, False


def level(value: Any) -> tuple[int, bool]:
    """Indent level held to Reticle's 0–2; the flag says whether it already was."""
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        return 0, False
    clamped = min(max(number, 0), 2)
    return clamped, clamped == number


def instant(epoch_seconds: Any) -> datetime | None:
    """A UNIX timestamp as an aware UTC instant; ``0`` and junk are "not given"."""
    try:
        value = float(epoch_seconds)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


HIDDEN_CATEGORY = re.compile(r"\bhid+en\b", re.IGNORECASE)
"""Matches the holding categories, including the site's own misspelling.

The facility names them "... - hidden", "... - hidden guides", "hidden - ..."
and, once, "Image processing - hiden".
"""


def is_hidden_category(*names: str | None) -> bool:
    return any(HIDDEN_CATEGORY.search(name) for name in names if name)


def clip(value: str, limit: int) -> tuple[str, bool]:
    """Hold text to a field's limit; the flag says whether anything was cut."""
    if len(value) <= limit:
        return value, False
    return value[: limit - 1].rstrip() + "…", True
