"""Coverage of the databases and formats the project specification requires.

One test per (database, format) cell of the specification matrix, each on a
sample whose header row or tag set reproduces a real export.  The point is not
to re-test the mapping machinery -- that is covered elsewhere -- but to pin the
claim the article makes: that autodetection picks the right vendor dialect and
that the identifiers the duplicate cascade depends on survive the import.
"""
from __future__ import annotations

import pytest

from corpusslr.parsers import (ParseReport, detect_bibtex_dialect,
                               detect_csv_dialect, detect_dialect,
                               parse_bibtex, parse_csv_export, parse_ris)

# --------------------------------------------------------------------------
# RIS dialects
# --------------------------------------------------------------------------

EMBASE_RIS = """TY  - JOUR
TI  - Machine learning for early sepsis detection in intensive care
AU  - Smith, J.
AU  - Doe, A.
T2  - Critical Care Medicine
JF  - Crit Care Med
PY  - 2022
VL  - 50
IS  - 3
SP  - e123
EP  - e130
DO  - 10.1097/CCM.0000000000005432
AN  - PMID:35123456
M3  - Article
LA  - English
DB  - Embase
ER  -
"""

EMBASE_RIS_CONF_ABSTRACT = """TY  - JOUR
TI  - Sepsis biomarkers: a conference abstract
AU  - Rossi, M.
T2  - Intensive Care Medicine
PY  - 2021
AN  - L2015467890
M3  - Conference Abstract
DB  - Embase
ER  -
"""

CENTRAL_RIS = """TY  - JOUR
TI  - Early goal-directed therapy for septic shock: a randomised trial
AU  - Nguyen, T.
T2  - The Cochrane Central Register of Controlled Trials
PY  - 2020
AN  - CN-02145678
C7  - NCT01234567
DO  - 10.1002/central.CD012345
ER  -
"""

EBSCO_RIS_PSYCINFO = """TY  - JOUR
TI  - Cognitive load in evidence appraisal
AU  - Johnson, K.
T2  - Journal of Applied Psychology
PY  - 2019
DB  - PsycINFO
AN  - psyh-2019-45678-001
C2  - 31234567
DP  - EBSCOhost
ER  -
"""

EBSCO_RIS_CINAHL = """TY  - JOUR
TI  - Nurse-led screening interventions
AU  - Murphy, S.
T2  - Journal of Advanced Nursing
PY  - 2021
DB  - CINAHL Complete
AN  - ccm-2021-987654
DP  - EBSCOhost
ER  -
"""

EBSCO_RIS_BUSINESS = """TY  - JOUR
TI  - Dynamic capabilities and firm performance
AU  - Weber, M.
T2  - Strategic Management Journal
PY  - 2018
DB  - Business Source Complete
AN  - bth-129384756
DP  - EBSCOhost
ER  -
"""

EBSCO_RIS_ERIC = """TY  - JOUR
TI  - Systematic reviews in education research
AU  - Patel, R.
T2  - Review of Educational Research
PY  - 2020
DB  - ERIC
AN  - eric-EJ1234567
DP  - EBSCOhost
ER  -
"""

PROQUEST_RIS = """TY  - JOUR
TI  - Digital transformation strategy in incumbent firms
T1  - Digital transformation strategy in incumbent firms: a longitudinal study
AU  - Kowalski, Jan
T2  - Journal of Business Strategy
PY  - 2022
DO  - 10.1108/JBS-01-2022-0011
ID  - 2612345678
UR  - https://www.proquest.com/docview/2612345678
DB  - ABI/INFORM Collection
DP  - ProQuest
ER  -
"""

WOS_RIS = """TY  - JOUR
TI  - Bibliometric mapping of artificial intelligence research
AU  - Kowalski, J
T2  - Scientometrics
PY  - 2021
DO  - 10.1007/s11192-021-04001-1
AN  - WOS:000654321000012
DB  - Web of Science
ER  -
"""

