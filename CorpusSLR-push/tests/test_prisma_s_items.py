"""Every PRISMA-S item number cited in the package must match the checklist.

The appendix hands a reviewer explicit item numbers. A wrong number is worse
than none: it tells the reviewer to look for the deduplication description under
"Dates of searches". Six such references were wrong before this test existed, so
the checklist is encoded here and every citation in the source tree is checked
against it.

Source: Rethlefsen ML, Kirtley S, Waffenschmidt S, et al. PRISMA-S: an extension
to the PRISMA Statement for Reporting Literature Searches in Systematic Reviews.
Systematic Reviews 10:39 (2021), Table 1. doi:10.1186/s13643-020-01542-z
"""
from __future__ import annotations

import pathlib
import re

import pytest

#: item number -> (short label, keywords that must plausibly appear near a
#: citation of this item)
PRISMA_S_CHECKLIST = {
    1: ("Database name", {"database", "platform", "name", "source"}),
    2: ("Multi-database searching", {"platform", "simultaneous", "multi"}),
    3: ("Study registries", {"registry", "registries", "trial"}),
    4: ("Online resources and browsing", {"browsing", "online", "print",
                                          "contents", "website", "web site"}),
    5: ("Citation searching", {"citation", "cited", "citing", "snowball"}),
    6: ("Contacts", {"contact", "author", "expert", "manufacturer"}),
    7: ("Other methods", {"other", "additional"}),
    8: ("Full search strategies", {"strategy", "strategies", "as run",
                                   "query", "search string", "request",
                                   "executed", "search as", "offset",
                                   "max_results", "retrieval"}),
    9: ("Limits and restrictions", {"limit", "restriction", "filter applied",
                                    "language", "date range"}),
    10: ("Search filters", {"published filter", "search filter", "hedge"}),
    11: ("Prior work", {"prior", "adapted", "reused", "previous review"}),
    12: ("Updates", {"update", "rerun", "alert"}),
    13: ("Dates of searches", {"date", "when", "executed", "last search"}),
    14: ("Peer review", {"peer review"}),
    15: ("Total records", {"records identified", "record count", "total",
                           "records per", "hit count", "number of records",
                           "| records |", "records retrieved"}),
    16: ("Deduplication", {"deduplic", "duplicate"}),
}

_PKG = pathlib.Path(__file__).resolve().parent.parent / "corpusslr"
_CITE = re.compile(r"PRISMA-S\s+[Ii]tems?\s+([0-9]+(?:\s*[,-]\s*[0-9]+)*)"
                   r"|\[Items?\s+([0-9]+(?:\s*,\s*[0-9]+)*)\]")


