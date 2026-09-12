#!/usr/bin/env python
"""Cross-disciplinary validation of CorpusSLR deduplication.

Motivation
----------
CorpusSLR's deduplication is calibrated and validated on the ASySD Diabetes
gold standard (Hair et al. 2023), which is biomedical.  Biomedical
bibliographic data has conventions that other fields do not share: a PMID on
almost every record, conference abstracts printed in journal supplements,
Vancouver-style titles, and near-universal DOI coverage.  A threshold tuned
there may not transfer.  This script tests transfer to four disciplines
(biomedicine, computer science, management, economics) using an
identifier-blind protocol.

Protocol (identifier-blind cross-database matching)
---------------------------------------------------
1. For each discipline, run two or three realistic topical queries against
   several databases that index that discipline: Crossref (all fields),
   Europe PMC (life sciences plus a surprising amount of social science),
   DOAJ (open-access journals across all fields), arXiv (CS, quantitative
   economics), PubMed (biomedicine).  Overlapping coverage produces genuine
   cross-database duplicates with genuine metadata disagreement -- the exact
   situation a review team faces.
2. Ground truth: two records with the same normalized DOI are the same work.
   This is externally verifiable and needs no annotator.
3. Blinding: every identifier field is then deleted (``hide_identifiers``), so
   deduplication has to rebuild those clusters from title, authors, year,
   journal, volume, pages alone.  The truth comes from a hard identifier; the
   ability measured is matching without one.
4. Metrics at *shipped defaults*, per discipline and per query: pairwise
   precision / recall / F1 (primary) and ASySD-style record-level metrics
   (for comparability with the published benchmark).
5. Threshold calibration is reported separately, as a sweep, and never used to
   choose the numbers in step 4.
6. Controlled perturbations (truncated title, added subtitle, uppercase,
   missing authors, year off by one, transliterated diacritics, Excel-mangled
   pages) are injected one at a time into one copy of each duplicate pair, and
   sensitivity is measured per perturbation per discipline.  Records a
   perturbation cannot affect are excluded from its denominator.

Honest limitations are listed in the generated report; the most important are
that records without a DOI cannot enter the truth set, and that two records
sharing a DOI are occasionally *not* the same report (a supplement-wide DOI),
which makes the truth set slightly noisy in the conservative direction.

Usage
-----
Retrieve and cache (network required, ~10 min, polite rate limits)::

    PYTHONPATH=. python validation/eval_multidomain.py --fetch

Evaluate from the cache (no network; this is what a reviewer runs)::

    PYTHONPATH=. python validation/eval_multidomain.py

Outputs (all under ``validation/``): ``multidomain_raw.jsonl.gz`` (cached
normalized records), ``multidomain_metrics.csv``, ``multidomain_profile.csv``,
``multidomain_perturbations.csv``, ``multidomain_calibration.csv``,
``multidomain_validation.png``, ``multidomain_validation.md``.
"""
from __future__ import annotations

import argparse
import collections
import gzip
import json
import os
import random
import re
import sys
import time
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from corpusslr.dedup import deduplicate                              # noqa: E402
from corpusslr.record import Record, normalize_doi                   # noqa: E402
from corpusslr.validate import (PERTURBATIONS, apply_perturbation,   # noqa: E402
                                clusters_from_decisions, corpus_profile,
                                hide_identifiers, pair_metrics,
                                record_metrics, truth_groups)

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "multidomain_raw.jsonl.gz")

