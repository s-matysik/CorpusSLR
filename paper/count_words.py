"""Count the article against the SoftwareX word limit.

Two numbers are reported, because the journal's rule and a conservative body
count are not the same thing and confusing them once cost real content.

The journal's published rule is 4000 words, "excluding: title, authors,
affiliations, references, metadata tables and including: abstract, running
text, captions, footnotes". That is the number to submit against, and it is
printed first.

This file originally counted only the running text against 3000, excluding the
abstract and the captions. That was stricter than the journal on both the
threshold and the components, and passages were trimmed to fit a limit that
does not exist. The stricter figure is still printed, as a body-length
diagnostic rather than a constraint.

Excluded from the body figure, each reported separately so the reader can see
what was left out rather than take the total on trust:

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


def _strip_comments_text(text: str) -> str:
    return "\n".join(re.sub(r"(?<!\\\\)%.*$", "", line) for line in text.split("\n"))


def _plain_words(text: str) -> int:
    text = re.sub(r"\\\\[a-zA-Z@]+\s*(\[[^\]]*\])?", " ", text)
    text = re.sub(r"[{}$&~\\\\]", " ", text)
    return len([w for w in text.split() if any(c.isalnum() for c in w)])


def journal_components(path: str) -> Dict[str, int]:
    """The pieces the journal's rule names, each measured separately.

    The rule counts the abstract, the running text, the captions and the
    footnotes, and excludes the title, the authors, the affiliations, the
    references and the metadata tables. Listings are not named either way, so
    they are reported separately and added only to the conservative bound.
    """
    with open(path, encoding="utf-8") as handle:
        src = _strip_comments_text(handle.read())
    abstract = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", src, re.S)
    return {
        "abstract": _plain_words(abstract.group(1)) if abstract else 0,
        "captions": sum(_plain_words(m.group(1))
                        for m in re.finditer(r"\\caption\{(.*?)\}\s*\n", src, re.S)),
        "footnotes": sum(_plain_words(m.group(1))
                         for m in re.finditer(r"\\footnote\{(.*?)\}", src, re.S)),
        "listings": sum(_plain_words(m.group(1))
                        for m in re.finditer(
                            r"\\begin\{lstlisting\}(.*?)\\end\{lstlisting\}", src, re.S)),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tex")
    ap.add_argument("--limit", type=int, default=4000,
                    help="the journal's published limit")
    ap.add_argument("--body-limit", type=int, default=3000,
                    help="diagnostic threshold for the running text alone")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    n, excluded = count(args.tex, args.verbose)
    parts = journal_components(args.tex)
    journal = n + parts["abstract"] + parts["captions"] + parts["footnotes"]
    upper = journal + parts["listings"]
    print(f"file: {os.path.relpath(args.tex)}")
    print()
    print("excluded from the body figure (words each):")
    for env, c in sorted(excluded.items(), key=lambda kv: -kv[1]):
        print(f"  {env:16s} {c:5d}")
    print()
    print("the journal's rule: abstract + running text + captions + footnotes")
    for k in ("abstract", "captions", "footnotes"):
        print(f"  {k:16s} {parts[k]:5d}")
    print(f"  {'running text':16s} {n:5d}")
    print(f"JOURNAL COUNT: {journal} words")
    print(f"LIMIT        : {args.limit} words")
    margin = args.limit - journal
    verdict = "within limit" if margin >= 0 else "OVER LIMIT"
    print(f"{verdict}, margin {margin:+d} words "
          f"({100.0 * journal / args.limit:.1f}% of the limit)")
    print(f"  including listings as well: {upper} words, "
          f"margin {args.limit - upper:+d}")
    print()
    print(f"MAIN TEXT: {n} words   (running text only, diagnostic; "
          f"not the journal's rule)")
    return 0 if margin >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
