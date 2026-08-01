"""Rendering the published corpus to plain files.

The database is the system of record: authoring, drafts, per-role visibility,
search, tags, publish history and concurrency are all things a folder of HTML
cannot do, and the whole point of this project is that a scientist edits a step
at the bench and it is live, with no build and no repository.

But a folder of HTML has one property the application never will — it outlives
the application. Nothing to run, nothing to upgrade, no Python, no database
engine, no certificate. Open the file. That is worth having for three specific
situations, and this exists for those and nothing else:

**The archive.** A frozen copy of the procedures as they read on a given day,
which is what an audit or an incident review actually needs.

**Offline.** A microscope room in a basement with no network, or a laptop taken
to another building. Copy the folder onto a stick and every guide still works,
pictures and all.

**The server being down.** A read-only mirror that nginx can serve on its own.

One rule governs everything here, and it is not stylistic: **only published
content is rendered, and only the media that published content shows.** The
output has no login in front of it, so a draft that leaks into it is a
half-written procedure published to whoever finds the folder — and unlike the
application, where visibility is a ``WHERE`` clause somebody can re-check, a
file once written is gone.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import html
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from . import images
from .models import Category, Guide, Media, Page
from .schemas import guide_out, page_out
from .settings import Settings

PUBLISHED = "published"

DIFFICULTY_LABELS = {
    "very_easy": "Very easy",
    "easy": "Easy",
    "moderate": "Moderate",
    "difficult": "Difficult",
    "very_difficult": "Very difficult",
}

FLAG_LABELS = {"note": "Note", "caution": "Caution", "reminder": "Reminder"}


@dataclass
class SiteReport:
    guides: int = 0
    pages: int = 0
    categories: int = 0
    media: int = 0
    skipped_drafts: int = 0

    def to_text(self) -> str:
        return "\n".join(
            [
                "Reticle static snapshot",
                "=======================",
                "",
                f"  categories  {self.categories}",
                f"  guides      {self.guides}",
                f"  wiki pages  {self.pages}",
                f"  media       {self.media}",
                "",
                f"Left out because they are not published: {self.skipped_drafts}",
                "",
            ]
        )


def esc(value: object) -> str:
    """Everything that reaches the output goes through this.

    Guide text is written by staff and read by everyone, and this renderer
    concatenates strings — so the escaping is not a precaution against a hostile
    author, it is what stops a bullet containing ``<`` from silently breaking the
    page it is on.
    """
    return html.escape(str(value if value is not None else ""), quote=True)


def duration(minimum: int | None, maximum: int | None) -> str:
    def render(total: int) -> str:
        hours, minutes = divmod(total, 60)
        if hours and minutes:
            return f"{hours} h {minutes} min"
        if hours:
            return f"{hours} h"
        return f"{minutes} min"

    if minimum is None and maximum is None:
        return "Not specified"
    if minimum is not None and maximum is not None and minimum != maximum:
        return f"{render(minimum)} – {render(maximum)}"
    return render(minimum if minimum is not None else maximum)  # type: ignore[arg-type]


def annotation_overlay(annotations: list[dict]) -> str:
    """The shapes, drawn over the picture as SVG.

    Redrawn rather than burned into the image for the same reason the
    application keeps them as data: the coordinates are fractions, so one
    overlay is correct at every size the page is viewed or printed at. The
    colours are the bullet palette, because a red shape and the red bullet
    beside it are one instruction and separating them here would break the guide
    in the copy people keep.
    """
    if not annotations:
        return ""

    shapes = []
    for shape in annotations:
        colour = f"var(--bullet-{shape['color'].replace('_', '-')})"
        x, y = shape["x"] * 100, shape["y"] * 100
        width, height = shape["width"] * 100, shape["height"] * 100

        if shape["shape"] == "arrow":
            shapes.append(
                f'<line x1="{x:.3f}" y1="{y:.3f}" x2="{x + width:.3f}" y2="{y + height:.3f}" '
                f'stroke="{colour}" stroke-width="1.2" marker-end="url(#arrowhead)" />'
            )
        elif shape["shape"] == "ellipse":
            shapes.append(
                f'<ellipse cx="{x + width / 2:.3f}" cy="{y + height / 2:.3f}" '
                f'rx="{abs(width) / 2:.3f}" ry="{abs(height) / 2:.3f}" '
                f'fill="none" stroke="{colour}" stroke-width="1.2" />'
            )
        else:
            shapes.append(
                f'<rect x="{min(x, x + width):.3f}" y="{min(y, y + height):.3f}" '
                f'width="{abs(width):.3f}" height="{abs(height):.3f}" '
                f'fill="none" stroke="{colour}" stroke-width="1.2" />'
            )

    return (
        '<svg class="overlay" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">'
        '<defs><marker id="arrowhead" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" '
        'markerHeight="5" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="currentColor"/>'
        "</marker></defs>" + "".join(shapes) + "</svg>"
    )


def _page_shell(title: str, organisation: str, body: str, depth: int = 1) -> str:
    root = "../" * depth
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} — {esc(organisation)}</title>
<link rel="stylesheet" href="{root}assets/site.css">
</head>
<body>
<header class="site-header">
  <a class="site-brand" href="{root}index.html">{esc(organisation)}</a>
  <span class="site-note">Offline copy · {datetime.now(timezone.utc).strftime('%Y-%m-%d')}</span>
</header>
<main>
{body}
</main>
</body>
</html>
"""


