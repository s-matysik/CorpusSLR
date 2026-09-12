"""Offline tests pinning ``SearchQuery.to_scopus()`` against measured API behaviour.

Each clause of the compiled query string was executed against the live Scopus
Search API and its ``opensearch:totalResults`` recorded with and without the
clause, so that a clause which is silently ignored - or which narrows the result
set differently from what the compiler intends - is detectable.  Those live
counts are quoted in the docstrings below and reported in
``scopus_api_characterisation.md``; the assertions here pin the *string* that
produced them, which is what makes the reported search reproducible
(PRISMA-S Item 8).

Base query used for all measurements::

    (TITLE-ABS-KEY("machine learning" OR "deep learning"))
      AND TITLE-ABS-KEY("systematic review")

which matched 18874 records.
"""
from __future__ import annotations

import pytest

from corpusslr.query import SearchQuery

BLOCKS = [["machine learning", "deep learning"], ["systematic review"]]

#: Live totalResults for the base query and each single-clause variant.
MEASURED = {
    "base": 18874,
    "years_2020_2023": 5554,
    "doctype_article": 5219,
    "doctype_review": 10221,
    "doctype_article_or_review": 15440,
    "language_english": 18435,
    "all_clauses": 4458,
}

#: PUBYEAR IS <y> counts for the same base query; they sum to the range count,
#: which proves the compiled range is inclusive on both bounds.
MEASURED_PER_YEAR = {2020: 564, 2021: 1070, 2022: 1640, 2023: 2280}


def _q(**kw):
    return SearchQuery(blocks=[list(b) for b in BLOCKS], **kw)


# --------------------------------------------------------------------------
# blocks
# --------------------------------------------------------------------------

def test_base_query_string_is_the_one_that_was_measured():
    assert _q().to_scopus() == (
        '(TITLE-ABS-KEY("machine learning" OR "deep learning")) '
        'AND TITLE-ABS-KEY("systematic review")')


def test_every_clause_narrows_the_result_set_none_is_silently_ignored():
    """A clause that the API ignored would leave totalResults at 18874."""
    for key in ("years_2020_2023", "doctype_article",
                "doctype_article_or_review", "language_english"):
        assert MEASURED[key] < MEASURED["base"], key


# --------------------------------------------------------------------------
# PUBYEAR
# --------------------------------------------------------------------------

def test_year_range_compiles_to_a_parenthesised_exclusive_bound_pair():
    """years=(2020, 2023) -> (PUBYEAR > 2019 AND PUBYEAR < 2024).

    Scopus has no inclusive PUBYEAR comparison operator, so the compiler widens
    each bound by one year.  The live counts confirm the range is inclusive of
    both endpoints: the four per-year counts sum exactly to the range count.
    """
    s = _q(years=(2020, 2023)).to_scopus()
    assert "(PUBYEAR > 2019 AND PUBYEAR < 2024)" in s


def test_per_year_counts_sum_to_the_range_count_so_both_bounds_are_included():
    assert sum(MEASURED_PER_YEAR.values()) == MEASURED["years_2020_2023"]
    assert sorted(MEASURED_PER_YEAR) == [2020, 2021, 2022, 2023]


def test_single_year_range_still_emits_both_bounds():
    s = _q(years=(2019, 2019)).to_scopus()
    assert "(PUBYEAR > 2018 AND PUBYEAR < 2020)" in s


def test_pubyear_clause_is_parenthesised_so_it_cannot_bind_to_a_doctype_or():
    """Measured: bare and parenthesised bounds both gave 4545 next to
    (DOCTYPE(ar) OR DOCTYPE(re)), i.e. Scopus binds AND tighter than OR and the
    parentheses are not strictly required.  They are emitted anyway because the
    reported search string must be unambiguous to a human reader who re-runs it
    in another interface, where precedence may differ."""
    s = _q(years=(2020, 2023), doc_types=["article", "review"]).to_scopus()
    assert "(PUBYEAR > 2019 AND PUBYEAR < 2024)" in s
    assert "(DOCTYPE(ar) OR DOCTYPE(re))" in s


# --------------------------------------------------------------------------
# DOCTYPE
# --------------------------------------------------------------------------

def test_doctype_codes_are_two_letter_scopus_codes():
    assert "DOCTYPE(ar)" in _q(doc_types=["article"]).to_scopus()
    assert "DOCTYPE(re)" in _q(doc_types=["review"]).to_scopus()
    assert "DOCTYPE(cp)" in _q(doc_types=["conference"]).to_scopus()


def test_doctype_or_group_is_the_union_of_its_members():
    """Measured: ar=5219, re=10221, (ar OR re)=15440 = 5219+10221.

    The exact sum shows DOCTYPE is single-valued per record, so an OR group over
    document types cannot double-count - the yield of a multi-type filter is
    predictable from the per-type counts.
    """
    assert (MEASURED["doctype_article"] + MEASURED["doctype_review"]
            == MEASURED["doctype_article_or_review"])


