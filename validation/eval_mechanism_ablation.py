"""Regenerate the two mechanism-ablation tables by switching each one off.

`dedup_mechanism_ablation.csv` (ASySD Diabetes gold standard) and
`dedup_ablation_domains.csv` (the fifteen disciplines) back Table 2 of the
article. Neither had a script. The domain table could not even be reconciled
with the fifteen-discipline table it claims to ablate: its "shipped defaults"
row said precision 0.9189, while the pooled confusion matrix of
`domains_15_final.csv` gives 0.9417, so it described an earlier state of the
software and no command in the repository could say which.

Method: each mechanism has a switch on ``deduplicate()``. The baseline is the
shipped defaults. For each mechanism the same corpus is rescored with that one
switch off and everything else unchanged; the delta is baseline F1 minus F1
without the mechanism. Gold-standard scoring is cluster-level (Hair et al.
2023), the discipline scoring pooled pairwise (summed confusion matrices).

    PYTHONPATH=. python validation/eval_mechanism_ablation.py
    PYTHONPATH=. python validation/eval_mechanism_ablation.py --check
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

#: name, origin, the deduplicate() keyword that switches it off
MECHANISMS = (
    ("identifier guarded by title", "this work", {"id_title_min": 0.0}),
    ("shared-locus guard", "this work", {"separate_by_locus": False}),
    ("multi-round blocking", "ASySD (Hair et al. 2023)", {"blocking_rounds": False}),
    ("conflicting-identifier override", "this work", {"allow_copublication": False}),
    ("conference/article separation", "this work", {"separate_conference": False}),
)
GOLD_CSV = os.path.join(HERE, "dedup_mechanism_ablation.csv")
DOMAIN_CSV = os.path.join(HERE, "dedup_ablation_domains.csv")


def _prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def gold_rows():
    import verify_reviewer_claims as V
    from corpusslr.dedup import deduplicate
    recs, truth = V._load_gold_records(os.path.join(HERE, "labelled_test_set.csv"))

    def score(**kw):
        res = deduplicate(recs, **kw)
        kept = V._cluster_survivors(res.report.decisions, list(truth), truth)
        tp = sum(1 for u, g in truth.items() if g == "duplicate" and u not in kept)
        fn = sum(1 for u, g in truth.items() if g == "duplicate" and u in kept)
        fp = sum(1 for u, g in truth.items() if g == "unique" and u not in kept)
        return tp, fp, fn

    base = _prf(*score())[2]
    out = []
    for name, origin, kw in MECHANISMS:
        tp, fp, fn = score(**kw)
        f1 = _prf(tp, fp, fn)[2]
        out.append({"mechanism": name, "origin": origin, "FP": fp, "FN": fn,
                    "f1_without": round(f1, 4), "delta_f1": round(base - f1, 4)})
    out.sort(key=lambda r: -r["delta_f1"])
    return out, base


def domain_rows():
    import eval_domains_15 as E

    def pooled(kw):
        rows = E.build(kw)
        tp = sum(int(r["pair_tp"]) for r in rows)
        fp = sum(int(r["pair_fp"]) for r in rows)
        fn = sum(int(r["pair_fn"]) for r in rows)
        return _prf(tp, fp, fn)

    bp, br, bf = pooled(None)
    out = [{"mechanism": "shipped defaults", "origin": "-",
            "precision": round(bp, 4), "recall": round(br, 4),
            "f1": round(bf, 4), "delta_f1": 0.0}]
    for name, origin, kw in MECHANISMS:
        p, r, f = pooled(kw)
        out.append({"mechanism": name, "origin": origin, "precision": round(p, 4),
                    "recall": round(r, 4), "f1": round(f, 4),
                    "delta_f1": round(bf - f, 4)})
    return out


def _write(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    gold, base = gold_rows()
    dom = domain_rows()
    print("gold standard baseline F1 %.4f" % base)
    for r in gold:
        print("  %-34s FP=%d FN=%d F1 without %.4f  delta %.4f"
              % (r["mechanism"], r["FP"], r["FN"], r["f1_without"], r["delta_f1"]))
    print("fifteen disciplines, pooled")
    for r in dom:
        print("  %-34s P=%.4f R=%.4f F1=%.4f delta %.4f"
              % (r["mechanism"], r["precision"], r["recall"], r["f1"], r["delta_f1"]))
    if args.check:
        bad = []
        for path, rows in ((GOLD_CSV, gold), (DOMAIN_CSV, dom)):
            with open(path, encoding="utf-8", newline="") as fh:
                old = list(csv.DictReader(fh))
            if [{k: str(v) for k, v in r.items()} for r in rows] != \
                    [{k: str(v) for k, v in r.items()} for r in old]:
                bad.append(os.path.basename(path))
        print("tables agree with the committed CSVs" if not bad
              else "STALE: " + ", ".join(bad))
        return 1 if bad else 0
    _write(GOLD_CSV, gold)
    _write(DOMAIN_CSV, dom)
    print("wrote", os.path.basename(GOLD_CSV), "and", os.path.basename(DOMAIN_CSV))
    return 0


if __name__ == "__main__":                                  # pragma: no cover
    raise SystemExit(main())
