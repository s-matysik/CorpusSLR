"""Assemble the validation data that is uploaded alongside the article.

This is narrower than tools/build_reviewer_package.py: that one bundles the
whole evidence base including the code and the manuscript, whereas this
produces the "supplementary data" upload the journal attaches to the article -
the measurements behind every table and figure, the inputs needed to recompute
them, and the scripts that do the recomputing.

The file list is derived, not typed out. Every entry declares which element of
the article or supplement it supports, and the build fails if a declared file
is absent or if a document cites a validation file that no entry covers. That
second check is the one that matters: a reader who follows a filename from the
supplement to a package that does not contain it has found a hole in the
evidence, and only a machine notices before they do.

Usage::

    PYTHONPATH=. python tools/build_data_package.py
    PYTHONPATH=. python tools/build_data_package.py --outdir /tmp/data --no-zip
"""
import argparse
import csv
import hashlib
import os
import re
import shutil
import sys
import zipfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import corpusslr                                             # noqa: E402

PKG_DIRNAME = "corpusslr_validation_data"

#: file -> (subdirectory, what it supports). "supports" is the article or
#: supplement element the file backs, in the wording a reader looks for.
INVENTORY = (
    # --- accuracy against a published gold standard ------------------------
    ("validation/asysd_metrics.csv", "gold_standard",
     ("Supplement S2, comparison table: confusion matrix per tool on the "
      "ASySD Diabetes set, with the published values and the derived ones "
      "marked separately.")),
    ("validation/labelled_test_set.csv", "gold_standard",
     ("The ASySD Diabetes gold standard itself (Hair et al. 2023, CC BY 4.0), "
      "so S2 can be recomputed without downloading anything.")),
    ("validation/eval_asysd.py", "gold_standard",
     ("Regenerates every S2 number, the threshold sweep and the error "
      "analysis.")),
    ("validation/threshold_calibration.csv", "gold_standard",
     ("Supplement S2, threshold sweep: F1 across 20 thresholds by 3 year "
      "tolerances, the evidence that the 0.93 default is not fitted to this "
      "dataset.")),

    # --- fifteen disciplines ----------------------------------------------
    ("validation/domains_15_final.csv", "disciplines",
     ("Article Table 2 and Supplement S3: the pooled per-discipline result, "
      "identifier-blind, behind the headline accuracy figures.")),
    ("validation/eval_domains_15.py", "disciplines",
     ("Regenerates domains_15_final.csv from the raw archives below, and "
      "documents why it differs from the per-track files.")),
    ("validation/domains_social_raw.jsonl.gz", "disciplines/raw_records",
     ("Raw retrieved records, social-science disciplines: the input that "
      "makes the fifteen-discipline evaluation reproducible offline.")),
    ("validation/domains_stem_raw.jsonl.gz", "disciplines/raw_records",
     "Raw retrieved records, STEM disciplines."),
    ("validation/domains_nature_hum_raw.jsonl.gz", "disciplines/raw_records",
     ("Raw retrieved records, natural-science and humanities disciplines.")),
    ("validation/domains_social_metrics.csv", "disciplines/per_track",
     ("Per-track metrics as first measured, before the three guards were "
      "added; kept so the improvement is auditable rather than asserted.")),
    ("validation/domains_stem_metrics.csv", "disciplines/per_track",
     "Per-track metrics, STEM, pre-guard state."),
    ("validation/domains_nature_hum_metrics.csv", "disciplines/per_track",
     ("Per-track metrics, natural sciences and humanities, pre-guard state.")),
    ("validation/domains_social_false_positives.csv",
     "disciplines/false_merges",
     ("Every rejected pair classified by kind. Supports the central claim "
      "that almost all apparent false merges are version variants of one "
      "study rather than errors.")),
    ("validation/domains_stem_false_positives.csv", "disciplines/false_merges",
     "As above, STEM disciplines."),
    ("validation/domains_nature_hum_false_positives.csv",
     "disciplines/false_merges",
     "As above, natural sciences and humanities."),

    # --- mechanism ablation -----------------------------------------------
    ("validation/dedup_mechanism_ablation.csv", "ablation",
     ("Article Figure 1 and Supplement S4: F1 lost when each deduplication "
      "mechanism is switched off, measured on the gold standard.")),
    ("validation/dedup_ablation_domains.csv", "ablation",
     "Supplement S4: the same ablation across the fifteen disciplines."),
    ("validation/na_doi_fix_impact.csv", "ablation",
     ("Supplement S4: effect of rejecting a missing-value literal in the DOI "
      "field, the defect that merged unrelated works.")),

    # --- performance and downstream compatibility --------------------------
    ("validation/dedup_performance.csv", "performance",
     ("Article section 3.3: runtime and peak memory against corpus size, for "
      "both corpus shapes.")),
    ("validation/bibliometrix_verification.json", "downstream",
     ("Supplement S5: the executed round trip through bibliometrix, including "
      "the affiliation defect it found and the institution count after the "
      "fix.")),
    ("validation/scopus_roundtrip_sample.csv", "downstream",
     "The real vendor export used for that round trip, so S5 is repeatable."),

    # --- test inventory ----------------------------------------------------
    ("validation/supplementary_test_inventory.csv", "tests",
     "Supplement S1: every test file with its count and the area it covers."),
    ("validation/supplementary_test_areas.csv", "tests",
     "Supplement S1: the same inventory aggregated per area."),
    ("validation/parser_coverage.csv", "tests",
     ("Coverage of the project specification, measured by running each entry "
      "point rather than by inspection.")),

    # --- provenance --------------------------------------------------------
    ("validation/references_verified.json", "provenance",
     ("Every bibliographic anchor confirmed at Crossref, including the claims "
      "that were checked and rejected as unsupported.")),
    ("validation/wos_live_verification.json", "provenance",
     ("The live Web of Science verification record: what was queried, what "
      "came back, and the metadata completeness per field.")),
)

