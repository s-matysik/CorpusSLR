"""Tests for the identifier-blind validation machinery (corpusslr.validate)."""
from __future__ import annotations

import random

import pytest

from corpusslr.dedup import deduplicate, excel_mangled_pages
from corpusslr.record import Record
from corpusslr.validate import (PERTURBATIONS, apply_perturbation,
                                clusters_from_decisions, corpus_profile,
                                excel_mangle_pages, hide_identifiers,
                                pair_metrics, record_metrics, truth_groups)


def rec(uid, title, doi="", **kw):
    r = Record(title=title, doi=doi, **kw)
    r.uid = uid
    return r


# ----------------------------------------------------------------------
# hide_identifiers
# ----------------------------------------------------------------------
def test_hide_identifiers_clears_every_id_channel():
    src = rec("a", "T", doi="10.5001/X", pmid="12345", url="https://doi.org/10.5001/x",
              source_id="10.5001/X", openalex_id="W1", scopus_id="2-s2.0-1")
    src.raw = {"DOI": "10.5001/X"}
    src.provenance = [{"source_id": "10.5001/X"}]
    out = hide_identifiers([src])[0]
    assert (out.doi, out.pmid, out.openalex_id, out.scopus_id) == ("", "", "", "")
    assert out.url == "" and out.source_id == ""
    assert out.raw == {} and out.provenance == []


def test_hide_identifiers_does_not_mutate_input():
    src = rec("a", "T", doi="10.5001/x", pmid="9")
    hide_identifiers([src])
    assert src.doi == "10.5001/x" and src.pmid == "9"


def test_hide_identifiers_keeps_matchable_fields():
    src = rec("a", "Title Here", doi="10.5001/x", authors=["Kowalski, Jan"],
              year=2020, journal="J", volume="3", pages="10-20")
    out = hide_identifiers([src])[0]
    assert out.title == "Title Here" and out.year == 2020
    assert out.authors == ["Kowalski, Jan"] and out.pages == "10-20"


def test_hide_identifiers_respects_custom_field_list():
    src = rec("a", "T", doi="10.5001/x", pmid="7")
    out = hide_identifiers([src], fields=("doi",))[0]
    assert out.doi == "" and out.pmid == "7"


# ----------------------------------------------------------------------
# truth_groups
# ----------------------------------------------------------------------
def test_truth_groups_normalizes_and_skips_missing_doi():
    recs = [rec("a", "T", doi="https://doi.org/10.5001/ABC"),
            rec("b", "T", doi="10.5001/abc"),
            rec("c", "T")]
    truth = truth_groups(recs)
    assert truth == {"a": "10.5001/abc", "b": "10.5001/abc"}


def test_truth_groups_skips_records_without_uid():
    r = Record(title="T", doi="10.5001/x")
    assert truth_groups([r]) == {}


# ----------------------------------------------------------------------
# clusters_from_decisions
# ----------------------------------------------------------------------
class _Dec:
    def __init__(self, kept, removed):
        self.kept_uid, self.removed_uid = kept, removed


def test_clusters_transitive_closure():
    clusters = clusters_from_decisions([_Dec("a", "b"), _Dec("b", "c")],
                                       ["a", "b", "c", "d"])
    sets = sorted((sorted(c) for c in clusters), key=len, reverse=True)
    assert sets[0] == ["a", "b", "c"] and sets[1] == ["d"]


def test_clusters_ignores_unknown_uids():
    clusters = clusters_from_decisions([_Dec("a", "zzz")], ["a", "b"])
    assert sorted(sorted(c) for c in clusters) == [["a"], ["b"]]


def test_clusters_all_singletons_when_no_decisions():
    clusters = clusters_from_decisions([], ["a", "b", "c"])
    assert len(clusters) == 3


# ----------------------------------------------------------------------
# pair_metrics
# ----------------------------------------------------------------------
def test_pair_metrics_perfect():
    truth = {"a": "g1", "b": "g1", "c": "g2"}
    m = pair_metrics([["a", "b"], ["c"]], truth)
    assert (m["pair_tp"], m["pair_fp"], m["pair_fn"]) == (1, 0, 0)
    assert m["precision"] == m["recall"] == m["f1"] == 1.0


def test_pair_metrics_missed_pair_is_false_negative():
    truth = {"a": "g1", "b": "g1"}
    m = pair_metrics([["a"], ["b"]], truth)
    assert m["pair_fn"] == 1 and m["recall"] == 0.0


def test_pair_metrics_wrong_merge_is_false_positive():
    truth = {"a": "g1", "b": "g2"}
    m = pair_metrics([["a", "b"]], truth)
    assert m["pair_fp"] == 1 and m["precision"] == 0.0
    assert m["pair_truth"] == 0


