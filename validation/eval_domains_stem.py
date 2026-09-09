#!/usr/bin/env python
"""Identifier-blind deduplication validation on five STEM/informatics domains.

Track ``stem``: computer science, software engineering, business informatics,
physics, chemistry.  Two topical queries per domain, harvested from Web of
Science Expanded, Scopus, Crossref and arXiv.  Ground truth is the normalized
DOI; the deduplicator sees records with every identifier field wiped, so it has
to rebuild the DOI clusters from title, authors, year and bibliographic
coordinates alone (``corpusslr.validate``).

Every false-positive pair (a merge the DOI arbiter rejects) is classified, and
precision is reported twice: as measured, and after subtracting pairs that are
two *versions* of one work (preprint vs. published, two preprint servers, book
editions, working paper vs. published).  Cochrane practice treats those as one
study, so charging them as errors measures the definition of the truth set
rather than the implementation.

Usage
-----
Harvest (network, ~10 min) then evaluate::

    PYTHONPATH=. python eval_domains_stem.py --fetch

Evaluate from the cached raw records (no network -- what a reviewer runs)::

    PYTHONPATH=. python eval_domains_stem.py

Outputs, all under ``validation/``: ``domains_stem_raw.jsonl.gz``,
``domains_stem_metrics.csv``, ``domains_stem_false_positives.csv``,
``domains_stem_profile.csv``.
"""
from __future__ import annotations

import argparse
import collections
import csv
import gzip
import json
import os
import re
import sys
import time
from typing import Dict, List, Optional, Sequence, Tuple

REPO = "/Users/sebastianmatysik/!!!CorpusSLR/corpusslr"
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from corpusslr import SearchQuery                                   # noqa: E402
from corpusslr.dedup import deduplicate                             # noqa: E402
from corpusslr.record import Record                                 # noqa: E402
from corpusslr.sources.arxiv import parse_arxiv_atom                # noqa: E402
from corpusslr.sources.crossref import CrossrefSource               # noqa: E402
from corpusslr.sources.scopus import ScopusSource                   # noqa: E402
from corpusslr.sources.wos_expanded import WosExpandedSource        # noqa: E402
from corpusslr.validate import (clusters_from_decisions,            # noqa: E402
                                corpus_profile, hide_identifiers,
                                pair_metrics, record_metrics, truth_groups)

OUT = os.path.join(REPO, "validation")
CACHE = os.path.join(OUT, "domains_stem_raw.jsonl.gz")
TRACK = "stem"
YEARS = (2015, 2024)
MAX_PER_DB = 150          # WoS/Scopus budget is shared with two other tracks

# ----------------------------------------------------------------------
# 1. Study design
# ----------------------------------------------------------------------
#: Each query is two concept blocks (OR within, AND between), translated to
#: every database dialect by ``SearchQuery`` itself, so the four arms ask the
#: same question and differ only in the metadata they return -- which is the
#: quantity under test.
QUERIES: List[dict] = [
    dict(domain="computer science", qid="cs1",
         label="graph neural networks / node classification",
         blocks=[["graph neural network", "graph neural networks"],
                 ["node classification"]], arxiv=True),
    dict(domain="computer science", qid="cs2",
         label="federated learning / privacy",
         blocks=[["federated learning"],
                 ["differential privacy", "privacy preserving"]], arxiv=True),
    dict(domain="software engineering", qid="se1",
         label="technical debt / code smell",
         blocks=[["technical debt"], ["code smell", "code smells"]],
         arxiv=True),
    dict(domain="software engineering", qid="se2",
         label="continuous integration / build failure",
         blocks=[["continuous integration"],
                 ["build failure", "build failures", "build breakage"]],
         arxiv=True),
    dict(domain="business informatics", qid="bi1",
         label="process mining / event log",
         blocks=[["process mining"], ["event log", "event logs"]],
         arxiv=True),
    dict(domain="business informatics", qid="bi2",
         label="enterprise architecture / digital transformation",
         blocks=[["enterprise architecture"],
                 ["digital transformation", "business it alignment"]],
         arxiv=True),
    dict(domain="physics", qid="ph1",
         label="topological insulator / edge states",
         blocks=[["topological insulator", "topological insulators"],
                 ["edge state", "edge states", "surface states"]],
         arxiv=True),
    dict(domain="physics", qid="ph2",
         label="gravitational wave / binary neutron star",
         blocks=[["gravitational wave", "gravitational waves"],
                 ["binary neutron star", "neutron star merger"]],
         arxiv=True),
    dict(domain="chemistry", qid="ch1",
         label="metal-organic framework / gas adsorption",
         blocks=[["metal organic framework", "metal-organic framework",
                  "metal-organic frameworks"],
                 ["gas adsorption", "gas storage", "co2 capture"]],
         arxiv=True),
    dict(domain="chemistry", qid="ch2",
         label="asymmetric catalysis / enantioselectivity",
         blocks=[["asymmetric catalysis", "asymmetric hydrogenation"],
                 ["enantioselectivity", "enantioselective"]], arxiv=True),
]


