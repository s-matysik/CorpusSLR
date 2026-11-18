"""95 % confidence intervals for the fifteen-discipline deduplication results.

A reviewer asked for intervals on the reported metrics, noting that the number
of judgeable pairs per discipline is small (66 to 344). They are computed here
from the confusion matrices already in `domains_15_final.csv`; nothing is
re-run, so the intervals describe exactly the figures the article reports.

* Precision and recall per discipline: Wilson score interval for a binomial
  proportion (precision = TP / (TP + FP), recall = TP / (TP + FN)). Wilson is
  used rather than the normal approximation because several proportions sit
  near 1, where the normal interval leaves [0, 1].
* F1 per discipline: percentile bootstrap, 2000 resamples. Each resample draws
  TP + FP + FN pair outcomes with replacement from that discipline's own
  counts and recomputes F1 = 2TP / (2TP + FP + FN).
* The median F1 over disciplines: percentile bootstrap over the fifteen
  disciplines, 2000 resamples. This interval is about the discipline-to-
  discipline spread, not about pair sampling, and is labelled as such.
* Pooled precision, recall and F1 over all disciplines: Wilson for the first
  two, bootstrap for F1, treating pairs as exchangeable across disciplines.

The random generator is seeded, so the table is deterministic and `--check`
reproduces it.

    PYTHONPATH=. python validation/intervals_domains_15.py
    PYTHONPATH=. python validation/intervals_domains_15.py --check
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import random
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, "domains_15_final.csv")
OUT = os.path.join(HERE, "domains_15_intervals.csv")
Z = 1.959964
RESAMPLES = 2000
SEED = 20260913


def wilson(successes, total, z=Z):
    """Wilson score interval; (1, 1) when there is nothing to judge."""
    if total <= 0:
        return 1.0, 1.0
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def f1(tp, fp, fn):
    d = 2 * tp + fp + fn
    return 2 * tp / d if d else 1.0


def percentile(sorted_values, q):
    k = (len(sorted_values) - 1) * q
    lo, hi = int(math.floor(k)), int(math.ceil(k))
    if lo == hi:
        return sorted_values[lo]
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


def bootstrap_f1(tp, fp, fn, rng):
    n = tp + fp + fn
    if n == 0:
        return 1.0, 1.0
    weights = [tp, fp, fn]
    stats = []
    for _ in range(RESAMPLES):
        draw = rng.choices((0, 1, 2), weights=weights, k=n)
        stats.append(f1(draw.count(0), draw.count(1), draw.count(2)))
    stats.sort()
    return percentile(stats, 0.025), percentile(stats, 0.975)


def compute():
    with open(SOURCE, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    rng = random.Random(SEED)
    out = []
    for r in sorted(rows, key=lambda r: r["domain"]):
        tp, fp, fn = (int(float(r[k])) for k in ("pair_tp", "pair_fp", "pair_fn"))
        p_lo, p_hi = wilson(tp, tp + fp)
        r_lo, r_hi = wilson(tp, tp + fn)
        f_lo, f_hi = bootstrap_f1(tp, fp, fn, rng)
        out.append({
            "scope": r["domain"], "judgeable_pairs": int(float(r["truth_pairs"])),
            "tp": tp, "fp": fp, "fn": fn,
            "precision": round(tp / (tp + fp), 4) if tp + fp else 1.0,
            "precision_lo": round(p_lo, 4), "precision_hi": round(p_hi, 4),
            "recall": round(tp / (tp + fn), 4) if tp + fn else 1.0,
            "recall_lo": round(r_lo, 4), "recall_hi": round(r_hi, 4),
            "f1": round(f1(tp, fp, fn), 4),
            "f1_lo": round(f_lo, 4), "f1_hi": round(f_hi, 4)})

    tp = sum(r["tp"] for r in out)
    fp = sum(r["fp"] for r in out)
    fn = sum(r["fn"] for r in out)
    p_lo, p_hi = wilson(tp, tp + fp)
    r_lo, r_hi = wilson(tp, tp + fn)
    f_lo, f_hi = bootstrap_f1(tp, fp, fn, rng)
    out.append({
        "scope": "ALL (pooled pairs)", "judgeable_pairs": sum(r["judgeable_pairs"] for r in out),
        "tp": tp, "fp": fp, "fn": fn,
        "precision": round(tp / (tp + fp), 4), "precision_lo": round(p_lo, 4),
        "precision_hi": round(p_hi, 4), "recall": round(tp / (tp + fn), 4),
        "recall_lo": round(r_lo, 4), "recall_hi": round(r_hi, 4),
        "f1": round(f1(tp, fp, fn), 4), "f1_lo": round(f_lo, 4), "f1_hi": round(f_hi, 4)})

    per = [r["f1"] for r in out[:-1]]
    meds = []
    for _ in range(RESAMPLES):
        meds.append(statistics.median(rng.choices(per, k=len(per))))
    meds.sort()
    out.append({
        "scope": "MEDIAN over disciplines (interval = spread between disciplines)",
        "judgeable_pairs": "", "tp": "", "fp": "", "fn": "",
        "precision": "", "precision_lo": "", "precision_hi": "",
        "recall": "", "recall_lo": "", "recall_hi": "",
        "f1": round(statistics.median(per), 4),
        "f1_lo": round(percentile(meds, 0.025), 4),
        "f1_hi": round(percentile(meds, 0.975), 4)})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    rows = compute()
    if args.check:
        with open(OUT, encoding="utf-8", newline="") as fh:
            old = list(csv.DictReader(fh))
        same = [{k: str(v) for k, v in r.items()} for r in rows] == old
        print("intervals agree with the committed CSV" if same else "intervals are STALE")
        return 0 if same else 1
    with open(OUT, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    for r in rows[-3:]:
        print("%-62s F1 %.4f [%.4f, %.4f]" % (r["scope"][:62], r["f1"], r["f1_lo"], r["f1_hi"]))
    print("wrote", os.path.basename(OUT), "(%d rows)" % len(rows))
    return 0


if __name__ == "__main__":                                  # pragma: no cover
    raise SystemExit(main())
