"""Offline tests for the bioRxiv/medRxiv (Cold Spring Harbor) clients."""
import datetime as dt

import pytest

from conftest import FakeResponse, FakeSession

from corpusslr import SearchQuery
from corpusslr.sources.base import SourceError
from corpusslr.sources.preprints import (BiorxivSource, MedrxivSource,
                                         matches_query, parse_preprint,
                                         render_local_filter)


def _item(**kw):
    base = {
        "doi": "10.1101/2024.01.01.123456",
        "title": "Wpływ sieci neuronowych na diagnostykę",
        "authors": "Kowalski, J.; Nowak-Zielińska, A.",
        "author_corresponding": "Jan Kowalski",
        "author_corresponding_institution": "Uniwersytet Testowy",
        "date": "2024-03-15",
        "version": "2",
        "type": "new results",
        "license": "cc_by",
        "category": "bioinformatics",
        "abstract": "Machine learning applied to diagnostics.",
        "published": "10.1016/j.test.2024.01",
        "server": "biorxiv",
    }
    base.update(kw)
    return base


def _payload(items, total=None, status="ok", cursor=0):
    return {"messages": [{"status": status, "interval": "x",
                          "cursor": cursor,
                          "count": len(items),
                          "total": len(items) if total is None else total}],
            "collection": items}


def _q(terms=None, **kw):
    return SearchQuery(blocks=terms if terms is not None else [["machine learning"]],
                       **kw)


# ----------------------------------------------------------------- parsing
def test_parse_full_item():
    r = parse_preprint(_item())
    assert r.doi == "10.1101/2024.01.01.123456"
    assert r.doc_type == "preprint"
    assert r.year == 2024
    assert r.source == "bioRxiv" and r.journal == "bioRxiv"
    assert r.source_id == r.doi
    assert r.open_access is True
    assert r.url == "https://doi.org/10.1101/2024.01.01.123456"
    assert r.authors == ["Kowalski, J.", "Nowak-Zielińska, A."]
    assert r.keywords == ["bioinformatics"]
    assert r.raw["published"] == "10.1016/j.test.2024.01"
    assert r.raw["version"] == "2"


def test_parse_medrxiv_label():
    r = parse_preprint(_item(server="medrxiv"))
    assert r.source == "medRxiv" and r.journal == "medRxiv"


def test_parse_na_published_becomes_empty():
    assert parse_preprint(_item(published="NA")).raw["published"] == ""
    assert parse_preprint(_item(published="na")).raw["published"] == ""


def test_parse_empty_and_missing_fields():
    r = parse_preprint({})
    assert r.title == "" and r.authors == [] and r.year is None
    assert r.doi == "" and r.url == "" and r.keywords == []
    r2 = parse_preprint({"date": "bad-date", "authors": "  ;  ",
                         "category": "   "})
    assert r2.year is None and r2.authors == [] and r2.keywords == []


def test_parse_none_is_safe():
    assert parse_preprint(None).title == ""


# ---------------------------------------------------------- local matching
def test_matches_query_is_and_of_ors():
    rec = parse_preprint(_item())
    assert matches_query(rec, _q([["machine learning"], ["diagnostics"]]))
    assert not matches_query(rec, _q([["machine learning"], ["oncology"]]))
    assert matches_query(rec, _q([["oncology", "machine learning"]]))


def test_matches_query_is_diacritic_and_case_insensitive():
    rec = parse_preprint(_item())
    assert matches_query(rec, _q([["WPLYW"]]))          # ł -> l, case folded
    assert matches_query(rec, _q([["diagnostyke"]]))    # ę -> e
    assert matches_query(rec, _q([["MACHINE Learning"]]))


def test_author_names_are_not_searched():
    """Topical query terms must not be satisfied by an author surname."""
    rec = parse_preprint(_item())
    assert not matches_query(rec, _q([["Nowak-Zielinska"]]))


def test_matches_query_searches_category_and_abstract():
    rec = parse_preprint(_item())
    assert matches_query(rec, _q([["bioinformatics"]]))     # category
    assert matches_query(rec, _q([["applied to"]]))         # abstract


