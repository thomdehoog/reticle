"""Upload validation and safe delivery of image bytes.

Uploads are the most exposed surface in the application, so the assertions here
are about what actually reaches disk and what actually comes back over the
wire, not merely about status codes.
"""

from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image
from sqlalchemy import select

from app.models import Media
from app.settings import get_settings

from .conftest import (
    create_guide,
    document_from,
    image_bytes,
    jpeg_with_exif,
    noisy_png,
    step,
    upload_media,
)


def _attach_to_guide(author, category, image: dict, publish: bool) -> dict:
    """Put an uploaded image on a guide, optionally publishing it."""
    created = create_guide(author, category.id)
    saved = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(created, steps=[step("Mount the sample", media=[image])]),
    )
    assert saved.status_code == 200, saved.text
    if publish:
        published = author.post(f"/api/guides/{created['id']}/publish")
        assert published.status_code == 200, published.text
    return saved.json()


def test_uploading_a_png_returns_the_domain_media_object(author, media_root):
    response = author.post(
        "/api/media", files={"file": ("turret.png", image_bytes(64, 48), "image/png")}
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {
        "id",
        "url",
        "kind",
        "alt",
        "width",
        "height",
        "durationSeconds",
        "posterUrl",
        "annotations",
    }
    assert body["kind"] == "image"
    assert body["width"] == 64
    assert body["height"] == 48
    assert body["alt"] == ""
    assert body["durationSeconds"] is None
    assert body["posterUrl"] is None
    assert body["annotations"] == []
    assert body["url"] == f"/api/media/{body['id']}"


@pytest.mark.parametrize(
    "image_format,mime",
    [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp"), ("GIF", "image/gif")],
)
def test_the_four_accepted_formats_round_trip(author, image_format, mime):
    payload = image_bytes(20, 12, image_format)

    created = author.post(
        "/api/media", files={"file": (f"x.{image_format.lower()}", payload, mime)}
    ).json()
    fetched = author.get(f"/api/media/{created['id']}")

    assert fetched.status_code == 200
    assert fetched.headers["content-type"] == mime
    assert Image.open(BytesIO(fetched.content)).size == (20, 12)


def test_a_text_file_renamed_to_png_is_rejected(author, media_root):
    payload = b"#!/bin/sh\necho this is not an image at all\n"

    response = author.post("/api/media", files={"file": ("payload.png", payload, "image/png")})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"
    assert not (media_root.exists() and [p for p in media_root.rglob("*") if p.is_file()])


def test_html_disguised_as_an_image_is_rejected(author):
    payload = b"<html><script>alert(document.cookie)</script></html>"

    response = author.post("/api/media", files={"file": ("xss.png", payload, "image/png")})

    assert response.status_code == 422


def test_an_svg_is_rejected_because_it_is_executable_markup(author):
    payload = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'

    assert (
        author.post(
            "/api/media", files={"file": ("vector.svg", payload, "image/svg+xml")}
        ).status_code
        == 422
    )


def test_a_truncated_image_is_rejected(author):
    payload = image_bytes(40, 40, "PNG")[:60]

    assert (
        author.post("/api/media", files={"file": ("cut.png", payload, "image/png")}).status_code
        == 422
    )


def test_a_corrupted_image_is_rejected_rather_than_stored(author, media_root):
    """A half-transferred upload has a valid header and a broken payload; it
    must not reach disk, where it would only fail years later on a reader's
    screen."""
    raw = bytearray(image_bytes(40, 40, "PNG"))
    raw[raw.find(b"IDAT") + 8] ^= 0xFF

    response = author.post("/api/media", files={"file": ("corrupt.png", bytes(raw), "image/png")})

    assert response.status_code == 422
    assert not (media_root.exists() and [p for p in media_root.rglob("*") if p.is_file()])


def test_an_unsupported_but_genuine_image_format_is_rejected(author):
    buffer = BytesIO()
    Image.new("RGB", (8, 8), "white").save(buffer, format="BMP")

    response = author.post(
        "/api/media", files={"file": ("bitmap.bmp", buffer.getvalue(), "image/bmp")}
    )

    assert response.status_code == 422
    assert "png" in response.json()["error"]["message"].lower()


def test_an_empty_upload_is_rejected(author):
    assert (
        author.post("/api/media", files={"file": ("empty.png", b"", "image/png")}).status_code
        == 422
    )


def test_an_image_wider_than_the_limit_is_rejected(author, monkeypatch):
    monkeypatch.setenv("RETICLE_MAX_IMAGE_DIMENSION", "64")
    get_settings.cache_clear()

    response = author.post(
        "/api/media", files={"file": ("wide.png", image_bytes(65, 8), "image/png")}
    )

    assert response.status_code == 422
    assert "64" in response.json()["error"]["message"]


def test_an_image_taller_than_the_limit_is_rejected(author, monkeypatch):
    monkeypatch.setenv("RETICLE_MAX_IMAGE_DIMENSION", "64")
    get_settings.cache_clear()

    assert (
        author.post(
            "/api/media", files={"file": ("tall.png", image_bytes(8, 65), "image/png")}
        ).status_code
        == 422
    )


def test_the_default_dimension_limit_is_ten_thousand():
    assert get_settings().max_image_dimension == 10000


def test_the_default_upload_cap_is_twenty_megabytes():
    assert get_settings().max_upload_bytes == 20 * 1024 * 1024


def test_an_oversized_body_is_refused_with_payload_too_large(author, monkeypatch):
    monkeypatch.setenv("RETICLE_MAX_UPLOAD_BYTES", "2048")
    get_settings.cache_clear()

    response = author.post("/api/media", files={"file": ("big.png", noisy_png(), "image/png")})

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_a_hopelessly_oversized_upload_is_refused_from_its_declared_length(
    author, monkeypatch, media_root
):
    """Streaming the body against the cap is the guarantee; refusing on the
    declared length first is what stops the process buffering a body it has
    already decided to reject."""
    monkeypatch.setenv("RETICLE_MAX_UPLOAD_BYTES", "1024")
    get_settings.cache_clear()

    response = author.post(
        "/api/media", files={"file": ("huge.png", noisy_png(700, 700), "image/png")}
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert not (media_root.exists() and [p for p in media_root.rglob("*") if p.is_file()])


def test_exif_is_stripped_from_what_is_stored(author, db_session, media_root):
    original = jpeg_with_exif()
    assert Image.open(BytesIO(original)).getexif().get(0x010F) == "ZMB-Stellaris"

    created = author.post(
        "/api/media", files={"file": ("camera.jpg", original, "image/jpeg")}
    ).json()
    served = author.get(f"/api/media/{created['id']}").content

    assert dict(Image.open(BytesIO(served)).getexif()) == {}
    stored = db_session.scalars(select(Media)).one()
    assert dict(Image.open(media_root / stored.storage_path).getexif()) == {}


def test_the_stored_filename_is_generated_and_the_original_never_used(
    author, db_session, media_root
):
    created = author.post(
        "/api/media", files={"file": ("Ünsafe Name (1).png", image_bytes(), "image/png")}
    ).json()

    stored = db_session.scalars(select(Media)).one()
    on_disk = list(media_root.rglob("*.png"))

    assert len(on_disk) == 1
    assert created["id"] in stored.storage_path
    assert "Ünsafe" not in stored.storage_path
    assert on_disk[0].stem.endswith(created["id"])


def test_a_traversing_filename_cannot_escape_the_media_root(author, media_root):
    created = author.post(
        "/api/media",
        files={"file": ("../../../../windows/system32/evil.png", image_bytes(), "image/png")},
    ).json()

    assert created["id"]
    assert len(list(media_root.rglob("*.png"))) == 1
    assert not (media_root.parent.parent / "evil.png").exists()


def test_serving_an_image_forbids_sniffing_and_inline_scripting(author):
    created = author.post(
        "/api/media", files={"file": ("x.png", image_bytes(), "image/png")}
    ).json()

    response = author.get(f"/api/media/{created['id']}")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"].startswith("inline")
    assert response.headers["content-type"] == "image/png"
    assert "attachment" not in response.headers["content-disposition"]


def test_the_served_bytes_are_the_stored_bytes(author, db_session, media_root):
    created = author.post(
        "/api/media", files={"file": ("x.png", image_bytes(30, 20), "image/png")}
    ).json()

    stored = db_session.scalars(select(Media)).one()
    assert (
        author.get(f"/api/media/{created['id']}").content
        == (media_root / stored.storage_path).read_bytes()
    )


def test_media_bytes_are_behind_the_login(anon, author):
    created = author.post(
        "/api/media", files={"file": ("x.png", image_bytes(), "image/png")}
    ).json()

    assert anon.get(f"/api/media/{created['id']}").status_code == 401


def test_viewers_may_read_an_image_on_a_published_guide_but_not_upload(viewer, author, category):
    image = upload_media(author)
    _attach_to_guide(author, category, image, publish=True)

    assert viewer.get(f"/api/media/{image['id']}").status_code == 200
    assert (
        viewer.post("/api/media", files={"file": ("x.png", image_bytes(), "image/png")}).status_code
        == 403
    )


def test_a_viewer_cannot_read_an_image_from_an_unpublished_guide(viewer, author, category):
    """Authentication is not the same as permission.

    The realistic case is not a guessed URL — media ids are ULIDs. It is a guide
    that was unpublished *because* it turned out to hold something it should
    not, whose images would otherwise keep being served to every account for
    ever.
    """
    image = upload_media(author)
    guide = _attach_to_guide(author, category, image, publish=False)

    assert viewer.get(f"/api/guides/{guide['id']}").status_code == 404
    assert viewer.get(f"/api/media/{image['id']}").status_code == 404


def test_unpublishing_a_guide_withdraws_its_images_too(viewer, author, category):
    image = upload_media(author)
    guide = _attach_to_guide(author, category, image, publish=True)
    assert viewer.get(f"/api/media/{image['id']}").status_code == 200

    assert author.post(f"/api/guides/{guide['id']}/unpublish").status_code == 200

    assert viewer.get(f"/api/media/{image['id']}").status_code == 404


def test_an_orphaned_upload_is_not_readable_by_a_viewer(viewer, author):
    """Media is never deleted, so an upload that was never attached to anything
    must not become a permanently readable object."""
    image = upload_media(author)

    assert author.get(f"/api/media/{image['id']}").status_code == 200
    assert viewer.get(f"/api/media/{image['id']}").status_code == 404


def test_an_unknown_media_id_is_not_found(author):
    assert author.get("/api/media/01JQNOTAREALULID00000000").status_code == 404


def test_a_media_row_whose_file_vanished_is_not_found(author, db_session, media_root):
    created = author.post(
        "/api/media", files={"file": ("x.png", image_bytes(), "image/png")}
    ).json()
    stored = db_session.scalars(select(Media)).one()
    (media_root / stored.storage_path).unlink()

    assert author.get(f"/api/media/{created['id']}").status_code == 404


def test_uploading_without_a_file_is_rejected(author):
    assert author.post("/api/media", data={"alt": "no file"}).status_code == 422
