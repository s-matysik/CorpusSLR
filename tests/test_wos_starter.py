"""Offline tests for the Web of Science Starter API client and to_wos().

No test touches the network: every HTTP interaction goes through the
``FakeSession``/``FakeResponse`` doubles from ``conftest``.
"""
import pytest

from conftest import FakeResponse, FakeSession

from corpusslr import SearchQuery
from corpusslr.sources.base import SourceError
from corpusslr.sources.wos import (MAX_LIMIT, WosStarterSource, parse_wos_hit,
                                   wos_doc_type)


def _hit(**kw):
    base = {
        "uid": "WOS:000123456700001",
        "title": "Wpływ sztucznej inteligencji na małe przedsiębiorstwa",
        "types": ["Article"],
        "sourceTypes": ["Journal"],
        "source": {
            "sourceTitle": "Journal of Testing",
            "publishYear": 2023,
            "publishMonth": "MAY",
            "volume": "12",
            "issue": "3",
            "pages": {"range": "101-118", "begin": "101", "end": "118",
                      "count": 18},
        },
        "names": {"authors": [
            {"displayName": "Kowalski, Jan", "wosStandard": "Kowalski, J"},
            {"displayName": "Nowak-Zielińska, Anna",
             "wosStandard": "Nowak-Zielinska, A"},
        ]},
        "identifiers": {"doi": "10.1000/XYZ", "issn": "1234-5678",
                        "eissn": "8765-4321", "pmid": "MEDLINE:12345678"},
        "links": {"record": "https://www.webofscience.com/wos/woscc/"
                            "full-record/WOS:000123456700001"},
        "citations": [{"db": "WOS", "count": 42}, {"db": "BCI", "count": 7}],
        "keywords": {"authorKeywords": ["artificial intelligence", "SME"]},
    }
    base.update(kw)
    return base


def _page(hits, total=1, page=1, limit=MAX_LIMIT):
    return FakeResponse(payload={
        "metadata": {"total": total, "page": page, "limit": limit},
        "hits": hits,
    })


def _query():
    return SearchQuery(blocks=[["artificial intelligence", "machine learning"],
                               ["adoption"]],
                       years=(2015, 2026), doc_types=["article"],
                       languages=["en"])


def _source(responses, **kw):
    kw.setdefault("min_interval", 0.0)
    return WosStarterSource(api_key="KEY", session=FakeSession(responses), **kw)


# ------------------------------------------------------------------ parsing
def test_parse_maps_all_fields():
    r = parse_wos_hit(_hit())
    assert r.source_id == "WOS:000123456700001"
    assert r.source == "Web of Science Core Collection"
    assert r.title.startswith("Wpływ")          # non-ASCII survives untouched
    assert r.doi == "10.1000/xyz"               # normalized by Record
    assert r.pmid == "12345678"
    assert r.issn == "1234-5678"
    assert r.journal == "Journal of Testing"
    assert r.year == 2023
    assert r.volume == "12" and r.issue == "3" and r.pages == "101-118"
    assert r.doc_type == "article"
    assert r.authors == ["Kowalski, Jan", "Nowak-Zielińska, Anna"]
    assert r.keywords == ["artificial intelligence", "SME"]
    assert r.cited_by == 42                     # the WOS count, not BCI's
    assert r.url.endswith("WOS:000123456700001")


def test_parse_minimal_hit_and_empty_hit():
    r = parse_wos_hit({"uid": "WOS:1", "title": "T"})
    assert r.source_id == "WOS:1" and r.title == "T"
    assert r.authors == [] and r.keywords == [] and r.year is None
    assert r.doi == "" and r.pmid == "" and r.doc_type == ""
    assert r.cited_by is None
    # A deep link is still constructed from the UID alone.
    assert r.url == ("https://www.webofscience.com/wos/woscc/full-record/WOS:1")
    empty = parse_wos_hit({})
    assert empty.title == "" and empty.source_id == "" and empty.url == ""
    assert parse_wos_hit(None).title == ""


