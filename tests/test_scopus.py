"""Regression tests for the Scopus Search API client.

No test touches the network: every payload below is a hand-written fixture
replayed through the offline harness in ``conftest.py``.  The shapes covered
(page-size caps per view, the start+count<=5000 boundary, ``cursor["@next"]``,
the COMPLETE author array including its single-author object form,
``authkeywords`` joined by " | ", and the 400/401/403/429 error envelopes)
follow the Scopus Search API documentation and response shapes reported by the
package maintainer from an entitled institutional account.  They were not
verified against the live API from this test environment, so a payload shape
may drift from the current API; treat a live-API mismatch as a reason to
re-check the fixture rather than assuming the client is wrong.
"""
import pytest

from conftest import FakeResponse, FakeSession

from corpusslr import ScopusSource, SearchQuery
from corpusslr.sources.base import SourceError

Q = SearchQuery(blocks=[["artificial intelligence", "machine learning"],
                        ["adoption"]],
                years=(2015, 2026), doc_types=["article", "review"],
                languages=["en"])

_URL = "https://api.elsevier.com/content/search/scopus"


def _standard_entry(i=0):
    """STANDARD view: one author in dc:creator, no abstract, no keywords."""
    return {
        "dc:identifier": "SCOPUS_ID:8500{}".format(i),
        "eid": "2-s2.0-8500{}".format(i),
        "dc:title": "Scopus paper {}".format(i),
        "dc:creator": "Kowalski J.",
        "prism:coverDate": "2024-03-01",
        "prism:publicationName": "Journal of Business Research",
        "prism:doi": "10.1016/j.jbusres.2024.{}".format(i),
        "prism:issn": "01482963",
        "prism:volume": "170",
        "prism:issueIdentifier": "4",
        "prism:pageRange": "114-128",
        "subtypeDescription": "Article",
        "openaccessFlag": True,
        "citedby-count": "12",
    }


def _complete_entry(i=0, n_authors=3):
    """COMPLETE view: author array, authkeywords, dc:description."""
    names = [("Wu", "Yulong"), ("Nowak", "Anna"), ("van der Berg", "Jan")]
    authors = [{"@seq": str(k + 1), "authid": "570000{}".format(k),
                "authname": "{} {}.".format(f, g[0]), "surname": f,
                "given-name": g, "initials": "{}.".format(g[0]),
                "afid": [{"$": "6000{}".format(k)}]}
               for k, (f, g) in enumerate(names[:n_authors])]
    e = _standard_entry(i)
    e.update({
        "dc:description": "A full abstract as returned by the COMPLETE view.",
        "author": authors,
        "author-count": {"@limit": "100", "@total": str(n_authors)},
        "authkeywords": ("Aqueous Mg-air battery | Electrolyte additive | "
                         "Machine learning | Self-discharge"),
    })
    return e


def _results(entries, total=None, cursor=None):
    sr = {"opensearch:totalResults": str(
        total if total is not None else len(entries)), "entry": entries}
    if cursor is not None:
        sr["cursor"] = {"@next": cursor}
    return {"search-results": sr}


def _src(session, **kw):
    kw.setdefault("use_cursor", False)
    return ScopusSource(api_key="KEY", session=session, **kw)


# ------------------------------------------------------------------ parsing
def test_standard_entry_parses_single_creator_as_only_author():
    s = FakeSession([FakeResponse(200, payload=_results([_standard_entry(1)]))])
    res = _src(s).search(Q)
    r = res.records[0]
    # dc:creator is family-first ("Kowalski J.") and is normalised to the
    # "Family, Given" record contract, so its surname agrees with the COMPLETE
    # view; see tests/test_scopus_live_shapes.py for the measured evidence.
    assert r.authors == ["Kowalski, J."]
    assert r.keywords == []
    assert r.abstract == ""
    assert r.scopus_id == "85001" and r.source_id == "85001"
    assert r.year == 2024 and r.doc_type == "article"
    assert r.cited_by == 12 and r.open_access is True
    assert r.issn == "01482963" and r.pages == "114-128"


def test_standard_view_notes_incomplete_author_list():
    s = FakeSession([FakeResponse(200, payload=_results([_standard_entry(1)]))])
    notes = _src(s).search(Q).event.notes
    assert "only the first author" in notes
    assert "COMPLETE" in notes


