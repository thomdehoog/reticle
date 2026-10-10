"""A guide as a printable A4 document.

ZMB prints guides and tapes them next to instruments, so the export has to carry
what the screen carries: the step images with their annotations drawn on, the
coloured bullets, the flags, the indentation. It is built from the same wire
object the reader page receives, which is what guarantees the two cannot
disagree about what a guide says.

Everything an author typed is data here and never markup. ReportLab's paragraphs
understand an XML-like tag language, so every user string is escaped on its way
in; the only tags in the output are the handful this module writes itself.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import logging
import math
import threading
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image
from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer

from . import errors
from .schemas import AnnotationOut, BulletOut, GuideOut, MediaOut, StepOut

logger = logging.getLogger(__name__)

PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN = 18 * mm
CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN

COLORS = {
    "black": "#1f2328",
    "red": "#d1242f",
    "orange": "#bc4c00",
    "yellow": "#9a6700",
    "green": "#1a7f37",
    "light_blue": "#0e7490",
    "blue": "#0969da",
    "violet": "#8250df",
}
"""The bullet palette, identical to the frontend's so print matches screen."""

FLAGS = {
    "note": ("Note", COLORS["blue"]),
    "caution": ("Caution", COLORS["red"]),
    "reminder": ("Reminder", COLORS["violet"]),
}

DIFFICULTY_LABELS = {
    "very_easy": "Very easy",
    "easy": "Easy",
    "moderate": "Moderate",
    "difficult": "Difficult",
    "very_difficult": "Very difficult",
}

MUTED = HexColor("#57606a")
RULE = HexColor("#d0d7de")

IMAGE_GAP = 8.0
SINGLE_IMAGE_MAX_WIDTH = 360.0
SINGLE_IMAGE_MAX_HEIGHT = 260.0
ROW_IMAGE_MAX_HEIGHT = 200.0

EMBED_MAX_PIXELS = 1400
"""Longest edge, in pixels, of an image as embedded in the PDF.

A step image is printed at most thirteen centimetres wide; 1400 pixels across
that is already past 270 dpi. Embedding the original instead would put a
forty-megapixel stitched panel into every export of the guide that uses it.
"""

INDENT_PER_LEVEL = 16.0
MARKER_WIDTH = 16.0

MAX_CONCURRENT_RENDERS = 2
RENDER_WAIT_SECONDS = 20.0

_render_slots = threading.BoundedSemaphore(MAX_CONCURRENT_RENDERS)
"""Laying out a long guide and decoding its images is the most expensive thing
the server does on behalf of a reader, and any account can ask for it. Two at a
time per worker keeps a burst of exports from starving everything else."""

FONT_CANDIDATES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "DejaVuSans.ttf",
        "DejaVuSans-Bold.ttf",
        ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu", "/usr/share/fonts/TTF", "/Library/Fonts"),
    ),
    ("arial.ttf", "arialbd.ttf", ("C:/Windows/Fonts",)),
)


@lru_cache(maxsize=1)
def fonts() -> tuple[str, str]:
    """Register and name the regular and bold faces.

    PDF's built-in Helvetica covers Latin-1 and nothing else, and microscopy
    text is full of what lies just outside it: λ, Å, ≥, →. DejaVu Sans is on
    essentially every Linux server and Arial on every Windows one, so those are
    used when found. ReportLab's bundled Bitstream Vera is the fallback, which
    keeps the export working on a bare install at the cost of the rarer glyphs.
    """
    for regular, bold, directories in FONT_CANDIDATES:
        for directory in directories:
            regular_path, bold_path = Path(directory) / regular, Path(directory) / bold
            if regular_path.is_file() and bold_path.is_file():
                pdfmetrics.registerFont(TTFont("Reticle", str(regular_path)))
                pdfmetrics.registerFont(TTFont("Reticle-Bold", str(bold_path)))
                return "Reticle", "Reticle-Bold"
    pdfmetrics.registerFont(TTFont("Reticle", "Vera.ttf"))
    pdfmetrics.registerFont(TTFont("Reticle-Bold", "VeraBd.ttf"))
    return "Reticle", "Reticle-Bold"


def plain(text: str) -> str:
    """Strip what cannot be typeset: control characters and broken surrogates."""
    cleaned = text.encode("utf-8", "ignore").decode("utf-8")
    return "".join(
        character if character in "\n" or ord(character) >= 32 else " " for character in cleaned
    )


