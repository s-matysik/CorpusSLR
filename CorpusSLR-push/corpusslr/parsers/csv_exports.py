"""Spreadsheet-export parser with per-vendor column mapping.

CSV/XLSX is the default export of every major bibliographic database, and it
is the format in which reviewers actually hand each other search results.
It is also the least standardised: the article title is ``Title`` in Scopus,
``Article Title`` in Web of Science, ``Document Title`` in IEEE Xplore and
``Title`` again -- but with a different neighbourhood -- in Dimensions and
EBSCO.  Merging such files by hand is where records get silently dropped.

:func:`detect_csv_dialect` fingerprints the header row against per-vendor
signature columns and returns the best-scoring vendor, so a reviewer can
feed a directory of heterogeneous exports to one function.  Detection uses
*discriminating* columns (``EID`` for Scopus, ``UT (Unique WOS ID)`` for Web
of Science, ``IEEE Terms`` for IEEE Xplore, ``PubYear`` for Dimensions,
``Accession Number`` for EBSCO) rather than generic ones, because ``Title``
and ``Authors`` appear in all five.

Robustness features that matter on real files:

* UTF-8 BOM stripping (Scopus and WoS both emit one);
* delimiter sniffing over ``,`` ``;`` ``\\t`` ``|`` with a frequency-count
  fallback, since :class:`csv.Sniffer` raises on single-column files;
* header matching that is case-, whitespace- and punctuation-insensitive;
* years exported by spreadsheet round-trips as ``2024.0``;
* author cells separated by ``;``, ``and`` or bare commas;
* duplicated/blank trailing columns, which Excel adds when a file is
  re-saved.
"""
from __future__ import annotations

import csv
import io
import re
from typing import Dict, List, Optional, Sequence, Tuple

from ..record import Record
from ._io import csv_field_limit, looks_like_html, read_export_text
from ._report import ParseReport, _ensure
from ._util import (clean_pages, collapse_ws, map_doc_type, parse_int,
                    parse_year, split_authors, split_keywords)

__all__ = ["detect_csv_dialect", "parse_csv_export", "parse_csv_export_file",
           "parse_csv_rows", "CSV_DIALECTS"]

_NONALNUM = re.compile(r"[^a-z0-9]+")


def _key(name: Optional[str]) -> str:
    """Canonical header key: lowercase, alphanumeric only."""
    if name is None:
        return ""
    return _NONALNUM.sub("", str(name).replace("\ufeff", "").lower())


# ---------------------------------------------------------------------------
# Vendor column maps
# ---------------------------------------------------------------------------
# Each field maps to an ordered list of candidate headers; the first header
# present in the file wins.  Headers are given in their human-readable form
# and canonicalised at import time, so this table stays readable in the
# paper's supplementary material.

_SCOPUS = {
    "title": ["Title"],
    "authors": ["Authors", "Author full names", "Author Names"],
    "year": ["Year"],
    "journal": ["Source title"],
    "doi": ["DOI"],
    "abstract": ["Abstract"],
    "volume": ["Volume"],
    "issue": ["Issue"],
    "pages_start": ["Page start"],
    "pages_end": ["Page end"],
    # "Page count" is deliberately absent: it holds a length, not a range,
    # and mapping it onto `pages` would overwrite the real page numbers.
    "pages": ["Pages"],
    "issn": ["ISSN"],
    "keywords": ["Author Keywords"],
    "keywords2": ["Index Keywords"],
    "affiliations": ["Affiliations"],
    "doc_type": ["Document Type"],
    "language": ["Language of Original Document", "Language"],
    "cited_by": ["Cited by"],
    "url": ["Link", "DOI Link"],
    "scopus_id": ["EID"],
    "pmid": ["PubMed ID"],
    "open_access": ["Open Access"],
}

