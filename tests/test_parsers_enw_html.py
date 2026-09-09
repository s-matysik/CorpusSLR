"""EndNote tagged (.enw) and HTML-table (.xls) export parsers.

Samples reproduce the header rows and tag sets of real exports: the ``.enw``
fixtures are shaped like an ACM Digital Library "Export Citation -> EndNote"
download, the HTML fixtures like a ProQuest ABI/INFORM "XLS" download (which
is an HTML document, not a workbook).
"""
from __future__ import annotations

import os

import pytest

from corpusslr.parsers import (extract_table_rows, looks_like_enw,
                               looks_like_html, parse_enw, parse_enw_file,
                               parse_html_table, parse_html_table_file)
from corpusslr.parsers._report import ParseReport

# --------------------------------------------------------------------------
# Realistic samples
# --------------------------------------------------------------------------

# ACM DL: conference paper + journal article. Note %B (not %J) for the
# proceedings, and %@ carrying an ISBN on the first record and an ISSN on the
# second -- both real ACM behaviour.
ACM_ENW = """%0 Conference Paper
%A Chen, Wei
%A Garcia, Maria
%T Neural Retrieval for Systematic Review Screening
%B Proceedings of the 32nd ACM International Conference on Information and Knowledge Management
%S CIKM '23
%D 2023
%P 1123-1132
%I Association for Computing Machinery
%C New York, NY, USA
%R 10.1145/3583780.3614999
%U https://doi.org/10.1145/3583780.3614999
%K systematic review
%K neural ranking
%X We present a neural retrieval model for citation screening
that reduces reviewer workload by 42%.
%@ 979-8-4007-0124-5

%0 Journal Article
%A Nowak, Anna
%T Screening automation in evidence synthesis
%J ACM Transactions on Information Systems
%D 2024
%V 42
%N 3
%P 1-28
%R 10.1145/3640000
%@ 1046-8188
%M 38912345
%G eng

"""

# ProQuest ABI/INFORM "XLS": an HTML document whose data table is nested
# inside a layout table, with a <br> inside one cell.
PROQUEST_HTML = """<html><head><title>ProQuest Documents</title>
<style>td {font-family: Arial}</style></head><body>
<table><tr><td>ProQuest export &mdash; 2 documents</td></tr></table>
<table border="1">
<tr><th>Title</th><th>Author</th><th>publication title</th>
    <th>Publication year</th><th>DOI</th><th>StoreId</th>
    <th>document url</th><th>Subject</th></tr>
<tr><td>Firm strategy under radical uncertainty</td><td>Lee, Min-Jae</td>
    <td>Academy of Management Review</td><td>2021</td>
    <td>10.5465/amr.2019.0123</td><td>2555000111</td>
    <td>https://www.proquest.com/docview/2555000111</td>
    <td>Strategic management; Uncertainty</td></tr>
<tr><td>Digital transformation<br>and dynamic capabilities</td>
    <td>Brown, Charlotte</td><td>Journal of Marketing</td><td>2020</td>
    <td>10.1177/0022242920912345</td><td></td>
    <td>https://www.proquest.com/docview/2555000112</td>
    <td>Digitalization</td></tr>
</table></body></html>"""


# --------------------------------------------------------------------------
# EndNote tagged
# --------------------------------------------------------------------------

def test_enw_detected_and_not_confused_with_xml_or_bibtex():
    assert looks_like_enw(ACM_ENW) is True
    assert looks_like_enw("<xml><records><record/></records></xml>") is False
    assert looks_like_enw("@article{k1, title={T}}") is False
    # A single stray % line is not an .enw file.
    assert looks_like_enw("TY  - JOUR\nN1  - 95% CI reported\nER  - \n") is False


def test_enw_acm_conference_paper_field_mapping():
    recs = parse_enw(ACM_ENW, source_name="ACM Digital Library")
    assert len(recs) == 2
    conf = recs[0]
    assert conf.doc_type == "conference"
    assert conf.title == "Neural Retrieval for Systematic Review Screening"
    # %B is the proceedings name; without the %B fallback the venue would be
    # empty and the journal blocking key in dedup would fail.
    assert conf.journal.startswith("Proceedings of the 32nd ACM")
    assert conf.doi == "10.1145/3583780.3614999"
    assert conf.year == 2023
    assert conf.pages == "1123-1132"
    assert conf.authors == ["Chen, Wei", "Garcia, Maria"]
    assert conf.keywords == ["systematic review", "neural ranking"]
    assert "reduces reviewer workload" in conf.abstract
    assert conf.source == "ACM Digital Library"


def test_enw_isbn_never_written_into_issn_field():
    """%@ carries both ISSN and ISBN; conflating them corrupts dedup."""
    conf, art = parse_enw(ACM_ENW)
    assert conf.issn == ""                      # 979-8-... is an ISBN
    assert conf.raw["isbn"] == "979-8-4007-0124-5"
    assert art.issn == "1046-8188"              # dddd-dddd is an ISSN
    assert art.raw["isbn"] == ""


def test_enw_journal_article_and_accession_pmid():
    art = parse_enw(ACM_ENW)[1]
    assert art.doc_type == "article"
    assert art.journal == "ACM Transactions on Information Systems"
    assert (art.volume, art.issue) == ("42", "3")
    assert art.pmid == "38912345"
    assert art.language == "eng"
    assert art.url == "https://doi.org/10.1145/3640000"