def test_title_only_restricts_the_haystack():
    rec = parse_preprint(_item())
    assert not matches_query(rec, _q([["bioinformatics"]], title_only=True))
    assert matches_query(rec, _q([["sieci neuronowych"]], title_only=True))


def test_empty_query_matches_everything():
    rec = parse_preprint(_item())
    assert matches_query(rec, _q([]))
    assert matches_query(rec, _q([[], [""]]))


def test_render_local_filter():
    assert render_local_filter(_q([["a", "b"], ["c"]])) == \
        'title/abstract/category: ("a" OR "b") AND ("c")'
    assert render_local_filter(_q([["a"]], title_only=True)).startswith("title:")
    assert render_local_filter(_q([])) == ""


# ------------------------------------------------------------------ search
def test_search_filters_locally_and_documents_it():
    hit = _item(title="Machine learning for X")
    miss = _item(doi="10.1101/other", title="Crystallography of Y",
                 abstract="No relevant terms here.", category="biophysics")
    sess = FakeSession(FakeResponse(payload=_payload([hit, miss], total=2)))
    res = BiorxivSource(session=sess).search(_q([["machine learning"]]),
                                             max_results=50)
    assert len(res.records) == 1
    assert res.records[0].title == "Machine learning for X"
    n = res.event.notes
    assert "scanned locally=2" in n
    assert "retained after local filtering=1" in n
    assert "NO full-text or boolean search" in n
    assert "SUPPLEMENTARY" in n
    assert "preprints" in n


def test_url_carries_server_and_interval():
    sess = FakeSession(FakeResponse(payload=_payload([])))
    q = _q([["x"]], years=(2020, 2021))
    res = MedrxivSource(session=sess).search(q)
    assert "/details/medrxiv/2020-01-01/2021-12-31/" in sess.calls[0]["url"]
    assert res.event.database == "medRxiv"
    assert res.event.platform == "Cold Spring Harbor Laboratory"
    assert "posting date 2020-01-01 to 2021-12-31" in res.event.filters


def test_interval_defaults_to_epoch_and_today():
    sess = FakeSession(FakeResponse(payload=_payload([])))
    BiorxivSource(session=sess).search(_q())
    url = sess.calls[0]["url"]
    assert "/2013-01-01/" in url
    assert dt.date.today().isoformat() in url


def test_future_end_date_is_clamped_to_today():
    sess = FakeSession(FakeResponse(payload=_payload([])))
    BiorxivSource(session=sess).search(_q(years=(2020, 2099)))
    assert dt.date.today().isoformat() in sess.calls[0]["url"]


def test_cursor_paging_advances_and_stops_when_total_is_reached():
    page1 = _payload([_item(doi="10.1101/%d" % i,
                            title="machine learning %d" % i)
                      for i in range(100)], total=150)
    page2 = _payload([_item(doi="10.1101/x%d" % i,
                            title="machine learning x%d" % i)
                      for i in range(50)], total=150)
    sess = FakeSession([FakeResponse(payload=page1),
                        FakeResponse(payload=page2)])
    res = BiorxivSource(session=sess).search(_q(), max_results=1000)
    assert len(res.records) == 150
    assert sess.calls[0]["url"].endswith("/0")
    assert sess.calls[1]["url"].endswith("/100")
    # cursor reached messages.total, so no third request is made
    assert len(sess.calls) == 2