def test_pair_metrics_ignores_unjudgeable_records():
    """A record absent from truth (no DOI) must not create TP, FP or FN."""
    truth = {"a": "g1", "b": "g1"}
    m = pair_metrics([["a", "b", "nodoi"]], truth)
    assert (m["pair_tp"], m["pair_fp"], m["pair_fn"]) == (1, 0, 0)


def test_pair_metrics_empty_truth_is_vacuously_perfect():
    m = pair_metrics([["a"], ["b"]], {})
    assert m["precision"] == 1.0 and m["recall"] == 1.0 and m["pair_truth"] == 0


def test_pair_metrics_triple_cluster_counts_three_pairs():
    truth = {"a": "g", "b": "g", "c": "g"}
    assert pair_metrics([["a", "b", "c"]], truth)["pair_tp"] == 3
    split = pair_metrics([["a", "b"], ["c"]], truth)
    assert split["pair_tp"] == 1 and split["pair_fn"] == 2


# ----------------------------------------------------------------------
# record_metrics
# ----------------------------------------------------------------------
def test_record_metrics_perfect_clustering():
    truth = {"a": "g1", "b": "g1", "c": "g2"}
    m = record_metrics([["a", "b"], ["c"]], truth)
    assert m["rec_tp"] == 1 and m["rec_fn"] == 0 and m["rec_fp"] == 0
    assert m["rec_f1"] == 1.0


def test_record_metrics_missed_duplicate_is_fn():
    truth = {"a": "g1", "b": "g1"}
    m = record_metrics([["a"], ["b"]], truth)
    assert m["rec_fn"] == 1 and m["rec_sensitivity"] == 0.0


def test_record_metrics_over_merge_removes_a_unique():
    truth = {"a": "g1", "b": "g2"}
    m = record_metrics([["a", "b"]], truth)
    assert m["rec_fp"] == 1


def test_record_metrics_ignores_clusters_without_judged_members():
    truth = {"a": "g1", "b": "g1"}
    m = record_metrics([["a", "b"], ["x", "y"]], truth)
    assert m["rec_tp"] == 1 and m["rec_fp"] == 0


# ----------------------------------------------------------------------
# corpus_profile
# ----------------------------------------------------------------------
def test_corpus_profile_empty():
    assert corpus_profile([]) == {"n": 0}


def test_corpus_profile_percentages_and_medians():
    recs = [rec("a", "one two three", doi="10.5001/a", abstract="x",
                authors=["A, B"], year=2020, journal="J", pages="1-2",
                volume="3"),
            rec("b", "one two three four five")]
    p = corpus_profile(recs)
    assert p["n"] == 2 and p["pct_doi"] == 50.0 and p["pct_abstract"] == 50.0
    assert p["median_title_words"] == 4.0     # (3 + 5) / 2
    assert p["median_authors"] == 0.5


def test_corpus_profile_flags_preprints_and_diacritics():
    recs = [rec("a", "Wp\u0142yw czego\u015b", doc_type="preprint"),
            rec("b", "Plain title", journal="bioRxiv")]
    p = corpus_profile(recs)
    assert p["pct_preprint"] == 100.0
    assert p["pct_diacritics"] == 50.0


# ----------------------------------------------------------------------
# excel_mangle_pages -- inverse of dedup.excel_mangled_pages
# ----------------------------------------------------------------------
@pytest.mark.parametrize("value,expected", [
    ("11-9", "11-Sep"),
    ("11-19", "Nov-19"),
    ("3-7", "3-Jul"),
])
def test_excel_mangle_pages_known_cases(value, expected):
    assert excel_mangle_pages(value) == expected


@pytest.mark.parametrize("value", ["413-420", "", "e0137960", "S354", "20-13"])
def test_excel_mangle_pages_out_of_scope(value):
    assert excel_mangle_pages(value) == ""


def test_mangled_output_is_recognised_by_the_dedup_guard():
    """The injected corruption must be the same shape the guard tolerates."""
    for value in ("11-9", "11-19", "3-7"):
        assert excel_mangled_pages(excel_mangle_pages(value))


# ----------------------------------------------------------------------
# perturbations
# ----------------------------------------------------------------------
def test_all_perturbations_are_registered():
    assert set(PERTURBATIONS) == {
        "truncated_title", "added_subtitle", "uppercase_title",
        "missing_authors", "year_off_by_one", "transliterated",
        "excel_mangled_pages"}


def test_apply_perturbation_rejects_unknown_name():
    with pytest.raises(ValueError):
        apply_perturbation(rec("a", "T"), "no_such_perturbation")


def test_apply_perturbation_does_not_mutate_source():
    src = rec("a", "one two three four five six seven eight nine")
    apply_perturbation(src, "truncated_title", random.Random(0))
    assert src.title == "one two three four five six seven eight nine"


def test_truncated_title_shortens_long_titles_only():
    long = rec("a", " ".join("w%d" % i for i in range(12)))
    out = apply_perturbation(long, "truncated_title", random.Random(0))
    assert out is not None and len(out.title.split()) < 12
    short = rec("b", "three word title")
    assert apply_perturbation(short, "truncated_title", random.Random(0)) is None


