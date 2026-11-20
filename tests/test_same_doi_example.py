"""The article's opening example is a measurement, so it is tested.

Twelve records of the ASySD Diabetes benchmark share one conference-supplement
DOI and represent six different abstracts. The package must keep six, not one
(what a DOI-only matcher would give) and not twelve (no merging at all).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "validation"))

import same_doi_example as ex                               # noqa: E402


def test_twelve_records_six_abstracts_six_kept():
    n, abstracts, kept = ex.run()
    assert (n, abstracts, kept) == (12, 6, 6)


def test_a_doi_only_matcher_would_have_given_one():
    n, abstracts, kept = ex.run()
    assert kept > 1 and kept == abstracts


def test_an_unknown_doi_selects_nothing():
    assert ex.run(doi="10.0000/does-not-exist") == (0, 0, 0)


def test_with_both_guards_off_the_twelve_collapse_to_one(monkeypatch):
    """The example is only meaningful if removing the guards reproduces the
    failure it illustrates: a shared DOI alone merges all twelve."""
    real = ex.deduplicate
    monkeypatch.setattr(
        ex, "deduplicate",
        lambda recs: real(recs, id_title_min=0.0, separate_by_locus=False))
    assert ex.run() == (12, 6, 1)
