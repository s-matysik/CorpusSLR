"""Reproducible harvesting: archive -> replay -> equality, checksums, drift.

Every test is offline: the live sources are driven through FakeSession, and
replay by construction never opens a socket.
"""
import json
import os

import pytest
import requests

from conftest import FakeResponse, FakeSession

from corpusslr import (ARCHIVE_VERSION, CrossrefSource, HarvestArchive,
                       HarvestDiff, HarvestError, HarvestManifest, Record,
                       SearchQuery, SemanticScholarSource, compare_harvests,
                       harvest, harvest_markdown, record_checksum,
                       record_diff_fields, record_fingerprint, record_key,
                       records_checksum, records_equal, redact_params,
                       replay_harvest, request_key, sort_records,
                       verify_archive)
from corpusslr.corpus import Corpus
from corpusslr.harvest import (ArchivedResponse, RecordingSession,
                               ReplaySession, checksum_payload)

QUERY = SearchQuery(blocks=[["artificial intelligence"], ["marketing"]],
                    years=(2020, 2023), doc_types=["article"])


# ---------------------------------------------------------------- fixtures ---
def _cr_item(doi, title, year=2021, cites=3, extra=None):
    it = {"DOI": doi, "title": [title], "type": "journal-article",
          "container-title": ["Journal of Testing"],
          "issued": {"date-parts": [[year, 3, 1]]},
          "author": [{"family": "Kowalski", "given": "Jan"}],
          "ISSN": ["1234-5678"], "volume": "7", "issue": "2",
          "page": "1-20", "language": "en",
          "URL": "https://doi.org/" + doi,
          "is-referenced-by-count": cites,
          "abstract": "<jats:p>An abstract.</jats:p>"}
    if extra:
        it.update(extra)
    return it


def _cr_page(items, total=3, next_cursor=""):
    msg = {"total-results": total, "items": items, "message-version": "1.0.0"}
    if next_cursor:
        msg["next-cursor"] = next_cursor
    return {"status": "ok", "message-version": "1.0.0", "message": msg}


def crossref_responses(pages=None):
    """Two-page cursor harvest, 3 records."""
    if pages is None:
        pages = [
            _cr_page([_cr_item("10.1000/bbb", "Beta study"),
                      _cr_item("10.1000/aaa", "Alpha study")],
                     next_cursor="CUR2"),
            _cr_page([_cr_item("10.1000/ccc", "Gamma study")]),
        ]
    return [FakeResponse(200, p) for p in pages]


def _s2_paper(pid, doi, title, year=2021, cites=5):
    return {"paperId": pid, "externalIds": {"DOI": doi} if doi else {},
            "title": title, "abstract": "An abstract.", "year": year,
            "venue": "Venue of Testing",
            "authors": [{"name": "Jan Kowalski"}],
            "publicationTypes": ["JournalArticle"],
            "openAccessPdf": {"url": "https://x/y.pdf"},
            "citationCount": cites, "publicationDate": "%d-03-01" % year}


def s2_responses():
    return [
        FakeResponse(200, {"total": 3, "next": 2,
                           "data": [_s2_paper("p2", "10.2000/bbb", "Beta"),
                                    _s2_paper("p1", "10.2000/aaa", "Alpha")]}),
        FakeResponse(200, {"total": 3,
                           "data": [_s2_paper("p3", "", "Gamma no doi")]}),
    ]


def cr_source(responses=None):
    return CrossrefSource(mailto="a@b.org",
                          session=FakeSession(responses
                                              if responses is not None
                                              else crossref_responses()))


def s2_source(responses=None, api_key=""):
    return SemanticScholarSource(
        api_key=api_key,
        session=FakeSession(responses if responses is not None
                            else s2_responses()))


# ------------------------------------------------------- redaction / keys ---
def test_redact_params_drops_secrets_and_masks_contact():
    p = redact_params({"apiKey": "s3cret", "insttoken": "t", "mailto": "a@b.org",
                       "query": "ai", "rows": 20, "cursor": None})
    assert "apiKey" not in p and "insttoken" not in p
    assert p["mailto"] == "<redacted>"
    assert p == {"mailto": "<redacted>", "query": "ai", "rows": "20",
                 "cursor": ""}


def test_request_key_ignores_credentials_and_contact():
    a = request_key("https://x/works", {"query": "ai", "mailto": "a@b.org"})
    b = request_key("https://x/works", {"query": "ai", "mailto": "z@q.org",
                                        "api_key": "K"})
    c = request_key("https://x/works", {"query": "ai"})
    assert a == b == c
    assert request_key("https://x/works", {"query": "ml"}) != a


def test_request_key_is_order_independent():
    assert (request_key("u", {"a": 1, "b": 2})
            == request_key("u", {"b": 2, "a": 1}))


# ----------------------------------------------------------- fingerprints ---
def test_checksum_excludes_volatile_fields():
    a = Record(title="T", doi="10.5001/x", year=2020, cited_by=3,
               open_access=True, url="https://a")
    b = Record(title="T", doi="10.5001/x", year=2020, cited_by=9999,
               open_access=False, url="https://b")
    assert record_checksum(a) == record_checksum(b)
    assert "cited_by" not in checksum_payload(a)