def build_query(spec: dict) -> SearchQuery:
    return SearchQuery(blocks=[list(b) for b in spec["blocks"]], years=YEARS)


# ----------------------------------------------------------------------
# 2. Retrieval
# ----------------------------------------------------------------------
def _arxiv_dated(session, query: SearchQuery, limit: int,
                 mailto: str = "") -> List[Record]:
    """arXiv records restricted to the study window at *search* time.

    ``ArxivSource`` filters the year range client-side after retrieval, and the
    Atom API returns newest-first, so a 150-record page of a live topic is
    entirely outside a 2015-2024 window and the arm would come back empty.  The
    API's own ``submittedDate`` range solves it, so the range is appended to the
    query string ``SearchQuery.to_arxiv()`` produced and the records are parsed
    by the package's own ``parse_arxiv_atom`` -- the HTTP loop is the only part
    that is not package code, and normalization is unchanged.
    """
    import requests
    q = "{} AND submittedDate:[{}01010000 TO {}12312359]".format(
        query.to_arxiv(), YEARS[0], YEARS[1])
    out: List[Record] = []
    start = 0
    while len(out) < limit:
        page_size = min(100, limit - len(out))
        try:
            r = session.get("http://export.arxiv.org/api/query",
                            params={"search_query": q, "start": start,
                                    "max_results": page_size,
                                    "sortBy": "submittedDate",
                                    "sortOrder": "descending"}, timeout=90)
        except requests.RequestException:
            break
        if r.status_code != 200:
            break
        page = parse_arxiv_atom(r.text)
        if not page:
            break
        out.extend(page)
        if len(page) < page_size:
            break
        start += len(page)
        time.sleep(3.0)                       # arXiv terms of use
    return out[:limit]


def _crossref_relevance(session, query: SearchQuery, limit: int,
                        mailto: str = "") -> List[Record]:
    """Crossref hits in relevance order, parsed by the package's own parser.

    Measured behaviour of the shipped :class:`CrossrefSource` at a small cap:
    it opens paging with ``cursor="*"``, and Crossref serves cursor requests in
    index order rather than by relevance, so the first 150 records of a topical
    query are essentially unrelated works.  On the physics query ``ph1`` the
    cursor path returned 0 DOIs shared with Web of Science or Scopus while this
    rows-only path returned 3 -- with the cursor arm the Crossref arm cannot
    contribute a single judgeable duplicate pair.

    Both arms are therefore harvested and cached: this one (``crossref``) is
    scored, the shipped cursor arm is cached as ``crossref_cursor`` and excluded
    from scoring by :data:`SCORED_DBS`, so the diagnosis stays auditable from
    the raw file without any change to package code.
    """
    import requests
    from corpusslr.sources.crossref import _parse_item
    params = dict(query.to_crossref_params())
    params["rows"] = min(200, limit)
    if mailto:
        params["mailto"] = mailto
    try:
        r = session.get("https://api.crossref.org/works", params=params,
                        timeout=90)
    except requests.RequestException:
        return []
    if r.status_code != 200:
        return []
    items = (r.json().get("message") or {}).get("items") or []
    out = [_parse_item(it) for it in items[:limit]]
    for rec in out:
        rec.source = "Crossref"
    return out


