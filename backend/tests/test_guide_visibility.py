"""A finished guide that a viewer must never see, on every route that could show it.

``visibility`` is orthogonal to ``status``: a staff guide drafts, publishes and
archives like any other and is simply never served to a viewer. The whole of it
is enforcement, so this file is one test per route that can return a guide
rather than one test for the idea — a rule proved on the listing tells you
nothing about search, and search is where it was forgotten first.

The last two tests are the sweep, in the style of ``test_hardening``. The
failure mode this is really written against is not any of the routes below: it
is the route somebody adds next year. So the guide-bearing routes are discovered
by walking the response models, measured against a list written by hand, and
every viewer-reachable one is called with a staff guide in the database and
required not to mention it.
"""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute
from pydantic import BaseModel
from sqlalchemy import select

from app.main import _all_routes
from app.models import Guide
from app.schemas import GuideOut, GuideSummaryOut

from .conftest import create_guide, document_from, step


@pytest.fixture()
def staff_guide(author, category) -> dict:
    """A published, tagged, quick-linked staff guide — every route's problem."""
    created = create_guide(author, category.id, "Escorting an Auditor Through the Facility")
    saved = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(
            created,
            summary="Internal procedure for a site inspection.",
            tags=["internal"],
            visibility="staff",
            isQuickLink=True,
            steps=[step("Meet them at reception")],
        ),
    )
    assert saved.status_code == 200, saved.text
    published = author.post(f"/api/guides/{created['id']}/publish")
    assert published.status_code == 200, published.text
    return published.json()


@pytest.fixture()
def open_guide(author, category) -> dict:
    """A published guide for everyone, carrying the same tag and category.

    Present in every test so that a route returning nothing at all cannot be
    mistaken for a route that filtered correctly.
    """
    created = create_guide(author, category.id, "Booking the Confocal")
    author.put(
        f"/api/guides/{created['id']}",
        json=document_from(created, tags=["internal"], isQuickLink=True, steps=[step("Book it")]),
    )
    published = author.post(f"/api/guides/{created['id']}/publish")
    assert published.status_code == 200, published.text
    return published.json()


def titles(response) -> list[str]:
    return [entry["title"] for entry in response.json()]


# --- the default ----------------------------------------------------------


def test_a_guide_is_readable_by_everyone_unless_somebody_says_otherwise(author, category):
    guide = create_guide(author, category.id)

    assert guide["visibility"] == "everyone"


def test_visibility_and_status_are_independent(author, category, db_session):
    """A staff guide is drafted, published and archived like any other. If
    marking one staff had touched its status, "internal" would once again mean
    "unfinished" and the whole distinction would be back where it started."""
    created = create_guide(author, category.id)
    author.put(f"/api/guides/{created['id']}", json=document_from(created, visibility="staff"))

    assert author.get(f"/api/guides/{created['id']}").json()["status"] == "draft"

    author.post(f"/api/guides/{created['id']}/publish")
    published = author.get(f"/api/guides/{created['id']}").json()
    assert (published["status"], published["visibility"]) == ("published", "staff")

    author.post(f"/api/guides/{created['id']}/unpublish")
    assert author.get(f"/api/guides/{created['id']}").json()["visibility"] == "staff"

    assert (
        db_session.scalars(select(Guide).where(Guide.id == created["id"])).one().status == "draft"
    )


