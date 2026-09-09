"""Exports: CSV, RIS, BibTeX and a screening-ready CSV.

``to_screening_csv`` emits the column layout consumed by title-abstract
screening tools (ASReview-compatible: ``title, abstract, authors, year,
doi, record_id``) and by embedding-based rankers such as EmbedSLR.
"""
from __future__ import annotations

import csv
import hashlib
import re
from typing import Iterable, List

from .record import Record

_RIS_TYPE = {"article": "JOUR", "review": "JOUR", "conference": "CONF",
             "chapter": "CHAP", "book": "BOOK", "thesis": "THES",
             "report": "RPRT"}

_FORMULA_LEAD = ("=", "+", "-", "@", "\t", "\r")


def _safe_cell(value):
    """Prefix a leading =/+/-/@ with an apostrophe (CSV injection defence).

    Bibliographic titles legitimately start with '-' or '+' (chemical names,
    charge states), and spreadsheets evaluate such cells as formulas when a
    screening CSV is opened in Excel or Sheets. Quoting keeps the text visible
    while stopping evaluation.
    """
    if isinstance(value, str) and value.startswith(_FORMULA_LEAD):
        return "'" + value
    return value


def to_csv(records: Iterable[Record], path: str,
           columns: List[str] | None = None) -> str:
    """Write records to CSV, returning the path written.

    Leading ``=``, ``+``, ``-`` and ``@`` are neutralised in every cell: a title
    beginning with a hyphen is a formula to a spreadsheet, and a corpus is
    routinely opened in one. Pass ``columns`` to choose and order the fields;
    list-valued fields are joined with ``"; "``.
    """
    columns = columns or ["uid", "title", "abstract", "authors", "year",
                          "journal", "doi", "pmid", "openalex_id",
                          "scopus_id", "issn", "doc_type", "language",
                          "cited_by", "source", "search_id"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(columns)
        for r in records:
            row = []
            for c in columns:
                v = getattr(r, c, "")
                if isinstance(v, list):
                    v = "; ".join(str(x) for x in v)
                row.append("" if v is None else _safe_cell(v))
            w.writerow(row)
    return path


def to_screening_csv(records: Iterable[Record], path: str) -> str:
    """Write the columns a screening tool needs, returning the path written.

    Deliberately narrow -- uid, title, abstract, authors, year, DOI -- because
    this file is the handoff to ASReview, Rayyan or a spreadsheet, and a wide
    export makes a human screener scroll past the two fields that matter. Cells
    are neutralised against spreadsheet formula injection.
    """
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["record_id", "title", "abstract", "authors", "year", "doi"])
        for r in records:
            w.writerow([r.uid, _safe_cell(r.title), _safe_cell(r.abstract),
                        _safe_cell("; ".join(r.authors)), r.year or "", r.doi])
    return path


#: Column names and their order in a Scopus CSV export, transcribed from the
#: header row of real exports (two independent Scopus downloads, 46 columns
#: each, byte-identical header) and cross-checked against the ``scopus``
#: dialect map in :mod:`corpusslr.parsers.csv_exports`, which is what reads
#: such a file back in.  The order is reproduced verbatim rather than
#: rearranged: ``bibliometrix::convert2df`` and VOSviewer both address columns
#: by name, but a reviewer who opens the file next to a genuine Scopus export
#: needs the two to look alike, and a diff of the header row is the cheapest
#: check that the format has not drifted.
SCOPUS_COLUMNS = (
    "Authors", "Author full names", "Author(s) ID", "Title", "Year",
    "Source title", "Volume", "Issue", "Art. No.", "Page start", "Page end",
    "Page count", "Cited by", "DOI", "Link", "Affiliations",
    "Authors with affiliations", "Abstract", "Author Keywords",
    "Index Keywords", "Molecular Sequence Numbers", "Chemicals/CAS",
    "Tradenames", "Manufacturers", "Funding Details", "Funding Texts",
    "References", "Correspondence Address", "Editors", "Publisher",
    "Sponsors", "Conference name", "Conference date", "Conference location",
    "Conference code", "ISSN", "ISBN", "CODEN", "PubMed ID",
    "Language of Original Document", "Abbreviated Source Title",
    "Document Type", "Publication Stage", "Open Access", "Source", "EID",
)

