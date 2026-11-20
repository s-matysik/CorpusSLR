"""The fifteen-discipline tables in the documents are the CSV, not copies of it.

Two digits of this table were wrong in the last place for a long time (0.8572
for 0.8571 and 0.9672 for 0.9671): the values were typed into the documents and
the checks compared totals only. Every row is now compared with
``validation/domains_15_final.csv`` after rounding to four decimals, and the F1
is recomputed from the counts so that the CSV itself cannot drift from them.
"""
import csv
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "validation"))


def _csv():
    with open(os.path.join(ROOT, "validation", "domains_15_final.csv"),
              encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _table_rows(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
        rows = {}
        for line in fh:
            if line.startswith("|"):
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                rows.setdefault(cells[0].lower(), []).append(cells)
    return rows


def test_f1_in_the_csv_follows_from_its_own_counts():
    for r in _csv():
        tp, fp, fn = int(r["pair_tp"]), int(r["pair_fp"]), int(r["pair_fn"])
        assert round(2 * tp / (2 * tp + fp + fn), 4) == pytest.approx(float(r["f1"]), abs=1e-4), r["domain"]


@pytest.mark.parametrize("doc", ["MANUSCRIPT.md", "SUPPLEMENTARY.md"])
def test_every_discipline_row_matches_the_csv(doc):
    rows = _table_rows(doc)
    for r in _csv():
        cells = [c for c in rows.get(r["domain"].lower(), []) if "0." in " ".join(c)]
        assert cells, "%s has no table row for %s" % (doc, r["domain"])
        text = " ".join(cells[0])
        for key in ("precision", "recall", "f1"):
            assert "%.4f" % float(r[key]) in cells[0], (
                "%s, %s: %s should read %.4f in %r" % (doc, r["domain"], key, float(r[key]), text))
        assert str(int(r["n_records"])) in cells[0] or "{:,}".format(int(r["n_records"])) in text


def test_the_cell_cap_option_changes_the_scored_population():
    import eval_domains_15 as E
    rows = [{"_qid": q, "source": "Crossref", "title": "t%d" % i, "doi": "10.1/%d" % i,
             "authors": [], "year": 2020} for q in ("a", "b") for i in range(5)]
    sizes = {}
    for cap in (None, 3):
        seen = {}
        orig = E.deduplicate

        def spy(records, *a, **k):
            seen["n"] = len(records)
            return orig(records, *a, **k)
        E.deduplicate = spy
        try:
            E.evaluate(rows, cell_cap=cap)
        finally:
            E.deduplicate = orig
        sizes[cap] = seen["n"]
    assert sizes[None] == 10 and sizes[3] == 6, sizes


def test_the_false_merge_export_lists_every_false_merge_with_a_class(tmp_path):
    import eval_domains_15 as E
    out = tmp_path / "fm.csv"
    assert E.main(["--check", "--false-merges", str(out)]) == 0
    with open(out, encoding="utf-8", newline="") as fh:
        merges = list(csv.DictReader(fh))
    want = sum(int(r["pair_fp"]) for r in _csv())
    assert len(merges) == want == 154
    assert all(m["kind"] for m in merges)
    with open(os.path.join(ROOT, "validation", "domains_15_false_merges.csv"),
              encoding="utf-8", newline="") as fh:
        assert list(csv.DictReader(fh)) == merges