_WOS = {
    "title": ["Article Title", "Title"],
    "authors": ["Author Full Names", "Authors"],
    "year": ["Publication Year", "Year Published"],
    "journal": ["Source Title", "Journal"],
    "doi": ["DOI"],
    "abstract": ["Abstract"],
    "volume": ["Volume"],
    "issue": ["Issue"],
    "pages_start": ["Start Page"],
    "pages_end": ["End Page"],
    "issn": ["ISSN", "eISSN"],
    "keywords": ["Author Keywords"],
    "keywords2": ["Keywords Plus"],
    "affiliations": ["Addresses", "Affiliations"],
    "doc_type": ["Document Type", "Publication Type"],
    "language": ["Language"],
    "cited_by": ["Times Cited, All Databases", "Times Cited, WoS Core"],
    "url": ["DOI Link"],
    "source_id": ["UT (Unique WOS ID)", "UT (Unique ID)"],
    "pmid": ["Pubmed Id", "PubMed ID"],
    "open_access": ["Open Access Designations"],
}

_IEEE = {
    "title": ["Document Title"],
    "authors": ["Authors"],
    "year": ["Publication Year"],
    "journal": ["Publication Title"],
    "doi": ["DOI"],
    "abstract": ["Abstract"],
    "volume": ["Volume"],
    "issue": ["Issue"],
    "pages_start": ["Start Page"],
    "pages_end": ["End Page"],
    "issn": ["ISSN", "ISBNs"],
    "keywords": ["Author Keywords"],
    "keywords2": ["IEEE Terms", "INSPEC Controlled Terms"],
    "affiliations": ["Author Affiliations", "Affiliations"],
    "doc_type": ["Document Identifier", "Content Type"],
    "cited_by": ["Article Citation Count"],
    "url": ["PDF Link"],
    "pmid": ["PubMed ID"],
}

_DIMENSIONS = {
    "title": ["Title"],
    "authors": ["Authors", "Authors (Raw Affiliation)"],
    "year": ["PubYear", "Publication Year"],
    "journal": ["Source title", "Source Title/Anthology Title"],
    "doi": ["DOI"],
    "abstract": ["Abstract"],
    "volume": ["Volume"],
    "issue": ["Issue"],
    "pages": ["Pagination", "Pages"],
    "issn": ["ISSN"],
    "keywords": ["MeSH terms", "Keywords"],
    "doc_type": ["Publication Type", "Document Type"],
    "cited_by": ["Times cited", "Times Cited"],
    "url": ["Source Linkout", "Dimensions URL"],
    "source_id": ["Publication ID"],
    "pmid": ["PMID", "PubMed ID"],
    "open_access": ["Open Access"],
}

_EBSCO = {
    "title": ["Title", "Article Title"],
    "authors": ["Authors", "Author"],
    "year": ["Year", "Publication Date"],
    "journal": ["Journal", "Journal Title", "Source"],
    "doi": ["DOI"],
    "abstract": ["Abstract"],
    "volume": ["Volume"],
    "issue": ["Issue"],
    "pages": ["Pages", "Page Range"],
    "issn": ["ISSN"],
    "keywords": ["Subjects", "Keywords", "Subject Terms"],
    "doc_type": ["Document Type", "Publication Type"],
    "language": ["Language"],
    "url": ["PLink", "URL"],
    "source_id": ["Accession Number", "An"],
}

_GENERIC = {
    "title": ["Title", "Article Title", "Document Title", "Primary Title"],
    "authors": ["Authors", "Author", "Author Full Names", "Author Names",
                "Creator"],
    "year": ["Year", "Publication Year", "PubYear", "Date", "Publication Date"],
    "journal": ["Journal", "Source title", "Source Title", "Publication Title",
                "Journal Title", "Container Title", "Periodical"],
    "doi": ["DOI", "doi", "Digital Object Identifier"],
    "abstract": ["Abstract", "Abstract Note", "Summary"],
    "volume": ["Volume"],
    "issue": ["Issue", "Number"],
    "pages": ["Pages", "Pagination", "Page Range"],
    "pages_start": ["Page start", "Start Page", "First Page"],
    "pages_end": ["Page end", "End Page", "Last Page"],
    "issn": ["ISSN", "eISSN", "ISBN"],
    "keywords": ["Keywords", "Author Keywords", "Subjects", "Subject Terms"],
    "keywords2": ["Index Keywords", "Keywords Plus", "IEEE Terms"],
    "affiliations": ["Affiliations", "Addresses", "Author Address",
                     "Author affiliation", "Author Affiliations"],
    "doc_type": ["Document Type", "Publication Type", "Type", "Item Type"],
    "language": ["Language"],
    "cited_by": ["Cited by", "Times cited", "Times Cited, All Databases",
                 "Citation Count"],
    "url": ["URL", "Link", "PDF Link"],
    "source_id": ["Accession Number", "ID", "Publication ID",
                  "UT (Unique WOS ID)"],
    "pmid": ["PMID", "PubMed ID", "Pubmed Id"],
    "scopus_id": ["EID", "Scopus ID"],
    "open_access": ["Open Access"],
}