#: ``Record.doc_type`` (controlled vocabulary) -> the label Scopus prints in
#: its ``Document Type`` column.  Every value here maps back onto the same
#: ``doc_type`` through :func:`corpusslr.parsers._util.map_doc_type`, which is
#: what makes the export/parse round trip type-preserving; the test suite
#: asserts that for the whole table rather than trusting this comment.
_SCOPUS_DOC_TYPE = {
    "article": "Article",
    "review": "Review",
    "conference": "Conference Paper",
    "chapter": "Book Chapter",
    "book": "Book",
    "thesis": "Thesis",
    "report": "Report",
    "editorial": "Editorial",
    "letter": "Letter",
    "preprint": "Preprint",
}


#: Namespace prefix of the surrogate record key written to ``EID`` when a
#: record carries no Scopus identifier.  Deliberately *not* shaped like a
#: Scopus EID (``2-s2.0-<digits>``): the value must be impossible to mistake
#: for one, because inventing a Scopus identifier would be fabricating
#: metadata and would collide with the real identifier space.
SURROGATE_EID_PREFIX = "corpusslr:"


def _surrogate_eid(record: Record) -> str:
    """Return a stable, collision-free record key for the ``EID`` column.

    ``bibliometrix::convert2df(dbsource = "scopus", format = "csv")`` **drops
    every record whose EID repeats**: for the CSV format it sets
    ``id_field <- "UT"`` (fed from ``EID``) and applies
    ``duplicated(M[id_field])``.  An empty EID is a value like any other, so a
    corpus assembled from sources that assign no Scopus identifier --
    Crossref, PubMed, arXiv, Web of Science -- collapses to a *single* record.
    Measured on 20 records with 20 distinct titles and 20 distinct DOIs but no
    EID: bibliometrix reported "Removed 19 duplicated documents" and returned
    1 row.  Leaving the column empty is therefore not the cautious option; it
    is the option that silently destroys the corpus.

    The key is derived, never invented, and is namespaced with
    :data:`SURROGATE_EID_PREFIX` so no reader can mistake it for a Scopus EID:

    * a DOI is globally unique, so ``corpusslr:10.1016/j.jbusres.2024.001``
      is used when one is present;
    * otherwise PubMed, OpenAlex or the source's own record id, in that order;
    * otherwise a SHA-1 of the normalized title and year.

    Deriving it from the metadata rather than from ``Record.uid`` matters:
    ``uid`` is sequential *within* one corpus, so two independently exported
    corpora would both contain ``R000001`` for different works and a later
    re-import would merge them.  A DOI- or title-derived key is stable across
    corpora, so the same work exported twice yields the same key and the
    re-import merges *correctly* -- the surrogate strengthens the identifier
    cascade instead of poisoning it.
    """
    if record.doi:
        return SURROGATE_EID_PREFIX + record.doi
    if record.pmid:
        return SURROGATE_EID_PREFIX + "pmid:" + record.pmid
    if record.openalex_id:
        return SURROGATE_EID_PREFIX + "openalex:" + record.openalex_id
    if record.source_id:
        return SURROGATE_EID_PREFIX + "srcid:" + record.source_id
    stem = "{}|{}".format(record.norm_title, record.year or "")
    digest = hashlib.sha1(stem.encode("utf-8")).hexdigest()[:16]
    return SURROGATE_EID_PREFIX + "sha1:" + digest


def _split_pages(pages: str):
    """Split a ``start-end`` page range into the two Scopus columns.

    Scopus keeps the first and last page in separate columns, so a record
    whose ``pages`` is ``"114-128"`` has to be taken apart again on the way
    out.  A single page (``"114"``) fills only ``Page start``; anything that
    does not look like a range (``"e0123456"``, ``"S12-S18"``) is written to
    ``Page start`` whole rather than guessed at, because a wrong split is
    worse than an unsplit cell -- the reader
    (:func:`corpusslr.parsers.csv_exports.parse_csv_export`) reconstructs
    ``pages`` from ``Page start`` alone when ``Page end`` is empty.
    """
    text = (pages or "").strip()
    if not text:
        return "", ""
    if text.count("-") == 1:
        start, end = text.split("-", 1)
        start, end = start.strip(), end.strip()
        if start and end:
            return start, end
    return text, ""


