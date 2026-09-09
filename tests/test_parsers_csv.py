"""CSV export parser: per-vendor header detection and field mapping."""
import pytest

from corpusslr import detect_csv_dialect, parse_csv_export
from corpusslr.parsers.csv_exports import parse_csv_export_file

# --------------------------------------------------------------------------
# Header rows copied from real vendor exports
# --------------------------------------------------------------------------

SCOPUS_HEADER = ('"Authors","Author full names","Author(s) ID","Title","Year",'
                 '"Source title","Volume","Issue","Art. No.","Page start",'
                 '"Page end","Page count","Cited by","DOI","Link","Abstract",'
                 '"Author Keywords","Index Keywords","ISSN","Document Type",'
                 '"Publication Stage","Open Access",'
                 '"Language of Original Document","EID"')

SCOPUS_CSV = "\ufeff" + SCOPUS_HEADER + "\n" + (
    '"Kowalski J.; Nowak A.; Wr\u00f3bel \u0141.",'
    '"Kowalski, Jan (57123456);Nowak, Anna (57123457)","57123456",'
    '"Artificial intelligence adoption in small firms","2024.0",'
    '"Journal of Business Research","170","3","","114","128","15","12",'
    '"10.1016/j.jbusres.2024.001","https://www.scopus.com/x",'
    '"This study examines AI adoption drivers.",'
    '"artificial intelligence; SME","Artificial intelligence; Small firms",'
    '"01482963","Article","Final","All Open Access; Gold","English",'
    '"2-s2.0-85123456789"\n'
    '"Smith J.","Smith, John (1)","1","A second paper","2023",'
    '"Technovation","5","","","1","","","0","10.5001/second","","","","",'
    '"","Review","Final","","English","2-s2.0-85000000002"\n')

WOS_HEADER = ("Publication Type\tAuthors\tAuthor Full Names\tArticle Title\t"
              "Source Title\tDocument Type\tAuthor Keywords\tKeywords Plus\t"
              "Abstract\tISSN\teISSN\tPublication Year\tVolume\tIssue\t"
              "Start Page\tEnd Page\tDOI\tPubmed Id\t"
              "Times Cited, All Databases\tUT (Unique WOS ID)\t"
              "Open Access Designations\tLanguage")

WOS_CSV = WOS_HEADER + "\n" + (
    "J\tWrobel, L; Muller, HJ\tWr\u00f3bel, \u0141ukasz; M\u00fcller, "
    "Hans-J\u00f6rg\tUczenie maszynowe w przegl\u0105dach\t"
    "PRZEGL\u0104D ORGANIZACJI\tReview\tmachine learning; SLR\t"
    "SCREENING; AUTOMATION\tAbstrakt badania.\t0137-7221\t2544-0322\t2023\t"
    "12\t4\t101\t118\t10.33141/po.2023.04.01\t37123456\t7\t"
    "WOS:001200000001\tgold\tPolish\n")

IEEE_HEADER = ('"Document Title","Authors","Author Affiliations",'
               '"Publication Title","Date Added To Xplore",'
               '"Publication Year","Volume","Issue","Start Page","End Page",'
               '"Abstract","ISSN","ISBNs","DOI","Funding Information",'
               '"PDF Link","Author Keywords","IEEE Terms",'
               '"INSPEC Controlled Terms","Article Citation Count",'
               '"Reference Count","License","Online Date","Issue Date",'
               '"Meeting Date","Publisher","Document Identifier"')

IEEE_CSV = IEEE_HEADER + "\n" + (
    '"Edge {AI} for federated screening","J. Smith; A. Nowak; T. Nguyen",'
    '"MIT; UW","IEEE Access","1 Jan 2024","2024","12","","1","14",'
    '"We present edge inference for screening.","2169-3536","",'
    '"10.1109/ACCESS.2024.1234567","NSF",'
    '"https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=10412345",'
    '"edge computing;federated learning","Cloud computing;Servers",'
    '"Learning (artificial intelligence)","3","41","CCBY","1 Jan 2024",'
    '"2024","","IEEE","IEEE Journals"\n')

