"""Offline tests of the four API clients + shared HTTP machinery."""
import pytest
import requests

from conftest import FakeResponse, FakeSession

from corpusslr import (CrossrefSource, OpenAlexSource, PubMedSource,
                       ScopusSource, SearchQuery)
from corpusslr.sources.base import BaseSource, SourceError

Q = SearchQuery(blocks=[["artificial intelligence", "machine learning"],
                        ["adoption"]],
                years=(2015, 2026), doc_types=["article", "review"],
                languages=["en"])


# ----------------------------------------------------------------- base
def test_base_retries_on_429_then_succeeds():
    s = FakeSession([FakeResponse(429, text="slow down"),
                     FakeResponse(200, payload={"ok": True})])
    src = BaseSource(session=s)
    r = src._get("https://example.org")
    assert r.json() == {"ok": True}
    assert len(s.calls) == 2


def test_base_raises_after_exhausting_retries_on_500():
    s = FakeSession([FakeResponse(500, text="boom")] * 3)
    with pytest.raises(SourceError) as ei:
        BaseSource(session=s)._get("https://example.org")
    assert "HTTP 500" in str(ei.value)


def test_base_raises_immediately_on_400():
    s = FakeSession([FakeResponse(400, text="bad query")])
    with pytest.raises(SourceError):
        BaseSource(session=s)._get("https://example.org")
    assert len(s.calls) == 1  # no retry on 4xx


def test_base_retries_network_errors_then_raises():
    calls = {"n": 0}

    def flaky(url, params, headers):
        calls["n"] += 1
        raise requests.ConnectionError("dns")

    with pytest.raises(SourceError) as ei:
        BaseSource(session=FakeSession(flaky))._get("https://example.org")
    assert calls["n"] == 3 and "network error" in str(ei.value)


def test_user_agent_contains_mailto():
    s = FakeSession([])
    BaseSource(mailto="me@uni.edu", session=s)
    assert "mailto:me@uni.edu" in s.headers["User-Agent"]


def test_base_search_is_abstract():
    with pytest.raises(NotImplementedError):
        BaseSource(session=FakeSession([])).search(Q)


# ------------------------------------------------------------- openalex
def _oa_work(i, doi=None, cursor_meta=None):
    return {
        "id": f"https://openalex.org/W{i}",
        "doi": doi or f"https://doi.org/10.5001/{i}",
        "ids": {"pmid": f"https://pubmed.ncbi.nlm.nih.gov/999{i}"},
        "display_name": f"Paper number {i}",
        "publication_year": 2024,
        "language": "en",
        "type": "article",
        "primary_location": {"source": {"display_name": "Journal X",
                                        "issn_l": "1234-5678"},
                             "landing_page_url": f"https://ex.org/{i}"},
        "biblio": {"volume": "10", "issue": "2", "first_page": "1",
                   "last_page": "9"},
        "authorships": [{"author": {"display_name": "Anna Nowak"}},
                        {"raw_author_name": "Jan Kowalski"}],
        "cited_by_count": 7,
        "open_access": {"is_oa": True},
        "abstract_inverted_index": {"An": [0], "abstract": [1], "here": [2]},
    }


def test_openalex_paging_parsing_and_event():
    page1 = FakeResponse(200, payload={
        "results": [_oa_work(1), _oa_work(2)],
        "meta": {"count": 3, "next_cursor": "C2"}})
    page2 = FakeResponse(200, payload={
        "results": [_oa_work(3)],
        "meta": {"count": 3, "next_cursor": None}})
    s = FakeSession([page1, page2])
    res = OpenAlexSource(mailto="me@uni.edu", session=s).search(Q, max_results=50)

    assert len(res.records) == 3
    r = res.records[0]
    assert r.title == "Paper number 1"
    assert r.abstract == "An abstract here"
    assert r.doi == "10.5001/1"                       # normalized
    assert r.openalex_id == "W1"                   # id stripped + upper
    assert r.pmid == "9991"
    assert r.authors == ["Anna Nowak", "Jan Kowalski"]
    assert r.journal == "Journal X" and r.issn == "1234-5678"
    assert r.pages == "1-9" and r.cited_by == 7 and r.open_access is True
    assert r.source == "OpenAlex"
    # provenance of the search itself
    assert res.event.database == "OpenAlex" and res.event.interface == "API"
    assert "title_and_abstract.search" in res.event.query
    assert "meta.count=3" in res.event.notes
    # mailto and cursor were sent
    assert s.calls[0]["params"]["mailto"] == "me@uni.edu"
    assert s.calls[0]["params"]["cursor"] == "*"
    assert s.calls[1]["params"]["cursor"] == "C2"


