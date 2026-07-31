"""Upload validation and on-disk storage for images.

The rule this module exists to enforce is that nothing the uploader controls is
ever trusted. The declared MIME type and the filename are discarded outright;
the format is whatever Pillow can actually decode, and the stored name is
derived from a server-minted identifier, so a hostile filename can neither
traverse out of the media root nor land somewhere a web server would execute.

Re-encoding rather than copying is what strips EXIF: a JPEG straight off a
microscope camera carries serial numbers, and occasionally GPS.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

from PIL import Image

from . import errors

ACCEPTED_FORMATS = {
    "PNG": ("image/png", "png"),
    "JPEG": ("image/jpeg", "jpg"),
    "WEBP": ("image/webp", "webp"),
    "GIF": ("image/gif", "gif"),
}

READ_CHUNK_BYTES = 64 * 1024

Image.MAX_IMAGE_PIXELS = 10_000 * 10_000


@dataclass(frozen=True)
class NormalisedImage:
    payload: bytes
    content_type: str
    extension: str
    width: int
    height: int


def read_within_limit(stream: BinaryIO, limit: int) -> bytes:
    """Read the body, refusing as soon as it passes the cap.

    Streaming the check means a hostile client cannot make the process hold an
    arbitrarily large buffer just by lying about ``Content-Length``.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = stream.read(READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise errors.payload_too_large(f"Images must be at most {limit // (1024 * 1024)} MB.")
        chunks.append(chunk)
    return b"".join(chunks)


def normalise(payload: bytes, max_dimension: int) -> NormalisedImage:
    if not payload:
        raise errors.validation_failed("The uploaded file is empty.")

    try:
        with Image.open(BytesIO(payload)) as probe:
            probe.verify()
    except Exception as exc:
        raise errors.validation_failed("That file is not a readable image.") from exc

    with Image.open(BytesIO(payload)) as image:
        image_format = image.format or ""
        if image_format not in ACCEPTED_FORMATS:
            raise errors.validation_failed("Images must be PNG, JPEG, WebP or GIF.")

        width, height = image.size
        if width > max_dimension or height > max_dimension:
            raise errors.validation_failed(f"Images must be at most {max_dimension} pixels on each side.")
        if width == 0 or height == 0:
            raise errors.validation_failed("That image has no pixels.")

        buffer = BytesIO()
        save_options = {}
        if getattr(image, "n_frames", 1) > 1:
            save_options["save_all"] = True
        try:
            image.save(buffer, format=image_format, **save_options)
        except Exception as exc:
            raise errors.validation_failed("That image could not be processed.") from exc

    content_type, extension = ACCEPTED_FORMATS[image_format]
    return NormalisedImage(buffer.getvalue(), content_type, extension, width, height)


def relative_storage_path(media_id: str, extension: str) -> str:
    """Shard by the leading characters of the ULID.

    ULIDs are time-ordered, so a flat directory would grow one hot folder that
    every write contends on and that ``ls`` eventually cannot open.
    """
    return f"{media_id[:2]}/{media_id[2:4]}/{media_id}.{extension}"


def write_file(media_root: Path, storage_path: str, payload: bytes) -> Path:
    target = media_root / storage_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return target


def resolve_file(media_root: Path, storage_path: str) -> Path:
    """Re-check containment on read as well as on write.

    The stored path is generated, so this can only fire if the database has been
    tampered with directly, which is exactly when a path check is worth having.
    """
    root = media_root.resolve()
    target = (root / storage_path).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise errors.not_found("That image is no longer available.")
    return target