#: Cited filenames deliberately left out, with the reason. Anything else a
#: document cites and the inventory omits fails the build.
EXCLUDED = {
    "multidomain_raw.jsonl.gz": (
        "superseded by the fifteen-discipline archives; stands behind no "
        "figure in the submitted version"),
    "multidomain_metrics.csv": (
        "superseded by domains_15_final.csv; the article cites it only when "
        "describing the earlier four-discipline study"),
}

MANIFEST_FIELDS = ("path", "supports", "bytes", "sha256", "source")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cited_validation_files():
    """Validation filenames the article and the supplement actually name."""
    out = {}
    docs = (
        ("article", "MANUSCRIPT.md"),
        ("supplement", "SUPPLEMENTARY.md"),
        ("typeset article", os.path.join("paper", "corpusslr_softwarex.tex")),
    )
    for label, rel in docs:
        path = os.path.join(HERE, rel)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        for m in re.finditer(r"([A-Za-z0-9_]+\.(?:csv|json|jsonl\.gz))", text):
            name = m.group(1)
            if os.path.exists(os.path.join(HERE, "validation", name)):
                out.setdefault(name, set()).add(label)
    return out


def build(outdir, write_zip=True, quiet=False):
    root = os.path.join(outdir, PKG_DIRNAME)
    if os.path.exists(root):
        shutil.rmtree(root)
    os.makedirs(root)

    entries = []
    missing = []
    for rel, sub, supports in INVENTORY:
        src = os.path.join(HERE, rel)
        if not os.path.exists(src):
            missing.append(rel)
            continue
        dst_dir = os.path.join(root, sub)
        os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, os.path.basename(rel))
        shutil.copy2(src, dst)
        arc = os.path.join(sub, os.path.basename(rel)).replace(os.sep, "/")
        entries.append({
            "path": arc,
            "supports": supports,
            "bytes": os.path.getsize(dst),
            "sha256": sha256(dst),
            "source": rel,
        })

    packaged = {os.path.basename(e["source"]) for e in entries}
    uncovered = {}
    for name, srcs in cited_validation_files().items():
        if name not in packaged and name not in EXCLUDED:
            uncovered[name] = sorted(srcs)

    _write_manifest(root, entries)
    _write_readme(root, entries, uncovered)

    zip_path = None
    if write_zip:
        zip_path = os.path.join(outdir, PKG_DIRNAME + ".zip")
        _write_zip(root, zip_path)

    result = {
        "root": root,
        "zip": zip_path,
        "files": len(entries),
        "missing": missing,
        "uncovered": uncovered,
        "bytes": sum(e["bytes"] for e in entries),
    }
    if not quiet:
        print("wrote %s (%d files, %.1f MB)"
              % (root, len(entries), result["bytes"] / 1e6))
        if zip_path:
            print("wrote %s (%.1f MB)"
                  % (zip_path, os.path.getsize(zip_path) / 1e6))
        for rel in missing:
            print("  MISSING, not packaged: %s" % rel)
        for name in sorted(uncovered):
            print("  CITED BUT NOT PACKAGED: %s (named in %s)"
                  % (name, ", ".join(uncovered[name])))
    return result


