"""arXiv Atom API client (``http://export.arxiv.org/api/query``).

arXiv is the largest preprint server in physics, mathematics and computer
science.  PRISMA 2020 (Page et al., 2021) explicitly asks reviewers to state
whether preprint servers were searched, because restricting evidence to
peer-reviewed journals is a documented source of time-lag and publication
bias; CorpusSLR therefore ships a first-class arXiv client and marks its
records ``doc_type="preprint"`` so they can be counted, or excluded, as
grey literature at screening.

Methodological status: **supplementary** (Gusenbauer & Haddaway, 2020) - the
Atom API does support prefixed fields and boolean operators, but it indexes a
single, discipline-restricted repository and provides no document-type or
language filtering.

Rate limit: the arXiv API terms of use ask for at least a three-second gap
between requests and a single connection at a time; ``min_interval`` is set
accordingly and must not be lowered.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import List, Optional

from ..corpus import SourceResult
from ..query import SearchQuery
from ..record import Record
from .base import BaseSource, SourceError, format_author_name

_URL = "http://export.arxiv.org/api/query"

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}

_WS = re.compile(r"\s+")


def _text(el) -> str:
    if el is None:
        return ""
    return _WS.sub(" ", "".join(el.itertext())).strip()


def _arxiv_id(entry_id: str) -> str:
    """``http://arxiv.org/abs/2401.01234v2`` -> ``2401.01234v2``."""
    if not entry_id:
        return ""
    tail = entry_id.rstrip("/").rsplit("/abs/", 1)[-1]
    return tail.rsplit("/", 1)[-1]


def parse_arxiv_atom(xml_text: str) -> List[Record]:
    """Parse an arXiv Atom feed into records (no HTTP, unit-testable).

    Namespace-aware: entry metadata lives in the Atom namespace while the DOI,
    journal reference and primary category live in arXiv's own schema.  A feed
    with no ``entry`` elements (a legitimate empty result) yields ``[]``.
    """
    if not xml_text or not xml_text.strip():
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise SourceError("arXiv: malformed Atom feed: %s" % exc)
    out: List[Record] = []
    for entry in root.findall("atom:entry", _NS):
        entry_id = _text(entry.find("atom:id", _NS))
        aid = _arxiv_id(entry_id)
        title = _text(entry.find("atom:title", _NS))
        abstract = _text(entry.find("atom:summary", _NS))
        authors = []
        for au in entry.findall("atom:author", _NS):
            nm = _text(au.find("atom:name", _NS))
            if nm:
                authors.append(format_author_name(nm))
        published = _text(entry.find("atom:published", _NS))
        year: Optional[int] = None
        if len(published) >= 4 and published[:4].isdigit():
            year = int(published[:4])
        doi = _text(entry.find("arxiv:doi", _NS))
        journal = _text(entry.find("arxiv:journal_ref", _NS))
        # Prefer the human-readable abstract page over the id URI.
        url = entry_id
        for link in entry.findall("atom:link", _NS):
            href = link.get("href")
            if link.get("rel") == "alternate" and href:
                url = href
                break
        cats: List[str] = [term for term in
                          (c.get("term")
                           for c in entry.findall("atom:category", _NS))
                          if term]
        primary = entry.find("arxiv:primary_category", _NS)
        primary_term = primary.get("term") if primary is not None else None
        if primary_term:
            cats = [primary_term] + [c for c in cats if c != primary_term]
        out.append(Record(
            title=title,
            abstract=abstract,
            authors=authors,
            year=year,
            journal=journal,
            doi=doi,
            doc_type="preprint",
            keywords=cats,
            url=url,
            open_access=True,  # every arXiv record is freely readable
            source="arXiv",
            source_id=aid,
            raw={"id": entry_id, "published": published,
                 "updated": _text(entry.find("atom:updated", _NS)),
                 "categories": cats,
                 "comment": _text(entry.find("arxiv:comment", _NS))},
        ))
    return out


def parse_arxiv_atom_file(path: str, encoding: str = "utf-8-sig") -> List[Record]:
    """Parse a saved Atom feed from disk (offline replication of a search)."""
    with open(path, "r", encoding=encoding) as fh:
        return parse_arxiv_atom(fh.read())


def _total_results(xml_text: str) -> Optional[int]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    el = root.find("opensearch:totalResults", _NS)
    txt = _text(el)
    return int(txt) if txt.isdigit() else None


class ArxivSource(BaseSource):
    """Boolean search over arXiv metadata via the Atom API."""

    name = "arXiv"
    platform = "Cornell University / arXiv"
    # The arXiv API terms of use require a minimum of one request every three
    # seconds from a single connection; do not lower this value.
    min_interval = 3.0

    PAGE = 100

    def search(self, query: SearchQuery, max_results: int = 1000) -> SourceResult:
        search_query = query.to_arxiv()
        records: List[Record] = []
        start = 0
        total = None
        while len(records) < max_results:
            page_size = min(self.PAGE, max_results - len(records))
            params = {"search_query": search_query, "start": start,
                      "max_results": page_size,
                      "sortBy": "submittedDate", "sortOrder": "descending"}
            r = self._get(_URL, params=params)
            if total is None:
                total = _total_results(r.text)
            page = parse_arxiv_atom(r.text)
            if not page:
                break
            records.extend(page)
            # arXiv returns fewer entries than requested only on the last page;
            # a short page also guards against a server that ignores `start`.
            if len(page) < page_size:
                break
            start += len(page)
        records = records[:max_results]
        filters = ""
        if query.years:
            y1, y2 = query.years
            kept = [rec for rec in records
                    if rec.year is None or y1 <= rec.year <= y2]
            filters = "publication year {}-{} applied client-side".format(y1, y2)
            dropped = len(records) - len(kept)
            records = kept
        else:
            dropped = 0
        notes = ("opensearch:totalResults={}; every record registered as "
                 "doc_type='preprint' (grey literature, PRISMA 2020 Item 6); "
                 "the API offers no document-type or language filter; "
                 "min_interval=3.0 s per arXiv API terms of use; "
                 "capped at max_results={}".format(total, max_results))
        if dropped:
            notes += ("; {} record(s) removed by the client-side year "
                      "filter".format(dropped))
        ev = self._event(search_query, filters=filters, url=_URL, notes=notes)
        return SourceResult(event=ev, records=records)
