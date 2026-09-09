"""Offline tests for the arXiv Atom client."""
import pytest

from conftest import FakeResponse, FakeSession

from corpusslr import SearchQuery
from corpusslr.sources.arxiv import (ArxivSource, parse_arxiv_atom,
                                     parse_arxiv_atom_file)
from corpusslr.sources.base import SourceError

FEED_HEAD = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
  <opensearch:totalResults>1234</opensearch:totalResults>
"""
FEED_TAIL = "</feed>\n"

ENTRY = """
  <entry>
    <id>http://arxiv.org/abs/2401.01234v2</id>
    <updated>2024-02-01T00:00:00Z</updated>
    <published>2024-01-02T18:00:00Z</published>
    <title>Uczenie   maszynowe
      w praktyce</title>
    <summary>  Streszczenie
      wieloliniowe.  </summary>
    <author><name>Jan Kowalski</name></author>
    <author><name>Anna Nowak-Zielińska</name></author>
    <arxiv:doi>10.1000/ARXIV.TEST</arxiv:doi>
    <arxiv:journal_ref>J. Test 12 (2024) 1-9</arxiv:journal_ref>
    <arxiv:comment>9 pages</arxiv:comment>
    <link href="http://arxiv.org/abs/2401.01234v2" rel="alternate" type="text/html"/>
    <link title="pdf" href="http://arxiv.org/pdf/2401.01234v2" rel="related"/>
    <category term="cs.LG" scheme="http://arxiv.org/schemas/atom"/>
    <arxiv:primary_category term="cs.AI" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
"""

MINIMAL_ENTRY = """
  <entry>
    <id>http://arxiv.org/abs/0704.0001v1</id>
    <title>Bare</title>
    <summary>S</summary>
  </entry>
"""


def _feed(*entries):
    return FEED_HEAD + "".join(entries) + FEED_TAIL


def _query():
    return SearchQuery(blocks=[["neural network"], ["review"]])


# ----------------------------------------------------------------- parsing
def test_parse_full_entry():
    recs = parse_arxiv_atom(_feed(ENTRY))
    assert len(recs) == 1
    r = recs[0]
    assert r.source == "arXiv"
    assert r.source_id == "2401.01234v2"
    assert r.doc_type == "preprint"
    assert r.doi == "10.1000/arxiv.test"
    assert r.year == 2024
    assert r.journal == "J. Test 12 (2024) 1-9"
    assert r.open_access is True
    assert r.url == "http://arxiv.org/abs/2401.01234v2"
    assert r.authors == ["Kowalski, Jan", "Nowak-Zielińska, Anna"]
    # whitespace inside titles/summaries is collapsed
    assert r.title == "Uczenie maszynowe w praktyce"
    assert r.abstract == "Streszczenie wieloliniowe."
    # the primary category is promoted to the front of the keyword list
    assert r.keywords[0] == "cs.AI"
    assert "cs.LG" in r.keywords
    assert r.raw["comment"] == "9 pages"


def test_parse_entry_without_optional_fields():
    r = parse_arxiv_atom(_feed(MINIMAL_ENTRY))[0]
    assert r.doi == "" and r.journal == "" and r.authors == []
    assert r.year is None
    assert r.keywords == []
    assert r.source_id == "0704.0001v1"
    assert r.url == "http://arxiv.org/abs/0704.0001v1"


def test_parse_empty_feed_and_blank_input():
    assert parse_arxiv_atom(_feed()) == []
    assert parse_arxiv_atom("") == []
    assert parse_arxiv_atom("   ") == []


def test_parse_malformed_xml_raises():
    with pytest.raises(SourceError):
        parse_arxiv_atom("<feed><entry></feed>")


def test_namespaces_are_required_not_guessed():
    """An entry outside the Atom namespace must not be silently parsed."""
    bogus = "<feed><entry><id>x</id><title>T</title></entry></feed>"
    assert parse_arxiv_atom(bogus) == []


def test_entry_without_id_yields_empty_source_id():
    entry = """
  <entry><title>No identifier</title><summary>S</summary></entry>
