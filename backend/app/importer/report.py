"""What a load did, written so that a person can act on it.

The report is the importer's half of a conversation with whoever runs it. Counts
say whether the run was complete; the warnings say where to look. Every lossy
decision the loader makes — a step split in two, an image imported with its
markers burned in, a piece of markup it did not recognise — lands here with the
guide it happened in, grouped by kind so that forty instances of the same thing
read as one item of work and not forty.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from dataclasses import dataclass, field

OUTCOMES = ("created", "updated", "unchanged", "skipped", "failed")

WARNING_TITLES = {
    "split_step": "Steps split because they held more media than a Reticle step allows",
    "fallback_image": "Images imported with their markers burned in (not editable annotations)",
    "marker_note": "Marker conversions worth a glance",
    "unknown_markup": "Markup that was not recognised and was kept as plain text",
    "unmapped_bullet": "Bullets whose colour or icon was not recognised",
    "level_clamped": "Bullets whose indent level was outside 0–2",
    "missing_media": "Media that could not be imported",
    "missing_image": "Images referenced in page text that are not in the archive",
    "empty_step": "Empty steps that were left out",
    "duplicate_media": "Pictures that appeared twice in one step",
    "not_published": "Content imported as a draft although the original was public",
    "vendor_flag": "Guides carrying a flag on the old site",
    "clipped": "Text shortened to fit a field",
    "difficulty": "Difficulty values that were not recognised",
    "tags": "Tags that could not be carried over",
    "category": "Category placement worth checking",
    "author": "Authors that could not be matched cleanly",
    "unresolved_link": "Internal links that match nothing imported",
    "vendor_link": "Links that still point at the old site",
    "guidelist": "Guide lists worth checking",
    "table_span": "Tables with merged cells, flattened",
    "table_flattened": "Tables inside plain-text fields",
    "inline_image": "Images inside plain-text fields, left out",
    "video_embed": "Embedded external videos turned into links",
    "comment_dropped": "Editor-only comments that were not carried over",
    "redirect": "Redirect pages",
    "landing": "Category pages imported as ordinary pages",
    "page_tags": "Page tags (Reticle pages have no tags)",
    "links_flattened": "Links that became plain text inside bullets and introductions",
}


@dataclass(frozen=True)
class Outcome:
    kind: str
    reference: str
    outcome: str
    detail: str = ""


@dataclass(frozen=True)
class ReportWarning:
    code: str
    reference: str
    message: str


@dataclass
class Report:
    outcomes: list[Outcome] = field(default_factory=list)
    warnings: list[ReportWarning] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    header: dict[str, str] = field(default_factory=dict)

    def add(self, kind: str, reference: str, outcome: str, detail: str = "") -> None:
        self.outcomes.append(Outcome(kind, reference, outcome, detail))

    def warn(self, code: str, reference: str, message: str) -> None:
        self.warnings.append(ReportWarning(code, reference, message))

    def note(self, message: str) -> None:
        if message not in self.notes:
            self.notes.append(message)

    def counts(self) -> dict[str, dict[str, int]]:
        counts: dict[str, dict[str, int]] = {}
        for entry in self.outcomes:
            bucket = counts.setdefault(entry.kind, dict.fromkeys(OUTCOMES, 0))
            bucket[entry.outcome] += 1
        return counts

    @property
    def failed(self) -> list[Outcome]:
        return [entry for entry in self.outcomes if entry.outcome == "failed"]

    def with_outcome(self, outcome: str) -> list[Outcome]:
        return [entry for entry in self.outcomes if entry.outcome == outcome]

    # ------------------------------------------------------------ rendering

    def summary(self) -> str:
        """The few lines printed to the console at the end of a run."""
        lines = []
        for kind, bucket in self.counts().items():
            parts = [f"{count} {name}" for name, count in bucket.items() if count]
            lines.append(f"  {kind + ':':<11}{', '.join(parts)}")
        lines.append(f"  warnings:  {len(self.warnings)}")
        if self.failed:
            lines.append(f"  FAILED:    {len(self.failed)} item(s) — see the report")
        return "\n".join(lines)

    def markdown(self) -> str:
        lines = ["# Import report", ""]
        for key, value in self.header.items():
            lines.append(f"- **{key}:** {value}")
        lines.append("")

        lines += ["## Counts", "", "| | " + " | ".join(OUTCOMES) + " |", "| --- |" + " ---: |" * len(OUTCOMES)]
        for kind, bucket in self.counts().items():
            lines.append(f"| {kind} | " + " | ".join(str(bucket[name]) for name in OUTCOMES) + " |")
        lines.append("")

        for outcome, title in (
            ("failed", "Failed — nothing was written for these"),
            ("skipped", "Skipped"),
        ):
            entries = self.with_outcome(outcome)
            if entries:
                lines += [f"## {title}", ""]
                lines += [f"- {entry.kind} {entry.reference}: {entry.detail}" for entry in entries]
                lines.append("")

        lines += [f"## Warnings ({len(self.warnings)})", ""]
        if not self.warnings:
            lines += ["None.", ""]
        grouped: dict[str, list[ReportWarning]] = {}
        for warning in self.warnings:
            grouped.setdefault(warning.code, []).append(warning)
        for code in sorted(grouped, key=lambda item: (list(WARNING_TITLES).index(item) if item in WARNING_TITLES else 999, item)):
            lines += [f"### {WARNING_TITLES.get(code, code)} ({len(grouped[code])})", ""]
            lines += [f"- {warning.reference}: {warning.message}" for warning in grouped[code]]
            lines.append("")

        if self.notes:
            lines += ["## Notes", ""]
            lines += [f"- {note}" for note in self.notes]
            lines.append("")

        for outcome, title in (("created", "Created"), ("updated", "Updated")):
            entries = self.with_outcome(outcome)
            if entries:
                lines += [f"## {title} ({len(entries)})", ""]
                lines += [f"- {entry.kind} {entry.reference}" + (f" — {entry.detail}" if entry.detail else "") for entry in entries]
                lines.append("")
        return "\n".join(lines)