# Embase (Elsevier) CSV export.  Distinguishing features: the PubMed and
# Embase identifiers ship in their own columns -- which is why an Embase CSV
# is worth mapping natively rather than through the generic map, since those
# two identifiers drive the first two stages of the duplicate cascade in
# :mod:`corpusslr.dedup` -- and the venue column is "Source title" while the
# author column is "Author Names".
_EMBASE = {
    "title": ["Title"],
    "authors": ["Author Names", "Authors", "Author"],
    "year": ["Date of Publication", "Publication Year", "Year"],
    "journal": ["Source title", "Source Title", "Journal"],
    "doi": ["DOI"],
    "abstract": ["Abstract"],
    "volume": ["Volume"],
    "issue": ["Issue"],
    "pages": ["Pages", "Page Range"],
    "issn": ["ISSN", "CODEN"],
    "keywords": ["Author Keywords", "Emtree Drug Index Terms",
                 "Emtree Medical Index Terms"],
    "keywords2": ["Emtree Medical Index Terms (Major Focus)",
                  "Emtree Drug Index Terms (Major Focus)"],
    "affiliations": ["Author Address", "Affiliations"],
    "doc_type": ["Publication Type", "Document Type"],
    "language": ["Language of Article", "Language"],
    "url": ["Full Text Link", "Embase Link"],
    "pmid": ["Medline PMID", "PMID"],
    "source_id": ["Embase Accession ID", "Accession Number", "PUI"],
}

# ProQuest (ABI/INFORM, Dissertations & Theses).  ProQuest's own column names
# are lower-cased with spaces ("publication title", "StoreId"), and the
# document identifier appears either as "StoreId" or inside the "document url"
# as ``/docview/<id>``.
_PROQUEST = {
    "title": ["Title", "Document Title"],
    "authors": ["Author", "Authors"],
    "year": ["Publication year", "Year", "publication date"],
    "journal": ["publication title", "Publication Title", "Journal"],
    "doi": ["DOI", "digitalObjectIdentifier"],
    "abstract": ["Abstract"],
    "volume": ["Volume"],
    "issue": ["Issue"],
    "pages": ["Pages", "pagination"],
    "issn": ["ISSN", "eISSN", "ISBN"],
    "keywords": ["Subject", "subjectTerms", "Keywords"],
    "keywords2": ["Identifier / keyword", "identifierKeywords"],
    "affiliations": ["Author affiliation", "Affiliations"],
    "doc_type": ["Document type", "Source type", "Publication type"],
    "language": ["Language of Publication", "Language"],
    "url": ["document url", "Document URL", "URL"],
    "source_id": ["StoreId", "ProQuest document ID", "Accession Number"],
}

CSV_DIALECTS = {
    "scopus": _SCOPUS, "wos": _WOS, "ieee": _IEEE,
    "dimensions": _DIMENSIONS, "ebsco": _EBSCO, "embase": _EMBASE,
    "proquest": _PROQUEST, "generic": _GENERIC,
}

