"""OpenAlex API client (https://api.openalex.org/works).

Includes reconstruction of abstracts from OpenAlex's inverted index - the
mechanism CorpusSLR also uses to recover full abstracts for truncated
Scopus records (see :mod:`corpusslr.enrich`).
"""
from __future__ import annotations

from typing import List, Optional

from ..corpus import SourceResult
from ..query import SearchQuery
from ..record import Record
from .base import BaseSource

_URL = "https://api.openalex.org/works"


def reconstruct_abstract(inverted: Optional[dict]) -> str:
    """Rebuild plain text from OpenAlex ``abstract_inverted_index``."""
    if not inverted:
        return ""
    positions: dict[int, str] = {}
    for word, idxs in inverted.items():
        for i in idxs:
            positions[i] = word
    if not positions:
        return ""
    return " ".join(positions[i] for i in sorted(positions))


def _parse_work(w: dict) -> Record:
    ids = w.get("ids", {}) or {}
    pmid = (ids.get("pmid") or "").rsplit("/", 1)[-1]
    authors = []
    for a in (w.get("authorships") or []):
        name = (a.get("author") or {}).get("display_name") or a.get("raw_author_name")
        if name:
            authors.append(name)
    loc = (w.get("primary_location") or {}) or {}
    src = (loc.get("source") or {}) or {}
    oa = (w.get("open_access") or {}).get("is_oa")
    return Record(
        title=w.get("display_name") or w.get("title") or "",
        abstract=reconstruct_abstract(w.get("abstract_inverted_index")),
        authors=authors,
        year=w.get("publication_year"),
        journal=src.get("display_name") or "",
        doi=w.get("doi") or "",
        pmid=pmid,
        openalex_id=(w.get("id") or "").rsplit("/", 1)[-1],
        issn=src.get("issn_l") or "",
        volume=(w.get("biblio") or {}).get("volume") or "",
        issue=(w.get("biblio") or {}).get("issue") or "",
        pages="-".join(p for p in [(w.get("biblio") or {}).get("first_page"),
                                   (w.get("biblio") or {}).get("last_page")] if p),
        doc_type=w.get("type") or "",
        language=w.get("language") or "",
        url=loc.get("landing_page_url") or "",
        open_access=oa,
        cited_by=w.get("cited_by_count"),
        source="OpenAlex",
        source_id=(w.get("id") or "").rsplit("/", 1)[-1],
        raw=w,
    )


class OpenAlexSource(BaseSource):
    name = "OpenAlex"
    platform = "OurResearch"
    min_interval = 0.12  # polite pool: <=10 req/s

    SELECT = ("id,doi,ids,display_name,title,publication_year,language,type,"
              "primary_location,biblio,authorships,cited_by_count,open_access,"
              "abstract_inverted_index")

    def search(self, query: SearchQuery, max_results: int = 2000) -> SourceResult:
        filt = query.to_openalex()
        records: List[Record] = []
        cursor = "*"
        per_page = max(1, min(200, max_results))
        seen_cursors = {cursor}
        total = None
        while cursor and len(records) < max_results:
            params = {"filter": filt, "per-page": per_page, "cursor": cursor,
                      "select": self.SELECT}
            if self.mailto:
                params["mailto"] = self.mailto
            r = self._get(_URL, params=params)
            data = r.json()
            meta = data.get("meta") or {}
            if total is None:
                total = meta.get("count")
            page = data.get("results") or []
            for w in page:
                records.append(_parse_work(w))
                if len(records) >= max_results:
                    break
            nxt = meta.get("next_cursor")
            # An empty page or a cursor that does not advance means the server
            # is not making progress; without this guard the loop never ends.
            if not page or not nxt or nxt in seen_cursors:
                break
            seen_cursors.add(nxt)
            cursor = nxt
        ev = self._event(filt, filters="cursor paging; select=" + self.SELECT,
                         url=_URL, notes=f"meta.count={total}; capped at "
                                         f"max_results={max_results}")
        return SourceResult(event=ev, records=records)
