"""Measure parser/source coverage against the project specification.

Emits ``validation/parser_coverage.csv`` and ``validation/parser_coverage.md``.
Every cell of the table is produced by actually running the parser on the
realistic sample committed in the test suite -- nothing is asserted from
memory.  For each specification item the script records:

* whether an implementation exists (an importable public entry point);
* whether autodetection identifies the vendor dialect from the sample alone;
* how many records the sample yields and whether the parse report balances;
* which of the identifier fields the duplicate cascade needs were populated;
* the test that pins the behaviour ("verified how" column of the article).

Run from the package root:  ``PYTHONPATH=. python validation/measure_parser_coverage.py``
"""
from __future__ import annotations

import csv
import json
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests"))

import corpusslr as C  # noqa: E402
from corpusslr.parsers import ParseReport  # noqa: E402

import test_parsers_vendor_coverage as V  # noqa: E402
from test_parsers_enw_html import ACM_ENW, PROQUEST_HTML  # noqa: E402
from test_parsers_robustness import (ENDNOTE_XML, NBIB_MEDLINE,  # noqa: E402
                                     WOS_TAGGED)

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Level 1: API clients
# ---------------------------------------------------------------------------

API_SPEC = [
    ("Scopus", "ScopusSource", "tests/test_scopus.py, "
     "tests/test_scopus_live_shapes.py"),
    ("OpenAlex", "OpenAlexSource", "tests/test_sources_offline.py"),
    ("PubMed/MEDLINE (E-utilities)", "PubMedSource",
     "tests/test_sources_offline.py"),
    ("Crossref", "CrossrefSource", "tests/test_sources_offline.py"),
    ("Semantic Scholar", "SemanticScholarSource",
     "tests/test_semanticscholar.py"),
    ("arXiv", "ArxivSource", "tests/test_arxiv.py"),
    ("medRxiv", "MedrxivSource", "tests/test_preprints.py"),
    ("bioRxiv", "BiorxivSource", "tests/test_preprints.py"),
]


def measure_apis():
    """Measure each API client by running a recorded response through it.

    Checking that the class exists and has a ``search`` attribute proves almost
    nothing: a client that raises on the payload shape, or returns records with
    no identifiers, would pass such a check while being useless in a review. So
    each client is driven with the response fixtures its own test module uses,
    through a fake session, and the row reports how many records came out and
    which identifier fields they carried -- the inputs the duplicate cascade
    actually consumes.
    """
    rows = []
    for label, symbol, tests in API_SPEC:
        cls = getattr(C, symbol, None)
        exists = cls is not None
        name = getattr(cls, "name", "") if exists else ""
        n_records, ids, status = "", "", "MISSING"
        if exists and hasattr(cls, "search"):
            status = "covered"
            try:
                recs = _drive_client(cls)
                n_records = str(len(recs))
                fields = set()
                for r in recs:
                    for f in ("doi", "pmid", "openalex_id", "scopus_id",
                              "source_id"):
                        if getattr(r, f, ""):
                            fields.add(f)
                ids = "+".join(sorted(fields)) or "(none populated)"
                if not recs:
                    status = "NO RECORDS PARSED"
            except Exception as exc:                 # noqa: BLE001 - reported
                status = "PARSE ERROR"
                ids = "{}: {}".format(type(exc).__name__, exc)[:70]
        rows.append({
            "level": "1 - API",
            "requirement": label,
            "format": "REST API",
            "implementation": symbol if exists else "",
            "status": status,
            "detected": "n/a",
            "records": n_records,
            "balanced": "n/a",
            "identifiers": ids or name,
            "verified_how": tests,
        })
    return rows


# ---------------------------------------------------------------------------
# Driving the API clients offline
# ---------------------------------------------------------------------------

class _Resp:
    """Minimal stand-in for a requests.Response."""

    def __init__(self, payload=None, text=""):
        self.status_code = 200
        self._payload = payload
        self.text = text if text else (json.dumps(payload) if payload else "")
        self.headers = {}

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload

    def raise_for_status(self):
        return None


class _Session:
    """Replays a payload per GET, optionally choosing it by URL.

    PubMed needs this: it calls esearch (JSON) and then efetch (XML), so a
    session that returned one payload for both would make the client look
    broken when it is the fixture that is wrong.
    """

    def __init__(self, payload=None, text="", by_url=None):
        self.headers = {}
        self._payload, self._text = payload, text
        self._by_url = by_url or {}

    def get(self, url, params=None, headers=None, timeout=None, **kw):
        for fragment, (payload, text) in self._by_url.items():
            if fragment in url:
                return _Resp(payload, text)
        return _Resp(self._payload, self._text)

    post = get


