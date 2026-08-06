"""The facility's own description of itself.

The front page's name, tagline and picture used to be environment variables read
once at start-up, which meant a facility could not change its own front page
without a shell on the server and a restart. They are a row now, and the
environment is what fills it the first time.

Both halves are worth holding: a fresh installation must still come up saying
what its environment says, and a save must survive without it.
"""

from __future__ import annotations

from app.settings import get_settings

from .conftest import upload_media


def test_the_configuration_starts_as_the_environment_describes_it(anon):
    """Nobody has saved anything, so the environment is what the front page says."""
    settings = get_settings()
    body = anon.get("/api/config").json()["organisation"]

    assert body["name"] == settings.organisation_name
    assert body["shortName"] == settings.organisation_short_name


def test_an_admin_reads_the_facility_with_the_picture_identifier(admin):
    """`/api/config` hands out a URL for an ``img``; the form needs the id it
    would have to send back."""
    settings = get_settings()
    body = admin.get("/api/facility").json()

    assert body["name"] == settings.organisation_name
    assert body["heroMediaId"] is None
    assert body["heroImageUrl"] is None


def test_saving_the_facility_changes_what_every_visitor_is_told(admin, anon):
    saved = admin.patch(
        "/api/facility",
        json={"name": "Center for Microscopy and Image Analysis", "tagline": "The guidebook."},
    )

    assert saved.status_code == 200
    public = anon.get("/api/config").json()["organisation"]
    assert public["name"] == "Center for Microscopy and Image Analysis"
    assert public["tagline"] == "The guidebook."


def test_the_saved_name_outlives_the_environment(admin, anon, monkeypatch):
    """The environment is a default, not the answer.

    Once a facility has said its own name, changing the variable — or deploying
    somewhere it is not set — must not overwrite it. This is the difference
    between seeding a row and reading configuration.
    """
    admin.patch("/api/facility", json={"name": "Renamed By An Administrator"})

    from app import settings as settings_module

    settings_module.get_settings.cache_clear()
    monkeypatch.setenv("RETICLE_ORGANISATION_NAME", "Something Else Entirely")
    try:
        assert (
            anon.get("/api/config").json()["organisation"]["name"] == "Renamed By An Administrator"
        )
    finally:
        settings_module.get_settings.cache_clear()


def test_a_picture_can_be_set_and_taken_off_again(admin):
    image = upload_media(admin)

    with_picture = admin.patch("/api/facility", json={"heroMediaId": image["id"]}).json()
    without = admin.patch("/api/facility", json={"heroMediaId": None}).json()

    assert with_picture["heroMediaId"] == image["id"]
    assert with_picture["heroImageUrl"] is not None
    assert without["heroMediaId"] is None


def test_a_picture_that_does_not_exist_is_refused(admin):
    response = admin.patch("/api/facility", json={"heroMediaId": "01JQNOTAREALULID00000000"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_a_blank_name_is_refused(admin):
    """The name is the front page's heading and the browser tab; there is no
    sensible thing to show in its place."""
    response = admin.patch("/api/facility", json={"name": "   "})

    assert response.status_code == 422


def test_only_an_administrator_may_read_or_write_the_facility(author, viewer, anon):
    """It is the whole institute's front page, so it is an administrator's.
    Reading it is admin-only too: the public half is `/api/config`, which
    carries no identifiers to write back with."""
    for client in (author, viewer):
        assert client.get("/api/facility").status_code == 403
        assert client.patch("/api/facility", json={"name": "Mine now"}).status_code == 403

    assert anon.get("/api/facility").status_code == 401
