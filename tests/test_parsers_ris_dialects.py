"""RIS vendor dialects: Embase, Cochrane CENTRAL, EBSCOhost, ProQuest."""
import pytest

from corpusslr import detect_dialect, parse_ris
from corpusslr.parsers.ris import parse_ris_file

# --------------------------------------------------------------------------
# Embase (Elsevier)
# --------------------------------------------------------------------------

EMBASE = """TY  - JOUR
DB  - Embase
TI  - Machine learning in oncology screening: a systematic review
AU  - Smith J.
AU  - Wróbel Ł.
T2  - The Lancet Oncology
JF  - Lancet Oncol
J2  - Lancet Oncol.
PY  - 2023
VL  - 24
IS  - 6
SP  - 601
EP  - 612
M3  - Review
AN  - PMID:36123456
C2  - 36123456
DO  - 10.1016/S1470-2045(23)00001-1
SN  - 1470-2045
KW  - machine learning
KW  - oncology
AB  - Background: ML improves screening.
      Methods: multicentre cohort study.
LA  - English
ER  -

TY  - JOUR
DB  - Embase
TI  - Late-breaking results on cardiac imaging
AU  - Jones A.
T2  - European Heart Journal
PY  - 2022
M3  - Conference Abstract
AN  - L638123456
ER  -

TY  - JOUR
DB  - Embase
TI  - An ordinary Embase article
AU  - Novák J.
T2  - Ceska Kardiologie
PY  - 2021
M3  - Article
AN  - 2021456789
ER  -
"""

# --------------------------------------------------------------------------
# Cochrane CENTRAL (Wiley)
# --------------------------------------------------------------------------

CENTRAL = """TY  - JOUR
TI  - Effect of supervised exercise on blood pressure: a randomised controlled trial
AU  - Andersson, Åsa
AU  - Lindqvist, Bjørn
T2  - Journal of Hypertension
PY  - 2021
VL  - 39
SP  - 120
EP  - 131
DO  - 10.1097/HJH.0000000000002700
AN  - CN-02345678
DB  - Cochrane Central Register of Controlled Trials
C7  - NCT04567890
KW  - hypertension
KW  - exercise
ER  -

TY  - JOUR
TI  - Registry-only trial report without a DOI
AU  - Müller H.
T2  - Trials
PY  - 2020
AN  - CN-01234567
DB  - Cochrane Central Register of Controlled Trials
N1  - ISRCTN12345678; also registered as NCT01111111
ER  -
"""

# --------------------------------------------------------------------------
# EBSCOhost (several databases in one file)
# --------------------------------------------------------------------------

EBSCO = """TY  - JOUR
TI  - Consumer trust in AI advisors
AU  - Andersson, Åsa
JF  - Journal of Consumer Research
PY  - 2021
VL  - 48
SP  - 55
EP  - 70
DO  - 10.1093/jcr/ucab001
DB  - Business Source Complete
DP  - EBSCOhost
AN  - bth-149203311
KW  - artificial intelligence
ER  -

TY  - JOUR
TI  - Cognitive load and decision automation
AU  - Novák, Jiří
JF  - Journal of Experimental Psychology
PY  - 2020
DB  - PsycINFO
DP  - EBSCOhost
AN  - 2020-45678-001
C2  - PMID: 32123456
ER  -

TY  - JOUR
TI  - Nurse staffing and patient outcomes
AU  - O'Brien, Sinead
JF  - Journal of Advanced Nursing
PY  - 2019
DB  - CINAHL Complete
DP  - EBSCOhost
AN  - ccm-137001234
ER  -

TY  - JOUR
TI  - Teacher training and digital literacy
AU  - Kowalska, Maria
JF  - Computers and Education
PY  - 2018
DB  - ERIC
DP  - EBSCOhost
AN  - eric-EJ1234567
ER  -
"""

EBSCO_NO_DB_TAG = """TY  - JOUR
DP  - EBSCOhost
TI  - Record whose database is only implied by the accession prefix
AU  - Smith, John
JF  - Academy of Management Review
PY  - 2017
AN  - buh-121212121
ER  -
"""

# --------------------------------------------------------------------------
# ProQuest ABI/INFORM
# --------------------------------------------------------------------------

