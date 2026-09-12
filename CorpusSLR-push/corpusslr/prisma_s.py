"""PRISMA-S search-reporting appendix (Rethlefsen et al., 2021).

Generates, from the corpus audit trail, the appendix reviewers ask for.
Item numbers follow the 16-item PRISMA-S checklist (Rethlefsen et al., 2021,
*Systematic Reviews* 10:39, Table 1):

======  ====================================================================
Item    What the appendix supplies
======  ====================================================================
1       Database name, with the platform stated for each source
2       The platform, when several databases were searched on one platform
8       Full search strategies, copied exactly as run
9       Limits and restrictions applied to each search
13      Date of the last search, per strategy
15      Total records identified from each database
16      Deduplication: the process and software, with per-stage counts
======  ====================================================================

Items 3-7 (study registries, browsed sources, citation searching, contacts,
other methods), 10-12 (published search filters, prior work, updates) and 14
(peer review) describe activities outside a retrieval library's knowledge; the
appendix leaves placeholders for them rather than inventing content, since an
unreported item and a falsely reported one are not equally bad.

Markdown by default; ``.docx`` if python-docx is installed.
"""
from __future__ import annotations

from typing import Optional

from . import __version__ as _pkg_version
from .corpus import Corpus
from .dedup import DedupResult

_METHOD_LABEL = {
    "doi": "exact DOI match (normalized)",
    "pmid": "exact PubMed ID match",
    "openalex": "exact OpenAlex ID match",
    "scopus": "exact Scopus ID/EID match",
    "fuzzy": ("fuzzy match: normalized-title Ratcliff-Obershelp similarity "
              "with year and first-author agreement"),
}


def _dedup_paragraph(result: Optional[DedupResult],
                     fuzzy_threshold: float, year_tolerance: int) -> str:
    if result is None:
        return ("Deduplication was not performed within CorpusSLR "
                "(records exported as retrieved).")
    rep = result.report
    stages = "; ".join(f"{_METHOD_LABEL.get(m, m)}: n = {n}"
                       for m, n in rep.by_method.items())

    # PRISMA-S item 16 asks for the process actually used, so every guard that
    # can change the outcome has to appear here. Describing only the identifier
    # cascade and the fuzzy stage -- as this paragraph did until 1.4.0 --
    # understated the method by three mechanisms that decide real merges, and a
    # reviewer reading the appendix would have been told the wrong thing.
    guards = []
    if getattr(rep, "id_links_rejected", 0):
        guards.append(
            f"a shared identifier was refused as evidence for "
            f"{rep.id_links_rejected} pair(s) whose titles disagreed or whose "
            f"bibliographic coordinates placed them at different locations "
            f"(the signature of one DOI covering a whole conference "
            f"supplement)")
    if getattr(rep, "round_candidates", 0):
        guards.append(
            f"{rep.round_candidates} additional candidate pair(s) were raised "
            f"by exact agreement on composite keys (title+pages, "
            f"author+year+page, journal+volume+page)")
    if getattr(rep, "copublication_merges", 0):
        guards.append(
            f"{rep.copublication_merges} pair(s) with conflicting DOIs were "
            f"merged on complete agreement of title, year, first page and "
            f"first author (one work co-published under two publisher DOIs)")
    if getattr(rep, "by_locus", None):
        detail = ", ".join(f"{k}: {v}" for k, v in sorted(rep.by_locus.items()))
        guards.append(f"pairs separated by a differing field ({detail})")
    if getattr(rep, "oversized_blocks_skipped", 0):
        guards.append(
            f"{rep.oversized_blocks_skipped} blocking bucket(s) exceeded the "
            f"size cap and were probed through a composite index instead")
    guard_text = (" Additional stages that affected the outcome: "
                  + "; ".join(guards) + ".") if guards else ""

    return (
        f"Records were deduplicated with CorpusSLR v{_pkg_version} using a "
        f"cascading procedure: (1) exact identifier matching in the order "
        f"DOI -> PMID -> OpenAlex ID -> Scopus ID, with transitive closure over "
        f"a union-find structure, so that a record sharing one identifier with "
        f"a second and a different identifier with a third joins both; "
        f"(2) blocking rounds on composite field keys; and (3) fuzzy matching "
        f"of normalized titles (Ratcliff-Obershelp similarity >= "
        f"{fuzzy_threshold}, publication year within +/-{year_tolerance}, "
        f"first-author surname agreement). A conflicting identifier blocks a "
        f"merge, and journal articles are kept separate from their conference "
        f"abstracts. Stage counts: {stages or 'none'}.{guard_text} "
        f"In total {rep.removed} of {rep.before} records were removed as "
        f"duplicates, leaving {rep.after} unique records. Every pairwise "
        f"decision, with its matching evidence, is available in the "
        f"machine-readable deduplication report (CSV). [PRISMA-S Item 16]")


