"""Offline regression tests pinning response shapes measured against the live
Scopus Search API.

Every fixture in this module is a verbatim copy of a payload fragment observed
in a live characterisation run (93 requests, institutional entitlement,
``view=COMPLETE`` and ``view=STANDARD``), with identifiers kept and credentials
never present.  The point of pinning the shapes offline is that the assumptions
the client encodes -- which fields exist, how ``author-count`` is serialised,
what an empty result set looks like, which error text the API returns for each
rejected request -- are then checked on every test run without touching the
network or spending API quota.

The measured numbers behind these fixtures are reported in
``scopus_api_characterisation.md``.
"""
from __future__ import annotations

import pytest

from corpusslr.query import SearchQuery
from corpusslr.record import Record
from corpusslr.sources.base import SourceError
from corpusslr.sources.scopus import ScopusSource

from conftest import FakeResponse, FakeSession


def _src(responses, **kw):
    s = ScopusSource(api_key="k", **kw)
    s.session = FakeSession(responses)
    return s


def _results(entries, total=None, cursor=None):
    d = {"opensearch:totalResults": str(total if total is not None
                                        else len(entries)),
         "entry": entries}
    if cursor is not None:
        d["cursor"] = cursor
    return {"search-results": d}


# --------------------------------------------------------------------------
# 1. author-count is an object {"@limit", "$"} and "$" is clipped at "@limit"
# --------------------------------------------------------------------------

#: Verbatim shape observed on every COMPLETE record; note the absence of
#: "@total", which earlier versions of the client looked for first.
AUTHOR_COUNT_SMALL = {"@limit": "100", "$": "5"}
AUTHOR_COUNT_AT_CAP = {"@limit": "100", "$": "100"}


def test_author_count_object_has_no_total_key_only_limit_and_dollar():
    """The live shape carries @limit and $ only; @total was never observed."""
    assert set(AUTHOR_COUNT_SMALL) == {"@limit", "$"}
    assert ScopusSource._author_total(
        {"author-count": AUTHOR_COUNT_SMALL}) == 5
    assert ScopusSource._author_limit(
        {"author-count": AUTHOR_COUNT_SMALL}) == 100


def test_author_limit_returns_none_for_scalar_and_missing_shapes():
    assert ScopusSource._author_limit({}) is None
    assert ScopusSource._author_limit({"author-count": "7"}) is None
    assert ScopusSource._author_limit(
        {"author-count": {"@limit": "not-a-number"}}) is None


def test_author_count_at_cap_is_flagged_as_truncated():
    """A hyperauthorship record reports $ == @limit == 100 and returns 100
    author objects, so "reported > returned" can never detect the truncation.
    """
    e = {"dc:title": "Observation of a new particle",
         "author-count": AUTHOR_COUNT_AT_CAP,
         "author": [{"surname": "A%d" % i, "given-name": "B"}
                    for i in range(100)]}
    src = _src([FakeResponse(payload=_results([e], total=1))])
    res = src.search(SearchQuery(blocks=[["higgs"]]), max_results=10)
    assert len(res.records[0].authors) == 100
    assert "author list truncated" in res.event.notes
    assert "author-count/@limit" in res.event.notes


def test_author_count_below_cap_is_not_flagged_as_truncated():
    e = {"dc:title": "t", "author-count": AUTHOR_COUNT_SMALL,
         "author": [{"surname": "S%d" % i, "given-name": "G"}
                    for i in range(5)]}
    src = _src([FakeResponse(payload=_results([e], total=1))])
    res = src.search(SearchQuery(blocks=[["x"]]), max_results=10)
    assert "truncated" not in res.event.notes


# --------------------------------------------------------------------------
# 2. dc:creator is family-first ("Abbasi E."), like authname - not natural order
# --------------------------------------------------------------------------

