"""The cheap predicates run before the string matcher; the output must not move.

`deduplicate()` used to compute the title similarity (difflib, the dominant
cost) before testing year and first author. The conjunction is order-independent
because every predicate is pure, so the order was changed to put the cheap tests
first. That is a claim, and this test is how it is kept honest: the digests
below were computed from the decisions of the code *before* the reordering on
three fixed synthetic corpora, and the current code must reproduce them exactly.
A change that alters any merge decision, any kept or removed record, any method
label or any score to six decimals changes the digest.
"""
import hashlib
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "validation"))

GOLDEN = {
    "realistic": (900, 150, "6c3ace17be668290c8d8bda926a602cfa1f7f6021902d2e7c4b568ef1a11b063"),
    "pathological": (1200, 699, "2910d429ea956df0bcb5161f9aa41580cde3e18cd1c92485ea260f994d2dad26"),
    "stock_stems": (500, 83, "d2fec39eb080e9e1e4ddfd4b330752711dab3e9b43c8591580ae8934b9754a84")
}


def _digest(name, n):
    import benchmark_dedup as bench
    from corpusslr import deduplicate
    recs, _truth = bench._generators()[name](n)
    res = deduplicate(recs)
    sig = sorted((d.kept_uid, d.removed_uid, d.method, round(d.score or 0, 6))
                 for d in res.report.decisions)
    return len(sig), hashlib.sha256(json.dumps(sig).encode()).hexdigest()


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_decisions_match_the_pre_reordering_output(name):
    n, count, digest = GOLDEN[name]
    got_count, got_digest = _digest(name, n)
    assert got_count == count, "%s: %d decisions, expected %d" % (name, got_count, count)
    assert got_digest == digest, "%s: the decisions changed" % name


def test_year_and_first_author_still_veto_a_merge():
    """The reordering must not have turned the cheap tests into optional ones."""
    from corpusslr import Record, deduplicate
    t = "Effect of metformin on cardiovascular outcomes in obese patients"
    base = {"title": t, "journal": "Diabetologia", "source": "pubmed"}
    far = deduplicate([Record(uid="A", year=2001, authors=["Nowak A."], **base),
                       Record(uid="B", year=2019, authors=["Nowak A."], **{**base, "source": "scopus"})])
    other = deduplicate([Record(uid="A", year=2019, authors=["Nowak A."], **base),
                         Record(uid="B", year=2019, authors=["Kowalski B."], **{**base, "source": "scopus"})])
    same = deduplicate([Record(uid="A", year=2019, authors=["Nowak A."], **base),
                        Record(uid="B", year=2019, authors=["Nowak A."], **{**base, "source": "scopus"})])
    assert (far.report.removed, other.report.removed, same.report.removed) == (0, 0, 1)