def markup(text: str) -> str:
    """User text as inert paragraph markup: escaped, with its line breaks kept."""
    return escape(plain(text)).replace("\n", "<br/>")


@dataclass(frozen=True)
class Styles:
    title: ParagraphStyle
    summary: ParagraphStyle
    meta: ParagraphStyle
    heading: ParagraphStyle
    step: ParagraphStyle
    body: ParagraphStyle
    bullet: ParagraphStyle
    caption: ParagraphStyle


@lru_cache(maxsize=1)
def styles() -> Styles:
    regular, bold = fonts()
    base = ParagraphStyle("base", fontName=regular, fontSize=10, leading=14, alignment=TA_LEFT, splitLongWords=1)
    return Styles(
        title=ParagraphStyle("title", parent=base, fontName=bold, fontSize=22, leading=27, spaceAfter=6),
        summary=ParagraphStyle("summary", parent=base, fontSize=12, leading=16, textColor=MUTED, spaceAfter=8),
        meta=ParagraphStyle("meta", parent=base, fontSize=9, leading=13, textColor=MUTED, spaceAfter=12),
        heading=ParagraphStyle(
            "heading", parent=base, fontName=bold, fontSize=13, leading=17, spaceBefore=14, spaceAfter=6, keepWithNext=1
        ),
        step=ParagraphStyle(
            "step", parent=base, fontName=bold, fontSize=13, leading=17, spaceBefore=16, spaceAfter=8, keepWithNext=1
        ),
        body=ParagraphStyle("body", parent=base, spaceAfter=6),
        bullet=ParagraphStyle("bullet", parent=base),
        caption=ParagraphStyle("caption", parent=base, fontSize=9, leading=12, textColor=MUTED, spaceAfter=4),
    )


def format_minutes(minutes: int) -> str:
    hours, rest = divmod(minutes, 60)
    if hours and rest:
        return f"{hours} h {rest} min"
    if hours:
        return f"{hours} h"
    return f"{rest} min"


def format_time_range(low: int | None, high: int | None) -> str | None:
    if low is None and high is None:
        return None
    if low is None:
        return f"up to {format_minutes(high)}"
    if high is None:
        return f"from {format_minutes(low)}"
    if low == high:
        return format_minutes(low)
    return f"{format_minutes(low)} – {format_minutes(high)}"


def meta_line(guide: GuideOut, category_name: str) -> str:
    parts = []
    if category_name:
        parts.append(category_name)
    parts.append(f"Difficulty: {DIFFICULTY_LABELS[guide.difficulty]}")
    time_range = format_time_range(guide.time_required_min_minutes, guide.time_required_max_minutes)
    if time_range:
        parts.append(f"Time: {time_range}")
    if guide.tags:
        parts.append("Tags: " + ", ".join(guide.tags))
    parts.append(f"Version {guide.version}" if guide.version else "Unpublished draft")
    parts.append(f"Last updated {guide.updated_at.date().isoformat()}")
    return "  ·  ".join(parts)


@dataclass(frozen=True)
class EmbeddedImage:
    """One decoded, flattened, shrunken image, ready to be drawn any number of times."""

    reader: ImageReader
    width: int
    height: int


@dataclass(frozen=True)
class PreparedImage:
    """An embedded image as it appears in one step: with that step's annotations."""

    embedded: EmbeddedImage
    annotations: tuple[AnnotationOut, ...]

    @property
    def reader(self) -> ImageReader:
        return self.embedded.reader

    @property
    def width(self) -> int:
        return self.embedded.width

    @property
    def height(self) -> int:
        return self.embedded.height


def embed_image(path: Path) -> EmbeddedImage | None:
    """Decode, flatten and shrink one step image for embedding.

    Returns ``None`` for a file that is missing or will not decode; the export
    then says so in place of the picture rather than failing as a whole, because
    eleven good steps are worth more than no document.
    """
    try:
        with Image.open(path) as source:
            source.draft("RGB", (EMBED_MAX_PIXELS, EMBED_MAX_PIXELS))
            frame = source.convert("RGBA")
        flattened = Image.new("RGB", frame.size, "white")
        flattened.paste(frame, mask=frame.getchannel("A"))
        flattened.thumbnail((EMBED_MAX_PIXELS, EMBED_MAX_PIXELS))
        buffer = BytesIO()
        flattened.save(buffer, format="JPEG", quality=88)
    except Exception:
        logger.warning("Could not prepare %s for a PDF export.", path, exc_info=True)
        return None
    buffer.seek(0)
    return EmbeddedImage(ImageReader(buffer), flattened.width, flattened.height)