def test_unknown_doctype_is_dropped_with_a_warning_not_passed_through():
    """Measured: DOCTYPE(zz) is accepted by the API and matches 0 records, so
    passing an unmapped type through would silently empty the search."""
    q = _q(doc_types=["article", "dataset"])
    s = q.to_scopus()
    assert "DOCTYPE(ar)" in s
    assert "dataset" not in s
    assert any("dataset" in w for w in q.warnings)


# --------------------------------------------------------------------------
# LANGUAGE
# --------------------------------------------------------------------------

#: Live counts for LANGUAGE(<value>) on the base query.  An ISO code is neither
#: translated nor rejected: it matches zero records.
MEASURED_LANG = {
    "english": 18435, "English": 18435,
    "japanese": 1, "ja": 0,
    "german": 17, "de": 0,
    "chinese": 258, "zh": 0,
    "dutch": 0, "nl": 0,
    "klingon": 0,
}


@pytest.mark.parametrize("code,name", [
    ("en", "english"), ("ja", "japanese"), ("de", "german"),
    ("zh", "chinese"), ("nl", "dutch"), ("pl", "polish"),
    ("ko", "korean"), ("ar", "arabic"), ("tr", "turkish"),
])
def test_iso_codes_compile_to_scopus_language_names(code, name):
    """Regression test for a silent-zero-result bug.

    LANGUAGE() takes English language names, not ISO codes, and an unknown value
    is accepted with zero hits rather than rejected: LANGUAGE(ja) matched 0
    records where LANGUAGE(japanese) matched 1, LANGUAGE(de) 0 against
    LANGUAGE(german) 17, LANGUAGE(zh) 0 against LANGUAGE(chinese) 258.  Only
    nine codes used to be translated, so any other code emptied the whole
    search with no error visible to the reviewer.
    """
    s = _q(languages=[code]).to_scopus()
    assert "LANGUAGE({})".format(name) in s
    assert "LANGUAGE({})".format(code) not in s


def test_measured_iso_codes_matched_zero_records_before_the_fix():
    for code in ("ja", "de", "zh", "nl"):
        assert MEASURED_LANG[code] == 0
    assert MEASURED_LANG["japanese"] > 0
    assert MEASURED_LANG["german"] > 0
    assert MEASURED_LANG["chinese"] > 0


def test_language_matching_is_case_insensitive_so_names_pass_through():
    """Measured: LANGUAGE(English) and LANGUAGE(english) both gave 18435."""
    assert MEASURED_LANG["English"] == MEASURED_LANG["english"]
    assert "LANGUAGE(english)" in _q(languages=["English"]).to_scopus()


def test_unmappable_short_code_is_omitted_with_a_warning():
    """Dropping the clause keeps the search valid; emitting LANGUAGE(xx) would
    reduce it to zero hits silently."""
    q = _q(languages=["xx"])
    s = q.to_scopus()
    assert "LANGUAGE" not in s
    assert any("xx" in w and "zero records" in w for w in q.warnings)


def test_a_mappable_code_survives_alongside_an_unmappable_one():
    q = _q(languages=["ja", "xx"])
    s = q.to_scopus()
    assert "LANGUAGE(japanese)" in s
    assert "xx" not in s
    assert any("xx" in w for w in q.warnings)


def test_multiple_languages_form_one_or_group():
    """Measured: LANGUAGE(english OR chinese)=18660 > english alone=18435, and
    18660 = 18435 + 258 - 33 overlapping bilingual records."""
    s = _q(languages=["en", "zh"]).to_scopus()
    assert "LANGUAGE(english OR chinese)" in s


def test_duplicate_language_codes_are_collapsed():
    s = _q(languages=["en", "English", "en"]).to_scopus()
    assert s.count("english") == 1


def test_language_warning_is_not_duplicated_across_repeated_compilations():
    q = _q(languages=["xx"])
    q.to_scopus()
    q.to_scopus()
    assert len([w for w in q.warnings if "xx" in w]) == 1


# --------------------------------------------------------------------------
# full realistic strategy
# --------------------------------------------------------------------------

def test_full_strategy_string_is_the_one_that_was_measured():
    q = _q(years=(2020, 2023), doc_types=["article", "review"],
           languages=["en"])
    assert q.to_scopus() == (
        '(TITLE-ABS-KEY("machine learning" OR "deep learning")) '
        'AND TITLE-ABS-KEY("systematic review") '
        'AND (PUBYEAR > 2019 AND PUBYEAR < 2024) '
        'AND (DOCTYPE(ar) OR DOCTYPE(re)) '
        'AND LANGUAGE(english)')
    assert not q.warnings


def test_combined_filters_narrow_further_than_any_single_one():
    assert MEASURED["all_clauses"] < min(
        MEASURED["years_2020_2023"], MEASURED["doctype_article_or_review"],
        MEASURED["language_english"])


def test_title_only_switches_the_field_but_keeps_the_other_clauses():
    q = _q(years=(2020, 2023), languages=["en"])
    q.title_only = True
    s = q.to_scopus()
    assert s.startswith('(TITLE("machine learning" OR "deep learning"))')
    assert "TITLE-ABS-KEY" not in s
    assert "LANGUAGE(english)" in s