def test_complete_entry_parses_full_author_list_and_keywords():
    s = FakeSession([FakeResponse(200, payload=_results([_complete_entry(1)]))])
    res = _src(s, view="COMPLETE").search(Q)
    r = res.records[0]
    assert r.authors == ["Wu, Yulong", "Nowak, Anna", "van der Berg, Jan"]
    assert r.keywords == ["Aqueous Mg-air battery", "Electrolyte additive",
                          "Machine learning", "Self-discharge"]
    assert r.abstract.startswith("A full abstract")
    # a complete author list must not trigger the STANDARD-view warning
    assert "only the first author" not in res.event.notes


def test_complete_single_author_arrives_as_object_not_list():
    """Elsevier collapses a one-element XML array into a bare JSON object."""
    e = _complete_entry(2)
    e["author"] = e["author"][0]
    e["author-count"] = {"@total": "1"}
    s = FakeSession([FakeResponse(200, payload=_results([e]))])
    r = _src(s, view="COMPLETE").search(Q).records[0]
    assert r.authors == ["Wu, Yulong"]


def test_author_without_given_name_falls_back_to_authname():
    e = _complete_entry(3, n_authors=1)
    e["author"] = [{"authname": "Kowalski J."}]
    s = FakeSession([FakeResponse(200, payload=_results([e]))])
    assert _src(s, view="COMPLETE").search(Q).records[0].authors == \
        ["Kowalski, J."]


def test_author_with_surname_only_keeps_surname():
    e = _complete_entry(3, n_authors=1)
    e["author"] = [{"surname": "Kowalski"}]
    s = FakeSession([FakeResponse(200, payload=_results([e]))])
    assert _src(s, view="COMPLETE").search(Q).records[0].authors == ["Kowalski"]


def test_non_dict_author_members_are_skipped():
    e = _complete_entry(3, n_authors=1)
    e["author"] = ["garbage", {"surname": "Wu", "given-name": "Yulong"}]
    s = FakeSession([FakeResponse(200, payload=_results([e]))])
    assert _src(s, view="COMPLETE").search(Q).records[0].authors == \
        ["Wu, Yulong"]


def test_truncated_author_list_is_reported_in_event():
    e = _complete_entry(4, n_authors=2)
    e["author-count"] = {"@limit": "100", "@total": "9"}
    s = FakeSession([FakeResponse(200, payload=_results([e]))])
    res = _src(s, view="COMPLETE").search(Q)
    assert len(res.records[0].authors) == 2
    assert "author list truncated" in res.event.notes


def test_authkeywords_non_string_is_ignored():
    e = _complete_entry(5)
    e["authkeywords"] = {"unexpected": "shape"}
    s = FakeSession([FakeResponse(200, payload=_results([e]))])
    assert _src(s, view="COMPLETE").search(Q).records[0].keywords == []


def test_missing_fields_do_not_crash():
    thin = FakeResponse(200, payload=_results([{"dc:title": "Bare entry"}], 1))
    r = _src(FakeSession([thin])).search(Q).records[0]
    assert r.title == "Bare entry"
    assert r.year is None and r.doi == "" and r.pages == ""
    assert r.cited_by is None and r.open_access is None and r.authors == []


def test_subtype_description_maps_to_doc_type_vocabulary():
    e = _standard_entry(6)
    e["subtypeDescription"] = "Conference Paper"
    s = FakeSession([FakeResponse(200, payload=_results([e]))])
    assert _src(s).search(Q).records[0].doc_type == "conference"


def test_eissn_used_when_issn_absent():
    e = _standard_entry(7)
    del e["prism:issn"]
    e["prism:eIssn"] = "14710072"
    s = FakeSession([FakeResponse(200, payload=_results([e]))])
    assert _src(s).search(Q).records[0].issn == "14710072"


# ------------------------------------------------------------------- paging
def test_page_size_follows_view():
    assert _src(FakeSession([])).page_size() == 200                 # STANDARD
    assert _src(FakeSession([]), view="COMPLETE").page_size() == 25
    assert _src(FakeSession([]), view="MADE-UP").page_size() == 25  # fallback
    assert _src(FakeSession([])).page_size(10) == 10                # caller cap


def test_standard_view_requests_200_per_page():
    s = FakeSession([FakeResponse(200, payload=_results(
        [_standard_entry(i) for i in range(200)], total=200))])
    _src(s).search(Q, max_results=1000)
    assert s.calls[0]["params"]["count"] == 200


def test_complete_view_requests_25_per_page():
    s = FakeSession([FakeResponse(200, payload=_results(
        [_complete_entry(i) for i in range(25)], total=25))])
    _src(s, view="COMPLETE").search(Q, max_results=1000)
    assert s.calls[0]["params"]["count"] == 25


