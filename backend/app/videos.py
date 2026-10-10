"""Recognising and storing uploaded video.

The rule is the one ``images`` enforces: nothing the uploader controls is
trusted. The filename and the declared MIME type are ignored, and a file is a
video only if its first bytes are the container signature of one of the two
formats every current browser plays — MP4 and WebM.

Unlike an image, a video is not decoded or re-encoded. Transcoding would mean
shipping and patching ffmpeg on a facility server for the sake of ninety short
clips, so the bytes are stored as they arrived. That is safe to serve only
because the response says exactly what they are and forbids the browser from
guessing otherwise; see ``routers.media``.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from . import errors

SNIFF_BYTES = 4096
COPY_CHUNK_BYTES = 1024 * 1024

MP4_BRANDS = frozenset(
    {b"isom", b"iso2", b"iso3", b"iso4", b"iso5", b"iso6", b"mp41", b"mp42", b"avc1", b"M4V ", b"dash", b"mmp4"}
)
"""Brands that mean "an MP4 a browser can play".

ISO base media is a family, not a format: HEIC and AVIF photographs, M4A audio
and QuickTime movies all open with the same ``ftyp`` box. The box only counts as
video when it names one of these.
"""

NOT_VIDEO_BRANDS = frozenset(
    {b"avif", b"avis", b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"M4A ", b"M4B ", b"M4P ", b"qt  "}
)

EBML_MAGIC = b"\x1a\x45\xdf\xa3"
EBML_DOCTYPE_ID = 0x4282


@dataclass(frozen=True)
class VideoFormat:
    content_type: str
    extension: str


MP4 = VideoFormat("video/mp4", "mp4")
WEBM = VideoFormat("video/webm", "webm")


def _is_mp4(head: bytes) -> bool:
    """An ``ftyp`` box first, naming a playable brand."""
    if len(head) < 16 or head[4:8] != b"ftyp":
        return False
    box_size = int.from_bytes(head[0:4], "big")
    if box_size < 16 or box_size % 4 != 0:
        return False
    box = head[: min(box_size, len(head))]
    major = box[8:12]
    compatible = [box[offset : offset + 4] for offset in range(16, len(box) - 3, 4)]
    if major in NOT_VIDEO_BRANDS:
        return False
    return major in MP4_BRANDS or any(brand in MP4_BRANDS for brand in compatible)


def _read_vint(data: bytes, offset: int, keep_marker: bool) -> tuple[int, int] | None:
    """Read one EBML variable-length integer; return its value and the next offset.

    The count of leading zero bits in the first byte gives the length. Element
    identifiers keep that marker bit as part of the value; sizes drop it.
    """
    if offset >= len(data):
        return None
    first = data[offset]
    if first == 0:
        return None
    length = 8 - first.bit_length() + 1
    if offset + length > len(data):
        return None
    value = first if keep_marker else first & (0xFF >> length)
    for byte in data[offset + 1 : offset + length]:
        value = (value << 8) | byte
    return value, offset + length


def _is_webm(head: bytes) -> bool:
    """An EBML header whose document type is ``webm``.

    The magic number alone is not enough: it is shared with Matroska, which
    browsers do not play and which can carry almost anything.
    """
    if not head.startswith(EBML_MAGIC):
        return False
    header_size = _read_vint(head, len(EBML_MAGIC), keep_marker=False)
    if header_size is None:
        return False
    size, offset = header_size
    end = min(offset + size, len(head))
    while offset < end:
        element_id = _read_vint(head, offset, keep_marker=True)
        if element_id is None:
            return False
        identifier, offset = element_id
        element_size = _read_vint(head, offset, keep_marker=False)
        if element_size is None:
            return False
        length, offset = element_size
        if identifier == EBML_DOCTYPE_ID:
            return head[offset : offset + length].rstrip(b"\x00") == b"webm"
        offset += length
    return False


def sniff(head: bytes) -> VideoFormat | None:
    """Which accepted video container these opening bytes belong to, if any."""
    if _is_mp4(head):
        return MP4
    if _is_webm(head):
        return WEBM
    return None


STILL_IMAGE_BRANDS = frozenset({b"avif", b"avis", b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"})

UNSUPPORTED_MESSAGE = (
    "That looks like a video or audio file, but not one Reticle accepts. Videos must be MP4 (H.264) "
    "or WebM; convert QuickTime (.mov), Matroska (.mkv) and other formats first."
)


def resembles_other_media(head: bytes) -> bool:
    """Whether a refused file is plainly a film or a sound, just not an accepted one.

    This changes no decision — the file is refused either way — only what the
    author is told. A QuickTime recording straight off a phone is the commonest
    thing dropped on a step that Reticle will not take, and "that is not a
    readable image" sends its owner looking for the wrong problem.
    """
    if head.startswith(EBML_MAGIC):
        return True
    return len(head) >= 12 and head[4:8] == b"ftyp" and head[8:12] not in STILL_IMAGE_BRANDS


def too_large_message(limit: int) -> str:
    return f"Videos must be at most {limit // (1024 * 1024)} MB."


def store(stream: BinaryIO, media_root: Path, storage_path: str, limit: int) -> int:
    """Copy the upload to its place in bounded chunks; return the byte count.

    A two-hundred-megabyte clip must never sit in memory, and the declared
    length is not evidence of anything, so the cap is applied to the bytes
    actually copied. An upload that runs over leaves nothing behind.
    """
    target = media_root / storage_path
    target.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    try:
        with target.open("wb") as output:
            while True:
                chunk = stream.read(COPY_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise errors.payload_too_large(too_large_message(limit))
                output.write(chunk)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return total
