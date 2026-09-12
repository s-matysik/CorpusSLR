"""Per-source data-quality report: field completeness and abstract length.

Motivated by documented metadata heterogeneity across bibliographic sources
(e.g., OpenAlex completeness issues, Scopus abstract truncation): the report
makes source quality visible *before* screening, so coverage decisions are
evidence-based rather than habitual.
"""
from __future__ import annotations

import csv
from typing import Dict, Iterable, List

from .record import Record

_FIELDS = ("doi", "abstract", "year", "authors", "issn", "language", "keywords")


def quality_report(records: Iterable[Record]) -> Dict[str, Dict[str, float]]:
    """Per-source metadata completeness, as the fraction of records with a field.

    Returns ``{source: {field: fraction}}``. Completeness is a property of the
    database and of the API view requested, not of the corpus: Scopus in its
    STANDARD view returns no abstracts or author lists at all, so a corpus that
    looks thin may need the request changed rather than the records enriched.
    Read this before screening -- an abstract-free arm silently weakens every
    title/abstract decision made on it.
    """
    by_source: Dict[str, List[Record]] = {}
    for r in records:
        by_source.setdefault(r.source or "?", []).append(r)
    out: Dict[str, Dict[str, float]] = {}
    for src, recs in sorted(by_source.items()):
        n = len(recs)
        row: Dict[str, float] = {"n": n}
        for f in _FIELDS:
            filled = sum(1 for r in recs if getattr(r, f))
            row[f"pct_{f}"] = round(100.0 * filled / n, 1) if n else 0.0
        lens = [len(r.abstract) for r in recs if r.abstract]
        row["mean_abstract_len"] = round(sum(lens) / len(lens), 1) if lens else 0.0
        out[src] = row
    return out


def quality_markdown(records: Iterable[Record]) -> str:
    """Render the per-source completeness table as Markdown.

    Suitable for pasting into a methods section: it documents which arm of the
    corpus could support abstract screening and which could not.
    """
    rep = quality_report(records)
    cols = ["n"] + [f"pct_{f}" for f in _FIELDS] + ["mean_abstract_len"]
    head = "| source | " + " | ".join(cols) + " |"
    sep = "|" + "---|" * (len(cols) + 1)
    lines = [head, sep]
    for src, row in rep.items():
        lines.append("| " + src + " | " +
                     " | ".join(str(row[c]) for c in cols) + " |")
    return "\n".join(lines)


def quality_csv(records: Iterable[Record], path: str) -> str:
    """Write the per-source completeness table to CSV, returning the path."""
    rep = quality_report(records)
    cols = ["source", "n"] + [f"pct_{f}" for f in _FIELDS] + \
        ["mean_abstract_len"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for src, row in rep.items():
            w.writerow([src] + [row[c] for c in cols[1:]])
    return path
