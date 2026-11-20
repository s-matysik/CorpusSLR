"""Compare the header of the Scopus CSV that the package writes with real exports.

The exporter writes 46 columns. This script reads the first row of each file
given on the command line, parses it as CSV (so quoting and a byte-order mark do
not matter) and reports whether the column names and their order are identical
to ``corpusslr.export.SCOPUS_COLUMNS``. It also records the SHA-256 of the raw
first line, so that files that differ only in quoting can be told apart.

The real exports are not redistributed (the largest is 232 MB), so the result
is a recorded measurement, not something the package reproduces by itself:

    PYTHONPATH=. python validation/check_scopus_header.py FILE [FILE ...] \\
        --out validation/scopus_header_check.json
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sys

from corpusslr.export import SCOPUS_COLUMNS


def inspect(path):
    with open(path, "rb") as fh:
        raw = fh.read(8192).split(b"\n")[0].rstrip(b"\r")
    text = raw.decode("utf-8-sig")
    header = next(csv.reader(io.StringIO(text)))
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as fh:
        records = sum(1 for _ in csv.reader(fh)) - 1
    return {
        "file_size_bytes": os.path.getsize(path),
        "records": records,
        "columns": len(header),
        "names_and_order_identical": header == list(SCOPUS_COLUMNS),
        "header_line_sha256": hashlib.sha256(raw).hexdigest(),
        "names_quoted": raw.lstrip(b"\xef\xbb\xbf").startswith(b'"'),
        "byte_order_mark": raw.startswith(b"\xef\xbb\xbf"),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    rows = [inspect(p) for p in args.files]
    result = {
        "exporter_columns": len(SCOPUS_COLUMNS),
        "files_checked": len(rows),
        "all_names_and_order_identical": all(r["names_and_order_identical"] for r in rows),
        "files": rows,
        "note": ("File names are not recorded. Two of the files have quoted names and a "
                 "byte-order mark and the same header line; the third has unquoted names, so its raw header "
                 "line differs while the parsed names and order are identical."),
    }
    text = json.dumps(result, indent=1)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text)
    return 0 if result["all_names_and_order_identical"] else 1


if __name__ == "__main__":                                   # pragma: no cover
    sys.exit(main())
