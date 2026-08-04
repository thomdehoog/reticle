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

from .conftest import image_bytes, mp4_bytes


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
        # The two things a guide payload does not carry, each on its own
        # endpoint: which sections sit under which, and which groups a guide
        # belongs to. Default to what the fixture guide claims so the existing
        # assertions keep meaning what they meant.
        self.category_tree: dict = {"Light Microscopy": {}}
        self.guide_tags: dict[str, list[str]] = {
            str(guide["guideid"]): list(guide.get("tags") or []) for guide in guides
        }
        # The record for the standard fixture image, carrying one rectangle in
        # the vendor's own notation. A thousand pixels square keeps the
        # arithmetic legible: 100/1000 and 300-100 over 1000 are the 0.1 and 0.2
        # the assertions read.
        self.images: dict[str, dict] = {
            "9001": {
                "width": 1000,
                "height": 1000,
                "markup": ";rectangle,100x100,300x300,red;",
                # The vendor keeps two renditions: the one a guide links, with
                # the shapes painted in, and the untouched original beside it.
                "srcImageInfo": {
                    "width": 1000,
                    "height": 1000,
                    "image": {"original": "https://example.test/one-original.png"},
                },
            }
        }

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

    def get_category_tree(self):
        """The nesting, which a guide's own payload does not carry."""
        return self.category_tree

    def get_guide_tags(self, guide_id):
        """The groups a guide belongs to, which live on their own endpoint."""
        return self.guide_tags.get(str(guide_id), [])

    def get_image(self, image_id):
        """An image's own record, which is the only place its shapes live.

        Defaults to a picture nobody drew on, so a test that says nothing about
        annotations gets none rather than whatever a shared fixture happened to
        carry. A test that wants shapes puts them in ``images``.
        """
        return self.images.get(str(image_id), {"width": 4032, "height": 3024, "markup": None})

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
                        # No markup here: a guide payload has never carried any.
                        # The shapes drawn on this picture are on its own record,
                        # which ``FakeDozuki.get_image`` serves.
                        "data": {
                            "id": 9001,
                            "original": "https://example.test/one.png",
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
    """Everything ``main`` does, in the order it does it."""
    resolved = options or _options()
    importer = Importer(db_session, client, resolved, get_settings())
    importer.adopt_category_tree()
    importer.import_guides()
    importer.import_pages()
    if not resolved.dry_run:
        importer.resolve_page_guide_embeds()
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


def test_the_sections_arrive_nested_the_way_the_site_nests_them(
    db_session, author_account, media_root
):
    """A guide names its section and nothing above it.

    Built from guides alone the hierarchy flattens — which is what the first
    real run produced: twenty-four sections, every one of them top-level. The
    nesting is published by itself and has to be read by itself.
    """
    client = FakeDozuki([_guide(1, category="Widefield Microscopy")])
    client.category_tree = {
        "Light Micrscopy": {"Widefield Microscopy": {}, "Basic Guides": {}},
        "CryoEM": {},
    }

    _run(db_session, client)

    by_name = {c.name: c for c in db_session.scalars(select(Category)).all()}
    assert by_name["Light Micrscopy"].parent_id is None
    assert by_name["CryoEM"].parent_id is None
    assert by_name["Widefield Microscopy"].parent_id == by_name["Light Micrscopy"].id
    assert by_name["Basic Guides"].parent_id == by_name["Light Micrscopy"].id
    # And the guide lands in the child, not beside it.
    guide = db_session.scalars(select(Guide)).one()
    assert guide.category_id == by_name["Widefield Microscopy"].id


def test_children_are_ordered_within_their_parent(db_session, author_account, media_root):
    """Numbering across the whole tree gave one parent's five children the
    indices 3, 9, 14, 15, 22 — an order that means nothing and cannot be
    adjusted without renumbering the rest of the site."""
    client = FakeDozuki([_guide(1)])
    client.category_tree = {"A": {"A1": {}, "A2": {}}, "B": {"B1": {}}}

    _run(db_session, client)

    by_name = {c.name: c for c in db_session.scalars(select(Category)).all()}
    assert [by_name["A1"].order_index, by_name["A2"].order_index] == [0, 1]
    assert by_name["B1"].order_index == 0


def test_the_groups_a_guide_belongs_to_come_from_their_own_endpoint(
    db_session, author_account, media_root
):
    """No `tags` key exists on a guide document.

    Reading one produced "0 tags" against a corpus where eighty-nine groups
    drive thirteen section front pages.
    """
    client = FakeDozuki([_guide(1)])
    client.guide_tags["1"] = ["OSD", "THUNDER"]

    _run(db_session, client)

    guide = db_session.scalars(select(Guide)).one()
    assert guide.tag_slugs == ["osd", "thunder"]


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


def test_the_picture_kept_is_the_one_without_the_shapes_painted_into_it(
    db_session, author_account, media_root
):
    """ZMB has to be able to edit these guides after the migration.

    The vendor stores an annotated photograph twice: the original, and a
    flattened copy with the shapes burned into the pixels. A guide payload links
    the flattened one, and importing that shows every arrow twice — once in the
    pixels and once from Reticle's own overlay. The doubling is the visible
    symptom; the real loss is that a shape painted into a photograph can never
    be moved, recoloured or taken off again.
    """
    client = FakeDozuki([_guide()])

    _run(db_session, client)

    assert "https://example.test/one-original.png" in client.downloads
    assert "https://example.test/one.png" not in client.downloads


def test_shapes_are_measured_against_the_original_not_the_rendition(
    db_session, author_account, media_root
):
    """Coordinates are in the original's pixel space.

    Read against a rendition of a different size they land somewhere else on the
    picture, or off it altogether — which is a shape that no longer points at
    the control the sentence beside it is naming.
    """
    client = FakeDozuki([_guide()])
    client.images["9001"] = {
        # The rendition is half the size of the photograph the author drew on.
        "width": 500,
        "height": 500,
        "markup": ";rectangle,100x100,300x300,red;",
        "srcImageInfo": {
            "width": 1000,
            "height": 1000,
            "image": {"original": "https://example.test/one-original.png"},
        },
    }

    _run(db_session, client)

    annotation = db_session.scalars(select(Annotation)).one()
    assert (annotation.x, annotation.y) == (0.1, 0.1)
    assert (annotation.width, annotation.height) == (0.2, 0.2)


def test_annotations_land_on_the_image_they_belong_to(db_session, author_account, media_root):
    """The shape on the picture is half of the instruction the bullet gives."""
    _run(db_session, FakeDozuki([_guide()]))

    annotation = db_session.scalars(select(Annotation)).one()
    assert annotation.shape == "rectangle"
    assert annotation.color == "red"
    assert (annotation.x, annotation.y, annotation.width, annotation.height) == (0.1, 0.1, 0.2, 0.2)

    media = db_session.scalars(select(Media)).one()
    assert annotation.media_id == media.id


def test_a_private_guide_arrives_finished_but_staff_only(db_session, author_account, media_root):
    """It was written, correct and in daily use; only its audience was narrower.

    Importing it as a draft — which is what happened before guides had a
    visibility — said nobody had written it, and made publishing it, the obvious
    thing to do with a finished guide, a disclosure to the whole institute.
    """
    client = FakeDozuki([_guide(public=False)])
    importer = Importer(db_session, client, _options(include_private=True), get_settings())
    importer.import_guides()

    guide = db_session.scalars(select(Guide)).one()
    assert guide.status == "published"
    assert guide.visibility == "staff"
    assert guide.published_at is not None
    assert guide.version == 1


def test_a_public_guide_arrives_readable_by_everyone(db_session, author_account, media_root):
    _run(db_session, FakeDozuki([_guide()]))

    assert db_session.scalars(select(Guide)).one().visibility == "everyone"


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
    # The original, which is what actually gets downloaded now.
    client.failing_urls.add("https://example.test/one-original.png")

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


def _category_wiki(**overrides) -> dict:
    payload = {
        "wikiid": 77,
        "namespace": "CATEGORY",
        "title": "Light Microscopy",
        "description": "Widefield, confocal and live-cell systems.",
        "image": {
            "id": 4165,
            "thumbnail": "https://example.test/section-small.jpg",
            "original": "https://example.test/section.jpg",
        },
    }
    payload.update(overrides)
    return payload


def test_a_section_arrives_with_the_words_and_the_picture_its_banner_needs(
    db_session, author_account, media_root
):
    """Both halves of a section's front matter, from the payload that has them.

    The description was already read; the picture was not, so every imported
    section came out with ZMB's own sentence under a drawn placeholder. Both
    are in the same response, and the run already fetches it.
    """
    client = FakeDozuki([_guide()], {"CATEGORY": [_category_wiki()]})
    _run(db_session, client)

    page = db_session.scalars(select(Page).where(Page.is_landing.is_(True))).one()
    assert page.summary == "Widefield, confocal and live-cell systems."
    assert page.hero_media_id is not None

    media = db_session.get(Media, page.hero_media_id)
    assert media is not None and media.kind == "image"
    # The size it was taken at, not the size it was shown at.
    assert "https://example.test/section.jpg" in client.downloads
    assert "https://example.test/section-small.jpg" not in client.downloads


def test_a_second_run_does_not_fetch_a_sections_picture_again(
    db_session, author_account, media_root
):
    client = FakeDozuki([_guide()], {"CATEGORY": [_category_wiki()]})
    _run(db_session, client)
    before = client.downloads.count("https://example.test/section.jpg")

    _run(db_session, client)

    assert before == 1
    assert client.downloads.count("https://example.test/section.jpg") == 1
    assert db_session.scalars(select(Page).where(Page.is_landing.is_(True))).one().hero_media_id


def test_a_section_whose_picture_will_not_download_still_brings_its_page(
    db_session, author_account, media_root
):
    """The words are the page. The photograph at the top of it is not."""
    client = FakeDozuki([_guide()], {"CATEGORY": [_category_wiki()]})
    client.failing_urls.add("https://example.test/section.jpg")

    report = _run(db_session, client).report

    page = db_session.scalars(select(Page).where(Page.is_landing.is_(True))).one()
    assert page.hero_media_id is None
    assert page.summary == "Widefield, confocal and live-cell systems."
    assert any("did not download" in note for note in report.skipped)


def test_skipping_media_skips_a_sections_picture_too(db_session, author_account, media_root):
    client = FakeDozuki([_guide()], {"CATEGORY": [_category_wiki()]})
    _run(db_session, client, _options(skip_media=True))

    page = db_session.scalars(select(Page).where(Page.is_landing.is_(True))).one()
    assert page.hero_media_id is None
    assert client.downloads == []


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


# --- guide embeds on wiki pages -------------------------------------------


def _wiki(body: str, wiki_id: int = 77, title: str = "Accessing Your Data") -> dict:
    return {
        "wikiid": wiki_id,
        "namespace": "WIKI",
        "title": title,
        "contents_raw": body,
    }


def test_an_embed_pointing_at_an_imported_guide_becomes_a_guide_block(
    db_session, author_account, media_root
):
    client = FakeDozuki(
        [_guide(1234)],
        {"WIKI": [_wiki("Start here:\n\n[guide|1234|Starting a Session]")]},
    )
    importer = _run(db_session, client)

    guide = db_session.scalars(select(Guide)).one()
    page = db_session.scalars(select(Page)).one()
    assert page.body == f"Start here:\n\n```guide\n{guide.slug}\n```"
    assert importer.report.guide_embeds_resolved == 1
    assert importer.report.guide_embeds_unresolved == []


def test_a_page_imported_before_the_guide_it_names_still_gets_its_block(
    db_session, author_account, media_root
):
    """The second pass is why: at the moment the page was written the guide it
    names had not been imported, so nothing could have translated the id then."""
    client = FakeDozuki(
        [_guide(1234)],
        {"WIKI": [_wiki("[guide|1234|Starting a Session]")]},
    )
    importer = Importer(db_session, client, _options(), get_settings())
    importer.import_pages()
    assert db_session.scalars(select(Page)).one().body == "[guide|1234|Starting a Session]"

    importer.import_guides()
    importer.resolve_page_guide_embeds()

    guide = db_session.scalars(select(Guide)).one()
    assert db_session.scalars(select(Page)).one().body == f"```guide\n{guide.slug}\n```"


def test_an_embed_naming_a_guide_outside_the_import_is_left_alone_and_counted(
    db_session, author_account, media_root
):
    """A guide deleted from the site, or one outside the imported set. The
    marker stays visible and the report says so, because a pointer that quietly
    disappears during a one-time migration is found years later, if at all."""
    client = FakeDozuki(
        [_guide(1234)],
        {"WIKI": [_wiki("[guide|1234|Kept]\n\n[guide|4321|Gone]")]},
    )
    importer = _run(db_session, client)

    page = db_session.scalars(select(Page)).one()
    assert "[guide|4321|Gone]" in page.body
    assert importer.report.guide_embeds_resolved == 1
    assert importer.report.guide_embeds_unresolved == ["Accessing Your Data: [guide|4321|Gone]"]

    text = importer.report.to_text()
    assert "[guide|4321|Gone]" in text
    assert "left as the site wrote them" in text


def test_the_json_report_carries_the_embed_counts(db_session, author_account, media_root):
    import json

    client = FakeDozuki([_guide(1234)], {"WIKI": [_wiki("[guide|4321|Gone]")]})
    importer = _run(db_session, client)

    decoded = json.loads(importer.report.to_json())
    assert decoded["guideEmbedsResolved"] == 0
    assert decoded["guideEmbedsUnresolved"] == ["Accessing Your Data: [guide|4321|Gone]"]


def test_the_pages_published_snapshot_is_rewritten_with_it(db_session, author_account, media_root):
    """A revision that differs from the page it claims to be a copy of is worse
    than no revision at all: it is what somebody reaches for to find out what
    was actually published."""
    from app.models import PageRevision

    client = FakeDozuki([_guide(1234)], {"WIKI": [_wiki("[guide|1234|Starting a Session]")]})
    _run(db_session, client)

    page = db_session.scalars(select(Page)).one()
    revision = db_session.scalars(select(PageRevision)).one()
    assert revision.document["body"] == page.body
    assert "```guide" in revision.document["body"]


def test_a_dry_run_does_not_rewrite_a_page_an_earlier_run_left(
    db_session, author_account, media_root
):
    """--dry-run promises to write nothing, and pages from a previous real run
    are sitting in the database it would otherwise reach into."""
    client = FakeDozuki([_guide(1234)], {"WIKI": [_wiki("[guide|1234|Starting a Session]")]})
    Importer(db_session, client, _options(), get_settings()).import_pages()
    before = db_session.scalars(select(Page)).one().body

    _run(db_session, client, _options(dry_run=True))

    assert db_session.scalars(select(Page)).one().body == before


# ---------------------------------------------------------------- video path


class ClientWithVideo(FakeDozuki):
    """A vendor whose steps carry a clip as well as photographs."""

    clip_padding = 64

    def download(self, url: str):
        from app.importer.client import FetchedFile

        if url.endswith(".mp4"):
            self.downloads.append(url)
            return FetchedFile(
                payload=mp4_bytes(padding=self.clip_padding), content_type="video/mp4", url=url
            )
        return super().download(url)


def _guide_with_a_clip(video_url: str = "https://example.test/seating-the-cube.mp4") -> dict:
    return {
        "guideid": 4001,
        "title": "Seating a filter cube",
        "public": True,
        "category": "Light Microscopy",
        "steps": [
            {
                "stepid": 1,
                "orderby": 1,
                "title": "Seat it square",
                "lines": [{"text_raw": "Push until it clicks.", "bullet": "black", "level": 0}],
                "media": {"type": "video", "data": {"url": video_url}},
            }
        ],
    }


def test_a_step_video_is_downloaded_and_stored_as_a_clip(db_session, author_account):
    """The importer's video path, which no test reached.

    A guide demonstrating a movement is exactly the kind that has one, and the
    whole branch — the download, the size refusal, the container sniff and the
    ledger entry that stops a re-run fetching it twice — had never run.
    """
    client = ClientWithVideo([_guide_with_a_clip()])
    _run(db_session, client)

    stored = db_session.scalars(select(Media).where(Media.kind == "video")).all()
    assert len(stored) == 1
    assert stored[0].content_type == "video/mp4"
    assert stored[0].byte_size > 0


def test_a_second_run_does_not_download_the_same_clip_again(db_session, author_account):
    """The ledger, not the filename, is what makes a re-run cheap and safe."""
    client = ClientWithVideo([_guide_with_a_clip()])
    _run(db_session, client)
    first = list(client.downloads)

    _run(db_session, client)

    assert client.downloads == first, "the clip was fetched a second time"
    assert db_session.scalars(select(Media).where(Media.kind == "video")).all().__len__() == 1


def test_a_clip_above_the_cap_is_refused_and_named_in_the_report(
    db_session, author_account, monkeypatch
):
    """Refusing is the point, and so is saying which guide it happened to.

    The run does not stop — one oversized clip should not abandon 250 other
    guides — so the failure is recorded against the guide it belongs to. A
    migration that quietly skipped the file would leave a procedure whose
    demonstration is missing and no way to find out which.
    """
    monkeypatch.setenv("RETICLE_MAX_VIDEO_BYTES", "1024")
    get_settings.cache_clear()

    client = ClientWithVideo([_guide_with_a_clip()])
    client.clip_padding = 4096  # comfortably over the cap set above

    importer = _run(db_session, client)

    failures = [failure for tally in importer.report.guides for failure in tally.failures]
    assert any("above the configured cap" in failure for failure in failures), failures
    assert db_session.scalars(select(Media).where(Media.kind == "video")).all() == []