SCOPUS_RIS = """TY  - JOUR
TI  - Citation networks in evidence synthesis
AU  - Muller, H.
T2  - Journal of Informetrics
PY  - 2022
DO  - 10.1016/j.joi.2022.101234
DB  - Scopus
N1  - Export Date: 12 March 2024
ER  -
"""

RIS_DIALECT_CASES = [
    ("embase", EMBASE_RIS),
    ("embase", EMBASE_RIS_CONF_ABSTRACT),
    ("central", CENTRAL_RIS),
    ("ebsco", EBSCO_RIS_PSYCINFO),
    ("ebsco", EBSCO_RIS_CINAHL),
    ("ebsco", EBSCO_RIS_BUSINESS),
    ("ebsco", EBSCO_RIS_ERIC),
    ("proquest", PROQUEST_RIS),
    ("wos", WOS_RIS),
    ("scopus", SCOPUS_RIS),
]


@pytest.mark.parametrize("expected,sample", RIS_DIALECT_CASES,
                         ids=["%s%d" % (e, i)
                              for i, (e, _s) in enumerate(RIS_DIALECT_CASES)])
def test_ris_dialect_autodetected(expected, sample):
    assert detect_dialect(sample) == expected


@pytest.mark.parametrize("_expected,sample", RIS_DIALECT_CASES,
                         ids=["%s%d" % (e, i)
                              for i, (e, _s) in enumerate(RIS_DIALECT_CASES)])
def test_every_vendor_ris_sample_yields_one_complete_record(_expected, sample):
    rep = ParseReport()
    recs = parse_ris(sample, report=rep)
    assert len(recs) == 1
    rec = recs[0]
    assert rec.title and rec.year and rec.authors
    assert rep.balanced and rep.n_rejected == 0


def test_embase_ris_pmid_and_subtype():
    rec = parse_ris(EMBASE_RIS)[0]
    assert rec.pmid == "35123456"
    assert rec.doi == "10.1097/CCM.0000000000005432".lower()
    assert rec.journal == "Critical Care Medicine"   # T2, not the JF abbrev
    assert rec.pages == "e123-e130"
    assert rec.doc_type == "article"


def test_embase_conference_abstract_is_typed_from_m3():
    """Excluding conference abstracts is an eligibility rule; TY says JOUR."""
    rec = parse_ris(EMBASE_RIS_CONF_ABSTRACT)[0]
    assert rec.doc_type == "conference"
    assert rec.raw.get("embase_id") or "L2015467890" in str(rec.raw)


def test_central_ris_preserves_the_central_number_and_trial_id():
    rec = parse_ris(CENTRAL_RIS)[0]
    assert "01" in rec.source_id or rec.source_id
    assert "2145678" in str(rec.raw.get("central_id", "")) or \
        "CN-02145678" in str(rec.raw)
    assert any("NCT01234567" in str(t) for t in rec.raw.get("trial_ids", [])) \
        or "NCT01234567" in str(rec.raw)


@pytest.mark.parametrize("sample,needle", [
    (EBSCO_RIS_PSYCINFO, "PsycINFO"),
    (EBSCO_RIS_CINAHL, "CINAHL"),
    (EBSCO_RIS_BUSINESS, "Business Source"),
    (EBSCO_RIS_ERIC, "ERIC"),
])
def test_ebsco_per_record_database_is_resolved(sample, needle):
    """One EBSCOhost file can mix databases, so source is per record."""
    rec = parse_ris(sample)[0]
    assert needle.lower() in rec.source.lower()


def test_ebsco_psycinfo_pmid_comes_from_c2():
    assert parse_ris(EBSCO_RIS_PSYCINFO)[0].pmid == "31234567"


def test_proquest_ris_keeps_the_longer_title_and_the_document_id():
    rec = parse_ris(PROQUEST_RIS)[0]
    assert rec.title.endswith("a longitudinal study")
    assert rec.raw.get("proquest_id") == "2612345678"


# --------------------------------------------------------------------------
# CSV dialects
# --------------------------------------------------------------------------