DIMENSIONS_HEADER = ("Publication ID;DOI;PMID;Title;Abstract;"
                     "Acknowledgements;Funding;Source title;Anthology title;"
                     "Publisher;ISSN;MeSH terms;PubYear;Volume;Issue;"
                     "Pagination;Open Access;Publication Type;Authors;"
                     "Times cited;Dimensions URL")

DIMENSIONS_CSV = DIMENSIONS_HEADER + "\n" + (
    "pub.1234567890;10.1038/s41586-022-00001-1;35123456;"
    "Deep learning for protein folding;We describe a model.;;;"
    "Nature;;Springer Nature;0028-0836;Machine Learning;2022;605;7909;"
    "123-129;All OA, Green, Published;Article;"
    '"Jumper, John; Hassabis, Demis";4421;'
    "https://app.dimensions.ai/details/publication/pub.1234567890\n")

EBSCO_HEADER = ("Title,Authors,Journal,Year,Volume,Issue,Pages,DOI,"
                "Accession Number,Abstract,ISSN,Subjects,Document Type,"
                "Language,PLink")

EBSCO_CSV = EBSCO_HEADER + "\n" + (
    '"Consumer trust in AI advisors",'
    '"Andersson, \u00c5sa and Lindqvist, Bj\u00f8rn",'
    '"Journal of Consumer Research",2021,48,1,"55-70","10.1093/jcr/ucab001",'
    '"bth-149203311","We study trust.","0093-5301",'
    '"artificial intelligence; consumer trust","Article","English",'
    '"http://search.ebscohost.com/login.aspx?direct=true&db=bth&AN=149203311"\n')


# --------------------------------------------------------------------------
# Dialect detection
# --------------------------------------------------------------------------

@pytest.mark.parametrize("header,expected", [
    (SCOPUS_HEADER, "scopus"),
    (WOS_HEADER, "wos"),
    (IEEE_HEADER, "ieee"),
    (DIMENSIONS_HEADER, "dimensions"),
    (EBSCO_HEADER, "ebsco"),
])
def test_detect_dialect_from_header_line(header, expected):
    assert detect_csv_dialect(header) == expected


@pytest.mark.parametrize("cells,expected", [
    (["Title", "Authors", "Year", "DOI", "EID", "Cited by",
      "Index Keywords"], "scopus"),
    (["Article Title", "UT (Unique WOS ID)", "Keywords Plus"], "wos"),
    (["Document Title", "IEEE Terms", "Publication Title"], "ieee"),
    (["Title", "PubYear", "Publication ID", "Times cited"], "dimensions"),
    (["Title", "Authors", "Journal", "Accession Number", "PLink"], "ebsco"),
    (["Title", "Authors", "Year"], "generic"),
    ([], "generic"),
    (["", "", ""], "generic"),
])
def test_detect_dialect_from_cells(cells, expected):
    assert detect_csv_dialect(cells) == expected


def test_detect_dialect_none_and_case_insensitivity():
    assert detect_csv_dialect(None) == "generic"
    assert detect_csv_dialect(["title", "AUTHORS", "eid", "cited by",
                               "index keywords"]) == "scopus"
    assert detect_csv_dialect(["\ufeffTitle", "EID", "Cited by",
                               "Index Keywords"]) == "scopus"


# --------------------------------------------------------------------------
# Scopus
# --------------------------------------------------------------------------

