"""PubMed .nbib (MEDLINE tagged) parser.

Format: 4-character tag padded with spaces, ``- `` separator, continuation
lines indented with six spaces; records separated by blank lines and always
starting with ``PMID``.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from ..record import Record
from ._io import read_export_text
from ._report import ParseReport, _ensure

_TAG_RE = re.compile(r"^([A-Z]{1,4})\s*- (.*)$")

# RIS declares itself: TY opens a reference, ER closes it. Neither is a MEDLINE
# tag. MEDLINE in turn has tags RIS never uses.
_RIS_MARKER_RE = re.compile(r"^(?:TY|ER)\s+- ", re.M)
_MEDLINE_MARKER_RE = re.compile(r"^(?:PMID|PT|LID|AID|FAU|MH|JT)\s*- ", re.M)


class ParseFormatMismatch(ValueError):
    """Raised when a file is asked to be parsed as a format it plainly is not.

    Silently returning identifier-less records would be worse: the import looks
    successful, the PRISMA count is right, and deduplication then fails to match
    anything because the identifiers never made it in.
    """


def _year(val: str) -> Optional[int]:
    m = re.search(r"(19|20)\d{2}", val)
    return int(m.group(0)) if m else None


def parse_nbib(text: str, source_name: str = "PubMed",
               report: Optional[ParseReport] = None,
               strict_format: bool = False) -> List[Record]:
    """Parse a PubMed ``.nbib`` (MEDLINE tagged) export.

    A block is kept when it carries a title, a PMID or a DOI -- any one of the
    three makes the record screenable and deduplicable. Blocks with none of them
    are rejected with a reason rather than dropped silently, so an import can be
    reconciled against the file it came from.

    ``strict_format`` raises :class:`ParseFormatMismatch` when the text is
    plainly a RIS export rather than a MEDLINE one. It defaults to ``False``
    because this parser's contract is that no input raises -- damaged files are
    counted as rejections, not exceptions -- but a caller who *asked* for nbib
    (``parse --format nbib``) is better served by an error than by records that
    carry a title and no identifier and therefore cannot deduplicate.
    ``parse_nbib_file`` and format auto-detection pass ``strict_format=True``.
    """
    rep = _ensure(report, "nbib", "medline")
    text = text.replace("\ufeff", "")

    # MEDLINE and RIS use nearly the same tag shape (``XX  - value``), so a RIS
    # file fed to this parser does not fail -- it yields records carrying a title
    # and nothing else, because RIS spells the identifier ``DO`` and the type
    # ``TY`` while MEDLINE uses ``LID``/``AID`` and ``PT``. Those records look
    # imported but cannot deduplicate, which is worse than an error. RIS is
    # unambiguous about itself: it opens each reference with ``TY  - `` and
    # closes with ``ER  - ``, neither of which is a MEDLINE tag.
    if (strict_format and _RIS_MARKER_RE.search(text)
            and not _MEDLINE_MARKER_RE.search(text)):
        raise ParseFormatMismatch(
            "this looks like a RIS export, not a MEDLINE/nbib one: found "
            "'TY  - ' and/or 'ER  - ' tags and no MEDLINE-only tag (PMID, PT, "
            "LID, AID, FAU). Parsing it as nbib would produce records with a "
            "title and no identifier. Use parse_ris() instead, or let the "
            "format be detected from content.")
    blocks: List[Dict[str, List[str]]] = []
    fields: Dict[str, List[str]] = {}
    tag = ""
    for line in text.splitlines():
        m = _TAG_RE.match(line)
        if m:
            tag, val = m.group(1), m.group(2).strip()
            if tag == "PMID" and fields:
                blocks.append(fields)
                fields = {}
            fields.setdefault(tag, []).append(val)
        elif line.startswith("      ") and tag and fields.get(tag):
            fields[tag][-1] = (fields[tag][-1] + " " + line.strip()).strip()
        elif not line.strip():
            continue
    if fields:
        blocks.append(fields)

    out: List[Record] = []
    for _index, f in enumerate(blocks):
        rep.saw()

        def first(t: str) -> str:
            return f.get(t, [""])[0]

        doi = ""
        for cand in f.get("LID", []) + f.get("AID", []):
            if "[doi]" in cand:
                doi = cand.replace("[doi]", "").strip()
                break
        ptypes = [p.lower() for p in f.get("PT", [])]
        doc_type = ("review" if "review" in ptypes
                    else "article" if "journal article" in ptypes
                    else (ptypes[0] if ptypes else ""))
        rec = Record(
            title=first("TI"),
            abstract=first("AB"),
            authors=f.get("FAU", []) or f.get("AU", []),
            year=_year(first("DP")),
            journal=first("JT") or first("TA"),
            doi=doi,
            pmid=re.sub(r"\D", "", first("PMID")),
            issn=first("IS").split(" ")[0] if first("IS") else "",
            volume=first("VI"),
            issue=first("IP"),
            pages=first("PG"),
            doc_type=doc_type,
            language=first("LA").lower(),
            keywords=[k.rstrip("*") for k in f.get("MH", []) + f.get("OT", [])],
            source=source_name,
            source_id=first("PMID"),
            raw={"tags": dict(f)},
        )
        if rec.title or rec.pmid or rec.doi:
            out.append(rec)
        else:
            rep.reject(_index, "no_content",
                       "block has no title, no PMID and no DOI; tags present: "
                       + ",".join(sorted(f)[:12]))
    rep.accept(len(out))
    return out


def parse_nbib_file(path: str, source_name: str = "PubMed",
                    encoding: str = "auto",
                    report: Optional[ParseReport] = None,
                    strict_format: bool = True) -> List[Record]:
    """Read and parse a ``.nbib`` file, sniffing the encoding by default.

    Naming a file as nbib is a claim about it, so a RIS export reaching here
    raises :class:`ParseFormatMismatch` rather than yielding identifier-less
    records. Pass ``strict_format=False`` to restore the tolerant behaviour.
    """
    rep = _ensure(report, "nbib", "medline")
    text = read_export_text(path, encoding=encoding, report=rep)
    if not text:
        return []
    return parse_nbib(text, source_name=source_name, report=rep,
                      strict_format=strict_format)
