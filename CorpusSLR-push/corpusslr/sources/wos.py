"""Web of Science Core Collection client via the Clarivate *Starter* API.

Endpoint: ``https://api.clarivate.com/apis/wos-starter/v1/documents``.

Methodological status: **principal**.  Web of Science Core Collection is one
of the 14 search systems that Gusenbauer & Haddaway (2020, *Research Synthesis
Methods* 11:181-217) accept as a basis for a systematic search, and Bramer
et al. (2017, *Systematic Reviews* 6:245) found it indispensable for adequate
recall.  Until now CorpusSLR could only ingest Web of Science through the
tagged-file export parser (:mod:`corpusslr.parsers.wos`), which requires a
manual download step and therefore breaks the "one structured query, one
reproducible pipeline" property of the package.  This client closes that gap:
the same :class:`~corpusslr.query.SearchQuery` that drives Scopus and PubMed
is compiled to native WoS advanced-search syntax by
:meth:`~corpusslr.query.SearchQuery.to_wos` and executed over HTTP.

**The Starter API does not return abstracts.**  This is a documented property
of the *Starter* plan, not a transient defect: the plan exposes short-record
metadata (identifiers, title, source, authors, keywords, times-cited) and
omits abstracts, author affiliations, funding data and cited references, all
of which are available only through the separate *Expanded* API
(``/apis/wos/v1``, licensed per full-record download quota).  Because
abstract text is what title/abstract screening operates on, every search
performed through this client attaches a note to its
:class:`~corpusslr.corpus.SearchEvent` telling the reviewer to run
:func:`corpusslr.enrich.recover_abstracts` (DOI -> OpenAlex) before
screening, so the limitation is carried into the PRISMA-S appendix instead of
silently producing a corpus of empty abstracts.  Records whose abstract is
still missing after recovery must be screened on title and keywords, which
should be reported as a limitation.

Paging and quotas: ``limit`` is capped at **50** hits per request and ``page``
is 1-indexed, so a 5 000-record result set costs 100 requests.  The Starter
plan allowances are per-second *and* per-day (the free tier is roughly
1 request/s and 50 requests/day; institutional subscriptions are higher), and
exceeding either returns HTTP 429 with ``X-RateLimit-*`` headers.  The client
therefore throttles conservatively by default, records the quota state it
observes in the search event, and reports the observed headers in the error
message when the limit is hit.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..corpus import SourceResult
from ..query import SearchQuery
from ..record import Record
from .base import BaseSource, SourceError, format_author_name

_URL = "https://api.clarivate.com/apis/wos-starter/v1/documents"

#: Hard server-side cap on ``limit`` for the Starter plan (the Expanded API
#: allows 100).  Requesting more is rejected with HTTP 400.
MAX_LIMIT = 50

#: Web of Science document type -> CorpusSLR ``doc_type`` vocabulary.
#: Matching is on the whole normalized type string, never on substrings,
#: because "Book Review" (a non-research notice) must not be mistaken for
#: "Review" (a review article) - the two play opposite roles in screening.
#: The list is ordered by specificity: a record typed
#: ``["Article", "Proceedings Paper"]`` is a conference paper, and one typed
#: ``["Article", "Review"]`` is a review.
_TYPE_PRIORITY = [
    ("review", "review"),
    ("review article", "review"),
    ("proceedings paper", "conference"),
    ("meeting abstract", "conference"),
    ("meeting", "conference"),
    ("book chapter", "chapter"),
    ("book review", "editorial"),
    ("editorial material", "editorial"),
    ("correction", "editorial"),
    ("letter", "letter"),
    ("data paper", "article"),
    ("article", "article"),
    ("book", "book"),
]

#: Fallback used only when ``types`` is absent or unrecognized: the carrier of
#: the item still constrains its document type.
_SOURCE_TYPE_FALLBACK = [
    ("conference proceeding", "conference"),
    ("conference", "conference"),
    ("book in series", "chapter"),
    ("book", "book"),
    ("journal", "article"),
]

#: Rate-limit headers published by the Clarivate gateway, lowercased.  Read
#: defensively: absent on some responses and on test doubles.
_RATE_HEADERS = ("x-ratelimit-limit-second", "x-ratelimit-remaining-second",
                 "x-ratelimit-limit-day", "x-ratelimit-remaining-day",
                 "retry-after")


def _norm_type(value: object) -> str:
    return " ".join(str(value or "").lower().replace("-", " ").split())


def wos_doc_type(types: Optional[list],
                 source_types: Optional[list] = None) -> str:
    """Map Web of Science ``types``/``sourceTypes`` onto the CorpusSLR vocabulary.

    Returns ``""`` when nothing matches, so that a caller can tell "no
    document type reported" from "reported as an article".  An unrecognized
    label is never guessed at: leaving the field empty keeps the
    :func:`corpusslr.quality.quality_report` completeness statistics honest.
    """
    lowered = {_norm_type(t) for t in (types or []) if t}
    for needle, mapped in _TYPE_PRIORITY:
        if needle in lowered:
            return mapped
    src = {_norm_type(t) for t in (source_types or []) if t}
    for needle, mapped in _SOURCE_TYPE_FALLBACK:
        if needle in src:
            return mapped
    return ""


def _clean_pmid(value: object) -> str:
    """Strip the ``MEDLINE:`` namespace prefix from a Starter API PMID.

    Web of Science reports PubMed identifiers namespaced
    (``"MEDLINE:12345678"``).  PMID is the second step of the CorpusSLR
    deduplication cascade (:func:`corpusslr.dedup.deduplicate`), so a prefixed
    value would silently disable cross-database matching against PubMed for
    every record that has no DOI - exactly the older records where PMID is the
    only usable identifier.
    """
    if not value:
        return ""
    text = str(value).strip()
    if ":" in text:
        text = text.rsplit(":", 1)[-1].strip()
    return "".join(ch for ch in text if ch.isdigit())


def _pages(source: dict) -> str:
    pages = source.get("pages")
    if isinstance(pages, dict):
        rng = pages.get("range") or ""
        if rng:
            return str(rng)
        begin, end = pages.get("begin") or "", pages.get("end") or ""
        if begin and end:
            return "{}-{}".format(begin, end)
        return str(begin or end or "")
    return str(pages or "")


def _cited_by(citations: Optional[list], db: str = "WOS") -> Optional[int]:
    """Times-cited count for database *db*, falling back to the largest count.

    ``citations`` is a list of ``{"db": ..., "count": ...}`` objects because a
    document can be indexed in several Web of Science databases at once.
    """
    best: Optional[int] = None
    for entry in citations or []:
        if not isinstance(entry, dict):
            continue
        try:
            count = int(str(entry.get("count")))
        except (TypeError, ValueError):
            continue
        if str(entry.get("db") or "").upper() == str(db).upper():
            return count
        best = count if best is None else max(best, count)
    return best


def parse_wos_hit(hit: dict, source_name: str = "Web of Science Core Collection",
                  db: str = "WOS") -> Record:
    """Map one Starter API ``hits[]`` object onto a :class:`Record`.

    Kept free of HTTP so that the field mapping - the part that silently
    corrupts a corpus when it is wrong - can be tested exhaustively offline.

    Every field of a Starter hit is optional (the plan omits abstracts
    entirely, and non-journal items carry no volume/issue/pages), so each
    access is defensive.  Two mappings matter beyond bookkeeping:

    * ``uid`` (``"WOS:000123456700001"``) becomes :attr:`Record.source_id` and
      is the accession number a reviewer needs to retrieve the record in the
      Web of Science interface, so it is preserved verbatim rather than
      stripped to digits;
    * ``identifiers.pmid`` is de-namespaced by :func:`_clean_pmid` before it
      reaches the deduplication cascade.

    Author names arrive already inverted (``"Kowalski, Jan"``), and
    :func:`~corpusslr.sources.base.format_author_name` passes such names
    through unchanged, so the call is a safety net for the ``wosStandard``
    fallback rather than a transformation.
    """
    hit = hit or {}
    source = hit.get("source") or {}
    if not isinstance(source, dict):
        source = {}
    ids = hit.get("identifiers") or {}
    if not isinstance(ids, dict):
        ids = {}
    names = hit.get("names") or {}
    if not isinstance(names, dict):
        names = {}
    authors: List[str] = []
    for a in names.get("authors") or []:
        if not isinstance(a, dict):
            continue
        nm = a.get("displayName") or a.get("wosStandard") or ""
        if nm:
            authors.append(format_author_name(str(nm)))
    year = source.get("publishYear")
    try:
        year = int(year) if year not in (None, "") else None
    except (TypeError, ValueError):
        year = None
    uid = str(hit.get("uid") or "")
    links = hit.get("links") or {}
    url = ""
    if isinstance(links, dict):
        url = str(links.get("record") or "")
    if not url and uid:
        # Deterministic deep link: the record page accepts the UID directly.
        url = "https://www.webofscience.com/wos/woscc/full-record/" + uid
    keywords: List[str] = []
    kw = hit.get("keywords") or {}
    if isinstance(kw, dict):
        keywords = [str(k) for k in (kw.get("authorKeywords") or []) if k]
    return Record(
        title=str(hit.get("title") or ""),
        # The Starter plan returns no abstract field at all; see module
        # docstring and recover_abstracts().
        abstract=str(hit.get("abstract") or ""),
        authors=authors,
        year=year,
        journal=str(source.get("sourceTitle") or ""),
        doi=str(ids.get("doi") or ids.get("xref_doi") or ""),
        pmid=_clean_pmid(ids.get("pmid")),
        issn=str(ids.get("issn") or ids.get("eissn") or ""),
        volume=str(source.get("volume") or ""),
        issue=str(source.get("issue") or ""),
        pages=_pages(source),
        doc_type=wos_doc_type(hit.get("types"), hit.get("sourceTypes")),
        keywords=keywords,
        url=url,
        cited_by=_cited_by(hit.get("citations"), db),
        source=source_name,
        source_id=uid,
        raw=hit,
    )


class WosStarterSource(BaseSource):
    """Search the Web of Science Core Collection through the Starter API.

    Authentication is a plain ``X-ApiKey`` request header carrying a key
    issued on the Clarivate developer portal; the key is bound to a plan whose
    per-second and per-day request allowances are enforced by the gateway.
    """

    name = "Web of Science Core Collection"
    platform = "Clarivate"
    #: The free Starter tier answers roughly 1 request/s; institutional plans
    #: allow ~5/s.  Defaulting to the slow side avoids burning a small daily
    #: quota on 429 retries; pass ``min_interval`` to speed it up.
    min_interval = 1.1

    #: Safety net for the paging loop: 50 hits/page x 400 pages = 20 000
    #: records, far beyond a screenable set, so hitting it means the query is
    #: too broad (or the server ignores ``page``) rather than that the cap is
    #: too low.
    MAX_PAGES = 400

    def __init__(self, api_key: str, db: str = "WOS", sort_field: str = "",
                 min_interval: Optional[float] = None, **kw):
        super().__init__(**kw)
        self.api_key = api_key or ""
        #: Web of Science product database: ``WOS`` (Core Collection),
        #: ``BIOABS``, ``BCI``, ``CCC``, ``DIIDW``, ``DRCI``, ``MEDLINE``,
        #: ``ZOOREC``, ``PPRN`` or ``WOK`` (everything the key is entitled
        #: to).  Requesting a database outside the subscription returns 403.
        self.db = db or "WOS"
        #: Optional ``sortField`` (``LD``, ``PY``, ``RS``, ``TS`` with a
        #: ``+A``/``+D`` direction, e.g. ``"PY+D"``).  Left empty the API
        #: sorts by relevance, which is not guaranteed stable between
        #: requests; the paging loop deduplicates by UID so an unstable order
        #: cannot silently duplicate records, but an explicit sort makes the
        #: retrieval order reproducible for PRISMA-S reporting.
        self.sort_field = sort_field or ""
        if min_interval is not None:
            self.min_interval = min_interval
        #: Quota state observed on the most recent response, for diagnostics.
        self.last_rate_limit: Dict[str, str] = {}

    # ------------------------------------------------------------------
    def _headers(self) -> Dict[str, str]:
        """Starter API authentication: the API key travels in ``X-ApiKey``."""
        return {"X-ApiKey": self.api_key, "Accept": "application/json"}

    # ------------------------------------------------------------------
    def _remember_quota(self, response) -> None:
        headers = getattr(response, "headers", None) or {}
        try:
            items = list(headers.items())
        except AttributeError:  # pragma: no cover - non-mapping headers
            return
        for key, value in items:
            if str(key).lower() in _RATE_HEADERS:
                self.last_rate_limit[str(key)] = str(value)

    def _quota_note(self) -> str:
        if not self.last_rate_limit:
            return "no X-RateLimit-* headers seen"
        return "; ".join("{}={}".format(k, v)
                         for k, v in sorted(self.last_rate_limit.items()))

    # ------------------------------------------------------------------
    def _explain(self, message: str) -> str:
        """Turn a gateway status code into an actionable diagnosis.

        The three failure modes of the Starter API are indistinguishable from
        their bodies alone but need completely different fixes, and a reviewer
        re-running a search months later has to be able to tell them apart.
        """
        if "HTTP 401" in message:
            return (message + " -- Web of Science Starter API rejected the "
                    "API key. Check the X-ApiKey value on the Clarivate "
                    "developer portal (https://developer.clarivate.com); the "
                    "Starter key is not the same as a Web of Science login or "
                    "an Expanded API key.")
        if "HTTP 403" in message:
            return (message + " -- 'You cannot consume this service' means the "
                    "key is not provisioned for the STARTER API at all, which "
                    "most often means it was issued for a different Clarivate "
                    "product. Verified against the live gateway: an Expanded "
                    "API key returns HTTP 401 'Not authorized for product: "
                    "WWS' on /api/wos and this HTTP 403 on the Starter "
                    "endpoint, while a syntactically invalid key returns a "
                    "bare 401 'Unauthorized' -- so a 403 here is an "
                    "entitlement or wrong-product problem, never a typo. "
                    "Check on https://developer.clarivate.com which API your "
                    "key is registered for; this client speaks Starter "
                    "(/apis/wos-starter/v1), not Expanded (/api/wos), and the "
                    "two return different response shapes. If the key is right "
                    "and the Starter subscription is in place, the remaining "
                    "cause is database entitlement for db='{}' (the Core "
                    "Collection is "
                    "'WOS'; 'WOK' additionally requires entitlement to every "
                    "product database it spans).".format(self.db))
        if "HTTP 429" in message:
            return (message + " -- Starter API rate limit exceeded ({}). The "
                    "plan caps requests per second AND per day; a paged "
                    "search costs one request per 50 records. Raise "
                    "min_interval, lower max_results, or resume after the "
                    "daily quota resets.".format(self._quota_note()))
        if "HTTP 400" in message:
            return (message + " -- the gateway rejected the request. The "
                    "usual causes are a malformed WoS advanced-search string "
                    "in 'q' (unbalanced parentheses or an unknown field tag) "
                    "or limit>{}.".format(MAX_LIMIT))
        return message

    def _fetch(self, params: dict) -> dict:
        try:
            response = self._get(_URL, params=params, headers=self._headers())
        except SourceError as exc:
            raise SourceError(self._explain(str(exc)))
        self._remember_quota(response)
        try:
            data = response.json()
        except ValueError:
            raise SourceError("{}: malformed JSON response from the Starter "
                              "API".format(self.name))
        if not isinstance(data, dict):
            raise SourceError("{}: unexpected response type {}".format(
                self.name, type(data).__name__))
        return data

    # ------------------------------------------------------------------
    def search(self, query: SearchQuery, max_results: int = 2000) -> SourceResult:
        """Execute *query* against the Starter API and page through the hits.

        The query is compiled by :meth:`corpusslr.query.SearchQuery.to_wos`,
        so the executed search string is the one reported in the PRISMA-S
        appendix - no hidden server-side reinterpretation.

        Paging is defended on four fronts, because an exhaustive search that
        loops forever or stops early is worse than one that fails loudly: the
        page counter is capped at :attr:`MAX_PAGES`, an empty page ends the
        loop, ``metadata.total`` bounds it, and a page byte-identical to its
        predecessor ends retrieval (a server that ignores ``page`` would
        otherwise return the same hits indefinitely).

        Records are deduplicated within the retrieval loop on WoS accession
        number and DOI only - never on title - because the Core Collection
        indexes same-titled corrigenda, errata and reprints as separate
        documents, and collapsing them here would understate the identified
        count that PRISMA requires. Genuine cross-record duplicates are the
        job of :func:`corpusslr.dedup.deduplicate`, which is auditable.
        """
        q = query.to_wos()
        limit = max(1, min(MAX_LIMIT, max_results))
        records: List[Record] = []
        seen = set()
        total = None
        page = 1
        pages_read = 0
        duplicate_pages = 0
        prev_signature = None
        while len(records) < max_results and pages_read < self.MAX_PAGES:
            params = {"q": q, "db": self.db, "limit": limit, "page": page}
            if self.sort_field:
                params["sortField"] = self.sort_field
            data = self._fetch(params)
            pages_read += 1
            metadata = data.get("metadata") or {}
            if isinstance(metadata, dict) and total is None:
                try:
                    total = int(str(metadata.get("total")))
                except (TypeError, ValueError):
                    total = None
            hits = data.get("hits")
            if not isinstance(hits, list) or not hits:
                break
            signature = tuple(str((h or {}).get("uid") or "")
                              for h in hits if isinstance(h, dict))
            if prev_signature is not None and signature == prev_signature:
                # The server returned the same page again: stop rather than
                # loop, and say so in the event notes.
                duplicate_pages += 1
                break
            prev_signature = signature
            for hit in hits:
                rec = parse_wos_hit(hit, source_name=self.name, db=self.db)
                key = rec.source_id or rec.doi
                if key and key in seen:
                    continue
                if key:
                    seen.add(key)
                records.append(rec)
                if len(records) >= max_results:
                    break
            if len(hits) < limit:
                break
            if total is not None and len(records) >= total:
                break
            page += 1
        notes = (
            "total={}; pages_read={}; limit={}/page (Starter API maximum {}); "
            "db={}; sortField={}; capped at max_results={}. "
            "The Starter plan returns NO abstracts (and no affiliations, "
            "funding or cited references): run "
            "corpusslr.enrich.recover_abstracts() on these records before "
            "title/abstract screening, and report any records screened "
            "without an abstract as a limitation. Full abstracts require the "
            "separate Web of Science Expanded API. Rate-limit state: {}."
            .format(total, pages_read, limit, MAX_LIMIT, self.db,
                    self.sort_field or "(API default: relevance)",
                    max_results, self._quota_note()))
        if duplicate_pages:
            notes += (" Paging stopped early: page {} repeated the previous "
                      "page's record UIDs, which means the server did not "
                      "advance - verify the retrieved count against the Web "
                      "of Science interface before reporting it."
                      .format(page))
        if total is not None and total > max_results:
            notes += (" WARNING: {} records matched but only {} were "
                      "retrieved; narrow the query or raise max_results "
                      "before reporting this as the identified count."
                      .format(total, max_results))
        ev = self._event(q, filters="db={}; limit={}".format(self.db, limit),
                         url=_URL, notes=notes)
        return SourceResult(event=ev, records=records)