def test_scopus_mapping():
    recs = parse_csv_export(SCOPUS_CSV)
    assert len(recs) == 2
    r = recs[0]
    assert r.raw["dialect"] == "scopus"
    assert r.title == "Artificial intelligence adoption in small firms"
    assert r.authors == ["Kowalski, J.", "Nowak, A.", "Wr\u00f3bel, \u0141."]
    assert r.year == 2024                      # "2024.0"
    assert r.journal == "Journal of Business Research"
    assert r.doi == "10.1016/j.jbusres.2024.001"
    assert r.volume == "170" and r.issue == "3"
    assert r.pages == "114-128"
    assert r.issn == "01482963"
    assert r.cited_by == 12
    assert r.doc_type == "article"
    assert r.language == "english"
    assert r.open_access is True
    assert r.scopus_id == "2-s2.0-85123456789"
    assert r.source_id == "2-s2.0-85123456789"
    # index keywords are appended after author keywords, case-insensitively
    # deduplicated ("Artificial intelligence" is already present)
    assert r.keywords == ["artificial intelligence", "SME", "Small firms"]


def test_scopus_second_row_sparse_fields():
    r = parse_csv_export(SCOPUS_CSV)[1]
    assert r.doc_type == "review"
    assert r.pages == "1"           # only Page start present
    assert r.cited_by == 0
    assert r.keywords == []
    assert r.open_access is None
    assert r.abstract == ""


# --------------------------------------------------------------------------
# Web of Science
# --------------------------------------------------------------------------

def test_wos_tab_separated_mapping():
    r = parse_csv_export(WOS_CSV)[0]
    assert r.raw["dialect"] == "wos"
    assert r.title == "Uczenie maszynowe w przegl\u0105dach"
    assert r.authors == ["Wr\u00f3bel, \u0141ukasz", "M\u00fcller, Hans-J\u00f6rg"]
    assert r.journal == "PRZEGL\u0104D ORGANIZACJI"
    assert r.year == 2023
    assert r.doi == "10.33141/po.2023.04.01"
    assert r.pmid == "37123456"
    assert r.pages == "101-118"
    assert r.cited_by == 7
    assert r.doc_type == "review"
    assert r.source_id == "WOS:001200000001"
    assert r.keywords == ["machine learning", "SLR", "SCREENING", "AUTOMATION"]
    assert r.open_access is True


# --------------------------------------------------------------------------
# IEEE Xplore
# --------------------------------------------------------------------------

def test_ieee_mapping():
    r = parse_csv_export(IEEE_CSV)[0]
    assert r.raw["dialect"] == "ieee"
    assert r.title == "Edge {AI} for federated screening"
    assert r.authors == ["Smith, J.", "Nowak, A.", "Nguyen, T."]
    assert r.journal == "IEEE Access"
    assert r.year == 2024
    assert r.pages == "1-14"
    assert r.doi == "10.1109/access.2024.1234567"
    assert r.cited_by == 3
    assert r.keywords == ["edge computing", "federated learning",
                          "Cloud computing", "Servers"]
    assert r.source_id == "10412345"      # arnumber recovered from PDF link


# --------------------------------------------------------------------------
# Dimensions
# --------------------------------------------------------------------------

def test_dimensions_semicolon_delimited():
    r = parse_csv_export(DIMENSIONS_CSV)[0]
    assert r.raw["dialect"] == "dimensions"
    assert r.title == "Deep learning for protein folding"
    assert r.year == 2022
    assert r.journal == "Nature"
    assert r.doi == "10.1038/s41586-022-00001-1"
    assert r.pmid == "35123456"
    assert r.pages == "123-129"
    assert r.cited_by == 4421
    assert r.source_id == "pub.1234567890"
    assert r.open_access is True
    assert r.doc_type == "article"


# --------------------------------------------------------------------------
# EBSCO
# --------------------------------------------------------------------------

def test_ebsco_mapping_and_and_separated_authors():
    r = parse_csv_export(EBSCO_CSV)[0]
    assert r.raw["dialect"] == "ebsco"
    assert r.authors == ["Andersson, \u00c5sa", "Lindqvist, Bj\u00f8rn"]
    assert r.journal == "Journal of Consumer Research"
    assert r.year == 2021
    assert r.source_id == "bth-149203311"
    assert r.doi == "10.1093/jcr/ucab001"
    assert r.keywords == ["artificial intelligence", "consumer trust"]
    assert r.doc_type == "article"


