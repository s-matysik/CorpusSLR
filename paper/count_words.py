"""Count the words of the main text against the SoftwareX 3000-word limit.

SoftwareX counts the body of the article. Excluded here, and each exclusion is
reported separately so the reader can see what was left out rather than take
the total on trust:

  - the frontmatter (title, authors, abstract, keywords)
  - the code metadata table and every other table body
  - figure and table captions
  - listings (code is not prose)
  - the bibliography, acknowledgements and competing-interest declaration
  - TeX comments and markup

Usage:  python paper/count_words.py paper/corpusslr_softwarex.tex [--verbose]
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Dict, List, Tuple

EXCLUDED_ENVS = ["frontmatter", "table", "table*", "figure", "figure*",
                 "lstlisting", "verbatim", "thebibliography", "abstract",
                 "keyword"]


def _strip_comments(text: str) -> str:
    out = []
    for line in text.split("\n"):
        res, i = [], 0
        while i < len(line):
            c = line[i]
            if c == "\\" and i + 1 < len(line):
                res.append(line[i:i + 2])
                i += 2
                continue
            if c == "%":
                break
            res.append(c)
            i += 1
        out.append("".join(res))
    return "\n".join(out)


def _words(text: str) -> List[str]:
    """Words of prose, after markup has been removed."""
    t = text
    # \caption{...} and \label{...} contribute no body words
    for cmd in ("caption", "label", "bibliographystyle", "bibliography",
                "graphicspath", "lstset", "definecolor", "journal",
                "newcommand", "documentclass", "usepackage", "includegraphics"):
        t = re.sub(r"\\" + cmd + r"\s*(?:\[[^\]]*\])?\s*\{(?:[^{}]|\{[^{}]*\})*\}",
                   " ", t)
    # \cite{...} is one citation marker, not its keys
    t = re.sub(r"\\cite[tp]?\*?(?:\[[^\]]*\])*\{[^}]*\}", " ", t)
    t = re.sub(r"\\(?:ref|pageref|eqref|autoref)\{[^}]*\}", " X ", t)
    # keep the argument of text-formatting commands, drop the command
    t = re.sub(r"\\(?:emph|textbf|textit|texttt|text|url)\s*\{", "{", t)
    t = re.sub(r"\\begin\{[^}]*\}(?:\[[^\]]*\])?", " ", t)
    t = re.sub(r"\\end\{[^}]*\}", " ", t)
    t = re.sub(r"\$[^$]*\$", " N ", t)          # inline maths counts as a word
    t = re.sub(r"\\[A-Za-z]+\*?", " ", t)        # remaining commands
    t = t.replace("~", " ")
    t = re.sub(r"[{}&\\]", " ", t)
    # a token counts if it contains a letter or digit
    return [w for w in re.split(r"\s+", t) if re.search(r"[A-Za-z0-9]", w)]


def count(tex_path: str, verbose: bool = False) -> Tuple[int, Dict[str, int]]:
    with open(tex_path, encoding="utf-8") as fh:
        raw = fh.read()
    src = _strip_comments(raw)
    # cut everything before \end{frontmatter} and the back matter
    body = src.split("\\end{frontmatter}", 1)[-1]
    for marker in ("\\section*{Acknowledgements}", "\\bibliographystyle"):
        body = body.split(marker, 1)[0]

    excluded: Dict[str, int] = {}
    kept = body
    for env in EXCLUDED_ENVS:
        pat = re.compile(r"\\begin\{" + re.escape(env) + r"\}(?:\[[^\]]*\])?"
                         r".*?\\end\{" + re.escape(env) + r"\}", re.S)
        found = pat.findall(kept)
        if found:
            excluded[env] = sum(len(_words(f)) for f in found)
            kept = pat.sub(" ", kept)

    words = _words(kept)
    if verbose:
        print("kept prose, first 60 words:")
        print(" ".join(words[:60]))
        print()
    return len(words), excluded


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tex")
    ap.add_argument("--limit", type=int, default=3000)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    n, excluded = count(args.tex, args.verbose)
    print(f"file: {os.path.relpath(args.tex)}")
    print()
    print("excluded from the count (words each):")
    for env, c in sorted(excluded.items(), key=lambda kv: -kv[1]):
        print(f"  {env:16s} {c:5d}")
    print()
    print(f"MAIN TEXT: {n} words")
    print(f"LIMIT    : {args.limit} words")
    margin = args.limit - n
    verdict = "within limit" if margin >= 0 else "OVER LIMIT"
    print(f"{verdict}, margin {margin:+d} words "
          f"({100.0 * n / args.limit:.1f}% of the limit)")
    return 0 if margin >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