def render_guide(guide: Guide, organisation: str, filenames: dict[str, str]) -> str:
    document = guide_out(guide).model_dump(mode="json", by_alias=True)

    parts = [f'<article class="guide"><h1>{esc(document["title"])}</h1>']
    if document["summary"]:
        parts.append(f'<p class="lead">{esc(document["summary"])}</p>')

    parts.append(
        '<dl class="meta">'
        f'<div><dt>Difficulty</dt><dd>{esc(DIFFICULTY_LABELS.get(document["difficulty"], document["difficulty"]))}</dd></div>'
        f'<div><dt>Time required</dt><dd>{esc(duration(document["timeRequiredMinMinutes"], document["timeRequiredMaxMinutes"]))}</dd></div>'
        f'<div><dt>Steps</dt><dd>{len(document["steps"])}</dd></div>'
        f'<div><dt>Author</dt><dd>{esc(document["author"]["displayName"])}</dd></div>'
        f'<div><dt>Version</dt><dd>{document["version"]}</dd></div>'
        "</dl>"
    )

    if document["tags"]:
        parts.append(
            '<p class="tags">' + " ".join(f'<span class="tag">{esc(tag)}</span>' for tag in document["tags"]) + "</p>"
        )

    if document["introduction"]:
        parts.append(f'<p class="intro">{esc(document["introduction"])}</p>')

    for number, step in enumerate(document["steps"], start=1):
        parts.append('<section class="step">')
        parts.append(f'<h2><span class="step-number">{number}</span>{esc(step["title"] or f"Step {number}")}</h2>')

        if step["media"] or step.get("video"):
            parts.append('<div class="step-media">')
            for item in step["media"]:
                parts.append(
                    '<figure class="shot">'
                    f'<img src="../media/{esc(filenames.get(item["id"], item["id"]))}" alt="{esc(item["alt"])}">'
                    f'{annotation_overlay(item["annotations"])}'
                    "</figure>"
                )
            if step.get("video"):
                parts.append(
                    '<figure class="shot"><video controls preload="metadata" '
                    f'src="../media/{esc(filenames.get(step["video"]["id"], step["video"]["id"]))}"></video></figure>'
                )
            parts.append("</div>")

        bullets = [b for b in step["bullets"] if b["text"].strip()]
        if bullets:
            parts.append('<ul class="bullets">')
            for bullet in bullets:
                classes = f'bullet bullet--color-{bullet["color"]} bullet--level-{bullet["level"]}'
                if bullet["icon"]:
                    classes += " bullet--flagged"
                flag = (
                    f'<span class="flag">{esc(FLAG_LABELS[bullet["icon"]])}</span>'
                    if bullet["icon"]
                    else ""
                )
                parts.append(f'<li class="{classes}">{flag}{esc(bullet["text"])}</li>')
            parts.append("</ul>")

        parts.append("</section>")

    if document["conclusion"]:
        parts.append(f'<section class="step"><h2>Conclusion</h2><p>{esc(document["conclusion"])}</p></section>')

    parts.append("</article>")
    return _page_shell(document["title"], organisation, "\n".join(parts))