def test_parse_survives_wrong_container_types():
    """A field the API documents as an object arriving as something else must
    not raise: a single malformed hit would otherwise abort a whole search."""
    r = parse_wos_hit({"uid": "WOS:2", "source": "Journal of Testing",
                       "identifiers": ["10.1000/x"], "names": "Kowalski",
                       "keywords": ["not", "a", "dict"],
                       "citations": ["junk", {"count": "x"}],
                       "links": "https://example.org"})
    assert r.journal == "" and r.doi == "" and r.authors == []
    assert r.keywords == [] and r.cited_by is None
    assert r.url.endswith("WOS:2")
    # Empty/None containers take the same path.
    r2 = parse_wos_hit({"uid": "WOS:3", "source": None, "identifiers": [],
                        "names": None, "keywords": None, "citations": None})
    assert r2.doi == "" and r2.authors == [] and r2.journal == ""


def test_parse_starter_hit_has_no_abstract():
    """The Starter plan omits abstracts entirely - the mapping must not invent
    one, because an empty abstract is what triggers recover_abstracts()."""
    assert parse_wos_hit(_hit()).abstract == ""


def test_abstract_is_used_when_present():
    """Forward compatibility with the Expanded API, which does return one."""
    assert parse_wos_hit(_hit(abstract="Badanie.")).abstract == "Badanie."


@pytest.mark.parametrize("raw,expected", [
    ("MEDLINE:12345678", "12345678"),
    ("12345678", "12345678"),
    ("pmid:12345678", "12345678"),
    ("", ""),
    (None, ""),
])
def test_pmid_prefix_is_stripped(raw, expected):
    """PMID is the second step of the dedup cascade: a namespaced value would
    silently break matching against PubMed."""
    r = parse_wos_hit(_hit(identifiers={"pmid": raw}))
    assert r.pmid == expected


def test_eissn_fallback_and_page_variants():
    assert parse_wos_hit(
        _hit(identifiers={"eissn": "8765-4321"})).issn == "8765-4321"
    src = dict(_hit()["source"])
    src["pages"] = {"begin": "101", "end": "118"}
    assert parse_wos_hit(_hit(source=src)).pages == "101-118"
    src["pages"] = {"begin": "e12345"}
    assert parse_wos_hit(_hit(source=src)).pages == "e12345"
    src["pages"] = "7-9"
    assert parse_wos_hit(_hit(source=src)).pages == "7-9"
    src["pages"] = {}
    assert parse_wos_hit(_hit(source=src)).pages == ""


def test_year_and_citation_edge_cases():
    src = dict(_hit()["source"])
    src["publishYear"] = "2019"
    assert parse_wos_hit(_hit(source=src)).year == 2019
    src["publishYear"] = "in press"
    assert parse_wos_hit(_hit(source=src)).year is None
    src["publishYear"] = None
    assert parse_wos_hit(_hit(source=src)).year is None
    # No WOS entry: the largest reported count is used as a fallback.
    r = parse_wos_hit(_hit(citations=[{"db": "BCI", "count": 3},
                                      {"db": "CCC", "count": 9}]))
    assert r.cited_by == 9
    assert parse_wos_hit(_hit(citations=[])).cited_by is None


def test_wosstandard_used_when_displayname_missing():
    r = parse_wos_hit(_hit(names={"authors": [
        {"wosStandard": "Kowalski, J"}, {"displayName": ""}, {}, "junk"]}))
    assert r.authors == ["Kowalski, J"]


