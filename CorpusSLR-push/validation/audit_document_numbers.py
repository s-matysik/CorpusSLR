"""Check that every figure stated in the documentation follows from a measurement.

Three separate defects in this project's history were a number in prose that no
longer matched the code: a test count left behind by a later commit, an F1 that
did not follow from its own confusion matrix, and a speed-up extrapolated past
the size it was measured at. Prose is not covered by the test suite, so this
script covers it instead.

Checks, per document:
  1. any test count must equal the measured count on 3.13 or 3.9
  2. every markdown table row carrying TP/FP/FN + precision/recall/F1 must be
     arithmetically self-consistent
  3. the same for sentences of the form "TP a ... FP b ... FN c ... F1 d"
  4. the specification-coverage claim must match validation/parser_coverage.csv
  5. the version must agree across the metadata files

Usage:  python validation/audit_document_numbers.py    (exit 1 on any finding)
"""
import csv
import os
import re
import subprocess
import sys

import corpusslr

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: SUPPLEMENTARY.md was missing from this list until 1.7.2, which is how it
#: came to state a test count 62 cases out of date: it is submitted alongside
#: the article, so a reviewer reads it with the same eye as the manuscript.
#: PUBLISHING.md quotes the same figures in its release notes.
DOCS = ["MANUSCRIPT.md", "SUPPLEMENTARY.md", "AUDIT_REPORT.md", "CHANGELOG.md",
        "README.md", "PUBLISHING.md", "KNOWN_ISSUES.md",
        "docs/user_guide.md", "docs/api_reference.md",
        "validation/asysd_validation_report.md",
        "validation/multidomain_validation.md",
        "validation/parser_coverage.md",
        # Added after this file was found stating six references and a six-page
        # PDF against a twenty-two-entry bibliography and a seven-page article.
        # It documents the built paper, so its numbers age with every rebuild.
        "paper/README.md"]


def measured_test_counts():
    """Run the suite and return the accepted counts, rather than trusting prose."""
    # No -q: the terse reporter suppresses the "N passed" summary line, and
    # parsing an absent line is how a placeholder ended up in the changelog once.
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-p", "no:cacheprovider"],
        cwd=HERE, capture_output=True, text=True,
        env=dict(os.environ, PYTHONPATH=HERE)).stdout
    m = re.search(r"(\d+) passed", out)
    if not m:
        raise SystemExit("could not measure the test count:\n" + out[-800:])
    n = int(m.group(1))
    s = re.search(r"(\d+) skipped", out)
    accepted = {n, n - (int(s.group(1)) if s else 0), n - 3, n + 3}

    # A source distribution does not package .gitignore or .github/workflows,
    # so tests/test_publishing.py skips there and the passed-count is lower
    # than the repository's. Documents legitimately quote that second figure,
    # so it has to be measured too rather than flagged as disagreeing. The
    # count is read from the collected node ids that would skip, which is
    # cheap and does not need an sdist built on the spot.
    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_publishing.py",
         "-p", "no:cacheprovider", "--collect-only", "-q"],
        cwd=HERE, capture_output=True, text=True,
        env=dict(os.environ, PYTHONPATH=HERE)).stdout
    # Accepting a window below the repository count would weaken the rule to
    # the point of uselessness, so the second figure is measured rather than
    # bounded: the suite is run against a copy that lacks exactly what a
    # source distribution lacks. That reproduces the sdist condition without
    # building one.
    accepted |= _sdist_counts()
    accepted |= _optional_absent_counts()
    return accepted


