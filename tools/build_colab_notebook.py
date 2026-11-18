"""Generate ``notebooks/corpusslr_colab.ipynb``.

The notebook is a build product rather than a hand-edited file for one
reason: a notebook that has been *run* carries its outputs, and an output cell
is exactly where a pasted API key would end up if anyone ever executed the
key cell and saved. Generating it guarantees ``outputs == []`` and
``execution_count == null`` in every code cell, and lets the same script
compile every cell before writing, so a notebook that ships cannot contain a
syntax error.

Run from the repository root:

    PYTHONPATH=. python tools/build_colab_notebook.py
"""
from __future__ import annotations

import json
import os
import sys

NOTEBOOK = os.path.join("notebooks", "corpusslr_colab.ipynb")


def md(*lines: str) -> dict:
    return {"cell_type": "markdown", "metadata": {},
            "source": _source(lines)}


def code(*lines: str) -> dict:
    return {"cell_type": "code", "metadata": {}, "execution_count": None,
            "outputs": [], "source": _source(lines)}


def _source(lines):
    """nbformat stores source as a list of lines each ending in \\n."""
    text = "\n".join(lines)
    out = [ln + "\n" for ln in text.split("\n")]
    if out:
        out[-1] = out[-1].rstrip("\n")
    return out


CELLS = [
    md(
        "# CorpusSLR: a systematic review from one query",
        "",
        "This notebook runs a complete, PRISMA-documented literature search.",
        "You edit one cell -- the databases, the query and the years -- and",
        "run the cells from top to bottom. Nothing else needs changing.",
        "",
        "**What you will have at the end**",
        "",
        "| File | What it is for |",
        "|---|---|",
        "| `corpus_scopus.csv` | the deduplicated corpus in Scopus column"
        " format -- opens in bibliometrix, VOSviewer and EmbedSLR without"
        " conversion |",
        "| `screening.csv` | titles and abstracts for ASReview, Rayyan or a"
        " spreadsheet |",
        "| `prisma_s_appendix.md` | the search-reporting appendix (PRISMA-S)"
        " |",
        "| `prisma2020_flow.svg` | the PRISMA 2020 flow diagram |",
        "| `dedup_report.csv` | every duplicate decision and the rule that"
        " made it |",
        "| `review.json` | the search strategy as data -- deposit this and"
        " anyone can rerun your search |",
        "",
        "**About API keys.** Scopus and Web of Science need a key from your",
        "library. This notebook asks for keys with `getpass`, which does not",
        "echo what you type and does not store it in the notebook file. Never",
        "type a key directly into a cell: a saved notebook keeps cell text and",
        "cell outputs, and both end up in your Drive and in anything you",
        "share. Everything else here works with no key at all, so you can run",
        "a real review without any subscription.",
    ),
    md(
        "## 1. Install CorpusSLR",
        "",
        "CorpusSLR depends only on `requests`, which Colab already has, so",
        "this is quick and cannot break the rest of your environment.",
        "Run the cell and wait for `installed:` to appear. The cell tries the",
        "release archive first and the git repository second; if neither is",
        "reachable it says so and tells you how to install from a local copy,",
        "instead of failing later with a bare import error.",
    ),
    code(
        "# Step 1: install the package.",
        "#",
        "# Two sources are tried: the release archive, which needs no git, and",
        "# then the git repository at the same tag. The package is deliberately",
        "# NOT installed by name from the package index: it is not published",
        "# there, and 'pip install corpusslr' would install whatever project",
        "# happens to hold that name.",
        "import subprocess",
        "import sys",
        "",
        "SOURCES = ['https://github.com/s-matysik/CorpusSLR/archive/refs/tags/v1.2.0.zip',",
        "           'git+https://github.com/s-matysik/CorpusSLR.git@v1.2.0']",
        "",
        "",
        "def install(spec):",
        "    done = subprocess.run([sys.executable, '-m', 'pip', 'install',",
        "                           '--quiet', spec],",
        "                          capture_output=True, text=True)",
        "    return done.returncode == 0",
        "",
        "",
        "if not any(install(s) for s in SOURCES):",
        "    raise SystemExit(",
        "        'Could not install corpusslr from the release archive or from the '",
        "        'repository.\\n'",
        "        'If you have the source tree (for example unzipped in Drive), '",
        "        'install from that copy instead, by running '",
        "        'pip install /content/corpusslr in a new cell.\\n'",
        "        'Otherwise use the repository or archive address given in the '",
        "        'code metadata table of the accompanying article.')",
        "",
        "import corpusslr",
        "print('installed:', corpusslr.__version__)",
    ),
    md(
        "## 2. Say who you are (an email address)",
        "",
        "Crossref, PubMed and OpenAlex ask automated clients to identify",
        "themselves with a contact address, and they throttle anonymous",
        "clients harder. This is politeness, not authentication: the address",
        "is sent in a request header and is not a credential. It is kept in",
        "this session only.",
    ),
    code(
        "# Step 2: contact address for the polite request header.",
        "import os",
        "",
        "email = input('Your email address (Enter to skip): ').strip()",
        "if email:",
        "    os.environ['CORPUSSLR_CONTACT_EMAIL'] = email",
        "    print('Will identify requests as:', email)",
        "else:",
        "    print('No address set. The free databases still work, just with '",
        "          'a lower rate limit.')",
    ),
    md(
        "## 3. API keys, typed hidden",
        "",
        "Run this cell only if you have a Scopus or Web of Science key. Press",
        "Enter to skip either one -- skipping is normal and nothing will",
        "break.",
        "",
        "`getpass` hides what you type, so the key never appears on screen,",
        "never in the notebook's saved text, and never in a cell output. The",
        "value lives in this session's memory and disappears when the runtime",
        "is recycled.",
        "",
        "*Off campus?* An Elsevier key is tied to your institution's IP range;",
        "from outside it also needs an institutional token (`SCOPUS_INSTTOKEN`",
        "below). Ask your library for both.",
    ),
    code(
        "# Step 3: API keys. Nothing typed here is echoed or saved.",
        "import getpass",
        "import os",
        "",
        "SLOTS = [",
        "    ('SCOPUS_API_KEY', 'Scopus API key'),",
        "    ('SCOPUS_INSTTOKEN', 'Scopus institutional token (off campus)'),",
        "    ('WOS_API_KEY', 'Web of Science API key'),",
        "]",
        "",
        "for variable, label in SLOTS:",
        "    value = getpass.getpass('{} (Enter to skip): '.format(label))",
        "    value = (value or '').strip()",
        "    if value:",
        "        os.environ[variable] = value",
        "",
        "# Presence only -- the values themselves are never printed.",
        "for variable, label in SLOTS:",
        "    state = 'set' if os.environ.get(variable) else 'not set'",
        "    print('{:<20} {:<9} {}'.format(variable, state, label))",
    ),
    md(
        "## 4. Choose the databases and write the query",
        "",
        "No single database covers a field. PRISMA-S (Rethlefsen et al.,",
        "2021) expects a review to name every database it searched, and",
        "Gusenbauer & Haddaway (2020) distinguish *principal* search systems,",
        "which can carry a review on their own (Scopus, Web of Science,",
        "PubMed), from *supplementary* ones that should be added on top rather",
        "than used instead. `list_databases()` shows what is available and",
        "marks which need a key.",
        "",
        "A CorpusSLR query is a set of **blocks**. Inside a block the terms are",
        "alternatives joined with OR; the blocks are then joined with AND.",
        "This is the three-block pattern reviewers are expected to report --",
        "what the technology is, what it does, where it is applied. The blocks",
        "below mean `(artificial intelligence OR machine learning) AND",
        "(adoption OR acceptance) AND (small business OR SME)`.",
        "",
        "Writing the query once and letting CorpusSLR translate it into each",
        "database's own syntax removes the most common methodological problem",
        "in multi-database searching: a query that quietly means something",
        "different in every interface.",
        "",
        "**This is the only cell you edit.** Change the databases, the blocks",
        "and the years, then run it.",
    ),
    code(
        "# Step 4: the databases, the query, the years.",
        "from corpusslr.notebook import (download_results, list_databases,",
        "                                make_config, read_summary, run_review,",
        "                                show_appendix, show_queries,",
        "                                write_scopus_csv)",
        "",
        "list_databases()",
        "",
        "databases = ['crossref', 'pubmed', 'openalex']",
        "blocks = [['artificial intelligence', 'machine learning'],",
        "          ['adoption', 'acceptance'],",
        "          ['small business', 'SME']]",
        "years = (2018, 2025)      # or None for no limit",
    ),
    md(
        "## 5. Build the search strategy file",
        "",
        "Everything you have chosen now becomes one JSON file. This file is",
        "the reproducible artefact of your review: it holds the query, the",
        "database list, the year window and every deduplication parameter, and",
        "it holds **no credentials** -- keys are read from the environment, by",
        "design, so the file is safe to deposit as supplementary material.",
        "",
        "Anyone with the file can rerun your entire search with one command:",
        "`corpusslr run -c review.json`. That is what makes the search",
        "*repeatable* in the PRISMA-S sense (Item 8) rather than merely",
        "described.",
    ),
    code(
        "# Step 5: validate the query and write review.json.",
        "config, config_path = make_config(blocks, databases, years=years)",
    ),
    md(
        "## 6. See the plan before anything is retrieved",
        "",
        "This shows the query exactly as each database will receive it, in that",
        "database's own syntax, and nothing is sent anywhere. Two reasons to",
        "read it carefully:",
        "",
        "1. These strings are what PRISMA-S Item 8 asks you to publish -- the",
        "   full search strategies *as run*. Copy them into your methods",
        "   section.",
        "2. Filters some APIs cannot express are listed too. A limit that the",
        "   API silently drops must be applied during screening instead, and",
        "   said so in the appendix.",
    ),
    code(
        "# Step 6: dry run -- compiles the query, retrieves nothing.",
        "show_queries(config)",
    ),
    md(
        "## 7. Run the search",
        "",
        "Now the retrieval happens. This can take several minutes: the",
        "databases are rate-limited on purpose and CorpusSLR respects their",
        "limits rather than hammering them.",
        "",
        "What happens in this one step, in order: every database is queried;",
        "missing abstracts are recovered from Crossref and PubMed; duplicates",
        "are removed by a cascade that matches identifiers first and then title",
        "similarity with a year tolerance, recording which rule removed which",
        "record; the PRISMA 2020 flow diagram and the PRISMA-S appendix are",
        "generated from the actual counts; and the export files are written.",
        "",
        "A database without a key is skipped and recorded as a gap in the run",
        "summary, instead of stopping the whole review. That is deliberate: a",
        "missing subscription should not cost you the databases you *can*",
        "reach, but it must be visible in the report.",
    ),
    code(
        "# Step 7: run the review. Progress appears below; be patient.",
        "exit_code = run_review(config_path)",
    ),
    md(
        "## 8. What the numbers say",
        "",
        "The run summary is the audit trail: how many records each database",
        "contributed, how many duplicates were removed and by which rule, and",
        "the configuration checksum that ties these numbers to this exact",
        "search strategy. Report the identified and unique totals in your",
        "PRISMA diagram.",
    ),
    code(
        "# Step 8: the counts, read back from the run summary.",
        "summary = read_summary()",
    ),
    md(
        "## 9. The canonical export: Scopus CSV",
        "",
        "After deduplication the corpus is written in the **Scopus CSV column",
        "layout**. That is the format bibliometrix, VOSviewer and EmbedSLR all",
        "read without conversion, so using it as the hand-off means no renaming",
        "step that none of those tools document. The writer is `to_scopus_csv`.",
    ),
    code(
        "# Step 9: write corpus_scopus.csv.",
        "scopus_path = write_scopus_csv()",
    ),
    md(
        "## 10. The PRISMA-S appendix",
        "",
        "PRISMA-S is the search-reporting extension to PRISMA: it asks for the",
        "databases and platforms, the full strategies as run, the date of the",
        "search, any limits applied and how duplicates were handled. CorpusSLR",
        "generates the appendix from the run itself, so the appendix cannot",
        "drift out of agreement with what was actually searched.",
        "",
        "Read it, add the parts only you know (the protocol registration, peer",
        "review of the strategy) and submit it as supplementary material.",
    ),
    code(
        "# Step 10: the PRISMA-S appendix.",
        "appendix = show_appendix()",
    ),
    md(
        "## 11. Download everything",
        "",
        "This packs the output folder into one zip and downloads it to your",
        "computer. Colab deletes the runtime's files when the session ends, so",
        "**do not skip this step** -- an unsaved corpus is a search you have to",
        "run again.",
        "",
        "Outside Colab (Jupyter on your own machine) the download call is",
        "skipped and the zip is simply left in the folder.",
    ),
    code(
        "# Step 11: zip the results and download them.",
        "archive = download_results()",
    ),
    md(
        "## What to do next",
        "",
        "1. **Screen** `screening.csv` in ASReview, Rayyan or a spreadsheet,",
        "   with two reviewers where your protocol requires it.",
        "2. **Record your screening counts** in `review.json` under",
        "   `screening` -- how many records you excluded, how many full texts",
        "   you could not retrieve, how many studies you included. Rerun",
        "   `corpusslr prisma` and the flow diagram becomes the complete PRISMA",
        "   2020 figure rather than only its identification stage.",
        "3. **Deposit** `review.json`, `run_summary.json`,",
        "   `prisma_s_appendix.md` and `dedup_report.csv`. Together they let a",
        "   reader repeat your search and recompute every number you report --",
        "   which is the whole point.",
        "",
        "Prefer a terminal? The same review runs as a guided menu with",
        "`corpusslr tui`, or from a configuration file with",
        "`corpusslr run -c review.json`.",
    ),
]


def build() -> dict:
    return {
        "cells": CELLS,
        "metadata": {
            "colab": {"provenance": [], "toc_visible": True},
            "kernelspec": {"display_name": "Python 3",
                           "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 0,
    }


def main() -> int:
    notebook = build()
    failures = []
    for i, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] != "code":
            continue
        source = "".join(cell["source"])
        try:
            compile(source, "<cell {}>".format(i), "exec")
        except SyntaxError as exc:
            failures.append((i, exc))
    if failures:
        for i, exc in failures:
            sys.stderr.write("cell {}: {}\n".format(i, exc))
        return 1
    os.makedirs(os.path.dirname(NOTEBOOK), exist_ok=True)
    with open(NOTEBOOK, "w", encoding="utf-8") as fh:
        json.dump(notebook, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    code_cells = sum(1 for c in notebook["cells"]
                     if c["cell_type"] == "code")
    sys.stdout.write("{}: {} cells ({} code, {} markdown)\n".format(
        NOTEBOOK, len(notebook["cells"]), code_cells,
        len(notebook["cells"]) - code_cells))
    return 0


if __name__ == "__main__":
    sys.exit(main())