def test_checksum_reacts_to_bibliographic_change():
    a = Record(title="T", doi="10.5001/x", year=2020)
    for mutated in (Record(title="T", doi="10.5001/x", year=2021),
                    Record(title="T2", doi="10.5001/x", year=2020),
                    Record(title="T", doi="10.5001/y", year=2020),
                    Record(title="T", doi="10.5001/x", year=2020, pages="1-9"),
                    Record(title="T", doi="10.5001/x", year=2020,
                           abstract="now present")):
        assert record_checksum(mutated) != record_checksum(a)


def test_checksum_is_insensitive_to_title_case_and_whitespace():
    a = Record(title="Artificial  Intelligence", doi="10.5001/x")
    b = Record(title="artificial intelligence", doi="10.5001/x")
    assert record_checksum(a) == record_checksum(b)


def test_records_checksum_is_order_independent():
    recs = [Record(title="A", doi="10.5001/a"), Record(title="B", doi="10.5001/b"),
            Record(title="C", doi="10.5001/c")]
    assert records_checksum(recs) == records_checksum(list(reversed(recs)))
    assert records_checksum(recs) != records_checksum(recs[:2])


def test_records_checksum_stable_literal():
    """A checksum published in a paper must not move between releases."""
    recs = [Record(title="Alpha study", doi="10.1000/aaa", year=2021)]
    assert records_checksum(recs) == records_checksum(
        [Record(title="alpha  study", doi="10.1000/AAA", year=2021,
                cited_by=42)])


def test_record_key_cascade():
    assert record_key(Record(doi="10.5001/x", pmid="9")) == "doi:10.5001/x"
    assert record_key(Record(pmid="9")) == "pmid:9"
    assert record_key(Record(openalex_id="W1")) == "openalex:W1"
    assert record_key(Record(scopus_id="S1")) == "scopus:S1"
    assert record_key(Record(source="X", source_id="p1")) == "sid:X:p1"
    k = record_key(Record(title="Some Title", year=2020))
    assert k.startswith("title:some title|2020")


def test_sort_records_is_deterministic_and_relevance_free():
    recs = [Record(title="Zeta", doi="10.5001/b"), Record(title="Alpha"),
            Record(title="Beta", doi="10.5001/a")]
    order = [r.title for r in sort_records(recs)]
    assert order == ["Alpha", "Beta", "Zeta"]
    assert order == [r.title for r in sort_records(list(reversed(recs)))]


def test_record_fingerprint_carries_volatile_fields():
    fp = record_fingerprint(Record(title="T", doi="10.5001/x", cited_by=7,
                                   open_access=True))
    assert fp["cited_by"] == 7 and fp["open_access"] is True
    assert fp["key"] == "doi:10.5001/x" and len(fp["checksum"]) == 64


def test_records_equal_compares_fields_not_identity():
    a = [Record(title="T", doi="10.5001/x", year=2020)]
    b = [Record(title="T", doi="10.5001/x", year=2020)]
    assert a[0] is not b[0]
    assert records_equal(a, b)
    b[0].uid = "R000001"          # corpus bookkeeping is ignored
    b[0].search_id = "S1"
    assert records_equal(a, b)
    b[0].year = 2021
    assert not records_equal(a, b)
    assert record_diff_fields(a[0], b[0]) == ["year"]
    assert not records_equal(a, b * 2)


# --------------------------------------------------------------- archiving ---
def test_live_harvest_writes_archive_and_manifest(tmp_path):
    arc = str(tmp_path / "arc")
    res = harvest(cr_source(), QUERY, max_results=10, archive=arc)
    assert len(res.records) == 3
    assert res.mode == "live"
    assert os.path.isfile(os.path.join(arc, "manifest.json"))
    files = sorted(os.listdir(os.path.join(arc, "responses")))
    assert files == ["000001.json", "000002.json"]
    man = json.load(open(os.path.join(arc, "manifest.json")))
    assert man["archive_version"] == ARCHIVE_VERSION
    assert man["package"] == "corpusslr" and man["package_version"]
    assert man["n_responses"] == 2 and man["n_harvests"] == 1
    h = man["harvests"][0]
    assert h["database"] == "Crossref"
    assert h["n_records"] == 3 and h["n_with_doi"] == 3
    assert len(h["checksum"]) == 64
    assert h["harvested_at"].endswith("Z")
    assert h["api_version"] == "1.0.0"            # Crossref message-version
    assert "cited_by" in h["volatile_fields"]
    assert len(h["record_index"]) == 3


def test_archive_never_stores_secrets(tmp_path):
    arc = str(tmp_path / "arc")
    src = s2_source(api_key="TOPSECRET")
    harvest(src, QUERY, max_results=10, archive=arc)
    blob = ""
    for root, _dirs, names in os.walk(arc):
        for n in names:
            blob += open(os.path.join(root, n), encoding="utf-8").read()
    assert "TOPSECRET" not in blob
    assert "a@b.org" not in blob
    man = json.load(open(os.path.join(arc, "manifest.json")))
    assert man["harvests"][0]["authenticated"] is True


def test_archive_redacts_mailto_in_stored_params(tmp_path):
    arc = str(tmp_path / "arc")
    harvest(cr_source(), QUERY, max_results=10, archive=arc)
    man = json.load(open(os.path.join(arc, "manifest.json")))
    assert man["responses"][0]["params"]["mailto"] == "<redacted>"


def test_harvest_restores_the_source_session(tmp_path):
    src = cr_source()
    original = src.session
    harvest(src, QUERY, max_results=10, archive=str(tmp_path / "arc"))
    assert src.session is original
    assert src.min_interval == CrossrefSource.min_interval


