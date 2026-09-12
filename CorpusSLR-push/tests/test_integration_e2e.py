"""End-to-end run of the documented workflow with all HTTP mocked.

Mirrors examples/example_slr.py: one SearchQuery -> four sources -> abstract
recovery -> quality report -> dedup -> PRISMA 2020 SVG + PRISMA-S appendix
-> screening CSV, asserting the numbers stay consistent across all artifacts.
"""
import csv
import re

from conftest import FakeResponse, FakeSession

from corpusslr import (Corpus, CrossrefSource, OpenAlexSource, PrismaFlow,
                       PubMedSource, ScopusSource, SearchQuery, deduplicate,
                       parse_wos, prisma_s_markdown, quality_report,
                       recover_abstracts, to_screening_csv)

QUERY = SearchQuery(
    blocks=[["artificial intelligence", "machine learning"],
            ["adoption", "implementation"],
            ["SME", "small firm"]],
    years=(2015, 2026), doc_types=["article", "review"], languages=["en"])

# One shared work (DOI 10.5001/shared) appears in Scopus, OpenAlex and WoS;
# PubMed has it under a PMID only, plus each source has one unique record.
SCOPUS = {"search-results": {"opensearch:totalResults": "2", "entry": [
    {"dc:identifier": "SCOPUS_ID:85001", "dc:title": "AI adoption in SMEs",
     "dc:description": "Truncated abs...", "dc:creator": "Kowalski J.",
     "prism:coverDate": "2024-01-01", "prism:doi": "10.5001/shared",
     "prism:publicationName": "JBR", "subtypeDescription": "Article",
     "citedby-count": "10"},
    {"dc:identifier": "SCOPUS_ID:85002", "dc:title": "Scopus only study",
     "prism:coverDate": "2023-01-01", "prism:doi": "10.5001/scopus-only",
     "subtypeDescription": "Article"}]}}

OPENALEX = {"meta": {"count": 2, "next_cursor": None}, "results": [
    {"id": "https://openalex.org/W1", "doi": "https://doi.org/10.5001/shared",
     "display_name": "AI adoption in SMEs", "publication_year": 2024,
     "type": "article", "language": "en",
     "primary_location": {"source": {"display_name": "Journal of Business "
                                                     "Research",
                                     "issn_l": "0148-2963"}},
     "authorships": [{"author": {"display_name": "Jan Kowalski"}}],
     "abstract_inverted_index": {f"w{i}": [i] for i in range(80)},
     "cited_by_count": 11, "biblio": {}},
    {"id": "https://openalex.org/W2", "doi": "https://doi.org/10.5001/oa-only",
     "display_name": "OpenAlex only study", "publication_year": 2022,
     "type": "article", "authorships": [], "biblio": {}}]}

ESEARCH = ("<eSearchResult><Count>1</Count><WebEnv>W</WebEnv>"
           "<QueryKey>1</QueryKey></eSearchResult>")
EFETCH = """<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>4242</PMID>
<Article><ArticleTitle>AI adoption in SMEs</ArticleTitle>
<Journal><Title>JBR</Title><JournalIssue><PubDate><Year>2024</Year></PubDate>
</JournalIssue></Journal>
<Abstract><AbstractText>PubMed abstract text.</AbstractText></Abstract>
<AuthorList><Author><LastName>Kowalski</LastName><ForeName>Jan</ForeName>
</Author></AuthorList>
<PublicationTypeList><PublicationType>Journal Article</PublicationType>
</PublicationTypeList></Article></MedlineCitation>
<PubmedData><ArticleIdList>
<ArticleId IdType="doi">10.5001/shared</ArticleId></ArticleIdList></PubmedData>
</PubmedArticle></PubmedArticleSet>"""

CROSSREF = {"message": {"total-results": 1, "next-cursor": "", "items": [
    {"DOI": "10.5001/crossref-only", "title": ["Crossref only item"],
     "issued": {"date-parts": [[2021]]}, "type": "journal-article"}]}}

WOS_EXPORT = """FN Clarivate Analytics Web of Science
VR 1.0
PT J
AU Kowalski, J
AF Kowalski, Jan
TI AI adoption in SMEs
SO JOURNAL OF BUSINESS RESEARCH
DT Article
AB Web of Science abstract for the shared work.
PY 2024
DI 10.5001/shared
UT WOS:000111
ER

EF
"""