class ImageCache:
    """Each file is decoded once per export, however many steps show it.

    Guides reuse screenshots — the same overview with a different button
    outlined in each step — and decoding is the expensive part of an export.
    """

    def __init__(self, files: dict[str, Path]) -> None:
        self.files = files
        self.embedded: dict[str, EmbeddedImage | None] = {}

    def prepare(self, item: MediaOut) -> PreparedImage | None:
        if item.id not in self.embedded:
            path = self.files.get(item.id)
            self.embedded[item.id] = embed_image(path) if path is not None else None
        embedded = self.embedded[item.id]
        return None if embedded is None else PreparedImage(embedded, tuple(item.annotations))


class ImageRow(Flowable):
    """Up to three step images side by side, each with its annotations drawn on."""

    def __init__(self, images: list[PreparedImage]) -> None:
        super().__init__()
        self.images = images
        self.placements: list[tuple[float, float, float]] = []

    def wrap(self, available_width: float, available_height: float) -> tuple[float, float]:
        count = len(self.images)
        if count == 1:
            cell_width = min(available_width, SINGLE_IMAGE_MAX_WIDTH)
            max_height = SINGLE_IMAGE_MAX_HEIGHT
        else:
            cell_width = (available_width - IMAGE_GAP * (count - 1)) / count
            max_height = ROW_IMAGE_MAX_HEIGHT

        self.placements = []
        row_height = 0.0
        for index, image in enumerate(self.images):
            scale = min(cell_width / image.width, max_height / image.height)
            width, height = image.width * scale, image.height * scale
            self.placements.append((index * (cell_width + IMAGE_GAP), width, height))
            row_height = max(row_height, height)
        self.width, self.height = available_width, row_height
        return available_width, row_height

    def draw(self) -> None:
        canvas = self.canv
        for image, (x, width, height) in zip(self.images, self.placements):
            y = self.height - height
            canvas.drawImage(image.reader, x, y, width=width, height=height)
            canvas.saveState()
            canvas.setStrokeColor(RULE)
            canvas.setLineWidth(0.5)
            canvas.rect(x, y, width, height, stroke=1, fill=0)
            clip = canvas.beginPath()
            clip.rect(x, y, width, height)
            canvas.clipPath(clip, stroke=0, fill=0)
            for annotation in image.annotations:
                draw_annotation(canvas, annotation, x, y, width, height)
            canvas.restoreState()


def draw_annotation(canvas: Canvas, annotation: AnnotationOut, x: float, y: float, width: float, height: float) -> None:
    """Draw one shape over an image whose bottom-left corner is at ``(x, y)``.

    Stored coordinates are fractions measured from the top-left, as on screen;
    PDF measures from the bottom-left, so every vertical value is flipped. Each
    shape is stroked twice, white underneath and the colour on top, for the same
    reason the frontend does it: half of ZMB's screenshots are of near-black
    acquisition software, where a black or dark-blue outline alone disappears.
    """
    start_x = x + annotation.x * width
    start_y = y + height - annotation.y * height
    end_x = x + (annotation.x + annotation.width) * width
    end_y = y + height - (annotation.y + annotation.height) * height

    left, right = min(start_x, end_x), max(start_x, end_x)
    bottom, top = min(start_y, end_y), max(start_y, end_y)

    canvas.setLineCap(1)
    canvas.setLineJoin(1)
    for stroke, line_width in ((white, 3.4), (HexColor(COLORS[annotation.color]), 1.7)):
        canvas.setStrokeColor(stroke)
        canvas.setLineWidth(line_width)
        if annotation.shape == "rectangle":
            canvas.rect(left, bottom, right - left, top - bottom, stroke=1, fill=0)
        elif annotation.shape == "ellipse":
            canvas.ellipse(left, bottom, right, top, stroke=1, fill=0)
        else:
            _draw_arrow(canvas, start_x, start_y, end_x, end_y)