def test_harvest_without_archive_still_yields_checksum():
    res = harvest(cr_source(), QUERY, max_results=10)
    assert res.archive_path == ""
    assert len(res.manifest.checksum) == 64
    assert res.manifest.n_records == 3


def test_event_notes_carry_the_audit_trail(tmp_path):
    arc = str(tmp_path / "arc")
    res = harvest(cr_source(), QUERY, max_results=10, archive=arc)
    assert "corpus checksum sha256=" in res.event.notes
    assert "harvest_id=H1" in res.event.notes
    assert res.event.records_retrieved == 3


def test_to_source_result_feeds_corpus(tmp_path):
    res = harvest(cr_source(), QUERY, max_results=10,
                  archive=str(tmp_path / "arc"))
    corpus = Corpus()
    ev = corpus.add_search(res.to_source_result())
    assert ev.search_id == "S1" and len(corpus) == 3
    assert corpus.identified_by_source() == {"Crossref": 3}


def test_two_harvests_share_one_archive(tmp_path):
    arc = HarvestArchive.create(str(tmp_path / "arc"))
    a = harvest(cr_source(), QUERY, max_results=10, archive=arc)
    b = harvest(s2_source(), QUERY, max_results=10, archive=arc)
    assert a.manifest.harvest_id == "H1" and b.manifest.harvest_id == "H2"
    assert arc.harvest_ids() == ["H1", "H2"]
    assert verify_archive(str(tmp_path / "arc")) == []
    reopened = HarvestArchive.open(str(tmp_path / "arc"))
    assert len(reopened.response_index("H1")) == 2
    assert len(reopened.response_index("H2")) == 2
    with pytest.raises(HarvestError):
        reopened.manifest()               # ambiguous without harvest_id
    assert reopened.manifest("H2").database == "Semantic Scholar"


def test_archive_append_across_sessions(tmp_path):
    p = str(tmp_path / "arc")
    harvest(cr_source(), QUERY, max_results=10, archive=p)
    harvest(s2_source(), QUERY, max_results=10, archive=p)   # fresh open
    man = json.load(open(os.path.join(p, "manifest.json")))
    assert man["n_harvests"] == 2 and man["n_responses"] == 4
    assert [e["seq"] for e in man["responses"]] == [1, 2, 3, 4]


# ------------------------------------------------------------------ replay ---
def test_replay_reproduces_records_exactly(tmp_path):
    arc = str(tmp_path / "arc")
    live = harvest(cr_source(), QUERY, max_results=10, archive=arc)
    # A source whose session would raise if touched: replay must not use it.
    offline = CrossrefSource(mailto="reviewer@uni.edu", session=FakeSession([]))
    rep = harvest(offline, QUERY, max_results=None, archive=arc, replay=True)
    assert rep.mode == "replay"
    assert rep.checksum_matches is True
    assert rep.checksum == live.checksum
    assert records_equal(live.records, rep.records)
    assert [r.doi for r in rep.records] == [r.doi for r in live.records]
    assert offline.session.calls == []          # network never consulted


def test_replay_reproduces_semanticscholar(tmp_path):
    arc = str(tmp_path / "arc")
    live = harvest(s2_source(), QUERY, max_results=10, archive=arc)
    rep = replay_harvest(s2_source(responses=[]), QUERY, arc)
    assert records_equal(live.records, rep.records)
    assert rep.checksum == live.checksum
    assert rep.manifest.n_records == 3
    # paging replays along the same path: 2 pages recorded, 2 served
    assert rep.manifest.n_responses == 2


def test_replay_reuses_recorded_max_results(tmp_path):
    arc = str(tmp_path / "arc")
    harvest(cr_source(), QUERY, max_results=2, archive=arc)
    rep = replay_harvest(cr_source(responses=[]), QUERY, arc)
    assert rep.manifest.max_results == 2
    assert len(rep.records) == 2


def test_replay_keeps_the_original_harvest_date(tmp_path):
    arc = str(tmp_path / "arc")
    live = harvest(cr_source(), QUERY, max_results=10, archive=arc)
    rep = replay_harvest(cr_source(responses=[]), QUERY, arc)
    assert rep.manifest.harvested_at == live.manifest.harvested_at
    assert rep.manifest.mode == "replay"


def test_replay_is_idempotent(tmp_path):
    arc = str(tmp_path / "arc")
    harvest(cr_source(), QUERY, max_results=10, archive=arc)
    a = replay_harvest(cr_source(responses=[]), QUERY, arc)
    b = replay_harvest(cr_source(responses=[]), QUERY, arc)
    assert a.checksum == b.checksum
    assert records_equal(a.records, b.records)


def test_replay_selects_the_harvest_by_database(tmp_path):
    arc = HarvestArchive.create(str(tmp_path / "arc"))
    cr = harvest(cr_source(), QUERY, max_results=10, archive=arc)
    s2 = harvest(s2_source(), QUERY, max_results=10, archive=arc)
    p = str(tmp_path / "arc")
    assert replay_harvest(cr_source(responses=[]), QUERY, p).checksum == cr.checksum
    assert replay_harvest(s2_source(responses=[]), QUERY, p).checksum == s2.checksum


def test_replay_requires_an_archive():
    with pytest.raises(HarvestError):
        harvest(cr_source(), QUERY, replay=True)


