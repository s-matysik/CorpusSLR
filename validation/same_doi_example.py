"""The example that opens the article: one DOI, six different abstracts.

In the ASySD Diabetes benchmark, twelve records carry the DOI
10.1007/s00125-015-3687-4 (a conference supplement) and represent six
different abstracts, two copies of each. A matcher that treats a shared DOI as
decisive would merge all twelve into one record. This script runs the package
on those twelve records and prints what it keeps.

    PYTHONPATH=. python validation/same_doi_example.py
"""
from __future__ import annotations

import csv
import os

from corpusslr import Record, deduplicate

HERE = os.path.dirname(os.path.abspath(__file__))
GOLD = os.path.join(HERE, "labelled_test_set.csv")
DOI = "10.1007/s00125-015-3687-4"


def run(gold=GOLD, doi=DOI):
    """Return (records in, distinct abstracts in, records kept)."""
    with open(gold, encoding="utf-8", errors="replace", newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if doi in (r["doi"] or "").lower()]
    records = [Record(uid=r["record_id"], title=r["title"], abstract=r["abstract"],
                      authors=[a for a in (r["author"] or "").split(";") if a.strip()],
                      year=int(r["year"]) if (r["year"] or "").isdigit() else None,
                      journal=r["journal"], volume=r["volume"], pages=r["pages"],
                      doi=r["doi"]) for r in rows]
    kept = deduplicate(records).records
    return len(records), len({(r.abstract or "")[:80] for r in records}), len(kept)


def main():
    n, abstracts, kept = run()
    print("records sharing the DOI:", n)
    print("distinct abstracts among them:", abstracts)
    print("records kept after deduplication:", kept)


if __name__ == "__main__":                                  # pragma: no cover
    main()