def test_added_subtitle_skips_titles_that_have_one():
    plain = rec("a", "A title")
    out = apply_perturbation(plain, "added_subtitle", random.Random(1))
    assert out is not None and ":" in out.title
    already = rec("b", "A title: with subtitle")
    assert apply_perturbation(already, "added_subtitle", random.Random(1)) is None


def test_uppercase_title_skips_already_uppercase():
    out = apply_perturbation(rec("a", "Mixed Case"), "uppercase_title")
    assert out is not None and out.title == "MIXED CASE"
    assert apply_perturbation(rec("b", "ALL CAPS"), "uppercase_title") is None


def test_missing_authors_requires_authors():
    out = apply_perturbation(rec("a", "T", authors=["X, Y"]), "missing_authors")
    assert out is not None and out.authors == []
    assert apply_perturbation(rec("b", "T"), "missing_authors") is None


def test_year_off_by_one_moves_year_by_exactly_one():
    src = rec("a", "T", year=2020)
    out = apply_perturbation(src, "year_off_by_one", random.Random(3))
    assert out is not None and abs(out.year - 2020) == 1
    assert apply_perturbation(rec("b", "T"), "year_off_by_one") is None


def test_transliterated_strips_diacritics_and_strokes():
    src = rec("a", "Wp\u0142yw za\u017c\u00f3\u0142\u0107",
              authors=["\u0141ukasiewicz, Jan"])
    out = apply_perturbation(src, "transliterated")
    assert out is not None
    assert out.title == "Wplyw zazolc"
    assert out.authors == ["Lukasiewicz, Jan"]


def test_transliterated_out_of_scope_for_ascii():
    assert apply_perturbation(rec("a", "Plain ascii", authors=["Smith, J"]),
                              "transliterated") is None


def test_excel_perturbation_out_of_scope_for_safe_ranges():
    assert apply_perturbation(rec("a", "T", pages="413-420"),
                              "excel_mangled_pages") is None
    out = apply_perturbation(rec("b", "T", pages="11-9"), "excel_mangled_pages")
    assert out is not None and out.pages == "11-Sep"


# ----------------------------------------------------------------------
# end-to-end: the protocol on a hand-built corpus
# ----------------------------------------------------------------------
def _two_database_corpus():
    """Same two works retrieved from two databases, with realistic drift."""
    return [
        rec("cr-1", "Dynamic capabilities and firm performance",
            doi="10.1000/A", authors=["Teece, David J."], year=2007,
            journal="Strategic Management Journal", volume="28", pages="1319-1350"),
        rec("db-1", "Dynamic Capabilities and Firm Performance",
            doi="https://doi.org/10.1000/a", authors=["Teece, D."], year=2008,
            journal="Strat. Mgmt. J.", volume="28", pages="1319-1350"),
        rec("cr-2", "Minimum wage effects on employment",
            doi="10.1000/B", authors=["Card, David"], year=1994,
            journal="American Economic Review", volume="84", pages="772-793"),
        rec("db-2", "Minimum wage effects on employment",
            doi="10.1000/b", authors=["Card, D."], year=1994,
            journal="Am Econ Rev", volume="84", pages="772-793"),
    ]


def test_end_to_end_blind_protocol_recovers_clusters():
    recs = _two_database_corpus()
    truth = truth_groups(recs)
    assert len(truth) == 4
    blinded = hide_identifiers(recs)
    assert all(not r.doi for r in blinded)
    result = deduplicate(blinded)
    clusters = clusters_from_decisions(result.report.decisions,
                                       [r.uid for r in blinded])
    m = pair_metrics(clusters, truth)
    assert m["pair_truth"] == 2
    assert m["recall"] == 1.0 and m["precision"] == 1.0


def test_end_to_end_distinct_works_are_not_merged():
    recs = _two_database_corpus()
    truth = truth_groups(recs)
    clusters = clusters_from_decisions(
        deduplicate(hide_identifiers(recs)).report.decisions,
        [r.uid for r in recs])
    # the management pair and the economics pair must stay apart
    for cluster in clusters:
        groups = {truth[u] for u in cluster if u in truth}
        assert len(groups) <= 1


def test_end_to_end_records_without_doi_are_not_scored():
    recs = _two_database_corpus()
    orphan = rec("x-1", "Completely unrelated title about something else",
                 authors=["Nobody, N."], year=2001)
    truth = truth_groups(recs + [orphan])
    assert "x-1" not in truth
    result = deduplicate(hide_identifiers(recs + [orphan]))
    clusters = clusters_from_decisions(result.report.decisions,
                                       [r.uid for r in recs] + ["x-1"])
    assert pair_metrics(clusters, truth)["f1"] == 1.0
