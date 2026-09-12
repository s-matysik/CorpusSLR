"""Web of Science Expanded API client.

Every fixture below is the shape of a real response, captured from the live
service on 2026-09-07 with an entitled institutional key. The single-author
record is not hypothetical: WOS:001155884300001 (Akhtar, Salman) returns
``names.name`` as a dict rather than a list, and treating that dict as a list
yields its keys as "authors" -- the most common way to get this API wrong.
"""
import pytest

from conftest import FakeResponse, FakeSession
from corpusslr import SearchQuery
from corpusslr.sources.base import SourceError
from corpusslr.sources.wos_expanded import (MAX_COUNT, WosExpandedSource,
                                            parse_wos_expanded_record)

_Q = SearchQuery(blocks=[["deep learning"]], years=(2020, 2024))


def _rec(names, doctype="Article", with_abstract=True, doi="10.5001/x", uid="WOS:0001"):
    rec = {
        "UID": uid,
        "static_data": {
            "summary": {
                "pub_info": {"pubyear": 2024, "vol": 12, "issue": 3,
                             "pubtype": "Journal",
                             "page": {"begin": 17, "end": 23, "content": "17-23"}},
                "titles": {"title": [
                    {"type": "source", "content": "Journal of Testing"},
                    {"type": "item", "content": "A study of things"}]},
                "names": {"name": names},
                "doctypes": {"doctype": doctype},
            },
            "fullrecord_metadata": {
                "keywords": {"keyword": ["alpha", "beta"]},
            },
        },
        "dynamic_data": {"cluster_related": {"identifiers": {"identifier": [
            {"type": "doi", "value": doi},
            {"type": "issn", "value": "1234-5678"}]}}},
    }
    if with_abstract:
        rec["static_data"]["fullrecord_metadata"]["abstracts"] = {
            "abstract": {"abstract_text": {"p": "We measured the thing."}}}
    return rec


def _payload(records, found=None):
    records = records if isinstance(records, list) else [records]
    return {"QueryResult": {"RecordsFound": found if found is not None else len(records),
                            "RecordsSearched": 100},
            "Data": {"Records": {"records": {"REC": records}}}}


def _source(responses, **kw):
    kw.setdefault("min_interval", 0.0)
    return WosExpandedSource(api_key="KEY", session=FakeSession(responses), **kw)


# ------------------------------------------------------------------ parsing
def test_a_single_author_record_yields_one_author_not_its_field_names():
    """names.name is a dict when there is one author and a list when there are
    several. This is the shape that silently produces garbage author lists."""
    rec = _rec({"seq_no": 1, "role": "author", "full_name": "Akhtar, Salman",
                "last_name": "Akhtar"})
    r = parse_wos_expanded_record(rec)
    assert r.authors == ["Akhtar, Salman"]


def test_a_multi_author_record_keeps_every_author():
    rec = _rec([{"seq_no": i, "role": "author", "full_name": "Smith, A{}".format(i)}
                for i in range(1, 14)])
    assert len(parse_wos_expanded_record(rec).authors) == 13


def test_non_author_contributors_are_excluded():
    rec = _rec([{"seq_no": 1, "role": "author", "full_name": "Real, A"},
                {"seq_no": 2, "role": "book_editor", "full_name": "Editor, B"}])
    assert parse_wos_expanded_record(rec).authors == ["Real, A"]


def test_the_item_title_is_the_document_and_the_source_title_is_the_venue():
    """Picking the wrong one puts the journal name in the title field, which
    then matches every other paper in that journal during deduplication."""
    r = parse_wos_expanded_record(_rec({"role": "author", "full_name": "A, B"}))
    assert r.title == "A study of things"
    assert r.journal == "Journal of Testing"


def test_identifiers_are_read_by_type_not_position():
    r = parse_wos_expanded_record(_rec({"role": "author", "full_name": "A, B"},
                                       doi="10.5555/zzz"))
    assert r.doi == "10.5555/zzz"
    assert r.issn == "1234-5678"


def test_an_abstract_split_into_paragraphs_is_joined():
    rec = _rec({"role": "author", "full_name": "A, B"}, with_abstract=False)
    rec["static_data"]["fullrecord_metadata"]["abstracts"] = {
        "abstract": {"abstract_text": {"p": ["First part.", "Second part."]}}}
    assert parse_wos_expanded_record(rec).abstract == "First part.\n\nSecond part."


def test_a_record_without_an_abstract_gives_an_empty_string_not_a_crash():
    rec = _rec({"role": "author", "full_name": "A, B"}, with_abstract=False)
    assert parse_wos_expanded_record(rec).abstract == ""


