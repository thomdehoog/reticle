"""Editing the facility's own front page.

Reading it is ``/api/config``, which is public and has to be: the login screen
says whose server it is before anybody has signed in. Writing it is here, and it
is an administrator's job — the name across the top of the front page is the
whole institute's, and one person changing it changes it for everyone.

Only three things are writable, and they are the three a facility would want to
change: the name, the sentence under it, and the picture behind it. The short
name and the URL stay in the environment for now; they are set once at
deployment and appear in places a form would have to explain.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from .. import audit, errors, organisation
from ..auth import AdminUser, DbDep, client_address
from ..models import Media
from ..schemas import FacilityOut, FacilityPatchIn, facility_out
from ..settings import get_settings

router = APIRouter(prefix="/api/facility", tags=["facility"])


@router.get("", response_model=FacilityOut)
def read_facility(db: DbDep, user: AdminUser) -> FacilityOut:
    """What the form starts with.

    Separate from ``/api/config`` even though the two overlap, because they
    answer different questions: the config is what a reader's browser needs to
    draw the page, and this is the record an administrator is about to edit. The
    config hands out a URL for the picture; this hands out its identifier, which
    is what a save has to send back.
    """
    return facility_out(organisation.load(db, get_settings()))


@router.patch("", response_model=FacilityOut)
def patch_facility(
    payload: FacilityPatchIn, request: Request, db: DbDep, user: AdminUser
) -> FacilityOut:
    facility = organisation.load(db, get_settings())
    changed = payload.model_fields_set

    if "name" in changed and payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise errors.validation_failed("A facility needs a name.")
        facility.name = name

    if "tagline" in changed and payload.tagline is not None:
        facility.tagline = payload.tagline.strip()

    if "hero_media_id" in changed:
        if payload.hero_media_id is not None and db.get(Media, payload.hero_media_id) is None:
            raise errors.validation_failed("That picture does not exist.")
        facility.hero_media_id = payload.hero_media_id

    audit.record(
        db,
        action="facility.update",
        entity_type="facility",
        entity_id=facility.id,
        actor=user,
        ip_address=client_address(request),
        detail={"fields": sorted(changed)},
    )
    db.commit()
    return facility_out(facility)
