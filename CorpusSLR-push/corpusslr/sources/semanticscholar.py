"""Semantic Scholar Academic Graph (S2AG) client.

Endpoint: ``https://api.semanticscholar.org/graph/v1/paper/search`` - the
relevance-ranked search of the Allen Institute's academic graph (~200M
records, including venues poorly covered by Scopus and Web of Science).

Methodological status: **supplementary**.  The search endpoint accepts a
plain term string and applies proprietary relevance ranking; it exposes no
boolean field syntax, no exhaustive result set and no stable ranking
guarantee, which are precisely the properties Gusenbauer & Haddaway (2020,
*Research Synthesis Methods* 11:181-217) require of a *principal* search
system.  CorpusSLR therefore flattens the query (as it does for Crossref),
attaches a warning to :attr:`corpusslr.query.SearchQuery.warnings` and a note
to the :class:`~corpusslr.corpus.SearchEvent`, so the limitation is carried
into the PRISMA-S appendix instead of being hidden.

Rate limits: the unauthenticated pool is shared and throttled aggressively
(roughly 1 request/s, 429 on bursts); an API key raises the allowance.  The
client therefore uses a slower ``min_interval`` when no key is supplied.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..corpus import SourceResult
from ..query import SearchQuery
from ..record import Record
from .base import BaseSource, SourceError, format_author_name

_URL = "https://api.semanticscholar.org/graph/v1/paper/search"

#: ``publicationTypes`` values mapped onto the CorpusSLR ``doc_type``
#: vocabulary.  Order matters: a paper tagged both Review and JournalArticle
#: is a review, so the more specific label wins.
_TYPE_MAP = [
    ("review", "review"),
    ("conference", "conference"),
    ("booksection", "chapter"),
    ("book", "book"),
    ("journalarticle", "article"),
    ("editorial", "editorial"),
    ("lettersandcomments", "letter"),
    ("clinicaltrial", "article"),
    ("casereport", "article"),
    ("study", "article"),
    ("dataset", "report"),
]

FIELDS = ("paperId,externalIds,title,abstract,year,venue,authors,"
          "publicationTypes,openAccessPdf,citationCount,publicationDate,"
          "publicationVenue")


def _doc_type(pub_types: Optional[list]) -> str:
    if not pub_types:
        return ""
    lowered = {str(p).replace(" ", "").lower() for p in pub_types if p}
    for needle, mapped in _TYPE_MAP:
        if needle in lowered:
            return mapped
    return ""


def parse_s2_paper(p: dict) -> Record:
    """Map one S2AG ``paper`` object onto a :class:`Record`.

    Every field is optional in the API response (``fields`` selection, access
    restrictions and incomplete metadata all produce ``null``), so each access
    is defensive.
    """
    p = p or {}
    ext = p.get("externalIds") or {}
    authors = []
    for a in p.get("authors") or []:
        nm = (a or {}).get("name")
        if nm:
            authors.append(format_author_name(nm))
    year = p.get("year")
    if year is None:
        date = p.get("publicationDate") or ""
        if len(date) >= 4 and date[:4].isdigit():
            year = int(date[:4])
    try:
        year = int(year) if year is not None else None
    except (TypeError, ValueError):
        year = None
    venue = p.get("venue") or ""
    if not venue:
        venue = ((p.get("publicationVenue") or {}) or {}).get("name") or ""
    oa_pdf = p.get("openAccessPdf")
    paper_id = p.get("paperId") or ""
    arxiv_id = ext.get("ArXiv") or ""
    doc_type = _doc_type(p.get("publicationTypes"))
    if not doc_type and arxiv_id and not ext.get("DOI"):
        # An arXiv-only record with no publication type is a preprint.
        doc_type = "preprint"
    url = ((oa_pdf or {}) or {}).get("url") or ""
    if not url and paper_id:
        url = "https://www.semanticscholar.org/paper/" + paper_id
    return Record(
        title=p.get("title") or "",
        abstract=p.get("abstract") or "",
        authors=authors,
        year=year,
        journal=venue,
        doi=ext.get("DOI") or "",
        pmid=str(ext.get("PubMed") or ""),
        doc_type=doc_type,
        url=url,
        open_access=bool(oa_pdf) if "openAccessPdf" in p else None,
        cited_by=p.get("citationCount"),
        source="Semantic Scholar",
        source_id=paper_id,
        raw=p,
    )


class SemanticScholarSource(BaseSource):
    """Relevance search over the Semantic Scholar Academic Graph."""

    name = "Semantic Scholar"
    platform = "Allen Institute for AI"
    #: Overwritten per instance: the shared unauthenticated pool is slower.
    min_interval = 1.1

    #: Hard server-side cap on ``offset + limit`` for the search endpoint.
    MAX_OFFSET = 1000
    PAGE = 100

    def __init__(self, api_key: str = "", **kw):
        super().__init__(**kw)
        self.api_key = api_key or ""
        # With a key the documented allowance is ~10 req/s; without one the
        # shared pool answers roughly 1 req/s and 429s on bursts.
        self.min_interval = 0.11 if self.api_key else 1.1

    # ------------------------------------------------------------------
    def _headers(self) -> Dict[str, str]:
        h = {"Accept": "application/json"}
        if self.api_key:
            h["x-api-key"] = self.api_key
        return h

    # ------------------------------------------------------------------
    def search(self, query: SearchQuery, max_results: int = 1000) -> SourceResult:
        params = dict(query.to_semanticscholar())
        base_params: Dict[str, object] = dict(params)
        records: List[Record] = []
        total = None
        offset = 0
        limit = max(1, min(self.PAGE, max_results))
        while len(records) < max_results and offset < self.MAX_OFFSET:
            page_params = dict(base_params)
            page_params["offset"] = offset
            page_params["limit"] = min(limit, self.MAX_OFFSET - offset,
                                       max_results - len(records))
            page_params["fields"] = FIELDS
            r = self._get(_URL, params=page_params, headers=self._headers())
            try:
                data = r.json()
            except ValueError:
                raise SourceError("Semantic Scholar: malformed JSON response")
            if not isinstance(data, dict):
                raise SourceError(
                    "Semantic Scholar: unexpected response type "
                    "%s" % type(data).__name__)
            if total is None:
                total = data.get("total")
            page = data.get("data") or []
            if not page:
                break
            for p in page:
                records.append(parse_s2_paper(p))
                if len(records) >= max_results:
                    break
            nxt = data.get("next")
            # ``next`` is absent on the last page; a value that does not move
            # forward would otherwise spin the loop forever.
            if nxt is None:
                break
            try:
                nxt = int(nxt)
            except (TypeError, ValueError):
                break  # unparseable cursor: stop rather than guess
            # An offset that does not move forward would spin the loop
            # forever; this is the only exit besides an empty page.
            if nxt <= offset:
                break
            offset = nxt
        notes = ("total={}; SUPPLEMENTARY source - the /paper/search endpoint "
                 "offers relevance ranking without boolean syntax, so this "
                 "search is NOT reproducible in the sense of PRISMA-S Item 8; "
                 "server caps offset+limit at {}; capped at max_results={}; "
                 "authenticated={}".format(total, self.MAX_OFFSET, max_results,
                                           bool(self.api_key)))
        filters = []
        if "year" in base_params:
            filters.append("year=" + str(base_params["year"]))
        if "publicationTypes" in base_params:
            filters.append("publicationTypes=" +
                           str(base_params["publicationTypes"]))
        ev = self._event(str(base_params.get("query", "")),
                         filters="; ".join(filters) or
                                 "relevance search (non-boolean)",
                         url=_URL, notes=notes)
        return SourceResult(event=ev, records=records)