# Signature headers: (canonical header, weight).  Weight 3 = unique to the
# vendor, 2 = strongly indicative, 1 = weak corroboration.
_SIGNATURES: Dict[str, Sequence[Tuple[str, int]]] = {
    "scopus": (("eid", 3), ("citedby", 2), ("authorkeywords", 1),
               ("indexkeywords", 2), ("sourcetitle", 1),
               ("languageoforiginaldocument", 2), ("documenttype", 1)),
    "wos": (("utuniquewosid", 3), ("utuniqueid", 3), ("articletitle", 2),
            ("publicationyear", 1), ("keywordsplus", 3),
            ("timescitedalldatabases", 3), ("timescitedwoscore", 3),
            ("authorfullnames", 1)),
    "ieee": (("documenttitle", 3), ("ieeeterms", 3),
             ("inspeccontrolledterms", 3), ("publicationtitle", 2),
             ("pdflink", 2), ("articlecitationcount", 2)),
    "dimensions": (("pubyear", 3), ("publicationid", 3), ("timescited", 2),
                   ("dimensionsurl", 3), ("sourcelinkout", 2),
                   ("meshterms", 1)),
    "ebsco": (("accessionnumber", 3), ("plink", 3), ("subjectterms", 2),
              ("journal", 1), ("an", 1)),
    # "Embase Accession ID" and the Emtree thesaurus columns occur in no other
    # vendor's export; "Medline PMID" is Elsevier's spelling of the PMID
    # column and does not appear in a PubMed or WoS export.
    "embase": (("embaseaccessionid", 3), ("medlinepmid", 3),
               ("emtreedrugindexterms", 3), ("emtreemedicalindexterms", 3),
               ("authornames", 2), ("dateofpublication", 2),
               ("languageofarticle", 2)),
    # ProQuest's "StoreId" and "document url" are unique to its platform;
    # "publication title" is shared with IEEE, hence only weight 1.
    "proquest": (("storeid", 3), ("proquestdocumentid", 3),
                 ("documenturl", 3), ("identifierkeyword", 2),
                 ("subjectterms", 1), ("publicationyear", 1),
                 ("publicationtitle", 1)),
}

_MIN_SCORE = 3

#: Namespace of the surrogate record key CorpusSLR writes into the ``EID``
#: column of its own Scopus export.  Declared here rather than imported from
#: :mod:`corpusslr.export` to keep the parser package free of a dependency on
#: the writer; ``tests/test_export_scopus.py`` asserts the two agree, so the
#: duplication cannot drift silently.
_SURROGATE_EID_PREFIX = "corpusslr:"


def detect_csv_dialect(header_row) -> str:
    """Return the vendor whose signature columns best match *header_row*.

    Accepts a list of header cells or a raw header line.  Returns
    ``"generic"`` when no vendor scores above the confidence floor, which is
    the safe outcome: the generic map covers the union of common header
    names and merely loses vendor-specific identifiers.
    """
    if header_row is None:
        return "generic"
    cells = (_split_header_line(header_row) if isinstance(header_row, str)
             else list(header_row))
    keys = {_key(c) for c in cells if _key(c)}
    if not keys:
        return "generic"
    best, best_score = "generic", 0
    for name, sig in _SIGNATURES.items():
        score = sum(w for col, w in sig if col in keys)
        if score > best_score:
            best, best_score = name, score
    return best if best_score >= _MIN_SCORE else "generic"


def _split_header_line(line: str) -> List[str]:
    """Split the first line of *line* into header cells.

    Callers pass either a bare header line or a whole export (detecting the
    dialect from a file's text is the common case), so only the first physical
    line is handed to the reader -- feeding it a multi-line string raises
    ``_csv.Error: new-line character seen in unquoted field``.
    """
    delim = _sniff_delimiter(line)
    first = line.splitlines()[0] if line.splitlines() else line
    return next(csv.reader([first], delimiter=delim), [])


