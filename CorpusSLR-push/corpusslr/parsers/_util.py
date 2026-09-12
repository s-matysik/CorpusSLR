"""Field-level normalization shared by the file-export parsers.

Every bibliographic database exports the *same* metadata in a different
shape: Scopus writes authors as ``Kowalski J.; Nowak A.``, Web of Science as
``Kowalski, Jan``, BibTeX as ``Jan Kowalski and Anna Nowak``, EndNote as
``Kowalski, Jan``.  Deduplication in :mod:`corpusslr.dedup` compares first
author surnames, so an inconsistent author format silently lowers recall of
the duplicate cascade.  This module centralises the normalizations that all
export parsers must agree on -- author names to ``Family, Given``, keyword
splitting, page ranges, publication years and controlled ``doc_type``
vocabulary -- so that a record parsed from a Scopus CSV and the same record
parsed from an IEEE BibTeX file collapse onto one another.

The helpers are deliberately dependency-free (stdlib ``re`` only) and safe on
Python 3.9.
"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence

__all__ = [
    "normalize_author_name", "split_authors", "split_keywords",
    "clean_pages", "parse_year", "map_doc_type", "collapse_ws",
    "parse_int",
]

_WS_RE = re.compile(r"\s+")
_YEAR_RE = re.compile(r"(1[5-9]|20)\d{2}")
_FLOAT_YEAR_RE = re.compile(r"^\s*(\d{4})(?:\.0+)?\s*$")

# Name particles that belong to the family name rather than the given name.
# Only consulted when the token is not the first token of the name, so that
# "Al Gore" is read as Given=Al / Family=Gore while "Ludwig van Beethoven"
# is read as Family="van Beethoven".
_PARTICLES = {
    "van", "von", "vo", "de", "del", "della", "dello", "der", "den", "des",
    "di", "da", "do", "dos", "das", "du", "la", "le", "les", "lo", "los",
    "ter", "ten", "te", "af", "av", "bin", "ibn", "abu", "al", "el",
    "vander", "vanden", "vande", "op", "zu", "zum", "zur", "ould",
}

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "phd", "md", "msc", "bsc"}


def collapse_ws(value: Optional[str]) -> str:
    """Trim and squeeze internal whitespace (incl. newlines) to single spaces."""
    if not value:
        return ""
    return _WS_RE.sub(" ", str(value)).strip()


def _is_initials(token: str) -> bool:
    """True for ``J``, ``J.``, ``JM``, ``J.M.``, ``Ł.`` -- initial clusters."""
    t = token.replace(".", "").replace("-", "")
    if not t or len(t) > 4:
        return False
    return t.isupper() and t.isalpha()


def normalize_author_name(name: Optional[str]) -> str:
    """Return *name* as ``Family, Given``.

    Handles the four shapes that occur in real exports:

    ``Kowalski, Jan``      -> unchanged
    ``Kowalski J.``        -> ``Kowalski, J.``   (Scopus / Embase style)
    ``Jan Kowalski``       -> ``Kowalski, Jan``  (Crossref / BibTeX style)
    ``Ludwig van Beethoven`` -> ``van Beethoven, Ludwig``

    Suffixes (``Jr``, ``III``) are dropped from the given-name part because
    they are not present consistently across databases and would otherwise
    break surname comparison.
    """
    name = collapse_ws(name)
    # Trailing "." is preserved: it is part of an initial ("Kowalski J.") and
    # dropping it would make the same author look different across exports.
    name = name.strip(" ,;")
    if not name:
        return ""
    if "," in name:
        parts = [p.strip() for p in name.split(",")]
        parts = [p for p in parts if p]
        if not parts:
            return ""
        family = parts[0]
        given_parts = [p for p in parts[1:]
                       if p.lower().rstrip(".") not in _SUFFIXES]
        given_toks = " ".join(given_parts).split()
        while given_toks and given_toks[-1].lower().rstrip(".") in _SUFFIXES:
            given_toks.pop()
        given = collapse_ws(" ".join(given_toks))
        if given:
            return "{}, {}".format(family, given)
        # Dropping the suffix emptied the given-name part, so the comma was
        # separating a suffix rather than family from given: Scopus writes
        # "Lynch J.G., Jr." and Embase "Gutsche R.E., Jr.".  Returning
        # *family* alone here yields "Lynch J.G." -- a name in the
        # space-separated shape this function exists to convert, so the result
        # is not a fixed point and re-normalising it (which happens whenever a
        # corpus is exported and re-imported) yields a DIFFERENT string.  That
        # is not cosmetic: surname() reads the text before the comma, so
        # "Lynch J.G." gives the surname "j g" instead of "lynch", and the
        # first-author agreement test in the duplicate cascade compares the
        # initials of one record against the family name of the other.
        # Measured on a 14 302-record Scopus export: 31 records carry such a
        # name, 10 of them in first-author position.  Re-running the
        # space-separated branch on the family part fixes both the
        # idempotency and the surname.
        return normalize_author_name(family) if " " in family else family

    toks = name.split()
    if len(toks) == 1:
        return toks[0]
    # drop trailing suffix tokens ("John Smith Jr")
    while len(toks) > 2 and toks[-1].lower().rstrip(".") in _SUFFIXES:
        toks = toks[:-1]
    # "Kowalski J. M." -- trailing initials mean the family name comes first
    k = len(toks)
    while k > 1 and _is_initials(toks[k - 1]):
        k -= 1
    if k < len(toks):
        return "{}, {}".format(" ".join(toks[:k]), " ".join(toks[k:]))
    # "J. M. Kowalski" -- leading initials mean the family name comes last
    lead = 0
    while lead < len(toks) - 1 and _is_initials(toks[lead]):
        lead += 1
    if lead > 0:
        return "{}, {}".format(" ".join(toks[lead:]), " ".join(toks[:lead]))
    # "Ludwig van Beethoven"
    for i in range(1, len(toks) - 1):
        if toks[i].lower() in _PARTICLES:
            return "{}, {}".format(" ".join(toks[i:]), " ".join(toks[:i]))
    return "{}, {}".format(toks[-1], " ".join(toks[:-1]))


def _looks_like_given(token: str) -> bool:
    if not token:
        return False
    if _is_initials(token):
        return True
    words = token.split()
    if len(words) > 3:
        return False
    return all(w[:1].isupper() or _is_initials(w) for w in words)


#: A separator-less author list: an initial's period immediately followed by a
#: capitalised surname ("Adeli K.Lewis G. F."). The lookahead requires a lower
#: case letter after that capital, so an all-caps initial run ("Smith J.R.")
#: and a sentence boundary inside a single name are both left alone. Split on
#: the period, which is why the pattern is a lookbehind-free zero-width match
#: placed after it.
_RUN_TOGETHER_AUTHORS = re.compile(r"(?<=\.)(?=[A-Z][a-z])")


def split_authors(value, normalize: bool = True) -> List[str]:
    """Split an author cell into individual names.

    Separator precedence is ``;`` -> ``" and "`` -> ``,``.  A comma-only cell
    is ambiguous (``Smith, John, Doe, Jane`` is two authors, ``Smith, John``
    is one), so commas are only treated as author separators when the cell
    splits into an even number of parts whose odd positions look like given
    names or initials; otherwise the cell is kept whole.
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        raw = [collapse_ws(v) for v in value]
    else:
        text = collapse_ws(value)
        if not text:
            return []
        if ";" in text:
            raw = text.split(";")
        elif _RUN_TOGETHER_AUTHORS.search(text):
            # Some reference managers export the author list with no separator
            # at all: "Adeli K.Lewis G. F." is two authors, because the initial
            # period is doing double duty as abbreviation mark and separator.
            # Without this branch the whole cell became one mangled author, so
            # author evidence contributed nothing to matching for such records.
            # Observed in the ASySD Diabetes gold standard, where the entire
            # author column is in this form.
            raw = _RUN_TOGETHER_AUTHORS.split(text)
        elif re.search(r"\band\b", text):
            raw = re.split(r"\s+and\s+", text)
        elif "," in text:
            parts = [p.strip() for p in text.split(",") if p.strip()]
            if (len(parts) >= 4 and len(parts) % 2 == 0
                    and all(_looks_like_given(parts[i])
                            for i in range(1, len(parts), 2))):
                raw = ["{}, {}".format(parts[i], parts[i + 1])
                       for i in range(0, len(parts), 2)]
            else:
                raw = [text]
        else:
            raw = [text]
    out: List[str] = []
    for item in raw:
        item = collapse_ws(item).strip(" ,;")
        if not item or item.lower() in ("et al", "et al.", "others", "anonymous"):
            continue
        out.append(normalize_author_name(item) if normalize else item)
    return [a for a in out if a]