def test_openalex_respects_max_results_mid_page():
    page = FakeResponse(200, payload={
        "results": [_oa_work(i) for i in range(1, 6)],
        "meta": {"count": 5, "next_cursor": "C2"}})
    res = OpenAlexSource(session=FakeSession([page])).search(Q, max_results=2)
    assert len(res.records) == 2
    assert "max_results=2" in res.event.notes


def test_openalex_empty_result_set():
    page = FakeResponse(200, payload={"results": [],
                                      "meta": {"count": 0, "next_cursor": None}})
    res = OpenAlexSource(session=FakeSession([page])).search(Q)
    assert res.records == [] and res.event.records_retrieved == 0


def test_openalex_stops_when_cursor_never_advances():
    """A non-advancing cursor must terminate paging, not spin forever."""
    calls = {"n": 0}

    def always_same(url, params, headers):
        calls["n"] += 1
        if calls["n"] > 20:
            raise RuntimeError("infinite paging loop")
        return FakeResponse(200, payload={
            "results": [_oa_work(calls["n"])],
            "meta": {"count": 999, "next_cursor": "SAME"}})

    res = OpenAlexSource(session=FakeSession(always_same)).search(Q,
                                                                 max_results=100)
    assert calls["n"] == 2          # second page repeats the cursor -> stop
    assert len(res.records) == 2


def test_openalex_stops_on_empty_page_with_cursor():
    s = FakeSession([FakeResponse(200, payload={
        "results": [], "meta": {"count": 50, "next_cursor": "NEXT"}})])
    res = OpenAlexSource(session=s).search(Q, max_results=50)
    assert res.records == [] and len(s.calls) == 1


def test_crossref_stops_when_cursor_never_advances():
    calls = {"n": 0}

    def always_same(url, params, headers):
        calls["n"] += 1
        if calls["n"] > 20:
            raise RuntimeError("infinite paging loop")
        return FakeResponse(200, payload={"message": {
            "total-results": 999, "next-cursor": "*",
            "items": [_cr_item(calls["n"])]}})

    res = CrossrefSource(session=FakeSession(always_same)).search(
        Q, max_results=500)
    assert calls["n"] == 1          # cursor equals the initial one -> stop
    assert len(res.records) == 1


# --------------------------------------------------------------- scopus
def _scopus_entry(i):
    return {
        "dc:identifier": f"SCOPUS_ID:8500{i}",
        "eid": f"2-s2.0-8500{i}",
        "dc:title": f"Scopus paper {i}",
        "dc:description": "Truncated abstract...",
        "dc:creator": "Kowalski J.",
        "prism:coverDate": "2024-03-01",
        "prism:publicationName": "Journal of Business Research",
        "prism:doi": f"10.1016/j.jbusres.2024.{i}",
        "prism:issn": "01482963",
        "prism:volume": "170",
        "prism:issueIdentifier": "4",
        "prism:pageRange": "114-128",
        "subtypeDescription": "Article",
        "prism:url": f"https://api.elsevier.com/content/abstract/scopus_id/8500{i}",
        "openaccessFlag": True,
        "citedby-count": "12",
    }


