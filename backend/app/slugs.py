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

_TRANSLITERATIONS = str.maketrans(
    {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
        "æ": "ae",
        "œ": "oe",
        "ø": "o",
        "å": "a",
        "đ": "d",
        "ð": "d",
        "þ": "th",
        "ł": "l",
    }
)
"""Letters whose readable ASCII form is not what stripping the accent gives.

German is the case that matters here: "Präparation" is spelt "Praeparation"
when umlauts are unavailable, and a German reader guesses that URL; "praparation"
is a different-looking word. Everything not listed falls through to NFKD, which
is right for é, ç, ñ and the like. ``frontend/src/domain/slug.ts`` carries the
same table, and ``tests/data/tag_slug_cases.json`` is checked by both suites.
"""

_COMBINING_MARKS = re.compile("[\u0300-\u036f]")
"""Spelt as a range, not as "category Mn", so the JavaScript mirror can use the
identical expression instead of depending on two Unicode databases agreeing."""


def fold(value: str) -> str:
    """Lower-case and reduce accented Latin letters to plain ones.

    NFC comes first because macOS hands over file names and pasted text with
    the umlaut as a separate combining character, which the table would not
    recognise; NFKD afterwards splits whatever is left into base letter plus
    marks, and the marks are dropped.
    """
    composed = unicodedata.normalize("NFC", value.strip().lower())
    decomposed = unicodedata.normalize("NFKD", composed.translate(_TRANSLITERATIONS))
    return _COMBINING_MARKS.sub("", decomposed)


def slugify(value: str, fallback: str = "untitled") -> str:
    ascii_only = fold(value).encode("ascii", "ignore").decode("ascii")
    slug = _NON_SLUG.sub("-", ascii_only).strip("-")
    return slug[:200].strip("-") or fallback


def unique_slug(value: str, exists: Callable[[str], bool], fallback: str = "untitled") -> str:
    """Append the smallest numeric suffix that clears the collision test."""
    base = slugify(value, fallback)
    if not exists(base):
        return base
    suffix = 2
    while exists(f"{base}-{suffix}"):
        suffix += 1
    return f"{base}-{suffix}"


def tag_slug(value: str) -> str:
    """The identity of a tag: folded to plain lower-case letters and hyphenated.

    This is deliberately not :func:`slugify`, which truncates and falls back to
    a placeholder. The tag input in the frontend applies exactly this rule
    before it sends anything, and the two have to agree character for character
    or a tag typed in the editor would file the guide under a different tag
    from the one the wiki page asks for. Accents fold rather than turn into
    hyphens, so "Präparation" is ``praeparation`` and not ``pr-paration``; the
    author's own spelling survives as the tag's display name. An empty result
    means the text had no Latin letter or digit in it, which the caller refuses.

    A slug is a fixed point of the rule, so tags stored before folding was
    introduced (``pr-paration``) keep working when an editor sends them back.
    """
    return _NON_SLUG.sub("-", fold(value)).strip("-")