def test_a_visibility_the_vocabulary_does_not_hold_is_refused(author, category):
    created = create_guide(author, category.id)

    response = author.put(
        f"/api/guides/{created['id']}", json=document_from(created, visibility="everybody")
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


# --- one test per route ----------------------------------------------------


def test_the_listing_does_not_show_a_viewer_a_staff_guide(viewer, staff_guide, open_guide):
    assert titles(viewer.get("/api/guides")) == ["Booking the Confocal"]


def test_the_tag_listing_does_not_show_a_viewer_a_staff_guide(viewer, staff_guide, open_guide):
    """The route ZMB navigates by: a guide is reached through its tags far more
    often than through the category it sits in."""
    assert titles(viewer.get("/api/guides", params={"tags": "internal"})) == [
        "Booking the Confocal"
    ]


def test_the_category_listing_does_not_show_a_viewer_a_staff_guide(
    viewer, staff_guide, open_guide, category
):
    response = viewer.get("/api/guides", params={"categoryId": category.id})

    assert titles(response) == ["Booking the Confocal"]


def test_the_free_text_filter_on_the_listing_does_not_reach_a_staff_guide(viewer, staff_guide):
    assert viewer.get("/api/guides", params={"q": "Auditor"}).json() == []


def test_the_author_filter_on_the_listing_does_not_reach_a_staff_guide(viewer, staff_guide):
    author_id = staff_guide["author"]["id"]

    assert viewer.get("/api/guides", params={"authorId": author_id}).json() == []


def test_the_quick_link_listing_does_not_show_a_viewer_a_staff_guide(
    viewer, staff_guide, open_guide
):
    """Quick links are rendered as picture-and-text blocks on the front page,
    which is the most public surface in the application."""
    assert titles(viewer.get("/api/guides", params={"quickLink": "true"})) == [
        "Booking the Confocal"
    ]


def test_a_status_filter_does_not_get_a_viewer_past_the_visibility_rule(viewer, staff_guide):
    """``?status=published`` replaces the status clause; it must not replace
    this one."""
    assert viewer.get("/api/guides", params={"status": "published"}).json() == []


def test_the_detail_endpoint_answers_404_for_a_viewer_by_slug_and_by_id(viewer, staff_guide):
    """404 rather than 403, so the existence of the guide is not confirmed. A
    guide's address is its title, so a 403 discloses that the facility has a
    procedure for whatever was guessed at."""
    for key in (staff_guide["slug"], staff_guide["id"]):
        response = viewer.get(f"/api/guides/{key}")
        assert response.status_code == 404, key
        assert response.json()["error"]["code"] == "not_found", key
        assert "Auditor" not in response.text


def test_search_does_not_return_a_staff_guide_to_a_viewer(viewer, staff_guide, open_guide):
    """Search reads the steps and the bullets as well as the front matter, so a
    staff guide leaks through a phrase buried in it, not only through its title."""
    assert viewer.get("/api/search", params={"q": "Auditor"}).json() == []
    assert viewer.get("/api/search", params={"q": "reception"}).json() == []

    hits = viewer.get("/api/search", params={"q": "Confocal"}).json()
    assert [hit["guide"]["title"] for hit in hits] == ["Booking the Confocal"]


def test_the_tag_index_does_not_offer_a_viewer_a_tag_only_staff_guides_carry(viewer, staff_guide):
    """The tag itself is the disclosure: a tag named after an internal procedure,
    with a count beside it, and a link that leads to an empty page."""
    assert viewer.get("/api/tags").json() == []


def test_the_tag_index_counts_only_what_a_viewer_can_open(viewer, staff_guide, open_guide):
    counts = {tag["slug"]: tag["documentCount"] for tag in viewer.get("/api/tags").json()}

    assert counts == {"internal": 1}


def test_a_viewer_cannot_read_a_staff_guides_revisions(viewer, staff_guide):
    """Author-only, so a viewer is refused by role before visibility is reached
    — but the revision holds the whole document, so it is checked rather than
    assumed."""
    for path in (
        f"/api/guides/{staff_guide['id']}/revisions",
        f"/api/guides/{staff_guide['id']}/revisions/1",
    ):
        response = viewer.get(path)
        assert response.status_code == 403, path
        assert "Auditor" not in response.text


def test_a_viewer_cannot_open_a_staff_guide_through_the_export(viewer, staff_guide):
    for path in ("/api/export", "/api/export/archive"):
        assert viewer.get(path).status_code == 403, path


def test_a_refused_reading_does_not_move_the_view_counter(viewer, staff_guide, db_session):
    """The counter is the one thing a refused request could still write, and a
    counter that climbs is an answer to "does this guide exist"."""
    viewer.get(f"/api/guides/{staff_guide['slug']}")

    guide = db_session.scalars(select(Guide).where(Guide.id == staff_guide["id"])).one()
    assert guide.view_count == 0


def test_a_picture_only_a_staff_guide_shows_is_not_served_to_a_viewer(author, category, viewer):
    """Authentication is not visibility, and the whole point of a staff guide is
    often what is *in* the screenshot — a badge, a keypad, a licence key. The
    bytes are behind the same rule as the words around them."""
    from .conftest import upload_media

    image = upload_media(author)
    created = create_guide(author, category.id, "Escorting an Auditor Through the Facility")
    author.put(
        f"/api/guides/{created['id']}",
        json=document_from(
            created,
            visibility="staff",
            steps=[step("Badge", media=[{"id": image["id"], "alt": ""}])],
        ),
    )
    author.post(f"/api/guides/{created['id']}/publish")

    assert author.get(f"/api/media/{image['id']}").status_code == 200
    assert viewer.get(f"/api/media/{image['id']}").status_code == 404


# --- the people who write them --------------------------------------------


def test_an_author_sees_a_staff_guide_everywhere_a_viewer_does_not(author, staff_guide):
    assert titles(author.get("/api/guides")) == ["Escorting an Auditor Through the Facility"]
    assert author.get(f"/api/guides/{staff_guide['slug']}").status_code == 200
    assert author.get("/api/search", params={"q": "Auditor"}).json() != []
    assert [tag["slug"] for tag in author.get("/api/tags").json()] == ["internal"]


def test_an_admin_sees_a_staff_guide_everywhere_a_viewer_does_not(admin, staff_guide):
    assert titles(admin.get("/api/guides")) == ["Escorting an Auditor Through the Facility"]
    assert admin.get(f"/api/guides/{staff_guide['slug']}").status_code == 200
    assert admin.get("/api/search", params={"q": "Auditor"}).json() != []


# --- the artefact that has no login in front of it -------------------------


def test_the_static_snapshot_does_not_write_a_staff_guide_out(
    db_session, admin, category, staff_guide, open_guide, tmp_path
):
    """A published folder of HTML has no login in front of it, and a file once
    written cannot be un-published."""
    from app.settings import get_settings
    from app.static_site import publish

    report = publish(db_session, get_settings(), tmp_path / "site")

    assert report.guides == 1
    assert report.skipped_staff == 1
    assert [path.name for path in (tmp_path / "site" / "g").iterdir()] == [
        "booking-the-confocal.html"
    ]
    for path in (tmp_path / "site").rglob("*.html"):
        assert "Auditor" not in path.read_text(encoding="utf-8"), path


def test_the_snapshot_report_separates_the_unfinished_from_the_internal(
    db_session, admin, category, staff_guide, tmp_path
):
    """Both are left out, and an operator counting guides needs to know which
    is which — one is somebody's work in progress, the other is deliberate."""
    from app.settings import get_settings
    from app.static_site import publish

    create_guide(admin, category.id, "A Draft Nobody Has Finished")
    report = publish(db_session, get_settings(), tmp_path / "site")

    assert (report.skipped_drafts, report.skipped_staff) == (1, 1)
    assert "staff-only:    1" in report.to_text()


# --- the sweep -------------------------------------------------------------


RETURNS_A_GUIDE = frozenset(
    {
        "/api/guides",
        "/api/guides/{key}",
        "/api/guides/{guide_id}",
        "/api/guides/{guide_id}/publish",
        "/api/guides/{guide_id}/unpublish",
        "/api/search",
    }
)
"""Every route whose declared response can carry a guide.

Written by hand. A list derived from the routers agrees with them however wrong
they are, so this is what a new guide-bearing route has to be added to — and
adding it to this set is what drags the author into deciding whether it filters.
"""

READABLE_BY_A_VIEWER = frozenset({"/api/guides", "/api/guides/{key}", "/api/search"})
"""The subset a viewer can call at all. The rest are author-only, which the
sweep proves rather than assumes."""

CARRIES_GUIDE_CONTENT_WITHOUT_A_MODEL = frozenset(
    {
        "/api/guides/{guide_id}/revisions",
        "/api/guides/{guide_id}/revisions/{version}",
        "/api/export",
        "/api/export/archive",
    }
)
"""Routes that return a guide but do not declare it in a response model, so the
walk below cannot find them: a revision document and the export are both plain
JSON. They are listed here and required to refuse a viewer outright."""


def _mentions_a_guide(annotation: object, seen: set[object] | None = None) -> bool:
    """Whether a guide can appear anywhere inside a declared response type."""
    from typing import get_args

    seen = seen if seen is not None else set()
    if annotation in (GuideOut, GuideSummaryOut):
        return True
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if annotation in seen:
            return False
        seen.add(annotation)
        return any(
            _mentions_a_guide(field.annotation, seen) for field in annotation.model_fields.values()
        )
    return any(_mentions_a_guide(argument, seen) for argument in get_args(annotation))


def _guide_bearing_routes() -> dict[str, APIRoute]:
    return {
        route.path: route
        for route in _all_routes()
        if isinstance(route, APIRoute) and _mentions_a_guide(route.response_model)
    }


def test_every_route_that_can_return_a_guide_has_been_accounted_for():
    """The sweep's own tripwire.

    A route added later that serves guides is found by walking the response
    models, and fails here until somebody puts it in one of the two sets above —
    at which point they have had to decide whether a viewer may call it, and the
    test below then holds them to it.
    """
    assert set(_guide_bearing_routes()) == RETURNS_A_GUIDE
    assert RETURNS_A_GUIDE >= READABLE_BY_A_VIEWER

    paths = {getattr(route, "path", None) for route in _all_routes()}
    assert paths >= CARRIES_GUIDE_CONTENT_WITHOUT_A_MODEL


def test_the_sweep_can_actually_see_a_route_nobody_declared():
    """The sweep's own regression test.

    ``set(...) == RETURNS_A_GUIDE`` is worthless if the walk finds nothing,
    which is what happens the moment a response model is declared in a shape it
    cannot see through — a union, a wrapper, a bare ``dict``. Planting a route
    and requiring the walk to name it is the only assertion that distinguishes
    "every guide-bearing route is accounted for" from "no sight".
    """
    from fastapi import APIRouter

    from app.main import app

    planted = APIRouter(prefix="/api/deliberate-guide-leak")

    @planted.get("", response_model=list[GuideSummaryOut])
    def wide_open():  # pragma: no cover - never called
        return []

    original = list(app.routes)
    try:
        app.include_router(planted)
        assert "/api/deliberate-guide-leak" in _guide_bearing_routes()
    finally:
        app.router.routes[:] = original

    assert set(_guide_bearing_routes()) == RETURNS_A_GUIDE


def test_no_route_that_can_return_a_guide_gives_a_viewer_a_staff_one(viewer, staff_guide):
    """Every one of them called, with a staff guide sitting in the database.

    The author-only ones must refuse the viewer outright; the rest must answer
    without ever naming the guide. Nothing here is hand-written per route, so a
    route added to the sets above is exercised whether or not anybody wrote it
    a test of its own.
    """
    routes = _guide_bearing_routes()
    substitutions = {
        "{key}": staff_guide["slug"],
        "{guide_id}": staff_guide["id"],
        "{version}": "1",
    }

    for path in sorted(RETURNS_A_GUIDE | CARRIES_GUIDE_CONTENT_WITHOUT_A_MODEL):
        url = path
        for placeholder, value in substitutions.items():
            url = url.replace(placeholder, value)

        route = routes.get(path)
        methods = route.methods if route is not None else {"GET"}
        for method in sorted(methods):
            response = viewer.raw.request(method, url, json={})
            if path in READABLE_BY_A_VIEWER:
                assert response.status_code in (200, 404), (path, method, response.status_code)
                assert staff_guide["slug"] not in response.text, (path, method)
                assert "Auditor" not in response.text, (path, method)
            else:
                assert response.status_code in (403, 404), (path, method, response.status_code)
                assert "Auditor" not in response.text, (path, method)