def _write_zip(root, zip_path):
    """Deterministic archive: fixed timestamps, sorted members."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for base, dirs, files in os.walk(root):
            dirs[:] = sorted(dirs)
            for name in sorted(files):
                full = os.path.join(base, name)
                arc = os.path.join(PKG_DIRNAME,
                                   os.path.relpath(full, root))
                info = zipfile.ZipInfo(arc.replace(os.sep, "/"),
                                       date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                with open(full, "rb") as fh:
                    zf.writestr(info, fh.read())


def _write_manifest(root, entries):
    path = os.path.join(root, "MANIFEST.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(MANIFEST_FIELDS))
        writer.writeheader()
        for entry in entries:
            writer.writerow(entry)


INTRO = (
    ("Every table and figure in the article and the supplement is backed by a"
     " file here. MANIFEST.csv lists each file with a SHA-256 checksum and the"
     " element it supports; the same information is grouped by topic below."),
    ("The evaluation reproduces offline. The raw record archives under"
     " disciplines/raw_records/ are the retrieved records themselves, so"
     " eval_domains_15.py and eval_asysd.py recompute the published numbers"
     " without contacting any database."),
)

HOWTO = (
    ("The two scripts import the software, so install it first. Both then find"
     " their data beside themselves and need no network access:"),
)

VERIFIED = (
    ("Verified: run exactly as printed above, eval_domains_15.py --check"
     " reports agreement for all fifteen disciplines and eval_asysd.py reports"
     " F1 0.9996 at the default threshold, which are the figures the article"
     " states."),
    "Source: https://github.com/s-matysik/CorpusSLR",
)

LICENCE = (
    ("The software and these measurements are MIT-licensed."
     " gold_standard/labelled_test_set.csv is redistributed from the ASySD"
     " project (Hair K, Bahor Z, Macleod M, Liao J, Sena E. BMC Biology"
     " 21:189, 2023) under CC BY 4.0."),
)

UNRESOLVED_NOTE = (
    ("These filenames appear in the documents but are not in this package, and"
     " no omission reason is recorded for them:"),
)


def _commands():
    return [
        "pip install corpusslr==%s" % corpusslr.__version__,
        "",
        "# accuracy on the published gold standard (Supplement S2)",
        "cd gold_standard",
        "python eval_asysd.py --gold labelled_test_set.csv --skip-bench",
        "",
        "# the fifteen-discipline table (Article Table 2, Supplement S3)",
        "cd ../disciplines",
        "python eval_domains_15.py --check   # non-zero exit on disagreement",
    ]


def _write_readme(root, entries, uncovered):
    by_sub = {}
    for entry in entries:
        path = entry["path"]
        sub = path.rsplit("/", 1)[0] if "/" in path else "."
        by_sub.setdefault(sub, []).append(entry)

    lines = ["# CorpusSLR validation data", ""]
    lines.append("Supplementary data for the SoftwareX article on CorpusSLR "
                 "%s." % corpusslr.__version__)
    lines.append("")
    for para in INTRO:
        lines += [para, ""]

    lines += ["## Reproducing the numbers", ""]
    for para in HOWTO:
        lines += [para, ""]
    lines += ["```"] + _commands() + ["```", ""]
    for para in VERIFIED:
        lines += [para, ""]

    lines += ["## Contents", ""]
    for sub in sorted(by_sub):
        lines += ["### %s" % ("(top level)" if sub == "." else sub), ""]
        for entry in sorted(by_sub[sub], key=lambda e: e["path"]):
            lines.append("- **%s** (%s) - %s"
                         % (entry["path"].rsplit("/", 1)[-1],
                            _human(entry["bytes"]), entry["supports"]))
        lines.append("")

    lines += ["## Deliberate omissions", ""]
    for name in sorted(EXCLUDED):
        lines.append("- `%s` - %s" % (name, EXCLUDED[name]))
    lines.append("")

    if uncovered:
        lines += ["## Unresolved", ""]
        for para in UNRESOLVED_NOTE:
            lines += [para, ""]
        for name in sorted(uncovered):
            lines.append("- `%s` (named in %s)"
                         % (name, ", ".join(uncovered[name])))
        lines.append("")

    lines += ["## Licence", ""]
    for para in LICENCE:
        lines += [para, ""]

    with open(os.path.join(root, "README.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def _human(n):
    if n < 1024:
        return "%d B" % n
    if n < 1024 * 1024:
        return "%.1f kB" % (n / 1024.0)
    return "%.1f MB" % (n / (1024.0 * 1024.0))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--outdir", default=HERE)
    ap.add_argument("--no-zip", action="store_true")
    args = ap.parse_args(argv)
    res = build(args.outdir, write_zip=not args.no_zip)
    return 1 if (res["missing"] or res["uncovered"]) else 0


if __name__ == "__main__":                       # pragma: no cover
    sys.exit(main())
