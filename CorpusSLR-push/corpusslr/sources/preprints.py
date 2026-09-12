"""bioRxiv and medRxiv clients (Cold Spring Harbor Laboratory content API).

Endpoint: ``https://api.biorxiv.org/details/{server}/{interval}/{cursor}``
where *server* is ``biorxiv`` or ``medrxiv`` and *interval* is either a
``YYYY-MM-DD/YYYY-MM-DD`` posting-date range or a single DOI.

**Documented limitation - read before citing these sources in a review.**
The Cold Spring Harbor API is a *content-listing* interface, not a search
interface: it enumerates every preprint posted in a date window and offers no
full-text, field or boolean query at all.  CorpusSLR therefore downloads the
window and applies the :class:`~corpusslr.query.SearchQuery` terms *locally*
to title, abstract and category.  The consequences are stated plainly in the
:class:`~corpusslr.corpus.SearchEvent` notes, and hence in the PRISMA-S
appendix, because they change how the search must be reported:

* matching is literal substring matching on normalized text - there is no
  stemming, no lemmatization, no proximity operator and no controlled
  vocabulary, so recall is lower than a database search with the same terms;
* the date window drives retrieval, so a wide window is a large download
  (use ``max_results`` and a realistic interval);
* the filter is applied to the metadata the API returns, i.e. title,
  abstract and subject category only, never full text.

Reporting these two servers as if a boolean search had been executed against
them would misdescribe the method; report them as supplementary sources
screened by local filtering, and record the date window as the search limit.

Methodological status: **supplementary** (Gusenbauer & Haddaway, 2020).
Both servers are preprint repositories: records are registered with
``doc_type="preprint"`` (grey literature under PRISMA 2020 Item 6).
"""
from __future__ import annotations

import datetime as _dt
from typing import List, Optional, Tuple

from ..corpus import SourceResult
from ..query import SearchQuery
from ..record import Record, normalize_title
from .base import BaseSource, SourceError

_BASE = "https://api.biorxiv.org/details/{server}/{interval}/{cursor}"

#: Fallback window start when a query carries no year range: the API rejects
#: an open-ended interval, and bioRxiv's first preprint is from 2013.
_EPOCH = "2013-01-01"


def _split_authors(raw: str) -> List[str]:
    """Split the API's ``"Family, G.; Family, H."`` author string.

    The server already uses inverted order, so entries are kept verbatim
    apart from whitespace cleanup.
    """
    if not raw:
        return []
    return [a.strip() for a in str(raw).split(";") if a.strip()]


def parse_preprint(item: dict, server: str = "") -> Record:
    """Map one Cold Spring Harbor ``collection`` entry onto a :class:`Record`.

    ``published`` holds the DOI of the peer-reviewed version once the preprint
    is published, or the string ``"NA"``; it is preserved in ``raw`` so that a
    review can report how many preprints have since appeared in a journal.
    """
    item = item or {}
    date = str(item.get("date") or "")
    year: Optional[int] = None
    if len(date) >= 4 and date[:4].isdigit():
        year = int(date[:4])
    srv = str(item.get("server") or server or "").strip()
    label = {"biorxiv": "bioRxiv", "medrxiv": "medRxiv"}.get(srv.lower(),
                                                            srv or "bioRxiv")
    doi = str(item.get("doi") or "")
    published = str(item.get("published") or "")
    if published.upper() in ("NA", "NONE", "NULL"):
        published = ""
    category = str(item.get("category") or "").strip()
    return Record(
        title=str(item.get("title") or ""),
        abstract=str(item.get("abstract") or ""),
        authors=_split_authors(item.get("authors") or ""),
        year=year,
        journal=label,
        doi=doi,
        doc_type="preprint",
        keywords=[category] if category else [],
        url="https://doi.org/" + doi if doi else "",
        open_access=True,  # preprint servers are fully open
        source=label,
        source_id=doi,
        raw={"date": date, "version": item.get("version"),
             "category": category, "type": item.get("type"),
             "license": item.get("license"),
             "published": published, "server": srv,
             "author_corresponding": item.get("author_corresponding"),
             "author_corresponding_institution":
                 item.get("author_corresponding_institution")},
    )


def _haystack(rec: Record) -> str:
    return normalize_title(" ".join([rec.title, rec.abstract,
                                     " ".join(rec.keywords)]))


def matches_query(rec: Record, query: SearchQuery) -> bool:
    """Local approximation of the boolean query: AND of ORs, substring match.

    Terms and text are pushed through :func:`corpusslr.record.normalize_title`
    (case folding, Unicode transliteration, punctuation removal) so that
    diacritics and hyphenation do not silently drop matches.  When
    ``query.title_only`` is set, only the title is searched.
    """
    blocks = [b for b in (query.blocks or []) if b]
    if not blocks:
        return True
    text = normalize_title(rec.title) if query.title_only else _haystack(rec)
    for block in blocks:
        terms = [normalize_title(t) for t in block]
        terms = [t for t in terms if t]
        if not terms:
            continue
        if not any(t in text for t in terms):
            return False
    return True


