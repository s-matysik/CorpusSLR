"""Parser dialects, query compilation and record normalization: edge cases."""
import pytest

from corpusslr import (Record, SearchQuery, detect_dialect, normalize_doi,
                       normalize_title, parse_nbib, parse_nbib_file, parse_ris,
                       parse_ris_file, parse_wos, parse_wos_file)
from corpusslr.record import surname


# ------------------------------------------------------- normalization
@pytest.mark.parametrize("raw,expected", [
    ("HTTPS://DOI.ORG/10.1016/J.X.2024.01", "10.1016/j.x.2024.01"),
    ("http://dx.doi.org/10.5001/ABC", "10.5001/abc"),
    ("DOI: 10.5001/abc;", "10.5001/abc"),
    ("  10.5001/abc  ", "10.5001/abc"),
    # A value that is not shaped like a DOI is not a DOI. Returning it verbatim
    # used to make every "NA" in an export share one identifier, and the
    # cascade treats a shared identifier as decisive evidence: on the ASySD
    # Diabetes file, 492 unrelated works collapsed onto the key "na".
    ("no doi here", ""),
    ("NA", ""),
    ("N/A", ""),
    ("NULL", ""),
    ("-", ""),
    ("", ""),
])
def test_normalize_doi_variants(raw, expected):
    assert normalize_doi(raw) == expected


def test_normalize_title_strips_combining_diacritics_html_and_punctuation():
    assert normalize_title("Zarządzanie jakością") == "zarzadzanie jakoscia"
    assert normalize_title("<b>Deep</b>  learning!") == "deep learning"
    assert normalize_title(None) == "" and normalize_title("") == ""


@pytest.mark.parametrize("raw,expected", [
    ("Wpływ AI na małe firmy", "wplyw ai na male firmy"),
    ("Økonomi og bærekraft", "okonomi og baerekraft"),
    ("Größe der Stichprobe", "grosse der stichprobe"),
])
def test_normalize_title_handles_stroked_letters(raw, expected):
    assert normalize_title(raw) == expected


def test_surname_extraction_forms():
    assert surname("Kowalski, Jan") == "kowalski"
    assert surname("Jan Kowalski") == "kowalski"
    assert surname("van der Berg, A") == "van der berg"
    assert surname("") == "" and surname(None) == ""


def test_record_postinit_normalizes_ids():
    r = Record(doi="https://doi.org/10.5001/X", pmid="PMID: 12345678",
               openalex_id="https://openalex.org/w999")
    assert r.doi == "10.5001/x" and r.pmid == "12345678"
    assert r.openalex_id == "W999"


def test_record_to_dict_drops_raw():
    d = Record(title="T", raw={"big": "payload"}).to_dict()
    assert "raw" not in d and d["title"] == "T"


def test_richness_prefers_complete_records():
    thin = Record(title="T")
    fat = Record(title="T", doi="10.5001/x", journal="J", issn="1", volume="1",
                 pages="1-2", doc_type="article", language="en", url="u",
                 year=2024, authors=["A"] * 5, keywords=["k"],
                 abstract="x" * 2000)
    assert fat.richness() > thin.richness()


def test_merge_does_not_overwrite_existing_values():
    a = Record(title="Keep me", journal="A journal", year=2020,
               abstract="longer abstract text here")
    b = Record(title="Other", journal="B journal", year=1999, abstract="short")
    a.merge_from(b)
    assert a.title == "Keep me" and a.journal == "A journal"
    assert a.year == 2020 and a.abstract.startswith("longer")


# --------------------------------------------------------------- RIS
RIS_MULTI = """TY  - JOUR
AU  - One, A
TI  - First record
PY  - 2020
DO  - 10.5001/one
ER  -

TY  - CONF
AU  - Two, B
TI  - Second record
PY  - 2021
ER  -

TY  - CHAP
TI  - Third record
Y1  - 2019///
ER  -
"""

RIS_NO_ER = """TY  - JOUR
TI  - Unterminated record
PY  - 2020
DO  - 10.5001/x
"""

RIS_EBSCO = """TY  - JOUR
DP  - EBSCOhost
AU  - Smith, J
TI  - EBSCO sourced study
JF  - Business Source Journal
PY  - 2022
AN  - 12345678
ER  -
"""

RIS_PROQUEST = """TY  - JOUR
DB  - ProQuest Central
TI  - ProQuest study
JF  - Some Journal
T2  - Other Title
PY  - 2021
ER  -
"""

RIS_ZOTERO = """TY  - JOUR
TI  - Zotero export
DA  - 2023/05/01/
M3  - 10.5001/zot
T2  - Zotero Journal
ER  -
"""


