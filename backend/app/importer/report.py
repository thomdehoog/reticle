"""The reconciliation report: proof that nothing was lost.

A migration that runs to completion tells you nothing. What matters is whether
the number of guides, steps, bullets, images and — above all — annotations on
this side equals the number on the other side, guide by guide. So the importer
counts both, and this module is what turns those counts into something a person
can check in a minute and a reviewer can diff.

Everything the mapping did not understand is grouped here too. Seven guides
using an unrecognised bullet colour is one line of report and one decision;
seven warnings scrolling past during a long run is neither.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, field

from .mapping import Unmapped

UNKNOWN_FIELD = "unknown_field"


@dataclass
class GuideTally:
    """What one guide contained, on each side of the migration."""

    source_id: str
    title: str
    slug: str = ""
    source_steps: int = 0
    imported_steps: int = 0
    source_bullets: int = 0
    imported_bullets: int = 0
    source_images: int = 0
    imported_images: int = 0
    source_annotations: int = 0
    imported_annotations: int = 0
    source_videos: int = 0
    imported_videos: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def balanced(self) -> bool:
        return (
            not self.failures
            and self.source_steps == self.imported_steps
            and self.source_bullets == self.imported_bullets
            and self.source_images == self.imported_images
            and self.source_annotations == self.imported_annotations
            and self.source_videos == self.imported_videos
        )

    def discrepancies(self) -> list[str]:
        rows = [
            ("steps", self.source_steps, self.imported_steps),
            ("bullets", self.source_bullets, self.imported_bullets),
            ("images", self.source_images, self.imported_images),
            ("annotations", self.source_annotations, self.imported_annotations),
            ("videos", self.source_videos, self.imported_videos),
        ]
        return [
            f"{name}: {expected} on the site, {actual} imported"
            for name, expected, actual in rows
            if expected != actual
        ]


@dataclass
class MigrationReport:
    guides: list[GuideTally] = field(default_factory=list)
    pages_seen: int = 0
    pages_imported: int = 0
    categories_created: int = 0
    tags_created: int = 0
    unmapped: list[Unmapped] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def guides_seen(self) -> int:
        return len(self.guides)

    @property
    def guides_imported(self) -> int:
        return sum(1 for tally in self.guides if not tally.failures)

    @property
    def losses(self) -> list[Unmapped]:
        """Values the mapping could not read. Each one is content not imported."""
        return [item for item in self.unmapped if item.kind != UNKNOWN_FIELD]

    @property
    def questions(self) -> list[Unmapped]:
        """Fields the source carries and this importer does not read.

        Not losses — nobody asked for them — but the only mechanical way to
        notice a capability the other system has and Reticle does not.
        """
        return [item for item in self.unmapped if item.kind == UNKNOWN_FIELD]

    @property
    def balanced(self) -> bool:
        return all(tally.balanced for tally in self.guides) and not self.losses

    def unmapped_summary(self) -> list[tuple[str, str, int]]:
        counted = Counter((item.kind, item.value) for item in self.losses)
        return [(kind, value, count) for (kind, value), count in counted.most_common()]

    def question_summary(self) -> list[tuple[str, int]]:
        counted = Counter(item.value for item in self.questions)
        return counted.most_common()

    def to_json(self) -> str:
        return json.dumps(
            {
                "guidesSeen": self.guides_seen,
                "guidesImported": self.guides_imported,
                "pagesSeen": self.pages_seen,
                "pagesImported": self.pages_imported,
                "categoriesCreated": self.categories_created,
                "tagsCreated": self.tags_created,
                "balanced": self.balanced,
                "guides": [asdict(tally) for tally in self.guides],
                "unmapped": [asdict(item) for item in self.losses],
                "unreadFields": [asdict(item) for item in self.questions],
                "skipped": self.skipped,
            },
            indent=2,
            ensure_ascii=False,
        )

    def to_text(self) -> str:
        lines = [
            "Reticle migration report",
            "========================",
            "",
            f"Guides   {self.guides_imported} imported of {self.guides_seen} seen",
            f"Pages    {self.pages_imported} imported of {self.pages_seen} seen",
            f"Created  {self.categories_created} categories, {self.tags_created} tags",
            "",
        ]

        totals = {
            "steps": (sum(t.source_steps for t in self.guides), sum(t.imported_steps for t in self.guides)),
            "bullets": (sum(t.source_bullets for t in self.guides), sum(t.imported_bullets for t in self.guides)),
            "images": (sum(t.source_images for t in self.guides), sum(t.imported_images for t in self.guides)),
            "annotations": (
                sum(t.source_annotations for t in self.guides),
                sum(t.imported_annotations for t in self.guides),
            ),
            "videos": (sum(t.source_videos for t in self.guides), sum(t.imported_videos for t in self.guides)),
        }
        lines.append("Totals, site versus Reticle")
        for name, (expected, actual) in totals.items():
            marker = "ok" if expected == actual else "MISMATCH"
            lines.append(f"  {name:<12} {expected:>6} -> {actual:>6}  {marker}")
        lines.append("")

        unbalanced = [tally for tally in self.guides if not tally.balanced]
        if unbalanced:
            lines.append(f"Guides that did not reconcile ({len(unbalanced)})")
            for tally in unbalanced:
                lines.append(f"  {tally.source_id}  {tally.title}")
                for failure in tally.failures:
                    lines.append(f"      failed: {failure}")
                for discrepancy in tally.discrepancies():
                    lines.append(f"      {discrepancy}")
            lines.append("")
        else:
            lines.append("Every guide reconciled exactly.")
            lines.append("")

        if self.questions:
            lines.append(f"Fields the source carries that Reticle does not read ({len(self.questions)})")
            lines.append("Not losses — but this is where a missing feature shows up.")
            for value, count in self.question_summary():
                lines.append(f"  {count:>5}  {value}")
            lines.append("")

        if self.losses:
            lines.append(f"Unmapped values ({len(self.losses)} occurrences)")
            lines.append("These are things the site has and this importer does not recognise.")
            lines.append("Each one is a decision, not a warning to scroll past.")
            for kind, value, count in self.unmapped_summary():
                lines.append(f"  {count:>5}  {kind}: {value}")
            lines.append("")

        if self.skipped:
            lines.append(f"Skipped ({len(self.skipped)})")
            lines.extend(f"  {reason}" for reason in self.skipped)
            lines.append("")

        return "\n".join(lines)
