"""Universal RIS parser with vendor-dialect handling.

RIS is a de-facto standard, but every vendor speaks its own dialect: Embase
puts the journal in ``T2``, EBSCO hides provider info in ``DP``, Scopus adds
``DB  - Scopus`` and export notes in ``N1``, ProQuest duplicates titles.
The parser auto-detects the dialect (overridable) and maps tags accordingly.

Vendor specifics that the identifier cascade in :mod:`corpusslr.dedup`
depends on:

``embase``
    Elsevier writes the PubMed identifier into ``AN`` (as ``PMID:########``
    or bare digits) and, for records not indexed in MEDLINE, an Embase
    accession, recognised either as ``L`` followed by 7-10 digits or as a
    bare 9-digit number beginning with ``6``.  The article
    subtype lives in ``M3`` (``Article``, ``Review``, ``Conference
    Abstract``) rather than in ``TY``, which is almost always ``JOUR``;
    reading ``M3`` is what lets an eligibility filter exclude conference
    abstracts.  Journal priority is ``T2`` because ``JF`` carries the
    abbreviated title.

``central``
    Cochrane CENTRAL exports carry ``AN  - CN-01234567``.  That CENTRAL
    number is the only stable identifier for the trial reports that have no
    DOI, so it is preserved in ``source_id`` and mirrored into
    ``raw['central_id']``.  Trial registry numbers found in ``AN``/``C7``
    (``NCT...``, ``ISRCTN...``) are kept in ``raw['trial_ids']``.

``ebsco``
    One EBSCOhost export can mix several databases (Business Source
    Complete, PsycINFO, CINAHL, ERIC, Academic Search).  The per-record
    database name is in ``DB`` or ``DP``, so ``source`` is set per record
    rather than per file; the accession prefix (``bth-``, ``psyh-``,
    ``ccm-``, ``eric-``) is used as a fallback.  PsycINFO puts its own
    identifier in ``AN`` while the PMID, when present, is in ``C2``/``N1``.

``proquest``
    ABI/INFORM duplicates the title across ``TI`` and ``T1`` (occasionally
    with different truncation, so the longer one is kept), stores the
    ProQuest document ID in ``ID`` and repeats it in ``AN``, and puts the
    stable document URL in ``UR`` with a ``docview`` path.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from ..record import Record
from ._io import read_export_text
from ._report import ParseReport, _ensure
from ._util import collapse_ws, map_doc_type

_TAG_RE = re.compile(r"^([A-Z][A-Z0-9])  ?- ?(.*)$")

_TYPE_MAP = {"JOUR": "article", "JFULL": "article", "EJOUR": "article",
             "CONF": "conference", "CPAPER": "conference", "CHAP": "chapter",
             "BOOK": "book", "THES": "thesis", "RPRT": "report",
             "GEN": "", "ABST": "article"}

# journal-tag priority per dialect
_JOURNAL_PRIORITY = {
    "generic": ["JF", "JO", "T2", "J2", "JA"],
    "scopus": ["T2", "JF", "JO", "J2"],
    "embase": ["T2", "JF", "JO", "J2"],
    "central": ["T2", "JF", "JO", "J2"],
    "ebsco": ["JF", "T2", "JO", "J2"],
    "proquest": ["JF", "T2", "JO", "J2"],
    "wos": ["T2", "JO", "JF"],
    "zotero": ["T2", "JF", "JO"],
}

# EBSCOhost database labels -> canonical source names.  A single export can
# interleave records from several of these, so the mapping is applied per
# record (see :func:`_ebsco_database`).
_EBSCO_DATABASES = (
    ("business source", "Business Source"),
    ("bsc", "Business Source"),
    ("psycinfo", "PsycINFO"),
    ("psycharticles", "PsycARTICLES"),
    ("cinahl", "CINAHL"),
    ("eric", "ERIC"),
    ("academic search", "Academic Search"),
    ("medline", "MEDLINE"),
    ("sportdiscus", "SPORTDiscus"),
    ("econlit", "EconLit"),
    ("communication", "Communication Source"),
    ("library, information science", "LISTA"),
    ("greenfile", "GreenFILE"),
)

# Accession-number prefixes used by EBSCOhost when the DB tag is absent.
_EBSCO_PREFIXES = {
    "bth": "Business Source", "buh": "Business Source",
    "psyh": "PsycINFO", "pdh": "PsycARTICLES", "ccm": "CINAHL",
    "eric": "ERIC", "a9h": "Academic Search", "cmedm": "MEDLINE",
    "s3h": "SPORTDiscus", "ecn": "EconLit", "ufh": "Communication Source",
    "lxh": "LISTA", "8gh": "GreenFILE",
}

_CENTRAL_RE = re.compile(r"\bCN-?\s?(\d{6,10})\b", re.I)
_EMBASE_ACC_RE = re.compile(r"\b(L\d{7,10}|6\d{8})\b")
_TRIAL_RE = re.compile(
    r"\b(NCT\d{8}|ISRCTN\d{6,8}|ACTRN\d{11,14}|ChiCTR[-\w]*\d{6,}"
    r"|EUCTR\d{4}-\d{6}-\d{2}|IRCT\d{8,}\w*|DRKS\d{8})\b", re.I)
_PROQUEST_ID_RE = re.compile(r"\b(\d{6,12})\b")


def detect_dialect(text: str) -> str:
    """Identify the exporting platform from marker tags in the header.

    ``central`` is tested before ``embase``/``ebsco`` because Cochrane
    CENTRAL is delivered through the Wiley platform yet indexes Embase and
    MEDLINE records, so a CENTRAL file can contain both vendors' markers;
    the ``CN-`` accession is the discriminating one.
    """
    head = text[:6000]
    if re.search(r"^DB  ?- ?Scopus", head, re.M):
        return "scopus"
    # "CENTRAL" alone is ambiguous: ProQuest Central and Ovid deliver
    # databases with that word in the name, so only the CN- accession or an
    # explicit Cochrane mention identifies Cochrane CENTRAL.
    if re.search(r"^(?:AN|ID)  ?- ?CN-?\s?\d{6,}", head, re.M) \
            or re.search(r"^DB  ?- ?[^\n]*Cochrane", head, re.M | re.I) \
            or "Cochrane Central Register" in head:
        return "central"
    if re.search(r"^DB  ?- ?Embase", head, re.M) or "Embase" in head:
        return "embase"
    if re.search(r"^(?:DP|DB)  ?- ?[^\n]*EBSCO", head, re.M) \
            or "EBSCOhost" in head \
            or re.search(r"^DB  ?- ?[^\n]*(" + "|".join(
                re.escape(k) for k, _ in _EBSCO_DATABASES) + ")",
                head, re.M | re.I):
        return "ebsco"
    if "ProQuest" in head or "ABI/INFORM" in head:
        return "proquest"
    if re.search(r"^DB  ?- ?(WOS|Web of Science)", head, re.M) \
            or "Clarivate" in head:
        return "wos"
    if re.search(r"^M3  ?- ?", head, re.M) and re.search(r"^DA  ?- ?", head, re.M):
        return "zotero"
    return "generic"


def _ebsco_database(values: List[str]) -> str:
    """Resolve an EBSCOhost ``DB``/``DP`` value to a canonical name."""
    for val in values:
        low = collapse_ws(val).lower()
        if not low:
            continue
        for needle, canonical in _EBSCO_DATABASES:
            if needle in low:
                return canonical
    return ""


def _split_raw(text: str) -> List[List[Tuple[str, str]]]:
    """Split RIS text into per-record lists of (tag, value)."""
    text = text.replace("\ufeff", "")
    records: List[List[Tuple[str, str]]] = []
    current: List[Tuple[str, str]] = []
    for line in text.splitlines():
        m = _TAG_RE.match(line)
        if m:
            tag, val = m.group(1), m.group(2).strip()
            if tag == "TY":
                if current:
                    records.append(current)
                current = [(tag, val)]
            elif tag == "ER":
                if current:
                    records.append(current)
                    current = []
            else:
                current.append((tag, val))
        elif line.strip() and current:
            # continuation line -> append to previous value
            tag, val = current[-1]
            current[-1] = (tag, (val + " " + line.strip()).strip())
    if current:
        records.append(current)
    return records


def _year_from(val: str) -> Optional[int]:
    m = re.search(r"(19|20)\d{2}", val)
    return int(m.group(0)) if m else None


def parse_ris(text: str, dialect: str = "auto",
              source_name: str = "",
              report: Optional[ParseReport] = None) -> List[Record]:
    """Parse a RIS export, detecting the vendor dialect from content.

    RIS is a family rather than a format: Embase, EBSCOhost, ProQuest, Cochrane
    CENTRAL and Scopus each use different tags for the same field, so the
    dialect decides which tag carries the journal, the accession and the
    abstract. ``dialect="auto"`` sniffs it; pass an explicit name to override.

    Pass ``report`` to keep the import reconcilable: a stanza with neither a
    title nor an identifier is counted as a rejection with a reason rather than
    dropped, so ``report.n_input == len(records) + report.n_rejected`` holds.
    """
    rep = _ensure(report, "ris")
    if dialect == "auto":
        dialect = detect_dialect(text)
    rep.dialect = rep.dialect or dialect
    jprio = _JOURNAL_PRIORITY.get(dialect, _JOURNAL_PRIORITY["generic"])
    out: List[Record] = []
    for _index, raw in enumerate(_split_raw(text)):
        rep.saw()
        fields: Dict[str, List[str]] = {}
        for tag, val in raw:
            fields.setdefault(tag, []).append(val)

        def first(*tags: str) -> str:
            for t in tags:
                if fields.get(t):
                    return fields[t][0]
            return ""

        journal = ""
        for t in jprio:
            if fields.get(t):
                journal = fields[t][0]
                break
        pages = first("SP")
        if fields.get("EP") and pages and "-" not in pages:
            pages = f"{pages}-{fields['EP'][0]}"
        pmid = ""
        # MEDLINE-through-RIS, Embase, EBSCO and CENTRAL all route the PMID
        # through accession/note tags rather than a dedicated one.
        for cand in fields.get("AN", []) + fields.get("C2", []) + \
                fields.get("N1", []) + fields.get("U1", []) + \
                fields.get("ID", []):
            if _CENTRAL_RE.search(cand):
                continue          # CN-01234567 is not a PubMed identifier
            m = re.search(r"(?:PMID[:\s]*|MEDLINE[:\s]*)?(\b\d{7,8}\b)", cand)
            if not m:
                continue
            if ("PMID" in cand.upper() or "PUBMED" in cand.upper()
                    or dialect in ("ebsco", "embase", "central")):
                pmid = m.group(1)
                break
        ty = first("TY")
        doc_type = _TYPE_MAP.get(ty, ty.lower())

        title = first("TI", "T1")
        url = first("UR", "L2")
        source = source_name or "RIS/{}".format(dialect)
        source_id = first("AN", "ID", "U1")
        extra: Dict[str, object] = {}

        # ---------------- vendor-specific refinements ----------------
        if dialect in ("embase", "central"):
            # Embase encodes the article subtype in M3, not in TY.
            m3 = first("M3")
            if m3 and not re.match(r"^10\.\d{4,9}/", m3):
                mapped = map_doc_type(m3)
                if mapped:
                    doc_type = mapped
                extra["embase_subtype"] = collapse_ws(m3)
            for cand in fields.get("AN", []) + fields.get("ID", []):
                m = _EMBASE_ACC_RE.search(cand)
                if m:
                    extra["embase_id"] = m.group(1)
                    source_id = m.group(1)
                    break
            else:
                # AN held the PMID; keep the bare number as the record id so
                # that source_id stays comparable across vendors.
                if source_id.upper().startswith(("PMID", "MEDLINE")):
                    source_id = re.sub(r"\D", "", source_id) or source_id

        if dialect == "central":
            for cand in fields.get("AN", []) + fields.get("ID", []) + \
                    fields.get("U1", []):
                m = _CENTRAL_RE.search(cand)
                if m:
                    central_id = "CN-{}".format(m.group(1))
                    extra["central_id"] = central_id
                    source_id = central_id
                    break
            trials: List[str] = []
            for cand in (fields.get("AN", []) + fields.get("C7", [])
                         + fields.get("N1", []) + fields.get("DB", [])
                         + fields.get("U1", [])):
                for m in _TRIAL_RE.finditer(cand):
                    tid = m.group(1).upper()
                    if tid not in trials:
                        trials.append(tid)
            if trials:
                extra["trial_ids"] = trials

        if dialect == "ebsco":
            db = _ebsco_database(fields.get("DB", []) + fields.get("DP", [])
                                 + fields.get("T3", []))
            if not db and source_id:
                prefix = source_id.split("-", 1)[0].strip().lower()
                db = _EBSCO_PREFIXES.get(prefix, "")
            if db:
                extra["ebsco_database"] = db
                if not source_name:
                    source = db
            for cand in fields.get("AN", []):
                if cand and not cand.isdigit():
                    source_id = cand
                    break

        if dialect == "proquest":
            # ABI/INFORM emits TI and T1; keep whichever is not truncated.
            for cand in fields.get("TI", []) + fields.get("T1", []):
                if len(collapse_ws(cand)) > len(collapse_ws(title)):
                    title = cand
            pq = ""
            for cand in fields.get("ID", []) + fields.get("AN", []):
                m = _PROQUEST_ID_RE.search(cand)
                if m:
                    pq = m.group(1)
                    break
            if not pq and url:
                m = re.search(r"docview/(\d+)", url)
                if m:
                    pq = m.group(1)
            if pq:
                extra["proquest_id"] = pq
                source_id = source_id or pq

        raw_meta: Dict[str, object] = {"dialect": dialect,
                                       "tags": dict(fields)}
        raw_meta.update(extra)
        rec = Record(
            title=collapse_ws(title),
            abstract=first("AB", "N2"),
            authors=fields.get("AU", []) or fields.get("A1", []),
            year=_year_from(first("PY", "Y1", "DA")),
            journal=journal,
            doi=first("DO", "DI", "M3" if dialect == "scopus" else "DO"),
            pmid=pmid,
            issn=first("SN"),
            volume=first("VL"),
            issue=first("IS"),
            pages=pages,
            doc_type=doc_type,
            language=first("LA").lower(),
            keywords=fields.get("KW", []),
            url=url,
            source=source,
            source_id=source_id,
            raw=raw_meta,
        )
        if rec.title or rec.doi or rec.pmid or rec.source_id:
            out.append(rec)
        elif not fields:
            rep.reject(_index, "empty", "stanza carries no RIS tags")
        else:
            rep.reject(_index, "no_content",
                       "stanza has no title and no identifier; tags present: "
                       + ",".join(sorted(fields)[:12]))
    rep.accept(len(out))
    return out


def parse_ris_file(path: str, dialect: str = "auto",
                   source_name: str = "", encoding: str = "auto",
                   report: Optional[ParseReport] = None
                   ) -> List[Record]:
    """Read and parse an RIS file, sniffing the encoding by default.

    ``encoding="auto"`` matters here: Ovid and Web of Science deliver RIS as
    UTF-16 on Windows, and the previous fixed ``"utf-8-sig"`` decoded such a
    file into NUL-separated characters that matched no ``TY  -`` tag, so the
    export silently produced **zero** records.
    """
    rep = _ensure(report, "ris")
    text = read_export_text(path, encoding=encoding, report=rep)
    if not text:
        return []
    return parse_ris(text, dialect=dialect, source_name=source_name,
                     report=rep)