# ----------------------------------------------------------------------
# 1. Study design: disciplines, queries, databases
# ----------------------------------------------------------------------
#: Each query is expressed once per database dialect.  Writing the dialects out
#: explicitly rather than compiling them from a single SearchQuery is
#: deliberate: the point of the exercise is that different databases return
#: different metadata for the same work, so the query must be as close to
#: equivalent as each API allows, and the reader must be able to see it.
#:
#: ``max`` caps records per database per query.  The caps are small enough to be
#: polite and large enough that the DOI overlap between databases yields a
#: usable number of duplicate pairs.
QUERIES: List[dict] = [
    # ---------------- biomedicine / biology ----------------
    dict(domain="biomedicine", qid="bio1", label="CRISPR off-target effects",
         crossref="CRISPR Cas9 off-target effects genome editing",
         epmc='(TITLE_ABS:"CRISPR") AND (TITLE_ABS:"off-target")',
         doaj='bibjson.title:("CRISPR" AND "off-target")',
         pubmed='("CRISPR"[Title] AND "off-target"[Title])',
         arxiv=None, max=300),
    dict(domain="biomedicine", qid="bio2", label="gut microbiome obesity",
         crossref="gut microbiome obesity metabolic syndrome",
         epmc='(TITLE:"gut microbiome") AND (TITLE:"obesity")',
         doaj='bibjson.title:("gut microbiome" AND "obesity")',
         pubmed='("gut microbiome"[Title] AND "obesity"[Title])',
         arxiv=None, max=300),
    # ---------------- computer science ----------------
    dict(domain="computer science", qid="cs1",
         label="graph neural networks for drug discovery",
         crossref="graph neural network drug discovery molecular property",
         epmc='(TITLE_ABS:"graph neural network") AND (TITLE_ABS:"drug discovery")',
         doaj='bibjson.title:("graph neural network" AND "drug")',
         pubmed='("graph neural network"[Title/Abstract] AND '
                '"drug discovery"[Title/Abstract])',
         arxiv='(all:"graph neural network" OR all:"graph neural networks") '
               'AND (all:"drug discovery" OR all:"molecular property prediction")',
         max=300),
    dict(domain="computer science", qid="cs2",
         label="federated learning privacy",
         crossref="federated learning differential privacy",
         epmc='(TITLE_ABS:"federated learning") AND (TITLE_ABS:"privacy")',
         doaj='bibjson.title:("federated learning" AND "privacy")',
         pubmed='("federated learning"[Title] AND "privacy"[Title/Abstract])',
         arxiv='(all:"federated learning") AND (all:"differential privacy")',
         max=300),
    # ---------------- management ----------------
    dict(domain="management", qid="mgmt1",
         label="dynamic capabilities and firm performance",
         crossref="dynamic capabilities firm performance",
         epmc='("dynamic capabilities") AND ("firm performance")',
         doaj='bibjson.title:("dynamic capabilit*") OR '
              'bibjson.abstract:("dynamic capabilities" AND "firm performance")',
         pubmed=None,
         arxiv=None, max=300),
    dict(domain="management", qid="mgmt2",
         label="transformational leadership and employee creativity",
         crossref="transformational leadership employee creativity innovation",
         epmc='("transformational leadership") AND ("creativity")',
         doaj='bibjson.title:("transformational leadership") OR '
              'bibjson.abstract:("transformational leadership" AND "creativity")',
         pubmed='("transformational leadership"[Title/Abstract])',
         arxiv=None, max=300),
    # ---------------- economics ----------------
    dict(domain="economics", qid="econ1",
         label="minimum wage and employment",
         crossref="minimum wage employment effects labor market",
         epmc='("minimum wage") AND ("employment")',
         doaj='bibjson.title:("minimum wage") OR '
              'bibjson.abstract:("minimum wage" AND "employment")',
         pubmed='("minimum wage"[Title/Abstract] AND "employment"[Title/Abstract])',
         arxiv='(all:"minimum wage") AND (all:"employment")', max=300),
    dict(domain="economics", qid="econ2",
         label="monetary policy inflation expectations",
         crossref="monetary policy inflation expectations",
         epmc='("monetary policy") AND ("inflation")',
         doaj='bibjson.title:("inflation expectations") OR '
              'bibjson.abstract:("monetary policy" AND "inflation expectations")',
         pubmed=None,
         arxiv='(all:"monetary policy") AND (all:"inflation expectations")',
         max=300),
]


# ----------------------------------------------------------------------
# 2. Retrieval (network; only with --fetch)
# ----------------------------------------------------------------------
def _get(session, url, params, tries: int = 4, pause: float = 1.0):
    """GET with bounded exponential backoff; ``None`` when the host gives up.

    Returning ``None`` rather than raising matters for a multi-database harvest:
    Semantic Scholar's unauthenticated pool answers 429 for long stretches, and
    losing one database must degrade the study (fewer arms, reported as such)
    instead of aborting it.
    """
    for attempt in range(tries):
        try:
            resp = session.get(url, params=params, timeout=90)
        except Exception:                                # network hiccup
            time.sleep(pause * 2 ** attempt)
            continue
        if resp.status_code == 200:
            return resp
        if resp.status_code in (429,) or resp.status_code >= 500:
            time.sleep(pause * 2 ** attempt)
            continue
        return None
    return None


def fetch_crossref(session, query: str, limit: int) -> List[Record]:
    from corpusslr.sources.crossref import _parse_item
    out: List[Record] = []
    cursor = "*"
    seen = {cursor}
    while len(out) < limit:
        resp = _get(session, "https://api.crossref.org/works",
                    {"query.bibliographic": query, "rows": 100,
                     "cursor": cursor})
        if resp is None:
            break
        msg = resp.json().get("message", {})
        items = msg.get("items") or []
        if not items:
            break
        out.extend(_parse_item(it) for it in items)
        cursor = msg.get("next-cursor") or ""
        if not cursor or cursor in seen:
            break
        seen.add(cursor)
    return out[:limit]


