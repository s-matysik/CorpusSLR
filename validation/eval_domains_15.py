"""Recompute domains_15_final.csv from the archived raw records.

Why this script exists: the table was first produced in an interactive session,
which made it unreproducible and, worse, made it look inconsistent with the
per-track metric files it sits beside. It is not inconsistent, but the reason
was undocumented, so a reviewer comparing the two would have found a
discrepancy with no explanation. Both differences are deliberate:

1. **The guards.** The per-track files were produced before three guards were
   added to the package: rejecting a missing-value literal in the DOI field,
   refusing fuzzy matches on a title that is only an identifier, and separating
   instalments of a recurring publication. Those guards are exactly what
   removes false merges, so the per-track numbers are the BEFORE state and this
   table is the AFTER state. Pooled false merges fall from 228 to 154.

2. **The scoring population.** This script caps Crossref at 300 records per
   discipline and drops non-work document types (peer reviews, datasets,
   errata, editorials). Both narrow the judgeable population slightly, so a few
   disciplines report fewer true pairs here than in their track file.

Run with ``--check`` to compare against the committed CSV instead of writing
it; the exit status is non-zero on any disagreement, which is what the test
uses. Runs offline: every record comes from ``domains_*_raw.jsonl.gz``.
"""
import argparse
import csv
import gzip
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from corpusslr import Record, deduplicate                       # noqa: E402
from corpusslr.validate import (clusters_from_decisions,        # noqa: E402
                                hide_identifiers, truth_groups)

TRACKS = ("social", "stem", "nature_hum")

#: Document types that are not works under review and must not be scored.
NON_WORK = {"peer-review", "dataset", "other", "component", "grant", "erratum",
            "editorial-material", "correction"}

#: Crossref returns relevance-ranked results, so its tail is only loosely on
#: topic; capping keeps one database from dominating a discipline's pairs.
CROSSREF_CAP = 300

#: DOI prefixes that identify a preprint server or working-paper series. A pair
#: spanning one of these is a version of one study, not a merge error.
PREPRINT_PREFIX = {
    "10.48550": "arXiv", "10.1101": "bioRxiv/medRxiv", "10.36227": "TechRxiv",
    "10.26434": "ChemRxiv", "10.21203": "Research Square", "10.31234": "PsyArXiv",
    "10.2139": "SSRN", "10.3386": "NBER", "10.17016": "Fed",
    "10.31235": "SocArXiv", "10.31219": "OSF",
}

FIELDS = ["track", "domain", "n_records", "truth_pairs", "pair_tp", "pair_fp",
          "pair_fn", "preprint_vs_published", "two_versions_one_server",
          "two_preprint_servers", "same_title_two_dois", "over_merge",
          "fp_versions", "fp_over", "precision", "recall", "f1",
          "precision_excl", "f1_excl", "doi_coverage"]


