"""End-to-end illustrative example (SoftwareX 'Illustrative example' section).

Runs one structured query against Scopus + OpenAlex + PubMed + Crossref,
recovers abstracts, deduplicates with a full audit trail and produces the
PRISMA 2020 flow diagram + PRISMA-S appendix + screening-ready CSV.

Set SCOPUS_API_KEY and CONTACT_EMAIL before running. Sources without
credentials are skipped gracefully.
"""
import os

from corpusslr import (Corpus, CrossrefSource, OpenAlexSource, PrismaFlow,
                       PubMedSource, ScopusSource, SearchQuery, deduplicate,
                       prisma_s_appendix, quality_markdown, recover_abstracts,
                       to_csv, to_screening_csv)

EMAIL = os.environ.get("CONTACT_EMAIL", "you@example.org")
SCOPUS_KEY = os.environ.get("SCOPUS_API_KEY", "")

query = SearchQuery(
    blocks=[["artificial intelligence", "machine learning"],
            ["adoption", "acceptance", "implementation"],
            ["SME", "small firm", "small business"]],
    years=(2015, 2026),
    doc_types=["article", "review"],
    languages=["en"],
)
print("Compiled queries:")
for k, v in query.compile_all().items():
    print(f"  {k}: {v}")

corpus = Corpus()
if SCOPUS_KEY:
    corpus.add_search(ScopusSource(api_key=SCOPUS_KEY).search(query, max_results=1000))
corpus.add_search(OpenAlexSource(mailto=EMAIL).search(query, max_results=1000))
corpus.add_search(PubMedSource(email=EMAIL).search(query, max_results=1000))
corpus.add_search(CrossrefSource(mailto=EMAIL).search(query, max_results=300))

print(f"\nIdentified: {corpus.total_identified()} "
      f"{corpus.identified_by_source()}")

stats = recover_abstracts(corpus.records, mailto=EMAIL)
print(f"Abstract recovery: {stats}")
print("\nData quality per source:\n" + quality_markdown(corpus.records))

result = deduplicate(corpus)
print("\n" + result.report.summary())
result.report.to_csv("dedup_report.csv")
print(result.report.overlap_markdown())

flow = PrismaFlow.from_dedup(corpus, result)
# screening numbers come from your screening tool (e.g. EmbedSLR/ASReview):
flow.set_screening(records_excluded=0, studies_included=0)
flow.to_svg("prisma2020_flow.svg")
prisma_s_appendix(corpus, result, "prisma_s_appendix.md")
to_csv(result.records, "corpus_unique.csv")
to_screening_csv(result.records, "screening.csv")
print("\nWrote: prisma2020_flow.svg, prisma_s_appendix.md, "
      "dedup_report.csv, corpus_unique.csv, screening.csv")