def render_page(page: Page, organisation: str) -> str:
    document = page_out(page).model_dump(mode="json", by_alias=True)
    body = [f'<article class="guide"><h1>{esc(document["title"])}</h1>']
    if document["summary"]:
        body.append(f'<p class="lead">{esc(document["summary"])}</p>')
    # The body is Markdown, rendered as pre-wrapped text rather than converted:
    # a half-implemented Markdown renderer here would differ from the
    # application's and show people something other than what they wrote.
    body.append(f'<div class="wiki-body">{esc(document["body"])}</div>')
    body.append("</article>")
    return _page_shell(document["title"], organisation, "\n".join(body))


def render_index(
    categories: list[Category], guides: list[Guide], pages: list[Page], organisation: str
) -> str:
    body = [f"<h1>{esc(organisation)}</h1>", '<p class="lead">Standard operating procedures.</p>']

    for category in categories:
        in_category = [g for g in guides if g.category_id == category.id]
        category_pages = [p for p in pages if p.category_id == category.id]
        if not in_category and not category_pages:
            continue
        body.append(f'<section class="section"><h2>{esc(category.name)}</h2><ul class="index">')
        for page in category_pages:
            body.append(f'<li><a href="w/{esc(page.slug)}.html">{esc(page.title)}</a> <span class="kind">wiki</span></li>')
        for guide in in_category:
            body.append(f'<li><a href="g/{esc(guide.slug)}.html">{esc(guide.title)}</a></li>')
        body.append("</ul></section>")

    return _page_shell("Guides", organisation, "\n".join(body), depth=0)


def publish(db: DbSession, settings: Settings, destination: Path) -> SiteReport:
    """Write the published corpus out as a browsable folder."""
    report = SiteReport()

    destination.mkdir(parents=True, exist_ok=True)
    for folder in ("g", "w", "media", "assets"):
        (destination / folder).mkdir(exist_ok=True)

    organisation = settings.organisation_short_name

    everything = db.scalars(select(Guide)).all()
    guides = [guide for guide in everything if guide.status == PUBLISHED]
    report.skipped_drafts += len(everything) - len(guides)

    all_pages = db.scalars(select(Page)).all()
    pages = [page for page in all_pages if page.status == PUBLISHED]
    report.skipped_drafts += len(all_pages) - len(pages)

    categories = db.scalars(select(Category).order_by(Category.order_index)).all()

    # Work out what published content displays, and copy only that. The folder
    # has no login in front of it, so a picture copied here because it merely
    # exists is a picture from an unpublished guide handed to whoever opens the
    # directory — and a file once written cannot be un-published.
    shown: set[str] = set()
    for guide in guides:
        for step in guide.steps:
            shown.update(link.media_id for link in step.media_links)
            if step.video_media_id:
                shown.add(step.video_media_id)
    for page in pages:
        if page.hero_media_id:
            shown.add(page.hero_media_id)

    filenames: dict[str, str] = {}
    for media_id in sorted(shown):
        media = db.get(Media, media_id)
        if media is None:
            continue
        source = images.resolve_file(settings.media_root, media.storage_path)
        filename = f"{media.id}{source.suffix}"
        shutil.copyfile(source, destination / "media" / filename)
        filenames[media.id] = filename
        report.media += 1

    for guide in guides:
        (destination / "g" / f"{guide.slug}.html").write_text(
            render_guide(guide, organisation, filenames), encoding="utf-8"
        )
        report.guides += 1

    for page in pages:
        (destination / "w" / f"{page.slug}.html").write_text(
            render_page(page, organisation), encoding="utf-8"
        )
        report.pages += 1

    report.categories = sum(
        1
        for category in categories
        if any(g.category_id == category.id for g in guides)
        or any(p.category_id == category.id for p in pages)
    )

    (destination / "index.html").write_text(
        render_index(list(categories), guides, pages, organisation), encoding="utf-8"
    )
    (destination / "assets" / "site.css").write_text(SITE_CSS, encoding="utf-8")

    return report