# ------------------------------------------------------------- doc types
@pytest.mark.parametrize("types,expected", [
    (["Article"], "article"),
    (["Review"], "review"),
    (["Article", "Review"], "review"),            # the specific label wins
    (["Article", "Proceedings Paper"], "conference"),
    (["Proceedings Paper"], "conference"),
    (["Meeting Abstract"], "conference"),
    (["Book Chapter"], "chapter"),
    (["Book"], "book"),
    (["Editorial Material"], "editorial"),
    (["Correction"], "editorial"),
    (["Book Review"], "editorial"),               # NOT a review article
    (["Letter"], "letter"),
    (["Data Paper"], "article"),
    (["Review Article"], "review"),
    (["ARTICLE"], "article"),                     # case-insensitive
    (["Proceedings-Paper"], "conference"),        # hyphen tolerated
    (["Retracted Publication"], ""),              # unknown: never guessed
    ([], ""),
    (None, ""),
])
def test_doc_type_mapping(types, expected):
    assert wos_doc_type(types) == expected
    assert parse_wos_hit(_hit(types=types, sourceTypes=[])).doc_type == expected


@pytest.mark.parametrize("source_types,expected", [
    (["Conference Proceeding"], "conference"),
    (["Book in series"], "chapter"),
    (["Book"], "book"),
    (["Journal"], "article"),
    (["Something Else"], ""),
])
def test_source_type_fallback(source_types, expected):
    assert wos_doc_type(None, source_types) == expected
    # An explicit, recognized type always wins over the carrier.
    assert wos_doc_type(["Review"], source_types) == "review"


# ----------------------------------------------------------------- search
def test_search_single_page_sends_apikey_and_params():
    src = _source([_page([_hit()], total=1)])
    res = src.search(_query(), max_results=10)
    assert len(res.records) == 1
    call = src.session.calls[0]
    assert call["url"].endswith("/wos-starter/v1/documents")
    assert call["headers"]["X-ApiKey"] == "KEY"
    assert "Authorization" not in call["headers"]
    assert call["params"]["db"] == "WOS"
    assert call["params"]["page"] == 1
    assert call["params"]["limit"] == 10
    assert "TS=(" in call["params"]["q"]
    assert res.event.database == "Web of Science Core Collection"
    assert res.event.platform == "Clarivate"
    assert res.event.interface == "API"
    assert res.event.query == _query().to_wos()


def test_limit_is_capped_at_starter_maximum():
    src = _source([_page([_hit(uid="WOS:%d" % i) for i in range(MAX_LIMIT)],
                         total=MAX_LIMIT)])
    src.search(_query(), max_results=5000)
    assert src.session.calls[0]["params"]["limit"] == MAX_LIMIT == 50


def test_search_pages_through_multiple_pages():
    def hits(start, n):
        return [_hit(uid="WOS:%06d" % i) for i in range(start, start + n)]
    src = _source([_page(hits(0, MAX_LIMIT), total=120, page=1),
                   _page(hits(50, MAX_LIMIT), total=120, page=2),
                   _page(hits(100, 20), total=120, page=3)])
    res = src.search(_query(), max_results=1000)
    assert len(res.records) == 120
    assert [c["params"]["page"] for c in src.session.calls] == [1, 2, 3]
    assert "total=120" in res.event.notes
    assert len({r.source_id for r in res.records}) == 120


def test_paging_stops_at_max_results_mid_page():
    src = _source([_page([_hit(uid="WOS:%d" % i) for i in range(MAX_LIMIT)],
                         total=500)])
    res = src.search(_query(), max_results=30)
    assert len(res.records) == 30
    assert len(src.session.calls) == 1
    assert "only 30 were" in res.event.notes    # under-retrieval is flagged


def test_paging_stops_on_empty_page():
    src = _source([_page([_hit(uid="WOS:%d" % i) for i in range(MAX_LIMIT)],
                         total=999),
                   _page([], total=999, page=2)])
    res = src.search(_query(), max_results=1000)
    assert len(res.records) == MAX_LIMIT
    assert len(src.session.calls) == 2


def test_paging_stops_when_the_server_repeats_a_page():
    """A server ignoring ``page`` must not spin the loop; the repeated page
    ends retrieval and the anomaly is reported in the event."""
    page = [_hit(uid="WOS:%d" % i) for i in range(MAX_LIMIT)]
    src = _source(lambda url, params, headers: _page(list(page), total=999))
    res = src.search(_query(), max_results=1000)
    assert len(res.records) == MAX_LIMIT
    assert len(src.session.calls) == 2
    assert "repeated the previous page" in res.event.notes