def test_ris_multiple_records_and_types():
    recs = parse_ris(RIS_MULTI)
    assert len(recs) == 3
    assert [r.doc_type for r in recs] == ["article", "conference", "chapter"]
    assert recs[2].year == 2019          # Y1 fallback


def test_ris_record_without_er_is_still_parsed():
    recs = parse_ris(RIS_NO_ER)
    assert len(recs) == 1 and recs[0].doi == "10.5001/x"


def test_ris_empty_and_garbage_input():
    assert parse_ris("") == []
    assert parse_ris("this is not RIS at all\njust prose\n") == []


def test_ris_dialect_detection_all_vendors():
    assert detect_dialect(RIS_EBSCO) == "ebsco"
    assert detect_dialect(RIS_PROQUEST) == "proquest"
    assert detect_dialect(RIS_ZOTERO) == "zotero"
    assert detect_dialect("DB  - Embase\n") == "embase"
    assert detect_dialect("DB  - WOS\n") == "wos"
    assert detect_dialect("TY  - JOUR\n") == "generic"


def test_ris_ebsco_pmid_from_an():
    r = parse_ris(RIS_EBSCO)[0]
    assert r.pmid == "12345678"
    assert r.journal == "Business Source Journal"     # JF priority for EBSCO
    # the specific EBSCO database is recorded when the export names it,
    # which PRISMA-S Item 1 requires (platform vs database distinction)
    assert r.source == "Business Source"


def test_ris_proquest_journal_priority():
    assert parse_ris(RIS_PROQUEST)[0].journal == "Some Journal"


def test_ris_zotero_doi_from_m3_is_not_picked_up():
    """M3 holds the DOI only in the Scopus mapping; Zotero DOIs land in DO."""
    r = parse_ris(RIS_ZOTERO)[0]
    assert r.year == 2023 and r.journal == "Zotero Journal"
    assert r.doi == ""                     # documents current behaviour


def test_ris_source_name_override():
    r = parse_ris(RIS_MULTI, source_name="Embase")[0]
    assert r.source == "Embase"


def test_ris_file_roundtrip_with_bom(tmp_path):
    p = tmp_path / "x.ris"
    p.write_text("\ufeff" + RIS_MULTI, encoding="utf-8")
    recs = parse_ris_file(str(p))
    assert len(recs) == 3 and recs[0].title == "First record"


def test_ris_page_range_not_double_joined():
    text = "TY  - JOUR\nTI  - T\nSP  - 10-20\nEP  - 20\nER  -\n"
    assert parse_ris(text)[0].pages == "10-20"


# --------------------------------------------------------------- WoS
WOS_TWO = """FN Clarivate Analytics Web of Science
VR 1.0
PT J
AU Alpha, A
TI First WoS record
SO JOURNAL ONE
DT Review
DE kw1; kw2
ID kw3
AB Abstract line one
   continued line two
SN 1111-1111
EI 2222-2222
PY 2020
BP 1
EP 10
DI 10.5001/w1
PM 11111111
TC 5
UT WOS:000000000001
ER

PT J
AU Beta, B
TI Second WoS record
SO JOURNAL TWO
DT Proceedings Paper
PY 2021
AR e12345
UT WOS:000000000002
ER

EF
"""


def test_wos_two_records_continuations_and_keywords():
    recs = parse_wos(WOS_TWO)
    assert len(recs) == 2
    a, b = recs
    assert a.abstract == "Abstract line one continued line two"
    assert a.keywords == ["kw1", "kw2", "kw3"]
    assert a.doc_type == "review" and a.issn == "1111-1111"
    assert a.pages == "1-10" and a.cited_by == 5
    assert b.doc_type == "conference" and b.pages == "e12345"   # AR fallback
    assert b.cited_by is None


def test_wos_empty_and_headers_only():
    assert parse_wos("") == []
    assert parse_wos("FN Clarivate\nVR 1.0\nEF\n") == []


def test_wos_file_parsing(tmp_path):
    p = tmp_path / "wos.txt"
    p.write_text(WOS_TWO, encoding="utf-8")
    assert len(parse_wos_file(str(p), source_name="WoS CC")) == 2
    assert parse_wos_file(str(p))[0].source == "Web of Science"


def test_wos_unknown_doctype_passes_through_lowercased():
    txt = "PT J\nTI T\nDT Data Paper\nPY 2020\nER\n"
    assert parse_wos(txt)[0].doc_type == "data paper"


