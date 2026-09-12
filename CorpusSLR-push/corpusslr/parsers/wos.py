"""Web of Science Core Collection tagged-format parser (.txt / .ciw exports).

Handles the 'Plain Text' export: 2-letter tags, values continued on lines
indented with three spaces, records terminated with ``ER``.  Preserves the
``UT`` accession number (WOS:...) and the ``PM`` PubMed ID, which makes
WoS records first-class citizens of the identifier-cascade deduplication.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from ..record import Record
from ._io import read_export_text
from ._report import ParseReport, _ensure

_TYPE_MAP = {"article": "article", "review": "review",
             "proceedings paper": "conference", "book chapter": "chapter",
             "book": "book", "editorial material": "editorial",
             "letter": "letter"}


def _year(val: str) -> Optional[int]:
    m = re.search(r"(19|20)\d{2}", val)
    return int(m.group(0)) if m else None


def parse_wos(text: str, source_name: str = "Web of Science",
              report: Optional[ParseReport] = None) -> List[Record]:
    """Parse a Web of Science tagged export (``.txt`` / ``.ciw``).

    A stanza that yields neither a title nor an identifier is rejected rather
    than returned as an empty record.  The previous behaviour emitted it, so
    feeding the parser a file in the wrong format (an RIS export mistaken for
    "plain text" -- both use two-letter tags) produced content-free records
    that inflated the "records identified" count of the PRISMA flow diagram.
    """
    rep = _ensure(report, "wos-tagged")
    text = text.replace("\ufeff", "")
    out: List[Record] = []
    fields: Dict[str, List[str]] = {}
    tag = ""

    def flush(f: Dict[str, List[str]], index: int) -> None:
        rep.saw()
        rec = _build(f, source_name)
        if rec.title or rec.doi or rec.pmid or rec.source_id:
            out.append(rec)
        else:
            rep.reject(index, "no_content",
                       "stanza has no title and no identifier; tags present: "
                       + ",".join(sorted(f)[:12]))

    for line in text.splitlines():
        if not line.strip():
            continue
        head = line[:2]
        if head == "ER":
            if fields:
                flush(fields, rep.n_input)
            fields, tag = {}, ""
            continue
        if head in ("FN", "VR", "EF"):
            tag = ""
            continue
        if re.match(r"^[A-Z][A-Z0-9] ", line) or re.match(r"^[A-Z][A-Z0-9]$", line):
            tag = head
            val = line[3:].strip()
            fields.setdefault(tag, [])
            if val:
                fields[tag].append(val)
        elif line.startswith("   ") and tag:
            fields[tag].append(line.strip())
    if fields:
        # No trailing ER: the download was truncated mid-record. The stanza is
        # still emitted when it has content -- losing a real record because the
        # file lacks its terminator would be worse than the missing tags.
        flush(fields, rep.n_input)
        rep.warn("input ends without a final 'ER' terminator; the last "
                 "record may be truncated")
    rep.accept(len(out))
    return out


def _build(f: Dict[str, List[str]], source_name: str) -> Record:
    def joined(t: str) -> str:
        return " ".join(f.get(t, [])).strip()

    def listed(t: str) -> List[str]:
        return [x for x in f.get(t, []) if x]

    authors = listed("AF") or listed("AU")
    kws: List[str] = []
    for t in ("DE", "ID"):
        for chunk in f.get(t, []):
            kws += [k.strip() for k in chunk.split(";") if k.strip()]
    pages = joined("BP")
    if joined("EP") and pages:
        pages = f"{pages}-{joined('EP')}"
    dt = joined("DT").lower()
    cited = joined("TC")
    return Record(
        title=joined("TI"),
        abstract=joined("AB"),
        authors=authors,
        year=_year(joined("PY")),
        journal=joined("SO"),
        doi=joined("DI"),
        pmid=re.sub(r"\D", "", joined("PM")),
        issn=joined("SN") or joined("EI"),
        volume=joined("VL"),
        issue=joined("IS"),
        pages=pages or joined("AR"),
        doc_type=_TYPE_MAP.get(dt, dt),
        language=joined("LA").lower(),
        keywords=kws,
        cited_by=int(cited) if cited.isdigit() else None,
        source=source_name,
        source_id=joined("UT"),
        raw={"tags": dict(f)},
    )


def parse_wos_file(path: str, source_name: str = "Web of Science",
                   encoding: str = "auto",
                   report: Optional[ParseReport] = None) -> List[Record]:
    """Read and parse a WoS tagged export, sniffing the encoding by default.

    ``encoding="auto"`` is what makes the ``.ciw`` path work: Web of Science's
    "Save to Other File Formats -> Plain text" writes UTF-16 on Windows, and
    the previous fixed ``"utf-8-sig"`` turned such a file into NUL-separated
    characters that matched no two-letter tag, so the export silently yielded
    **zero** records.
    """
    rep = _ensure(report, "wos-tagged")
    text = read_export_text(path, encoding=encoding, report=rep)
    if not text:
        return []
    return parse_wos(text, source_name=source_name, report=rep)