def _sniff_delimiter(sample: str) -> str:
    """Pick the field delimiter, falling back to a count outside quotes.

    :class:`csv.Sniffer` raises ``csv.Error`` on single-column files and
    mis-detects when a quoted abstract contains many semicolons, so its
    verdict is only accepted when it agrees with the candidate set.
    """
    head = sample[:8192]
    line = head.splitlines()[0] if head.splitlines() else head
    counts = {}
    for cand in (",", ";", "\t", "|"):
        inq, n = False, 0
        i = 0
        while i < len(line):
            ch = line[i]
            if ch == '"':
                if inq and i + 1 < len(line) and line[i + 1] == '"':
                    i += 1
                else:
                    inq = not inq
            elif ch == cand and not inq:
                n += 1
            i += 1
        counts[cand] = n
    best = max(counts, key=lambda c: counts[c])
    if counts[best] == 0:
        return ","
    # A vendor header legitimately contains commas inside a column name
    # ("Times Cited, All Databases" in Web of Science TSV).  Sniffer picks
    # the comma there, so its verdict is only trusted when no other
    # candidate occurs markedly more often on the header line.
    try:
        sniffed = csv.Sniffer().sniff(head, delimiters=",;\t|").delimiter
        if counts.get(sniffed, 0) >= counts[best]:
            return sniffed
    except (csv.Error, IndexError):
        pass
    return best


def _build_index(fieldnames: Sequence[str], mapping: Dict[str, List[str]]
                 ) -> Dict[str, str]:
    """Resolve the vendor map against the actual header row.

    Returns ``{logical_field: actual_header}``.  Falls back to the generic
    map for any logical field the vendor map does not resolve, so a Scopus
    file re-saved with an extra ``PMID`` column still yields the PMID.
    """
    present = {}
    for fn in fieldnames:
        k = _key(fn)
        if k and k not in present:
            present[k] = fn
    index: Dict[str, str] = {}
    for logical, candidates in mapping.items():
        for cand in candidates:
            k = _key(cand)
            if k in present:
                index[logical] = present[k]
                break
    if mapping is not _GENERIC:
        for logical, candidates in _GENERIC.items():
            if logical in index:
                continue
            for cand in candidates:
                k = _key(cand)
                if k in present:
                    index[logical] = present[k]
                    break
    return index


_OA_TRUE = ("yes", "true", "gold", "green", "hybrid", "bronze", "all open",
            "open access", "doaj", "1")
_OA_FALSE = ("no", "false", "0", "closed", "subscription", "none")


def _open_access(value: str) -> Optional[bool]:
    v = collapse_ws(value).lower()
    if not v:
        return None
    for token in _OA_TRUE:
        if token in v:
            return True
    for token in _OA_FALSE:
        if v == token or v.startswith(token):
            return False
    return None


def parse_csv_rows(rows: Sequence[Sequence[str]], dialect: str = "auto",
                   source_name: str = "",
                   report: Optional[ParseReport] = None) -> List[Record]:
    """Map an already-split cell grid onto records.

    Exposed separately from :func:`parse_csv_export` so that the HTML-table
    reader in :mod:`corpusslr.parsers.html_table` -- ProQuest and Web of
    Science both ship HTML documents named ``.xls`` -- reuses the identical
    vendor column mapping and field normalisation.  Two code paths mapping the
    same vendor columns would drift, and the drift would be invisible: the two
    exports of one search would stop deduplicating against each other.

    *rows* is a sequence whose first element is the header row.
    """
    rep = _ensure(report, "csv")
    grid = [list(r) for r in rows if r is not None]
    if not grid:
        return []
    fieldnames = [collapse_ws(c) for c in grid[0]]
    if not any(fieldnames):
        rep.saw(len(grid))
        for i in range(len(grid)):
            rep.reject(i, "malformed", "no usable header row")
        return []
    if dialect == "auto":
        dialect = detect_csv_dialect(fieldnames)
    rep.dialect = rep.dialect or dialect
    mapping = CSV_DIALECTS.get(dialect, _GENERIC)
    index = _build_index(fieldnames, mapping)
    dict_rows = []
    width = len(fieldnames)
    for values in grid[1:]:
        row = {}
        for i, name in enumerate(fieldnames):
            if name and name not in row:
                row[name] = values[i] if i < width and i < len(values) else ""
        dict_rows.append(row)
    return _rows_to_records(dict_rows, index, dialect, source_name, rep)


