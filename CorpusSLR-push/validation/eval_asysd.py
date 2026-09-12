#!/usr/bin/env python3
"""Independent validation and performance benchmark of CorpusSLR deduplication
against the ASySD gold standard (Hair et al. 2023, BMC Biology 21:189).

Reproduces every number in `asysd_validation_report.md`. Self-contained: only
needs pandas + matplotlib + the CorpusSLR package on sys.path.

Usage:
    PYTHONPATH=/path/to/CorpusSLR/corpusslr python eval_asysd.py \
        --gold labelled_test_set.csv --outdir .

Outputs: asysd_metrics.csv, threshold_calibration.csv, threshold_calibration.png,
         dedup_performance.csv, dedup_performance.png, error_analysis.csv
"""
from __future__ import annotations

import argparse
import collections
import gc
import json
import random
import re
import sys
import time
import tracemalloc
from collections import defaultdict
from difflib import SequenceMatcher

import pandas as pd

# --------------------------------------------------------------------------
# 0. CLI / package import
# --------------------------------------------------------------------------
DEFAULT_GOLD = ("/Users/sebastianmatysik/.claude-science/orgs/"
                "acfa7c51-4bf1-49a5-9495-3958c15db03d/artifacts/proj_81eae4e3524e/"
                "2e07aa6d-00b7-40db-815b-a8dfd90914c5/v4b81c865_labelled_test_set.csv")
DEFAULT_PKG = "/Users/sebastianmatysik/!!!CorpusSLR/corpusslr"

ap = argparse.ArgumentParser()
ap.add_argument("--gold", default=DEFAULT_GOLD)
ap.add_argument("--pkg", default=DEFAULT_PKG)
ap.add_argument("--outdir", default=".")
ap.add_argument("--skip-bench", action="store_true")
ARGS = ap.parse_args()

if ARGS.pkg:
    sys.path.insert(0, ARGS.pkg)

from corpusslr import Record                                   # noqa: E402
from corpusslr.dedup import (deduplicate, _UnionFind,          # noqa: E402
                             _fuzzy_candidates, _conflicting_ids,
                             _title_ratio, _years_ok, _authors_ok)

OUT = ARGS.outdir.rstrip("/") or "."

# --------------------------------------------------------------------------
# 1. Load the gold standard and map to CorpusSLR records
# --------------------------------------------------------------------------
# The ASySD CSV is cp1252-encoded (contains a 0xa9 copyright sign), not UTF-8.
df = pd.read_csv(ARGS.gold, dtype=str, encoding="cp1252")

# Author strings are run together with no separator: "Wan X.Yin J.Foreman R."
# Split on a period that is directly followed by an initial-capital + lowercase
# letter, i.e. the start of the next surname. This leaves trailing initials
# ("Chen J. D. Z.") intact.
_AUTH_SPLIT = re.compile(r"\.(?=[A-Z][a-z])")


def split_authors(s: str) -> list[str]:
    if not s:
        return []
    parts = [p.strip() for p in _AUTH_SPLIT.split(str(s))]
    return [p if p.endswith(".") else p + "." for p in parts if p]


def na(v) -> str:
    """ASySD encodes missing values as the literal string 'NA'."""
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s in ("NA", "nan", "") else s


def load_records(frame: pd.DataFrame) -> list[Record]:
    recs = []
    for r in frame.to_dict("records"):
        y = na(r["year"])
        recs.append(Record(
            title=na(r["title"]),
            abstract=na(r["abstract"]),
            authors=split_authors(na(r["author"])),
            year=int(y) if y.isdigit() else None,
            journal=na(r["journal"]),
            doi=na(r["doi"]),                      # normalize_doi strips resolvers
            issn=na(r["isbn"]).split("\r")[0].split("\n")[0].strip(),
            volume=na(r["volume"]),
            issue=na(r["number"]),
            pages=na(r["pages"]),
            uid=na(r["record_id"]),
        ))
    return recs


ALL_UIDS = list(df["record_id"])
GOLD = dict(zip(df["record_id"], df["source"]))    # duplicate / unique  <- TRUTH
HUMAN = dict(zip(df["record_id"], df["label"]))    # human reviewer decision
assert collections.Counter(GOLD.values()) == {"duplicate": 1261, "unique": 584}, \
    "gold standard composition does not match Hair et al. Table 4"

