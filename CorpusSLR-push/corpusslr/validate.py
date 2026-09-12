"""Reusable machinery for validating deduplication against a known truth.

Deduplication quality can only be claimed against labelled data, and labelled
duplicate sets exist for biomedicine (ASySD; Hair et al. 2023) and essentially
nowhere else.  This module supplies the two pieces needed to build a defensible
validation set in any discipline:

*Identifier-blind evaluation.*  When the same topic is retrieved from several
databases, records that share a normalized DOI are the same work -- a hard,
externally verifiable fact rather than an annotator's judgement.
:func:`truth_groups` turns that fact into ground truth and
:func:`hide_identifiers` then removes every identifier from the records, so the
deduplicator has to rebuild the same clusters from titles, authors, year and
bibliographic coordinates alone.  The truth comes from an identifier; the
ability measured is matching *without* one.  The limitation is explicit and
unavoidable: records carrying no DOI cannot enter the truth set, so they are
scored as neither correct nor incorrect (see :func:`pair_metrics`).

*Controlled perturbations.*  Cross-database disagreement is not random noise but
a small set of recurring corruptions -- a truncated title field, a subtitle
present in one export and absent in another, a title stored in upper case, a
missing author list, an online-first year one off the issue year, diacritics
transliterated to ASCII, a page range silently converted to a date by a
spreadsheet.  :data:`PERTURBATIONS` implements them individually so sensitivity
to each can be measured separately instead of being averaged into one number.

Every perturbation reports *applicability*: transliteration is meaningless for
a title with no diacritics and Excel mangling is impossible for a page range no
spreadsheet would misread.  Applying a perturbation to a record it cannot
affect and then reporting unchanged recall would overstate robustness, so
:func:`apply_perturbation` returns ``None`` when the record is out of scope and
callers are expected to restrict the denominator to records it touched.
"""
from __future__ import annotations

import copy
import random
import re
import unicodedata
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Union

from .record import Record, normalize_doi

__all__ = [
    "hide_identifiers",
    "truth_groups",
    "clusters_from_decisions",
    "pair_metrics",
    "record_metrics",
    "corpus_profile",
    "PERTURBATIONS",
    "apply_perturbation",
    "excel_mangle_pages",
]

# Fields wiped by :func:`hide_identifiers`.  ``doi``/``pmid``/``openalex_id``/
# ``scopus_id`` are the ones :mod:`corpusslr.dedup` actually consults; ``url``,
# ``source_id``, ``raw`` and ``provenance`` are wiped too because they carry a
# verbatim copy of the DOI in several APIs (Crossref stores the DOI as both
# ``URL`` and ``source_id``).  Leaving them in place would not change a single
# merge decision, but it would leave the published blinded corpus open to the
# entirely reasonable objection that the answer was still in the file.
_ID_FIELDS = ("doi", "pmid", "openalex_id", "scopus_id", "url", "source_id")


def hide_identifiers(records: Iterable[Record],
                     fields: Sequence[str] = _ID_FIELDS) -> List[Record]:
    """Return deep copies of *records* with every identifier field emptied.

    This is the blinding step of the identifier-blind protocol: ground truth is
    derived from the DOI, so the DOI (and every field mirroring it) must be
    unavailable to the deduplicator, otherwise the evaluation is circular.

    ``pmid`` is removed as well even though it is an independent identifier.  A
    PMID maps one-to-one onto a DOI for records that have both, so keeping it
    would leak the same answer through a different column and would flatter the
    biomedical arm of a cross-disciplinary comparison specifically -- the arm
    whose external validity is under test.
    """
    out: List[Record] = []
    for rec in records:
        clone = copy.deepcopy(rec)
        for name in fields:
            setattr(clone, name, "")
        clone.raw = {}
        clone.provenance = []
        out.append(clone)
    return out