def split_keywords(value, seps: Sequence[str] = (";", "|", ",")) -> List[str]:
    """Split a keyword cell, preferring ``;`` over ``|`` over ``,``.

    Order is preserved and case-insensitive duplicates are dropped, because
    Scopus exports repeat author keywords inside the index-keyword column.
    """
    if value is None:
        return []
    items: Iterable
    if isinstance(value, (list, tuple)):
        items = value
    else:
        text = collapse_ws(value)
        if not text:
            return []
        chosen = None
        for s in seps:
            if s in text:
                chosen = s
                break
        items = text.split(chosen) if chosen else [text]
    out: List[str] = []
    seen = set()
    for kw in items:
        kw = collapse_ws(kw).strip(" .;,")
        if not kw:
            continue
        low = kw.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(kw)
    return out


_DASHES = re.compile(r"[\u2010-\u2015\u2212]|-{2,}")


def clean_pages(value: Optional[str]) -> str:
    """Normalize page ranges to ``start-end`` with an ASCII hyphen.

    BibTeX writes ``10--20``, EndNote ``10-20``, Scopus ``10-20`` and some
    CSV exports keep start and end in separate columns; downstream string
    comparison of the ``pages`` field only works if all of them agree.
    """
    text = collapse_ws(value)
    if not text:
        return ""
    text = _DASHES.sub("-", text)
    text = re.sub(r"\s*-\s*", "-", text)
    return text.strip(" -,;") if text.strip(" -,;") else ""