def test_scopus_paging_headers_and_parsing():
    p1 = FakeResponse(200, payload={"search-results": {
        "opensearch:totalResults": "30",
        "entry": [_scopus_entry(i) for i in range(25)]}})
    p2 = FakeResponse(200, payload={"search-results": {
        "opensearch:totalResults": "30",
        "entry": [_scopus_entry(i) for i in range(25, 30)]}})
    s = FakeSession([p1, p2])
    # COMPLETE caps the page size at 25, and use_cursor=False selects the
    # offset paging mode whose start values are asserted below.
    res = ScopusSource(api_key="KEY", insttoken="TOK", view="COMPLETE",
                       use_cursor=False, session=s).search(Q)

    assert len(res.records) == 30
    r = res.records[0]
    assert r.scopus_id == "85000" and r.source_id == "85000"
    assert r.year == 2024 and r.doc_type == "article"
    assert r.cited_by == 12 and r.open_access is True
    assert s.calls[0]["headers"]["X-ELS-APIKey"] == "KEY"
    assert s.calls[0]["headers"]["X-ELS-Insttoken"] == "TOK"
    assert s.calls[0]["params"]["start"] == 0
    assert s.calls[1]["params"]["start"] == 25
    assert "totalResults=30" in res.event.notes
    assert res.event.filters == "view=COMPLETE; paging=offset"


def test_scopus_stops_on_error_entry():
    err = FakeResponse(200, payload={"search-results": {
        "opensearch:totalResults": "1",
        "entry": [{"error": "Result set was empty"}]}})
    res = ScopusSource(api_key="K", session=FakeSession([err])).search(Q)
    assert res.records == []


def test_scopus_stops_on_empty_entry_list():
    empty = FakeResponse(200, payload={"search-results": {
        "opensearch:totalResults": "5", "entry": []}})
    res = ScopusSource(api_key="K", session=FakeSession([empty])).search(Q)
    assert res.records == []


def test_scopus_missing_fields_do_not_crash():
    thin = FakeResponse(200, payload={"search-results": {
        "opensearch:totalResults": "1",
        "entry": [{"dc:title": "Bare entry"}]}})
    res = ScopusSource(api_key="K", session=FakeSession([thin])).search(Q)
    r = res.records[0]
    assert r.title == "Bare entry" and r.year is None
    assert r.cited_by is None and r.open_access is None and r.doi == ""


# --------------------------------------------------------------- pubmed
ESEARCH = """<?xml version="1.0"?><eSearchResult><Count>2</Count>
<WebEnv>WE1</WebEnv><QueryKey>1</QueryKey></eSearchResult>"""

EFETCH = """<?xml version="1.0"?>
<PubmedArticleSet>
 <PubmedArticle><MedlineCitation><PMID>111</PMID><Article>
  <Journal><ISSN>1474-5488</ISSN><Title>Lancet Oncol</Title>
   <JournalIssue><Volume>24</Volume><Issue>6</Issue>
    <PubDate><MedlineDate>2023 Jun-Jul</MedlineDate></PubDate>
   </JournalIssue></Journal>
  <ArticleTitle>First study</ArticleTitle>
  <Abstract><AbstractText Label="BACKGROUND">B.</AbstractText>
   <AbstractText>Plain.</AbstractText></Abstract>
  <AuthorList><Author><LastName>Smith</LastName><ForeName>John</ForeName></Author>
   <Author><CollectiveName>WHO Group</CollectiveName></Author></AuthorList>
  <Language>eng</Language>
  <PublicationTypeList><PublicationType>Journal Article</PublicationType>
  </PublicationTypeList></Article>
  <MeshHeadingList><MeshHeading><DescriptorName>Neoplasms</DescriptorName>
  </MeshHeading></MeshHeadingList></MedlineCitation>
  <PubmedData><ArticleIdList>
   <ArticleId IdType="doi">10.5001/second-place-doi</ArticleId>
  </ArticleIdList></PubmedData></PubmedArticle>
 <PubmedArticle><MedlineCitation><PMID>222</PMID><Article>
  <ArticleTitle>Second study</ArticleTitle>
  <PublicationTypeList><PublicationType>Review</PublicationType>
  </PublicationTypeList></Article></MedlineCitation></PubmedArticle>
</PubmedArticleSet>"""