def test_offset_paging_advances_start_and_sends_no_cursor():
    pages = [FakeResponse(200, payload=_results(
        [_standard_entry(i) for i in range(200)], total=250)),
        FakeResponse(200, payload=_results(
            [_standard_entry(i) for i in range(200, 250)], total=250))]
    s = FakeSession(pages)
    res = _src(s).search(Q, max_results=1000)
    assert len(res.records) == 250
    assert [c["params"]["start"] for c in s.calls] == [0, 200]
    assert all("cursor" not in c["params"] for c in s.calls)
    assert res.event.filters == "view=STANDARD; paging=offset"


def test_cursor_paging_sends_cursor_and_never_start():
    pages = [
        FakeResponse(200, payload=_results(
            [_standard_entry(i) for i in range(200)], total=600, cursor="C1")),
        FakeResponse(200, payload=_results(
            [_standard_entry(i) for i in range(200, 400)], total=600,
            cursor="C2")),
        FakeResponse(200, payload=_results(
            [_standard_entry(i) for i in range(400, 600)], total=600,
            cursor="C3")),
    ]
    s = FakeSession(pages)
    res = ScopusSource(api_key="K", session=s).search(Q, max_results=1000)
    assert len(res.records) == 600
    assert [c["params"]["cursor"] for c in s.calls] == ["*", "C1", "C2"]
    assert all("start" not in c["params"] for c in s.calls)
    assert res.event.filters == "view=STANDARD; paging=cursor"


def test_cursor_paging_stops_when_cursor_does_not_advance():
    page = _results([_standard_entry(i) for i in range(200)], total=100000,
                    cursor="SAME")
    s = FakeSession([FakeResponse(200, payload=page),
                     FakeResponse(200, payload=page)])
    res = ScopusSource(api_key="K", session=s).search(Q, max_results=10000)
    # the second page repeats cursor "SAME" -> stop instead of looping forever
    assert len(s.calls) == 2 and len(res.records) == 400


def test_cursor_paging_stops_when_next_cursor_missing():
    s = FakeSession([FakeResponse(200, payload=_results(
        [_standard_entry(i) for i in range(200)], total=100000))])
    res = ScopusSource(api_key="K", session=s).search(Q, max_results=10000)
    assert len(s.calls) == 1 and len(res.records) == 200


def test_cursor_paging_exceeds_the_offset_cap_without_a_note():
    """Cursor paging is not subject to start+count<=5000."""
    pages = []
    for p in range(30):                              # 30 x 200 = 6000 records
        pages.append(FakeResponse(200, payload=_results(
            [_standard_entry(i) for i in range(p * 200, p * 200 + 200)],
            total=6000, cursor="C{}".format(p))))
    res = ScopusSource(api_key="K", session=FakeSession(pages)).search(
        Q, max_results=6000)
    assert len(res.records) == 6000
    assert "caps offset paging" not in res.event.notes


def test_offset_paging_stops_at_max_offset_with_explicit_note():
    src = ScopusSource(api_key="K", use_cursor=False,
                       session=FakeSession(lambda url, params, headers:
                                           FakeResponse(200, payload=_results(
                                               [_standard_entry(i)
                                                for i in range(params["count"])],
                                               total=12345))))
    res = src.search(Q, max_results=12345)
    assert len(res.records) == ScopusSource.MAX_OFFSET == 5000
    assert "caps offset paging" in res.event.notes
    assert "5000 of 12345" in res.event.notes
    assert "use_cursor=True" in res.event.notes


def test_last_offset_page_is_shrunk_to_respect_start_plus_count():
    """start+count must stay <= 5000: 4800+200 is the last legal request."""
    calls = []

    def handler(url, params, headers):
        calls.append(dict(params))
        return FakeResponse(200, payload=_results(
            [_standard_entry(i) for i in range(params["count"])], total=12345))

    src = ScopusSource(api_key="K", use_cursor=False,
                       session=FakeSession(handler))
    src.search(Q, max_results=12345)
    assert all(c["start"] + c["count"] <= ScopusSource.MAX_OFFSET
               for c in calls)
    assert calls[-1]["start"] == 4800 and calls[-1]["count"] == 200


