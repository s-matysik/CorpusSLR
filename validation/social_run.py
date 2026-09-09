"""Produce the four ``validation/domains_social_*`` deliverables."""
from __future__ import annotations

import collections
import os
from typing import Dict, List, Sequence

import social_eval as SE
from social_eval import (KINDS, MIN_PAIRS, OUTDIR, VERSION_KINDS, _DB_LABEL,
                         doi_coverage, measure, rows_to_records, write_csv)
from social_harvest import load_cache
from social_queries import SOCIAL_QUERIES

from corpusslr.validate import corpus_profile

METRIC_FIELDS = ["track", "domain", "qid", "level", "n_records", "databases",
                 "doi_coverage", "truth_pairs", "pair_tp", "pair_fp", "pair_fn",
                 "precision", "recall", "f1"] + \
                ["fp_" + k for k in KINDS] + \
                ["precision_excl_versions", "f1_excl_versions",
                 "sample_sufficient", "note"]

FP_FIELDS = ["domain", "qid", "kind", "doi_a", "doi_b", "title_a", "title_b",
             "source_a", "source_b"]

PROFILE_FIELDS = ["track", "domain", "database", "n", "pct_doi", "pct_abstract",
                  "pct_authors", "pct_year", "pct_journal", "pct_pages",
                  "pct_volume", "median_title_words", "median_authors",
                  "pct_preprint", "pct_diacritics"]


def _round(x: float, n: int = 4) -> float:
    return round(float(x), n)


def metric_row(track: str, domain: str, qid: str, level: str,
               rows: Sequence[dict], note_extra: str = "") -> dict:
    m = measure(rows)
    pm, counts = m["metrics"], m["counts"]
    dbs = sorted({r["_db"] for r in rows})
    truth_pairs = int(pm["pair_truth"])
    sufficient = truth_pairs >= MIN_PAIRS

    notes: List[str] = []
    if not sufficient:
        notes.append("truth_pairs={} < {}: too few judgeable pairs; this row "
                     "describes a handful of pairs and must not be read as a "
                     "domain-level accuracy estimate".format(truth_pairs,
                                                             MIN_PAIRS))
    version_fp = sum(counts[k] for k in VERSION_KINDS)
    if pm["pair_fp"]:
        notes.append("{}/{} false positives are version variants of one study"
                     .format(version_fp, int(pm["pair_fp"])))
    if note_extra:
        notes.append(note_extra)

    row = dict(track=track, domain=domain, qid=qid, level=level,
               n_records=len(rows),
               databases="+".join(_DB_LABEL.get(d, d) for d in dbs),
               doi_coverage=_round(doi_coverage(m["records"]), 2),
               truth_pairs=truth_pairs,
               pair_tp=int(pm["pair_tp"]), pair_fp=int(pm["pair_fp"]),
               pair_fn=int(pm["pair_fn"]),
               precision=_round(pm["precision"]), recall=_round(pm["recall"]),
               f1=_round(pm["f1"]),
               precision_excl_versions=_round(m["precision_excl_versions"]),
               f1_excl_versions=_round(m["f1_excl_versions"]),
               sample_sufficient=sufficient,
               note="; ".join(notes))
    for k in KINDS:
        row["fp_" + k] = int(counts.get(k, 0))
    return row, m


def main() -> None:
    raw = load_cache()
    rows = SE.EM.drop_non_works(raw)
    dropped = len(raw) - len(rows)

    by_qid: Dict[str, List[dict]] = collections.defaultdict(list)
    by_domain: Dict[str, List[dict]] = collections.defaultdict(list)
    for r in rows:
        by_qid[r["_qid"]].append(r)
        by_domain[r["_domain"]].append(r)

    metric_rows: List[dict] = []
    fp_rows: List[dict] = []
    profile_rows: List[dict] = []

    domains_seen: List[str] = []
    for spec in SOCIAL_QUERIES:
        if spec["domain"] not in domains_seen:
            domains_seen.append(spec["domain"])

    for domain in domains_seen:
        specs = [s for s in SOCIAL_QUERIES if s["domain"] == domain]
        for spec in specs:
            qrows = by_qid[spec["qid"]]
            row, m = metric_row("social", domain, spec["qid"], "query", qrows,
                                note_extra=spec["label"])
            metric_rows.append(row)
            for a, b, kind in m["fps"]:
                fp_rows.append(dict(domain=domain, qid=spec["qid"], kind=kind,
                                    doi_a=a.doi, doi_b=b.doi,
                                    title_a=a.title, title_b=b.title,
                                    source_a=a.source, source_b=b.source))
        drows = by_domain[domain]
        row, _ = metric_row("social", domain, "ALL", "domain", drows,
                            note_extra="pooled over {} queries".format(len(specs)))
        metric_rows.append(row)

        # metadata completeness per database within the domain
        for db in ("wos", "scopus", "crossref"):
            sub = [r for r in drows if r["_db"] == db]
            if not sub:
                continue
            prof = corpus_profile(rows_to_records(sub))
            profile_rows.append(dict(
                track="social", domain=domain, database=_DB_LABEL[db],
                n=int(prof["n"]),
                **{k: _round(prof[k], 2) for k in
                   ("pct_doi", "pct_abstract", "pct_authors", "pct_year",
                    "pct_journal", "pct_pages", "pct_volume",
                    "median_title_words", "median_authors", "pct_preprint",
                    "pct_diacritics")}))

    # track-wide pooled row, so the arm has one headline number
    row, _ = metric_row("social", "ALL", "ALL", "track", rows,
                        note_extra="all 5 domains pooled; {} non-work records "
                                   "(Crossref component/dataset/peer-review "
                                   "types) removed before scoring"
                                   .format(dropped))
    metric_rows.append(row)

    write_csv(os.path.join(OUTDIR, "domains_social_metrics.csv"),
              metric_rows, METRIC_FIELDS)
    write_csv(os.path.join(OUTDIR, "domains_social_false_positives.csv"),
              fp_rows, FP_FIELDS)
    write_csv(os.path.join(OUTDIR, "domains_social_profile.csv"),
              profile_rows, PROFILE_FIELDS)
    return metric_rows, fp_rows, profile_rows
