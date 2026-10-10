"""``python -m app.maintenance purge-orphans``: what it removes and, above all,
what it must not.

The media directory used to only grow: an upload that was dropped into a step
and taken out again, or abandoned in a closed tab, stayed for ever. The command
that collects those is the one piece of Reticle whose mistakes are unrecoverable
without a backup, so most of this file is about what counts as "in use".
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app import maintenance
from app.db import utcnow
from app.models import AuditLog, Guide, LoginAttempt, Media, PublishedGuide, User
from app.models import Session as SessionRow
from app.settings import get_settings

from .conftest import (
    bullet,
    create_guide,
    create_page,
    image_bytes,
    published_guide,
    published_page,
    save_guide,
    save_page,
    step,
    upload_media,
)

BACKEND = Path(__file__).resolve().parent.parent
OLD = timedelta(days=30)


def age(db_session, media_root, media_id: str, by: timedelta = OLD) -> None:
    """Make an upload look as if it arrived a while ago, row and files both."""
    db_session.expire_all()
    media = db_session.get(Media, media_id)
    media.created_at = utcnow() - by
    db_session.commit()
    past = time.time() - by.total_seconds()
    for path in (media_root / media.storage_path).parent.glob(f"{media_id}*"):
        os.utime(path, (past, past))


def purge(db_session, days: int = 7, dry_run: bool = False) -> maintenance.PurgeReport:
    db_session.expire_all()
    return maintenance.purge_orphans(db_session, get_settings(), days, dry_run)


def exists(db_session, media_id: str) -> bool:
    db_session.expire_all()
    return db_session.get(Media, media_id) is not None


def files(media_root) -> list[str]:
    return sorted(path.name for path in media_root.rglob("*") if path.is_file())


def test_an_old_upload_nothing_uses_is_removed_with_its_files(author, db_session, media_root):
    orphan = upload_media(author, image_bytes(3000, 200))
    assert len(files(media_root)) == 2, "an original and a display copy"
    age(db_session, media_root, orphan["id"])

    report = purge(db_session)

    assert report.media == [orphan["id"]] and report.media_bytes > 0
    assert not exists(db_session, orphan["id"])
    assert files(media_root) == []
    entry = db_session.scalars(select(AuditLog).where(AuditLog.action == "media.purge")).one()
    assert entry.detail["count"] == 1 and entry.detail["olderThanDays"] == 7


def test_a_recent_upload_is_left_alone(author, db_session, media_root):
    """An upload is unreferenced for the seconds before the autosave that
    places it, and for as long as an author leaves the tab open."""
    recent = upload_media(author)
    age(db_session, media_root, recent["id"], timedelta(days=6))

    assert purge(db_session).media == []
    assert exists(db_session, recent["id"])
    assert purge(db_session, days=5).media == [recent["id"]], "the age is the operator's to choose"


def test_everything_that_shows_an_upload_protects_it(author, category, db_session, media_root):
    in_draft, in_body, as_hero, in_history, unused = (upload_media(author, image_bytes(10 + n, 10)) for n in range(5))
    save_guide(author, create_guide(author, category.id, "Draft"), steps=[step("Look", media=[in_draft])])
    page = create_page(author, "Page")
    save_page(author, page, body=f"![x](/api/media/{in_body['id']})", heroMediaId=as_hero["id"])
    guide = published_guide(author, category.id, "Was Illustrated", steps=[step("Look", media=[in_history])])
    save_guide(author, guide, steps=[step("Look", bullets=[bullet("No picture now.")])])
    author.post(f"/api/guides/{guide['id']}/publish")
    for media in (in_draft, in_body, as_hero, in_history, unused):
        age(db_session, media_root, media["id"])

    report = purge(db_session)

    assert report.media == [unused["id"]]
    for media in (in_draft, in_body, as_hero, in_history):
        assert exists(db_session, media["id"])
        assert author.get(media["url"]).status_code == 200
    assert author.get(f"/api/guides/{guide['id']}/revisions/1").json()["steps"][0]["media"][0]["id"] == in_history["id"]


def test_an_upload_only_an_old_page_version_shows_is_protected(author, db_session, media_root):
    old_inline, old_hero = upload_media(author, image_bytes(11, 11)), upload_media(author, image_bytes(12, 12))
    page = published_page(author, "Rules", body=f"![x](/api/media/{old_inline['id']})", heroMediaId=old_hero["id"])
    save_page(author, page, body="Text only.", heroMediaId=None)
    author.post(f"/api/pages/{page['id']}/publish")
    for media in (old_inline, old_hero):
        age(db_session, media_root, media["id"])

    assert purge(db_session).media == []


def test_a_body_that_mentions_an_upload_protects_it_even_without_a_recorded_reference(author, db_session, media_root):
    """Belt and braces: the reference table is written on save, and a body put
    there by anything that skipped that step must not cost the page its pictures."""
    from app.models import Page, PageMedia

    image = upload_media(author)
    page = create_page(author, "Imported Oddly")
    save_page(author, page, body=f"![x](/api/media/{image['id']})")
    db_session.execute(PageMedia.__table__.delete())
    db_session.commit()
    assert db_session.scalars(select(Page.body)).one().count(image["id"]) == 1
    age(db_session, media_root, image["id"])

    assert purge(db_session).media == []


def test_a_dry_run_reports_and_changes_nothing(author, db_session, media_root):
    orphan = upload_media(author)
    age(db_session, media_root, orphan["id"])
    before = files(media_root)

    report = purge(db_session, dry_run=True)

    assert report.media == [orphan["id"]]
    assert report.lines()[0].startswith("Would remove 1 unused upload(s)")
    assert exists(db_session, orphan["id"]) and files(media_root) == before
    assert db_session.scalars(select(AuditLog).where(AuditLog.action == "media.purge")).all() == []


def test_files_no_upload_owns_are_swept_up_once_they_are_old(author, db_session, media_root):
    kept = upload_media(author)
    age(db_session, media_root, kept["id"], timedelta(days=1))
    shard = media_root / "01" / "ZZ"
    shard.mkdir(parents=True)
    old_stray = shard / "01ZZAAAAAAAAAAAAAAAAAAAAAA.png"
    old_part = shard / ".01ZZBBBBBBBBBBBBBBBBBBBBBB.display.png.12.34.part"
    new_stray = shard / "01ZZCCCCCCCCCCCCCCCCCCCCCC.png"
    not_ours = shard / "README.txt"
    elsewhere = media_root / "notes.txt"
    cache = media_root / ".pdf-cache" / "01ZZDDDDDDDDDDDDDDDDDDDDDD"
    cache.mkdir(parents=True)
    beside_the_shards = media_root / "01" / "01ZZEEEEEEEEEEEEEEEEEEEEEE.png"
    loose_in_the_cache = media_root / ".pdf-cache" / "note.txt"
    for path in (old_stray, old_part, new_stray, not_ours, elsewhere, beside_the_shards, loose_in_the_cache):
        path.write_bytes(b"x")
    past = time.time() - OLD.total_seconds()
    for path in (old_stray, old_part, not_ours, elsewhere, beside_the_shards, loose_in_the_cache):
        os.utime(path, (past, past))

    report = purge(db_session)

    assert sorted(path.name for path in report.stray_files) == sorted([old_stray.name, old_part.name])
    assert not old_stray.exists() and not old_part.exists()
    assert new_stray.exists(), "possibly an upload whose row is about to be committed"
    assert not_ours.exists() and elsewhere.exists(), "not named like an upload, so not this command's to judge"
    assert beside_the_shards.exists() and loose_in_the_cache.exists(), "nor is anything outside where uploads are put"
    assert maintenance._is_older(media_root / "vanished-meanwhile", time.time()) is False
    assert exists(db_session, kept["id"]) and author.get(kept["url"]).status_code == 200


def test_cached_exports_that_are_no_longer_current_are_removed(author, viewer, category, db_session, media_root):
    current = published_guide(author, category.id, "Current")
    withdrawn = published_guide(author, category.id, "Withdrawn")
    for guide in (current, withdrawn):
        assert viewer.get(f"/api/guides/{guide['slug']}/pdf").status_code == 200
    author.post(f"/api/guides/{withdrawn['id']}/unpublish")
    cache_root = media_root / ".pdf-cache"
    leftover = cache_root / current["id"] / "01ZZOLDREVISION00000000000-l1-abc.pdf"
    leftover.write_bytes(b"%PDF- an older version")
    gone = cache_root / "01ZZNOSUCHGUIDE00000000000"
    gone.mkdir()
    (gone / "x.pdf").write_bytes(b"%PDF-")

    report = purge(db_session)

    assert len(report.cached_exports) == 3
    assert [path.name for path in (cache_root / current["id"]).iterdir()] != [leftover.name]
    assert len(list((cache_root / current["id"]).glob("*.pdf"))) == 1
    assert not (cache_root / withdrawn["id"]).exists() and not gone.exists()
    assert viewer.get(f"/api/guides/{current['slug']}/pdf").status_code == 200


def test_expired_sessions_and_old_attempts_are_pruned(db_session, make_user):
    user = make_user("someone@zmb.uzh.ch")
    long_ago = utcnow() - timedelta(days=60)
    db_session.add(SessionRow(user_id=user.id, token_hash="a" * 64, csrf_token="c", expires_at=long_ago))
    db_session.add(SessionRow(user_id=user.id, token_hash="b" * 64, csrf_token="c", expires_at=utcnow() + timedelta(hours=1)))
    db_session.add(LoginAttempt(scope="email", key="k", created_at=long_ago))
    db_session.commit()

    report = purge(db_session)

    assert (report.sessions, report.login_attempts) == (1, 1)
    assert len(db_session.scalars(select(SessionRow)).all()) == 1


def test_index_rows_left_by_a_status_change_outside_the_lifecycle_are_withdrawn(author, category, db_session):
    guide = published_guide(author, category.id)
    db_session.get(Guide, guide["id"]).status = "draft"
    db_session.commit()

    report = purge(db_session)

    assert report.stale_index_rows == 1
    assert db_session.scalars(select(PublishedGuide)).all() == []


def test_running_it_twice_finds_nothing_the_second_time(author, db_session, media_root):
    age(db_session, media_root, upload_media(author)["id"])

    purge(db_session)
    again = purge(db_session)

    assert (again.media, again.stray_files, again.cached_exports) == ([], [], [])
    assert again.lines()[0] == "Removed 0 unused upload(s), 0.0 MB."


def test_it_copes_with_a_media_directory_that_does_not_exist_yet(db_session, media_root):
    assert not media_root.exists()

    report = purge(db_session)

    assert report.stray_files == [] and report.cached_exports == []


# ------------------------------------------------------------- the command line


def test_the_command_reports_what_it_did(migrated, media_root, capsys):
    from app import db

    with db.SessionLocal() as session:
        user = User(email="a@zmb.uzh.ch", display_name="A", role="author", password_hash="x")
        session.add(user)
        session.flush()
        session.add(
            Media(storage_path="aa/bb/gone.png", content_type="image/png", byte_size=3 * 1024 * 1024,
                  uploaded_by_id=user.id, created_at=utcnow() - OLD)
        )
        session.commit()

    assert maintenance.main(["purge-orphans", "--dry-run"]) == 0
    assert capsys.readouterr().out.splitlines()[0] == "Would remove 1 unused upload(s), 3.0 MB."

    assert maintenance.main(["purge-orphans", "--older-than-days", "60"]) == 0
    assert capsys.readouterr().out.splitlines()[0] == "Removed 0 unused upload(s), 0.0 MB."

    assert maintenance.main(["purge-orphans"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "Removed 1 unused upload(s), 3.0 MB." and len(out) == 5
    with db.SessionLocal() as session:
        assert session.scalars(select(Media)).all() == []


def test_the_command_refuses_a_database_that_has_not_been_migrated(file_db, capsys):
    assert maintenance.main(["purge-orphans"]) == 1
    assert "python -m app.migrate" in capsys.readouterr().err


def test_a_negative_age_is_refused(migrated, capsys):
    assert maintenance.main(["purge-orphans", "--older-than-days", "-1"]) == 2
    assert "must not be negative" in capsys.readouterr().err


def test_the_command_needs_to_be_told_what_to_do(capsys):
    with pytest.raises(SystemExit) as stopped:
        maintenance.main([])

    assert stopped.value.code == 2
    assert "purge-orphans" in capsys.readouterr().err


def test_it_runs_as_a_module_from_the_backend_directory(tmp_path):
    """The exact command the deployment documentation gives."""
    environment = {
        **os.environ,
        "RETICLE_DATABASE_URL": f"sqlite:///{tmp_path / 'cli.db'}",
        "RETICLE_MEDIA_ROOT": str(tmp_path / "media"),
    }
    subprocess.run([sys.executable, "-m", "app.migrate"], cwd=BACKEND, env=environment, check=True, capture_output=True)

    result = subprocess.run(
        [sys.executable, "-m", "app.maintenance", "purge-orphans", "--older-than-days", "7", "--dry-run"],
        cwd=BACKEND, env=environment, capture_output=True, text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("Would remove 0 unused upload(s)")