def test_same_uid_is_not_returned_twice_across_pages():
    """Overlapping pages (a shifting relevance order) must not inflate the
    identified count, which is reported to PRISMA."""
    first = [_hit(uid="WOS:%d" % i) for i in range(MAX_LIMIT)]
    second = [_hit(uid="WOS:%d" % i) for i in range(40, 40 + MAX_LIMIT)]
    src = _source([_page(first, total=200), _page(second, total=200),
                   _page([], total=200)])
    res = src.search(_query(), max_results=1000)
    uids = [r.source_id for r in res.records]
    assert len(uids) == len(set(uids)) == 90


def test_same_titled_records_are_kept_apart():
    """The Core Collection indexes corrigenda under the parent article's
    title; collapsing them here would understate the identified count."""
    src = _source([_page([_hit(uid="WOS:A", identifiers={}),
                          _hit(uid="WOS:B", identifiers={},
                               types=["Correction"])], total=2)])
    res = src.search(_query(), max_results=100)
    assert len(res.records) == 2
    assert res.records[0].title == res.records[1].title
    assert [r.doc_type for r in res.records] == ["article", "editorial"]


def test_records_without_identifiers_are_all_retained():
    src = _source([_page([_hit(uid="", identifiers={}) for _ in range(3)],
                         total=3)])
    assert len(src.search(_query(), max_results=100).records) == 3


def test_page_cap_bounds_a_runaway_result_set():
    src = _source(lambda url, params, headers: _page(
        [_hit(uid="WOS:%s-%d" % (params["page"], i)) for i in range(MAX_LIMIT)],
        total=10 ** 6))
    src.MAX_PAGES = 3
    res = src.search(_query(), max_results=10 ** 6)
    assert len(src.session.calls) == 3
    assert len(res.records) == 3 * MAX_LIMIT
    assert "pages_read=3" in res.event.notes


def test_total_bounds_the_loop_when_server_keeps_returning_full_pages():
    src = _source(lambda url, params, headers: _page(
        [_hit(uid="WOS:%s-%d" % (params["page"], i)) for i in range(MAX_LIMIT)],
        total=100))
    res = src.search(_query(), max_results=1000)
    assert len(res.records) == 100
    assert len(src.session.calls) == 2


def test_empty_result_set():
    src = _source([_page([], total=0)])
    res = src.search(_query(), max_results=100)
    assert res.records == []
    assert "total=0" in res.event.notes


def test_missing_metadata_block_is_tolerated():
    src = _source([FakeResponse(payload={"hits": [_hit()]})])
    res = src.search(_query(), max_results=10)
    assert len(res.records) == 1
    assert "total=None" in res.event.notes


def test_non_integer_total_is_tolerated():
    src = _source([FakeResponse(payload={"metadata": {"total": "many"},
                                         "hits": [_hit()]})])
    assert len(src.search(_query(), max_results=10).records) == 1


def test_db_and_sort_field_are_forwarded():
    src = _source([_page([_hit()], total=1)], db="WOK", sort_field="PY+D")
    res = src.search(_query(), max_results=10)
    assert src.session.calls[0]["params"]["db"] == "WOK"
    assert src.session.calls[0]["params"]["sortField"] == "PY+D"
    assert "db=WOK" in res.event.filters
    assert "sortField=PY+D" in res.event.notes


def test_default_sort_field_is_not_sent():
    src = _source([_page([_hit()], total=1)])
    res = src.search(_query(), max_results=10)
    assert "sortField" not in src.session.calls[0]["params"]
    assert "API default: relevance" in res.event.notes


# ------------------------------------------------------------------ notes
def test_event_notes_document_the_missing_abstracts():
    src = _source([_page([_hit()], total=1)])
    notes = src.search(_query(), max_results=10).event.notes
    assert "NO abstracts" in notes
    assert "recover_abstracts()" in notes
    assert "Expanded API" in notes
    assert "Starter API maximum 50" in notes