def _data_path(name):
    """Find a data file in the repository layout or beside this script.

    The script is shipped twice: in the repository as ``validation/`` and in
    the submitted data package, where it sits next to a ``raw_records/``
    directory instead. Resolving both means the commands printed in the
    package README actually work there, rather than only in a checkout.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(HERE, "validation", name),      # repository layout
        os.path.join(here, name),                    # beside this script
        os.path.join(here, "raw_records", name),     # data package layout
        os.path.join(here, "..", "validation", name),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    raise SystemExit(
        "cannot find {}; looked in:\n  {}".format(
            name, "\n  ".join(os.path.normpath(c) for c in candidates)))


def _load(track):
    path = _data_path("domains_{}_raw.jsonl.gz".format(track))
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except ValueError:
                    continue


def _record(d, i):
    return Record(
        title=d.get("title") or "", abstract=d.get("abstract") or "",
        authors=list(d.get("authors") or []), year=d.get("year"),
        journal=d.get("journal") or "", doi=d.get("doi") or "",
        pmid=d.get("pmid") or "", volume=str(d.get("volume") or ""),
        issue=str(d.get("issue") or ""), pages=str(d.get("pages") or ""),
        doc_type=d.get("doc_type") or "", source=d.get("source") or "",
        uid="r{:06d}".format(i))


def _prefix(doi):
    return (doi or "").split("/")[0]


def _classify(a, b):
    """Name what kind of pair this false merge is."""
    pa, pb = _prefix(a.doi), _prefix(b.doi)
    a_pre, b_pre = pa in PREPRINT_PREFIX, pb in PREPRINT_PREFIX
    if a_pre and b_pre:
        return ("two_preprint_servers" if pa != pb
                else "two_versions_one_server")
    if a_pre or b_pre:
        return "preprint_vs_published"
    if (a.title or "").strip().lower() == (b.title or "").strip().lower():
        return "same_title_two_dois"
    return "over_merge"


def _pairs(groups):
    out = set()
    for members in groups.values():
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                out.add(tuple(sorted((members[i], members[j]))))
    return out


def evaluate(rows):
    """Score one discipline. Returns the metric dict for its CSV row."""
    kept, by_source = [], {}
    for d in rows:
        by_source.setdefault(d.get("source"), []).append(d)
    for name, items in by_source.items():
        if name == "Crossref" and len(items) > CROSSREF_CAP:
            items = items[:CROSSREF_CAP]
        kept += items

    records = [_record(d, i) for i, d in enumerate(kept)
               if (d.get("doc_type") or "").lower() not in NON_WORK]
    truth = truth_groups(records)
    by_uid = {r.uid: r for r in records}

    blinded = hide_identifiers(records)
    result = deduplicate(blinded)
    clusters = clusters_from_decisions(result.report.decisions,
                                       [r.uid for r in blinded])

    found = set()
    for cluster in clusters:
        scorable = [u for u in cluster if u in truth]
        for i in range(len(scorable)):
            for j in range(i + 1, len(scorable)):
                found.add(tuple(sorted((scorable[i], scorable[j]))))

    groups = {}
    for uid, key in truth.items():
        groups.setdefault(key, []).append(uid)
    true_pairs = _pairs(groups)

    false_merges = [p for p in found if p not in true_pairs]
    kinds = {}
    for a, b in false_merges:
        k = _classify(by_uid[a], by_uid[b])
        kinds[k] = kinds.get(k, 0) + 1

    tp = len(found & true_pairs)
    fp = len(false_merges)
    fn = len(true_pairs - found)
    versions = sum(v for k, v in kinds.items() if k != "over_merge")
    over = kinds.get("over_merge", 0)

    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    p_excl = tp / (tp + over) if tp + over else 1.0
    with_doi = sum(1 for r in records if (r.doi or "").strip())

    row = dict(n_records=len(records), truth_pairs=len(true_pairs),
               pair_tp=tp, pair_fp=fp, pair_fn=fn,
               fp_versions=versions, fp_over=over,
               precision=round(precision, 4), recall=round(recall, 4),
               f1=round(2 * precision * recall / (precision + recall), 4)
               if precision + recall else 0.0,
               precision_excl=round(p_excl, 4),
               f1_excl=round(2 * p_excl * recall / (p_excl + recall), 4)
               if p_excl + recall else 0.0,
               doi_coverage=round(100.0 * with_doi / len(records), 2)
               if records else 0.0)
    for key in ("preprint_vs_published", "two_versions_one_server",
                "two_preprint_servers", "same_title_two_dois", "over_merge"):
        row[key] = kinds.get(key, 0)
    return row


def build():
    rows = []
    for track in TRACKS:
        by_domain = {}
        for d in _load(track):
            name = d.get("_domain") or d.get("domain")
            if name:
                by_domain.setdefault(name, []).append(d)
        for domain in sorted(by_domain):
            row = evaluate(by_domain[domain])
            row.update(track=track, domain=domain)
            rows.append({k: row.get(k, 0) for k in FIELDS})
    rows.sort(key=lambda r: (-r["f1"], r["domain"]))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="compare against the committed CSV, do not write")
    ap.add_argument("--out", default=None,
                    help="defaults to the committed table, wherever it is")
    args = ap.parse_args(argv)
    if args.out is None:
        args.out = _data_path("domains_15_final.csv")

    rows = build()
    if not args.check:
        with open(args.out, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        print("wrote {} ({} disciplines)".format(args.out, len(rows)))
        return 0

    with open(args.out, encoding="utf-8") as fh:
        committed = {r["domain"]: r for r in csv.DictReader(fh)}
    problems = []
    for row in rows:
        old = committed.get(row["domain"])
        if old is None:
            problems.append((row["domain"], "absent from the committed CSV"))
            continue
        for key in ("truth_pairs", "pair_tp", "pair_fp", "pair_fn"):
            if int(old[key]) != row[key]:
                problems.append((row["domain"], "{}: committed {} recomputed {}"
                                 .format(key, old[key], row[key])))
    if problems:
        for domain, detail in problems:
            print("{}: {}".format(domain, detail))
        return 1
    print("recomputed table agrees with the committed CSV "
          "({} disciplines)".format(len(rows)))
    return 0


if __name__ == "__main__":                       # pragma: no cover
    sys.exit(main())
