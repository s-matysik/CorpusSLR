"""Scopus Search API client (https://api.elsevier.com/content/search/scopus).

Two response views matter for systematic reviews and they differ in what a
record contains, which in turn decides how complete the exported corpus can
be:

* ``view="STANDARD"`` (default entitlement of any API key) returns a single
  author in ``dc:creator``, no author keywords and no abstract.  Records are
  therefore usable for deduplication by first-author surname but incomplete
  for screening and export; abstracts have to be recovered afterwards with
  :func:`corpusslr.enrich.recover_abstracts`.
* ``view="COMPLETE"`` (requires an institutional entitlement) returns the full
  ``author`` array, ``authkeywords`` and ``dc:description`` (the abstract), so
  abstract recovery is normally unnecessary.  Without the entitlement the API
  answers HTTP 403 ``AUTHORIZATION_ERROR``.

Page sizes and offset paging are capped by the API (``MAX_OFFSET``,
:attr:`ScopusSource.PAGE_SIZE`); both caps are reported in the resulting
:class:`~corpusslr.corpus.SearchEvent` notes so that a truncated retrieval is
visible in the PRISMA-S search report instead of silently under-counting.

Authentication uses the ``X-ELS-APIKey`` header, optionally accompanied by
``X-ELS-Insttoken``; both are passed as constructor arguments (``api_key=``,
``insttoken=``) and must never be hard-coded.  Elsevier keys are scoped to the
subscribing institution's IP range, so off-campus use requires the insttoken.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple, cast

import requests

from ..corpus import SourceResult
from ..query import SearchQuery
from ..record import Record
from .base import BaseSource, SourceError, format_author_name

_URL = "https://api.elsevier.com/content/search/scopus"

# Scopus ``subtypeDescription`` values mapped onto the CorpusSLR doc_type
# vocabulary; unmapped values are passed through lowercased so nothing is lost.
_SUBTYPE_MAP = {
    "conference paper": "conference",
    "conference review": "conference",
    "book chapter": "chapter",
    "short survey": "review",
}


def _as_list(value) -> list:
    """Return *value* as a list, tolerating Elsevier's XML->JSON collapsing.

    Elsevier serializes repeated XML elements as a JSON array only when there
    is more than one of them: a record with a single author arrives as a plain
    object under ``author`` rather than a one-element list.  Iterating such a
    payload without this guard silently yields dictionary *keys* instead of
    author objects, so every single-author record would lose its authors.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


#: Matches a trailing initials token of a Scopus ``authname``/``dc:creator``
#: ("Y.", "V.R.", "S.N.F.N.B.").  The count is deliberately unbounded: an
#: earlier ``{1,4}`` limit made "Mustaffa S.N.F.N.B." (five initials, a common
#: shape for Malay and Indonesian names) fall through to the natural-order
#: helper, which inverted it to "S.N.F.N.B., Mustaffa" and put the initials in
#: the surname slot used for deduplication.  Measured on 1220 initials tokens
#: from the live sample, 3 exceeded four initials - rare, but a wrong surname
#: is not recoverable downstream.  An internal hyphen ("H.-J.", the romanised
#: Korean/Chinese given-name form) is accepted for the same reason; it was not
#: observed in the live sample (0 of 1220 tokens, Scopus appears to normalise
#: it to "H.J."), so this branch is defensive rather than measured.
_INITIALS_RE = re.compile(r"^[A-Z](?:[\.\-]*[A-Z])*\.?$")


def _split_authname(authname: str) -> str:
    """Convert a Scopus ``authname`` ("Wu Y.") into ``"Family, Given"``.

    Unlike the display names of Semantic Scholar or arXiv, Scopus writes
    ``authname`` family-first with abbreviated given names, so passing it
    through :func:`~corpusslr.sources.base.format_author_name` would invert it
    ("Y., Wu") and corrupt the surname used for deduplication.  A trailing
    initials token is therefore treated as the given part; anything else is
    handled by the generic natural-order helper.
    """
    n = " ".join(str(authname or "").split())
    if not n or "," in n:
        return n
    parts = n.split(" ")
    if len(parts) > 1 and _INITIALS_RE.match(parts[-1]):
        return "{}, {}".format(" ".join(parts[:-1]), parts[-1])
    return format_author_name(n)