def test_a_short_page_is_not_treated_as_the_last_page():
    """Regression: the API's real page size is 30, not the documented 100.

    Verified live against ``api.biorxiv.org`` for the bioRxiv window
    2024-01-01/2024-01-02: every cursor step returns ``messages.count == 30``
    while ``messages.total == 220``.  Terminating on a page shorter than a
    nominal 100 therefore stopped after the first 30 of 220 records -- an 86 %
    silent loss of the date window -- so termination must be driven by
    ``messages.total`` and by an empty page instead.  The fixture reproduces
    the measured shape: 30-record pages, total 220.
    """
    pages = []
    for start in range(0, 220, 30):
        n = min(30, 220 - start)
        pages.append(FakeResponse(payload=_payload(
            [_item(doi="10.1101/%d" % (start + i),
                   title="machine learning %d" % (start + i))
             for i in range(n)], total=220)))
    sess = FakeSession(list(pages))
    res = BiorxivSource(session=sess).search(_q(), max_results=1000)
    assert len(res.records) == 220, (
        "stopped after %d records; a 30-record page was mistaken for the "
        "last page" % len(res.records))
    assert "scanned locally=220" in res.event.notes
    # 220 / 30 -> 8 requests (the last one carries 10 records)
    assert [c["url"].rsplit("/", 1)[1] for c in sess.calls] == [
        "0", "30", "60", "90", "120", "150", "180", "210"]


def test_paging_stops_on_an_empty_page_when_total_is_unusable():
    """An empty collection is the fallback stop signal.

    When ``messages.total`` is missing or unparseable the loop cannot compare
    the cursor against it, so it must still terminate rather than page for
    ever.
    """
    payload_pages = [
        FakeResponse(payload={"messages": [{"status": "ok",
                                            "total": "unknown"}],
                              "collection": [
                                  _item(doi="10.1101/%d" % i,
                                        title="machine learning %d" % i)
                                  for i in range(30)]}),
        FakeResponse(payload={"messages": [{"status": "ok",
                                            "total": "unknown"}],
                              "collection": []}),
    ]
    sess = FakeSession(payload_pages)
    res = BiorxivSource(session=sess).search(_q(), max_results=1000)
    assert len(res.records) == 30
    assert len(sess.calls) == 2


def test_max_results_stops_paging_and_is_reported():
    full = _payload([_item(doi="10.1101/%d" % i,
                           title="machine learning %d" % i)
                     for i in range(100)], total=9999)
    sess = FakeSession(lambda url, params, headers:
                       FakeResponse(payload=full))
    res = BiorxivSource(session=sess).search(_q(), max_results=25)
    assert len(res.records) == 25
    assert "stopped at max_results=25" in res.event.notes


def test_empty_collection_returns_nothing():
    res = BiorxivSource(session=FakeSession(
        FakeResponse(payload=_payload([], total=0)))).search(_q())
    assert res.records == []
    assert "retained after local filtering=0" in res.event.notes


def test_no_posts_found_status_is_not_an_error():
    res = MedrxivSource(session=FakeSession(FakeResponse(
        payload={"messages": [{"status": "no posts found"}],
                 "collection": []}))).search(_q())
    assert res.records == []


def test_error_status_raises():
    src = BiorxivSource(session=FakeSession(FakeResponse(
        payload={"messages": [{"status": "malformed interval"}],
                 "collection": []})))
    with pytest.raises(SourceError):
        src.search(_q())


def test_malformed_json_raises():
    src = BiorxivSource(session=FakeSession(
        FakeResponse(status_code=200, text="<html>not json</html>")))
    with pytest.raises(SourceError):
        src.search(_q())


def test_non_dict_payload_raises():
    src = BiorxivSource(session=FakeSession(FakeResponse(payload=[1, 2])))
    with pytest.raises(SourceError):
        src.search(_q())


def test_http_error_raises():
    src = MedrxivSource(session=FakeSession(
        FakeResponse(status_code=404, text="nope")))
    with pytest.raises(SourceError):
        src.search(_q())


def test_missing_total_does_not_crash():
    res = BiorxivSource(session=FakeSession(FakeResponse(
        payload={"messages": [{"status": "ok", "total": "unknown"}],
                 "collection": [_item(title="machine learning z")]}))
    ).search(_q())
    assert len(res.records) == 1
    assert "messages.total=None" in res.event.notes


def test_missing_messages_key_is_tolerated():
    res = BiorxivSource(session=FakeSession(FakeResponse(
        payload={"collection": [_item(title="machine learning z")]}))
    ).search(_q())
    assert len(res.records) == 1


