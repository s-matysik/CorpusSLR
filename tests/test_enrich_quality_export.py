"""Abstract recovery (offline), quality report and all export formats."""
import csv
import re

import requests

from conftest import FakeResponse, FakeSession

from corpusslr import (Record, quality_csv, quality_markdown, quality_report,
                       recover_abstracts, to_bibtex, to_csv, to_ris,
                       to_screening_csv)
from corpusslr.parsers.ris import parse_ris
from corpusslr.sources.openalex import reconstruct_abstract


# ------------------------------------------------------------- enrich
def _long_abstract(n):
    """n distinct words -- distinct keys are required by the inverted index."""
    return " ".join(f"w{i}" for i in range(n))


def _oa_hit(doi, words, oa_id="W1", pmid=None):
    inv = {}
    for i, w in enumerate(words.split()):
        inv.setdefault(w, []).append(i)
    d = {"id": f"https://openalex.org/{oa_id}",
         "doi": f"https://doi.org/{doi}",
         "abstract_inverted_index": inv}
    if pmid:
        d["ids"] = {"pmid": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}"}
    return d


def test_recover_abstracts_fills_short_abstracts_and_ids():
    recs = [Record(title="A", doi="10.5001/a", abstract="too short", source="Scopus"),
            Record(title="B", doi="10.5001/b", abstract="x" * 400, source="Scopus"),
            Record(title="C", abstract="", source="Scopus")]  # no DOI -> skipped
    payload = {"results": [_oa_hit("10.5001/a", _long_abstract(60),
                                   oa_id="W42", pmid="555")]}
    s = FakeSession([FakeResponse(200, payload=payload)])
    stats = recover_abstracts(recs, mailto="me@uni.edu", session=s)

    # only the short-abstract record with a DOI qualifies
    assert stats == {"candidates": 1, "recovered": 1, "ids_added": 2}
    assert len(recs[0].abstract.split()) == 60
    assert recs[0].openalex_id == "W42" and recs[0].pmid == "555"
    assert recs[0].provenance[-1]["source_id"] == "abstract_recovery"
    assert recs[1].abstract == "x" * 400          # long abstract untouched
    assert s.calls[0]["params"]["mailto"] == "me@uni.edu"
    assert s.calls[0]["params"]["filter"].startswith("doi:")


def test_recover_abstracts_no_candidates_makes_no_request():
    recs = [Record(title="A", doi="10.5001/a", abstract="y" * 500)]
    s = FakeSession([])
    assert recover_abstracts(recs, session=s)["candidates"] == 0
    assert s.calls == []


def test_recover_abstracts_batches_requests():
    recs = [Record(title=f"T{i}", doi=f"10.5001/{i}", abstract="") for i in range(7)]
    s = FakeSession([FakeResponse(200, payload={"results": []})] * 4)
    recover_abstracts(recs, batch=2, session=s)
    assert len(s.calls) == 4      # ceil(7/2)
    assert s.calls[0]["params"]["per-page"] == 2


def test_recover_abstracts_survives_http_failure():
    recs = [Record(title="A", doi="10.5001/a", abstract="")]

    def boom(url, params, headers):
        raise requests.ConnectionError("down")

    stats = recover_abstracts(recs, session=FakeSession(boom))
    assert stats == {"candidates": 1, "recovered": 0, "ids_added": 0}
    assert recs[0].abstract == ""


def test_recover_abstracts_ignores_shorter_openalex_abstract():
    recs = [Record(title="A", doi="10.5001/a", abstract="a" * 200)]
    payload = {"results": [_oa_hit("10.5001/a", "tiny")]}
    stats = recover_abstracts(recs, session=FakeSession(
        [FakeResponse(200, payload=payload)]))
    assert stats["recovered"] == 0 and recs[0].abstract == "a" * 200