SITE_CSS = """\
/* The snapshot's own stylesheet: one file, no build, no fonts to fetch. */
:root {
  --ink: #10151c; --muted: #5b6675; --line: #dde3ec; --surface: #fff;
  --bullet-black: #1f2328; --bullet-red: #d1242f; --bullet-orange: #bc4c00;
  --bullet-yellow: #9a6700; --bullet-green: #1a7f37; --bullet-light-blue: #0e7490;
  --bullet-blue: #0969da; --bullet-violet: #8250df;
}
* { box-sizing: border-box; }
body { margin: 0; font: 16px/1.6 system-ui, sans-serif; color: var(--ink); background: var(--surface); }
main { max-width: 62rem; margin: 0 auto; padding: 1.5rem 1.25rem 4rem; }
.site-header { display: flex; justify-content: space-between; align-items: center;
  padding: 0.75rem 1.25rem; background: #0a2f6f; color: #fff; }
.site-brand { color: #fff; font-weight: 700; text-decoration: none; }
.site-note { font-size: 0.8rem; opacity: 0.75; }
h1 { font-size: 1.75rem; margin: 1.5rem 0 0.5rem; }
.lead { color: var(--muted); margin-top: 0; }
.meta { display: flex; flex-wrap: wrap; gap: 1.5rem; padding: 0.75rem 0; margin: 1rem 0;
  border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
.meta div { margin: 0; }
.meta dt { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); }
.meta dd { margin: 0.15rem 0 0; font-weight: 600; }
.tags { display: flex; gap: 0.4rem; flex-wrap: wrap; padding: 0; }
.tag { font-size: 0.8rem; padding: 0.1rem 0.5rem; border-radius: 999px; background: #eef3fd; color: #0a2f6f; }
.step { padding: 1.25rem 0; border-top: 1px solid var(--line); }
.step h2 { display: flex; align-items: center; gap: 0.6rem; font-size: 1.15rem; }
.step-number { display: inline-flex; align-items: center; justify-content: center;
  width: 1.9rem; height: 1.9rem; border-radius: 999px; background: #eef3fd; color: #0a2f6f; font-size: 0.9rem; }
.step-media { display: flex; flex-wrap: wrap; gap: 0.75rem; margin-bottom: 0.75rem; }
.shot { position: relative; flex: 1 1 260px; margin: 0; }
.shot img, .shot video { display: block; width: 100%; height: auto; border: 1px solid var(--line); border-radius: 6px; }
.overlay { position: absolute; inset: 0; width: 100%; height: 100%; }
.bullets { list-style: none; padding: 0; margin: 0; }
.bullet { position: relative; padding-left: 1.1rem; margin: 0.4rem 0; }
.bullet::before { content: ""; position: absolute; left: 0; top: 0.6em; width: 7px; height: 7px;
  border-radius: 999px; background: currentColor; }
.bullet--level-1 { margin-left: 1.5rem; } .bullet--level-2 { margin-left: 3rem; }
.bullet--color-black { color: var(--bullet-black); } .bullet--color-red { color: var(--bullet-red); }
.bullet--color-orange { color: var(--bullet-orange); } .bullet--color-yellow { color: var(--bullet-yellow); }
.bullet--color-green { color: var(--bullet-green); } .bullet--color-light_blue { color: var(--bullet-light-blue); }
.bullet--color-blue { color: var(--bullet-blue); } .bullet--color-violet { color: var(--bullet-violet); }
.flag { font-size: 0.72rem; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase;
  margin-right: 0.4rem; }
.wiki-body { white-space: pre-wrap; }
.index { list-style: none; padding: 0; }
.index li { padding: 0.35rem 0; border-bottom: 1px solid var(--line); }
.index a { color: #0d3b8c; }
.kind { font-size: 0.75rem; color: var(--muted); }
@media print { .site-header { color: #000; background: none; } }
"""
