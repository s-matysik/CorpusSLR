"""Regenerate the test inventory tables from the test tree.

`validation/supplementary_test_inventory.csv` and
`validation/supplementary_test_areas.csv` back section S1 of the supplementary
material. Until now they had no producing script, so they froze at the moment
someone generated them by hand and went stale the next time a test file was
added: three files were added after the committed tables were written, and the
tables still reported the earlier totals.

This script counts test functions by parsing each test module, which is the
same quantity the tables store. That is deliberately not what pytest reports:
pytest counts test *cases*, with parametrised variants expanded, so the two
totals differ and are not interchangeable. Both are quoted in S1 and each needs
its own measurement.

Area names come from the mapping below. A test file that is not mapped is
reported rather than silently dropped into an "other" bucket, because a
miscategorised file is a table that quietly stops summing to the truth.

Usage:  PYTHONPATH=. python validation/measure_test_inventory.py
        PYTHONPATH=. python validation/measure_test_inventory.py --check
"""
from __future__ import annotations

import argparse
import ast
import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
TESTS = os.path.join(REPO, "tests")

INVENTORY = os.path.join(HERE, "supplementary_test_inventory.csv")
AREAS = os.path.join(HERE, "supplementary_test_areas.csv")

# file -> area. Kept explicit rather than inferred from the filename so that a
# rename cannot silently move a file into a different area of the table.
AREA_OF = {
    "test_arxiv.py": "arXiv client",
    "test_cli.py": "Command-line interface",
    "test_dedup_prisma_ext.py": "Deduplication",
    "test_docs_examples.py": "Documentation consistency",
    "test_docx.py": "Submission documents",
    "test_push_tree.py": "Submission documents",
    "test_data_package.py": "Submission documents",
    "test_enrich_quality_export.py": "Export formats",
    "test_export_scopus.py": "Scopus client and export",
    "test_file_export_integration.py": "Export formats",
    "test_harvest.py": "Reproducible harvesting",
    "test_integration_e2e.py": "End-to-end pipeline",
    "test_integrity.py": "Publication integrity",
    "test_metadata_consistency.py": "Release metadata",
    "test_notebook.py": "Colab notebook",
    "test_parser_utils.py": "File-format parsers",
    "test_parsers.py": "File-format parsers",
    "test_parsers_bibtex.py": "File-format parsers",
    "test_parsers_csv.py": "File-format parsers",
    "test_parsers_endnote.py": "File-format parsers",
    "test_parsers_enw_html.py": "File-format parsers",
    "test_parsers_query_ext.py": "File-format parsers",
    "test_parsers_ris_dialects.py": "File-format parsers",
    "test_parsers_robustness.py": "File-format parsers",
    "test_parsers_vendor_coverage.py": "File-format parsers",
    "test_pipeline.py": "End-to-end pipeline",
    "test_preprints.py": "Preprint servers",
    "test_prisma_s_items.py": "PRISMA reporting",
    "test_publishing.py": "Release metadata",
    "test_record_query.py": "Record model",
    "test_registry.py": "Source registry",
    "test_reviewer_package.py": "Reviewer package",
    "test_scopus.py": "Scopus client and export",
    "test_scopus_live_shapes.py": "Scopus client and export",
    "test_scopus_query_compliance.py": "Scopus client and export",
    "test_semanticscholar.py": "Semantic Scholar client",
    "test_site.py": "Documentation site",
    "test_sources_offline.py": "API clients",
    "test_tui.py": "Terminal interface",
    "test_validate.py": "Validation protocol",
    "test_wos_expanded.py": "Web of Science clients",
    "test_wos_starter.py": "Web of Science clients",
}


def count_functions(path: str) -> int:
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    return sum(1 for node in ast.walk(tree)
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
               and node.name.startswith("test_"))


def measure():
    rows, unmapped = [], []
    for name in sorted(os.listdir(TESTS)):
        if not (name.startswith("test_") and name.endswith(".py")):
            continue
        area = AREA_OF.get(name)
        if area is None:
            unmapped.append(name)
            continue
        rows.append({"file": "tests/" + name, "area": area,
                     "tests": count_functions(os.path.join(TESTS, name))})
    return rows, unmapped


def area_rows(rows):
    agg = {}
    for r in rows:
        a = agg.setdefault(r["area"], {"area": r["area"], "files": 0, "tests": 0})
        a["files"] += 1
        a["tests"] += r["tests"]
    # Largest first, as the supplementary table presents it.
    return sorted(agg.values(), key=lambda a: (-a["tests"], a["area"]))


def write(path, fieldnames, rows):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="report drift without writing; exit 1 if stale")
    args = ap.parse_args(argv)

    rows, unmapped = measure()
    if unmapped:
        print("test files with no area mapping (add them to AREA_OF): %s"
              % ", ".join(unmapped))
        return 1
    areas = area_rows(rows)
    total = sum(r["tests"] for r in rows)

    if args.check:
        with open(INVENTORY, encoding="utf-8", newline="") as fh:
            old = {r["file"]: int(r["tests"]) for r in csv.DictReader(fh)}
        new = {r["file"]: r["tests"] for r in rows}
        if old == new:
            print("inventory is current: %d files, %d test functions"
                  % (len(rows), total))
            return 0
        print("inventory is stale: %d files / %d functions on disk, "
              "%d / %d in the table" % (len(new), total, len(old),
                                        sum(old.values())))
        for f in sorted(set(new) - set(old)):
            print("  added:   %s (%d)" % (f, new[f]))
        for f in sorted(set(old) - set(new)):
            print("  removed: %s (%d)" % (f, old[f]))
        for f in sorted(set(old) & set(new)):
            if old[f] != new[f]:
                print("  changed: %s %d -> %d" % (f, old[f], new[f]))
        return 1

    write(INVENTORY, ["file", "area", "tests"], rows)
    write(AREAS, ["area", "files", "tests"], areas)
    print("wrote %s and %s: %d files, %d areas, %d test functions"
          % (os.path.relpath(INVENTORY, REPO), os.path.relpath(AREAS, REPO),
             len(rows), len(areas), total))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