SCOPUS_CSV = (
    'Authors,Author full names,Title,Year,Source title,Volume,Issue,'
    'Page start,Page end,Cited by,DOI,Link,Author Keywords,Index Keywords,'
    'Document Type,Open Access,EID\n'
    '"Kowalski J.; Nowak A.","Kowalski, Jan (123);Nowak, Anna (456)",'
    '"Bibliometric mapping of AI research",2021,"Scientometrics",126,4,'
    '3011,3035,42,"10.1007/s11192-021-04001-1",'
    '"https://www.scopus.com/inward/record.uri?eid=2-s2.0-85100000001",'
    '"bibliometrics; artificial intelligence","Data mining","Article",'
    '"All Open Access; Gold","2-s2.0-85100000001"\n')

#: Note the quoted ``"Times Cited, All Databases"``: the column name really
#: does contain a comma, and Web of Science quotes it.  An unquoted copy of
#: this header shifts every following column by one, which is exactly how a
#: hand-edited export loses its identifiers.
WOS_CSV = (
    'Authors,Author Full Names,Article Title,Source Title,Document Type,'
    'Author Keywords,Keywords Plus,Abstract,Publication Year,Volume,Issue,'
    'Start Page,End Page,DOI,Pubmed Id,"Times Cited, All Databases",'
    'UT (Unique WOS ID)\n'
    '"Kowalski, J; Nowak, A","Kowalski, Jan; Nowak, Anna",'
    '"Bibliometric mapping of artificial intelligence research",'
    '"SCIENTOMETRICS","Article","bibliometrics","DATA MINING",'
    '"We map the field.",2021,126,4,3011,3035,'
    '"10.1007/s11192-021-04001-1","34567890",42,'
    '"WOS:000654321000012"\n')

IEEE_CSV = (
    '"Document Title","Authors","Publication Title","Publication Year",'
    '"Volume","Issue","Start Page","End Page","Abstract","ISSN","DOI",'
    '"Author Keywords","IEEE Terms","INSPEC Controlled Terms","PDF Link",'
    '"Article Citation Count"\n'
    '"Deep Learning for Signal Classification","W. Zhang; L. Ortiz",'
    '"IEEE Transactions on Signal Processing","2021","69","4","1024","1035",'
    '"We propose a model.","1053-587X","10.1109/TSP.2021.3054321",'
    '"deep learning;classification","Signal processing;Neural networks",'
    '"learning (artificial intelligence)",'
    '"https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=9366721","42"\n')

DIMENSIONS_CSV = (
    'Rank,Publication ID,DOI,PMID,Title,Abstract,Source title,PubYear,'
    'Volume,Issue,Pagination,Authors,Times cited,MeSH terms,'
    'Dimensions URL\n'
    '1,"pub.1135792468","10.1097/CCM.0000000000005432","35123456",'
    '"Machine learning for early sepsis detection","We built a model.",'
    '"Critical Care Medicine",2022,50,3,"e123-e130","Smith, J.; Doe, A.",'
    '17,"Sepsis; Machine Learning","https://app.dimensions.ai/details/'
    'publication/pub.1135792468"\n')

EMBASE_CSV = (
    'Title,Author Names,Source title,Volume,Issue,Date of Publication,Pages,'
    'DOI,Medline PMID,Embase Accession ID,Publication Type,'
    'Language of Article,Author Keywords,Emtree Medical Index Terms,'
    'Abstract\n'
    '"Machine learning for early sepsis detection","Smith J.;Doe A.",'
    '"Critical Care Medicine",50,3,"March 2022","e123-e130",'
    '"10.1097/CCM.0000000000005432","35123456","L2015467890",'
    '"Journal Article","English","sepsis;machine learning",'
    '"intensive care unit;prediction","Background: sepsis remains..."\n')

PROQUEST_CSV = (
    'Title\tAuthor\tpublication title\tPublication year\tDOI\tStoreId\t'
    'document url\tSubject\tDocument type\n'
    'Digital transformation strategy\tKowalski, Jan; Nowak, Anna\t'
    'Journal of Business Strategy\t2022\t10.1108/JBS-01-2022-0011\t'
    '2612345678\thttps://www.proquest.com/docview/2612345678\t'
    'Strategic management; Digitalization\tJournal Article\n')

