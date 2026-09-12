"""EndNote XML parser: style-wrapped fields, ref-types, malformed input."""
import pytest

from corpusslr import parse_endnote_xml, parse_endnote_xml_file

ENDNOTE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<xml>
<records>
<record>
<database name="SLR.enl" path="C:\\Users\\rev\\SLR.enl">SLR.enl</database>
<source-app name="EndNote" version="20.4">EndNote</source-app>
<rec-number>412</rec-number>
<foreign-keys><key app="EN" db-id="s9xvz0">412</key></foreign-keys>
<ref-type name="Journal Article">17</ref-type>
<contributors>
<authors>
<author><style face="normal" font="default" size="100%">Wr&#243;bel, &#321;ukasz</style></author>
<author><style face="normal" font="default" size="100%">M&#252;ller, Hans-J&#246;rg</style></author>
<author><style face="normal" font="default" size="100%">Andersson, &#197;sa</style></author>
</authors>
</contributors>
<titles>
<title><style face="normal">Machine learning for </style><style face="italic">in vitro</style><style face="normal"> screening</style></title>
<secondary-title><style face="normal">The Lancet Oncology</style></secondary-title>
</titles>
<periodical><full-title><style face="normal">The Lancet Oncology</style></full-title><abbr-1>Lancet Oncol</abbr-1></periodical>
<pages><style face="normal">601-612</style></pages>
<volume><style face="normal">24</style></volume>
<number><style face="normal">6</style></number>
<keywords>
<keyword><style face="normal">machine learning</style></keyword>
<keyword><style face="normal">screening; oncology</style></keyword>
<keyword><style face="normal">Machine Learning</style></keyword>
</keywords>
<dates><year><style face="normal">2023</style></year></dates>
<isbn><style face="normal">1474-5488</style></isbn>
<accession-num><style face="normal">36123456</style></accession-num>
<abstract><style face="normal">Background: ML improves screening. Methods: cohort study.</style></abstract>
<urls><related-urls><url><style face="normal">https://doi.org/10.1016/S1470-2045(23)00001-1</style></url></related-urls></urls>
<electronic-resource-num><style face="normal">10.1016/S1470-2045(23)00001-1</style></electronic-resource-num>
<language><style face="normal">eng</style></language>
<remote-database-name><style face="normal">MEDLINE</style></remote-database-name>
<times-cited>34</times-cited>
</record>

<record>
<rec-number>413</rec-number>
<ref-type name="Conference Paper">47</ref-type>
<contributors><authors>
<author>Nguyen, Th&#7909;y</author>
<author>Kowalski, Jan</author>
</authors></contributors>
<titles>
<title>Retrieval augmented screening at scale</title>
<secondary-title>Proceedings of the ACM Web Conference</secondary-title>
</titles>
<dates><year>2023</year></dates>
<pages>1123-1131</pages>
<accession-num>WOS:001200000001</accession-num>
<remote-database-name>Web of Science Core Collection</remote-database-name>
</record>

<record>
<rec-number>414</rec-number>
<ref-type name="Book Section">5</ref-type>
<contributors><authors><author>Lindqvist, Bj&#248;rn</author></authors></contributors>
<titles><title>A chapter on evidence synthesis</title>
<secondary-title>Handbook of Review Methods</secondary-title></titles>
<dates><year>2019</year></dates>
</record>

<record>
<rec-number>415</rec-number>
<ref-type name="Thesis">32</ref-type>
<contributors><authors><author>Nowak, Anna</author></authors></contributors>
<titles><title>Adopcja AI w ma&#322;ych firmach</title></titles>
<dates><year>2022</year></dates>
</record>