def prisma_s_markdown(corpus: Corpus, result: Optional[DedupResult] = None,
                      fuzzy_threshold: float = 0.93,
                      year_tolerance: int = 1) -> str:
    """Render the PRISMA-S search-reporting appendix as Markdown.

    Covers the checklist items a software tool can answer from its own record:
    databases and platforms with dates and hit counts (items 1-2), the query as
    executed per database (item 8), limits and filters (items 13, 15) and the
    deduplication procedure with its stage counts (item 16). Items requiring
    human judgement -- peer review of the strategy, grey-literature sources --
    are listed as gaps for the author to complete rather than silently omitted.

    Pass ``result`` to have the deduplication described from the run itself; the
    description names every guard that affected the outcome, so the appendix
    reflects what happened rather than a simplified account of the method.
    """
    lines = [
        "# Search strategy appendix (PRISMA-S)",
        "",
        (f"Generated automatically by CorpusSLR v{_pkg_version}. Item numbers "
         "refer to the PRISMA-S checklist (Rethlefsen et al., 2021, "
         "*Systematic Reviews* 10:39)."),
        "",
        "## Information sources and dates [Items 1, 2, 13, 15]",
        "",
        "| # | Database | Platform | Interface | Date searched | Records |",
        "|---|----------|----------|-----------|---------------|---------|",
    ]
    for ev in corpus.searches:
        lines.append(f"| {ev.search_id} | {ev.database} | {ev.platform or '-'} "
                     f"| {ev.interface} | {ev.date_run} "
                     f"| {ev.records_retrieved} |")
    lines += ["", f"Total records identified: **{corpus.total_identified()}**",
              "", "## Full search strategies as run [Item 8]", ""]
    for ev in corpus.searches:
        lines += [f"### {ev.search_id} - {ev.database}", "", "```",
                  ev.query or "(not recorded)", "```", ""]
        if ev.filters:
            lines.append(f"Limits/filters applied: {ev.filters}  [Item 9]")
        if ev.url:
            lines.append(f"Endpoint: `{ev.url}`")
        if ev.notes:
            lines.append(f"Notes: {ev.notes}")
        lines.append("")
    # Classification of the searched systems as principal or supplementary
    # (Gusenbauer & Haddaway, 2020). PRISMA-S Item 1 asks reviewers to name
    # each source; naming them without stating which ones can carry a
    # reproducible search leaves the recall claim unexamined.
    try:
        from .sources.registry import audit_markdown
        lines += [audit_markdown(corpus).rstrip(), ""]
    except Exception:  # pragma: no cover - the appendix must still render
        pass
    lines += ["## Deduplication [Item 16]", "",
              _dedup_paragraph(result, fuzzy_threshold, year_tolerance), ""]
    if result is not None and result.report.overlap:
        lines += ["### Cross-source overlap (duplicate pairs by source)", "",
                  result.report.overlap_markdown(), ""]
    # Retraction status belongs in the appendix whether or not anything was
    # found: a reviewer reading "no records flagged" learns that the check ran,
    # while silence leaves them unable to tell it apart from a check omitted.
    # Measured on a live 323-record corpus, four records carried a retraction
    # marker -- three retracted studies and one notice -- so this is not a
    # hypothetical gap in a search that looks clean.
    try:
        from .integrity import integrity_markdown
        recs = list(result.records) if result is not None else list(corpus.records)
        if recs:
            lines += [integrity_markdown(recs).rstrip(), ""]
    except Exception:  # pragma: no cover - the appendix must still render
        pass
    return "\n".join(lines)


def prisma_s_appendix(corpus: Corpus, result: Optional[DedupResult] = None,
                      path: str = "prisma_s_appendix.md",
                      fuzzy_threshold: float = 0.93,
                      year_tolerance: int = 1) -> str:
    """Write the appendix to *path* (.md, or .docx if python-docx present)."""
    md = prisma_s_markdown(corpus, result, fuzzy_threshold, year_tolerance)
    if path.lower().endswith(".docx"):
        try:
            _write_docx(md, path)
            return path
        except ImportError:
            path = path[:-5] + ".md"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(md)
    return path


def _write_docx(md: str, path: str) -> None:
    from docx import Document  # optional dependency

    doc = Document()
    table_buf = []
    in_code = False
    for line in md.splitlines():
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            p = doc.add_paragraph(line)
            p.style = doc.styles["No Spacing"]
            for run in p.runs:
                run.font.name = "Courier New"
            continue
        if line.startswith("|"):
            table_buf.append([c.strip() for c in line.strip("|").split("|")])
            continue
        if table_buf:
            rows = [r for r in table_buf if not set("".join(r)) <= set("-: ")]
            t = doc.add_table(rows=len(rows), cols=len(rows[0]))
            t.style = "Light Grid Accent 1"
            for i, r in enumerate(rows):
                for j, c in enumerate(r):
                    t.cell(i, j).text = c
            table_buf = []
        if line.startswith("### "):
            doc.add_heading(line[4:], level=3)
        elif line.startswith("## "):
            doc.add_heading(line[3:], level=2)
        elif line.startswith("# "):
            doc.add_heading(line[2:], level=1)
        elif line.strip():
            doc.add_paragraph(line.replace("**", ""))
    doc.save(path)
