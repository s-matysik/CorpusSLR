"""Crossref REST API client (https://api.crossref.org/works).

Crossref lacks reproducible boolean search, so CorpusSLR flags it as a
*supplementary* source per Gusenbauer & Haddaway (2020); use it mainly for
DOI-based metadata enrichment and coverage checks.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, cast

from ..corpus import SourceResult
from ..query import SearchQuery
from ..record import Record
from .base import BaseSource

_URL = "https://api.crossref.org/works"
_JATS = re.compile(r"<[^>]+>")


def _parse_item(it: dict) -> Record:
    issued = (it.get("issued") or {}).get("date-parts") or [[None]]
    year = issued[0][0] if issued and issued[0] else None
    authors = []
    for a in it.get("author", []) or []:
        fam, giv = a.get("family", ""), a.get("given", "")
        if fam:
            authors.append(f"{fam}, {giv}" if giv else fam)
    abstract = _JATS.sub(" ", it.get("abstract", "") or "")
    abstract = re.sub(r"\s+", " ", abstract).strip()
    return Record(
        title=(it.get("title") or [""])[0],
        abstract=abstract,
        authors=authors,
        year=int(year) if year else None,
        journal=(it.get("container-title") or [""])[0],
        doi=it.get("DOI", ""),
        issn=(it.get("ISSN") or [""])[0],
        volume=it.get("volume", "") or "",
        issue=it.get("issue", "") or "",
        pages=it.get("page", "") or "",
        doc_type=it.get("type", "") or "",
        language=it.get("language", "") or "",
        url=it.get("URL", "") or "",
        cited_by=it.get("is-referenced-by-count"),
        source="Crossref",
        source_id=it.get("DOI", ""),
        raw=it,
    )


class CrossrefSource(BaseSource):
    name = "Crossref"
    platform = "Crossref REST"
    min_interval = 0.5

    def search(self, query: SearchQuery, max_results: int = 2000) -> SourceResult:
        # The compiled query is all strings; the paging keys added here are
        # not, so the request mapping is widened at this boundary rather than
        # loosening the return type of to_crossref_params().
        compiled = query.to_crossref_params()
        params: Dict[str, object] = dict(compiled)
        params["rows"] = min(200, max_results)
        params["cursor"] = "*"
        if self.mailto:
            params["mailto"] = self.mailto
        records: List[Record] = []
        total = None
        seen_cursors = {"*"}
        while len(records) < max_results:
            r = self._get(_URL, params=cast(Any, params))
            msg = r.json().get("message", {})
            if total is None:
                total = msg.get("total-results")
            items = msg.get("items", []) or []
            if not items:
                break
            for it in items:
                records.append(_parse_item(it))
                if len(records) >= max_results:
                    break
            nxt = msg.get("next-cursor", "") or ""
            # a non-advancing cursor would otherwise spin forever
            if not nxt or nxt in seen_cursors:
                break
            seen_cursors.add(nxt)
            params["cursor"] = nxt
        qrepr = str(params.get("query.bibliographic", "")) + (
            " | filter=" + str(params["filter"]) if "filter" in params else "")
        ev = self._event(qrepr, filters="relevance search (non-boolean)",
                         url=_URL,
                         notes=f"total-results={total}; SUPPLEMENTARY source - "
                               "not reproducible boolean search; capped at "
                               f"max_results={max_results}")
        return SourceResult(event=ev, records=records)
