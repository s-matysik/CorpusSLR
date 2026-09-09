"""Web of Science Core Collection client via the Clarivate *Expanded* API.

Endpoint: ``https://api.clarivate.com/api/wos``.

Why this exists alongside :mod:`corpusslr.sources.wos`: the two Clarivate APIs
are different services with different response shapes, and a key issued for one
is refused by the other. The Starter plan returns short records **without
abstracts**, which makes title/abstract screening impossible on a Starter-only
corpus; Expanded returns the full record, including the abstract, the complete
author list and the addresses. Measured against the live service on
2026-09-07, a five-record sample carried 5 to 13 authors per record and an
abstract on every record that declares ``has_abstract='Y'``.

Response shape (verified against live responses, not from documentation):

    QueryResult.RecordsFound          total hits
    Data.Records.records.REC[]        the records
      UID                             "WOS:000123456700001"
      static_data.summary
        titles.title[]                type="item" is the document title,
                                      type="source" is the journal or the
                                      proceedings volume
        pub_info                      pubyear, vol, issue, page.begin/end,
                                      pubtype ("Journal" | "Book" | ...)
        names.name[]                  full_name, last_name, seq_no, role
        doctypes.doctype              str or list
      static_data.fullrecord_metadata
        abstracts.abstract[].abstract_text.p   str or list of paragraphs
        keywords.keyword[]
      dynamic_data.cluster_related.identifiers.identifier[]
                                      {type: doi|issn|eissn|pmid|isbn, value}

Every one of those nodes is *either a dict or a list of dicts* depending on
cardinality, which is the single largest source of parsing bugs against this
API: a one-author paper gives ``names.name`` as a dict, a two-author paper
gives a list. :func:`_as_list` normalizes that in one place.

Paging: ``firstRecord`` is 1-indexed and ``count`` is capped at 100. The
gateway publishes remaining quota in ``x-req-reqperday-remaining`` and
``x-rec-amtpermonth-remaining`` headers; the observed values are recorded in
the search event so the PRISMA-S appendix can report what allowance the search
consumed.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..corpus import SourceResult
from ..query import SearchQuery
from ..record import Record
from .base import BaseSource, SourceError, format_author_name
from .wos import _SOURCE_TYPE_FALLBACK, _TYPE_PRIORITY

_URL = "https://api.clarivate.com/api/wos"

#: Server-side cap on ``count`` for the Expanded API. Requesting more is
#: rejected with HTTP 400.
MAX_COUNT = 100

#: Rate-limit headers published by the Clarivate gateway for this API,
#: lowercased. Read defensively: absent on some responses and on test doubles.
_RATE_HEADERS = ("x-req-reqperday-remaining", "x-req-reqpersec-remaining",
                 "x-rec-amtpermonth-remaining")


def _as_list(node: Any) -> List[Any]:
    """Normalize a node that is a dict when singular and a list when plural.

    The Expanded API does this for names, titles, identifiers, abstracts and
    doctypes. Treating a single-author record's ``names.name`` dict as a list
    of its keys is the classic failure here, so every access goes through this.
    """
    if node is None:
        return []
    return node if isinstance(node, list) else [node]


def _title_of(summary: Dict[str, Any], kind: str) -> str:
    for t in _as_list((summary.get("titles") or {}).get("title")):
        if isinstance(t, dict) and t.get("type") == kind:
            return str(t.get("content") or "").strip()
    return ""


def _identifiers(rec: Dict[str, Any]) -> Dict[str, str]:
    ids: Dict[str, str] = {}
    node = (((rec.get("dynamic_data") or {}).get("cluster_related") or {})
            .get("identifiers") or {})
    for entry in _as_list(node.get("identifier")):
        if isinstance(entry, dict):
            t, v = str(entry.get("type") or "").lower(), str(entry.get("value") or "")
            if t and v and t not in ids:      # first occurrence wins
                ids[t] = v
    return ids


def _affiliations_of(rec: Dict[str, Any]) -> List[str]:
    """Full author addresses, one per distinct affiliation.

    bibliometrix derives its institutional collaboration network from this
    field, so dropping it silently costs the reviewer an entire analysis while
    the export still looks complete.
    """
    node = ((rec.get("static_data") or {}).get("fullrecord_metadata") or {}
            ).get("addresses") or {}
    out: List[str] = []
    for entry in _as_list(node.get("address_name")):
        if not isinstance(entry, dict):
            continue
        spec = entry.get("address_spec") or {}
        full = str(spec.get("full_address") or "").strip()
        if full and full not in out:
            out.append(full)
    return out


def _abstract_of(rec: Dict[str, Any]) -> str:
    node = ((rec.get("static_data") or {}).get("fullrecord_metadata") or {}
            ).get("abstracts") or {}
    parts: List[str] = []
    for ab in _as_list(node.get("abstract")):
        if not isinstance(ab, dict):
            continue
        p = (ab.get("abstract_text") or {}).get("p")
        parts.extend(str(x) for x in _as_list(p) if x)
    return "\n\n".join(parts).strip()


def _doc_type(summary: Dict[str, Any]) -> str:
    """Map WoS document types onto the package vocabulary.

    Reuses the Starter client's priority table so the two clients cannot drift
    apart: a record typed both "Article" and "Proceedings Paper" is a
    conference paper under either API, and deduplication relies on that.
    """
    raw = [str(x).strip().lower()
           for x in _as_list((summary.get("doctypes") or {}).get("doctype")) if x]
    for needle, mapped in _TYPE_PRIORITY:
        if needle in raw:
            return mapped
    pubtype = str((summary.get("pub_info") or {}).get("pubtype") or "").lower()
    for needle, mapped in _SOURCE_TYPE_FALLBACK:
        if needle in pubtype:
            return mapped
    return ""


def parse_wos_expanded_record(rec: Dict[str, Any]) -> Record:
    """Turn one ``REC`` node into a :class:`~corpusslr.record.Record`."""
    static = rec.get("static_data") or {}
    summary = static.get("summary") or {}
    pub = summary.get("pub_info") or {}
    ids = _identifiers(rec)

    authors = []
    for n in _as_list((summary.get("names") or {}).get("name")):
        if not isinstance(n, dict) or n.get("role") not in (None, "author"):
            continue
        raw = n.get("full_name") or n.get("display_name") or n.get("last_name")
        if raw:
            authors.append(format_author_name(str(raw)))

    page = pub.get("page") or {}
    year = pub.get("pubyear")
    try:
        year = int(year) if year not in (None, "") else None
    except (TypeError, ValueError):
        year = None

    kw = [str(k) for k in _as_list(((static.get("fullrecord_metadata") or {})
                                    .get("keywords") or {}).get("keyword")) if k]

    return Record(
        title=_title_of(summary, "item"),
        authors=authors,
        year=year,
        journal=_title_of(summary, "source"),
        abstract=_abstract_of(rec),
        doi=ids.get("doi", ""),
        pmid=ids.get("pmid", ""),
        issn=ids.get("issn") or ids.get("eissn", ""),
        volume=str(pub.get("vol") or ""),
        issue=str(pub.get("issue") or ""),
        pages=str(page.get("content") or ""),
        keywords=kw,
        affiliations=_affiliations_of(rec),
        doc_type=_doc_type(summary),
        source="Web of Science Core Collection",
        source_id=str(rec.get("UID") or ""),
        raw=rec,
    )


class WosExpandedSource(BaseSource):
    """Search the Web of Science Core Collection through the Expanded API.

    Authentication is an ``X-ApiKey`` request header. Verified against the live
    service: ``Authorization: Bearer`` and an ``?apikey=`` query parameter are
    both rejected by the gateway with "No API key found in request", so the
    header is the only supported form.
    """

    name = "Web of Science Core Collection"
    platform = "Clarivate"

    #: The gateway reported 2 requests/s remaining on a fresh institutional
    #: key, so pace below that. Raise via ``min_interval`` if your plan allows.
    min_interval = 0.6

    #: Safety net for the paging loop: 100 records/page x 200 pages = 20 000
    #: records, beyond any screenable set, so hitting it means the query is too
    #: broad rather than that the cap is too low.
    MAX_PAGES = 200

    def __init__(self, api_key: str, db: str = "WOS",
                 min_interval: Optional[float] = None, **kw):
        super().__init__(**kw)
        if not api_key:
            raise ValueError("Web of Science Expanded API requires an api_key")
        self.api_key = api_key
        self.db = db
        if min_interval is not None:
            self.min_interval = min_interval
        self.last_rate_limit: Dict[str, str] = {}

    def _headers(self) -> Dict[str, str]:
        return {"X-ApiKey": self.api_key, "Accept": "application/json"}

    def _remember_quota(self, response) -> None:
        headers = getattr(response, "headers", None) or {}
        try:
            items = headers.items()
        except AttributeError:
            return
        for k, v in items:
            if str(k).lower() in _RATE_HEADERS:
                self.last_rate_limit[str(k)] = str(v)

    def _quota_note(self) -> str:
        if not self.last_rate_limit:
            return "no quota headers seen"
        return "; ".join("{}={}".format(k, v)
                         for k, v in sorted(self.last_rate_limit.items()))

    def _explain(self, message: str) -> str:
        """Turn a gateway status into an actionable diagnosis.

        The failure modes were measured against the live service and are
        distinguishable only by their bodies, not their status codes alone.
        """
        if "HTTP 401" in message and "product" in message:
            return (message + " -- the key is recognised by the gateway but the "
                    "account is not provisioned for the Expanded API (product "
                    "'WWS'). This is an entitlement, not a bad key: an invalid "
                    "key returns a bare 401 'Unauthorized' instead. Ask "
                    "Clarivate Customer Care to enable the product.")
        if "HTTP 401" in message:
            return (message + " -- the Expanded API rejected the key itself. "
                    "Check the X-ApiKey value on https://developer.clarivate.com; "
                    "an Expanded key is not a Starter key and the two APIs do "
                    "not accept each other's credentials.")
        if "HTTP 403" in message:
            return (message + " -- 'You cannot consume this service' means the "
                    "key is not provisioned for THIS endpoint. Verify whether "
                    "your subscription covers Expanded (/api/wos) or Starter "
                    "(/apis/wos-starter/v1); use WosStarterSource for the latter.")
        if "HTTP 429" in message:
            return (message + " -- rate limit exceeded ({}). The plan caps "
                    "requests per second AND per day, and a paged search costs "
                    "one request per 100 records. Raise min_interval or lower "
                    "max_results.".format(self._quota_note()))
        if "HTTP 400" in message:
            return (message + " -- the gateway rejected the request, usually a "
                    "malformed WoS advanced-search string in 'usrQuery' "
                    "(unbalanced parentheses or an unknown field tag) or a "
                    "'count' above {}.".format(MAX_COUNT))
        return message

    def search(self, query: SearchQuery, max_results: int = 2000) -> SourceResult:
        q = query.to_wos()
        records: List[Record] = []
        first, pages, found = 1, 0, None
        notes: List[str] = []

        while len(records) < max_results and pages < self.MAX_PAGES:
            count = min(MAX_COUNT, max_results - len(records))
            params = {"databaseId": self.db, "usrQuery": q,
                      "count": count, "firstRecord": first}
            try:
                response = self._get(_URL, params=params, headers=self._headers())
            except SourceError as exc:
                raise SourceError(self._explain(str(exc))) from exc
            self._remember_quota(response)
            payload = response.json()

            result = payload.get("QueryResult") or {}
            if found is None:
                found = result.get("RecordsFound")

            batch = _as_list((((payload.get("Data") or {}).get("Records") or {})
                              .get("records") or {}).get("REC"))
            if not batch:
                break
            for rec in batch:
                if isinstance(rec, dict):
                    records.append(parse_wos_expanded_record(rec))

            pages += 1
            first += len(batch)
            if found is not None and first > int(found):
                break

        if pages >= self.MAX_PAGES:
            notes.append("stopped at the {}-page safety cap; the query returned "
                         "more than {} records and is too broad to screen"
                         .format(self.MAX_PAGES, self.MAX_PAGES * MAX_COUNT))
        if found is not None:
            notes.append("RecordsFound={}".format(found))
        notes.append("quota after search: {}".format(self._quota_note()))

        with_abstract = sum(1 for r in records if r.abstract)
        notes.append("{}/{} records carry an abstract".format(with_abstract,
                                                              len(records)))
        return SourceResult(
            records=records,
            event=self._event(q, url=_URL, notes="; ".join(notes)))