def _epmc_record(item: dict) -> Record:
    """Map a Europe PMC ``resultType=core`` hit onto :class:`Record`.

    Europe PMC is used instead of PubMed alone because it also indexes preprint
    servers and a non-trivial slice of social-science journals, which is what
    makes it usable as a second arm for the management and economics queries.
    """
    ji = item.get("journalInfo") or {}
    journal = (ji.get("journal") or {}).get("title", "") or ""
    authors = []
    for a in (item.get("authorList") or {}).get("author", []) or []:
        fam, giv = a.get("lastName", "") or "", a.get("firstName", "") or ""
        if fam:
            authors.append("{}, {}".format(fam, giv) if giv else fam)
        elif a.get("fullName"):
            authors.append(a["fullName"])
    year = ji.get("yearOfPublication") or item.get("pubYear")
    try:
        year = int(year) if year else None
    except (TypeError, ValueError):
        year = None
    src = item.get("source", "")
    return Record(
        title=item.get("title", "") or "",
        abstract=item.get("abstractText", "") or "",
        authors=authors,
        year=year,
        journal=journal,
        doi=item.get("doi", "") or "",
        pmid=item.get("pmid", "") or "",
        issn=(ji.get("journal") or {}).get("issn", "") or "",
        volume=str(ji.get("volume") or ""),
        issue=str(ji.get("issue") or ""),
        pages=item.get("pageInfo", "") or "",
        doc_type="preprint" if src == "PPR" else "article",
        language=item.get("language", "") or "",
        source="EuropePMC",
        source_id="{}:{}".format(src, item.get("id", "")),
    )


def fetch_epmc(session, query: str, limit: int) -> List[Record]:
    out: List[Record] = []
    cursor = "*"
    while len(out) < limit:
        resp = _get(session,
                    "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                    {"query": query, "format": "json", "pageSize": 100,
                     "resultType": "core", "cursorMark": cursor})
        if resp is None:
            break
        data = resp.json()
        items = (data.get("resultList") or {}).get("result") or []
        if not items:
            break
        out.extend(_epmc_record(it) for it in items)
        nxt = data.get("nextCursorMark") or ""
        if not nxt or nxt == cursor:
            break
        cursor = nxt
    return out[:limit]


def _doaj_record(item: dict) -> Record:
    bj = item.get("bibjson", {}) or {}
    doi = ""
    for ident in bj.get("identifier", []) or []:
        if (ident.get("type") or "").lower() == "doi":
            doi = ident.get("id", "") or ""
            break
    journals = bj.get("journal", {}) or {}
    authors = []
    for a in bj.get("author", []) or []:
        nm = a.get("name", "") or ""
        if nm:
            from corpusslr.sources.base import format_author_name
            authors.append(format_author_name(nm))
    start, end = bj.get("start_page", ""), bj.get("end_page", "")
    pages = "{}-{}".format(start, end) if start and end else (start or "")
    try:
        year = int(bj.get("year")) if bj.get("year") else None
    except (TypeError, ValueError):
        year = None
    issns = journals.get("issns") or []
    return Record(
        title=bj.get("title", "") or "",
        abstract=bj.get("abstract", "") or "",
        authors=authors,
        year=year,
        journal=journals.get("title", "") or "",
        doi=doi,
        issn=issns[0] if issns else "",
        volume=str(journals.get("volume") or ""),
        issue=str(journals.get("number") or ""),
        pages=pages,
        doc_type="article",
        language=(journals.get("language") or [""])[0] if journals.get("language") else "",
        keywords=list(bj.get("keywords") or []),
        source="DOAJ",
        source_id=item.get("id", "") or "",
    )


def fetch_doaj(session, query: str, limit: int) -> List[Record]:
    from urllib.parse import quote
    out: List[Record] = []
    page = 1
    while len(out) < limit and page <= 10:
        resp = _get(session,
                    "https://doaj.org/api/search/articles/" + quote(query, safe=""),
                    {"pageSize": 100, "page": page})
        if resp is None:
            break
        items = resp.json().get("results") or []
        if not items:
            break
        out.extend(_doaj_record(it) for it in items)
        page += 1
    return out[:limit]


def fetch_pubmed(session, query: str, limit: int) -> List[Record]:
    from corpusslr.sources.pubmed import parse_pubmed_xml
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    resp = _get(session, base + "esearch.fcgi",
                {"db": "pubmed", "term": query, "retmode": "json",
                 "retmax": min(limit, 500), "tool": "CorpusSLR"})
    if resp is None:
        return []
    ids = (resp.json().get("esearchresult") or {}).get("idlist") or []
    out: List[Record] = []
    for start in range(0, len(ids), 100):
        chunk = ids[start:start + 100]
        fr = _get(session, base + "efetch.fcgi",
                  {"db": "pubmed", "id": ",".join(chunk), "retmode": "xml",
                   "tool": "CorpusSLR"})
        if fr is None:
            break
        out.extend(parse_pubmed_xml(fr.text))
        time.sleep(0.4)
    return out[:limit]