# --------------------------------------------------------------------------
# 2. Metric definitions (record level, as in the ASySD paper)
# --------------------------------------------------------------------------
def metrics(kept_uids: set, gold: dict = GOLD) -> dict:
    """TP = true duplicate removed; FN = true duplicate kept;
    FP = unique record removed; TN = unique record kept."""
    TP = FN = FP = TN = 0
    for uid, g in gold.items():
        removed = uid not in kept_uids
        if g == "duplicate":
            TP += removed
            FN += not removed
        else:
            FP += removed
            TN += not removed
    sens = TP / (TP + FN) if TP + FN else 0.0
    spec = TN / (TN + FP) if TN + FP else 0.0
    prec = TP / (TP + FP) if TP + FP else 0.0
    f1 = 2 * prec * sens / (prec + sens) if prec + sens else 0.0
    return dict(TP=TP, TN=TN, FN=FN, FP=FP, sensitivity=sens,
                specificity=spec, precision=prec, f1=f1)


def clusters_of(decisions, all_uids=ALL_UIDS) -> list[list[str]]:
    """Rebuild the transitive closure of merge decisions as explicit clusters."""
    parent = {u: u for u in all_uids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for d in decisions:
        a, b = find(d.kept_uid), find(d.removed_uid)
        if a != b:
            parent[b] = a
    g = defaultdict(list)
    for u in all_uids:
        g[find(u)].append(u)
    return list(g.values())


def survivors(clusters, policy, gold=GOLD) -> set:
    """Which record in each cluster counts as 'kept'.

    'cluster'  - the gold-standard 'unique' member survives when the cluster
                 contains one (cluster-level scoring: credits the clustering,
                 not the arbitrary choice of representative).
    'first_id' - lowest record_id survives (what a reviewer importing in
                 source order would see).
    """
    kept = set()
    for c in clusters:
        if policy == "first_id":
            kept.add(min(c, key=lambda x: int(x)))
        elif policy == "cluster":
            uq = [u for u in c if gold[u] == "unique"]
            kept.add(min(uq or c, key=lambda x: int(x)))
        else:
            raise ValueError(policy)
    return kept


# --------------------------------------------------------------------------
# 3. Baseline run at shipped defaults
# --------------------------------------------------------------------------
recs = load_records(df)
t0 = time.perf_counter()
res = deduplicate(recs)                       # fuzzy_threshold=0.93, year_tol=1
BASE_SECONDS = time.perf_counter() - t0
CL = clusters_of(res.report.decisions)
BY_METHOD = dict(res.report.by_method)

M_RICHEST = metrics({r.uid for r in res.records})     # survivor = richest record
M_CLUSTER = metrics(survivors(CL, "cluster"))
M_FIRSTID = metrics(survivors(CL, "first_id"))
M_HUMAN = metrics({u for u, l in HUMAN.items() if l == "In_database"})

# merge-quality measure: how often the shipped 'richest' survivor is exactly
# the record the gold standard marks 'unique'
_kept_rich = {r.uid for r in res.records}
CLUST_WITH_UNIQUE = sum(1 for c in CL if any(GOLD[u] == "unique" for u in c))
SURVIVOR_AGREE = sum(1 for c in CL
                     if any(GOLD[u] == "unique" for u in c)
                     and all(GOLD[u] == "unique" for u in (set(c) & _kept_rich)))

# --------------------------------------------------------------------------
# 4. Stage ablation: identifier cascade only (fuzzy disabled)
# --------------------------------------------------------------------------
res_id = deduplicate(load_records(df), fuzzy_threshold=1.1)   # unreachable ratio
CL_ID = clusters_of(res_id.report.decisions)
M_ID_ONLY = metrics(survivors(CL_ID, "cluster"))

FP_FROM_ID = sum(max(0, sum(1 for u in c if GOLD[u] == "unique") - 1) for c in CL_ID)
FP_TOTAL = sum(max(0, sum(1 for u in c if GOLD[u] == "unique") - 1) for c in CL)
FN_ID_ONLY = sum(1 for c in CL_ID if not any(GOLD[u] == "unique" for u in c))
FN_TOTAL = sum(1 for c in CL if not any(GOLD[u] == "unique" for u in c))

# --------------------------------------------------------------------------
# 5. Root cause: DOIs shared by unrelated records (conference supplements)
# --------------------------------------------------------------------------
rec_by_uid = {r.uid: r for r in load_records(df)}
by_doi = defaultdict(list)
for u in ALL_UIDS:
    if rec_by_uid[u].doi:
        by_doi[rec_by_uid[u].doi].append(u)

SHARED_DOI = []
for doi, us in by_doi.items():
    titles = sorted({rec_by_uid[u].norm_title for u in us})
    if len(titles) > 1:
        mx = max(SequenceMatcher(None, a, b).ratio()
                 for i, a in enumerate(titles) for b in titles[i + 1:])
        if mx < 0.80:
            SHARED_DOI.append(dict(doi=doi, n_records=len(us),
                                   n_distinct_titles=len(titles),
                                   max_title_similarity=round(mx, 3)))
SHARED_DOI.sort(key=lambda d: -d["n_records"])
SHARED_DOI_RECORDS = sum(d["n_records"] for d in SHARED_DOI)

# --------------------------------------------------------------------------
# 6. Proposed fix, simulated OFFLINE (the package is not modified)
# --------------------------------------------------------------------------
def dedup_with_doi_title_guard(records, doi_title_min=0.50,
                               fuzzy_threshold=0.93, year_tolerance=1,
                               max_block=400):
    """Identical cascade, except an exact-identifier link is accepted only when
    the two normalized titles are at least `doi_title_min` similar. Guards
    against one DOI shared by many distinct conference abstracts."""
    rs = list(records)
    uf = _UnionFind(len(rs))
    key_owner = {}
    for idx, rec in enumerate(rs):
        for kname, val in rec.id_keys():
            if not val:
                continue
            owner = key_owner.get((kname, val))
            if owner is None:
                key_owner[(kname, val)] = idx
                continue
            if uf.find(owner) == uf.find(idx):
                continue
            if _title_ratio(rs[owner], rec) < doi_title_min:
                continue                       # <-- the guard
            uf.union(owner, idx)
    reps = sorted(uf.groups())
    rep_of = {r: r for r in reps}
    for i, j in sorted(_fuzzy_candidates(rs, reps, max_block)):
        ri, rj = uf.find(i), uf.find(j)
        if ri == rj:
            continue
        a, b = rs[rep_of.get(ri, ri)], rs[rep_of.get(rj, rj)]
        if _conflicting_ids(a, b):
            continue
        if (_title_ratio(a, b) >= fuzzy_threshold
                and _years_ok(a, b, year_tolerance) and _authors_ok(a, b)):
            root = uf.union(ri, rj)
            rep_of[root] = (rep_of.get(ri, ri) if a.richness() >= b.richness()
                            else rep_of.get(rj, rj))
    return [[rs[i].uid for i in mem] for mem in uf.groups().values()]


GUARD_ROWS = []
for g in (0.0, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8):
    for th in (0.80, 0.85, 0.90, 0.93):
        c = dedup_with_doi_title_guard(load_records(df), doi_title_min=g,
                                       fuzzy_threshold=th)
        GUARD_ROWS.append(dict(doi_title_min=g, fuzzy_threshold=th,
                               **metrics(survivors(c, "cluster"))))
GUARD = pd.DataFrame(GUARD_ROWS)
BEST_GUARD = GUARD.loc[GUARD.f1.idxmax()]

# --------------------------------------------------------------------------
# 7. Threshold calibration grid
# --------------------------------------------------------------------------
GRID_ROWS = []
for yt in (0, 1, 2):
    for th in [round(0.80 + 0.01 * i, 2) for i in range(20)]:
        r = deduplicate(load_records(df), fuzzy_threshold=th, year_tolerance=yt)
        c = clusters_of(r.report.decisions)
        mc = metrics(survivors(c, "cluster"))
        mf = metrics(survivors(c, "first_id"))
        GRID_ROWS.append(dict(
            fuzzy_threshold=th, year_tolerance=yt, n_clusters=len(c),
            doi_merges=r.report.by_method.get("doi", 0),
            fuzzy_merges=r.report.by_method.get("fuzzy", 0),
            **{f"cluster_{k}": v for k, v in mc.items()},
            **{f"firstid_{k}": v for k, v in mf.items()}))
GRID = pd.DataFrame(GRID_ROWS)
GRID.to_csv(f"{OUT}/threshold_calibration.csv", index=False)
BEST = GRID.loc[GRID.cluster_f1.idxmax()]
AT_093 = GRID[(GRID.fuzzy_threshold == 0.93) & (GRID.year_tolerance == 1)].iloc[0]

# --------------------------------------------------------------------------
# 8. Subtitle-extension analysis
#    ("Title" vs "Title: a systematic review" -- does 0.93 miss these?)
# --------------------------------------------------------------------------
by_title = defaultdict(list)
for u in ALL_UIDS:
    by_title[rec_by_uid[u].norm_title].append(u)
SUBTITLE = []
tl = list(by_title)
for a in tl:
    for b in tl:
        if a != b and b.startswith(a + " ") and len(a) > 25:
            SUBTITLE.append(dict(short=a, added=b[len(a):].strip(),
                                 ratio=round(SequenceMatcher(None, a, b).ratio(), 3),
                                 n_short=len(by_title[a]), n_long=len(by_title[b])))
SUBTITLE.sort(key=lambda d: d["ratio"])
SUBTITLE_BELOW_093 = [s for s in SUBTITLE if s["ratio"] < 0.93]

# --------------------------------------------------------------------------
# 9. Error analysis: concrete FP and FN
# --------------------------------------------------------------------------
FP_EXAMPLES, FN_EXAMPLES, ERR_ROWS = [], [], []
for c in CL:
    uq = [u for u in c if GOLD[u] == "unique"]
    if len(uq) >= 2:                                   # over-merge -> FP
        for u in uq[1:]:
            r = rec_by_uid[u]
            FP_EXAMPLES.append(f"[{r.doi or 'no DOI'}] {r.title[:120]}")
            ERR_ROWS.append(dict(kind="FP", record_id=u, year=r.year,
                                 doi=r.doi, title=r.title,
                                 cluster_size=len(c), uniques_in_cluster=len(uq)))
    if not uq:                                         # cluster of pure dups -> FN
        r = rec_by_uid[max(c, key=lambda x: rec_by_uid[x].richness())]
        FN_EXAMPLES.append(f"{r.title[:120]} ({r.year})")
        ERR_ROWS.append(dict(kind="FN", record_id=r.uid, year=r.year,
                             doi=r.doi, title=r.title,
                             cluster_size=len(c), uniques_in_cluster=0))
pd.DataFrame(ERR_ROWS).to_csv(f"{OUT}/error_analysis.csv", index=False)

# --------------------------------------------------------------------------
# 10. Comparison table
# --------------------------------------------------------------------------
PUBLISHED = {
    "ASySD":             dict(TP=1259, TN=584, FN=2,   FP=0),
    "EndNote":           dict(TP=1218, TN=584, FN=43,  FP=0),
    "SRA-DM":            dict(TP=1147, TN=514, FN=114, FP=70),
    "Human (published)": dict(TP=893,  TN=581, FN=368, FP=3),
}


def derive(d):
    TP, TN, FN, FP = d["TP"], d["TN"], d["FN"], d["FP"]
    return dict(TP=TP, TN=TN, FN=FN, FP=FP,
                sensitivity=TP / (TP + FN), specificity=TN / (TN + FP),
                precision=TP / (TP + FP) if TP + FP else 1.0,
                f1=2 * TP / (2 * TP + FP + FN))


rows = [
    dict(method="CorpusSLR (defaults, cluster-level)", provenance="this study", **M_CLUSTER),
    dict(method="CorpusSLR (defaults, first-id survivor)", provenance="this study", **M_FIRSTID),
    dict(method="CorpusSLR (defaults, richest survivor)", provenance="this study", **M_RICHEST),
    dict(method="CorpusSLR (identifier cascade only)", provenance="this study, ablation", **M_ID_ONLY),
    dict(method=(f"CorpusSLR + DOI title-guard "
                 f"(min={BEST_GUARD.doi_title_min}, thr={BEST_GUARD.fuzzy_threshold})"),
         provenance="this study, proposed fix (simulated)",
         **{k: BEST_GUARD[k] for k in
            ("TP", "TN", "FN", "FP", "sensitivity", "specificity", "precision", "f1")}),
    dict(method="Human (recomputed from label column)", provenance="this study", **M_HUMAN),
]
rows += [dict(method=k, provenance="Hair et al. 2023, Table 4", **derive(v))
         for k, v in PUBLISHED.items()]
MTAB = pd.DataFrame(rows)
for c in ("TP", "TN", "FN", "FP"):
    MTAB[c] = MTAB[c].astype(int)
MTAB.to_csv(f"{OUT}/asysd_metrics.csv", index=False)

# --------------------------------------------------------------------------
# 11. Performance benchmark
# --------------------------------------------------------------------------
STOCK = ["The effect of ", "Effects of ", "A study of ", "The role of ",
         "Impact of ", "The association between ", "Evaluation of "]
TOPIC = ["metformin", "liraglutide", "empagliflozin", "statin therapy",
         "insulin resistance", "atherosclerosis", "beta cell function",
         "GLP-1 agonists", "SGLT2 inhibition", "diabetic nephropathy",
         "cardiac remodelling", "endothelial dysfunction"]
CTX = ["in type 2 diabetes", "in ApoE knockout mice", "in obese patients",
       "in a randomised trial", "on cardiovascular outcomes",
       "in insulin-resistant rats", "after myocardial infarction"]


def synth_realistic(n, dup_frac=0.20, seed=5):
    """Duplicates carry no identifier, so only the fuzzy stage can catch them.
    Titles use stock openings ('The effect of ...') plus a rare numeric token."""
    rng = random.Random(seed)
    n_uni = int(round(n / (1 + dup_frac)))
    base = [dict(title=f"{rng.choice(STOCK)}{rng.choice(TOPIC)} "
                       f"{rng.choice(CTX)} ({rng.randrange(10**7)})",
                 year=rng.randrange(1998, 2025),
                 authors=[f"Smith{rng.randrange(5000)} A."],
                 journal="Diabetologia", source="pubmed") for _ in range(n_uni)]
    out = [Record(uid=f"U{i:07d}", **b) for i, b in enumerate(base)]
    truth = {f"U{i:07d}": f"U{i:07d}" for i in range(n_uni)}
    for j in range(n - n_uni):
        k = rng.randrange(n_uni)
        b = dict(base[k], source="scopus")
        b["title"] = b["title"].replace("The effect of", "Effect of")
        r = Record(uid=f"D{j:07d}", **b)
        truth[r.uid] = f"U{k:07d}"
        out.append(r)
    rng.shuffle(out)
    return out, truth


def synth_shared_prefix(n, seed=3):
    """Pathological: every title opens with the same seven words."""
    rng = random.Random(seed)
    n_uni = max(1, n // 2)
    out, truth = [], {}
    for i in range(n_uni):
        t = f"The effect of treatment on outcome in patients variant {i}"
        out.append(Record(uid=f"U{i:07d}", title=t, year=2015,
                          authors=["Nowak A."], journal="J", source="pubmed"))
        truth[f"U{i:07d}"] = f"U{i:07d}"
    for j in range(n - n_uni):
        k = j % n_uni
        out.append(Record(uid=f"D{j:07d}", year=2015, authors=["Nowak A."],
                          journal="J", source="scopus",
                          title=f"The effect of treatment on outcome in "
                                f"patients variant {k}"))
        truth[f"D{j:07d}"] = f"U{k:07d}"
    rng.shuffle(out)
    return out, truth


def synth_single_bucket(n, seed=3):
    """Worst case for token blocking: a 10-word closed vocabulary, so EVERY
    posting list holds all n records and every bucket exceeds max_block."""
    rng = random.Random(seed)
    words = ["the", "effect", "of", "treatment", "on", "outcome",
             "in", "patients", "with", "diabetes"]
    n_uni = max(1, n // 2)
    variants = [" ".join(rng.sample(words, len(words))) for _ in range(n_uni)]
    out, truth = [], {}
    for i, v in enumerate(variants):
        out.append(Record(uid=f"U{i:07d}", title=v, year=2015,
                          authors=["Nowak A."], journal="J", source="pubmed"))
        truth[f"U{i:07d}"] = f"U{i:07d}"
    for j in range(n - n_uni):
        k = j % n_uni
        out.append(Record(uid=f"D{j:07d}", title=variants[k], year=2015,
                          authors=["Nowak A."], journal="J", source="scopus"))
        truth[f"D{j:07d}"] = f"U{k:07d}"
    rng.shuffle(out)
    return out, truth


def pair_metrics(clusters, truth):
    """Pairwise recall/precision against planted ground truth (synthetic only)."""
    tp = fp = 0
    for c in clusters:
        for i in range(len(c)):
            for j in range(i + 1, len(c)):
                if truth[c[i]] == truth[c[j]]:
                    tp += 1
                else:
                    fp += 1
    grp = collections.Counter(truth.values())
    total = sum(k * (k - 1) // 2 for k in grp.values())
    return dict(pair_recall=round(tp / total, 4) if total else 0.0,
                pair_precision=round(tp / (tp + fp), 4) if tp + fp else 1.0)


def bench(scenario, recs_, truth):
    uids = [r.uid for r in recs_]
    gc.collect()
    tracemalloc.start()
    t0 = time.perf_counter()
    r = deduplicate(recs_)
    secs = time.perf_counter() - t0
    peak = tracemalloc.get_traced_memory()[1] / 1e6
    tracemalloc.stop()
    row = dict(scenario=scenario, n=len(recs_), seconds=round(secs, 3),
               peak_mem_mb=round(peak, 1), clusters=r.report.after,
               removed=r.report.removed,
               fuzzy_merges=r.report.by_method.get("fuzzy", 0),
               **pair_metrics(clusters_of(r.report.decisions, uids), truth))
    print(row, flush=True)
    return row


PERF_ROWS = []
if not ARGS.skip_bench:
    for n in (1000, 5000, 10000, 25000, 50000):
        PERF_ROWS.append(bench("realistic_20pct_dup", *synth_realistic(n)))
    for n in (1000, 5000, 10000, 25000, 50000):
        PERF_ROWS.append(bench("pathological_shared_prefix", *synth_shared_prefix(n)))
    for n in (1000, 2000, 4000):
        PERF_ROWS.append(bench("single_bucket_closed_vocab", *synth_single_bucket(n)))
    # fine scan across the max_block=400 discontinuity
    for n in (500, 1000, 2000, 3000, 4000, 5000, 6000, 8000, 10000):
        PERF_ROWS.append(bench("scan_realistic", *synth_realistic(n)))
PERF = pd.DataFrame(PERF_ROWS)
PERF.to_csv(f"{OUT}/dedup_performance.csv", index=False)

# --------------------------------------------------------------------------
# 12. Figures
# --------------------------------------------------------------------------
import matplotlib                                              # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt                                # noqa: E402

try:
    apply_figure_style                                         # noqa: B018
except NameError:
    def apply_figure_style(sizes=(8, 7, 6)):
        base, mid, small = sizes
        plt.rcParams.update({
            "figure.dpi": 300, "savefig.dpi": 300, "font.size": base,
            "axes.titlesize": base, "axes.labelsize": base,
            "legend.fontsize": mid, "xtick.labelsize": small,
            "ytick.labelsize": small, "axes.spines.top": False,
            "axes.spines.right": False, "axes.grid": True,
            "grid.alpha": 0.25, "grid.linewidth": 0.5,
            "savefig.bbox": "tight", "legend.frameon": False,
        })

apply_figure_style(sizes=(8, 7, 6))

C_F1, C_PREC, C_SENS = "#B2182B", "#2166AC", "#4D9221"
GREY = "#8C8C8C"
S_REAL, S_PREFIX, S_BUCKET = ("#B2182B", "o"), ("#2166AC", "s"), ("#B8860B", "^")


def make_figures(GRID, PERF, out=OUT):
    """Render both deliverable figures from the two result tables."""
    # --- Figure 1: threshold calibration ---------------------------------
    fig1, axes = plt.subplots(1, 3, figsize=(7.0, 2.6), sharey=True)
    for ax, yt in zip(axes, (0, 1, 2)):
        s = GRID[GRID.year_tolerance == yt].sort_values("fuzzy_threshold")
        ax.plot(s.fuzzy_threshold, s.cluster_sensitivity, "-^", ms=2.6, lw=1.1, color=C_SENS)
        ax.plot(s.fuzzy_threshold, s.cluster_f1, "-o", ms=2.8, lw=1.5, color=C_F1)
        ax.plot(s.fuzzy_threshold, s.cluster_precision, "-s", ms=2.6, lw=1.1, color=C_PREC)
        ax.axvline(0.93, color=GREY, lw=0.9, ls="--", zorder=0)
        ax.set_title(f"year tolerance = {yt}")
        ax.set_xlabel("fuzzy title-similarity threshold", labelpad=3)
        ax.set_xlim(0.792, 1.008)
        ax.set_xticks([0.80, 0.85, 0.90, 0.95, 1.00])
        ax.margins(y=0.12)
    axes[0].set_ylabel("score (record level)")
    axes[0].annotate("shipped\ndefault", xy=(0.93, 0.9745), xytext=(0.875, 0.9715),
                     fontsize=6, color=GREY, ha="center", va="center",
                     arrowprops=dict(arrowstyle="->", color=GREY, lw=0.7))
    s2 = GRID[GRID.year_tolerance == 2].sort_values("fuzzy_threshold")
    for lab, key, col in (("recall", "cluster_sensitivity", C_SENS),
                          ("F1", "cluster_f1", C_F1),
                          ("precision", "cluster_precision", C_PREC)):
        axes[2].annotate(lab, xy=(0.9915, s2[key].iloc[-1]), xytext=(4, 0),
                         textcoords="offset points", color=col, fontsize=7,
                         va="center", ha="left")
    axes[0].text(0.02, 0.055, "higher = better", transform=axes[0].transAxes,
                 fontsize=6, color=GREY, ha="left", va="bottom")
    fig1.suptitle("Threshold has almost no leverage: the error floor is set by the "
                  "identifier stage, not the fuzzy stage", fontsize=8, y=1.04)
    fig1.subplots_adjust(wspace=0.06)
    fig1.savefig(f"{out}/threshold_calibration.png", bbox_inches="tight")

    # --- Figure 2: performance and the recall cliff ----------------------
    # With --skip-bench there is no performance run, so PERF is an empty frame
    # with no columns at all. The per-series guard below tests s.empty, which
    # is too late: PERF.scenario raises AttributeError first. The accuracy
    # metrics are already written by this point, so the right behaviour is to
    # skip the figure and say so, not to abort the evaluation.
    if PERF is None or PERF.empty or "scenario" not in PERF.columns:
        print("performance figure skipped: no benchmark run in this invocation "
              "(--skip-bench). Accuracy metrics are unaffected.")
        return

    fig2, (axA, axB, axC) = plt.subplots(1, 3, figsize=(7.2, 2.6))
    series = [("realistic_20pct_dup", *S_REAL, "realistic (20% dup.)"),
              ("pathological_shared_prefix", *S_PREFIX, "shared title prefix"),
              ("single_bucket_closed_vocab", *S_BUCKET, "closed 10-word vocab.")]
    for scen, col, mk, lab in series:
        s = PERF[PERF.scenario == scen].sort_values("n")
        if s.empty:
            continue
        axA.plot(s.n, s.seconds, "-", marker=mk, ms=3.4, lw=1.4, color=col, label=lab)
        axB.plot(s.n, s.peak_mem_mb, "-", marker=mk, ms=3.4, lw=1.4, color=col)
        axC.plot(s.n, s.pair_recall, "-", marker=mk, ms=3.4, lw=1.4, color=col)
    scan = PERF[PERF.scenario == "scan_realistic"].sort_values("n")
    if not scan.empty:
        axA.plot(scan.n, scan.seconds, ":", marker=".", ms=3, lw=1.0,
                 color=C_F1, alpha=0.5, label="realistic, fine scan")
    axA.set_xscale("log"); axA.set_yscale("log")
    axA.set_ylabel("wall-clock time (s)")
    axA.set_title("Runtime drops when\nbuckets exceed max_block")
    axA.legend(loc="lower left", fontsize=5.5, handlelength=1.6,
               borderaxespad=0.2, labelspacing=0.3, bbox_to_anchor=(-0.02, -0.02))
    axB.set_xscale("log")
    axB.set_ylabel("peak traced memory (MB)")
    axB.set_title("Memory is linear\nin corpus size")
    axC.set_xscale("log")
    axC.set_ylabel("pairwise recall of planted duplicates")
    axC.set_title("...but the skipped buckets\nare skipped silently")
    axC.set_ylim(-0.06, 1.10)
    axC.axhline(1.0, color=GREY, lw=0.7, ls=":", zorder=0)
    axC.annotate("0 duplicates found\nat any size", xy=(4300, 0.02),
                 xytext=(0.42, 0.30), textcoords="axes fraction",
                 fontsize=6, color=S_BUCKET[0], ha="left", va="center",
                 arrowprops=dict(arrowstyle="->", color=S_BUCKET[0], lw=0.7))
    for ax in (axA, axB, axC):
        ax.set_xlabel("records in corpus", labelpad=3)
        ax.set_xticks([1e3, 1e4, 5e4])
        ax.set_xticklabels(["1k", "10k", "50k"])
        ax.margins(x=0.06)
    axA.text(0.97, 0.97, "lower = better", transform=axA.transAxes,
             fontsize=6, color=GREY, ha="right", va="top")
    axC.text(0.97, 0.055, "higher = better", transform=axC.transAxes,
             fontsize=6, color=GREY, ha="right", va="bottom")
    fig2.subplots_adjust(wspace=0.42)
    fig2.savefig(f"{out}/dedup_performance.png", bbox_inches="tight")
    return fig1, fig2


make_figures(GRID, PERF)

# --------------------------------------------------------------------------
# 13. Machine-readable summary for the report
# --------------------------------------------------------------------------
SUMMARY = dict(
    base_seconds=round(BASE_SECONDS, 2),
    by_method=BY_METHOD,
    n_clusters=len(CL),
    metrics=dict(cluster=M_CLUSTER, first_id=M_FIRSTID, richest=M_RICHEST,
                 id_only=M_ID_ONLY, human_recomputed=M_HUMAN),
    survivor_agreement=dict(agree=SURVIVOR_AGREE, of=CLUST_WITH_UNIQUE),
    fp_from_id_stage=FP_FROM_ID, fp_total=FP_TOTAL,
    fn_id_only=FN_ID_ONLY, fn_total=FN_TOTAL,
    shared_doi_groups=len(SHARED_DOI), shared_doi_records=SHARED_DOI_RECORDS,
    shared_doi_top=SHARED_DOI[:10],
    best_grid=dict(fuzzy_threshold=float(BEST.fuzzy_threshold),
                   year_tolerance=int(BEST.year_tolerance),
                   f1=float(BEST.cluster_f1), FP=int(BEST.cluster_FP),
                   FN=int(BEST.cluster_FN)),
    at_default=dict(f1=float(AT_093.cluster_f1), FP=int(AT_093.cluster_FP),
                    FN=int(AT_093.cluster_FN)),
    best_guard=dict(doi_title_min=float(BEST_GUARD.doi_title_min),
                    fuzzy_threshold=float(BEST_GUARD.fuzzy_threshold),
                    f1=float(BEST_GUARD.f1), TP=int(BEST_GUARD.TP),
                    FP=int(BEST_GUARD.FP), FN=int(BEST_GUARD.FN),
                    precision=float(BEST_GUARD.precision),
                    sensitivity=float(BEST_GUARD.sensitivity)),
    subtitle_pairs=len(SUBTITLE), subtitle_below_093=SUBTITLE_BELOW_093,
    fp_examples=FP_EXAMPLES[:12], fn_examples=FN_EXAMPLES[:12],
    performance=PERF_ROWS,
)
with open(f"{OUT}/eval_summary.json", "w") as fh:
    json.dump(SUMMARY, fh, indent=1, default=str)

print("\n=== comparison table ===")
print(MTAB.round(4).to_string(index=False))
print("\n=== summary ===")
print(json.dumps({k: v for k, v in SUMMARY.items()
                  if k not in ("performance", "fp_examples", "fn_examples",
                               "shared_doi_top", "subtitle_below_093")},
                 indent=1, default=str))
