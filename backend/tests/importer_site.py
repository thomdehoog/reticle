"""A stand-in for the vendor site, for testing the importer offline.

The payload shapes are the ones recorded in ``docs/dozuki-api-notes.md`` and in
anonymous GETs against the live API: the field names, the nesting, the two
marker formats (``NODE_MARKUP`` and ``MARKER_JS``), the placeholder image
objects, the list endpoints that apply ``limit`` before removing rows the caller
may not see. The *content* is invented — the people, addresses and e-mail
domains here do not exist — and every picture is drawn below.

The site is served through an ``httpx.MockTransport``, so the exporter under
test makes real requests against it, and the archive the loader tests read is
one the exporter itself wrote.

It can also be run, to write that archive to a directory for a manual check::

    python -m tests.importer_site <directory>
"""

from __future__ import annotations

import json
import sys
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
from PIL import Image, ImageDraw

HOST = "zmb.dozuki.com"
API = "/api/2.0"
CDN = "https://d3t0tbmlie281e.cloudfront.net/igi/zmb"
VIDEO_STORE = "https://dozuki-prod-us-east-1-guide-objects.s3.amazonaws.com/igo/video/zmb"
GOOD_TOKEN = "good-token-123"
EMAIL = "exporter@zmb.example"
PASSWORD = "local-admin-password"
SESSION_COOKIE = "session=abc123; other=1"

MARKER_RED = "#c1280b"
MARKER_GREEN = "#16dc81"


# ---------------------------------------------------------------- pictures