def test_max_results_caps_retrieval_and_is_reported():
    s = FakeSession([FakeResponse(200, payload=_results(
        [_standard_entry(i) for i in range(200)], total=5000, cursor="C1"))])
    res = ScopusSource(api_key="K", session=s).search(Q, max_results=30)
    assert len(res.records) == 30
    assert s.calls[0]["params"]["count"] == 30      # do not over-fetch
    assert "max_results=30" in res.event.notes


def test_paging_stops_once_total_is_reached():
    s = FakeSession([FakeResponse(200, payload=_results(
        [_standard_entry(i) for i in range(5)], total=5, cursor="C1"))])
    res = ScopusSource(api_key="K", session=s).search(Q, max_results=1000)
    assert len(s.calls) == 1 and len(res.records) == 5


# ------------------------------------------------------------------- errors
def _err(code, text):
    return {"service-error": {"status": {"statusCode": code,
                                         "statusText": text}}}


def test_401_message_names_both_causes_and_insttoken():
    s = FakeSession([FakeResponse(401, payload=_err(
        "AUTHENTICATION_ERROR",
        "Invalid API Key: valid apikey credentials required."))])
    with pytest.raises(SourceError) as ei:
        _src(s).search(Q)
    msg = str(ei.value)
    assert "401" in msg and "AUTHENTICATION_ERROR" in msg
    assert "insttoken" in msg
    assert "IP range" in msg          # off-campus cause named explicitly
    assert "wrong" in msg             # bad-key cause named explicitly
    assert len(s.calls) == 1          # deterministic 4xx: no retry


def test_403_authorization_error_points_at_the_view_entitlement():
    s = FakeSession([FakeResponse(403, payload=_err(
        "AUTHORIZATION_ERROR", "APIKey ... is not authorized"))])
    with pytest.raises(SourceError) as ei:
        _src(s, view="COMPLETE").search(Q)
    msg = str(ei.value)
    assert "403" in msg and "AUTHORIZATION_ERROR" in msg
    assert "view='COMPLETE'" in msg and "view='STANDARD'" in msg
    assert "quota" not in msg.lower()


def test_403_quota_exceeded_is_distinguished_from_authorization():
    s = FakeSession([FakeResponse(403, payload=_err(
        "QUOTA_EXCEEDED", "Quota Exceeded"))])
    with pytest.raises(SourceError) as ei:
        _src(s).search(Q)
    msg = str(ei.value)
    assert "QUOTA_EXCEEDED" in msg and "weekly request quota" in msg
    assert "entitled to this request" not in msg


def test_429_message_carries_ratelimit_headers():
    r = FakeResponse(429, payload=_err("RATE_LIMIT_EXCEEDED", "Too Many"))
    r.headers = {"X-RateLimit-Remaining": "0",
                 "X-RateLimit-Reset": "1718000000"}
    s = FakeSession([r])
    with pytest.raises(SourceError) as ei:
        _src(s).search(Q)
    msg = str(ei.value)
    assert "429" in msg
    assert "X-RateLimit-Remaining=0" in msg
    assert "X-RateLimit-Reset=1718000000" in msg


def test_400_offset_message_explains_the_misleading_status_text():
    s = FakeSession([FakeResponse(400, payload=_err(
        "INVALID_INPUT", "Exceeds the number of search results"))])
    with pytest.raises(SourceError) as ei:
        _src(s).search(Q)
    msg = str(ei.value)
    assert "misleading" in msg and "start+count" in msg and "5000" in msg


def test_400_page_size_message_names_the_per_view_cap():
    s = FakeSession([FakeResponse(400, payload=_err(
        "INVALID_INPUT", "Exceeds the maximum number allowed for ..."))])
    with pytest.raises(SourceError) as ei:
        _src(s, view="COMPLETE").search(Q)
    msg = str(ei.value)
    assert "page size exceeds" in msg and "25 for view=COMPLETE" in msg


def test_error_response_envelope_is_also_decoded():
    s = FakeSession([FakeResponse(404, payload={"error-response": {
        "error-code": "RESOURCE_NOT_FOUND", "error-message": "no such view"}})])
    with pytest.raises(SourceError) as ei:
        _src(s).search(Q)
    assert "RESOURCE_NOT_FOUND" in str(ei.value)


def test_flat_status_envelope_is_also_decoded():
    s = FakeSession([FakeResponse(404, payload={"statusCode": "X",
                                                "statusText": "flat"})])
    with pytest.raises(SourceError) as ei:
        _src(s).search(Q)
    assert "X" in str(ei.value) and "flat" in str(ei.value)


