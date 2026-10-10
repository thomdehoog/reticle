"""Phase two of the import: an export archive, loaded into Reticle.

The archive is written by the real exporter from the stand-in vendor site, the
database is a file created by the migrations, and the assertions are made the
way a reader would meet the result — through the HTTP API, signed in as a
viewer — so that "imported" means "readable", not "rows exist".
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfReader
from sqlalchemy import func, select

from app import db, errors, images, migrate, videos
from app.importer import cli, loader as loader_module
from app.importer.archive import Archive
from app.importer.loader import UNUSABLE_PASSWORD_HASH, Loader, LoadOptions, _positive_int, fingerprint
from app.importer.report import Report
from app.main import app
from app.models import AuditLog, Category, Guide, GuideRevision, ImportRecord, Media, Page, PageRevision, Step, Tag, User
from app.security import hash_password, verify_password
from app.settings import get_settings

from .conftest import TEST_PASSWORD, ApiClient, document_from, instant
from .importer_site import HOST, FakeSite, photo, write_archive

GUIDE_15 = "leica-stellaris-5-inverse-usz-how-to-get-there"
GUIDE_27 = "mesospim-part-1-start-up"
SEQIF = "strategy-to-run-a-full-multiplex-seqif"


@contextmanager
def reticle(directory: Path, **environment: str) -> Iterator[None]:
    """Point the application at an empty, migrated database file and media store."""
    directory.mkdir(parents=True, exist_ok=True)
    with pytest.MonkeyPatch.context() as patch:
        url = f"sqlite:///{directory / 'reticle.db'}"
        patch.setenv("RETICLE_DATABASE_URL", url)
        patch.setenv("RETICLE_MEDIA_ROOT", str(directory / "media"))
        for name, value in environment.items():
            patch.setenv(name, value)
        get_settings.cache_clear()
        engine = db.build_engine(url)
        writer, reader = db.session_factories(engine)
        patch.setattr(db, "engine", engine)
        patch.setattr(db, "SessionLocal", writer)
        patch.setattr(db, "ReadSessionLocal", reader)
        try:
            yield
        finally:
            engine.dispose()
    get_settings.cache_clear()


def add_user(email: str, role: str, active: bool = True) -> None:
    with db.SessionLocal() as session:
        session.add(User(email=email, display_name=email.split("@")[0], role=role, password_hash=hash_password(TEST_PASSWORD), is_active=active))
        session.commit()


def staff() -> None:
    """The accounts that exist before the import: one of them is a vendor author."""
    add_user("ada.example@zmb.example", "author")
    add_user("viewer@zmb.example", "viewer")
    add_user("admin@zmb.example", "admin")


def load(archive: Path, *arguments: str) -> SimpleNamespace:
    lines: list[str] = []
    status = cli.main(["load", "--archive", str(archive), *arguments], out=lines.append)
    text = "\n".join(lines)
    return SimpleNamespace(status=status, lines=text.splitlines(), text=text)


@contextmanager
def signed_in(email: str) -> Iterator[ApiClient]:
    with TestClient(app) as raw:
        client = ApiClient(raw)
        assert client.login(email).status_code == 200
        yield client


def count(model: type) -> int:
    with db.SessionLocal() as session:
        return session.scalar(select(func.count()).select_from(model))


def media_files() -> list[Path]:
    return sorted(path for path in get_settings().media_root.rglob("*") if path.is_file())


def edit_json(archive: Path, relative: str, change: Any) -> None:
    path = archive / relative
    document = json.loads(path.read_text())
    change(document)
    path.write_text(json.dumps(document))


@pytest.fixture(scope="module")
def pristine(tmp_path_factory) -> Path:
    directory = tmp_path_factory.mktemp("export") / "archive"
    write_archive(directory)
    return directory


@pytest.fixture()
def archive(pristine, tmp_path) -> Path:
    """A private copy, for tests that alter the archive or want their own report."""
    shutil.copytree(pristine, tmp_path / "archive")
    return tmp_path / "archive"


@pytest.fixture(scope="module")
def world(pristine, tmp_path_factory) -> Iterator[SimpleNamespace]:
    """The archive loaded once into a fresh installation, for the read-only tests."""
    archive_copy = tmp_path_factory.mktemp("loaded") / "archive"
    shutil.copytree(pristine, archive_copy)
    with reticle(tmp_path_factory.mktemp("reticle")):
        migrate.upgrade()
        staff()
        result = load(archive_copy)
        with signed_in("viewer@zmb.example") as viewer, signed_in("ada.example@zmb.example") as author:
            yield SimpleNamespace(result=result, archive=archive_copy, viewer=viewer, author=author, report=(archive_copy / "import-report.md").read_text())


@pytest.fixture()
def fresh(tmp_path) -> Iterator[None]:
    with reticle(tmp_path / "reticle"):
        migrate.upgrade()
        staff()
        yield


# ---------------------------------------------------------------- a guide, as a reader sees it


def test_the_load_reports_success(world):
    assert world.result.status == 0, world.result.text
    assert "Load finished." in world.result.lines
    assert "  guide:     4 created" in world.result.lines
    assert "  page:      4 created, 1 skipped" in world.result.lines
    assert f"Full report: {world.archive / 'import-report.md'}" in world.result.lines


def test_a_viewer_reads_an_imported_guide(world):
    response = world.viewer.get(f"/api/guides/{GUIDE_15}")

    assert response.status_code == 200, response.text
    guide = response.json()
    assert guide["title"] == "Leica Stellaris 5 inverse (USZ) - How to get there"
    assert guide["summary"] == "How to get to the Stellaris 5 inverse in USZ."
    assert guide["status"] == "published" and guide["version"] == 1
    assert guide["difficulty"] == "very_easy"
    assert (guide["timeRequiredMinMinutes"], guide["timeRequiredMaxMinutes"]) == (None, 5)
    assert guide["tags"] == ["location-access", "stellusz"]
    assert guide["author"]["displayName"] == "ada.example"
    assert guide["conclusion"] == ""
    assert [step["title"] for step in guide["steps"]] == ["", "Every kind of bullet"]


def test_vendor_dates_are_kept(world):
    guide = world.viewer.get(f"/api/guides/{GUIDE_15}").json()

    assert instant(guide["createdAt"]) == datetime.fromtimestamp(1554800000, timezone.utc)
    assert instant(guide["publishedAt"]) == datetime.fromtimestamp(1561989541, timezone.utc)
    assert instant(guide["updatedAt"]) == datetime.fromtimestamp(1788435314, timezone.utc)


def test_the_introduction_is_plain_text_with_the_link_spelled_out(world):
    guide = world.viewer.get(f"/api/guides/{GUIDE_15}").json()

    assert guide["introduction"] == "Find the room first. See cite Huygens (https://svi.nl/HowtoCiteHuygens)."


def test_wiki_source_is_used_where_the_vendor_sent_no_rendering(world):
    guide = world.viewer.get(f"/api/guides/{GUIDE_27}").json()

    assert guide["introduction"] == "Start with getting there. Read the manual."
    assert guide["conclusion"] == "Done."
    assert (guide["timeRequiredMinMinutes"], guide["timeRequiredMaxMinutes"]) == (30, 30)
    assert guide["difficulty"] == "moderate"


def test_every_bullet_colour_icon_and_level_arrives(world):
    bullets = world.viewer.get(f"/api/guides/{GUIDE_15}").json()["steps"][1]["bullets"]

    assert [(bullet["text"], bullet["color"], bullet["icon"], bullet["level"]) for bullet in bullets] == [
        ("Black bullet", "black", None, 0),
        ("Red, nested", "red", None, 1),
        ("Orange, nested twice", "orange", None, 2),
        ("Yellow", "yellow", None, 0),
        ("Green", "green", None, 0),
        ("Light blue", "light_blue", None, 0),
        ("Blue", "blue", None, 0),
        ("Violet", "violet", None, 0),
        ("A note with a SVI Nyquist Calculator (https://svi.nl/NyquistCalculator)", "black", "note", 0),
        ('Mind the "laser"', "black", "caution", 0),
        ("Book the next slot", "black", "reminder", 0),
        ("A site-defined bullet", "green", None, 0),
        ("Too deep", "black", None, 2),
    ]
    assert not any(re.search(r"'''|\*\*|\[|<", bullet["text"]) for bullet in bullets), "no markup reaches a plain-text bullet"


def test_an_arrow_becomes_an_annotation_on_the_clean_source_image(world):
    (media,) = world.viewer.get(f"/api/guides/{GUIDE_15}").json()["steps"][0]["media"]

    assert (media["kind"], media["width"], media["height"]) == ("image", 800, 600)
    (arrow,) = media["annotations"]
    assert (arrow["shape"], arrow["color"]) == ("arrow", "red")
    assert (arrow["x"], arrow["y"], arrow["width"], arrow["height"]) == pytest.approx((505 / 800, 440 / 600, -320 / 800, -2 / 600), abs=1e-4)


def test_three_images_on_one_step_with_their_markers(world):
    letterboxed, cropped, plain = world.viewer.get(f"/api/guides/{GUIDE_15}").json()["steps"][1]["media"]

    assert (letterboxed["width"], letterboxed["height"]) == (710, 451), "the padding the vendor added is not part of the picture"
    assert [(shape["shape"], shape["color"]) for shape in letterboxed["annotations"]] == [("rectangle", "red"), ("arrow", "green")]
    rectangle = letterboxed["annotations"][0]
    assert (rectangle["x"], rectangle["y"], rectangle["width"], rectangle["height"]) == pytest.approx((3 / 710, 29 / 451, 122 / 710, 178 / 451), abs=1e-4)

    assert (cropped["width"], cropped["height"]) == (696, 522), "the author's crop is applied to the clean source"
    (frame,) = cropped["annotations"]
    assert frame["shape"] == "rectangle" and frame["width"] == pytest.approx(0.993, abs=2e-3)

    assert (plain["width"], plain["height"], plain["annotations"]) == (320, 240, [])


def test_imported_media_is_served_to_a_viewer(world):
    guide = world.viewer.get(f"/api/guides/{GUIDE_15}").json()

    for step in guide["steps"]:
        for media in step["media"]:
            response = world.viewer.get(media["url"])
            assert response.status_code == 200
            with Image.open(BytesIO(response.content)) as image:
                assert image.size == (media["width"], media["height"])


def test_the_clean_image_really_is_clean(world):
    """The red arrow is an annotation now; it must not also be in the pixels."""
    media = world.viewer.get(f"/api/guides/{GUIDE_15}").json()["steps"][0]["media"][0]

    with Image.open(BytesIO(world.viewer.get(media["url"]).content)) as image:
        red, green, blue = image.convert("RGB").getpixel((345, 439))
    assert not (red > 150 and green < 90 and blue < 60)


def test_a_video_step_plays_and_seeks(world):
    step = world.viewer.get(f"/api/guides/{GUIDE_27}").json()["steps"][0]

    assert step["title"] == "Mount ViewFinder"
    assert [bullet["text"] for bullet in step["bullets"]] == ["Mount the ViewFinder.", "Close the doors."]
    (video,) = step["media"]
    assert (video["kind"], video["width"], video["annotations"]) == ("video", None, [])
    whole = world.viewer.get(video["url"])
    part = world.viewer.get(video["url"], headers={"Range": "bytes=0-99"})
    assert whole.status_code == 200 and whole.headers["content-type"] == "video/mp4" and len(whole.content) == 4096
    assert part.status_code == 206 and len(part.content) == 100


def test_a_step_with_four_images_is_split_and_reported(world):
    steps = world.viewer.get(f"/api/guides/{GUIDE_27}").json()["steps"]

    assert [(step["title"], len(step["bullets"]), len(step["media"])) for step in steps] == [
        ("Mount ViewFinder", 2, 1),
        ("Four pictures", 1, 3),
        ("Four pictures (continued)", 0, 1),
        ("Hard cases", 1, 2),
        ("Embedded", 1, 0),
    ]
    assert [step["orderIndex"] for step in steps] == [0, 1, 2, 3, 4]
    assert "step 2: It held 4 media items; Reticle allows 3 per step, so 1 continuation step(s) follow it." in world.report


def test_markers_that_cannot_be_converted_keep_the_burned_in_picture(world):
    text_marker, wrong_metadata = world.viewer.get(f"/api/guides/{GUIDE_27}").json()["steps"][3]["media"]

    assert text_marker["annotations"] == [] and wrong_metadata["annotations"] == []
    with Image.open(BytesIO(world.viewer.get(wrong_metadata["url"]).content)) as image:
        red, green, blue = image.convert("RGB").getpixel((150, 75))
    assert red > 150 and green < 90, "the arrow the vendor drew is still in the picture"
    assert "Image 600: marker type “TextMarker” has no Reticle equivalent. The marked-up picture is used as it is." in world.report
    assert "Image 950: the converted markers do not line up with the markers visible in the picture." in world.report


def test_private_guides_are_drafts_that_viewers_cannot_see(world):
    assert world.viewer.get("/api/guides/internal-laser-safety-interlock").status_code == 404
    draft = world.author.get("/api/guides/internal-laser-safety-interlock").json()

    assert draft["status"] == "draft" and draft["version"] == 0 and draft["publishedAt"] is None
    assert sorted(guide["title"] for guide in world.viewer.get("/api/guides").json()) == [
        "Leica Stellaris 5 inverse (USZ) - How to get there", "MesoSPIM - Part 1: Start-up", "Work in progress"
    ]
    picture = draft["steps"][0]["media"][0]["url"]
    assert world.author.get(picture).status_code == 200
    assert world.viewer.get(picture).status_code == 404, "a draft's pictures are as private as the draft"
    assert "Guides that were private, unpublished or archived on the old site were imported as drafts." in world.report


def test_published_guides_have_a_first_revision_dated_as_on_the_vendor_site(world):
    guide = world.author.get(f"/api/guides/{GUIDE_15}").json()
    revisions = world.author.get(f"/api/guides/{guide['id']}/revisions").json()

    assert [revision["version"] for revision in revisions] == [1]
    assert instant(revisions[0]["publishedAt"]) == datetime.fromtimestamp(1561989541, timezone.utc)
    snapshot = world.author.get(f"/api/guides/{guide['id']}/revisions/1").json()
    assert snapshot["title"] == guide["title"] and len(snapshot["steps"]) == 2


def test_an_imported_guide_exports_as_a_pdf(world):
    response = world.viewer.get(f"/api/guides/{GUIDE_15}/pdf")

    assert response.status_code == 200 and response.headers["content-type"] == "application/pdf"
    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(response.content)).pages)
    assert "Leica Stellaris 5 inverse (USZ)" in text and "Orange, nested twice" in text


def test_imported_guides_are_found_by_search(world):
    results = world.viewer.get("/api/search", params={"q": "Pathology building"}).json()

    assert [result["guide"]["slug"] for result in results if result["kind"] == "guide"] == [GUIDE_15]


def test_unknown_values_are_mapped_and_reported(world):
    guide = world.viewer.get("/api/guides/work-in-progress").json()

    assert guide["difficulty"] == "moderate" and guide["status"] == "published"
    assert instant(guide["createdAt"]) > instant(guide["publishedAt"]), "the vendor's own odd ordering is kept, not corrected"
    for line in (
        "Difficulty 'Legendary' is not a known value; set to “moderate”.",
        "Flagged GUIDE_IN_PROGRESS on the old site",
        "Bullet style 'custom_17' is not a known value; shown as a green bullet.",
        "Indent level 5 was set to 2.",
        "Tag “!!!” has no letter or digit in it and was left out.",
        "is longer than 60 characters and was left out.",
        "step 4: The step had no title, no text and no importable media; it was left out.",
        "step 5: Media of type “embed” has no Reticle equivalent and was left out.",
        "2 link(s) are now plain text",
        "Tag spellings StellUSZ, stellusz are one tag in Reticle (“stellusz”)",
    ):
        assert line in world.report, line


# ---------------------------------------------------------------- categories, tags and pages


def test_the_category_tree_uses_display_titles_and_hides_holding_categories(world):
    categories = {category["name"]: category for category in world.viewer.get("/api/categories").json()}

    assert "Confocal Microscopy" in categories and "Basic Guides" not in categories
    assert "Light Microscopy" in categories and "Light Micrscopy" not in categories
    assert "Center for Microscopy and Image Analysis" not in categories and "Root" not in categories
    hidden = {name for name, category in categories.items() if category["isHidden"]}
    assert hidden == {"basics access and IT - hidden", "LS - hidden guides", "Image processing - hiden", "Confocal - hidden guides", "Imported – uncategorised"}

    def parent(name: str) -> str | None:
        parent_id = categories[name]["parentId"]
        return next((other["name"] for other in categories.values() if other["id"] == parent_id), None)

    assert parent("Confocal Microscopy") == "Light Microscopy"
    assert parent("IT") == "Basics and IT"
    assert parent("Confocal - hidden guides") == "Confocal Microscopy", "from the parent's list of children"
    assert parent("LS - hidden guides") == "Lightsheet microscopy", "from the category's own ancestors"
    assert parent("Light Microscopy") is None and parent("Image processing - hiden") is None
    assert categories["Confocal Microscopy"]["description"].startswith("In this category you find guides")
    assert categories["Confocal Microscopy"]["slug"] == "confocal-microscopy"


def test_guides_sit_in_their_holding_categories(world):
    categories = {category["id"]: category["name"] for category in world.viewer.get("/api/categories").json()}

    assert categories[world.viewer.get(f"/api/guides/{GUIDE_15}").json()["categoryId"]] == "basics access and IT - hidden"
    assert categories[world.viewer.get(f"/api/guides/{GUIDE_27}").json()["categoryId"]] == "LS - hidden guides"
    assert categories[world.viewer.get("/api/guides/work-in-progress").json()["categoryId"]] == "Confocal Microscopy"
    assert categories[world.author.get("/api/guides/internal-laser-safety-interlock").json()["categoryId"]] == "Imported – uncategorised"


def test_a_category_wiki_becomes_the_landing_page_with_working_guide_lists(world):
    categories = {category["name"]: category for category in world.viewer.get("/api/categories").json()}
    page = world.viewer.get(f"/api/categories/{categories['Confocal Microscopy']['id']}/page").json()

    assert page["isLanding"] is True and page["status"] == "published" and page["title"] == "Confocal Microscopy"
    assert page["summary"] == "Guides for the confocal microscopes."
    assert page["body"] == (
        "## Leica Stellaris 5 inverse (USZ)\n\n```guidelist\ntags: stellusz\n```\n\n"
        "## Lightsheet 🔬\n\n```guidelist\ntags: lightsheet\nheading: All lightsheet guides\n```\n"
    )
    assert world.viewer.get(f"/api/media/{page['heroMediaId']}").status_code == 200

    known = {tag["slug"]: tag for tag in world.viewer.get("/api/tags").json()}
    asked = re.findall(r"^tags: (.+)$", page["body"], flags=re.MULTILINE)
    assert asked == ["stellusz", "lightsheet"]
    assert set(asked) <= set(known), "every tag a guide list asks for is a tag some guide carries"
    listed = {tag: [guide["title"] for guide in world.viewer.get("/api/guides", params={"tags": tag}).json()] for tag in asked}
    assert sorted(listed["stellusz"]) == ["Leica Stellaris 5 inverse (USZ) - How to get there", "Work in progress"]
    assert listed["lightsheet"] == ["MesoSPIM - Part 1: Start-up"]
    assert known["stellusz"]["name"] == "StellUSZ" and known["stellusz"]["guideCount"] == 2


def test_a_holding_categorys_own_page_is_its_landing_page(world):
    categories = {category["name"]: category for category in world.viewer.get("/api/categories").json()}
    page = world.viewer.get(f"/api/categories/{categories['LS - hidden guides']['id']}/page").json()

    assert page["body"] == "Internal list.\n\n```guidelist\ntags: mesospim\n```\n"
    assert world.viewer.get(f"/api/categories/{categories['Light Microscopy']['id']}/page").json() is None, "an empty page is not imported"


def test_a_standalone_wiki_page_with_a_table_links_and_an_image(world):
    page = world.viewer.get(f"/api/pages/{SEQIF}").json()

    assert page["title"] == "Strategy to Run a Full Multiplex SeqIF" and page["summary"] == "COMET"
    assert page["isLanding"] is False and page["categoryId"] is None and page["status"] == "published"
    assert page["author"]["displayName"] == "ada.example"
    assert instant(page["updatedAt"]) == datetime.fromtimestamp(1626439287, timezone.utc)
    body = page["body"]
    assert "Run the **full** panel *once*." in body
    assert f"[the start-up guide](/g/{GUIDE_27})" in body
    assert f"[how to get there](/g/{GUIDE_15})" in body, "a link to the old site is rewritten"
    assert "[the protocol](https://example.org/protocol)" in body
    assert "- Prepare\n    - Buffers\n- Run" in body
    assert "| Marker | Dilution |\n| :--- | :--- |\n| CD3 | 1:100 |\n| CD8 | 1:200 |" in body
    assert "\\[quiz|3\\]" in body and "A page that was never written" in body

    image = re.search(r"!\[The panel layout\]\((/api/media/[0-9A-Z]{26})\)", body)
    assert image and world.viewer.get(image.group(1)).status_code == 200, "the page's image is readable by viewers"
    assert "Unrecognised markup kept as text: [quiz|3]" in world.report
    assert "Internal link to “A page that was never written” matches no imported page; kept as text." in world.report


def test_the_sites_root_page_becomes_an_ordinary_page(world):
    page = world.viewer.get("/api/pages/center-for-microscopy-and-image-analysis").json()

    assert page["isLanding"] is False and page["categoryId"] is None
    assert page["body"] == (
        "Welcome. Start with [confocal microscopy](/c/confocal-microscopy) or the "
        f"[Strategy to Run a Full Multiplex SeqIF Without Prior Optimization](/w/{SEQIF}).\n"
    )


def test_vendor_boilerplate_pages_are_not_loaded(world):
    titles = [page["title"] for page in world.author.get("/api/pages").json()]

    assert "Answers FAQ" not in titles
    assert "1 page(s) in the INFO namespace are in the archive but were not loaded." in world.report


# ---------------------------------------------------------------- people


def test_an_existing_account_is_matched_by_email_and_left_as_it_was(world):
    with db.SessionLocal() as session:
        ada = session.scalars(select(User).where(User.email == "ada.example@zmb.example")).one()
        assert (ada.role, ada.is_active) == ("author", True)
        assert verify_password(ada.password_hash, TEST_PASSWORD)


def test_unknown_authors_become_inactive_accounts_that_cannot_sign_in(world):
    with db.SessionLocal() as session:
        created = {user.email: user for user in session.scalars(select(User).where(User.password_hash == UNUSABLE_PASSWORD_HASH))}

        assert set(created) == {"new.author@zmb.example", "dozuki-user-26@import.invalid", "imported-content@import.invalid"}
        assert all(user.role == "viewer" and not user.is_active for user in created.values())
        assert created["new.author@zmb.example"].display_name == "New Author"
        assert not verify_password(UNUSABLE_PASSWORD_HASH, UNUSABLE_PASSWORD_HASH)

    with TestClient(app) as raw:
        for password in (TEST_PASSWORD, UNUSABLE_PASSWORD_HASH, ""):
            assert ApiClient(raw).login("new.author@zmb.example", password).status_code in {401, 422}
    assert world.viewer.get(f"/api/guides/{GUIDE_27}").json()["author"]["displayName"] == "New Author"
    assert "user 26: No e-mail address in the archive for “z mbstaff”; a placeholder account stands in." in world.report


def test_every_import_is_in_the_audit_log(world):
    with db.SessionLocal() as session:
        entries = session.scalars(select(AuditLog).where(AuditLog.action.in_(["guide.import", "page.import"]))).all()

        assert len(entries) == 8
        assert {entry.detail["source"] for entry in entries} == {HOST}
        assert sorted(entry.detail["vendorId"] for entry in entries if entry.action == "guide.import") == ["15", "27", "422", "430"]


def test_the_report_is_complete_and_readable(world):
    report = world.report

    assert report.startswith("# Import report\n")
    assert "- **Source site:** zmb.dozuki.com" in report and "- **Mode:** live, public content published" in report
    assert "- **Database:** sqlite:///" in report
    assert "| guide | 4 | 0 | 0 | 0 | 0 |" in report
    assert "## Skipped\n\n- page CATEGORY “Light Microscopy”: the page has no content" in report
    assert "### Steps split because they held more media than a Reticle step allows (1)" in report
    assert "### Images imported with their markers burned in (not editable annotations) (2)" in report
    assert "Holding categories marked hidden (kept out of the browsable tree):" in report
    assert "Not available from the vendor API and therefore not imported: view counts" in report
    assert f"- guide 15 “Leica Stellaris 5 inverse (USZ) - How to get there” — published, /g/{GUIDE_15} — public on the old site" in report
    assert "- guide 430 “Internal: laser safety interlock” — draft, /g/internal-laser-safety-interlock — private or unpublished on the old site" in report
    assert f"- page WIKI “Strategy to Run a Full Multiplex SeqIF” — published, /w/{SEQIF} — shown to visitors who were not signed in on the old site" in report
    assert "- page CATEGORY “LS - hidden guides” — published, /w/ls-hidden-guides — the landing page of its category" in report
    assert "- **Database write lock:** 9 write transactions, " in report
    assert "## Failed" not in report


# ---------------------------------------------------------------- running it again


def test_a_second_run_changes_nothing(fresh, archive):
    first = load(archive)
    before = {model: count(model) for model in (Guide, Page, Category, Media, User, Tag, Step, ImportRecord, GuideRevision, PageRevision)}
    files = media_files()
    with db.SessionLocal() as session:
        stamps = {guide.slug: (guide.updated_at, guide.version) for guide in session.scalars(select(Guide))}

    second = load(archive)

    assert first.status == 0 and second.status == 0, second.text
    assert "  guide:     4 unchanged" in second.lines
    assert "  page:      4 unchanged, 1 skipped" in second.lines
    assert "  category:  9 unchanged" in second.lines
    assert "  warnings:  0" in second.lines
    assert {model: count(model) for model in before} == before
    assert media_files() == files
    with db.SessionLocal() as session:
        assert {guide.slug: (guide.updated_at, guide.version) for guide in session.scalars(select(Guide))} == stamps


def test_a_dry_run_writes_nothing(fresh, archive):
    before = {model: count(model) for model in (Guide, Page, Category, Media, User, Tag, ImportRecord, AuditLog)}

    result = load(archive, "--dry-run")

    assert result.status == 0, result.text
    assert "DRY RUN — nothing was written to Reticle." in result.lines
    assert "  guide:     4 created" in result.lines and "  page:      4 created, 1 skipped" in result.lines
    assert {model: count(model) for model in before} == before
    assert not get_settings().media_root.exists()
    assert not (archive / "import-report.md").exists()
    report = (archive / "import-report-dry-run.md").read_text()
    assert "- **Mode:** DRY RUN — nothing was written" in report
    assert "It held 4 media items" in report, "a dry run predicts the same warnings"

    for_real = load(archive)
    assert for_real.status == 0 and "  guide:     4 created" in for_real.lines, "and it left nothing behind to trip over"


def test_content_edited_in_reticle_is_not_overwritten(fresh, archive):
    load(archive)
    with signed_in("ada.example@zmb.example") as author:
        guide = author.get(f"/api/guides/{GUIDE_15}").json()
        saved = author.put(f"/api/guides/{guide['id']}", json=document_from(guide, title="Stellaris 5 (USZ): finding the room"))
        assert saved.status_code == 200, saved.text
    edit_json(archive, "api/guides/15/guide.json", lambda document: document.update(summary="Changed on the vendor site too."))

    result = load(archive)

    assert result.status == 0, result.text
    assert "  guide:     3 unchanged, 1 skipped" in result.lines
    report = (archive / "import-report.md").read_text()
    assert "- guide 15 “Leica Stellaris 5 inverse (USZ) - How to get there”: edited in Reticle since it was imported; left untouched (use --force to overwrite)" in report
    with signed_in("ada.example@zmb.example") as author:
        kept = author.get(f"/api/guides/{GUIDE_15}").json()
    assert kept["title"] == "Stellaris 5 (USZ): finding the room" and kept["summary"] == "How to get to the Stellaris 5 inverse in USZ."


def test_force_overwrites_an_edit_and_records_a_new_version(fresh, archive):
    load(archive)
    with signed_in("ada.example@zmb.example") as author:
        guide = author.get(f"/api/guides/{GUIDE_15}").json()
        author.put(f"/api/guides/{guide['id']}", json=document_from(guide, title="Edited here"))

    result = load(archive, "--force", "--guide", "15")

    assert result.status == 0 and "  guide:     1 updated" in result.lines
    with signed_in("ada.example@zmb.example") as author:
        restored = author.get(f"/api/guides/{GUIDE_15}").json()
        assert restored["title"] == "Leica Stellaris 5 inverse (USZ) - How to get there"
        assert restored["version"] == 2 and restored["id"] == guide["id"]
        assert [revision["version"] for revision in author.get(f"/api/guides/{guide['id']}/revisions").json()] == [2, 1]
    assert count(Guide) == 4


def test_a_change_on_the_vendor_side_updates_the_same_guide(fresh, archive):
    load(archive)
    with db.SessionLocal() as session:
        original_id = session.scalars(select(Guide.id).where(Guide.slug == GUIDE_27)).one()
    media_before = count(Media)

    def revise(document: dict) -> None:
        document["title"] = "MesoSPIM - Part 1: Start-up, revised"
        document["modified_date"] += 3600
        document["steps"] = document["steps"][:1]
        document["public"] = False

    edit_json(archive, "api/guides/27/guide.json", revise)
    result = load(archive)

    assert result.status == 0, result.text
    assert "  guide:     1 updated, 3 unchanged" in result.lines
    with signed_in("ada.example@zmb.example") as author:
        updated = author.get(f"/api/guides/{GUIDE_27}").json()
    assert updated["id"] == original_id, "the slug and the identity stay; links to it keep working"
    assert updated["title"] == "MesoSPIM - Part 1: Start-up, revised" and len(updated["steps"]) == 1
    assert updated["status"] == "draft", "it is no longer public on the vendor side"
    assert instant(updated["updatedAt"]) == datetime.fromtimestamp(1780923676 + 3600, timezone.utc)
    assert count(Media) == media_before, "media already imported is reused"
    assert count(Guide) == 4

    assert "  guide:     4 unchanged" in load(archive).lines


def test_a_page_edited_in_reticle_is_kept_and_a_changed_one_is_updated(fresh, archive):
    load(archive)
    with signed_in("ada.example@zmb.example") as author:
        page = author.get(f"/api/pages/{SEQIF}").json()
        assert author.put(f"/api/pages/{page['id']}", json=document_from(page, body="Rewritten in Reticle.")).status_code == 200
    edit_json(archive, "api/wikis/WIKI/108.json", lambda document: document.update(contents_raw="== Vendor rewrite =="))
    edit_json(archive, "api/wikis/CATEGORY/23.json", lambda document: document.update(contents_raw="== New heading ==\n\n[guidelist|tags=StellUSZ]"))

    result = load(archive)

    assert "  page:      1 updated, 2 unchanged, 2 skipped" in result.lines
    with signed_in("ada.example@zmb.example") as author:
        assert author.get(f"/api/pages/{SEQIF}").json()["body"] == "Rewritten in Reticle."
    with signed_in("viewer@zmb.example") as viewer:
        landing = viewer.get("/api/pages/confocal-microscopy").json()
    assert landing["body"] == "## New heading\n\n```guidelist\ntags: stellusz\n```\n"
    assert landing["version"] == 2 and landing["isLanding"] is True
    assert count(Page) == 4


# ---------------------------------------------------------------- options


def test_as_drafts_publishes_nothing(fresh, archive):
    result = load(archive, "--as-drafts")

    assert result.status == 0, result.text
    with signed_in("viewer@zmb.example") as viewer:
        assert viewer.get("/api/guides").json() == [] and viewer.get("/api/pages").json() == []
    with db.SessionLocal() as session:
        assert {guide.status for guide in session.scalars(select(Guide))} == {"draft"}
        assert {page.status for page in session.scalars(select(Page))} == {"draft"}
    assert count(GuideRevision) == 0 and count(PageRevision) == 0
    report = (archive / "import-report.md").read_text()
    assert "everything as drafts" in report and "Everything was imported as a draft (--as-drafts)." in report


def test_owner_email_gives_everything_to_one_account(fresh, archive):
    result = load(archive, "--owner-email", " Admin@ZMB.example ")

    assert result.status == 0, result.text
    with db.SessionLocal() as session:
        admin = session.scalars(select(User).where(User.email == "admin@zmb.example")).one()
        assert {guide.author_id for guide in session.scalars(select(Guide))} == {admin.id}
        assert {page.author_id for page in session.scalars(select(Page))} == {admin.id}
        assert {media.uploaded_by_id for media in session.scalars(select(Media))} == {admin.id}
    assert count(User) == 3, "no author accounts are created"
    assert "All imported content is owned by admin@zmb.example" in (archive / "import-report.md").read_text()


def test_an_unknown_owner_stops_the_load_before_it_starts(fresh, archive):
    result = load(archive, "--owner-email", "nobody@zmb.example")

    assert result.status == 2
    assert "--owner-email nobody@zmb.example is not an existing Reticle account" in result.text
    assert count(Guide) == 0 and count(Category) == 0


def test_markers_can_be_left_burned_into_the_pictures(fresh, archive):
    result = load(archive, "--markers", "burned")

    assert result.status == 0, result.text
    with signed_in("viewer@zmb.example") as viewer:
        guide = viewer.get(f"/api/guides/{GUIDE_15}").json()
        media = [item for step in guide["steps"] for item in step["media"]]
        assert all(item["annotations"] == [] for item in media)
        assert (media[1]["width"], media[1]["height"]) == (710, 532), "the vendor's letterboxed rendering, as it was"
    report = (archive / "import-report.md").read_text()
    assert "Image markers were left burned into the pictures (--markers burned)" in report
    assert "markers burned in (not editable annotations)" not in report


def test_the_arrow_direction_can_be_forced(fresh, archive):
    load(archive, "--arrow-head", "start", "--guide", "15")

    with signed_in("viewer@zmb.example") as viewer:
        arrow = viewer.get(f"/api/guides/{GUIDE_15}").json()["steps"][0]["media"][0]["annotations"][0]
    assert (arrow["x"], arrow["width"]) == pytest.approx((185 / 800, 320 / 800), abs=1e-4)


def test_a_trial_run_can_be_limited_to_chosen_guides(fresh, archive):
    result = load(archive, "--guide", "15", "--guide", "422", "--namespaces", "wiki")

    assert "  guide:     2 created" in result.lines and "  page:      1 created" in result.lines
    with db.SessionLocal() as session:
        assert sorted(session.scalars(select(Guide.title))) == ["Leica Stellaris 5 inverse (USZ) - How to get there", "Work in progress"]
        assert session.scalars(select(Page.title)).all() == ["Strategy to Run a Full Multiplex SeqIF"]
    assert "page(s) in the CATEGORY namespace are in the archive but were not loaded. Pass --namespaces to include them." in (archive / "import-report.md").read_text()


def test_info_pages_load_only_when_asked_for(fresh, archive):
    load(archive, "--namespaces", "INFO", "--report", str(archive / "custom" / "report.md"))

    with db.SessionLocal() as session:
        assert session.scalars(select(Page.title)).all() == ["Answers FAQ"]
    assert (archive / "custom" / "report.md").is_file() and not (archive / "import-report.md").exists()


# ---------------------------------------------------------------- failures stay local


def test_one_bad_guide_does_not_stop_the_others(fresh, archive):
    step = {"title": "x", "lines": [{"text_raw": "t", "text_rendered": "t", "bullet": "black", "level": 0}], "media": {"type": "image", "data": []}, "orderby": 1}
    edit_json(archive, "api/guides/27/guide.json", lambda document: document.update(steps=[dict(step, orderby=number) for number in range(201)]))
    (archive / "api/guides/422/guide.json").unlink()
    manifest = json.loads((archive / "manifest.json").read_text())
    manifest["items"]["guide:422"] = {"kind": "guide", "status": "failed", "error": "GET /guides/422: HTTP 500 after 6 attempts"}
    (archive / "manifest.json").write_text(json.dumps(manifest))

    result = load(archive)

    assert result.status == 1
    assert "  guide:     2 created, 2 failed" in result.lines
    assert "  FAILED:    2 item(s) — see the report" in result.lines
    report = (archive / "import-report.md").read_text()
    assert "## Failed — nothing was written for these" in report
    assert "- guide 27 “MesoSPIM - Part 1: Start-up”: the converted document is not valid (steps: List should have at most 200 items" in report
    assert "- guide 422 “Work in progress”: LookupError: the guide is not in the archive (GET /guides/422: HTTP 500 after 6 attempts)" in report
    with db.SessionLocal() as session:
        assert sorted(session.scalars(select(Guide.slug))) == sorted([GUIDE_15, "internal-laser-safety-interlock"])
        assert session.scalars(select(User).where(User.email == "new.author@zmb.example")).one_or_none() is None, "the failed guide's author was rolled back with it"
    assert count(Page) == 4, "pages still load"

    files_before = media_files()
    edit_json(archive, "api/guides/27/guide.json", lambda document: document.update(steps=document["steps"][:2]))
    retried = load(archive)
    assert "  guide:     1 created, 2 unchanged, 1 failed" in retried.lines
    assert len(media_files()) == len(files_before), "the guide needed no media that was not already stored"


def test_media_written_for_a_guide_that_then_fails_is_removed_again(fresh, archive):
    def poison(document: dict) -> None:
        document["steps"][0]["lines"][0]["bullet"] = "black"
        document["steps"] = document["steps"] * 120  # more steps than a guide may have, after its media was stored

    edit_json(archive, "api/guides/27/guide.json", poison)

    result = load(archive, "--guide", "27", "--namespaces", "ITEM")

    assert result.status == 1
    assert count(Media) == 0 and media_files() == []
    assert count(ImportRecord) == count(Category)


def test_missing_media_is_reported_and_the_guide_still_loads(fresh, archive):
    (archive / "files/images/901.png").unlink()
    (archive / "files/images/477.jpg").unlink()
    (archive / "files/images/600.jpg").write_bytes(b"not an image at all")
    (archive / "files/videos/137.mp4").write_bytes(b"RIFF....AVI LIST")
    (archive / "api/guides/15/tags.json").unlink()
    edit_json(archive, "api/wikis/WIKI/108.json", lambda document: document.update(contents_raw="[image|901] and [image|4711]"))

    result = load(archive)

    assert result.status == 0, result.text
    report = (archive / "import-report.md").read_text()
    for line in (
        "step 2: Image 901 is not in the archive.",
        "Image 507: its clean source image 477 is not in the archive. The marked-up picture is used as it is.",
        "Image 600 could not be imported: UnidentifiedImageError",
        "Video 137 is not an MP4 or WebM file a browser can play; it was left out.",
        "Its tags are not in the archive; imported without tags, so no guide list will show it.",
        "page WIKI “Strategy to Run a Full Multiplex SeqIF”: Image 901 is not in the archive.",
        "Image 4711 is not in the archive; a placeholder was left in the text.",
    ):
        assert line in report, line
    with signed_in("viewer@zmb.example") as viewer:
        steps = viewer.get(f"/api/guides/{GUIDE_27}").json()["steps"]
        assert [(step["title"], len(step["media"])) for step in steps] == [("Mount ViewFinder", 0), ("Four pictures", 3), ("Hard cases", 1), ("Embedded", 0)]
        burned = viewer.get(f"/api/guides/{GUIDE_15}").json()
        assert burned["steps"][0]["media"][0]["annotations"] == [] and burned["tags"] == []
        assert viewer.get(f"/api/pages/{SEQIF}").json()["body"] == "\\[missing image 901\\] and \\[missing image 4711\\]\n"


def test_a_marked_up_picture_missing_from_the_archive_cannot_be_checked(fresh, archive):
    (archive / "files/images/507.jpg").unlink()

    load(archive, "--guide", "15")

    report = (archive / "import-report.md").read_text()
    assert "Image 507: the marked-up picture itself is not in the archive, so the markers cannot be checked." in report
    assert "step 1: Image 507 is not in the archive." in report


def test_a_clean_source_that_disagrees_with_its_metadata_is_not_trusted(fresh, archive):
    photo(640, 480, 1).save(archive / "files/images/477.jpg", format="JPEG")
    (archive / "files/images/14435.png").write_bytes(b"\x89PNG\r\n\x1a\n truncated")

    load(archive, "--guide", "15")

    report = (archive / "import-report.md").read_text()
    assert "Image 507: the clean source file is 640×480 but the metadata says 800×600, so marker positions cannot be trusted." in report
    assert "Image 14438: the clean source could not be processed (" in report


def test_pictures_too_large_for_reticle_are_scaled_down_not_dropped(tmp_path, archive):
    with reticle(tmp_path / "reticle", RETICLE_MAX_IMAGE_DIMENSION="500"):
        migrate.upgrade()
        staff()
        result = load(archive, "--guide", "15")

        assert result.status == 0, result.text
        with signed_in("viewer@zmb.example") as viewer:
            guide = viewer.get(f"/api/guides/{GUIDE_15}").json()
        arrow_image, letterboxed, cropped, small = [media for step in guide["steps"] for media in step["media"]]
        assert (arrow_image["width"], arrow_image["height"]) == (500, 375)
        assert arrow_image["annotations"][0]["x"] == pytest.approx(505 / 800, abs=1e-4), "fractions survive a resize"
        assert max(letterboxed["width"], cropped["width"]) <= 500 and small["width"] == 320
        assert "Image 477 was re-encoded to fit Reticle’s limits (Images must be at most 500 pixels on each side.)" in (archive / "import-report.md").read_text()


def test_files_over_the_upload_limit_are_recompressed(tmp_path, archive):
    with reticle(tmp_path / "reticle", RETICLE_MAX_UPLOAD_BYTES="12000", RETICLE_MAX_VIDEO_BYTES="1000"):
        migrate.upgrade()
        staff()
        dry = load(archive, "--dry-run")
        result = load(archive)

        assert result.status == 0, result.text
        report = (archive / "import-report.md").read_text()
        assert "was re-encoded to fit Reticle’s limits (the file is larger than the upload limit)" in report
        assert "Video 137: Videos must be at most 0 MB." in report
        assert "Video 137: Videos must be at most 0 MB." in (archive / "import-report-dry-run.md").read_text()
        assert dry.status == 0
        with db.SessionLocal() as session:
            sizes = session.scalars(select(Media.byte_size)).all()
            assert sizes and max(sizes) <= 12000
            assert session.scalars(select(Media).where(Media.kind == "video")).all() == []
        assert not any(path.suffix == ".mp4" for path in media_files())


def test_a_photograph_stored_sideways_is_turned_upright(fresh, archive):
    exif = Image.Exif()
    exif[0x0112] = 6
    photo(240, 320, 3).save(archive / "files/images/904.png", format="PNG", exif=exif)

    load(archive, "--guide", "430", "--namespaces", "ITEM")

    with db.SessionLocal() as session:
        media = session.scalars(select(Media)).one()
        assert (media.width, media.height) == (320, 240)
        with Image.open(get_settings().media_root / media.storage_path) as stored:
            assert stored.size == (320, 240)
            assert stored.getexif().get(0x0112) is None
    assert "re-encoded" not in (archive / "import-report.md").read_text()


def test_a_category_that_already_has_a_landing_page_keeps_it(fresh, archive):
    with signed_in("admin@zmb.example") as admin:
        category = admin.post("/api/categories", json={"name": "Confocal Microscopy"}).json()
        page = admin.post("/api/pages", json={"title": "Our own confocal page", "categoryId": category["id"], "isLanding": True}).json()

    result = load(archive)

    assert result.status == 0, result.text
    report = (archive / "import-report.md").read_text()
    assert "Category “Confocal Microscopy” (internal title “Basic Guides”) matched an existing Reticle category of the same name and was reused." in report
    assert "page CATEGORY “Confocal Microscopy”: Its category already has a landing page in Reticle; imported as an ordinary page in that category." in report
    with db.SessionLocal() as session:
        imported = session.scalars(select(Page).where(Page.slug == "confocal-microscopy")).one()
        assert not imported.is_landing and imported.category_id == category["id"]
        assert session.get(Page, page["id"]).is_landing
        assert session.scalar(select(func.count()).select_from(Category).where(Category.name == "Confocal Microscopy")) == 1


def test_titles_and_slugs_that_collide_are_kept_apart(fresh, archive):
    def same_title(document: dict) -> None:
        document["title"] = "Leica Stellaris 5 inverse (USZ) - How to get there"

    edit_json(archive, "api/guides/27/guide.json", same_title)
    edit_json(archive, "api/guides/422/guide.json", lambda document: document.update(title="   "))
    edit_json(archive, "api/guides/430/guide.json", lambda document: document.update(title="T" * 300, summary="S" * 5000))

    result = load(archive)

    assert result.status == 0, result.text
    with db.SessionLocal() as session:
        slugs = sorted(session.scalars(select(Guide.slug)))
        assert GUIDE_15 in slugs and f"{GUIDE_15}-2" in slugs and "untitled-guide-422" in slugs
        long_one = session.scalars(select(Guide).where(Guide.title.like("TTT%"))).one()
        assert len(long_one.title) == 240 and long_one.title.endswith("…") and len(long_one.summary) == 4000
    report = (archive / "import-report.md").read_text()
    assert "Title shortened to 240 characters." in report and "Summary shortened to 4000 characters." in report


# ---------------------------------------------------------------- refusing to start


def test_a_database_that_was_never_migrated_is_refused(tmp_path, archive):
    with reticle(tmp_path / "reticle"):
        result = load(archive)

    assert result.status == 2
    assert "The database has not been initialised. Run `python -m app.migrate`" in result.text


def test_a_directory_that_is_not_an_archive_is_refused(fresh, tmp_path):
    result = load(tmp_path / "nothing-here")

    assert result.status == 2 and "has no readable manifest.json" in result.text


def test_an_unfinished_export_loads_what_it_has_and_says_so(fresh, archive):
    edit_json(archive, "manifest.json", lambda manifest: manifest.update(finished_at=None, authenticated=False))

    result = load(archive)

    assert result.status == 0
    report = (archive / "import-report.md").read_text()
    assert "(anonymously: public content only)" in report
    assert "The export did not run to completion; this load covers only what the archive holds." in report


# ---------------------------------------------------------------- internals worth pinning


def test_the_fingerprint_ignores_fields_that_describe_the_caller():
    payload = {"guideid": 1, "title": "T", "can_edit": False, "steps": [{"comments": [], "lines": [1]}]}
    other_account = {"title": "T", "guideid": 1, "can_edit": True, "favorited": True, "steps": [{"comments": ["hi"], "lines": [1]}]}

    assert fingerprint(payload, 1) == fingerprint(other_account, 1)
    assert fingerprint(payload, 1) != fingerprint({**payload, "title": "U"}, 1)
    assert fingerprint(payload, 1) != fingerprint(payload, 2)


def test_category_parents_survive_self_reference_and_cycles(fresh, archive):
    def know(title: str, **facts: Any) -> dict:
        return {"display": None, "parent": None, "description": "", "children": [], "ancestors": [], **facts}

    with db.SessionLocal() as session:
        loader = Loader(session, Archive(archive), LoadOptions(), get_settings(), log=lambda message: None)
        parents = loader._parents({
            "A": know("A", children=["A", "B"]),
            "B": know("B", children=["A"], display="Bee"),
            "C": know("C", parent="D"),
            "D": know("D", parent="C"),
            "E": know("E", parent="Gone"),
            "F": know("F", ancestors=["Bee", "A"]),
            "G": know("G", ancestors=["Twin"]),
            "T1": know("T1", display="Twin"),
            "T2": know("T2", display="Twin"),
            "Root": know("Root"),
            "H": know("H", parent="Root"),
        })

    assert parents["B"] == "A" and parents["A"] is None, "a category listing itself, or its own parent, as a child is ignored"
    assert parents["C"] is None or parents["D"] is None, "a cycle is broken"
    assert parents["E"] is None, "an unknown parent means top level"
    assert parents["F"] == "B", "ancestors name display titles"
    assert parents["G"] is None, "an ambiguous display title is not guessed at"
    assert parents["H"] is None, "children of the root are top level"


def test_small_helpers():
    assert [_positive_int(value) for value in (7, "7", 0, -1, True, "x", None, 1.5)] == [7, 7, None, None, None, None, None, None]
    assert Loader._explain(errors.conflict("That category already has a landing page.")) == "That category already has a landing page."
    assert Loader._explain(KeyError("srcid")) == "KeyError: 'srcid'"
    empty = Report()
    assert "## Warnings (0)\n\nNone." in empty.markdown() and "## Notes" not in empty.markdown()
    assert empty.summary() == "  warnings:  0"
    empty.note("once")
    empty.note("once")
    assert empty.notes == ["once"]


# ---------------------------------------------------------------- awkward content


def test_oversized_and_malformed_guide_content_is_trimmed_and_reported(fresh, archive):
    def awkward(document: dict) -> None:
        line = document["steps"][0]["lines"][0]
        document["steps"] = [
            {"orderby": 2, "title": "T" * 450, "lines": ["not a line", dict(line, text_rendered="", text_raw="B" * 4500)] + [dict(line)] * 205, "media": None},
            {"orderby": 1, "title": "Only a title", "lines": [], "media": {"type": "image", "data": []}},
            {"orderby": "last", "title": "No order", "lines": [dict(line, level="deep")], "media": {"type": "image", "data": []}},
        ]

    edit_json(archive, "api/guides/422/guide.json", awkward)
    (archive / "api/guides/422/tags.json").write_text(json.dumps(["", None, "  "] + [f"tag {number}" for number in range(35)]))

    result = load(archive, "--guide", "422", "--namespaces", "ITEM")

    assert result.status == 0, result.text
    with db.SessionLocal() as session:
        guide = session.scalars(select(Guide)).one()
        assert guide.status == "draft", "a step with nothing in it cannot be published"
        assert [step.title[:12] for step in guide.steps] == ["No order", "Only a title", "TTTTTTTTTTTT"]
        long_step = guide.steps[2]
        assert len(long_step.title) == 400 and len(long_step.bullets) == 200
        assert len(long_step.bullets[0].text) == 4000 and long_step.bullets[0].text.endswith("…")
        assert len(guide.tags) == 30
    report = (archive / "import-report.md").read_text()
    for line in (
        "Step title shortened to 400 characters.",
        "Text shortened to 4000 characters.",
        "6 bullets beyond the first 200 were left out.",
        "It has 35 tags; only the first 30 were kept.",
        "Indent level 'deep' was set to 0.",
        "### Content imported as a draft although the original was public (1)",
        "Imported as a draft: Step 2 (\"Only a title\") has neither text nor an image.",
    ):
        assert line in report, line


def test_awkward_pages_are_trimmed_refused_or_reported_one_by_one(fresh, archive):
    edit_json(archive, "api/wikis/WIKI/108.json", lambda document: document.update(
        display_title="W" * 300, description="D" * 5000, contents_raw="[image|900] and again [image|900]"))
    edit_json(archive, "api/wikis/CATEGORY/1.json", lambda document: document.update(contents_raw="The same picture: [image|900]"))
    edit_json(archive, "api/wikis/CATEGORY/23.json", lambda document: document.update(contents_raw="word " * 50_000))
    (archive / "api/wikis/CATEGORY/41.json").unlink()

    result = load(archive)

    assert result.status == 1
    assert "  page:      2 created, 1 skipped, 2 failed" in result.lines
    report = (archive / "import-report.md").read_text()
    assert "- page CATEGORY “Confocal Microscopy”: ValueError: the converted page is 250000 characters long; Reticle's limit is 200000" in report
    assert "- page CATEGORY “LS - hidden guides”: LookupError: the page is not in the archive (it was never exported)" in report
    assert "Title shortened to 240 characters." in report and "Summary shortened to 4000 characters." in report
    with db.SessionLocal() as session:
        long_page = session.scalars(select(Page).where(Page.title.like("WWW%"))).one()
        root_page = session.scalars(select(Page).where(Page.slug == "center-for-microscopy-and-image-analysis")).one()
        first, second = re.findall(r"/api/media/([0-9A-Z]{26})", long_page.body)
        assert first == second and first in root_page.body, "one vendor image is one Reticle upload, wherever it is used"
        assert len(long_page.summary) == 4000


def test_odd_shapes_in_the_category_data_are_tolerated(fresh, archive):
    edit_json(archive, "api/categories/all.json", lambda titles: titles.extend([12345, "C" * 250]))
    (archive / "api/categories/detail/IT.json").write_text("[]")
    edit_json(archive, "api/wikis/CATEGORY/index.json", lambda entries: entries.extend(["junk", {"wikiid": 99}, {"wikiid": "x", "title": "T"}]))
    edit_json(archive, "api/guides/index.json", lambda entries: entries.extend(["junk", {"guideid": None}]))
    edit_json(archive, "api/guides/27/guide.json", lambda document: document.update(category=""))
    edit_json(archive, "api/guides/index.json", lambda entries: [entry.update(category="") for entry in entries if isinstance(entry, dict) and entry.get("guideid") == 27])

    result = load(archive)

    assert result.status == 0, result.text
    with db.SessionLocal() as session:
        long_name = session.scalars(select(Category).where(Category.name.like("CCC%"))).one()
        assert len(long_name.name) == 200
        uncategorised = session.scalars(select(Category).where(Category.name == "Imported – uncategorised")).one()
        assert session.scalar(select(func.count()).select_from(Guide).where(Guide.category_id == uncategorised.id)) == 2
    assert "Name shortened to 200 characters." in (archive / "import-report.md").read_text()

    again = load(archive, "--force")
    assert again.status == 0 and "  guide:     4 updated" in again.lines
    assert count(Category) == 12, "the holding category for uncategorised guides is found again, not duplicated"


def test_media_files_that_went_missing_are_restored_by_a_forced_run(fresh, archive):
    load(archive)
    stored = media_files()
    shutil.rmtree(get_settings().media_root)

    result = load(archive, "--force")

    assert result.status == 0, result.text
    assert len(media_files()) == len(stored)
    with signed_in("viewer@zmb.example") as viewer:
        guide = viewer.get(f"/api/guides/{GUIDE_27}").json()
        assert all(viewer.get(media["url"]).status_code == 200 for step in guide["steps"] for media in step["media"])


def test_marker_notes_and_missing_videos_reach_the_report(fresh, archive):
    edit_json(archive, "api/media/images/507.json", lambda meta: meta["markupState"]["annotations"]["data"][0].update(color="nonsense"))
    (archive / "files/videos/137.mp4").unlink()

    result = load(archive, "--namespaces", "ITEM")

    assert result.status == 0, result.text
    report = (archive / "import-report.md").read_text()
    assert "### Marker conversions worth a glance (1)" in report
    assert "step 1: Image 507: marker colour 'nonsense' is not a known colour; drawn in red" in report
    assert "step 1: Video 137 is not in the archive." in report


def test_two_marked_versions_of_one_photograph_in_one_step_both_survive(fresh, archive):
    """They share a clean source, and a step cannot hold the same upload twice."""
    def twice(document: dict) -> None:
        step = document["steps"][0]
        first = step["media"]["data"][0]
        step["media"]["data"] = [first, dict(first, id=508), dict(first), document["image"], dict(document["image"])]
        document["difficulty"] = ""

    edit_json(archive, "api/guides/15/guide.json", twice)
    shutil.copy(archive / "api/media/images/507.json", archive / "api/media/images/508.json")
    edit_json(archive, "api/media/images/508.json", lambda meta: meta["image"].update(id=508))
    shutil.copy(archive / "files/images/507.jpg", archive / "files/images/508.jpg")
    edit_json(archive, "manifest.json", lambda manifest: manifest["items"].update(
        {"image-file:508": dict(manifest["items"]["image-file:507"], path="files/images/508.jpg")}))

    result = load(archive, "--guide", "15", "--namespaces", "ITEM")

    assert result.status == 0, result.text
    with signed_in("viewer@zmb.example") as viewer:
        guide = viewer.get(f"/api/guides/{GUIDE_15}").json()
    first_step, continued = guide["steps"][0], guide["steps"][1]
    media = first_step["media"]
    assert [len(item["annotations"]) for item in media] == [1, 1, 0]
    assert media[0]["id"] != media[1]["id"], "the second marked version got a clean copy of its own"
    assert continued["title"] != "Step 1 (continued)" and len(guide["steps"]) == 2, "three media fit in one step"
    assert guide["difficulty"] == "moderate"
    report = (archive / "import-report.md").read_text()
    assert "step 1: Image 507 appears twice in the step; it is shown once." in report
    assert "step 1: Image 900 appears twice in the step; it is shown once." in report
    assert "Guides with no difficulty set on the old site were given “moderate”, Reticle's default." in report
    assert "### Difficulty values that were not recognised" not in report


def test_progress_is_logged_during_a_long_load(fresh, archive, monkeypatch):
    monkeypatch.setattr(loader_module, "PROGRESS_EVERY", 2)

    result = load(archive, "--namespaces", "ITEM")

    assert "  guide 2 of 4" in result.lines and "  guide 4 of 4" in result.lines


def test_a_failure_while_creating_categories_stops_the_load(fresh, archive, monkeypatch):
    def broken(self: Loader) -> None:
        raise RuntimeError("the category tree is unreadable")

    monkeypatch.setattr(Loader, "load_categories", broken)

    result = load(archive)

    assert result.status == 2
    assert "The categories could not be created (RuntimeError: the category tree is unreadable); nothing else was attempted." in result.text
    assert count(Guide) == 0 and count(Category) == 0


def test_a_minimal_archive_without_categories_or_pages_loads(fresh, tmp_path):
    root = tmp_path / "tiny"
    files = {
        "manifest.json": {"site": "tiny.example", "finished_at": "2026-10-10T00:00:00Z", "authenticated": True, "namespaces": [], "items": {}},
        "api/guides/index.json": [{"guideid": 7, "title": "Tiny", "category": "Plain", "userid": "3", "username": "Sam Sample"}],
        "api/guides/7/guide.json": {"guideid": 7, "title": "Tiny", "category": "Plain", "public": True, "difficulty": "Easy",
                                    "steps": [{"orderby": 1, "title": "", "lines": [{"text_raw": "Do ''it''.", "bullet": "black", "level": 0}], "media": None}]},
        "api/guides/7/tags.json": ["Tiny"],
    }
    for relative, document in files.items():
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text(json.dumps(document))

    result = load(root)

    assert result.status == 0, result.text
    with signed_in("viewer@zmb.example") as viewer:
        guide = viewer.get("/api/guides/tiny").json()
    assert guide["steps"][0]["bullets"][0]["text"] == "Do it."
    assert guide["author"]["displayName"] == "Sam Sample", "the name in the listing stands in when there is no profile"
    report = (root / "import-report.md").read_text()
    assert "Holding categories marked hidden" not in report
    with db.SessionLocal() as session:
        assert session.scalars(select(User.email).where(User.display_name == "Sam Sample")).one() == "dozuki-user-3@import.invalid"
        assert session.scalars(select(ImportRecord.source).distinct()).all() == ["tiny.example"]


# ---------------------------------------------------------------- beside the running server


def live_database() -> Path:
    return Path(get_settings().database_url.removeprefix("sqlite:///"))


class LockProbe:
    """A second connection to the live database, standing in for the running server.

    ``try_write`` asks for the database's write lock without waiting, the way a
    login would have to get it, and gives it straight back.
    """

    def __init__(self) -> None:
        self.connection = sqlite3.connect(live_database(), timeout=0, isolation_level=None, check_same_thread=False)
        self.attempts = 0
        self.refused: list[str] = []

    def try_write(self, where: str) -> None:
        self.attempts += 1
        try:
            self.connection.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError:
            self.refused.append(where)
        else:
            self.connection.execute("ROLLBACK")

    def wrap(self, patch: pytest.MonkeyPatch, owner: Any, name: str) -> None:
        original = getattr(owner, name)

        def probed(*arguments: Any, **keywords: Any) -> Any:
            self.try_write(name)
            return original(*arguments, **keywords)

        patch.setattr(owner, name, probed)

    def watch_the_slow_work(self, patch: pytest.MonkeyPatch) -> None:
        """Ask for the write lock every time the loader does something that takes time."""
        self.wrap(patch, Archive, "read_json")
        self.wrap(patch, Archive, "media_file")
        self.wrap(patch, images, "normalise")
        self.wrap(patch, images, "write_file")
        self.wrap(patch, videos, "store")
        self.wrap(patch, videos, "sniff")
        self.wrap(patch, loader_module.markers, "interpret")
        self.wrap(patch, loader_module.markers, "realise")
        self.wrap(patch, loader_module, "to_markdown")
        self.wrap(patch, loader_module, "to_plain")
        self.wrap(patch, loader_module, "html_to_plain")
        self.wrap(patch, Loader, "_open")
        self.wrap(patch, Loader, "_encode")


def test_a_load_holds_the_write_lock_only_while_it_writes_rows(fresh, archive, monkeypatch):
    """All the slow work happens with the database free for the server's own writes."""
    probe = LockProbe()
    probe.watch_the_slow_work(monkeypatch)
    logins: list[int] = []
    store = videos.store

    def store_while_someone_signs_in(*arguments: Any, **keywords: Any) -> int:
        with TestClient(app) as raw:  # a login writes a session row: it needs the write lock, and has five seconds to get it
            logins.append(ApiClient(raw).login("viewer@zmb.example").status_code)
        return store(*arguments, **keywords)

    monkeypatch.setattr(videos, "store", store_while_someone_signs_in)

    result = load(archive)

    assert result.status == 0, result.text
    assert "  guide:     4 created" in result.lines and "  page:      4 created, 1 skipped" in result.lines
    assert probe.attempts > 150, "the probe really was consulted throughout"
    assert probe.refused == [], "a writer was turned away while the loader was reading files or working on pictures"
    assert logins == [200], "someone signed in while a video was being copied into the media store"
    summary = next(line for line in result.lines if line.startswith("  database write lock: "))
    held = re.fullmatch(r"  database write lock: 9 write transactions, (\d+\.\d+) s in total, longest (\d+) ms \((.+)\)", summary)
    assert held, summary
    assert int(held.group(2)) < 2000 and float(held.group(1)) < 5, "milliseconds per item, not the minutes the pictures take"