def render_local_filter(query: SearchQuery) -> str:
    """Human-readable rendering of the locally applied filter, for the audit.

    Built here rather than through one of the ``SearchQuery.to_*`` compilers so
    that no foreign database's warnings are appended as a side effect.
    """
    blocks = [b for b in (query.blocks or []) if b]
    if not blocks:
        return ""
    field = "title" if query.title_only else "title/abstract/category"
    groups = ["(" + " OR ".join('"%s"' % t.strip() for t in b if t.strip()) + ")"
              for b in blocks if any(t.strip() for t in b)]
    return "{}: {}".format(field, " AND ".join(groups))


def _interval(query: SearchQuery) -> Tuple[str, str]:
    today = _dt.date.today().isoformat()
    if query.years:
        y1, y2 = query.years
        end = "{}-12-31".format(y2)
        return "{}-01-01".format(y1), min(end, today)
    return _EPOCH, today


class _ColdSpringHarborSource(BaseSource):
    """Shared paging/filtering logic for the two Cold Spring Harbor servers."""

    server = ""
    platform = "Cold Spring Harbor Laboratory"
    min_interval = 1.0  # undocumented limit; stay conservative

    #: Nominal page size, kept only as the cursor step for the degenerate case
    #: where a response carries no records at all.  It is deliberately **not**
    #: used as an end-of-results test.  Measured against the live API on
    #: 2024-01-01/2024-01-02 (bioRxiv), every cursor step returns
    #: ``messages.count == 30`` while ``messages.total == 220``: the page size
    #: is 30, not the 100 the endpoint's documentation implies.  Treating a
    #: short page as the last page therefore stopped retrieval after the first
    #: 30 of 220 records -- an 86 % silent loss of the date window -- so
    #: termination is driven by ``messages.total`` and by an empty page
    #: instead.
    PAGE = 30

    #: Default ceiling on how many records may be *listed* (not retained) in one
    #: search.  Because this API has no query interface, a selective query on a
    #: wide window degenerates into a full-archive crawl: measured against the
    #: live service, ``2018-01-01/2024-12-31`` on bioRxiv reports
    #: ``messages.total == 335,871`` at 30 records per request and ~1.6 s per
    #: request -- 11,196 requests, about five hours, for one ``search()`` call
    #: that looked like every other one.  A review must be able to *see* that
    #: bound rather than discover it as a hang, so retrieval stops here and the
    #: search event records how much of the window was covered.  Raise it (or
    #: pass ``max_scanned=None``) deliberately, with the runtime in mind.
    #: The default is small on purpose: at ~2 s per 30-record request it is
    #: about a minute, which is a cost a caller can absorb without noticing a
    #: hang. It is NOT enough for an exhaustive multi-year search, and
    #: :meth:`estimate_cost` exists so a caller can see that before paying.
    MAX_SCANNED = 1500

    def estimate_cost(self, query: SearchQuery) -> dict:
        """Report what an exhaustive search of this query's window would cost.

        One cheap request answers it, because the API states the window size in
        ``messages.total``. Call it before a wide search: the answer for a
        seven-year window is thousands of requests and hours of wall time, which
        is a planning decision rather than something to discover as a hang.
        """
        start, end = _interval(query)
        r = self._get(_BASE.format(server=self.server,
                                   interval="{}/{}".format(start, end),
                                   cursor=0))
        try:
            msg = (r.json().get("messages") or [{}])[0]
            total = int(str(msg.get("total")))
        except (ValueError, TypeError, AttributeError):
            total = None
        requests_needed = (-(-total // self.PAGE)) if total else None
        return {
            "server": self.server,
            "interval": "{}/{}".format(start, end),
            "records_in_window": total,
            "page_size": self.PAGE,
            "requests_for_exhaustive_search": requests_needed,
            "seconds_estimate": (round(requests_needed * max(self.min_interval, 1.6))
                                 if requests_needed else None),
            "default_scan_budget": self.MAX_SCANNED,
            "coverage_at_default": (round(100.0 * self.MAX_SCANNED / total, 2)
                                    if total else None),
        }

    def search(self, query: SearchQuery, max_results: int = 1000,
               max_scanned: Optional[int] = -1) -> SourceResult:
        """Enumerate a posting-date window and filter it locally.

        ``max_scanned`` bounds how many records are listed, which is the cost
        driver here: this API offers no search, so every record in the window is
        downloaded and matched client-side. It defaults to :attr:`MAX_SCANNED`;
        ``None`` removes the bound and may run for hours on a multi-year window.
        Whatever the setting, the resulting coverage is stated in the search
        event so the PRISMA-S appendix reports the real extent of the search.
        """
        if max_scanned == -1:
            max_scanned = self.MAX_SCANNED
        start, end = _interval(query)
        interval = "{}/{}".format(start, end)
        kept: List[Record] = []
        scanned = 0
        total = None
        cursor = 0
        exhausted = True
        stalled = False
        budget_reached = False
        # (identifier, version) of every record already scanned, so that a
        # server-side cursor that stops advancing is detected instead of
        # looping, and a record delivered twice is counted once.
        seen = set()
        while len(kept) < max_results:
            url = _BASE.format(server=self.server, interval=interval,
                               cursor=cursor)
            r = self._get(url)
            try:
                data = r.json()
            except ValueError:
                raise SourceError("%s: malformed JSON response" % self.name)
            if not isinstance(data, dict):
                raise SourceError("%s: unexpected response type %s"
                                  % (self.name, type(data).__name__))
            messages = data.get("messages") or []
            msg = messages[0] if messages else {}
            status = str(msg.get("status") or "").lower()
            if status and status not in ("ok", "no posts found"):
                raise SourceError("%s: API status '%s' for interval %s"
                                  % (self.name, msg.get("status"), interval))
            if total is None:
                try:
                    total = int(str(msg.get("total")))
                except (TypeError, ValueError):
                    total = None
            collection = data.get("collection") or []
            if not collection:
                # An empty page is the primary end-of-results signal: the page
                # size is not what the endpoint's documentation implies (see
                # PAGE), so a short page must NOT be treated as the last one.
                break
            fresh = 0
            for item in collection:
                rec = parse_preprint(item, self.server)
                key = (rec.doi or normalize_title(rec.title),
                       str((item or {}).get("version") or ""))
                if key in seen:
                    continue
                seen.add(key)
                fresh += 1
                scanned += 1
                if matches_query(rec, query):
                    kept.append(rec)
                    if len(kept) >= max_results:
                        exhausted = False
                        break
            if len(kept) >= max_results:
                break
            if not fresh:
                # The window repeated itself: the cursor is not advancing
                # server-side. Continuing would loop for ever, and the extra
                # requests would return nothing new, so stop and say so.
                stalled = True
                break
            # The cursor advances by the number of records actually returned,
            # so it is strictly increasing.
            cursor += len(collection)
            # ``messages.total`` is the number of records in the window and is
            # the authoritative stop condition when the API reports it.
            if total is not None and cursor >= total:
                break
            if max_scanned is not None and scanned >= max_scanned:
                budget_reached = True
                exhausted = False
                break
        notes = (
            "interval={}; records listed by the API and scanned locally={}; "
            "records retained after local filtering={}; messages.total={}. "
            "LIMITATION: the Cold Spring Harbor API provides date-window "
            "listing only - it has NO full-text or boolean search, so the "
            "query terms were applied client-side as case- and "
            "diacritic-insensitive substring matching over title, abstract "
            "and category (no stemming, no proximity, no controlled "
            "vocabulary); recall is therefore lower than a database search "
            "with the same terms. SUPPLEMENTARY source; all records are "
            "preprints (grey literature, PRISMA 2020)."
            .format(interval, scanned, len(kept), total))
        if not exhausted:
            notes += (" Retrieval stopped at max_results={} before the date "
                      "window was exhausted.".format(max_results))
        if stalled:
            notes += (" WARNING: retrieval stopped because the API returned a "
                      "page containing no records that had not already been "
                      "seen (the cursor stopped advancing server-side); the "
                      "date window may not have been fully enumerated.")
        if budget_reached:
            covered = ("{:.1f}%".format(100.0 * scanned / total)
                       if total else "an unknown fraction of")
            notes += (" WARNING: the scan budget of {} listed records was "
                      "reached, so only {} of the {} records in the date window "
                      "were examined. This is a COVERAGE LIMIT and must be "
                      "reported as one: the search is not exhaustive for this "
                      "window. Narrow the year range, or raise max_scanned "
                      "(None removes the bound) accepting the runtime -- this "
                      "API lists ~30 records per request, so a full multi-year "
                      "window costs thousands of requests."
                      .format(max_scanned, covered,
                              "{:,}".format(total) if total else "unknown"))
        ev = self._event(
            render_local_filter(query),
            filters="posting date {} to {}; local substring filtering".format(
                start, end),
            url=_BASE.format(server=self.server, interval=interval,
                             cursor="{cursor}"),
            notes=notes)
        return SourceResult(event=ev, records=kept)


class BiorxivSource(_ColdSpringHarborSource):
    """bioRxiv preprints (life sciences)."""

    name = "bioRxiv"
    server = "biorxiv"


class MedrxivSource(_ColdSpringHarborSource):
    """medRxiv preprints (health sciences)."""

    name = "medRxiv"
    server = "medrxiv"
