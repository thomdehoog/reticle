"""Readable, stable URL slugs.

ZMB documentation is written in German as often as in English, so accented
characters have to transliterate rather than vanish: dropping the umlaut from
"Präparation" would give "prparation", which nobody can read or guess.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable

_NON_SLUG = re.compile(r"[^a-z0-9]+")
_TRANSLITERATIONS = str.maketrans({"ß": "ss", "æ": "ae", "œ": "oe", "ø": "o", "đ": "d", "ł": "l"})


def slugify(value: str, fallback: str = "untitled") -> str:
    lowered = value.strip().lower().translate(_TRANSLITERATIONS)
    decomposed = unicodedata.normalize("NFKD", lowered)
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    slug = _NON_SLUG.sub("-", ascii_only).strip("-")
    return slug[:200] or fallback


def unique_slug(value: str, exists: Callable[[str], bool], fallback: str = "untitled") -> str:
    """Append the smallest numeric suffix that clears the collision test."""
    base = slugify(value, fallback)
    if not exists(base):
        return base
    suffix = 2
    while exists(f"{base}-{suffix}"):
        suffix += 1
    return f"{base}-{suffix}"
