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

MAX_IMAGE_PIXELS_DEFAULT = 40_000_000
"""Ceiling on width times height, independent of the per-side limit.

A per-side limit alone is not a memory limit: 10000 x 10000 satisfies "at most
10000 pixels on each side" and is 100 megapixels, which costs the process
several hundred megabytes the moment anything decodes it. Forty megapixels sits
comfortably above a stitched 8000 x 5000 microscopy panel and far below the
point at which one upload can exhaust the host.
"""

Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS_DEFAULT


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


def too_many_pixels_message(max_pixels: int) -> str:
    return (
        f"That image is larger than {max_pixels // 1_000_000} megapixels, which is more than Reticle "
        "will decode. Downscale it — a guide is read on a screen, so 2000 pixels on the long edge is "
        "already generous — or split a large stitched figure into one image per panel."
    )


def normalise(payload: bytes, max_dimension: int, max_pixels: int) -> NormalisedImage:
    """Validate the declared geometry, then re-encode.

    Every size question is answered from the header, before anything decodes.
    That ordering is the whole point: ``open()`` and ``verify()`` read structure
    only, and ``save()`` is what actually asks for width times height pixels of
    memory, so a limit applied anywhere after the format probe has already let
    the allocation happen. A 300 KiB flat PNG declaring 10000 x 10000 is the
    concrete case — cheap to transfer, three quarters of a gigabyte to encode.
    """
    if not payload:
        raise errors.validation_failed("The uploaded file is empty.")

    Image.MAX_IMAGE_PIXELS = max_pixels

    try:
        with Image.open(BytesIO(payload)) as header:
            image_format = header.format or ""
            width, height = header.size
    except Image.DecompressionBombError as exc:
        raise errors.validation_failed(too_many_pixels_message(max_pixels)) from exc
    except Exception as exc:
        raise errors.validation_failed("That file is not a readable image.") from exc

    if image_format not in ACCEPTED_FORMATS:
        raise errors.validation_failed("Images must be PNG, JPEG, WebP or GIF.")
    if width == 0 or height == 0:
        raise errors.validation_failed("That image has no pixels.")
    if width > max_dimension or height > max_dimension:
        raise errors.validation_failed(
            f"Images must be at most {max_dimension} pixels on each side."
        )
    if width * height > max_pixels:
        raise errors.validation_failed(too_many_pixels_message(max_pixels))

    try:
        with Image.open(BytesIO(payload)) as probe:
            probe.verify()
    except Exception as exc:
        raise errors.validation_failed("That file is not a readable image.") from exc

    with Image.open(BytesIO(payload)) as image:
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
    """Kept as a thin wrapper over ``LocalStorage``.

    New code should take a ``Storage`` rather than a media root — see
    ``app/storage.py``. This exists so the local path stays a single
    implementation rather than two that can drift.
    """
    from .storage import LocalStorage

    LocalStorage(media_root).write(storage_path, payload)
    return media_root / storage_path


def resolve_file(media_root: Path, storage_path: str) -> Path:
    """Re-check containment on read as well as on write.

    The stored path is generated, so this can only fire if the database has been
    tampered with directly, which is exactly when a path check is worth having.
    """
    from .storage import LocalStorage

    return LocalStorage(media_root).local_path_or_404(storage_path)