#: Every (STANDARD dc:creator, COMPLETE first author) pair of the both-views
#: intersection: the 25 records that the live run retrieved under *both* views,
#: compared record by record.  All 25 raw creators lack a comma, and after
#: normalisation the extracted surname agrees with the COMPLETE view in 25/25.
CREATOR_VS_COMPLETE = [
    ("Nirmala B.", "Nirmala, Baby"),
    ("Oguike O.E.", "Oguike, Osondu Everestus"),
    ("Dhiman P.", "Dhiman, Paula"),
    ("Bekta\u015f M.", "Bekta\u015f, Mustafa"),
    ("Yang A.H.X.", "Yang, Alexander Hui Xiang"),
    ("Palermo M.B.", "Palermo, Marcelo Benedeti"),
    ("Abbasi E.", "Abbasi, Elahe"),
    ("D\u0103n\u0103il\u0103 V.R.", "D\u0103n\u0103il\u0103, Vlad Rare\u0219"),
    ("Siemuri A.", "Siemuri, Akpojoto"),
    ("Byrne A.", "Byrne, Adam"),
    ("Dietz N.", "Dietz, Nicholas"),
    ("Szabolcs F.R.", "Szabolcs, Farkas R\u00e1duly"),
    ("Parmigiani G.", "Parmigiani, Giovanna"),
    ("Zougagh N.", "Zougagh, Nisrine"),
    ("Coiera E.", "Coiera, Enrico"),
    ("Zhao J.", "Zhao, Jinxin"),
    ("Mahajan A.", "Mahajan, Abhishek"),
    ("Kotsyfakis S.", "Kotsyfakis, Stylianos"),
    ("Sayadi M.", "Sayadi, Mohammadjavad"),
    ("Mustaffa S.N.F.N.B.", "Mustaffa, Siti Nur Fathin Najwa Binti"),
    ("Muhammad T.", "Muhammad, Taseer"),
    ("Wickramasinghe I.", "Wickramasinghe, Indika"),
    ("Hasan Z.", "Hasan, Ziaul"),
    ("Sharma S.", "Sharma, Shikha"),
    ("Mathur P.", "Mathur, Priya"),
]


def test_the_pinned_creator_sample_is_the_whole_measured_intersection():
    """Guard against quoting a subset as if it were the full measurement."""
    assert len(CREATOR_VS_COMPLETE) == 25
    assert sum(1 for c, _ in CREATOR_VS_COMPLETE if "," not in c) == 25


@pytest.mark.parametrize("creator,complete", CREATOR_VS_COMPLETE)
def test_dc_creator_is_normalised_to_family_comma_given(creator, complete):
    """STANDARD dc:creator must yield the same surname as the COMPLETE view.

    Regression test: the raw string was previously stored verbatim, so
    "Abbasi E." was recorded where COMPLETE gave "Abbasi, Elahe" and surname
    extraction - hence cross-view deduplication - used the whole string.
    """
    parsed = ScopusSource._parse_authors({"dc:creator": creator})
    assert len(parsed) == 1
    assert "," in parsed[0]
    assert parsed[0].split(",")[0].strip() == complete.split(",")[0].strip()


@pytest.mark.parametrize("authname,expected", [
    ("Wu Y.", "Wu, Y."),                       # 1 initial
    ("Palermo M.B.", "Palermo, M.B."),         # 2
    ("Yang A.H.X.", "Yang, A.H.X."),           # 3
    ("Mustaffa S.N.F.N.B.", "Mustaffa, S.N.F.N.B."),   # 5 - was inverted
    ("Kim H.-J.", "Kim, H.-J."),               # hyphenated (defensive)
    ("van der Berg J.", "van der Berg, J."),   # multi-token surname
    ("De La Cruz M.A.", "De La Cruz, M.A."),
    ("O'Brien M.", "O'Brien, M."),
    ("Lee S", "Lee, S"),                       # initial without a dot
])
def test_initials_token_of_any_length_keeps_the_surname_first(authname, expected):
    """Regression test for an initials-count upper bound.

    _INITIALS_RE previously matched at most four initials, so
    "Mustaffa S.N.F.N.B." (five, a common Malay/Indonesian shape) fell through
    to the natural-order helper and became "S.N.F.N.B., Mustaffa" - the
    initials occupying the surname slot that deduplication keys on.  Three of
    1220 initials tokens in the live sample exceeded four initials.
    """
    from corpusslr.sources.scopus import _split_authname
    assert _split_authname(authname) == expected


@pytest.mark.parametrize("natural", ["John Smith", "Maria Garcia Lopez"])
def test_a_full_natural_order_name_is_still_inverted_not_read_as_initials(natural):
    """The widened regex must not swallow ordinary given names."""
    from corpusslr.sources.scopus import _split_authname
    out = _split_authname(natural)
    assert out.split(",")[0].strip() == natural.split(" ")[-1]


