"""Corpus container: records + search-event provenance (PRISMA-S audit trail)."""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .record import Record


@dataclass
class SearchEvent:
    """One executed search in one information source (PRISMA-S items 1-13)."""

    database: str
    platform: str = ""
    interface: str = "API"
    query: str = ""
    filters: str = ""
    date_run: str = ""
    records_retrieved: int = 0
    url: str = ""
    notes: str = ""
    search_id: str = ""

    def __post_init__(self) -> None:
        if not self.date_run:
            self.date_run = _dt.date.today().isoformat()


@dataclass
class SourceResult:
    """Return type of every source/parser entry point."""

    event: SearchEvent
    records: List[Record] = field(default_factory=list)


class Corpus:
    """Holds all retrieved records together with their retrieval provenance."""

    def __init__(self) -> None:
        self.records: List[Record] = []
        self.searches: List[SearchEvent] = []
        self._uid = 0

    # ------------------------------------------------------------------
    def add_search(self, result: SourceResult) -> SearchEvent:
        event = result.event
        event.search_id = f"S{len(self.searches) + 1}"
        event.records_retrieved = len(result.records)
        self.searches.append(event)
        for rec in result.records:
            self._uid += 1
            rec.uid = f"R{self._uid:06d}"
            rec.search_id = event.search_id
            if not rec.source:
                rec.source = event.database
            rec.provenance.append({
                "database": event.database,
                "search_id": event.search_id,
                "source_id": rec.source_id or rec.doi,
            })
            self.records.append(rec)
        return event

    def add_records(self, records: List[Record], database: str,
                    platform: str = "", interface: str = "file export",
                    query: str = "", filters: str = "",
                    date_run: str = "", notes: str = "") -> SearchEvent:
        """Register file-parsed records (WoS/RIS/nbib exports) as a search event."""
        event = SearchEvent(database=database, platform=platform,
                            interface=interface, query=query, filters=filters,
                            date_run=date_run, notes=notes)
        return self.add_search(SourceResult(event=event, records=records))

    # ------------------------------------------------------------------
    def identified_by_source(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for ev in self.searches:
            counts[ev.database] = counts.get(ev.database, 0) + ev.records_retrieved
        return counts

    def total_identified(self) -> int:
        return sum(self.identified_by_source().values())

    def get(self, uid: str) -> Optional[Record]:
        for r in self.records:
            if r.uid == uid:
                return r
        return None

    def __len__(self) -> int:
        return len(self.records)

    def __iter__(self):
        return iter(self.records)
