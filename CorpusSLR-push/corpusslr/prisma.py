"""PRISMA 2020 flow diagram (Page et al., 2021), auto-filled and rendered.

The identification block is populated automatically from the corpus'
search events and the deduplication report; screening/eligibility numbers
are supplied by the researcher (or by downstream tools such as EmbedSLR).
The diagram is emitted as dependency-free SVG (convertible to PNG/PDF with
any standard tool) plus a Markdown/dict representation, and arithmetic
consistency is validated before rendering.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .corpus import Corpus
from .dedup import DedupResult

_FONT = "Helvetica, Arial, sans-serif"


@dataclass
class PrismaFlow:
    db_counts: Dict[str, int] = field(default_factory=dict)
    duplicates_removed: int = 0
    dedup_by_method: Dict[str, int] = field(default_factory=dict)
    automation_excluded: int = 0
    other_excluded: int = 0
    records_excluded: int = 0
    reports_not_retrieved: int = 0
    fulltext_exclusions: Dict[str, int] = field(default_factory=dict)
    studies_included: int = 0
    reports_included: Optional[int] = None

    # ------------------------------------------------------------------
    @classmethod
    def from_dedup(cls, corpus: Corpus, result: DedupResult) -> "PrismaFlow":
        return cls(db_counts=corpus.identified_by_source(),
                   duplicates_removed=result.report.removed,
                   dedup_by_method=dict(result.report.by_method))

    def set_screening(self, records_excluded: int,
                      reports_not_retrieved: int = 0,
                      fulltext_exclusions: Optional[Dict[str, int]] = None,
                      studies_included: int = 0,
                      reports_included: Optional[int] = None,
                      automation_excluded: int = 0,
                      other_excluded: int = 0) -> "PrismaFlow":
        self.records_excluded = records_excluded
        self.reports_not_retrieved = reports_not_retrieved
        self.fulltext_exclusions = fulltext_exclusions or {}
        self.studies_included = studies_included
        self.reports_included = reports_included
        self.automation_excluded = automation_excluded
        self.other_excluded = other_excluded
        return self

    # ------------------------------------------------------------------
    @property
    def identified(self) -> int:
        return sum(self.db_counts.values())

    @property
    def records_screened(self) -> int:
        return (self.identified - self.duplicates_removed
                - self.automation_excluded - self.other_excluded)

    @property
    def reports_sought(self) -> int:
        return self.records_screened - self.records_excluded

    @property
    def reports_assessed(self) -> int:
        return self.reports_sought - self.reports_not_retrieved

    def validate(self) -> List[str]:
        """Return every arithmetic inconsistency in the flow (empty = valid).

        The full-text balance is checked unconditionally: a review that
        includes zero studies still has to account for what happened to the
        reports it assessed, and skipping the check whenever
        ``studies_included == 0`` let impossible diagrams pass silently.
        """
        problems = []
        for name, value in (("duplicates_removed", self.duplicates_removed),
                            ("automation_excluded", self.automation_excluded),
                            ("other_excluded", self.other_excluded),
                            ("records_excluded", self.records_excluded),
                            ("reports_not_retrieved", self.reports_not_retrieved),
                            ("studies_included", self.studies_included)):
            if value < 0:
                problems.append(f"Negative count for {name} ({value}).")
        for db, n in self.db_counts.items():
            if n < 0:
                problems.append(f"Negative record count for source {db} ({n}).")
        for reason, n in self.fulltext_exclusions.items():
            if n < 0:
                problems.append(
                    f"Negative full-text exclusion count for '{reason}' ({n}).")
        if self.reports_included is not None and self.reports_included < 0:
            problems.append(
                f"Negative count for reports_included ({self.reports_included}).")

        if self.records_screened < 0:
            problems.append("Removed before screening exceeds records identified.")
        if self.reports_sought < 0:
            problems.append("Records excluded exceeds records screened.")
        if self.reports_assessed < 0:
            problems.append("Reports not retrieved exceeds reports sought.")
        ft = sum(self.fulltext_exclusions.values())
        if self.reports_assessed - ft != self.studies_included:
            problems.append(
                f"Reports assessed ({self.reports_assessed}) minus full-text "
                f"exclusions ({ft}) != studies included "
                f"({self.studies_included}).")
        return problems

    # ------------------------------------------------------------------
    def counts(self) -> Dict[str, object]:
        return {
            "identified": self.identified,
            "identified_by_source": dict(self.db_counts),
            "duplicates_removed": self.duplicates_removed,
            "automation_excluded": self.automation_excluded,
            "other_excluded": self.other_excluded,
            "records_screened": self.records_screened,
            "records_excluded": self.records_excluded,
            "reports_sought": self.reports_sought,
            "reports_not_retrieved": self.reports_not_retrieved,
            "reports_assessed": self.reports_assessed,
            "fulltext_exclusions": dict(self.fulltext_exclusions),
            "studies_included": self.studies_included,
            "reports_included": self.reports_included,
        }

    def to_markdown(self) -> str:
        c = self.counts()
        # counts() is declared Dict[str, object] because it mixes ints, None and
        # nested mappings; the two mapping-valued entries are re-bound here so
        # the reader (and the type checker) can see what they contain.
        by_source: Dict[str, int] = dict(self.db_counts)
        exclusions: Dict[str, int] = dict(self.fulltext_exclusions)
        dbs = "; ".join(f"{k} (n = {v})" for k, v in by_source.items())
        lines = [
            "## PRISMA 2020 flow (new studies)",
            f"- Records identified from databases (n = {c['identified']}): {dbs}",
            (f"- Records removed before screening: duplicates "
             f"(n = {c['duplicates_removed']}), automation tools "
             f"(n = {c['automation_excluded']}), other "
             f"(n = {c['other_excluded']})"),
            f"- Records screened (n = {c['records_screened']})",
            f"- Records excluded (n = {c['records_excluded']})",
            f"- Reports sought for retrieval (n = {c['reports_sought']})",
            f"- Reports not retrieved (n = {c['reports_not_retrieved']})",
            f"- Reports assessed for eligibility (n = {c['reports_assessed']})",
        ]
        for reason, n in exclusions.items():
            lines.append(f"    - Excluded: {reason} (n = {n})")
        lines.append(f"- Studies included in review (n = {c['studies_included']})")
        if c["reports_included"] is not None:
            lines.append(f"- Reports of included studies "
                         f"(n = {c['reports_included']})")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # SVG rendering (no third-party dependencies)
    # ------------------------------------------------------------------
    def to_svg(self, path: Optional[str] = None) -> str:
        left_w, right_w = 330, 360
        lx, rx = 90, 520
        gap = 26
        font = 12

        def wrap(text: str, width_px: int) -> List[str]:
            max_chars = max(10, int(width_px / (font * 0.52)))
            lines, cur = [], ""
            for word in text.split():
                cand = (cur + " " + word).strip()
                if len(cand) <= max_chars:
                    cur = cand
                else:
                    if cur:
                        lines.append(cur)
                    cur = word
            if cur:
                lines.append(cur)
            return lines or [""]

        boxes = []  # (x, y, w, h, lines)

        def add_box(x: int, y: int, w: int, texts: List[str]) -> int:
            lines: List[str] = []
            for t in texts:
                lines += wrap(t, w - 20)
            h = 16 * len(lines) + 14
            boxes.append((x, y, w, h, lines))
            return h

        dbs = "; ".join(f"{k} (n = {v})" for k, v in self.db_counts.items())
        y = 60
        h1 = add_box(lx, y, left_w,
                     [f"Records identified from databases (n = {self.identified}):",
                      dbs])
        removed_lines = ["Records removed before screening:",
                         f"Duplicate records removed (n = {self.duplicates_removed})"]
        meth = "; ".join(f"{m}: {n}" for m, n in self.dedup_by_method.items())
        if meth:
            removed_lines.append(f"[{meth}]")
        removed_lines += [
            (f"Records marked ineligible by automation tools "
             f"(n = {self.automation_excluded})"),
            f"Records removed for other reasons (n = {self.other_excluded})"]
        add_box(rx, y, right_w, removed_lines)
        y2 = y + h1 + gap
        h2 = add_box(lx, y2, left_w,
                     [f"Records screened (n = {self.records_screened})"])
        add_box(rx, y2, right_w,
                [f"Records excluded (n = {self.records_excluded})"])
        y3 = y2 + h2 + gap
        h3 = add_box(lx, y3, left_w,
                     [f"Reports sought for retrieval (n = {self.reports_sought})"])
        add_box(rx, y3, right_w,
                [f"Reports not retrieved (n = {self.reports_not_retrieved})"])
        y4 = y3 + h3 + gap
        h4 = add_box(lx, y4, left_w,
                     [(f"Reports assessed for eligibility "
                       f"(n = {self.reports_assessed})")])
        excl = [f"Reports excluded (n = {sum(self.fulltext_exclusions.values())}):"]
        excl += [f"{r} (n = {n})" for r, n in self.fulltext_exclusions.items()]
        add_box(rx, y4, right_w, excl if self.fulltext_exclusions
                else ["Reports excluded (n = 0)"])
        y5 = y4 + h4 + gap
        inc = [f"Studies included in review (n = {self.studies_included})"]
        if self.reports_included is not None:
            inc.append(f"Reports of included studies "
                       f"(n = {self.reports_included})")
        h5 = add_box(lx, y5, left_w, inc)
        height = y5 + h5 + 40
        width = rx + right_w + 30

        parts = [
            (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
             f'height="{height}" font-family="{_FONT}" font-size="{font}">'),
            ('<defs><marker id="arr" markerWidth="10" markerHeight="10" '
             'refX="8" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6 z" '
             'fill="#333"/></marker></defs>'),
            f'<rect x="0" y="0" width="{width}" height="{height}" fill="white"/>',
            (f'<text x="{lx}" y="30" font-size="15" font-weight="bold">'
             'Identification of studies via databases and registers '
             '(PRISMA 2020)</text>'),
        ]
        # phase side bars
        phases = [("Identification", y, h1), ("Screening", y2, y4 + h4 - y2),
                  ("Included", y5, h5)]
        for label, py, ph in phases:
            parts.append(f'<rect x="20" y="{py}" width="34" height="{ph}" '
                         'fill="#e8edf5" stroke="#94a3b8"/>')
            cx, cy = 37, py + ph / 2
            parts.append(f'<text x="{cx}" y="{cy}" text-anchor="middle" '
                         f'transform="rotate(-90 {cx} {cy})" '
                         'font-weight="bold">' + label + '</text>')
        for (x, by, w, h, lines) in boxes:
            parts.append(f'<rect x="{x}" y="{by}" width="{w}" height="{h}" '
                         'fill="#ffffff" stroke="#333" rx="3"/>')
            ty = by + 18
            for ln in lines:
                parts.append(f'<text x="{x + 10}" y="{ty}">{_esc(ln)}</text>')
                ty += 16
        # arrows: vertical between left boxes, horizontal to right boxes
        left = [b for b in boxes if b[0] == lx]
        right = [box for box in boxes if box[0] == rx]
        mid_x = lx + left_w / 2
        for a, b in zip(left, left[1:]):
            parts.append(f'<line x1="{mid_x}" y1="{a[1] + a[3]}" x2="{mid_x}" '
                         f'y2="{b[1]}" stroke="#333" marker-end="url(#arr)"/>')
        for a, _rbox in zip(left[:len(right)], right):
            ymid = a[1] + min(a[3], 40) / 2 + 4
            parts.append(f'<line x1="{lx + left_w}" y1="{ymid}" x2="{rx}" '
                         f'y2="{ymid}" stroke="#333" marker-end="url(#arr)"/>')
        parts.append("</svg>")
        svg = "\n".join(parts)
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(svg)
        return svg


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