# --------------------------------------------------------------------------
# Degenerate and adversarial input
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["", "   ", "\n"])
def test_empty_input(text):
    assert parse_csv_export(text) == []


def test_header_only_file():
    assert parse_csv_export(SCOPUS_HEADER + "\n") == []
    assert parse_csv_export(EBSCO_HEADER) == []


def test_rows_without_title_and_doi_are_skipped():
    text = "Title,Authors,DOI\n,,\n,Someone,\nReal title,X,\n"
    recs = parse_csv_export(text)
    assert len(recs) == 1 and recs[0].title == "Real title"


def test_row_with_only_doi_is_kept():
    recs = parse_csv_export("Title,DOI\n,10.5001/only\n")
    assert len(recs) == 1 and recs[0].doi == "10.5001/only"


def test_single_column_file_does_not_crash_sniffer():
    recs = parse_csv_export("Title\nA lone title\nAnother title\n")
    assert [r.title for r in recs] == ["A lone title", "Another title"]


def test_semicolons_inside_quoted_abstract_do_not_change_delimiter():
    text = ('Title,Abstract,Year\n'
            '"A study","We compare A; B; C; and D across sites.",2020\n')
    r = parse_csv_export(text)[0]
    assert r.abstract == "We compare A; B; C; and D across sites."
    assert r.year == 2020


def test_embedded_newline_in_quoted_abstract():
    text = 'Title,Abstract\n"Multiline","line one\nline two"\n'
    r = parse_csv_export(text)[0]
    assert r.abstract == "line one line two"


def test_blank_and_duplicate_trailing_columns():
    text = 'Title,Authors,,\nA title,John Smith,,\n'
    r = parse_csv_export(text)[0]
    assert r.title == "A title" and r.authors == ["Smith, John"]


def test_bom_is_stripped_from_first_header():
    r = parse_csv_export("\ufeffTitle,Year\nBOM row,2020\n")[0]
    assert r.title == "BOM row" and r.year == 2020


def test_explicit_dialect_and_delimiter_override():
    recs = parse_csv_export(DIMENSIONS_CSV, dialect="generic", delimiter=";")
    assert recs[0].raw["dialect"] == "generic"
    assert recs[0].title == "Deep learning for protein folding"


def test_generic_fallback_recovers_vendor_columns():
    """A vendor map must not hide columns the generic map knows about."""
    text = ("Article Title,Authors,UT (Unique WOS ID),Keywords Plus,PMID\n"
            "T,Smith J,WOS:1,kw,31234567\n")
    r = parse_csv_export(text)[0]
    assert r.raw["dialect"] == "wos"
    assert r.pmid == "31234567"


def test_source_name_override():
    recs = parse_csv_export(SCOPUS_CSV, source_name="Scopus")
    assert all(r.source == "Scopus" for r in recs)


def test_year_variants():
    text = "Title,Year\nA,2024.0\nB,2024\nC,2024-05-01\nD,\nE,n.d.\n"
    years = [r.year for r in parse_csv_export(text)]
    assert years == [2024, 2024, 2024, None, None]


def test_cited_by_with_thousand_separator():
    r = parse_csv_export("Title,Cited by\nA,\"1,234\"\n")[0]
    assert r.cited_by == 1234


def test_doi_recovered_from_link_column():
    r = parse_csv_export(
        "Title,Link\nA,https://doi.org/10.1234/abc\n")[0]
    assert r.doi == "10.1234/abc"


def test_pipe_delimited_export():
    text = "Title|Authors|Year\nPiped title|Smith, John|2020\n"
    r = parse_csv_export(text)[0]
    assert r.title == "Piped title" and r.year == 2020


