"""Identifier-blind deduplication measurement for the social-sciences arm.

Protocol is the package's own (``corpusslr.validate``): ground truth is the
normalized DOI, every identifier field is then wiped, and deduplication has to
rebuild the clusters from title, authors, year and bibliographic coordinates.
Classification of false positives reuses ``validation/eval_multidomain.py``
verbatim rather than reimplementing it, so the social numbers are comparable
with the four-discipline study already in the repository.

Nothing in this module touches package code or any shared file; it writes only
the four ``validation/domains_social_*`` files.
"""
from __future__ import annotations

import collections
import csv
import os
import re
import sys
import unicodedata
from typing import Dict, List, Sequence, Tuple

REPO = "/Users/sebastianmatysik/!!!CorpusSLR/corpusslr"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "validation"))

from corpusslr.dedup import deduplicate                                # noqa: E402
from corpusslr.record import Record, normalize_doi                     # noqa: E402
from corpusslr.validate import (clusters_from_decisions, corpus_profile,  # noqa: E402
                                hide_identifiers, pair_metrics,
                                record_metrics, truth_groups)
import eval_multidomain as EM                                          # noqa: E402

from social_harvest import load_cache                                  # noqa: E402

OUTDIR = os.path.join(REPO, "validation")

#: The seven categories the study reports.  ``eval_multidomain`` distinguishes
#: two further labels, folded in by :func:`collapse_kind` rather than dropped.
KINDS = ("preprint_vs_published", "two_preprint_servers", "book_edition",
         "working_paper_vs_published", "two_working_paper_series",
         "correction_vs_original", "over_merge")

#: Categories in which the merged pair is two versions of one study.  Precision
#: is reported both with and without them; neither figure replaces the other.
VERSION_KINDS = frozenset(("preprint_vs_published", "two_preprint_servers",
                           "book_edition", "working_paper_vs_published",
                           "two_working_paper_series"))

#: Below this many judgeable pairs, a precision/recall figure is a description
#: of a handful of pairs and must not be read as a domain-level result.
MIN_PAIRS = 30

_DB_LABEL = {"wos": "Web of Science", "scopus": "Scopus", "crossref": "Crossref"}


# ----------------------------------------------------------------------
# Serial-installment detection
# ----------------------------------------------------------------------
#: ``eval_multidomain.classify_false_positive`` decides ``two_working_paper_
#: series`` from the *record type* of both members, which is right for the case
#: it was written for (one study circulated as an NBER and an IZA working paper)
#: but wrong for a numbered periodical.  The transport arm contains NREL's
#: quarterly report "Electric Vehicle Charging Infrastructure Trends from the
#: Alternative Fueling Station Locator", published seven times between Q1 2021
#: and Q3 2022 under seven OSTI DOIs.  Consecutive quarters differ by two or
#: three tokens out of nineteen, so fuzzy matching merges them and the type rule
#: excuses the merge as a version variant.  They are not versions of one study:
#: they are seven different reports with different data, and a review team that
#: silently kept one of them would lose six.  Merging them is a genuine
#: over-merge and is counted as one.
#:
#: The rule fires only when both titles carry an installment designation and the
#: designations differ.  Measured on this corpus: 21 of 21 NREL pairs flagged,
#: 0 of the other 109 false positives, 0 of 1023 true duplicate pairs.
_SERIAL_CUE = re.compile(r"\b(quarter|part|volume|vol|issue|no|number|episode|"
                         r"chapter|series|wave|round|edition|q[1-4])\b")