# -------------------------------------------------------------- nbib
NBIB_TWO = """PMID- 111
DP  - 2020 Jan
TI  - First nbib record.
AB  - Abstract with a
      continuation line.
FAU - Alpha, Anna
AU  - Alpha A
JT  - Journal One
VI  - 1
IP  - 2
PG  - 3-4
AID - 10.5001/n1 [doi]
IS  - 1234-5678 (Print)
PT  - Journal Article
LA  - eng
MH  - Humans*
OT  - keyword

PMID- 222
DP  - 2021
TI  - Second nbib record.
TA  - JrnlTwo
PT  - Letter
"""


def test_nbib_two_records_and_field_fallbacks():
    recs = parse_nbib(NBIB_TWO)
    assert len(recs) == 2
    a, b = recs
    assert a.abstract == "Abstract with a continuation line."
    assert a.doi == "10.5001/n1"        # AID fallback when LID absent
    assert a.issn == "1234-5678" and a.pages == "3-4"
    assert a.authors == ["Alpha, Anna"]
    assert a.keywords == ["Humans", "keyword"]   # MeSH asterisk stripped
    assert b.journal == "JrnlTwo" and b.doc_type == "letter"


def test_nbib_empty_input_and_file(tmp_path):
    assert parse_nbib("") == []
    p = tmp_path / "x.nbib"
    p.write_text(NBIB_TWO, encoding="utf-8")
    assert len(parse_nbib_file(str(p))) == 2


def test_nbib_record_without_title_but_with_pmid_is_kept():
    recs = parse_nbib("PMID- 999\nPT  - Journal Article\n")
    assert len(recs) == 1 and recs[0].pmid == "999"


# -------------------------------------------------------------- query
def test_query_single_block_no_filters():
    q = SearchQuery(blocks=[["digital twin"]])
    assert q.to_scopus() == 'TITLE-ABS-KEY("digital twin")'
    assert q.to_pubmed() == '("digital twin"[Title/Abstract])'
    assert q.to_openalex_filters() == {
        "title_and_abstract.search": '("digital twin")'}


def test_query_title_only_mode():
    q = SearchQuery(blocks=[["ai"]], title_only=True)
    assert "TITLE(" in q.to_scopus() and "TITLE-ABS-KEY" not in q.to_scopus()
    assert "[Title]" in q.to_pubmed()
    assert "title.search" in q.to_openalex_filters()


def test_query_empty_blocks_are_skipped():
    q = SearchQuery(blocks=[[], ["ai"], []])
    assert q.to_scopus() == 'TITLE-ABS-KEY("ai")'


def test_query_unsupported_doctypes_warn_per_backend():
    q = SearchQuery(blocks=[["ai"]], doc_types=["preprint", "dataset"])
    q.compile_all()
    joined = " ".join(q.warnings)
    assert "Scopus: unsupported doc_type 'preprint'" in joined
    assert "PubMed: unsupported doc_type 'preprint'" in joined
    assert "OpenAlex: unsupported doc_type 'dataset'" in joined
    assert "Crossref: unsupported doc_type 'dataset'" in joined


def test_query_compile_all_dedupes_warnings():
    q = SearchQuery(blocks=[["ai"]], doc_types=["dataset"], languages=["en"])
    q.compile_all()
    out = q.compile_all()
    assert len(out["warnings"]) == len(set(out["warnings"]))


def test_query_crossref_flattens_and_warns_about_language():
    q = SearchQuery(blocks=[["a", "b", "c", "d"], ["e"]], languages=["pl"])
    p = q.to_crossref_params()
    assert "d" not in p["query.bibliographic"]      # only first 3 per block
    assert any("language filter not reliable" in w for w in q.warnings)


def test_query_quotes_and_commas_are_sanitized():
    q = SearchQuery(blocks=[['"quoted", term']])
    s = q.to_scopus()
    assert s.count('"') == 2 and "," not in s


def test_query_language_mapping_unknown_code_passthrough():
    """PubMed passes an unknown code through; Scopus must not.

    Measured against the live Search API: LANGUAGE() takes English language
    names and an unrecognised value matches zero records instead of raising,
    so emitting LANGUAGE(xx) would silently empty the entire search.  Scopus
    therefore drops the clause and records a warning, while PubMed - which
    rejects an unknown [la] tag visibly - keeps the passthrough.
    """
    q = SearchQuery(blocks=[["ai"]], languages=["xx"])
    s = q.to_scopus()
    assert "LANGUAGE" not in s
    assert any("xx" in w and "zero records" in w for w in q.warnings)
    assert "xx[la]" in q.to_pubmed()


def test_scopus_year_clause_is_parenthesized():
    q = SearchQuery(blocks=[["ai"]], years=(2015, 2026),
                    doc_types=["article", "review"])
    s = q.to_scopus()
    assert "(PUBYEAR > 2014 AND PUBYEAR < 2027)" in s