def harvest(wos_key: str, sc_key: str, sc_tok: str, mailto: str = "",
            path: str = CACHE) -> int:
    import requests
    from corpusslr import __version__ as ver
    session = requests.Session()
    session.headers.update({"User-Agent": "CorpusSLR/{} validation".format(ver)})

    wos = WosExpandedSource(api_key=wos_key)
    scopus = ScopusSource(api_key=sc_key, insttoken=sc_tok)
    crossref = CrossrefSource(mailto=mailto)

    rows: List[dict] = []
    for spec in QUERIES:
        q = build_query(spec)
        arms: List[Tuple[str, callable]] = [
            ("wos", lambda q=q: wos.search(q, max_results=MAX_PER_DB).records),
            ("scopus", lambda q=q: scopus.search(q, max_results=MAX_PER_DB).records),
            ("crossref", lambda q=q: _crossref_relevance(session, q,
                                                         MAX_PER_DB, mailto)),
            ("crossref_cursor",
             lambda q=q: crossref.search(q, max_results=MAX_PER_DB).records),
        ]
        if spec.get("arxiv"):
            arms.append(("arxiv",
                         lambda q=q: _arxiv_dated(session, q, MAX_PER_DB, mailto)))
        for db, call in arms:
            try:
                recs = call()
            except Exception as exc:                  # keep the harvest alive
                print("  ! {}/{}: {}: {}".format(spec["qid"], db,
                                                 type(exc).__name__, exc),
                      flush=True)
                recs = []
            print("  {}/{}: {} records".format(spec["qid"], db, len(recs)),
                  flush=True)
            for rec in recs:
                row = rec.to_dict()
                row["_domain"] = spec["domain"]
                row["_qid"] = spec["qid"]
                row["_db"] = db
                rows.append(row)
            time.sleep(0.5)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print("cached {} records -> {}".format(len(rows), path))
    return len(rows)


def load_cache(path: str = CACHE) -> List[dict]:
    if not os.path.exists(path):
        raise SystemExit("cache missing: run with --fetch first")
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def rows_to_records(rows: Sequence[dict]) -> List[Record]:
    out: List[Record] = []
    for row in rows:
        meta = {k: v for k, v in row.items() if not k.startswith("_")}
        meta.pop("uid", None)
        meta.pop("provenance", None)
        rec = Record(**meta)
        rec.raw = {}
        out.append(rec)
    return out


def build_arm(rows: Sequence[dict]) -> Tuple[List[Record], Dict[str, str],
                                             Dict[str, str]]:
    """uid-stamped records, DOI ground truth, and uid -> qid."""
    records = rows_to_records(rows)
    qid_of: Dict[str, str] = {}
    for n, (rec, row) in enumerate(zip(records, rows), 1):
        rec.uid = "{}-{:05d}".format(row["_db"], n)
        rec.source = rec.source or row["_db"]
        qid_of[rec.uid] = row["_qid"]
    return records, truth_groups(records), qid_of


# ----------------------------------------------------------------------
# 3. False-positive classification
# ----------------------------------------------------------------------
#: Record types that are not bibliographic works.  ``component`` is the
#: load-bearing one: Crossref registers every supplementary file of an article
#: under its own DOI with the *article's* title, so a DOI arbiter calls a
#: supplement a different work from its own parent and recognising them as one
#: paper is scored as an error.  Dropped by a mechanical rule on the record
#: type, decided before any metric was computed and applied in every domain.
NON_WORK_TYPES = frozenset(("component", "peer-review", "grant", "dataset",
                            "other"))

PREPRINT_PREFIXES = ("10.48550", "10.2139/ssrn", "10.21203/rs", "10.1101/",
                     "10.31234", "10.20944", "10.22541", "10.31235",
                     "10.31219", "10.26434", "10.36227", "10.32388",
                     "10.33774", "10.21467")

WORKING_PAPER_PREFIXES = ("10.3386", "10.17016", "10.5089", "10.1596",
                          "10.24149", "10.26509", "10.2866", "10.4054",
                          "10.2760")

_BOOK_TYPES = frozenset(("book-chapter", "book", "monograph", "book-part",
                         "book-section", "edited-book", "chapter",
                         "reference-entry", "book chapter"))

