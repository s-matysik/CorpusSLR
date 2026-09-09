"""Harvest the social-sciences arm from WoS Expanded, Scopus and Crossref.

Writes ``validation/domains_social_raw.jsonl.gz`` so the whole evaluation
reproduces without network access.

Crossref note (measured, not assumed)
-------------------------------------
``corpusslr.sources.CrossrefSource`` sets ``cursor="*"`` on every request.
Crossref's deep-paging cursor is documented to page the *whole* matching set
and it discards the relevance ordering: the same ``query.bibliographic`` that
returns "Influencer marketing: purchase intention and its antecedents" as hit
#2 with plain ``rows``/``offset`` returns "Experiences de consommation et
marketing experientiel" as hit #1 once a cursor is supplied.  With the cursor
the first 150 Crossref records for the marketing query shared **0** DOIs with
either WoS or Scopus; harvested by offset they share 10 and 7.  A cursor-paged
first page of a 180 000-record relevance set is effectively a random sample, so
it cannot produce cross-database duplicates.  This harvester therefore pages
Crossref by ``offset`` and parses the payload with the package's own
``_parse_item``, leaving the package code untouched.
"""
from __future__ import annotations

import gzip
import json
import os
import sys
import time
from typing import Dict, List

sys.path.insert(0, "/Users/sebastianmatysik/!!!CorpusSLR/corpusslr")

import requests

from corpusslr import SearchQuery, WosExpandedSource, ScopusSource
from corpusslr.record import Record
from corpusslr.sources.crossref import _parse_item

from social_queries import SOCIAL_QUERIES, MAX_PER_DB

REPO = "/Users/sebastianmatysik/!!!CorpusSLR/corpusslr"
OUT = os.path.join(REPO, "validation", "domains_social_raw.jsonl.gz")
CROSSREF_URL = "https://api.crossref.org/works"


def crossref_relevance(query: SearchQuery, max_results: int,
                       session: requests.Session, mailto: str = "") -> List[Record]:
    """Offset-paged Crossref harvest that preserves relevance ranking."""
    params: Dict[str, object] = dict(query.to_crossref_params())
    if mailto:
        params["mailto"] = mailto
    recs: List[Record] = []
    offset = 0
    while len(recs) < max_results and offset < 1000:
        params["rows"] = min(100, max_results - len(recs))
        params["offset"] = offset
        msg = None
        for attempt in range(4):
            try:
                r = session.get(CROSSREF_URL, params=params, timeout=90)
                if r.status_code == 200:
                    msg = r.json().get("message", {})
                    break
            except Exception:
                pass
            time.sleep(3 * (attempt + 1))
        if msg is None:
            break
        items = msg.get("items") or []
        if not items:
            break
        recs.extend(_parse_item(it) for it in items)
        offset += len(items)
        time.sleep(0.6)
    return recs


def harvest(wos_key: str, scopus_key: str, insttoken: str,
            mailto: str = "", path: str = OUT) -> int:
    session = requests.Session()
    session.headers.update({"User-Agent":
                            "CorpusSLR validation "
                            "(https://github.com/s-matysik/CorpusSLR)"})
    wos = WosExpandedSource(api_key=wos_key, mailto=mailto)
    scopus = ScopusSource(api_key=scopus_key, insttoken=insttoken, mailto=mailto)

    rows: List[dict] = []
    for spec in SOCIAL_QUERIES:
        q = SearchQuery(blocks=spec["blocks"], years=spec["years"],
                        title_only=spec["title_only"])
        per_db = {}
        for db in ("wos", "scopus", "crossref"):
            try:
                if db == "wos":
                    recs = wos.search(q, max_results=MAX_PER_DB).records
                elif db == "scopus":
                    recs = scopus.search(q, max_results=MAX_PER_DB).records
                else:
                    recs = crossref_relevance(q, MAX_PER_DB, session, mailto)
            except Exception as exc:                     # keep the harvest alive
                print("  ! {}/{}: {}".format(spec["qid"], db, exc), flush=True)
                recs = []
            per_db[db] = len(recs)
            for rec in recs:
                row = rec.to_dict()
                row.pop("raw", None)
                row["_track"] = "social"
                row["_domain"] = spec["domain"]
                row["_qid"] = spec["qid"]
                row["_label"] = spec["label"]
                row["_db"] = db
                row["_query"] = (q.to_wos() if db == "wos" else
                                 q.to_scopus() if db == "scopus" else
                                 json.dumps(q.to_crossref_params(),
                                            ensure_ascii=False))
                rows.append(row)
            time.sleep(0.5)
        print("  {} {}: {}".format(spec["qid"], spec["label"], per_db), flush=True)

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(rows)


def load_cache(path: str = OUT) -> List[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]
