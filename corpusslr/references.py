"""Cited references: one field, three forms, one merge rule.

Databases do not agree on what a "reference" is.

* Scopus and Web of Science exports carry the reference list as free text, one
  string per cited work ("Kowalski J., Nowak A., A title, J Name, 12, pp. 1-9,
  (2019)"), joined with "; ". The string is whatever the publisher deposited.
* Crossref returns structured entries, of which some carry a DOI and some only
  an unstructured string.
* OpenAlex returns the identifiers of the cited works inside OpenAlex, with no
  DOI and no string.

Mapping these onto one structure cannot be lossless, and this module does not
pretend otherwise. :attr:`Record.references` holds a list of strings, each as
the source wrote it. Two entries are treated as the same cited work only when
they share a DOI, or share an OpenAlex identifier, or are identical after case
folding and whitespace normalisation (:func:`reference_key`). Free-text strings
from different databases are NOT matched to each other by similarity: a Scopus
string and a Web of Science string for the same cited paper usually differ in
author initials, journal abbreviation and page format, so they stay two
entries. That is deliberate. Merging by fuzzy match would silently fuse
distinct cited works, and a reference list is what backward snowballing is
built on.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Dict, Iterable, List, Optional, Tuple

from .record import Record

_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>;,]+)", re.I)
_OPENALEX = re.compile(r"openalex\.org/(W\d+)|^(W\d{4,})$", re.I)


def reference_key(entry: str) -> str:
    """Key under which two reference entries count as the same cited work.

    ``doi:...`` when a DOI is recognisable in the entry, ``oa:W...`` for an
    OpenAlex work, otherwise the casefolded, whitespace-collapsed string.
    """
    text = (entry or "").strip()
    m = _DOI.search(text)
    if m:
        return "doi:" + m.group(1).rstrip(".)").lower()
    m = _OPENALEX.search(text)
    if m:
        return "oa:" + (m.group(1) or m.group(2)).upper()
    return "txt:" + re.sub(r"\s+", " ", text).strip(" .;").casefold()


def merge_references(into: List[str], other: Iterable[str]) -> List[str]:
    """Append the entries of *other* whose key is not already in *into*."""
    seen = {reference_key(e) for e in into}
    for entry in other:
        k = reference_key(entry)
        if entry and k not in seen:
            into.append(entry)
            seen.add(k)
    return into


def split_reference_cell(cell: Optional[str]) -> List[str]:
    """Split an export cell on the separator vendors use (``"; "``)."""
    return [p.strip() for p in (cell or "").split(";") if p.strip()]


def cited_dois(records: Iterable[Record]) -> Counter:
    """How many records of the corpus cite each DOI that appears in a reference."""
    counts: Counter = Counter()
    for r in records:
        mine = {reference_key(e) for e in r.references}
        for k in mine:
            if k.startswith("doi:"):
                counts[k[4:]] += 1
    return counts


def cited_but_absent(records: List[Record], min_citing: int = 1) -> List[Tuple[str, int]]:
    """Backward-snowballing candidates: cited DOIs that are not in the corpus.

    Returns ``(doi, citing_records)`` sorted by the number of corpus records
    that cite the work, most cited first. Only references with a recognisable
    DOI can be listed; entries given as free text without a DOI are not
    resolved here, and the count of such entries is available from
    :func:`reference_coverage`.
    """
    from .record import normalize_doi
    present = {normalize_doi(r.doi) for r in records if r.doi}
    out = [(d, n) for d, n in cited_dois(records).items()
           if n >= min_citing and normalize_doi(d) not in present]
    return sorted(out, key=lambda x: (-x[1], x[0]))


def reference_coverage(records: List[Record]) -> Dict[str, int]:
    """Counts needed to judge whether snowballing from this corpus is possible."""
    total = with_refs = entries = with_doi = 0
    for r in records:
        total += 1
        if r.references:
            with_refs += 1
        for e in r.references:
            entries += 1
            if reference_key(e).startswith("doi:"):
                with_doi += 1
    return {"records": total, "records_with_references": with_refs,
            "reference_entries": entries, "entries_with_doi": with_doi}