PROQUEST = """TY  - JOUR
TI  - Digital transformation in mid-sized manufacturing
T1  - Digital transformation in mid-sized manufacturing firms: evidence from Poland
AU  - Kowalski, Jan
AU  - Nowak, Anna
JF  - Journal of Business Strategy
PY  - 2024
VL  - 45
IS  - 2
SP  - 33
EP  - 47
DO  - 10.1108/JBS-01-2024-0001
ID  - 3012345678
AN  - 3012345678
UR  - https://www.proquest.com/docview/3012345678
DB  - ABI/INFORM Collection
KW  - digital transformation
AB  - This paper studies SMEs.
ER  -

TY  - JOUR
TI  - Short title
AU  - Brown, Alice
JF  - Management Today
PY  - 2023
UR  - https://www.proquest.com/docview/2988776655
DB  - ProQuest One Business
ER  -
"""


# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    (EMBASE, "embase"),
    (CENTRAL, "central"),
    (EBSCO, "ebsco"),
    (EBSCO_NO_DB_TAG, "ebsco"),
    (PROQUEST, "proquest"),
])
def test_detect_dialect(text, expected):
    assert detect_dialect(text) == expected


def test_central_wins_over_embase_marker():
    """A CENTRAL file indexes Embase records; the CN- accession decides."""
    text = ("TY  - JOUR\nTI  - T\nAN  - CN-01234567\n"
            "N1  - Embase record\nER  -\n")
    assert detect_dialect(text) == "central"


def test_generic_and_existing_dialects_unaffected():
    assert detect_dialect("TY  - JOUR\nTI  - T\nER  -\n") == "generic"
    assert detect_dialect("TY  - JOUR\nDB  - Scopus\nTI  - T\nER  -\n") \
        == "scopus"


# --------------------------------------------------------------------------
# Embase
# --------------------------------------------------------------------------

def test_embase_full_record():
    r = parse_ris(EMBASE)[0]
    assert r.journal == "The Lancet Oncology"          # T2 priority
    assert r.pmid == "36123456"
    assert r.doc_type == "review"                       # from M3, not TY
    assert r.raw["embase_subtype"] == "Review"
    assert r.pages == "601-612"
    assert r.doi == "10.1016/s1470-2045(23)00001-1"
    assert r.authors == ["Smith J.", "Wr\u00f3bel \u0141."]
    assert "Methods: multicentre cohort study." in r.abstract
    assert r.source_id == "36123456"


def test_embase_conference_abstract_subtype():
    r = parse_ris(EMBASE)[1]
    assert r.doc_type == "conference"
    assert r.raw["embase_subtype"] == "Conference Abstract"
    assert r.raw["embase_id"] == "L638123456"
    assert r.source_id == "L638123456"
    assert r.pmid == ""


def test_embase_numeric_accession_is_not_mistaken_for_pmid():
    r = parse_ris(EMBASE)[2]
    assert r.doc_type == "article"
    assert r.pmid == ""            # 2021456789 is 10 digits, not a PMID


def test_embase_m3_holding_a_doi_is_not_treated_as_subtype():
    text = ("TY  - JOUR\nDB  - Embase\nTI  - T\n"
            "M3  - 10.1016/j.x.2020.01.001\nER  -\n")
    r = parse_ris(text)[0]
    assert r.doc_type == "article"
    assert "embase_subtype" not in r.raw


# --------------------------------------------------------------------------
# Cochrane CENTRAL
# --------------------------------------------------------------------------

def test_central_accession_extracted():
    r = parse_ris(CENTRAL)[0]
    assert r.raw["central_id"] == "CN-02345678"
    assert r.source_id == "CN-02345678"
    assert r.pmid == ""            # CN number must never become a PMID
    assert r.journal == "Journal of Hypertension"
    assert r.pages == "120-131"


def test_central_trial_registry_ids():
    recs = parse_ris(CENTRAL)
    assert recs[0].raw["trial_ids"] == ["NCT04567890"]
    assert recs[1].raw["trial_ids"] == ["ISRCTN12345678", "NCT01111111"]
    assert recs[1].raw["central_id"] == "CN-01234567"


def test_central_record_without_doi_still_identifiable():
    r = parse_ris(CENTRAL)[1]
    assert r.doi == "" and r.source_id == "CN-01234567"


def test_central_cn_without_hyphen():
    text = "TY  - JOUR\nTI  - T\nAN  - CN 01234567\nDB  - Cochrane\nER  -\n"
    r = parse_ris(text)[0]
    assert r.raw["central_id"] == "CN-01234567"


# --------------------------------------------------------------------------
# EBSCOhost
# --------------------------------------------------------------------------