_REPORT_TYPES = frozenset(("report", "working-paper", "working paper",
                           "dissertation", "report-component", "posted-content"))

_CORRECTION_RE = re.compile(
    r"^\s*(correction|corrigendum|erratum|retraction|addendum|"
    r"editorial expression of concern|expression of concern|comment on|"
    r"reply to|author correction|publisher correction|"
    r"comment on \u201c|retraction note)\b[:\s\u201c]", re.I)

_PREPRINT_VENUE_RE = re.compile(
    r"arxiv|biorxiv|medrxiv|chemrxiv|ssrn|research square|preprint|techrxiv",
    re.I)

FP_KINDS = ("preprint_vs_published", "two_preprint_servers", "book_edition",
            "working_paper_vs_published", "two_working_paper_series",
            "correction_vs_original", "over_merge")

#: Kinds in which the merged pair is two versions of one work.  A review team
#: deduplicating for screening wants these merged (Cochrane counts them as one
#: study), so a second precision figure is reported that does not charge them --
#: clearly labelled, alongside the strict figure, never instead of it.
VERSION_KINDS = frozenset(("preprint_vs_published", "two_preprint_servers",
                           "book_edition", "working_paper_vs_published",
                           "two_working_paper_series"))


#: Database arms that enter the scored corpus.  ``crossref_cursor`` is cached
#: but not scored: it is the shipped source's cursor-paged output, kept as
#: evidence for the ordering diagnosis in :func:`_crossref_relevance`.  Scoring
#: both would double-count Crossref and let an artefact of paging order drive
#: the headline numbers.
SCORED_DBS = frozenset(("wos", "scopus", "crossref", "arxiv"))


def drop_non_works(rows: Sequence[dict]) -> List[dict]:
    return [r for r in rows
            if (r.get("doc_type") or "").lower() not in NON_WORK_TYPES
            and r.get("_db") in SCORED_DBS]


def _is_preprint(rec: Record) -> bool:
    doi = (rec.doi or "").lower()
    if any(doi.startswith(p) for p in PREPRINT_PREFIXES):
        return True
    if (rec.doc_type or "").lower() in ("preprint", "posted-content"):
        return True
    return bool(_PREPRINT_VENUE_RE.search(rec.journal or "")) or \
        rec.source == "arXiv"


def _is_working_paper(rec: Record) -> bool:
    doi = (rec.doi or "").lower()
    if any(doi.startswith(p) for p in WORKING_PAPER_PREFIXES):
        return True
    return (rec.doc_type or "").lower() in _REPORT_TYPES


def _is_correction(rec: Record) -> bool:
    if (rec.doc_type or "").lower() in ("published erratum", "erratum",
                                        "retraction", "correction",
                                        "correction notice"):
        return True
    return bool(_CORRECTION_RE.match(rec.title or ""))


def classify_false_positive(a: Record, b: Record) -> str:
    """Name the reason a merged pair disagrees with the DOI arbiter.

    Order matters: a correction is checked before the preprint tests because a
    corrigendum posted to a preprint server would otherwise be filed as a
    version variant and excused, which it must not be.  Everything the named
    conventions do not explain is ``over_merge`` -- the only category that is
    unambiguously a defect, including byte-identical titles under two DOIs that
    cannot be resolved without full text.
    """
    if _is_correction(a) != _is_correction(b):
        return "correction_vs_original"
    pa, pb = _is_preprint(a), _is_preprint(b)
    if pa and pb:
        return "two_preprint_servers"
    if pa != pb:
        return "preprint_vs_published"
    wa, wb = _is_working_paper(a), _is_working_paper(b)
    if wa and wb:
        return "two_working_paper_series"
    if wa != wb:
        return "working_paper_vs_published"
    at, bt = (a.doc_type or "").lower(), (b.doc_type or "").lower()
    if at in _BOOK_TYPES or bt in _BOOK_TYPES:
        return "book_edition"
    return "over_merge"


# ----------------------------------------------------------------------
# 4. Evaluation
# ----------------------------------------------------------------------
_REPO_PREFIXES = ("10.6084", "10.5281", "10.32920", "10.5061", "10.17632",
                  "10.7910", "10.4225", "10.26180", "10.25911", "10.48420")


