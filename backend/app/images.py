"""Upload validation for images, and on-disk storage for all media.

The rule this module exists to enforce is that nothing the uploader controls is
ever trusted. The declared MIME type and the filename are discarded outright;
the format is whatever Pillow can actually decode, and the stored name is
derived from a server-minted identifier, so a hostile filename can neither
traverse out of the media root nor land somewhere a web server would execute.

A file that is nothing but a picture is stored byte for byte. Most uploads are
screenshots of acquisition software, and re-encoding a JPEG of one at an
encoder's default quality smears exactly the small text the screenshot was taken
to show; a file with nothing to remove gains nothing from a second trip through
an encoder. "Nothing but a picture" is decided by walking the container, not by
asking the decoder what it noticed: anything that is not pixel data, colour
description or structure — EXIF, XMP, comments, text chunks, bytes after the
end — means the file is re-encoded instead, which is what strips it. A JPEG
straight off a microscope camera carries serial numbers, and occasionally GPS.
The one EXIF field that changes how a picture looks, its orientation, is applied
to the pixels first, because the tag does not survive and the picture has to.
Either way the file is decoded in full before it is accepted.

Alongside a large picture this module keeps a **display copy**, held to what a
screen or a printed column can use. It is what the reader's ``<img>`` and the
PDF export are given; the original stays for "open full size".

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import logging
import os
import threading
import warnings
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, BinaryIO

from PIL import ExifTags, Image, ImageOps, JpegImagePlugin

from . import errors

ACCEPTED_FORMATS = {
    "PNG": ("image/png", "png"),
    "JPEG": ("image/jpeg", "jpg"),
    "WEBP": ("image/webp", "webp"),
    "GIF": ("image/gif", "gif"),
}

READ_CHUNK_BYTES = 64 * 1024

logger = logging.getLogger(__name__)

JPEG_REENCODE_QUALITY = 92
"""The quality a JPEG is written at when it has to be re-encoded at all.

Pillow's default is 75, which is visibly soft on a screenshot. Ninety-two with
the source's own chroma subsampling is close enough to the original that the
second generation is hard to find, and it only applies to the files that carry
something to strip or a rotation to apply; the rest are not re-encoded.
"""

WEBP_REENCODE_QUALITY = 92

DISPLAY_MAX_SIDE = 2560
"""Longest edge, in pixels, of the copy of an image that is shown.

Wide enough to fill a 2560-pixel monitor and to be sharp at twice the width of
any column the reader lays a step image out in; small enough that a stitched
8000 x 5000 panel is not sent to a phone, or decoded at full size by every PDF
export of the guide it sits in. Pictures no larger than this have no display
copy: the original is one.
"""

DISPLAY_JPEG_QUALITY = 88
DISPLAY_SUFFIX = ".display"

MAX_CONCURRENT_DECODES = 1
DECODE_WAIT_SECONDS = 2.0

_decode_slots = threading.BoundedSemaphore(MAX_CONCURRENT_DECODES)
"""Decoding a forty-megapixel picture takes 160 MB for as long as it lasts,
whatever is done with it afterwards: Pillow holds four bytes a pixel. One at a
time per worker keeps a burst of large uploads, or of first requests for
pictures that have no display copy yet, at that figure instead of multiplying
it by the number of requests in flight — the container is given one gigabyte
for two workers. An ordinary screenshot holds the slot for milliseconds."""

_no_display_copy: set[str] = set()
"""Files a display copy could not be made from, so they are not tried again on
every request. Per process and forgotten on restart, which is the right
lifetime: a transient failure gets another go, a damaged file costs one decode
per worker rather than one per page view."""

MAX_IMAGE_PIXELS_DEFAULT = 40_000_000
"""Ceiling on width times height, independent of the per-side limit.

A per-side limit alone is not a memory limit: 10000 x 10000 satisfies "at most
10000 pixels on each side" and is 100 megapixels, which costs the process
several hundred megabytes the moment anything decodes it. Forty megapixels sits
comfortably above a stitched 8000 x 5000 microscopy panel and far below the
point at which one upload can exhaust the host.
"""

Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS_DEFAULT

warnings.simplefilter("ignore", Image.DecompressionBombWarning)
"""Pillow warns at the cap and only raises at twice it. ``normalise`` refuses at
the cap itself, so the warning would announce something already dealt with."""

MAX_ANIMATION_FACTOR = 4
"""How many times the single-frame pixel budget an animation may use in total.