def test_recover_abstracts_min_len_is_configurable():
    recs = [Record(title="A", doi="10.5001/a", abstract="x" * 300)]
    s = FakeSession([FakeResponse(200, payload={"results": []})])
    assert recover_abstracts(recs, min_len=500, session=s)["candidates"] == 1


def test_reconstruct_abstract_multiword_positions_and_gaps():
    inv = {"machine": [0, 3], "learning": [1], "for": [2], "vision": [4]}
    assert reconstruct_abstract(inv) == "machine learning for machine vision"
    assert reconstruct_abstract({}) == "" and reconstruct_abstract(None) == ""
    assert reconstruct_abstract({"w": []}) == ""


def test_recover_abstracts_matches_case_insensitively():
    rec = Record(title="A", doi="10.5001/ABC", abstract="")
    assert rec.doi == "10.5001/abc"          # normalized on construction
    payload = {"results": [_oa_hit("10.5001/ABC", _long_abstract(60))]}
    stats = recover_abstracts([rec], session=FakeSession(
        [FakeResponse(200, payload=payload)]))
    assert stats["recovered"] == 1


def test_recover_abstracts_handles_alternate_resolver_prefix():
    rec = Record(title="A", doi="10.5001/abc", abstract="")
    hit = _oa_hit("10.5001/abc", _long_abstract(60))
    hit["doi"] = "http://dx.doi.org/10.5001/abc"
    stats = recover_abstracts([rec], session=FakeSession(
        [FakeResponse(200, payload={"results": [hit]})]))
    assert stats["recovered"] == 1


# ------------------------------------------------------------ quality
def _mixed():
    return [
        Record(title="A", doi="10.5001/a", abstract="x" * 100, year=2024,
               authors=["A, B"], issn="1", language="en", keywords=["k"],
               source="Scopus"),
        Record(title="B", abstract="", source="Scopus"),
        Record(title="C", doi="10.5001/c", abstract="y" * 300, year=2023,
               authors=["C, D"], source="OpenAlex"),
        Record(title="D", source=""),          # unlabeled source
    ]


def test_quality_report_percentages_and_means():
    rep = quality_report(_mixed())
    assert rep["Scopus"]["n"] == 2
    assert rep["Scopus"]["pct_doi"] == 50.0
    assert rep["Scopus"]["pct_abstract"] == 50.0
    assert rep["Scopus"]["mean_abstract_len"] == 100.0
    assert rep["OpenAlex"]["pct_language"] == 0.0
    assert rep["?"]["n"] == 1 and rep["?"]["mean_abstract_len"] == 0.0


def test_quality_report_empty_input():
    assert quality_report([]) == {}
    assert quality_markdown([]).startswith("| source |")


def test_quality_markdown_has_row_per_source():
    md = quality_markdown(_mixed())
    body = [line for line in md.splitlines() if line.startswith("| ")][1:]
    assert len(body) == 3            # Scopus, OpenAlex, ?
    assert md.count("pct_abstract") == 1


def test_quality_csv_columns_match_header(tmp_path):
    p = quality_csv(_mixed(), str(tmp_path / "q.csv"))
    rows = list(csv.DictReader(open(p, encoding="utf-8")))
    assert len(rows) == 3
    assert rows[0]["source"] in {"?", "OpenAlex", "Scopus"}
    assert set(rows[0]) == {"source", "n", "pct_doi", "pct_abstract",
                            "pct_year", "pct_authors", "pct_issn",
                            "pct_language", "pct_keywords",
                            "mean_abstract_len"}
    assert all(r["n"] for r in rows)


# ------------------------------------------------------------ exports
def _recs():
    return [
        Record(title="Title one", abstract="Abstract one", authors=["A, B", "C, D"],
               year=2024, journal="J1", doi="10.5001/1", issn="1111-1111",
               volume="1", issue="2", pages="10-20", doc_type="article",
               language="en", keywords=["k1", "k2"], url="http://1",
               source="Scopus", uid="R000001"),
        Record(title="Title two & <special>", abstract="", authors=[],
               year=None, doi="", doc_type="conference", source="WoS",
               uid="R000002"),
    ]