def to_scopus_csv(records: Iterable[Record], path: str) -> str:
    """Write records as a Scopus CSV export, returning the path written.

    This is the canonical hand-off format of the package: it is the input
    ``bibliometrix::convert2df(dbsource = "scopus", format = "csv")``,
    VOSviewer ("Create a map from bibliographic data" -> Scopus) and EmbedSLR
    all read, so emitting it means the deduplicated corpus goes straight into
    a bibliometric analysis without a hand-written conversion step in between.

    The full 46-column layout of :data:`SCOPUS_COLUMNS` is written even though
    :class:`~corpusslr.record.Record` cannot fill all of it.  Two reasons: the
    consumers address columns by name and a missing column is a hard error in
    ``convert2df``, whereas an *empty* column is missing data it reports; and
    a file with the genuine header can be concatenated with a real Scopus
    download.  Columns with no counterpart in the record schema
    (``Affiliations``, ``References``, ``Funding Details``, the conference
    block, ...) are therefore written **empty and never invented** -- an
    affiliation string synthesised out of nothing would silently become a
    finding in someone's collaboration map.

    Two conversions are lossy in the direction the Scopus format itself is
    lossy, and are documented rather than papered over:

    * ``open_access=False`` is written as an empty cell, because a Scopus
      export marks open access and says nothing at all about closed access.
      Reading the file back yields ``None`` (unknown), not ``False``.
    * keywords are written to ``Author Keywords`` only.  ``Record`` holds one
      merged keyword list, and splitting it back into author-supplied and
      index terms is not possible; writing the same list into both columns
      would assert that Scopus indexed those terms.

    The ``Source`` column carries the record's own provenance (``"Crossref"``,
    ``"PubMed"``, ...) rather than the constant ``"Scopus"`` a genuine export
    prints there.  A merged corpus is not a Scopus download and must not claim
    to be one; the column is informational for the downstream tools, which
    address the metadata columns by name and do not key on it.

    Every cell passes through :func:`_safe_cell`, so a title beginning with
    ``=``, ``+``, ``-`` or ``@`` cannot execute as a formula when the corpus
    is opened in Excel or Google Sheets.
    """
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(list(SCOPUS_COLUMNS))
        for r in records:
            authors = "; ".join(r.authors)
            page_start, page_end = _split_pages(r.pages)
            doc_type = _SCOPUS_DOC_TYPE.get(r.doc_type, r.doc_type or "")
            row = {
                "Authors": authors,
                "Author full names": authors,
                "Title": r.title,
                "Year": r.year if r.year else "",
                "Source title": r.journal,
                "Volume": r.volume,
                "Issue": r.issue,
                "Page start": page_start,
                "Page end": page_end,
                "Cited by": r.cited_by if r.cited_by is not None else "",
                "DOI": r.doi,
                "Link": r.url,
                "Abstract": r.abstract,
                "Author Keywords": "; ".join(r.keywords),
                # bibliometrix reads C1 from this column and derives AU_UN, the
                # institutional collaboration network, from it. Scopus separates
                # distinct addresses with "; ", so joining that way is what the
                # downstream parser expects.
                "Affiliations": "; ".join(r.affiliations),
                "ISSN": r.issn,
                "PubMed ID": r.pmid,
                "Language of Original Document": r.language,
                "Document Type": doc_type,
                # "All Open Access" is the phrasing Scopus uses and the token
                # the CSV reader recognises; the colour of the route (gold,
                # green, hybrid) is not in the record, so it is not claimed.
                "Open Access": "All Open Access" if r.open_access else "",
                "Source": r.source,
                # A real Scopus EID when the record has one; otherwise a
                # namespaced surrogate, because bibliometrix deduplicates a
                # Scopus CSV on this column and an empty one collapses the
                # whole corpus to one row.  See _surrogate_eid.
                "EID": r.scopus_id or _surrogate_eid(r),
            }
            w.writerow([_safe_cell(row.get(col, ""))
                        for col in SCOPUS_COLUMNS])
    return path