_ORD = {"first": 1, "second": 2, "third": 3, "fourth": 4,
        "1st": 1, "2nd": 2, "3rd": 3, "4th": 4,
        "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6}
_ORD_RE = re.compile(r"\b(first|second|third|fourth|1st|2nd|3rd|4th)\b")
_YEAR_RE = re.compile(r"(19|20)\d{2}")


def _norm_title(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text or "")
    folded = folded.encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", " ", folded.lower())


def serial_designations(title: str) -> set:
    """Tokens naming *which* installment of a series a title designates.

    Two mechanisms, both requiring an explicit periodicity marker so that a
    bare number in an ordinary title cannot trigger the rule: a serial noun
    (quarter, part, volume, issue, wave...) with a digit or ordinal within two
    tokens, or an ordinal word, which in a serial title always designates the
    installment.  A four-digit year is added only once one of the two has
    fired, because a year on its own distinguishes editions as often as
    installments.
    """
    words = _norm_title(title).split()
    out: set = set()
    fired = False
    for i, word in enumerate(words):
        if _SERIAL_CUE.match(word):
            fired = True
            for near in words[max(0, i - 2):i + 3]:
                if near.isdigit():
                    out.add(near)
                elif near in _ORD:
                    out.add(str(_ORD[near]))
    for m in _ORD_RE.finditer(" ".join(words)):
        fired = True
        out.add(str(_ORD[m.group(1)]))
    if fired:
        out |= {wd for wd in words if re.fullmatch(r"(19|20)\d{2}", wd)}
        out |= {m.group(1) for wd in words
                for m in [re.fullmatch(r"q((19|20)\d{2})", wd)] if m}
    return out


def is_serial_installment(title_a: str, title_b: str) -> bool:
    """True when two titles name *different* installments of one serial."""
    if _norm_title(title_a).split() == _norm_title(title_b).split():
        return False
    da, db = serial_designations(title_a), serial_designations(title_b)
    return bool(da and db and da != db)


def collapse_kind(kind: str, a: Record = None, b: Record = None) -> str:
    """Map the finer eval_multidomain labels onto the seven reported ones.

    ``identical_title_distinct_doi`` -- two byte-identical normalized titles
    under two DOIs with no version relationship visible in the metadata -- is
    charged as ``over_merge``: without full text there is no evidence the two
    are one work, so the conservative reading counts the pair as an error.
    ``supplementary_component`` cannot arise here (non-work record types are
    removed before scoring) and is mapped the same way for safety.
    """
    if a is not None and b is not None and is_serial_installment(a.title,
                                                                 b.title):
        return "over_merge"
    if kind in ("identical_title_distinct_doi", "supplementary_component"):
        return "over_merge"
    return kind


def rows_to_records(rows: Sequence[dict]) -> List[Record]:
    out = []
    for n, row in enumerate(rows, 1):
        meta = {k: v for k, v in row.items() if not k.startswith("_")}
        meta.pop("uid", None)
        meta.pop("provenance", None)
        meta.pop("raw", None)
        rec = Record(**meta)
        rec.raw = {}
        rec.uid = "{}-{:05d}".format(row["_db"], n)
        rec.source = rec.source or row["_db"]
        out.append(rec)
    return out


def build_arm(rows: Sequence[dict]) -> Tuple[List[Record], Dict[str, str]]:
    records = rows_to_records(rows)
    return records, truth_groups(records)


def measure(rows: Sequence[dict]) -> dict:
    """Blind, deduplicate, score, and classify every false positive."""
    records, truth = build_arm(rows)
    index = {r.uid: r for r in records}
    blinded = hide_identifiers(records)
    result = deduplicate(blinded)
    uids = [r.uid for r in blinded]
    clusters = clusters_from_decisions(result.report.decisions, uids)

    pm = pair_metrics(clusters, truth)
    rm = record_metrics(clusters, truth)

    fps: List[Tuple[Record, Record, str]] = []
    for cluster in clusters:
        judged = [u for u in cluster if u in truth]
        for i in range(len(judged)):
            for j in range(i + 1, len(judged)):
                ua, ub = judged[i], judged[j]
                if truth[ua] == truth[ub]:
                    continue
                a, b = index[ua], index[ub]
                fps.append((a, b, collapse_kind(
                    EM.classify_false_positive(a, b), a, b)))

    counts = collections.Counter(k for _, _, k in fps)
    version_fp = sum(counts[k] for k in VERSION_KINDS)

    tp, fp = pm["pair_tp"], pm["pair_fp"]
    fp_strict = fp - version_fp
    prec_excl = tp / (tp + fp_strict) if tp + fp_strict else 1.0
    rec = pm["recall"]
    f1_excl = (2 * prec_excl * rec / (prec_excl + rec)) if prec_excl + rec else 0.0

    return dict(records=records, truth=truth, metrics=pm, rec_metrics=rm,
                fps=fps, counts=counts,
                precision_excl_versions=prec_excl, f1_excl_versions=f1_excl)


def doi_coverage(records: Sequence[Record]) -> float:
    if not records:
        return 0.0
    return 100.0 * sum(1 for r in records if normalize_doi(r.doi)) / len(records)


def write_csv(path: str, rows: Sequence[dict], fields: Sequence[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(fields))
        wr.writeheader()
        for row in rows:
            wr.writerow(row)