def _draw_arrow(canvas: Canvas, start_x: float, start_y: float, end_x: float, end_y: float) -> None:
    length = math.hypot(end_x - start_x, end_y - start_y)
    canvas.line(start_x, start_y, end_x, end_y)
    if length == 0:
        return
    angle = math.atan2(end_y - start_y, end_x - start_x)
    head = min(9.0, length * 0.35)
    spread = 0.42
    for side in (angle + math.pi - spread, angle + math.pi + spread):
        canvas.line(end_x, end_y, end_x + head * math.cos(side), end_y + head * math.sin(side))


class BulletRow(Flowable):
    """One bullet: a coloured dot or a flag, then its text, at its indent level.

    A flowable of its own rather than a table row. A guide may hold thousands of
    bullets, and a one-row table per bullet makes the layout pass several times
    slower for no visible difference.
    """

    def __init__(self, bullet: BulletOut, paragraph: Paragraph, show_marker: bool = True) -> None:
        super().__init__()
        self.bullet = bullet
        self.paragraph = paragraph
        self.show_marker = show_marker
        self.offset = bullet.level * INDENT_PER_LEVEL + MARKER_WIDTH
        self.spaceAfter = 3

    def wrap(self, available_width: float, available_height: float) -> tuple[float, float]:
        _, height = self.paragraph.wrap(max(available_width - self.offset, 60), available_height)
        self.width, self.height = available_width, height
        return available_width, height

    def split(self, available_width: float, available_height: float) -> list[Flowable]:
        parts = self.paragraph.split(max(available_width - self.offset, 60), available_height)
        if len(parts) < 2:
            return []
        return [
            BulletRow(self.bullet, parts[0], self.show_marker),
            BulletRow(self.bullet, parts[1], show_marker=False),
        ]

    def draw(self) -> None:
        self.paragraph.drawOn(self.canv, self.offset, 0)
        if self.show_marker:
            centre_x = self.offset - MARKER_WIDTH / 2
            centre_y = self.height - self.paragraph.style.leading / 2
            draw_marker(self.canv, self.bullet, centre_x, centre_y)


def draw_marker(canvas: Canvas, bullet: BulletOut, centre_x: float, centre_y: float) -> None:
    """A dot in the bullet's colour, or the flag's own shape and colour.

    The three flags differ in outline as well as in colour — circle, triangle,
    square — so they stay distinguishable on a black-and-white printer.
    """
    _, bold = fonts()
    canvas.saveState()
    if bullet.icon is None:
        canvas.setFillColor(HexColor(COLORS[bullet.color]))
        canvas.circle(centre_x, centre_y, 2.6, stroke=0, fill=1)
        canvas.restoreState()
        return

    _, color = FLAGS[bullet.icon]
    canvas.setFillColor(HexColor(color))
    if bullet.icon == "note":
        canvas.circle(centre_x, centre_y, 5, stroke=0, fill=1)
        glyph = "i"
    elif bullet.icon == "caution":
        path = canvas.beginPath()
        path.moveTo(centre_x, centre_y + 6)
        path.lineTo(centre_x - 6, centre_y - 4.5)
        path.lineTo(centre_x + 6, centre_y - 4.5)
        path.close()
        canvas.drawPath(path, stroke=0, fill=1)
        glyph = "!"
    else:
        canvas.roundRect(centre_x - 4.8, centre_y - 4.8, 9.6, 9.6, 1.6, stroke=0, fill=1)
        glyph = "R"
    canvas.setFillColor(white)
    canvas.setFont(bold, 7)
    canvas.drawCentredString(centre_x, centre_y - 2.5, glyph)
    canvas.restoreState()


def bullet_flowable(bullet: BulletOut) -> BulletRow:
    text = markup(bullet.text)
    if bullet.icon is not None:
        label, color = FLAGS[bullet.icon]
        text = f'<font color="{color}"><b>{label}:</b></font> {text}'
    return BulletRow(bullet, Paragraph(text, styles().bullet))


def media_flowables(media: list[MediaOut], cache: ImageCache) -> list[Flowable]:
    look = styles()
    flowables: list[Flowable] = []
    images: list[PreparedImage] = []
    notes: list[str] = []

    for item in media:
        if item.kind == "video":
            description = f" — {markup(item.alt)}" if item.alt.strip() else ""
            notes.append(f"<b>Video:</b> view this step online{description}")
            continue
        prepared = cache.prepare(item)
        if prepared is None:
            notes.append("<i>An image for this step could not be included.</i>")
        else:
            images.append(prepared)

    if images:
        flowables.append(ImageRow(images))
        flowables.append(Spacer(1, 8))
    flowables.extend(Paragraph(note, look.caption) for note in notes)
    return flowables


