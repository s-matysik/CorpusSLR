"""Shared HTTP machinery for all API sources: politeness, retries, paging."""
from __future__ import annotations

import time
from typing import Optional

import requests

from ..corpus import SearchEvent, SourceResult
from ..query import SearchQuery

USER_AGENT = "CorpusSLR/1.0 (https://github.com/s-matysik/CorpusSLR)"


class SourceError(RuntimeError):
    pass


# Suffixes that must not be mistaken for a family name when an API returns
# author names in natural "Given Family" order (Semantic Scholar, arXiv).
_NAME_SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "phd", "md"}


def format_author_name(name: str) -> str:
    """Normalize a personal name to the package-wide ``"Family, Given"`` form.

    Several APIs (Semantic Scholar, arXiv Atom) publish display names in
    natural order, while the CorpusSLR :class:`~corpusslr.record.Record`
    schema - and therefore deduplication by first-author surname - assumes
    inverted order.  Converting at ingestion keeps the surname comparison in
    :mod:`corpusslr.dedup` meaningful across sources.  Names that already
    contain a comma are passed through unchanged; particles ("van der",
    "de la") and generational suffixes ("Jr.") are kept with the family name.
    """
    if not name:
        return ""
    n = " ".join(str(name).split())
    if "," in n:
        return n
    parts = n.split(" ")
    if len(parts) == 1:
        return parts[0]
    tail = 1
    while tail < len(parts) and parts[-tail].lower().strip(".") in _NAME_SUFFIXES:
        tail += 1
    # Lowercase particles belong to the family name ("van der Berg, Jan").
    head = len(parts) - tail
    while head > 1 and parts[head - 1].islower():
        head -= 1
    family = " ".join(parts[head:])
    given = " ".join(parts[:head])
    return "{}, {}".format(family, given) if given else family


class BaseSource:
    """Abstract API source. Subclasses implement :meth:`search`."""

    name = "base"
    platform = ""
    min_interval = 0.2  # seconds between requests

    def __init__(self, mailto: str = "", session: Optional[requests.Session] = None):
        self.mailto = mailto
        self.session = session or requests.Session()
        ua = USER_AGENT + (f"; mailto:{mailto}" if mailto else "")
        self.session.headers.update({"User-Agent": ua})
        self._last = 0.0

    # ------------------------------------------------------------------
    def _throttle(self) -> None:
        wait = self.min_interval - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()

    def _get(self, url: str, params: dict | None = None,
             headers: dict | None = None, retries: int = 3):
        for attempt in range(retries):
            self._throttle()
            try:
                r = self.session.get(url, params=params, headers=headers,
                                     timeout=60)
            except requests.RequestException as exc:
                if attempt == retries - 1:
                    raise SourceError(f"{self.name}: network error: {exc}")
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 429 or r.status_code >= 500:
                if attempt == retries - 1:
                    raise SourceError(
                        f"{self.name}: HTTP {r.status_code} after "
                        f"{retries} attempts: {r.text[:200]}")
                time.sleep(2 ** (attempt + 1))
                continue
            if r.status_code >= 400:
                raise SourceError(
                    f"{self.name}: HTTP {r.status_code}: {r.text[:300]}")
            return r
        raise SourceError(f"{self.name}: retries exhausted")

    # ------------------------------------------------------------------
    def _event(self, query_str: str, filters: str = "",
               url: str = "", notes: str = "") -> SearchEvent:
        return SearchEvent(database=self.name, platform=self.platform,
                           interface="API", query=query_str, filters=filters,
                           url=url, notes=notes)

    def search(self, query: SearchQuery, max_results: int = 2000) -> SourceResult:
        raise NotImplementedError
