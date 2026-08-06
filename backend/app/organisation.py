"""The facility's own description of itself, and where it comes from.

One row, and the environment is what fills it the first time. Both halves of
that matter:

- **A facility can change its own front page.** The name, the sentence under it
  and the picture behind it used to be `RETICLE_ORGANISATION_*`, read once at
  start-up, so changing the tagline meant editing a file on the server and
  restarting the process. The person who knows what the tagline should say is
  not the person with a shell on the box.
- **A fresh installation still comes up saying something.** The environment is
  not ignored; it is the default. A server deployed with those variables set
  shows exactly what it showed before, and the first save is what detaches it.

This module is the only place that reads the row, so "if it is missing, make it
from the settings" is written once rather than at each caller.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from .models import ORGANISATION_ROW, Organisation
from .settings import Settings


def load(db: Session, settings: Settings) -> Organisation:
    """The facility, seeded from the environment if nobody has saved it yet.

    Committed on creation rather than left pending, so the row exists for the
    next request even if this one goes on to fail. Two requests racing to create
    it both write the same primary key, so the loser gets an integrity error and
    is retried by reading — which is why this re-reads rather than trusting its
    own insert.
    """
    existing = db.get(Organisation, ORGANISATION_ROW)
    if existing is not None:
        return existing

    db.add(
        Organisation(
            id=ORGANISATION_ROW,
            name=settings.organisation_name,
            short_name=settings.organisation_short_name,
            url=settings.organisation_url,
            tagline=settings.organisation_tagline or "",
            hero_media_id=settings.organisation_hero_media_id,
        )
    )
    try:
        db.commit()
    except Exception:
        db.rollback()

    found = db.get(Organisation, ORGANISATION_ROW)
    if found is None:  # pragma: no cover - only reachable if the insert truly failed
        raise RuntimeError("The organisation row could not be created.")
    return found