def test_event_notes_record_observed_rate_limit_headers():
    resp = _page([_hit()], total=1)
    resp.headers = {"X-RateLimit-Remaining-Day": "37",
                    "X-RateLimit-Limit-Second": "5",
                    "Content-Type": "application/json"}
    src = _source([resp])
    res = src.search(_query(), max_results=10)
    assert "X-RateLimit-Remaining-Day=37" in res.event.notes
    assert "Content-Type" not in res.event.notes
    assert src.last_rate_limit["X-RateLimit-Limit-Second"] == "5"


def test_event_notes_when_no_rate_limit_headers_present():
    src = _source([_page([_hit()], total=1)])
    assert "no X-RateLimit-* headers seen" in \
        src.search(_query(), max_results=10).event.notes


# ----------------------------------------------------------------- errors
def test_bad_api_key_gives_actionable_401_message():
    src = _source([FakeResponse(status_code=401, text="Invalid API key")])
    with pytest.raises(SourceError) as exc:
        src.search(_query(), max_results=10)
    msg = str(exc.value)
    assert "HTTP 401" in msg and "X-ApiKey" in msg
    assert "developer.clarivate.com" in msg


def test_403_names_the_unsubscribed_database():
    src = _source([FakeResponse(status_code=403, text="Not entitled")],
                  db="DIIDW")
    with pytest.raises(SourceError) as exc:
        src.search(_query(), max_results=10)
    msg = str(exc.value)
    assert "HTTP 403" in msg and "db='DIIDW'" in msg
    assert "subscription" in msg


def test_429_reports_the_quota_headers_after_retries():
    resp = FakeResponse(status_code=429, text="Too many requests")
    resp.headers = {"X-RateLimit-Remaining-Day": "0", "Retry-After": "60"}
    src = _source([resp, resp, resp])
    with pytest.raises(SourceError) as exc:
        src.search(_query(), max_results=10)
    msg = str(exc.value)
    assert "HTTP 429" in msg
    assert "per second AND per day" in msg
    # Three attempts consumed (BaseSource retries a 429 before giving up).
    assert len(src.session.calls) == 3


def test_400_points_at_the_query_string():
    src = _source([FakeResponse(status_code=400, text="Invalid query")])
    with pytest.raises(SourceError) as exc:
        src.search(_query(), max_results=10)
    assert "advanced-search string" in str(exc.value)
    assert "limit>50" in str(exc.value)


def test_500_is_retried_then_raised_unchanged():
    boom = FakeResponse(status_code=500, text="server error")
    src = _source([boom, boom, boom])
    with pytest.raises(SourceError) as exc:
        src.search(_query(), max_results=10)
    assert "HTTP 500" in str(exc.value)
    assert len(src.session.calls) == 3


def test_transient_500_then_success():
    src = _source([FakeResponse(status_code=500, text="oops"),
                   _page([_hit()], total=1)])
    assert len(src.search(_query(), max_results=10).records) == 1


def test_malformed_json_body():
    src = _source([FakeResponse(status_code=200, text="<html>not json</html>")])
    with pytest.raises(SourceError) as exc:
        src.search(_query(), max_results=10)
    assert "malformed JSON" in str(exc.value)


def test_json_list_instead_of_object():
    src = _source([FakeResponse(payload=[1, 2, 3])])
    with pytest.raises(SourceError) as exc:
        src.search(_query(), max_results=10)
    assert "unexpected response type list" in str(exc.value)


def test_network_error_is_wrapped():
    import requests

    def boom(url, params, headers):
        raise requests.ConnectionError("no route to host")

    with pytest.raises(SourceError) as exc:
        _source(boom).search(_query(), max_results=10)
    assert "network error" in str(exc.value)


def test_hits_not_a_list_ends_retrieval():
    src = _source([FakeResponse(payload={"metadata": {"total": 5},
                                         "hits": {"uid": "WOS:1"}})])
    res = src.search(_query(), max_results=10)
    assert res.records == []