# --------------------------------------------------------------------------
# Scan budget. This API has no query interface, so retrieval enumerates a date
# window and filters locally. Measured against the live service, bioRxiv reports
# messages.total == 335,871 for 2018-01-01/2024-12-31 at 30 records per request
# and ~1.6 s per request: 11,196 requests, about five hours, for one search()
# call that looks like any other. An unbounded default made that the default.
# --------------------------------------------------------------------------
def _window_session(n_records, page=30, total=None):
    """A session that serves a large date window one page at a time."""
    pages = {}
    total = total if total is not None else n_records
    for cursor in range(0, n_records, page):
        items = [{"doi": "10.1101/%06d" % i,
                  "title": "Unrelated preprint %d" % i,
                  "abstract": "Nothing matching here.",
                  "authors": "Doe, J.", "date": "2020-06-01",
                  "category": "bioinformatics", "version": "1"}
                 for i in range(cursor, min(cursor + page, n_records))]
        pages[cursor] = {"collection": items,
                         "messages": [{"status": "ok", "count": len(items),
                                       "total": total}]}
    return FakeSession(lambda url, params, headers: FakeResponse(
        200, payload=pages.get(int(url.rstrip("/").rsplit("/", 1)[-1]),
                               {"collection": [],
                                "messages": [{"status": "ok", "count": 0,
                                              "total": total}]})))


def test_the_scan_budget_bounds_the_number_of_requests():
    """Without a budget a selective query on a wide window crawls the archive."""
    session = _window_session(3000)
    src = BiorxivSource(session=session)
    src.MAX_SCANNED = 300
    q = SearchQuery(blocks=[["nothing will match this"]], years=(2018, 2024))
    res = src.search(q, max_results=50)
    assert res.records == []
    # 300 records at 30 per page is 10 pages, plus at most one more before the
    # budget is observed.
    assert len(session.calls) <= 12, len(session.calls)


def test_reaching_the_budget_is_reported_as_a_coverage_limit():
    """A truncated search that reports itself as complete misleads the review."""
    session = _window_session(3000)
    src = BiorxivSource(session=session)
    src.MAX_SCANNED = 300
    q = SearchQuery(blocks=[["nothing will match this"]], years=(2018, 2024))
    res = src.search(q, max_results=50)
    notes = res.event.notes
    assert "scan budget" in notes
    assert "COVERAGE LIMIT" in notes
    assert "not exhaustive" in notes
    assert "3,000" in notes or "3000" in notes


def test_the_budget_can_be_removed_deliberately():
    session = _window_session(300)
    src = BiorxivSource(session=session)
    src.MAX_SCANNED = 60
    q = SearchQuery(blocks=[["nothing will match this"]], years=(2018, 2024))
    res = src.search(q, max_results=50, max_scanned=None)
    assert "scan budget" not in res.event.notes
    assert len(session.calls) >= 10          # the whole window was enumerated


def test_a_window_smaller_than_the_budget_is_not_flagged():
    """The warning must mean something, so it may not fire on a complete search."""
    session = _window_session(60)
    src = BiorxivSource(session=session)
    src.MAX_SCANNED = 5000
    q = SearchQuery(blocks=[["nothing will match this"]], years=(2020, 2020))
    res = src.search(q, max_results=50)
    assert "scan budget" not in res.event.notes
    assert "COVERAGE LIMIT" not in res.event.notes


def test_estimate_cost_answers_before_the_search_is_paid_for():
    """One cheap request makes the trade-off visible instead of a surprise."""
    session = _window_session(30, total=335871)
    src = BiorxivSource(session=session)
    est = src.estimate_cost(SearchQuery(blocks=[["x"]], years=(2018, 2024)))
    assert est["records_in_window"] == 335871
    assert est["requests_for_exhaustive_search"] == -(-335871 // src.PAGE)
    assert est["seconds_estimate"] > 3600, "a five-hour crawl must read as hours"
    assert 0 < est["coverage_at_default"] < 5
    assert len(session.calls) == 1, "estimating must not itself crawl"
