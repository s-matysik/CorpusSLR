# Search strategy appendix (PRISMA-S)

Generated automatically by CorpusSLR v1.4.0. Item numbers refer to the PRISMA-S checklist (Rethlefsen et al., 2021, *Systematic Reviews* 10:39).

## Information sources and dates [Items 1, 2, 13, 15]

| # | Database | Platform | Interface | Date searched | Records |
|---|----------|----------|-----------|---------------|---------|
| S1 | Scopus | Elsevier | API | 2026-08-19 | 100 |
| S2 | PubMed | NCBI Entrez | API | 2026-08-19 | 100 |
| S3 | Crossref | Crossref REST | API | 2026-08-19 | 100 |
| S4 | arXiv | Cornell University / arXiv | API | 2026-08-19 | 23 |

Total records identified: **323**

## Full search strategies as run [Item 8]

### S1 - Scopus

```
(TITLE-ABS-KEY("deep learning" OR "convolutional neural network")) AND TITLE-ABS-KEY("diabetic retinopathy") AND (PUBYEAR > 2017 AND PUBYEAR < 2025) AND (DOCTYPE(ar)) AND LANGUAGE(english)
```

Limits/filters applied: view=COMPLETE; paging=cursor  [Item 9]
Endpoint: `https://api.elsevier.com/content/search/scopus`
Notes: totalResults=1717; retrieved=100; retrieval capped by caller at max_results=100

### S2 - PubMed

```
("deep learning"[Title/Abstract] OR "convolutional neural network"[Title/Abstract]) AND ("diabetic retinopathy"[Title/Abstract]) AND 2018:2024[dp] AND ("journal article"[pt]) AND (english[la])
```

Limits/filters applied: E-utilities history server  [Item 9]
Endpoint: `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi`
Notes: Count=712; capped at max_results=100

### S3 - Crossref

```
deep learning convolutional neural network diabetic retinopathy | filter=from-pub-date:2018-01-01,until-pub-date:2024-12-31,type:journal-article
```

Limits/filters applied: relevance search (non-boolean)  [Item 9]
Endpoint: `https://api.crossref.org/works`
Notes: total-results=1383416; SUPPLEMENTARY source - not reproducible boolean search; capped at max_results=100

### S4 - arXiv

```
(all:"deep learning" OR all:"convolutional neural network") AND (all:"diabetic retinopathy")
```

Limits/filters applied: publication year 2018-2024 applied client-side  [Item 9]
Endpoint: `http://export.arxiv.org/api/query`
Notes: opensearch:totalResults=255; every record registered as doc_type='preprint' (grey literature, PRISMA 2020 Item 6); the API offers no document-type or language filter; min_interval=3.0 s per arXiv API terms of use; capped at max_results=100; 77 record(s) removed by the client-side year filter

## Search-system classification [Gusenbauer & Haddaway, 2020]

Sources are classified as *principal* (systems meeting the requirements for a reproducible systematic search) or *supplementary* (systems suitable for coverage checks, citation chasing and grey literature, but not for the primary search).

| Database | Tier | Searches | Records | Share of identified |
|----------|------|----------|---------|---------------------|
| PubMed/MEDLINE | principal | 1 | 100 | 31.0% |
| Scopus | principal | 1 | 100 | 31.0% |
| Crossref | supplementary | 1 | 100 | 31.0% |
| arXiv | supplementary | 1 | 23 | 7.1% |

Principal systems searched: **2**; supplementary: **2**; unclassified: **0**.
Records from supplementary systems: **123 of 323 (38.1%)**.

No strategy warnings: the corpus rests on more than one principal search system and supplementary systems do not dominate the identified records.

## Deduplication [Item 16]

Records were deduplicated with CorpusSLR v1.4.0 using a cascading procedure: (1) exact identifier matching in the order DOI -> PMID -> OpenAlex ID -> Scopus ID, with transitive closure over a union-find structure, so that a record sharing one identifier with a second and a different identifier with a third joins both; (2) blocking rounds on composite field keys; and (3) fuzzy matching of normalized titles (Ratcliff-Obershelp similarity >= 0.93, publication year within +/-1, first-author surname agreement). A conflicting identifier blocks a merge, and journal articles are kept separate from their conference abstracts. Stage counts: exact DOI match (normalized): n = 24; fuzzy match: normalized-title Ratcliff-Obershelp similarity with year and first-author agreement: n = 2. Additional stages that affected the outcome: 1 pair(s) with conflicting DOIs were merged on complete agreement of title, year, first page and first author (one work co-published under two publisher DOIs). In total 26 of 323 records were removed as duplicates, leaving 297 unique records. Every pairwise decision, with its matching evidence, is available in the machine-readable deduplication report (CSV). [PRISMA-S Item 16]

### Cross-source overlap (duplicate pairs by source)

| |Crossref|PubMed|Scopus|arXiv|
|---|---|---|---|---|
|Crossref|-|0|2|1|
|PubMed|0|-|22|0|
|Scopus|2|22|-|0|
|arXiv|1|0|0|-|

### Publication-integrity check

4 of 297 records carry an integrity marker.

| Flag | Records | Meaning for the review |
|---|---:|---|
| `retracted` | 3 | must not enter synthesis; exclude and record the exclusion |
| `retraction_notice` | 1 | a notice about another article, not a study |

Records that should be excluded from synthesis:

- RETRACTED ARTICLE: An enhanced diabetic retinopathy detection and classification approach using deep convoluti (Crossref, DOI 10.1007/s00521-018-03974-0)
- Retracted: 3D Convolutional Neural Network Framework with Deep Learning for Nuclear Medicine (Crossref, DOI 10.1155/2023/9765894)
- RETRACTED ARTICLE: Efficient diabetic retinopathy detection using convolutional neural network and data augmen (Crossref, DOI 10.1007/s00500-023-08537-7)

*Detection reads the record's document type and title only. A publisher that retracts an article without amending either cannot be detected this way, so this is a lower bound on the retractions in the corpus, not a clearance. For an authoritative answer, check the DOIs against Crossref's retraction records or the Retraction Watch database, and report the date of the check -- retraction status changes after a search is run.*