def test_non_json_error_body_still_raises_source_error():
    s = FakeSession([FakeResponse(404, text="<html>gateway</html>")])
    with pytest.raises(SourceError) as ei:
        _src(s).search(Q)
    assert "HTTP 404" in str(ei.value)


def test_service_error_without_status_object_uses_status_text():
    s = FakeSession([FakeResponse(404, payload={
        "service-error": {"statusText": "plain text only"}})])
    with pytest.raises(SourceError) as ei:
        _src(s).search(Q)
    assert "plain text only" in str(ei.value)


def test_5xx_is_retried_then_raised():
    s = FakeSession([FakeResponse(500, text="boom")] * 3)
    with pytest.raises(SourceError) as ei:
        _src(s).search(Q)
    assert "HTTP 500" in str(ei.value) and len(s.calls) == 3


def test_5xx_then_success_recovers():
    s = FakeSession([FakeResponse(500, text="boom"),
                     FakeResponse(200, payload=_results([_standard_entry(1)]))])
    res = _src(s).search(Q)
    assert len(res.records) == 1 and len(s.calls) == 2


def test_network_error_is_wrapped_in_source_error():
    import requests as _rq

    def boom(url, params, headers):
        raise _rq.ConnectionError("dns down")

    with pytest.raises(SourceError) as ei:
        _src(FakeSession(boom)).search(Q)
    assert "network error" in str(ei.value)


# -------------------------------------------------------------- empty result
def test_empty_result_set_is_not_an_error_and_keeps_the_event():
    s = FakeSession([FakeResponse(200, payload={"search-results": {
        "opensearch:totalResults": "0",
        "entry": [{"error": "Result set was empty"}]}})])
    res = _src(s).search(Q)
    assert res.records == []
    assert res.event.database == "Scopus" and res.event.query
    assert "empty result set" in res.event.notes
    assert "totalResults=0" in res.event.notes


def test_empty_entry_list_stops_cleanly():
    s = FakeSession([FakeResponse(200, payload={"search-results": {
        "opensearch:totalResults": "5", "entry": []}})])
    res = _src(s).search(Q)
    assert res.records == [] and "totalResults=5" in res.event.notes


# ----------------------------------------------------------------- request
def test_query_sent_is_exactly_query_to_scopus():
    s = FakeSession([FakeResponse(200, payload=_results([_standard_entry(1)]))])
    res = _src(s).search(Q)
    assert s.calls[0]["params"]["query"] == Q.to_scopus()
    assert res.event.query == Q.to_scopus()
    assert s.calls[0]["url"] == _URL
    assert s.calls[0]["params"]["httpAccept"] == "application/json"
    assert s.calls[0]["params"]["view"] == "STANDARD"


def test_authentication_headers():
    s = FakeSession([FakeResponse(200, payload=_results([_standard_entry(1)]))])
    ScopusSource(api_key="KEY", insttoken="TOK", session=s).search(Q)
    h = s.calls[0]["headers"]
    assert h["X-ELS-APIKey"] == "KEY"
    assert h["X-ELS-Insttoken"] == "TOK"
    assert h["Accept"] == "application/json"


def test_insttoken_header_absent_when_not_supplied():
    s = FakeSession([FakeResponse(200, payload=_results([_standard_entry(1)]))])
    _src(s).search(Q)
    assert "X-ELS-Insttoken" not in s.calls[0]["headers"]


def test_view_name_is_normalized_to_upper_case():
    s = FakeSession([FakeResponse(200, payload=_results([_complete_entry(1)]))])
    res = _src(s, view="complete").search(Q)
    assert s.calls[0]["params"]["view"] == "COMPLETE"
    assert res.records[0].keywords[0] == "Aqueous Mg-air battery"


def test_complete_view_entry_without_author_array_gets_its_own_note():
    e = _complete_entry(8)
    del e["author"]
    del e["author-count"]
    s = FakeSession([FakeResponse(200, payload=_results([e]))])
    res = _src(s, view="COMPLETE").search(Q)
    assert res.records[0].authors == ["Kowalski, J."]     # dc:creator fallback
    assert "despite view=COMPLETE" in res.event.notes
    assert "only the first author" not in res.event.notes


def test_authname_helper_handles_all_observed_shapes():
    from corpusslr.sources.scopus import _split_authname
    assert _split_authname("Wu Y.") == "Wu, Y."          # Scopus display form
    assert _split_authname("van der Berg J.A.") == "van der Berg, J.A."
    assert _split_authname("Kowalski, Jan") == "Kowalski, Jan"   # already inverted
    assert _split_authname("Yulong Wu") == "Wu, Yulong"  # natural order fallback
    assert _split_authname("") == ""
    assert _split_authname(None) == ""