def test_replay_of_a_different_query_fails_loudly(tmp_path):
    arc = str(tmp_path / "arc")
    harvest(cr_source(), QUERY, max_results=10, archive=arc)
    other = SearchQuery(blocks=[["quantum computing"]], years=(2020, 2023),
                        doc_types=["article"])
    with pytest.raises(HarvestError) as exc:
        replay_harvest(cr_source(responses=[]), other, arc)
    assert "no archived response left" in str(exc.value)


def test_replay_skips_recorded_transient_failures(tmp_path):
    """A 429 the live run retried past must not be re-served on replay."""
    arc = str(tmp_path / "arc")
    responses = [FakeResponse(429, text="slow down"),
                 FakeResponse(200, _cr_page([_cr_item("10.1000/aaa", "Alpha")],
                                            total=1))]
    live = harvest(cr_source(responses), QUERY, max_results=10, archive=arc)
    assert len(live.records) == 1
    stored = json.load(open(os.path.join(arc, "manifest.json")))
    assert [e["status"] for e in stored["responses"]] == [429, 200]
    rep = replay_harvest(cr_source(responses=[]), QUERY, arc)
    assert records_equal(live.records, rep.records)
    assert rep.manifest.n_responses == 1


def test_replay_can_re_serve_transient_failures_when_asked(tmp_path):
    arc = HarvestArchive.create(str(tmp_path / "arc"))
    responses = [FakeResponse(429, text="slow down"),
                 FakeResponse(200, _cr_page([_cr_item("10.1000/aaa", "A")], 1))]
    harvest(cr_source(responses), QUERY, max_results=10, archive=arc)
    ro = HarvestArchive.open(str(tmp_path / "arc"))
    sess = ReplaySession(ro, harvest_id="H1", skip_transient=False)
    src = cr_source(responses=[])
    src.session = sess
    src.min_interval = 0.0
    out = src.search(QUERY, max_results=10)      # retry path consumes both
    assert len(out.records) == 1 and sess.served == 2


