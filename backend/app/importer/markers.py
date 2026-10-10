"""Vendor image markers, turned into Reticle annotations — and checked against pixels.

On the vendor side a marked-up image is a *second* image record with the
arrows and boxes already drawn into its pixels; the record it was made from
(``srcid``) is the clean picture. Reticle keeps annotations as data over a clean
picture, so they stay editable and stay sharp at any size. The import therefore
wants the clean source plus the marker geometry, and falls back to the burned-in
picture — which is always *right*, only no longer editable — whenever it cannot
be sure the two agree.

Two marker formats were observed on the live site (``markupState``):

* ``NODE_MARKUP`` — ``annotations.data`` is a list of ``arrow`` records
  (``xStart, yStart, xEnd, yEnd``) and ``rectangle`` records
  (``x, y, width, height``), with an optional ``edits.data.crop``;
* ``MARKER_JS`` — ``annotations.data`` holds a drawing canvas size and a list of
  ``markers`` (``FrameMarker`` with ``left, top, width, height`` was seen), with
  an optional ``edits`` of type ``CROPRO`` carrying a ``cropRect``.

What could not be established from the payloads alone is stated where it is
used: which coordinate space the older format's markers live in once a crop is
involved, which end of an arrow carries the head, and the layout of a circle.
That is why nothing here is trusted on its own. :func:`realise` lays the
predicted shapes over the difference between the clean and the burned-in
picture, and only an interpretation that the pixels confirm is used.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from PIL import Image, ImageChops, ImageDraw

from . import mapping

MAX_ANNOTATIONS = 50
DEFAULT_MARKER_COLOR = "red"


@dataclass(frozen=True)
class Shape:
    """One marker in pixels of the clean source image.

    For a rectangle or an ellipse the two points are opposite corners of its
    box; for an arrow they are the two ends in the order the vendor stored them.
    """

    kind: str
    color: str
    x1: float
    y1: float
    x2: float
    y2: float
    head: str = "end"
    """For an arrow: which stored end carries the head, when the payload says."""


@dataclass(frozen=True)
class Candidate:
    """One reading of the payload: a crop of the source, and shapes within it."""

    label: str
    crop: tuple[float, float, float, float]
    shapes: tuple[Shape, ...]


@dataclass
class Plan:
    has_markers: bool = False
    candidates: list[Candidate] = field(default_factory=list)
    fallback_reason: str | None = None
    notes: list[str] = field(default_factory=list)


class Unrepresentable(Exception):
    """The payload describes something Reticle's three shapes cannot express."""


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise Unrepresentable("a marker coordinate is missing or not a number")
    return float(value)


def _color(value: Any, notes: list[str]) -> str:
    found = mapping.color(value)
    if found is None:
        notes.append(f"marker colour {value!r} is not a known colour; drawn in {DEFAULT_MARKER_COLOR}")
        return DEFAULT_MARKER_COLOR
    return found


