"""Unified bibliographic record schema and normalization helpers."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, asdict
from typing import List, Optional
from urllib.parse import unquote

_DOI_RE = re.compile(r"10\.\d{4,9}/\S+", re.I)
_TAG_RE = re.compile(r"<[^>]+>")

# Letters whose diacritic is a stroke, slash or ligature are NOT decomposed by
# Unicode NFKD, so a plain "strip combining marks" pass turns them into
# nothing.  Without this table Polish, Nordic, German, Turkish and Croatian
# titles normalize into gapped strings ("wp yw" for "wpływ"), which both breaks
# fuzzy matching and makes ASCII-transliterated copies of the same record look
# like different works.
_TRANSLIT = str.maketrans({
    "ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D",
    "ð": "d", "Ð": "D", "ħ": "h", "Ħ": "H", "ı": "i", "İ": "I",
    "ŀ": "l", "Ŀ": "L", "ŧ": "t", "Ŧ": "T", "ə": "e", "ŋ": "ng",
    "ß": "ss", "ẞ": "SS", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE",
    "þ": "th", "Þ": "TH", "µ": "u", "ĸ": "k",
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-",
    "\u2014": "-", "\u2015": "-", "\u2018": "'", "\u2019": "'",
    "\u201c": '"', "\u201d": '"', "\u00a0": " ",
})


#: A "title" that is only an identifier: some publishers deposit the DOI, the
#: handle URL or the ISBN into the title field. Observed live on five Crossref
#: records from one African journal issue whose title field is the literal DOI
#: (``10.4314/jsda.v17i2.23834`` and siblings).
_IDENTIFIER_ONLY_TITLE_RE = re.compile(
    r"^\s*(?:"
    r"(?:https?://)?(?:dx\.)?doi\.org/\S+"          # resolver URL
    r"|doi:\s*\S+"                                   # labelled DOI
    r"|10\.\d{4,9}/\S+"                              # bare DOI
    r"|(?:https?://)?hdl\.handle\.net/\S+"           # handle
    r"|urn:[a-z0-9-]+:\S+"                           # URN
    r"|isbn[\s:-]*[\d\-xX]{10,17}"                   # ISBN
    r"|https?://\S+"                                 # bare URL
    r")\s*$",
    re.I)


def is_identifier_only_title(title: Optional[str]) -> bool:
    """True when *title* carries an identifier and no bibliographic content.

    Such a title must not drive fuzzy matching. Two DOIs from one journal issue
    differ in their last digits and are therefore ~95% similar as strings, so a
    matcher that trusts them merges distinct articles: measured on a live
    sociology corpus, four separate papers from one issue of *Journal of Social
    Development in Africa* collapsed into one record. The identifier itself is
    still used -- it is parsed into the DOI field, where it belongs.
    """
    return bool(title and _IDENTIFIER_ONLY_TITLE_RE.match(title))


def normalize_doi(doi: Optional[str]) -> str:
    """Normalize a DOI: lowercase, percent-decode, strip resolver prefixes.

    Percent-decoding matters for real exports: a database that serialises the
    DOI out of a URL renders the parentheses of an Elsevier PII as ``%28``/
    ``%29``, so ``10.1016/s0025-7753%2817%2930624-3`` and
    ``10.1016/s0025-7753(17)30624-3`` are the same DOI stored as two different
    keys. Without decoding, the identifier cascade misses a duplicate that
    agrees on the strongest evidence there is.
    """
    if not doi:
        return ""
    doi = str(doi).strip().lower()
    for _ in range(3):                  # bounded; handles double-encoding
        if "%" not in doi:
            break
        decoded = unquote(doi)
        if decoded == doi:
            break
        doi = decoded
    doi = re.sub(r"^(https?://)?(dx\.)?doi\.org/", "", doi)
    doi = re.sub(r"^doi:\s*", "", doi)
    doi = doi.strip().rstrip(".;,")
    m = _DOI_RE.search(doi)
    # A value that does not have the registered DOI shape is not a DOI, and
    # returning it as one is not a harmless pass-through: exports write missing
    # values as literals. R writes "NA", several databases write "N/A", "NULL",
    # "none" or "-", and every record in such a file then shares one identifier.
    # The cascade treats a shared identifier as the strongest evidence there is,
    # so two unrelated studies merge silently and the review loses one of them
    # while the PRISMA count still looks right. Measured on the ASySD Diabetes
    # file, whose missing DOIs are the literal "NA": 492 distinct works
    # collapsed onto a single key.
    return m.group(0) if m else ""


def normalize_title(title: Optional[str]) -> str:
    """Aggressive title normalization for fuzzy duplicate detection."""
    if not title:
        return ""
    t = str(title).translate(_TRANSLIT)
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = _TAG_RE.sub(" ", t)
    t = t.lower()
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def surname(author: Optional[str]) -> str:
    """Best-effort surname extraction from 'Family, Given' or 'Given Family'."""
    if not author:
        return ""
    a = str(author).strip()
    if "," in a:
        s = a.split(",", 1)[0]
    else:
        parts = a.split()
        s = parts[-1] if parts else ""
    return normalize_title(s)


@dataclass
class Record:
    """A single harmonized bibliographic record."""

    title: str = ""
    abstract: str = ""
    authors: List[str] = field(default_factory=list)
    year: Optional[int] = None
    journal: str = ""
    doi: str = ""
    pmid: str = ""
    openalex_id: str = ""
    scopus_id: str = ""
    issn: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    doc_type: str = ""
    language: str = ""
    keywords: List[str] = field(default_factory=list)
    #: Author affiliations, one string per distinct address, in the order the
    #: source lists them. Carried because bibliometrix builds its institutional
    #: collaboration analysis from this field (``C1`` -> ``AU_UN``): without it
    #: the co-authorship-by-institution network is empty even though Web of
    #: Science and Scopus both return the addresses.
    affiliations: List[str] = field(default_factory=list)
    url: str = ""
    open_access: Optional[bool] = None
    cited_by: Optional[int] = None
    source: str = ""
    source_id: str = ""
    search_id: str = ""
    uid: str = ""
    provenance: List[dict] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    # ------------------------------------------------------------------
    def __post_init__(self) -> None:
        self.doi = normalize_doi(self.doi)
        if self.pmid:
            self.pmid = re.sub(r"\D", "", str(self.pmid))
        if self.openalex_id:
            self.openalex_id = str(self.openalex_id).rsplit("/", 1)[-1].upper()

    # ------------------------------------------------------------------
    @property
    def norm_title(self) -> str:
        """Normalized title, memoized against the current ``title``.

        Deduplication reads this for every candidate pair -- tens of times per
        record once blocking is in play -- and the normalization itself walks
        the string several times. Memoising it is the single largest speed-up in
        the deduplication path: measured against a recomputing property it is
        worth 7.0x-8.0x (7.02x at 3 000 records and 7.14x at 6 000 with mixed
        title vocabulary; 7.95x at 2 000 and 7.24x at 4 000 with a narrow one),
        with identical output in every case. The cached
        value is keyed on the raw title, so assigning a new ``title`` (which
        ``merge_from`` may do) recomputes it rather than serving a stale value.
        """
        cached = getattr(self, "_norm_title_cache", None)
        if cached is not None and cached[0] == self.title:
            return cached[1]
        value = normalize_title(self.title)
        object.__setattr__(self, "_norm_title_cache", (self.title, value))
        return value

    @property
    def first_author_surname(self) -> str:
        return surname(self.authors[0]) if self.authors else ""

    def id_keys(self):
        """Ordered (method, value) identifier keys for exact-match dedup."""
        return [
            ("doi", self.doi),
            ("pmid", self.pmid),
            ("openalex", self.openalex_id),
            ("scopus", self.scopus_id),
        ]

    def richness(self) -> float:
        """Heuristic completeness score used to pick the record to keep."""
        score = 0.0
        for f in (self.title, self.doi, self.journal, self.issn, self.volume,
                  self.pages, self.doc_type, self.language, self.url):
            if f:
                score += 1
        if self.year:
            score += 1
        if self.authors:
            score += 1 + min(len(self.authors), 10) / 10.0
        if self.keywords:
            score += 1
        score += min(len(self.abstract), 3000) / 1000.0
        return score

    def merge_from(self, other: "Record") -> None:
        """Fill blanks from *other*; keep the longer abstract; union ids."""
        if len(other.abstract) > len(self.abstract):
            self.abstract = other.abstract
        if not self.authors and other.authors:
            self.authors = list(other.authors)
        for name in ("title", "journal", "doi", "pmid", "openalex_id",
                     "scopus_id", "issn", "volume", "issue", "pages",
                     "doc_type", "language", "url", "source_id"):
            if not getattr(self, name) and getattr(other, name):
                setattr(self, name, getattr(other, name))
        if self.year is None:
            self.year = other.year
        if other.keywords:
            seen = {k.lower() for k in self.keywords}
            self.keywords += [k for k in other.keywords if k.lower() not in seen]
        if other.affiliations:
            seen_a = {a.lower() for a in self.affiliations}
            self.affiliations += [a for a in other.affiliations
                                  if a.lower() not in seen_a]
        if other.cited_by is not None:
            self.cited_by = max(self.cited_by or 0, other.cited_by)
        if self.open_access is None:
            self.open_access = other.open_access
        self.provenance += [p for p in other.provenance if p not in self.provenance]

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("raw", None)
        return d
