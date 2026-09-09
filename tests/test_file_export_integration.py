"""End-to-end: heterogeneous file exports -> Corpus -> deduplication.

The point of the export parsers is that the *same* article, retrieved from
five databases in five formats, collapses onto one record.  These tests
assert that property rather than the individual field mappings, which are
covered per parser elsewhere.
"""
from corpusslr import (Corpus, deduplicate, parse_bibtex, parse_csv_export,
                       parse_endnote_xml, parse_ris)

DOI = "10.1016/j.jbusres.2024.001"

BIB = r"""@ARTICLE{9876543,
  author={Kowalsk{\'i}, Jan and Wr{\'o}bel, {\L}ukasz},
  journal={IEEE Access},
  title={Artificial Intelligence Adoption in Small Firms},
  year={2024},
  doi={10.1016/j.jbusres.2024.001}}
"""

ENDNOTE = """<xml><records><record>
<ref-type name="Journal Article">17</ref-type>
<contributors><authors>
<author><style face="normal">Kowalski, Jan</style></author>
<author><style face="normal">Wr&#243;bel, &#321;ukasz</style></author>
</authors></contributors>
<titles><title><style face="normal">Artificial intelligence adoption in small firms</style></title></titles>
<periodical><full-title>Journal of Business Research</full-title></periodical>
<dates><year>2024</year></dates>
<electronic-resource-num>10.1016/j.jbusres.2024.001</electronic-resource-num>
<abstract><style face="normal">A long recovered abstract with plenty of detail for screening purposes.</style></abstract>
</record></records></xml>"""

CSV = ('Authors,Title,Year,Source title,DOI,EID,Cited by,Author Keywords,'
       'Index Keywords,Abstract,Document Type\n'
       '"Kowalski J.; Wr\u00f3bel \u0141.",'
       '"Artificial intelligence adoption in small firms",2024,'
       '"Journal of Business Research",10.1016/j.jbusres.2024.001,'
       '2-s2.0-85123456789,12,"AI; SME","Artificial intelligence",'
       '"Short abstract.",Article\n')

RIS = """TY  - JOUR
DB  - Embase
TI  - Artificial intelligence adoption in small firms
AU  - Kowalski J.
T2  - Journal of Business Research
PY  - 2024
M3  - Article
AN  - PMID:38999999
DO  - 10.1016/j.jbusres.2024.001
ER  -
"""

UNIQUE_CSV = ('Title,Authors,Year,DOI\n'
              '"A completely different paper","Solo, Han",2022,10.5001/unique\n')


def _corpus():
    c = Corpus()
    c.add_records(parse_bibtex(BIB), database="IEEE Xplore",
                  interface="file export (BibTeX)", date_run="2026-08-01")
    c.add_records(parse_endnote_xml(ENDNOTE), database="EndNote library",
                  interface="file export (EndNote XML)", date_run="2026-08-01")
    c.add_records(parse_csv_export(CSV), database="Scopus",
                  interface="file export (CSV)", date_run="2026-08-01")
    c.add_records(parse_ris(RIS), database="Embase",
                  interface="file export (RIS)", date_run="2026-08-01")
    c.add_records(parse_csv_export(UNIQUE_CSV), database="Scopus",
                  interface="file export (CSV)", date_run="2026-08-01")
    return c


def test_four_formats_collapse_to_one_record():
    c = _corpus()
    assert len(c) == 5
    res = deduplicate(c)
    assert res.report.before == 5
    assert res.report.after == 2
    assert res.report.by_method.get("doi") == 3


def test_merged_record_unions_identifiers_and_richest_abstract():
    res = deduplicate(_corpus())
    merged = [r for r in res.records if r.doi == DOI][0]
    assert merged.pmid == "38999999"
    assert merged.scopus_id == "2-s2.0-85123456789"
    assert merged.year == 2024
    assert "recovered abstract" in merged.abstract
    assert merged.journal == "Journal of Business Research"


def test_latex_and_unicode_surnames_do_not_block_the_match():
    """The BibTeX record's LaTeX-escaped surname must not split the cluster."""
    res = deduplicate(_corpus())
    assert res.report.after == 2
    merged = [r for r in res.records if r.doi == DOI][0]
    assert merged.first_author_surname == "kowalski"


def test_prisma_identification_counts_per_database():
    c = _corpus()
    counts = c.identified_by_source()
    assert counts["IEEE Xplore"] == 1
    assert counts["EndNote library"] == 1
    assert counts["Embase"] == 1
    assert counts["Scopus"] == 2
    assert c.total_identified() == 5


def test_every_parsed_record_gets_provenance():
    c = _corpus()
    assert all(r.uid and r.search_id and r.provenance for r in c)
    assert all(p["database"] for r in c for p in r.provenance)


def test_file_interface_recorded_for_prisma_s():
    c = _corpus()
    interfaces = {ev.database: ev.interface for ev in c.searches}
    assert interfaces["IEEE Xplore"] == "file export (BibTeX)"
    assert interfaces["Embase"] == "file export (RIS)"