@pytest.mark.parametrize("idx,database,accession", [
    (0, "Business Source", "bth-149203311"),
    (1, "PsycINFO", "2020-45678-001"),
    (2, "CINAHL", "ccm-137001234"),
    (3, "ERIC", "eric-EJ1234567"),
])
def test_ebsco_per_record_database(idx, database, accession):
    r = parse_ris(EBSCO)[idx]
    assert r.raw["ebsco_database"] == database
    assert r.source == database
    assert r.source_id == accession


def test_ebsco_pmid_from_c2():
    r = parse_ris(EBSCO)[1]
    assert r.pmid == "32123456"


def test_ebsco_psycinfo_accession_not_read_as_pmid():
    r = parse_ris(EBSCO)[1]
    assert r.source_id == "2020-45678-001"


def test_ebsco_database_from_accession_prefix_only():
    r = parse_ris(EBSCO_NO_DB_TAG)[0]
    assert r.raw["ebsco_database"] == "Business Source"
    assert r.source == "Business Source"


def test_ebsco_source_name_argument_wins_over_database():
    r = parse_ris(EBSCO, source_name="EBSCO combined export")[0]
    assert r.source == "EBSCO combined export"
    assert r.raw["ebsco_database"] == "Business Source"


def test_ebsco_journal_priority_is_jf():
    text = ("TY  - JOUR\nDP  - EBSCOhost\nTI  - T\n"
            "JF  - Full Journal Name\nT2  - Wrong Container\nER  -\n")
    assert parse_ris(text)[0].journal == "Full Journal Name"


# --------------------------------------------------------------------------
# ProQuest
# --------------------------------------------------------------------------

def test_proquest_keeps_longer_of_duplicated_titles():
    r = parse_ris(PROQUEST)[0]
    assert r.title == ("Digital transformation in mid-sized manufacturing "
                       "firms: evidence from Poland")


def test_proquest_document_id():
    r = parse_ris(PROQUEST)[0]
    assert r.raw["proquest_id"] == "3012345678"
    assert r.source_id == "3012345678"


def test_proquest_id_recovered_from_docview_url():
    r = parse_ris(PROQUEST)[1]
    assert r.raw["proquest_id"] == "2988776655"
    assert r.source_id == "2988776655"


def test_proquest_id_is_not_a_pmid():
    assert all(r.pmid == "" for r in parse_ris(PROQUEST))


# --------------------------------------------------------------------------
# Backwards compatibility and edge cases
# --------------------------------------------------------------------------

def test_generic_records_unchanged():
    text = ("TY  - JOUR\nTI  - Plain record\nAU  - Doe, Jane\n"
            "JF  - Some Journal\nPY  - 2015\nSP  - 1\nEP  - 9\nER  -\n")
    r = parse_ris(text)[0]
    assert r.journal == "Some Journal" and r.pages == "1-9"
    assert r.source == "RIS/generic" and r.doc_type == "article"
    assert "central_id" not in r.raw and "ebsco_database" not in r.raw


def test_explicit_dialect_override():
    r = parse_ris(EMBASE, dialect="generic")[0]
    assert r.raw["dialect"] == "generic"
    assert "embase_subtype" not in r.raw
    assert r.journal == "Lancet Oncol"       # generic prefers JF


def test_empty_and_garbage_input():
    assert parse_ris("") == []
    assert parse_ris("   \n\n") == []
    assert parse_ris("this is not RIS at all") == []


def test_record_without_er_terminator_is_still_returned():
    text = "TY  - JOUR\nTI  - Unterminated record\nPY  - 2020\n"
    recs = parse_ris(text)
    assert len(recs) == 1 and recs[0].title == "Unterminated record"


def test_bom_and_crlf_line_endings():
    text = "\ufeffTY  - JOUR\r\nTI  - CRLF title\r\nPY  - 2020\r\nER  -\r\n"
    r = parse_ris(text)[0]
    assert r.title == "CRLF title" and r.year == 2020


def test_single_space_tag_separator():
    text = "TY - JOUR\nTI - Single space form\nPY - 2019\nER - \n"
    r = parse_ris(text)[0]
    assert r.title == "Single space form" and r.year == 2019


def test_parse_file_dialects(tmp_path):
    p = tmp_path / "central.ris"
    p.write_text(CENTRAL, encoding="utf-8")
    recs = parse_ris_file(str(p))
    assert len(recs) == 2 and recs[0].raw["central_id"] == "CN-02345678"


def test_parse_file_with_bom(tmp_path):
    p = tmp_path / "embase.ris"
    p.write_text("\ufeff" + EMBASE, encoding="utf-8-sig")
    recs = parse_ris_file(str(p))
    assert len(recs) == 3 and recs[0].pmid == "36123456"