_SCOPUS = {"search-results": {"opensearch:totalResults": "1", "entry": [{
    "dc:title": "Artificial intelligence adoption in small firms",
    "dc:creator": "Kowalski J.",
    "author": [{"authname": "Kowalski J."}, {"authname": "Nowak A."}],
    "author-count": {"@limit": "100", "$": "2"},
    "prism:publicationName": "Journal of Business Research",
    "prism:coverDate": "2024-01-01", "prism:volume": "170",
    "prism:pageRange": "114-128", "prism:doi": "10.1016/j.jbusres.2024.001",
    "dc:description": "This study examines AI adoption drivers.",
    "authkeywords": "artificial intelligence | SME",
    "citedby-count": "12", "subtypeDescription": "Article",
    "eid": "2-s2.0-85123456789", "dc:identifier": "SCOPUS_ID:85123456789"}]}}

_OPENALEX = {"meta": {"count": 1, "next_cursor": None}, "results": [{
    "id": "https://openalex.org/W2741809807", "doi": "https://doi.org/10.1/oa",
    "title": "Machine learning for credit risk",
    "publication_year": 2023, "type": "article",
    "abstract_inverted_index": {"Machine": [0], "learning": [1], "works": [2]},
    "authorships": [{"author": {"display_name": "Anna Nowak"}}],
    "primary_location": {"source": {"display_name": "Journal of Finance"}},
    "biblio": {"volume": "78", "first_page": "1", "last_page": "30"},
    "cited_by_count": 5, "ids": {"pmid": "https://pubmed.ncbi.nlm.nih.gov/33333333"}}]}

# esearch returns XML, not JSON, when usehistory is used -- the client reads
# r.text with ElementTree, so the fixture must be XML or the client only looks
# broken.
_PUBMED_SEARCH = """<?xml version="1.0"?>
<eSearchResult><Count>1</Count><RetMax>0</RetMax><RetStart>0</RetStart>
 <QueryKey>1</QueryKey><WebEnv>MCID_test</WebEnv>
</eSearchResult>"""

_PUBMED_FETCH = """<?xml version="1.0"?>
<PubmedArticleSet><PubmedArticle><MedlineCitation>
 <PMID>33333333</PMID>
 <Article>
  <Journal><Title>Diabetologia</Title>
   <JournalIssue><Volume>63</Volume><Issue>4</Issue>
    <PubDate><Year>2020</Year></PubDate></JournalIssue>
   <ISSN>0012-186X</ISSN></Journal>
  <ArticleTitle>Machine learning for glycaemic control</ArticleTitle>
  <Pagination><MedlinePgn>413-420</MedlinePgn></Pagination>
  <Abstract><AbstractText>We evaluate models.</AbstractText></Abstract>
  <AuthorList><Author><LastName>Kowalski</LastName>
    <ForeName>Jan</ForeName></Author></AuthorList>
  <PublicationTypeList><PublicationType>Journal Article</PublicationType>
    </PublicationTypeList>
  <Language>eng</Language>
 </Article>
</MedlineCitation>
<PubmedData><ArticleIdList>
 <ArticleId IdType="doi">10.1007/s00125-020-05100-z</ArticleId>
 <ArticleId IdType="pubmed">33333333</ArticleId>
</ArticleIdList></PubmedData>
</PubmedArticle></PubmedArticleSet>"""


_CROSSREF = {"message": {"total-results": 1, "next-cursor": "", "items": [{
    "DOI": "10.1/cr", "title": ["Consumer trust in chatbots"],
    "author": [{"family": "Nowak", "given": "Anna"}],
    "container-title": ["Journal Y"], "issued": {"date-parts": [[2022, 5, 1]]},
    "volume": "12", "page": "1-20", "type": "journal-article",
    "is-referenced-by-count": 4}]}}

_S2 = {"total": 1, "data": [{
    "paperId": "abc123", "title": "Edge AI for federated screening",
    "abstract": "We present edge inference.", "year": 2024,
    "venue": "IEEE Access", "citationCount": 7,
    "externalIds": {"DOI": "10.1109/ACCESS.2024.1234567", "PubMed": "34444444"},
    "authors": [{"name": "J. Smith"}], "publicationTypes": ["JournalArticle"]}]}