# --------------------------------------------------------------------------
# File variants
# --------------------------------------------------------------------------

def test_parse_file(tmp_path):
    p = tmp_path / "scopus.csv"
    p.write_text(SCOPUS_CSV, encoding="utf-8")
    recs = parse_csv_export_file(str(p))
    assert len(recs) == 2 and recs[0].scopus_id == "2-s2.0-85123456789"


def test_parse_file_utf8_bom_written_by_excel(tmp_path):
    p = tmp_path / "excel.csv"
    p.write_text(EBSCO_CSV, encoding="utf-8-sig")
    recs = parse_csv_export_file(str(p))
    assert len(recs) == 1 and recs[0].raw["dialect"] == "ebsco"


def test_parse_empty_file(tmp_path):
    p = tmp_path / "empty.csv"
    p.write_text("", encoding="utf-8")
    assert parse_csv_export_file(str(p)) == []


def test_parse_file_cp1252_fallback(tmp_path):
    p = tmp_path / "cp1252.csv"
    p.write_bytes("Title,Year\nCaf\u00e9 study,2020\n".encode("cp1252"))
    recs = parse_csv_export_file(str(p))
    assert len(recs) == 1 and recs[0].year == 2020


# --------------------------------------------------------------------------
# String input: parse_csv_export(text) was unusable before 1.3.1 -- StringIO's
# newline="" left the line terminators in the buffer, so every dialect raised
# "new-line character seen in unquoted field", and detect_csv_dialect() handed
# csv.reader the whole export as a single line.
# --------------------------------------------------------------------------
STR_SCOPUS_CSV = (
    'Authors,Author full names,Title,Year,Source title,Volume,Issue,'
    'Page start,Page end,DOI,EID\n'
    '"Smith A.","Smith, Alan (123)","A study of things",2024,"J Test",'
    '1,2,10,20,10.5001/x,2-s2.0-1\n'
)
STR_IEEE_CSV = (
    'Document Title,Authors,Publication Title,Publication_Year,Volume,Issue,'
    'Start Page,End Page,Abstract,ISSN,DOI\n'
    '"A study of things","A. Smith","IEEE Trans",2024,1,2,10,20,'
    '"Abstract here",1234-5678,10.5001/y\n'
)
STR_DIMENSIONS_CSV = (
    'Rank,Publication ID,DOI,PMID,Title,Abstract,Source title,PubYear,'
    'Volume,Issue,Pagination,Authors\n'
    '1,pub.1,10.5001/z,123,"A study of things","Abs","J Test",2024,1,2,'
    '10-20,"Smith, A"\n'
)


@pytest.mark.parametrize("text,dialect,doi", [
    (STR_SCOPUS_CSV, "scopus", "10.5001/x"),
    (STR_IEEE_CSV, "ieee", "10.5001/y"),
    (STR_DIMENSIONS_CSV, "dimensions", "10.5001/z"),
])
def test_parse_csv_export_accepts_a_string(text, dialect, doi):
    assert detect_csv_dialect(text) == dialect
    recs = parse_csv_export(text)
    assert len(recs) == 1
    assert recs[0].doi == doi
    assert recs[0].year == 2024
    assert recs[0].title == "A study of things"


def test_detect_csv_dialect_accepts_a_whole_export_not_just_the_header():
    """Callers fingerprint a file's text, not a hand-extracted header line."""
    assert detect_csv_dialect(STR_SCOPUS_CSV) == "scopus"
    assert detect_csv_dialect(STR_SCOPUS_CSV.splitlines()[0]) == "scopus"
    assert detect_csv_dialect(STR_SCOPUS_CSV.splitlines()[0].split(",")) == "scopus"


def test_csv_export_handles_crlf_and_cr_line_endings():
    """Windows-exported Scopus/IEEE files carry \\r\\n; old Mac tools carry \\r."""
    for ending in ("\r\n", "\r"):
        recs = parse_csv_export(STR_SCOPUS_CSV.replace("\n", ending))
        assert len(recs) == 1 and recs[0].doi == "10.5001/x"