def fetch_arxiv(session, query: str, limit: int) -> List[Record]:
    from corpusslr.sources.arxiv import parse_arxiv_atom
    out: List[Record] = []
    start = 0
    while len(out) < limit:
        resp = _get(session, "http://export.arxiv.org/api/query",
                    {"search_query": query, "start": start,
                     "max_results": min(100, limit - len(out))})
        if resp is None:
            break
        page = parse_arxiv_atom(resp.text)
        if not page:
            break
        out.extend(page)
        start += len(page)
        if len(page) < 100:
            break
        time.sleep(3.0)          # arXiv terms of use
    return out[:limit]


FETCHERS = dict(crossref=fetch_crossref, epmc=fetch_epmc, doaj=fetch_doaj,
                pubmed=fetch_pubmed, arxiv=fetch_arxiv)


def harvest(path: str = CACHE) -> None:
    """Retrieve every (query, database) cell and cache normalized records."""
    import requests
    session = requests.Session()
    from corpusslr import __version__ as _ver
    session.headers.update({"User-Agent":
                            "CorpusSLR/{} validation "
                            "(https://github.com/s-matysik/CorpusSLR)".format(_ver)})
    rows: List[dict] = []
    for spec in QUERIES:
        for db, fetch in FETCHERS.items():
            query = spec.get(db)
            if not query:
                continue
            try:
                recs = fetch(session, query, spec["max"])
            except Exception as exc:                     # keep the harvest alive
                print("  ! {}/{}: {}".format(spec["qid"], db, exc), flush=True)
                recs = []
            print("  {}/{}: {} records".format(spec["qid"], db, len(recs)),
                  flush=True)
            for rec in recs:
                row = rec.to_dict()
                row["_domain"] = spec["domain"]
                row["_qid"] = spec["qid"]
                row["_db"] = db
                rows.append(row)
            time.sleep(1.0)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print("cached {} records -> {}".format(len(rows), path))


def load_cache(path: str = CACHE) -> List[dict]:
    if not os.path.exists(path):
        raise SystemExit("cache missing: run with --fetch first ({})".format(path))
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def rows_to_records(rows: Iterable[dict]) -> List[Record]:
    out = []
    for row in rows:
        meta = {k: v for k, v in row.items() if not k.startswith("_")}
        meta.pop("uid", None)
        meta.pop("provenance", None)
        rec = Record(**meta)
        rec.raw = {}
        out.append(rec)
    return out


# ----------------------------------------------------------------------
# 3. Evaluation
# ----------------------------------------------------------------------
def build_arm(rows: Sequence[dict]) -> Tuple[List[Record], Dict[str, str]]:
    """Assemble one evaluation arm: uid-stamped records plus DOI ground truth.

    Records are stamped with a uid encoding their database of origin, which
    keeps the decision log readable and lets cross-database pairs be counted
    separately from within-database ones.
    """
    records = rows_to_records(rows)
    for n, (rec, row) in enumerate(zip(records, rows), 1):
        rec.uid = "{}-{:05d}".format(row["_db"], n)
        rec.source = rec.source or row["_db"]
    truth = truth_groups(records)
    return records, truth


#: Crossref ``type`` values that are not bibliographic works and that no review
#: team would screen.  ``component`` is the load-bearing one: Crossref registers
#: each supplementary file of an article under its own DOI
#: (``10.1021/acs.jcim.2c01099.s001``) with the *article's* title and no year,
#: journal or pages.  Under a DOI arbiter those files count as works distinct
#: from their own parent article, so correctly recognising them as the same
#: paper is scored as a false positive.  They are excluded by a mechanical rule
#: on the record type, decided before any metric was computed, applied
#: identically in every discipline, and reported as its own arm so the effect of
#: the decision is visible rather than baked in.
NON_WORK_TYPES = frozenset(("component", "peer-review", "grant", "dataset",
                            "other"))

#: DOI prefixes of preprint servers, used only to *classify* false positives,
#: never to exclude records.  A preprint and its journal version carry different
#: DOIs, so the arbiter calls them distinct works, while systematic-review
#: practice treats them as one study and deduplicates them.  Merging such a pair
#: is therefore defensible behaviour scored as an error, and it has to be
#: counted separately from a genuine over-merge.
PREPRINT_PREFIXES = ("10.2139/ssrn", "10.21203/rs", "10.1101/", "10.31234",
                     "10.48550", "10.20944", "10.22541", "10.31235",
                     "10.31219", "10.26434", "10.36227")