def step_flowables(number: int, step: StepOut, cache: ImageCache) -> list[Flowable]:
    look = styles()
    title = markup(step.title.strip())
    heading = f"Step {number}" + (f" &nbsp;—&nbsp; {title}" if title else "")
    flowables: list[Flowable] = [Paragraph(heading, look.step)]
    flowables.extend(media_flowables(step.media, cache))
    flowables.extend(bullet_flowable(bullet) for bullet in step.bullets)
    return flowables


def prose(text: str, style: ParagraphStyle) -> list[Flowable]:
    """Free text as paragraphs, split on blank lines."""
    blocks = [block for block in plain(text).split("\n\n") if block.strip()]
    return [Paragraph(markup(block.strip("\n")), style) for block in blocks]


def numbered_canvas(footer_title: str) -> type[Canvas]:
    """A canvas that can write "Page x of y".

    The total is not known until the last page has been laid out, so each page's
    state is kept and the footers are drawn in a second pass at save time.
    """
    regular, _ = fonts()

    class NumberedCanvas(Canvas):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self._pages: list[dict] = []

        def showPage(self) -> None:
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self) -> None:
            total = len(self._pages)
            for state in self._pages:
                self.__dict__.update(state)
                self._draw_footer(total)
                super().showPage()
            super().save()

        def _draw_footer(self, total: int) -> None:
            self.saveState()
            self.setStrokeColor(RULE)
            self.setLineWidth(0.5)
            self.line(MARGIN, 14 * mm, PAGE_WIDTH - MARGIN, 14 * mm)
            self.setFont(regular, 8)
            self.setFillColor(MUTED)
            page_label = f"Page {self._pageNumber} of {total}"
            room = CONTENT_WIDTH - pdfmetrics.stringWidth(page_label, regular, 8) - 12
            self.drawString(MARGIN, 10 * mm, fit(footer_title, regular, 8, room))
            self.drawRightString(PAGE_WIDTH - MARGIN, 10 * mm, page_label)
            self.restoreState()

    return NumberedCanvas


def fit(text: str, font: str, size: float, room: float) -> str:
    """Shorten a string with an ellipsis until it fits the given width."""
    if pdfmetrics.stringWidth(text, font, size) <= room:
        return text
    while text and pdfmetrics.stringWidth(text + "…", font, size) > room:
        text = text[:-1]
    return text.rstrip() + "…"


def build(guide: GuideOut, category_name: str, files: dict[str, Path]) -> bytes:
    look = styles()
    title = plain(guide.title).strip() or "Untitled guide"
    version = f"version {guide.version}" if guide.version else "unpublished draft"

    story: list[Flowable] = [Paragraph(markup(title), look.title)]
    if guide.summary.strip():
        story.extend(prose(guide.summary, look.summary))
    story.append(Paragraph(markup(meta_line(guide, plain(category_name))), look.meta))

    if guide.introduction.strip():
        story.append(Paragraph("Introduction", look.heading))
        story.extend(prose(guide.introduction, look.body))

    cache = ImageCache(files)
    for number, step in enumerate(guide.steps, start=1):
        story.extend(step_flowables(number, step, cache))

    if guide.conclusion.strip():
        story.append(Paragraph("Conclusion", look.heading))
        story.extend(prose(guide.conclusion, look.body))

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=20 * mm,
        title=title,
        author="Reticle",
        subject=f"{title} — {version}",
    )
    document.build(story, canvasmaker=numbered_canvas(f"{title}  ·  {version}"))
    return buffer.getvalue()


def render_guide(guide: GuideOut, category_name: str, files: dict[str, Path]) -> bytes:
    """Render a guide to PDF bytes.

    ``files`` maps the identifier of each image in the guide to where it is on
    disk. The caller has already decided the reader may see the guide and has
    resolved the paths; nothing here looks anything up.
    """
    if not _render_slots.acquire(timeout=RENDER_WAIT_SECONDS):
        raise errors.rate_limited("The PDF export is busy. Try again in a moment.")
    try:
        return build(guide, category_name, files)
    finally:
        _render_slots.release()
