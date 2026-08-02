"""Getting the corpus out, and proving it can be put back.

ZMB is here because a hosted platform held their material behind an API that
ends with the subscription. An export that has never been restored is a
hypothesis, and the day it stops being one is the day the system that produced
it is gone — so the central test here does the whole round trip: build a corpus,
export it, restore it into an empty database, and compare the two documents
field for field.

The other failures guarded here are the ones that make an export worthless
quietly. A document that omits an entity — the annotations on a picture, a
revision, the tag that decides where a guide appears — still looks like a
complete file. A media checksum that is never verified turns a truncated
transfer into a discovery somebody makes years later. And an export that
carries password hashes hands whoever ends up with the file every account in
the institute.
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile

import pytest
from sqlalchemy import select

from app import exporter
from app.importer.client import MigrationError
from app.importer.reticle import read_export, restore
from app.models import Media, User
from app.settings import get_settings

from .conftest import (
    annotated,
    annotation,
    bullet,
    create_guide,
    create_page,
    document_from,
    page_document_from,
    step,
    upload_media,
)


def build_corpus(admin, category) -> dict:
    """A guide with everything on it, a wiki page, and both published.

    Deliberately not a minimal fixture: the entities most likely to be dropped
    from an export are the ones hanging off something else — the shapes on a
    picture, the tags, the contributor list, the publish snapshot. Every flag on
    the guide is set away from its default for the same reason: a field the
    export drops still round-trips perfectly when both sides happen to be false.
    """
    image = upload_media(admin)
    guide = create_guide(admin, category.id, "Starting a Session on the Confocal")
    saved = admin.put(
        f"/api/guides/{guide['id']}",
        json=document_from(
            guide,
            summary="From booking to shutdown.",
            tags=["confocal", "stellaris"],
            difficulty="easy",
            timeRequiredMinMinutes=20,
            timeRequiredMaxMinutes=40,
            introduction="Assumes a valid booking.",
            conclusion="Report faults the same day.",
            isQuickLink=True,
            steps=[
                step(
                    "Power up in order",
                    bullets=[
                        bullet("Switch on the mains strip.", color="black"),
                        bullet("Never skip the self-test.", color="red", icon="caution"),
                        bullet("The 405 needs ten minutes.", color="light_blue", level=1),
                    ],
                    media=[
                        annotated(
                            image,
                            annotation(
                                shape="rectangle", color="red", x=0.1, y=0.1, width=0.2, height=0.2
                            ),
                            annotation(
                                shape="arrow", color="blue", x=0.8, y=0.8, width=-0.3, height=-0.3
                            ),
                        )
                    ],
                ),
                step("Acquire and shut down", bullets=[bullet("Save to the group folder.")]),
            ],
        ),
    )
    assert saved.status_code == 200, saved.text
    published = admin.post(f"/api/guides/{guide['id']}/publish")
    assert published.status_code == 200, published.text

    page = create_page(admin, title="Light Microscopy", category_id=category.id, is_landing=True)
    admin.put(
        f"/api/pages/{page['id']}",
        json=page_document_from(page, body="# Welcome\n\n```guidelist\ntags: confocal\n```"),
    )
    admin.post(f"/api/pages/{page['id']}/publish")

    return {"guide": published.json(), "page": page, "image": image}


def export_of(db_session) -> dict:
    return exporter.build_document(db_session, get_settings())


# --- the document ---------------------------------------------------------


def test_the_export_carries_every_kind_of_thing_the_corpus_holds(admin, category, db_session):
    build_corpus(admin, category)

    document = export_of(db_session)

    assert document["reticleExport"]["formatVersion"] == exporter.FORMAT_VERSION
    assert document["reticleExport"]["exportedAt"].endswith("Z")
    for key in ("users", "categories", "tags", "media", "guides", "pages", "guideRevisions"):
        assert document[key], f"{key} is empty"
    assert document["reticleExport"]["counts"]["guides"] == len(document["guides"])


def test_a_guide_is_exported_in_the_shape_the_api_already_serves(admin, category, db_session):
    """One contract, not two: the export cannot drift from the documented API."""
    corpus = build_corpus(admin, category)

    exported = export_of(db_session)["guides"][0]
    served = admin.get(f"/api/guides/{corpus['guide']['id']}").json()

    # The reader's view has moved the view counter on; everything else matches.
    exported.pop("viewCount")
    served.pop("viewCount")
    assert exported == served


def test_the_shapes_drawn_on_a_picture_survive(admin, category, db_session):
    """The half of a step that a naive export loses without anyone noticing."""
    build_corpus(admin, category)

    shapes = export_of(db_session)["guides"][0]["steps"][0]["media"][0]["annotations"]

    assert [shape["shape"] for shape in shapes] == ["rectangle", "arrow"]
    assert [shape["color"] for shape in shapes] == ["red", "blue"]
    assert shapes[1]["width"] == -0.3


def test_tags_survive_because_they_are_the_navigation(admin, category, db_session):
    build_corpus(admin, category)

    document = export_of(db_session)

    assert sorted(tag["slug"] for tag in document["tags"]) == ["confocal", "stellaris"]
    assert document["guides"][0]["tags"] == ["confocal", "stellaris"]


def test_a_quick_link_is_still_a_quick_link_after_a_restore(
    admin, category, db_session, tmp_path, empty_database
):
    """Named on its own as well as being covered by the whole-document round
    trip, because a boolean is the easiest thing in an export to lose: nothing
    looks wrong, the guide simply stops being on the front page."""
    build_corpus(admin, category)
    assert export_of(db_session)["guides"][0]["isQuickLink"] is True

    exporter.write_to_directory(db_session, get_settings(), tmp_path / "out")
    document, files = read_export(tmp_path / "out")

    restore(empty_database, get_settings(), document, files)

    served = exporter.build_document(empty_database, get_settings())
    assert served["guides"][0]["isQuickLink"] is True


def test_publish_history_survives(admin, category, db_session):
    build_corpus(admin, category)

    revisions = export_of(db_session)["guideRevisions"]

    assert len(revisions) == 1
    assert revisions[0]["version"] == 1
    assert revisions[0]["document"]["title"] == "Starting a Session on the Confocal"


def test_media_carry_a_checksum_of_the_bytes_on_disk(admin, category, db_session, media_root):
    build_corpus(admin, category)

    entry = export_of(db_session)["media"][0]
    stored = (media_root / db_session.get(Media, entry["id"]).storage_path).read_bytes()

    assert entry["sha256"] == hashlib.sha256(stored).hexdigest()
    assert entry["file"].startswith("media/")
    assert entry["byteSize"] == len(stored)


def test_no_credential_of_any_kind_leaves_in_the_export(admin, category, db_session):
    """This file gets emailed. It should be worth nothing to whoever else gets it."""
    build_corpus(admin, category)

    raw = json.dumps(export_of(db_session))

    assert "passwordHash" not in raw
    assert "password_hash" not in raw
    assert "$argon2" not in raw
    assert "tokenHash" not in raw
    for user in export_of(db_session)["users"]:
        assert set(user) == {"id", "email", "displayName", "role", "isActive", "createdAt"}


def test_where_a_migrated_guide_came_from_is_carried_forward(admin, category, db_session):
    """A second move must not be where the thread back to the original ends."""
    from app.models import ImportedRecord

    corpus = build_corpus(admin, category)
    db_session.add(
        ImportedRecord(
            source_system="dozuki",
            source_kind="guide",
            source_id="1234",
            source_url="https://zmb.dozuki.com/Guide/1234",
            local_id=corpus["guide"]["id"],
        )
    )
    db_session.commit()

    provenance = export_of(db_session)["provenance"]

    assert provenance[0]["sourceId"] == "1234"
    assert provenance[0]["localId"] == corpus["guide"]["id"]


# --- the archive ----------------------------------------------------------


def test_the_archive_holds_the_document_and_every_file(admin, category, db_session):
    build_corpus(admin, category)

    payload = b"".join(exporter.stream_archive(db_session, get_settings()))

    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        names = archive.getnames()
        document = json.loads(archive.extractfile(exporter.DOCUMENT_NAME).read().decode("utf-8"))

    assert exporter.DOCUMENT_NAME in names
    for entry in document["media"]:
        assert entry["file"] in names


def test_the_files_in_the_archive_match_their_checksums(admin, category, db_session):
    build_corpus(admin, category)

    payload = b"".join(exporter.stream_archive(db_session, get_settings()))

    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        document = json.loads(archive.extractfile(exporter.DOCUMENT_NAME).read().decode("utf-8"))
        for entry in document["media"]:
            bytes_in_archive = archive.extractfile(entry["file"]).read()
            assert hashlib.sha256(bytes_in_archive).hexdigest() == entry["sha256"]


def test_a_directory_export_is_readable_without_unpacking_anything(
    admin, category, db_session, tmp_path
):
    build_corpus(admin, category)

    exporter.write_to_directory(db_session, get_settings(), tmp_path / "out")

    document = json.loads((tmp_path / "out" / exporter.DOCUMENT_NAME).read_text(encoding="utf-8"))
    for entry in document["media"]:
        assert (tmp_path / "out" / entry["file"]).exists()


# --- the endpoints --------------------------------------------------------


def test_only_an_administrator_may_take_the_corpus_out(viewer, author, admin):
    """It is the whole institute's documentation in one request."""
    assert viewer.get("/api/export").status_code == 403
    assert author.get("/api/export").status_code == 403
    assert admin.get("/api/export").status_code == 200