#: Working-paper series DOI prefixes.  Economics does not use preprint servers
#: the way physics or biology do; it circulates a paper as a numbered working
#: paper (NBER ``10.3386``, Federal Reserve ``10.17016``, IMF ``10.5089``, World
#: Bank ``10.1596``, IZA/CEPR via SSRN) months or years before the journal
#: version, and Crossref types those as ``report``, not ``posted-content``.  A
#: preprint detector written for biomedicine misses them entirely, which is
#: exactly the kind of discipline-specific convention this study exists to find.
WORKING_PAPER_PREFIXES = ("10.3386", "10.17016", "10.5089", "10.1596",
                          "10.24149", "10.26509", "10.2866", "10.4054")

_BOOK_TYPES = frozenset(("book-chapter", "book", "monograph", "book-part",
                         "book-section", "edited-book", "chapter"))

_REPORT_TYPES = frozenset(("report", "working-paper", "dissertation",
                           "report-component"))

#: Titles differing only by one of these prefixes are a published correction and
#: its target.  Crossref and PubMed register a corrigendum under its own DOI, so
#: the arbiter calls them distinct works; the title differs by two or three
#: words, so fuzzy matching pairs them.  Whether that is desirable is a review
#: policy decision (Cochrane links an erratum to its target rather than merging
#: it), so it is counted in its own category and NOT excused.
_CORRECTION_RE = re.compile(
    r"^\s*(correction|corrigendum|erratum|retraction|addendum|"
    r"editorial expression of concern|expression of concern|comment on|"
    r"reply to|author correction|publisher correction)\b[:\s]", re.I)


def drop_non_works(rows: Sequence[dict]) -> List[dict]:
    """Remove rows whose record type is not a bibliographic work."""
    return [r for r in rows
            if (r.get("doc_type") or "").lower() not in NON_WORK_TYPES]


#: A DOAJ page range of the form ``1-N``.  DOAJ derives ``start_page`` /
#: ``end_page`` from the publisher's article XML, and for the many open-access
#: journals that number articles instead of paginating them (BMC, Frontiers,
#: PLOS, F1000Research, BMJ Open) the publisher supplies the article's *own*
#: page count, so DOAJ stores ``1-15`` for an article that PubMed and Europe PMC
#: both report as article number ``393``.  This is not a page range at all: it
#: is a length.  Diagnosed here because it turned out to be the single largest
#: source of missed duplicates in this study, and because the fix belongs at
#: ingestion (a parser should not emit a coordinate it knows to be fictional)
#: rather than in the matcher.
_PSEUDO_PAGES_RE = re.compile(r"^\s*1\s*[-\u2013]\s*(\d{1,3})\s*$")


def suppress_pseudo_pages(rows: Sequence[dict],
                          source: str = "doaj") -> List[dict]:
    """Blank DOAJ ``1-N`` page ranges, which are page *counts*, not loci.

    Used only for the clearly-labelled sensitivity arm: the headline metrics are
    computed on the records exactly as the APIs returned them.  A first page of
    1 is of course legitimate for the opening article of an issue, so this rule
    is deliberately restricted to one source and to ranges ending below 1000;
    it is a diagnosis of a known DOAJ convention, not a general heuristic.
    """
    out: List[dict] = []
    for row in rows:
        if (row.get("_db") == source
                and _PSEUDO_PAGES_RE.match(row.get("pages") or "")):
            row = dict(row)
            row["pages"] = ""
        out.append(row)
    return out


def _is_preprint(rec: Record) -> bool:
    doi = (rec.doi or "").lower()
    if any(doi.startswith(p) for p in PREPRINT_PREFIXES):
        return True
    return (rec.doc_type or "").lower() in ("preprint", "posted-content")


def _is_working_paper(rec: Record) -> bool:
    doi = (rec.doi or "").lower()
    if any(doi.startswith(p) for p in WORKING_PAPER_PREFIXES):
        return True
    return (rec.doc_type or "").lower() in _REPORT_TYPES


def _is_correction(rec: Record) -> bool:
    if (rec.doc_type or "").lower() in ("published erratum", "erratum",
                                        "retraction", "correction"):
        return True
    return bool(_CORRECTION_RE.match(rec.title or ""))


