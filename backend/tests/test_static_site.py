"""The offline copy, and the one rule it must never break.

A static snapshot has no login in front of it. Whatever is written into that
folder is readable by anyone who opens it, on a laptop, on a memory stick, in a
backup — and unlike the application, where visibility is a ``WHERE`` clause
somebody can go and re-check, a file that has been written and copied cannot be
un-published.

So the test that matters most here is not that a guide renders. It is that a
draft does not, and that a photograph belonging only to a draft is not sitting
in the media folder next to the published ones.

The rest guards the things that make the copy worth keeping: the shapes drawn
on the pictures, which are half of what a step says; the bullet colours that
pair with them; and the escaping, because this renderer builds HTML by joining
strings and a bullet containing a ``<`` would otherwise take the page with it.
"""

from __future__ import annotations

from app.static_site import annotation_overlay, duration, esc, publish
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


def published_guide(admin, category, title="Starting the Confocal", **fields):
    guide = create_guide(admin, category.id, title)
    saved = admin.put(f"/api/guides/{guide['id']}", json=document_from(guide, **fields))
    assert saved.status_code == 200, saved.text
    return admin.post(f"/api/guides/{guide['id']}/publish").json()


def site(db_session, tmp_path, name="site"):
    return publish(db_session, get_settings(), tmp_path / name), tmp_path / name


# --- the rule --------------------------------------------------------------


def test_a_draft_is_not_written_into_a_folder_that_has_no_login(
    admin, category, db_session, tmp_path
):
    create_guide(admin, category.id, "Unfinished Safety Procedure")

    report, out = site(db_session, tmp_path)

    assert report.guides == 0
    assert report.skipped_drafts == 1
    assert not (out / "g" / "unfinished-safety-procedure.html").exists()
    assert "Unfinished" not in (out / "index.html").read_text(encoding="utf-8")


def test_a_picture_only_a_draft_shows_is_not_copied_out(
    admin, category, db_session, tmp_path
):
    """The subtler half of the same rule, and the one nobody checks."""
    secret = upload_media(admin)
    draft = create_guide(admin, category.id, "Unpublished")
    admin.put(
        f"/api/guides/{draft['id']}",
        json=document_from(draft, steps=[step("Secret", media=[{"id": secret["id"], "alt": ""}])]),
    )

    shown = upload_media(admin)
    published_guide(
        admin,
        category,
        steps=[step("Shown", media=[{"id": shown["id"], "alt": "fine"}])],
    )

    report, out = site(db_session, tmp_path)

    copied = {path.name.split(".")[0] for path in (out / "media").iterdir()}
    assert shown["id"] in copied
    assert secret["id"] not in copied
    assert report.media == 1


def test_an_unpublished_wiki_page_is_left_out(admin, db_session, tmp_path):
    create_page(admin, title="Draft policy")

    report, out = site(db_session, tmp_path)

    assert report.pages == 0
    assert not (out / "w" / "draft-policy.html").exists()


# --- what the copy is for --------------------------------------------------


def test_a_published_guide_renders_with_its_steps_and_bullets(
    admin, category, db_session, tmp_path
):
    published_guide(
        admin,
        category,
        summary="From booking to shutdown.",
        timeRequiredMinMinutes=30,
        timeRequiredMaxMinutes=90,
        steps=[
            step(
                "Power up in order",
                bullets=[
                    bullet("Switch on the mains strip.", color="black"),
                    bullet("Never skip the self-test.", color="red", icon="caution"),
                    bullet("The 405 needs ten minutes.", color="light_blue", level=1),
                ],
            )
        ],
    )

    _, out = site(db_session, tmp_path)
    page = (out / "g" / "starting-the-confocal.html").read_text(encoding="utf-8")

    assert "Power up in order" in page
    assert "Never skip the self-test." in page
    assert "bullet--color-red" in page
    assert "bullet--color-light_blue" in page
    assert "bullet--level-1" in page
    assert "CAUTION" in page.upper()
    assert "30 min – 1 h 30 min" in page