Re-encoding an animated GIF decodes every frame in turn. The per-frame cap
bounds the memory; this bounds the time, because a few kilobytes can declare a
thousand full-size frames and each one costs as much to process as a
photograph.
"""


@dataclass(frozen=True)
class NormalisedImage:
    payload: bytes
    content_type: str
    extension: str
    width: int
    height: int


@dataclass(frozen=True)
class ProcessedImage:
    """An accepted upload: what is stored, and its display copy if it needs one."""

    image: NormalisedImage
    display: bytes | None


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


# ------------------------------------------------ is this file only a picture?

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

_PNG_PICTURE_CHUNKS = frozenset(
    {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"iCCP", b"sBIT", b"bKGD", b"pHYs"}
)
"""Chunks that say what the pixels are and how to show them, and nothing else.

Deliberately a list of what is allowed. ``tEXt``, ``iTXt``, ``zTXt``, ``eXIf``
and ``tIME`` are the ones that carry who, where and with what; a private chunk
nobody has heard of could carry anything, and is treated the same."""

_WEBP_PICTURE_CHUNKS = frozenset({b"VP8 ", b"VP8L", b"VP8X", b"ALPH", b"ICCP"})


def _png_is_only_a_picture(data: bytes) -> bool:
    if not data.startswith(_PNG_SIGNATURE):
        return False
    position = len(_PNG_SIGNATURE)
    while position + 12 <= len(data):
        length = int.from_bytes(data[position : position + 4], "big")
        kind = data[position + 4 : position + 8]
        if kind not in _PNG_PICTURE_CHUNKS:
            return False
        position += 12 + length
        if kind == b"IEND":
            return position == len(data)
    return False


def _jpeg_is_only_a_picture(data: bytes) -> bool:
    """Walk the segments: frame and table data, JFIF, a colour profile, and no more.

    Every other application segment is metadata of some kind — EXIF and XMP in
    APP1, IPTC in APP13, a second embedded picture in APP2 — and so is a
    comment. The walk has to reach the end-of-image marker exactly at the end
    of the file, so nothing can ride along behind the picture either.
    """
    if not data.startswith(b"\xff\xd8"):
        return False
    position, size = 2, len(data)
    while position + 2 <= size:
        if data[position] != 0xFF:
            return False
        marker = data[position + 1]
        if marker == 0xFF:
            position += 1
            continue
        if marker == 0xD9:
            return position + 2 == size
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            position += 2
            continue
        if position + 4 > size:
            return False
        length = int.from_bytes(data[position + 2 : position + 4], "big")
        if length < 2:
            return False
        body = data[position + 4 : position + 2 + length]
        if marker == 0xE0:
            allowed = body.startswith((b"JFIF\x00", b"JFXX\x00"))
        elif marker == 0xE2:
            allowed = body.startswith(b"ICC_PROFILE\x00")
        elif marker == 0xEE:
            allowed = body.startswith(b"Adobe")
        else:
            allowed = not (0xE0 <= marker <= 0xEF or marker == 0xFE)
        if not allowed:
            return False
        position += 2 + length
        if marker == 0xDA:
            # Entropy-coded data runs to the next marker. Inside it 0xFF is
            # always followed by a stuffed zero or a restart marker.
            while True:
                position = data.find(b"\xff", position)
                if position < 0 or position + 1 >= size:
                    return False
                following = data[position + 1]
                if following == 0x00 or 0xD0 <= following <= 0xD7:
                    position += 2
                elif following == 0xFF:
                    position += 1
                else:
                    break
    return False


def _webp_chunks(data: bytes) -> list[bytes] | None:
    """The chunk types of a WebP file in order, or ``None`` if it is not well formed."""
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    if int.from_bytes(data[4:8], "little") + 8 != len(data):
        return None
    kinds: list[bytes] = []
    position = 12
    while position + 8 <= len(data):
        kinds.append(data[position : position + 4])
        length = int.from_bytes(data[position + 4 : position + 8], "little")
        position += 8 + length + (length & 1)
    return kinds if position == len(data) else None


def _webp_is_only_a_picture(data: bytes) -> bool:
    kinds = _webp_chunks(data)
    return kinds is not None and all(kind in _WEBP_PICTURE_CHUNKS for kind in kinds)


def _webp_is_lossless(data: bytes) -> bool:
    """Whether a WebP was stored losslessly, so that its copies are too."""
    return b"VP8L" in (_webp_chunks(data) or [])


def is_only_a_picture(data: bytes, image_format: str) -> bool:
    """Whether the file can be stored as it is, with nothing in it to remove.

    A GIF never qualifies. Its extension blocks are free-form, and it is the
    one format here where re-encoding costs nothing in quality.
    """
    if image_format == "PNG":
        return _png_is_only_a_picture(data)
    if image_format == "JPEG":
        return _jpeg_is_only_a_picture(data)
    if image_format == "WEBP":
        return _webp_is_only_a_picture(data)
    return False


# ------------------------------------------------------------------ encoding


GIF_OPTIONS: dict[str, Any] = {"comment": b""}
"""Pillow's GIF writer starts from everything in ``image.info``, the comment
extension included. Naming an empty comment is how it is told to leave it out."""


def _encode(image: Image.Image, image_format: str, source: bytes) -> bytes:
    """Re-encode a decoded picture, carrying over its colour and nothing else.

    Nothing is taken from ``image.info`` implicitly. Pillow copies a JPEG's
    comment segment into the new file unless told otherwise, which would put
    back part of what re-encoding is for.
    """
    buffer = BytesIO()
    options: dict[str, Any] = {}
    profile = image.info.get("icc_profile")
    if image_format == "JPEG":
        options = {"quality": JPEG_REENCODE_QUALITY, "comment": b""}
        sampling = JpegImagePlugin.get_sampling(image) if hasattr(image, "layer") else -1
        if sampling in (0, 1, 2):
            options["subsampling"] = sampling
        if profile:
            options["icc_profile"] = profile
    elif image_format == "WEBP":
        options = {"lossless": True} if _webp_is_lossless(source) else {"quality": WEBP_REENCODE_QUALITY}
        if profile:
            options["icc_profile"] = profile
    elif image_format == "GIF":
        options = dict(GIF_OPTIONS)
    image.save(buffer, format=image_format, **options)
    return buffer.getvalue()


_PREMULTIPLIED = {"LA": "La", "RGBA": "RGBa"}
REDUCE_BAND_ROWS = 512


def reduced(image: Image.Image, target: int) -> Image.Image:
    """Bring a decoded picture within reach of ``target`` pixels on its long side.

    Averaging whole blocks of pixels into a small image is nearly free in
    memory: the only new buffer is the small one. A good resampling filter
    applied straight to the full-size picture is not — it works in two passes
    and keeps a full-height intermediate — and for a picture with an alpha
    channel Pillow first converts the *whole thing* to premultiplied alpha,
    which is a second buffer as large as the decode: another 160 MB for a
    forty-megapixel PNG, for the sake of a thumbnail.

    So the bulk of any large reduction is done here by block averaging, and
    the caller's ordinary resize finishes the job on a picture that is already
    at most twice the size wanted. With an alpha channel the averaging is done
    a band of rows at a time — premultiply the band, average it, paste it — so
    that the premultiplied copy is only ever one band. The bands are a multiple
    of the factor tall, so the blocks are the same blocks one pass would have
    averaged and no seam can show.
    """
    factor = max(image.size) // target
    if factor < 2:
        return image
    if image.mode not in _PREMULTIPLIED:
        smaller = image.reduce(factor)
        smaller.info = dict(image.info)
        return smaller
    width, height = image.size
    band = factor * max(1, REDUCE_BAND_ROWS // factor)
    result = Image.new(image.mode, ((width + factor - 1) // factor, (height + factor - 1) // factor))
    for top in range(0, height, band):
        strip = image.crop((0, top, width, min(height, top + band)))
        strip = strip.convert(_PREMULTIPLIED[image.mode]).reduce(factor).convert(image.mode)
        result.paste(strip, (0, top // factor))
    result.info = dict(image.info)
    return result


def draft_for(image: Image.Image, target: int) -> None:
    """Ask a JPEG to decode itself smaller, when it is much larger than wanted.

    A JPEG can be decoded at a half, a quarter or an eighth of its size for a
    fraction of the memory. The decoder only does so if *both* sides stay at
    least as large as the size asked for, so the request has to have the
    picture's own proportions: asking a 8000 x 5000 photograph for a square
    2560 gets it decoded at full size, because half of 5000 is less than 2560.
    Other formats ignore this.
    """
    width, height = image.size
    scale = target / max(width, height)
    if scale < 1:
        image.draft(None, (max(1, int(width * scale)), max(1, int(height * scale))))


def _display_copy(image: Image.Image, image_format: str, lossless_webp: bool) -> bytes:
    """Shrink a decoded picture, in place, to the display size and encode it.

    In place because the caller is finished with the full-size pixels, and a
    second full-size buffer is the cost this whole mechanism exists to avoid.
    """
    if image.mode == "P":
        image = image.convert("RGBA" if "transparency" in image.info else "RGB")
    elif image.mode not in {"L", "LA", "RGB", "RGBA"}:
        # CMYK from a print workflow, 1-bit, 16-bit greyscale off a camera: all
        # are shown as ordinary 8-bit colour.
        image = image.convert("RGB")
    image = reduced(image, DISPLAY_MAX_SIDE)
    image.thumbnail((DISPLAY_MAX_SIDE, DISPLAY_MAX_SIDE), Image.Resampling.LANCZOS)

    buffer = BytesIO()
    profile = image.info.get("icc_profile")
    extra: dict[str, Any] = {"icc_profile": profile} if profile else {}
    if image_format == "JPEG":
        image.save(buffer, format="JPEG", quality=DISPLAY_JPEG_QUALITY, optimize=True, comment=b"", **extra)
    elif image_format == "WEBP":
        quality: dict[str, Any] = {"lossless": True} if lossless_webp else {"quality": DISPLAY_JPEG_QUALITY}
        image.save(buffer, format="WEBP", **quality, **extra)
    else:
        image.save(buffer, format="PNG", **extra)
    return buffer.getvalue()


def wants_display_copy(width: int | None, height: int | None, content_type: str) -> bool:
    """Whether a picture of this size and type is shown through a display copy.

    An animated GIF is left alone: shrinking it means re-timing every frame, and
    the pixel budget at upload already bounds what one can cost.
    """
    if not width or not height or content_type == "image/gif":
        return False
    return max(width, height) > DISPLAY_MAX_SIDE


# ---------------------------------------------------------------- validation


def process(payload: bytes, max_dimension: int, max_pixels: int, want_display: bool = True) -> ProcessedImage:
    """Validate an upload, decide what is stored, and make its display copy.

    Every size question is answered from the header, before anything decodes.
    That ordering is the whole point: ``open()`` and ``verify()`` read structure
    only, and ``load()`` is what actually asks for width times height pixels of
    memory, so a limit applied anywhere after the format probe has already let
    the allocation happen. A 300 KiB flat PNG declaring 10000 x 10000 is the
    concrete case — cheap to transfer, three quarters of a gigabyte to decode.

    The picture is then decoded once, completely. That one decode is the proof
    that the file is an image and not merely a header; it is where an EXIF
    rotation is applied; and it is what the display copy is made from, so the
    largest thing an upload costs is one decoded picture and never two.
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
        raise errors.validation_failed(f"Images must be at most {max_dimension} pixels on each side.")
    if width * height > max_pixels:
        raise errors.validation_failed(too_many_pixels_message(max_pixels))

    try:
        with Image.open(BytesIO(payload)) as probe:
            frames = getattr(probe, "n_frames", 1)
    except Exception as exc:
        raise errors.validation_failed("That file is not a readable image.") from exc
    if width * height * frames > max_pixels * MAX_ANIMATION_FACTOR:
        raise errors.validation_failed(
            "That animation is too large to process. Shorten it, shrink it, or upload it as a video instead."
        )

    try:
        with Image.open(BytesIO(payload)) as probe:
            probe.verify()
    except Exception as exc:
        raise errors.validation_failed("That file is not a readable image.") from exc

    content_type, extension = ACCEPTED_FORMATS[image_format]
    with _decode_slots, Image.open(BytesIO(payload)) as image:
        try:
            if frames > 1:
                # An animation is re-encoded frame by frame, as it always was.
                # Transposing would keep its first frame only, and the formats
                # that animate are not the ones cameras write.
                buffer = BytesIO()
                image.save(buffer, format=image_format, save_all=True, **(GIF_OPTIONS if image_format == "GIF" else {}))
                return ProcessedImage(
                    NormalisedImage(buffer.getvalue(), content_type, extension, *image.size), None
                )

            if is_only_a_picture(payload, image_format):
                # Stored as it is, so the pixels are wanted for two things
                # only: to prove the whole file decodes, and to make the
                # display copy. A JPEG does both at reduced scale — every byte
                # of it is still read and decoded — for a quarter of the memory.
                draft_for(image, DISPLAY_MAX_SIDE)
                image.load()
                stored = payload
            else:
                image.load()
                # A phone held upright records a landscape frame plus a tag
                # saying "turn me"; the tag is about to be stripped with the
                # rest of the EXIF, so the turn is made in the pixels — in
                # place, because the alternative is a second full-size copy of
                # a picture that needed no turning.
                if image.getexif().get(ExifTags.Base.Orientation, 1) != 1:
                    ImageOps.exif_transpose(image, in_place=True)
                stored = _encode(image, image_format, payload)
                width, height = image.size

            display = None
            if want_display and wants_display_copy(width, height, content_type):
                display = _display_copy(image, image_format, image_format == "WEBP" and _webp_is_lossless(payload))
        except Exception as exc:
            raise errors.validation_failed("That image could not be processed.") from exc

    return ProcessedImage(NormalisedImage(stored, content_type, extension, width, height), display)