def classify_false_positive(a: Record, b: Record) -> str:
    """Name the reason a merged pair disagrees with the DOI arbiter.

    Reported because the headline precision figure is not interpretable without
    it.  A pair the arbiter rejects falls into one of several kinds, and only the
    last is unambiguously an algorithm defect:

    ``supplementary_component``
        A Crossref-registered supplementary file matched to its parent article.
        The two carry the same title by construction; no review team screens
        them as separate records.
    ``preprint_vs_published`` / ``working_paper_vs_published`` /
    ``two_preprint_servers``
        Versions of one study circulated under different DOIs.  Cochrane and
        ASySD practice is to treat them as one study for screening, so merging
        them is the behaviour a review team wants -- but the DOI arbiter cannot
        see it, so it is scored as an error.  Reported, not excused.
    ``correction_vs_original``
        A corrigendum or retraction notice matched to the article it corrects.
        Genuinely undesirable (they are separate records with separate roles) but
        a distinct failure mode from confusing two unrelated papers.
    ``book_edition``
        The same chapter in two printings of a book (a hardback and a paperback
        DOI), differing by a page or two.
    ``identical_title_distinct_doi``
        Byte-identical normalized titles under two DOIs with no other
        explanation -- unresolvable without full text.
    ``over_merge``
        Two different works merged.  The only category that is straightforwardly
        a defect.
    """
    if "component" in ((a.doc_type or "").lower(), (b.doc_type or "").lower()):
        return "supplementary_component"
    if _is_correction(a) != _is_correction(b):
        return "correction_vs_original"
    if _is_preprint(a) != _is_preprint(b):
        return "preprint_vs_published"
    if _is_preprint(a) and _is_preprint(b):
        return "two_preprint_servers"
    if _is_working_paper(a) != _is_working_paper(b):
        return "working_paper_vs_published"
    if _is_working_paper(a) and _is_working_paper(b):
        return "two_working_paper_series"
    at, bt = (a.doc_type or "").lower(), (b.doc_type or "").lower()
    if at in _BOOK_TYPES or bt in _BOOK_TYPES:
        return "book_edition"
    if a.norm_title == b.norm_title:
        return "identical_title_distinct_doi"
    return "over_merge"


#: Categories in which the merged pair is two versions of one study.  A review
#: team deduplicating for screening wants these merged, so a second precision
#: figure is reported that does not charge them as errors -- clearly labelled as
#: a *version-tolerant* reading, alongside the strict one, never instead of it.
VERSION_KINDS = frozenset(("preprint_vs_published", "two_preprint_servers",
                           "working_paper_vs_published",
                           "two_working_paper_series", "book_edition",
                           "supplementary_component"))


def false_positive_pairs(records: Sequence[Record], truth: Dict[str, str],
                         **dedup_kw) -> List[Tuple[Record, Record, str]]:
    """Every merged pair the DOI arbiter rejects, with its classification."""
    index = {r.uid: r for r in records}
    blinded = hide_identifiers(records)
    result = deduplicate(blinded, **dedup_kw)
    clusters = clusters_from_decisions(result.report.decisions,
                                       [r.uid for r in blinded])
    out: List[Tuple[Record, Record, str]] = []
    for cluster in clusters:
        judged = [u for u in cluster if u in truth]
        for i in range(len(judged)):
            for j in range(i + 1, len(judged)):
                ua, ub = judged[i], judged[j]
                if truth[ua] == truth[ub]:
                    continue
                a, b = index[ua], index[ub]
                out.append((a, b, classify_false_positive(a, b)))
    return out


def evaluate(records: Sequence[Record], truth: Dict[str, str],
             **dedup_kw) -> Dict[str, float]:
    """Blind the identifiers, deduplicate, and score against *truth*."""
    blinded = hide_identifiers(records)
    result = deduplicate(blinded, **dedup_kw)
    uids = [r.uid for r in blinded]
    clusters = clusters_from_decisions(result.report.decisions, uids)
    out = dict(pair_metrics(clusters, truth))
    out.update(record_metrics(clusters, truth))
    out["clusters"] = result.report.after
    out["removed"] = result.report.removed
    out["fuzzy_merges"] = result.report.by_method.get("fuzzy", 0)
    out["round_candidates"] = result.report.round_candidates
    out["no_candidate_records"] = result.report.records_without_candidates
    return out


