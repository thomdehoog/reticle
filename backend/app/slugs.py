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

NON_SLUG = re.compile(r"[^a-z0-9]+")

TRANSLITERATIONS = str.maketrans({"ß": "ss", "æ": "ae", "œ": "oe", "ø": "o", "đ": "d", "ł": "l"})
"""Letters that decomposition alone throws away.

``unicodedata.normalize("NFKD", …)`` splits *ä* into *a* plus a combining
diaeresis, and dropping the diaeresis leaves the *a* — which is what makes
"Präparation" slug as "praparation". These six letters have no such
decomposition, so without this line "Größe" would become "gre".

The importer's tag slugs use the same table, and the browser's tag input has its
own copy in ``frontend/src/components/editor/TagInput.tsx``. All three must
agree, or a tag typed by an author and the same tag arriving from the migration
become two tags that look identical on screen. ``test_unicode.py`` pins the
exact strings.
"""

MAX_SLUG_LENGTH = 200
"""What fits the ``slug`` columns, which are 200 or 240 characters wide.

Tag slugs are cut shorter — see ``importer.mapping.MAX_TAG_LENGTH`` — because a
tag is a chip in a row of chips rather than a URL somebody reads.
"""


def slugify(value: str, fallback: str = "untitled") -> str:
    lowered = value.strip().lower().translate(TRANSLITERATIONS)
    decomposed = unicodedata.normalize("NFKD", lowered)
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    slug = NON_SLUG.sub("-", ascii_only).strip("-")
    return slug[:MAX_SLUG_LENGTH].rstrip("-") or fallback


def unique_slug(value: str, exists: Callable[[str], bool], fallback: str = "untitled") -> str:
    """Append the smallest numeric suffix that clears the collision test."""
    base = slugify(value, fallback)
    if not exists(base):
        return base
    suffix = 2
    while exists(f"{base}-{suffix}"):
        suffix += 1
    return f"{base}-{suffix}"