def normalise(payload: bytes, max_dimension: int, max_pixels: int) -> NormalisedImage:
    """Validate an upload and return what should be stored for it.

    The form of :func:`process` for a caller that stores the file itself and
    leaves the display copy to be made the first time it is asked for — the
    importer and the demo seed. Same checks, same stored bytes.
    """
    return process(payload, max_dimension, max_pixels, want_display=False).image


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


def write_file_atomically(target: Path, payload: bytes) -> None:
    """Write beside the target and rename over it.

    For files that are made on demand and may be asked for while they are being
    made: a reader either finds the whole file or finds none, never the first
    half, including when two workers make the same one at the same moment.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    scratch = target.with_name(f".{target.name}.{os.getpid()}.{threading.get_ident()}.part")
    try:
        scratch.write_bytes(payload)
        os.replace(scratch, target)
    finally:
        scratch.unlink(missing_ok=True)


def display_storage_path(storage_path: str) -> str:
    """Where an upload's display copy lives: beside the original, same format.

    Beside it so that a backup, a restore and a delete all treat the pair as
    one thing without having to know that there are two.
    """
    stem, dot, extension = storage_path.rpartition(".")
    return f"{stem}{DISPLAY_SUFFIX}{dot}{extension}"


def stored_files(media_root: Path, storage_path: str) -> list[Path]:
    """Every file on disk that belongs to one upload."""
    return [media_root / storage_path, media_root / display_storage_path(storage_path)]


def _make_display_copy(original: Path, target: Path) -> None:
    with Image.open(original) as image:
        if getattr(image, "n_frames", 1) > 1:
            raise ValueError("an animation has no display copy")
        image_format = image.format or ""
        lossless = image_format == "WEBP" and _webp_is_lossless(original.read_bytes())
        draft_for(image, DISPLAY_MAX_SIDE)
        image.load()
        write_file_atomically(target, _display_copy(image, image_format, lossless))


def display_file(
    media_root: Path,
    storage_path: str,
    width: int | None,
    height: int | None,
    content_type: str,
    wait_seconds: float = DECODE_WAIT_SECONDS,
) -> Path:
    """The file to show for an image: its display copy, made now if it has none.

    Uploads get their display copy as they arrive. Whatever predates that, or
    came in through the importer, gets one here the first time anybody asks.
    When that cannot happen — the decoders are busy, or the file will not
    decode — the answer is the original, which is always a correct picture and
    only ever a larger one.
    """
    original = resolve_file(media_root, storage_path)
    if not wants_display_copy(width, height, content_type) or storage_path in _no_display_copy:
        return original
    target = original.with_name(Path(display_storage_path(storage_path)).name)
    if target.is_file():
        return target
    if not _decode_slots.acquire(timeout=wait_seconds):
        return original
    try:
        if not target.is_file():
            _make_display_copy(original, target)
    except Exception:
        logger.warning("Could not make a display copy of %s.", storage_path, exc_info=True)
        _no_display_copy.add(storage_path)
        return original
    finally:
        _decode_slots.release()
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