def test_the_archive_endpoint_is_restricted_the_same_way(viewer, author):
    assert viewer.get("/api/export/archive").status_code == 403
    assert author.get("/api/export/archive").status_code == 403


def test_taking_the_corpus_out_is_recorded(admin, category, db_session):
    """A download that should not have happened is noticed afterwards or never."""
    from app.models import AuditLog

    build_corpus(admin, category)
    admin.get("/api/export")

    actions = [row.action for row in db_session.scalars(__import__("sqlalchemy").select(AuditLog))]
    assert "export.document" in actions


def test_the_archive_downloads_as_a_named_file(admin, category):
    build_corpus(admin, category)

    response = admin.get("/api/export/archive")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/gzip"
    assert "reticle-export-" in response.headers["content-disposition"]


# --- the round trip -------------------------------------------------------


def test_a_corpus_survives_being_exported_and_restored(
    admin, category, db_session, tmp_path, make_user, empty_database
):
    """The whole promise, asserted in one place.

    Export a corpus, restore it into an empty database, and compare what the
    two would serve. Anything the export drops or the restore mangles shows up
    here as a difference between two documents.
    """
    build_corpus(admin, category)
    before = export_of(db_session)
    exporter.write_to_directory(db_session, get_settings(), tmp_path / "out")

    document, files = read_export(tmp_path / "out")
    report = restore(empty_database, get_settings(), document, files)

    assert report.intact, report.to_text()

    after = exporter.build_document(empty_database, get_settings())

    # The header carries the moment of export, which is legitimately different.
    before.pop("reticleExport")
    after.pop("reticleExport")
    assert after == before


