"""Proving an imported guide is what the source says, and nothing more.

The reconciliation report in ``report`` counts things. Counting catches a
migration that lost half a corpus; it does not catch one where a step arrived
with the right number of bullets and the wrong words in them. This module reads
the *content* back: it re-fetches each guide from the source, maps it again, and
compares the result field by field against what Reticle is actually storing.

Two failures are worth separating, and this reports them separately.

**Drift** is a value that differs — a bullet whose text does not match, a
colour that changed, a shape that moved. Something was lost or altered on the
way in.

**Invention** is content in Reticle with no counterpart in the source at all: an
extra bullet, an extra step, a tag nobody applied. That is the failure mode
nobody looks for, because a guide with more in it than the original still reads
perfectly well — and it is the one that matters most when a language model is
anywhere near the pipeline. Nothing in this importer generates prose, and this
is how that stays true rather than being asserted.

The comparison is mechanical. It re-fetches rather than trusting a cached copy,
compares strings exactly rather than approximately, and reports the first
difference in full, because a verifier that says "mostly fine" is a verifier
nobody acts on.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..models import Guide, ImportedRecord
from ..schemas import guide_out
from .client import MigrationError
from .mapping import MappedGuide, map_guide

SOURCE_SYSTEM = "dozuki"

ROUNDING = 4
"""Coordinates are compared to four decimals.

