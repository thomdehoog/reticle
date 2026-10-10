"""What is stored for an upload, how it is handed out, and how it is removed.

Four things an uploads directory needs that Reticle's did not have: pictures
kept as they were sent instead of being put through an encoder twice; a copy of
a large picture at a size a screen can use; responses a shared PC has to ask
about again instead of replaying from its cache; and a way to make a file be
gone.
"""

from __future__ import annotations

import struct
import zlib
from io import BytesIO

import pytest
from PIL import Image, JpegImagePlugin, PngImagePlugin
from sqlalchemy import select

from app import images, pdf
from app.models import AuditLog, GuideRevision, Media, PageRevision, PublishedGuideMedia
from app.settings import get_settings

from .conftest import (
    annotation,
    bullet,
    create_guide,
    create_page,
    image_bytes,
    mp4_bytes,
    publish_guide,
    published_guide,
    published_page,
    save_guide,
    save_page,
    step,
    upload_media,
    upload_video,
)


def stored_bytes(db_session, media_root, media_id: str) -> bytes:
    db_session.expire_all()
    return (media_root / db_session.get(Media, media_id).storage_path).read_bytes()


def display_path(db_session, media_root, media_id: str):
    db_session.expire_all()
    return media_root / images.display_storage_path(db_session.get(Media, media_id).storage_path)


def post(client, payload: bytes, name: str = "picture"):
    return client.post("/api/media", files={"file": (name, payload, "application/octet-stream")})


