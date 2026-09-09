"""Classification of information sources as *principal* or *supplementary*.

Gusenbauer & Haddaway (2020, *Research Synthesis Methods* 11:181-217)
evaluated 28 academic search systems against the requirements of systematic
searching - reproducible boolean queries, field-level operators, a stable and
fully retrievable result set, and export of all hits - and concluded that only
14 of them qualify as **principal search systems**, i.e. systems on which the
evidence base of a review may rest.  The remaining systems, including Google
Scholar and most open bibliographic APIs, are **supplementary**: valuable for
coverage checks, citation chasing and grey-literature discovery, but unable to
support a reproducible primary search.

This module encodes that distinction so that a CorpusSLR corpus can be audited
before the review is written, rather than after a reviewer objects.  The
warnings raised by :func:`audit_strategy` are deliberately anchored in the
methodological literature:

* **no principal source at all** - the search cannot be described as
  systematic in the Gusenbauer & Haddaway sense; this is a critical finding;
* **exactly one principal source** - single-database searching is the best
  documented recall failure in the field.  Bramer et al. (2017,
  *Systematic Reviews* 6:245) found that adequate recall (98.3% overall in
  their prospective sample of reviews) required the *combination* of Embase,
  MEDLINE, Web of Science Core Collection and Google Scholar, with any single
  database falling well short;
* **supplementary-dominated corpus** - when more than half of the identified
  records come from supplementary systems, the corpus is shaped mainly by
  non-reproducible relevance ranking.

Matching is normalized rather than exact: database names arrive from user
input, file exports and API clients in many spellings ("Web of Science",
"WoS", "Web of Science Core Collection", "PubMed/MEDLINE"), and an audit that
silently returned ``"unknown"`` for a misspelling would be worse than none.

**The tiers are not all equally attributable, and the module says so.**
Gusenbauer & Haddaway name 14 principal systems; CorpusSLR's registry also
covers databases they assessed only through an access platform (Embase via
OVID, Business Source via EbscoHost) and one, IEEE Xplore, that their
assessment does *not* place in the principal set -- it is there because
software-engineering review guidance treats IEEE Xplore and the ACM Digital
Library as the field's core pair. :data:`SOURCE_EVIDENCE` records which case
each entry is, and :func:`source_note` returns the caveat to put in a methods
section, so a review can cite the classification accurately instead of
attributing all of it to one paper.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

PRINCIPAL = "principal"
SUPPLEMENTARY = "supplementary"
UNKNOWN = "unknown"

#: Canonical database name -> tier.  Keys are the names CorpusSLR prints in
#: the PRISMA-S appendix; recognition of variants is handled by
#: :func:`classify_source`.
SOURCE_TIER: Dict[str, str] = {
    # -- principal search systems -------------------------------------------
    # Provenance per entry is in SOURCE_EVIDENCE below: most are named in
    # Gusenbauer & Haddaway's principal list, some inherit the tier from a
    # listed access platform, and IEEE Xplore is a field-convention choice that
    # their assessment does NOT support. Do not cite this dict as a whole to
    # them; cite the entry's evidence level.
    "Scopus": PRINCIPAL,
    "Web of Science Core Collection": PRINCIPAL,
    "PubMed/MEDLINE": PRINCIPAL,
    "Embase": PRINCIPAL,
    "Cochrane CENTRAL": PRINCIPAL,
    "EBSCOhost Business Source": PRINCIPAL,
    "EBSCOhost PsycINFO": PRINCIPAL,
    "EBSCOhost CINAHL": PRINCIPAL,
    "EBSCOhost ERIC": PRINCIPAL,
    "ProQuest ABI/INFORM": PRINCIPAL,
    "IEEE Xplore": PRINCIPAL,
    "ACM Digital Library": PRINCIPAL,
    # -- supplementary systems ---------------------------------------------
    "Crossref": SUPPLEMENTARY,
    "OpenAlex": SUPPLEMENTARY,
    "Semantic Scholar": SUPPLEMENTARY,
    "arXiv": SUPPLEMENTARY,
    "bioRxiv": SUPPLEMENTARY,
    "medRxiv": SUPPLEMENTARY,
    "Google Scholar": SUPPLEMENTARY,
    "Dimensions": SUPPLEMENTARY,
    "Lens.org": SUPPLEMENTARY,
}

#: Why each entry carries its tier.  Encoding the *provenance* of a
#: classification matters as much as the classification itself: a reviewer who
#: checks the cited source must find the entry there, and three of the levels
#: below are weaker than a direct citation.
#:
#: ``"listed"``
#:     The system is named in the principal list of Gusenbauer & Haddaway
#:     (2020), section 6: ACM Digital Library, BASE, ClinicalTrials.gov,
#:     Cochrane Library, EbscoHost, OVID, ProQuest, PubMed, ScienceDirect,
#:     Scopus, TRID, Virtual Health Library, Web of Science, Wiley Online
#:     Library.
#: ``"platform"``
#:     The *access platform* is in that list but this particular database was
#:     not individually tested, so the tier is inherited from the platform.
#:     PRISMA-S requires reporting the platform alongside the database, which
#:     is exactly why this distinction is kept rather than flattened.
#: ``"field-convention"``
#:     NOT principal in Gusenbauer & Haddaway, but treated as a core source by
#:     discipline-specific guidance.  The tier follows the published
#:     assessment; the note records the tension.
#: ``"not-principal"``
#:     Assessed and found unsuitable as a principal system.
SOURCE_EVIDENCE: Dict[str, str] = {
    "Scopus": "listed",
    "Web of Science Core Collection": "listed",
    "PubMed/MEDLINE": "listed",
    "ACM Digital Library": "listed",
    "Cochrane CENTRAL": "listed",          # via the Cochrane Library
    "EBSCOhost CINAHL": "listed",          # EbscoHost tested for CINAHL Plus
    "EBSCOhost ERIC": "listed",            # EbscoHost tested for ERIC
    "EBSCOhost PsycINFO": "platform",      # PsychINFO tested via OVID
    "EBSCOhost Business Source": "platform",
    "Embase": "platform",                  # tested via OVID, not EbscoHost
    "ProQuest ABI/INFORM": "platform",
    "IEEE Xplore": "field-convention",
    "Google Scholar": "not-principal",
    "Crossref": "not-assessed",
    "OpenAlex": "not-assessed",
    "Semantic Scholar": "not-assessed",
    "arXiv": "not-assessed",
    "bioRxiv": "not-assessed",
    "medRxiv": "not-assessed",
    "Dimensions": "not-assessed",
    "Lens.org": "not-assessed",
}

#: Caveats a review's methods section should carry, keyed by canonical name.
SOURCE_NOTES: Dict[str, str] = {
    "IEEE Xplore": (
        "Gusenbauer & Haddaway (2020) tested IEEE Xplore among their 28 systems "
        "but did not include it in the 14 they qualify as principal search "
        "systems. Software-engineering review guidance nonetheless treats IEEE "
        "Xplore and the ACM Digital Library as the core pair for the field, so "
        "CorpusSLR keeps it at principal tier for engineering and computing "
        "reviews while recording that the tier does not rest on Gusenbauer & "
        "Haddaway. Report it as a field-convention choice, not as their finding."),
    "bioRxiv": (
        "Preprint repository, supplementary tier: grey literature under PRISMA "
        "2020 Item 6. The Cold Spring Harbor content API offers date-window "
        "listing only -- no boolean, field or full-text search -- so CorpusSLR "
        "downloads the window and applies the query terms client-side as "
        "case- and diacritic-insensitive substring matching over title, "
        "abstract and category. Recall is therefore lower than a database "
        "search with the same terms; report the date window as the search "
        "limit and the filtering as local, not as an executed boolean query. "
        "Measured page size is 30 records per cursor step (not the 100 the "
        "endpoint documentation implies), so retrieval is driven by "
        "messages.total."),
    "medRxiv": (
        "Preprint repository, supplementary tier: grey literature under PRISMA "
        "2020 Item 6. Same Cold Spring Harbor content API and the same "
        "limitation as bioRxiv -- date-window listing only, query terms "
        "applied client-side by substring matching over title, abstract and "
        "category. Report the date window as the search limit."),
    "Embase": (
        "Assessed by Gusenbauer & Haddaway through the OVID platform. Embase "
        "accessed through a different platform may not offer the same query "
        "reproducibility, which is why PRISMA-S asks for database and platform "
        "together."),
    "EBSCOhost Business Source": (
        "The EbscoHost platform qualifies as principal, but Business Source was "
        "not among the databases individually tested (ERIC, MEDLINE, EconLit, "
        "CINAHL Plus, SportsDiscus)."),
    "EBSCOhost PsycINFO": (
        "PsycINFO was assessed through the OVID platform, not EbscoHost. Both "
        "platforms qualify as principal, but their query syntax and export "
        "behaviour differ, so report which one was used (PRISMA-S item 1 names\n"
        "the database with its platform; item 2 covers several databases on\n"
        "one platform)."),
    "ProQuest ABI/INFORM": (
        "The ProQuest platform qualifies as principal, but ABI/INFORM was not "
        "among the databases individually tested (Nursing & Allied Health, "
        "Public Health)."),
    "Google Scholar": (
        "Explicitly found inadequate as a principal search system: results are "
        "not reproducible and retrieval is capped. Bramer et al. (2017) "
        "nonetheless found it contributes unique references, so it belongs in a "
        "search as a supplementary source, never as the basis of one."),
}

#: Regular expressions recognizing name variants, evaluated in order.  The
#: first match wins, so more specific patterns (EBSCOhost databases, Cochrane)
#: precede the broader platform patterns.
_PATTERNS = [
    # --- principal ---------------------------------------------------------
    (r"\bscopus\b|elsevier scopus", "Scopus"),
    ((r"\bwos\b|\bwoscc\b|web of science|web of knowledge|"
      r"\bsci ?expanded\b|social sciences citation index|\bssci\b|\bscie\b"),
     "Web of Science Core Collection"),
    # "central" alone is ambiguous (ProQuest Central), so it only counts with
    # Cochrane context or the full register name.
    ((r"\bcochrane\b|central register of controlled trials|"
      r"controlled trials register"), "Cochrane CENTRAL"),
    (r"\bembase\b|excerpta medica", "Embase"),
    (r"\bpubmed\b|\bmedline\b|\bpmc\b|ncbi|entrez|e-?utilities",
     "PubMed/MEDLINE"),
    (r"\bpsyc ?info\b|\bpsyclit\b", "EBSCOhost PsycINFO"),
    (r"\bcinahl\b|cumulative index to nursing", "EBSCOhost CINAHL"),
    (r"\beric\b|education resources information", "EBSCOhost ERIC"),
    (r"business source|\bbspremier\b|\bbsc\b|\bebsco", "EBSCOhost Business Source"),
    (r"abi/?inform|\babi\b|\bproquest\b", "ProQuest ABI/INFORM"),
    (r"ieee ?xplore|\bieee\b|\biel\b", "IEEE Xplore"),
    (r"\bacm\b|association for computing machinery|acm ?dl", "ACM Digital Library"),
    # --- supplementary -----------------------------------------------------
    (r"\bcrossref\b|cross ?ref", "Crossref"),
    (r"\bopen ?alex\b", "OpenAlex"),
    (r"semantic ?scholar|\bs2ag\b|\bs2\b|allen institute", "Semantic Scholar"),
    (r"\barxiv\b", "arXiv"),
    (r"\bbio ?rxiv\b", "bioRxiv"),
    (r"\bmed ?rxiv\b", "medRxiv"),
    (r"google ?scholar|\bgscholar\b|publish or perish", "Google Scholar"),
    (r"\bdimensions\b|digital science", "Dimensions"),
    (r"\blens\b|lens\.?org", "Lens.org"),
]

_COMPILED = [(re.compile(p, re.I), canon) for p, canon in _PATTERNS]
_PUNCT = re.compile(r"[^a-z0-9./ ]+")
_WS = re.compile(r"\s+")


def _normalize(name: Optional[str]) -> str:
    if not name:
        return ""
    n = str(name).lower()
    n = _PUNCT.sub(" ", n)
    return _WS.sub(" ", n).strip()


def canonical_source(name: Optional[str]) -> str:
    """Resolve a free-form database name to its canonical registry key.

    Returns ``""`` when the name matches nothing known, so that callers can
    distinguish "unrecognized" from "recognized but supplementary".
    """
    n = _normalize(name)
    if not n:
        return ""
    for canon in SOURCE_TIER:
        if _normalize(canon) == n:
            return canon
    for rx, canon in _COMPILED:
        if rx.search(n):
            return canon
    return ""


def classify_source(name: Optional[str]) -> str:
    """Return ``"principal"``, ``"supplementary"`` or ``"unknown"``."""
    canon = canonical_source(name)
    return SOURCE_TIER.get(canon, UNKNOWN)


# ----------------------------------------------------------------------
def source_evidence(name: Optional[str]) -> str:
    """Return how a source's tier is evidenced (see :data:`SOURCE_EVIDENCE`).

    ``"listed"`` means the system is named in Gusenbauer & Haddaway's principal
    set; ``"platform"`` that only its access platform was assessed;
    ``"field-convention"`` that discipline guidance, not that assessment,
    supports the tier; ``"not-principal"`` that it was assessed and rejected;
    ``"not-assessed"`` that it postdates or fell outside their sample. Returns
    ``""`` for an unrecognized name.
    """
    canon = canonical_source(name)
    return SOURCE_EVIDENCE.get(canon, "") if canon else ""


def source_note(name: Optional[str]) -> str:
    """Return the methods-section caveat for *name*, or ``""`` if none applies.

    Sources whose tier does not rest directly on Gusenbauer & Haddaway carry a
    note explaining what to report instead, so that a review's methods section
    can attribute the classification accurately.
    """
    canon = canonical_source(name)
    return SOURCE_NOTES.get(canon, "") if canon else ""


def audit_strategy(corpus) -> dict:
    """Audit a corpus's source mix against Gusenbauer & Haddaway (2020).

    Accepts any object exposing ``searches`` (a list of
    :class:`~corpusslr.corpus.SearchEvent`); records are counted from
    ``records_retrieved``.  Returns a dictionary with per-tier source lists,
    record counts, the supplementary share and a list of warnings, each a
    ``dict`` with ``level`` (``"critical"`` or ``"warning"``), ``code`` and
    ``message``.
    """
    tiers: Dict[str, Dict[str, int]] = {PRINCIPAL: {}, SUPPLEMENTARY: {},
                                        UNKNOWN: {}}
    per_source: Dict[str, dict] = {}
    for ev in getattr(corpus, "searches", []) or []:
        raw_name = getattr(ev, "database", "") or ""
        canon = canonical_source(raw_name)
        tier = SOURCE_TIER.get(canon, UNKNOWN)
        label = canon or (raw_name or "(unnamed source)")
        n = int(getattr(ev, "records_retrieved", 0) or 0)
        tiers[tier][label] = tiers[tier].get(label, 0) + n
        entry = per_source.setdefault(
            label, {"tier": tier, "records": 0, "searches": 0,
                    "names_seen": []})
        entry["records"] += n
        entry["searches"] += 1
        if raw_name and raw_name not in entry["names_seen"]:
            entry["names_seen"].append(raw_name)

    counts = {t: sum(d.values()) for t, d in tiers.items()}
    total = sum(counts.values())
    principal_sources = sorted(tiers[PRINCIPAL])
    supplementary_sources = sorted(tiers[SUPPLEMENTARY])
    unknown_sources = sorted(tiers[UNKNOWN])
    share = (counts[SUPPLEMENTARY] / total) if total else 0.0

    warnings: List[dict] = []
    if not principal_sources:
        warnings.append({
            "level": "critical", "code": "no_principal",
            "message": (
                "No principal search system was searched. Of the 28 systems "
                "evaluated by Gusenbauer & Haddaway (2020), only 14 support "
                "reproducible boolean searching with a fully retrievable "
                "result set; a corpus built exclusively from supplementary "
                "systems cannot be described as a systematic search. Add at "
                "least one principal database (e.g. Scopus, Web of Science "
                "Core Collection, PubMed/MEDLINE, Embase).")})
    elif len(principal_sources) == 1:
        warnings.append({
            "level": "warning", "code": "single_principal",
            "message": (
                "Only one principal search system was searched ({}). Single-"
                "database searching is a documented recall failure: Bramer "
                "et al. (2017, Systematic Reviews 6:245) reached adequate "
                "recall (98.3%) only by combining Embase, MEDLINE, Web of "
                "Science Core Collection and Google Scholar, with no single "
                "database sufficient on its own. "
                "Justify the restriction explicitly or add a second "
                "principal database.".format(principal_sources[0]))})
    if total and share > 0.5:
        warnings.append({
            "level": "warning", "code": "supplementary_majority",
            "message": (
                "{:.1f}% of identified records ({} of {}) come from "
                "supplementary systems, whose relevance ranking is not "
                "reproducible and whose result sets are not guaranteed to be "
                "complete. Report this share in the limitations section and "
                "verify that the principal searches were not "
                "under-specified.".format(share * 100, counts[SUPPLEMENTARY],
                                          total))})
    # A tier that does not rest directly on the cited assessment must be
    # reported as such, or the review misattributes its own classification.
    # These are reporting notes, not defects in the strategy, so they are kept
    # out of `warnings`: a corpus whose only remark is "report the platform too"
    # is a clean strategy, and folding the note into the warning list would make
    # every well-built search look flawed.
    notes: List[dict] = []
    qualified = [s for s in principal_sources
                 if SOURCE_EVIDENCE.get(s) in ("platform", "field-convention")]
    if qualified:
        notes.append({
            "level": "note", "code": "tier_provenance",
            "message": (
                "The principal tier of {} is not taken directly from Gusenbauer "
                "& Haddaway (2020): it is inherited from an access platform they "
                "assessed, or follows discipline-specific guidance instead. "
                "Report the platform alongside the database as PRISMA-S item 1 "
                "requires, and see source_note() for the wording to use."
                .format(", ".join(qualified))),
            "sources": qualified})
    if unknown_sources:
        warnings.append({
            "level": "warning", "code": "unclassified_source",
            "message": (
                "Source(s) not present in the CorpusSLR registry: {}. "
                "Classify them manually as principal or supplementary in the "
                "PRISMA-S appendix.".format(", ".join(unknown_sources)))})

    return {
        "principal": principal_sources,
        "supplementary": supplementary_sources,
        "unknown": unknown_sources,
        "records": {PRINCIPAL: counts[PRINCIPAL],
                    SUPPLEMENTARY: counts[SUPPLEMENTARY],
                    UNKNOWN: counts[UNKNOWN]},
        "records_by_source": {k: v["records"] for k, v in per_source.items()},
        "per_source": per_source,
        "total_records": total,
        "supplementary_share": share,
        "warnings": warnings,
        "notes": notes,
        "n_principal": len(principal_sources),
    }


def audit_markdown(corpus) -> str:
    """Render :func:`audit_strategy` as a Markdown section for the appendix."""
    a = audit_strategy(corpus)
    total = a["total_records"]
    lines = [
        "## Search-system classification [Gusenbauer & Haddaway, 2020]",
        "",
        ("Sources are classified as *principal* (systems meeting the "
         "requirements for a reproducible systematic search) or "
         "*supplementary* (systems suitable for coverage checks, citation "
         "chasing and grey literature, but not for the primary search)."),
        "",
        "| Database | Tier | Searches | Records | Share of identified |",
        "|----------|------|----------|---------|---------------------|",
    ]
    order = {PRINCIPAL: 0, SUPPLEMENTARY: 1, UNKNOWN: 2}
    for label in sorted(a["per_source"],
                        key=lambda k: (order[a["per_source"][k]["tier"]],
                                       -a["per_source"][k]["records"], k)):
        e = a["per_source"][label]
        pct = (100.0 * e["records"] / total) if total else 0.0
        lines.append("| {} | {} | {} | {} | {:.1f}% |".format(
            label, e["tier"], e["searches"], e["records"], pct))
    if not a["per_source"]:
        lines.append("| (no searches recorded) | - | 0 | 0 | 0.0% |")
    lines += [
        "",
        "Principal systems searched: **{}**; supplementary: **{}**; "
        "unclassified: **{}**.".format(a["n_principal"],
                                       len(a["supplementary"]),
                                       len(a["unknown"])),
        "Records from supplementary systems: **{} of {} ({:.1f}%)**.".format(
            a["records"][SUPPLEMENTARY], total,
            a["supplementary_share"] * 100),
        "",
    ]
    if a["warnings"]:
        lines.append("### Strategy warnings")
        lines.append("")
        for w in a["warnings"]:
            lines.append("- **{}**: {}".format(w["level"].upper(),
                                               w["message"]))
        lines.append("")
    if a.get("notes"):
        lines.append("### Reporting notes")
        lines.append("")
        for n in a["notes"]:
            lines.append("- {}".format(n["message"]))
        for src in {s for n in a["notes"] for s in n.get("sources", ())}:
            note = SOURCE_NOTES.get(src)
            if note:
                lines.append("  - *{}*: {}".format(src, note))
        lines.append("")
    if not a["warnings"]:
        # Reporting notes do not cancel this: they ask for extra detail in the
        # write-up, they do not indicate a defect in the strategy itself.
        lines += [("No strategy warnings: the corpus rests on more than one "
                   "principal search system and supplementary systems do not "
                   "dominate the identified records."), ""]
    return "\n".join(lines)