def _citations():
    """Yield (path, item_number, surrounding_text) for every PRISMA-S citation."""
    for path in sorted(_PKG.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for m in _CITE.finditer(text):
            nums = m.group(1) or m.group(2) or ""
            start, end = max(0, m.start() - 320), min(len(text), m.end() + 200)
            context = " ".join(text[start:end].split()).lower()
            for tok in re.split(r"[,\s-]+", nums):
                if tok.isdigit():
                    yield path.name, int(tok), context


def test_the_package_cites_prisma_s_items():
    """Guard the guard: if the citation regex stops matching, this test is void."""
    found = list(_citations())
    assert len(found) >= 8, f"only {len(found)} citations found - regex broken?"


@pytest.mark.parametrize("filename,item,context", list(_citations()),
                         ids=lambda v: str(v)[:24])
def test_cited_item_numbers_exist_in_the_checklist(filename, item, context):
    assert item in PRISMA_S_CHECKLIST, (
        f"{filename} cites PRISMA-S item {item}, but the checklist has 16 items")


def test_each_cited_item_is_used_for_its_own_subject():
    """A citation must sit near wording that matches what the item is about."""
    mismatches = []
    for filename, item, context in _citations():
        label, keywords = PRISMA_S_CHECKLIST[item]
        if not any(k in context for k in keywords):
            mismatches.append((filename, item, label, context[-140:]))
    assert not mismatches, "item numbers cited for the wrong subject:\n" + "\n".join(
        f"  {f} cites item {i} ({lab}) - context: ...{c}"
        for f, i, lab, c in mismatches)


def test_appendix_labels_its_sections_with_real_item_numbers():
    from corpusslr import Corpus, Record, deduplicate, prisma_s_markdown
    c = Corpus()
    c.add_records([Record(title="A", doi="10.5001/a")], database="Scopus",
                  interface="API", query="TITLE-ABS-KEY(ai)",
                  date_run="2026-01-01", platform="Elsevier")
    md = prisma_s_markdown(c, deduplicate(c))
    for m in re.finditer(r"\[Items?\s+([0-9,\s]+)\]", md):
        for tok in re.split(r"[,\s]+", m.group(1).strip()):
            if tok.isdigit():
                assert int(tok) in PRISMA_S_CHECKLIST, (tok, m.group(0))
    # the sections that carry the data must cite the items that ask for it
    assert "[Items 1, 2, 13, 15]" in md
    assert "[Item 8]" in md and "[Item 16]" in md


# --------------------------------------------------------------------------
# Fidelity of the deduplication description (PRISMA-S item 16 asks for the
# process actually used). Until 1.4.0 the paragraph described only the
# identifier cascade and the fuzzy stage, understating the method by three
# mechanisms that decide real merges.
# --------------------------------------------------------------------------
def _supplement_corpus():
    from corpusslr import Corpus, Record
    c = Corpus()
    c.add_records([
        Record(title="Effects of drug A on vascular outcomes", doi="10.5001/suppl",
               year=2020, volume="63", pages="45-52", authors=["Smith, A"]),
        Record(title="Effects of drug B on renal outcomes", doi="10.5001/suppl",
               year=2020, volume="63", pages="374-380", authors=["Jones, B"]),
        Record(title="Effects of drug C on cardiac outcomes", doi="10.5001/suppl",
               year=2020, volume="63", pages="512-519", authors=["Muller, C"]),
    ], database="Embase", interface="OVID", query="q", date_run="2026-01-01")
    c.add_records([
        Record(title="Effects of drug A on vascular outcomes", doi="10.5001/suppl",
               year=2020, volume="63", pages="45-52", authors=["Smith, A"]),
    ], database="Scopus", interface="API", query="q", date_run="2026-01-01")
    return c


def test_appendix_describes_every_stage_that_can_change_the_outcome():
    from corpusslr import deduplicate, prisma_s_markdown
    c = _supplement_corpus()
    md = prisma_s_markdown(c, deduplicate(c))
    for phrase in ("union-find", "blocking rounds", "conflicting identifier",
                   "conference abstracts"):
        assert phrase in md, f"appendix does not mention {phrase!r}"


def test_appendix_reports_the_guards_that_actually_fired_with_counts():
    from corpusslr import deduplicate, prisma_s_markdown
    c = _supplement_corpus()
    res = deduplicate(c)
    md = prisma_s_markdown(c, res)
    assert res.report.id_links_rejected >= 1
    assert "shared identifier was refused" in md
    assert str(res.report.id_links_rejected) in md
    assert res.report.by_locus
    for field, n in res.report.by_locus.items():
        assert f"{field}: {n}" in md


def test_appendix_omits_guard_sentences_when_no_guard_fired():
    """A clean corpus must not carry paragraphs about mechanisms that idled."""
    from corpusslr import Corpus, Record, deduplicate, prisma_s_markdown
    c = Corpus()
    c.add_records([Record(title="A distinct study of things", doi="10.5001/a",
                          year=2024, authors=["Nowak, A"])],
                  database="Scopus", interface="API", query="q",
                  date_run="2026-01-01")
    md = prisma_s_markdown(c, deduplicate(c))
    assert "Additional stages that affected the outcome" not in md
    assert "union-find" in md          # the method description still appears