def photo(width: int = 320, height: int = 200) -> Image.Image:
    """Something with detail in it, so that encoder quality is visible."""
    image = Image.effect_noise((width, height), 60).convert("RGB")
    image.paste((200, 30, 30), (width // 4, height // 4, width // 2, height // 2))
    return image


def jpeg(image: Image.Image | None = None, **options) -> bytes:
    buffer = BytesIO()
    (image or photo()).save(buffer, format="JPEG", **{"quality": 95, **options})
    return buffer.getvalue()


def png(image: Image.Image | None = None, **options) -> bytes:
    buffer = BytesIO()
    (image or photo()).save(buffer, format="PNG", **options)
    return buffer.getvalue()


def webp(image: Image.Image | None = None, **options) -> bytes:
    buffer = BytesIO()
    (image or photo()).save(buffer, format="WEBP", **options)
    return buffer.getvalue()


def exif_bytes(make: str = "ZMB-Stellaris-SN-00417") -> bytes:
    exif = Image.Exif()
    exif[0x010F] = make
    return exif.tobytes()


# ------------------------------------------- a file that is only a picture is kept


@pytest.mark.parametrize("make", [jpeg, png, webp, lambda: webp(lossless=True)], ids=["jpeg", "png", "webp", "webp-lossless"])
def test_an_upload_with_nothing_to_remove_is_stored_byte_for_byte(author, db_session, media_root, make):
    """A screenshot re-encoded as JPEG at an encoder's default quality has its
    small text smeared, and one that needed nothing done to it gains nothing
    from the trip. What the author sent is what is kept and what is served."""
    payload = make()

    created = post(author, payload).json()

    assert stored_bytes(db_session, media_root, created["id"]) == payload
    assert author.get(f"/api/media/{created['id']}").content == payload
    assert (created["width"], created["height"]) == (320, 200)


def test_a_truncated_jpeg_is_refused(author, media_root):
    """Kept is not the same as trusted. A file that stops half way through its
    scan has a perfectly good header."""
    whole = jpeg(photo(640, 480))

    response = post(author, whole[: len(whole) // 2])

    assert response.status_code == 422
    assert [path for path in media_root.rglob("*") if path.is_file()] == []


def test_a_png_with_damaged_pixel_data_is_refused_even_though_its_chunks_are_all_allowed(author):
    """Every chunk is of an allowed kind, so this file would be kept as it is —
    if keeping were decided without decoding."""
    payload = bytearray(png(photo(200, 200)))
    position = payload.index(b"IDAT") + 40
    payload[position : position + 30] = b"\x00" * 30
    assert images.is_only_a_picture(bytes(payload), "PNG")

    assert post(author, bytes(payload)).status_code == 422


# -------------------------------------------- anything else in the file is removed


def test_a_jpeg_that_carries_exif_is_re_encoded_at_high_quality_not_the_default(author, db_session, media_root):
    """Stripping EXIF means re-encoding. Pillow's default quality of 75 is
    what blurred screenshots; 92 with the source's chroma subsampling is used."""
    payload = jpeg(exif=exif_bytes(), subsampling=0)
    assert b"ZMB-Stellaris-SN-00417" in payload

    created = post(author, payload).json()

    stored = stored_bytes(db_session, media_root, created["id"])
    assert stored != payload and b"ZMB-Stellaris" not in stored
    assert dict(Image.open(BytesIO(stored)).getexif()) == {}
    reference = Image.open(BytesIO(jpeg(quality=images.JPEG_REENCODE_QUALITY)))
    default = Image.open(BytesIO(jpeg(quality=75)))
    kept = Image.open(BytesIO(stored))
    assert kept.quantization == reference.quantization
    assert kept.quantization != default.quantization
    assert images.JPEG_REENCODE_QUALITY >= 90
    assert JpegImagePlugin.get_sampling(kept) == 0, "4:4:4 in, 4:4:4 out — not the encoder's 4:2:0 default"


@pytest.mark.parametrize("subsampling", [0, 1, 2])
def test_the_sources_chroma_subsampling_is_kept(subsampling):
    normalised = images.normalise(jpeg(exif=exif_bytes(), subsampling=subsampling), 10_000, 40_000_000)

    assert JpegImagePlugin.get_sampling(Image.open(BytesIO(normalised.payload))) == subsampling


def test_a_jpeg_comment_is_removed(author, db_session, media_root):
    """Pillow copies a comment segment into the file it writes unless told not
    to, so re-encoding alone did not remove this one."""
    payload = jpeg(comment=b"taken by H. Muster, room Y42-H-91")

    created = post(author, payload).json()

    stored = stored_bytes(db_session, media_root, created["id"])
    assert b"Muster" not in stored
    assert "comment" not in Image.open(BytesIO(stored)).info


def test_png_text_chunks_are_removed(author, db_session, media_root):
    info = PngImagePlugin.PngInfo()
    info.add_text("Author", "H. Muster")
    info.add_itxt("Description", "Patient 4471, slide 3")
    source = photo()
    payload = png(source, pnginfo=info)

    created = post(author, payload).json()

    stored = stored_bytes(db_session, media_root, created["id"])
    assert b"Muster" not in stored and b"4471" not in stored
    assert Image.open(BytesIO(stored)).convert("RGB").tobytes() == source.tobytes(), "and it is still lossless"


@pytest.mark.parametrize(("make", "kwargs"), [(png, {}), (webp, {"lossless": True})], ids=["png", "webp"])
def test_exif_is_removed_from_the_lossless_formats_without_touching_a_pixel(author, db_session, media_root, make, kwargs):
    source = photo()
    payload = make(source, exif=exif_bytes(), **kwargs)
    assert b"Stellaris" in payload

    created = post(author, payload).json()

    stored = stored_bytes(db_session, media_root, created["id"])
    assert b"Stellaris" not in stored
    assert Image.open(BytesIO(stored)).convert("RGB").tobytes() == source.tobytes()


def test_a_lossy_webp_with_exif_is_re_encoded_lossy_at_high_quality(author, db_session, media_root):
    payload = webp(exif=exif_bytes(), quality=95)

    created = post(author, payload).json()

    stored = stored_bytes(db_session, media_root, created["id"])
    assert b"Stellaris" not in stored
    assert not images._webp_is_lossless(stored)
    assert len(stored) > len(webp(quality=60)), "not the encoder's default"


@pytest.mark.parametrize("make", [jpeg, png, webp], ids=["jpeg", "png", "webp"])
def test_bytes_riding_along_after_the_picture_are_not_kept(author, db_session, media_root, make):
    """A file can decode perfectly and still carry something behind its end
    marker. Kept verbatim, an upload would be a place to park arbitrary data."""
    payload = make() + b"PK\x03\x04 an archive appended to a picture"

    response = post(author, payload)

    if response.status_code == 201:
        assert b"an archive appended" not in stored_bytes(db_session, media_root, response.json()["id"])
    else:
        assert response.status_code == 422


def test_the_colour_profile_survives_a_re_encode(author, db_session, media_root):
    profile = b"\x00" * 128 + b"a profile body"
    payload = jpeg(exif=exif_bytes(), icc_profile=profile)

    created = post(author, payload).json()

    assert Image.open(BytesIO(stored_bytes(db_session, media_root, created["id"]))).info.get("icc_profile") == profile


def test_a_gif_is_always_re_encoded(author, db_session, media_root):
    buffer = BytesIO()
    photo().convert("P").save(buffer, format="GIF", comment=b"made on the confocal PC")

    created = post(author, buffer.getvalue()).json()

    assert b"confocal PC" not in stored_bytes(db_session, media_root, created["id"])


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def test_which_files_count_as_only_a_picture():
    """The rule is a list of what is allowed, checked by walking the container."""
    plain_png, plain_jpeg, plain_webp = png(), jpeg(), webp()
    assert images.is_only_a_picture(plain_png, "PNG")
    assert images.is_only_a_picture(plain_jpeg, "JPEG")
    assert images.is_only_a_picture(plain_webp, "WEBP")
    assert images.is_only_a_picture(jpeg(icc_profile=b"\x00" * 200), "JPEG"), "a colour profile is part of the picture"
    assert images.is_only_a_picture(jpeg(progressive=True), "JPEG")
    assert images.is_only_a_picture(jpeg(photo().convert("CMYK")), "JPEG"), "the Adobe marker says how to read CMYK"
    assert images.is_only_a_picture(webp(photo().convert("RGBA")), "WEBP")

    unknown_chunk = plain_png[:-12] + _png_chunk(b"prVt", b"anything at all") + plain_png[-12:]
    assert Image.open(BytesIO(unknown_chunk)).size == (320, 200)
    assert not images.is_only_a_picture(unknown_chunk, "PNG"), "a private chunk nobody has heard of"
    assert not images.is_only_a_picture(png(exif=exif_bytes()), "PNG")
    assert not images.is_only_a_picture(jpeg(exif=exif_bytes()), "JPEG")
    assert not images.is_only_a_picture(jpeg(comment=b"hello"), "JPEG")
    assert not images.is_only_a_picture(webp(exif=exif_bytes()), "WEBP")
    assert not images.is_only_a_picture(webp(xmp=b"<x:xmpmeta/>"), "WEBP")
    assert not images.is_only_a_picture(plain_png, "GIF")

    for broken in (b"", b"\xff\xd8", b"\xff\xd8\x00\x00", b"\xff\xd8\xff", b"\xff\xd8\xff\xe0\x00", b"\xff\xd8\xff\xdb\x00\x01"):
        assert not images.is_only_a_picture(broken, "JPEG")
    assert not images.is_only_a_picture(plain_jpeg[:-2], "JPEG"), "no end-of-image marker"
    assert not images.is_only_a_picture(plain_jpeg[: plain_jpeg.index(b"\xff\xda") + 20], "JPEG"), "ends inside the scan"
    assert not images.is_only_a_picture(b"\xff\xd8\xff\xff\xff\xd9" + b"x", "JPEG")
    assert images.is_only_a_picture(b"\xff\xd8\xff\xff\xd0\xff\xd9", "JPEG"), "fill bytes and bare markers are structure"
    scan = b"\xff\xd8\xff\xda\x00\x02" + b"ab\xff\x00cd\xff\xd3ef\xff\xff\xd9"
    assert images.is_only_a_picture(scan, "JPEG"), "stuffed bytes, restart markers and fill inside a scan"
    assert not images.is_only_a_picture(b"not a png", "PNG")
    assert not images.is_only_a_picture(plain_png[:-12], "PNG"), "no IEND"
    assert images.is_only_a_picture(b"RIFF\x04\x00\x00\x00WEBP", "WEBP"), "structurally empty; decoding is what refuses it"
    assert not images.is_only_a_picture(b"RIFF\xff\x00\x00\x00WEBPVP8 ", "WEBP"), "the length does not match the file"
    assert not images.is_only_a_picture(b"JUNK", "WEBP")
    assert not images.is_only_a_picture(plain_webp[:-3] , "WEBP")


# ------------------------------------------------------------- the display copy


BIG = (3200, 2000)


def test_a_large_upload_gets_a_display_copy_beside_the_original(author, db_session, media_root):
    payload = png(photo(*BIG))

    created = post(author, payload).json()

    assert (created["width"], created["height"]) == BIG, "the dimensions reported are the original's"
    assert created["url"] == f"/api/media/{created['id']}"
    assert created["displayUrl"] == f"/api/media/{created['id']}?size=display"
    copy = display_path(db_session, media_root, created["id"])
    assert copy.name.endswith(".display.png") and copy.is_file()
    assert Image.open(copy).size == (2560, 1600)
    assert stored_bytes(db_session, media_root, created["id"]) == payload, "and the original is untouched"


def test_the_display_url_serves_the_copy_and_the_plain_url_the_original(author):
    payload = jpeg(photo(*BIG))
    created = post(author, payload).json()

    shown = author.get(created["displayUrl"])
    full = author.get(created["url"])

    assert shown.status_code == 200 and shown.headers["content-type"] == "image/jpeg"
    assert Image.open(BytesIO(shown.content)).size == (2560, 1600)
    assert len(shown.content) < len(payload)
    assert full.content == payload
    assert shown.headers["etag"] != full.headers["etag"]
    assert "sandbox" in shown.headers["content-security-policy"]


def test_a_picture_that_is_already_small_is_its_own_display_copy(author, db_session, media_root):
    payload = png(photo(images.DISPLAY_MAX_SIDE, 100))
    created = post(author, payload).json()

    shown = author.get(created["displayUrl"])

    assert shown.content == payload
    assert shown.headers["etag"] == author.get(created["url"]).headers["etag"]
    assert not display_path(db_session, media_root, created["id"]).exists()


def test_a_video_has_one_file_and_its_display_url_is_its_url(author):
    created = upload_video(author)

    assert created["displayUrl"] == created["url"]
    assert author.get(created["url"], params={"size": "display"}).content == mp4_bytes()


def test_an_unknown_size_is_refused(author):
    created = upload_media(author)

    assert author.get(created["url"], params={"size": "thumbnail"}).status_code == 422


@pytest.mark.parametrize(
    ("mode", "make", "expected_mode"),
    [("RGBA", png, "RGBA"), ("LA", png, "LA"), ("L", png, "L"), ("P", png, "RGB"), ("1", png, "RGB"), ("CMYK", jpeg, "RGB"), ("RGBA", webp, "RGBA")],
)
def test_every_colour_mode_gets_a_display_copy(author, mode, make, expected_mode):
    source = photo(3000, 600).convert(mode)
    if mode in {"RGBA", "LA"}:
        source.putalpha(128)

    created = post(author, make(source)).json()
    shown = Image.open(BytesIO(author.get(created["displayUrl"]).content))

    assert shown.size == (2560, 512)
    assert shown.mode == expected_mode


def test_transparency_survives_into_the_display_copy(author):
    source = Image.new("RGBA", (4000, 3000), (0, 0, 0, 0))
    source.paste((255, 0, 0, 255), (0, 0, 2000, 3000))
    created = post(author, png(source)).json()

    shown = Image.open(BytesIO(author.get(created["displayUrl"]).content))

    assert shown.getpixel((100, 100)) == (255, 0, 0, 255)
    assert shown.getpixel((2400, 100))[3] == 0


def test_a_palette_image_with_transparency_keeps_it(author):
    source = Image.new("P", (3000, 400), 0)
    source.putpalette([0, 0, 0, 0, 200, 0])
    source.paste(1, (0, 0, 1500, 400))
    created = post(author, png(source, transparency=0)).json()

    shown = Image.open(BytesIO(author.get(created["displayUrl"]).content))

    assert shown.mode == "RGBA" and shown.getpixel((2500, 10))[3] == 0


def test_a_lossless_webp_gets_a_lossless_display_copy(author):
    created = post(author, webp(photo(3000, 600), lossless=True)).json()

    assert images._webp_is_lossless(author.get(created["displayUrl"]).content)


def test_a_large_animation_is_served_as_it_is(author, db_session, media_root):
    frames = [Image.new("RGB", (2600, 20), colour) for colour in ("red", "green", "blue")]
    buffer = BytesIO()
    frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:], duration=50)
    created = post(author, buffer.getvalue()).json()

    shown = Image.open(BytesIO(author.get(created["displayUrl"]).content))

    assert shown.n_frames == 3 and shown.size == (2600, 20)
    assert not display_path(db_session, media_root, created["id"]).exists()


def test_a_display_copy_follows_the_same_visibility_rule(author, viewer, category):
    created = post(author, png(photo(*BIG))).json()
    guide = create_guide(author, category.id)
    save_guide(author, guide, steps=[step("Look", media=[created])])
    assert viewer.get(created["displayUrl"]).status_code == 404

    author.post(f"/api/guides/{guide['id']}/publish")

    assert viewer.get(created["displayUrl"]).status_code == 200


def test_media_without_a_display_copy_gets_one_the_first_time_it_is_asked_for(author, db_session, media_root):
    """Everything uploaded before display copies existed, and everything the
    importer stores, has none. It must still work, and it should only be slow once."""
    created = post(author, png(photo(*BIG))).json()
    copy = display_path(db_session, media_root, created["id"])
    copy.unlink()

    first = author.get(created["displayUrl"])

    assert first.status_code == 200 and Image.open(BytesIO(first.content)).size == (2560, 1600)
    assert copy.is_file()
    made_at = copy.stat().st_mtime_ns
    assert author.get(created["displayUrl"]).content == first.content
    assert copy.stat().st_mtime_ns == made_at, "made once, served from then on"
    assert [path.name for path in copy.parent.iterdir() if path.name.endswith(".part")] == []


def test_a_lazily_made_copy_of_a_camera_jpeg_is_decoded_small(author, db_session, media_root, monkeypatch):
    created = post(author, jpeg(photo(6000, 3750))).json()
    display_path(db_session, media_root, created["id"]).unlink()
    loaded = []
    load = Image.Image.load
    monkeypatch.setattr(JpegImagePlugin.JpegImageFile, "load", lambda self: loaded.append(self.size) or load(self), raising=False)

    assert author.get(created["displayUrl"]).status_code == 200

    assert loaded and max(loaded[0]) < 6000, "the decoder was asked for a reduced size before it decoded anything"


def test_the_original_is_served_while_the_decoders_are_busy(author, db_session, media_root, monkeypatch):
    payload = png(photo(*BIG))
    created = post(author, payload).json()
    copy = display_path(db_session, media_root, created["id"])
    copy.unlink()
    monkeypatch.setattr(images, "DECODE_WAIT_SECONDS", 0.01)
    held = [images._decode_slots.acquire(blocking=False) for _ in range(images.MAX_CONCURRENT_DECODES)]
    try:
        assert all(held)
        db_session.expire_all()
        media = db_session.get(Media, created["id"])
        path = images.display_file(media_root, media.storage_path, media.width, media.height, media.content_type, wait_seconds=0.01)
    finally:
        for _ in held:
            images._decode_slots.release()

    assert path.read_bytes() == payload and not copy.exists()
    assert author.get(created["displayUrl"]).status_code == 200 and copy.exists(), "and it is made once they are free"


def test_a_file_that_cannot_be_shrunk_is_served_as_it_is_and_not_retried(author, db_session, media_root, monkeypatch):
    payload = png(photo(*BIG))
    created = post(author, payload).json()
    display_path(db_session, media_root, created["id"]).unlink()
    attempts = []

    def fail(original, target):
        attempts.append(original)
        raise OSError("disk full")

    monkeypatch.setattr(images, "_make_display_copy", fail)
    monkeypatch.setattr(images, "_no_display_copy", set())

    assert author.get(created["displayUrl"]).content == payload
    assert author.get(created["displayUrl"]).content == payload
    assert len(attempts) == 1


def test_reducing_an_image_with_alpha_never_copies_it_whole(monkeypatch):
    """Pillow's own resize converts an RGBA picture to premultiplied alpha at
    full size first. ``images.reduced`` does it a band of rows at a time, and
    the result is pixel for pixel what one pass would have given."""
    source = Image.effect_noise((3001, 2003), 70).convert("RGB").convert("RGBA")
    source.putalpha(Image.linear_gradient("L").resize(source.size))
    reference = source.convert("RGBa").reduce(2).convert("RGBA")
    converted: list[tuple[int, int]] = []
    convert = Image.Image.convert
    monkeypatch.setattr(Image.Image, "convert", lambda self, *a, **k: converted.append(self.size) or convert(self, *a, **k))

    result = images.reduced(source, 1500)

    assert result.size == reference.size and result.tobytes() == reference.tobytes()
    assert max(height for _, height in converted) <= images.REDUCE_BAND_ROWS
    assert images.reduced(source, 3001) is source, "nothing to do when it is already close"
    assert images.reduced(source.convert("RGB"), 1000).size == (1001, 668)


def test_a_failed_upload_leaves_neither_file_behind(author, media_root, monkeypatch):
    from app import audit as audit_module

    def explode(*args, **kwargs):
        raise RuntimeError("database went away")

    monkeypatch.setattr(audit_module, "record", explode)

    with pytest.raises(RuntimeError):
        post(author, png(photo(*BIG)))

    assert [path for path in media_root.rglob("*") if path.is_file()] == []


# ------------------------------------------------ revalidation instead of max-age


def test_media_carries_a_strong_validator_and_must_be_revalidated(author):
    created = upload_media(author)

    response = author.get(created["url"])

    assert response.headers["cache-control"] == "private, no-cache"
    tag = response.headers["etag"]
    assert tag.startswith('"') and tag.endswith('"') and not tag.startswith("W/")
    assert created["id"] in tag


@pytest.mark.parametrize("wrap", [str, lambda tag: f"W/{tag}", lambda tag: f'"other", {tag}', lambda tag: "*"])
def test_a_matching_validator_is_answered_304_with_no_body(author, wrap):
    created = upload_media(author)
    tag = author.get(created["url"]).headers["etag"]

    again = author.get(created["url"], headers={"If-None-Match": wrap(tag)})

    assert again.status_code == 304
    assert again.content == b""
    assert again.headers["etag"] == tag
    assert again.headers["cache-control"] == "private, no-cache"


def test_a_stale_validator_gets_the_bytes(author):
    created = upload_media(author)

    response = author.get(created["url"], headers={"If-None-Match": '"something-else"'})

    assert response.status_code == 200 and response.content


def test_revalidating_is_not_a_way_round_the_login_or_the_visibility_rule(author, viewer, anon, category):
    """The whole point of ``no-cache``: a browser left on a shared PC has the
    bytes and the validator, and asking again must get it nothing once the
    session is gone or the picture withdrawn."""
    image = upload_media(author)
    guide = published_guide(author, category.id, steps=[step("Look", media=[image])])
    tag = viewer.get(image["url"]).headers["etag"]

    assert viewer.get(image["url"], headers={"If-None-Match": tag}).status_code == 304
    assert anon.get(image["url"], headers={"If-None-Match": tag}).status_code == 401
    author.post(f"/api/guides/{guide['id']}/unpublish")
    assert viewer.get(image["url"], headers={"If-None-Match": tag}).status_code == 404
    assert viewer.post("/api/auth/logout").status_code == 204
    assert viewer.get(image["url"], headers={"If-None-Match": tag}).status_code == 401


def test_ranges_still_work_and_if_range_uses_the_same_validator(author):
    payload = mp4_bytes(10_000)
    created = upload_video(author, payload)
    tag = author.get(created["url"]).headers["etag"]

    part = author.get(created["url"], headers={"Range": "bytes=100-199"})
    conditional = author.get(created["url"], headers={"Range": "bytes=100-199", "If-Range": tag})
    outdated = author.get(created["url"], headers={"Range": "bytes=100-199", "If-Range": '"an-older-file"'})

    assert part.status_code == 206 and part.content == payload[100:200]
    assert part.headers["etag"] == tag and part.headers["cache-control"] == "private, no-cache"
    assert conditional.status_code == 206 and conditional.content == payload[100:200]
    assert outdated.status_code == 200 and outdated.content == payload, "the file changed: send all of it"


def test_the_validator_changes_when_the_file_does(author, db_session, media_root):
    created = upload_media(author)
    before = author.get(created["url"]).headers["etag"]

    db_session.expire_all()
    (media_root / db_session.get(Media, created["id"]).storage_path).write_bytes(image_bytes(30, 30))

    assert author.get(created["url"]).headers["etag"] != before


# ------------------------------------------------------------------- deleting


def test_the_uploader_can_delete_an_upload_nothing_uses(author, db_session, media_root):
    """A badge photographed by mistake could once only be unlinked: the bytes
    stayed on disk, in every backup, fetchable by any author with the address."""
    created = post(author, png(photo(*BIG))).json()
    original = media_root / db_session.get(Media, created["id"]).storage_path
    copy = display_path(db_session, media_root, created["id"])
    assert original.is_file() and copy.is_file()

    response = author.delete(created["url"])

    assert response.status_code == 204
    assert not original.exists() and not copy.exists()
    db_session.expire_all()
    assert db_session.get(Media, created["id"]) is None
    assert author.get(created["url"]).status_code == 404
    entry = db_session.scalars(select(AuditLog).where(AuditLog.action == "media.delete")).one()
    assert entry.entity_id == created["id"]
    assert entry.detail["forced"] is False and entry.detail["kind"] == "image"


def test_only_the_uploader_or_an_administrator_may_delete(author, viewer, admin, as_role):
    mine = upload_media(author)
    colleague = as_role("author", "colleague@zmb.uzh.ch")

    assert viewer.delete(mine["url"]).status_code == 403
    refused = colleague.delete(mine["url"])
    assert refused.status_code == 403 and "uploaded" in refused.json()["error"]["message"]
    assert author.get(mine["url"]).status_code == 200

    assert admin.delete(mine["url"]).status_code == 204


def test_deleting_something_that_is_not_there_is_not_found(author, admin):
    assert author.delete("/api/media/01JQNOTAREALULID0000000000").status_code == 404
    assert admin.delete("/api/media/not-an-identifier", params={"force": "true"}).status_code == 404
    assert admin.delete("/api/media/%25").status_code == 404


def test_an_upload_in_a_working_copy_is_not_deleted(author, admin, category):
    image = upload_media(author)
    guide = create_guide(author, category.id, "Aligning the Confocal")
    save_guide(author, guide, steps=[step("Look", media=[image])])

    for client in (author, admin):
        refused = client.delete(image["url"])
        assert refused.status_code == 409
        assert refused.json()["error"]["code"] == "conflict"
        assert "the guide “Aligning the Confocal”" in refused.json()["error"]["message"]
    assert author.get(image["url"]).status_code == 200


def test_an_upload_only_a_past_published_version_shows_is_still_in_use(author, admin, viewer, category):
    """Old versions stay readable. Removing a picture from the working copy
    and publishing does not make it unused."""
    image = upload_media(author)
    guide = published_guide(author, category.id, "Laser Safety", steps=[step("Look", media=[image])])
    save_guide(author, guide, steps=[step("Look", bullets=[bullet("No picture any more.")])])
    author.post(f"/api/guides/{guide['id']}/publish")
    assert viewer.get(image["url"]).status_code == 404

    refused = admin.delete(image["url"])

    assert refused.status_code == 409
    assert "published version 1 of the guide “Laser Safety”" in refused.json()["error"]["message"]
    assert author.get(f"/api/guides/{guide['id']}/revisions/1").json()["steps"][0]["media"][0]["id"] == image["id"]


def test_an_upload_a_page_uses_is_named_too(author, admin):
    hero, inline = upload_media(author), upload_media(author)
    page = create_page(author, "Booking Rules")
    save_page(author, page, body=f"![plan](/api/media/{inline['id']})", heroMediaId=hero["id"])

    for image in (hero, inline):
        refused = admin.delete(image["url"])
        assert refused.status_code == 409 and "the page “Booking Rules”" in refused.json()["error"]["message"]

    published = published_page(author, "Published Once", body=f"![x](/api/media/{upload_media(author)['id']})")
    shown = author.get(f"/api/pages/{published['id']}").json()["body"].split("/api/media/")[1][:26]
    save_page(author, published, body="No picture.")
    author.post(f"/api/pages/{published['id']}/publish")
    message = admin.delete(f"/api/media/{shown}").json()["error"]["message"]
    assert "published version 1 of the page “Published Once”" in message


def test_a_long_list_of_uses_is_cut_short(author, admin, category):
    image = upload_media(author)
    for index in range(8):
        save_guide(author, create_guide(author, category.id, f"Guide {index}"), steps=[step("Look", media=[image])])

    message = admin.delete(image["url"]).json()["error"]["message"]

    assert message.count("the guide “") == 5 and "and 3 more" in message


def test_forcing_is_an_administrators_action(author, category):
    image = upload_media(author)
    save_guide(author, create_guide(author, category.id), steps=[step("Look", media=[image])])

    refused = author.delete(image["url"], params={"force": "true"})

    assert refused.status_code == 403
    assert author.get(image["url"]).status_code == 200


def test_a_forced_delete_removes_the_upload_from_everything(author, admin, viewer, category, db_session, media_root):
    """"This must be gone": the working copies, every stored snapshot, what
    readers are served, the cached PDF and the files."""
    doomed = post(author, png(photo(*BIG))).json()
    kept = upload_media(author, image_bytes(20, 20))
    guide = published_guide(
        author,
        category.id,
        "Laser Safety",
        steps=[step("Badge", bullets=[bullet("Text stays.")], media=[{**doomed, "annotations": [annotation()]}, kept])],
    )
    page = published_page(
        author, "Access", body=f"Before ![badge](/api/media/{doomed['id']} \"title\") after. [file](/api/media/{doomed['id']})",
        heroMediaId=doomed["id"], heroAlt="A badge",
    )
    assert viewer.get(f"/api/guides/{guide['slug']}/pdf").status_code == 200
    cache = media_root / ".pdf-cache" / guide["id"]
    assert list(cache.glob("*.pdf"))
    files = [media_root / db_session.get(Media, doomed["id"]).storage_path, display_path(db_session, media_root, doomed["id"])]
    before_guide = author.get(f"/api/guides/{guide['id']}").json()
    before_page = author.get(f"/api/pages/{page['id']}").json()

    response = admin.delete(doomed["url"], params={"force": "true"})

    assert response.status_code == 204, response.text
    assert not any(path.exists() for path in files)
    assert not cache.exists(), "a cached export had the picture in it"
    assert author.get(doomed["url"]).status_code == 404

    for body in (
        author.get(f"/api/guides/{guide['id']}").json(),
        viewer.get(f"/api/guides/{guide['slug']}").json(),
        author.get(f"/api/guides/{guide['id']}/revisions/1").json(),
    ):
        assert [m["id"] for m in body["steps"][0]["media"]] == [kept["id"]]
        assert body["steps"][0]["bullets"][0]["text"] == "Text stays."
    for body in (
        author.get(f"/api/pages/{page['id']}").json(),
        viewer.get(f"/api/pages/{page['slug']}").json(),
        author.get(f"/api/pages/{page['id']}/revisions/1").json(),
    ):
        assert body["heroMediaId"] is None and body["heroAlt"] == ""
        assert body["body"] == "Before  after. [file]()"
        assert doomed["id"] not in body["body"]

    db_session.expire_all()
    assert doomed["id"] not in str([r.document for r in db_session.scalars(select(GuideRevision))])
    assert doomed["id"] not in str([r.document for r in db_session.scalars(select(PageRevision))])
    assert db_session.scalars(select(PublishedGuideMedia.media_id)).all() == [kept["id"]]
    assert viewer.get(kept["url"]).status_code == 200
    assert viewer.get(f"/api/guides/{guide['slug']}/pdf").status_code == 200

    after_guide = author.get(f"/api/guides/{guide['id']}").json()
    after_page = author.get(f"/api/pages/{page['id']}").json()
    assert after_guide["hasUnpublishedChanges"] is False and after_page["hasUnpublishedChanges"] is False, (
        "the picture left the snapshot too, so nothing is pending"
    )
    assert after_guide["updatedAt"] != before_guide["updatedAt"] and after_page["updatedAt"] != before_page["updatedAt"], (
        "an editor that still has the picture open must be refused as stale"
    )
    stale = author.put(f"/api/guides/{guide['id']}", json={**before_guide, "expectedUpdatedAt": before_guide["updatedAt"]})
    assert stale.status_code == 409

    entry = db_session.scalars(select(AuditLog).where(AuditLog.action == "media.delete")).one()
    assert entry.detail["forced"] is True
    assert entry.detail["removedFrom"] == {"guides": 1, "pages": 1, "guideRevisions": 1, "pageRevisions": 1}


def test_a_forced_delete_keeps_a_pending_edit_pending(author, admin, category):
    image = upload_media(author)
    guide = published_guide(author, category.id, steps=[step("Look", media=[image])])
    save_guide(author, guide, summary="An unpublished change.")

    assert admin.delete(image["url"], params={"force": "true"}).status_code == 204

    after = author.get(f"/api/guides/{guide['id']}").json()
    assert after["hasUnpublishedChanges"] is True and after["summary"] == "An unpublished change."


def test_a_reference_in_a_page_body_is_taken_out_in_every_form():
    from app.published import strip_media_from_body

    target, other = "01JQAAAAAAAAAAAAAAAAAAAAAA", "01JQBBBBBBBBBBBBBBBBBBBBBB"
    body = (
        f"![a](/api/media/{target}) ![b]( /api/media/{target}?size=display \"t\" ) ![keep](/api/media/{other})\n"
        f"[link](/api/media/{target}) and [ref]: /api/media/{target}?size=display\n"
        f"<img src=\"/api/media/{target}\"> /api/media/{target}X"
    )

    stripped = strip_media_from_body(body, target)

    assert stripped == (
        f"  ![keep](/api/media/{other})\n[link]() and [ref]: \n<img src=\"\"> /api/media/{target}X"
    )


# ------------------------------------------------------------ the store's ceiling


@pytest.fixture()
def small_store(monkeypatch):
    def _limit(size: int) -> None:
        monkeypatch.setenv("RETICLE_MAX_MEDIA_STORE_BYTES", str(size))
        get_settings.cache_clear()

    return _limit


def test_the_store_is_unlimited_unless_a_ceiling_is_set(author):
    assert get_settings().max_media_store_bytes == 0
    assert post(author, png()).status_code == 201


def test_an_upload_that_would_overfill_the_store_is_refused(author, small_store, media_root, db_session):
    first = png()
    assert post(author, first).status_code == 201
    small_store(len(first) + 100)

    refused = post(author, png(photo(321, 200)))

    assert refused.status_code == 413
    assert refused.json()["error"]["code"] == "payload_too_large"
    assert "media store is full" in refused.json()["error"]["message"]
    assert len([path for path in media_root.rglob("*") if path.is_file()]) == 1, "nothing was written for it"
    assert len(db_session.scalars(select(Media)).all()) == 1
    assert post(author, image_bytes(4, 4)).status_code == 201, "something that still fits is accepted"


def test_a_video_is_held_to_the_same_ceiling_before_it_is_copied(author, small_store, media_root):
    small_store(1000)

    refused = author.post("/api/media", files={"file": ("clip.mp4", mp4_bytes(5000), "video/mp4")})

    assert refused.status_code == 413
    assert [path for path in media_root.rglob("*") if path.is_file()] == []


def test_the_ceiling_is_measured_in_the_database_not_on_the_disk(author, small_store, db_session, make_user):
    """Summing a column costs the same however many files there are. The proof
    that nothing walks the directory: a row with no file behind it counts."""
    owner = make_user("someone@zmb.uzh.ch", role="author")
    db_session.add(Media(storage_path="zz/zz/ghost.png", content_type="image/png", byte_size=10_000, uploaded_by_id=owner.id))
    db_session.commit()
    small_store(10_050)

    assert post(author, png()).status_code == 413


def test_deleting_makes_room_again(author, small_store):
    payload = png()
    first = post(author, payload).json()
    small_store(len(payload) + 10)
    assert post(author, payload).status_code == 413

    assert author.delete(first["url"]).status_code == 204

    assert post(author, payload).status_code == 201


def test_the_ceiling_cannot_be_negative(monkeypatch):
    monkeypatch.setenv("RETICLE_MAX_MEDIA_STORE_BYTES", "-1")
    get_settings.cache_clear()

    with pytest.raises(ValueError):
        get_settings()
    monkeypatch.delenv("RETICLE_MAX_MEDIA_STORE_BYTES")
    get_settings.cache_clear()


# ------------------------------------------------------------ the awkward cases


def test_a_cmyk_jpeg_with_exif_is_re_encoded_without_guessing_its_subsampling(author, db_session, media_root):
    payload = jpeg(photo().convert("CMYK"), exif=exif_bytes())

    created = post(author, payload).json()

    stored = Image.open(BytesIO(stored_bytes(db_session, media_root, created["id"])))
    assert stored.mode == "CMYK" and dict(stored.getexif()) == {}


def test_a_webp_keeps_its_colour_profile_through_a_re_encode(author, db_session, media_root):
    profile = b"\x00" * 128 + b"a profile body"
    payload = webp(exif=exif_bytes(), icc_profile=profile, lossless=True)

    created = post(author, payload).json()

    assert Image.open(BytesIO(stored_bytes(db_session, media_root, created["id"]))).info.get("icc_profile") == profile


def test_a_large_animated_webp_is_served_as_it_is(author, db_session, media_root, monkeypatch):
    """Its row looks like any large image, so the first request tries to make a
    display copy, finds an animation, and remembers not to try again."""
    monkeypatch.setattr(images, "_no_display_copy", set())
    frames = [Image.new("RGB", (2600, 20), colour) for colour in ("red", "green", "blue")]
    buffer = BytesIO()
    frames[0].save(buffer, format="WEBP", save_all=True, append_images=frames[1:], duration=50)
    created = post(author, buffer.getvalue()).json()

    shown = Image.open(BytesIO(author.get(created["displayUrl"]).content))

    assert shown.n_frames == 3
    assert not display_path(db_session, media_root, created["id"]).exists()
    assert len(images._no_display_copy) == 1


def test_a_copy_made_by_another_worker_while_waiting_is_used_not_made_again(author, db_session, media_root, monkeypatch):
    created = post(author, png(photo(*BIG))).json()
    copy = display_path(db_session, media_root, created["id"])
    made_elsewhere = copy.read_bytes()
    copy.unlink()

    class OtherWorkerFinishesFirst:
        def acquire(self, timeout=None):
            copy.write_bytes(made_elsewhere)
            return True

        def release(self):
            pass

    monkeypatch.setattr(images, "_decode_slots", OtherWorkerFinishesFirst())
    monkeypatch.setattr(images, "_make_display_copy", lambda *args: pytest.fail("made a second time"))

    assert author.get(created["displayUrl"]).content == made_elsewhere


def test_a_page_that_only_mentions_the_upload_in_its_body_is_stripped_too(author, admin):
    image, hero = upload_media(author), upload_media(author, image_bytes(9, 9))
    page = create_page(author, "Body Only")
    save_page(author, page, body=f"Text ![x](/api/media/{image['id']}) more.", heroMediaId=hero["id"], heroAlt="Kept")

    assert admin.delete(image["url"], params={"force": "true"}).status_code == 204

    after = author.get(f"/api/pages/{page['id']}").json()
    assert (after["body"], after["heroMediaId"], after["heroAlt"]) == ("Text  more.", hero["id"], "Kept")


def test_a_forced_delete_rewrites_old_versions_as_well_as_the_current_one(author, admin, viewer, category):
    doomed = upload_media(author)
    guide = published_guide(author, category.id, steps=[step("Look", bullets=[bullet("v1")], media=[doomed])])
    save_guide(author, guide, steps=[step("Look", bullets=[bullet("v2, no picture")])])
    author.post(f"/api/guides/{guide['id']}/publish")
    page = published_page(author, "Rules", body=f"v1 ![x](/api/media/{doomed['id']})")
    save_page(author, page, body="v2")
    author.post(f"/api/pages/{page['id']}/publish")

    assert admin.delete(doomed["url"], params={"force": "true"}).status_code == 204

    assert author.get(f"/api/guides/{guide['id']}/revisions/1").json()["steps"][0]["media"] == []
    assert author.get(f"/api/pages/{page['id']}/revisions/1").json()["body"] == "v1 "
    assert viewer.get(f"/api/guides/{guide['slug']}").json()["steps"][0]["bullets"][0]["text"] == "v2, no picture"
    assert viewer.get(f"/api/pages/{page['slug']}").json()["body"] == "v2"


def test_a_file_that_cannot_be_removed_is_logged_and_left_for_the_sweep(author, db_session, media_root, monkeypatch, caplog):
    from pathlib import Path

    created = upload_media(author)
    unlink = Path.unlink

    def refuse(self, *args, **kwargs):
        if created["id"] in self.name:
            raise PermissionError("read-only file system")
        return unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", refuse)

    with caplog.at_level("WARNING", logger="app.uploads"):
        assert author.delete(created["url"]).status_code == 204

    assert "maintenance command will retry" in caplog.text
    db_session.expire_all()
    assert db_session.get(Media, created["id"]) is None, "the row is gone either way"


def test_storing_an_export_twice_keeps_one_file(tmp_path):
    path = pdf.cache_file(tmp_path, "GUIDE", "REVISION", "Category")
    older = path.with_name("OLDER-l1-abc.pdf")

    pdf.store(path, b"%PDF- first")
    older.write_bytes(b"%PDF- a previous version")
    pdf.store(path, b"%PDF- second")

    assert [entry.name for entry in path.parent.iterdir()] == [path.name]
    assert path.read_bytes() == b"%PDF- second"
    pdf.forget(tmp_path, "GUIDE")
    assert not path.parent.exists()
    pdf.forget(tmp_path, "GUIDE")


def test_head_answers_like_get_without_the_bytes(author, viewer, anon, category):
    """How a video player, or a script, asks whether a file is there and how
    large before fetching it. It is under the same rules as the fetch."""
    payload = mp4_bytes(5000)
    clip = upload_video(author, payload)

    head = author.raw.head(clip["url"])

    assert head.status_code == 200 and head.content == b""
    assert head.headers["content-length"] == str(len(payload))
    assert head.headers["content-type"] == "video/mp4"
    assert head.headers["etag"] == author.get(clip["url"]).headers["etag"]
    assert head.headers["cache-control"] == "private, no-cache"
    assert viewer.raw.head(clip["url"]).status_code == 404, "nothing published shows it"
    assert anon.raw.head(clip["url"]).status_code == 401

    guide = create_guide(author, category.id)
    save_guide(author, guide, steps=[step("Watch", media=[clip])])
    publish_guide(author, guide)
    assert viewer.raw.head(clip["url"]).status_code == 200
