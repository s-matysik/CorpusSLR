"""Scan every file written for the SoftwareX article for forbidden dashes.

The project rule is that the only dash is the hyphen "-": no em dash (U+2014),
no en dash (U+2013), no LaTeX "---" and no LaTeX "--". This scans the files
this task produced, in every format, including the Markdown and the Python
sources, not just the LaTeX.

The scan is proved rather than asserted: --self-test writes a temporary file
containing one instance of each forbidden form and confirms the scanner finds
all of them, so a clean report means "checked" and not "did not look".

Usage:  python paper/check_dashes.py [--self-test]
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from typing import List, Tuple

FILES = [
    "corpusslr_softwarex.tex",
    "references.bib",
    "README.md",
    "listing_example.py",
    "verify_tex.py",
    "count_words.py",
    "check_dashes.py",
]

# A Unicode dash is forbidden in every file and every context: there is no
# legitimate use of one here.
UNICODE_FORMS: List[Tuple[str, str]] = [
    ("em dash U+2014", "\u2014"),
    ("en dash U+2013", "\u2013"),
    ("horizontal bar U+2015", "\u2015"),
    ("minus sign U+2212", "\u2212"),
]
# The ASCII sequences "--" and "---" are only dashes where a typesetter turns
# them into one, that is, in prose inside .tex, .bib and .md. Elsewhere the
# same characters are something else entirely, and flagging them is a false
# positive rather than a finding. The first version of this scanner reported
# 147 "dashes", every one of which was one of the following:
#
#   --self-test, --verbose, --limit   POSIX command-line flags
#   |---|---|                         a Markdown table delimiter row
#   %% -----, # --- BEGIN ...         comment separator rules
#   ("LaTeX en dash --", "--")        this scanner's own pattern definitions
#
# So the ASCII forms are checked only in typeset prose, with those exemptions
# applied. The Unicode forms are still checked everywhere, unconditionally.
ASCII_FORMS: List[Tuple[str, str]] = [
    ("LaTeX em dash ---", "---"),
    ("LaTeX en dash --", "--"),
]
TYPESET_SUFFIXES = {".tex", ".bib", ".md"}

# a run of 4+ dashes is a rule, not a dash; -- attached to a word is a flag
_RULE = re.compile(r"-{4,}")
_FLAG = re.compile(r"(?<![-\w])--[A-Za-z][\w-]*")
_MD_TABLE_ROW = re.compile(r"^\s*\|?[\s|:-]+\|[\s|:-]*$")


def _mask_exempt(line: str, suffix: str) -> str:
    """Blank the spans where "--" is not a dash, preserving line length."""
    blank = lambda m: " " * (m.end() - m.start())  # noqa: E731
    if suffix == ".md":
        if _MD_TABLE_ROW.match(line):
            return " " * len(line)
        # inline code spans: `--flag` is code, not prose
        line = re.sub(r"`[^`]*`", blank, line)
    if suffix in (".tex", ".bib"):
        # a TeX comment is not typeset
        m = re.search(r"(?<!\\)%", line)
        if m:
            line = line[:m.start()] + " " * (len(line) - m.start())
    line = _RULE.sub(blank, line)
    return _FLAG.sub(blank, line)


def scan_text(text: str, label: str, suffix: str = "") -> List[str]:
    """Every forbidden dash in `text`, as 'label:line: what'."""
    findings: List[str] = []
    check_ascii = suffix in TYPESET_SUFFIXES
    for i, line in enumerate(text.split("\n"), start=1):
        forms = list(UNICODE_FORMS)
        masked = _mask_exempt(line, suffix) if check_ascii else line
        for name, needle in forms:
            start = 0
            while True:
                j = line.find(needle, start)
                if j < 0:
                    break
                snippet = line[max(0, j - 30):j + 30].strip()
                findings.append(f"{label}:{i}: {name} in {snippet!r}")
                start = j + len(needle)
        if not check_ascii:
            continue
        for name, needle in ASCII_FORMS:
            start = 0
            while True:
                j = masked.find(needle, start)
                if j < 0:
                    break
                if needle == "--" and "---" in masked[max(0, j - 2):j + 3]:
                    start = j + 1
                    continue
                snippet = line[max(0, j - 30):j + 30].strip()
                findings.append(f"{label}:{i}: {name} in {snippet!r}")
                start = j + len(needle)
    return findings


def scan_file(path: str) -> List[str]:
    with open(path, encoding="utf-8") as fh:
        return scan_text(fh.read(), os.path.basename(path),
                         os.path.splitext(path)[1].lower())


def self_test() -> int:
    """Prove the scanner: a file with one of each form must yield one each."""
    import tempfile

    print("self-test: a file containing every forbidden form must be flagged")
    sample = "\n".join([
        "alpha \u2014 em dash",
        "beta \u2013 en dash",
        "gamma \u2015 horizontal bar",
        "delta \u2212 minus sign",
        "epsilon --- latex em",
        "zeta -- latex en",
        "eta - a plain hyphen, which is allowed and must NOT be flagged",
    ])
    found = scan_text(sample, "sample", ".tex")
    all_forms = UNICODE_FORMS + ASCII_FORMS
    by_form = {name: 0 for name, _ in all_forms}
    for f in found:
        for name, _ in all_forms:
            if name in f:
                by_form[name] += 1
    ok = True
    for name, n in by_form.items():
        status = "CAUGHT" if n == 1 else f"WRONG ({n})"
        print(f"  [{status:10s}] {name}")
        if n != 1:
            ok = False
    hyphen_flagged = any("plain hyphen" in f for f in found)
    print(f"  [{'OK' if not hyphen_flagged else 'FALSE POSITIVE':10s}] "
          "a plain hyphen is not flagged")
    if hyphen_flagged:
        ok = False

    # The exemptions must not swallow a real dash, and must not fire on the
    # constructs that are not dashes. Both directions are checked.
    print()
    print("  exemptions: not-a-dash must pass, a real dash next to it must not")
    cases = [
        (".md", "run `python x.py --self-test` now", 0, "CLI flag in code span"),
        (".md", "|---|---|", 0, "Markdown table delimiter row"),
        (".tex", "%% ------------------------------", 0, "TeX comment rule"),
        (".py", "ap.add_argument('--verbose')", 0, "flag in a .py file"),
        (".py", "x = 'a \u2014 b'", 1, "Unicode dash in a .py file"),
        (".tex", "the result -- which is prose -- counts", 2,
         "real -- in TeX prose"),
        (".md", "real prose with -- inside it", 1, "real -- in Markdown prose"),
        (".tex", "% a comment with -- inside", 0, "-- inside a TeX comment"),
    ]
    for suffix, line, expected, label in cases:
        n = len(scan_text(line, "case", suffix))
        good = n == expected
        print(f"  [{'OK' if good else 'WRONG':10s}] {label}: "
              f"{n} finding(s), expected {expected}")
        if not good:
            ok = False
    # and a clean file must produce nothing
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                     encoding="utf-8") as fh:
        fh.write("only hyphens - here - and nothing else\n")
        clean_path = fh.name
    try:
        clean = scan_file(clean_path)
        print(f"  [{'OK' if not clean else 'WRONG':10s}] "
              "a clean file produces no findings")
        if clean:
            ok = False
    finally:
        os.unlink(clean_path)
    print()
    print("SELF-TEST PASSED" if ok else "SELF-TEST FAILED")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()

    here = os.path.dirname(os.path.abspath(__file__))
    total = 0
    print("dash scan: forbidden are U+2014, U+2013, U+2015, U+2212, "
          "'---' and '--'")
    print("allowed is the hyphen '-' only")
    print()
    for name in FILES:
        path = os.path.join(here, name)
        if not os.path.exists(path):
            print(f"  [MISSING  ] {name}")
            total += 1
            continue
        findings = scan_file(path)
        total += len(findings)
        status = "clean" if not findings else f"{len(findings)} finding(s)"
        print(f"  [{status:12s}] {name}")
        for f in findings[:10]:
            print(f"                 - {f}")
    print()
    print(f"RESULT: {total} forbidden dash(es) across {len(FILES)} files")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
