"""Offline tests for the Semantic Scholar (S2AG) client."""
import pytest

from conftest import FakeResponse, FakeSession

from corpusslr import SearchQuery
from corpusslr.sources.base import SourceError, format_author_name
from corpusslr.sources.semanticscholar import (FIELDS, SemanticScholarSource,
                                               parse_s2_paper)


def _paper(**kw):
    base = {
        "paperId": "abc123",
        "externalIds": {"DOI": "10.1000/XYZ", "PubMed": "12345678",
                        "CorpusId": 99, "ArXiv": "2401.00001"},
        "title": "Wpływ AI na małe przedsiębiorstwa",
        "abstract": "Badanie wpływu.",
        "year": 2023,
        "venue": "Journal of Testing",
        "authors": [{"authorId": "1", "name": "Jan Kowalski"},
                    {"authorId": "2", "name": "Anna Nowak-Zielińska"}],
        "publicationTypes": ["JournalArticle", "Review"],
        "openAccessPdf": {"url": "https://example.org/p.pdf"},
        "citationCount": 42,
        "publicationDate": "2023-05-01",
    }
    base.update(kw)
    return base


def _query():
    return SearchQuery(blocks=[["artificial intelligence", "machine learning"],
                               ["adoption"]],
                       years=(2015, 2026), doc_types=["article"])


# ----------------------------------------------------------------- parsing
def test_parse_maps_all_fields():
    r = parse_s2_paper(_paper())
    assert r.doi == "10.1000/xyz"          # normalized by Record
    assert r.pmid == "12345678"
    assert r.source == "Semantic Scholar"
    assert r.source_id == "abc123"
    assert r.journal == "Journal of Testing"
    assert r.year == 2023
    assert r.cited_by == 42
    assert r.open_access is True
    assert r.url == "https://example.org/p.pdf"
    assert r.authors == ["Kowalski, Jan", "Nowak-Zielińska, Anna"]
    assert r.title.startswith("Wpływ")     # non-ASCII survives untouched


def test_doc_type_precedence_review_over_article():
    assert parse_s2_paper(_paper()).doc_type == "review"
    assert parse_s2_paper(
        _paper(publicationTypes=["JournalArticle"])).doc_type == "article"
    assert parse_s2_paper(
        _paper(publicationTypes=["Conference"])).doc_type == "conference"
    assert parse_s2_paper(
        _paper(publicationTypes=["BookSection"])).doc_type == "chapter"
    assert parse_s2_paper(
        _paper(publicationTypes=["Book"])).doc_type == "book"
    assert parse_s2_paper(
        _paper(publicationTypes=["Dataset"])).doc_type == "report"
    assert parse_s2_paper(
        _paper(publicationTypes=["SomethingNew"])).doc_type == ""


def test_arxiv_only_record_is_preprint():
    r = parse_s2_paper(_paper(publicationTypes=None,
                              externalIds={"ArXiv": "2401.00001"}))
    assert r.doc_type == "preprint"
    assert r.doi == ""


def test_parse_empty_and_null_fields():
    r = parse_s2_paper({})
    assert r.title == "" and r.abstract == "" and r.authors == []
    assert r.year is None and r.doi == "" and r.pmid == ""
    assert r.open_access is None          # key absent -> unknown, not False
    r2 = parse_s2_paper({"paperId": "p", "title": None, "abstract": None,
                         "authors": None, "externalIds": None,
                         "venue": None, "publicationTypes": None,
                         "openAccessPdf": None, "year": None})
    assert r2.open_access is False        # key present but null -> not OA
    assert r2.url == "https://www.semanticscholar.org/paper/p"


def test_year_falls_back_to_publication_date_and_survives_garbage():
    assert parse_s2_paper(_paper(year=None)).year == 2023
    assert parse_s2_paper(_paper(year=None, publicationDate="")).year is None
    assert parse_s2_paper(_paper(year="not-a-year")).year is None
    assert parse_s2_paper(_paper(year="2019")).year == 2019


def test_venue_falls_back_to_publication_venue():
    r = parse_s2_paper(_paper(venue="",
                              publicationVenue={"name": "Fallback Venue"}))
    assert r.journal == "Fallback Venue"
    assert parse_s2_paper(_paper(venue="", publicationVenue=None)).journal == ""


@pytest.mark.parametrize("raw,expected", [
    ("Ludwig van Beethoven", "van Beethoven, Ludwig"),
    ("Jan van der Berg", "van der Berg, Jan"),
    ("Charles de la Cruz", "de la Cruz, Charles"),
    ("Martin Luther King Jr.", "King Jr., Martin Luther"),
    ("John Smith III", "Smith III, John"),
    ("Cher", "Cher"),
    ("Smith, John", "Smith, John"),
    ("  John   Smith  ", "Smith, John"),
    ("", ""),
    (None, ""),
    ("van Gogh", "Gogh, van"),   # single given name is never swallowed
])
def test_author_name_inversion_edge_cases(raw, expected):
    assert format_author_name(raw) == expected