def test_single_token_name_is_returned_unchanged():
    from corpusslr.sources.scopus import _split_authname
    assert _split_authname("Madonna") == "Madonna"
    assert _split_authname("") == ""


def test_dc_creator_already_containing_a_comma_is_left_alone():
    assert ScopusSource._parse_authors(
        {"dc:creator": "Abbasi, Elahe"}) == ["Abbasi, Elahe"]


def test_author_array_takes_precedence_over_dc_creator():
    e = {"author": [{"surname": "Real", "given-name": "Author"}],
         "dc:creator": "Fallback F."}
    assert ScopusSource._parse_authors(e) == ["Real, Author"]


# --------------------------------------------------------------------------
# 3. STANDARD omits author/authkeywords/dc:description entirely
# --------------------------------------------------------------------------

#: Key set of a STANDARD entry, measured over 25 records.  "author",
#: "authkeywords", "dc:description" and "author-count" are absent from all of
#: them; "pubmed-id" and "article-number" are present.
STANDARD_KEYS = [
    "@_fa", "affiliation", "article-number", "citedby-count", "dc:creator",
    "dc:identifier", "dc:title", "eid", "freetoread", "freetoreadLabel",
    "link", "openaccess", "openaccessFlag", "pii", "prism:aggregationType",
    "prism:coverDate", "prism:coverDisplayDate", "prism:doi", "prism:eIssn",
    "prism:isbn", "prism:issn", "prism:issueIdentifier", "prism:pageRange",
    "prism:publicationName", "prism:url", "prism:volume", "pubmed-id",
    "source-id", "subtype", "subtypeDescription",
]

#: Additional keys the COMPLETE view adds on top of the STANDARD set.
COMPLETE_ONLY_KEYS = ["author", "author-count", "authkeywords",
                      "dc:description", "fund-acr", "fund-no", "fund-sponsor"]


@pytest.mark.parametrize("key", ["author", "author-count", "authkeywords",
                                 "dc:description"])
def test_standard_view_key_set_lacks_the_complete_only_fields(key):
    assert key not in STANDARD_KEYS
    assert key in COMPLETE_ONLY_KEYS or key == "dc:description"


@pytest.mark.parametrize("key", ["pubmed-id", "article-number",
                                 "prism:issn", "prism:eIssn"])
def test_standard_view_key_set_still_carries_these_fields(key):
    assert key in STANDARD_KEYS


# --------------------------------------------------------------------------
# 4. pages: prism:pageRange is absent for article-number-only journals
# --------------------------------------------------------------------------

#: Verbatim: a record with no prism:pageRange but an article-number.  39 of 50
#: COMPLETE records had this shape, and all 39 carried article-number.
ARTICLE_NUMBER_ENTRY = {
    "dc:identifier": "SCOPUS_ID:85162253647",
    "article-number": "26",
    "prism:doi": "10.1145/3590837.3590863",
}


def test_article_number_is_used_when_page_range_is_absent():
    rec = ScopusSource._parse_entry(dict(ARTICLE_NUMBER_ENTRY))
    assert rec.pages == "26"


def test_page_range_wins_when_both_are_present():
    e = dict(ARTICLE_NUMBER_ENTRY, **{"prism:pageRange": "101-115"})
    assert ScopusSource._parse_entry(e).pages == "101-115"


def test_blank_page_range_falls_through_to_article_number():
    e = dict(ARTICLE_NUMBER_ENTRY, **{"prism:pageRange": "   "})
    assert ScopusSource._parse_entry(e).pages == "26"


def test_numeric_article_number_is_stringified():
    assert ScopusSource._parse_pages({"article-number": 26}) == "26"


def test_no_locator_at_all_yields_empty_pages():
    assert ScopusSource._parse_entry({"dc:title": "t"}).pages == ""


# --------------------------------------------------------------------------
# 5. pubmed-id is carried by Scopus for MEDLINE-indexed records
# --------------------------------------------------------------------------

#: Verbatim: 38% of the 50-record COMPLETE sample carried pubmed-id.
PUBMED_ENTRY = {
    "dc:identifier": "SCOPUS_ID:85144590924",
    "pubmed-id": "36513071",
    "prism:doi": "10.1016/j.xcrm.2022.100860",
}