"""
    r = parse_arxiv_atom(_feed(entry))[0]
    assert r.source_id == "" and r.url == ""
    assert r.doc_type == "preprint"


def test_totalresults_absent_is_reported_as_none():
    feed = ('<feed xmlns="http://www.w3.org/2005/Atom">'
            '<entry><id>http://arxiv.org/abs/1</id><title>T</title>'
            '<summary>S</summary></entry></feed>')
    from conftest import FakeResponse as FR
    src = ArxivSource(session=FakeSession(FR(text=feed)))
    assert "totalResults=None" in src.search(_query()).event.notes


def test_parse_from_file(tmp_path):
    p = tmp_path / "feed.xml"
    p.write_text(_feed(ENTRY), encoding="utf-8")
    assert len(parse_arxiv_atom_file(str(p))) == 1


# ------------------------------------------------------------------ search
def test_min_interval_respects_api_terms():
    assert ArxivSource.min_interval >= 3.0


def test_search_single_short_page_stops():
    sess = FakeSession(FakeResponse(text=_feed(ENTRY)))
    src = ArxivSource(session=sess)
    res = src.search(_query(), max_results=100)
    assert len(res.records) == 1
    assert len(sess.calls) == 1
    assert sess.calls[0]["params"]["start"] == 0
    assert sess.calls[0]["params"]["search_query"] == \
        '(all:"neural network") AND (all:"review")'


def test_search_pages_until_short_page():
    full = _feed(*([ENTRY] * 100))
    sess = FakeSession([FakeResponse(text=full),
                        FakeResponse(text=_feed(ENTRY, ENTRY))])
    res = ArxivSource(session=sess).search(_query(), max_results=1000)
    assert len(res.records) == 102
    assert sess.calls[1]["params"]["start"] == 100


def test_search_empty_feed_returns_nothing():
    res = ArxivSource(session=FakeSession(FakeResponse(text=_feed()))).search(
        _query())
    assert res.records == []
    assert "totalResults=1234" in res.event.notes


def test_client_side_year_filter_and_note():
    old = ENTRY.replace("2024-01-02T18:00:00Z", "2005-01-02T18:00:00Z")
    sess = FakeSession(FakeResponse(text=_feed(ENTRY, old)))
    q = SearchQuery(blocks=[["x"]], years=(2020, 2026))
    res = ArxivSource(session=sess).search(q, max_results=50)
    assert len(res.records) == 1
    assert res.records[0].year == 2024
    assert "client-side" in res.event.filters
    assert "1 record(s) removed" in res.event.notes


def test_records_with_unknown_year_survive_the_filter():
    sess = FakeSession(FakeResponse(text=_feed(MINIMAL_ENTRY)))
    q = SearchQuery(blocks=[["x"]], years=(2020, 2026))
    assert len(ArxivSource(session=sess).search(q).records) == 1


def test_event_flags_preprint_status_and_limits():
    ev = ArxivSource(session=FakeSession(
        FakeResponse(text=_feed(ENTRY)))).search(_query()).event
    assert ev.database == "arXiv"
    assert "preprint" in ev.notes
    assert "PRISMA 2020" in ev.notes
    assert "min_interval=3.0" in ev.notes
    assert ev.url.startswith("http://export.arxiv.org")


def test_malformed_feed_from_search_raises():
    src = ArxivSource(session=FakeSession(
        FakeResponse(status_code=200, text="<feed><entry></feed>")))
    with pytest.raises(SourceError):
        src.search(_query())


def test_http_error_propagates():
    src = ArxivSource(session=FakeSession(
        FakeResponse(status_code=400, text="bad")))
    with pytest.raises(SourceError):
        src.search(_query())


def test_server_error_is_retried():
    sess = FakeSession([FakeResponse(status_code=503, text="down"),
                        FakeResponse(text=_feed(ENTRY))])
    assert len(ArxivSource(session=sess).search(_query()).records) == 1


# ------------------------------------------------------------------- query
def test_to_arxiv_title_only_and_warnings():
    q = SearchQuery(blocks=[["deep learning", "neural nets"], ["survey"]],
                    title_only=True, years=(2020, 2024),
                    doc_types=["article"], languages=["en"])
    s = q.to_arxiv()
    assert s == ('(ti:"deep learning" OR ti:"neural nets") AND (ti:"survey")')
    joined = " ".join(q.warnings)
    assert "document-type" in joined and "language" in joined
    assert "client-side" in joined


def test_to_arxiv_skips_empty_blocks_and_terms():
    q = SearchQuery(blocks=[["a", "", "  "], [], ["b"]])
    assert q.to_arxiv() == '(all:"a") AND (all:"b")'


def test_to_arxiv_no_blocks():
    assert SearchQuery(blocks=[]).to_arxiv() == ""
