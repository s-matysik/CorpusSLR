from corpusslr import Record, SearchQuery, normalize_doi, normalize_title


def test_normalize_doi():
    assert normalize_doi("https://doi.org/10.1016/J.SOFTX.2025.101") == \
        "10.1016/j.softx.2025.101"
    assert normalize_doi("doi: 10.1000/ABC.") == "10.1000/abc"
    assert normalize_doi(None) == ""


def test_normalize_title():
    a = normalize_title("The  Impact of <i>AI</i> on SMEs: a review!")
    b = normalize_title("the impact of ai on smes a review")
    assert a == b


def test_record_ids_and_merge():
    r1 = Record(title="T", doi="10.5001/x", abstract="short", authors=["A, B"])
    r2 = Record(title="T", pmid="PMID: 123456", abstract="a much longer abstract",
                journal="J", year=2020, keywords=["k1"])
    assert r2.pmid == "123456"
    r1.merge_from(r2)
    assert r1.abstract.startswith("a much")
    assert r1.journal == "J" and r1.year == 2020 and r1.pmid == "123456"
    assert "k1" in r1.keywords


def test_query_scopus_pubmed():
    q = SearchQuery(blocks=[["artificial intelligence", "machine learning"],
                            ["adoption"]],
                    years=(2015, 2026), doc_types=["article", "review"],
                    languages=["en"])
    s = q.to_scopus()
    assert 'TITLE-ABS-KEY("artificial intelligence" OR "machine learning")' in s
    assert "PUBYEAR > 2014" in s and "PUBYEAR < 2027" in s
    assert "DOCTYPE(ar)" in s and "DOCTYPE(re)" in s
    assert "LANGUAGE(english)" in s
    p = q.to_pubmed()
    assert '"artificial intelligence"[Title/Abstract]' in p
    assert "2015:2026[dp]" in p and "english[la]" in p
    assert '"journal article"[pt]' in p


def test_query_openalex_crossref():
    q = SearchQuery(blocks=[["ai, robots"], ["health"]], years=(2020, 2026),
                    doc_types=["article"], languages=["en"])
    f = q.to_openalex_filters()
    assert "title_and_abstract.search" in f
    assert "," not in f["title_and_abstract.search"]  # commas stripped
    assert f["from_publication_date"] == "2020-01-01"
    assert f["type"] == "article" and f["language"] == "en"
    cp = q.to_crossref_params()
    assert "query.bibliographic" in cp
    assert "from-pub-date:2020-01-01" in cp["filter"]
    assert any("Crossref" in w for w in q.warnings)


def test_repeated_compilation_does_not_duplicate_warnings():
    """Warnings reach the PRISMA-S appendix verbatim, so they must not pile up
    when a query is compiled more than once (compile_all + per-source client)."""
    q = SearchQuery(blocks=[["ai"]], doc_types=["dataset"], languages=["pl"])
    for _ in range(3):
        q.to_crossref_params()
        q.to_scopus()
        q.to_pubmed()
        q.to_openalex_filters()
        q.compile_all()
    assert q.warnings and len(q.warnings) == len(set(q.warnings))


# --------------------------------------------------------------------------
# One person, one surname, whichever way the export wrote the name.
#
# surname("Nowak A.") returned "a": the last token was read as the family name,
# so the Family-Initials form that Scopus, Web of Science and PubMed use never
# matched "Nowak, A" from another export, and the first-author comparison in
# deduplication rejected two copies of the same record. The parsers normalise
# names before they reach a Record, which hid it on every route except a Record
# built by hand, from a data frame or by a custom client.
# --------------------------------------------------------------------------

import pytest as _pytest_authors


@_pytest_authors.mark.parametrize("written", [
    "Nowak, A", "Nowak, A.", "Nowak A", "Nowak A.", "Nowak AB", "Nowak A. B.",
    "A. Nowak", "Andrzej Nowak", "Nowak, Andrzej", "NOWAK A",
])
def test_every_common_author_form_yields_the_same_surname(written):
    from corpusslr.record import surname
    assert surname(written) == "nowak", written


@_pytest_authors.mark.parametrize("a, b", [
    (["Nowak A.", "Kowalski B."], ["Nowak, A", "Kowalski, B"]),
    (["Nowak A", "Kowalski B"], ["Andrzej Nowak", "Bogdan Kowalski"]),
    (["Nowak, Andrzej"], ["Nowak AJ"]),
])
def test_deduplication_merges_a_pair_whose_authors_are_written_differently(a, b):
    from corpusslr import Record, deduplicate
    title = "Effect of metformin on cardiovascular outcomes in obese patients"
    one = Record(uid="A", title=title, year=2019, authors=a, journal="Diabetologia",
                 source="pubmed")
    two = Record(uid="B", title=title.lower(), year=2019, authors=b,
                 journal="Diabetologia", source="scopus")
    assert deduplicate([one, two]).report.removed == 1


def test_different_first_authors_are_still_not_merged():
    from corpusslr import Record, deduplicate
    title = "Effect of metformin on cardiovascular outcomes in obese patients"
    one = Record(uid="A", title=title, year=2019, authors=["Nowak A."],
                 journal="Diabetologia", source="pubmed")
    two = Record(uid="B", title=title, year=2019, authors=["Kowalski B."],
                 journal="Diabetologia", source="scopus")
    assert deduplicate([one, two]).report.removed == 0
