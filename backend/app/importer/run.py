"""The migration itself: fetch, map, write, reconcile.

Run it with::

    python -m app.importer.run --base-url https://zmb.dozuki.com --report migration.txt

Nothing here is clever. It walks the catalogue, maps each document with
``mapping``, writes it through the same models the application uses, downloads
every file it referenced, and counts both sides as it goes so that
``report`` can prove the two agree.

Three decisions are worth knowing:

**Files go through the same validation as an upload.** Images are re-decoded and
re-encoded by ``images.normalise``, which is what strips camera EXIF and what
guarantees that a migrated picture cannot be a decompression bomb aimed at the
server. A corrupt file fails its guide rather than the run.

**Public guides arrive published, private ones arrive as drafts.** The site's
own visibility is the only honest default: publishing something that was private
would be a disclosure, and importing everything as a draft would leave the
institute with an empty-looking library on the morning of the switch.

**Nothing is guessed.** Unrecognised values stop the run unless
``--allow-unmapped`` is passed, and even then they are all in the report.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .. import images, videos
from ..db import SessionLocal, init_db, utcnow
from ..models import (
    Annotation,
    Bullet,
    Category,
    Guide,
    GuideContributor,
    GuideRevision,
    GuideTag,
    ImportedRecord,
    Media,
    Page,
    PageContributor,
    PageRevision,
    Step,
    StepMedia,
    Tag,
    User,
    new_id,
)
from ..schemas import guide_document, page_document
from ..settings import Settings, get_settings
from ..slugs import unique_slug
from .client import DozukiClient, MigrationError
from .mapping import (
    MappedGuide,
    MappedImage,
    MappedPage,
    MappedVideo,
    map_guide,
    map_page,
)
from .report import GuideTally, MigrationReport

SOURCE_SYSTEM = "dozuki"

UNCATEGORISED = "Imported"
"""Where a guide whose category does not exist yet ends up.