def test_a_restore_refuses_a_database_that_already_holds_content(
    admin, category, db_session, tmp_path
):
    """Merging two corpora is a different operation with different answers."""
    build_corpus(admin, category)
    exporter.write_to_directory(db_session, get_settings(), tmp_path / "out")
    document, files = read_export(tmp_path / "out")

    with pytest.raises(MigrationError, match="already holds"):
        restore(db_session, get_settings(), document, files)


def test_a_restore_refuses_a_format_it_does_not_understand(db_session):
    with pytest.raises(MigrationError, match="format version"):
        restore(db_session, get_settings(), {"reticleExport": {"formatVersion": 99}}, {})


def test_a_truncated_file_is_reported_rather_than_restored_silently(
    admin, category, db_session, tmp_path, empty_database
):
    """Otherwise a broken transfer is discovered by whoever opens that guide."""
    build_corpus(admin, category)
    exporter.write_to_directory(db_session, get_settings(), tmp_path / "out")

    document, files = read_export(tmp_path / "out")
    damaged = dict(files)
    first = next(iter(damaged))
    damaged[first] = damaged[first][: len(damaged[first]) // 2]

    report = restore(empty_database, get_settings(), document, damaged)

    assert not report.intact
    assert first in report.checksum_failures
    assert "did not match" in report.to_text()


def test_a_restored_account_cannot_be_signed_into_with_a_known_password(
    admin, category, db_session, tmp_path, empty_database
):
    """Accounts arrive without credentials, and must not gain a guessable one."""
    build_corpus(admin, category)
    exporter.write_to_directory(db_session, get_settings(), tmp_path / "out")
    document, files = read_export(tmp_path / "out")

    from app.security import verify_password

    restore(empty_database, get_settings(), document, files)

    restored = empty_database.scalars(select(User)).first()
    assert restored is not None
    assert not verify_password("", restored.password_hash)
    assert not verify_password("password", restored.password_hash)


def test_an_archive_and_a_directory_restore_identically(admin, category, db_session, tmp_path):
    """An operator should not have to remember which form they made."""
    build_corpus(admin, category)

    exporter.write_to_directory(db_session, get_settings(), tmp_path / "out")
    archive_path = tmp_path / "export.tar.gz"
    with archive_path.open("wb") as handle:
        for chunk in exporter.stream_archive(db_session, get_settings()):
            handle.write(chunk)

    from_directory, directory_files = read_export(tmp_path / "out")
    from_archive, archive_files = read_export(archive_path)

    from_directory.pop("reticleExport")
    from_archive.pop("reticleExport")
    assert from_directory == from_archive
    assert set(directory_files) == set(archive_files)


# --- what an archive is allowed to contain --------------------------------


def test_a_restored_slug_cannot_escape_the_directory_it_is_written_into(db_session, tmp_path):
    """An archive is a file an administrator was handed, and its slugs become
    URLs and — in ``static_site`` — file names.

    ``(destination / "g" / f"{slug}.html").write_text(...)`` with a slug of
    ``../../../../tmp/PWNED`` writes outside the destination entirely, and
    restoring an archive and then publishing a snapshot is the documented
    migration workflow.
    """
    from app.importer.reticle import safe_slug

    assert safe_slug("../../../../tmp/PWNED", "guide") == "tmp-pwned"
    assert safe_slug("/etc/passwd", "guide") == "etc-passwd"
    assert safe_slug("", "guide") == "guide"
    # An ordinary slug is untouched, so a real restore is not renamed.
    assert safe_slug("aligning-the-confocal", "guide") == "aligning-the-confocal"


def test_a_restore_writes_media_through_the_configured_storage_backend(
    admin, category, db_session, tmp_path, monkeypatch, empty_database
):
    """On an S3 installation, writing straight to local disk puts every image
    somewhere ``Media.storage_path`` is never read from — so the restore reports
    success and every picture in the corpus 404s."""
    from app.storage import LocalStorage

    build_corpus(admin, category)
    exporter.write_to_directory(db_session, get_settings(), tmp_path / "out")
    document, files = read_export(tmp_path / "out")

    from app import importer

    elsewhere = tmp_path / "bucket"
    written: list[str] = []

    class RecordingStorage(LocalStorage):
        def write(self, storage_path: str, payload: bytes) -> None:
            written.append(storage_path)
            super().write(storage_path, payload)

    monkeypatch.setattr(
        importer.reticle, "build_storage", lambda settings: RecordingStorage(elsewhere)
    )
    restore(empty_database, get_settings(), document, files)

    assert written, "the restore bypassed the storage interface"
    stored = empty_database.scalars(select(Media)).all()
    assert {media.storage_path for media in stored} >= set(written)
    for storage_path in written:
        assert (elsewhere / storage_path).is_file()