# ------------------------------------------------------------------ search
def test_search_paging_and_headers():
    pages = [
        FakeResponse(payload={"total": 250, "offset": 0, "next": 100,
                              "data": [_paper(paperId="p%d" % i)
                                       for i in range(100)]}),
        FakeResponse(payload={"total": 250, "offset": 100,
                              "data": [_paper(paperId="q%d" % i)
                                       for i in range(20)]}),
    ]
    sess = FakeSession(pages)
    src = SemanticScholarSource(api_key="KEY", session=sess)
    res = src.search(_query(), max_results=500)
    assert len(res.records) == 120
    assert len(sess.calls) == 2
    assert sess.calls[0]["headers"]["x-api-key"] == "KEY"
    assert sess.calls[0]["params"]["offset"] == 0
    assert sess.calls[1]["params"]["offset"] == 100
    assert sess.calls[0]["params"]["fields"] == FIELDS
    assert src.min_interval < 1.0  # authenticated pool is faster


def test_no_api_key_means_no_header_and_slow_interval():
    sess = FakeSession(FakeResponse(payload={"total": 0, "data": []}))
    src = SemanticScholarSource(session=sess)
    src.search(_query())
    assert "x-api-key" not in sess.calls[0]["headers"]
    assert src.min_interval >= 1.0


def test_search_stops_on_non_advancing_next():
    resp = FakeResponse(payload={"total": 9, "next": 0,
                                 "data": [_paper()] * 5})
    src = SemanticScholarSource(session=FakeSession(resp))
    res = src.search(_query(), max_results=1000)
    assert len(res.records) == 5  # would loop forever without the guard


def test_search_stops_on_unparseable_next():
    resp = FakeResponse(payload={"total": 9, "next": "not-a-number",
                                 "data": [_paper()] * 3})
    res = SemanticScholarSource(session=FakeSession(resp)).search(
        _query(), max_results=1000)
    assert len(res.records) == 3


def test_search_respects_max_results_and_offset_cap():
    sess = FakeSession(lambda url, params, headers: FakeResponse(
        payload={"total": 100000, "next": params["offset"] + 100,
                 "data": [_paper()] * 100}))
    src = SemanticScholarSource(session=sess)
    assert len(src.search(_query(), max_results=17).records) == 17
    sess2 = FakeSession(lambda url, params, headers: FakeResponse(
        payload={"total": 100000, "next": params["offset"] + 100,
                 "data": [_paper()] * 100}))
    src2 = SemanticScholarSource(session=sess2)
    res = src2.search(_query(), max_results=100000)
    assert len(res.records) == SemanticScholarSource.MAX_OFFSET


def test_search_empty_result():
    src = SemanticScholarSource(
        session=FakeSession(FakeResponse(payload={"total": 0, "data": []})))
    res = src.search(_query())
    assert res.records == []
    assert "total=0" in res.event.notes


def test_event_records_supplementary_status_and_filters():
    q = _query()
    src = SemanticScholarSource(
        session=FakeSession(FakeResponse(payload={"total": 3, "data": []})))
    ev = src.search(q).event
    assert ev.database == "Semantic Scholar"
    assert ev.platform == "Allen Institute for AI"
    assert ev.interface == "API"
    assert "SUPPLEMENTARY" in ev.notes
    assert "not reproducible" in ev.notes.lower()
    assert "year=2015-2026" in ev.filters
    assert "publicationTypes=JournalArticle" in ev.filters
    assert ev.query == "artificial intelligence machine learning adoption"
    assert any("Semantic Scholar" in w and "boolean" in w for w in q.warnings)


def test_http_error_raises_source_error():
    src = SemanticScholarSource(
        session=FakeSession(FakeResponse(status_code=400, text="bad request")))
    with pytest.raises(SourceError):
        src.search(_query())


def test_malformed_json_raises_source_error():
    src = SemanticScholarSource(
        session=FakeSession(FakeResponse(status_code=200, text="<html>")))
    with pytest.raises(SourceError):
        src.search(_query())


def test_non_dict_payload_raises_source_error():
    src = SemanticScholarSource(
        session=FakeSession(FakeResponse(payload=["not", "a", "dict"])))
    with pytest.raises(SourceError):
        src.search(_query())


def test_rate_limit_is_retried_then_succeeds():
    responses = [FakeResponse(status_code=429, text="slow down"),
                 FakeResponse(payload={"total": 1, "data": [_paper()]})]
    src = SemanticScholarSource(session=FakeSession(responses))
    assert len(src.search(_query()).records) == 1


# ------------------------------------------------------------------- query
def test_query_compiler_flattens_and_warns():
    q = SearchQuery(blocks=[["ai, robots", "b", "c", "d"], ["health"]],
                    years=(2020, 2024), doc_types=["article", "thesis"],
                    languages=["en"], title_only=True)
    p = q.to_semanticscholar()
    assert "," not in p["query"]           # _clean strips commas
    assert p["query"].count("d") == 0      # only first 3 terms per block
    assert p["year"] == "2020-2024"
    assert p["publicationTypes"] == "JournalArticle"
    joined = " ".join(q.warnings)
    assert "boolean" in joined
    assert "thesis" in joined              # unsupported doc_type reported
    assert "title-only" in joined
    assert "language" in joined


def test_query_compiler_minimal():
    q = SearchQuery(blocks=[["x"]])
    p = q.to_semanticscholar()
    assert p == {"query": "x"}


def test_compile_all_includes_new_backends():
    out = SearchQuery(blocks=[["a"], ["b"]]).compile_all()
    assert {"scopus", "openalex", "pubmed", "crossref",
            "semanticscholar", "arxiv", "warnings"} <= set(out)
    assert out["semanticscholar"]["query"] == "a b"
    assert out["arxiv"] == '(all:"a") AND (all:"b")'