# ----------------------------------------------------------- construction
def test_defaults_and_throttling_interval():
    s = WosStarterSource(api_key="K")
    assert s.name == "Web of Science Core Collection"
    assert s.platform == "Clarivate"
    assert s.db == "WOS"
    assert s.min_interval == pytest.approx(1.1)
    assert WosStarterSource(api_key="K", min_interval=0.2).min_interval == 0.2
    assert WosStarterSource(api_key="K", db="").db == "WOS"


def test_registry_classifies_the_client_as_principal():
    from corpusslr import classify_source
    assert classify_source(WosStarterSource.name) == "principal"


def test_client_is_exported_from_the_package():
    import corpusslr
    from corpusslr import sources
    for mod in (corpusslr, sources):
        assert mod.WosStarterSource is WosStarterSource
        assert mod.parse_wos_hit is parse_wos_hit
    # The file-export parser keeps its own, distinct entry points.
    assert corpusslr.parse_wos is not parse_wos_hit


def test_corpus_integration_records_the_search_event():
    from corpusslr import Corpus
    c = Corpus()
    src = _source([_page([_hit()], total=1)])
    ev = c.add_search(src.search(_query(), max_results=10))
    assert ev.records_retrieved == 1
    assert c.records[0].provenance[0]["database"] == \
        "Web of Science Core Collection"
    assert c.records[0].provenance[0]["source_id"] == "WOS:000123456700001"


# ------------------------------------------------------------------ to_wos
def test_to_wos_blocks_repeat_the_field_tag():
    s = _query().to_wos()
    assert 'TS=("artificial intelligence" OR "machine learning")' in s
    assert 'TS=("adoption")' in s
    assert s.count("TS=") == 2          # every clause carries its own tag
    assert " AND " in s


def test_to_wos_year_range():
    assert "PY=2015-2026" in _query().to_wos()
    assert "PY=" not in SearchQuery(blocks=[["ai"]]).to_wos()


def test_to_wos_doc_types_use_wos_labels():
    q = SearchQuery(blocks=[["ai"]],
                    doc_types=["article", "review", "conference", "chapter",
                               "book", "editorial", "letter"])
    s = q.to_wos()
    assert ("DT=(Article OR Review OR Proceedings Paper OR Book Chapter OR "
            "Book OR Editorial Material OR Letter)") in s
    assert q.warnings == []


def test_to_wos_languages_use_english_names():
    assert "LA=(English)" in SearchQuery(blocks=[["ai"]],
                                         languages=["en"]).to_wos()
    assert "LA=(Polish OR German)" in \
        SearchQuery(blocks=[["ai"]], languages=["pl", "de"]).to_wos()


def test_to_wos_title_only_switches_the_field_tag():
    s = SearchQuery(blocks=[["ai"]], title_only=True).to_wos()
    assert s == 'TI=("ai")'
    assert "TS=" not in s


def test_to_wos_unsupported_doc_type_warns():
    q = SearchQuery(blocks=[["ai"]], doc_types=["article", "preprint",
                                                "thesis"])
    s = q.to_wos()
    assert s.endswith("DT=(Article)")
    joined = " ".join(q.warnings)
    assert "Web of Science: unsupported doc_type 'preprint'" in joined
    assert "Web of Science: unsupported doc_type 'thesis'" in joined


def test_to_wos_unmapped_language_passes_through_with_a_warning():
    q = SearchQuery(blocks=[["ai"]], languages=["sv"])
    assert "LA=(sv)" in q.to_wos()
    assert any("language code 'sv'" in w for w in q.warnings)


def test_to_wos_warnings_are_idempotent():
    q = SearchQuery(blocks=[["ai"]], doc_types=["preprint"],
                    languages=["sv"])
    for _ in range(4):
        q.to_wos()
        q.compile_all()
    assert q.warnings and len(q.warnings) == len(set(q.warnings))
    assert len([w for w in q.warnings if "unsupported doc_type" in w
                and "Web of Science" in w]) == 1


