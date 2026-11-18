"""Cited references: parsing, merging, export and the snowballing helpers.

A reviewer asked how the very different reference representations of the major
databases are handled when records are merged. The answer is a rule, stated in
corpusslr/references.py, and these tests pin it: entries are the source's own
strings; two entries are one cited work only when they share a DOI, share an
OpenAlex identifier or are equal after case and whitespace folding; free-text
strings from different databases are never matched by similarity.
"""
import csv
import io

import pytest

from corpusslr import (Record, cited_but_absent, deduplicate, parse_csv_export,
                       reference_coverage, reference_key, to_scopus_csv)

SCOPUS_REF_A = "Nowak A., Kowalski B., Deep nets for review screening, J Inf Sci, 45, pp. 1-9, (2019)"
SCOPUS_REF_B = "Lee C., Park D., Query translation, Res Synth Methods, 11, 2, pp. 181-217, (2020)"


@pytest.mark.parametrize("a, b, same", [
    ("10.1000/ABC.1", "https://doi.org/10.1000/abc.1", True),
    ("Smith J., Title, J Name, 1, (2019). doi:10.1000/abc.1", "10.1000/abc.1", True),
    ("W123456789", "https://openalex.org/W123456789", True),
    ("Nowak A.,  Title  Here", "nowak a., title here", True),
    ("10.1000/abc.1", "10.1000/abc.2", False),
    ("W123456789", "W123456780", False),
    # free text for the same paper written two ways is deliberately NOT merged
    ("Nowak A., Deep nets, J Inf Sci, 45, 1-9 (2019)", "Nowak, A. Deep nets. J. Inf. Sci. 45:1-9", False),
])
def test_reference_key_equality(a, b, same):
    assert (reference_key(a) == reference_key(b)) is same


def test_merge_unions_references_without_duplicating():
    a = Record(uid="A", title="T", references=[SCOPUS_REF_A, "10.1000/x.1"])
    b = Record(uid="B", title="T", references=["https://doi.org/10.1000/X.1", SCOPUS_REF_B])
    a.merge_from(b)
    assert len(a.references) == 3
    assert a.references[:2] == [SCOPUS_REF_A, "10.1000/x.1"], "existing entries keep their wording"


def test_deduplication_carries_references_from_the_removed_copy():
    t = "Effect of metformin on cardiovascular outcomes in obese patients"
    one = Record(uid="A", title=t, year=2019, authors=["Nowak A."], journal="J", source="scopus",
                 doi="10.1000/m.1", references=[SCOPUS_REF_A])
    two = Record(uid="B", title=t, year=2019, authors=["Nowak A."], journal="J", source="openalex",
                 doi="10.1000/M.1", references=["W1111111111", SCOPUS_REF_B])
    res = deduplicate([one, two])
    assert len(res.records) == 1
    assert len(res.records[0].references) == 3


def _scopus_cell(refs):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Authors", "Title", "Year", "Source title", "DOI", "References", "Document Type",
                "Cited by", "EID", "Abstract", "Author Keywords", "Affiliations", "Link"])
    w.writerow(["Nowak A.", "A paper", "2020", "J Name", "10.1000/p.1", "; ".join(refs), "Article",
                "3", "2-s2.0-1", "abs", "kw", "Univ A, City", "http://x"])
    return out.getvalue()


def test_scopus_csv_references_are_split_one_entry_each():
    recs = parse_csv_export(_scopus_cell([SCOPUS_REF_A, SCOPUS_REF_B]), dialect="scopus")
    assert recs[0].references == [SCOPUS_REF_A, SCOPUS_REF_B]


def test_references_survive_the_scopus_round_trip(tmp_path):
    rec = Record(uid="A", title="A paper", year=2020, authors=["Nowak A."], journal="J",
                 doi="10.1000/p.1", references=[SCOPUS_REF_A, SCOPUS_REF_B])
    path = tmp_path / "out.csv"
    to_scopus_csv([rec], str(path))
    back = parse_csv_export(path.read_text(encoding="utf-8-sig"), dialect="scopus")
    assert back[0].references == rec.references


def test_a_record_without_references_exports_an_empty_cell_not_invented_text(tmp_path):
    path = tmp_path / "out.csv"
    to_scopus_csv([Record(uid="A", title="A paper", year=2020)], str(path))
    with open(path, encoding="utf-8-sig", newline="") as fh:
        assert next(csv.DictReader(fh))["References"] == ""


def test_cited_but_absent_lists_only_dois_missing_from_the_corpus():
    in_corpus = Record(uid="A", title="In corpus", doi="10.1000/in.1",
                       references=["10.1000/out.9", "10.1000/out.8"])
    other = Record(uid="B", title="Other", doi="10.1000/b.1",
                   references=["https://doi.org/10.1000/OUT.9", "10.1000/in.1", SCOPUS_REF_A])
    got = cited_but_absent([in_corpus, other])
    assert got == [("10.1000/out.9", 2), ("10.1000/out.8", 1)]
    assert cited_but_absent([in_corpus, other], min_citing=2) == [("10.1000/out.9", 2)]


def test_reference_coverage_counts_what_snowballing_can_use():
    recs = [Record(uid="A", title="a", references=["10.1000/a.1", SCOPUS_REF_A]),
            Record(uid="B", title="b")]
    assert reference_coverage(recs) == {"records": 2, "records_with_references": 1,
                                        "reference_entries": 2, "entries_with_doi": 1}


def test_openalex_and_crossref_mappers_fill_the_field():
    from corpusslr.sources.crossref import _parse_item as cr
    from corpusslr.sources.openalex import _parse_work as oa
    c = cr({"DOI": "10.1000/z.1", "title": ["Z"], "reference": [
        {"DOI": "10.1000/r.1"}, {"unstructured": "Doe J. 2001 A book"}, {"key": "empty"}]})
    assert c.references == ["10.1000/r.1", "Doe J. 2001 A book"]
    o = oa({"id": "https://openalex.org/W1", "display_name": "Z",
            "referenced_works": ["https://openalex.org/W22", "https://openalex.org/W33"]})
    assert o.references == ["W22", "W33"]
