"""``GET /api/config``: the limits a client checks before it uploads.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from app.settings import get_settings


def test_the_defaults_are_the_documented_limits(viewer):
    response = viewer.get("/api/config")

    assert response.status_code == 200
    assert response.json() == {
        "maxImageBytes": 20 * 1024 * 1024,
        "maxVideoBytes": 200 * 1024 * 1024,
        "maxMediaPerStep": 3,
    }


def test_it_reports_what_the_operator_configured(author, monkeypatch):
    monkeypatch.setenv("RETICLE_MAX_UPLOAD_BYTES", "5000000")
    monkeypatch.setenv("RETICLE_MAX_VIDEO_BYTES", "600000000")
    monkeypatch.setenv("RETICLE_MAX_MEDIA_PER_STEP", "5")
    get_settings.cache_clear()

    assert author.get("/api/config").json() == {
        "maxImageBytes": 5_000_000,
        "maxVideoBytes": 600_000_000,
        "maxMediaPerStep": 5,
    }


def test_it_is_behind_the_login(anon):
    response = anon.get("/api/config")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


def test_it_exposes_the_limits_and_nothing_else(admin):
    """The settings object also holds the secret key; this must stay a short list."""
    assert set(admin.get("/api/config").json()) == {"maxImageBytes", "maxVideoBytes", "maxMediaPerStep"}
