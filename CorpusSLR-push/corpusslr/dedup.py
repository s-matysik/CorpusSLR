"""Cascading, fully auditable deduplication.

Stages (each decision is logged, exportable and PRISMA-S-item-16 ready):

1. exact DOI (normalized),
2. exact PMID,
3. exact OpenAlex ID,
4. exact Scopus ID / EID,
5. fuzzy: normalized-title similarity (Ratcliff-Obershelp via ``difflib``)
   >= *fuzzy_threshold*, publication year within *year_tolerance*, and
   first-author surname agreement (missing values treated permissively).

Merging keeps the richest record (heuristic completeness score) and fills
its blanks from the removed ones, so no metadata is lost. The report exposes
per-method counts, every pairwise decision with its evidence, and a
source-overlap matrix (empirical redundancy between databases, cf. Singh
et al., 2021).
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Dict, List, Tuple

from .corpus import Corpus
from .record import is_identifier_only_title, Record, normalize_title


@dataclass
class DedupDecision:
    kept_uid: str
    removed_uid: str
    method: str
    score: float
    key: str
    kept_source: str
    removed_source: str
    kept_title: str
    removed_title: str


@dataclass
class DedupReport:
    before: int = 0
    after: int = 0
    decisions: List[DedupDecision] = field(default_factory=list)
    by_method: Dict[str, int] = field(default_factory=dict)
    overlap: Dict[Tuple[str, str], int] = field(default_factory=dict)
    id_links_rejected: int = 0
    oversized_blocks_skipped: int = 0
    records_without_candidates: int = 0
    round_candidates: int = 0
    copublication_merges: int = 0
    by_locus: Dict[str, int] = field(default_factory=dict)

    @property
    def removed(self) -> int:
        return self.before - self.after

    def warnings(self) -> List[str]:
        """Conditions that may have degraded recall, for the audit trail.

        Silent degradation is the failure mode that matters here: a corpus whose
        blocking buckets all overflowed looks identical to a corpus with no
        duplicates unless the report says otherwise.
        """
        out: List[str] = []
        if self.records_without_candidates:
            out.append(
                f"{self.records_without_candidates} record(s) received no "
                "fuzzy-match candidate (title too short or blocking buckets "
                "exhausted); duplicates among them cannot be detected. "
                "Consider raising max_block.")
        if self.oversized_blocks_skipped:
            out.append(
                f"{self.oversized_blocks_skipped} oversized blocking bucket(s) "
                "were skipped in favour of composite keys; recall may be "
                "reduced for records with a very narrow title vocabulary.")
        if self.id_links_rejected:
            out.append(
                f"{self.id_links_rejected} identifier link(s) were rejected "
                "because the titles disagreed (typically one DOI shared by a "
                "whole conference-abstract supplement).")
        return out

    def summary(self) -> str:
        lines = [(f"Deduplication: {self.before} -> {self.after} records "
                  f"({self.removed} removed)")]
        for m in ("doi", "pmid", "openalex", "scopus", "fuzzy"):
            if self.by_method.get(m):
                lines.append(f"  - {m}: {self.by_method[m]}")
        for w in self.warnings():
            lines.append(f"  ! {w}")
        return "\n".join(lines)

    def to_csv(self, path: str) -> str:
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["kept_uid", "removed_uid", "method", "score", "key",
                        "kept_source", "removed_source",
                        "kept_title", "removed_title"])
            for d in self.decisions:
                w.writerow([d.kept_uid, d.removed_uid, d.method,
                            f"{d.score:.4f}", d.key, d.kept_source,
                            d.removed_source, d.kept_title, d.removed_title])
        return path

    def overlap_markdown(self) -> str:
        sources = sorted({s for pair in self.overlap for s in pair})
        if not sources:
            return "_No cross-source duplicates detected._"
        head = "| |" + "|".join(sources) + "|"
        sep = "|---" * (len(sources) + 1) + "|"
        rows = [head, sep]
        for a in sources:
            cells = []
            for b in sources:
                lo, hi = sorted((a, b))
                cells.append(str(self.overlap.get((lo, hi), 0))
                             if a != b else "-")
            rows.append(f"|{a}|" + "|".join(cells) + "|")
        return "\n".join(rows)


@dataclass
class DedupResult:
    records: List[Record]
    report: DedupReport


# ----------------------------------------------------------------------
def _length_permits(a: Record, b: Record, threshold: float) -> bool:
    """Cheap necessary condition for the Ratcliff-Obershelp ratio to reach *threshold*.

    The ratio is ``2M/T`` where M is the number of matched characters and T the
    combined length, so M <= min(len_a, len_b) bounds it:
    ``ratio <= 2*min/(len_a+len_b)``. When that bound already falls below the
    threshold the expensive matcher cannot possibly succeed, and one integer
    comparison replaces it.

    Measured separately, this bound is worth close to nothing: 0.92x-1.05x on
    corpora with mixed and with narrow title vocabularies, i.e. within noise.
    The speed-up at scale comes from memoising :attr:`Record.norm_title`
    (7.0x-8.0x measured), not from here. The bound is kept because it is an
    exact necessary condition -- it can only reject pairs the matcher would
    have rejected anyway, which a test verifies exhaustively -- so it costs
    nothing and bounds the worst case; it is not, as an earlier version of this
    docstring claimed, what keeps the fuzzy stage off the critical path.
    """
    la, lb = len(a.norm_title), len(b.norm_title)
    if not la or not lb:
        return False
    return 2 * min(la, lb) >= threshold * (la + lb)


def _title_ratio(a: Record, b: Record) -> float:
    """Title similarity, refusing titles that carry no bibliographic content.

    Some publishers deposit the DOI, a handle or an ISBN into the title field.
    Two such "titles" from one journal issue differ only in their final digits
    and score ~0.95, so trusting them merges distinct articles. Measured live:
    four separate papers from one issue of *Journal of Social Development in
    Africa*, whose Crossref title field is the literal DOI, collapsed into a
    single record. The identifier is not lost -- it is still read into the DOI
    field, where the identifier stage can use it as evidence.
    """
    if is_identifier_only_title(a.title) or is_identifier_only_title(b.title):
        return 0.0
    return SequenceMatcher(None, a.norm_title, b.norm_title).ratio()


_FIRST_PAGE_RE = re.compile(r"([a-z]?)\s?(\d+)")

_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
     "nov", "dec"), 1)}

_MANGLED_A = re.compile(r"([a-z]{3})[a-z]*[-/ ](\d{1,4})$")   # "Nov-19"
_MANGLED_B = re.compile(r"(\d{1,4})[-/ ]([a-z]{3})[a-z]*$")   # "11-Sep"


def excel_mangled_pages(value: str) -> bool:
    """True when a page range was silently converted to a date by a spreadsheet.

    Opening a database export in Excel turns "11-9" into "11-Sep" and "11-19"
    into "Nov-19"; the two renderings of the SAME range no longer look alike.
    In the ASySD Diabetes set 38 of 1845 records carry such a value, and they
    caused false positives once the locus guard started trusting page numbers.

    Recovering the original is possible but not reliable ("Sep-11" could be
    9-11 or 11-9), so the guard treats a mangled value as *unknown* rather than
    guessing: an unreadable page never blocks a merge.
    """
    v = (value or "").strip().lower()
    if not v:
        return False
    m = _MANGLED_A.fullmatch(v)
    if m and m.group(1) in _MONTHS:
        return True
    m = _MANGLED_B.fullmatch(v)
    return bool(m and m.group(2) in _MONTHS)


def normalize_pages(value: str) -> str:
    """First page of a range, comparable across databases.

    Exports disagree on the form of a page range ("413-420", "413--420",
    "413 - 20", "pp. 413"), but agree on the first page, and supplement
    abstracts carry a section letter that is part of the identity ("S354",
    "A121"). Returning ``letter + first number`` keeps that signal while
    absorbing the formatting differences.
    """
    v = (value or "").strip().lower()
    if not v:
        return ""
    m = _FIRST_PAGE_RE.search(v)
    return (m.group(1) + m.group(2)) if m else ""


def normalize_volume(value: str) -> str:
    """Leading digits of a volume, dropping supplement decoration.

    Databases render the same volume as "38", "38 (Supplement 1)" or "3)",
    so only the numeric part is comparable.
    """
    m = re.search(r"\d+", value or "")
    return m.group(0) if m else ""


_CONFERENCE_RE = re.compile(
    r"\bconference\b|\bsuppl(ement)?\b|\babstracts?\b|\bmeeting\b|"
    r"\bproceedings\b|\bcongress\b|\bsymposium\b|\bannual (scientific )?session",
    re.I)


def is_conference_venue(record: Record) -> bool:
    """True when the source title marks the record as a conference item."""
    return bool(_CONFERENCE_RE.search(record.journal or ""))


def _conference_vs_article(a: Record, b: Record) -> bool:
    """True when one record is the conference version of the other's article.

    Cochrane and ASySD treat a conference abstract and the subsequent journal
    article as two separate reports of one study: they are cited separately,
    carry different data, and a review has to account for both. They are however
    near-indistinguishable by title and authors, so the signature used here is
    the venue plus the absence of article-level coordinates -- a conference
    record without a DOI and without page numbers, paired against a record that
    has both.
    """
    for x, y in ((a, b), (b, a)):
        if (is_conference_venue(x) and not x.doi
                and not normalize_pages(x.pages)
                and y.doi and normalize_pages(y.pages)):
            return True
    return False


def _copublication_evidence(a: Record, b: Record) -> bool:
    """True when two records agree so completely that a differing DOI is noise.

    A conflicting identifier is normally a hard block, and it must stay one: it
    is what stops "Part 1" merging with "Part 2". But one work can genuinely
    carry two publisher DOIs -- a conference abstract printed in two journals of
    the same publisher, an article with both a journal and a proceedings DOI.
    Overriding the block therefore demands agreement on *everything else*:
    an all-but-identical title, the same year, the same first page or article
    number, and a compatible first author. Measured on the ASySD Diabetes gold
    standard this fires for 4 record pairs, all of them true duplicates, and
    for no pair the gold standard calls distinct.

    The tests are ordered cheapest-first: the year and page comparisons are
    dictionary lookups, while ``_title_ratio`` runs a Ratcliff-Obershelp match
    and dominates the runtime if it is evaluated on every candidate pair.
    """
    return (a.year is not None and a.year == b.year
            and _page_digits(a.pages) == _page_digits(b.pages) != ""
            and _authors_ok(a, b)
            and _title_ratio(a, b) >= 0.99)


# The separator in a page range is written three different ways by three
# different databases, so all three are matched. They are spelled as escapes
# rather than as literal characters because a literal em dash next to a hyphen
# inside a character class reads as a range to the regex engine, and the
# repository-wide dash normalizer would rewrite the literals anyway.
_PSEUDO_RANGE_RE = re.compile("1\\s*[-\u2013\u2014]\\s*(\\d{1,3})$")


def pseudo_page_range(value: str) -> bool:
    """True when a page range is probably an article *length*, not a location.

    Journals that number articles instead of paginating them (BMC, Frontiers,
    PLOS, BMJ Open, F1000Research) supply the article's length to indexers, and
    several of them serialise it into the page-range fields: DOAJ returns
    ``start_page='1', end_page='15'`` for the article Europe PMC and PubMed
    number 393 (verified for ``10.1186/s12912-024-01991-0``). The record then
    claims a first page of 1, the locus guard reads two different first pages,
    and a true duplicate is refused.

    A range starting at page 1 is genuinely ambiguous -- the first article in an
    issue does start there -- so, as with a spreadsheet-damaged range, the value
    is treated as *unknown* rather than reinterpreted.

    Measured on a four-discipline corpus of 7440 harvested records, of which
    7187 enter the evaluation after the document-type curation drops 253 rows
    (272 of the harvested records carry such a range), at the domain level and
    against ``validation/multidomain_metrics.csv``:

        biomedicine       recall 0.9804 -> 0.9864, precision 0.9258 -> 0.9262
        computer science  recall 0.9941 -> 0.9941, precision unchanged
        economics         recall 0.9254 -> 0.9254, precision unchanged
        management        recall 0.9224 -> 0.9224, precision unchanged

    So the effect is confined to biomedicine in this corpus, which is where the
    article-numbering journals that cause the problem are concentrated: it
    recovers 4 true pairs there at a cost of no false ones. It is kept because
    the failure it fixes is silent and unbounded elsewhere -- a corpus drawn from
    BMC, Frontiers or PLOS carries many such ranges -- not because it moves the
    aggregate. On the ASySD Diabetes benchmark no record carries such a range, so
    nothing changes there.
    """
    m = _PSEUDO_RANGE_RE.fullmatch((value or "").strip())
    return m is not None and int(m.group(1)) > 1


def _page_digits(value: str) -> str:
    """Digits of a page/article number, without letter prefix or zero padding."""
    m = re.search(r"\d+", value or "")
    return str(int(m.group(0))) if m else ""


#: Markers that name *which instalment* of a recurring publication a title is.
#: Grey literature is full of series whose instalments share a title verbatim
#: and differ only here: agency quarterlies, annual reports, survey waves,
#: multi-part papers. Measured on a live transport corpus by rerunning it with
#: the rule disabled and enabled: 19 false merges eliminated (39 -> 20 over 182
#: judgeable pairs), all 19 consecutive quarters of one Department of Energy
#: series ("... Alternative Fueling Station Locator (Third Quarter 2021)" versus
#: "... Fourth Quarter 2021") -- fuzzy title matching cannot separate them,
#: because the titles really are ~97% identical.
_PERIOD_MARKER_RE = re.compile(
    r"\b(first|second|third|fourth|1st|2nd|3rd|4th)\s+quarter\b"
    r"|\bq[1-4]\b"
    r"|\b(january|february|march|april|may|june|july|august|september|october|"
    r"november|december)\b"
    r"|\b(spring|summer|autumn|fall|winter)\b"
    r"|\b(part|vol|volume|no|number|issue|wave|round|edition|ed)\.?\s*"
    r"([ivxlcdm]+|\d+)\b"
    # A bare year is NOT a marker. It is far more often part of the subject
    # ("Democracy in Latin America, 2012-2022") than an instalment label, and
    # databases disagree on the hyphen: one export renders that span as
    # "20122022", so a bare-year rule reported different markers for two copies
    # of one paper and split a true duplicate. A year counts only when a word
    # names it as the reporting period.
    r"|\b(annual|yearly|monthly|quarterly|biennial)\b(?:\s+\w+){0,3}\s+(19|20)\d{2}\b"
    r"|\b(19|20)\d{2}\s+(edition|report|update|survey|review|yearbook)\b",
    re.I)


def period_markers(title: str) -> "set[str]":
    """Instalment markers found in a title, lowercased.

    A year counts as a marker only through comparison: "The 1918 pandemic" and
    "The 1919 pandemic" are different works, while two copies of "COVID-19
    impact" carry the same marker set and are not separated by it.

    Selectivity and reach, measured on the 15-discipline corpus (13,809
    records): of 3,193 near-identical-title pairs the rule fires on 28. On the
    transport arm, measured by rerunning that corpus with the rule disabled and
    enabled, it eliminates 19 false merges (39 -> 20 over 182 judgeable pairs),
    and all 19 are consecutive quarters of one U.S. Department of Energy report
    series (DOI prefix 10.2172). It is
    English-only by construction -- "Rapport annuel 2019"/"2020",
    "Jahresbericht", "Raport roczny" are NOT separated, so a non-English serial
    still merges. Widening the vocabulary is safe (the rule only ever refuses a
    merge the identifier stage did not make); inferring periodicity from a bare
    year is not, and was reverted after it split a true duplicate whose title
    ends in the span "2012-2022" that one database renders as "20122022".
    """
    return {m.group(0).lower() for m in _PERIOD_MARKER_RE.finditer(title or "")}


def _separating_field(a: Record, b: Record) -> str:
    """Name a bibliographic coordinate proving *a* and *b* are distinct works.

    Two records reached by the same DOI are usually the same paper, but a
    conference supplement shares one DOI across an entire session. What
    distinguishes those abstracts is where they sit in the volume. Measured on
    the ASySD Diabetes gold standard: among pairs of *distinct* works that a
    shared identifier wrongly merged, the volume differs in 86% of cases and the
    first page in 60%, whereas among true duplicate pairs the first page differs
    in only 0.6% -- so the page test is close to free while the volume test
    needs the year to disagree as well before it is trusted.
    """
    if not (excel_mangled_pages(a.pages) or excel_mangled_pages(b.pages)
            or pseudo_page_range(a.pages) or pseudo_page_range(b.pages)):
        pa, pb = normalize_pages(a.pages), normalize_pages(b.pages)
        # An article number is rendered with or without its letter prefix and
        # zero padding ("137960" / "e0137960" for the same PLoS ONE article),
        # so compare the digits before declaring a disagreement.
        if pa and pb and pa != pb and _page_digits(pa) != _page_digits(pb):
            return "pages"
    va, vb = normalize_volume(a.volume), normalize_volume(b.volume)
    if (va and vb and va != vb
            and a.year is not None and b.year is not None and a.year != b.year):
        return "volume+year"
    # Instalments of a recurring publication: the titles agree except for the
    # marker naming which instalment this is, so only the marker separates them.
    ma, mb = period_markers(a.title), period_markers(b.title)
    if (ma or mb) and ma != mb:
        return "series instalment"
    return ""


def _years_ok(a: Record, b: Record, tol: int) -> bool:
    if a.year is None or b.year is None:
        return True
    return abs(a.year - b.year) <= tol


def _authors_ok(a: Record, b: Record) -> bool:
    sa, sb = a.first_author_surname, b.first_author_surname
    if not sa or not sb:
        return True
    return sa == sb or SequenceMatcher(None, sa, sb).ratio() >= 0.85


class _UnionFind:
    """Disjoint-set forest over record indices (path compression + union by size).

    Required for correctness, not speed: a record sharing a DOI with one record
    and a PMID with another means all three describe the same work, and that
    transitive closure cannot be expressed by first-match cluster assignment.
    """

    def __init__(self, n: int) -> None:
        self._parent = list(range(n))
        self._size = [1] * n

    def find(self, i: int) -> int:
        p = self._parent
        while p[i] != i:
            p[i] = p[p[i]]
            i = p[i]
        return i

    def union(self, a: int, b: int) -> int:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return ra
        if self._size[ra] < self._size[rb]:
            ra, rb = rb, ra
        self._parent[rb] = ra
        self._size[ra] += self._size[rb]
        return ra

    def groups(self) -> Dict[int, List[int]]:
        out: Dict[int, List[int]] = {}
        for i in range(len(self._parent)):
            out.setdefault(self.find(i), []).append(i)
        return out


def _conflicting_ids(a: Record, b: Record) -> str:
    """Return the name of an identifier both records carry with DIFFERENT values.

    Two records that each declare a DOI (or PMID/OpenAlex/Scopus ID) and
    disagree on it are, by the databases' own authority, distinct works --
    however similar their titles. Without this check the fuzzy stage merges
    'Part 1' with 'Part 2' and silently drops a study from the review.
    """
    for (ka, va), (_kb, vb) in zip(a.id_keys(), b.id_keys()):
        if va and vb and va != vb:
            return ka
    return ""


def _fuzzy_candidates(records: List[Record], reps: List[int], max_block: int,
                      report: "DedupReport | None" = None
                      ) -> "set[Tuple[int, int]]":
    """Candidate representative pairs sharing a rare-ish title token.

    Blocking on the first N characters of the title (the previous approach)
    both misses duplicates that differ early ('The effect of X' vs 'Effect of
    X') and degenerates to O(n^2) on real corpora, where hundreds of titles
    share a stock opening. Inverted-index blocking on tokens keyed to the
    rarest tokens of each title fixes both: recall no longer depends on the
    first characters, and buckets stay small because very common tokens are
    skipped.

    Oversized buckets must never leave a record without candidates. In a corpus
    with a narrow title vocabulary every single-token bucket can exceed
    *max_block*, and simply skipping them made the fuzzy stage silently do
    nothing -- exact-duplicate titles went undetected and the report claimed a
    clean corpus. Records whose buckets are all oversized therefore fall back to
    a composite key built from their two rarest tokens, which partitions a large
    bucket instead of discarding it; whatever remains unmatched is counted in
    the report so the degradation is visible.
    """
    postings: Dict[str, List[int]] = {}
    tokens_by_rep: Dict[int, List[str]] = {}
    for idx in reps:
        toks = [t for t in records[idx].norm_title.split() if len(t) > 2]
        tokens_by_rep[idx] = toks
        for t in set(toks):
            postings.setdefault(t, []).append(idx)

    # composite index over the two rarest tokens, used when single-token
    # buckets are all too large to scan
    pair_postings: Dict[Tuple[str, str], List[int]] = {}
    for idx in reps:
        toks = sorted(set(tokens_by_rep[idx]), key=lambda t: len(postings[t]))
        for i in range(min(3, len(toks))):
            for j in range(i + 1, min(4, len(toks))):
                pair_postings.setdefault((toks[i], toks[j]), []).append(idx)

    pairs: "set[Tuple[int, int]]" = set()
    oversized_skipped = 0
    no_candidates = 0
    for idx in reps:
        toks = tokens_by_rep[idx]
        if not toks:
            no_candidates += 1
            continue
        # probe the rarest tokens first; a true duplicate shares nearly all
        # tokens, so a handful of probes suffices and keeps the cost linear
        ranked = sorted(set(toks), key=lambda t: len(postings[t]))
        found = False
        for t in ranked[:4]:
            bucket = postings[t]
            if len(bucket) > max_block:
                oversized_skipped += 1
                continue
            for other in bucket:
                if other != idx:
                    pairs.add((idx, other) if idx < other else (other, idx))
                    found = True
        if found:
            continue
        # fallback: every candidate bucket was oversized (or singleton), so use
        # the composite key -- a much narrower bucket over the same tokens
        for i in range(min(3, len(ranked))):
            for j in range(i + 1, min(4, len(ranked))):
                bucket = pair_postings.get((ranked[i], ranked[j]), [])
                if len(bucket) > max_block:
                    continue
                for other in bucket:
                    if other != idx:
                        pairs.add((idx, other) if idx < other else (other, idx))
                        found = True
        if not found:
            no_candidates += 1

    if report is not None:
        report.oversized_blocks_skipped = oversized_skipped
        report.records_without_candidates = no_candidates
    return pairs


def _surname_key(r: Record) -> str:
    """Normalized first-author surname, truncated to absorb initial noise."""
    first = (r.authors or [""])[0]
    return normalize_title(first.split(",")[0])[:12]


def _round_keys(r: Record) -> List[Tuple[str, ...]]:
    """Composite blocking keys after ASySD's multi-round design.

    Title-token blocking finds duplicates whose titles are lexically close, but
    it cannot pair records whose titles were truncated, translated or mangled by
    an export. The remedy in ASySD (Hair et al. 2023, Table 2) is to run several
    rounds keyed on *combinations of fields that are individually weak but
    jointly identifying* -- author with year and first page, journal with volume
    and page. A pair agreeing exactly on such a combination is a candidate even
    when the titles look unrelated; the usual similarity checks still decide.
    """
    t = r.norm_title
    page, vol, year = (normalize_pages(r.pages), normalize_volume(r.volume),
                       str(r.year) if r.year is not None else "")
    au, jr = _surname_key(r), normalize_title(r.journal)[:24]
    keys: List[Tuple[str, ...]] = []
    if t and page:
        keys.append(("title+pages", t, page))
    if t and au:
        keys.append(("title+author", t, au))
    if au and year and page:
        keys.append(("author+year+pages", au, year, page))
    if jr and vol and page:
        keys.append(("journal+volume+pages", jr, vol, page))
    if au and year and len(t) >= 18:
        keys.append(("author+year+titlehead", au, year, t[:18]))
    return keys


#: A composite key is supposed to be nearly unique: a handful of records can
#: legitimately share "author+year+first page", but dozens cannot -- that means
#: the key degenerated (a common surname with a one-digit page, say). Such
#: buckets are dropped rather than expanded, which also keeps the pair set from
#: growing quadratically: at the general ``max_block`` of 400 a single bucket
#: would contribute ~80k pairs and the round index dominated both runtime and
#: memory (1.2 GB at 60k records before this cap).
_ROUND_BLOCK_CAP = 25


def _round_candidates(records: List[Record], reps: List[int], max_block: int
                      ) -> "set[Tuple[int, int]]":
    """Representative pairs agreeing exactly on one composite blocking key."""
    cap = min(max_block, _ROUND_BLOCK_CAP)
    index: Dict[Tuple[str, ...], List[int]] = {}
    for idx in reps:
        for key in _round_keys(records[idx]):
            bucket = index.setdefault(key, [])
            if len(bucket) <= cap:      # stop growing a degenerate bucket
                bucket.append(idx)
    pairs: "set[Tuple[int, int]]" = set()
    for bucket in index.values():
        if len(bucket) < 2 or len(bucket) > cap:
            continue
        for i, a in enumerate(bucket):
            for b in bucket[i + 1:]:
                pairs.add((a, b) if a < b else (b, a))
    return pairs


def deduplicate(corpus: Corpus | List[Record],
                fuzzy_threshold: float = 0.93,
                year_tolerance: int = 1,
                block_prefix: int = 10,
                max_block: int = 400,
                id_title_min: float = 0.50,
                separate_by_locus: bool = True,
                blocking_rounds: bool = True,
                round_title_min: float = 0.70,
                allow_copublication: bool = True,
                separate_conference: bool = True) -> DedupResult:
    """Cascading deduplication: identifiers first, then fuzzy title matching.

    Parameters
    ----------
    fuzzy_threshold:
        Minimum normalized-title similarity for the fuzzy stage. Calibrated on
        the ASySD Diabetes gold standard: across the whole 0.80-0.99 sweep F1
        moves by only ~0.005, because on that corpus the error floor is set by
        the identifier stage rather than the fuzzy stage; recall does fall off
        above ~0.95, so the default sits inside the flat region.
    year_tolerance:
        Permitted publication-year difference (databases disagree on
        online-first vs issue year).
    block_prefix:
        Accepted for backward compatibility and no longer used.
    max_block:
        Caps a title-token blocking bucket; oversized buckets fall back to
        composite keys and are reported.
    id_title_min:
        Minimum title similarity required before a *shared identifier* links
        two records. Guards against one DOI covering a whole conference
        supplement. Set to 0.0 to restore unconditional identifier matching.
    separate_by_locus:
        When a shared identifier links three or more records, refuse the link if
        the records sit at different places in the volume (different first page,
        or different volume *and* year). This separates distinct abstracts that
        a supplement-wide DOI would otherwise collapse.
    blocking_rounds:
        Also generate candidate pairs from exact agreement on composite field
        keys (title+pages, title+author, author+year+pages,
        journal+volume+pages, author+year+title-head), after ASySD's multi-round
        blocking. Recovers duplicates whose titles are too different for
        token blocking to pair them.
    round_title_min:
        Title similarity required for a pair reached *only* through a composite
        blocking key. Lower than *fuzzy_threshold* because exact agreement on
        author, year and page (or journal, volume and page) is independent
        evidence; the locus guard still applies, so records at different places
        in a volume are never joined this way.
    allow_copublication:
        Permit a differing DOI to be overridden when the title, year, first page
        and first author all agree -- the signature of one work carrying two
        publisher DOIs. Set to False for a strict reading in which a conflicting
        identifier always blocks a merge.
    separate_conference:
        Keep a conference abstract distinct from the journal article of the same
        study, following Cochrane and ASySD practice: they are separate reports
        of one study, cited separately and carrying different data. Set to False
        for one-record-per-study behaviour.
    """
    records = list(corpus.records if isinstance(corpus, Corpus) else corpus)
    report = DedupReport(before=len(records))
    if not records:
        return DedupResult(records=[], report=report)

    # ensure the decision log is traceable even for bare record lists
    for n, rec in enumerate(records, 1):
        if not rec.uid:
            rec.uid = f"T{n:06d}"

    uf = _UnionFind(len(records))

    # --- stage 1-4: identifier cascade (transitive via union-find) ----
    # count how many records share each identifier value first: a value held by
    # three or more records is the fingerprint of a supplement-wide DOI, and
    # only those links are title-checked below
    key_members: Dict[Tuple[str, str], List[int]] = {}
    for idx, rec in enumerate(records):
        for kname, val in rec.id_keys():
            if val:
                key_members.setdefault((kname, val), []).append(idx)

    key_owner: Dict[Tuple[str, str], int] = {}
    for idx, rec in enumerate(records):
        for kname, val in rec.id_keys():
            if not val:
                continue
            key = (kname, val)
            owner = key_owner.get(key)
            if owner is None:
                key_owner[key] = idx
                continue
            if uf.find(owner) == uf.find(idx):
                continue          # already the same work via another identifier
            # A shared identifier is strong evidence but not proof: publishers
            # assign one DOI to a whole conference-abstract supplement, so
            # dozens of unrelated studies can carry it. Validated on the ASySD
            # Diabetes gold standard, where 21 such DOIs spanned 140 records and
            # caused 91% of all false positives; requiring a minimum title
            # agreement raised F1 from 0.966 to 0.996.
            #
            # The check is applied only to identifiers shared by three or more
            # records -- the supplement signature. A one-to-one identifier match
            # with divergent titles is the normal cross-database case (differing
            # subtitle, translated title, or a title missing from one export)
            # and must still merge, otherwise the transitive closure breaks.
            if len(key_members.get(key, ())) >= 3:
                if id_title_min > 0.0 and \
                        _title_ratio(records[owner], rec) < id_title_min:
                    report.id_links_rejected += 1
                    continue
                # Titles can be near-identical and the works still distinct:
                # the same study presented at two conferences appears twice in
                # one supplement under one DOI, separated only by where it sits
                # in the volume.
                if separate_by_locus:
                    why = _separating_field(records[owner], rec)
                    if not why and separate_conference and \
                            _conference_vs_article(records[owner], rec):
                        why = "conference"
                    if why:
                        report.id_links_rejected += 1
                        report.by_locus[why] = report.by_locus.get(why, 0) + 1
                        continue
            uf.union(owner, idx)
            report.by_method[kname] = report.by_method.get(kname, 0) + 1
            _log(report, records[owner], rec, kname, 1.0, val)

    # --- stage 5: fuzzy title matching on cluster representatives -----
    reps = sorted(uf.groups())
    rep_of = {r: r for r in reps}
    candidates = _fuzzy_candidates(records, reps, max_block, report)
    # Pairs found by exact agreement on a composite field key carry evidence the
    # title similarity does not: agreeing on author, year and first page (or on
    # journal, volume and page) is itself strong. Such a pair is therefore
    # judged against a relaxed title threshold -- otherwise a truncated or
    # translated title in one export keeps the duplicate hidden even though
    # every other coordinate matches.
    round_pairs: "set[Tuple[int, int]]" = set()
    if blocking_rounds:
        round_pairs = _round_candidates(records, reps, max_block)
        extra = round_pairs - candidates
        report.round_candidates = len(extra)
        candidates |= extra
    for idx_i, idx_j in sorted(candidates):
        ri, rj = uf.find(idx_i), uf.find(idx_j)
        if ri == rj:
            continue
        a, b = records[rep_of.get(ri, ri)], records[rep_of.get(rj, rj)]
        via_round = (idx_i, idx_j) in round_pairs
        need = round_title_min if via_round else fuzzy_threshold
        # Reject on title length before running the matcher: this is the hot
        # path (tens of candidate pairs per record) and the bound is exact.
        if not _length_permits(a, b, need):
            continue
        conflict = _conflicting_ids(a, b)
        if conflict and not (allow_copublication
                             and _copublication_evidence(a, b)):
            continue
        if conflict:
            report.copublication_merges += 1
        ratio = _title_ratio(a, b)
        if (ratio >= need and _years_ok(a, b, year_tolerance)
                and _authors_ok(a, b)
                and not (separate_by_locus and _separating_field(a, b))
                and not (separate_conference and _conference_vs_article(a, b))):
            root = uf.union(ri, rj)
            # the surviving root keeps the richer representative
            rep_of[root] = (rep_of.get(ri, ri) if a.richness() >= b.richness()
                            else rep_of.get(rj, rj))
            report.by_method["fuzzy"] = report.by_method.get("fuzzy", 0) + 1
            _log(report, a, b, "fuzzy", ratio, "")

    # --- merge clusters into final records ---------------------------
    # The surviving record is the FIRST one encountered, not the one with the
    # richest metadata. `merge_from()` fills every empty field from the copies
    # being removed, so metadata completeness is identical either way; what
    # differs is reproducibility. First-encountered makes the surviving uid a
    # function of input order alone, rather than of how complete each database's
    # export happened to be, which is what a reference manager does on import.
    #
    # Measured on the ASySD Diabetes gold standard, where the reviewers kept the
    # copy from the first database searched (end-to-end F1, this rule vs
    # richness-first):
    #
    #   records added in search order        0.981  vs  0.870
    #   input grouped by duplicate cluster   0.839  vs  0.846
    #   input randomly shuffled (3 seeds)    0.716  vs  0.735
    #
    # The advantage is therefore NOT order-independent: it holds decisively when
    # the input carries search order, and richness-first is marginally ahead when
    # it does not, since neither rule can recover an ordering the input does not
    # contain. This rule is chosen for determinism and for the search-order case
    # real imports exhibit, not because it dominates on every permutation.
    #
    # Remaining copies are merged richest-first so the fullest available value
    # wins each empty field.
    out: List[Record] = []
    for _, member_idx in sorted(uf.groups().items()):
        first, *rest = sorted(member_idx)
        base = records[first]
        members = [base] + sorted((records[i] for i in rest),
                                  key=lambda r: r.richness(), reverse=True)
        _resolve_conflicts(base, members)
        for other in members[1:]:
            base.merge_from(other)
            lo, hi = sorted((base.source or "?", other.source or "?"))
            if lo != hi:
                report.overlap[(lo, hi)] = report.overlap.get((lo, hi), 0) + 1
        out.append(base)
    report.after = len(out)
    return DedupResult(records=out, report=report)


_CONSENSUS_FIELDS = ("journal", "volume", "issue", "pages", "doc_type",
                     "language", "issn")


def _resolve_conflicts(base: Record, members: List[Record]) -> None:
    """Adopt the majority value where cluster members disagree on a field.

    ``merge_from()`` only fills blanks, so whichever copy is kept imposes its own
    value on every field it already has. That is wrong when databases disagree:
    an IEEE Xplore export of an Elsevier article can carry the wrong journal
    title, and keeping the first copy would propagate it. Taking the value most
    copies agree on -- ties broken by metadata richness, which is the order
    *members* already carries -- makes the merged record independent of which
    copy happened to be encountered first.
    """
    if len(members) < 3:
        return          # no majority to speak of in a pair
    for name in _CONSENSUS_FIELDS:
        counts: Dict[str, int] = {}
        for m in members:
            val = getattr(m, name)
            if val:
                counts[val] = counts.get(val, 0) + 1
        if len(counts) < 2:
            continue
        order = {getattr(m, name): i for i in range(len(members) - 1, -1, -1)
                 for m in (members[i],) if getattr(m, name)}
        winner = min(counts, key=lambda v: (-counts[v], order[v]))
        if getattr(base, name) != winner:
            setattr(base, name, winner)


def _log(report: DedupReport, kept: Record, removed: Record,
         method: str, score: float, key: str) -> None:
    report.decisions.append(DedupDecision(
        kept_uid=kept.uid, removed_uid=removed.uid, method=method,
        score=score, key=key, kept_source=kept.source,
        removed_source=removed.source,
        kept_title=kept.title[:120], removed_title=removed.title[:120]))