def test_the_write_lock_really_is_held_during_the_write_and_released_after_each_item(fresh, archive, monkeypatch):
    """The other half: the probe is not blind, and nothing stays locked between items."""
    probe = LockProbe()
    during: list[bool] = []
    finish = Loader._finish

    def finish_and_probe(self: Loader, *arguments: Any, **keywords: Any) -> None:
        refused = len(probe.refused)
        probe.try_write("write phase")
        during.append(len(probe.refused) > refused)
        finish(self, *arguments, **keywords)

    monkeypatch.setattr(Loader, "_finish", finish_and_probe)
    between: list[int] = []

    def pause(seconds: float) -> None:
        refused = len(probe.refused)
        probe.try_write("between items")
        between.append(len(probe.refused) - refused)
        assert seconds == 0.05

    lines: list[str] = []
    status = cli.main(["load", "--archive", str(archive)], out=lines.append, sleep=pause)

    assert status == 0, "\n".join(lines)
    assert during == [True] * 8, "while an item's rows are being written, the lock is the loader's"
    assert between == [0] * 9, "after each item written (the categories, four guides, four pages) the lock is free, and the loader waits a moment"


def test_a_dry_run_never_takes_the_write_lock_of_the_live_database(fresh, archive, tmp_path, monkeypatch):
    """Held by somebody else from start to finish, and the dry run does not notice."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    before = {model: count(model) for model in (Guide, Page, Category, Media, User, Tag, ImportRecord, AuditLog)}
    blocker = sqlite3.connect(live_database(), timeout=0, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")
    blocker.execute("UPDATE users SET display_name = display_name")
    try:
        result = load(archive, "--dry-run")
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()

    assert result.status == 0, result.text
    assert "  guide:     4 created" in result.lines and "  page:      4 created, 1 skipped" in result.lines
    assert any(line.startswith("Dry run: working on a snapshot copy of the database in ") for line in result.lines)
    assert not any("database write lock" in line for line in result.lines)
    assert {model: count(model) for model in before} == before
    assert list(scratch.iterdir()) == [], "the snapshot and its throwaway media directory are removed"
    assert not get_settings().media_root.exists()
    report = (archive / "import-report-dry-run.md").read_text()
    assert "(dry run on a private snapshot copy; the database itself was only read)" in report
    assert "Database write lock" not in report


def test_a_dry_run_after_a_load_sees_what_is_already_there(fresh, archive):
    load(archive)
    files = media_files()
    edit_json(archive, "api/guides/27/guide.json", lambda document: document.update(title="MesoSPIM, retitled", modified_date=document["modified_date"] + 60))

    result = load(archive, "--dry-run")

    assert result.status == 0, result.text
    assert "  guide:     1 updated, 3 unchanged" in result.lines and "  page:      4 unchanged, 1 skipped" in result.lines
    assert media_files() == files
    with db.SessionLocal() as session:
        assert session.scalars(select(Guide.title).where(Guide.slug == GUIDE_27)).one() == "MesoSPIM - Part 1: Start-up"


def test_the_dry_run_snapshot_is_removed_even_when_the_load_cannot_start(fresh, archive, tmp_path, monkeypatch):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))

    result = load(archive, "--dry-run", "--owner-email", "nobody@zmb.example")

    assert result.status == 2 and "is not an existing Reticle account" in result.text
    assert list(scratch.iterdir()) == []


def test_a_dry_run_that_cannot_copy_the_database_says_so_and_cleans_up(fresh, archive, tmp_path, monkeypatch):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))

    def full(source: Path, target: Path) -> None:
        target.write_bytes(b"partial")
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr(cli, "snapshot_database", full)

    result = load(archive, "--dry-run")

    assert result.status == 2
    assert "The database could not be copied for the dry run (database or disk is full). The copy goes to the temporary directory (TMPDIR, now " in result.text
    assert list(scratch.iterdir()) == [] and count(Guide) == 0

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "does-not-exist"))
    missing = load(archive, "--dry-run")
    assert missing.status == 2 and "has to exist, be writable" in missing.text


def test_a_dry_run_on_a_database_that_cannot_be_snapshotted_is_one_rolled_back_transaction(fresh, archive, monkeypatch):
    """PostgreSQL, in practice: no single write lock there, so one uncommitted transaction is harmless."""
    monkeypatch.setattr(cli, "sqlite_file", lambda url: None)
    before = {model: count(model) for model in (Guide, Page, Category, Media, User, Tag, ImportRecord, AuditLog)}
    slept: list[float] = []
    lines: list[str] = []

    status = cli.main(["load", "--archive", str(archive), "--dry-run"], out=lines.append, sleep=slept.append)

    text = "\n".join(lines)
    assert status == 0, text
    assert "  guide:     4 created" in text and "  page:      4 created, 1 skipped" in text
    assert {model: count(model) for model in before} == before
    assert media_files() == [] and slept == []
    assert "(dry run in one transaction that was rolled back)" in (archive / "import-report-dry-run.md").read_text()
    assert load(archive).status == 0


def test_which_databases_can_be_snapshotted():
    assert cli.sqlite_file("sqlite:////data/reticle.db") == Path("/data/reticle.db")
    assert cli.sqlite_file("sqlite:///relative/reticle.db") == Path("relative/reticle.db")
    for url in ("sqlite://", "sqlite:///:memory:", "sqlite:///file:shared?mode=memory&uri=true", "postgresql+psycopg://reticle:secret@db/reticle"):
        assert cli.sqlite_file(url) is None, url


def test_the_snapshot_is_a_consistent_copy_taken_while_the_database_is_in_use(fresh, tmp_path):
    writer = sqlite3.connect(live_database(), timeout=0, isolation_level=None)
    writer.execute("BEGIN IMMEDIATE")
    writer.execute("UPDATE users SET display_name = 'uncommitted'")

    cli.snapshot_database(live_database(), tmp_path / "copy.db")
    writer.execute("ROLLBACK")
    writer.close()

    with sqlite3.connect(tmp_path / "copy.db") as copy:
        names = {row[0] for row in copy.execute("SELECT display_name FROM users")}
    assert names == {"ada.example", "viewer", "admin"}, "the copy holds what was committed, not what was in flight"


def test_nothing_is_written_and_nobody_waits_when_nothing_changed(fresh, archive):
    load(archive)
    slept: list[float] = []
    lines: list[str] = []

    status = cli.main(["load", "--archive", str(archive)], out=lines.append, sleep=slept.append)

    assert status == 0
    assert "  database write lock: no write transaction was needed" in lines
    assert slept == []
    assert "- **Database write lock:** no write transaction was needed" in (archive / "import-report.md").read_text()


def test_the_pause_between_items_can_be_changed_or_switched_off(fresh, archive, capsys):
    slept: list[float] = []

    cli.main(["load", "--archive", str(archive), "--guide", "422", "--namespaces", "ITEM", "--pause", "0.5"], out=lambda line: None, sleep=slept.append)
    cli.main(["load", "--archive", str(archive), "--force", "--guide", "422", "--namespaces", "ITEM", "--pause", "0"], out=lambda line: None, sleep=slept.append)

    assert slept == [0.5, 0.5]
    for value in ("-1", "61", "soon"):
        with pytest.raises(SystemExit):
            cli.main(["load", "--archive", str(archive), "--pause", value])
    assert "pause" in capsys.readouterr().err


def test_a_failure_while_writing_takes_back_the_files_the_rows_and_the_report_lines(fresh, archive, monkeypatch):
    def refuse(*arguments: Any, **keywords: Any) -> None:
        raise errors.validation_failed("The application refused the document.")

    monkeypatch.setattr(loader_module, "apply_guide_document", refuse)
    probe = LockProbe()

    result = load(archive, "--guide", "27", "--namespaces", "ITEM")
    probe.try_write("afterwards")

    assert result.status == 1
    assert "  guide:     1 failed" in result.lines
    assert not any(line.strip().startswith("user:") for line in result.lines), "the author account was rolled back, so the report does not claim it"
    report = (archive / "import-report.md").read_text()
    assert "- guide 27 “MesoSPIM - Part 1: Start-up”: The application refused the document." in report
    assert count(Media) == 0 and media_files() == [], "pictures and the video stored before the transaction are removed again"
    assert count(Guide) == 0 and count(ImportRecord) == count(Category)
    with db.SessionLocal() as session:
        assert session.scalars(select(User).where(User.email == "new.author@zmb.example")).one_or_none() is None
    assert probe.refused == [], "and the failed transaction did not leave the database locked"


def test_an_interrupted_load_leaves_no_orphaned_media_files(fresh, archive, monkeypatch):
    realise = loader_module.markers.realise
    calls: list[int] = []

    def interrupt(*arguments: Any, **keywords: Any) -> Any:
        calls.append(1)
        if len(calls) == 2:
            raise KeyboardInterrupt
        return realise(*arguments, **keywords)

    monkeypatch.setattr(loader_module.markers, "realise", interrupt)

    with pytest.raises(KeyboardInterrupt):
        load(archive, "--guide", "15", "--namespaces", "ITEM")

    assert media_files() == [] and count(Media) == 0 and count(Guide) == 0


def test_an_interruption_in_the_middle_of_a_write_rolls_it_back(fresh, archive, monkeypatch):
    def interrupt(*arguments: Any, **keywords: Any) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(loader_module.audit, "record", interrupt)
    probe = LockProbe()

    with pytest.raises(KeyboardInterrupt):
        load(archive, "--guide", "15", "--namespaces", "ITEM")
    probe.try_write("afterwards")

    assert media_files() == [] and count(Media) == 0 and count(Guide) == 0 and probe.refused == []


def test_a_guide_saved_in_reticle_while_its_import_was_being_prepared_is_left_alone(fresh, archive, monkeypatch):
    """Preparing a guide can take a while, and the server is running: the check is made again under the lock."""
    load(archive)
    edit_json(archive, "api/guides/15/guide.json", lambda document: document.update(summary="Changed on the vendor site."))
    steps = Loader._steps

    def steps_while_an_author_saves(self: Loader, *arguments: Any, **keywords: Any) -> Any:
        prepared = steps(self, *arguments, **keywords)
        with signed_in("ada.example@zmb.example") as author:
            guide = author.get(f"/api/guides/{GUIDE_15}").json()
            assert author.put(f"/api/guides/{guide['id']}", json=document_from(guide, title="Saved meanwhile")).status_code == 200
        return prepared

    monkeypatch.setattr(Loader, "_steps", steps_while_an_author_saves)
    files = media_files()

    result = load(archive, "--guide", "15", "--namespaces", "ITEM")

    assert result.status == 0, result.text
    assert "  guide:     1 skipped" in result.lines
    assert "- guide 15 “Leica Stellaris 5 inverse (USZ) - How to get there”: edited in Reticle since it was imported; left untouched" in (archive / "import-report.md").read_text()
    with signed_in("ada.example@zmb.example") as author:
        kept = author.get(f"/api/guides/{GUIDE_15}").json()
    assert kept["title"] == "Saved meanwhile" and kept["summary"] == "How to get to the Stellaris 5 inverse in USZ."
    assert media_files() == files


def test_a_page_saved_in_reticle_while_its_import_was_being_prepared_is_left_alone(fresh, archive, monkeypatch):
    load(archive)
    edit_json(archive, "api/wikis/WIKI/108.json", lambda document: document.update(contents_raw="== Vendor rewrite =="))
    convert = loader_module.to_markdown

    def convert_while_an_author_saves(*arguments: Any, **keywords: Any) -> Any:
        with signed_in("ada.example@zmb.example") as author:
            page = author.get(f"/api/pages/{SEQIF}").json()
            assert author.put(f"/api/pages/{page['id']}", json=document_from(page, body="Saved meanwhile.")).status_code == 200
        return convert(*arguments, **keywords)

    monkeypatch.setattr(loader_module, "to_markdown", convert_while_an_author_saves)

    result = load(archive, "--namespaces", "WIKI", "--guide", "15")

    assert "  page:      1 skipped" in result.lines
    with signed_in("ada.example@zmb.example") as author:
        assert author.get(f"/api/pages/{SEQIF}").json()["body"] == "Saved meanwhile."


# ---------------------------------------------------------------- what may be published


def exported(directory: Path, change: Any = None, token: str | None = "good-token-123") -> Path:
    site = FakeSite()
    if change is not None:
        change(site)
    write_archive(directory, site, token)
    return directory


def statuses(model: type) -> dict[str, str]:
    with db.SessionLocal() as session:
        return {item.slug: item.status for item in session.scalars(select(model))}


def test_a_page_the_old_site_did_not_show_publicly_is_imported_as_a_draft(fresh, tmp_path):
    archive = exported(tmp_path / "archive", lambda site: site.private_wikis.update({108, 1}))

    result = load(archive)

    assert result.status == 0, result.text
    assert statuses(Page) == {
        SEQIF: "draft",
        "center-for-microscopy-and-image-analysis": "draft",
        "confocal-microscopy": "published",
        "ls-hidden-guides": "published",
    }
    assert set(statuses(Guide).values()) == {"published", "draft"}, "guides follow the old site's own public flag, as before"
    with signed_in("viewer@zmb.example") as viewer, signed_in("ada.example@zmb.example") as author:
        assert viewer.get(f"/api/pages/{SEQIF}").status_code == 404
        assert sorted(page["slug"] for page in viewer.get("/api/pages").json()) == ["confocal-microscopy", "ls-hidden-guides"]
        draft = author.get(f"/api/pages/{SEQIF}").json()
        assert draft["status"] == "draft" and draft["version"] == 0 and "Run the **full** panel" in draft["body"]
    assert count(PageRevision) == 2
    report = (archive / "import-report.md").read_text()
    assert "### Pages imported as drafts because the old site did not show them publicly (2)" in report
    assert (
        "- page WIKI “Strategy to Run a Full Multiplex SeqIF”: Imported as a draft: NOT shown to visitors who were not signed in on the old site. "
        "Publish it in Reticle if every reader may see it."
    ) in report
    assert f"- page WIKI “Strategy to Run a Full Multiplex SeqIF” — draft, /w/{SEQIF} — NOT shown to visitors who were not signed in on the old site" in report
    assert "- page CATEGORY “Confocal Microscopy” — published, /w/confocal-microscopy — the landing page of its category" in report
    assert "Content imported as a draft although the original was public" not in report


def test_an_archive_that_cannot_say_what_was_public_gets_drafts_except_for_landing_pages(fresh, archive):
    """An export made before the anonymous pass existed, or from a site that shows nothing without a login."""
    for namespace in ("WIKI", "CATEGORY"):
        edit_json(archive, f"api/wikis/{namespace}/index.json", lambda entries: [entry.pop("anonymousVisible") for entry in entries])
    edit_json(archive, "api/wikis/WIKI/index.json", lambda entries: entries[0].update(anonymousVisible="yes"))

    result = load(archive)

    assert result.status == 0, result.text
    assert statuses(Page) == {
        SEQIF: "draft",
        "center-for-microscopy-and-image-analysis": "draft",
        "confocal-microscopy": "published",
        "ls-hidden-guides": "published",
    }
    report = (archive / "import-report.md").read_text()
    assert (
        "- page CATEGORY “Center for Microscopy and Image Analysis”: Imported as a draft: the archive does not say whether the old site showed it "
        "to visitors who were not signed in. Publish it in Reticle if every reader may see it. (Running the export again records this for every page.)"
    ) in report


def test_a_page_becomes_public_when_a_later_export_finds_it_was(fresh, tmp_path):
    archive = exported(tmp_path / "archive", lambda site: site.private_wikis.add(108))
    load(archive)
    edit_json(archive, "api/wikis/WIKI/index.json", lambda entries: entries[0].update(anonymousVisible=True))

    result = load(archive)

    assert "  page:      1 updated, 3 unchanged, 1 skipped" in result.lines
    assert statuses(Page)[SEQIF] == "published"
    with signed_in("viewer@zmb.example") as viewer:
        assert viewer.get(f"/api/pages/{SEQIF}").json()["version"] == 1


def test_a_page_that_stops_being_public_is_withdrawn_from_readers(fresh, archive):
    load(archive)
    edit_json(archive, "api/wikis/WIKI/index.json", lambda entries: entries[0].update(anonymousVisible=False))

    result = load(archive)

    assert "  page:      1 updated, 3 unchanged, 1 skipped" in result.lines
    with signed_in("viewer@zmb.example") as viewer, signed_in("ada.example@zmb.example") as author:
        assert viewer.get(f"/api/pages/{SEQIF}").status_code == 404
        assert SEQIF not in [page["slug"] for page in viewer.get("/api/pages").json()]
        assert author.get(f"/api/pages/{SEQIF}").json()["status"] == "draft"


def test_an_anonymous_export_publishes_what_it_holds(fresh, tmp_path):
    archive = exported(tmp_path / "archive", token=None)

    result = load(archive)

    assert result.status == 0, result.text
    assert set(statuses(Page).values()) == {"published"} and set(statuses(Guide).values()) == {"published"}
    assert "Pages imported as drafts" not in (archive / "import-report.md").read_text()


def test_a_public_guide_the_old_site_did_not_list_anonymously_is_published_and_flagged(fresh, archive):
    edit_json(archive, "api/guides/index.json", lambda entries: entries[0].update(anonymousVisible=False))

    result = load(archive, "--namespaces", "ITEM")

    assert result.status == 0 and statuses(Guide)[GUIDE_15] == "published"
    report = (archive / "import-report.md").read_text()
    assert "### Guides published as marked, though the old site did not list them to anonymous visitors (1)" in report
    assert "It is published here as the old site marked it; check that it should be." in report
    assert f"published, /g/{GUIDE_15} — public on the old site, though not listed to visitors who were not signed in" in report


def test_an_archived_guide_is_a_draft_and_the_report_says_why(fresh, archive):
    edit_json(archive, "api/guides/index.json", lambda entries: entries[0].update(isArchived=True))

    load(archive, "--namespaces", "ITEM")

    assert statuses(Guide)[GUIDE_15] == "draft"
    assert f"draft, /g/{GUIDE_15} — archived on the old site" in (archive / "import-report.md").read_text()


# ---------------------------------------------------------------- a doctored archive


def test_a_manifest_cannot_point_the_loader_at_a_file_outside_the_archive(fresh, archive, tmp_path):
    secret = tmp_path / "secret.png"
    photo(64, 48, 7).save(secret, format="PNG")
    (archive / "files/images/planted.png").symlink_to(secret)
    (archive / "api/guides/430/guide.json").rename(archive / "api/guides/430/real.json")
    (archive / "api/guides/430/guide.json").symlink_to(archive / "api/guides/430/real.json")

    def doctor(manifest: dict) -> None:
        manifest["items"]["image-file:900"]["path"] = str(secret)
        manifest["items"]["image-file:901"]["path"] = "../secret.png"
        manifest["items"]["image-file:902"]["path"] = "files/images/planted.png"
        manifest["items"]["image-file:903"]["path"] = "files/images/../../../secret.png"

    edit_json(archive, "manifest.json", doctor)
    edit_json(archive, "api/guides/index.json", lambda entries: entries.extend([{"guideid": "../../../etc", "title": "Hostile"}, {"guideid": "27/../15"}]))
    edit_json(archive, "api/wikis/WIKI/index.json", lambda entries: entries.append({"wikiid": "../../x", "title": "Hostile"}))

    result = load(archive)

    assert result.status == 1, result.text
    assert "  guide:     3 created, 1 failed" in result.lines and "  page:      4 created, 1 skipped" in result.lines
    report = (archive / "import-report.md").read_text()
    for image_id in (900, 901, 902, 903):
        assert f"Image {image_id} is not in the archive." in report
    assert "- guide 430 “Internal: laser safety interlock”: LookupError: the guide is not in the archive" in report, "a link in place of a file is not read"
    with db.SessionLocal() as session:
        sizes = {(media.width, media.height) for media in session.scalars(select(Media))}
    assert (64, 48) not in sizes, "the file outside the archive was not imported"
    assert "Hostile" not in report


def test_an_archive_whose_folders_are_links_is_not_read(fresh, archive, tmp_path):
    (archive / "api/categories/detail").rename(tmp_path / "detail")
    (archive / "api/categories/detail").symlink_to(tmp_path / "detail", target_is_directory=True)

    result = load(archive, "--namespaces", "ITEM")

    assert result.status == 0, result.text
    with db.SessionLocal() as session:
        assert session.scalars(select(Category).where(Category.name == "Confocal - hidden guides")).one_or_none() is None, (
            "that category is known only from the detail files, which were not read"
        )


# ---------------------------------------------------------------- shared rules, not copies


def sideways(picture: Image.Image) -> tuple[Image.Image, Image.Exif]:
    """The picture as a phone held upright stores it: turned, with a tag saying so."""
    exif = Image.Exif()
    exif[0x0112] = 6
    return picture.transpose(Image.Transpose.ROTATE_90), exif


def test_a_sideways_picture_that_has_to_be_re_encoded_is_turned_exactly_once(tmp_path, archive):
    stored, exif = sideways(photo(320, 240, 904))
    stored.save(archive / "files/images/904.png", format="PNG", exif=exif)
    with reticle(tmp_path / "reticle", RETICLE_MAX_IMAGE_DIMENSION="200"):
        migrate.upgrade()
        staff()

        result = load(archive, "--guide", "430", "--namespaces", "ITEM")

        assert result.status == 0, result.text
        with db.SessionLocal() as session:
            media = session.scalars(select(Media)).one()
            assert (media.width, media.height) == (200, 150), "landscape, as the photograph is shown — not turned twice into portrait"
            with Image.open(get_settings().media_root / media.storage_path) as kept:
                assert kept.size == (200, 150) and kept.getexif().get(0x0112) is None
                expected = photo(320, 240, 904).resize((200, 150)).convert("RGB")
                difference = sum(abs(a - b) for a, b in zip(kept.convert("RGB").resize((20, 15)).tobytes(), expected.resize((20, 15)).tobytes())) / (20 * 15 * 3)
                assert difference < 12, "and it is the same way up as the original"
        assert "Image 904 was re-encoded to fit Reticle’s limits" in (archive / "import-report.md").read_text()


def test_markers_land_in_the_right_place_on_a_photograph_stored_sideways(fresh, archive):
    """The clean source is turned once, by the application; the marker check sees it the same way up."""
    stored, exif = sideways(photo(800, 600, 1))
    stored.save(archive / "files/images/477.jpg", format="JPEG", quality=95, exif=exif)

    result = load(archive, "--guide", "15", "--namespaces", "ITEM")

    assert result.status == 0, result.text
    with signed_in("viewer@zmb.example") as viewer:
        media = viewer.get(f"/api/guides/{GUIDE_15}").json()["steps"][0]["media"][0]
        assert (media["width"], media["height"]) == (800, 600)
        (arrow,) = media["annotations"]
        assert (arrow["x"], arrow["y"]) == pytest.approx((505 / 800, 440 / 600), abs=1e-4)
        with Image.open(BytesIO(viewer.get(media["url"]).content)) as served:
            assert served.size == (800, 600) and served.getexif().get(0x0112) is None
    assert "Image 507" not in (archive / "import-report.md").read_text(), "no fallback to the burned-in picture was needed"


def test_tags_and_slugs_follow_the_applications_own_rules(fresh, archive):
    """Umlauts transliterate; the importer uses the application's functions, so the two cannot drift."""
    from app import slugs
    from app.importer import wikitext

    assert wikitext.tag_slug is slugs.tag_slug and loader_module.tag_slug is slugs.tag_slug
    assert loader_module.slugify is slugs.slugify and loader_module.unique_slug is slugs.unique_slug

    edit_json(archive, "api/guides/422/guide.json", lambda document: document.update(title="Präparation für die Übersicht"))
    edit_json(archive, "api/guides/index.json", lambda entries: [entry.update(title="Präparation für die Übersicht") for entry in entries if entry["guideid"] == 422])
    (archive / "api/guides/422/tags.json").write_text(json.dumps(["Präparation", "Größe"]))
    edit_json(archive, "api/wikis/CATEGORY/23.json", lambda document: document.update(
        contents_raw="== Präparation ==\n\n[guidelist|tags=Präparation]\n\nSee [guide|422] and [guide|422|die Anleitung].\n"))

    result = load(archive)

    assert result.status == 0, result.text
    with signed_in("viewer@zmb.example") as viewer:
        guide = viewer.get("/api/guides/praeparation-fuer-die-uebersicht").json()
        assert sorted(guide["tags"]) == sorted([slugs.tag_slug("Präparation"), slugs.tag_slug("Größe")]) == ["groesse", "praeparation"]
        page = viewer.get("/api/pages/confocal-microscopy").json()
        assert page["body"] == (
            "## Präparation\n\n```guidelist\ntags: praeparation\n```\n\n"
            "See [Präparation für die Übersicht](/g/praeparation-fuer-die-uebersicht) and [die Anleitung](/g/praeparation-fuer-die-uebersicht).\n"
        )
        (asked,) = re.findall(r"^tags: (.+)$", page["body"], flags=re.MULTILINE)
        assert [listed["slug"] for listed in viewer.get("/api/guides", params={"tags": asked}).json()] == ["praeparation-fuer-die-uebersicht"]
        assert {tag["slug"]: tag["name"] for tag in viewer.get("/api/tags").json()}["praeparation"] == "Präparation"


