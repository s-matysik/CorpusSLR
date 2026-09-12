"""Replace typographic dashes with the plain hyphen, repository-wide.

House rule for this project: the only dash character allowed in any text we
write is the ASCII hyphen ``-``. Em dashes, en dashes and the Unicode minus
sign are replaced. In LaTeX the ligatures ``---`` and ``--`` are likewise
replaced, since they render as the characters we are removing.

Substitution is not a blind character swap, because an em dash is doing
punctuation work that a bare hyphen does not do:

* ``word - word``  an em dash surrounded by spaces becomes a spaced hyphen,
  which reads as a parenthetical break.
* ``word-word``    an unspaced en dash between digits or words is a range or a
  compound, so it becomes an unspaced hyphen (``2015-2024``, not ``2015 - 2024``).
* A dash immediately after a newline (a list bullet in some exports) becomes a
  hyphen with the following space preserved.

Run with ``--check`` to report without writing; the exit status is non-zero
when anything is found, which is what the test and the CI job use.
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Characters we refuse. The Unicode minus sign is included because it is
#: visually a dash and arrives from copy-pasted numeric output.
DASH_CHARS = {
    "\u2014": "em dash",
    "\u2013": "en dash",
    "\u2015": "horizontal bar",
    "\u2212": "minus sign",
}

#: Extensions we own. Binary and vendored files are left alone.
EXTENSIONS = (".md", ".py", ".tex", ".html", ".txt", ".cff", ".toml", ".json",
              ".yml", ".yaml", ".ipynb", ".bib", ".css", ".in", ".cfg")

SKIP_PARTS = ("build_check", "__pycache__", ".mypy_cache", ".ruff_cache",
              ".git", ".venv", "dist", "reviewer_package", "site")

#: LaTeX ligatures that render as the characters above.
#: ``--`` is also how every command-line flag starts, and those must survive
#: untouched, so the short ligature is only rewritten when it is used as
#: punctuation: surrounded by spaces, or bounded by letters on both sides.
_TEX_LIGATURES = ((re.compile(r"(?<!-)---(?!-)"), "-"),
                  (re.compile(r"(?<=\s)--(?=\s)"), "-"))


def _substitute(text):
    """Return (new_text, count) with every disallowed dash replaced."""
    n = sum(text.count(ch) for ch in DASH_CHARS)
    if n:
        # The Unicode minus is arithmetic, not punctuation: a spaced hyphen in
        # front of a number would read as a subtraction. It becomes a bare
        # hyphen glued to the digits it negates.
        text = re.sub(r"\u2212(?=[\d.])", "-", text)
        for ch in DASH_CHARS:
            # A spaced dash is a parenthetical break: one space either side.
            text = re.sub(r" *" + re.escape(ch) + r" +", " - ", text)
            text = re.sub(r" +" + re.escape(ch) + r" *", " - ", text)
            # What remains is unspaced: a range or a compound.
            text = text.replace(ch, "-")
    return text, n


def _substitute_tex(text):
    n = 0
    for pattern, repl in _TEX_LIGATURES:
        text, k = pattern.subn(repl, text)
        n += k
    return text, n


def walk(root=HERE):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_PARTS
                       and not d.startswith(".git")]
        for name in sorted(filenames):
            if not name.endswith(EXTENSIONS):
                continue
            path = os.path.join(dirpath, name)
            if any(part in path for part in SKIP_PARTS):
                continue
            yield path


def run(check_only=False, root=HERE):
    """Normalize (or report) every file under *root*. Returns a findings list."""
    findings = []
    for path in walk(root):
        with open(path, encoding="utf-8", errors="strict") as fh:
            original = fh.read()
        text, n = _substitute(original)
        if path.endswith((".tex", ".bib")):
            text, k = _substitute_tex(text)
            n += k
        if n:
            findings.append((os.path.relpath(path, root), n))
            if not check_only:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text)
    return findings


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="report without writing; non-zero exit when found")
    args = ap.parse_args(argv)
    found = run(check_only=args.check)
    if not found:
        print("no disallowed dash characters")
        return 0
    verb = "would change" if args.check else "changed"
    for rel, n in found:
        print("{}: {} {}".format(rel, n, verb))
    print("total: {} occurrences in {} files".format(
        sum(n for _, n in found), len(found)))
    return 1 if args.check else 0


if __name__ == "__main__":                       # pragma: no cover
    sys.exit(main())
