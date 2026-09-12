"""Metadata enrichment: recover full abstracts (and IDs) via OpenAlex.

The Scopus Search API returns truncated or missing abstracts in the
STANDARD view; OpenAlex metadata is broad but heterogeneous in quality
(Alperin et al., 2024; Culbert et al., 2025).  CorpusSLR therefore treats
OpenAlex as an *enrichment layer*: records with a DOI and a missing/short
abstract are batch-resolved against OpenAlex and the abstract is rebuilt
from the inverted index, while provenance of the recovery is recorded.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Iterable, List, cast

import requests

from .record import Record, normalize_doi
from .sources.base import USER_AGENT
from .sources.openalex import reconstruct_abstract

_URL = "https://api.openalex.org/works"
_SELECT = "id,doi,ids,abstract_inverted_index"


def recover_abstracts(records: Iterable[Record], mailto: str = "",
                      min_len: int = 250, batch: int = 25,
                      session: requests.Session | None = None,
                      sleep: float = 0.15) -> Dict[str, int]:
    """Fill missing/short abstracts from OpenAlex by DOI. Returns stats."""
    recs: List[Record] = list(records)
    todo = {r.doi: r for r in recs
            if r.doi and len(r.abstract or "") < min_len}
    stats = {"candidates": len(todo), "recovered": 0, "ids_added": 0}
    if not todo:
        return stats
    sess = session or requests.Session()
    sess.headers.update({"User-Agent": USER_AGENT +
                         (f"; mailto:{mailto}" if mailto else "")})
    dois = list(todo)
    for i in range(0, len(dois), batch):
        chunk = dois[i:i + batch]
        filt = "doi:" + "|".join(chunk)
        params: Dict[str, object] = {"filter": filt,
                                     "per-page": len(chunk),
                                     "select": _SELECT}
        if mailto:
            params["mailto"] = mailto
        try:
            r = sess.get(_URL, params=cast(Any, params), timeout=60)
            r.raise_for_status()
        except requests.RequestException:
            continue
        for w in r.json().get("results", []):
            # use the package's own normalization so any resolver form matches
            # the key the request was built from
            rec = todo.get(normalize_doi(w.get("doi")))
            if not rec:
                continue
            abs_ = reconstruct_abstract(w.get("abstract_inverted_index"))
            if len(abs_) > len(rec.abstract or ""):
                rec.abstract = abs_
                rec.provenance.append({"database": "OpenAlex",
                                       "search_id": "enrichment",
                                       "source_id": "abstract_recovery"})
                stats["recovered"] += 1
            if not rec.openalex_id and w.get("id"):
                rec.openalex_id = w["id"].rsplit("/", 1)[-1]
                stats["ids_added"] += 1
            pmid = ((w.get("ids") or {}).get("pmid") or "").rsplit("/", 1)[-1]
            if pmid and not rec.pmid:
                rec.pmid = pmid
                stats["ids_added"] += 1
        time.sleep(sleep)
    return stats