def test_a_hero_image_takes_its_description_when_the_vendor_has_one(fresh, archive):
    edit_json(archive, "api/wikis/CATEGORY/23.json", lambda document: document["image"].update(caption="  The confocal\nroom, seen from the door  "))

    load(archive, "--guide", "15")

    with signed_in("viewer@zmb.example") as viewer:
        landing = viewer.get("/api/pages/confocal-microscopy").json()
    assert landing["heroMediaId"] and landing["heroAlt"] == "The confocal room, seen from the door"


def test_a_hero_image_without_a_description_has_no_alt_text(world):
    """What the live API sends: an id, a guid and URLs. Nothing is made up to fill the gap."""
    landing = world.viewer.get("/api/pages/confocal-microscopy").json()

    assert landing["heroMediaId"] and landing["heroAlt"] == ""
    assert Loader._image_description({"description": "D", "alt": "A"}) == "D"
    assert Loader._image_description({"caption": 7, "alt": " A "}) == "A"
    assert len(Loader._image_description({"caption": "c" * 2000})) == 1000


def test_a_hero_image_that_cannot_be_imported_brings_no_description_with_it(fresh, archive):
    edit_json(archive, "api/wikis/CATEGORY/23.json", lambda document: document["image"].update(caption="Described, but missing"))
    (archive / "files/images/12099.jpg").unlink()

    load(archive, "--guide", "15")

    with signed_in("viewer@zmb.example") as viewer:
        landing = viewer.get("/api/pages/confocal-microscopy").json()
    assert landing["heroMediaId"] is None and landing["heroAlt"] == ""