def test_pubmed_history_flow_and_parsing():
    s = FakeSession([FakeResponse(200, text=ESEARCH),
                     FakeResponse(200, text=EFETCH)])
    res = PubMedSource(email="me@uni.edu", api_key="APIKEY",
                       session=s).search(Q, max_results=100)
    assert len(res.records) == 2
    a, b = res.records
    assert a.pmid == "111" and a.year == 2023          # MedlineDate fallback
    assert a.abstract == "BACKGROUND: B. Plain."
    assert a.authors == ["Smith, John", "WHO Group"]   # CollectiveName kept
    assert a.doi == "10.5001/second-place-doi"            # ArticleIdList fallback
    assert "Neoplasms" in a.keywords and a.doc_type == "article"
    assert b.pmid == "222" and b.doc_type == "review" and b.year is None
    # esearch then efetch, with credentials propagated
    assert s.calls[0]["params"]["usehistory"] == "y"
    assert s.calls[1]["params"]["WebEnv"] == "WE1"
    assert s.calls[1]["params"]["api_key"] == "APIKEY"
    assert s.calls[1]["params"]["email"] == "me@uni.edu"
    assert "Count=2" in res.event.notes


def test_pubmed_api_key_sets_faster_rate():
    fast = PubMedSource(email="a@b.c", api_key="K", session=FakeSession([]))
    slow = PubMedSource(email="a@b.c", session=FakeSession([]))
    assert fast.min_interval < slow.min_interval


def test_pubmed_zero_hits_skips_efetch():
    zero = """<eSearchResult><Count>0</Count><WebEnv>W</WebEnv>
    <QueryKey>1</QueryKey></eSearchResult>"""
    s = FakeSession([FakeResponse(200, text=zero)])
    res = PubMedSource(session=s).search(Q)
    assert res.records == [] and len(s.calls) == 1


def test_pubmed_caps_at_max_results():
    s = FakeSession([FakeResponse(200, text=ESEARCH),
                     FakeResponse(200, text=EFETCH)])
    res = PubMedSource(session=s).search(Q, max_results=1)
    assert len(res.records) == 1
    assert s.calls[1]["params"]["retmax"] == 1


# ------------------------------------------------------------- crossref
def _cr_item(i):
    return {
        "DOI": f"10.5001/cr{i}",
        "title": [f"Crossref item {i}"],
        "abstract": "<jats:p>Structured <jats:italic>abstract</jats:italic>.</jats:p>",
        "author": [{"family": "Nowak", "given": "Anna"}, {"given": "NoFamily"}],
        "issued": {"date-parts": [[2022, 5, 1]]},
        "container-title": ["Journal Y"],
        "ISSN": ["1111-2222"],
        "volume": "3", "issue": "1", "page": "10-20",
        "type": "journal-article", "language": "en",
        "URL": f"https://doi.org/10.5001/cr{i}",
        "is-referenced-by-count": 4,
    }


def test_crossref_paging_and_jats_stripping():
    p1 = FakeResponse(200, payload={"message": {
        "total-results": 3, "next-cursor": "CUR2",
        "items": [_cr_item(1), _cr_item(2)]}})
    p2 = FakeResponse(200, payload={"message": {
        "total-results": 3, "next-cursor": "",
        "items": [_cr_item(3)]}})
    s = FakeSession([p1, p2])
    res = CrossrefSource(mailto="me@uni.edu", session=s).search(Q, max_results=10)
    assert len(res.records) == 3
    r = res.records[0]
    assert r.abstract == "Structured abstract ."
    assert r.year == 2022 and r.journal == "Journal Y"
    assert r.authors == ["Nowak, Anna"]     # entries without family dropped
    assert r.cited_by == 4 and r.source == "Crossref"
    assert s.calls[0]["params"]["mailto"] == "me@uni.edu"
    assert s.calls[1]["params"]["cursor"] == "CUR2"
    assert "SUPPLEMENTARY source" in res.event.notes
    assert res.event.filters == "relevance search (non-boolean)"


def test_crossref_missing_dates_and_titles():
    p = FakeResponse(200, payload={"message": {
        "total-results": 1, "next-cursor": "",
        "items": [{"DOI": "10.5001/x", "issued": {"date-parts": [[]]}}]}})
    res = CrossrefSource(session=FakeSession([p])).search(Q)
    r = res.records[0]
    assert r.year is None and r.title == "" and r.doi == "10.5001/x"
