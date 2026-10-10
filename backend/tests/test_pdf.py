"""The printable PDF export of a guide.

A PDF cannot be asserted on by eye in a test, so these read it back: the text
with ``pypdf``, and the drawing operators in the page content stream for the
things that are drawn rather than typeset — annotation strokes and images.
"""

from __future__ import annotations

from io import BytesIO

import pytest
from pypdf import PdfReader
from sqlalchemy import select

from app import pdf
from app.models import Media

from .conftest import (
    annotation,
    bullet,
    create_guide,
    image_bytes,
    publish_guide,
    save_guide,
    step,
    upload_media,
    upload_video,
)

RED_STROKE = b".819608 .141176 .184314 RG"
LIGHT_BLUE_STROKE = b".054902 .454902 .564706 RG"
GREEN_STROKE = b".101961 .498039 .215686 RG"


def fetch(client, key: str) -> PdfReader:
    response = client.get(f"/api/guides/{key}/pdf")
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"%PDF-")
    return PdfReader(BytesIO(response.content))


def text_of(reader: PdfReader) -> str:
    return "\n".join(page.extract_text() for page in reader.pages)


def drawing_of(reader: PdfReader) -> bytes:
    return b"\n".join(page.get_contents().get_data() for page in reader.pages)


def rich_guide(author, category) -> dict:
    created = create_guide(author, category.id, "Setting Up a Tile Scan")
    picture = {**upload_media(author, image_bytes(320, 200)), "alt": "The toolbar"}
    picture["annotations"] = [
        annotation("rectangle", "red"),
        annotation("ellipse", "green"),
        annotation("arrow", "light_blue", x=0.9, y=0.9, width=-0.5, height=-0.4),
    ]
    return save_guide(
        author,
        created,
        summary="Define the region and let the stage stitch it.",
        difficulty="difficult",
        timeRequiredMinMinutes=30,
        timeRequiredMaxMinutes=90,
        tags=["Confocal", "LAS X"],
        introduction="Set it up at low magnification.\n\nThen switch objective.",
        conclusion="Check the overview before unmounting.",
        steps=[
            step(
                "Open the Navigator",
                bullets=[
                    bullet("Click the Navigator button.", color="red"),
                    bullet("The stage map takes over.", level=1),
                    bullet("Deeper detail.", level=2, color="violet"),
                    bullet("The stage must be initialised.", color="blue", icon="note"),
                    bullet("Never force the stage.", color="red", icon="caution"),
                    bullet("Book enough time.", color="violet", icon="reminder"),
                ],
                media=[picture],
            ),
            step("Mark the region", bullets=[bullet("Drag a rectangle.", color="green")]),
        ],
    )