def photo(width: int, height: int, seed: int = 0) -> Image.Image:
    """Something with texture: a flat colour would hide a misplaced comparison."""
    image = Image.new("RGB", (width, height), (40 + seed * 7 % 60, 60, 80))
    draw = ImageDraw.Draw(image)
    for index in range(24):
        left = (index * 97 + seed * 31) % width
        top = (index * 61 + seed * 17) % height
        shade = 70 + (index * 23) % 120
        draw.rectangle((left, top, left + width // 7, top + height // 9), fill=(shade, shade + 20, 150 - shade // 2))
    return image


def encode(image: Image.Image, image_format: str) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format=image_format, **({"quality": 90} if image_format == "JPEG" else {}))
    return buffer.getvalue()


def draw_arrow(image: Image.Image, tail: tuple[float, float], head: tuple[float, float], color: str, width: int = 8) -> None:
    import math

    draw = ImageDraw.Draw(image)
    draw.line((*tail, *head), fill=color, width=width)
    angle = math.atan2(head[1] - tail[1], head[0] - tail[0])
    size = width * 4
    wings = [
        (head[0] - size * math.cos(angle - 0.45), head[1] - size * math.sin(angle - 0.45)),
        (head[0] - size * math.cos(angle + 0.45), head[1] - size * math.sin(angle + 0.45)),
    ]
    draw.polygon([head, *wings], fill=color)


def image_object(image_id: int, guid: str, huge: bool = True) -> dict[str, Any]:
    sizes = ["mini", "thumbnail", "140x105", "200x150", "standard", "440x330", "medium", "large"] + (["huge"] if huge else [])
    record: dict[str, Any] = {"id": image_id, "guid": guid}
    record.update({size: f"{CDN}/{guid}.{size}" for size in sizes})
    record["original"] = f"{CDN}/{guid}.full"
    return record


NO_IMAGE = {
    "mini": "https://d3015z1jd0uox2.cloudfront.net/static/images/default_images/WikiNoImage_56x42.jpg",
    "thumbnail": "https://d3015z1jd0uox2.cloudfront.net/static/images/default_images/WikiNoImage_96x72.jpg",
    "standard": "https://d3015z1jd0uox2.cloudfront.net/static/images/default_images/WikiNoImage_300x225.jpg",
    "medium": "https://d3015z1jd0uox2.cloudfront.net/static/images/default_images/WikiNoImage_592x444.jpg",
}
"""What a wiki without a picture carries: URLs, and no ``id`` (seen live)."""


def mp4(size: int = 4096) -> bytes:
    brands = b"isommp42"
    ftyp = (16 + len(brands)).to_bytes(4, "big") + b"ftyp" + b"isom" + b"\x00\x00\x02\x00" + brands
    padding = size - len(ftyp) - 8
    return ftyp + (8 + padding).to_bytes(4, "big") + b"free" + bytes(index % 251 for index in range(padding))


def bullet_style(color: str) -> dict[str, Any]:
    return {
        "bullet_styleid": 1, "type": "dot", "is_default": 1, "color_locked": 1, "label": None, "description": None,
        "is_disabled": 0, "bullet_color": color, "size": "small", "imageid": None, "char": None,
        "last_modified": 1702940726, "userid_modified": 1,
    }


def line(text_raw: str, bullet: str = "black", level: int = 0, rendered: str | None = None, color: str = "#11161a") -> dict[str, Any]:
    return {
        "text_raw": text_raw,
        "text_rendered": text_raw if rendered is None else rendered,
        "bullet": bullet,
        "bullet_styleid": 1,
        "bullet_style": bullet_style(color),
        "level": level,
        "lineid": None,
    }


class FakeSite:
    """Routes, pictures and a request log."""

    def __init__(self) -> None:
        self.documents: dict[str, Any] = {}
        self.lists: dict[str, list[Any]] = {}
        self.files: dict[str, tuple[bytes, str]] = {}
        self.private_guides: set[int] = set()
        self.failures: dict[str, list[httpx.Response | Exception]] = {}
        self.requests: list[httpx.Request] = []
        self.images: dict[int, dict[str, Any]] = {}
        self.app_id_required: str | None = None
        self.max_limit: dict[str, int] = {}
        self._build()

    # ------------------------------------------------------------ construction

    def add_image(
        self,
        image_id: int,
        picture: Image.Image,
        *,
        image_format: str = "JPEG",
        source: int | None = None,
        markup: str | None = None,
        state: dict[str, Any] | None = None,
        huge: bool = True,
    ) -> dict[str, Any]:
        guid = f"Guid{image_id:012d}"
        record = image_object(image_id, guid, huge)
        self.images[image_id] = record
        self.files[record["original"]] = (encode(picture, image_format), f"image/{image_format.lower()}")
        meta: dict[str, Any] = {
            "image": record,
            "srcid": source,
            "width": picture.size[0],
            "height": picture.size[1],
            "ratio": "FOUR_THREE" if abs(picture.size[0] / picture.size[1] - 4 / 3) < 0.01 else "VARIABLE",
            "markup": markup,
            "markupState": state,
            "exif": [],
            "encoding": image_format.lower(),
        }
        if source is not None:
            source_meta = self.documents[f"/media/images/{source}"]
            meta["srcImageInfo"] = {
                "image": source_meta["image"], "srcid": None, "width": source_meta["width"], "height": source_meta["height"],
                "ratio": source_meta["ratio"], "markup": None, "markupState": None, "encoding": source_meta["encoding"],
                "suggestedCrop": {"width": source_meta["width"], "height": source_meta["height"], "x": 0, "y": 0},
            }
        self.documents[f"/media/images/{image_id}"] = meta
        return record

    def _pictures(self) -> None:
        # 477 -> 507: a phone photograph with one arrow, no crop (the shape recorded in the notes).
        clean = photo(800, 600, 1)
        self.add_image(477, clean)
        marked = clean.copy()
        draw_arrow(marked, (505, 440), (185, 438), MARKER_RED)
        self.add_image(
            507, marked, source=477,
            markup=";arrow,505x440,185x438,red;",
            state={"annotations": {"type": "NODE_MARKUP", "version": "1", "data": [
                {"shape": "arrow", "xStart": 505, "yStart": 440, "xEnd": 185, "yEnd": 438, "color": "red"}]}},
        )

        # 14435 -> 14438: a screenshot letterboxed to 4:3 by a crop that reaches above the picture,
        # with a rectangle and an arrow given in source-image pixels (live: image 14438).
        clean = photo(710, 451, 2)
        self.add_image(14435, clean, image_format="PNG")
        drawn = clean.copy()
        ImageDraw.Draw(drawn).rectangle((3, 29, 125, 207), outline=MARKER_RED, width=6)
        draw_arrow(drawn, (690, 144), (617, 144), MARKER_GREEN, width=6)
        padded = Image.new("RGB", (710, 532), "white")
        padded.paste(drawn, (0, 41))
        self.add_image(
            14438, padded, image_format="PNG", source=14435, huge=False,
            markup=";crop,0x-40.75,710x532.5;",
            state={
                "edits": {"type": "NODE_MARKUP", "version": "1", "data": {"crop": {"x": 0, "y": -40.75, "width": 710, "height": 532.5}}},
                "annotations": {"type": "NODE_MARKUP", "version": "1", "data": [
                    {"shape": "rectangle", "x": 3, "y": 29, "width": 122, "height": 178, "color": "red"},
                    {"shape": "arrow", "xStart": 690, "yStart": 144, "xEnd": 617, "yEnd": 144, "color": "green"}]},
            },
        )

        # 22066 -> 22069: the newer editor. A real crop, and a frame drawn on a 959x719 canvas (live: image 22069).
        clean = photo(1435, 640, 3)
        self.add_image(22066, clean, image_format="PNG")
        cropped = clean.crop((107, 26, 803, 548)).resize((695, 521))
        scale = 695 / 959
        ImageDraw.Draw(cropped).rectangle((2.5 * scale, 346 * scale, 954.5 * scale, 386 * scale), outline=MARKER_RED, width=4)
        self.add_image(
            22069, cropped, image_format="PNG", source=22066, huge=False,
            state={
                "edits": {"type": "CROPRO", "version": "1", "data": {
                    "width": 1435, "height": 640,
                    "cropRect": {"x": 107.32251521298174, "y": 26.002789046653135, "width": 695.6693711967546, "height": 521.7520283975659},
                    "rotationAngle": 0, "flippedVertically": False, "flippedHorizontally": False}},
                "annotations": {"type": "MARKER_JS", "version": "2", "data": {"width": 959, "height": 719, "markers": [{
                    "top": 346, "left": 2.5, "state": "select", "width": 952, "height": 40, "opacity": 1,
                    "typeName": "FrameMarker", "fillColor": "transparent", "strokeColor": "#c1280b", "strokeWidth": 4.1,
                    "rotationAngle": 0, "strokeDasharray": "",
                    "visualTransformMatrix": {"a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0},
                    "containerTransformMatrix": {"a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0},
                    "strokeWidthRatioToDefault": 0.5}]}},
            },
        )

        # 599 -> 600: a marker Reticle cannot express (free text), so the burned-in picture must be used.
        clean = photo(640, 480, 4)
        self.add_image(599, clean)
        marked = clean.copy()
        ImageDraw.Draw(marked).text((200, 200), "PRESS HERE", fill=MARKER_RED)
        self.add_image(600, marked, source=599, state={"annotations": {"type": "MARKER_JS", "version": "2", "data": {
            "width": 640, "height": 480, "markers": [{"typeName": "TextMarker", "left": 200, "top": 200, "width": 90, "height": 20, "text": "PRESS HERE", "color": "#c1280b"}]}}})

        # 949 -> 950: metadata that does not describe the picture (the arrow is drawn somewhere else).
        clean = photo(640, 480, 5)
        self.add_image(949, clean)
        marked = clean.copy()
        draw_arrow(marked, (60, 60), (240, 90), MARKER_RED)
        self.add_image(950, marked, source=949, state={"annotations": {"type": "NODE_MARKUP", "version": "1", "data": [
            {"shape": "arrow", "xStart": 560, "yStart": 420, "xEnd": 380, "yEnd": 300, "color": "red"}]}})

        for image_id in (900, 901, 902, 903, 904):
            self.add_image(image_id, photo(320, 240, image_id), image_format="PNG", huge=False)
        self.add_image(12099, photo(400, 300, 9))
        self.add_image(17613, photo(1280, 720, 10))

    def _build(self) -> None:
        self._pictures()
        images = self.images

        video = {
            "objectid": 163, "videoid": 137, "srcid": None, "filename": "viewfinder.mp4", "duration": 8230,
            "width": 1280, "height": 720, "meta": None,
            "image": {"image": {key: images[17613][key] for key in ("id", "guid", "standard", "original")}, "srcid": None,
                      "width": 1280, "height": 720, "ratio": "VARIABLE", "markup": None, "markupState": None, "exif": [], "encoding": "jpeg"},
            "encodings": [{
                "column": "MP4_720", "label": "480p", "width": 720, "height": 480, "codecs": "avc1.4D401E, mp4a.40.2",
                "ffmpeg_args": "-vcodec libx264 -profile:v main", "mime": "video/mp4", "always_generate": True,
                "url": f"{VIDEO_STORE}/BJGvyPRLJAnukGuV_MP4_720.mp4", "format": "mp4"}],
        }
        self.documents["/media/videos/137"] = video
        self.files[video["encodings"][0]["url"]] = (mp4(), "video/mp4")

        def author(user_id: int, name: str) -> dict[str, Any]:
            return {"userid": user_id, "username": name, "unique_username": None, "join_date": 1556515438, "reputation": 1194,
                    "teams": [1], "enabled": True, "image": {"id": -32, "guid": "default"}}

        def guide(guide_id: int, title: str, category: str, steps: list[dict[str, Any]], **fields: Any) -> dict[str, Any]:
            document = {
                "guideid": guide_id, "title": title, "summary": "", "introduction_raw": "", "introduction_rendered": "",
                "conclusion_raw": "", "conclusion_rendered": "", "difficulty": "Easy", "time_required": "",
                "time_required_min": 0, "time_required_max": 0, "type": "how-to", "subject": "", "category": category,
                "public": True, "flags": [], "locale": "en", "langid": "en", "revisionid": 7000 + guide_id,
                "guide_revisionid": 28000 + guide_id, "created_date": 1554800000, "published_date": 1561989541,
                "modified_date": 1788435314, "prereq_modified_date": 0, "url": f"https://{HOST}/Guide/x/{guide_id}",
                "author": author(12, "Ada Example"), "image": images[900], "prerequisites": [], "documents": [],
                "tools": [], "parts": [], "comments": [], "can_edit": False, "favorited": False, "steps": steps,
            }
            document.update(fields)
            for number, step in enumerate(document["steps"], start=1):
                step.setdefault("guideid", guide_id)
                step.setdefault("orderby", number)
                step.setdefault("stepid", guide_id * 100 + number)
                step.setdefault("revisionid", 18000 + number)
                step.setdefault("time_estimate", 0)
                step.setdefault("comments", [])
                step.setdefault("title", "")
            self.documents[f"/guides/{guide_id}"] = document
            return document

        def pictures(*ids: int) -> dict[str, Any]:
            return {"type": "image", "data": [images[image_id] for image_id in ids]}

        guide(
            15, "Leica Stellaris 5 inverse (USZ) - How to get there", "basics access and IT - hidden",
            summary="How to get to the Stellaris 5 inverse in USZ.",
            introduction_raw="Find the room first. See [link|https://svi.nl/HowtoCiteHuygens|cite Huygens].",
            introduction_rendered='<p>Find the room first. See <a href="https://svi.nl/HowtoCiteHuygens" rel="nofollow noopener noreferrer">cite Huygens</a>.</p>',
            difficulty="Very easy", time_required="5 minutes", time_required_max=300,
            steps=[
                {"lines": [line("Get to the Pathology building at USZ, Schmelzbergstrasse 12 , CH-8091 Zürich.")], "media": pictures(507)},
                {"title": "Every kind of bullet", "media": pictures(14438, 22069, 900), "lines": [
                    line("'''Black''' bullet", "black", rendered="<strong>Black</strong> bullet"),
                    line("Red, nested", "red", 1, color="#c1280b"),
                    line("Orange, nested twice", "orange", 2, color="#ff9024"),
                    line("Yellow", "yellow"),
                    line("Green", "green", color="#16dc81"),
                    line("Light blue", "light_blue", color="#15a1d6"),
                    line("Blue", "blue"),
                    line("Violet", "violet"),
                    line("A note with a [https://svi.nl/NyquistCalculator|SVI Nyquist Calculator]", "icon_note",
                         rendered='A note with a <a href="https://svi.nl/NyquistCalculator" rel="nofollow noopener noreferrer">SVI Nyquist Calculator</a>'),
                    line("Mind the &quot;laser&quot;", "icon_caution", rendered="Mind the &quot;laser&quot;"),
                    line("Book the next slot", "icon_reminder"),
                    line("A site-defined bullet", "custom_17", color="#16dc81"),
                    line("Too deep", "black", 5),
                    line("", "black"),
                ]},
            ],
        )
        guide(
            27, "MesoSPIM - Part 1: Start-up", "LS - hidden guides",
            summary="Start-up guide for the ZMB mesoSPIM microscope.",
            introduction_raw="Start with [guide|15|getting there]. ***Read*** the manual.", introduction_rendered="",
            conclusion_raw="Done.", conclusion_rendered="<p>Done.</p>",
            difficulty="Moderate", time_required="30 minutes", time_required_min=1800, time_required_max=1800,
            created_date=1557814417, published_date=1585664812, modified_date=1780923676, author=author(22, "New Author"),
            steps=[
                {"title": "Mount ViewFinder", "lines": [line("Mount the ViewFinder."), line("Close the doors.")], "media": {"type": "video", "data": video}},
                {"title": "Four pictures", "lines": [line("Look at all of them.")], "media": pictures(900, 901, 902, 903)},
                {"title": "Hard cases", "lines": [line("A text marker and a wrong marker.")], "media": pictures(600, 950)},
                {"title": "", "lines": [line("")], "media": {"type": "image", "data": []}},
                {"title": "Embedded", "lines": [line("An embed.")], "media": {"type": "embed", "data": {"html": "<iframe></iframe>"}}},
            ],
        )
        guide(
            422, "Work in progress", "Basic Guides", difficulty="Legendary", created_date=1740643317,
            flags=[{"title": "In Progress", "flagid": "GUIDE_IN_PROGRESS", "text": "This guide is currently being written."}],
            author=author(26, "z mbstaff"),
            steps=[{"lines": [line("One line of text.")], "media": {"type": "image", "data": []}}],
        )
        guide(
            430, "Internal: laser safety interlock", "", public=False, published_date=0, author=author(12, "Ada Example"),
            steps=[{"lines": [line("Staff only.")], "media": pictures(904)}],
        )
        self.private_guides = {430}

        self.documents.update({
            "/guides/15/tags": ["location-access", "StellUSZ"],
            "/guides/27/tags": ["Lightsheet", "mesoSPIM", "!!!", "x" * 70],
            "/guides/422/tags": ["stellusz"],
            "/guides/430/tags": [],
        })

        def summary(guide_id: int) -> dict[str, Any]:
            full = self.documents[f"/guides/{guide_id}"]
            return {
                "dataType": "guide", "guideid": guide_id, "locale": "en", "revisionid": full["revisionid"],
                "guide_revisionid": full["guide_revisionid"], "modified_date": full["modified_date"], "prereq_modified_date": 0,
                "url": full["url"], "type": "how-to", "category": full["category"], "subject": "", "title": full["title"],
                "summary": full["summary"], "difficulty": full["difficulty"], "time_required_max": full["time_required_max"],
                "public": full["public"], "userid": full["author"]["userid"], "username": full["author"]["username"],
                "flags": [flag["flagid"] for flag in full["flags"]], "image": full["image"], "tags": False, "isArchived": False,
            }

        self.lists["/guides"] = [summary(guide_id) for guide_id in (15, 27, 422, 430)]

        # ------------------------------------------------------------ categories
        self.documents["/categories"] = {
            "Basics and IT": {"IT": {}},
            "Light Micrscopy": {"Basic Guides": {}, "Lightsheet microscopy": []},
        }
        self.documents["/wikis/CATEGORY?display=hierarchy"] = {
            "hierarchy": {"Root": {"Basics and IT": {"IT": None}, "Light Micrscopy": {"Basic Guides": None, "Lightsheet microscopy": None}}},
            "display_titles": {"Root": "Center for Microscopy and Image Analysis", "Basic Guides": "Confocal Microscopy", "Light Micrscopy": "Light Microscopy"},
        }
        self.lists["/categories/all"] = [
            "Root", "Basics and IT", "IT", "Light Micrscopy", "Basic Guides", "Lightsheet microscopy",
            "basics access and IT - hidden", "LS - hidden guides", "Image processing - hiden",
        ]

        def category(title: str, wiki_id: int, display: str | None = None, **fields: Any) -> None:
            self.documents[f"/categories/{title}"] = {
                "wikiid": wiki_id, "wiki_title": title, "display_title": display or title, "locale": "en", "topic_info": [],
                "image": None, "description": "", "flags": [], "parts": [], "tools": [], "ancestors": [], "children": [],
                "guides": [], "documents": [], "contents_rendered": "", **fields,
            }

        root = "Center for Microscopy and Image Analysis"
        category("Root", 1, root, children=["Basics and IT", "Light Microscopy"])
        category("Basics and IT", 10, ancestors=[root], children=["IT", "basics access and IT - hidden"])
        category("IT", 11, ancestors=["Basics and IT", root])
        category("Light Micrscopy", 20, "Light Microscopy", ancestors=[root], children=["Confocal Microscopy", "Lightsheet microscopy"])
        category(
            "Basic Guides", 23, "Confocal Microscopy", image=images[12099],
            description="In this category you find guides about how to start-up and operate the various light microscopes.",
            ancestors=["Light Microscopy", root], children=["Basic Guides", "Confocal - hidden guides"],
            guides=[self.lists["/guides"][2]],
        )
        category("Lightsheet microscopy", 24, ancestors=["Light Microscopy", root])
        category("basics access and IT - hidden", 40, ancestors=["Basics and IT", root])
        category("LS - hidden guides", 41, ancestors=["Lightsheet microscopy", "Light Microscopy", root])
        category("Confocal - hidden guides", 42, ancestors=["Confocal Microscopy", "Light Microscopy", root])

        # ------------------------------------------------------------ wikis
        def wiki(namespace: str, wiki_id: int, title: str, display: str, contents: str, **fields: Any) -> None:
            full = {
                "url": f"/Wiki/{title.replace(' ', '_')}", "fullUrl": f"https://{HOST}/Wiki/{title.replace(' ', '_')}",
                "wikiid": wiki_id, "langid": "en", "namespace": namespace, "title": title, "revisionid": 500 + wiki_id,
                "contents_raw": contents, "contents_json": {"type": "doc", "content": []}, "contents_rendered": "<p>…</p>",
                "can_edit": False, "editUrl": "", "flags": [], "image": None, "documents": [], "display_title": display,
                "description": "", "source_revisionid": None, "attachedQuiz": None, "release_title": "v2.0", **fields,
            }
            self.documents[f"/wikis/{namespace}/{title}"] = full
            self.documents[f"/wikis/{namespace}/{title}/tags"] = full.pop("_tags", [])
            if not full.pop("_listed", True):
                return
            self.lists.setdefault(f"/wikis/{namespace}", []).append({
                "dataType": "wiki", "wikiid": wiki_id, "revisionid": full["revisionid"], "title": title, "display_title": display,
                "namespace": namespace, "summary": full["description"], "url": full["fullUrl"], "text": full["description"],
                "image": full["image"] or NO_IMAGE, "modified_date": 1626439287, "langid": "en",
                "permissions": {"canEdit": False},
            })

        wiki("CATEGORY", 1, "Root", root, "Welcome. Start with [[Category:Basic Guides|confocal microscopy]] or the [[Strategy to Run a Full Multiplex SeqIF Without Prior Optimization]].")
        wiki("CATEGORY", 20, "Light Micrscopy", "Light Microscopy", "")
        wiki(
            "CATEGORY", 23, "Basic Guides", "Confocal Microscopy",
            "== Leica Stellaris 5 inverse (USZ) ==\n\n[guidelist|tags=StellUSZ|type=howto]\n\n"
            "== Lightsheet 🔬 ==\n\n[guidelist|tag=Lightsheet|title=All lightsheet guides]\n",
            image=images[12099], description="Guides for the confocal microscopes.", _tags=["overview"],
        )
        wiki(
            "WIKI", 108, "Strategy to Run a Full Multiplex SeqIF Without Prior Optimization", "Strategy to Run a Full Multiplex SeqIF",
            "== Overview ==\n\n"
            "Run the '''full''' panel ''once''. See [guide|27|the start-up guide], [https://zmb.dozuki.com/Guide/x/15|how to get there] "
            "and [https://example.org/protocol|the protocol].\n\n"
            "=== Steps ===\n\n* Prepare\n** Buffers\n* Run\n\n"
            "{table\n|format=30%l:70%l\n|! Marker\n|! Dilution\n|--\n| CD3\n| 1:100\n|--\n| CD8\n| 1:200\n}\n\n"
            "[image|900|caption=The panel layout]\n\n[quiz|3]\n\n[[A page that was never written]]\n",
            description="COMET", author=author(12, "Ada Example"),
        )
        # A holding category's page: it exists, but the wiki listing does not return it (as on the live site).
        wiki("CATEGORY", 41, "LS - hidden guides", "LS - hidden guides", "Internal list.\n\n[guidelist|tags=mesoSPIM]\n", _listed=False)
        wiki("INFO", 5, "Answers FAQ", "Answers FAQ", "== Vendor boilerplate ==\n\nNot the facility's text.")

        # ------------------------------------------------------------ users
        self.documents["/users/12"] = {
            "userid": 12, "username": "Ada Example", "unique_username": "aexample", "login": "ada.example@zmb.example",
            "image": None, "teams": [1, 3], "reputation": 3830, "join_date": 1554793315, "privileges": ["Admin"], "langid": "en",
        }
        self.documents["/users/22"] = {
            "userid": 22, "username": "New Author", "unique_username": None, "login": "New.Author@zmb.example",
            "image": None, "teams": [1], "reputation": 1194, "join_date": 1556515438, "privileges": [], "langid": "en",
        }
        self.documents["/users/26"] = {"userid": 26, "username": "z mbstaff", "unique_username": None, "image": None, "teams": [1]}

    # ------------------------------------------------------------ serving

    def fail(self, key: str, *responses: httpx.Response | Exception) -> None:
        """Answer the next requests for ``key`` (an API path or a file URL) with these instead."""
        self.failures.setdefault(key, []).extend(responses)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def paths(self, method: str = "GET") -> list[str]:
        return [request.url.path.removeprefix(API) for request in self.requests if request.method == method and request.url.host == HOST]

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if request.url.host != HOST:
            key = url.split("?")[0]
            queued = self.failures.get(key)
            if queued:
                planned = queued.pop(0)
                if isinstance(planned, Exception):
                    raise planned
                return planned
            if key not in self.files:
                return httpx.Response(404)
            payload, content_type = self.files[key]
            return httpx.Response(200, content=payload, headers={"Content-Type": content_type})

        path = request.url.path.removeprefix(API)
        query = {name: values[0] for name, values in parse_qs(request.url.query.decode()).items()}
        queued = self.failures.get(path)
        if queued:
            planned = queued.pop(0)
            if isinstance(planned, Exception):
                raise planned
            return planned

        authorization = request.headers.get("Authorization")
        if authorization is not None and authorization != f"api {GOOD_TOKEN}":
            return httpx.Response(401, json={"message": "Invalid token"})
        cookie = request.headers.get("Cookie")
        if cookie is not None and cookie != SESSION_COOKIE:
            return httpx.Response(401, json={"message": "Session expired"})
        signed_in = authorization is not None or cookie is not None

        if request.method == "POST" and path == "/user/token":
            body = json.loads(request.content)
            if self.app_id_required and request.headers.get("X-App-Id") != self.app_id_required:
                return httpx.Response(403, json={"message": "App id required"})
            if body == {"email": EMAIL, "password": PASSWORD}:
                return httpx.Response(201, json={"userid": 1, "username": "Exporter", "authToken": GOOD_TOKEN})
            return httpx.Response(401, json={"message": "Invalid login"})

        if path == "/wikis/CATEGORY" and query.get("display") == "hierarchy":
            return httpx.Response(200, json=self.documents["/wikis/CATEGORY?display=hierarchy"])

        if path in self.lists:
            if path == "/guides" and query.get("includePrivate") == "true" and not signed_in:
                return httpx.Response(401, json={"message": "Authentication required"})
            limit, offset = int(query.get("limit", 20)), int(query.get("offset", 0))
            if limit > self.max_limit.get(path, 200):
                return httpx.Response(400, json={"message": "limit out of range"})
            window = self.lists[path][offset : offset + limit]
            if path == "/guides" and not (signed_in and query.get("includePrivate") == "true"):
                window = [entry for entry in window if entry["guideid"] not in self.private_guides]
            return httpx.Response(200, json=window)

        if path.startswith("/guides/"):
            guide_id = path.split("/")[2]
            if guide_id.isdigit() and int(guide_id) in self.private_guides and not signed_in:
                return httpx.Response(403, json={"message": "Forbidden"})
        if path in self.documents:
            return httpx.Response(200, json=self.documents[path])
        return httpx.Response(404, json={"message": "Not found"})


def write_archive(directory: Path, site: FakeSite | None = None, token: str | None = GOOD_TOKEN) -> FakeSite:
    """Export the fake site into ``directory`` with the real exporter."""
    from app.importer.archive import Archive
    from app.importer.client import DozukiClient
    from app.importer.exporter import Exporter

    site = site or FakeSite()
    with DozukiClient(HOST, token=token, transport=site.transport(), delay=0, sleep=lambda seconds: None) as client:
        Exporter(client, Archive(directory), log=lambda message: None).run()
    return site


if __name__ == "__main__":
    target = Path(sys.argv[1])
    write_archive(target)
    print(f"Fixture archive written to {target}")
