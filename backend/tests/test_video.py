"""Step videos: upload, identification and the slot they may occupy.

The corpus has video on ninety steps, and a fifteen-second clip of a stage
moving is frequently the entire content of a step — it cannot be replaced by a
photograph and a sentence. Video is also the one upload path that is not
re-encoded, because shipping ffmpeg is not an option on these workstations, so
the container is identified from its own header bytes and everything else the
uploader claims is discarded. If that sniff is wrong in either direction the
consequences are concrete: an accepted non-video is an arbitrary file stored and
served back from the institute's documentation server, and a rejected genuine
clip sends an author away to convert files by hand, which is how a migration
stalls.

The slot rules are the other half. A video dropped into an image slot renders as
a broken picture and an image in the video slot as a player that never starts,
and both stay silent until a reader opens the step — so they are refused at the
write. And the bytes are behind the same visibility rule images have: a clip in
a draft guide is not readable by a viewer just because they hold an account.
"""

from __future__ import annotations

import pytest

from app import videos
from app.settings import get_settings

from .conftest import (
    create_guide,
    document_from,
    image_bytes,
    mp4_bytes,
    step,
    upload_media,
    upload_video,
    webm_bytes,
)


def attach(client, guide: dict, *, video: dict | None = None, media: list[dict] | None = None):
    return client.put(
        f"/api/guides/{guide['id']}",
        json=document_from(guide, steps=[step("Move the stage", media=media or [], video=video)]),
    )


def test_an_mp4_is_stored_as_a_video(author):
    body = author.post("/api/media", files={"file": ("stage.mp4", mp4_bytes(), "video/mp4")}).json()

    assert body["kind"] == "video"
    assert body["width"] is None and body["height"] is None
    assert body["annotations"] == []
    assert body["url"] == f"/api/media/{body['id']}"


def test_a_webm_is_stored_as_a_video(author):
    body = author.post(
        "/api/media", files={"file": ("stage.webm", webm_bytes(), "video/webm")}
    ).json()

    assert body["kind"] == "video"


def test_the_stored_bytes_and_type_come_from_the_header_not_the_upload(
    author, db_session, media_root
):
    """The declared type and the filename are discarded exactly as they are for
    images, and the file is served back with a fixed type and ``nosniff`` so a
    browser cannot be talked into treating it as anything else."""
    from sqlalchemy import select

    from app.models import Media

    payload = webm_bytes()
    created = author.post("/api/media", files={"file": ("clip.mp4", payload, "image/png")}).json()

    stored = db_session.scalars(select(Media)).one()
    served = author.get(f"/api/media/{created['id']}")

    assert stored.content_type == "video/webm"
    assert stored.storage_path.endswith(".webm")
    assert (media_root / stored.storage_path).read_bytes() == payload
    assert served.headers["content-type"] == "video/webm"
    assert served.headers["x-content-type-options"] == "nosniff"
    assert served.content == payload


@pytest.mark.parametrize("brand", [b"isom", b"iso2", b"mp42", b"avc1", b"qt  ", b"dash"])
def test_the_brands_a_browser_will_actually_play_are_accepted(author, brand):
    """A QuickTime file is on the list because that is what the Mac in the EM
    suite writes by default; rejecting it would send people away to convert."""
    response = author.post(
        "/api/media", files={"file": ("clip.mp4", mp4_bytes(brand), "video/mp4")}
    )

    assert response.status_code == 201
    assert response.json()["kind"] == "video"


def test_an_unknown_container_brand_is_not_treated_as_a_video(author):
    payload = b"\x00\x00\x00\x18ftypXXXX" + b"\x00" * 64

    response = author.post("/api/media", files={"file": ("clip.mp4", payload, "video/mp4")})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_a_truncated_video_is_rejected(author, media_root):
    response = author.post(
        "/api/media", files={"file": ("cut.webm", webm_bytes()[:6], "video/webm")}
    )

    assert response.status_code == 422
    assert not (media_root.exists() and [p for p in media_root.rglob("*") if p.is_file()])


def test_a_script_renamed_to_mp4_is_rejected(author):
    payload = b"#!/bin/sh\nrm -rf /\n" * 8

    response = author.post("/api/media", files={"file": ("evil.mp4", payload, "video/mp4")})

    assert response.status_code == 422


def test_the_identifier_refuses_bytes_it_cannot_name(author):
    """Belt and braces around the sniff: the router only reaches ``identify``
    for something that already looked like a video, so this asserts the guard
    directly rather than through a request that cannot express it."""
    with pytest.raises(Exception) as failure:
        videos.identify(b"not a container at all")

    assert "MP4" in str(failure.value) and "WebM" in str(failure.value)
    assert videos.looks_like_video(b"short") is False