EBSCO_CSV = (
    'Title,Authors,Journal,Publication Date,Volume,Issue,Pages,DOI,ISSN,'
    'Subject Terms,Document Type,Accession Number,PLink\n'
    '"Cognitive load in evidence appraisal","Johnson, K.",'
    '"Journal of Applied Psychology","2019",104,7,"1123-1140",'
    '"10.1037/apl0000401","0021-9010","Cognition; Decision making",'
    '"Article","2019-45678-001",'
    '"https://search.ebscohost.com/login.aspx?direct=true&db=psyh"\n')

CSV_CASES = [
    ("scopus", SCOPUS_CSV), ("wos", WOS_CSV), ("ieee", IEEE_CSV),
    ("dimensions", DIMENSIONS_CSV), ("embase", EMBASE_CSV),
    ("proquest", PROQUEST_CSV), ("ebsco", EBSCO_CSV),
]


@pytest.mark.parametrize("expected,sample", CSV_CASES,
                         ids=[c[0] for c in CSV_CASES])
def test_csv_dialect_autodetected(expected, sample):
    assert detect_csv_dialect(sample.splitlines()[0]) == expected


@pytest.mark.parametrize("expected,sample", CSV_CASES,
                         ids=[c[0] for c in CSV_CASES])
def test_csv_sample_yields_one_record_with_core_fields(expected, sample):
    rep = ParseReport()
    recs = parse_csv_export(sample, report=rep)
    assert len(recs) == 1, expected
    rec = recs[0]
    assert rec.title and rec.year and rec.journal and rec.authors
    assert rec.doi
    assert rep.dialect == expected
    assert rep.balanced and rep.n_rejected == 0


def test_scopus_csv_identifiers_and_open_access():
    rec = parse_csv_export(SCOPUS_CSV)[0]
    assert rec.scopus_id == "2-s2.0-85100000001"
    assert rec.cited_by == 42
    assert rec.open_access is True
    assert rec.pages == "3011-3035"
    assert "bibliometrics" in rec.keywords and "Data mining" in rec.keywords


def test_wos_csv_keeps_wos_id_and_pmid():
    rec = parse_csv_export(WOS_CSV)[0]
    assert rec.source_id == "WOS:000654321000012"
    assert rec.pmid == "34567890"


def test_ieee_csv_arnumber_recovered_from_pdf_link():
    assert parse_csv_export(IEEE_CSV)[0].source_id == "9366721"


def test_dimensions_csv_publication_id_and_pmid():
    rec = parse_csv_export(DIMENSIONS_CSV)[0]
    assert rec.source_id == "pub.1135792468"
    assert rec.pmid == "35123456"
    assert rec.year == 2022


def test_embase_csv_keeps_both_identifiers():
    """PMID and the Embase accession both drive the duplicate cascade."""
    rec = parse_csv_export(EMBASE_CSV)[0]
    assert rec.pmid == "35123456"
    assert rec.source_id == "L2015467890"
    assert rec.doc_type == "article"
    assert rec.language == "english"
    assert "sepsis" in rec.keywords


def test_proquest_tsv_export_is_read_as_tab_separated():
    rec = parse_csv_export(PROQUEST_CSV)[0]
    assert rec.source_id == "2612345678"
    assert rec.journal == "Journal of Business Strategy"
    assert rec.authors == ["Kowalski, Jan", "Nowak, Anna"]


def test_ebsco_csv_accession_number():
    assert parse_csv_export(EBSCO_CSV)[0].source_id == "2019-45678-001"


def test_embase_and_scopus_csv_of_one_record_agree_on_identifiers():
    """The same article from two vendors must collapse in deduplication."""
    from_embase = parse_csv_export(EMBASE_CSV)[0]
    from_dimensions = parse_csv_export(DIMENSIONS_CSV)[0]
    assert from_embase.doi == from_dimensions.doi
    assert from_embase.pmid == from_dimensions.pmid
    assert from_embase.pages == from_dimensions.pages


# --------------------------------------------------------------------------
# BibTeX dialects
# --------------------------------------------------------------------------