def test_to_csv_default_and_custom_columns(tmp_path):
    p = to_csv(_recs(), str(tmp_path / "a.csv"))
    rows = list(csv.DictReader(open(p, encoding="utf-8")))
    assert rows[0]["authors"] == "A, B; C, D"
    assert rows[0]["keywords" if "keywords" in rows[0] else "title"]
    assert rows[1]["year"] == ""          # None -> empty, not 'None'
    p2 = to_csv(_recs(), str(tmp_path / "b.csv"), columns=["uid", "doi"])
    assert open(p2, encoding="utf-8").readline().strip() == "uid,doi"


def test_to_screening_csv_is_asreview_shaped(tmp_path):
    p = to_screening_csv(_recs(), str(tmp_path / "s.csv"))
    r = csv.reader(open(p, encoding="utf-8"))
    assert next(r) == ["record_id", "title", "abstract", "authors", "year", "doi"]
    rows = list(r)
    assert rows[0][0] == "R000001" and rows[1][4] == ""


def test_to_ris_roundtrip_preserves_core_fields(tmp_path):
    p = to_ris(_recs(), str(tmp_path / "x.ris"))
    text = open(p, encoding="utf-8").read()
    assert text.startswith("TY  - JOUR")
    assert "TY  - CONF" in text and text.count("ER  - ") == 2
    back = parse_ris(text)
    assert len(back) == 2
    a = back[0]
    assert a.title == "Title one" and a.doi == "10.5001/1"
    assert a.authors == ["A, B", "C, D"] and a.year == 2024
    assert a.pages == "10-20" and a.journal == "J1"
    assert a.keywords == ["k1", "k2"] and a.language == "en"


def test_to_ris_splits_page_range_into_sp_ep(tmp_path):
    p = to_ris([Record(title="T", pages="100-110")], str(tmp_path / "p.ris"))
    t = open(p, encoding="utf-8").read()
    assert "SP  - 100" in t and "EP  - 110" in t


def test_to_bibtex_keys_are_unique_and_escaped(tmp_path):
    recs = [Record(title="One {brace} & amp", authors=["Smith, A"], year=2020),
            Record(title="Two", authors=["Smith, B"], year=2020),
            Record(title="Three", authors=["Smith, C"], year=2020),
            Record(title="Anon", authors=[], year=None)]
    p = to_bibtex(recs, str(tmp_path / "x.bib"))
    text = open(p, encoding="utf-8").read()
    keys = re.findall(r"@article\{([^,]+),", text)
    assert len(keys) == len(set(keys)) == 4
    assert keys[0] == "smith2020" and keys[1] == "smith2020b"
    assert "anon" in keys[3]
    assert "\\{brace\\}" in text and "\\&" in text


def test_exports_handle_empty_record_list(tmp_path):
    assert open(to_csv([], str(tmp_path / "e.csv")), encoding="utf-8").read()
    assert open(to_screening_csv([], str(tmp_path / "e2.csv")),
                encoding="utf-8").read()
    assert open(to_ris([], str(tmp_path / "e.ris")), encoding="utf-8").read() == ""
    assert open(to_bibtex([], str(tmp_path / "e.bib")),
                encoding="utf-8").read() == "\n"


def test_csv_export_neutralizes_formula_injection(tmp_path):
    """A title starting with '=' is a spreadsheet formula when reopened."""
    p = to_csv([Record(title="=HYPERLINK(\"http://evil\")", uid="R1")],
               str(tmp_path / "inj.csv"))
    first_cell = list(csv.reader(open(p, encoding="utf-8")))[1][1]
    assert not first_cell.startswith(("=", "+", "-", "@")), \
        "exported cell is interpreted as a formula by Excel/Sheets"
