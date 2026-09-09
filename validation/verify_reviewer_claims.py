"""Re-derive every headline claim of the reviewer package from the files it ships.

A reviewer should not have to trust a table. This script recomputes each claim
either from the evidence file or, where the claim is about the software rather
than about a table, by running the software on the shipped input:

  C1  gold standard, live      re-runs deduplication on validation/labelled_test_set.csv
                               and checks TP/FP/FN and F1 against SUPPLEMENTARY S2
  C2  gold standard, table     asysd_metrics.csv and na_doi_fix_impact.csv are
                               arithmetically self-consistent and agree with C1
  C3  fifteen disciplines      domains_15_final.csv reproduces the S3 aggregates
                               (records, judgeable pairs, false merges, median F1)
  C4  per-discipline rows      every row's precision/recall/F1 follows from its
                               own TP/FP/FN
  C5  mechanism ablation       both ablation tables are self-consistent and the
                               ranking inversion S4 asserts is present in them
  C6  specification coverage   parser_coverage.csv really contains 32 of 32
  C7  test suite               the inventory tables agree with each other and
                               with the test tree on disk, and the suite passes
  C8  typography               no em dash, en dash or LaTeX dash run in the
                               package documentation
  C9  headline provenance      the gap between domains_15_final.csv and the
                               reproducible per-track metrics files is measured,
                               and KNOWN_ISSUES.md states it in those figures

Rule of the project: a check that passes proves nothing until it is shown to
fail on an injected error of its own class. ``--self-test`` injects one error
per check into a scratch copy and requires the check to reject it.

Usage
-----
    PYTHONPATH=. python validation/verify_reviewer_claims.py
    PYTHONPATH=. python validation/verify_reviewer_claims.py --self-test
    PYTHONPATH=. python validation/verify_reviewer_claims.py --root reviewer_package

Exit code 0 means every claim was re-derived; 1 means at least one was not.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The gold standard is scored at cluster level, the convention of Hair et al.
# (2023): a cluster counts as correctly resolved when the member the gold
# standard marks "unique" is the survivor, which credits the clustering rather
# than the arbitrary choice of representative.
GOLD_TP, GOLD_FP, GOLD_FN = 1257, 0, 4
GOLD_F1 = 0.9984

DOMAIN_RECORDS = 13809
DOMAIN_PAIRS = 2584
DOMAIN_FALSE_MERGES = 154
DOMAIN_VERSIONS = 141
DOMAIN_OVER = 13
DOMAIN_MEDIAN_F1 = 0.9592

SPEC_COVERED, SPEC_TOTAL = 32, 32

DASHES = {"\u2014": "em dash", "\u2013": "en dash"}
DASH_RUNS = (" --- ", " -- ")
DOC_SUFFIXES = (".md", ".txt", ".tex", ".html")

# Non-document files that legitimately contain a long dash, with the reason.
# Anything not listed here fails check C8, so the list is a decision record
# rather than a mute allowance.
DASH_EXCEPTIONS = {
    "code/corpusslr/dedup.py":
        "a character class that matches the en and em dash in page ranges; "
        "removing the characters would stop the parser recognising them",
    "code/corpusslr/parsers/_util.py":
        "a docstring quoting how BibTeX, EndNote and Scopus each write a page "
        "range, which requires showing the characters",
    "data/bibliometrix_verification.json":
        "prose fields recording what an R session reported, quoted verbatim",
    "data/prisma_s_checklist.json":
        "the PRISMA-S item titles as published, quoted verbatim",
    "data/references_verified.json":
        "quoted claims from the sources that were checked",
    "data/wos_live_verification.json":
        "prose fields recording a live API run, quoted verbatim",
    "data/dedup_ablation_domains.csv":
        "an em dash used as the 'not applicable' marker in the origin column "
        "of the shipped table",
    "data/domains_stem_false_positives.csv":
        "publication titles as the databases returned them",
}


class Layout:
    """Where the evidence files sit.

    The same checks run against the repository and against an unpacked
    reviewer package, which arranges the same files under data/ and
    manuscript/. Resolution tries every candidate directory in order.
    """

    def __init__(self, root: str) -> None:
        self.root = os.path.abspath(root)
        self.candidates = ["", "validation", "data", "manuscript", "code",
                           "reproduce", "figures"]

    def find(self, name: str) -> str:
        for sub in self.candidates:
            p = os.path.join(self.root, sub, name)
            if os.path.exists(p):
                return p
        raise FileNotFoundError(
            "%s not found under %s" % (name, self.root))

    def rows(self, name: str) -> list:
        with open(self.find(name), encoding="utf-8-sig", newline="") as fh:
            return list(csv.DictReader(fh))

    def text(self, name: str) -> str:
        with open(self.find(name), encoding="utf-8") as fh:
            return fh.read()


def prf(tp: int, fp: int, fn: int):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def close(a: float, b: float, tol: float = 5e-4) -> bool:
    return abs(a - b) <= tol


# --------------------------------------------------------------------------
# C1  gold standard, measured live from the shipped labelled set
# --------------------------------------------------------------------------
def _load_gold_records(path: str):
    from corpusslr.record import Record

    def clean(v):
        s = "" if v is None else str(v).strip()
        return "" if s in ("NA", "N/A", "NULL", "nan", "") else s

    recs, truth = [], {}
    with open(path, encoding="utf-8", errors="replace", newline="") as fh:
        for row in csv.DictReader(fh):
            uid = clean(row["record_id"])
            truth[uid] = row["source"]
            year = clean(row["year"])
            recs.append(Record(
                title=clean(row["title"]),
                abstract=clean(row["abstract"]),
                # The gold file stores the author list as one opaque string.
                # It is passed through unsplit on purpose: inventing author
                # boundaries with a regular expression is a harness that helps
                # the deduplicator, and the point here is to measure the
                # package, not the harness.
                authors=[clean(row["author"])] if clean(row["author"]) else [],
                year=int(year) if year.isdigit() else None,
                journal=clean(row["journal"]),
                doi=clean(row["doi"]),
                issn=clean(row["isbn"]).splitlines()[0].strip()
                if clean(row["isbn"]) else "",
                volume=clean(row["volume"]),
                issue=clean(row["number"]),
                pages=clean(row["pages"]),
                uid=uid,
            ))
    return recs, truth


def _cluster_survivors(decisions, uids, truth):
    parent = {u: u for u in uids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for d in decisions:
        a, b = find(d.kept_uid), find(d.removed_uid)
        if a != b:
            parent[b] = a
    groups = {}
    for u in uids:
        groups.setdefault(find(u), []).append(u)
    kept = set()
    for members in groups.values():
        unique = [u for u in members if truth[u] == "unique"]
        kept.add(min(unique or members, key=lambda x: int(x)))
    return kept


def check_gold_live(lay: Layout, out) -> bool:
    try:
        path = lay.find("labelled_test_set.csv")
    except FileNotFoundError:
        out.append(("C1", "SKIP", "labelled_test_set.csv is not in this package"))
        return True
    try:
        from corpusslr.dedup import deduplicate
    except ImportError as exc:  # pragma: no cover - environment problem
        out.append(("C1", "SKIP", "corpusslr not importable: %s" % exc))
        return True

    recs, truth = _load_gold_records(path)
    n_dup = sum(1 for v in truth.values() if v == "duplicate")
    n_uniq = sum(1 for v in truth.values() if v == "unique")
    if (n_dup, n_uniq) != (1261, 584):
        out.append(("C1", "FAIL", "gold composition is %d duplicate / %d unique, "
                                  "Hair et al. Table 4 is 1261 / 584"
                    % (n_dup, n_uniq)))
        return False

    res = deduplicate(recs)
    kept = _cluster_survivors(res.report.decisions, list(truth), truth)
    tp = sum(1 for u, g in truth.items() if g == "duplicate" and u not in kept)
    fn = sum(1 for u, g in truth.items() if g == "duplicate" and u in kept)
    fp = sum(1 for u, g in truth.items() if g == "unique" and u not in kept)
    p, r, f1 = prf(tp, fp, fn)
    ok = (tp, fp, fn) == (GOLD_TP, GOLD_FP, GOLD_FN) and close(f1, GOLD_F1)
    out.append(("C1", "PASS" if ok else "FAIL",
                "measured TP=%d FP=%d FN=%d precision=%.4f recall=%.4f F1=%.4f "
                "(claim TP=%d FP=%d FN=%d F1=%.4f)"
                % (tp, fp, fn, p, r, f1, GOLD_TP, GOLD_FP, GOLD_FN, GOLD_F1)))
    return ok


# --------------------------------------------------------------------------
# C2  gold standard tables
# --------------------------------------------------------------------------
def check_gold_tables(lay: Layout, out) -> bool:
    ok = True
    rows = lay.rows("na_doi_fix_impact.csv")
    after = [r for r in rows if r["stage"].startswith("after")]
    if len(after) != 1:
        out.append(("C2", "FAIL", "na_doi_fix_impact.csv has %d 'after' rows, expected 1"
                    % len(after)))
        return False
    a = after[0]
    fp, fn = int(a["FP"]), int(a["FN"])
    p, r, f1 = prf(GOLD_TP, fp, fn)
    same = (fp, fn) == (GOLD_FP, GOLD_FN)
    consistent = (close(p, float(a["precision"])) and close(r, float(a["recall"]))
                  and close(f1, float(a["f1"])))
    ok &= same and consistent
    out.append(("C2", "PASS" if same and consistent else "FAIL",
                "na_doi_fix_impact after-fix FP=%d FN=%d -> P=%.4f R=%.4f F1=%.4f; "
                "file states P=%s R=%s F1=%s" % (fp, fn, p, r, f1,
                                                 a["precision"], a["recall"], a["f1"])))

    published = 0
    for row in lay.rows("asysd_metrics.csv"):
        if row.get("metric") != "published":
            continue
        published += 1
        tp, fp2, fn2 = int(float(row["TP"])), int(row["FP"]), int(row["FN"])
        p2, r2, f2 = prf(tp, fp2, fn2)
        # Hair et al. print precision, recall and F1 rounded to three decimals,
        # so the tolerance here is one unit in the third place, not the fourth.
        good = (close(p2, float(row["precision"]), 1e-3)
                and close(r2, float(row["recall"]), 1e-3)
                and close(f2, float(row["f1"]), 1e-3))
        ok &= good
        if not good:
            out.append(("C2", "FAIL", "%s: TP=%d FP=%d FN=%d gives P=%.4f R=%.4f F1=%.4f, "
                                      "file states %s / %s / %s"
                        % (row["method"], tp, fp2, fn2, p2, r2, f2,
                           row["precision"], row["recall"], row["f1"])))
    if published:
        out.append(("C2", "PASS" if ok else "FAIL",
                    "%d published comparator rows in asysd_metrics.csv are "
                    "arithmetically self-consistent" % published))
    return ok


# --------------------------------------------------------------------------
# C3 / C4  fifteen disciplines
# --------------------------------------------------------------------------
def check_domains(lay: Layout, out) -> bool:
    rows = lay.rows("domains_15_final.csv")
    ok = True
    if len(rows) != 15:
        out.append(("C3", "FAIL", "domains_15_final.csv has %d rows, the claim is 15"
                    % len(rows)))
        ok = False

    recs = sum(int(r["n_records"]) for r in rows)
    pairs = sum(int(r["truth_pairs"]) for r in rows)
    merges = sum(int(r["pair_fp"]) for r in rows)
    versions = sum(int(r["fp_versions"]) for r in rows)
    over = sum(int(r["fp_over"]) for r in rows)
    median = statistics.median(float(r["f1"]) for r in rows)
    rate = 100.0 * over / pairs if pairs else 0.0

    for label, got, want in (("records", recs, DOMAIN_RECORDS),
                             ("judgeable pairs", pairs, DOMAIN_PAIRS),
                             ("false merges", merges, DOMAIN_FALSE_MERGES),
                             ("version variants", versions, DOMAIN_VERSIONS),
                             ("genuine over-merges", over, DOMAIN_OVER)):
        good = got == want
        ok &= good
        out.append(("C3", "PASS" if good else "FAIL",
                    "%s: table sums to %d, claim is %d" % (label, got, want)))
    good = versions + over == merges
    ok &= good
    out.append(("C3", "PASS" if good else "FAIL",
                "false merges decompose: %d versions + %d over-merges = %d"
                % (versions, over, versions + over)))
    good = close(median, DOMAIN_MEDIAN_F1)
    ok &= good
    out.append(("C3", "PASS" if good else "FAIL",
                "median F1 over 15 disciplines is %.4f, claim is %.4f"
                % (median, DOMAIN_MEDIAN_F1)))
    good = close(rate, 0.50, 0.005)
    ok &= good
    out.append(("C3", "PASS" if good else "FAIL",
                "over-merge rate is %.2f%% of judgeable pairs, claim is 0.50%%" % rate))

    bad = []
    for r in rows:
        tp, fp, fn = int(r["pair_tp"]), int(r["pair_fp"]), int(r["pair_fn"])
        p, rc, f1 = prf(tp, fp, fn)
        if not (close(p, float(r["precision"])) and close(rc, float(r["recall"]))
                and close(f1, float(r["f1"]))):
            bad.append("%s (TP=%d FP=%d FN=%d gives %.4f/%.4f/%.4f, file states %s/%s/%s)"
                       % (r["domain"], tp, fp, fn, p, rc, f1,
                          r["precision"], r["recall"], r["f1"]))
    ok &= not bad
    out.append(("C4", "PASS" if not bad else "FAIL",
                "all 15 discipline rows follow from their own confusion matrix"
                if not bad else "; ".join(bad)))
    return ok


# --------------------------------------------------------------------------
# C5  mechanism ablation
# --------------------------------------------------------------------------
def check_ablation(lay: Layout, out) -> bool:
    ok = True
    gold = lay.rows("dedup_mechanism_ablation.csv")
    for r in gold:
        tp = (GOLD_TP + GOLD_FN) - int(r["FN"])
        p, rc, f1 = prf(tp, int(r["FP"]), int(r["FN"]))
        stated = float(r["f1_without"])
        delta = GOLD_F1 - stated
        good = close(f1, stated) and close(delta, float(r["delta_f1"]))
        ok &= good
        if not good:
            out.append(("C5", "FAIL",
                        "%s: FP=%s FN=%s gives F1=%.4f and delta %.4f, file states "
                        "%s and %s" % (r["mechanism"], r["FP"], r["FN"], f1, delta,
                                       r["f1_without"], r["delta_f1"])))
    if ok:
        out.append(("C5", "PASS", "%d gold-standard ablation rows are self-consistent "
                                  "against F1 %.4f" % (len(gold), GOLD_F1)))

    dom = lay.rows("dedup_ablation_domains.csv")
    base = None
    sub_ok = True
    for r in dom:
        p, rc = float(r["precision"]), float(r["recall"])
        f1 = 2 * p * rc / (p + rc) if p + rc else 0.0
        if not close(f1, float(r["f1"])):
            sub_ok = False
            out.append(("C5", "FAIL", "%s: P=%.4f R=%.4f gives F1=%.4f, file states %s"
                        % (r["mechanism"], p, rc, f1, r["f1"])))
        if r["mechanism"].startswith("shipped"):
            base = float(r["f1"])
    if base is None:
        sub_ok = False
        out.append(("C5", "FAIL", "dedup_ablation_domains.csv has no 'shipped defaults' row"))
    else:
        for r in dom:
            d = base - float(r["f1"])
            if not close(d, float(r["delta_f1"]), 1e-3):
                sub_ok = False
                out.append(("C5", "FAIL", "%s: baseline %.4f minus %s is %.4f, file "
                                          "states delta %s" % (r["mechanism"], base,
                                                               r["f1"], d, r["delta_f1"])))
    ok &= sub_ok
    if sub_ok:
        out.append(("C5", "PASS", "%d discipline ablation rows are self-consistent "
                                  "against baseline F1 %.4f" % (len(dom), base)))

    # S4 asserts the ranking inverts between the two corpora. That is the
    # finding, so it is checked rather than restated.
    g = {r["mechanism"]: float(r["delta_f1"]) for r in gold}
    d = {r["mechanism"]: float(r["delta_f1"]) for r in dom}
    shared = sorted(set(g) & set(d))
    top_gold = max(shared, key=lambda m: g[m]) if shared else None
    top_dom = max(shared, key=lambda m: d[m]) if shared else None
    inverted = bool(shared) and top_gold != top_dom
    ok &= inverted
    out.append(("C5", "PASS" if inverted else "FAIL",
                "ranking inversion: largest delta on the gold standard is '%s' (%.4f), "
                "on the fifteen disciplines it is '%s' (%.4f)"
                % (top_gold, g.get(top_gold, 0.0), top_dom, d.get(top_dom, 0.0))))
    return ok


# --------------------------------------------------------------------------
# C6  specification coverage
# --------------------------------------------------------------------------
def check_spec_coverage(lay: Layout, out) -> bool:
    rows = lay.rows("parser_coverage.csv")
    covered = sum(1 for r in rows if r["status"] == "covered")
    ok = (covered, len(rows)) == (SPEC_COVERED, SPEC_TOTAL)
    out.append(("C6", "PASS" if ok else "FAIL",
                "parser_coverage.csv: %d of %d items covered, claim is %d of %d"
                % (covered, len(rows), SPEC_COVERED, SPEC_TOTAL)))
    return ok


# --------------------------------------------------------------------------
# C7  test suite
# --------------------------------------------------------------------------
def count_test_functions(tests_dir: str) -> dict:
    """Test functions per file, parsed from the sources rather than collected.

    Counting by parsing gives the same quantity the inventory CSV stores (test
    *functions*), which is not what pytest reports (test *cases*, parametrised
    variants expanded). Comparing the two directly is the mistake this function
    exists to avoid.
    """
    import ast
    out = {}
    for name in sorted(os.listdir(tests_dir)):
        if not (name.startswith("test_") and name.endswith(".py")):
            continue
        with open(os.path.join(tests_dir, name), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        out["tests/" + name] = sum(
            1 for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_"))
    return out


def check_tests(lay: Layout, out, run_suite: bool = True) -> bool:
    """The inventory must be self-consistent and must match the test tree.

    The stated totals are read from the inventory rather than hardcoded here.
    A constant would be wrong the first time anyone adds a test file, and would
    then report a stale figure as a verified one, which is the exact failure
    this whole script exists to prevent.
    """
    ok = True
    areas = lay.rows("supplementary_test_areas.csv")
    inv = lay.rows("supplementary_test_inventory.csv")
    a_files = sum(int(r["files"]) for r in areas)
    a_tests = sum(int(r["tests"]) for r in areas)
    i_tests = sum(int(r["tests"]) for r in inv)
    good = a_files == len(inv) and a_tests == i_tests
    ok &= good
    out.append(("C7", "PASS" if good else "FAIL",
                "test inventory is internally consistent: %d files in %d areas, "
                "%d functions by area and %d by file"
                % (len(inv), len(areas), a_tests, i_tests)
                if good else
                "test inventory disagrees with itself: %d files listed, %d "
                "counted by area; %d functions by area, %d by file"
                % (len(inv), a_files, a_tests, i_tests)))

    tests_dir = os.path.join(REPO, "tests")
    if os.path.isdir(tests_dir):
        actual = count_test_functions(tests_dir)
        listed = {r["file"]: int(r["tests"]) for r in inv}
        added = sorted(set(actual) - set(listed))
        removed = sorted(set(listed) - set(actual))
        moved = sorted(f for f in set(actual) & set(listed)
                       if actual[f] != listed[f])
        fresh = not (added or removed or moved)
        ok &= fresh
        if fresh:
            out.append(("C7", "PASS",
                        "the inventory matches the test tree: %d files, %d "
                        "functions" % (len(actual), sum(actual.values()))))
        else:
            out.append(("C7", "FAIL",
                        "the inventory is stale against the test tree "
                        "(%d files / %d functions listed, %d / %d on disk): "
                        "added %s; removed %s; count changed %s"
                        % (len(listed), i_tests, len(actual),
                           sum(actual.values()), added or "none",
                           removed or "none", moved or "none")))
    else:
        out.append(("C7", "SKIP", ("tests/ is not part of this package, so "
                                   "the inventory cannot be compared to it")))

    if not run_suite:
        out.append(("C7", "SKIP", "suite not run (--no-suite)"))
        return ok
    if not os.path.isdir(tests_dir):
        return ok
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-p", "no:cacheprovider"],
        cwd=REPO, capture_output=True, text=True,
        env=dict(os.environ, PYTHONPATH=REPO))
    m = re.search(r"(\d+) passed", proc.stdout)
    if not m:
        out.append(("C7", "FAIL", "could not read a test count from pytest output"))
        return False
    passed = int(m.group(1))
    s_m = re.search(r"(\d+) skipped", proc.stdout)
    skipped = int(s_m.group(1)) if s_m else 0
    failed = re.search(r"(\d+) failed", proc.stdout)
    good = failed is None
    ok &= good
    # Cases, not functions: pytest expands parametrised tests. The inventory
    # counts functions, so the two totals are not expected to be equal.
    out.append(("C7", "PASS" if good else "FAIL",
                "pytest: %d passed, %d skipped, %s failed (%d cases collected "
                "from %d test functions)"
                % (passed, skipped, failed.group(1) if failed else "0",
                   passed + skipped, i_tests)))
    return ok


# --------------------------------------------------------------------------
# C8  typography
# --------------------------------------------------------------------------
def scan_dashes(root: str):
    """Return [(relative path, line number, what was found)] for the tree."""
    findings = []
    for base, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs
                         if d not in ("__pycache__", ".git", ".mypy_cache",
                                      ".ruff_cache", ".pytest_cache"))
        for name in sorted(files):
            if not name.endswith(DOC_SUFFIXES):
                continue
            path = os.path.join(base, name)
            rel = os.path.relpath(path, root)
            try:
                with open(path, encoding="utf-8") as fh:
                    lines = fh.readlines()
            except (UnicodeDecodeError, OSError):
                continue
            for i, line in enumerate(lines, 1):
                for ch, label in DASHES.items():
                    if ch in line:
                        findings.append((rel, i, label))
                for run in DASH_RUNS:
                    if run in line:
                        findings.append((rel, i, "dash run '%s'" % run.strip()))
    return findings


def check_typography(lay: Layout, out) -> bool:
    """Documents use the hyphen only; other packaged files are enumerated.

    Two rules, because they are two different claims.

    Every document in the package (.md, .txt) must be free of the em dash, the
    en dash and the LaTeX dash run. The builder normalizes these when it copies
    a shared file in, so this verifies the normalization rather than trusting
    it.

    Data and source files are a different matter. A quoted publication title, a
    regular expression whose whole job is to match an en dash in a page range,
    and a docstring describing what BibTeX writes all legitimately contain the
    character; rewriting them would corrupt evidence or break the parser. Those
    files are therefore listed explicitly below with the reason. Anything not on
    the list fails, so a dash arriving in a new file is still caught.
    """
    def is_package(d):
        return os.path.exists(os.path.join(d, "MANIFEST.csv")) and \
            os.path.isdir(os.path.join(d, "manuscript"))

    if is_package(lay.root):
        target = lay.root
    elif is_package(os.path.join(lay.root, "reviewer_package")):
        target = os.path.join(lay.root, "reviewer_package")
    else:
        out.append(("C8", "SKIP", ("no built package here; run "
                                   "tools/build_reviewer_package.py first")))
        return True

    findings = scan_dashes(target)
    ok = not findings
    if ok:
        out.append(("C8", "PASS", "no em dash, en dash or dash run in any "
                                  "document under %s/"
                    % os.path.basename(target)))
    else:
        for rel, line, what in findings[:20]:
            out.append(("C8", "FAIL", "%s:%d contains %s" % (rel, line, what)))
        if len(findings) > 20:
            out.append(("C8", "FAIL", "... and %d more" % (len(findings) - 20)))

    unexpected = []
    seen = set()
    for base, dirs, files in os.walk(target):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(files):
            path = os.path.join(base, name)
            rel = os.path.relpath(path, target).replace(os.sep, "/")
            if rel.endswith((".md", ".txt")):
                continue          # covered by the document rule above
            try:
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
            except (UnicodeDecodeError, OSError):
                continue
            if "\u2014" not in text and "\u2013" not in text:
                continue
            seen.add(rel)
            if rel not in DASH_EXCEPTIONS:
                unexpected.append(rel)

    ok &= not unexpected
    if unexpected:
        for rel in unexpected[:10]:
            out.append(("C8", "FAIL", "%s contains a long dash and is not in "
                                      "the justified exception list" % rel))
    else:
        out.append(("C8", "PASS", "%d non-document files contain a long dash, "
                                  "each for a stated reason" % len(seen)))

    return ok


# --------------------------------------------------------------------------
# C9  the headline table against the per-track metrics files
# --------------------------------------------------------------------------
def check_headline_provenance(lay: Layout, out) -> bool:
    """The disclosed divergence must match the files, and must be disclosed.

    domains_15_final.csv is the table the manuscript quotes. It now has a
    producing script (validation/eval_domains_15.py, which regenerates it from
    the archived raw records and exits non-zero on disagreement), so the table
    is reproducible; when this check was written it was not, and the check was
    the only thing standing behind the number.

    What is checked here is the gap between that table and the per-track
    output, and that KNOWN_ISSUES.md states the gap in the measured figures.
    The check exists because the first draft of that document understated it;
    a disclosure nobody verifies decays into a claim.
    """
    final = {r["domain"]: r for r in lay.rows("domains_15_final.csv")}
    per = {}
    for track in ("social", "stem", "nature_hum"):
        try:
            rows = lay.rows("domains_%s_metrics.csv" % track)
        except FileNotFoundError:
            out.append(("C9", "SKIP", ("domains_%s_metrics.csv is not in this "
                                       "package" % track)))
            return True
        for r in rows:
            if r.get("level") == "domain":
                per[r["domain"]] = r

    missing = sorted(set(final) - set(per))
    if missing:
        out.append(("C9", "FAIL", "these disciplines are in the headline table "
                                  "but not in any per-track metrics file, so "
                                  "the two cannot be compared: %s"
                    % ", ".join(missing)))
        return False

    keys = ("n_records", "truth_pairs", "pair_tp", "pair_fp", "pair_fn")
    differing = sorted(d for d in final
                       if any(final[d][k] != per[d][k] for k in keys))
    per_fp = sum(int(r["pair_fp"]) for r in per.values())
    fin_fp = sum(int(r["pair_fp"]) for r in final.values())
    per_pairs = sum(int(r["truth_pairs"]) for r in per.values())
    fin_pairs = sum(int(r["truth_pairs"]) for r in final.values())
    per_med = statistics.median(float(r["f1"]) for r in per.values())
    fin_med = statistics.median(float(r["f1"]) for r in final.values())

    out.append(("C9", "PASS",
                "measured divergence: %d of %d disciplines differ; false merges "
                "%d per-track against %d headline; judgeable pairs %d against "
                "%d; median F1 %.4f against %.4f"
                % (len(differing), len(final), per_fp, fin_fp, per_pairs,
                   fin_pairs, per_med, fin_med)))

    try:
        doc = lay.text("KNOWN_ISSUES.md")
    except FileNotFoundError:
        out.append(("C9", "SKIP", ("KNOWN_ISSUES.md is not in this package, "
                                   "so the disclosure cannot be checked")))
        return True

    ok = True
    # The document must carry the measured numbers, not a rounded retelling.
    for label, value in (("false merges, per-track", per_fp),
                         ("false merges, headline", fin_fp),
                         ("judgeable pairs, per-track", per_pairs),
                         ("disciplines that differ", len(differing))):
        if str(value) not in doc:
            ok = False
            out.append(("C9", "FAIL", "KNOWN_ISSUES.md does not state the "
                                      "measured %s (%d)" % (label, value)))
    for value in ("%.4f" % per_med, "%.4f" % fin_med):
        if value not in doc:
            ok = False
            out.append(("C9", "FAIL", "KNOWN_ISSUES.md does not state the "
                                      "measured median F1 %s" % value))
    # The specific wording the first draft used, which the measurement refutes.
    if "is not affected" in doc:
        ok = False
        out.append(("C9", "FAIL", ("KNOWN_ISSUES.md still claims the headline "
                                   "table 'is not affected'")))
    if ok:
        out.append(("C9", "PASS", ("KNOWN_ISSUES.md discloses the divergence "
                                   "with the measured figures")))
    return ok


CHECKS = [
    ("C1", "gold standard, measured live", check_gold_live),
    ("C2", "gold standard tables", check_gold_tables),
    ("C3", "fifteen disciplines, aggregates", check_domains),
    ("C5", "mechanism ablation", check_ablation),
    ("C6", "specification coverage", check_spec_coverage),
    ("C7", "test suite", check_tests),
    ("C8", "typography", check_typography),
    ("C9", "headline table provenance", check_headline_provenance),
]


def run(root: str, run_suite: bool = True):
    lay = Layout(root)
    out = []
    ok = True
    for cid, _label, fn in CHECKS:
        if cid == "C7":
            ok &= fn(lay, out, run_suite)
        else:
            ok &= fn(lay, out)
    return ok, out


# --------------------------------------------------------------------------
# self-test: every check must reject an injected error of its own class
# --------------------------------------------------------------------------
def _rewrite(path: str, fn) -> None:
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
        fields = list(rows[0])
    fn(rows)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def _inject_domain_sum(d):
    _rewrite(os.path.join(d, "data", "domains_15_final.csv"),
             lambda rows: rows[0].__setitem__("n_records",
                                              str(int(rows[0]["n_records"]) + 1)))


def _inject_domain_arith(d):
    _rewrite(os.path.join(d, "data", "domains_15_final.csv"),
             lambda rows: rows[0].__setitem__("f1", "0.9999"))


def _inject_ablation(d):
    _rewrite(os.path.join(d, "data", "dedup_mechanism_ablation.csv"),
             lambda rows: rows[0].__setitem__("delta_f1", "0.5"))


def _inject_spec(d):
    _rewrite(os.path.join(d, "data", "parser_coverage.csv"),
             lambda rows: rows[0].__setitem__("status", "missing"))


def _inject_inventory(d):
    _rewrite(os.path.join(d, "data", "supplementary_test_areas.csv"),
             lambda rows: rows[0].__setitem__("tests",
                                              str(int(rows[0]["tests"]) + 7)))


def _inject_gold_table(d):
    _rewrite(os.path.join(d, "data", "na_doi_fix_impact.csv"),
             lambda rows: rows[-1].__setitem__("f1", "0.5000"))


def _inject_dash(d):
    path = os.path.join(d, "manuscript", "injected_typography.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("A line with an em dash \u2014 which the scanner must catch.\n")


def _inject_gold_input(d):
    """Relabel 40 duplicates as unique in the shipped gold set.

    C1 is a live measurement rather than a table read, so the error injected
    into it has to be an error in its input. Moving records out of the
    duplicate class changes the confusion matrix the deduplicator produces
    against it; a C1 that still reported TP 1257 would be reporting a constant.
    """
    path = os.path.join(d, "data", "labelled_test_set.csv")
    with open(path, encoding="utf-8", errors="replace", newline="") as fh:
        rows = list(csv.DictReader(fh))
        fields = list(rows[0])
    changed = 0
    for row in rows:
        if row["source"] == "duplicate" and changed < 40:
            row["source"] = "unique"
            changed += 1
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def _inject_understated_disclosure(d):
    """Restore the wording the first draft used, which the measurement refutes.

    C9 exists because a disclosure nobody verifies decays into a claim, so the
    injected error is exactly that decay: the measured numbers stay in the file
    and a sentence contradicting them comes back.
    """
    path = os.path.join(d, "KNOWN_ISSUES.md")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text + "\n\nThe headline table `data/domains_15_final.csv` "
                        "is not affected.\n")


def _inject_unlisted_dash_in_data(d):
    """Put an en dash into a data file that the exception list does not cover.

    The document rule and the data rule are separate claims, so each needs its
    own demonstration: injecting only into a .md would leave the data rule
    untested.
    """
    path = os.path.join(d, "data", "domains_summary_15.csv")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text + "\n# note: coverage 74\u201399 per cent\n")


INJECTIONS = [
    ("C1", "relabel 40 gold duplicates as unique", _inject_gold_input),
    ("C2", "corrupt the after-fix F1", _inject_gold_table),
    ("C3", "add one record to a discipline row", _inject_domain_sum),
    ("C4", "set one row's F1 to a value its matrix does not give", _inject_domain_arith),
    ("C5", "overstate one ablation delta", _inject_ablation),
    ("C6", "mark one specification item uncovered", _inject_spec),
    ("C7", "inflate one area's test count", _inject_inventory),
    ("C8", "write a document containing an em dash", _inject_dash),
    ("C8", "put an en dash in an unlisted data file",
     _inject_unlisted_dash_in_data),
    ("C9", "reinstate the understated disclosure",
     _inject_understated_disclosure),
]

# Copying the 3.8 MB gold set into every scratch tree costs more than it buys,
# so only the check that reads it gets a copy.
NEEDS_GOLD = {"C1"}


def _normalizer():
    """The builder's dash normalizer, so the scratch tree matches a real build.

    The builder lives in tools/ in the repository and in reproduce/ inside a
    built package, so it is looked up in both places. If it is not importable
    the self-test falls back to a local copy of the same substitutions, which
    keeps the self-test runnable from a package that ships the verifier without
    the builder.
    """
    for path in (os.path.join(REPO, "tools"), os.path.dirname(
            os.path.abspath(__file__))):
        if path not in sys.path:
            sys.path.insert(0, path)
    try:
        from build_reviewer_package import normalize_text
        return normalize_text
    except ImportError:
        def normalize_text(text):
            text = text.replace(" \u2014 ", " - ").replace(" \u2013 ", " - ")
            text = text.replace("\u2014", "-").replace("\u2013", "-")
            return text.replace(" --- ", " - ").replace(" -- ", " - ")
        return normalize_text


def _shipped_data_filenames():
    """Basenames the builder copies into the package's data/ directory.

    Returns None if the builder is not importable, in which case the caller
    falls back to copying everything.
    """
    for path in (os.path.join(REPO, "tools"),
                 os.path.dirname(os.path.abspath(__file__))):
        if path not in sys.path:
            sys.path.insert(0, path)
    try:
        from build_reviewer_package import BULK, INVENTORY
    except ImportError:
        return None
    return {os.path.basename(rel) for rel, sub, _ in list(INVENTORY) + list(BULK)
            if sub == "data"}


def _scratch(tmp: str, with_gold: bool) -> str:
    """A package-shaped scratch tree: data/, manuscript/ and a manifest.

    Shaped like a built package rather than like the repository because that is
    what C8 scans, and a self-test that ran against a different layout would be
    testing a different code path from the one reviewers run. Markdown is
    normalized on the way in exactly as the builder normalizes it, so the
    baseline is a clean package and the only dash in the tree is the injected
    one.
    """
    normalize_text = _normalizer()
    work = os.path.join(tmp, "reviewer_package")
    os.makedirs(os.path.join(work, "data"))
    os.makedirs(os.path.join(work, "manuscript"))
    # Mirror what the builder actually ships into data/, not everything in
    # validation/. Copying the whole directory pulled in files the package
    # never carries and made the baseline fail on their content, which would
    # turn every self-test row into a report about an unshipped file.
    shipped = _shipped_data_filenames()
    for name in sorted(os.listdir(os.path.join(REPO, "validation"))):
        src = os.path.join(REPO, "validation", name)
        if not os.path.isfile(src) or not name.endswith((".csv", ".json", ".md")):
            continue
        if shipped is not None and name not in shipped:
            continue
        if name == "labelled_test_set.csv" and not with_gold:
            continue
        dst = os.path.join(work, "data", name)
        if name.endswith(".md"):
            with open(src, encoding="utf-8") as fh:
                text = fh.read()
            with open(dst, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(normalize_text(text))
        else:
            shutil.copy2(src, dst)
    with open(os.path.join(work, "MANIFEST.csv"), "w", encoding="utf-8") as fh:
        fh.write("path,bytes,sha256,what it establishes\n")
    # C9 reads KNOWN_ISSUES.md, so the scratch tree needs the real one, built
    # from the same measurement the builder uses. Copying the shipped file
    # would be circular; generating it is what the builder does.
    _write_scratch_known_issues(work)
    _refresh_scratch_inventory(work)
    return work


def _refresh_scratch_inventory(work: str) -> None:
    """Regenerate the scratch tree's test inventory from the live test tree.

    C7 compares the inventory against ``REPO/tests``. Copying the committed CSV
    into the scratch tree makes the self-test fail whenever the committed table
    is stale for an unrelated reason, which turns a control into a tripwire for
    other people's work. Regenerating it here keeps the baseline clean by
    construction, so the only thing the self-test measures is whether each
    check rejects its own injected error.
    """
    sys.path.insert(0, os.path.join(REPO, "validation"))
    try:
        from measure_test_inventory import area_rows, measure
    except ImportError:
        return
    rows, unmapped = measure()
    if unmapped:
        return
    with open(os.path.join(work, "data", "supplementary_test_inventory.csv"),
              "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["file", "area", "tests"],
                           lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(work, "data", "supplementary_test_areas.csv"),
              "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["area", "files", "tests"],
                           lineterminator="\n")
        w.writeheader()
        w.writerows(area_rows(rows))


def _write_scratch_known_issues(work: str) -> None:
    """Render KNOWN_ISSUES.md for the scratch tree, as the builder renders it."""
    try:
        from build_reviewer_package import (KNOWN_ISSUES,
                                            measure_headline_divergence)
    except ImportError:
        return
    try:
        text = KNOWN_ISSUES.format(**measure_headline_divergence(work))
    except (FileNotFoundError, KeyError):
        return
    with open(os.path.join(work, "KNOWN_ISSUES.md"), "w", encoding="utf-8",
              newline="\n") as fh:
        fh.write(text)


def self_test() -> bool:
    """Each injected error must be rejected by the check that owns it."""
    all_ok = True
    for cid, label, inject in INJECTIONS:
        with tempfile.TemporaryDirectory() as tmp:
            work = _scratch(tmp, with_gold=cid in NEEDS_GOLD)
            # A clean run of the same tree must pass, otherwise "rejected"
            # would only mean the scratch tree was broken to begin with.
            base_ok, base_rows = run(work, run_suite=False)
            inject(work)
            ok, rows = run(work, run_suite=False)
            caught = any(r[1] == "FAIL" and r[0] == cid for r in rows)
            good = base_ok and caught and not ok
            all_ok &= good
            if not base_ok:
                first = next(r for r in base_rows if r[1] == "FAIL")
                note = ("SCRATCH TREE ALREADY FAILING before injection: %s %s"
                        % (first[0], first[2]))
            else:
                note = "rejected" if caught else "NOT DETECTED"
            print("  %-3s %-55s %s" % (cid, label, note))
    return all_ok


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=REPO,
                    help="repository root or an unpacked reviewer package")
    ap.add_argument("--self-test", action="store_true",
                    help="inject one error per check and require it to be rejected")
    ap.add_argument("--no-suite", action="store_true",
                    help="skip running pytest (C7 keeps its table checks)")
    args = ap.parse_args(argv)

    if args.self_test:
        print("self-test: each check must reject an injected error of its own class")
        ok = self_test()
        print("self-test:", "every injected error was rejected" if ok
              else "AT LEAST ONE INJECTED ERROR WENT UNDETECTED")
        return 0 if ok else 1

    ok, rows = run(args.root, run_suite=not args.no_suite)
    for cid, status, msg in rows:
        print("%-4s %-4s %s" % (cid, status, msg))
    print()
    print("every claim re-derived from the shipped files" if ok
          else "AT LEAST ONE CLAIM COULD NOT BE RE-DERIVED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
