"""The Python listing printed in the SoftwareX article, kept runnable.

This file is the source of truth for Listing 1. It runs offline: the two
records are supplied directly instead of being retrieved, so the listing can
be executed in a test environment with no network and no API key. The article
prints the block between the BEGIN/END markers verbatim.

Usage:  PYTHONPATH=. python paper/listing_example.py
"""
# --- BEGIN LISTING 1 ---
from corpusslr import (Corpus, PrismaFlow, Record, SearchQuery,
                       deduplicate, prisma_s_markdown, to_scopus_csv)

query = SearchQuery(
    blocks=[["deep learning", "convolutional neural network"],
            ["diabetic retinopathy"]],
    years=(2020, 2024), doc_types=["article"],
)
print(query.to_scopus())

# In a real review the records come from a client, e.g.
#     ScopusSource(api_key=...).search(query)
# Two records are supplied here so the example runs with no network.
corpus = Corpus()
corpus.add_records(
    [Record(title="Deep learning for diabetic retinopathy",
            doi="10.1000/ABC.123", year=2021, source="Scopus")],
    database="Scopus", platform="Elsevier", interface="Scopus Search API",
    query=query.to_scopus(), date_run="2026-09-07")
corpus.add_records(
    [Record(title="Deep learning for diabetic retinopathy",
            doi="https://doi.org/10.1000/abc.123", year=2021,
            source="PubMed")],
    database="PubMed", platform="NCBI", interface="E-utilities",
    query=query.to_pubmed(), date_run="2026-09-07")

result = deduplicate(corpus)
print(corpus.total_identified(), "identified ->",
      len(result.records), "unique")
print("merged by:", result.report.by_method)

to_scopus_csv(result.records, "corpus_scopus.csv")
flow = PrismaFlow.from_dedup(corpus, result)
flow.to_svg("prisma2020_flow.svg")
with open("prisma_s.md", "w") as fh:
    fh.write(prisma_s_markdown(corpus, result))
# --- END LISTING 1 ---