def truth_groups(records: Iterable[Record]) -> Dict[str, str]:
    """Map ``uid -> normalized DOI`` for records whose DOI is present.

    The returned mapping is the ground truth: two uids with the same value are
    the same work.  Records without a DOI are absent from the mapping and must
    therefore be excluded from scoring -- they stay in the corpus (they exert
    real blocking pressure and can pull two clusters together transitively, so
    removing them would make the task easier than reality) but no pair
    involving them is counted as a success or a failure.
    """
    out: Dict[str, str] = {}
    for rec in records:
        doi = normalize_doi(rec.doi)
        if doi and rec.uid:
            out[rec.uid] = doi
    return out


def clusters_from_decisions(decisions: Iterable, all_uids: Sequence[str]
                            ) -> List[List[str]]:
    """Rebuild the transitive closure of merge decisions as explicit clusters.

    :class:`corpusslr.dedup.DedupReport` logs pairwise decisions; cluster-level
    scoring needs the equivalence classes those pairs induce, including chains
    (a-b, b-c) that never appear as an explicit a-c decision.
    """
    parent = {u: u for u in all_uids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for dec in decisions:
        a, b = dec.kept_uid, dec.removed_uid
        if a not in parent or b not in parent:
            continue
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
    groups: Dict[str, List[str]] = {}
    for u in all_uids:
        groups.setdefault(find(u), []).append(u)
    return list(groups.values())


def pair_metrics(clusters: Iterable[Sequence[str]],
                 truth: Dict[str, str]) -> Dict[str, float]:
    """Pairwise precision/recall/F1 over co-membership, scored on *truth* only.

    Pair-level scoring is used as the primary metric because a cluster can hold
    more than two records: splitting a three-record cluster into 2+1 is a
    partial failure, and a record-level count either hides that or punishes it
    as a whole miss depending on which member survives.

    Only pairs whose *both* members appear in *truth* are counted.  A pair
    involving a record without a DOI is unjudgeable, so it contributes to
    neither numerator nor denominator -- an honest abstention rather than an
    assumption in either direction.
    """
    tp = fp = 0
    for cluster in clusters:
        judged = [u for u in cluster if u in truth]
        for i in range(len(judged)):
            for j in range(i + 1, len(judged)):
                if truth[judged[i]] == truth[judged[j]]:
                    tp += 1
                else:
                    fp += 1
    sizes: Dict[str, int] = {}
    for group in truth.values():
        sizes[group] = sizes.get(group, 0) + 1
    total = sum(n * (n - 1) // 2 for n in sizes.values())
    fn = total - tp
    prec = tp / (tp + fp) if tp + fp else 1.0
    rec = tp / total if total else 1.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"pair_tp": tp, "pair_fp": fp, "pair_fn": fn,
            "pair_truth": total, "precision": prec, "recall": rec, "f1": f1}


def record_metrics(clusters: Iterable[Sequence[str]],
                   truth: Dict[str, str]) -> Dict[str, float]:
    """Record-level metrics in the ASySD convention, for comparability.

    ASySD (Hair et al. 2023) counts records, not pairs: within each true group
    one record is the one a reviewer should keep and the rest are duplicates to
    remove.  TP is a true duplicate removed, FP a unique record removed, FN a
    true duplicate left in.  Reproduced here so the cross-disciplinary numbers
    can be read against the published biomedical benchmark, but reported
    alongside :func:`pair_metrics` rather than instead of it, because it credits
    a cluster as long as *one* member survives.
    """
    label: Dict[str, str] = {}
    seen: Dict[str, str] = {}
    for uid in sorted(truth):
        group = truth[uid]
        if group in seen:
            label[uid] = "duplicate"
        else:
            seen[group] = uid
            label[uid] = "unique"
    kept: set = set()
    for cluster in clusters:
        judged = [u for u in cluster if u in truth]
        if not judged:
            continue
        uniques = [u for u in judged if label[u] == "unique"]
        kept.add(sorted(uniques or judged)[0])
    tp = fn = fp = tn = 0
    for uid, lab in label.items():
        removed = uid not in kept
        if lab == "duplicate":
            tp += removed
            fn += not removed
        else:
            fp += removed
            tn += not removed
    sens = tp / (tp + fn) if tp + fn else 0.0
    spec = tn / (tn + fp) if tn + fp else 0.0
    prec = tp / (tp + fp) if tp + fp else 0.0
    f1 = 2 * prec * sens / (prec + sens) if prec + sens else 0.0
    return {"rec_tp": tp, "rec_tn": tn, "rec_fp": fp, "rec_fn": fn,
            "rec_sensitivity": sens, "rec_specificity": spec,
            "rec_precision": prec, "rec_f1": f1}


# ----------------------------------------------------------------------
def _median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


_PREPRINT_RE = re.compile(r"preprint|arxiv|biorxiv|medrxiv|ssrn|research square",
                          re.I)


def corpus_profile(records: Sequence[Record]) -> Dict[str, float]:
    """Metadata-completeness profile of a record set.

    Cross-disciplinary differences in deduplication accuracy are usually
    differences in the metadata the databases supply, not in the algorithm, so
    any accuracy table is uninterpretable without this alongside it: the share
    of records carrying a DOI, an abstract, an author list and page numbers, the
    typical title length, and the share of preprints.
    """
    n = len(records)
    if not n:
        return {"n": 0}
    titles = [len((r.title or "").split()) for r in records]
    return {
        "n": n,
        "pct_doi": 100.0 * sum(1 for r in records if r.doi) / n,
        "pct_pmid": 100.0 * sum(1 for r in records if r.pmid) / n,
        "pct_abstract": 100.0 * sum(1 for r in records if r.abstract) / n,
        "pct_authors": 100.0 * sum(1 for r in records if r.authors) / n,
        "pct_year": 100.0 * sum(1 for r in records if r.year) / n,
        "pct_journal": 100.0 * sum(1 for r in records if r.journal) / n,
        "pct_pages": 100.0 * sum(1 for r in records if r.pages) / n,
        "pct_volume": 100.0 * sum(1 for r in records if r.volume) / n,
        "median_title_words": _median(titles),
        "median_authors": _median([len(r.authors) for r in records]),
        "pct_preprint": 100.0 * sum(
            1 for r in records
            if _PREPRINT_RE.search((r.doc_type or "") + " " + (r.journal or ""))
        ) / n,
        "pct_diacritics": 100.0 * sum(
            1 for r in records if _has_diacritics(r.title)) / n,
    }


# ----------------------------------------------------------------------
# Controlled perturbations
# ----------------------------------------------------------------------
_MONTH_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

_RANGE_RE = re.compile(r"^\s*(\d{1,4})\s*[-\u2013]\s*(\d{1,4})\s*$")


def excel_mangle_pages(value: str) -> str:
    """Render a page range as the date a spreadsheet would turn it into.

    The inverse of :func:`corpusslr.dedup.excel_mangled_pages`: given ``"11-9"``
    return ``"11-Sep"``, given ``"11-19"`` return ``"Nov-19"``.  Used to inject
    the corruption on purpose, so that the guard which tolerates it can be
    measured rather than asserted.

    Returns ``""`` when no spreadsheet would misread the value (both parts
    greater than 12, or the field is not a plain numeric range), which marks the
    record as out of scope for this perturbation.
    """
    m = _RANGE_RE.match(value or "")
    if not m:
        return ""
    a, b = int(m.group(1)), int(m.group(2))
    if 1 <= b <= 12 and 1 <= a <= 31:
        return "{}-{}".format(a, _MONTH_ABBR[b - 1])
    if 1 <= a <= 12 and 1 <= b <= 99:
        return "{}-{:02d}".format(_MONTH_ABBR[a - 1], b)
    return ""


def _has_diacritics(text: Optional[str]) -> bool:
    if not text:
        return False
    if any(ch in text for ch in "\u0142\u0141\u00f8\u00d8\u0111\u00df\u00e6\u0153"):
        return True
    return any(unicodedata.combining(c)
               for c in unicodedata.normalize("NFKD", text))


def _strip_diacritics(text: str) -> str:
    table: Dict[str, Optional[Union[str, int]]] = {
        "\u0142": "l", "\u0141": "L", "\u00f8": "o", "\u00d8": "O",
        "\u0111": "d", "\u0110": "D", "\u00df": "ss", "\u00e6": "ae",
        "\u0153": "oe", "\u0131": "i"}
    out = text.translate(str.maketrans(table))
    out = unicodedata.normalize("NFKD", out)
    return "".join(c for c in out if not unicodedata.combining(c))


#: Subtitles appended by :func:`_add_subtitle`.  Deliberately generic and
#: discipline-neutral: the point is that one database stored a subtitle the
#: other dropped, not that the wording is plausible for a specific field.
_SUBTITLES = (
    ": evidence from a longitudinal study",
    ": a systematic review and meta-analysis",
    ": theory and empirical evidence",
    ": a comparative analysis",
)


def _truncate_title(rec: Record, rng: random.Random) -> bool:
    words = (rec.title or "").split()
    if len(words) < 8:
        return False        # too short to truncate without destroying identity
    keep = max(4, int(len(words) * 0.6))
    rec.title = " ".join(words[:keep])
    return True


def _add_subtitle(rec: Record, rng: random.Random) -> bool:
    if not rec.title:
        return False
    if ":" in rec.title:
        return False        # already carries a subtitle
    rec.title = rec.title.rstrip(" .") + rng.choice(_SUBTITLES)
    return True


def _upper_title(rec: Record, rng: random.Random) -> bool:
    if not rec.title or rec.title == rec.title.upper():
        return False
    rec.title = rec.title.upper()
    return True


def _drop_authors(rec: Record, rng: random.Random) -> bool:
    if not rec.authors:
        return False
    rec.authors = []
    return True


def _shift_year(rec: Record, rng: random.Random) -> bool:
    if rec.year is None:
        return False
    rec.year = rec.year + rng.choice((-1, 1))
    return True


def _translit(rec: Record, rng: random.Random) -> bool:
    hit = False
    if _has_diacritics(rec.title):
        rec.title = _strip_diacritics(rec.title)
        hit = True
    authors = []
    for a in rec.authors:
        if _has_diacritics(a):
            authors.append(_strip_diacritics(a))
            hit = True
        else:
            authors.append(a)
    rec.authors = authors
    return hit


def _excel_pages(rec: Record, rng: random.Random) -> bool:
    mangled = excel_mangle_pages(rec.pages)
    if not mangled:
        return False
    rec.pages = mangled
    return True


#: name -> in-place mutator returning True when the record was in scope.
PERTURBATIONS: Dict[str, Callable[[Record, random.Random], bool]] = {
    "truncated_title": _truncate_title,
    "added_subtitle": _add_subtitle,
    "uppercase_title": _upper_title,
    "missing_authors": _drop_authors,
    "year_off_by_one": _shift_year,
    "transliterated": _translit,
    "excel_mangled_pages": _excel_pages,
}


def apply_perturbation(record: Record, name: str,
                       rng: Optional[random.Random] = None) -> Optional[Record]:
    """Return a perturbed deep copy of *record*, or ``None`` if out of scope.

    ``None`` is the load-bearing part of the contract.  A transliteration
    perturbation applied to an all-ASCII title changes nothing, and counting
    that record as "survived the perturbation" would inflate measured
    robustness.  Callers must therefore score only the records for which this
    function returned a copy, and report that count as the denominator.
    """
    if name not in PERTURBATIONS:
        raise ValueError("unknown perturbation: {}".format(name))
    clone = copy.deepcopy(record)
    if not PERTURBATIONS[name](clone, rng or random.Random(0)):
        return None
    return clone
