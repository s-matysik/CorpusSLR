"""Generate docs/worked_example.md and its PRISMA diagram by running the package.

The page is the static counterpart of an interactive demonstration. The
documentation site is built without JavaScript and without external requests,
and a guard in CI rejects any page that has either, so a page that asks the
reader to run code in the browser cannot be published from here. What the page
can do is show a real run: every table below is produced by calling the
package, with fixed dates, and the committed file is compared with a fresh run
by ``--check``, so the page cannot drift from the code.

    PYTHONPATH=. python validation/generate_worked_example.py          # write
    PYTHONPATH=. python validation/generate_worked_example.py --check  # compare

The illustrative records of section 2 are written for this page and are not
data from a real search. Section 3 uses twelve records of the ASySD Diabetes
benchmark (``validation/labelled_test_set.csv``, GPL-3.0, see
``validation/THIRD_PARTY_DATA.md``), shown by title and page range only.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile

from corpusslr import (Corpus, PrismaFlow, Record, SearchQuery, deduplicate,
                       prisma_s_markdown)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT_MD = os.path.join(REPO, "docs", "worked_example.md")
OUT_SVG = os.path.join(REPO, "docs", "worked_example_prisma.svg")
DATE = "2026-09-07"


def _cell(text, limit=64):
    text = " ".join(str(text or "").split()).replace("|", "/")
    return text if len(text) <= limit else text[:limit - 3].rstrip() + "..."


def _table(header, rows):
    out = ["| " + " | ".join(header) + " |",
           "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def build_corpus():
    query = SearchQuery(
        blocks=[["deep learning", "convolutional neural network"],
                ["diabetic retinopathy"]],
        years=(2020, 2024), doc_types=["article"])
    corpus = Corpus()
    corpus.add_records([
        Record(uid="s1", title="Deep learning for diabetic retinopathy screening",
               doi="10.1000/ABC.123", year=2021, source="Scopus"),
        Record(uid="s2", title="Convolutional networks for retinal image grading",
               doi="10.1000/xyz.9", year=2022, source="Scopus"),
    ], database="Scopus", platform="Elsevier", interface="Scopus Search API",
        query=query.to_scopus(), date_run=DATE)
    corpus.add_records([
        Record(uid="p1", title="Deep learning for diabetic retinopathy screening",
               doi="https://doi.org/10.1000/abc.123", year=2021, source="PubMed"),
        Record(uid="p2", title="Convolutional networks for retinal image grading.",
               year=2022, source="PubMed"),
    ], database="PubMed", platform="NCBI", interface="E-utilities",
        query=query.to_pubmed(), date_run=DATE)
    corpus.add_records([
        Record(uid="o1", title="Transfer learning in fundus photography",
               doi="10.1000/tl.77", year=2023, source="OpenAlex"),
        Record(uid="o2", title="Deep Learning for Diabetic Retinopathy Screening",
               year=2021, source="OpenAlex"),
    ], database="OpenAlex", platform="OurResearch", interface="OpenAlex API",
        query=query.to_openalex(), date_run=DATE)
    return query, corpus


def same_doi_group():
    import csv
    sys.path.insert(0, HERE)
    import same_doi_example as ex
    with open(ex.GOLD, encoding="utf-8", errors="replace", newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if ex.DOI in (r["doi"] or "").lower()]
    recs = [Record(uid=r["record_id"], title=r["title"], abstract=r["abstract"],
                   authors=[a for a in (r["author"] or "").split(";") if a.strip()],
                   year=int(r["year"]) if (r["year"] or "").isdigit() else None,
                   journal=r["journal"], volume=r["volume"], pages=r["pages"],
                   doi=r["doi"]) for r in rows]
    return recs, deduplicate(recs)


def render(svg_path):
    query, corpus = build_corpus()
    result = deduplicate(corpus)
    flow = PrismaFlow.from_dedup(corpus, result)
    # The package does not screen. These counts stand in for a reviewer's
    # decisions so that the diagram is complete; they are not a result.
    flow.set_screening(records_excluded=1, fulltext_exclusions={"not a primary study": 1},
                       studies_included=1)
    problems = flow.validate()
    assert not problems, problems
    flow.to_svg(svg_path)
    by_uid = {r.uid: r for r in corpus.all_records()} if hasattr(corpus, "all_records") else {}

    md = []
    md.append("# Worked example\n")
    md.append(
        "This page shows a real run of the package. Every table below was produced "
        "by calling it, with fixed dates, by `validation/generate_worked_example.py`; "
        "the repository test suite compares the committed page with a fresh run, so "
        "the page cannot drift from the code. It is static on purpose: the "
        "documentation site is built without JavaScript and without external "
        "requests. To run the same steps yourself, see the last section.\n")

    md.append("## 1. One query, three dialects\n")
    md.append("A database-neutral query of two synonym blocks, a year range and a "
              "document type is compiled into each database's own syntax:\n")
    md.append("```\n# Scopus\n%s\n\n# PubMed\n%s\n\n# OpenAlex\n%s\n```\n"
              % (query.to_scopus(), query.to_pubmed(), query.to_openalex()))

    md.append("## 2. Six records from three databases\n")
    md.append("The records are written for this page and are not data from a real "
              "search. Three of them are duplicates of others under a different "
              "identifier form, or without an identifier.\n")
    rows = []
    for ev in corpus.search_events if hasattr(corpus, "search_events") else []:
        pass
    inp = []
    for rec in sum(([r for r in getattr(res, "records", [])] for res in getattr(corpus, "results", [])), []):
        inp.append(rec)
    if not inp:
        inp = list(corpus.records()) if hasattr(corpus, "records") and callable(corpus.records) else []
    md.append(_table(["uid", "database", "year", "DOI as delivered", "title"],
                     [(r.uid, r.source, r.year or "", r.doi or "(none)", _cell(r.title, 56))
                      for r in inp]))
    md.append("")
    md.append("Deduplication result: **%d identified, %d unique** (%s). Every merge is "
              "logged with its evidence:\n" % (corpus.total_identified(), len(result.records),
                                              ", ".join("%s %d" % kv for kv in sorted(result.report.by_method.items()))))
    md.append(_table(["kept", "removed", "method", "score", "removed record's title"],
                     [(d.kept_uid, d.removed_uid, d.method, "%.3f" % d.score, _cell(d.removed_title, 52))
                      for d in result.report.decisions]))
    md.append("")

    md.append("## 3. One DOI, six different abstracts\n")
    recs, res = same_doi_group()
    kept = {r.uid for r in res.records}
    merged_into = {d.removed_uid: d.kept_uid for d in res.report.decisions}
    md.append("In the ASySD Diabetes benchmark, twelve records carry the DOI "
              "10.1007/s00125-015-3687-4, a conference supplement, and represent six "
              "different abstracts, two copies of each. Merging on the DOI alone "
              "would leave one record. The package keeps %d, because a shared "
              "identifier is refused when the records sit at different places in the "
              "volume and when their titles disagree.\n" % len(res.records))
    md.append(_table(["record", "pages", "outcome", "title"],
                     [(r.uid, r.pages or "", "kept" if r.uid in kept else "merged into " + merged_into.get(r.uid, "?"),
                       _cell(r.title, 60)) for r in sorted(recs, key=lambda r: (r.pages or "", int(r.uid) if r.uid.isdigit() else 0))]))
    md.append("")

    md.append("## 4. The PRISMA 2020 flow diagram\n")
    md.append("Generated from the recorded search events and the deduplication result "
              "of section 2, and checked for arithmetic consistency (`PrismaFlow.validate()` "
              "returned no problems). The identification and deduplication counts come "
              "from the package; the screening counts are illustrative, because the "
              "package does not screen.\n")
    md.append("![PRISMA 2020 flow diagram generated from the example records](worked_example_prisma.svg)\n")

    md.append("## 5. The PRISMA-S appendix\n")
    md.append("The search appendix lists each database with its platform, interface, "
              "the query as executed, the date and the hit count. The first lines:\n")
    appendix = prisma_s_markdown(corpus, result).strip().splitlines()
    md.append("```\n%s\n```\n" % "\n".join(appendix[:28]))

    md.append("## 6. Run it yourself\n")
    md.append("```\npip install https://github.com/s-matysik/CorpusSLR/archive/refs/tags/v1.2.0.zip\n"
              "python paper/listing_example.py\n"
              "python validation/same_doi_example.py\n"
              "python validation/generate_worked_example.py --check\n```\n")
    md.append("The first example needs no network and no API key. Retrieval from a "
              "database needs that database's key, read from an environment variable.\n")
    return "\n".join(md)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true",
                    help="compare the committed page and diagram with a fresh run")
    args = ap.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        svg = os.path.join(tmp, "p.svg")
        text = render(svg)
        svg_text = open(svg, encoding="utf-8").read()
    if args.check:
        ok = (os.path.exists(OUT_MD) and open(OUT_MD, encoding="utf-8").read() == text
              and os.path.exists(OUT_SVG) and open(OUT_SVG, encoding="utf-8").read() == svg_text)
        print("worked example is current" if ok else "worked example is STALE")
        return 0 if ok else 1
    with open(OUT_MD, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    with open(OUT_SVG, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(svg_text)
    print("wrote", os.path.relpath(OUT_MD, REPO), "and", os.path.relpath(OUT_SVG, REPO))
    return 0


if __name__ == "__main__":                                  # pragma: no cover
    sys.exit(main())
