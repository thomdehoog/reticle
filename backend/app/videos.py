"""Upload validation and storage for step videos.

ZMB's corpus has video on 90 steps across 25 guides, so a replacement that
cannot hold a video loses a documented part of the material — a fifteen-second
clip of a stage moving is frequently the entire content of a step, and it cannot
be represented as a photograph and a sentence.

Video is validated differently from an image and it is worth being explicit
about why. Images are re-encoded through Pillow, which both proves the bytes are
an image and strips EXIF. There is no equivalent here: re-encoding video would
mean shipping ffmpeg, and ZMB's workstations are locked down by AppLocker, so
the deployment cost is real and the benefit is not. Instead the container is
identified from its own header bytes, the declared type and the filename are
discarded exactly as they are for images, and the file is served back with a
fixed ``Content-Type`` and ``nosniff`` so a browser cannot be talked into
treating it as anything else.

That is a smaller guarantee than the image path gives, and it is the reason
video uploads are capped separately and stored under a server-minted name like
everything else.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from dataclasses import dataclass

from . import errors

MP4_BRANDS = frozenset(
    {
        b"isom",
        b"iso2",
        b"iso4",
        b"iso5",
        b"iso6",
        b"mp41",
        b"mp42",
        b"avc1",
        b"M4V ",
        b"dash",
        b"qt  ",
    }
)
"""The ``ftyp`` brands a browser will actually play.

Screen recorders and phone cameras between them produce most of this list; a
QuickTime ``qt`` file is included because that is what a Mac in the EM suite
writes by default, and rejecting it would send people away to convert files by
hand, which is how a migration stalls.
"""

WEBM_MAGIC = b"\x1a\x45\xdf\xa3"

ACCEPTED_VIDEO_TYPES = {
    "mp4": "video/mp4",
    "webm": "video/webm",
}


@dataclass(frozen=True)
class IdentifiedVideo:
    content_type: str
    extension: str


def looks_like_video(payload: bytes) -> bool:
    """Cheap discriminator, used to route an upload to the right validator."""
    return _identify(payload) is not None


def identify(payload: bytes) -> IdentifiedVideo:
    """Name the container, or refuse the upload.

    The error deliberately names the two formats that work rather than saying
    "unsupported": an author whose upload bounced needs to know what to export,
    and every second spent guessing is a second they spend not writing the
    guide.
    """
    found = _identify(payload)
    if found is None:
        raise errors.validation_failed(
            "That file is not a picture Reticle can read, nor an MP4 or WebM video."
        )
    return found


def _identify(payload: bytes) -> IdentifiedVideo | None:
    if len(payload) < 12:
        return None
    if payload[:4] == WEBM_MAGIC:
        return IdentifiedVideo(content_type=ACCEPTED_VIDEO_TYPES["webm"], extension="webm")
    if payload[4:8] == b"ftyp" and payload[8:12] in MP4_BRANDS:
        return IdentifiedVideo(content_type=ACCEPTED_VIDEO_TYPES["mp4"], extension="mp4")
    return None