def _doi_core(doi: str) -> str:
    """A DOI reduced to its alphanumeric core, for spotting corrupt renderings."""
    return re.sub(r"[^a-z0-9]", "", (doi or "").lower())


def audit_over_merges(fps: Sequence[Tuple[Record, Record, str]]) -> Dict[str, int]:
    """Mechanical audit of the pairs classified ``over_merge``.

    ``over_merge`` is the only category the classification treats as a defect,
    so the headline claim rests on it and it has to be checked rather than
    trusted.  Three defects of the *truth set* mimic an over-merge, and each is
    detected by a rule on the identifiers alone, decided before the counts were
    read:

    ``malformed_doi``
        The two DOIs are the same string once punctuation is removed
        (``10.1109/icsme.2017.67`` against Scopus's ``10.1109/icsme.201767``,
        which does not resolve).  One work entered the truth set as two groups,
        so recognising it as one paper is scored as an error.
    ``repository_deposit``
        One side is a Figshare/Zenodo-class repository DOI and the normalized
        titles are identical: an author deposit of the publisher version.
    ``duplicate_registration``
        Identical normalized titles under two DOIs from the *same* registrant
        prefix -- a publisher that registered one paper twice.

    The counts are reported in the ``note`` column and never subtracted from
    ``fp_over_merge``: the CSV carries the measurement, and the audit says how
    much of it is an artefact of using the DOI as the arbiter.
    """
    out = collections.Counter()
    for a, b, kind in fps:
        if kind != "over_merge":
            continue
        da, db = (a.doi or "").lower(), (b.doi or "").lower()
        same_title = a.norm_title == b.norm_title and bool(a.norm_title)
        if _doi_core(da) == _doi_core(db) and da != db:
            out["malformed_doi"] += 1
        elif same_title and (da.startswith(_REPO_PREFIXES)
                             or db.startswith(_REPO_PREFIXES)):
            out["repository_deposit"] += 1
        elif same_title and da.split("/")[0] == db.split("/")[0]:
            out["duplicate_registration"] += 1
        else:
            out["unexplained"] += 1
    return dict(out)


def evaluate(records: Sequence[Record], truth: Dict[str, str],
             **dedup_kw) -> Tuple[Dict[str, float],
                                  List[Tuple[Record, Record, str]]]:
    """Blind the identifiers, deduplicate, score, and classify every FP pair."""
    index = {r.uid: r for r in records}
    blinded = hide_identifiers(records)
    result = deduplicate(blinded, **dedup_kw)
    uids = [r.uid for r in blinded]
    clusters = clusters_from_decisions(result.report.decisions, uids)
    met = dict(pair_metrics(clusters, truth))
    met.update(record_metrics(clusters, truth))
    fps: List[Tuple[Record, Record, str]] = []
    for cluster in clusters:
        judged = [u for u in cluster if u in truth]
        for i in range(len(judged)):
            for j in range(i + 1, len(judged)):
                ua, ub = judged[i], judged[j]
                if truth[ua] == truth[ub]:
                    continue
                a, b = index[ua], index[ub]
                fps.append((a, b, classify_false_positive(a, b)))
    return met, fps


def missed_pairs(records: Sequence[Record], truth: Dict[str, str],
                 **dedup_kw) -> List[Tuple[Record, Record]]:
    """True duplicate pairs the blinded run left in separate clusters."""
    index = {r.uid: r for r in records}
    blinded = hide_identifiers(records)
    result = deduplicate(blinded, **dedup_kw)
    clusters = clusters_from_decisions(result.report.decisions,
                                       [r.uid for r in blinded])
    of: Dict[str, int] = {}
    for n, cluster in enumerate(clusters):
        for uid in cluster:
            of[uid] = n
    by_group: Dict[str, List[str]] = collections.defaultdict(list)
    for uid, group in truth.items():
        by_group[group].append(uid)
    out: List[Tuple[Record, Record]] = []
    for members in by_group.values():
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                if of.get(members[i]) != of.get(members[j]):
                    out.append((index[members[i]], index[members[j]]))
    return out


