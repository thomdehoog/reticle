"""Upload validation and safe delivery of image and video bytes.

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
    create_page,
    document_from,
    image_bytes,
    jpeg_with_exif,
    mp4_bytes,
    noisy_png,
    published_page,
    save_page,
    step,
    upload_media,
    upload_video,
    webm_bytes,
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
    response = author.post("/api/media", files={"file": ("turret.png", image_bytes(64, 48), "image/png")})

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "kind", "url", "displayUrl", "alt", "width", "height", "annotations"}
    assert body["kind"] == "image"
    assert body["annotations"] == []
    assert body["width"] == 64
    assert body["height"] == 48
    assert body["alt"] == ""
    assert body["url"] == f"/api/media/{body['id']}"


@pytest.mark.parametrize(
    "image_format,mime",
    [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp"), ("GIF", "image/gif")],
)
def test_the_four_accepted_formats_round_trip(author, image_format, mime):
    payload = image_bytes(20, 12, image_format)

    created = author.post("/api/media", files={"file": (f"x.{image_format.lower()}", payload, mime)}).json()
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

    assert author.post("/api/media", files={"file": ("vector.svg", payload, "image/svg+xml")}).status_code == 422


def test_a_truncated_image_is_rejected(author):
    payload = image_bytes(40, 40, "PNG")[:60]

    assert author.post("/api/media", files={"file": ("cut.png", payload, "image/png")}).status_code == 422


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

    response = author.post("/api/media", files={"file": ("bitmap.bmp", buffer.getvalue(), "image/bmp")})

    assert response.status_code == 422
    assert "png" in response.json()["error"]["message"].lower()


def test_an_empty_upload_is_rejected(author):
    assert author.post("/api/media", files={"file": ("empty.png", b"", "image/png")}).status_code == 422


def test_an_image_wider_than_the_limit_is_rejected(author, monkeypatch):
    monkeypatch.setenv("RETICLE_MAX_IMAGE_DIMENSION", "64")
    get_settings.cache_clear()

    response = author.post("/api/media", files={"file": ("wide.png", image_bytes(65, 8), "image/png")})

    assert response.status_code == 422
    assert "64" in response.json()["error"]["message"]


def test_an_image_taller_than_the_limit_is_rejected(author, monkeypatch):
    monkeypatch.setenv("RETICLE_MAX_IMAGE_DIMENSION", "64")
    get_settings.cache_clear()

    assert author.post("/api/media", files={"file": ("tall.png", image_bytes(8, 65), "image/png")}).status_code == 422


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


def test_exif_is_stripped_from_what_is_stored(author, db_session, media_root):
    original = jpeg_with_exif()
    assert Image.open(BytesIO(original)).getexif().get(0x010F) == "ZMB-Stellaris"

    created = author.post("/api/media", files={"file": ("camera.jpg", original, "image/jpeg")}).json()
    served = author.get(f"/api/media/{created['id']}").content

    assert dict(Image.open(BytesIO(served)).getexif()) == {}
    stored = db_session.scalars(select(Media)).one()
    assert dict(Image.open(media_root / stored.storage_path).getexif()) == {}


def _sideways_photo(image_format: str = "JPEG") -> bytes:
    """A portrait photograph as a phone stores it: a landscape frame, red on the
    left and blue on the right, tagged "turn a quarter clockwise to view"."""
    frame = Image.new("RGB", (64, 32), (200, 0, 0))
    frame.paste((0, 0, 200), (32, 0, 64, 32))
    exif = Image.Exif()
    exif[0x0112] = 6
    buffer = BytesIO()
    frame.save(buffer, format=image_format, exif=exif.tobytes())
    return buffer.getvalue()


def _is_red(pixel) -> bool:
    return pixel[0] > 150 and pixel[2] < 80


def _is_blue(pixel) -> bool:
    return pixel[2] > 150 and pixel[0] < 80


@pytest.mark.parametrize(("image_format", "mime"), [("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")])
def test_a_photo_taken_in_portrait_is_stored_upright(author, image_format, mime):
    """Stripping EXIF used to strip the orientation with it, so every phone
    photo taken upright arrived lying on its side."""
    created = author.post("/api/media", files={"file": ("phone", _sideways_photo(image_format), mime)}).json()

    assert (created["width"], created["height"]) == (32, 64)
    served = Image.open(BytesIO(author.get(f"/api/media/{created['id']}").content)).convert("RGB")
    assert served.size == (32, 64)
    assert served.getexif().get(0x0112) is None
    assert _is_red(served.getpixel((16, 8)))
    assert _is_blue(served.getpixel((16, 56)))


def test_an_upright_image_is_not_turned_a_second_time():
    """The importer hands ``normalise`` pictures that were already normalised
    once; the orientation tag is consumed the first time, so nothing moves."""
    from app.images import normalise

    once = normalise(_sideways_photo(), 10_000, 40_000_000)
    twice = normalise(once.payload, 10_000, 40_000_000)

    assert (once.width, once.height) == (twice.width, twice.height) == (32, 64)
    assert _is_red(Image.open(BytesIO(twice.payload)).convert("RGB").getpixel((16, 8)))


def test_an_image_without_an_orientation_keeps_its_shape(author):
    created = author.post("/api/media", files={"file": ("a.jpg", jpeg_with_exif(), "image/jpeg")}).json()

    assert (created["width"], created["height"]) == (32, 24)


def test_an_animation_keeps_all_its_frames(author):
    """Turning is skipped for animations, because it would keep one frame."""
    frames = [Image.new("RGB", (20, 10), colour) for colour in ("red", "green", "blue")]
    buffer = BytesIO()
    frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:], duration=50)

    created = author.post("/api/media", files={"file": ("a.gif", buffer.getvalue(), "image/gif")}).json()

    served = Image.open(BytesIO(author.get(f"/api/media/{created['id']}").content))
    assert served.n_frames == 3
    assert (created["width"], created["height"]) == (20, 10)


def test_the_stored_filename_is_generated_and_the_original_never_used(author, db_session, media_root):
    created = author.post("/api/media", files={"file": ("Ünsafe Name (1).png", image_bytes(), "image/png")}).json()

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
    created = author.post("/api/media", files={"file": ("x.png", image_bytes(), "image/png")}).json()

    response = author.get(f"/api/media/{created['id']}")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"].startswith("inline")
    assert response.headers["content-type"] == "image/png"
    assert "attachment" not in response.headers["content-disposition"]


def test_the_served_bytes_are_the_stored_bytes(author, db_session, media_root):
    created = author.post("/api/media", files={"file": ("x.png", image_bytes(30, 20), "image/png")}).json()

    stored = db_session.scalars(select(Media)).one()
    assert author.get(f"/api/media/{created['id']}").content == (media_root / stored.storage_path).read_bytes()


def test_media_bytes_are_behind_the_login(anon, author):
    created = author.post("/api/media", files={"file": ("x.png", image_bytes(), "image/png")}).json()

    assert anon.get(f"/api/media/{created['id']}").status_code == 401


def test_viewers_may_read_an_image_on_a_published_guide_but_not_upload(viewer, author, category):
    image = upload_media(author)
    _attach_to_guide(author, category, image, publish=True)

    assert viewer.get(f"/api/media/{image['id']}").status_code == 200
    assert viewer.post("/api/media", files={"file": ("x.png", image_bytes(), "image/png")}).status_code == 403


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
    created = author.post("/api/media", files={"file": ("x.png", image_bytes(), "image/png")}).json()
    stored = db_session.scalars(select(Media)).one()
    (media_root / stored.storage_path).unlink()

    assert author.get(f"/api/media/{created['id']}").status_code == 404


def test_uploading_without_a_file_is_rejected(author):
    assert author.post("/api/media", data={"alt": "no file"}).status_code == 422


def test_alt_text_can_be_supplied_with_the_upload(author):
    response = author.post(
        "/api/media", files={"file": ("x.png", image_bytes(), "image/png")}, data={"alt": "The turret."}
    )

    assert response.status_code == 201
    assert response.json()["alt"] == "The turret."


def test_overlong_alt_text_is_rejected(author):
    response = author.post(
        "/api/media", files={"file": ("x.png", image_bytes(), "image/png")}, data={"alt": "x" * 1001}
    )

    assert response.status_code == 422


def test_a_non_multipart_upload_is_rejected(author):
    response = author.post("/api/media", json={"file": "not a file"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_a_text_field_named_file_is_not_a_file(author):
    assert author.post("/api/media", data={"file": "just text"}).status_code == 422


def test_a_broken_multipart_body_uses_the_error_envelope(author):
    response = author.post(
        "/api/media",
        content=b"--x\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.png\"\r\n\r\nabc",
        headers={"Content-Type": "multipart/form-data"},
    )

    assert response.status_code == 400
    assert set(response.json()) == {"error"}


# ------------------------------------------------------- decompression bombs


def png_declaring(width: int, height: int) -> bytes:
    """A few hundred bytes of PNG whose header claims an enormous canvas.

    This is the shape of the real attack: the file is tiny, the header is
    honest PNG, and everything expensive happens only if something decodes it.
    """
    import struct
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(b"\x00" * 64)) + chunk(b"IEND", b"")


def test_a_small_file_declaring_a_huge_canvas_is_refused_before_anything_decodes(author, media_root, monkeypatch):
    """10000 x 10000 passes the per-side limit and is a hundred megapixels.

    The assertion that matters is the second one. A cap applied after decoding
    has already spent the memory, so the test fails if any pixel data is ever
    loaded or re-encoded on the way to the refusal.
    """
    decoded = []
    monkeypatch.setattr(Image.Image, "load", lambda self, *a, **k: decoded.append("load"))
    monkeypatch.setattr(Image.Image, "save", lambda self, *a, **k: decoded.append("save"))
    payload = png_declaring(10_000, 10_000)
    assert len(payload) < 1024

    response = author.post("/api/media", files={"file": ("bomb.png", payload, "image/png")})

    assert response.status_code == 422
    assert "megapixels" in response.json()["error"]["message"]
    assert decoded == []
    assert not (media_root.exists() and [p for p in media_root.rglob("*") if p.is_file()])


def test_the_pixel_cap_is_independent_of_the_per_side_limit(author, monkeypatch):
    monkeypatch.setenv("RETICLE_MAX_IMAGE_PIXELS", "5000")
    get_settings.cache_clear()

    assert author.post("/api/media", files={"file": ("ok.png", image_bytes(70, 70), "image/png")}).status_code == 201
    response = author.post("/api/media", files={"file": ("big.png", image_bytes(80, 80), "image/png")})

    assert response.status_code == 422
    assert "megapixels" in response.json()["error"]["message"]


def test_the_default_pixel_cap_is_forty_megapixels():
    assert get_settings().max_image_pixels == 40_000_000


def test_an_animation_is_budgeted_across_all_of_its_frames(author, monkeypatch):
    """Every frame is decoded on re-encode, so a thousand small frames cost what
    one enormous picture costs."""
    monkeypatch.setenv("RETICLE_MAX_IMAGE_PIXELS", "1000")
    get_settings.cache_clear()
    frames = [Image.new("RGB", (30, 30), (shade * 40, 0, 0)) for shade in range(6)]
    buffer = BytesIO()
    frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:])

    still = author.post("/api/media", files={"file": ("one.gif", image_bytes(30, 30, "GIF"), "image/gif")})
    animated = author.post("/api/media", files={"file": ("six.gif", buffer.getvalue(), "image/gif")})

    assert still.status_code == 201
    assert animated.status_code == 422
    assert "animation" in animated.json()["error"]["message"]


def test_a_modest_animated_gif_keeps_its_frames(author):
    frames = [Image.new("RGB", (20, 20), (shade * 80, 0, 0)) for shade in range(3)]
    buffer = BytesIO()
    frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:])

    created = author.post("/api/media", files={"file": ("three.gif", buffer.getvalue(), "image/gif")}).json()

    assert Image.open(BytesIO(author.get(f"/api/media/{created['id']}").content)).n_frames == 3


# -------------------------------------------------------------------- videos


def test_an_mp4_is_accepted_by_its_container_signature(author, db_session, media_root):
    payload = mp4_bytes(4096)

    response = author.post("/api/media", files={"file": ("clip.mp4", payload, "video/mp4")})

    assert response.status_code == 201
    body = response.json()
    assert body["kind"] == "video"
    assert body["width"] is None and body["height"] is None
    assert body["annotations"] == []
    stored = db_session.scalars(select(Media)).one()
    assert stored.content_type == "video/mp4"
    assert stored.byte_size == len(payload)
    assert stored.storage_path.endswith(f"{body['id']}.mp4")
    assert (media_root / stored.storage_path).read_bytes() == payload


def test_a_webm_is_accepted_by_its_ebml_doctype(author, db_session):
    created = upload_video(author, webm_bytes(), filename="clip.webm")

    assert created["kind"] == "video"
    assert db_session.scalars(select(Media)).one().content_type == "video/webm"
    assert author.get(f"/api/media/{created['id']}").headers["content-type"] == "video/webm"


def test_the_filename_and_declared_type_of_a_video_are_ignored(author, db_session):
    """A video called ``holiday.png`` and labelled ``image/png`` is still a
    video; what it is comes from its own first bytes."""
    response = author.post("/api/media", files={"file": ("holiday.png", mp4_bytes(), "image/png")})

    assert response.status_code == 201
    assert response.json()["kind"] == "video"
    assert db_session.scalars(select(Media)).one().content_type == "video/mp4"


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(webm_bytes(doctype=b"matroska"), id="matroska-not-webm"),
        pytest.param(mp4_bytes(major=b"qt  ", compatible=(b"qt  ",)), id="quicktime"),
        pytest.param(mp4_bytes(major=b"avif", compatible=(b"avif", b"mif1")), id="avif-image"),
        pytest.param(mp4_bytes(major=b"heic", compatible=(b"heic", b"isom")), id="heic-claiming-isom"),
        pytest.param(mp4_bytes(major=b"M4A ", compatible=(b"M4A ", b"mp42")), id="m4a-audio"),
        pytest.param(b"\x00\x00\x00\x08ftyp" + b"\x00" * 64, id="ftyp-box-too-short"),
        pytest.param(b"\x00\x00\x00\x21ftypisom" + b"\x00" * 64, id="ftyp-box-odd-size"),
        pytest.param(b"RIFF\x00\x00\x00\x00AVI LIST" + b"\x00" * 64, id="avi"),
        pytest.param(b"\x1a\x45\xdf\xa3", id="ebml-magic-only"),
        pytest.param(b"\x1a\x45\xdf\xa3\x84\x42\x82\x00\x00", id="ebml-empty-doctype"),
        pytest.param(b"\x1a\x45\xdf\xa3\x88\x42\x86\x81\x01\x00\x00\x00\x00", id="ebml-zero-id"),
        pytest.param(b"\x1a\x45\xdf\xa3\x83\x42\x82\x01", id="ebml-truncated-size"),
        pytest.param(b"\x1a\x45\xdf\xa3\x84\x42\x86\x81\x01", id="ebml-no-doctype"),
        pytest.param(b"<html><video src=x onerror=alert(1)></video></html>", id="html"),
    ],
)
def test_files_that_only_resemble_an_accepted_video_are_rejected(author, media_root, payload):
    response = author.post("/api/media", files={"file": ("clip.mp4", payload, "video/mp4")})

    assert response.status_code == 422
    assert not (media_root.exists() and [p for p in media_root.rglob("*") if p.is_file()])


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(mp4_bytes(major=b"qt  ", compatible=(b"qt  ",)), id="quicktime"),
        pytest.param(webm_bytes(doctype=b"matroska"), id="matroska"),
    ],
)
def test_a_video_in_another_container_is_told_so_rather_than_called_a_bad_image(author, payload):
    """A phone recording is the commonest thing refused here, and its owner
    should be told to convert it, not sent looking for a broken picture."""
    response = author.post("/api/media", files={"file": ("clip.mov", payload, "video/quicktime")})

    assert response.status_code == 422
    assert "MP4" in response.json()["error"]["message"]
    assert "WebM" in response.json()["error"]["message"]


def test_a_still_image_in_an_iso_container_is_still_described_as_an_image(author):
    response = author.post(
        "/api/media",
        files={"file": ("photo.heic", mp4_bytes(major=b"heic", compatible=(b"heic", b"mif1")), "image/heic")},
    )

    assert response.status_code == 422
    assert "image" in response.json()["error"]["message"].lower()
    assert "MP4" not in response.json()["error"]["message"]


def test_an_mp4_whose_playable_brand_is_only_in_the_compatible_list_is_accepted(author):
    created = upload_video(author, mp4_bytes(major=b"XAVC", compatible=(b"XAVC", b"mp42", b"iso2")))

    assert created["kind"] == "video"


def test_the_default_video_cap_is_two_hundred_megabytes():
    assert get_settings().max_video_bytes == 200 * 1024 * 1024


def test_a_video_over_the_cap_is_refused_and_leaves_nothing_on_disk(author, media_root, monkeypatch):
    monkeypatch.setenv("RETICLE_MAX_VIDEO_BYTES", "4096")
    get_settings.cache_clear()

    within = author.post("/api/media", files={"file": ("ok.mp4", mp4_bytes(4096), "video/mp4")})
    over = author.post("/api/media", files={"file": ("big.mp4", mp4_bytes(4097), "video/mp4")})

    assert within.status_code == 201
    assert over.status_code == 413
    assert over.json()["error"]["code"] == "payload_too_large"
    assert "MB" in over.json()["error"]["message"]
    assert len([p for p in media_root.rglob("*") if p.is_file()]) == 1


def test_a_video_may_be_larger_than_the_image_cap(author, monkeypatch):
    monkeypatch.setenv("RETICLE_MAX_UPLOAD_BYTES", "2048")
    get_settings.cache_clear()

    assert author.post("/api/media", files={"file": ("clip.mp4", mp4_bytes(64 * 1024), "video/mp4")}).status_code == 201


def test_a_video_is_copied_to_disk_in_bounded_chunks(tmp_path):
    """The file must never be held in memory whole.

    The stream records the largest single read it is asked for. A ``read()``
    with no size, or one sized to the file, would show up here.
    """
    from app import videos

    class Recording(BytesIO):
        largest = 0

        def read(self, size=-1):
            assert size is not None and size > 0, "an unbounded read would load the whole upload"
            Recording.largest = max(Recording.largest, size)
            return super().read(size)

    payload = mp4_bytes(3 * videos.COPY_CHUNK_BYTES + 17)

    written = videos.store(Recording(payload), tmp_path, "aa/bb/clip.mp4", limit=len(payload))

    assert written == len(payload)
    assert Recording.largest == videos.COPY_CHUNK_BYTES
    assert (tmp_path / "aa/bb/clip.mp4").read_bytes() == payload


def test_a_failed_database_write_does_not_leave_the_file_behind(author, media_root, monkeypatch):
    from app import audit as audit_module

    def explode(*args, **kwargs):
        raise RuntimeError("database went away")

    monkeypatch.setattr(audit_module, "record", explode)

    with pytest.raises(RuntimeError):
        author.post("/api/media", files={"file": ("clip.mp4", mp4_bytes(), "video/mp4")})

    assert [p for p in media_root.rglob("*") if p.is_file()] == []


def test_a_range_request_returns_just_that_slice(author):
    """Seeking in a video is a Range request; without 206 the browser has to
    download the whole clip to jump to the end of it."""
    payload = mp4_bytes(10_000)
    created = upload_video(author, payload)

    whole = author.get(f"/api/media/{created['id']}")
    part = author.get(f"/api/media/{created['id']}", headers={"Range": "bytes=1000-1999"})
    tail = author.get(f"/api/media/{created['id']}", headers={"Range": "bytes=-100"})

    assert whole.status_code == 200
    assert whole.headers["accept-ranges"] == "bytes"
    assert part.status_code == 206
    assert part.headers["content-range"] == f"bytes 1000-1999/{len(payload)}"
    assert part.headers["content-length"] == "1000"
    assert part.content == payload[1000:2000]
    assert tail.status_code == 206
    assert tail.content == payload[-100:]


def test_a_range_past_the_end_is_not_satisfiable(author):
    created = upload_video(author, mp4_bytes(1000))

    response = author.get(f"/api/media/{created['id']}", headers={"Range": "bytes=5000-6000"})

    assert response.status_code == 416
    assert response.headers["content-range"] == "bytes */1000"


def test_a_partial_response_keeps_the_hardening_headers(author):
    created = upload_video(author, mp4_bytes(5000))

    response = author.get(f"/api/media/{created['id']}", headers={"Range": "bytes=0-9"})

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-type"] == "video/mp4"
    assert "sandbox" in response.headers["content-security-policy"]
    assert "default-src 'none'" in response.headers["content-security-policy"]


def test_a_viewer_gets_ranges_only_for_media_they_may_see(viewer, author):
    created = upload_video(author)

    assert viewer.get(f"/api/media/{created['id']}", headers={"Range": "bytes=0-9"}).status_code == 404


def test_an_upload_is_refused_before_its_body_is_read_when_the_caller_may_not_upload(anon, viewer, monkeypatch):
    """Parsing the multipart body is what spools it to disk. An account that
    cannot upload must be turned away without that happening on its behalf."""
    from starlette.requests import Request

    parsed = []
    original = Request.form

    def recording_form(self, *args, **kwargs):
        parsed.append(self.url.path)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Request, "form", recording_form)
    files = {"file": ("clip.mp4", mp4_bytes(), "video/mp4")}

    assert viewer.post("/api/media", files=files).status_code == 403
    anon.raw.cookies.set("reticle_csrf", "x")
    assert anon.raw.post("/api/media", files=files, headers={"X-CSRF-Token": "x"}).status_code == 401
    assert parsed == []


# ------------------------------------------------- visibility through pages


def test_a_viewer_can_read_an_image_in_the_body_of_a_published_page(viewer, author):
    image = upload_media(author)
    page = create_page(author, "Illustrated")
    saved = save_page(author, page, body=f"Intro.\n\n![The suite](/api/media/{image['id']})\n")

    assert viewer.get(f"/api/media/{image['id']}").status_code == 404

    assert author.post(f"/api/pages/{page['id']}/publish").status_code == 200
    assert viewer.get(f"/api/media/{image['id']}").status_code == 200

    assert author.post(f"/api/pages/{saved['id']}/unpublish").status_code == 200
    assert viewer.get(f"/api/media/{image['id']}").status_code == 404


def test_a_viewer_can_read_the_hero_of_a_published_page(viewer, author):
    image = upload_media(author)
    page = create_page(author, "With a hero")
    save_page(author, page, body="Text.", heroMediaId=image["id"])

    assert viewer.get(f"/api/media/{image['id']}").status_code == 404
    author.post(f"/api/pages/{page['id']}/publish")

    assert viewer.get(f"/api/media/{image['id']}").status_code == 200


def test_removing_an_image_from_a_page_body_withdraws_it(viewer, author):
    image = upload_media(author)
    page = published_page(author, "Shrinking", body=f"![x](/api/media/{image['id']})")
    assert viewer.get(f"/api/media/{image['id']}").status_code == 200

    save_page(author, page, body="The picture has gone.")
    assert viewer.get(f"/api/media/{image['id']}").status_code == 200, "readers still have the version that shows it"

    assert author.post(f"/api/pages/{page['id']}/publish").status_code == 200
    assert viewer.get(f"/api/media/{image['id']}").status_code == 404


def test_archiving_a_page_withdraws_its_images(viewer, author, admin):
    image = upload_media(author)
    page = published_page(author, "Doomed", body=f"![x](/api/media/{image['id']})", heroMediaId=image["id"])
    assert viewer.get(f"/api/media/{image['id']}").status_code == 200

    assert admin.delete(f"/api/pages/{page['id']}").status_code == 204

    assert viewer.get(f"/api/media/{image['id']}").status_code == 404
    assert author.get(f"/api/media/{image['id']}").status_code == 200


def test_an_image_shared_by_a_draft_and_a_published_page_is_readable(viewer, author):
    image = upload_media(author)
    create_page(author, "Draft")
    published_page(author, "Live", body=f"![x](/api/media/{image['id']})")
    draft = create_page(author, "Another draft")
    save_page(author, draft, body=f"![x](/api/media/{image['id']})")

    assert viewer.get(f"/api/media/{image['id']}").status_code == 200


def test_archiving_a_guide_withdraws_its_images(viewer, author, admin, category):
    image = upload_media(author)
    guide = _attach_to_guide(author, category, image, publish=True)

    admin.delete(f"/api/guides/{guide['id']}")

    assert viewer.get(f"/api/media/{image['id']}").status_code == 404