def test_video_uploads_are_capped_separately_from_images(author, monkeypatch):
    """Holding video to the image limit would reject exactly the files the slot
    exists to accept, so the two ceilings are independent settings."""
    monkeypatch.setenv("RETICLE_MAX_VIDEO_BYTES", "32")
    get_settings.cache_clear()

    refused = author.post("/api/media", files={"file": ("stage.mp4", mp4_bytes(), "video/mp4")})
    accepted = author.post("/api/media", files={"file": ("still.png", image_bytes(), "image/png")})

    assert refused.status_code == 413
    assert refused.json()["error"]["code"] == "payload_too_large"
    assert "Videos" in refused.json()["error"]["message"]
    assert accepted.status_code == 201


def test_the_video_ceiling_stands_well_above_the_image_one_by_default():
    settings = get_settings()

    assert settings.max_video_bytes == 200 * 1024 * 1024
    assert settings.max_video_bytes > settings.max_upload_bytes


def test_a_video_round_trips_through_a_steps_video_slot(author, category):
    created = create_guide(author, category.id)
    clip = upload_video(author)

    body = attach(author, created, video=clip).json()

    assert body["steps"][0]["video"]["id"] == clip["id"]
    assert body["steps"][0]["video"]["kind"] == "video"
    assert body["steps"][0]["media"] == []
    assert (
        author.get(f"/api/guides/{created['id']}").json()["steps"][0]["video"]["id"] == clip["id"]
    )


def test_a_step_keeps_its_images_alongside_its_video(author, category):
    created = create_guide(author, category.id)
    clip = upload_video(author)
    picture = upload_media(author)

    body = attach(author, created, video=clip, media=[picture]).json()

    assert [m["id"] for m in body["steps"][0]["media"]] == [picture["id"]]
    assert body["steps"][0]["video"]["id"] == clip["id"]


def test_the_video_slot_carries_alt_text(author, category):
    created = create_guide(author, category.id)
    clip = upload_video(author)
    clip["alt"] = "The stage travelling to the second position."

    body = attach(author, created, video=clip).json()

    assert body["steps"][0]["video"]["alt"] == "The stage travelling to the second position."


def test_removing_the_video_from_a_step_empties_the_slot(author, category):
    created = create_guide(author, category.id)
    clip = upload_video(author)
    saved = attach(author, created, video=clip).json()

    cleared = attach(author, saved, video=None).json()

    assert cleared["steps"][0]["video"] is None


def test_a_video_in_an_image_slot_is_refused_at_the_write(author, category):
    created = create_guide(author, category.id)
    clip = upload_video(author)

    response = attach(author, created, media=[clip])

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"
    assert "video" in response.json()["error"]["message"].lower()


def test_an_image_in_the_video_slot_is_refused_at_the_write(author, category):
    created = create_guide(author, category.id)
    picture = upload_media(author)

    response = attach(author, created, video=picture)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"
    assert "video" in response.json()["error"]["message"].lower()


def test_a_video_that_no_longer_exists_is_rejected(author, category):
    from ulid import ULID

    created = create_guide(author, category.id)

    response = attach(author, created, video={"id": str(ULID()), "alt": ""})

    assert response.status_code == 422


def test_a_viewer_may_fetch_a_video_shown_by_a_published_guide(author, viewer, category):
    created = create_guide(author, category.id)
    clip = upload_video(author)
    attach(author, created, video=clip)
    author.post(f"/api/guides/{created['id']}/publish")

    assert viewer.get(f"/api/media/{clip['id']}").status_code == 200
    assert (
        viewer.get(f"/api/guides/{created['slug']}").json()["steps"][0]["video"]["id"] == clip["id"]
    )


def test_a_viewer_cannot_fetch_a_video_that_only_a_draft_shows(author, viewer, category):
    """Authentication is not visibility. A clip in a draft is exactly as
    unpublished as the text around it."""
    created = create_guide(author, category.id)
    clip = upload_video(author)
    attach(author, created, video=clip)

    assert viewer.get(f"/api/guides/{created['id']}").status_code == 404
    assert viewer.get(f"/api/media/{clip['id']}").status_code == 404


def test_unpublishing_a_guide_withdraws_its_video_too(author, viewer, category):
    created = create_guide(author, category.id)
    clip = upload_video(author)
    attach(author, created, video=clip)
    author.post(f"/api/guides/{created['id']}/publish")
    assert viewer.get(f"/api/media/{clip['id']}").status_code == 200

    author.post(f"/api/guides/{created['id']}/unpublish")

    assert viewer.get(f"/api/media/{clip['id']}").status_code == 404


def test_viewers_cannot_upload_a_video(viewer):
    response = viewer.post("/api/media", files={"file": ("stage.mp4", mp4_bytes(), "video/mp4")})

    assert response.status_code == 403