def missed_causes(pairs: Sequence[Tuple[Record, Record]]) -> Dict[str, int]:
    """Which metadata field disagreed on each missed pair.

    A recall figure says how many duplicates were missed; it does not say
    whether the matcher was too strict or the databases disagreed.  Each missed
    pair is attributed to the fields that differ, so the two are separable: a
    pair whose titles are byte-identical after normalization and whose page
    field is populated on one side only was missed because of a *coordinate*
    disagreement, not a title-similarity failure.
    """
    out = collections.Counter()
    for a, b in pairs:
        pa, pb = (a.pages or "").strip(), (b.pages or "").strip()
        if a.norm_title != b.norm_title:
            out["title_differs"] += 1
        if a.year != b.year:
            out["year_differs"] += 1
        if bool(pa) != bool(pb):
            out["pages_one_side_missing"] += 1
        elif pa and pb and pa != pb:
            out["pages_disagree"] += 1
        if (a.norm_title == b.norm_title and a.year == b.year
                and pa == pb):
            out["all_scored_fields_agree"] += 1
    return dict(out)


def metric_row(level: str, domain: str, qid: str, rows: Sequence[dict],
               records: Sequence[Record], truth: Dict[str, str],
               met: Dict[str, float],
               fps: Sequence[Tuple[Record, Record, str]],
               extra_note: str = "") -> dict:
    counts = collections.Counter(kind for _, _, kind in fps)
    sizes = collections.Counter(truth.values())
    truth_pairs = sum(n * (n - 1) // 2 for n in sizes.values() if n > 1)
    tp, fp = met["pair_tp"], met["pair_fp"]
    version_fp = sum(n for k, n in counts.items() if k in VERSION_KINDS)
    hard_fp = fp - version_fp
    prec_excl = tp / float(tp + hard_fp) if tp + hard_fp else 1.0
    rec = met["recall"]
    f1_excl = (2 * prec_excl * rec / (prec_excl + rec)
               if prec_excl + rec else 0.0)
    n_doi = sum(1 for r in records if r.doi)
    sufficient = truth_pairs >= 30
    note = extra_note
    if not sufficient:
        note = ("truth_pairs<30: sample too small for quantitative claims "
                "about this cell; reported for completeness only. " + note)
    row = dict(track=TRACK, domain=domain, qid=qid, level=level,
               n_records=len(records),
               databases=len({r["_db"] for r in rows}),
               doi_coverage=round(n_doi / float(len(records)), 4) if records else 0.0,
               truth_pairs=truth_pairs,
               pair_tp=int(tp), pair_fp=int(fp), pair_fn=int(met["pair_fn"]),
               precision=round(met["precision"], 4),
               recall=round(rec, 4), f1=round(met["f1"], 4))
    for kind in FP_KINDS:
        row["fp_" + kind] = int(counts.get(kind, 0))
    row["precision_excl_versions"] = round(prec_excl, 4)
    row["f1_excl_versions"] = round(f1_excl, 4)
    row["sample_sufficient"] = sufficient
    audit = audit_over_merges(fps)
    if audit:
        note = note + " over_merge audit: " + "; ".join(
            "{}={}".format(k, audit[k]) for k in sorted(audit)) + "."
    same_dep = sum(1 for a, b, k in fps
                   if k == "two_preprint_servers"
                   and re.sub(r"[._-]?v\d+$", "", (a.doi or "").lower())
                   == re.sub(r"[._-]?v\d+$", "", (b.doi or "").lower()))
    if same_dep:
        note = note + (" of {} two_preprint_servers pairs, {} are .vN version "
                       "DOIs of one deposit on one server, not two servers."
                       .format(int(counts.get("two_preprint_servers", 0)),
                               same_dep))
    row["note"] = note.strip()
    return row


COLUMNS = ["track", "domain", "qid", "level", "n_records", "databases",
           "doi_coverage", "truth_pairs", "pair_tp", "pair_fp", "pair_fn",
           "precision", "recall", "f1"] + \
          ["fp_" + k for k in FP_KINDS] + \
          ["precision_excl_versions", "f1_excl_versions", "sample_sufficient",
           "note"]

FP_COLUMNS = ["domain", "qid", "kind", "doi_a", "doi_b", "title_a", "title_b",
              "source_a", "source_b"]


def write_csv(path: str, rows: Sequence[dict],
              columns: Optional[Sequence[str]] = None) -> None:
    if not rows:
        return
    fields = list(columns) if columns else []
    if not fields:
        for row in rows:
            for key in row:
                if key not in fields:
                    fields.append(key)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    args = ap.parse_args(argv)

    if args.fetch:
        raise SystemExit("--fetch needs API keys; harvest is driven from the "
                         "working notebook, not the CLI")

    all_rows = load_cache()
    rows = drop_non_works(all_rows)
    print("loaded {} records; {} after dropping non-work types".format(
        len(all_rows), len(rows)))

    label_of = {s["qid"]: s["label"] for s in QUERIES}
    domain_of = {s["qid"]: s["domain"] for s in QUERIES}

    by_query: Dict[str, List[dict]] = collections.defaultdict(list)
    by_domain: Dict[str, List[dict]] = collections.defaultdict(list)
    by_domain_db: Dict[Tuple[str, str], List[dict]] = collections.defaultdict(list)
    for row in rows:
        by_query[row["_qid"]].append(row)
        by_domain[row["_domain"]].append(row)
        by_domain_db[(row["_domain"], row["_db"])].append(row)

    metric_rows: List[dict] = []
    fp_rows: List[dict] = []
    profile_rows: List[dict] = []

    order = [s["qid"] for s in QUERIES]
    for domain in [d for d in dict.fromkeys(s["domain"] for s in QUERIES)]:
        for qid in [q for q in order if domain_of[q] == domain]:
            qrows = by_query[qid]
            records, truth, _ = build_arm(qrows)
            met, fps = evaluate(records, truth)
            metric_rows.append(metric_row("query", domain, qid, qrows, records,
                                          truth, met, fps,
                                          extra_note=label_of[qid]))
            print("  {:<10} {:<22} n={:<5} pairs={:<4} P={:.3f} R={:.3f} "
                  "F1={:.3f}".format(qid, domain, len(records),
                                     metric_rows[-1]["truth_pairs"],
                                     met["precision"], met["recall"],
                                     met["f1"]), flush=True)

        drows = by_domain[domain]
        records, truth, qid_of = build_arm(drows)
        met, fps = evaluate(records, truth)
        fn_causes = missed_causes(missed_pairs(records, truth))
        fn_note = ("pooled over both queries. missed-pair causes: "
                   + ("; ".join("{}={}".format(k, fn_causes[k])
                                for k in sorted(fn_causes)) or "none")
                   + ".")
        metric_rows.append(metric_row("domain", domain, "", drows, records,
                                      truth, met, fps, extra_note=fn_note))
        for a, b, kind in fps:
            qa, qb = qid_of.get(a.uid, ""), qid_of.get(b.uid, "")
            fp_rows.append(dict(domain=domain, qid=qa if qa == qb else "pooled",
                                kind=kind, doi_a=a.doi, doi_b=b.doi,
                                title_a=(a.title or "")[:200],
                                title_b=(b.title or "")[:200],
                                source_a=a.source, source_b=b.source))
        for (dom, db), sub in sorted(by_domain_db.items()):
            if dom != domain:
                continue
            sub_recs = rows_to_records(sub)
            profile_rows.append(dict(track=TRACK, domain=dom, database=db,
                                     **{k: (round(v, 2) if isinstance(v, float)
                                            else v)
                                        for k, v in corpus_profile(sub_recs).items()}))
        profile_rows.append(dict(track=TRACK, domain=domain, database="ALL",
                                 **{k: (round(v, 2) if isinstance(v, float)
                                        else v)
                                    for k, v in corpus_profile(records).items()}))

    write_csv(os.path.join(OUT, "domains_stem_metrics.csv"), metric_rows,
              COLUMNS)
    write_csv(os.path.join(OUT, "domains_stem_false_positives.csv"), fp_rows,
              FP_COLUMNS)
    write_csv(os.path.join(OUT, "domains_stem_profile.csv"), profile_rows)
    print("wrote {} metric rows, {} FP rows, {} profile rows".format(
        len(metric_rows), len(fp_rows), len(profile_rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