# ---------------------------------------------------- corrupted archives ----
def test_missing_manifest_is_reported(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(HarvestError) as exc:
        HarvestArchive.open(str(tmp_path / "empty"))
    assert "not a CorpusSLR harvest archive" in str(exc.value)


def test_unparseable_manifest_is_reported(tmp_path):
    d = tmp_path / "bad"
    d.mkdir()
    (d / "manifest.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(HarvestError) as exc:
        HarvestArchive.open(str(d))
    assert "not valid JSON" in str(exc.value)


def test_non_object_manifest_is_reported(tmp_path):
    d = tmp_path / "bad2"
    d.mkdir()
    (d / "manifest.json").write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(HarvestError):
        HarvestArchive.open(str(d))


def test_future_archive_version_refuses_to_replay(tmp_path):
    arc = str(tmp_path / "arc")
    harvest(cr_source(), QUERY, max_results=10, archive=arc)
    mpath = os.path.join(arc, "manifest.json")
    doc = json.load(open(mpath))
    doc["archive_version"] = ARCHIVE_VERSION + 5
    json.dump(doc, open(mpath, "w"))
    with pytest.raises(HarvestError) as exc:
        HarvestArchive.open(arc)
    assert "newer than this corpusslr" in str(exc.value)


def test_deleted_response_file_is_detected(tmp_path):
    arc = str(tmp_path / "arc")
    harvest(cr_source(), QUERY, max_results=10, archive=arc)
    os.remove(os.path.join(arc, "responses", "000002.json"))
    problems = verify_archive(arc)
    assert len(problems) == 1 and "missing" in problems[0]
    with pytest.raises(HarvestError) as exc:
        replay_harvest(cr_source(responses=[]), QUERY, arc)
    assert "failed verification" in str(exc.value)


def test_tampered_response_body_is_detected(tmp_path):
    arc = str(tmp_path / "arc")
    harvest(cr_source(), QUERY, max_results=10, archive=arc)
    p = os.path.join(arc, "responses", "000001.json")
    doc = json.load(open(p))
    doc["body"]["message"]["items"][0]["title"] = ["Fabricated title"]
    json.dump(doc, open(p, "w"))
    problems = verify_archive(arc)
    assert problems and "tampered or corrupted" in problems[0]
    with pytest.raises(HarvestError):
        replay_harvest(cr_source(responses=[]), QUERY, arc)


def test_corrupted_response_json_is_detected(tmp_path):
    arc = str(tmp_path / "arc")
    harvest(cr_source(), QUERY, max_results=10, archive=arc)
    with open(os.path.join(arc, "responses", "000001.json"), "w") as fh:
        fh.write("{truncated")
    problems = verify_archive(arc)
    assert problems and "corrupted JSON" in problems[0]


def test_response_count_mismatch_is_detected(tmp_path):
    arc = str(tmp_path / "arc")
    harvest(cr_source(), QUERY, max_results=10, archive=arc)
    mpath = os.path.join(arc, "manifest.json")
    doc = json.load(open(mpath))
    doc["harvests"][0]["n_responses"] = 99
    json.dump(doc, open(mpath, "w"))
    problems = verify_archive(arc)
    assert any("manifest claims 99 responses" in p for p in problems)


def test_sequence_gap_is_detected(tmp_path):
    arc = str(tmp_path / "arc")
    harvest(cr_source(), QUERY, max_results=10, archive=arc)
    mpath = os.path.join(arc, "manifest.json")
    doc = json.load(open(mpath))
    doc["responses"][1]["seq"] = 7
    json.dump(doc, open(mpath, "w"))
    assert any("gaps or duplicates" in p for p in verify_archive(arc))


def test_tampered_replay_can_be_inspected_without_strict(tmp_path):
    """A reviewer may want the divergence, not an exception."""
    arc = str(tmp_path / "arc")
    live = harvest(cr_source(), QUERY, max_results=10, archive=arc)
    p = os.path.join(arc, "responses", "000002.json")
    doc = json.load(open(p))
    doc["body"]["message"]["items"][0]["title"] = ["Swapped study"]
    e_sha = [e for e in json.load(
        open(os.path.join(arc, "manifest.json")))["responses"]
        if e["seq"] == 2]
    json.dump(doc, open(p, "w"))
    assert e_sha                                   # manifest still indexes it
    rep = harvest(cr_source(responses=[]), QUERY, archive=arc, replay=True,
                  verify=False, strict=False)
    assert rep.checksum_matches is False
    assert rep.recorded_checksum == live.checksum
    assert not records_equal(live.records, rep.records)


def test_empty_archive_verify_reports_no_responses(tmp_path):
    arc = HarvestArchive.create(str(tmp_path / "arc"))
    arc.write_manifest()
    problems = verify_archive(str(tmp_path / "arc"))
    assert any("no harvests" in p for p in problems)
    assert any("no responses" in p for p in problems)


def test_read_only_archive_refuses_writes(tmp_path):
    arc = str(tmp_path / "arc")
    harvest(cr_source(), QUERY, max_results=10, archive=arc)
    ro = HarvestArchive.open(arc)
    with pytest.raises(HarvestError):
        ro.add_response("u", {}, 200, payload={})
    with pytest.raises(HarvestError):
        ro.add_harvest(HarvestManifest())
    with pytest.raises(HarvestError):
        ro.write_manifest()


def test_unknown_harvest_id_is_reported(tmp_path):
    arc = str(tmp_path / "arc")
    harvest(cr_source(), QUERY, max_results=10, archive=arc)
    with pytest.raises(HarvestError) as exc:
        HarvestArchive.open(arc).manifest("H99")
    assert "no harvest 'H99'" in str(exc.value)


def test_invalid_archive_mode_rejected(tmp_path):
    with pytest.raises(ValueError):
        HarvestArchive(str(tmp_path / "x"), mode="append")


def test_resolve_harvest_id_ambiguous(tmp_path):
    arc = HarvestArchive.create(str(tmp_path / "arc"))
    harvest(cr_source(), QUERY, max_results=10, archive=arc)
    harvest(s2_source(), QUERY, max_results=10, archive=arc)
    with pytest.raises(HarvestError):
        arc.resolve_harvest_id("PubMed")


def test_resolve_harvest_id_without_harvests(tmp_path):
    arc = HarvestArchive.create(str(tmp_path / "arc"))
    with pytest.raises(HarvestError):
        arc.resolve_harvest_id()
    with pytest.raises(HarvestError):
        arc.manifest()


# --------------------------------------------------------- non-JSON bodies ---
def test_non_json_response_is_archived_as_text(tmp_path):
    """Archiving must not depend on the body being JSON (XML sources)."""
    arc = HarvestArchive.create(str(tmp_path / "arc"))
    arc.add_response("https://x/y", {"q": "1"}, 200, text="<xml/>")
    arc.write_manifest()
    ro = HarvestArchive.open(str(tmp_path / "arc"))
    entry = ro.response_index()[0]
    assert entry["body_repr"] == "text"
    r = ro.load_response(entry)
    assert r.text == "<xml/>"
    with pytest.raises(ValueError):
        ArchivedResponse(200, text="").json()
    assert verify_archive(str(tmp_path / "arc"))[0:1] == \
        ["manifest lists no harvests"]


def test_archived_response_helpers():
    r = ArchivedResponse(404, text="nope", headers={"a": "b"}, url="u")
    assert r.status_code == 404 and r.headers == {"a": "b"}
    # ArchivedResponse mirrors requests' contract, so the replayed error must
    # be the same type a live client would raise -- a bare Exception here would
    # also pass if the method raised AttributeError.
    with pytest.raises(requests.HTTPError):
        r.raise_for_status()
    ok = ArchivedResponse(200, payload={"a": 1})
    assert ok.json() == {"a": 1}
    ok.raise_for_status()
    assert ArchivedResponse(200, text='{"b": 2}').json() == {"b": 2}


def test_recording_session_proxies_headers(tmp_path):
    arc = HarvestArchive.create(str(tmp_path / "arc"))
    inner = FakeSession([FakeResponse(200, {"ok": 1})])
    sess = RecordingSession(arc, inner, harvest_id="H1")
    sess.headers.update({"User-Agent": "x"})
    assert inner.headers["User-Agent"] == "x"
    sess.headers = {"User-Agent": "y"}
    assert inner.headers == {"User-Agent": "y"}
    r = sess.get("https://x/y", params={"q": 1}, headers={"x-api-key": "K"})
    assert r.status_code == 200
    assert arc.response_index()[0]["authenticated"] is True
    assert len(sess.calls) == 1


# --------------------------------------------------------------- manifests ---
def test_manifest_roundtrip_and_unknown_keys(tmp_path):
    live = harvest(cr_source(), QUERY, max_results=10,
                   archive=str(tmp_path / "arc"))
    d = live.manifest.to_dict()
    d["a_field_from_a_future_version"] = 1
    back = HarvestManifest.from_dict(d)
    assert back.checksum == live.checksum
    assert back.n_records == 3
    assert HarvestManifest.from_dict({}).harvest_id == "H1"


def test_manifest_markdown_reports_prisma_s_items(tmp_path):
    res = harvest(cr_source(), QUERY, max_results=10,
                  archive=str(tmp_path / "arc"))
    md = res.manifest.to_markdown()
    for needle in ("Database", "Crossref", "Corpus checksum",
                   "Records with DOI", "3 (100.0%)", "Date of harvest (UTC)",
                   "Software"):
        assert needle in md
    assert "Crossref: boolean logic not supported" in md


def test_manifest_markdown_handles_empty_harvest():
    md = HarvestManifest(n_records=0, n_with_doi=0).to_markdown()
    assert "0 (0.0%)" in md
    assert "not published by the API" in md


def test_write_manifest_standalone_file(tmp_path):
    res = harvest(cr_source(), QUERY, max_results=10,
                  archive=str(tmp_path / "arc"))
    p = res.write_manifest(str(tmp_path / "harvest_manifest.json"))
    doc = json.load(open(p))
    assert doc["checksum"] == res.checksum
    assert len(res) == 3


def test_harvest_markdown_over_several_harvests(tmp_path):
    arc = HarvestArchive.create(str(tmp_path / "arc"))
    a = harvest(cr_source(), QUERY, max_results=10, archive=arc)
    b = harvest(s2_source(), QUERY, max_results=10, archive=arc)
    md = harvest_markdown([a, b, type(a)()])
    assert "## Reproducible harvesting" in md
    assert "### Crossref" in md and "### Semantic Scholar" in md
    assert "replay=True" in md


def test_s2_manifest_records_absent_api_version(tmp_path):
    res = harvest(s2_source(), QUERY, max_results=10,
                  archive=str(tmp_path / "arc"))
    assert res.manifest.api_version == ""
    assert "not published by the API" in res.manifest.to_markdown()
    assert res.manifest.n_with_doi == 2      # one S2 record has no DOI


# ------------------------------------------------------------------- drift ---
def _harv(tmp_path, name, responses):
    return harvest(cr_source(responses), QUERY, max_results=50,
                   archive=str(tmp_path / name))


def test_compare_identical_harvests_is_stable(tmp_path):
    a = _harv(tmp_path, "a", crossref_responses())
    b = _harv(tmp_path, "b", crossref_responses())
    d = compare_harvests(a, b)
    assert d.stable is True
    assert (len(d.added), len(d.removed), len(d.changed)) == (0, 0, 0)
    assert d.unchanged == 3 and d.n_before == d.n_after == 3
    assert d.checksum_before == d.checksum_after
    assert "0 added" in d.summary()


def test_compare_detects_added_and_removed(tmp_path):
    a = _harv(tmp_path, "a", crossref_responses())
    later = [_cr_page([_cr_item("10.1000/aaa", "Alpha study"),
                       _cr_item("10.1000/ddd", "Delta study")], total=2)]
    b = _harv(tmp_path, "b", crossref_responses(later))
    d = compare_harvests(a, b, label_before="2026-01-05",
                         label_after="2026-07-05")
    assert [r["doi"] for r in d.added] == ["10.1000/ddd"]
    assert sorted(r["doi"] for r in d.removed) == ["10.1000/bbb", "10.1000/ccc"]
    assert d.unchanged == 1 and d.stable is False
    assert "2026-01-05 -> 2026-07-05" in d.summary()
    md = d.to_markdown()
    assert "| Added | 1 |" in md and "| Removed | 2 |" in md
    assert "Delta study" in md
    assert d.to_dict()["n_added"] == 1


def test_compare_flags_metadata_change_not_citation_growth(tmp_path):
    a = _harv(tmp_path, "a", crossref_responses(
        [_cr_page([_cr_item("10.1000/aaa", "Alpha study", year=2021, cites=3)],
                  total=1)]))
    b = _harv(tmp_path, "b", crossref_responses(
        [_cr_page([_cr_item("10.1000/aaa", "Alpha study", year=2022, cites=99)],
                  total=1)]))
    d = compare_harvests(a, b)
    assert len(d.changed) == 1 and d.changed[0]["doi"] == "10.1000/aaa"
    assert "year" in d.changed[0]["fields"]
    assert d.citation_updates == []          # a changed record is not double-counted
    assert d.stable is False


def test_compare_isolates_pure_citation_updates(tmp_path):
    a = _harv(tmp_path, "a", crossref_responses(
        [_cr_page([_cr_item("10.1000/aaa", "Alpha study", cites=3)], total=1)]))
    b = _harv(tmp_path, "b", crossref_responses(
        [_cr_page([_cr_item("10.1000/aaa", "Alpha study", cites=41)], total=1)]))
    d = compare_harvests(a, b)
    assert d.stable is True                  # the corpus did not change
    assert d.checksum_before == d.checksum_after
    assert len(d.citation_updates) == 1
    upd = d.citation_updates[0]
    assert upd["before"]["cited_by"] == 3 and upd["after"]["cited_by"] == 41
    assert "| Citation count updated only | 1 |" in d.to_markdown()


def test_compare_accepts_manifests_paths_and_record_lists(tmp_path):
    a = _harv(tmp_path, "a", crossref_responses())
    b = _harv(tmp_path, "b", crossref_responses())
    variants = [
        (a.manifest, b.manifest),
        (a.manifest.to_dict(), b.manifest.to_dict()),
        (str(tmp_path / "a"), str(tmp_path / "b")),
        (HarvestArchive.open(str(tmp_path / "a")),
         HarvestArchive.open(str(tmp_path / "b"))),
        (a.records, b.records),
    ]
    for x, y in variants:
        assert compare_harvests(x, y).stable is True
    mp = a.write_manifest(str(tmp_path / "m.json"))
    assert compare_harvests(mp, b.manifest).unchanged == 3


def test_compare_rejects_unsupported_objects():
    with pytest.raises(TypeError):
        compare_harvests([1, 2], [3])


def test_compare_empty_harvests():
    d = compare_harvests([], [])
    assert d.stable and d.unchanged == 0 and d.n_before == 0
    assert d.to_markdown().startswith("| Change | Records |")


def test_compare_truncates_long_lists():
    before = [Record(title="T%02d" % i, doi="10.5001/%02d" % i) for i in range(30)]
    d = compare_harvests(before, [])
    md = d.to_markdown(limit=5)
    assert "and 25 more" in md
    changed = HarvestDiff(changed=[{"key": "k%d" % i, "fields": ["year"]}
                                   for i in range(30)])
    assert "and 25 more" in changed.to_markdown(limit=5)


def test_compare_records_without_doi_align_on_title(tmp_path):
    a = [Record(title="Untitled study", year=2020, journal="J")]
    b = [Record(title="untitled  study", year=2020, journal="J",
                cited_by=5)]
    d = compare_harvests(a, b)
    assert d.stable and d.unchanged == 1


# -------------------------------------------------- interrupted harvests ----
def test_aborted_harvest_still_leaves_a_verifiable_archive(tmp_path):
    """Exhausted 429 retries must not leave unindexed response files behind."""
    from corpusslr import SourceError
    arc = str(tmp_path / "arc")
    src = cr_source([FakeResponse(429, text="Too Many Requests")] * 3)
    with pytest.raises(SourceError):
        harvest(src, QUERY, max_results=10, archive=arc)
    assert verify_archive(arc) == []
    man = json.load(open(os.path.join(arc, "manifest.json")))
    assert [e["status"] for e in man["responses"]] == [429, 429, 429]
    h = man["harvests"][0]
    assert h["mode"] == "aborted" and h["n_records"] == 0
    assert h["n_responses"] == 3
    assert "aborted after 3 response(s)" in h["notes"]
    assert "HTTP 429" in h["notes"]


def test_aborted_harvest_is_not_replayable(tmp_path):
    from corpusslr import SourceError
    arc = str(tmp_path / "arc")
    with pytest.raises(SourceError):
        harvest(cr_source([FakeResponse(429, text="x")] * 3), QUERY,
                max_results=10, archive=arc)
    with pytest.raises(HarvestError) as exc:
        replay_harvest(cr_source(responses=[]), QUERY, arc)
    assert "aborted before completion" in str(exc.value)


def test_truncated_archive_refuses_to_replay_as_complete(tmp_path):
    """A harvest that lost its last page must not silently replay as a corpus.

    Returning the pages that did arrive would hand the reviewer a smaller
    record set that looks complete, so replay fails loudly even with
    ``strict=False``; the surviving evidence stays readable through the
    archive API.
    """
    from corpusslr import SourceError
    arc = str(tmp_path / "arc")
    responses = [FakeResponse(200, _cr_page([_cr_item("10.1000/aaa", "Alpha")],
                                            total=9, next_cursor="CUR2"))] + \
                [FakeResponse(500, text="server error")] * 3
    with pytest.raises(SourceError):
        harvest(cr_source(responses), QUERY, max_results=50, archive=arc)
    man = json.load(open(os.path.join(arc, "manifest.json")))
    assert man["harvests"][0]["mode"] == "aborted"
    assert [e["status"] for e in man["responses"]] == [200, 500, 500, 500]
    assert verify_archive(arc) == []
    with pytest.raises(HarvestError) as exc:
        harvest(cr_source(responses=[]), QUERY, archive=arc, replay=True,
                strict=False, max_results=50)
    assert "no archived response left" in str(exc.value)
    # the page that did arrive remains inspectable evidence
    ro = HarvestArchive.open(arc)
    first = ro.load_response(ro.response_index("H1")[0])
    assert first.json()["message"]["items"][0]["DOI"] == "10.1000/aaa"
    assert [e["status"] for e in ro.response_index("H1")[1:]] == [500, 500, 500]


def test_aborted_harvest_after_success_keeps_both(tmp_path):
    from corpusslr import SourceError
    arc = HarvestArchive.create(str(tmp_path / "arc"))
    ok = harvest(cr_source(), QUERY, max_results=10, archive=arc)
    with pytest.raises(SourceError):
        harvest(s2_source([FakeResponse(429, text="x")] * 3), QUERY,
                max_results=10, archive=arc)
    p = str(tmp_path / "arc")
    assert verify_archive(p) == []
    ro = HarvestArchive.open(p)
    assert ro.manifest("H1").mode == "live"
    assert ro.manifest("H2").mode == "aborted"
    # the completed Crossref harvest still replays untouched
    assert replay_harvest(cr_source(responses=[]), QUERY, p,
                          harvest_id="H1").checksum == ok.checksum


# ------------------------------------------------------------ edge cases ----
def test_api_version_read_from_header_when_body_has_none(tmp_path):
    """Sources that version via headers (not the payload) must still be recorded."""
    arc = HarvestArchive.create(str(tmp_path / "arc"))
    arc.add_response("https://x/y", {"q": "1"}, 200, payload={"data": []},
                     headers={"X-Api-Version": "2.7", "content-type": "application/json"})
    arc.write_manifest()
    ro = HarvestArchive.open(str(tmp_path / "arc"))
    assert ro.response_index()[0]["api_version"] == "2.7"


def test_harvests_property_exposes_manifest_objects(tmp_path):
    arc = HarvestArchive.create(str(tmp_path / "arc"))
    harvest(cr_source(), QUERY, max_results=10, archive=arc)
    harvest(s2_source(), QUERY, max_results=10, archive=arc)
    got = arc.harvests
    assert [m.harvest_id for m in got] == ["H1", "H2"]
    assert isinstance(got[0], HarvestManifest)
    assert [m.database for m in got] == ["Crossref", "Semantic Scholar"]


def test_add_harvest_replaces_an_existing_id(tmp_path):
    arc = HarvestArchive.create(str(tmp_path / "arc"))
    arc.add_harvest(HarvestManifest(harvest_id="H1", n_records=1))
    arc.add_harvest(HarvestManifest(harvest_id="H1", n_records=5))
    assert len(arc.harvest_ids()) == 1
    assert arc.manifest("H1").n_records == 5
    assert arc.next_harvest_id() == "H2"


def test_recording_session_creates_its_own_session(tmp_path):
    arc = HarvestArchive.create(str(tmp_path / "arc"))
    sess = RecordingSession(arc)          # no session passed
    import requests
    assert isinstance(sess.session, requests.Session)
    assert sess.calls == []


def test_query_repr_tolerates_an_unknown_source(tmp_path):
    """A source outside the Crossref/S2 pair must not break harvesting."""
    from corpusslr import OpenAlexSource
    payload = {"meta": {"count": 1, "next_cursor": None},
               "results": [{"id": "https://openalex.org/W1", "title": "T",
                            "publication_year": 2021, "doi": "10.5001/oa",
                            "type": "article", "authorships": []}]}
    src = OpenAlexSource(mailto="a@b.org",
                         session=FakeSession([FakeResponse(200, payload)]))
    res = harvest(src, QUERY, max_results=5, archive=str(tmp_path / "arc"))
    assert res.manifest.database == "OpenAlex"
    assert res.manifest.compiled_params == {}
    assert len(res.records) == 1


def test_query_repr_survives_a_broken_query(tmp_path):
    """Deriving the manifest's query string must never sink a good harvest."""
    class Flaky(SearchQuery):
        calls = 0

        def to_crossref_params(self):
            Flaky.calls += 1
            if Flaky.calls > 1:            # fails only when harvest re-derives it
                raise RuntimeError("compilation failed")
            return SearchQuery.to_crossref_params(self)

    q = Flaky(blocks=[["ai"]])
    src = cr_source(crossref_responses([_cr_page([_cr_item("10.5001/a", "A")], 1)]))
    res = harvest(src, q, max_results=5, archive=str(tmp_path / "arc"))
    assert res.manifest.n_records == 1     # harvest completed
    assert res.manifest.compiled_params == {}
    assert res.manifest.query          # fell back to the SearchEvent's query


def test_next_harvest_id_skips_used_ids(tmp_path):
    arc = HarvestArchive.create(str(tmp_path / "arc"))
    arc.add_harvest(HarvestManifest(harvest_id="H2"))
    assert arc.next_harvest_id() == "H3"
    arc.add_harvest(HarvestManifest(harvest_id="H3"))
    assert arc.next_harvest_id() == "H4"


def test_default_max_results_is_applied(tmp_path):
    from corpusslr.harvest import DEFAULT_MAX_RESULTS
    res = harvest(cr_source(), QUERY, archive=str(tmp_path / "arc"))
    assert res.manifest.max_results == DEFAULT_MAX_RESULTS


def test_strict_replay_of_a_shrunken_archive_raises(tmp_path):
    """Checksum divergence must be fatal under the default strict=True."""
    arc = str(tmp_path / "arc")
    harvest(cr_source(), QUERY, max_results=10, archive=arc)
    mpath = os.path.join(arc, "manifest.json")
    doc = json.load(open(mpath))
    doc["harvests"][0]["checksum"] = "0" * 64
    json.dump(doc, open(mpath, "w"))
    with pytest.raises(HarvestError) as exc:
        replay_harvest(cr_source(responses=[]), QUERY, arc)
    assert "replay diverged" in str(exc.value)


def test_full_cycle_live_replay_drift(tmp_path):
    """The whole protocol a reviewer executes, end to end."""
    arc = str(tmp_path / "t0")
    t0 = harvest(cr_source(), QUERY, max_results=50, archive=arc)
    assert verify_archive(arc) == []
    rep = replay_harvest(cr_source(responses=[]), QUERY, arc)
    assert rep.checksum_matches and records_equal(t0.records, rep.records)
    later = [_cr_page([_cr_item("10.1000/aaa", "Alpha study"),
                       _cr_item("10.1000/bbb", "Beta study"),
                       _cr_item("10.1000/ccc", "Gamma study"),
                       _cr_item("10.1000/eee", "Epsilon study")], total=4)]
    t1 = harvest(cr_source(crossref_responses(later)), QUERY, max_results=50,
                 archive=str(tmp_path / "t1"))
    d = compare_harvests(t0, t1)
    assert len(d.added) == 1 and not d.removed and d.unchanged == 3
    assert d.checksum_before != d.checksum_after