@pytest.mark.parametrize("doctype,expected", [
    ("Article", "article"),
    ("Review", "review"),
    (["Article", "Proceedings Paper"], "conference"),
    (["Article", "Review"], "review"),
    ("Book Review", "editorial"),
])
def test_document_types_match_the_starter_clients_vocabulary(doctype, expected):
    """The two WoS clients must not disagree about what a record is: a
    conference paper read through Expanded has to deduplicate against the same
    paper read through Starter."""
    rec = _rec({"role": "author", "full_name": "A, B"}, doctype=doctype)
    assert parse_wos_expanded_record(rec).doc_type == expected


# ------------------------------------------------------------------- paging
def test_paging_advances_by_the_number_of_records_actually_returned():
    page1 = _payload([_rec({"role": "author", "full_name": "A, B"},
                           uid="WOS:{:04d}".format(i)) for i in range(100)], found=150)
    page2 = _payload([_rec({"role": "author", "full_name": "A, B"},
                           uid="WOS:{:04d}".format(100 + i)) for i in range(50)], found=150)
    session = FakeSession([FakeResponse(200, payload=page1),
                           FakeResponse(200, payload=page2)])
    res = WosExpandedSource(api_key="K", session=session,
                            min_interval=0.0).search(_Q, max_results=150)
    assert len(res.records) == 150
    assert session.calls[0]["params"]["firstRecord"] == 1
    assert session.calls[1]["params"]["firstRecord"] == 101


def test_count_never_exceeds_the_server_cap():
    session = FakeSession([FakeResponse(200, payload=_payload([], found=0))])
    WosExpandedSource(api_key="K", session=session,
                      min_interval=0.0).search(_Q, max_results=5000)
    assert session.calls[0]["params"]["count"] <= MAX_COUNT


def test_an_empty_page_stops_the_loop():
    """A server that keeps answering 200 with no records must not spin."""
    session = FakeSession(lambda url, params, headers:
                          FakeResponse(200, payload=_payload([], found=9999)))
    res = WosExpandedSource(api_key="K", session=session,
                            min_interval=0.0).search(_Q, max_results=500)
    assert res.records == []
    assert len(session.calls) == 1


def test_the_event_reports_abstract_coverage():
    """Abstract coverage is the difference between a screenable corpus and an
    unscreenable one, so it belongs in the PRISMA-S appendix."""
    recs = [_rec({"role": "author", "full_name": "A, B"}, with_abstract=(i < 3))
            for i in range(4)]
    session = FakeSession([FakeResponse(200, payload=_payload(recs, found=4))])
    res = WosExpandedSource(api_key="K", session=session,
                            min_interval=0.0).search(_Q, max_results=4)
    assert "3/4 records carry an abstract" in res.event.notes


# -------------------------------------------------------------- diagnostics
def test_a_401_naming_a_product_is_diagnosed_as_an_entitlement_gap():
    """Measured live: an unprovisioned account gets this exact body, while an
    invalid key gets a bare 401, so the two must not read alike."""
    body = ('{"code":"Unauthorized","message":"Server.authorization, '
            'Not authorized for product: WWS"}')
    with pytest.raises(SourceError) as exc:
        _source([FakeResponse(401, text=body)]).search(_Q, max_results=10)
    msg = str(exc.value)
    assert "entitlement, not a bad key" in msg
    assert "Customer Care" in msg


def test_a_plain_401_is_diagnosed_as_a_bad_key():
    with pytest.raises(SourceError) as exc:
        _source([FakeResponse(401, text='{"message":"Unauthorized"}')]).search(
            _Q, max_results=10)
    msg = str(exc.value)
    assert "rejected the key itself" in msg
    assert "entitlement, not a bad key" not in msg


def test_a_403_points_at_the_other_api():
    with pytest.raises(SourceError) as exc:
        _source([FakeResponse(403, text='{"message":"You cannot consume this service"}')
                 ]).search(_Q, max_results=10)
    assert "WosStarterSource" in str(exc.value)


def test_the_api_key_travels_in_the_header_not_the_query():
    """Verified live: ?apikey= and Authorization: Bearer are both rejected."""
    session = FakeSession([FakeResponse(200, payload=_payload([], found=0))])
    WosExpandedSource(api_key="SECRET", session=session,
                      min_interval=0.0).search(_Q, max_results=1)
    call = session.calls[0]
    assert call["headers"].get("X-ApiKey") == "SECRET"
    assert "apikey" not in {k.lower() for k in call["params"]}