def _optional_absent_counts():
    """Counts from a run where the optional libraries cannot be imported.

    The 3.9 environment has no python-docx and no PyYAML, so its pass count is
    lower than 3.13's and the documents state both. Rather than widening the
    tolerance until the difference fits - which would stop the rule catching
    anything - the second figure is measured here by making those imports
    fail, which reproduces that environment's condition on this interpreter.
    """
    import tempfile

    tmp = tempfile.mkdtemp(prefix="audit-optional-")
    try:
        for name in ("docx", "yaml"):
            with open(os.path.join(tmp, name + ".py"), "w",
                      encoding="utf-8") as fh:
                # ModuleNotFoundError, not a bare ImportError: pytest's
                # importorskip deliberately re-raises the latter so a broken
                # installation is not silently skipped, which would abort
                # collection instead of reproducing an absent library.
                fh.write("raise ModuleNotFoundError("
                         "'made unavailable by audit_document_numbers.py')\n")
        out = subprocess.run(
            [sys.executable, "-m", "pytest", "tests", "-p", "no:cacheprovider"],
            cwd=HERE, capture_output=True, text=True,
            env=dict(os.environ, PYTHONPATH=tmp + os.pathsep + HERE)).stdout
        m = re.search(r"(\d+) passed", out)
        if not m:
            return set()
        n = int(m.group(1))
        s = re.search(r"(\d+) skipped", out)
        return {n, n + (int(s.group(1)) if s else 0), n - 3, n + 3}
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def _test_function_count():
    """How many test FUNCTIONS the suite defines, which is not its case count.

    The supplement quotes both: 1354 functions collect into 2114 cases once
    parametrisation is expanded. Accepting the function count as a literal
    would blind the rule to a stale case count in the same sentence, so it is
    measured from the generator that writes the inventory rather than allowed
    as a magic number.
    """
    out = subprocess.run(
        [sys.executable, os.path.join(HERE, "validation",
                                      "measure_test_inventory.py")],
        cwd=HERE, capture_output=True, text=True,
        env=dict(os.environ, PYTHONPATH=HERE)).stdout
    m = re.search(r"(\d+) test functions", out)
    return {int(m.group(1))} if m else set()


