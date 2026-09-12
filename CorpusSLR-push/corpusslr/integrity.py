"""Publication-integrity flags: retractions, withdrawals, concerns, errata.

A retracted study that reaches synthesis is a review-level error, and one that
reaches it *unnoticed* is the kind that gets a review retracted in turn. Cochrane
and PRISMA 2020 both require that retraction status be checked, yet a database
search returns retracted articles alongside sound ones with nothing but a title
prefix to distinguish them -- when even that survives the export.

This module flags rather than filters. Two reasons: a retraction notice is a
legitimate record in its own right (a review may need to cite it), and the
decision to exclude a study belongs to the reviewer, documented in the PRISMA
flow, not to a library silently dropping rows. What the library owes the reviewer
is that nothing arrives unflagged.

Detection is title/type-based and therefore a *floor*, not a guarantee: a
publisher that retracts without amending the title in the metadata cannot be
caught this way. :func:`retraction_flags` says so in its report, and
``check_retractions_online`` is the escalation path for a corpus where the answer
has to be authoritative.
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Tuple, cast

from .record import Record

#: Title patterns publishers use to mark integrity events. Ordered so the more
#: specific notice forms are tested before the bare adjective.
_PATTERNS: Tuple[Tuple[str, str], ...] = (
    ("retraction_notice", r"^\s*retraction\s*(note|notice|statement)\b"),
    ("retraction_notice", r"^\s*retraction\s*:"),
    ("retraction_notice", r"^\s*(this article has been retracted)\b"),
    ("retracted", r"^\s*retracted\s*(article|paper)?\s*[:\-]"),
    ("retracted", r"^\s*\[?retracted\]?\s*:"),
    ("retracted", r"\bretracted\s+article\b"),
    ("withdrawn", r"^\s*withdrawn\s*[:\-]"),
    ("withdrawn", r"^\s*withdrawal\s*(note|notice)?\s*[:\-]"),
    ("withdrawn", r"\barticle\s+withdrawn\b"),
    ("concern", r"expression\s+of\s+concern"),
    ("erratum", r"^\s*(erratum|corrigendum)\s*[:\-]"),
    ("erratum", r"^\s*(erratum|corrigendum)\s+(to|for|in)\b"),
)

_COMPILED = tuple((label, re.compile(rx, re.I)) for label, rx in _PATTERNS)

#: Document types that databases use for integrity notices. Scopus reports
#: ``subtypeDescription`` "Erratum"; Crossref uses ``retraction`` and
#: ``correction`` types; PubMed publication types include "Retracted
#: Publication" and "Retraction of Publication".
_TYPE_FLAGS: Dict[str, str] = {
    "retraction": "retraction_notice",
    "retraction of publication": "retraction_notice",
    "retracted publication": "retracted",
    "withdrawn": "withdrawn",
    "erratum": "erratum",
    "corrigendum": "erratum",
    "correction": "erratum",
    "expression of concern": "concern",
}

#: Flags that mean "do not include this study in the synthesis".
EXCLUDING_FLAGS = frozenset({"retracted", "withdrawn"})

#: Flags that mean "this record is a notice about another publication".
NOTICE_FLAGS = frozenset({"retraction_notice", "erratum", "concern"})


def integrity_flag(record: Record) -> Optional[str]:
    """Return the integrity flag for one record, or ``None``.

    Checks the document type first, because a database that types a record as a
    retraction is making an explicit statement, whereas a title prefix is a
    convention that survives export inconsistently.
    """
    dt = (record.doc_type or "").strip().lower()
    if dt in _TYPE_FLAGS:
        return _TYPE_FLAGS[dt]
    title = record.title or ""
    for label, rx in _COMPILED:
        if rx.search(title):
            return label
    return None


def retraction_flags(records: Iterable[Record]) -> Dict[str, object]:
    """Flag integrity events across a corpus and report what was found.

    Returns a dict with ``by_flag`` (counts), ``flagged`` (position in the input
    sequence -> flag), ``excluded_candidates`` (records that should not enter
    synthesis), ``notices`` (records that are notices about other work), and
    ``caveat`` -- which is not decoration: this check reads titles and document
    types, so its recall depends on the publisher having amended them.

    ``flagged`` is keyed by input position, not by ``uid``: a record only
    acquires a uid when it passes through deduplication, so keying by uid
    collapsed every freshly parsed record onto the same empty key and lost all
    but one flag. Positions are always distinct. ``flagged_uids`` is provided as
    well for corpora that have been deduplicated.
    """
    flagged: Dict[int, str] = {}
    flagged_uids: Dict[str, str] = {}
    by_flag: Dict[str, int] = {}
    excluded: List[Record] = []
    notices: List[Record] = []
    total = 0
    for idx, rec in enumerate(records):
        total += 1
        flag = integrity_flag(rec)
        if not flag:
            continue
        flagged[idx] = flag
        if rec.uid:
            flagged_uids[rec.uid] = flag
        by_flag[flag] = by_flag.get(flag, 0) + 1
        if flag in EXCLUDING_FLAGS:
            excluded.append(rec)
        elif flag in NOTICE_FLAGS:
            notices.append(rec)
    return {
        "n_records": total,
        "n_flagged": len(flagged),
        "by_flag": by_flag,
        "flagged": flagged,
        "flagged_uids": flagged_uids,
        "excluded_candidates": excluded,
        "notices": notices,
        "caveat": (
            "Detection reads the record's document type and title only. A "
            "publisher that retracts an article without amending either cannot "
            "be detected this way, so this is a lower bound on the retractions "
            "in the corpus, not a clearance. For an authoritative answer, check "
            "the DOIs against Crossref's retraction records or the Retraction "
            "Watch database, and report the date of the check -- retraction "
            "status changes after a search is run."),
    }


def check_retractions_crossref(records: Iterable[Record], session=None,
                               mailto: str = "",
                               max_records: Optional[int] = None) -> Dict[str, object]:
    """Verify retraction status against Crossref's structured relations.

    The title check in :func:`retraction_flags` is a floor: it depends on the
    publisher having amended the title. Crossref records the relation itself --
    a retraction notice carries ``update-to``, and a retracted article carries
    ``updated-by`` -- so this answers the question rather than inferring it.

    One request per DOI, so it is a deliberate step rather than part of
    retrieval. Records without a DOI cannot be checked and are reported as such
    instead of being silently treated as clean. Pass ``mailto`` to identify the
    caller to Crossref as its etiquette asks.

    Returns ``{"checked", "retracted", "notices", "unchecked_no_doi",
    "errors", "checked_on"}`` where ``retracted`` and ``notices`` map DOI to the
    relation Crossref reports.
    """
    import datetime as _dt

    if session is None:  # pragma: no cover - exercised via the injected session
        import requests as _rq
        session = _rq.Session()

    recs = list(records)
    if max_records is not None:
        recs = recs[:max_records]
    retracted: Dict[str, List[str]] = {}
    notices: Dict[str, List[str]] = {}
    no_doi: List[str] = []
    errors: Dict[str, str] = {}
    checked = 0
    for rec in recs:
        if not rec.doi:
            no_doi.append(rec.uid)
            continue
        params = {"mailto": mailto} if mailto else None
        try:
            r = session.get("https://api.crossref.org/works/" + rec.doi,
                            params=params, timeout=30)
            msg = r.json()["message"]
        except Exception as exc:                      # noqa: BLE001
            errors[rec.doi] = "{}: {}".format(type(exc).__name__, str(exc)[:70])
            continue
        checked += 1
        updated_by = {str(u.get("type", "")).lower()
                      for u in (msg.get("updated-by") or [])}
        if updated_by & {"retraction", "withdrawal"}:
            retracted[rec.doi] = sorted(updated_by)
        update_to = {str(u.get("type", "")).lower()
                     for u in (msg.get("update-to") or [])}
        if str(msg.get("type", "")).lower() == "retraction" or \
                update_to & {"retraction", "withdrawal"}:
            notices[rec.doi] = sorted(update_to) or ["retraction"]
    return {
        "checked": checked,
        "retracted": retracted,
        "notices": notices,
        "unchecked_no_doi": no_doi,
        "errors": errors,
        "checked_on": _dt.date.today().isoformat(),
        "caveat": ("Retraction status changes over time, so this answer is "
                   "specific to the date recorded in 'checked_on' and should be "
                   "reported with it. Records without a DOI could not be "
                   "checked and are listed separately rather than assumed sound."),
    }


def integrity_markdown(records: Iterable[Record]) -> str:
    """Render the integrity check as Markdown for a PRISMA-S appendix.

    Written to be pasted into a methods section: it states what was found, what
    the reviewer must decide, and the limits of the check.
    """
    rep = retraction_flags(records)
    by_flag = cast(Dict[str, int], rep["by_flag"])
    excluded = cast(List[Record], rep["excluded_candidates"])
    lines = ["### Publication-integrity check", ""]
    if not rep["n_flagged"]:
        lines += [
            "No record in the corpus of {} carries a retraction, withdrawal, "
            "expression of concern or erratum marker in its title or document "
            "type.".format(rep["n_records"]),
            "",
            "*{}*".format(rep["caveat"]),
        ]
        return "\n".join(lines) + "\n"
    lines += ["{} of {} records carry an integrity marker.".format(
        rep["n_flagged"], rep["n_records"]), "",
        "| Flag | Records | Meaning for the review |",
        "|---|---:|---|"]
    meaning = {
        "retracted": "must not enter synthesis; exclude and record the exclusion",
        "withdrawn": "must not enter synthesis; exclude and record the exclusion",
        "retraction_notice": "a notice about another article, not a study",
        "concern": "assess before inclusion; report the concern",
        "erratum": "a correction notice; cite alongside the corrected article",
    }
    for flag, n in sorted(by_flag.items(), key=lambda kv: -kv[1]):
        lines.append("| `{}` | {} | {} |".format(flag, n, meaning.get(flag, "assess")))
    lines += [""]
    if excluded:
        lines += ["Records that should be excluded from synthesis:", ""]
        for rec in excluded:
            lines.append("- {} ({}{})".format(
                (rec.title or "")[:110], rec.source or "?",
                ", DOI {}".format(rec.doi) if rec.doi else ""))
        lines += [""]
    lines += ["*{}*".format(rep["caveat"])]
    return "\n".join(lines) + "\n"