def truth_shape(truth: Dict[str, str]) -> Dict[str, int]:
    """Size distribution of the true duplicate groups.

    An arm whose truth set contains only singletons cannot measure recall at
    all: recall is then 0/0.  Reporting the number of multi-record groups and of
    judgeable pairs alongside every metric makes such an arm impossible to
    mistake for a successful one.
    """
    sizes = collections.Counter(truth.values())
    multi = [n for n in sizes.values() if n > 1]
    return dict(truth_records=len(truth), truth_groups=len(sizes),
                truth_multi_groups=len(multi),
                truth_pairs=sum(n * (n - 1) // 2 for n in multi),
                truth_largest_group=max(sizes.values()) if sizes else 0)


# ----------------------------------------------------------------------
# 4. Perturbation study
# ----------------------------------------------------------------------
def perturbation_arm(records: Sequence[Record], truth: Dict[str, str],
                     name: str, seed: int = 11) -> Optional[Dict[str, float]]:
    """Recall after perturbing one member of every true duplicate pair.

    Design: for each true group with two or more records, the *second* member
    (in uid order) is perturbed and the first left alone, so every judgeable
    pair spans a clean and a corrupted copy.  Groups where the perturbation does
    not apply are dropped from both numerator and denominator, and the number
    dropped is reported -- an inapplicable perturbation must not be read as a
    perturbation survived.
    """
    rng = random.Random(seed)
    by_group: Dict[str, List[Record]] = collections.defaultdict(list)
    index = {r.uid: r for r in records}
    for uid, group in truth.items():
        by_group[group].append(index[uid])
    perturbed: List[Record] = []
    scored_truth: Dict[str, str] = {}
    n_applied = n_skipped = 0
    untouched: List[Record] = []
    for group, members in by_group.items():
        members = sorted(members, key=lambda r: r.uid)
        if len(members) < 2:
            untouched.extend(members)
            continue
        victim = apply_perturbation(members[1], name, rng)
        if victim is None:
            n_skipped += 1
            untouched.extend(members)
            continue
        n_applied += 1
        keep = [members[0], victim] + members[2:]
        perturbed.extend(keep)
        for rec in keep:
            scored_truth[rec.uid] = group
    if not n_applied:
        return None
    # Records outside any perturbed group stay in the corpus: they contribute
    # blocking pressure and false-positive opportunities exactly as in the
    # unperturbed run, so precision remains comparable.
    corpus = perturbed + untouched
    metrics = evaluate(corpus, scored_truth)

    # Matched control: the SAME groups, the SAME scored truth, nothing
    # perturbed.  Without it the reported recall drop is uninterpretable,
    # because the groups a perturbation applies to are not a random sample --
    # ``transliterated`` selects records with diacritics, which are also the
    # records most likely to be non-English and hard to match for unrelated
    # reasons.  The quantity of interest is ``recall_delta``, not the absolute
    # recall of the perturbed arm.
    control_records = [index[u] for u in scored_truth]
    control = evaluate(control_records + untouched, scored_truth)

    metrics.update(perturbation=name, groups_perturbed=n_applied,
                   groups_out_of_scope=n_skipped,
                   applicability=n_applied / float(n_applied + n_skipped),
                   control_recall=control["recall"],
                   control_precision=control["precision"],
                   control_f1=control["f1"],
                   recall_delta=metrics["recall"] - control["recall"],
                   precision_delta=metrics["precision"] - control["precision"])
    return metrics


# ----------------------------------------------------------------------
# 5. Main
# ----------------------------------------------------------------------
THRESHOLDS = (0.80, 0.84, 0.87, 0.90, 0.93, 0.95, 0.97, 0.99)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fetch", action="store_true",
                    help="retrieve from the APIs and refresh the cache")
    ap.add_argument("--cache", default=CACHE)
    ap.add_argument("--skip-figure", action="store_true")
    args = ap.parse_args(argv)

    if args.fetch:
        harvest(args.cache)

    all_rows = load_cache(args.cache)
    print("loaded {} cached records".format(len(all_rows)))

    domain_of = {spec["qid"]: spec["domain"] for spec in QUERIES}
    label_of = {spec["qid"]: spec["label"] for spec in QUERIES}

    metric_rows: List[dict] = []
    profile_rows: List[dict] = []
    pert_rows: List[dict] = []
    calib_rows: List[dict] = []
    fp_rows: List[dict] = []

    # Two arms.  "raw" keeps every retrieved record; "curated" drops record
    # types that are not bibliographic works (NON_WORK_TYPES).  Both are
    # reported: the raw arm is the unfiltered protocol, the curated arm is the
    # corpus a review team would actually screen.
    # Three arms.  "raw" keeps every retrieved record.  "curated" drops record
    # types that are not bibliographic works (NON_WORK_TYPES) -- the corpus a
    # review team would actually screen, and the arm the headline numbers come
    # from.  "pseudopages_fixed" additionally blanks DOAJ's fictional 1-N page
    # ranges; it is a diagnosis of an ingestion defect, reported separately and
    # never used as the headline result.
    curated = drop_non_works(all_rows)
    arms = [("raw", all_rows), ("curated", curated),
            ("pseudopages_fixed", suppress_pseudo_pages(curated))]
    print("raw {} records; curated {} records ({} non-work rows dropped)".format(
        len(all_rows), len(curated), len(all_rows) - len(curated)))

    for arm, rows in arms:
        by_query: Dict[str, List[dict]] = collections.defaultdict(list)
        by_domain: Dict[str, List[dict]] = collections.defaultdict(list)
        for row in rows:
            by_query[row["_qid"]].append(row)
            by_domain[row["_domain"]].append(row)

        for qid in sorted(by_query):
            records, truth = build_arm(by_query[qid])
            shape = truth_shape(truth)
            met = evaluate(records, truth)
            metric_rows.append(dict(arm=arm, level="query",
                                    domain=domain_of[qid], qid=qid,
                                    label=label_of[qid], n_records=len(records),
                                    databases=len({r["_db"]
                                                   for r in by_query[qid]}),
                                    **shape, **met))
            if arm == "curated":
                profile_rows.append(dict(level="query", domain=domain_of[qid],
                                         qid=qid, **corpus_profile(records)))
            print("  [{}] {:>6} {:<18} n={:<5} pairs={:<4} P={:.3f} R={:.3f} "
                  "F1={:.3f}".format(arm, qid, domain_of[qid], len(records),
                                     shape["truth_pairs"], met["precision"],
                                     met["recall"], met["f1"]), flush=True)

        for domain in sorted(by_domain):
            records, truth = build_arm(by_domain[domain])
            shape = truth_shape(truth)
            met = evaluate(records, truth)
            metric_rows.append(dict(arm=arm, level="domain", domain=domain,
                                    qid="", label="pooled",
                                    n_records=len(records),
                                    databases=len({r["_db"]
                                                   for r in by_domain[domain]}),
                                    **shape, **met))

            # ---- identifier-visible ceiling: how much of the residual error
            # ---- is truth-set noise rather than blind-matching failure
            res_vis = deduplicate([r for r in records])
            cl_vis = clusters_from_decisions(res_vis.report.decisions,
                                             [r.uid for r in records])
            metric_rows.append(dict(arm=arm, level="identifiers_visible",
                                    domain=domain, qid="",
                                    label="ceiling (DOI visible)",
                                    n_records=len(records),
                                    databases=len({r["_db"]
                                                   for r in by_domain[domain]}),
                                    **shape, **pair_metrics(cl_vis, truth)))

            # ---- false-positive forensics ----
            counts: Dict[str, int] = collections.Counter()
            for a, b, kind in false_positive_pairs(records, truth):
                counts[kind] += 1
                if arm == "curated":
                    fp_rows.append(dict(
                        domain=domain, kind=kind,
                        doi_a=a.doi, doi_b=b.doi,
                        type_a=a.doc_type, type_b=b.doc_type,
                        source_a=a.source, source_b=b.source,
                        title_a=(a.title or "")[:160],
                        title_b=(b.title or "")[:160]))
            version_fp = sum(n for k, n in counts.items() if k in VERSION_KINDS)
            hard_fp = met["pair_fp"] - version_fp
            tp = met["pair_tp"]
            metric_rows[-2].update(
                {"fp_" + k: v for k, v in counts.items()})
            metric_rows[-2].update(
                fp_version_variants=version_fp,
                fp_strict_errors=hard_fp,
                precision_version_tolerant=(
                    (tp + version_fp) / float(tp + met["pair_fp"])
                    if tp + met["pair_fp"] else 1.0),
                precision_excl_versions=(
                    tp / float(tp + hard_fp) if tp + hard_fp else 1.0))

            if arm != "curated":
                continue
            profile_rows.append(dict(level="domain", domain=domain, qid="",
                                     **corpus_profile(records)))
            for thr in THRESHOLDS:
                cal = evaluate(records, truth, fuzzy_threshold=thr)
                calib_rows.append(dict(domain=domain, fuzzy_threshold=thr,
                                       **{k: cal[k] for k in
                                          ("precision", "recall", "f1",
                                           "pair_tp", "pair_fp", "pair_fn",
                                           "fuzzy_merges")}))
            for name in sorted(PERTURBATIONS):
                res = perturbation_arm(records, truth, name)
                if res is None:
                    pert_rows.append(dict(domain=domain, perturbation=name,
                                          groups_perturbed=0,
                                          groups_out_of_scope=0,
                                          applicability=0.0,
                                          precision=float("nan"),
                                          recall=float("nan"),
                                          f1=float("nan"),
                                          control_recall=float("nan"),
                                          recall_delta=float("nan")))
                    continue
                pert_rows.append(dict(domain=domain, **{
                    k: res[k] for k in ("perturbation", "groups_perturbed",
                                        "groups_out_of_scope", "applicability",
                                        "precision", "recall", "f1",
                                        "control_recall", "control_precision",
                                        "control_f1", "recall_delta",
                                        "precision_delta")}))
            print("  [{}] domain {:<18} n={:<5} pairs={:<4} P={:.4f} "
                  "F1={:.4f}".format(arm, domain, len(records),
                                     shape["truth_pairs"], met["precision"],
                                     met["f1"]), flush=True)

    write_csv(os.path.join(HERE, "multidomain_metrics.csv"), metric_rows)
    write_csv(os.path.join(HERE, "multidomain_profile.csv"), profile_rows)
    write_csv(os.path.join(HERE, "multidomain_perturbations.csv"), pert_rows)
    write_csv(os.path.join(HERE, "multidomain_calibration.csv"), calib_rows)
    write_csv(os.path.join(HERE, "multidomain_false_positives.csv"), fp_rows)
    print("wrote metrics/profile/perturbations/calibration/FP CSVs")
    return 0


def write_csv(path: str, rows: Sequence[dict]) -> None:
    import csv
    if not rows:
        return
    fields: List[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


if __name__ == "__main__":
    raise SystemExit(main())