def _build_corpus():
    corpus = Corpus()
    corpus.add_search(ScopusSource(
        api_key="K", session=FakeSession([FakeResponse(200, payload=SCOPUS)])
    ).search(QUERY, max_results=100))
    corpus.add_search(OpenAlexSource(
        mailto="me@uni.edu",
        session=FakeSession([FakeResponse(200, payload=OPENALEX)])
    ).search(QUERY, max_results=100))
    corpus.add_search(PubMedSource(
        email="me@uni.edu",
        session=FakeSession([FakeResponse(200, text=ESEARCH),
                             FakeResponse(200, text=EFETCH)])
    ).search(QUERY, max_results=100))
    corpus.add_search(CrossrefSource(
        mailto="me@uni.edu",
        session=FakeSession([FakeResponse(200, payload=CROSSREF)])
    ).search(QUERY, max_results=100))
    corpus.add_records(parse_wos(WOS_EXPORT),
                       database="Web of Science Core Collection",
                       platform="Clarivate", interface="Web interface export",
                       query="TS=(...)", date_run="2026-08-10")
    return corpus


def test_end_to_end_pipeline(tmp_path):
    corpus = _build_corpus()
    # 5 search events, 7 records identified
    assert [e.search_id for e in corpus.searches] == ["S1", "S2", "S3", "S4", "S5"]
    assert corpus.total_identified() == 7 == len(corpus)
    assert corpus.identified_by_source() == {
        "Scopus": 2, "OpenAlex": 2, "PubMed": 1, "Crossref": 1,
        "Web of Science Core Collection": 1}

    # abstract recovery hits only the truncated Scopus record
    oa_payload = {"results": [
        {"id": "https://openalex.org/W1", "doi": "https://doi.org/10.5001/shared",
         "ids": {"pmid": "https://pubmed.ncbi.nlm.nih.gov/4242"},
         "abstract_inverted_index": {f"tok{i}": [i] for i in range(90)}}]}
    s = FakeSession([FakeResponse(200, payload=oa_payload)])
    stats = recover_abstracts(corpus.records, mailto="me@uni.edu", session=s)
    assert stats["recovered"] >= 1

    q = quality_report(corpus.records)
    assert q["Scopus"]["n"] == 2 and q["Crossref"]["pct_abstract"] == 0.0

    result = deduplicate(corpus)
    # the shared work exists in Scopus/OpenAlex/PubMed/WoS -> one record
    assert result.report.after == 4
    assert result.report.by_method.get("doi") == 3
    assert sum(result.report.by_method.values()) == result.report.removed
    shared = [r for r in result.records if r.doi == "10.5001/shared"][0]
    assert shared.scopus_id == "85001" and shared.openalex_id == "W1"
    assert shared.pmid == "4242" and shared.source_id
    assert len(shared.provenance) >= 4          # every origin retained
    assert result.report.overlap                # cross-source redundancy seen

    flow = PrismaFlow.from_dedup(corpus, result).set_screening(
        records_excluded=1, reports_not_retrieved=0,
        fulltext_exclusions={"not empirical": 1}, studies_included=2)
    assert flow.identified == 7 and flow.records_screened == 4
    assert flow.validate() == []
    svg = flow.to_svg(str(tmp_path / "flow.svg"))
    assert "Records identified from databases (n = 7)" in svg
    assert "Studies included in review (n = 2)" in svg

    md = prisma_s_markdown(corpus, result)
    for db in ("Scopus", "OpenAlex", "PubMed", "Crossref",
               "Web of Science Core Collection"):
        assert db in md
    assert "Total records identified: **7**" in md
    # the appendix must agree with the flow diagram
    assert f"leaving {result.report.after} unique records" in md

    p = to_screening_csv(result.records, str(tmp_path / "screening.csv"))
    rows = list(csv.DictReader(open(p, encoding="utf-8")))
    assert len(rows) == result.report.after
    assert all(re.match(r"R\d{6}$", r["record_id"]) for r in rows)


def test_compiled_queries_are_recorded_per_source():
    corpus = _build_corpus()
    by_db = {e.database: e for e in corpus.searches}
    assert "TITLE-ABS-KEY" in by_db["Scopus"].query
    assert "title_and_abstract.search" in by_db["OpenAlex"].query
    assert "[Title/Abstract]" in by_db["PubMed"].query
    assert by_db["Crossref"].query and "filter=" in by_db["Crossref"].query
    assert by_db["Web of Science Core Collection"].interface == \
        "Web interface export"
    # every event carries a date for PRISMA-S item 10
    assert all(e.date_run for e in corpus.searches)