def test_to_wos_strips_quotes_and_commas_like_the_other_compilers():
    s = SearchQuery(blocks=[['ai, robots', '"deep" learning']]).to_wos()
    # _clean() maps a comma to a space (shared with to_scopus) and strips the
    # inner quotes that would otherwise close the phrase early.
    assert s == 'TS=("ai  robots" OR "deep learning")'
    assert '""' not in s


def test_to_wos_skips_empty_blocks_and_terms():
    assert SearchQuery(blocks=[[], ["ai"], ["  "]]).to_wos() == 'TS=("ai")'
    assert SearchQuery(blocks=[]).to_wos() == ""


def test_to_wos_full_query_shape():
    q = SearchQuery(blocks=[["ai"], ["sme"]], years=(2020, 2024),
                    doc_types=["article", "review"], languages=["en"])
    assert q.to_wos() == ('TS=("ai") AND TS=("sme") AND PY=2020-2024 AND '
                          'DT=(Article OR Review) AND LA=(English)')


def test_compile_all_includes_wos():
    q = SearchQuery(blocks=[["a"], ["b"]])
    out = q.compile_all()
    assert "wos" in out
    assert out["wos"] == 'TS=("a") AND TS=("b")'
    # The pre-existing backends are untouched.
    assert {"scopus", "openalex", "pubmed", "crossref", "semanticscholar",
            "arxiv", "warnings"} <= set(out)


def test_search_uses_the_compiled_query_verbatim():
    """PRISMA-S Item 8: the reported search string must be the executed one."""
    q = _query()
    src = _source([_page([_hit()], total=1)])
    res = src.search(q, max_results=10)
    assert src.session.calls[0]["params"]["q"] == res.event.query == q.to_wos()


# --------------------------------------------------------------------------
# Gateway behaviour measured against the live Clarivate service on 2026-08-19
# with a real Web of Science EXPANDED API key. The authentication failure modes
# are indistinguishable from status codes alone, so the diagnosis has to tell
# them apart -- a user holding an Expanded key against this Starter client is
# the common case, and the message used to send them to check database
# entitlement, which is the wrong place to look.
#
#   Expanded key on /api/wos               -> 401 "Not authorized for product: WWS"
#   Expanded key on /apis/wos-starter/v1   -> 403 "You cannot consume this service"
#   syntactically invalid key on either    -> 401 bare "Unauthorized"
# --------------------------------------------------------------------------
_LIVE_403 = ('{"message":"You cannot consume this service",'
             '"request_id":"4b711f04f842886f42dcdd28a6fd6c3f"}')


def test_403_names_the_wrong_product_case():
    """The measured cause of a Starter 403 is a key issued for another product."""
    src = _source([FakeResponse(status_code=403, text=_LIVE_403)])
    with pytest.raises(SourceError) as exc:
        src.search(_query(), max_results=10)
    msg = str(exc.value)
    assert "different Clarivate product" in msg
    assert "Expanded" in msg
    assert "/apis/wos-starter/v1" in msg, "the message must name which API this client speaks"
    assert "developer.clarivate.com" in msg


def test_403_does_not_blame_a_mistyped_key():
    """An invalid key returns 401 at the gateway, so a 403 is never a typo."""
    src = _source([FakeResponse(status_code=403, text=_LIVE_403)])
    with pytest.raises(SourceError) as exc:
        src.search(_query(), max_results=10)
    assert "never a typo" in str(exc.value)


def test_401_and_403_do_not_collapse_into_one_diagnosis():
    """Each failure mode needs a different fix, so they must read differently."""
    src401 = _source([FakeResponse(status_code=401, text='{"message":"Unauthorized"}')])
    with pytest.raises(SourceError) as exc:
        src401.search(_query(), max_results=10)
    msg401 = str(exc.value)
    assert "different Clarivate product" not in msg401, (
        "the wrong-product wording belongs to 403, not 401")
    assert "API key" in msg401