def _service_error(body: object) -> Tuple[str, str]:
    """Extract ``(statusCode, statusText)`` from an Elsevier error payload.

    Elsevier reports failures in at least two envelopes
    (``service-error.status`` and ``error-response``); both carry the machine
    readable code that tells a quota exhaustion apart from a missing
    entitlement.  Returning the pair lets :class:`ScopusSource` build an error
    message a user can act on instead of an opaque HTTP status.
    """
    if not isinstance(body, dict):
        return "", ""
    status = body.get("service-error")
    if isinstance(status, dict):
        inner = status.get("status")
        if isinstance(inner, dict):
            return (str(inner.get("statusCode") or ""),
                    str(inner.get("statusText") or ""))
        return "", str(status.get("statusText") or "")
    resp = body.get("error-response")
    if isinstance(resp, dict):
        return (str(resp.get("error-code") or ""),
                str(resp.get("error-message") or ""))
    if "statusCode" in body or "statusText" in body:
        return str(body.get("statusCode") or ""), str(body.get("statusText") or "")
    return "", ""


class ScopusSource(BaseSource):
    """Scopus Search API source with view-aware paging and error diagnostics."""

    name = "Scopus"
    platform = "Elsevier"
    min_interval = 0.25

    #: ``start + count`` must not exceed this value; the API answers HTTP 400
    #: ``INVALID_INPUT`` beyond it, so start=4800&count=200 is the last legal
    #: offset request and start=4900&count=200 is rejected.  Cursor paging is
    #: not subject to this cap.
    MAX_OFFSET = 5000

    #: Maximum ``count`` per view, enforced by the API with HTTP 400: 200 for
    #: STANDARD, 25 for COMPLETE (COMPLETE records are far larger).  Using 25
    #: for STANDARD - as earlier versions did - issues eight times more
    #: requests than necessary for the same corpus.
    PAGE_SIZE = {"STANDARD": 200, "COMPLETE": 25}

    #: Conservative page size for any view name we do not know the cap for.
    DEFAULT_PAGE_SIZE = 25

    def __init__(self, api_key: str, insttoken: str = "", view: str = "auto",
                 use_cursor: bool = True, **kw):
        """Create a Scopus client.

        Args:
            api_key: Elsevier API key, sent as ``X-ELS-APIKey``.  Never embed
                it in code; read it from the environment or a config file.
            insttoken: optional institutional token sent as
                ``X-ELS-Insttoken``.  Required whenever the request originates
                outside the subscribing institution's IP range.
            view: ``"COMPLETE"``, ``"STANDARD"``, or ``"auto"`` (the default),
                which selects COMPLETE when an ``insttoken`` is supplied and
                STANDARD otherwise. The view controls both the fields returned
                and the maximum page size, and the difference is not cosmetic:
                measured against the live API on the same query, STANDARD
                returned **one author per record and no abstracts at all**,
                while COMPLETE returned up to 10 authors and an abstract for
                every record. A corpus retrieved under STANDARD cannot be
                title/abstract screened, so defaulting to it whenever the caller
                is entitled to more was a silent downgrade of the review.
            use_cursor: use cursor paging (``cursor=*``), which is not subject
                to the 5000-record offset cap.  Offset paging is kept as a
                fallback because it is the only mode that lets a caller resume
                at a known position.
        """
        super().__init__(**kw)
        self.api_key = api_key
        self.insttoken = insttoken
        requested = (view or "auto").upper()
        if requested == "AUTO":
            # An insttoken is the entitlement COMPLETE requires, so its presence
            # is the best available signal that the richer view will be granted.
            # If it is not, the API answers 401/403 and _view_error() explains
            # how to fall back, which is a better failure than silently
            # returning abstract-free records.
            self.view = "COMPLETE" if insttoken else "STANDARD"
            self.view_auto_selected = True
        else:
            self.view = requested
            self.view_auto_selected = False
        self.use_cursor = use_cursor

    # ------------------------------------------------------------------
    def _headers(self) -> Dict[str, str]:
        """Build the Elsevier authentication headers for one request."""
        h = {"X-ELS-APIKey": self.api_key, "Accept": "application/json"}
        if self.insttoken:
            h["X-ELS-Insttoken"] = self.insttoken
        return h

    def page_size(self, max_results: Optional[int] = None) -> int:
        """Return the largest page size the API accepts for the active view.

        The cap is per view (200 STANDARD / 25 COMPLETE) and exceeding it is a
        hard HTTP 400, so the value has to follow ``self.view`` rather than be
        a constant.  When fewer records than a full page are wanted, the
        request is shrunk accordingly to avoid downloading data the caller
        discards.
        """
        cap = self.PAGE_SIZE.get(self.view, self.DEFAULT_PAGE_SIZE)
        if max_results is not None:
            cap = max(1, min(cap, max_results))
        return cap

    # ------------------------------------------------------------------
    def _raise_for_scopus(self, r) -> None:
        """Translate an Elsevier error response into an actionable SourceError.

        The generic HTTP handling in :class:`~corpusslr.sources.base.BaseSource`
        cannot do this: the interpretation of 401/403/429 is Scopus-specific,
        the machine readable code lives in the response body, and the quota
        headers exist only on the response object.  Each branch names the
        remedy because these four failures account for most of the support
        questions around Scopus retrieval.
        """
        try:
            body = r.json()
        except Exception:                      # non-JSON error page
            body = {}
        code, text = _service_error(body)
        detail = "".join([
            " {}".format(code) if code else "",
            " ({})".format(text) if text else "",
        ])
        status = r.status_code
        headers = getattr(r, "headers", {}) or {}
        remaining = headers.get("X-RateLimit-Remaining")
        reset = headers.get("X-RateLimit-Reset")

        if status == 401:
            raise SourceError(
                "Scopus: HTTP 401{} - authentication failed. Elsevier returns "
                "the same message for two different causes: (a) the API key is "
                "wrong or not registered for the Scopus Search API, or (b) the "
                "key is valid but the request comes from outside the "
                "subscribing institution's IP range. Off-campus access "
                "additionally requires an institutional token, passed as "
                "insttoken= (header X-ELS-Insttoken); ask your library or "
                "Elsevier support for one.".format(detail))
        if status == 403:
            if "QUOTA" in code.upper() or "quota" in text.lower():
                raise SourceError(
                    "Scopus: HTTP 403{} - the weekly request quota for this "
                    "key is exhausted (X-RateLimit-Remaining={}, "
                    "X-RateLimit-Reset={}). Wait for the quota window to reset "
                    "or request a higher allowance from Elsevier.".format(
                        detail, remaining, reset))
            raise SourceError(
                "Scopus: HTTP 403{} - the key is authenticated but not "
                "entitled to this request. The usual cause is view='{}' "
                "without the corresponding institutional entitlement; retry "
                "with view='STANDARD' (and recover abstracts afterwards with "
                "corpusslr.enrich.recover_abstracts) or supply an "
                "insttoken=.".format(detail, self.view))
        if status == 429:
            raise SourceError(
                "Scopus: HTTP 429{} - request rate/quota limit reached "
                "(X-RateLimit-Remaining={}, X-RateLimit-Reset={}; Reset is a "
                "Unix timestamp). Retrying immediately will not help: slow the "
                "harvest down (min_interval) or resume after the reset "
                "time.".format(detail, remaining, reset))
        if status == 400:
            hint = ""
            low = text.lower()
            if "search results" in low:
                hint = (" This message is misleading: it does not mean the "
                        "result set is smaller than requested, but that "
                        "start+count exceeded the offset paging cap of {}. Use "
                        "use_cursor=True or slice the query by year.".format(
                            self.MAX_OFFSET))
            elif "maximum number" in low:
                hint = (" The page size exceeds the per-view maximum "
                        "({} for view={}).".format(
                            self.PAGE_SIZE.get(self.view,
                                               self.DEFAULT_PAGE_SIZE),
                            self.view))
            raise SourceError(
                "Scopus: HTTP 400{} - the API rejected the request.{}".format(
                    detail, hint))
        raise SourceError(
            "Scopus: HTTP {}{}: {}".format(status, detail, (r.text or "")[:300]))

    def _get_page(self, params: Dict[str, object], retries: int = 3):
        """Fetch one result page, retrying only on transient server errors.

        Server-side 5xx responses are worth retrying; the Scopus 4xx family
        (bad key, missing entitlement, exhausted quota, invalid paging) is
        deterministic, so retrying only delays a diagnosis the caller needs.
        """
        for attempt in range(retries):
            self._throttle()
            try:
                r = self.session.get(_URL,
                                     params=cast(Any, params),
                                     headers=self._headers(), timeout=60)
            except requests.RequestException as exc:
                if attempt == retries - 1:
                    raise SourceError(
                        "Scopus: network error: {}".format(exc))
                continue
            if r.status_code >= 500:
                if attempt == retries - 1:
                    self._raise_for_scopus(r)
                continue
            if r.status_code >= 400:
                self._raise_for_scopus(r)
            return r
        raise SourceError("Scopus: retries exhausted")

    # ------------------------------------------------------------------
    @staticmethod
    def _parse_authors(e: dict) -> List[str]:
        """Build the author list of one entry in ``"Family, Given"`` order.

        The COMPLETE view carries an ``author`` array whose members hold
        ``surname``/``given-name`` separately, which is what the CorpusSLR
        record schema expects; ``authname`` ("Wu Y.") is the fallback when the
        split fields are absent.  In the STANDARD view only ``dc:creator``
        exists and it holds the first author alone.
        """
        authors: List[str] = []
        for a in _as_list(e.get("author")):
            if not isinstance(a, dict):
                continue
            family = (a.get("surname") or "").strip()
            given = (a.get("given-name") or a.get("initials") or "").strip()
            if family:
                authors.append("{}, {}".format(family, given) if given
                               else family)
            elif a.get("authname"):
                authors.append(_split_authname(str(a["authname"])))
        if authors:
            return authors
        creator = e.get("dc:creator")
        # dc:creator is written in the same family-first, abbreviated-given
        # form as authname ("Abbasi E."), not in natural order.  Measured on
        # the 25 records retrieved in both views, passing it through unchanged
        # produced "Abbasi E." where the COMPLETE view gave "Abbasi, Elahe":
        # 25/25 first authors carried no comma and so violated the
        # "Family, Given" record contract, leaving surname extraction - and
        # therefore author-based deduplication across views - to operate on the
        # whole string.  Normalising it here makes the extracted surname agree
        # with the COMPLETE view in 25/25 of those records.
        return [_split_authname(str(creator))] if creator else []

    @staticmethod
    def _parse_keywords(e: dict) -> List[str]:
        """Split the COMPLETE view's ``authkeywords`` string into a list.

        Scopus returns author keywords as one string joined by ``" | "``;
        keeping them as a list makes them usable for the keyword frequency
        reports and for RIS/BibTeX export.
        """
        raw = e.get("authkeywords")
        parts: List[str] = []
        for chunk in _as_list(raw):
            if not isinstance(chunk, str):
                continue
            parts.extend(p.strip() for p in chunk.split("|"))
        return [p for p in parts if p]

    @staticmethod
    def _author_total(e: dict) -> Optional[int]:
        """Return the author count *as reported* by ``author-count``.

        Measured against the live Search API, the field is an object of the
        form ``{"@limit": "100", "$": "5"}``; ``@total`` and ``total`` were
        never observed and are accepted only defensively.  The crucial
        property is that ``$`` is **not** the true number of authors of the
        work: it is clipped at ``@limit``, so a 3000-author collaboration
        paper reports ``$`` = 100 and returns 100 author objects.  The value
        returned here therefore cannot be used on its own to detect
        truncation - see :meth:`_author_limit`.
        """
        ac = e.get("author-count")
        val = (ac.get("@total") or ac.get("$") or ac.get("total")
               if isinstance(ac, dict) else ac)
        try:
            return int(str(val))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _author_limit(e: dict) -> Optional[int]:
        """Return the ``author-count/@limit`` cap the API applied to the entry.

        Scopus caps the returned ``author`` array (observed limit: 100) and
        reports the cap in ``@limit`` while clipping the count in ``$`` to the
        same value.  Because both numbers collapse onto the cap, a record whose
        author list was truncated is recognisable *only* by ``$`` having
        reached ``@limit`` - comparing the reported count against the length of
        the parsed list can never reveal it.  Hyperauthorship records must be
        flagged in the search event, since exporting 100 of 3000 authors is a
        silent loss of data a systematic review has to declare.
        """
        ac = e.get("author-count")
        if not isinstance(ac, dict):
            return None
        try:
            return int(str(ac.get("@limit")))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_pages(e: dict) -> str:
        """Return the page range, falling back to the electronic article number.

        ``prism:pageRange`` is absent from every record published in an
        article-number-only (electronic) journal: in a 50-record COMPLETE
        sample it was present for 22% of records, while all 39 records without
        it carried ``article-number``.  Preferring the range and falling back
        to the article number raises locator coverage from 22% to 100%, which
        matters because a missing locator degrades both citation export
        (RIS ``SP``/BibTeX ``pages``) and locator-based deduplication.
        """
        rng = (e.get("prism:pageRange") or "").strip()
        if rng:
            return rng
        art = e.get("article-number")
        return str(art).strip() if art not in (None, "") else ""

    @classmethod
    def _parse_entry(cls, e: dict) -> Record:
        """Map one Scopus search entry onto a :class:`~corpusslr.record.Record`."""
        year = None
        cover = e.get("prism:coverDate") or ""
        if len(cover) >= 4 and cover[:4].isdigit():
            year = int(cover[:4])
        scopus_id = (e.get("dc:identifier") or "").replace("SCOPUS_ID:", "")
        cited = e.get("citedby-count")
        oa = e.get("openaccessFlag")
        subtype = (e.get("subtypeDescription", "") or "").lower().strip()
        return Record(
            title=e.get("dc:title", "") or "",
            abstract=e.get("dc:description", "") or "",
            authors=cls._parse_authors(e),
            year=year,
            journal=e.get("prism:publicationName", "") or "",
            doi=e.get("prism:doi", "") or "",
            scopus_id=scopus_id,
            issn=e.get("prism:issn", "") or e.get("prism:eIssn", "") or "",
            volume=e.get("prism:volume", "") or "",
            issue=e.get("prism:issueIdentifier", "") or "",
            pages=cls._parse_pages(e),
            # Scopus carries the PubMed identifier for records indexed in
            # MEDLINE (38% of a 50-record COMPLETE sample, 24% in STANDARD).
            # Dropping it discarded the strongest cross-database join key
            # available for biomedical corpora, where PMID matching resolves
            # pairs that differ in title punctuation and have no DOI.
            pmid=str(e.get("pubmed-id") or ""),
            doc_type=_SUBTYPE_MAP.get(subtype, subtype),
            keywords=cls._parse_keywords(e),
            url=e.get("prism:url", "") or "",
            open_access=bool(oa) if oa is not None else None,
            cited_by=int(cited) if cited not in (None, "") else None,
            source="Scopus",
            source_id=scopus_id or e.get("eid", ""),
            raw=e,
        )

    # ------------------------------------------------------------------
    def search(self, query: SearchQuery, max_results: int = 2000) -> SourceResult:
        """Run one Scopus search and return records plus its PRISMA-S event.

        The query string sent to the API is exactly ``query.to_scopus()`` so
        that the string recorded in the search event is the string executed
        (PRISMA-S Item 8).  Whatever limits the retrieval - the caller's
        ``max_results``, the 5000-record offset cap, a view that omits authors
        or abstracts - is written into the event notes, because a systematic
        review has to report an incomplete retrieval rather than treat the
        returned count as the true yield.
        """
        qstr = query.to_scopus()
        records: List[Record] = []
        page = self.page_size(max_results)
        total: Optional[int] = None
        start = 0
        cursor = "*" if self.use_cursor else None
        seen_cursors = {"*"}
        offset_capped = False
        empty_result_set = False
        partial_authors = False
        truncated_authors = 0

        while len(records) < max_results:
            params: Dict[str, object] = {
                "query": qstr, "count": page, "view": self.view,
                "httpAccept": "application/json"}
            if cursor is not None:
                # The cursor already carries the paging position, so start is
                # omitted. (The API tolerates both being sent -- verified
                # against the live service -- but start would then be the
                # parameter silently ignored, so sending it only invites
                # confusion about which one is in effect.)
                params["cursor"] = cursor
            else:
                if start >= self.MAX_OFFSET:
                    offset_capped = True
                    break
                # Shrink the last page so that start+count stays within the
                # documented start+count <= 5000 limit.
                params["count"] = page = min(page, self.MAX_OFFSET - start)
                params["start"] = start

            r = self._get_page(params)
            data = (r.json() or {}).get("search-results", {}) or {}
            if total is None:
                total = int(data.get("opensearch:totalResults", 0) or 0)
            entries = data.get("entry", []) or []
            if entries and isinstance(entries[0], dict) and "error" in entries[0]:
                # A 200 response whose single entry carries an "error" key is
                # how Scopus reports "no hits" - a valid, reportable outcome,
                # not a failure.
                empty_result_set = True
                break
            for e in entries:
                rec = self._parse_entry(e)
                records.append(rec)
                if "author" not in e:
                    partial_authors = True
                else:
                    n_total = self._author_total(e)
                    limit = self._author_limit(e)
                    # The API clips author-count/$ to @limit, so "reported >
                    # returned" never fires; a record is truncated exactly when
                    # the reported count reached the cap.
                    if (limit is not None and n_total is not None
                            and n_total >= limit) or n_total and n_total > len(rec.authors):
                        truncated_authors += 1
                if len(records) >= max_results:
                    break
            if not entries or len(records) >= max_results:
                break
            if total is not None and len(records) >= total:
                break
            if cursor is not None:
                nxt = ((data.get("cursor") or {}) or {}).get("@next")
                # A missing or repeated cursor means the server is not
                # advancing; without this guard the loop would never end.
                if not nxt or nxt in seen_cursors:
                    break
                seen_cursors.add(nxt)
                cursor = nxt
            else:
                start += page
                if total is not None and start >= total:
                    break
                # The offset cap is enforced once, at the top of the loop.

        notes = ["totalResults={}".format(total),
                 "retrieved={}".format(len(records))]
        if empty_result_set:
            notes.append("API reported an empty result set "
                         "(entry[0].error); zero records is the correct "
                         "outcome, the search event is still reportable")
        if offset_capped:
            notes.append(
                "retrieved {} of {}; Scopus caps offset paging at {} "
                "(start+count<={}) - narrow the query by year slices, or use "
                "use_cursor=True, to retrieve the full set".format(
                    len(records), total, self.MAX_OFFSET, self.MAX_OFFSET))
        if len(records) >= max_results and (total or 0) > len(records):
            notes.append("retrieval capped by caller at "
                         "max_results={}".format(max_results))
        if partial_authors and self.view != "COMPLETE":
            notes.append(
                "view={} returns only the first author (dc:creator) and no "
                "author keywords or abstracts: author lists in these records "
                "are incomplete, which affects export completeness and the "
                "PRISMA-S description of the retrieved data. Use "
                "view='COMPLETE' (institutional entitlement required) for the "
                "full author array".format(self.view))
        elif partial_authors:
            notes.append("some records carried no author array despite "
                         "view=COMPLETE; their author lists fall back to "
                         "dc:creator and are incomplete")
        if truncated_authors:
            notes.append(
                "author list truncated by the API in {} record(s) "
                "(author-count reached the per-record cap author-count/@limit, "
                "observed as 100); the true number of authors is not reported "
                "by the Search API and must be recovered from Abstract "
                "Retrieval if complete author lists are "
                "required".format(truncated_authors))
        ev = self._event(
            qstr,
            filters="view={}; paging={}".format(
                self.view, "cursor" if self.use_cursor else "offset"),
            url=_URL, notes="; ".join(notes))
        return SourceResult(event=ev, records=records)