They crossed as text and came back as floats, so demanding bit-for-bit equality
would report a difference where the picture is identical. Four decimals is finer
than a pixel on any image anybody will ever upload.
"""


@dataclass
class Difference:
    """One thing that does not match, named precisely enough to go and look."""

    kind: str
    where: str
    expected: Any
    found: Any

    def __str__(self) -> str:
        return f"{self.where}: expected {self.expected!r}, found {self.found!r}"


@dataclass
class GuideVerdict:
    source_id: str
    title: str
    slug: str = ""
    drift: list[Difference] = field(default_factory=list)
    invention: list[Difference] = field(default_factory=list)
    unreachable: str | None = None

    @property
    def faithful(self) -> bool:
        return not self.drift and not self.invention and self.unreachable is None


@dataclass
class VerificationReport:
    verdicts: list[GuideVerdict] = field(default_factory=list)
    not_imported: list[str] = field(default_factory=list)

    @property
    def faithful(self) -> bool:
        return all(verdict.faithful for verdict in self.verdicts) and not self.not_imported

    def to_text(self) -> str:
        checked = len(self.verdicts)
        clean = sum(1 for verdict in self.verdicts if verdict.faithful)
        lines = [
            "Reticle fidelity check",
            "======================",
            "",
            f"Checked {checked} guides against the source; {clean} match exactly.",
            "",
        ]

        drifted = [v for v in self.verdicts if v.drift]
        invented = [v for v in self.verdicts if v.invention]
        unreachable = [v for v in self.verdicts if v.unreachable]

        if invented:
            lines.append(f"CONTENT WITH NO SOURCE ({len(invented)} guides)")
            lines.append("Reticle holds something the source does not. Nothing here writes prose,")
            lines.append("so each of these is either a bug or an edit somebody made after import.")
            for verdict in invented:
                lines.append(f"  {verdict.source_id}  {verdict.title}")
                for difference in verdict.invention:
                    lines.append(f"      {difference}")
            lines.append("")

        if drifted:
            lines.append(f"DIFFERS FROM THE SOURCE ({len(drifted)} guides)")
            for verdict in drifted:
                lines.append(f"  {verdict.source_id}  {verdict.title}")
                for difference in verdict.drift:
                    lines.append(f"      {difference}")
            lines.append("")

        if unreachable:
            lines.append(f"COULD NOT BE RE-FETCHED ({len(unreachable)})")
            for verdict in unreachable:
                lines.append(f"  {verdict.source_id}  {verdict.unreachable}")
            lines.append("")

        if self.not_imported:
            lines.append(f"ON THE SOURCE, ABSENT HERE ({len(self.not_imported)})")
            lines.extend(f"  {source_id}" for source_id in self.not_imported)
            lines.append("")

        if self.faithful:
            lines.append("Every guide checked is a faithful copy of its source.")
            lines.append("")

        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps(
            {
                "checked": len(self.verdicts),
                "faithful": self.faithful,
                "guides": [
                    {
                        "sourceId": verdict.source_id,
                        "title": verdict.title,
                        "slug": verdict.slug,
                        "faithful": verdict.faithful,
                        "drift": [vars(d) for d in verdict.drift],
                        "invention": [vars(d) for d in verdict.invention],
                        "unreachable": verdict.unreachable,
                    }
                    for verdict in self.verdicts
                ],
                "notImported": self.not_imported,
            },
            indent=2,
            ensure_ascii=False,
        )


def verify(db: DbSession, client, limit: int | None = None) -> VerificationReport:
    """Re-read every imported guide from the source and compare it with ours."""
    report = VerificationReport()

    records = db.scalars(
        select(ImportedRecord).where(
            ImportedRecord.source_system == SOURCE_SYSTEM,
            ImportedRecord.source_kind == "guide",
        )
    ).all()

    for index, record in enumerate(records):
        if limit is not None and index >= limit:
            break

        guide = db.get(Guide, record.local_id)
        if guide is None:
            report.not_imported.append(record.source_id)
            continue

        verdict = GuideVerdict(source_id=record.source_id, title=guide.title, slug=guide.slug)
        report.verdicts.append(verdict)

        try:
            payload = client.get_guide(record.source_id)
        except MigrationError as error:
            verdict.unreachable = str(error)
            continue

        source, _ = map_guide(payload)
        compare(source, guide_out(guide).model_dump(mode="json", by_alias=True), verdict)

    return report


def compare(source: MappedGuide, stored: dict[str, Any], verdict: GuideVerdict) -> None:
    """Field by field, in the order somebody reading a guide would notice."""
    _scalar(verdict, "title", source.title, stored["title"])
    _scalar(verdict, "summary", source.summary, stored["summary"])
    _scalar(verdict, "introduction", source.introduction, stored["introduction"])
    _scalar(verdict, "conclusion", source.conclusion, stored["conclusion"])
    _scalar(verdict, "difficulty", source.difficulty, stored["difficulty"])
    _scalar(verdict, "time from", source.time_min_minutes, stored["timeRequiredMinMinutes"])
    _scalar(verdict, "time to", source.time_max_minutes, stored["timeRequiredMaxMinutes"])

    _sets(verdict, "tags", source.tags, stored["tags"])

    source_steps, stored_steps = source.steps, stored["steps"]
    if len(source_steps) != len(stored_steps):
        difference = Difference("steps", "step count", len(source_steps), len(stored_steps))
        (verdict.invention if len(stored_steps) > len(source_steps) else verdict.drift).append(
            difference
        )

    # strict=False is deliberate: a count mismatch has just been recorded
    # above as drift or invention, and this loop's job is to compare the steps
    # that do line up. Raising here would abandon the comparison at the first
    # length difference and report nothing about the rest.
    for index, (source_step, stored_step) in enumerate(
        zip(source_steps, stored_steps, strict=False), start=1
    ):
        where = f"step {index}"
        _scalar(verdict, f"{where} title", source_step.title, stored_step["title"])

        source_bullets = source_step.bullets
        stored_bullets = stored_step["bullets"]
        if len(source_bullets) != len(stored_bullets):
            difference = Difference(
                "bullets", f"{where} bullet count", len(source_bullets), len(stored_bullets)
            )
            (
                verdict.invention if len(stored_bullets) > len(source_bullets) else verdict.drift
            ).append(difference)

        for position, (source_bullet, stored_bullet) in enumerate(
            zip(source_bullets, stored_bullets, strict=False), start=1
        ):
            label = f"{where} bullet {position}"
            _scalar(verdict, f"{label} text", source_bullet.text, stored_bullet["text"])
            _scalar(verdict, f"{label} colour", source_bullet.color, stored_bullet["color"])
            _scalar(verdict, f"{label} flag", source_bullet.icon, stored_bullet["icon"])
            _scalar(verdict, f"{label} indent", source_bullet.level, stored_bullet["level"])

        _compare_media(verdict, where, source_step, stored_step)


def _compare_media(verdict: GuideVerdict, where: str, source_step, stored_step) -> None:
    source_images = source_step.images
    stored_images = stored_step["media"]

    if len(source_images) != len(stored_images):
        difference = Difference(
            "images", f"{where} image count", len(source_images), len(stored_images)
        )
        (verdict.invention if len(stored_images) > len(source_images) else verdict.drift).append(
            difference
        )

    for position, (source_image, stored_image) in enumerate(
        zip(source_images, stored_images, strict=False), start=1
    ):
        label = f"{where} image {position}"
        source_shapes = source_image.annotations
        stored_shapes = stored_image["annotations"]

        if len(source_shapes) != len(stored_shapes):
            difference = Difference(
                "annotations", f"{label} shape count", len(source_shapes), len(stored_shapes)
            )
            (
                verdict.invention if len(stored_shapes) > len(source_shapes) else verdict.drift
            ).append(difference)

        for order, (source_shape, stored_shape) in enumerate(
            zip(source_shapes, stored_shapes, strict=False), start=1
        ):
            marker = f"{label} shape {order}"
            _scalar(verdict, f"{marker} kind", source_shape.shape, stored_shape["shape"])
            _scalar(verdict, f"{marker} colour", source_shape.color, stored_shape["color"])
            for axis in ("x", "y", "width", "height"):
                _scalar(
                    verdict,
                    f"{marker} {axis}",
                    round(getattr(source_shape, axis), ROUNDING),
                    round(stored_shape[axis], ROUNDING),
                )

    has_video = source_step.video is not None
    stored_video = stored_step.get("video") is not None
    if has_video != stored_video:
        difference = Difference("video", f"{where} video", has_video, stored_video)
        (verdict.invention if stored_video else verdict.drift).append(difference)


def _scalar(verdict: GuideVerdict, where: str, expected: Any, found: Any) -> None:
    if expected == found:
        return
    # Something present here and absent at the source is content nobody wrote.
    empty_at_source = expected in (None, "", 0)
    difference = Difference("value", where, expected, found)
    (verdict.invention if empty_at_source and found else verdict.drift).append(difference)


def _sets(verdict: GuideVerdict, where: str, expected: list[str], found: list[str]) -> None:
    missing = [item for item in expected if item not in found]
    extra = [item for item in found if item not in expected]
    if missing:
        verdict.drift.append(Difference("value", f"{where} missing", missing, found))
    if extra:
        verdict.invention.append(Difference("value", f"{where} not on the source", expected, extra))