def test_the_shapes_drawn_on_a_picture_are_redrawn_over_it(
    admin, category, db_session, tmp_path
):
    """Half of what a step says is on the picture, not beside it."""
    image = upload_media(admin)
    published_guide(
        admin,
        category,
        steps=[
            step(
                "Point at the release",
                media=[
                    annotated(
                        image,
                        annotation(shape="rectangle", color="red", x=0.1, y=0.2, width=0.3, height=0.4),
                        annotation(shape="arrow", color="blue", x=0.8, y=0.8, width=-0.3, height=-0.3),
                        annotation(shape="ellipse", color="green", x=0.1, y=0.6, width=0.2, height=0.2),
                    )
                ],
            )
        ],
    )

    _, out = site(db_session, tmp_path)
    page = (out / "g" / "starting-the-confocal.html").read_text(encoding="utf-8")

    assert "<svg class=\"overlay\"" in page
    assert "<rect" in page and "<line" in page and "<ellipse" in page
    assert "var(--bullet-red)" in page
    assert "var(--bullet-blue)" in page
    assert "var(--bullet-green)" in page


def test_the_picture_is_beside_its_page_and_the_link_resolves(
    admin, category, db_session, tmp_path
):
    image = upload_media(admin)
    published_guide(
        admin, category, steps=[step("Shown", media=[{"id": image["id"], "alt": "the turret"}])]
    )

    _, out = site(db_session, tmp_path)
    page = (out / "g" / "starting-the-confocal.html").read_text(encoding="utf-8")

    filename = next(path.name for path in (out / "media").iterdir())
    assert f'src="../media/{filename}"' in page
    assert (out / "media" / filename).exists()
    assert 'alt="the turret"' in page


def test_the_index_leads_to_everything_published(admin, category, db_session, tmp_path):
    published_guide(admin, category, title="Aligning the Confocal")
    page = create_page(admin, title="Immersion oil", category_id=category.id)
    admin.put(f"/api/pages/{page['id']}", json=page_document_from(page, body="Which oil, and when."))
    admin.post(f"/api/pages/{page['id']}/publish")

    _, out = site(db_session, tmp_path)
    index = (out / "index.html").read_text(encoding="utf-8")

    assert 'href="g/aligning-the-confocal.html"' in index
    assert 'href="w/immersion-oil.html"' in index
    assert (out / "assets" / "site.css").exists()


def test_it_needs_nothing_from_the_network(admin, category, db_session, tmp_path):
    """A basement microscope room is the case this exists for."""
    published_guide(admin, category)

    _, out = site(db_session, tmp_path)
    page = (out / "g" / "starting-the-confocal.html").read_text(encoding="utf-8")

    assert "http://" not in page
    assert "https://" not in page


# --- the renderer itself ---------------------------------------------------


def test_text_is_escaped_rather_than_concatenated_into_the_page(
    admin, category, db_session, tmp_path
):
    published_guide(
        admin,
        category,
        title="Using <script> tags",
        steps=[step("A step", bullets=[bullet('Set gain to "5" & press <Enter>')])],
    )

    _, out = site(db_session, tmp_path)
    rendered = next((out / "g").iterdir()).read_text(encoding="utf-8")

    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "&amp;" in rendered


def test_escaping_handles_the_empty_cases():
    assert esc(None) == ""
    assert esc("") == ""
    assert esc("<b>") == "&lt;b&gt;"


def test_a_time_range_reads_the_way_it_does_in_the_application():
    assert duration(30, 90) == "30 min – 1 h 30 min"
    assert duration(45, None) == "45 min"
    assert duration(None, None) == "Not specified"
    assert duration(60, 60) == "1 h"


def test_an_image_with_no_shapes_gets_no_overlay():
    assert annotation_overlay([]) == ""