def test_the_export_is_a_pdf_attachment_named_after_the_slug(author, category):
    guide = rich_guide(author, category)

    response = author.get(f"/api/guides/{guide['id']}/pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == 'attachment; filename="setting-up-a-tile-scan.pdf"'
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "no-store" in response.headers["cache-control"]
    assert response.content.startswith(b"%PDF-")
    assert author.get(f"/api/guides/{guide['slug']}/pdf").status_code == 200


def test_the_document_carries_everything_the_reader_page_does(author, category):
    guide = publish_guide(author, rich_guide(author, category))

    reader = fetch(author, guide["slug"])
    text = " ".join(text_of(reader).split())

    for expected in (
        "Setting Up a Tile Scan",
        "Define the region and let the stage stitch it.",
        "Light Microscopy",
        "Difficulty: Difficult",
        "Time: 30 min – 1 h 30 min",
        "Tags: confocal, las-x",
        "Version 1",
        f"Last updated {guide['updatedAt'][:10]}",
        "Introduction",
        "Set it up at low magnification.",
        "Then switch objective.",
        "Step 1",
        "Open the Navigator",
        "Click the Navigator button.",
        "Deeper detail.",
        "Note: The stage must be initialised.",
        "Caution: Never force the stage.",
        "Reminder: Book enough time.",
        "Step 2",
        "Mark the region",
        "Conclusion",
        "Check the overview before unmounting.",
    ):
        assert expected in text, expected
    assert reader.metadata.title == "Setting Up a Tile Scan"
    assert text.index("Step 1") < text.index("Step 2") < text.index("Conclusion")


def test_every_page_has_a_footer_with_title_version_and_page_x_of_y(author, category):
    created = create_guide(author, category.id, "A Long Procedure")
    saved = save_guide(
        author,
        created,
        steps=[step(f"Stage {index}", bullets=[bullet("Line of instruction. " * 12)] * 6) for index in range(14)],
    )
    publish_guide(author, saved)

    reader = fetch(author, created["id"])

    total = len(reader.pages)
    assert total >= 3
    for number, page in enumerate(reader.pages, start=1):
        text = page.extract_text()
        assert f"Page {number} of {total}" in text
        assert "A Long Procedure" in text
        assert "version 1" in text


def test_annotations_are_drawn_over_the_image_in_their_colours(author, category):
    with_shapes = fetch(author, rich_guide(author, category)["id"])
    plain = create_guide(author, category.id, "Plain")
    save_guide(author, plain, steps=[step("Picture", media=[upload_media(author)])])
    without = fetch(author, plain["id"])

    drawing = drawing_of(with_shapes)

    assert sum(len(page.images) for page in with_shapes.pages) == 1
    for stroke in (RED_STROKE, GREEN_STROKE, LIGHT_BLUE_STROKE):
        assert stroke in drawing
        assert stroke not in drawing_of(without)
    assert b" c\n" in drawing or b" c " in drawing, "an ellipse is drawn with Bézier curves"


def test_annotation_geometry_is_flipped_into_pdf_coordinates():
    """Stored fractions are measured from the top-left; PDF from the bottom-left."""
    from reportlab.pdfgen.canvas import Canvas

    from app.schemas import AnnotationOut

    class Recording(Canvas):
        def __init__(self) -> None:
            super().__init__(BytesIO())
            self.rects, self.lines = [], []

        def rect(self, x, y, width, height, **kwargs):
            self.rects.append((round(x, 3), round(y, 3), round(width, 3), round(height, 3)))

        def line(self, x1, y1, x2, y2):
            self.lines.append((round(x1, 3), round(y1, 3), round(x2, 3), round(y2, 3)))

    canvas = Recording()
    box = AnnotationOut(id="a", shape="rectangle", color="red", x=0.1, y=0.2, width=0.3, height=0.25)
    arrow = AnnotationOut(id="b", shape="arrow", color="blue", x=0.5, y=0.5, width=-0.5, height=-0.5)
    dot = AnnotationOut(id="c", shape="arrow", color="blue", x=0.5, y=0.5, width=0, height=0)

    pdf.draw_annotation(canvas, box, 100, 1000, 200, 100)
    assert set(canvas.rects) == {(120.0, 1055.0, 60.0, 25.0)}

    pdf.draw_annotation(canvas, arrow, 0, 0, 200, 100)
    shaft = canvas.lines[0]
    assert shaft == (100.0, 50.0, 0.0, 100.0), "an arrow up and to the left ends at the top-left corner"
    assert len(canvas.lines) == 6, "a shaft and two head strokes, each drawn as halo then colour"

    canvas.lines.clear()
    pdf.draw_annotation(canvas, dot, 0, 0, 200, 100)
    assert len(canvas.lines) == 2, "a zero-length arrow has no head to compute"


def test_an_image_reused_across_steps_is_decoded_once(author, category, monkeypatch):
    calls = []
    original = pdf.embed_image
    monkeypatch.setattr(pdf, "embed_image", lambda path: calls.append(path) or original(path))
    created = create_guide(author, category.id, "Same Screenshot")
    picture = upload_media(author)
    save_guide(
        author,
        created,
        steps=[step(f"Step {index}", media=[{**picture, "annotations": [annotation()]}]) for index in range(5)],
    )

    reader = fetch(author, created["id"])

    assert len(calls) == 1
    assert RED_STROKE in drawing_of(reader)


def test_up_to_three_images_share_a_row(author, category):
    created = create_guide(author, category.id, "Three Pictures")
    pictures = [upload_media(author, image_bytes(300 + index * 40, 200)) for index in range(3)]
    save_guide(author, created, steps=[step("Compare", media=pictures)])

    reader = fetch(author, created["id"])

    assert len(reader.pages) == 1
    assert len(reader.pages[0].images) == 3


def test_a_video_is_represented_by_a_line_not_embedded(author, category):
    created = create_guide(author, category.id, "With a Clip")
    clip = {**upload_video(author), "alt": "Lowering the coverslip"}
    save_guide(author, created, steps=[step("Watch", media=[clip])])

    reader = fetch(author, created["id"])

    assert "Video: view this step online" in text_of(reader)
    assert "Lowering the coverslip" in text_of(reader)
    assert sum(len(page.images) for page in reader.pages) == 0


def test_user_text_is_never_interpreted_as_markup(author, category):
    """ReportLab paragraphs parse an XML-like tag language. Everything an author
    typed has to come out as the characters they typed."""
    hostile = '<b>bold</b> & <font color="red">red</font> <img src="/etc/passwd"/> </para><para> &amp; <unclosed'
    created = create_guide(author, category.id, "Escaping <i>Title</i> & Co")
    save_guide(
        author,
        created,
        summary=hostile,
        introduction=hostile,
        conclusion=hostile,
        tags=["a-b"],
        steps=[step(hostile, bullets=[bullet(hostile, icon="caution"), bullet("<a href='x'>link</a>")])],
    )

    reader = fetch(author, created["id"])
    text = " ".join(text_of(reader).split())

    assert "Escaping <i>Title</i> & Co" in text
    assert text.count('<b>bold</b> & <font color="red">red</font>') == 5
    assert "</para><para> &amp; <unclosed" in text
    assert "<a href='x'>link</a>" in text
    assert sum(len(page.images) for page in reader.pages) == 0


def test_awkward_characters_do_not_break_the_export(author, category):
    created = create_guide(author, category.id, "Präparation bei 4 °C — 10 µm")
    save_guide(
        author,
        created,
        introduction="Control\x07chars\x00and\ttabs\r\nλ = 488 nm ≥ 顕微鏡 🔬",
        steps=[step("x" * 400, bullets=[bullet("y" * 4000), bullet("")])],
    )

    text = text_of(fetch(author, created["id"]))

    assert "Präparation bei 4 °C — 10 µm" in text
    assert "Control chars and tabs" in " ".join(text.split())


def test_a_draft_exports_and_says_it_is_unpublished(author, category):
    created = create_guide(author, category.id, "Still a Draft")

    text = text_of(fetch(author, created["id"]))

    assert "Unpublished draft" in text
    assert "unpublished draft" in text
    assert "Step 1" not in text


def test_an_image_whose_file_is_gone_is_noted_and_the_rest_still_exports(author, category, db_session, media_root):
    created = create_guide(author, category.id, "Missing Picture")
    picture = upload_media(author)
    save_guide(author, created, steps=[step("Look", bullets=[bullet("Still here.")], media=[picture])])
    (media_root / db_session.scalars(select(Media)).one().storage_path).unlink()

    text = text_of(fetch(author, created["id"]))

    assert "could not be included" in text
    assert "Still here." in text


def test_an_image_that_will_not_decode_is_noted_too(author, category, db_session, media_root):
    created = create_guide(author, category.id, "Corrupt Picture")
    picture = upload_media(author)
    save_guide(author, created, steps=[step("Look", media=[picture])])
    (media_root / db_session.scalars(select(Media)).one().storage_path).write_bytes(b"not an image any more")

    assert "could not be included" in text_of(fetch(author, created["id"]))


def test_a_transparent_image_is_flattened_onto_white(tmp_path):
    from PIL import Image

    path = tmp_path / "clear.png"
    Image.new("RGBA", (40, 40), (0, 0, 0, 0)).save(path)

    embedded = pdf.embed_image(path)

    assert embedded is not None
    assert embedded.reader.getRGBData()[:3] == b"\xff\xff\xff"


def test_a_large_image_is_shrunk_before_it_is_embedded(author, category):
    """A stitched panel must not put its full resolution into every export."""
    created = create_guide(author, category.id, "Big Panel")
    save_guide(author, created, steps=[step("Overview", media=[upload_media(author, image_bytes(3000, 1800))])])

    reader = fetch(author, created["id"])

    embedded = reader.pages[0].images[0].image
    assert max(embedded.size) == pdf.EMBED_MAX_PIXELS


@pytest.mark.parametrize(
    "low,high,expected",
    [
        (None, None, None),
        (30, None, "from 30 min"),
        (None, 90, "up to 1 h 30 min"),
        (45, 45, "45 min"),
        (30, 120, "30 min – 2 h"),
        (0, 5, "0 min – 5 min"),
    ],
)
def test_time_ranges_read_naturally(low, high, expected):
    assert pdf.format_time_range(low, high) == expected


def test_a_long_title_is_shortened_to_fit_the_footer():
    regular, _ = pdf.fonts()

    assert pdf.fit("Short", regular, 8, 400) == "Short"
    shortened = pdf.fit("An extremely long guide title " * 10, regular, 8, 200)
    assert shortened.endswith("…")
    assert pdf.pdfmetrics.stringWidth(shortened, regular, 8) <= 200


def test_the_bundled_font_is_used_when_no_system_font_is_found(monkeypatch):
    monkeypatch.setattr(pdf, "FONT_CANDIDATES", (("missing.ttf", "missing-bold.ttf", ("/nonexistent",)),))
    pdf.fonts.cache_clear()
    try:
        assert pdf.fonts() == ("Reticle", "Reticle-Bold")
    finally:
        pdf.fonts.cache_clear()
        pdf.styles.cache_clear()


def test_the_pdf_follows_the_same_visibility_rule_as_the_guide(author, admin, viewer, category):
    draft = rich_guide(author, category)
    assert viewer.get(f"/api/guides/{draft['id']}/pdf").status_code == 404
    assert viewer.get(f"/api/guides/{draft['slug']}/pdf").json()["error"]["code"] == "not_found"

    publish_guide(author, draft)
    assert viewer.get(f"/api/guides/{draft['slug']}/pdf").status_code == 200

    author.post(f"/api/guides/{draft['id']}/unpublish")
    assert viewer.get(f"/api/guides/{draft['slug']}/pdf").status_code == 404
    assert author.get(f"/api/guides/{draft['slug']}/pdf").status_code == 200

    admin.delete(f"/api/guides/{draft['id']}")
    assert author.get(f"/api/guides/{draft['slug']}/pdf").status_code == 404
    assert admin.get(f"/api/guides/{draft['slug']}/pdf").status_code == 404


def test_an_unknown_guide_has_no_pdf(author):
    assert author.get("/api/guides/no-such-guide/pdf").status_code == 404


def test_exports_queue_and_then_give_up_rather_than_pile_up(author, category, monkeypatch):
    """Rendering is the costliest thing a reader can ask for. When every slot is
    busy the next request waits briefly and is then told to come back."""
    created = create_guide(author, category.id)
    monkeypatch.setattr(pdf, "RENDER_WAIT_SECONDS", 0.01)
    held = [pdf._render_slots.acquire(timeout=1) for _ in range(pdf.MAX_CONCURRENT_RENDERS)]
    try:
        assert all(held)
        response = author.get(f"/api/guides/{created['id']}/pdf")
    finally:
        for _ in held:
            pdf._render_slots.release()

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
    assert author.get(f"/api/guides/{created['id']}/pdf").status_code == 200


def test_the_largest_guide_the_api_accepts_still_exports(author, category):
    """The ceilings on a document are also the ceilings on what the renderer is
    ever handed: many steps, deep bullets, three images to a step."""
    created = create_guide(author, category.id, "Everything at Once")
    pictures = [{**upload_media(author, image_bytes(600, 400)), "annotations": [annotation()] * 50} for _ in range(3)]
    steps = [
        step(
            f"Step {index}",
            bullets=[bullet("word " * 40, level=level % 3, icon=("note" if level % 5 == 0 else None)) for level in range(20)],
            media=pictures,
        )
        for index in range(40)
    ]
    save_guide(author, created, steps=steps)

    reader = fetch(author, created["id"])

    assert len(reader.pages) > 40
    assert "Step 40" in reader.pages[-1].extract_text() or "Step 40" in text_of(reader)
