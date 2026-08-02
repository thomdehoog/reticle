"""The migration end to end, against a stand-in for the vendor API.

The mapping is tested on its own next door; this file tests the part that can
only go wrong once everything is connected — that a mapped guide actually
becomes rows, that its pictures are fetched and re-encoded through the same
validation an upload goes through, that the annotations land on the right image,
that a second run does not produce a second copy of the corpus, and that the
reconciliation report refuses to call a lossy run a success.

The site cannot be reached from the build environment, so the client is replaced
with one that serves recorded-shaped payloads from memory. That is the only
honest way to test a migration you get to perform once.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app.importer.client import MigrationError
from app.importer.run import Importer, Options
from app.models import Annotation, Category, Guide, ImportedRecord, Media, Page, Step, Tag
from app.settings import get_settings

from .conftest import image_bytes


class FakeDozuki:
    """Serves payloads from memory, and counts what was asked for.

    The counter matters: the importer must not re-download a picture it already
    holds, because the corpus runs to thousands of images and the run happens
    over a facility's network connection.
    """

    def __init__(self, guides: list[dict], wikis: dict[str, list[dict]] | None = None) -> None:
        self.base_url = "https://example.test"
        self._guides = {str(guide["guideid"]): guide for guide in guides}
        self._wikis = wikis or {}
        self.downloads: list[str] = []
        self.failing_urls: set[str] = set()

    def iter_guides(self, include_private: bool = False):
        for guide in self._guides.values():
            if include_private or guide.get("public", True):
                yield {"guideid": guide["guideid"], "title": guide.get("title", "")}

    def get_guide(self, guide_id):
        return self._guides[str(guide_id)]

    def iter_wikis(self, namespace: str = "CATEGORY"):
        yield from self._wikis.get(namespace, [])

    def get_wiki(self, namespace: str, title: str):
        for entry in self._wikis.get(namespace, []):
            if entry.get("title") == title:
                return entry
        raise MigrationError(f"No such wiki {namespace}/{title}")

    def download(self, url: str):
        self.downloads.append(url)
        if url in self.failing_urls:
            raise MigrationError(f"500 from {url}")

        from app.importer.client import FetchedFile

        return FetchedFile(payload=image_bytes(40, 30), content_type="image/png", url=url)


def _options(**overrides) -> Options:
    defaults = {
        "base_url": "https://example.test",
        "token": None,
        "include_private": False,
        "limit": None,
        "allow_unmapped": False,
        "dry_run": False,
        "skip_media": False,
        "report_path": None,
        "json_report_path": None,
        "author_email": "admin@zmb.uzh.ch",
    }
    defaults.update(overrides)
    return Options(**defaults)


def _guide(guide_id: int = 1234, **overrides) -> dict:
    payload = {
        "guideid": guide_id,
        "title": "Starting a Session on the Confocal",
        "summary": "From booking to shutdown.",
        "category": "Light Microscopy",
        "tags": ["Confocal", "Stellaris"],
        "difficulty": "Easy",
        "time_required": "30 - 90 minutes",
        "introduction_raw": "Assumes a valid booking.",
        "conclusion_raw": "Report faults the same day.",
        "public": True,
        "steps": [
            {
                "title": "Power up in order",
                "lines": [
                    {"text_raw": "Switch on the mains strip.", "bullet": "black", "level": 0},
                    {"text_raw": "Never skip the self-test.", "bullet": "icon_caution", "level": 0},
                ],
                "media": [
                    {
                        "type": "image",
                        "data": {
                            "id": 9001,
                            "original": "https://example.test/one.png",
                            "markup": [
                                {
                                    "shape": "rectangle",
                                    "color": "red",
                                    "x": 0.1,
                                    "y": 0.1,
                                    "width": 0.2,
                                    "height": 0.2,
                                }
                            ],
                        },
                    }
                ],
            },
            {
                "title": "Acquire and shut down",
                "lines": [{"text_raw": "Save to the group folder.", "bullet": "black", "level": 0}],
                "media": [],
            },
        ],
    }
    payload.update(overrides)
    return payload


@pytest.fixture()
def author_account(make_user):
    return make_user("admin@zmb.uzh.ch", role="admin")


def _run(db_session, client, options=None):
    importer = Importer(db_session, client, options or _options(), get_settings())
    importer.import_guides()
    importer.import_pages()
    return importer


def test_a_guide_arrives_whole(db_session, author_account, media_root):
    importer = _run(db_session, FakeDozuki([_guide()]))

    guide = db_session.scalars(select(Guide)).one()
    assert guide.title == "Starting a Session on the Confocal"
    assert guide.status == "published"
    assert guide.version == 1
    assert guide.time_required_min_minutes == 30
    assert guide.time_required_max_minutes == 90
    assert guide.difficulty == "easy"
    assert guide.tag_slugs == ["confocal", "stellaris"]
    assert [step.title for step in guide.steps] == ["Power up in order", "Acquire and shut down"]
    assert [bullet.text for bullet in guide.steps[0].bullets] == [
        "Switch on the mains strip.",
        "Never skip the self-test.",
    ]
    assert guide.steps[0].bullets[1].icon == "caution"
    assert importer.report.balanced is True


def test_the_category_is_created_from_the_source_and_reused(db_session, author_account, media_root):
    _run(db_session, FakeDozuki([_guide(1), _guide(2, title="Second guide")]))

    categories = db_session.scalars(select(Category)).all()
    assert [category.name for category in categories] == ["Light Microscopy"]


def test_pictures_are_fetched_and_stored_through_the_upload_validation(
    db_session, author_account, media_root
):
    """Re-encoding is what strips camera EXIF and what stops a decompression bomb."""
    _run(db_session, FakeDozuki([_guide()]))

    media = db_session.scalars(select(Media)).one()
    assert media.kind == "image"
    assert media.width == 40 and media.height == 30
    assert media.byte_size > 0
    stored = Path(get_settings().media_root) / media.storage_path
    assert stored.exists()


def test_annotations_land_on_the_image_they_belong_to(db_session, author_account, media_root):
    """The shape on the picture is half of the instruction the bullet gives."""
    _run(db_session, FakeDozuki([_guide()]))

    annotation = db_session.scalars(select(Annotation)).one()
    assert annotation.shape == "rectangle"
    assert annotation.color == "red"
    assert (annotation.x, annotation.y, annotation.width, annotation.height) == (0.1, 0.1, 0.2, 0.2)

    media = db_session.scalars(select(Media)).one()
    assert annotation.media_id == media.id


def test_a_private_guide_arrives_as_a_draft_rather_than_being_disclosed(
    db_session, author_account, media_root
):
    client = FakeDozuki([_guide(public=False)])
    importer = Importer(db_session, client, _options(include_private=True), get_settings())
    importer.import_guides()

    guide = db_session.scalars(select(Guide)).one()
    assert guide.status == "draft"
    assert guide.published_at is None


def test_running_twice_updates_rather_than_duplicating(db_session, author_account, media_root):
    """A network failure half way through must not cost a second copy of the corpus."""
    client = FakeDozuki([_guide()])
    _run(db_session, client)
    downloads_after_first = len(client.downloads)

    _run(db_session, client)

    assert len(db_session.scalars(select(Guide)).all()) == 1
    assert len(db_session.scalars(select(Step)).all()) == 2
    assert len(db_session.scalars(select(Annotation)).all()) == 1
    assert len(client.downloads) == downloads_after_first, "the picture was fetched twice"


def test_the_source_reference_survives_so_a_reviewer_can_find_the_original(
    db_session, author_account, media_root
):
    _run(db_session, FakeDozuki([_guide()]))

    record = db_session.scalars(
        select(ImportedRecord).where(ImportedRecord.source_kind == "guide")
    ).one()
    assert record.source_id == "1234"
    assert record.source_url.endswith("/Guide/1234")
    guide = db_session.scalars(select(Guide)).one()
    assert record.local_id == guide.id


def test_an_unrecognised_value_is_reported_and_leaves_the_run_unbalanced(
    db_session, author_account, media_root
):
    payload = _guide()
    payload["steps"][0]["lines"][0]["bullet"] = "teal"
    importer = _run(db_session, FakeDozuki([payload]))

    assert any(item.kind == "bullet" and item.value == "teal" for item in importer.report.unmapped)
    assert importer.report.balanced is False


def test_a_failing_download_fails_its_guide_and_not_the_run(db_session, author_account, media_root):
    client = FakeDozuki([_guide(1), _guide(2, title="Second guide")])
    client.failing_urls.add("https://example.test/one.png")

    importer = _run(db_session, client)

    assert importer.report.guides_seen == 2
    assert importer.report.balanced is False
    assert any(tally.failures for tally in importer.report.guides)


def test_a_dry_run_writes_nothing_but_still_reconciles(db_session, author_account, media_root):
    importer = _run(db_session, FakeDozuki([_guide()]), _options(dry_run=True))

    assert db_session.scalars(select(Guide)).all() == []
    assert importer.report.guides_seen == 1
    assert importer.report.balanced is True


def test_a_step_carrying_more_images_than_the_cap_fails_loudly(
    db_session, author_account, media_root
):
    """Truncating to the first few would lose pictures without saying so."""
    payload = _guide()
    payload["steps"][0]["media"] = [
        {"type": "image", "data": {"id": index, "original": f"https://example.test/{index}.png"}}
        for index in range(9)
    ]
    importer = _run(db_session, FakeDozuki([payload]))

    assert importer.report.balanced is False
    assert any(
        "above the configured maximum" in failure
        for tally in importer.report.guides
        for failure in tally.failures
    )


def test_a_category_wiki_becomes_the_categorys_landing_page(db_session, author_account, media_root):
    client = FakeDozuki(
        [_guide()],
        {
            "CATEGORY": [
                {
                    "wikiid": 77,
                    "namespace": "CATEGORY",
                    "title": "Light Microscopy",
                    "contents_raw": "== Before your first session ==\n\nBring your sample.",
                }
            ]
        },
    )
    _run(db_session, client)

    page = db_session.scalars(select(Page)).one()
    assert page.is_landing is True
    assert page.status == "published"
    assert page.version == 1
    assert "## Before your first session" in page.body

    category = db_session.scalars(select(Category).where(Category.name == "Light Microscopy")).one()
    assert page.category_id == category.id


def test_a_landing_page_that_would_displace_an_existing_one_is_kept_as_an_article(
    db_session, author_account, media_root
):
    """Losing it, or overwriting the one already written, both throw content away."""
    from app.models import Category as CategoryModel
    from app.models import Page as PageModel

    category = CategoryModel(slug="light-microscopy", name="Light Microscopy", order_index=0)
    db_session.add(category)
    db_session.flush()
    db_session.add(
        PageModel(
            slug="light-microscopy-landing",
            title="Light Microscopy",
            category_id=category.id,
            is_landing=True,
            body="written by hand",
            status="published",
            author_id=author_account.id,
            last_edited_by_id=author_account.id,
        )
    )
    db_session.commit()

    client = FakeDozuki(
        [],
        {
            "CATEGORY": [
                {
                    "wikiid": 2,
                    "namespace": "CATEGORY",
                    "title": "Light Microscopy",
                    "contents_raw": "imported",
                }
            ]
        },
    )
    importer = _run(db_session, client)

    pages = db_session.scalars(select(Page)).all()
    assert len(pages) == 2
    assert sum(1 for page in pages if page.is_landing) == 1
    assert any(page.body == "written by hand" and page.is_landing for page in pages)
    assert any("already has a landing page" in reason for reason in importer.report.skipped)


def test_tags_are_created_once_and_shared(db_session, author_account, media_root):
    _run(db_session, FakeDozuki([_guide(1), _guide(2, title="Second guide")]))

    tags = sorted(tag.slug for tag in db_session.scalars(select(Tag)).all())
    assert tags == ["confocal", "stellaris"]


def test_skip_media_leaves_the_text_intact(db_session, author_account, media_root):
    client = FakeDozuki([_guide()])
    importer = _run(db_session, client, _options(skip_media=True))

    assert client.downloads == []
    assert len(db_session.scalars(select(Step)).all()) == 2
    assert importer.report.balanced is False, "a text-only rehearsal is not a complete migration"


def test_the_report_names_what_did_not_reconcile(db_session, author_account, media_root):
    payload = _guide()
    payload["steps"][0]["lines"][0]["bullet"] = "teal"
    importer = _run(db_session, FakeDozuki([payload]))

    text = importer.report.to_text()
    assert "MISMATCH" in text or "did not reconcile" in text
    assert "teal" in text
    assert "bullets" in text


def test_the_json_report_carries_the_same_counts(db_session, author_account, media_root):
    importer = _run(db_session, FakeDozuki([_guide()]))

    import json

    decoded = json.loads(importer.report.to_json())
    assert decoded["guidesSeen"] == 1
    assert decoded["balanced"] is True
    assert decoded["guides"][0]["imported_annotations"] == 1


def test_an_account_that_does_not_exist_stops_the_run_before_anything_is_written(
    db_session, media_root
):
    with pytest.raises(MigrationError, match="No account for"):
        Importer(db_session, FakeDozuki([]), _options(), get_settings())


def test_an_unread_field_is_a_question_and_not_a_loss(db_session, author_account, media_root):
    """It must not fail the run: the content all arrived, and nobody asked for it."""
    payload = _guide()
    payload["quiz"] = {"questions": []}
    importer = _run(db_session, FakeDozuki([payload]))

    assert importer.report.balanced is True
    assert [item.value for item in importer.report.questions] == ["quiz"]
    assert importer.report.losses == []

    text = importer.report.to_text()
    assert "does not read" in text
    assert "quiz" in text