Named rather than left blank so that anything the migration could not place is
visible in one list on the morning after, instead of being scattered.
"""


@dataclass
class Options:
    base_url: str
    token: str | None
    include_private: bool
    limit: int | None
    allow_unmapped: bool
    dry_run: bool
    skip_media: bool
    report_path: Path | None
    json_report_path: Path | None
    author_email: str


def count_source(payload: dict[str, Any], tally: GuideTally) -> None:
    """Count what the *payload* holds, not what the mapping made of it.

    This distinction is the whole value of the report. Counting the mapped
    structure would mean a bullet the mapping refused to understand had
    disappeared from both sides of the comparison at once, and the run would
    reconcile perfectly while quietly losing a safety warning. Counting the raw
    JSON makes the loss arithmetic.
    """
    steps = payload.get("steps") or []
    tally.source_steps = sum(1 for step in steps if isinstance(step, dict))

    for step in steps:
        if not isinstance(step, dict):
            continue
        lines = step.get("lines") or step.get("bullets") or []
        tally.source_bullets += sum(
            1
            for line in lines
            if isinstance(line, dict)
            and str(line.get("text_raw") or line.get("text") or "").strip()
        )

        media = step.get("media")
        entries = media if isinstance(media, list) else ([media] if isinstance(media, dict) else [])
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            kind = str(entry.get("type") or entry.get("mediatype") or "image").strip().lower()
            data = entry.get("data") if isinstance(entry.get("data"), dict) else entry
            if kind in ("video", "movie"):
                tally.source_videos += 1
                continue
            if kind not in ("image", "photo", ""):
                continue
            tally.source_images += 1
            markup = data.get("markup") or data.get("annotations")
            if isinstance(markup, dict):
                markup = markup.get("shapes") or markup.get("annotations") or markup.get("markup")
            if isinstance(markup, list):
                tally.source_annotations += sum(1 for shape in markup if isinstance(shape, dict))


class Importer:
    def __init__(
        self,
        db: DbSession,
        client: DozukiClient,
        options: Options,
        settings: Settings,
    ) -> None:
        self.db = db
        self.client = client
        self.options = options
        self.settings = settings
        self.report = MigrationReport()
        self._author = self._resolve_author()
        self._categories: dict[str, Category] = {}
        self._tags: dict[str, Tag] = {}

    # -- people and taxonomy ---------------------------------------------

    def _resolve_author(self) -> User:
        """Everything imported is attributed to one real account.

        Inventing an account per original author would create logins nobody can
        use and cannot be deactivated by anyone who left; attributing the import
        to the person who ran it is both true and auditable. The original
        authorship is preserved in the source record.
        """
        email = self.options.author_email.strip().lower()
        user = self.db.scalars(select(User).where(User.email == email)).one_or_none()
        if user is None:
            raise MigrationError(
                f"No account for {email}. Create it first, or pass --author-email for one that exists."
            )
        return user

    def _category(self, name: str) -> Category:
        wanted = (name or "").strip() or UNCATEGORISED
        if wanted in self._categories:
            return self._categories[wanted]

        category = self.db.scalars(select(Category).where(Category.name == wanted)).one_or_none()
        if category is None:
            category = Category(
                slug=unique_slug(wanted, self._category_slug_taken, fallback="category"),
                name=wanted,
                description="",
                parent_id=None,
                order_index=self._next_category_order(),
                # Imported sections start visible; the ones that are really
                # holding pens are marked hidden afterwards, from the report,
                # rather than guessed at from a name.
                is_hidden=False,
            )
            self.db.add(category)
            self.db.flush()
            self.report.categories_created += 1
        self._categories[wanted] = category
        return category

    def _category_slug_taken(self, slug: str) -> bool:
        return self.db.scalars(select(Category).where(Category.slug == slug)).first() is not None

    def _next_category_order(self) -> int:
        existing = self.db.scalars(select(Category)).all()
        return max((item.order_index for item in existing), default=-1) + 1

    def _tag(self, slug: str) -> Tag:
        if slug in self._tags:
            return self._tags[slug]
        tag = self.db.scalars(select(Tag).where(Tag.slug == slug)).one_or_none()
        if tag is None:
            tag = Tag(slug=slug, name=slug.replace("-", " "))
            self.db.add(tag)
            self.db.flush()
            self.report.tags_created += 1
        self._tags[slug] = tag
        return tag

    # -- source records ---------------------------------------------------

    def _existing(self, kind: str, source_id: str) -> ImportedRecord | None:
        return self.db.scalars(
            select(ImportedRecord).where(
                ImportedRecord.source_system == SOURCE_SYSTEM,
                ImportedRecord.source_kind == kind,
                ImportedRecord.source_id == source_id,
            )
        ).one_or_none()

    def _remember(self, kind: str, source_id: str, local_id: str, url: str, digest: str) -> None:
        record = self._existing(kind, source_id)
        if record is None:
            record = ImportedRecord(
                source_system=SOURCE_SYSTEM,
                source_kind=kind,
                source_id=source_id,
                local_id=local_id,
                source_url=url,
                content_digest=digest,
            )
            self.db.add(record)
        else:
            record.local_id = local_id
            record.source_url = url
            record.content_digest = digest
            record.imported_at = utcnow()

    # -- media ------------------------------------------------------------

    def _import_image(self, spec: MappedImage) -> tuple[Media, int]:
        """Fetch a picture, validate it exactly as an upload is validated."""
        existing = self._existing("image", spec.source_id)
        if existing is not None:
            media = self.db.get(Media, existing.local_id)
            if media is not None:
                return media, self._sync_annotations(media, spec)

        fetched = self.client.download(spec.url)
        normalised = images.normalise(
            fetched.payload, self.settings.max_image_dimension, self.settings.max_image_pixels
        )

        media_id = new_id()
        storage_path = images.relative_storage_path(media_id, normalised.extension)
        images.write_file(self.settings.media_root, storage_path, normalised.payload)

        media = Media(
            id=media_id,
            storage_path=storage_path,
            content_type=normalised.content_type,
            kind="image",
            byte_size=len(normalised.payload),
            width=normalised.width,
            height=normalised.height,
            alt=spec.alt,
            original_filename="",
            uploaded_by_id=self._author.id,
        )
        self.db.add(media)
        self.db.flush()
        written = self._sync_annotations(media, spec)
        self._remember(
            "image",
            spec.source_id,
            media.id,
            spec.url,
            hashlib.sha256(fetched.payload).hexdigest(),
        )
        return media, written

    def _sync_annotations(self, media: Media, spec: MappedImage) -> int:
        """Replace the image's shapes, and report how many were written.

        The count is returned rather than read back off ``media.annotations``:
        the collection was loaded before the inserts and would still be the
        empty list it was, which would let the reconciliation report claim a
        guide balanced while every annotation on it had been lost.
        """
        for annotation in list(media.annotations):
            self.db.delete(annotation)
        self.db.flush()
        for index, shape in enumerate(spec.annotations):
            self.db.add(
                Annotation(
                    media_id=media.id,
                    order_index=index,
                    shape=shape.shape,
                    color=shape.color,
                    x=shape.x,
                    y=shape.y,
                    width=shape.width,
                    height=shape.height,
                )
            )
        self.db.flush()
        self.db.refresh(media)
        return len(spec.annotations)

    def _import_video(self, spec: MappedVideo) -> Media:
        existing = self._existing("video", spec.source_id)
        if existing is not None:
            media = self.db.get(Media, existing.local_id)
            if media is not None:
                return media

        fetched = self.client.download(spec.url)
        if len(fetched.payload) > self.settings.max_video_bytes:
            raise MigrationError(
                f"{spec.url} is {len(fetched.payload) // (1024 * 1024)} MB, above the configured cap."
            )
        identified = videos.identify(fetched.payload)

        media_id = new_id()
        storage_path = images.relative_storage_path(media_id, identified.extension)
        images.write_file(self.settings.media_root, storage_path, fetched.payload)

        media = Media(
            id=media_id,
            storage_path=storage_path,
            content_type=identified.content_type,
            kind="video",
            byte_size=len(fetched.payload),
            alt=spec.alt,
            original_filename="",
            uploaded_by_id=self._author.id,
        )
        self.db.add(media)
        self.db.flush()
        self._remember(
            "video", spec.source_id, media.id, spec.url, hashlib.sha256(fetched.payload).hexdigest()
        )
        return media

    # -- guides -----------------------------------------------------------

    def import_guides(self) -> None:
        seen = 0
        for summary in self.client.iter_guides(include_private=self.options.include_private):
            if self.options.limit is not None and seen >= self.options.limit:
                break
            seen += 1
            guide_id = summary.get("guideid") or summary.get("id")
            if guide_id is None:
                self.report.skipped.append(f"A listing entry had no identifier: {summary!r:.120}")
                continue
            try:
                payload = self.client.get_guide(guide_id)
            except MigrationError as error:
                self.report.guides.append(
                    GuideTally(
                        source_id=str(guide_id),
                        title=str(summary.get("title") or ""),
                        failures=[str(error)],
                    )
                )
                continue
            self._import_one_guide(payload)

    def _import_one_guide(self, payload: dict[str, Any]) -> None:
        mapped, problems = map_guide(payload)
        self.report.unmapped.extend(problems)

        tally = GuideTally(source_id=mapped.source_id, title=mapped.title)
        count_source(payload, tally)
        self.report.guides.append(tally)

        if self.options.dry_run:
            # A rehearsal reports what a real run *would* write, which is the
            # mapped document rather than the payload — so a value the mapping
            # could not read shows up as a shortfall here too.
            tally.imported_steps = len(mapped.steps)
            tally.imported_bullets = sum(len(step.bullets) for step in mapped.steps)
            tally.imported_images = sum(len(step.images) for step in mapped.steps)
            tally.imported_annotations = sum(
                len(image.annotations) for step in mapped.steps for image in step.images
            )
            tally.imported_videos = sum(1 for step in mapped.steps if step.video is not None)
            return

        try:
            guide = self._write_guide(mapped, tally)
        except MigrationError as error:
            tally.failures.append(str(error))
            self.db.rollback()
            return
        except Exception as error:
            tally.failures.append(f"{type(error).__name__}: {error}")
            self.db.rollback()
            return

        tally.slug = guide.slug
        self.db.commit()

    def _write_guide(self, mapped: MappedGuide, tally: GuideTally) -> Guide:
        existing = self._existing("guide", mapped.source_id)
        guide = self.db.get(Guide, existing.local_id) if existing is not None else None

        category = self._category(mapped.category_name)
        now = utcnow()

        if guide is None:
            guide = Guide(
                slug=unique_slug(mapped.title, self._guide_slug_taken, fallback="guide"),
                title=mapped.title,
                category_id=category.id,
                author_id=self._author.id,
                last_edited_by_id=self._author.id,
            )
            self.db.add(guide)
            self.db.flush()

        guide.title = mapped.title
        guide.summary = mapped.summary
        guide.category_id = category.id
        guide.difficulty = mapped.difficulty
        guide.time_required_min_minutes = mapped.time_min_minutes
        guide.time_required_max_minutes = mapped.time_max_minutes
        guide.introduction = mapped.introduction
        guide.conclusion = mapped.conclusion
        guide.last_edited_by_id = self._author.id
        guide.updated_at = now

        for link in list(guide.tag_links):
            self.db.delete(link)
        self.db.flush()
        for index, slug in enumerate(mapped.tags):
            self.db.add(GuideTag(guide_id=guide.id, tag_id=self._tag(slug).id, order_index=index))

        for step in list(guide.steps):
            self.db.delete(step)
        self.db.flush()

        for index, mapped_step in enumerate(mapped.steps):
            step = Step(guide_id=guide.id, order_index=index, title=mapped_step.title)
            self.db.add(step)
            self.db.flush()
            tally.imported_steps += 1

            for position, bullet in enumerate(mapped_step.bullets):
                self.db.add(
                    Bullet(
                        step_id=step.id,
                        order_index=position,
                        text=bullet.text,
                        color=bullet.color,
                        icon=bullet.icon,
                        level=bullet.level,
                    )
                )
                tally.imported_bullets += 1

            if self.options.skip_media:
                continue

            for position, image in enumerate(
                mapped_step.images[: self.settings.max_media_per_step]
            ):
                media, annotation_count = self._import_image(image)
                self.db.add(StepMedia(step_id=step.id, media_id=media.id, order_index=position))
                tally.imported_images += 1
                tally.imported_annotations += annotation_count

            if len(mapped_step.images) > self.settings.max_media_per_step:
                raise MigrationError(
                    f"Step {index + 1} has {len(mapped_step.images)} images, above the "
                    f"configured maximum of {self.settings.max_media_per_step}."
                )

            if mapped_step.video is not None:
                step.video_media_id = self._import_video(mapped_step.video).id
                tally.imported_videos += 1

        if not any(link.user_id == self._author.id for link in guide.contributor_links):
            self.db.add(
                GuideContributor(
                    guide_id=guide.id,
                    user_id=self._author.id,
                    first_edited_at=now,
                    last_edited_at=now,
                )
            )

        self.db.flush()

        if mapped.is_public:
            guide.status = "published"
            guide.published_at = guide.published_at or now
            if guide.version == 0:
                guide.version = 1
                self.db.flush()
                self.db.refresh(guide)
                self.db.add(
                    GuideRevision(
                        guide_id=guide.id,
                        version=guide.version,
                        published_at=now,
                        published_by_id=self._author.id,
                        document=guide_document(guide),
                    )
                )
        else:
            guide.status = "draft"

        self.db.flush()
        self._remember("guide", mapped.source_id, guide.id, self._guide_url(mapped.source_id), "")
        return guide

    def _guide_url(self, source_id: str) -> str:
        return f"{self.client.base_url}/Guide/{source_id}"

    def _guide_slug_taken(self, slug: str) -> bool:
        return self.db.scalars(select(Guide).where(Guide.slug == slug)).first() is not None

    # -- wiki pages -------------------------------------------------------

    def import_pages(self, namespaces: tuple[str, ...] = ("CATEGORY", "WIKI")) -> None:
        for namespace in namespaces:
            try:
                listing = list(self.client.iter_wikis(namespace))
            except MigrationError as error:
                self.report.skipped.append(f"Wiki namespace {namespace}: {error}")
                continue

            for entry in listing:
                self.report.pages_seen += 1
                title = entry.get("title")
                if not isinstance(title, str):
                    self.report.skipped.append(f"A {namespace} entry had no title.")
                    continue
                try:
                    payload = self.client.get_wiki(namespace, title)
                except MigrationError as error:
                    self.report.skipped.append(f"{namespace}/{title}: {error}")
                    continue

                mapped, problems = map_page(payload)
                self.report.unmapped.extend(problems)
                if self.options.dry_run:
                    self.report.pages_imported += 1
                    continue
                try:
                    self._write_page(mapped)
                    self.db.commit()
                    self.report.pages_imported += 1
                except Exception as error:
                    self.db.rollback()
                    self.report.skipped.append(
                        f"{namespace}/{title}: {type(error).__name__}: {error}"
                    )

    def _write_page(self, mapped: MappedPage) -> Page:
        existing = self._existing("page", mapped.source_id)
        page = self.db.get(Page, existing.local_id) if existing is not None else None

        category = self._category(mapped.category_name) if mapped.category_name else None
        now = utcnow()

        is_landing = mapped.is_landing and category is not None
        if is_landing and category is not None:
            clash = self.db.scalars(
                select(Page).where(Page.category_id == category.id, Page.is_landing.is_(True))
            ).first()
            if clash is not None and (page is None or clash.id != page.id):
                # The category already has a landing page from an earlier run or
                # from the seed. Import this one as an ordinary article rather
                # than losing it or overwriting the one already there.
                is_landing = False
                self.report.skipped.append(
                    f"{mapped.title} imported as an article: its category already has a landing page."
                )

        if page is None:
            page = Page(
                slug=unique_slug(mapped.title, self._page_slug_taken, fallback="page"),
                title=mapped.title,
                author_id=self._author.id,
                last_edited_by_id=self._author.id,
            )
            self.db.add(page)
            self.db.flush()

        page.title = mapped.title
        page.summary = mapped.summary
        page.body = mapped.body
        page.category_id = category.id if category is not None else None
        page.is_landing = is_landing
        page.last_edited_by_id = self._author.id
        page.updated_at = now
        page.status = "published"
        page.published_at = page.published_at or now

        if not any(link.user_id == self._author.id for link in page.contributor_links):
            self.db.add(
                PageContributor(
                    page_id=page.id,
                    user_id=self._author.id,
                    first_edited_at=now,
                    last_edited_at=now,
                )
            )

        if page.version == 0:
            page.version = 1
            self.db.flush()
            self.db.refresh(page)
            self.db.add(
                PageRevision(
                    page_id=page.id,
                    version=page.version,
                    published_at=now,
                    published_by_id=self._author.id,
                    document=page_document(page),
                )
            )

        self.db.flush()
        self._remember("page", mapped.source_id, page.id, "", "")
        return page

    def _page_slug_taken(self, slug: str) -> bool:
        return self.db.scalars(select(Page).where(Page.slug == slug)).first() is not None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.importer.run",
        description="Migrate a Dozuki site's guides and wiki pages into Reticle.",
    )
    parser.add_argument("--base-url", required=True, help="e.g. https://zmb.dozuki.com")
    parser.add_argument(
        "--token",
        default=None,
        help="API token. Only needed for private content; the public catalogue needs none.",
    )
    parser.add_argument(
        "--include-private",
        action="store_true",
        help="Ask for private guides too. Requires a token with administrator rights.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Stop after this many guides.")
    parser.add_argument(
        "--author-email",
        default="admin@zmb.uzh.ch",
        help="The existing Reticle account the imported content is attributed to.",
    )
    parser.add_argument(
        "--allow-unmapped",
        action="store_true",
        help="Finish even if the site uses values this importer does not recognise. "
        "They are listed in the report either way.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and map, write nothing. Produces the full reconciliation report.",
    )
    parser.add_argument(
        "--skip-media", action="store_true", help="Text only. For a fast rehearsal."
    )
    parser.add_argument(
        "--pages-only", action="store_true", help="Import wiki pages and nothing else."
    )
    parser.add_argument(
        "--guides-only", action="store_true", help="Import guides and nothing else."
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Do not import. Re-read every guide already imported and compare it with the "
        "source, field by field, reporting anything that differs and anything here that the "
        "source does not have.",
    )
    parser.add_argument("--report", type=Path, default=None, help="Write the text report here.")
    parser.add_argument(
        "--json-report", type=Path, default=None, help="Write the JSON report here."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    options = Options(
        base_url=args.base_url,
        token=args.token,
        include_private=args.include_private,
        limit=args.limit,
        allow_unmapped=args.allow_unmapped,
        dry_run=args.dry_run,
        skip_media=args.skip_media,
        report_path=args.report,
        json_report_path=args.json_report,
        author_email=args.author_email,
    )

    init_db()
    settings = get_settings()
    db = SessionLocal()
    try:
        client = DozukiClient(options.base_url, options.token)

        if args.verify:
            from .verify import verify

            verification = verify(db, client, limit=options.limit)
            text = verification.to_text()
            print(text)
            if options.report_path is not None:
                options.report_path.write_text(text, encoding="utf-8")
            if options.json_report_path is not None:
                options.json_report_path.write_text(verification.to_json(), encoding="utf-8")
            return 0 if verification.faithful else 5

        importer = Importer(db, client, options, settings)
        if not args.pages_only:
            importer.import_guides()
        if not args.guides_only:
            importer.import_pages()
    except MigrationError as error:
        print(f"Migration stopped: {error}", file=sys.stderr)
        return 2
    finally:
        db.close()

    report = importer.report
    text = report.to_text()
    print(text)
    if options.report_path is not None:
        options.report_path.write_text(text, encoding="utf-8")
    if options.json_report_path is not None:
        options.json_report_path.write_text(report.to_json(), encoding="utf-8")

    if report.losses and not options.allow_unmapped:
        print(
            "\nStopping: the site uses values this importer does not recognise (listed above).\n"
            "Decide what each one should become, extend app/importer/mapping.py, and run again.\n"
            "Pass --allow-unmapped to accept the losses knowingly.",
            file=sys.stderr,
        )
        return 3
    if not report.balanced:
        print("\nStopping: the counts above do not reconcile.", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
