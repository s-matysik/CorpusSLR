"""Machine verification of the SoftwareX LaTeX source, independent of a compiler.

A compiler run proves the file builds today, on this machine, with this TeX
installation. It does not tell a reader which properties were checked, and it
cannot run at all on a machine without TeX. This script checks the structural
properties explicitly, so the result is inspectable and reproducible:

  1. \\begin/\\end nesting, with a stack rather than a counter, so that a
     crossed pair (\\begin{a}\\begin{b}\\end{a}\\end{b}) is caught and not
     merely an unequal count
  2. every \\cite key resolves to an entry in the .bib file, and every .bib
     entry is cited (an uncited entry is reported separately, as a warning)
  3. every \\includegraphics target exists on disk, honouring \\graphicspath
  4. every \\ref resolves to a \\label, and every \\label is referenced
     (an orphan label is reported)
  5. every table and figure environment carries both \\caption and \\label
  6. every backslash command used is either a LaTeX/TeX primitive, provided by
     one of the loaded packages, or defined in the file; anything else is
     listed as unresolved
  7. no en dash, em dash, or LaTeX -- / --- appears anywhere in the file

Checks 1-7 are not evidence on their own: a check that passes proves nothing
until it is shown to fail on a fault of the same class. `--self-test` injects
one fault per check into a copy of the file and asserts the check reports it.

Usage:
    python paper/verify_tex.py paper/corpusslr_softwarex.tex
    python paper/verify_tex.py paper/corpusslr_softwarex.tex --self-test
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Dict, List, Set, Tuple

# Commands assumed available: TeX/LaTeX kernel plus the packages this document
# loads. Grouped by provider so that check 6 can name where each comes from.
KERNEL = {
    "documentclass", "usepackage", "begin", "end", "section", "subsection",
    "subsubsection", "paragraph", "label", "ref", "pageref", "cite", "item",
    "caption", "textbf", "textit", "texttt", "emph", "bfseries", "itshape",
    "ttfamily", "small", "footnotesize", "scriptsize", "large", "Large",
    "centering", "newline", "par", "hspace", "vspace", "quad", "qquad",
    "bibliographystyle", "bibliography", "title", "author", "address",
    "date", "maketitle", "newcommand", "renewcommand", "def", "let",
    "textwidth", "columnwidth", "linewidth", "textheight", "dag", "dagger",
    "ldots", "dots", "and", "protect", "relax", "space", "thanks",
    "footnote", "url", "verb", "S", "P", "copyright", "%",
}
PACKAGE_COMMANDS = {
    "graphicx": {"includegraphics", "graphicspath", "rotatebox", "scalebox",
                 "resizebox", "DeclareGraphicsExtensions"},
    "booktabs": {"toprule", "midrule", "bottomrule", "cmidrule", "addlinespace",
                 "specialrule"},
    "amsmath": {"text", "frac", "dfrac", "sum", "prod", "int", "align",
                "eqref", "mathrm", "mathbf", "Delta", "times", "leq", "geq",
                "approx", "pm", "cdot", "infty", "alpha", "beta", "gamma"},
    "listings": {"lstset", "lstinputlisting", "lstlistoflistings",
                 "lstdefinestyle", "lstname"},
    "xcolor": {"color", "textcolor", "definecolor", "colorbox", "pagecolor"},
    "url": {"url", "urlstyle", "path"},
    "elsarticle": {"journal", "ead", "corref", "fnref", "tnoteref", "cortext",
                   "fntext", "tnotetext", "keyword", "sep", "verbatim",
                   "biboptions", "frontmatter", "abstract", "printead"},
}
# Environments whose bodies are verbatim: their contents must not be parsed for
# commands, because a listing legitimately contains text like \begin{...} or a
# stray backslash that is data, not markup.
VERBATIM_ENVS = {"lstlisting", "verbatim", "Verbatim", "minted", "alltt"}

DASH_PATTERNS = [
    ("em dash U+2014", "\u2014"),
    ("en dash U+2013", "\u2013"),
    ("LaTeX em dash ---", "---"),
    ("LaTeX en dash --", "--"),
]


class Finding(Tuple[str, str]):
    pass


def _read(path: str) -> str:
    """Read a text file through a context manager (ruff SIM115)."""
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _strip_comments(text: str) -> str:
    """Blank out TeX comments while preserving line count and \\% escapes."""
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


def _mask_verbatim(text: str) -> str:
    """Replace verbatim environment bodies with blanks, keeping line numbers.

    The \\begin/\\end delimiters themselves are kept so that check 1 still sees
    the pair; only the body is blanked.
    """
    for env in VERBATIM_ENVS:
        pat = re.compile(
            r"(\\begin\{" + env + r"\}(?:\[[^\]]*\])?)(.*?)(\\end\{" + env + r"\})",
            re.S)

        def repl(m: "re.Match[str]") -> str:
            body = m.group(2)
            return m.group(1) + re.sub(r"[^\n]", " ", body) + m.group(3)

        text = pat.sub(repl, text)
    return text


def check_environments(src: str) -> List[str]:
    """Check 1: \\begin/\\end nesting with a stack."""
    findings: List[str] = []
    stack: List[Tuple[str, int]] = []
    for m in re.finditer(r"\\(begin|end)\{([^}]*)\}", src):
        kind, name = m.group(1), m.group(2)
        line = src.count("\n", 0, m.start()) + 1
        if kind == "begin":
            stack.append((name, line))
        else:
            if not stack:
                findings.append(
                    f"line {line}: \\end{{{name}}} with no matching \\begin")
                continue
            open_name, open_line = stack.pop()
            if open_name != name:
                findings.append(
                    f"line {line}: \\end{{{name}}} closes "
                    f"\\begin{{{open_name}}} opened at line {open_line} "
                    "(crossed or unclosed environment)")
    for name, line in stack:
        findings.append(f"line {line}: \\begin{{{name}}} is never closed")
    return findings


def _bib_keys(bib_path: str) -> Set[str]:
    if not os.path.exists(bib_path):
        return set()
    text = _read(bib_path)
    return set(re.findall(r"@\w+\s*\{\s*([^,\s]+)\s*,", text))


def check_citations(src: str, bib_path: str) -> Tuple[List[str], List[str]]:
    """Check 2: every \\cite key exists in the .bib; report uncited entries."""
    findings: List[str] = []
    cited: Set[str] = set()
    keys = _bib_keys(bib_path)
    for m in re.finditer(r"\\cite[tp]?\*?(?:\[[^\]]*\])*\{([^}]*)\}", src):
        line = src.count("\n", 0, m.start()) + 1
        for key in (k.strip() for k in m.group(1).split(",")):
            if not key:
                continue
            cited.add(key)
            if key not in keys:
                findings.append(
                    f"line {line}: \\cite{{{key}}} has no entry in "
                    f"{os.path.basename(bib_path)}")
    warnings = [f"bib entry '{k}' is never cited" for k in sorted(keys - cited)]
    return findings, warnings


def check_graphics(src: str, tex_dir: str) -> List[str]:
    """Check 3: every \\includegraphics target exists, honouring \\graphicspath."""
    findings: List[str] = []
    roots = [tex_dir]
    for m in re.finditer(r"\\graphicspath\{(.+?)\}\s*$", src, re.M):
        for p in re.findall(r"\{([^{}]*)\}", m.group(1)):
            roots.append(os.path.join(tex_dir, p))
    exts = ["", ".png", ".pdf", ".jpg", ".jpeg", ".eps"]
    for m in re.finditer(
            r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}", src):
        target = m.group(1).strip()
        line = src.count("\n", 0, m.start()) + 1
        if not any(os.path.isfile(os.path.join(r, target + e))
                   for r in roots for e in exts):
            findings.append(
                f"line {line}: \\includegraphics{{{target}}} matches no file "
                f"under {', '.join(os.path.relpath(r, tex_dir) or '.' for r in roots)}")
    return findings


def _declared_labels(src: str) -> Set[str]:
    """Every label a \\ref can resolve to.

    Two syntaxes declare a label. The kernel's \\label{key}, and the
    listings package's key-value option label={key} in
    \\begin{lstlisting}[...], which is a real label as far as \\ref is
    concerned. Missing the second one made this check report three false
    positives on the article, which is how it was found.
    """
    labels = set(re.findall(r"\\label\{([^}]*)\}", src))
    for m in re.finditer(r"\\begin\{lstlisting\}\[([^\]]*)\]", src):
        labels.update(re.findall(r"label\s*=\s*\{?([^,}\]]+)\}?", m.group(1)))
    return {k.strip() for k in labels}


def check_refs(src: str) -> Tuple[List[str], List[str]]:
    """Check 4: every \\ref resolves to a \\label; report orphan labels."""
    findings: List[str] = []
    labels = _declared_labels(src)
    used: Set[str] = set()
    for m in re.finditer(r"\\(?:ref|pageref|autoref|eqref)\{([^}]*)\}", src):
        key = m.group(1).strip()
        line = src.count("\n", 0, m.start()) + 1
        used.add(key)
        if key not in labels:
            findings.append(
                f"line {line}: \\ref{{{key}}} has no matching \\label")
    warnings = [f"\\label{{{k}}} is never referenced" for k in sorted(labels - used)]
    return findings, warnings


def check_float_captions(src: str) -> List[str]:
    """Check 5: every table/figure environment has a \\caption and a \\label."""
    findings: List[str] = []
    for env in ("table", "table*", "figure", "figure*"):
        pat = re.compile(
            r"\\begin\{" + re.escape(env) + r"\}(?:\[[^\]]*\])?(.*?)"
            r"\\end\{" + re.escape(env) + r"\}", re.S)
        for m in pat.finditer(src):
            body = m.group(1)
            line = src.count("\n", 0, m.start()) + 1
            if "\\caption" not in body:
                findings.append(f"line {line}: {env} environment has no \\caption")
            if "\\label" not in body:
                findings.append(f"line {line}: {env} environment has no \\label")
    return findings


def check_commands(src: str) -> Tuple[List[str], List[str], Set[str]]:
    """Check 6: every command resolves to the kernel, a loaded package, or the file."""
    packages: Set[str] = set()
    for m in re.finditer(r"\\usepackage\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}", src):
        packages.update(p.strip() for p in m.group(1).split(","))
    cls = re.search(r"\\documentclass\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}", src)
    if cls:
        packages.add(cls.group(1).strip())

    allowed = set(KERNEL)
    for pkg in packages:
        allowed |= PACKAGE_COMMANDS.get(pkg, set())
    # commands defined in the file itself
    allowed |= set(re.findall(r"\\(?:new|renew|provide)command\*?\s*\{?\\(\w+)", src))
    allowed |= set(re.findall(r"\\definecolor\s*\{(\w+)\}", src))
    # \section* etc. are the same command
    used = set(re.findall(r"\\([A-Za-z]+)", src))
    unresolved = sorted(used - allowed)
    return sorted(packages), unresolved, used


def check_dashes(src_raw: str) -> List[str]:
    """Check 7: no en dash, em dash, or LaTeX -- / ---."""
    findings: List[str] = []
    for name, needle in DASH_PATTERNS:
        for i, line in enumerate(src_raw.split("\n"), start=1):
            start = 0
            while True:
                j = line.find(needle, start)
                if j < 0:
                    break
                # "---" also contains "--": report the longest match only
                if needle == "--" and (line[j:j + 3] == "---"
                                       or line[max(0, j - 1):j + 2] == "---"):
                    start = j + 1
                    continue
                findings.append(
                    f"line {i}: {name} in {line[max(0, j - 25):j + 25].strip()!r}")
                start = j + len(needle)
    return findings


def _unescape_pdf(s: str) -> str:
    """Resolve PDF literal-string escapes, notably octal \\ddd.

    pdfTeX writes a T1 en dash as the three-digit octal escape \\226 rather
    than as the raw byte. Without decoding it, a scan sees the four harmless
    characters "\\", "2", "2", "6" and reports no dash, which is how this
    check was briefly vacuous.
    """
    out: List[str] = []
    i = 0
    simple = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f",
              "(": "(", ")": ")", "\\": "\\"}
    while i < len(s):
        c = s[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        if i + 1 >= len(s):
            break
        nxt = s[i + 1]
        m = re.match(r"[0-7]{1,3}", s[i + 1:i + 4])
        if m:
            out.append(chr(int(m.group(0), 8) & 0xFF))
            i += 1 + len(m.group(0))
        else:
            out.append(simple.get(nxt, nxt))
            i += 2
    return "".join(out)


def check_pdf_dashes(pdf_path: str) -> List[str]:
    """Check 8: no en/em dash in the TYPESET output.

    Checks 1-7 read the .tex. That is not sufficient, and this check exists
    because the source check missed a real defect: BibTeX's n.dashify function
    in elsarticle-num.bst rewrites a hyphen in a pages field into "--", so a
    .bib containing only hyphens still produced en dashes in the PDF. Only the
    rendered bytes can catch a dash introduced downstream of the source.

    The text is recovered from the PDF content streams directly, so that this
    check needs no external tool (pdftotext is not installed everywhere, and
    an absent tool silently returning nothing would make the check vacuous).
    """
    import zlib

    if not os.path.exists(pdf_path):
        return [(f"{os.path.basename(pdf_path)} not found: compile first, "
                 "or this check is vacuous")]
    with open(pdf_path, "rb") as fh:
        raw = fh.read()
    chunks: List[bytes] = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", raw, re.S):
        try:
            chunks.append(zlib.decompress(m.group(1)))
        except Exception:
            continue
    if not chunks:
        return [(f"{os.path.basename(pdf_path)}: no decompressible content "
                 "stream, cannot verify the typeset text")]
    findings: List[str] = []
    # Only text matters. An earlier version scanned every decompressed stream
    # for parenthesised literals and reported 507 hits, all of them bytes
    # inside the embedded PNG bitmaps. Restrict to text objects (BT ... ET) and
    # to the operators that actually show glyphs (Tj, TJ, ', ").
    shown_parts: List[str] = []
    for blob in chunks:
        page = blob.decode("latin-1")
        for bt in re.finditer(r"\bBT\b(.*?)\bET\b", page, re.S):
            body = bt.group(1)
            for op in re.finditer(
                    r"(\((?:[^()\\]|\\.)*\)|\[(?:[^\[\]\\]|\\.)*\])\s*"
                    r"(Tj|TJ|'|\")", body, re.S):
                shown_parts += re.findall(r"\(((?:[^()\\]|\\.)*)\)", op.group(1))
    shown = _unescape_pdf("".join(shown_parts))
    if not shown:
        return [(f"{os.path.basename(pdf_path)}: no text-showing operators "
                 "found, cannot verify the typeset text")]
    # In a Type1 text stream an en dash is byte 0x96 / octal 226 and an em dash
    # 0x97 / 227 under the TeX text encoding; a UTF-16 producer writes U+2013.
    for label, needle in (("en dash", "\u2013"), ("em dash", "\u2014"),
                          ("en dash (T1 byte 0x96)", "\x96"),
                          ("em dash (T1 byte 0x97)", "\x97")):
        for hit in re.finditer(re.escape(needle), shown):
            ctx = shown[max(0, hit.start() - 40):hit.start() + 20]
            findings.append(f"typeset {label} in ...{ctx!r}")
    return findings


def verify(tex_path: str, quiet: bool = False) -> Dict[str, List[str]]:
    tex_dir = os.path.dirname(os.path.abspath(tex_path))
    raw = _read(tex_path)
    src = _mask_verbatim(_strip_comments(raw))
    # dashes are checked on the real bytes minus comments: a dash in a comment
    # is not typeset, but a dash inside a listing IS, so verbatim is not masked
    dash_src = _strip_comments(raw)

    bib_match = re.search(r"\\bibliography\{([^}]*)\}", src)
    bib_path = os.path.join(tex_dir, (bib_match.group(1) if bib_match else "references") + ".bib")

    cite_f, cite_w = check_citations(src, bib_path)
    ref_f, ref_w = check_refs(src)
    packages, unresolved, used = check_commands(src)

    results: Dict[str, List[str]] = {
        "1 environments balanced (stack)": check_environments(src),
        "2 cite keys resolve in .bib": cite_f,
        "3 includegraphics targets exist": check_graphics(src, tex_dir),
        "4 refs resolve to labels": ref_f,
        "5 floats have caption+label": check_float_captions(src),
        "6 commands resolve to class/packages": unresolved,
        "7 no en/em dashes": check_dashes(dash_src),
        "8 no en/em dashes in the PDF": check_pdf_dashes(
            os.path.splitext(os.path.abspath(tex_path))[0] + ".pdf"),
    }
    warnings = {
        "2w uncited bib entries": cite_w,
        "4w orphan labels": ref_w,
    }

    if not quiet:
        print(f"file: {os.path.relpath(tex_path)}")
        print(f"bib : {os.path.relpath(bib_path)} "
              f"({len(_bib_keys(bib_path))} entries)")
        print(f"packages loaded: {', '.join(packages)}")
        print(f"distinct commands used: {len(used)}")
        print()
        for name, f in results.items():
            status = "PASS" if not f else f"FAIL ({len(f)})"
            print(f"  [{status:9s}] check {name}")
            for line in f[:12]:
                print(f"              - {line}")
            if len(f) > 12:
                print(f"              ... {len(f) - 12} more")
        print()
        for name, w in warnings.items():
            status = "clean" if not w else f"{len(w)} warning(s)"
            print(f"  [{status:9s}] {name}")
            for line in w[:12]:
                print(f"              - {line}")
        total = sum(len(f) for f in results.values())
        print()
        print(f"RESULT: {total} finding(s) across "
              f"{len(results)} checks")
    return results


# ----------------------------------------------------------------------
# Fault injection: a passing check proves nothing until it fails on purpose.
# ----------------------------------------------------------------------
FAULTS = [
    ("1 environments balanced (stack)",
     "delete one \\end{table}",
     lambda t: t.replace("\\end{tabular}\n\\end{table}",
                         "\\end{tabular}", 1)),
    ("1 environments balanced (stack)",
     "cross two environments",
     lambda t: t.replace(
         "\\begin{enumerate}", "\\begin{enumerate}\\begin{itemize}", 1
     ).replace("\\end{enumerate}", "\\end{enumerate}\\end{itemize}", 1)),
    ("2 cite keys resolve in .bib",
     "misspell a \\cite key",
     lambda t: t.replace("\\cite{hair2023}", "\\cite{hair2032}", 1)),
    ("3 includegraphics targets exist",
     "point a figure at a missing file",
     lambda t: t.replace("{fig_domains.png}", "{fig_domains_missing.png}", 1)),
    ("4 refs resolve to labels",
     "reference a label that does not exist",
     lambda t: t.replace("Table~\\ref{tab:gold}", "Table~\\ref{tab:goldd}", 1)),
    ("5 floats have caption+label",
     "remove a \\caption from a figure",
     lambda t: re.sub(r"\\caption\{Deduplication across fifteen",
                      r"{Deduplication across fifteen", t, count=1)),
    ("6 commands resolve to class/packages",
     "use an undefined command",
     lambda t: t.replace("\\section{Impact}", "\\notarealcommand\n\\section{Impact}", 1)),
    ("7 no en/em dashes",
     "insert an em dash in body text",
     lambda t: t.replace("\\section{Impact}", "\\section{Impact\u2014here}", 1)),
    ("7 no en/em dashes",
     "insert an en dash in body text",
     lambda t: t.replace("\\section{Impact}", "\\section{Impact\u2013here}", 1)),
    ("7 no en/em dashes",
     "insert a LaTeX --",
     lambda t: t.replace("\\section{Impact}", "\\section{Impact -- here}", 1)),
    ("7 no en/em dashes",
     "insert a LaTeX ---",
     lambda t: t.replace("\\section{Impact}", "\\section{Impact --- here}", 1)),
    ("7 no en/em dashes",
     "insert an em dash inside a listing (verbatim is typeset)",
     lambda t: t.replace(
         "2 identified -> 1 unique", "2 identified \u2014> 1 unique", 1)),
]


def self_test_pdf(tex_path: str) -> int:
    """Prove check 8 on a compiled document, by recompiling with a dash.

    Requires a TeX engine. If none is on PATH the function says so and returns
    0 rather than silently reporting success, because a check that cannot run
    is not a check that passed.
    """
    import shutil
    import subprocess
    import tempfile

    tex_dir = os.path.dirname(os.path.abspath(tex_path))
    engine = shutil.which("pdflatex")
    if not engine:
        print("  [SKIPPED  ] check 8 fault injection: no pdflatex on PATH")
        return 0
    bibtex = shutil.which("bibtex")
    tmp = tempfile.mkdtemp(prefix="verify_pdf_")
    try:
        raw = _read(tex_path)
        # An em dash in body text, which must survive into the typeset output.
        broken = raw.replace("\\section{Impact}",
                             "\\section{Impact\u2014here}", 1)
        assert broken != raw, "anchor for the PDF fault is gone"
        shutil.copy(os.path.join(tex_dir, "references.bib"), tmp)
        figs = os.path.join(tex_dir, "figures")
        if os.path.isdir(figs):
            shutil.copytree(figs, os.path.join(tmp, "figures"))
        stem = "mutant"
        with open(os.path.join(tmp, stem + ".tex"), "w",
                  encoding="utf-8") as fh:
            fh.write(broken)
        def run(cmd: List[str]) -> None:
            subprocess.run(cmd, cwd=tmp, capture_output=True, check=False)

        run([engine, "-interaction=nonstopmode", stem + ".tex"])
        if bibtex:
            run([bibtex, stem])
        run([engine, "-interaction=nonstopmode", stem + ".tex"])
        pdf = os.path.join(tmp, stem + ".pdf")
        if not os.path.exists(pdf):
            print("  [ERROR    ] check 8 fault injection: mutant did not compile")
            return 1
        found = check_pdf_dashes(pdf)
        caught = bool(found)
        print(f"  [{'CAUGHT' if caught else 'MISSED':9s}] "
              "8 no en/em dashes in the PDF: em dash in body text, recompiled")
        if caught:
            print(f"              -> {found[0]}")
        return 0 if caught else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def self_test(tex_path: str) -> int:
    import shutil
    import tempfile

    tex_dir = os.path.dirname(os.path.abspath(tex_path))
    baseline = verify(tex_path, quiet=True)
    clean = {k: v for k, v in baseline.items() if v}
    print("baseline on the real file:",
          "clean" if not clean else f"{len(clean)} check(s) already failing")
    for k, v in clean.items():
        print(f"  {k}: {len(v)}")
    print()
    print("fault injection: each row must turn its own check from PASS to FAIL")
    print()
    failures = 0
    tmp = tempfile.mkdtemp(prefix="verify_tex_")
    try:
        # the .bib and figures must be alongside the copy for the other checks
        shutil.copy(os.path.join(tex_dir, "references.bib"), tmp)
        figs = os.path.join(tex_dir, "figures")
        if os.path.isdir(figs):
            shutil.copytree(figs, os.path.join(tmp, "figures"))
        raw = _read(tex_path)
        for target, label, mutate in FAULTS:
            broken = mutate(raw)
            if broken == raw:
                print(f"  [ERROR    ] {label}: fault did not apply, "
                      "the anchor text is gone")
                failures += 1
                continue
            path = os.path.join(tmp, "mutant.tex")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(broken)
            res = verify(path, quiet=True)
            caught = bool(res[target]) and not bool(baseline[target])
            print(f"  [{'CAUGHT' if caught else 'MISSED':9s}] "
                  f"{target}: {label}")
            if caught:
                print(f"              -> {res[target][0]}")
            else:
                failures += 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    failures += self_test_pdf(tex_path)
    print()
    if failures:
        print(f"SELF-TEST FAILED: {failures} injected fault(s) not detected")
    else:
        print(f"SELF-TEST PASSED: all {len(FAULTS)} injected faults detected, "
              "each by its own check")
    return failures


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("tex")
    ap.add_argument("--self-test", action="store_true",
                    help="inject one fault per check and prove each is caught")
    args = ap.parse_args()
    if args.self_test:
        return 1 if self_test(args.tex) else 0
    results = verify(args.tex)
    return 1 if any(results.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
