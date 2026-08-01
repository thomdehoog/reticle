"""Configuration loading.

These exist because the rest of the suite drives settings through
``os.environ``, which silently skips the dotenv code path — and the dotenv path
is the one a real deployment uses. A list-typed setting behaves differently
there, and getting it wrong aborts start-up rather than degrading quietly.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.settings import ENV_FILE_VARIABLE, Settings

MINIMAL = "RETICLE_SECRET_KEY=a-secret-key-long-enough\n"


def load(tmp_path, body: str, encoding: str = "utf-8") -> Settings:
    env_file = tmp_path / "reticle.env"
    env_file.write_text(body, encoding=encoding)
    return Settings(_env_file=env_file)


def test_an_env_file_written_by_notepad_still_loads(tmp_path, monkeypatch):
    """Notepad and Windows PowerShell write a BOM by default. Read as plain
    utf-8 the mark fuses to the first variable name, so the first line — usually
    the secret key — vanishes and start-up fails with a misleading message.

    The process variable is cleared so the assertion is about the file, which is
    where the BOM lives.
    """
    monkeypatch.delenv("RETICLE_SECRET_KEY", raising=False)
    settings = load(tmp_path, MINIMAL + "RETICLE_SESSION_LIFETIME_HOURS=6\n", encoding="utf-8-sig")

    assert settings.secret_key == "a-secret-key-long-enough"
    assert settings.session_lifetime_hours == 6


def test_a_comma_separated_origin_list_loads_from_a_dotenv_file(tmp_path):
    settings = load(tmp_path, MINIMAL + "RETICLE_CORS_ORIGINS=https://guides.zmb.uzh.ch,http://localhost:5173\n")

    assert settings.cors_origins == ["https://guides.zmb.uzh.ch", "http://localhost:5173"]


def test_a_json_origin_list_also_loads_from_a_dotenv_file(tmp_path):
    settings = load(tmp_path, MINIMAL + 'RETICLE_CORS_ORIGINS=["https://guides.zmb.uzh.ch"]\n')

    assert settings.cors_origins == ["https://guides.zmb.uzh.ch"]


def test_a_comma_separated_origin_list_loads_from_the_process_environment(monkeypatch):
    monkeypatch.setenv("RETICLE_CORS_ORIGINS", "https://a.zmb.uzh.ch, https://b.zmb.uzh.ch")

    assert Settings(_env_file=None).cors_origins == ["https://a.zmb.uzh.ch", "https://b.zmb.uzh.ch"]


def test_the_origin_default_covers_the_vite_dev_server(tmp_path):
    assert load(tmp_path, MINIMAL).cors_origins == ["http://localhost:5173", "http://127.0.0.1:5173"]


def test_a_dotenv_file_supplies_the_whole_configuration(tmp_path):
    settings = load(
        tmp_path,
        MINIMAL
        + "RETICLE_COOKIE_SECURE=false\n"
        + "RETICLE_SESSION_LIFETIME_HOURS=4\n"
        + "RETICLE_MAX_MEDIA_PER_STEP=3\n"
        + "RETICLE_MEDIA_ROOT=/srv/reticle/media\n",
    )

    assert settings.cookie_secure is False
    assert settings.session_lifetime_hours == 4
    assert settings.max_media_per_step == 3
    assert str(settings.media_root).replace("\\", "/") == "/srv/reticle/media"


def test_startup_refuses_without_a_secret_key(monkeypatch):
    """A generated fallback would be the same on every installation, and it is
    the pepper for session-token digests."""
    monkeypatch.delenv("RETICLE_SECRET_KEY", raising=False)

    with pytest.raises(ValidationError, match="secret_key"):
        Settings(_env_file=None)


def test_a_short_secret_key_is_refused(monkeypatch):
    monkeypatch.setenv("RETICLE_SECRET_KEY", "tooshort")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_the_env_file_location_is_configurable(monkeypatch, tmp_path):
    """A service manager keeps the environment file outside the working
    directory, so the path has to be settable rather than assumed."""
    from app.settings import get_settings

    env_file = tmp_path / "elsewhere.env"
    env_file.write_text(MINIMAL + "RETICLE_SESSION_LIFETIME_HOURS=99\n", encoding="utf-8")
    monkeypatch.setenv(ENV_FILE_VARIABLE, str(env_file))
    get_settings.cache_clear()
    try:
        assert get_settings().session_lifetime_hours == 99
    finally:
        get_settings.cache_clear()


def test_secure_defaults_hold_when_nothing_is_configured(tmp_path, monkeypatch):
    """The suite weakens several settings through the process environment; this
    asserts what a deployment that configures nothing actually gets."""
    for name in ("RETICLE_COOKIE_SECURE", "RETICLE_ARGON2_TIME_COST", "RETICLE_ARGON2_MEMORY_COST_KIB",
                 "RETICLE_ARGON2_PARALLELISM", "RETICLE_MEDIA_ROOT", "RETICLE_DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)

    settings = load(tmp_path, MINIMAL)

    assert settings.cookie_secure is True
    assert settings.trust_forwarded_for is False
    assert settings.admin_password is None
    assert settings.max_upload_bytes == 20 * 1024 * 1024
    assert settings.max_image_dimension == 10_000
    assert settings.max_media_per_step == 4
    assert settings.max_video_bytes == 200 * 1024 * 1024
    assert settings.min_password_length == 12
    assert settings.argon2_memory_cost_kib == 65536


def test_video_uploads_have_their_own_ceiling(tmp_path):
    """A clip of a stage moving is an order of magnitude larger than any
    photograph, so holding it to the image cap would reject the files the video
    slot exists to accept."""
    settings = load(tmp_path, MINIMAL + "RETICLE_MAX_VIDEO_BYTES=52428800\n")

    assert settings.max_video_bytes == 50 * 1024 * 1024
    assert settings.max_upload_bytes == 20 * 1024 * 1024