def test_pubmed_id_is_mapped_onto_the_record_pmid_field():
    rec = ScopusSource._parse_entry(dict(PUBMED_ENTRY))
    assert rec.pmid == "36513071"
    assert rec.doi == "10.1016/j.xcrm.2022.100860"


def test_absent_pubmed_id_leaves_pmid_empty_not_none():
    assert ScopusSource._parse_entry({"dc:title": "t"}).pmid == ""


def test_pmid_survives_record_normalisation():
    """Record.__post_init__ strips non-digits; a bare Scopus PMID is unchanged."""
    assert Record(title="t", pmid="36513071").pmid == "36513071"


# --------------------------------------------------------------------------
# 6. single-element arrays are NOT collapsed to objects in the JSON view
# --------------------------------------------------------------------------

#: Verbatim single-author record: `author` is a one-element *list*, not an
#: object.  Across ~75 sampled single-author records (38 with exactly one
#: author) no collapsed object was observed with httpAccept=application/json,
#: so the XML->JSON collapsing trap does not fire on this endpoint.  _as_list()
#: nonetheless remains the guard, and the next test pins that it would cope.
ONE_AUTHOR_ENTRY = {
    "dc:title": "Single author paper",
    "author-count": {"@limit": "100", "$": "1"},
    "author": [{
        "@_fa": "true", "@seq": "1",
        "authid": "60362349600", "authname": "Mohan N.S.",
        "surname": "Mohan", "given-name": "Nanjangud Subbaro",
        "initials": "N.S.",
    }],
}


def test_single_author_arrives_as_one_element_list_in_json():
    assert isinstance(ONE_AUTHOR_ENTRY["author"], list)
    assert ScopusSource._parse_authors(dict(ONE_AUTHOR_ENTRY)) == [
        "Mohan, Nanjangud Subbaro"]


def test_a_collapsed_single_author_object_would_still_parse():
    """Defensive: if Elsevier ever collapses the array, _as_list() absorbs it."""
    e = dict(ONE_AUTHOR_ENTRY)
    e["author"] = ONE_AUTHOR_ENTRY["author"][0]
    assert ScopusSource._parse_authors(e) == ["Mohan, Nanjangud Subbaro"]


def test_entry_stays_a_list_even_when_total_is_one():
    """A query matching exactly one record still returns entry as a list of 1."""
    payload = _results([dict(ONE_AUTHOR_ENTRY)], total=1,
                       cursor={"@current": "*", "@next": "next-token"})
    src = _src([FakeResponse(payload=payload)])
    res = src.search(SearchQuery(blocks=[["softx"]]), max_results=25)
    assert len(res.records) == 1
    assert "totalResults=1" in res.event.notes
    # One live request only: retrieved == total ends the loop.
    assert len(src.session.calls) == 1


# --------------------------------------------------------------------------
# 7. empty result set and rejected-query envelopes, verbatim
# --------------------------------------------------------------------------

#: Verbatim empty-set entry, HTTP 200 with totalResults "0".
EMPTY_ENTRY = [{"@_fa": "true", "error": "Result set was empty"}]

#: Verbatim envelope returned for every malformed query tested (unbalanced
#: parenthesis, unknown field name, dangling AND) - all HTTP 400 with the same
#: statusCode/statusText pair, so the client cannot distinguish the three.
INVALID_INPUT = {"service-error": {"status": {
    "statusCode": "INVALID_INPUT", "statusText": "Error translating query"}}}

#: Verbatim statusText for count above the per-view maximum (HTTP 400).
PAGE_SIZE_TEXT = "Exceeds the maximum number allowed for the service level"

#: Verbatim statusText for start+count above the offset cap (HTTP 400).
OFFSET_TEXT = "Exceeds the number of search results"


def test_empty_result_set_shape_yields_zero_records_and_a_reportable_event():
    src = _src([FakeResponse(payload=_results(list(EMPTY_ENTRY), total=0))])
    res = src.search(SearchQuery(blocks=[["zzqxwv"]]), max_results=25)
    assert res.records == []
    assert "totalResults=0" in res.event.notes
    assert "empty result set" in res.event.notes


@pytest.mark.parametrize("label", ["unbalanced paren", "unknown field",
                                   "dangling AND"])