def test_enw_records_without_blank_separator_are_split_on_percent_zero():
    text = ("%0 Journal Article\n%T First paper\n%D 2020\n"
            "%0 Journal Article\n%T Second paper\n%D 2021\n")
    recs = parse_enw(text)
    assert [r.title for r in recs] == ["First paper", "Second paper"]


def test_enw_wrapped_abstract_is_joined():
    text = ("%0 Journal Article\n%T Wrapped\n"
            "%X First line of the abstract\n"
            "continues here\nand ends here.\n")
    assert parse_enw(text)[0].abstract == (
        "First line of the abstract continues here and ends here.")


def test_enw_contentless_stanza_is_rejected_not_dropped_silently():
    text = ACM_ENW + "%0 Journal Article\n%A Ghost, A\n\n"
    rep = ParseReport()
    recs = parse_enw(text, report=rep)
    assert len(recs) == 2
    assert rep.n_input == 3
    assert rep.n_rejected == 1
    assert rep.reason_counts() == {"no_content": 1}
    assert rep.balanced


def test_enw_file_roundtrip_with_bom(tmp_path):
    path = os.path.join(str(tmp_path), "acm.enw")
    with open(path, "wb") as fh:
        fh.write(b"\xef\xbb\xbf" + ACM_ENW.encode("utf-8"))
    rep = ParseReport()
    recs = parse_enw_file(path, report=rep)
    assert len(recs) == 2
    assert rep.encoding == "utf-8-sig"


# --------------------------------------------------------------------------
# HTML table (.xls that is not a workbook)
# --------------------------------------------------------------------------

def test_html_detection():
    assert looks_like_html(PROQUEST_HTML) is True
    assert looks_like_html("Title\tAuthor\nA\tB\n") is False


def test_html_table_extracts_data_table_not_layout_table():
    rows = extract_table_rows(PROQUEST_HTML)
    assert rows[0][0] == "Title"
    assert len(rows) == 3          # header + 2 records
    assert len(rows[0]) == 8


def test_proquest_html_export_field_mapping():
    rep = ParseReport()
    recs = parse_html_table(PROQUEST_HTML, report=rep)
    assert len(recs) == 2
    assert rep.dialect == "proquest"
    first = recs[0]
    assert first.title == "Firm strategy under radical uncertainty"
    assert first.journal == "Academy of Management Review"
    assert first.year == 2021
    assert first.doi == "10.5465/amr.2019.0123"
    assert first.source_id == "2555000111"
    assert first.authors == ["Lee, Min-Jae"]
    assert "Strategic management" in first.keywords


def test_html_cell_line_break_becomes_a_space():
    recs = parse_html_table(PROQUEST_HTML)
    assert recs[1].title == "Digital transformation and dynamic capabilities"


def test_proquest_html_id_recovered_from_docview_url():
    """The second row has an empty StoreId; the id is in the document url."""
    recs = parse_html_table(PROQUEST_HTML)
    assert recs[1].source_id == "2555000112"


def test_html_and_tsv_export_of_one_record_agree():
    """An HTML .xls and a TSV .xls of the same search must deduplicate.

    Both paths share ``parse_csv_rows``; this test is what detects a drift
    between them.
    """
    from corpusslr.parsers import parse_csv_export
    tsv = ("Title\tAuthor\tpublication title\tPublication year\tDOI\tStoreId\n"
           "Firm strategy under radical uncertainty\tLee, Min-Jae\t"
           "Academy of Management Review\t2021\t10.5465/amr.2019.0123\t"
           "2555000111\n")
    from_html = parse_html_table(PROQUEST_HTML)[0]
    from_tsv = parse_csv_export(tsv)[0]
    for field in ("title", "journal", "year", "doi", "source_id", "authors"):
        assert getattr(from_html, field) == getattr(from_tsv, field), field


def test_csv_parser_routes_html_input_to_the_table_reader():
    """A .xls HTML file handed to the CSV parser must not become garbage."""
    from corpusslr.parsers import parse_csv_export
    rep = ParseReport()
    recs = parse_csv_export(PROQUEST_HTML, report=rep)
    assert len(recs) == 2
    assert any("HTML" in w for w in rep.warnings)


def test_html_truncated_document_still_yields_complete_rows():
    truncated = PROQUEST_HTML.split("<tr><td>Digital transformation")[0]
    recs = parse_html_table(truncated)
    assert len(recs) == 1
    assert recs[0].title == "Firm strategy under radical uncertainty"


def test_html_without_any_table_returns_no_records():
    rep = ParseReport()
    assert parse_html_table("<html><body><p>No table here</p></body></html>",
                            report=rep) == []


def test_html_table_file(tmp_path):
    path = os.path.join(str(tmp_path), "proquest.xls")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(PROQUEST_HTML)
    assert len(parse_html_table_file(path)) == 2


@pytest.mark.parametrize("text", ["", "   ", "<html></html>", "\x00\x01\x02"])
def test_html_table_degenerate_inputs_do_not_raise(text):
    assert parse_html_table(text) == []
