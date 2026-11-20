# Search strategy appendix (PRISMA-S)

Generated automatically by CorpusSLR v1.2.0. Item numbers refer to the PRISMA-S checklist (Rethlefsen et al., 2021, *Systematic Reviews* 10:39).

## Information sources and dates [Items 1, 2, 13, 15]

| # | Database | Platform | Interface | Date searched | Records |
|---|----------|----------|-----------|---------------|---------|
| S1 | Scopus | Elsevier | Scopus Search API | 2026-09-07 | 1 |
| S2 | PubMed | NCBI | E-utilities | 2026-09-07 | 1 |

Total records identified: **2**

## Full search strategies as run [Item 8]

### S1 - Scopus

```
(TITLE-ABS-KEY("deep learning" OR "convolutional neural network")) AND TITLE-ABS-KEY("diabetic retinopathy") AND (PUBYEAR > 2019 AND PUBYEAR < 2025) AND (DOCTYPE(ar))
```


### S2 - PubMed

```
("deep learning"[Title/Abstract] OR "convolutional neural network"[Title/Abstract]) AND ("diabetic retinopathy"[Title/Abstract]) AND 2020:2024[dp] AND ("journal article"[pt])
```


## Search-system classification [Gusenbauer & Haddaway, 2020]

Sources are classified as *principal* (systems meeting the requirements for a reproducible systematic search) or *supplementary* (systems suitable for coverage checks, citation chasing and grey literature, but not for the primary search).

| Database | Tier | Searches | Records | Share of identified |
|----------|------|----------|---------|---------------------|
| PubMed/MEDLINE | principal | 1 | 1 | 50.0% |
| Scopus | principal | 1 | 1 | 50.0% |

Principal systems searched: **2**; supplementary: **0**; unclassified: **0**.
Records from supplementary systems: **0 of 2 (0.0%)**.

No strategy warnings: the corpus rests on more than one principal search system and supplementary systems do not dominate the identified records.

## Deduplication [Item 16]

Records were deduplicated with CorpusSLR v1.2.0 using a cascading procedure: (1) exact identifier matching in the order DOI -> PMID -> OpenAlex ID -> Scopus ID, with transitive closure over a union-find structure, so that a record sharing one identifier with a second and a different identifier with a third joins both; (2) blocking rounds on composite field keys; and (3) fuzzy matching of normalized titles (Ratcliff-Obershelp similarity >= 0.93, publication year within +/-1, first-author surname agreement). A conflicting identifier blocks a merge, and journal articles are kept separate from their conference abstracts. Stage counts: exact DOI match (normalized): n = 1. In total 1 of 2 records were removed as duplicates, leaving 1 unique records. Every pairwise decision, with its matching evidence, is available in the machine-readable deduplication report (CSV). [PRISMA-S Item 16]

### Cross-source overlap (duplicate pairs by source)

| |PubMed|Scopus|
|---|---|---|
|PubMed|-|1|
|Scopus|1|-|

### Publication-integrity check

No record in the corpus of 1 carries a retraction, withdrawal, expression of concern or erratum marker in its title or document type.

*Detection reads the record's document type and title only. A publisher that retracts an article without amending either cannot be detected this way, so this is a lower bound on the retractions in the corpus, not a clearance. For an authoritative answer, check the DOIs against Crossref's retraction records or the Retraction Watch database, and report the date of the check -- retraction status changes after a search is run.*
