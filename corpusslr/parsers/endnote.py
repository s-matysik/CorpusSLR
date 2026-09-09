"""EndNote XML export parser (``<xml><records><record>``).

EndNote XML is the interchange format of the reference managers that sit
between a database and a screening tool (EndNote itself, but also Zotero,
Mendeley, Rayyan and Covidence, all of which read and write it).  Reviews
frequently arrive as a single EndNote library rather than as per-database
exports, so this parser is what makes such a review reproducible.

Two structural properties of the format require care:

* **Style wrappers.**  EndNote stores rich text as
  ``<title><style face="normal" font="default">…</style></title>`` and
  splits a single title across several ``<style>`` siblings whenever the
  formatting changes mid-string (italic species names, superscripts).
  Reading ``element.text`` returns ``None`` or a fragment; the parser uses
  ``itertext()`` so a title broken over three style runs is reassembled.
* **Ambiguous journal container.**  Depending on the exporting database the
  journal name lands in ``<periodical><full-title>``, in
  ``<titles><secondary-title>`` or in ``<titles><alt-title>``.  All three
  are consulted, in that order.

``ref-type`` carries both a numeric ``name`` attribute and a human label;
the label is mapped onto the controlled ``doc_type`` vocabulary and the
numeric code is used as a fallback (17 = Journal Article, 47 = Conference
Paper, and so on).

Parsing is intentionally forgiving: a malformed record inside an otherwise
valid file is skipped rather than aborting the import, because a partial
corpus with a reported gap is more useful to a reviewer than an exception.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import List, Optional

from ..record import Record
from ._io import read_export_text
from ._report import ParseReport, _ensure
from ._util import (clean_pages, collapse_ws, map_doc_type,
                    normalize_author_name, parse_int, parse_year,
                    split_keywords)

__all__ = ["parse_endnote_xml", "parse_endnote_xml_file"]

# EndNote numeric ref-type codes -> controlled vocabulary.
_REF_TYPE_CODES = {
    "0": "", "1": "", "2": "book", "3": "book", "5": "chapter",
    "6": "conference", "7": "", "9": "", "10": "report", "13": "thesis",
    "16": "", "17": "article", "23": "", "25": "", "27": "thesis",
    "28": "", "31": "", "32": "conference", "34": "",
    "38": "", "43": "", "45": "", "46": "", "47": "conference",
    "48": "conference", "50": "", "63": "preprint", "67": "",
}

_REF_TYPE_LABELS = {
    "journal article": "article", "electronic article": "article",
    "journal": "article", "review": "review",
    "conference paper": "conference", "conference proceedings": "conference",
    "conference": "conference",
    "book section": "chapter", "book chapter": "chapter",
    "edited book": "book", "book": "book",
    "thesis": "thesis", "dissertation": "thesis",
    "report": "report", "government document": "report",
    "manuscript": "preprint", "unpublished work": "preprint",
    "electronic book": "book", "electronic book section": "chapter",
    "newspaper article": "editorial", "magazine article": "editorial",
    "preprint": "preprint", "dataset": "", "web page": "",
}

_DOI_RE = re.compile(r"10\.\d{4,9}/\S+", re.I)
_PMID_RE = re.compile(r"(?:pmid|pubmed)[:\s]*(\d{5,9})", re.I)
_WOS_RE = re.compile(r"(WOS:\d+)", re.I)


def _text(node) -> str:
    """Concatenate all descendant text of *node* (``<style>``-aware)."""
    if node is None:
        return ""
    return collapse_ws("".join(node.itertext()))


def _first_text(parent, *paths: str) -> str:
    for path in paths:
        node = parent.find(path)
        if node is not None:
            val = _text(node)
            if val:
                return val
    return ""


def _all_texts(parent, path: str) -> List[str]:
    out: List[str] = []
    for node in parent.findall(path):
        val = _text(node)
        if val:
            out.append(val)
    return out


def _strip_ns(root) -> None:
    """Drop XML namespaces in place (some exporters emit a default ns)."""
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]


def _doc_type(record) -> str:
    node = record.find("ref-type")
    label = ""
    code = ""
    if node is not None:
        label = collapse_ws(node.get("name") or "").lower()
        code = collapse_ws(node.text or "")
    if not label:
        label = collapse_ws(_first_text(record, "reftype")).lower()
    if label:
        if label in _REF_TYPE_LABELS:
            return _REF_TYPE_LABELS[label]
        mapped = map_doc_type(label)
        if mapped:
            return mapped
    if code and code in _REF_TYPE_CODES:
        return _REF_TYPE_CODES[code]
    return ""


def _build(record) -> Optional[Record]:
    title = _first_text(record, "titles/title", "title")
    journal = _first_text(record, "periodical/full-title",
                          "periodical/abbr-1",
                          "titles/secondary-title",
                          "titles/alt-title",
                          "alt-periodical/full-title")

    authors: List[str] = []
    for path in ("contributors/authors/author",
                 "contributors/secondary-authors/author"):
        for raw in _all_texts(record, path):
            name = normalize_author_name(raw)
            if name and name not in authors:
                authors.append(name)
        if authors:
            break

    keywords: List[str] = []
    for raw in _all_texts(record, "keywords/keyword"):
        for kw in split_keywords(raw):
            if kw.lower() not in {k.lower() for k in keywords}:
                keywords.append(kw)

    abstract = _first_text(record, "abstract")
    doi = _first_text(record, "electronic-resource-num", "doi")
    if doi:
        m = _DOI_RE.search(doi)
        doi = m.group(0) if m else doi

    urls = _all_texts(record, "urls/related-urls/url") \
        or _all_texts(record, "urls/web-urls/url") \
        or _all_texts(record, "urls/pdf-urls/url")
    url = urls[0] if urls else ""
    if not doi and url and "doi.org" in url.lower():
        m = _DOI_RE.search(url)
        if m:
            doi = m.group(0)

    accession = _first_text(record, "accession-num")
    custom = " ".join(_all_texts(record, "custom1")
                      + _all_texts(record, "custom2")
                      + _all_texts(record, "notes")
                      + _all_texts(record, "remote-database-name"))
    pmid = ""
    if accession.isdigit() and 5 <= len(accession) <= 9:
        pmid = accession
    else:
        m = _PMID_RE.search(accession + " " + custom)
        if m:
            pmid = m.group(1)

    pages = clean_pages(_first_text(record, "pages"))
    year = parse_year(_first_text(record, "dates/year", "dates/pub-dates/date",
                                  "year"))

    db = _first_text(record, "remote-database-name", "database", "source-app")
    rec = Record(
        title=title,
        abstract=abstract,
        authors=authors,
        year=year,
        journal=journal,
        doi=doi,
        pmid=pmid,
        issn=_first_text(record, "isbn"),
        volume=_first_text(record, "volume"),
        issue=_first_text(record, "number", "issue"),
        pages=pages,
        doc_type=_doc_type(record),
        language=_first_text(record, "language").lower(),
        keywords=keywords,
        url=url,
        cited_by=parse_int(_first_text(record, "times-cited")),
        source=db,
        source_id=accession or _first_text(record, "rec-number"),
        raw={"format": "endnote-xml"},
    )
    wos_match = _WOS_RE.search(accession)
    if wos_match:
        rec.raw["wos_id"] = wos_match.group(1)
    if not (rec.title or rec.doi):
        return None
    return rec


_RECORD_BLOCK_RE = re.compile(r"<record\b.*?</record>", re.S | re.I)


def _recover_records(text: str, rep: ParseReport) -> List[str]:
    """Salvage complete ``<record>`` elements from malformed XML.

    An interrupted download leaves the final ``<record>`` and the closing
    ``</records></xml>`` missing, and :func:`xml.etree.ElementTree.fromstring`
    then rejects the *whole* document -- so a 2 000-record EndNote export
    truncated in its last record used to yield **zero** records with no error.
    Every complete ``<record>...</record>`` block before the truncation point
    is well-formed on its own, so they are re-parsed individually and the
    incomplete tail is reported as ``truncated``.
    """
    blocks = _RECORD_BLOCK_RE.findall(text)
    tail = text[text.rfind("</record>") + len("</record>"):] if blocks else text
    if "<record" in tail.lower():
        rep.saw()
        rep.reject(len(blocks), "truncated",
                   "document ends inside a <record> element")
    return blocks


def parse_endnote_xml(text: str, source_name: str = "",
                      report: Optional[ParseReport] = None) -> List[Record]:
    """Parse an EndNote XML export into records.

    Returns an empty list for empty input rather than raising, mirroring the
    other export parsers: an import step that dies on one bad file cannot
    report how many records it lost.  Malformed XML is not given up on -- the
    complete ``<record>`` elements are recovered individually (see
    :func:`_recover_records`), because a truncated download must not cost the
    thousands of records that arrived intact before the connection dropped.
    """
    rep = _ensure(report, "endnote-xml")
    if not text or not text.strip():
        return []
    body = text.lstrip("\ufeff \t\r\n")
    nodes: List = []
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        rep.warn("XML is malformed ({}); recovering complete <record> "
                 "elements individually".format(exc))
        for block in _recover_records(body, rep):
            rep.saw()
            try:
                node = ET.fromstring(block)
            except ET.ParseError as inner:
                rep.reject(len(nodes), "malformed",
                           "unrecoverable <record>: {}".format(inner))
                continue
            _strip_ns(node)
            nodes.append(node)
    else:
        _strip_ns(root)
        nodes = root.findall(".//record")
        if not nodes and root.tag == "record":
            nodes = [root]
        rep.saw(len(nodes))
    out: List[Record] = []
    for index, node in enumerate(nodes):
        try:
            rec = _build(node)
        except Exception as exc:   # pragma: no cover - defensive
            rep.reject(index, "malformed",
                       "{}: {}".format(type(exc).__name__, exc))
            continue
        if rec is None:
            rep.reject(index, "no_content",
                       "<record> has no title and no DOI")
            continue
        if source_name:
            rec.source = source_name
        elif not rec.source:
            rec.source = "EndNote XML"
        out.append(rec)
    rep.accept(len(out))
    return out


def parse_endnote_xml_file(path: str, source_name: str = "",
                           encoding: str = "auto",
                           report: Optional[ParseReport] = None
                           ) -> List[Record]:
    """Read *path* and parse it with :func:`parse_endnote_xml`.

    ``encoding="auto"`` sniffs the byte-order mark: EndNote itself writes
    UTF-8 with a BOM, while Web of Science's "EndNote desktop" export is
    UTF-16 on Windows.
    """
    rep = _ensure(report, "endnote-xml")
    text = read_export_text(path, encoding=encoding, report=rep)
    if not text:
        return []
    return parse_endnote_xml(text, source_name=source_name, report=rep)