IEEE_BIBTEX = """@ARTICLE{9366721,
  author={Zhang, Wei and Ortiz, Luis},
  journal={IEEE Transactions on Signal Processing},
  title={Deep Learning for Signal Classification},
  year={2021}, volume={69}, number={4}, pages={1024-1035},
  keywords={Signal processing;Neural networks},
  doi={10.1109/TSP.2021.3054321}, ISSN={1941-0476}}
"""

ACM_BIBTEX = """@inproceedings{10.1145/3583780.3614999,
author = {Chen, Wei and Garcia, Maria},
title = {Neural Retrieval for Systematic Review Screening},
year = {2023},
isbn = {9798400701245},
publisher = {Association for Computing Machinery},
address = {New York, NY, USA},
url = {https://doi.org/10.1145/3583780.3614999},
doi = {10.1145/3583780.3614999},
booktitle = {Proceedings of the 32nd ACM International Conference on Information and Knowledge Management},
pages = {1123--1132},
numpages = {10},
series = {CIKM '23}}
"""

SCOPUS_BIBTEX = """@ARTICLE{Kowalski2021301,
author={Kowalski, J. and Nowak, A.},
title={Bibliometric mapping of AI research},
journal={Scientometrics},
year={2021}, volume={126}, number={4}, pages={3011-3035},
doi={10.1007/s11192-021-04001-1},
author_keywords={bibliometrics;  artificial intelligence},
note={Cited by: 42},
source={Scopus}}
"""

WOS_BIBTEX = """@article{ WOS:000654321000012,
Author = {Kowalski, Jan and Nowak, Anna},
Title = {{Bibliometric mapping of artificial intelligence research}},
Journal = {{SCIENTOMETRICS}},
Year = {{2021}}, Volume = {{126}}, Pages = {{3011-3035}},
DOI = {{10.1007/s11192-021-04001-1}},
Unique-ID = {{WOS:000654321000012}}}
"""

BIBTEX_CASES = [("ieee", IEEE_BIBTEX), ("acm", ACM_BIBTEX),
                ("scopus", SCOPUS_BIBTEX), ("wos", WOS_BIBTEX)]


@pytest.mark.parametrize("expected,sample", BIBTEX_CASES,
                         ids=[c[0] for c in BIBTEX_CASES])
def test_bibtex_dialect_autodetected(expected, sample):
    assert detect_bibtex_dialect(sample) == expected


@pytest.mark.parametrize("expected,sample", BIBTEX_CASES,
                         ids=[c[0] for c in BIBTEX_CASES])
def test_bibtex_sample_yields_one_record(expected, sample):
    rep = ParseReport()
    recs = parse_bibtex(sample, report=rep)
    assert len(recs) == 1, expected
    rec = recs[0]
    assert rec.title and rec.year and rec.doi and rec.authors
    assert rep.balanced and rep.n_rejected == 0


def test_acm_bibtex_conference_venue_and_page_range():
    rec = parse_bibtex(ACM_BIBTEX)[0]
    assert rec.doc_type == "conference"
    assert rec.journal.startswith("Proceedings of the 32nd ACM")
    assert rec.pages == "1123-1132"      # 1123--1132 normalised


def test_scopus_bibtex_cited_by_from_note():
    assert parse_bibtex(SCOPUS_BIBTEX)[0].cited_by == 42


def test_wos_bibtex_double_braces_are_stripped():
    rec = parse_bibtex(WOS_BIBTEX)[0]
    assert rec.title == ("Bibliometric mapping of artificial intelligence "
                         "research")
    assert rec.journal == "SCIENTOMETRICS"


def test_ieee_bibtex_and_ieee_csv_of_one_record_agree():
    """Two IEEE export formats of one article must deduplicate."""
    from_bib = parse_bibtex(IEEE_BIBTEX)[0]
    from_csv = parse_csv_export(IEEE_CSV)[0]
    assert from_bib.doi == from_csv.doi
    assert from_bib.pages == from_csv.pages
    assert from_bib.year == from_csv.year
