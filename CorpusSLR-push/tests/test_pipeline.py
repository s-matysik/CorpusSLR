import os

from corpusslr import (Corpus, PrismaFlow, Record, deduplicate,
                       prisma_s_markdown, quality_report, to_bibtex, to_csv,
                       to_ris, to_screening_csv)
from corpusslr.parsers.ris import parse_ris


def _corpus():
    c = Corpus()
    scopus = [
        Record(title="AI adoption in small firms: a systematic review",
               doi="10.5001/abc", year=2024, authors=["Kowalski, Jan"],
               abstract="short", source="Scopus", scopus_id="850001"),
        Record(title="Deep learning for X-ray analysis", doi="10.5001/xr",
               year=2023, authors=["Nowak, Anna"], source="Scopus",
               scopus_id="850002"),
        Record(title="Unique Scopus-only paper", year=2022,
               authors=["Solo, Han"], source="Scopus", scopus_id="850003"),
    ]
    openalex = [
        Record(title="AI adoption in small firms - a systematic review.",
               doi="10.5001/ABC", year=2024, authors=["Jan Kowalski"],
               abstract="A much longer, recovered abstract with details.",
               journal="JBR", source="OpenAlex", openalex_id="W111"),
        Record(title="Deep learning for x ray analysis", year=2023,
               authors=["Anna Nowak"], source="OpenAlex", openalex_id="W222"),
    ]
    pubmed = [
        Record(title="Deep learning for X-ray analysis", pmid="123",
               doi="10.5001/xr", year=2023, authors=["Nowak, Anna"],
               source="PubMed"),
    ]
    c.add_records(scopus, database="Scopus", interface="API",
                  query="TITLE-ABS-KEY(...)", date_run="2026-08-01")
    c.add_records(openalex, database="OpenAlex", interface="API",
                  query="title_and_abstract.search:...", date_run="2026-08-01")
    c.add_records(pubmed, database="PubMed", interface="API",
                  query='"deep learning"[tiab]', date_run="2026-08-02")
    return c


def test_dedup_cascade_and_report():
    c = _corpus()
    assert len(c) == 6 and c.total_identified() == 6
    res = deduplicate(c)
    assert res.report.before == 6 and res.report.after == 3
    # 10.5001/abc pair -> doi; 10.5001/xr pair -> doi; OpenAlex W222 (no doi) -> fuzzy
    assert res.report.by_method.get("doi") == 2
    assert res.report.by_method.get("fuzzy") == 1
    ai = [r for r in res.records if r.title.lower().startswith("ai adoption")][0]
    # merge kept richest (OpenAlex had long abstract + journal), filled ids
    assert "recovered abstract" in ai.abstract
    assert ai.scopus_id == "850001" and ai.openalex_id == "W111"
    xr = [r for r in res.records if "x-ray" in r.title.lower()
          or "x ray" in r.title.lower()][0]
    assert xr.pmid == "123" and xr.openalex_id == "W222"
    # overlap matrix records cross-source pairs
    assert sum(res.report.overlap.values()) >= 2
    assert "Deduplication: 6 -> 3" in res.report.summary()


def test_dedup_fuzzy_guards():
    a = Record(title="Effects of exercise on depression", year=2020,
               authors=["Smith, A"], source="X")
    b = Record(title="Effects of exercise on depression", year=2010,
               authors=["Smith, A"], source="Y")  # year too far
    res = deduplicate([a, b])
    assert res.report.after == 2  # not merged


def test_prisma_flow_and_svg(tmp_path):
    c = _corpus()
    res = deduplicate(c)
    flow = PrismaFlow.from_dedup(c, res)
    flow.set_screening(records_excluded=1, reports_not_retrieved=0,
                       fulltext_exclusions={"wrong population": 1},
                       studies_included=1)
    assert flow.identified == 6 and flow.duplicates_removed == 3
    assert flow.records_screened == 3 and flow.reports_sought == 2
    assert flow.reports_assessed == 2
    assert flow.validate() == []
    svg = flow.to_svg(str(tmp_path / "prisma.svg"))
    assert svg.startswith("<svg") and "Records screened (n = 3)" in svg
    assert "Scopus (n = 3)" in svg
    assert os.path.exists(tmp_path / "prisma.svg")
    md = flow.to_markdown()
    assert "Studies included in review (n = 1)" in md
    # broken arithmetic is caught
    bad = PrismaFlow(db_counts={"A": 2}, duplicates_removed=5)
    assert bad.validate()


def test_prisma_s_markdown():
    c = _corpus()
    res = deduplicate(c)
    md = prisma_s_markdown(c, res)
    assert "PRISMA-S" in md and "Item 16" in md
    assert "| S1 | Scopus |" in md
    assert "TITLE-ABS-KEY(...)" in md
    assert "exact DOI" in md and "Ratcliff-Obershelp" in md
    assert "Cross-source overlap" in md


def test_quality_and_exports(tmp_path):
    c = _corpus()
    rep = quality_report(c.records)
    assert rep["Scopus"]["n"] == 3
    assert rep["OpenAlex"]["pct_doi"] == 50.0
    res = deduplicate(c)
    p1 = to_csv(res.records, str(tmp_path / "corpus.csv"))
    p2 = to_screening_csv(res.records, str(tmp_path / "screen.csv"))
    p3 = to_ris(res.records, str(tmp_path / "corpus.ris"))
    p4 = to_bibtex(res.records, str(tmp_path / "corpus.bib"))
    for p in (p1, p2, p3, p4):
        assert os.path.getsize(p) > 0
    # RIS round-trip
    back = parse_ris(open(p3, encoding="utf-8").read())
    assert len(back) == len(res.records)
    assert any(r.doi == "10.5001/abc" for r in back)
    bib = open(p4, encoding="utf-8").read()
    assert "@article{kowalski2024" in bib