def test_csv_export_preserves_a_newline_inside_a_quoted_field():
    """An abstract spanning lines is one field, not two rows."""
    recs = parse_csv_export('Title,Abstract,DOI\r\n'
                            '"A study","line one\r\nline two",10.5001/e\r\n')
    assert len(recs) == 1
    assert "line one" in recs[0].abstract and "line two" in recs[0].abstract


def test_csv_export_string_and_file_paths_agree(tmp_path):
    p = tmp_path / "scopus.csv"
    p.write_text(STR_SCOPUS_CSV, encoding="utf-8")
    from corpusslr import parse_csv_export_file
    a = parse_csv_export(STR_SCOPUS_CSV)
    b = parse_csv_export_file(str(p))
    assert [r.doi for r in a] == [r.doi for r in b]
    assert [r.title for r in a] == [r.title for r in b]


# --------------------------------------------------------------------------
# Affiliations from a file export.
#
# Record.affiliations was added for the API clients, but no dialect map listed
# the column, so importing from a vendor CSV silently dropped every address.
# Measured on a real 597-record Scopus export: 595 rows carried affiliations,
# 0 survived the parse, and bibliometrix's institutional collaboration network
# (C1 -> AU_UN) came back "Matrix is empty!!". The addresses are the whole
# input to that analysis, so losing them removes it without any error.
# --------------------------------------------------------------------------

def test_scopus_export_affiliations_reach_the_record():
    src = ('"Authors","Title","Year","Source title","DOI","Affiliations"\r\n'
           '"Kowalski J.","A study","2024","J Test","10.5001/a",'
           '"Dept A, Univ One, Warsaw, Poland; Dept B, Univ Two, Krakow, Poland"\r\n')
    recs = parse_csv_export(src, dialect="scopus")
    assert len(recs) == 1
    assert recs[0].affiliations == ["Dept A, Univ One, Warsaw, Poland",
                                    "Dept B, Univ Two, Krakow, Poland"], (
        "addresses must split on '; ' only; splitting on the comma would "
        "shred one address into department, university, city and country")


def test_wos_export_addresses_reach_the_record():
    src = ('"Authors","Article Title","Publication Year","Source Title","DOI","Addresses"\r\n'
           '"Nowak A.","Another study","2023","J Test","10.5001/b",'
           '"[Nowak, A] Univ Three, Dept C, Gdansk, Poland"\r\n')
    recs = parse_csv_export(src, dialect="wos")
    assert recs[0].affiliations == ["[Nowak, A] Univ Three, Dept C, Gdansk, Poland"]


def test_an_empty_affiliation_column_yields_an_empty_list_not_a_blank_entry():
    src = ('"Authors","Title","Year","Source title","DOI","Affiliations"\r\n'
           '"Lee S.","Third study","2022","J Test","10.5001/c",""\r\n')
    recs = parse_csv_export(src, dialect="scopus")
    assert recs[0].affiliations == [], (
        "a blank cell must not become [''], which would be counted as one "
        "affiliation by anything that reads len()")


def test_affiliations_survive_the_scopus_round_trip():
    from corpusslr import Record, to_scopus_csv
    import os as _os
    import tempfile
    rec = Record(title="Round trip", doi="10.5001/rt", year=2024,
                 journal="J Test", authors=["Kowalski, J"],
                 affiliations=["Dept A, Univ One, Warsaw, Poland",
                               "Dept B, Univ Two, Krakow, Poland"])
    path = _os.path.join(tempfile.mkdtemp(), "s.csv")
    to_scopus_csv([rec], path)
    with open(path, encoding="utf-8-sig") as fh:
        back = parse_csv_export(fh.read(), dialect="scopus")
    assert back[0].affiliations == rec.affiliations