_ARXIV = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
 <opensearch:totalResults xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">1</opensearch:totalResults>
 <entry>
  <id>http://arxiv.org/abs/2401.00001v1</id>
  <title>Scaling laws for retrieval</title>
  <summary>We study scaling.</summary>
  <published>2024-01-01T00:00:00Z</published>
  <author><name>Jan Kowalski</name></author>
  <arxiv:doi xmlns:arxiv="http://arxiv.org/schemas/atom">10.48550/arXiv.2401.00001</arxiv:doi>
  <category term="cs.IR"/>
 </entry>
</feed>"""

_RXIV = {"messages": [{"status": "ok", "total": 1, "count": 1, "cursor": 0}],
         "collection": [{
             "doi": "10.1101/2024.01.01.573000",
             "title": "Machine learning applied to diagnostics",
             "authors": "Kowalski, J.; Nowak, A.",
             "date": "2024-01-01", "version": "1", "category": "bioinformatics",
             "abstract": "Machine learning applied to diagnostics.",
             "server": "biorxiv"}]}

_FIXTURES = {
    "ScopusSource": (dict(api_key="k" * 32), _SCOPUS, ""),
    "OpenAlexSource": ({}, _OPENALEX, ""),
    "PubMedSource": ({}, None, "",
                     {"esearch": (None, _PUBMED_SEARCH),
                      "efetch": (None, _PUBMED_FETCH)}),
    "CrossrefSource": ({}, _CROSSREF, ""),
    "SemanticScholarSource": ({}, _S2, ""),
    "ArxivSource": ({}, None, _ARXIV),
    "MedrxivSource": ({}, _RXIV, ""),
    "BiorxivSource": ({}, _RXIV, ""),
}

_QUERY = C.SearchQuery(blocks=[["machine learning"]], years=(2020, 2026),
                       doc_types=["article"])


def _drive_client(cls):
    """Run *cls* against its recorded payload and return the parsed records."""
    spec = _FIXTURES[cls.__name__]
    kwargs, payload, text = spec[0], spec[1], spec[2]
    by_url = spec[3] if len(spec) > 3 else None
    src = cls(session=_Session(payload, text, by_url), **kwargs)
    return src.search(_QUERY, max_results=5).records


# ---------------------------------------------------------------------------
# Level 2: file-export parsers
# ---------------------------------------------------------------------------

def _ident_summary(recs):
    """Which identifier fields the samples populated (dedup cascade inputs)."""
    fields = ("doi", "pmid", "source_id", "issn", "scopus_id")
    got = []
    for f in fields:
        if any(getattr(r, f, "") for r in recs):
            got.append(f)
    return "+".join(got)


#: ``(requirement, format, entry_point, sample, detector, expected_dialect,
#:   expected_n, test_reference)``
FILE_SPEC = [
    ("Web of Science", "tagged .txt/.ciw (FN/PT/AU/TI/SO/DI)",
     "parse_wos", WOS_TAGGED, None, "", 2,
     "tests/test_parsers_robustness.py::test_wellformed_sample_parses_"
     "and_balances[wos]"),
    ("Web of Science", "RIS", "parse_ris", V.WOS_RIS,
     "detect_dialect", "wos", 1,
     "tests/test_parsers_vendor_coverage.py::test_ris_dialect_autodetected"),
    ("Web of Science", "BibTeX", "parse_bibtex", V.WOS_BIBTEX,
     "detect_bibtex_dialect", "wos", 1,
     "tests/test_parsers_vendor_coverage.py::"
     "test_wos_bibtex_double_braces_are_stripped"),
    ("Web of Science", "CSV", "parse_csv_export", V.WOS_CSV,
     "detect_csv_dialect", "wos", 1,
     "tests/test_parsers_vendor_coverage.py::"
     "test_wos_csv_keeps_wos_id_and_pmid"),
    ("Embase", "RIS", "parse_ris", V.EMBASE_RIS,
     "detect_dialect", "embase", 1,
     "tests/test_parsers_vendor_coverage.py::"
     "test_embase_ris_pmid_and_subtype"),
    ("Embase", "CSV", "parse_csv_export", V.EMBASE_CSV,
     "detect_csv_dialect", "embase", 1,
     "tests/test_parsers_vendor_coverage.py::"
     "test_embase_csv_keeps_both_identifiers"),
    ("Cochrane CENTRAL", "RIS", "parse_ris", V.CENTRAL_RIS,
     "detect_dialect", "central", 1,
     "tests/test_parsers_vendor_coverage.py::"
     "test_central_ris_preserves_the_central_number_and_trial_id"),
    ("EBSCOhost - Business Source", "RIS", "parse_ris",
     V.EBSCO_RIS_BUSINESS, "detect_dialect", "ebsco", 1,
     "tests/test_parsers_vendor_coverage.py::"
     "test_ebsco_per_record_database_is_resolved"),
    ("EBSCOhost - PsycINFO", "RIS", "parse_ris", V.EBSCO_RIS_PSYCINFO,
     "detect_dialect", "ebsco", 1,
     "tests/test_parsers_vendor_coverage.py::"
     "test_ebsco_psycinfo_pmid_comes_from_c2"),
    ("EBSCOhost - CINAHL", "RIS", "parse_ris", V.EBSCO_RIS_CINAHL,
     "detect_dialect", "ebsco", 1,
     "tests/test_parsers_vendor_coverage.py::"
     "test_ebsco_per_record_database_is_resolved"),
    ("EBSCOhost - ERIC", "RIS", "parse_ris", V.EBSCO_RIS_ERIC,
     "detect_dialect", "ebsco", 1,
     "tests/test_parsers_vendor_coverage.py::"
     "test_ebsco_per_record_database_is_resolved"),
    ("ProQuest (ABI/INFORM)", "RIS", "parse_ris", V.PROQUEST_RIS,
     "detect_dialect", "proquest", 1,
     "tests/test_parsers_vendor_coverage.py::"
     "test_proquest_ris_keeps_the_longer_title_and_the_document_id"),
    ("ProQuest (ABI/INFORM)", ".xls that is TSV", "parse_csv_export",
     V.PROQUEST_CSV, "detect_csv_dialect", "proquest", 1,
     "tests/test_parsers_vendor_coverage.py::"
     "test_proquest_tsv_export_is_read_as_tab_separated"),
    ("ProQuest (ABI/INFORM)", ".xls that is HTML", "parse_html_table",
     PROQUEST_HTML, None, "proquest", 2,
     "tests/test_parsers_enw_html.py::"
     "test_proquest_html_export_field_mapping"),
    ("IEEE Xplore", "CSV", "parse_csv_export", V.IEEE_CSV,
     "detect_csv_dialect", "ieee", 1,
     "tests/test_parsers_vendor_coverage.py::"
     "test_ieee_csv_arnumber_recovered_from_pdf_link"),
    ("IEEE Xplore", "BibTeX", "parse_bibtex", V.IEEE_BIBTEX,
     "detect_bibtex_dialect", "ieee", 1,
     "tests/test_parsers_vendor_coverage.py::"
     "test_bibtex_dialect_autodetected[ieee]"),
    ("ACM Digital Library", "BibTeX", "parse_bibtex", V.ACM_BIBTEX,
     "detect_bibtex_dialect", "acm", 1,
     "tests/test_parsers_vendor_coverage.py::"
     "test_acm_bibtex_conference_venue_and_page_range"),
    ("ACM Digital Library", "EndNote tagged (.enw)", "parse_enw",
     ACM_ENW, None, "", 2,
     "tests/test_parsers_enw_html.py::"
     "test_enw_acm_conference_paper_field_mapping"),
    ("Scopus", "RIS", "parse_ris", V.SCOPUS_RIS,
     "detect_dialect", "scopus", 1,
     "tests/test_parsers_vendor_coverage.py::test_ris_dialect_autodetected"),
    ("Scopus", "CSV", "parse_csv_export", V.SCOPUS_CSV,
     "detect_csv_dialect", "scopus", 1,
     "tests/test_parsers_vendor_coverage.py::"
     "test_scopus_csv_identifiers_and_open_access"),
    ("Scopus", "BibTeX", "parse_bibtex", V.SCOPUS_BIBTEX,
     "detect_bibtex_dialect", "scopus", 1,
     "tests/test_parsers_vendor_coverage.py::"
     "test_scopus_bibtex_cited_by_from_note"),
    ("Dimensions", "CSV", "parse_csv_export", V.DIMENSIONS_CSV,
     "detect_csv_dialect", "dimensions", 1,
     "tests/test_parsers_vendor_coverage.py::"
     "test_dimensions_csv_publication_id_and_pmid"),
    ("PubMed", "MEDLINE / .nbib", "parse_nbib", NBIB_MEDLINE, None, "", 2,
     "tests/test_parsers_robustness.py::test_wellformed_sample_parses_"
     "and_balances[nbib]"),
    ("EndNote / WoS desktop", "EndNote XML", "parse_endnote_xml",
     ENDNOTE_XML, None, "", 2,
     "tests/test_parsers_robustness.py::test_wellformed_sample_parses_"
     "and_balances[endnote_xml]"),
]


def measure_files():
    rows = []
    for (req, fmt, entry, sample, detector, expected_dialect, expected_n,
         tests) in FILE_SPEC:
        fn = getattr(C, entry, None)
        if fn is None:
            rows.append({
                "level": "2 - file export", "requirement": req,
                "format": fmt, "implementation": "", "status": "MISSING",
                "detected": "", "records": "", "balanced": "",
                "identifiers": "", "verified_how": tests})
            continue
        rep = ParseReport()
        recs = fn(sample, report=rep)
        detected = ""
        if detector:
            detected = getattr(C, detector)(
                sample.splitlines()[0] if detector == "detect_csv_dialect"
                else sample)
        else:
            detected = rep.dialect or "n/a"
        ok = (len(recs) == expected_n and rep.balanced
              and (not expected_dialect or detected == expected_dialect))
        rows.append({
            "level": "2 - file export",
            "requirement": req,
            "format": fmt,
            "implementation": entry,
            "status": "covered" if ok else "PARTIAL",
            "detected": detected,
            "records": len(recs),
            "balanced": "yes" if rep.balanced else "NO",
            "identifiers": _ident_summary(recs),
            "verified_how": tests,
        })
    return rows


# ---------------------------------------------------------------------------
# Robustness matrix
# ---------------------------------------------------------------------------

ROBUSTNESS_SPEC = [
    ("truncated file", "truncated_half / truncated_quarter"),
    ("empty file", "empty / whitespace_only"),
    ("UTF-8 with and without BOM", "utf-8, utf-8+bom"),
    ("UTF-16 LE/BE with and without BOM", "utf-16, utf-16-le, utf-16-be"),
    ("Windows-1252 / latin-1", "cp1252, latin-1"),
    ("mixed CRLF / CR / LF line endings", "crlf, cr_only, mixed_newlines"),
    ("record without a title", "single_field_no_value, header_only"),
    ("very long field (200 kB)", "very_long_field"),
    ("binary file given by mistake", "PDF, ZIP magic numbers"),
    ("text-input vs file-input agreement", "all three line endings"),
]


def measure_robustness():
    """Re-run the property invariants and report the measured totals."""
    from test_parsers_robustness import FORMATS, _corruptions
    n_formats = len(FORMATS)
    n_inputs = 0
    n_raised = 0
    n_unbalanced = 0
    for _label, parse, _pf, sample, _e in FORMATS:
        for _name, text in _corruptions(sample).items():
            n_inputs += 1
            rep = ParseReport()
            try:
                recs = parse(text, report=rep)
            except Exception:
                n_raised += 1
                continue
            if rep.n_input != len(recs) + rep.n_rejected:
                n_unbalanced += 1
    return {"formats": n_formats, "inputs": n_inputs,
            "raised": n_raised, "unbalanced": n_unbalanced}


def measure_encodings():
    """Count (format x encoding) file-path combinations that round-trip."""
    import tempfile
    from test_parsers_robustness import ENCODINGS, FORMATS
    ok = 0
    total = 0
    failures = []
    tmp = tempfile.mkdtemp()
    for label, _p, parse_file, sample, expected in FORMATS:
        for encoding, bom in ENCODINGS:
            total += 1
            path = os.path.join(tmp, "c_%s_%s" % (label, encoding))
            with open(path, "wb") as fh:
                fh.write(bom + sample.encode(encoding, errors="replace"))
            try:
                n = len(parse_file(path))
            except Exception:
                n = -1
            if n == expected:
                ok += 1
            else:
                failures.append("%s/%s" % (label, encoding))
    return {"ok": ok, "total": total, "failures": failures}


# ---------------------------------------------------------------------------
# Emit
# ---------------------------------------------------------------------------

COLUMNS = ["level", "requirement", "format", "implementation", "status",
           "detected", "records", "balanced", "identifiers", "verified_how"]


def main():
    rows = measure_apis() + measure_files()
    robust = measure_robustness()
    enc = measure_encodings()

    csv_path = os.path.join(HERE, "parser_coverage.csv")
    with io.open(csv_path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    n_cov = sum(1 for r in rows if r["status"] == "covered")
    n_api = sum(1 for r in rows if r["level"].startswith("1"))
    n_file = len(rows) - n_api

    lines = []
    lines.append("# Parser and source coverage against the project "
                 "specification")
    lines.append("")
    lines.append("Generated by `validation/measure_parser_coverage.py`. "
                 "Every row is produced by running the named entry point on a "
                 "sample whose header row or tag set reproduces a real vendor "
                 "export; no cell is asserted from memory. `records` is the "
                 "number of records the sample yielded, `balanced` records "
                 "whether the parse report accounted for every input unit "
                 "(`n_input == len(records) + n_rejected`), and `identifiers` "
                 "lists the identifier fields the sample populated -- these "
                 "are the inputs to the duplicate cascade in "
                 "`corpusslr.dedup`.")
    lines.append("")
    lines.append("**Summary: %d of %d specification items covered "
                 "(%d API clients, %d file-export format cells).**"
                 % (n_cov, len(rows), n_api, n_file))
    lines.append("")

    for level, title in (("1", "Level 1 - API clients"),
                         ("2", "Level 2 - file-export parsers")):
        subset = [r for r in rows if r["level"].startswith(level)]
        lines.append("## " + title)
        lines.append("")
        lines.append("| Database | Format | Entry point | Status | Dialect "
                     "detected | Records | Accounted | Identifiers | "
                     "Verified how |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for r in subset:
            lines.append("| %s | %s | `%s` | %s | %s | %s | %s | %s | %s |" % (
                r["requirement"], r["format"],
                r["implementation"] or "-", r["status"],
                r["detected"] or "-", r["records"], r["balanced"] or "-",
                r["identifiers"] or "-", r["verified_how"]))
        lines.append("")

    lines.append("## Robustness to damaged input")
    lines.append("")
    lines.append("Two invariants are asserted for every parser against every "
                 "corruption mode. **P1**: no unhandled exception -- an import "
                 "step that dies on one bad file cannot report how many "
                 "records it found. **P2**: every rejected input unit is "
                 "counted with a reason, so the \"records identified\" figure "
                 "of a PRISMA 2020 flow diagram (Item 16a) can be reconciled "
                 "against the file.")
    lines.append("")
    lines.append("| Measure | Result |")
    lines.append("|---|---|")
    lines.append("| Parsers under test | %d |" % robust["formats"])
    lines.append("| (parser x corruption mode) combinations | %d |"
                 % robust["inputs"])
    lines.append("| P1 violations (unhandled exception) | %d |"
                 % robust["raised"])
    lines.append("| P2 violations (record lost without a rejection entry) "
                 "| %d |" % robust["unbalanced"])
    lines.append("| (parser x encoding) file round-trips passing | %d / %d |"
                 % (enc["ok"], enc["total"]))
    if enc["failures"]:
        lines.append("| encoding round-trip failures | %s |"
                     % ", ".join(enc["failures"]))
    lines.append("")
    lines.append("Corruption modes exercised: " + ", ".join(
        "%s (%s)" % (label, how) for label, how in ROBUSTNESS_SPEC) + ".")
    lines.append("")

    md_path = os.path.join(HERE, "parser_coverage.md")
    with io.open(md_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    print("rows=%d covered=%d missing=%d partial=%d"
          % (len(rows), n_cov,
             sum(1 for r in rows if r["status"] == "MISSING"),
             sum(1 for r in rows if r["status"] == "PARTIAL")))
    print("robustness: %d combos, P1 violations=%d, P2 violations=%d"
          % (robust["inputs"], robust["raised"], robust["unbalanced"]))
    print("encodings: %d/%d ok %s"
          % (enc["ok"], enc["total"],
             ("failures: " + ", ".join(enc["failures"]))
             if enc["failures"] else ""))
    print("wrote", csv_path)
    print("wrote", md_path)


if __name__ == "__main__":
    main()