<record>
<rec-number>416</rec-number>
<ref-type name="Journal Article">17</ref-type>
<titles><title></title></titles>
<dates><year>2021</year></dates>
</record>
</records>
</xml>
"""

NAMESPACED = """<?xml version="1.0"?>
<xml xmlns="http://www.endnote.com/ns"><records><record>
<ref-type name="Journal Article">17</ref-type>
<titles><title>Namespaced record</title></titles>
<dates><year>2020</year></dates>
</record></records></xml>"""


def _by_title(text):
    return {r.title: r for r in parse_endnote_xml(text)}


# --------------------------------------------------------------------------

def test_record_count_drops_empty():
    recs = parse_endnote_xml(ENDNOTE_XML)
    assert len(recs) == 4          # the title-less record is skipped


def test_style_runs_are_reassembled():
    r = parse_endnote_xml(ENDNOTE_XML)[0]
    assert r.title == "Machine learning for in vitro screening"


def test_core_fields_journal_article():
    r = parse_endnote_xml(ENDNOTE_XML)[0]
    assert r.journal == "The Lancet Oncology"
    assert r.year == 2023
    assert r.volume == "24" and r.issue == "6" and r.pages == "601-612"
    assert r.issn == "1474-5488"
    assert r.doi == "10.1016/s1470-2045(23)00001-1"
    assert r.pmid == "36123456"
    assert r.doc_type == "article"
    assert r.language == "eng"
    assert r.cited_by == 34
    assert r.source == "MEDLINE"
    assert r.source_id == "36123456"
    assert r.abstract.startswith("Background: ML improves")


def test_nonascii_authors_normalized():
    r = parse_endnote_xml(ENDNOTE_XML)[0]
    assert r.authors == ["Wr\u00f3bel, \u0141ukasz", "M\u00fcller, Hans-J\u00f6rg",
                         "Andersson, \u00c5sa"]


def test_keywords_split_and_deduplicated():
    r = parse_endnote_xml(ENDNOTE_XML)[0]
    assert r.keywords == ["machine learning", "screening", "oncology"]


@pytest.mark.parametrize("title,expected", [
    ("Machine learning for in vitro screening", "article"),
    ("Retrieval augmented screening at scale", "conference"),
    ("A chapter on evidence synthesis", "chapter"),
    ("Adopcja AI w ma\u0142ych firmach", "thesis"),
])
def test_ref_type_mapping(title, expected):
    assert _by_title(ENDNOTE_XML)[title].doc_type == expected


def test_wos_accession_kept_and_not_read_as_pmid():
    r = _by_title(ENDNOTE_XML)["Retrieval augmented screening at scale"]
    assert r.source_id == "WOS:001200000001"
    assert r.pmid == ""
    assert r.raw["wos_id"] == "WOS:001200000001"


def test_secondary_title_used_when_no_periodical():
    r = _by_title(ENDNOTE_XML)["A chapter on evidence synthesis"]
    assert r.journal == "Handbook of Review Methods"


def test_missing_fields_are_empty_not_none():
    r = _by_title(ENDNOTE_XML)["Adopcja AI w ma\u0142ych firmach"]
    assert r.doi == "" and r.journal == "" and r.abstract == ""
    assert r.keywords == [] and r.pages == ""
    assert r.year == 2022


def test_ref_type_numeric_fallback_without_name_attribute():
    text = """<xml><records><record><ref-type>17</ref-type>
    <titles><title>Numeric only</title></titles></record></records></xml>"""
    assert parse_endnote_xml(text)[0].doc_type == "article"


def test_unknown_ref_type_label_maps_via_vocabulary():
    text = """<xml><records><record><ref-type name="Systematic Review">17</ref-type>
    <titles><title>SR</title></titles></record></records></xml>"""
    assert parse_endnote_xml(text)[0].doc_type == "review"


def test_doi_recovered_from_related_url():
    text = """<xml><records><record>
    <titles><title>DOI in URL</title></titles>
    <urls><related-urls><url>https://doi.org/10.1234/abc</url></related-urls></urls>
    </record></records></xml>"""
    r = parse_endnote_xml(text)[0]
    assert r.doi == "10.1234/abc"


def test_doi_field_with_prefix_text():
    text = """<xml><records><record>
    <titles><title>Prefixed</title></titles>
    <electronic-resource-num>https://doi.org/10.1234/xyz</electronic-resource-num>
    </record></records></xml>"""
    assert parse_endnote_xml(text)[0].doi == "10.1234/xyz"


def test_pmid_from_custom_note():
    text = """<xml><records><record>
    <titles><title>Noted</title></titles>
    <accession-num>PSY-2020-001</accession-num>
    <notes>PMID: 31234567</notes>
    </record></records></xml>"""
    r = parse_endnote_xml(text)[0]
    assert r.pmid == "31234567" and r.source_id == "PSY-2020-001"


def test_namespaced_document():
    recs = parse_endnote_xml(NAMESPACED)
    assert len(recs) == 1 and recs[0].title == "Namespaced record"


def test_bare_record_root():
    text = """<record><titles><title>Lone record</title></titles>
    <dates><year>2018</year></dates></record>"""
    recs = parse_endnote_xml(text)
    assert len(recs) == 1 and recs[0].year == 2018


# --------------------------------------------------------------------------
# Degenerate input
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["", "   ", "\n\n"])
def test_empty_input(text):
    assert parse_endnote_xml(text) == []


def test_malformed_xml_returns_empty_not_raises():
    assert parse_endnote_xml("<xml><records><record>") == []
    assert parse_endnote_xml("not xml at all") == []
    assert parse_endnote_xml("<xml><records><record>"
                             "<titles><title>Unclosed") == []


def test_no_records_element():
    assert parse_endnote_xml("<xml></xml>") == []


def test_leading_bom_in_string():
    assert len(parse_endnote_xml("\ufeff" + NAMESPACED)) == 1


def test_source_name_override():
    recs = parse_endnote_xml(ENDNOTE_XML, source_name="EndNote library")
    assert all(r.source == "EndNote library" for r in recs)


def test_default_source_when_database_absent():
    r = parse_endnote_xml(NAMESPACED)[0]
    assert r.source == "EndNote XML"


def test_parse_file(tmp_path):
    p = tmp_path / "lib.xml"
    p.write_text(ENDNOTE_XML, encoding="utf-8")
    recs = parse_endnote_xml_file(str(p))
    assert len(recs) == 4 and recs[0].pmid == "36123456"


def test_parse_file_with_bom(tmp_path):
    p = tmp_path / "bom.xml"
    p.write_text("\ufeff" + NAMESPACED, encoding="utf-8")
    assert len(parse_endnote_xml_file(str(p))) == 1


def test_parse_empty_file(tmp_path):
    p = tmp_path / "empty.xml"
    p.write_text("", encoding="utf-8")
    assert parse_endnote_xml_file(str(p)) == []