def _rows_to_records(rows, index: Dict[str, str], dialect: str,
                     source_name: str, rep: ParseReport) -> List[Record]:
    """Shared row -> Record loop for the CSV and HTML-table code paths."""
    out: List[Record] = []
    for offset, row in enumerate(rows):
        rep.saw()
        if not row:
            rep.reject(offset, "empty", "row carries no cells")
            continue

        def cell(logical: str) -> str:
            col = index.get(logical)
            if not col:
                return ""
            return collapse_ws(row.get(col) or "")

        title = cell("title")
        doi = cell("doi")
        url_raw = cell("url")
        if not doi and url_raw and "doi.org" in url_raw.lower():
            m = re.search(r"10\.\d{4,9}/\S+", url_raw)
            if m:
                doi = m.group(0)
        if not title and not doi:
            if any(collapse_ws(v) for v in row.values()):
                rep.reject(offset, "no_content",
                           "row has no title and no DOI")
            else:
                rep.reject(offset, "empty",
                           "blank row (spreadsheet filler)")
            continue

        pages = clean_pages(cell("pages"))
        if not pages:
            sp, ep = cell("pages_start"), cell("pages_end")
            if sp and ep:
                pages = clean_pages("{}-{}".format(sp, ep))
            elif sp:
                pages = clean_pages(sp)

        keywords = split_keywords(cell("keywords"))
        seen = {k.lower() for k in keywords}
        for kw in split_keywords(cell("keywords2")):
            if kw.lower() not in seen:
                seen.add(kw.lower())
                keywords.append(kw)

        url = url_raw
        scopus_id = cell("scopus_id")
        # A CorpusSLR-written Scopus CSV puts a namespaced surrogate key in
        # the EID column when the record has no Scopus identifier (see
        # corpusslr.export._surrogate_eid: bibliometrix deduplicates a Scopus
        # CSV on that column, so an empty one collapses the corpus).  Reading
        # it back as a *Scopus* identifier would fabricate one, and the
        # duplicate cascade treats a shared scopus_id as strong evidence.  It
        # is therefore kept as the record id and cleared from scopus_id.
        surrogate = scopus_id.startswith(_SURROGATE_EID_PREFIX)
        if surrogate:
            scopus_id = ""
        source_id = cell("source_id") or scopus_id
        if surrogate and not source_id:
            source_id = collapse_ws(row.get(index.get("scopus_id", "")) or "")
        if not source_id and dialect == "ieee" and url:
            # IEEE Xplore CSV carries no record id column; the stable
            # accession number is the arnumber inside the PDF link.
            m = re.search(r"arnumber=(\d+)", url)
            if m:
                source_id = m.group(1)
        if not source_id and dialect == "proquest" and url:
            m = re.search(r"docview/(\d+)", url)
            if m:
                source_id = m.group(1)

        # Every vendor writes one address per distinct affiliation, separated by
        # "; ", which is also what bibliometrix expects in C1. Splitting on that
        # separator keeps the addresses countable; splitting on the comma inside
        # an address would shred "Dept, University, City, Country" into four.
        affiliations = [a.strip() for a in cell("affiliations").split(";")
                        if a.strip()]

        rec = Record(
            title=title,
            abstract=cell("abstract"),
            authors=split_authors(cell("authors")),
            affiliations=affiliations,
            year=parse_year(cell("year")),
            journal=cell("journal"),
            doi=doi,
            pmid=re.sub(r"\D", "", cell("pmid")),
            scopus_id=scopus_id,
            issn=cell("issn"),
            volume=cell("volume"),
            issue=cell("issue"),
            pages=pages,
            doc_type=map_doc_type(cell("doc_type")),
            language=cell("language").lower(),
            keywords=keywords,
            url=url,
            open_access=_open_access(cell("open_access")),
            cited_by=parse_int(cell("cited_by")),
            source=source_name or "CSV/{}".format(dialect),
            source_id=source_id,
            raw={"dialect": dialect,
                 "row": {k: v for k, v in row.items() if k and v}},
        )
        out.append(rec)
    rep.accept(len(out))
    return out