def parse_year(value) -> Optional[int]:
    """Extract a 4-digit year from ``2024``, ``"2024.0"``, ``"2024-05-01"``."""
    if value is None:
        return None
    if isinstance(value, int):
        return value if 1400 < value < 2200 else None
    if isinstance(value, float):
        return int(value) if 1400 < value < 2200 else None
    text = str(value).strip()
    if not text:
        return None
    m = _FLOAT_YEAR_RE.match(text)
    if m:
        return int(m.group(1))
    m = _YEAR_RE.search(text)
    return int(m.group(0)) if m else None


def parse_int(value) -> Optional[int]:
    """Tolerant integer parse: ``"12"``, ``"12.0"``, ``"1,234"`` -> int."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip().replace(",", "").replace(" ", "")
    if not text:
        return None
    m = re.match(r"^-?\d+(?:\.0+)?$", text)
    if not m:
        m2 = re.search(r"\d+", text)
        return int(m2.group(0)) if m2 else None
    return int(float(text))


# Controlled document-type vocabulary of :class:`corpusslr.record.Record`.
# Order matters: the first pattern that occurs in the input string wins, so
# "Review Article" resolves to review and "Conference Paper" to conference
# even though both contain a term of the generic "article" bucket.
_DOC_TYPE_RULES = (
    ("review", ("systematic review", "literature review", "meta-analysis",
                "meta analysis", "review", "short survey", "survey article")),
    ("preprint", ("preprint", "pre-print", "e-print", "eprint", "working paper",
                  "unpublished", "submitted manuscript")),
    ("conference", ("conference", "proceeding", "inproceedings", "cpaper",
                    "congress", "symposium", "workshop", "meeting abstract")),
    ("chapter", ("book chapter", "book section", "book part", "incollection",
                 "inbook", "chapter")),
    ("thesis", ("thesis", "dissertation", "phdthesis", "mastersthesis")),
    ("report", ("technical report", "techreport", "report", "manual",
                "guideline")),
    ("editorial", ("editorial", "erratum", "corrigendum", "note")),
    ("letter", ("letter", "correspondence", "comment", "reply")),
    ("book", ("book", "monograph", "edited volume")),
    ("article", ("journal article", "journal", "article", "original research",
                 "research paper", "paper", "jour", "data paper")),
)


def map_doc_type(value: Optional[str]) -> str:
    """Map a vendor document-type label onto the controlled vocabulary.

    Unknown labels return ``""`` rather than a guess: an empty ``doc_type``
    is honest missing data, whereas a wrong one propagates into PRISMA
    eligibility tables.
    """
    text = collapse_ws(value).lower()
    if not text:
        return ""
    for canonical, needles in _DOC_TYPE_RULES:
        for needle in needles:
            if needle in text:
                return canonical
    return ""