def to_ris(records: Iterable[Record], path: str) -> str:
    """Write records as RIS, returning the path written.

    Emits the neutral dialect that reference managers accept -- Zotero, EndNote
    and Mendeley all import it -- rather than reproducing the vendor dialect the
    records were read from.
    """
    lines: List[str] = []
    for r in records:
        lines.append(f"TY  - {_RIS_TYPE.get(r.doc_type, 'JOUR')}")
        for a in r.authors:
            lines.append(f"AU  - {a}")
        if r.title:
            lines.append(f"TI  - {r.title}")
        if r.abstract:
            lines.append(f"AB  - {r.abstract}")
        if r.year:
            lines.append(f"PY  - {r.year}")
        if r.journal:
            lines.append(f"T2  - {r.journal}")
        if r.doi:
            lines.append(f"DO  - {r.doi}")
        if r.issn:
            lines.append(f"SN  - {r.issn}")
        if r.volume:
            lines.append(f"VL  - {r.volume}")
        if r.issue:
            lines.append(f"IS  - {r.issue}")
        if r.pages:
            sp = r.pages.split("-")[0]
            lines.append(f"SP  - {sp}")
            if "-" in r.pages:
                lines.append(f"EP  - {r.pages.split('-')[-1]}")
        for k in r.keywords:
            lines.append(f"KW  - {k}")
        if r.url:
            lines.append(f"UR  - {r.url}")
        if r.language:
            lines.append(f"LA  - {r.language}")
        if r.uid:
            lines.append(f"ID  - {r.uid}")
        lines.append("ER  - ")
        lines.append("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return path


_BIB_ENTRY_TYPE = {"article": "article", "review": "article",
                   "conference": "inproceedings", "chapter": "incollection",
                   "book": "book", "thesis": "phdthesis",
                   "report": "techreport", "preprint": "misc",
                   "editorial": "article", "letter": "article"}


def _bib_escape(s: str) -> str:
    """Escape the ten characters LaTeX treats specially.

    Order matters: the backslash must be escaped FIRST, otherwise the
    backslashes introduced while escaping braces are themselves escaped and the
    output turns into control sequences. An unescaped '$' silently opens math
    mode and deletes the text up to the next '$' when the file is compiled or
    re-parsed.
    """
    # macro replacements go through placeholders so the braces they introduce
    # are not escaped again by the character pass below
    s = (s.replace("\\", "\x00BS\x00")
          .replace("~", "\x00TILDE\x00")
          .replace("^", "\x00CIRC\x00"))
    for ch in ("{", "}", "&", "%", "$", "#", "_"):
        s = s.replace(ch, "\\" + ch)
    return (s.replace("\x00BS\x00", "\\textbackslash{}")
             .replace("\x00TILDE\x00", "\\textasciitilde{}")
             .replace("\x00CIRC\x00", "\\textasciicircum{}"))


def to_bibtex(records: Iterable[Record], path: str) -> str:
    """Write records as BibTeX, returning the path written.

    Entry types follow the record's ``doc_type`` (``article``, ``inproceedings``,
    ``incollection``, ``phdthesis``, ``techreport``, ``misc`` for preprints), so
    a round trip through :func:`parse_bibtex` preserves the type rather than
    flattening everything to ``@article``. Keys are derived from first author,
    year and title and de-duplicated with a suffix.
    """
    used = set()
    entries: List[str] = []
    for r in records:
        base = re.sub(r"[^a-z]", "", (r.first_author_surname or "anon")) or "anon"
        key = f"{base}{r.year or ''}"
        k, i = key, 1
        while k in used:
            i += 1
            k = f"{key}{chr(96 + i)}"
        used.add(k)
        entry_type = _BIB_ENTRY_TYPE.get(r.doc_type, "article")
        # conference papers and chapters carry the venue in booktitle, not journal
        venue_field = ("booktitle" if entry_type in ("inproceedings",
                                                     "incollection")
                       else "journal")
        # @misc is ambiguous (preprint, dataset, software, editorial...), so the
        # document type is written into `type` as well; the parser reads it back
        # and the round-trip preserves doc_type instead of losing it.
        subtype = r.doc_type if entry_type == "misc" else ""
        fields = {
            "title": r.title, "author": " and ".join(r.authors),
            "type": subtype,
            venue_field: r.journal, "year": str(r.year or ""),
            "volume": r.volume, "number": r.issue, "pages": r.pages,
            "doi": r.doi, "issn": r.issn, "url": r.url,
            "language": r.language, "keywords": "; ".join(r.keywords),
            "note": f"PMID: {r.pmid}" if r.pmid else "",
            "abstract": r.abstract,
        }
        body = ",\n".join(f"  {name} = {{{_bib_escape(val)}}}"
                          for name, val in fields.items() if val)
        entries.append(f"@{entry_type}{{{k},\n{body}\n}}")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n\n".join(entries) + "\n")
    return path
