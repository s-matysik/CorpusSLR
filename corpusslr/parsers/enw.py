"""EndNote *tagged* export parser (``.enw``).

There are two unrelated formats both called "EndNote export", and confusing
them costs a whole database:

``EndNote XML``
    ``<xml><records><record>...`` -- handled by
    :mod:`corpusslr.parsers.endnote`.  This is what EndNote itself writes and
    what Web of Science offers as "EndNote desktop".

``EndNote tagged`` (this module)
    Line-oriented, ``%``-prefixed single-character tags::

        %0 Conference Paper
        %A Chen, Wei
        %T Neural retrieval for systematic reviews
        %R 10.1145/3583780.3614999

    This is what the **ACM Digital Library** produces when a user clicks
    *Export Citation -> EndNote*, and also what PubMed's "Citation manager"
    and several EBSCOhost interfaces emit.  It is not XML and not RIS, so
    neither of the other parsers reads it: before this module existed an ACM
    ``.enw`` file parsed to zero records.

Tag semantics follow the EndNote import filter specification.  The two that
need judgement are ``%J``/``%B`` and ``%@``:

* ``%J`` is the periodical title and ``%B`` the "secondary title", which for
  a conference paper *is* the proceedings name.  ACM exports conference
  papers with the proceedings in ``%B`` and no ``%J`` at all, so the journal
  field falls back ``%J`` -> ``%B`` -> ``%S``; without the ``%B`` fallback
  every ACM conference paper would have an empty venue and would fail the
  journal-based blocking key in :mod:`corpusslr.dedup`.
* ``%@`` carries an ISSN for serials and an ISBN for books/proceedings in the
  same tag.  They are told apart by shape (``dddd-dddd`` vs 10/13 digits), so
  that an ISBN is never written into the ``issn`` field where the identifier
  cascade would compare it against real ISSNs.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from ..record import Record
from ._io import read_export_text
from ._report import ParseReport, _ensure
from ._util import (clean_pages, collapse_ws, map_doc_type, parse_year,
                    split_authors, split_keywords)

__all__ = ["parse_enw", "parse_enw_file", "looks_like_enw", "ENW_TAGS"]

# Tag -> human-readable name, for documentation and the parse report.  Only
# tags CorpusSLR maps are listed; unknown tags are preserved in raw['tags'].
ENW_TAGS = {
    "0": "reference type", "A": "author", "T": "title",
    "B": "secondary title (book/proceedings)", "S": "tertiary title (series)",
    "J": "periodical title", "D": "year", "8": "date", "V": "volume",
    "N": "issue", "P": "pages", "I": "publisher", "C": "place published",
    "R": "DOI", "U": "URL", "K": "keywords", "X": "abstract", "Z": "notes",
    "@": "ISSN/ISBN", "M": "accession number", "G": "language",
    "E": "editor", "F": "label", "L": "call number", "&": "section",
    "!": "short title", "(": "original publication", ")": "reprint edition",
}

# ``%`` followed by exactly one non-space tag character, then whitespace.
_TAG_RE = re.compile(r"^%(.)[ \t]?(.*)$")

_ISSN_RE = re.compile(r"^\d{4}-\d{3}[\dxX]$")
_ISBN_RE = re.compile(r"^(?:97[89][- ]?)?[\d][\d\- ]{7,}[\dxX]$")
_PMID_RE = re.compile(r"(?:pmid|pubmed)[:\s]*(\d{5,9})", re.I)
_BARE_PMID_RE = re.compile(r"^\d{5,9}$")
_DOI_RE = re.compile(r"10\.\d{4,9}/\S+", re.I)

#: ``%0`` reference-type labels that the controlled vocabulary of
#: :func:`corpusslr.parsers._util.map_doc_type` does not resolve on its own.
_REF_TYPE_EXTRA = {
    "electronic article": "article",
    "journal": "article",
    "newspaper article": "article",
    "magazine article": "article",
    "conference proceedings": "conference",
    "conference paper": "conference",
    "web page": "",
    "generic": "",
}


def looks_like_enw(text: str) -> bool:
    """True when *text* is EndNote tagged rather than RIS, XML or BibTeX.

    Two ``%`` tag lines in the first part of the file are required, because a
    single ``%`` line also occurs in the middle of LaTeX or of an RIS note
    field; a leading ``<`` or ``@`` rules the format out immediately.
    """
    head = text[:8000].lstrip("\ufeff \t\r\n")
    if head[:1] in ("<", "@"):
        return False
    hits = 0
    for line in head.splitlines():
        if _TAG_RE.match(line):
            hits += 1
            if hits >= 2:
                return True
    return False


def _split_records(text: str) -> List[List[Tuple[str, str]]]:
    """Split tagged text into per-record ``(tag, value)`` lists.

    Records are separated by blank lines, but exports in the wild omit the
    separator, so a second ``%0`` also starts a new record.  Untagged
    non-blank lines continue the previous value, which is how abstracts wrap.
    """
    records: List[List[Tuple[str, str]]] = []
    current: List[Tuple[str, str]] = []
    for line in text.replace("\ufeff", "").splitlines():
        m = _TAG_RE.match(line)
        if m:
            tag, val = m.group(1), m.group(2).strip()
            if tag == "0" and current:
                records.append(current)
                current = []
            current.append((tag, val))
        elif not line.strip():
            if current:
                records.append(current)
                current = []
        elif current:
            tag, val = current[-1]
            current[-1] = (tag, (val + " " + line.strip()).strip())
    if current:
        records.append(current)
    return records


def _doc_type(label: str) -> str:
    """Resolve a ``%0`` reference-type label to the controlled vocabulary."""
    low = collapse_ws(label).lower()
    if not low:
        return ""
    if low in _REF_TYPE_EXTRA:
        return _REF_TYPE_EXTRA[low]
    return map_doc_type(low)


def parse_enw(text: str, source_name: str = "",
              report: Optional[ParseReport] = None) -> List[Record]:
    """Parse EndNote tagged (``.enw``) *text* into records.

    Passing a :class:`~corpusslr.parsers._report.ParseReport` makes the import
    auditable: every stanza that is dropped for lack of a title and identifier
    is counted with a reason, so the "records identified" figure of a PRISMA
    2020 flow diagram can be reconciled against the file.
    """
    rep = _ensure(report, "enw", "endnote-tagged")
    out: List[Record] = []
    for index, raw in enumerate(_split_records(text)):
        rep.saw()
        fields: Dict[str, List[str]] = {}
        for tag, val in raw:
            if val:
                fields.setdefault(tag, []).append(val)
        if not fields:
            rep.reject(index, "empty", "stanza carries no tagged values")
            continue

        def first(*tags: str) -> str:
            for t in tags:
                if fields.get(t):
                    return fields[t][0]
            return ""

        title = collapse_ws(first("T", "!"))
        doc_type = _doc_type(first("0"))
        journal = collapse_ws(first("J", "B", "S"))

        doi = ""
        for cand in fields.get("R", []) + fields.get("U", []) \
                + fields.get("Z", []) + fields.get("3", []):
            m = _DOI_RE.search(cand)
            if m:
                doi = m.group(0).rstrip(".,;)")
                break

        issn = ""
        isbn = ""
        for cand in fields.get("@", []):
            value = collapse_ws(cand).replace(" ", "")
            if _ISSN_RE.match(value):
                issn = issn or value
            elif _ISBN_RE.match(value):
                isbn = isbn or value
            elif not issn and not isbn:
                # Unrecognised shape: keep it out of ``issn`` so the
                # identifier cascade never compares it against a real ISSN.
                isbn = value

        pmid = ""
        for cand in fields.get("M", []) + fields.get("Z", []) \
                + fields.get("1", []):
            m = _PMID_RE.search(cand)
            if m:
                pmid = m.group(1)
                break
            value = collapse_ws(cand)
            if _BARE_PMID_RE.match(value) and not pmid:
                pmid = value

        keywords: List[str] = []
        for cand in fields.get("K", []):
            for kw in split_keywords(cand):
                if kw.lower() not in {k.lower() for k in keywords}:
                    keywords.append(kw)

        url = ""
        for cand in fields.get("U", []):
            value = collapse_ws(cand)
            if value.lower().startswith(("http://", "https://", "doi:")):
                url = value
                break
        if not url and doi:
            url = "https://doi.org/" + doi

        authors: List[str] = []
        for cand in fields.get("A", []):
            authors.extend(split_authors(cand))

        source_id = collapse_ws(first("M", "F", "L"))
        rec = Record(
            title=title,
            abstract=collapse_ws(first("X")),
            authors=authors,
            year=parse_year(first("D", "8")),
            journal=journal,
            doi=doi.lower(),
            pmid=pmid,
            issn=issn,
            volume=collapse_ws(first("V")),
            issue=collapse_ws(first("N")),
            pages=clean_pages(first("P")),
            doc_type=doc_type,
            language=collapse_ws(first("G")).lower(),
            keywords=keywords,
            url=url,
            source=source_name or collapse_ws(first("I")) or "EndNote",
            source_id=source_id,
            raw={"format": "enw", "tags": dict(fields),
                 "isbn": isbn, "publisher": collapse_ws(first("I")),
                 "place": collapse_ws(first("C")),
                 "reference_type": collapse_ws(first("0")),
                 "editors": [e for c in fields.get("E", [])
                             for e in split_authors(c)]},
        )
        if not (rec.title or rec.doi or rec.pmid):
            rep.reject(index, "no_content",
                       "stanza has no title and no identifier")
            continue
        out.append(rec)
    rep.accept(len(out))
    return out


def parse_enw_file(path: str, source_name: str = "",
                   encoding: str = "auto",
                   report: Optional[ParseReport] = None) -> List[Record]:
    """Read and parse an EndNote tagged file, sniffing the encoding.

    ``encoding="auto"`` is the default because ACM and EBSCOhost differ on
    whether the file carries a UTF-8 byte-order mark.
    """
    rep = _ensure(report, "enw", "endnote-tagged")
    text = read_export_text(path, encoding=encoding, report=rep)
    if not text:
        return []
    return parse_enw(text, source_name=source_name, report=rep)
