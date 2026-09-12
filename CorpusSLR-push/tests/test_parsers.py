from corpusslr import parse_nbib, parse_ris, parse_wos, detect_dialect
from corpusslr.sources.pubmed import parse_pubmed_xml
from corpusslr.sources.openalex import reconstruct_abstract

RIS_SCOPUS = """\ufeffTY  - JOUR
AU  - Kowalski, Jan
AU  - Nowak, Anna
TI  - Artificial intelligence adoption in small firms
PY  - 2024
T2  - Journal of Business Research
VL  - 170
SP  - 114
EP  - 128
DO  - 10.1016/j.jbusres.2024.001
SN  - 01482963
AB  - This study examines AI adoption drivers.
KW  - artificial intelligence
KW  - SME
UR  - https://example.org/a
N1  - Export Date: 1 May 2026
DB  - Scopus
ER  -
"""

RIS_EMBASE = """TY  - JOUR
DB  - Embase
AU  - Smith J.
TI  - Machine learning in oncology screening
T2  - The Lancet Oncology
PY  - 2023
AN  - PMID:36123456
DO  - 10.1016/S1470-2045(23)00001-1
AB  - Background: ML improves screening.
     Methods: cohort study.
ER  -
"""

WOS = """FN Clarivate Analytics Web of Science
VR 1.0
PT J
AU Kowalski, J
   Nowak, A
AF Kowalski, Jan
   Nowak, Anna
TI Artificial intelligence adoption
   in small firms
SO JOURNAL OF BUSINESS RESEARCH
LA English
DT Article
DE artificial intelligence; SME
AB This study examines AI adoption drivers in small firms across Europe.
SN 0148-2963
PY 2024
VL 170
BP 114
EP 128
DI 10.1016/j.jbusres.2024.001
PM 38999999
TC 12
UT WOS:001200000001
ER

EF
"""

NBIB = """PMID- 36123456
DP  - 2023 Jun 15
TI  - Machine learning in oncology
      screening.
AB  - Background: ML improves screening. Methods: a large
      multicentre cohort study.
FAU - Smith, John
AU  - Smith J
FAU - Doe, Jane
JT  - The Lancet. Oncology
TA  - Lancet Oncol
VI  - 24
IP  - 6
PG  - 601-612
LID - 10.1016/S1470-2045(23)00001-1 [doi]
IS  - 1474-5488 (Electronic)
PT  - Journal Article
PT  - Review
LA  - eng
MH  - Machine Learning
OT  - screening
"""

PUBMED_XML = """<?xml version="1.0"?>
<PubmedArticleSet>
 <PubmedArticle>
  <MedlineCitation>
   <PMID>36123456</PMID>
   <Article>
    <Journal><ISSN>1474-5488</ISSN><Title>The Lancet Oncology</Title>
      <JournalIssue><Volume>24</Volume><Issue>6</Issue>
        <PubDate><Year>2023</Year></PubDate></JournalIssue></Journal>
    <ArticleTitle>Machine learning in oncology screening.</ArticleTitle>
    <Pagination><MedlinePgn>601-612</MedlinePgn></Pagination>
    <ELocationID EIdType="doi">10.1016/S1470-2045(23)00001-1</ELocationID>
    <Abstract><AbstractText Label="BACKGROUND">ML improves screening.</AbstractText>
      <AbstractText>Cohort study.</AbstractText></Abstract>
    <AuthorList><Author><LastName>Smith</LastName><ForeName>John</ForeName></Author>
    </AuthorList>
    <Language>eng</Language>
    <PublicationTypeList><PublicationType>Journal Article</PublicationType>
      <PublicationType>Review</PublicationType></PublicationTypeList>
   </Article>
   <KeywordList><Keyword>screening</Keyword></KeywordList>
  </MedlineCitation>
 </PubmedArticle>
</PubmedArticleSet>
"""


def test_ris_scopus_dialect():
    assert detect_dialect(RIS_SCOPUS) == "scopus"
    recs = parse_ris(RIS_SCOPUS)
    assert len(recs) == 1
    r = recs[0]
    assert r.title.startswith("Artificial intelligence")
    assert r.journal == "Journal of Business Research"
    assert r.doi == "10.1016/j.jbusres.2024.001"
    assert r.year == 2024 and r.pages == "114-128"
    assert r.authors == ["Kowalski, Jan", "Nowak, Anna"]
    assert "SME" in r.keywords and r.doc_type == "article"


def test_ris_embase_dialect_continuation_and_pmid():
    recs = parse_ris(RIS_EMBASE)
    r = recs[0]
    assert r.journal == "The Lancet Oncology"  # T2 priority for Embase
    assert r.pmid == "36123456"
    assert "Methods: cohort study." in r.abstract  # continuation line joined


def test_wos_parser():
    recs = parse_wos(WOS)
    assert len(recs) == 1
    r = recs[0]
    assert r.title == "Artificial intelligence adoption in small firms"
    assert r.authors == ["Kowalski, Jan", "Nowak, Anna"]  # AF preferred
    assert r.doi == "10.1016/j.jbusres.2024.001"
    assert r.pmid == "38999999" and r.source_id == "WOS:001200000001"
    assert r.cited_by == 12 and r.year == 2024
    assert r.doc_type == "article" and "SME" in r.keywords


def test_nbib_parser():
    recs = parse_nbib(NBIB)
    assert len(recs) == 1
    r = recs[0]
    assert r.pmid == "36123456"
    assert r.title.endswith("screening.")
    assert "multicentre cohort study" in r.abstract
    assert r.authors[0] == "Smith, John"
    assert r.doi == "10.1016/s1470-2045(23)00001-1"
    assert r.doc_type == "review" and r.year == 2023
    assert r.issn == "1474-5488"


def test_pubmed_xml_parser():
    recs = parse_pubmed_xml(PUBMED_XML)
    r = recs[0]
    assert r.pmid == "36123456" and r.year == 2023
    assert r.abstract.startswith("BACKGROUND: ML improves")
    assert r.doc_type == "review"
    assert r.doi == "10.1016/s1470-2045(23)00001-1"


def test_reconstruct_abstract():
    inv = {"screening": [2], "improves": [1], "ML": [0]}
    assert reconstruct_abstract(inv) == "ML improves screening"
    assert reconstruct_abstract(None) == ""