IDENTITY = {"a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0}


def _is_identity(matrix: Any) -> bool:
    if matrix is None:
        return True
    if not isinstance(matrix, dict):
        return False
    return all(abs(float(matrix.get(key, default)) - default) < 1e-6 for key, default in IDENTITY.items())


def parse_markup_string(markup: str) -> dict[str, Any]:
    """The legacy ``;shape,AxB,CxD,colour;`` string as a ``markupState``.

    Only used when a payload has the string and no structured state. The
    ``arrow`` and ``crop`` records were seen live; ``rectangle`` and ``circle``
    follow the vendor's classic layout and are assumed.
    """

    def pair(text: str) -> tuple[float, float]:
        left, _, right = text.partition("x")
        return float(left), float(right)

    annotations: list[dict[str, Any]] = []
    edits: dict[str, Any] = {}
    for record in markup.split(";"):
        fields = [part.strip() for part in record.split(",")]
        if not fields or not fields[0]:
            continue
        shape = fields[0].lower()
        try:
            if shape == "crop":
                (x, y), (width, height) = pair(fields[1]), pair(fields[2])
                edits = {"type": "NODE_MARKUP", "data": {"crop": {"x": x, "y": y, "width": width, "height": height}}}
            elif shape == "arrow":
                (x1, y1), (x2, y2) = pair(fields[1]), pair(fields[2])
                annotations.append(
                    {"shape": "arrow", "xStart": x1, "yStart": y1, "xEnd": x2, "yEnd": y2, "color": fields[3] if len(fields) > 3 else None}
                )
            elif shape == "rectangle":
                (x1, y1), (x2, y2) = pair(fields[1]), pair(fields[2])
                annotations.append(
                    {"shape": "rectangle", "x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1, "color": fields[3] if len(fields) > 3 else None}
                )
            elif shape == "circle":
                x, y = pair(fields[1])
                annotations.append({"shape": "circle", "x": x, "y": y, "radius": float(fields[2]), "color": fields[3] if len(fields) > 3 else None})
            else:
                annotations.append({"shape": shape})
        except (IndexError, ValueError):
            annotations.append({"shape": f"{shape} (unreadable)"})

    state: dict[str, Any] = {}
    if edits:
        state["edits"] = edits
    if annotations:
        state["annotations"] = {"type": "NODE_MARKUP", "data": annotations}
    return state


def _node_markup_shapes(records: list[Any], notes: list[str]) -> list[Shape]:
    shapes: list[Shape] = []
    for record in records:
        if not isinstance(record, dict):
            raise Unrepresentable("a marker record is not an object")
        kind = str(record.get("shape") or "").lower()
        color = _color(record.get("color"), notes)
        if kind == "arrow":
            shapes.append(
                Shape("arrow", color, _number(record.get("xStart")), _number(record.get("yStart")), _number(record.get("xEnd")), _number(record.get("yEnd")), head="unknown")
            )
        elif kind == "rectangle":
            x, y = _number(record.get("x")), _number(record.get("y"))
            shapes.append(Shape("rectangle", color, x, y, x + _number(record.get("width")), y + _number(record.get("height"))))
        elif kind in {"circle", "ellipse"}:
            x, y = _number(record.get("x")), _number(record.get("y"))
            if "radius" in record:
                radius = _number(record.get("radius"))
                shapes.append(Shape("ellipse", color, x - radius, y - radius, x + radius, y + radius))
            else:
                shapes.append(Shape("ellipse", color, x, y, x + _number(record.get("width")), y + _number(record.get("height"))))
        else:
            raise Unrepresentable(f"marker shape “{kind or 'unknown'}” has no Reticle equivalent")
    return shapes


RECTANGLE_MARKERS = frozenset({"FrameMarker"})
ELLIPSE_MARKERS = frozenset({"EllipseFrameMarker", "EllipseMarker"})
ARROW_MARKERS = frozenset({"ArrowMarker"})


def _marker_js_shapes(markers: list[Any], notes: list[str]) -> list[Shape]:
    """Markers in the units of the drawing canvas they were made on.

    ``FrameMarker`` was seen live. The ellipse and arrow markers follow the
    marker library's published state format and are assumed.
    """
    shapes: list[Shape] = []
    for marker in markers:
        if not isinstance(marker, dict):
            raise Unrepresentable("a marker record is not an object")
        name = str(marker.get("typeName") or "unknown")
        if abs(float(marker.get("rotationAngle") or 0)) > 0.01:
            raise Unrepresentable(f"a rotated {name} has no Reticle equivalent")
        if not _is_identity(marker.get("visualTransformMatrix")) or not _is_identity(marker.get("containerTransformMatrix")):
            raise Unrepresentable(f"a transformed {name} has no Reticle equivalent")
        color = _color(marker.get("strokeColor"), notes)

        if name in RECTANGLE_MARKERS or name in ELLIPSE_MARKERS:
            fill = str(marker.get("fillColor") or "transparent").lower()
            if fill not in {"transparent", "none", ""}:
                raise Unrepresentable(f"a filled {name} hides what is under it; Reticle only draws outlines")
            left, top = _number(marker.get("left")), _number(marker.get("top"))
            kind = "rectangle" if name in RECTANGLE_MARKERS else "ellipse"
            shapes.append(Shape(kind, color, left, top, left + _number(marker.get("width")), top + _number(marker.get("height"))))
        elif name in ARROW_MARKERS:
            arrow_type = str(marker.get("arrowType") or "end").lower()
            if arrow_type not in {"start", "end"}:
                raise Unrepresentable(f"an arrow of type “{arrow_type}” has no Reticle equivalent")
            shapes.append(
                Shape("arrow", color, _number(marker.get("x1")), _number(marker.get("y1")), _number(marker.get("x2")), _number(marker.get("y2")), head=arrow_type)
            )
        else:
            raise Unrepresentable(f"marker type “{name}” has no Reticle equivalent")
    return shapes


def _rect(value: Any) -> tuple[float, float, float, float]:
    if not isinstance(value, dict):
        raise Unrepresentable("the crop record is not an object")
    return _number(value.get("x")), _number(value.get("y")), _number(value.get("width")), _number(value.get("height"))


def _crop(edits: Any, source: tuple[float, float]) -> tuple[float, float, float, float]:
    """The part of the source that the marked-up picture shows, in source pixels."""
    full = (0.0, 0.0, source[0], source[1])
    if not edits:
        return full
    if not isinstance(edits, dict) or not isinstance(edits.get("data"), dict):
        raise Unrepresentable("the edit record could not be read")
    kind = str(edits.get("type") or "")
    data = edits["data"]

    if kind == "NODE_MARKUP":
        unknown = set(data) - {"crop"}
        if unknown:
            raise Unrepresentable(f"image edit “{sorted(unknown)[0]}” is not understood")
        return _rect(data["crop"]) if data.get("crop") else full

    if kind == "CROPRO":
        if abs(float(data.get("rotationAngle") or 0)) > 0.01 or data.get("flippedVertically") or data.get("flippedHorizontally"):
            raise Unrepresentable("the picture was rotated or flipped after upload")
        if not data.get("cropRect"):
            return full
        x, y, width, height = _rect(data["cropRect"])
        base_width = float(data.get("width") or source[0])
        base_height = float(data.get("height") or source[1])
        scale_x, scale_y = source[0] / base_width, source[1] / base_height
        return x * scale_x, y * scale_y, width * scale_x, height * scale_y

    raise Unrepresentable(f"image edit type “{kind or 'unknown'}” is not understood")


def _move(shapes: list[Shape], offset: tuple[float, float], scale: tuple[float, float]) -> tuple[Shape, ...]:
    return tuple(
        Shape(
            shape.kind,
            shape.color,
            offset[0] + shape.x1 * scale[0],
            offset[1] + shape.y1 * scale[1],
            offset[0] + shape.x2 * scale[0],
            offset[1] + shape.y2 * scale[1],
            shape.head,
        )
        for shape in shapes
    )


def interpret(meta: dict[str, Any]) -> Plan:
    """Read an image's metadata into candidate annotation layouts.

    No pixels are involved yet. The result is either no markers at all, a
    reason the markers cannot be expressed, or one or more candidates for
    :func:`realise` to test.
    """
    plan = Plan()
    state = meta.get("markupState")
    if not isinstance(state, dict) and isinstance(meta.get("markup"), str):
        state = parse_markup_string(meta["markup"])
    if not isinstance(state, dict):
        return plan

    annotations = state.get("annotations")
    if not isinstance(annotations, dict):
        return plan
    data = annotations.get("data")
    kind = str(annotations.get("type") or "")
    records = data.get("markers") if isinstance(data, dict) else data
    if not records:
        return plan
    plan.has_markers = True

    source_info = meta.get("srcImageInfo")
    if not meta.get("srcid") or not isinstance(source_info, dict):
        plan.fallback_reason = "the markers have no clean source image to be drawn over"
        return plan

    try:
        if len(records) > MAX_ANNOTATIONS:
            raise Unrepresentable(f"{len(records)} markers on one image is more than Reticle's {MAX_ANNOTATIONS}")
        source = (_number(source_info.get("width")), _number(source_info.get("height")))
        if source[0] <= 0 or source[1] <= 0:
            raise Unrepresentable("the clean source image has no size")
        crop = _crop(state.get("edits"), source)
        if crop[2] <= 0 or crop[3] <= 0:
            raise Unrepresentable("the crop has no area")

        if kind == "NODE_MARKUP":
            shapes = _node_markup_shapes(list(records), plan.notes)
            plan.candidates.append(Candidate("markers in source-image pixels", crop, tuple(shapes)))
            if abs(crop[0]) > 0.5 or abs(crop[1]) > 0.5:
                plan.candidates.append(
                    Candidate("markers in cropped-image pixels", crop, _move(shapes, (crop[0], crop[1]), (1.0, 1.0)))
                )
        elif kind == "MARKER_JS":
            canvas = (_number(data.get("width")), _number(data.get("height")))
            if canvas[0] <= 0 or canvas[1] <= 0:
                raise Unrepresentable("the marker canvas has no size")
            shapes = _marker_js_shapes(list(records), plan.notes)
            scale = (crop[2] / canvas[0], crop[3] / canvas[1])
            plan.candidates.append(Candidate("markers on the editor canvas", crop, _move(shapes, (crop[0], crop[1]), scale)))
        else:
            raise Unrepresentable(f"marker format “{kind or 'unknown'}” is not understood")
    except (Unrepresentable, TypeError, ValueError) as problem:
        plan.candidates.clear()
        plan.fallback_reason = str(problem)
    return plan


# ---------------------------------------------------------------- pixels


@dataclass
class Realised:
    """A clean picture and the annotations that belong on it."""

    image: Image.Image
    cropped: bool
    annotations: list[dict[str, Any]]
    label: str
    score: float
    notes: list[str]


CHECK_SIZE = 640
"""Long edge, in pixels, at which the clean and marked pictures are compared."""

DIFFERENCE_THRESHOLD = 48
"""How far a pixel must move, out of 255, to count as "a marker was drawn here".

Re-encoding a JPEG moves pixels by a few levels everywhere; a marker stroke is a
saturated colour and moves them by far more.
"""

MIN_EXPLAINED = 0.6
"""Share of the changed pixels that must lie on the predicted shapes."""

MIN_EVIDENCE = 0.02
"""Share of a shape's own outline band that must have changed."""


def _visible(crop: tuple[float, float, float, float], size: tuple[int, int]) -> tuple[float, float, float, float] | None:
    """The crop, held to the picture: a crop may reach past the edge to pad."""
    left, top = max(crop[0], 0.0), max(crop[1], 0.0)
    right, bottom = min(crop[0] + crop[2], float(size[0])), min(crop[1] + crop[3], float(size[1]))
    if right - left < 1 or bottom - top < 1:
        return None
    return left, top, right, bottom


def _clamp(value: float) -> float:
    return min(max(value, 0.0), 1.0)


def _fractions(shape: Shape, frame: tuple[float, float, float, float], head_at_start: bool) -> dict[str, Any] | None:
    """One shape as Reticle stores it: fractions of the visible picture."""
    width, height = frame[2] - frame[0], frame[3] - frame[1]
    x1, y1 = (shape.x1 - frame[0]) / width, (shape.y1 - frame[1]) / height
    x2, y2 = (shape.x2 - frame[0]) / width, (shape.y2 - frame[1]) / height

    if shape.kind == "arrow":
        if head_at_start:
            x1, y1, x2, y2 = x2, y2, x1, y1
        x1, y1, x2, y2 = _clamp(x1), _clamp(y1), _clamp(x2), _clamp(y2)
        if abs(x2 - x1) < 1e-4 and abs(y2 - y1) < 1e-4:
            return None
        box = (x1, y1, x2 - x1, y2 - y1)
    else:
        left, right = sorted((_clamp(x1), _clamp(x2)))
        top, bottom = sorted((_clamp(y1), _clamp(y2)))
        if right - left < 1e-4 or bottom - top < 1e-4:
            return None
        box = (left, top, right - left, bottom - top)
    return {
        "shape": shape.kind,
        "color": shape.color,
        "x": round(box[0], 5),
        "y": round(box[1], 5),
        "width": round(box[2], 5),
        "height": round(box[3], 5),
    }


def _draw(annotation: dict[str, Any], size: tuple[int, int], stroke: int) -> Image.Image:
    """The band of pixels where this shape's outline is expected."""
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    x, y = annotation["x"] * size[0], annotation["y"] * size[1]
    width, height = annotation["width"] * size[0], annotation["height"] * size[1]
    if annotation["shape"] == "arrow":
        draw.line((x, y, x + width, y + height), fill=255, width=stroke)
        radius = stroke
        draw.ellipse((x + width - radius, y + height - radius, x + width + radius, y + height + radius), fill=255)
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=255)
    else:
        half = stroke / 2
        outer = (x - half, y - half, x + width + half, y + height + half)
        method = draw.rectangle if annotation["shape"] == "rectangle" else draw.ellipse
        method(outer, fill=255)
        if width > stroke and height > stroke:
            method((x + half, y + half, x + width - half, y + height - half), fill=0)
    return mask


def _count(mask: Image.Image) -> int:
    return mask.histogram()[255]


def _difference(clean: Image.Image, burned: Image.Image) -> Image.Image:
    """Where the marked picture differs from the clean one, as a 0/255 mask."""
    delta = ImageChops.difference(clean.convert("RGB"), burned.convert("RGB"))
    red, green, blue = delta.split()
    strongest = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    return strongest.point(lambda value: 255 if value >= DIFFERENCE_THRESHOLD else 0)


HEAD_RADII = (0.08, 0.15, 0.25, 0.35)
"""Disc sizes, as shares of an arrow's length, at which its two ends are compared.

How large the vendor draws an arrow head is not known, so several sizes are
tried: a head shows up as extra paint at whichever size roughly matches it.
"""


def _head_at_start(shape: Shape, frame: tuple[float, float, float, float], changed: Image.Image) -> bool | None:
    """Which end of an arrow has the head, judged by where more paint landed.

    A shaft puts the same amount of paint near both ends; the head adds to one
    of them. ``None`` means the picture does not settle it — the two ends look
    alike, or different disc sizes disagree.
    """
    size = changed.size
    scale_x, scale_y = size[0] / (frame[2] - frame[0]), size[1] / (frame[3] - frame[1])
    start = ((shape.x1 - frame[0]) * scale_x, (shape.y1 - frame[1]) * scale_y)
    end = ((shape.x2 - frame[0]) * scale_x, (shape.y2 - frame[1]) * scale_y)
    length = math.hypot(end[0] - start[0], end[1] - start[1])

    def paint(point: tuple[float, float], radius: float) -> int:
        disc = Image.new("L", size, 0)
        ImageDraw.Draw(disc).ellipse((point[0] - radius, point[1] - radius, point[0] + radius, point[1] + radius), fill=255)
        return _count(ImageChops.multiply(disc, changed))

    votes: set[bool] = set()
    for share in HEAD_RADII:
        radius = max(4.0, length * share)
        at_start, at_end = paint(start, radius), paint(end, radius)
        if at_start > at_end * 1.25 + 2:
            votes.add(True)
        elif at_end > at_start * 1.25 + 2:
            votes.add(False)
    return votes.pop() if len(votes) == 1 else None


def realise(plan: Plan, clean: Image.Image, burned: Image.Image | None, arrow_head: str = "auto") -> Realised | None:
    """Pick the candidate the pixels agree with, or ``None`` to use the burned-in picture.

    ``arrow_head`` is ``auto`` (decide per arrow from the pixels, falling back
    to the stored end), ``end`` or ``start``. With ``burned`` set to ``None``
    nothing is checked and the first candidate is taken on trust; that is for a
    caller who has chosen to skip verification, never the default.
    """
    best: Realised | None = None
    for candidate in plan.candidates:
        frame = _visible(candidate.crop, clean.size)
        if frame is None:
            continue
        box = (round(frame[0]), round(frame[1]), round(frame[2]), round(frame[3]))
        cropped = box != (0, 0, clean.size[0], clean.size[1])
        picture = clean.crop(box) if cropped else clean
        notes: list[str] = []

        changed: Image.Image | None = None
        if burned is not None:
            scale = CHECK_SIZE / max(picture.size)
            size = (max(8, round(picture.size[0] * scale)), max(8, round(picture.size[1] * scale))) if scale < 1 else picture.size
            # The marked picture shows the whole crop, padding included; take the part that is real picture.
            ratio_x, ratio_y = burned.size[0] / candidate.crop[2], burned.size[1] / candidate.crop[3]
            window = (
                round((frame[0] - candidate.crop[0]) * ratio_x),
                round((frame[1] - candidate.crop[1]) * ratio_y),
                round((frame[2] - candidate.crop[0]) * ratio_x),
                round((frame[3] - candidate.crop[1]) * ratio_y),
            )
            if abs(ratio_x - ratio_y) > 0.02 * max(ratio_x, ratio_y) or window[2] - window[0] < 2 or window[3] - window[1] < 2:
                continue
            changed = _difference(
                picture.resize(size, Image.Resampling.BILINEAR),
                burned.crop(window).resize(size, Image.Resampling.BILINEAR),
            )

        annotations: list[dict[str, Any]] = []
        for shape in candidate.shapes:
            head_at_start = shape.head == "start"
            if shape.kind == "arrow":
                if arrow_head == "start":
                    head_at_start = True
                elif arrow_head == "end":
                    head_at_start = False
                elif changed is not None:
                    judged = _head_at_start(shape, frame, changed)
                    if judged is not None:
                        head_at_start = judged
                    elif shape.head == "unknown":
                        notes.append("an arrow's direction could not be read from the picture; its head was put at the stored end point")
            annotation = _fractions(shape, frame, head_at_start)
            if annotation is None:
                notes.append("a marker lay outside the visible picture and was left out")
                continue
            annotations.append(annotation)
        if not annotations:
            continue

        score = 1.0
        if changed is not None:
            total = _count(changed)
            if total == 0:
                continue
            stroke = max(5, round(min(changed.size) * 0.035))
            union = Image.new("L", changed.size, 0)
            supported = True
            for annotation in annotations:
                band = _draw(annotation, changed.size, stroke)
                union = ImageChops.lighter(union, band)
                if _count(ImageChops.multiply(band, changed)) < max(3, _count(band) * MIN_EVIDENCE):
                    supported = False
            score = _count(ImageChops.multiply(union, changed)) / total
            if not supported or score < MIN_EXPLAINED:
                continue

        if best is None or score > best.score:
            best = Realised(picture, cropped, annotations, candidate.label, score, notes)
    return best