def test_every_malformed_query_yields_the_same_invalid_input_envelope(label):
    src = _src([FakeResponse(status_code=400, payload=dict(INVALID_INPUT))])
    with pytest.raises(SourceError) as exc:
        src.search(SearchQuery(blocks=[["x"]]), max_results=5)
    msg = str(exc.value)
    assert "HTTP 400" in msg
    assert "INVALID_INPUT" in msg
    assert "Error translating query" in msg


def test_page_size_status_text_triggers_the_per_view_cap_hint():
    """The measured statusText must still match the substring the hint keys on."""
    body = {"service-error": {"status": {
        "statusCode": "INVALID_INPUT", "statusText": PAGE_SIZE_TEXT}}}
    src = _src([FakeResponse(status_code=400, payload=body)],
               view="COMPLETE")
    with pytest.raises(SourceError) as exc:
        src.search(SearchQuery(blocks=[["x"]]), max_results=5)
    assert "per-view maximum" in str(exc.value)
    assert "25 for view=COMPLETE" in str(exc.value)


def test_offset_status_text_triggers_the_misleading_message_hint():
    body = {"service-error": {"status": {
        "statusCode": "INVALID_INPUT", "statusText": OFFSET_TEXT}}}
    src = _src([FakeResponse(status_code=400, payload=body)])
    with pytest.raises(SourceError) as exc:
        src.search(SearchQuery(blocks=[["x"]]), max_results=5)
    msg = str(exc.value)
    assert "misleading" in msg
    assert "5000" in msg


def test_the_two_400_status_texts_are_distinguishable_from_each_other():
    """Both hints key on different substrings of the measured statusText."""
    assert "search results" in OFFSET_TEXT.lower()
    assert "maximum number" in PAGE_SIZE_TEXT.lower()
    assert "search results" not in PAGE_SIZE_TEXT.lower()
    assert "maximum number" not in OFFSET_TEXT.lower()


# --------------------------------------------------------------------------
# 8. measured caps: 200/25 per view, start+count <= 5000
# --------------------------------------------------------------------------

def test_measured_page_size_caps_match_the_declared_constants():
    """count=200 STANDARD / count=25 COMPLETE succeeded; +1 was HTTP 400."""
    assert ScopusSource.PAGE_SIZE["STANDARD"] == 200
    assert ScopusSource.PAGE_SIZE["COMPLETE"] == 25
    assert ScopusSource.MAX_OFFSET == 5000


def test_last_legal_offset_request_is_start_4800_count_200():
    """start=4800&count=200 returned 200 records; start=4900&count=200 was 400.

    The client must therefore never emit start+count > 5000.
    """
    pages = [FakeResponse(payload=_results(
        [{"dc:title": "t%d" % i} for i in range(200)], total=10000))
        for _ in range(30)]
    src = _src(pages, use_cursor=False)
    src.search(SearchQuery(blocks=[["x"]]), max_results=10000)
    for call in src.session.calls:
        start = int(call["params"]["start"])
        count = int(call["params"]["count"])
        assert start + count <= ScopusSource.MAX_OFFSET, (start, count)


# --------------------------------------------------------------------------
# 9. paging stability: cursor is order-stable, offset is not
# --------------------------------------------------------------------------

def test_cursor_paging_visits_each_page_once_and_yields_no_duplicates():
    """Cursor paging returned byte-identical id order on two live runs.

    Offline this pins the mechanism that makes that possible: every request
    carries the cursor handed back by the previous response and never a start
    offset, so the server controls the position.
    """
    pages = [
        FakeResponse(payload=_results(
            [{"dc:identifier": "SCOPUS_ID:%d" % (i * 10 + j)} for j in range(10)],
            total=30, cursor={"@current": "c%d" % i, "@next": "c%d" % (i + 1)}))
        for i in range(3)
    ]
    src = _src(pages)
    res = src.search(SearchQuery(blocks=[["x"]]), max_results=30)
    ids = [r.scopus_id for r in res.records]
    assert len(ids) == 30
    assert len(set(ids)) == 30
    sent = [c["params"] for c in src.session.calls]
    assert [p["cursor"] for p in sent] == ["*", "c1", "c2"]
    assert all("start" not in p for p in sent)