def parse_csv_export(text: str, dialect: str = "auto",
                     source_name: str = "",
                     delimiter: Optional[str] = None,
                     report: Optional[ParseReport] = None) -> List[Record]:
    """Parse a CSV/TSV database export into records.

    *dialect* is one of :data:`CSV_DIALECTS` or ``"auto"`` (default), in
    which case the header row is fingerprinted by
    :func:`detect_csv_dialect`.  Rows without a title and without a DOI are
    skipped -- they are the blank trailing rows Excel appends -- and, when a
    :class:`~corpusslr.parsers._report.ParseReport` is supplied, each such row
    is counted with a reason so the import can be reconciled against the file.

    An HTML document handed in here (ProQuest and Web of Science both name
    their HTML export ``.xls``) is routed to
    :func:`corpusslr.parsers.html_table.parse_html_table` instead of being
    read as one garbage record per markup line.
    """
    rep = _ensure(report, "csv")
    if not text or not text.strip():
        return []
    text = text.lstrip("\ufeff")
    if looks_like_html(text):
        from .html_table import parse_html_table
        rep.warn("input is an HTML document, not delimited text; parsed as "
                 "an HTML table (ProQuest/WoS name this export '.xls')")
        return parse_html_table(text, dialect=dialect,
                                source_name=source_name, report=rep)
    delim = delimiter or _sniff_delimiter(text)
    # StringIO's second argument is *newline*, and the newline="" recipe the
    # csv docs give for open() does NOT transfer to a str already in memory:
    # it leaves the terminators in the buffer and every vendor export raised
    # "new-line character seen in unquoted field". Measured across the three
    # line endings a real export can carry:
    #
    #   newline=None -> LF, CRLF and CR all parse; embedded newlines normalized
    #   newline="\n" -> CR raises; CRLF leaves \r\n inside quoted abstracts
    #   newline=""   -> parses, but leaks \r\n / \r into field values
    #
    # Universal-newline handling is therefore the only correct choice here.
    # The stdlib reader aborts the WHOLE file with _csv.Error when any single
    # field exceeds 131 072 characters, and real rows do: a Scopus record with
    # a full abstract plus a 400-author affiliation list runs past 200 kB.
    # Raising the limit for the duration of the parse turns "5 000 records
    # lost" into "5 000 records parsed".
    with csv_field_limit():
        reader = csv.DictReader(io.StringIO(text, newline=None),
                                delimiter=delim)
        try:
            fieldnames = [f for f in (reader.fieldnames or [])
                          if f is not None]
        except csv.Error as exc:
            rep.saw(1)
            rep.reject(0, "malformed",
                       "header row unreadable: {}".format(exc))
            return []
        if not fieldnames:
            return []
        if dialect == "auto":
            dialect = detect_csv_dialect(fieldnames)
        rep.dialect = rep.dialect or dialect
        mapping = CSV_DIALECTS.get(dialect, _GENERIC)
        index = _build_index(fieldnames, mapping)

        rows: List[dict] = []
        while True:
            # Iterating row-by-row inside try/except keeps a single malformed
            # row (an unbalanced quote from a truncated download) from
            # discarding the rows that follow it.
            try:
                row = next(reader)
            except StopIteration:
                break
            except csv.Error as exc:
                rep.saw(1)
                rep.reject(len(rows), "malformed",
                           "unreadable row: {}".format(exc))
                continue
            rows.append(row)
        return _rows_to_records(rows, index, dialect, source_name, rep)


def parse_csv_export_file(path: str, dialect: str = "auto",
                          source_name: str = "",
                          encoding: str = "auto",
                          delimiter: Optional[str] = None,
                          report: Optional[ParseReport] = None
                          ) -> List[Record]:
    """Read *path* and parse it with :func:`parse_csv_export`.

    ``encoding="auto"`` (the default) sniffs the byte-order mark and the
    NUL-padding of a Windows UTF-16 export.  The previous fixed
    ``"utf-8-sig"`` decoded a UTF-16 file into NUL-separated characters that
    matched no header, so the export silently yielded **zero** records.
    """
    rep = _ensure(report, "csv")
    text = read_export_text(path, encoding=encoding, report=rep)
    if not text:
        return []
    return parse_csv_export(text, dialect=dialect, source_name=source_name,
                            delimiter=delimiter, report=rep)