def test_author_count_scalar_and_unparsable_shapes():
    src = _src(FakeSession([]))
    assert src._author_total({"author-count": "9"}) == 9
    assert src._author_total({"author-count": {"$": "4"}}) == 4
    assert src._author_total({"author-count": {"@total": "x"}}) is None
    assert src._author_total({}) is None


def test_non_dict_error_body_yields_plain_http_message():
    s = FakeSession([FakeResponse(400, payload=["unexpected", "list"])])
    with pytest.raises(SourceError) as ei:
        _src(s).search(Q)
    assert "HTTP 400" in str(ei.value)


def test_zero_retries_raises_retries_exhausted():
    src = _src(FakeSession([]))
    with pytest.raises(SourceError) as ei:
        src._get_page({"query": "x"}, retries=0)
    assert "retries exhausted" in str(ei.value)


def test_offset_paging_stops_when_start_passes_total():
    """A short page (fewer entries than count) still terminates the loop."""
    s = FakeSession([FakeResponse(200, payload=_results(
        [_standard_entry(i) for i in range(10)], total=30))])
    res = _src(s).search(Q, max_results=1000)
    assert len(res.records) == 10 and len(s.calls) == 1
    assert "totalResults=30" in res.event.notes


def test_offset_cap_reached_exactly_at_the_page_boundary():
    """The loop-entry guard fires when start lands exactly on MAX_OFFSET."""
    def handler(url, params, headers):
        return FakeResponse(200, payload=_results(
            [_standard_entry(i) for i in range(params["count"])], total=9999))

    src = ScopusSource(api_key="K", use_cursor=False,
                       session=FakeSession(handler))
    res = src.search(Q, max_results=9999)
    assert len(res.records) == 5000
    assert "caps offset paging" in res.event.notes


def test_search_event_reports_database_platform_and_url():
    s = FakeSession([FakeResponse(200, payload=_results([_standard_entry(1)]))])
    ev = _src(s).search(Q).event
    assert ev.database == "Scopus" and ev.platform == "Elsevier"
    assert ev.interface == "API" and ev.url == _URL and ev.date_run


# --------------------------------------------------------------------------
# View selection. Measured against the live API on the same query: view=STANDARD
# returned ONE author per record and ZERO abstracts across 100 records, while
# view=COMPLETE returned up to 10 authors and an abstract for every record.
# Deduplication survives that (title matching carries it) but title/abstract
# screening cannot happen at all on an abstract-free corpus, so defaulting to
# STANDARD while holding an institutional token silently degraded the review.
# --------------------------------------------------------------------------
def test_an_institutional_token_selects_the_richer_view():
    src = ScopusSource(api_key="k", insttoken="t")
    assert src.view == "COMPLETE"
    assert src.view_auto_selected is True


def test_without_a_token_the_standard_view_is_used():
    """COMPLETE requires an entitlement, so it may not be assumed."""
    src = ScopusSource(api_key="k")
    assert src.view == "STANDARD"
    assert src.view_auto_selected is True


def test_an_explicit_view_is_never_overridden():
    """A caller who names a view has a reason; auto-selection must not fight it."""
    src = ScopusSource(api_key="k", insttoken="t", view="STANDARD")
    assert src.view == "STANDARD"
    assert src.view_auto_selected is False
    src2 = ScopusSource(api_key="k", view="COMPLETE")
    assert src2.view == "COMPLETE"


def test_the_page_size_follows_the_selected_view():
    """The API caps count per view with a hard 400, so this must track the view."""
    assert ScopusSource(api_key="k", insttoken="t").page_size() == 25
    assert ScopusSource(api_key="k").page_size() == 200


def test_the_standard_view_still_warns_that_author_lists_are_incomplete():
    payload = {"search-results": {
        "opensearch:totalResults": "1",
        "entry": [{"dc:title": "A study", "dc:creator": "Wang, W.",
                   "prism:doi": "10.5001/a", "prism:coverDate": "2020-01-01",
                   "prism:publicationName": "Journal",
                   "subtypeDescription": "Article"}]}}
    session = FakeSession(lambda url, params, headers:
                          FakeResponse(200, payload=payload))
    res = ScopusSource(api_key="k", view="STANDARD",
                       session=session).search(Q, max_results=1)
    assert "dc:creator" in res.event.notes
    assert "COMPLETE" in res.event.notes