def _sdist_counts():
    """Counts from a tree stripped of what a source distribution omits."""
    import shutil
    import tempfile

    tmp = tempfile.mkdtemp(prefix="audit-sdist-")
    try:
        root = os.path.join(tmp, "pkg")
        shutil.copytree(
            HERE, root,
            ignore=shutil.ignore_patterns(
                "__pycache__", ".mypy_cache", ".ruff_cache", ".venv", "dist",
                "build_check", "reviewer_package", "site", ".git",
                # the two paths a source distribution does not package
                ".gitignore", ".github"))
        out = subprocess.run(
            [sys.executable, "-m", "pytest", "tests", "-p", "no:cacheprovider"],
            cwd=root, capture_output=True, text=True,
            env=dict(os.environ, PYTHONPATH=root)).stdout
        m = re.search(r"(\d+) passed", out)
        if not m:
            return set()
        n = int(m.group(1))
        s = re.search(r"(\d+) skipped", out)
        return {n, n - 3, n + int(s.group(1)) if s else n}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def spec_coverage():
    path = os.path.join(HERE, "validation", "parser_coverage.csv")
    with open(path, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return sum(1 for r in rows if r["status"] == "covered"), len(rows)


def _na_literal_dois():
    """(records whose DOI field is a missing-value literal, total) in the gold set.

    Counted from `validation/labelled_test_set.csv` itself, because the figure
    quoted in the manuscript is a property of that file, not a cell in any
    metrics table.
    """
    path = os.path.join(HERE, "validation", "labelled_test_set.csv")
    if not os.path.exists(path):
        return (0, 0)
    markers = {"NA", "N/A", "NULL", "NONE", "-", ""}
    n = total = 0
    with open(path, encoding="utf-8", errors="replace") as fh:
        for row in csv.DictReader(fh):
            total += 1
            if (row.get("doi") or "").strip().upper() in markers:
                n += 1
    return (n, total)


def _worst_doi_coverage():
    """(discipline, coverage %) with the lowest DOI coverage across all tracks."""
    worst = None
    for name in sorted(os.listdir(os.path.join(HERE, "validation"))):
        if not (name.startswith("domains_") and name.endswith("_metrics.csv")):
            continue
        with open(os.path.join(HERE, "validation", name),
                  encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row.get("level") != "domain":
                    continue
                try:
                    cov = float(row["doi_coverage"])
                except (KeyError, TypeError, ValueError):
                    continue
                if cov <= 1.0:            # a fraction, not a percentage
                    cov *= 100.0
                if worst is None or cov < worst[1]:
                    worst = (row["domain"].strip().lower(), cov)
    return worst


def _corpus_sizes_pair():
    """Return (harvested, evaluated) record counts from the metrics file.

    The multidomain study reports two corpus sizes and confusing them was a real
    error in this project's history: 7,440 records were harvested, 7,187 entered
    the evaluation after document-type curation, and the accuracy figures belong
    to the smaller number. Both are read from the file rather than restated here.
    """
    path = os.path.join(HERE, "validation", "multidomain_metrics.csv")
    if not os.path.exists(path):
        return None, None
    with open(path, encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r.get("level") == "domain"]
    by_arm = {}
    for r in rows:
        try:
            by_arm[r["arm"]] = by_arm.get(r["arm"], 0) + int(float(r["n_records"]))
        except (TypeError, ValueError):
            continue
    harvested = by_arm.get("raw")
    evaluated = by_arm.get("curated") or by_arm.get("pseudopages_fixed")
    return harvested, evaluated


#: Number words the paper documentation uses in prose ("Six references").
_WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
            "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
            "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
            "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
            "twenty": 20, "twenty-two": 22}


def _paper_facts():
    """Measure the figures paper/README.md states about the built article.

    These drifted unnoticed for several releases because the file was not in
    DOCS: it claimed six references and a six-page PDF long after the
    bibliography had grown to twenty-two and the article to seven pages. Each
    value below is read from the artefact it describes, so the claim cannot
    outlive the thing it claims about.
    """
    facts = {}
    bib = os.path.join(HERE, "paper", "references.bib")
    if os.path.exists(bib):
        with open(bib, encoding="utf-8") as fh:
            facts["bib_entries"] = len(re.findall(r"^@", fh.read(), re.M))

    # Page count from the committed PDF, standard library only. pdflatex emits
    # the page tree inside compressed object streams, so a regex over the raw
    # bytes finds nothing; inflating the streams first is what makes this
    # measurable without a TeX installation or a third-party PDF reader.
    pdf = os.path.join(HERE, "paper", "corpusslr_softwarex.pdf")
    if os.path.exists(pdf):
        import zlib
        with open(pdf, "rb") as fh:
            raw = fh.read()
        pages = 0
        for m in re.finditer(rb"stream\r?\n", raw):
            end = raw.find(b"endstream", m.end())
            try:
                data = zlib.decompress(raw[m.end():end])
            except Exception:
                continue
            pages += len(re.findall(rb"/Type\s*/Page[^s]", data))
        if pages:
            facts["pdf_pages"] = pages

    counter = os.path.join(HERE, "paper", "count_words.py")
    tex = os.path.join(HERE, "paper", "corpusslr_softwarex.tex")
    if os.path.exists(counter) and os.path.exists(tex):
        out = subprocess.run([sys.executable, counter, tex], cwd=HERE,
                             capture_output=True, text=True).stdout
        m = re.search(r"MAIN TEXT:\s*([\d,]+)\s*words", out)
        if m:
            facts["main_words"] = int(m.group(1).replace(",", ""))
        m = re.search(r"margin\s*([+-])\s*(\d+)\s*words", out)
        if m:
            facts["margin"] = int(m.group(2)) * (1 if m.group(1) == "+" else -1)

    # The self-test's fault count is the length of its own table, so reading
    # the table beats re-running a LaTeX compile inside the audit.
    verifier = os.path.join(HERE, "paper", "verify_tex.py")
    if os.path.exists(verifier):
        with open(verifier, encoding="utf-8") as fh:
            src = fh.read()
        m = re.search(r"^FAULTS\s*=\s*\[", src, re.M)
        if m:
            depth, j = 1, m.end()
            while depth and j < len(src):
                depth += (src[j] == "[") - (src[j] == "]")
                j += 1
            entries = re.split(r"\n {4}\(", src[m.end():j])[1:]
            facts["faults"] = len(entries)
            # The prose distinguishes the faults injected into the SOURCE from
            # the one that recompiles the document to test the PDF check, so
            # the two counts are measured separately rather than conflated.
            facts["source_faults"] = sum(
                1 for e in entries
                if not re.search(r"pdf|typeset|recompil", e, re.I))
    return facts


def _f1(p, r):
    return 2 * p * r / (p + r) if p + r else 0.0


def audit():
    accepted = measured_test_counts()
    _TEST_FUNCTIONS = _test_function_count()
    covered, total = spec_coverage()
    paper = _paper_facts()
    problems = []

    def _num(token):
        """A count written either as digits or as an English number word."""
        token = token.strip().lower().replace(",", "")
        if token.isdigit():
            return int(token)
        return _WORDNUM.get(token)
    for rel in DOCS:
        path = os.path.join(HERE, rel)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            txt = fh.read()

        # Claims about the built article, checked against the article. Each
        # pattern accepts a digit or a number word, because this prose says
        # "Six references" and "Twelve faults" rather than "6" and "12".
        _PAPER_RULES = (
            (r"\b([\w-]+|\d+)\s+references\b(?![_/])", "bib_entries",
             "bibliography entries"),
            (r"\b([\w-]+|\d+)\s+entries\s+written\s+to\s+the\s+\\?\.?bbl",
             "bib_entries", "entries in the .bbl"),
            # "N pages" is ambiguous in this repository: the generated
            # documentation site also has a page count, and an earlier version
            # of this rule reported the site's correct "8 pages" as a stale PDF
            # claim. The context decides, so the match is kept only when the
            # surrounding text is about the article and not about the site.
            (r"\b([\w-]+|\d+)\s+pages\b", "pdf_pages", "pages in the PDF"),
            # Markdown emphasis sits between the number and its noun
            # ("**2656 words** of main text"), which is how this claim survived
            # the first version of the rule.
            (r"\b([\d,]+)\**\s+words\**\s+of\s+main\s+text", "main_words",
             "main-text words"),
            (r"margin\s+of\**\s*([\d,]+)\s*\**\s+words", "margin",
             "word-count margin"),
            (r"\b([\w-]+|\d+)\s+faults\s+are\s+injected\s+into\s+the\s+source",
             "source_faults", "faults injected into the source"),
            (r"all\s+([\w-]+|\d+)\s+injected\s+faults", "faults",
             "injected faults in total"),
        )
        for pattern, key, what in _PAPER_RULES:
            if key not in paper:
                continue
            for m in re.finditer(pattern, txt, re.I):
                stated = _num(m.group(1))
                if stated is None or stated == paper[key]:
                    continue
                if _historical(m.start()):
                    continue
                if key == "pdf_pages":
                    window = txt[max(0, m.start() - 120):m.end() + 120].lower()
                    about_site = re.search(r"build_site|site/|html|witryn", window)
                    about_paper = re.search(r"pdf|article|artyku|pdflatex|"
                                            r"compiled|bibtex", window)
                    if about_site or not about_paper:
                        continue
                problems.append((rel, what, m.group(0).strip()[:52],
                                 "{} vs measured {}".format(stated, paper[key])))

        # A count is a count whether or not the word "test" sits next to it.
        # The first version of this check required that word, so
        # "1419 przechodzących i zero pominięć" -- a suite result phrased with a
        # verb instead of a noun -- stayed stale through a clean audit run. Match
        # the outcome vocabulary too, in both languages.
        # A changelog necessarily records what WAS true at each past release, so
        # its historical entries cannot be held against today's measurement --
        # rewriting them would falsify the release history. A line marked "at
        # that release" (or its Polish equivalent) is therefore exempt, and only
        # such an explicit marker exempts it: an unmarked stale count is still
        # an error, which is what this rule exists to catch.
        # "previously stated" marks a figure the text is CORRECTING: a changelog
        # entry that records a documentation error has to quote the wrong value
        # to be useful, and flagging that quotation as a stale claim would make
        # the error unrecordable. As with "at that release", only the explicit
        # marker exempts the line; an unmarked wrong number is still an error.
        _HISTORICAL = re.compile(r"at that release|w tym wydaniu|w chwili wydania"
                                 r"|previously stated|wcześniej podawano", re.I)

        # In a changelog, position is itself the marker: a figure inside the
        # section for a PAST release states what was true then, and rewriting
        # it would falsify the release history. Requiring an explicit "at that
        # release" phrase on every such line was the earlier rule, and it
        # flagged correct history as stale, because release notes are written
        # in the present tense of their own release. Only the section for the
        # CURRENT version, and text before the first version heading, are held
        # against today's measurement.
        _VERSION_HEADING = re.compile(r"^##\s*\[?([0-9]+\.[0-9]+\.[0-9]+)\]?",
                                      re.M)
        _sections = [(m.start(), m.group(1)) for m in
                     _VERSION_HEADING.finditer(txt)]

        def _released_version_at(pos):
            """The version whose section contains pos, or None."""
            current = None
            for start, version in _sections:
                if start <= pos:
                    current = version
                else:
                    break
            return current

        def _historical(pos):
            start = txt.rfind("\n", 0, pos) + 1
            end = txt.find("\n", pos)
            line = txt[start:end if end > 0 else len(txt)]
            if _HISTORICAL.search(line):
                return True
            if rel != "CHANGELOG.md":
                return False
            # Everything under the pre-release marker is history by definition:
            # those milestones were never published, their figures were correct
            # for the code at the time, and the version numbers they carry are
            # higher than the released one, so a section-name comparison alone
            # would not exempt them.
            marker = txt.find("## Pre-release development history")
            if marker >= 0 and pos > marker:
                return True
            section = _released_version_at(pos)
            return section is not None and section != corpusslr.__version__

        # The noun may be separated from the number by markdown emphasis
        # and by a line break: "collects **2114**\ncases" is one claim,
        # and reading only to the end of the line missed it entirely.
        for m in re.finditer(
                r"([\d,]{3,6})\**[ \u00a0\n]*(?:offline[ \u00a0]+)?"
                r"(?:tests?|testów|testy|cases?|przechodzi\w*|przeszł\w+|"
                r"pass\w*|passed|failed|skipped|pomini\w+)", txt):
            v = int(m.group(1).replace(",", ""))
            phrase = m.group(0).strip()
            # "N test functions" is a different measurement from "N passed";
            # each is checked against its own measured value. The keyword
            # pattern stops at "test", so the noun that follows has to be read
            # from the text after the match rather than from the match itself.
            tail = txt[m.end():m.end() + 24]
            pool = (accepted | _TEST_FUNCTIONS
                    if re.match(r"\s*functions?\b", tail) else accepted)
            if v > 900 and v not in pool and not _historical(m.start()):
                problems.append((rel, "test count", phrase, v))

        # A number that shares a sentence with the vocabulary of a suite result
        # is a suite result, whatever noun follows it. This catches the phrasing
        # the keyword rule missed ("1419 przechodzących i zero pominięć") without
        # flagging corpus sizes, page ranges, DOI fragments or default arguments,
        # which a bare four-digit sweep produced by the dozen.
        _RESULT_CTX = re.compile(
            r"pomini\w+|skip|zestaw|suite|sdist|xfail|"
            r"przechodz\w*|przeszł\w+|pass(?:es|ed|ing)?\b|zielon\w+", re.I)
        for m in re.finditer(r"(?<![\d.,/-])([1-9]\d{3})(?![\d.,%/-])", txt):
            v = int(m.group(1))
            if v in accepted or v in _TEST_FUNCTIONS:
                continue
            # This window stays line-scoped on purpose: widening it to the
            # paragraph made statement counts, publication years and pair
            # counts that merely share a paragraph with the word "passed" look
            # like suite results. The adjacency rule above is what catches a
            # wrapped claim, because it reads the noun that follows the number
            # across the line break rather than guessing from context.
            start = txt.rfind("\n", 0, m.start()) + 1
            end = txt.find("\n", m.end())
            line = txt[start:end if end > 0 else len(txt)]
            if not _RESULT_CTX.search(line) or _historical(m.start()):
                continue
            # A number introduced by a comparison or an assignment is a limit or
            # a default, not a result: "start+count <= 5000", "max_results=1000".
            before = txt[max(0, m.start() - 12):m.start()]
            if re.search(r"(?:<=|>=|<|>|=|≤|≥)\s*$", before):
                continue
            problems.append((rel, "suite result disagreeing with the measurement",
                             line.strip()[:72], v))

        # Column positions are read from each table's own header, not assumed.
        # Fixing the layout to "two integers then P|R|F1" skipped seven-column
        # tables entirely; matching the last three numbers instead produced false
        # alarms on tables laid out TP|TN|FN|FP or "before | after". The header
        # names the columns, so use it.
        for tbl in re.finditer(r"^(\|[^\n]*\|)\n\|[\s:|-]+\|\n((?:\|[^\n]*\|\n)+)",
                               txt, re.M):
            head = [c.strip().strip("*").lower()
                    for c in tbl.group(1).strip().strip("|").split("|")]
            def _col(*names):
                for i, h in enumerate(head):
                    if any(h == n or h.startswith(n + " ") for n in names):
                        return i
                return None
            ip = _col("precision", "precyzja")
            ir = _col("recall", "czułość", "czulosc")
            if_ = _col("f1")
            if None in (ip, ir, if_):
                continue
            for line in tbl.group(2).strip().split("\n"):
                cells = [c.strip().strip("*") for c in line.strip().strip("|").split("|")]
                if max(ip, ir, if_) >= len(cells):
                    continue
                try:
                    p_, r_, f_ = (float(cells[i].replace(",", "."))
                                  for i in (ip, ir, if_))
                except ValueError:
                    continue
                if abs(_f1(p_, r_) - f_) > 1.1e-3:
                    problems.append((rel, "F1 vs precision/recall",
                                     line.strip()[:52],
                                     "{} vs {:.4f}".format(f_, _f1(p_, r_))))

        for m in re.finditer(r"TP[ =:]*(\d+)[^\n]{0,40}?FP[ =:]*(\d+)"
                             r"[^\n]{0,40}?FN[ =:]*(\d+)[^\n]{0,60}?"
                             r"F1[ =:]*([01][.,]\d+)", txt):
            tp, fp, fn = (int(m.group(i)) for i in (1, 2, 3))
            f_ = float(m.group(4).replace(",", "."))
            p_ = tp / (tp + fp) if tp + fp else 1.0
            r_ = tp / (tp + fn) if tp + fn else 1.0
            if abs(_f1(p_, r_) - f_) > 1.1e-3:
                problems.append((rel, "F1 vs confusion matrix",
                                 m.group(0).strip()[:52],
                                 "{} vs {:.4f}".format(f_, _f1(p_, r_))))

        # Corpus size: the multidomain study harvested 7,440 records and
        # evaluated 7,187 after document-type curation dropped 253. Quoting the
        # harvested figure as the size a metric was computed on overstates it by
        # 3.4 %, which is exactly the error this rule exists to catch: any
        # sentence naming a corpus size next to a metric must say which arm it
        # means. Sizes are read from the metrics file, never hard-coded here.
        harvested, evaluated = _corpus_sizes_pair()
        if harvested and evaluated and harvested != evaluated:
            for m in re.finditer(r"(?<![\d.,])([\d][\d  ,]{2,7})\s*"
                                 r"(?:records|rekord\w*|rows)", txt):
                raw = m.group(1).replace(",", "").replace(" ", "").replace("\u00a0", "")
                if not raw.isdigit():
                    continue
                v = int(raw)
                if v not in (harvested, evaluated):
                    continue
                # Context is the surrounding SENTENCE, not the surrounding line:
                # markdown wraps, and the first version of this rule missed the
                # very error it was written for because "precyzja" sat one line
                # above the corpus size it qualified.
                w0 = max(0, m.start() - 320)
                w1 = min(len(txt), m.end() + 200)
                window = " ".join(txt[w0:w1].split())
                line_start = txt.rfind("\n", 0, m.start()) + 1
                line_end = txt.find("\n", m.end())
                line = txt[line_start:line_end if line_end > 0 else len(txt)]
                # A bare size is fine; a size next to a metric must disambiguate.
                near_metric = re.search(r"precyzj|precision|czułoś|recall|\bF1\b|"
                                        r"measured|zmierzon", window, re.I)
                # Word boundaries matter here: an unanchored "raw" matches
                # inside unrelated words and silently cleared the very sentence
                # this rule was written to catch. The qualifier must be a word.
                disambiguated = re.search(
                    r"\b(pobran\w*|harvested|ocenian\w*|evaluated|cached|raw|"
                    r"surow\w*)\b|po kuracji|after \w+ curation", window, re.I)
                if near_metric and not disambiguated:
                    problems.append((rel, "corpus size not attributed to an arm",
                                     line.strip()[:70],
                                     "{} harvested vs {} evaluated".format(
                                         harvested, evaluated)))

        for m in re.finditer(r"(\d+)\s*(?:of|/|z)\s*(\d+)\s*(?:items|pozycj)", txt):
            a, b = int(m.group(1)), int(m.group(2))
            if b in (31, 32, 33) and (a, b) != (covered, total):
                problems.append((rel, "spec coverage", m.group(0).strip(),
                                 "{}/{} measured {}/{}".format(a, b, covered, total)))

        # Two figures quoted in prose that no other rule reaches, because they
        # are counts over a source file rather than cells in a metrics table.
        # They were once "verified" by a hardcoded True in a throwaway cell,
        # which checks nothing; both are now recomputed from the data on every
        # run.
        na_count, na_total = _na_literal_dois()
        if na_count:
            for m in re.finditer(r"(\d[\d,]*)\s+of\s+(\d[\d,]*)\s+records\s*"
                                 r"\(([\d.]+)\s*%\)\s*shared the key", txt):
                a = int(m.group(1).replace(",", ""))
                b = int(m.group(2).replace(",", ""))
                pct = float(m.group(3))
                if (a, b) != (na_count, na_total) or \
                        abs(pct - 100.0 * na_count / na_total) > 0.05:
                    problems.append((rel, "missing-value DOI count",
                                     m.group(0).strip()[:52],
                                     "measured {}/{} ({:.1f} %)".format(
                                         na_count, na_total,
                                         100.0 * na_count / na_total)))

        worst = _worst_doi_coverage()
        if worst:
            name, cov = worst
            for m in re.finditer(r"(\w[\w ]*), with the weakest DOI coverage at "
                                 r"([\d.]+)\s*%", txt):
                if m.group(1).strip().lower() != name or \
                        abs(float(m.group(2)) - cov) > 0.06:
                    problems.append((rel, "weakest DOI coverage",
                                     m.group(0).strip()[:52],
                                     "measured {} at {:.2f} %".format(name, cov)))
    return problems


if __name__ == "__main__":
    found = audit()
    if not found:
        print("all stated figures agree with their measurements")
        raise SystemExit(0)
    for rel, kind, snippet, detail in found:
        print("{}: {} -- {!r} ({})".format(rel, kind, snippet, detail))
    raise SystemExit(1)
