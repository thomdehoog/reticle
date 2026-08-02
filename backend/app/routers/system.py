"""The three endpoints that answer questions about the server itself.

None of them is about a guide, and all three are reachable without a session,
which is why they live together rather than beside the content routes: the set
of things anybody on the network can ask is small enough to read in one file and
argue about as a whole. ``main.PUBLIC_PATHS`` is the list, and a test asserts
that nothing else has quietly joined it.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text as sqlalchemy_text

from ..db import SessionLocal
from ..schemas import media_url
from ..settings import get_settings

router = APIRouter(tags=["system"])


@router.get("/api/health")
async def health() -> dict[str, str]:
    """Liveness: is this process running?

    Deliberately touches nothing. A liveness probe that checks the database
    turns a database blip into a restart loop — every instance is killed for a
    fault none of them can fix by restarting, and the restarts add load to the
    thing that was already struggling.
    """
    return {"status": "ok"}


@router.get("/api/ready")
async def ready(request: Request) -> JSONResponse:
    """Readiness: should this process be sent traffic?

    A different question from liveness, and the reason for a second endpoint.
    This one *does* check the database, because an instance that cannot reach it
    should be taken out of the load balancer rather than restarted, and it
    reports not-ready during startup migrations so no request arrives before the
    schema is current.

    Returns 503 when not ready. The status code is the part orchestrators read;
    the body is for whoever is looking at it by hand.
    """
    if not getattr(request.app.state, "ready", False):
        return JSONResponse(status_code=503, content={"status": "starting"})
    try:
        with SessionLocal() as session:
            session.execute(sqlalchemy_text("SELECT 1"))
    except Exception:
        logging.getLogger("reticle").exception("readiness check failed")
        return JSONResponse(status_code=503, content={"status": "database_unavailable"})
    return JSONResponse(status_code=200, content={"status": "ready"})


@router.get("/api/config")
async def configuration() -> dict[str, object]:
    """Whose instance this is — needed before anyone has signed in.

    Reachable without a session because the login screen has to say which
    facility it belongs to, and because it discloses nothing: the name of the
    institute running a server is already in the hostname pointing at it.
    Everything else here stays behind the login.
    """
    settings = get_settings()
    return {
        "organisation": {
            "name": settings.organisation_name,
            "shortName": settings.organisation_short_name,
            "url": settings.organisation_url,
            "tagline": settings.organisation_tagline,
            "heroImageUrl": (
                media_url(settings.organisation_hero_media_id)
                if settings.organisation_hero_media_id
                else None
            ),
        }
    }
