"""Shared export-parser normalizers (corpusslr.parsers._util)."""
import pytest

from corpusslr.parsers._util import (clean_pages, collapse_ws, map_doc_type,
                                     normalize_author_name, parse_int,
                                     parse_year, split_authors,
                                     split_keywords)


@pytest.mark.parametrize("raw,expected", [
    ("Kowalski, Jan", "Kowalski, Jan"),
    ("Kowalski J.", "Kowalski, J."),
    ("Kowalski JM", "Kowalski, JM"),
    ("Jan Kowalski", "Kowalski, Jan"),
    ("J. Kowalski", "Kowalski, J."),
    ("J. M. Kowalski", "Kowalski, J. M."),
    ("Ludwig van Beethoven", "van Beethoven, Ludwig"),
    ("Vincent van Gogh", "van Gogh, Vincent"),
    ("Maria de la Cruz", "de la Cruz, Maria"),
    ("Wr\u00f3bel, \u0141ukasz", "Wr\u00f3bel, \u0141ukasz"),
    ("\u00c5sa Andersson", "Andersson, \u00c5sa"),
    ("Smith, John, Jr.", "Smith, John"),
    ("John Smith Jr", "Smith, John"),
    ("Madonna", "Madonna"),
    ("OECD", "OECD"),
    ("", ""),
    (None, ""),
    ("   ", ""),
    (",", ""),
])
def test_normalize_author_name(raw, expected):
    assert normalize_author_name(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("Kowalski J.; Nowak A.", ["Kowalski, J.", "Nowak, A."]),
    ("Jan Kowalski and Anna Nowak", ["Kowalski, Jan", "Nowak, Anna"]),
    ("Smith, John, Doe, Jane", ["Smith, John", "Doe, Jane"]),
    ("Smith, John", ["Smith, John"]),
    ("Kowalski, Jan; Nowak, Anna; et al.", ["Kowalski, Jan", "Nowak, Anna"]),
    ("", []),
    (None, []),
    (["Kowalski, Jan", "Anna Nowak"], ["Kowalski, Jan", "Nowak, Anna"]),
])
def test_split_authors(raw, expected):
    assert split_authors(raw) == expected


def test_split_authors_keeps_ambiguous_comma_cell_whole():
    """Three comma-separated parts cannot be split safely."""
    assert split_authors("Smith, John, Doe") == ["Smith, John Doe"]


def test_split_authors_without_normalization():
    assert split_authors("Jan Kowalski; Anna Nowak", normalize=False) \
        == ["Jan Kowalski", "Anna Nowak"]


@pytest.mark.parametrize("raw,expected", [
    ("a; b; c", ["a", "b", "c"]),
    ("a, b, c", ["a", "b", "c"]),
    ("a | b", ["a", "b"]),
    # ';' wins over ',' -- a keyword phrase may legitimately contain a comma
    ("machine learning, deep learning; AI",
     ["machine learning, deep learning", "AI"]),
    ("dup; DUP; other", ["dup", "other"]),
    ("  spaced  ;  out  ", ["spaced", "out"]),
    ("", []),
    (None, []),
    ([" x ", "y", ""], ["x", "y"]),
])
def test_split_keywords(raw, expected):
    assert split_keywords(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("10--20", "10-20"),
    ("10\u201320", "10-20"),
    ("10 - 20", "10-20"),
    ("e12345", "e12345"),
    ("601-612", "601-612"),
    ("", ""),
    (None, ""),
    ("-", ""),
])
def test_clean_pages(raw, expected):
    assert clean_pages(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    (2024, 2024), ("2024", 2024), ("2024.0", 2024), (2024.0, 2024),
    ("2024-05-01", 2024), ("May 2024", 2024), ("", None), (None, None),
    ("n.d.", None), ("in press", None), (12, None), ("1899", 1899),
])
def test_parse_year(raw, expected):
    assert parse_year(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    (12, 12), ("12", 12), ("12.0", 12), ("1,234", 1234), ("", None),
    (None, None), ("n/a", None), (True, None), ("Cited by 7", 7),
])
def test_parse_int(raw, expected):
    assert parse_int(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("Article", "article"),
    ("Journal Article", "article"),
    ("Review", "review"),
    ("Systematic Review", "review"),
    ("Conference Paper", "conference"),
    ("Proceedings Paper", "conference"),
    ("Book Chapter", "chapter"),
    ("Book Section", "chapter"),
    ("Book", "book"),
    ("Thesis", "thesis"),
    ("Doctoral Dissertation", "thesis"),
    ("Technical Report", "report"),
    ("Editorial Material", "editorial"),
    ("Letter", "letter"),
    ("Preprint", "preprint"),
    ("", ""),
    (None, ""),
    ("Nonsense Type", ""),
])
def test_map_doc_type(raw, expected):
    assert map_doc_type(raw) == expected


def test_map_doc_type_precedence_review_over_article():
    assert map_doc_type("Review Article") == "review"
    assert map_doc_type("Conference Paper (Article)") == "conference"


def test_collapse_ws():
    assert collapse_ws("  a\n b\t c ") == "a b c"
    assert collapse_ws(None) == "" and collapse_ws("") == ""


# --------------------------------------------------------------------------
# Author lists exported with no separator at all.
#
# "Adeli K.Lewis G. F." is two authors: the initial's period doubles as the
# separator. Reference managers export this form, and the entire author column
# of the ASySD Diabetes gold standard is in it. Without this handling the cell
# became one mangled author, so author evidence contributed nothing to matching
# and three true duplicates went unmerged: measured on that gold standard, the
# cluster-level F1 was 0.9984 (TP 1257, FN 4) with the cell kept whole and
# 0.9996 (TP 1260, FN 1) once it is parsed. The earlier figure was reachable
# only by preprocessing the file in the evaluation harness, i.e. by a step the
# package's own users do not have.
# --------------------------------------------------------------------------

def test_a_separatorless_author_list_is_split():
    assert split_authors("Adeli K.Lewis G. F.") == ["Adeli, K.", "Lewis, G. F."]
    assert split_authors("Kowalski J.Nowak A.") == ["Kowalski, J.", "Nowak, A."]


def test_a_multiword_surname_survives_the_split():
    assert split_authors("van der Berg A.Muller B.") == ["van der Berg, A.",
                                                         "Muller, B."]


def test_an_initial_run_is_not_a_separator():
    """"Smith J.R." is one author, not "Smith J." plus "R."."""
    assert split_authors("Smith J.R.") == ["Smith, J.R."]


def test_an_explicit_separator_still_wins():
    """Semicolons take precedence, so a mixed cell is not split twice."""
    assert split_authors("Smith, John; Doe, Jane") == ["Smith, John", "Doe, Jane"]


def test_a_single_name_with_a_trailing_period_is_not_split():
    assert split_authors("Lee, Sang-Hoon") == ["Lee, Sang-Hoon"]
    assert split_authors("O'Brien P.") == ["O'Brien, P."]