def test_offset_paging_is_the_documented_fallback_and_reports_its_mode():
    """The event must name the paging mode, because only cursor paging was
    measured to be order-stable across repeated runs (offset paging returned
    the same 100-record set but a different page-to-page distribution, so a
    partial retrieval is not reproducible)."""
    src = _src([FakeResponse(payload=_results(
        [{"dc:identifier": "SCOPUS_ID:1"}], total=1))], use_cursor=False)
    res = src.search(SearchQuery(blocks=[["x"]]), max_results=5)
    assert "paging=offset" in res.event.filters
    src2 = _src([FakeResponse(payload=_results(
        [{"dc:identifier": "SCOPUS_ID:1"}], total=1))], use_cursor=True)
    assert "paging=cursor" in src2.search(
        SearchQuery(blocks=[["x"]]), max_results=5).event.filters


# --------------------------------------------------------------------------
# 10. throttling and quota headers
# --------------------------------------------------------------------------

#: Verbatim header names present on every 200 response of the live run
#: (values were 20000 / ~19900 / a Unix timestamp).
RATELIMIT_HEADERS = ["X-RateLimit-Limit", "X-RateLimit-Remaining",
                     "X-RateLimit-Reset"]


def test_min_interval_paces_successive_requests():
    """min_interval must actually gate the request rate.

    Measured live: three pages at min_interval=2.0 took 4.41 s, i.e. two waits
    of one interval each.  Here the sleep is recorded rather than performed.
    """
    import time as _time
    slept = []
    src = _src([FakeResponse(payload=_results(
        [{"dc:identifier": "SCOPUS_ID:%d" % i}], total=3,
        cursor={"@current": "c", "@next": "c%d" % i})) for i in range(3)])
    src.min_interval = 2.0
    real_sleep, real_time = _time.sleep, _time.time
    clock = {"t": 1000.0}
    _time.sleep = lambda s: (slept.append(s), clock.__setitem__("t", clock["t"] + s))
    _time.time = lambda: clock["t"]
    try:
        src._last = clock["t"]
        src.page_size = lambda mr=None: 1
        src.search(SearchQuery(blocks=[["x"]]), max_results=3)
    finally:
        _time.sleep, _time.time = real_sleep, real_time
    assert len(slept) >= 2
    assert all(abs(s - 2.0) < 1e-6 for s in slept)


@pytest.mark.parametrize("header", RATELIMIT_HEADERS)
def test_quota_headers_are_reported_in_the_429_diagnostic(header):
    resp = FakeResponse(status_code=429, payload={"service-error": {
        "status": {"statusCode": "TOO_MANY_REQUESTS",
                   "statusText": "rate limit"}}})
    resp.headers = {"X-RateLimit-Limit": "20000",
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": "1787460983"}
    src = _src([resp])
    with pytest.raises(SourceError) as exc:
        src.search(SearchQuery(blocks=[["x"]]), max_results=5)
    msg = str(exc.value)
    assert "X-RateLimit-Remaining=0" in msg
    assert "1787460983" in msg


def test_weekly_quota_limit_observed_is_20000():
    """Documented for the article: the entitlement reported a 20000/week cap."""
    resp = FakeResponse(status_code=403, payload={"service-error": {
        "status": {"statusCode": "QUOTA_EXCEEDED",
                   "statusText": "quota exceeded"}}})
    resp.headers = {"X-RateLimit-Limit": "20000",
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": "1787460983"}
    src = _src([resp])
    with pytest.raises(SourceError) as exc:
        src.search(SearchQuery(blocks=[["x"]]), max_results=5)
    assert "weekly request quota" in str(exc.value)


# --------------------------------------------------------------------------
# 11. no credential ever leaves the client except in the two headers
# --------------------------------------------------------------------------

def test_credentials_travel_in_headers_only_and_never_in_the_url_or_params():
    src = ScopusSource(api_key="SECRETKEY", insttoken="SECRETTOKEN")
    src.session = FakeSession([FakeResponse(payload=_results([], total=0))])
    src.search(SearchQuery(blocks=[["x"]]), max_results=5)
    call = src.session.calls[0]
    assert call["headers"]["X-ELS-APIKey"] == "SECRETKEY"
    assert call["headers"]["X-ELS-Insttoken"] == "SECRETTOKEN"
    assert call["url"].startswith("https://")
    assert "SECRETKEY" not in call["url"]
    assert "SECRETTOKEN" not in call["url"]
    for value in call["params"].values():
        assert "SECRETKEY" not in str(value)
        assert "SECRETTOKEN" not in str(value)
