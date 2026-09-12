# Search strategy appendix (PRISMA-S)

Generated automatically by CorpusSLR v1.5.0. Item numbers refer to the PRISMA-S checklist (Rethlefsen et al., 2021, *Systematic Reviews* 10:39).

## Information sources and dates [Items 1, 2, 13, 15]

| # | Database | Platform | Interface | Date searched | Records |
|---|----------|----------|-----------|---------------|---------|
| S1 | Web of Science Core Collection | Clarivate | API | 2026-09-07 | 100 |
| S2 | PubMed | NCBI Entrez | API | 2026-09-07 | 100 |
| S3 | Crossref | Crossref REST | API | 2026-09-07 | 100 |

Total records identified: **300**

## Full search strategies as run [Item 8]

### S1 - Web of Science Core Collection

```
TS=("deep learning" OR "convolutional neural network") AND TS=("diabetic retinopathy") AND PY=2020-2024 AND DT=(Article)
```

Endpoint: `https://api.clarivate.com/api/wos`
Notes: RecordsFound=1431; quota after search: x-rec-amtpermonth-remaining=999798; x-req-reqperday-remaining=29992; x-req-reqpersec-remaining=2; 100/100 records carry an abstract

### S2 - PubMed

```
("deep learning"[Title/Abstract] OR "convolutional neural network"[Title/Abstract]) AND ("diabetic retinopathy"[Title/Abstract]) AND 2020:2024[dp] AND ("journal article"[pt])
```

Limits/filters applied: E-utilities history server  [Item 9]
Endpoint: `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi`
Notes: Count=636; capped at max_results=100

### S3 - Crossref

```
deep learning convolutional neural network diabetic retinopathy | filter=from-pub-date:2020-01-01,until-pub-date:2024-12-31,type:journal-article
```

Limits/filters applied: relevance search (non-boolean)  [Item 9]
Endpoint: `https://api.crossref.org/works`
Notes: total-results=1148125; SUPPLEMENTARY source - not reproducible boolean search; capped at max_results=100

## Search-system classification [Gusenbauer & Haddaway, 2020]

Sources are classified as *principal* (systems meeting the requirements for a reproducible systematic search) or *supplementary* (systems suitable for coverage checks, citation chasing and grey literature, but not for the primary search).

| Database | Tier | Searches | Records | Share of identified |
|----------|------|----------|---------|---------------------|
| PubMed/MEDLINE | principal | 1 | 100 | 33.3% |
| Web of Science Core Collection | principal | 1 | 100 | 33.3% |
| Crossref | supplementary | 1 | 100 | 33.3% |

Principal systems searched: **2**; supplementary: **1**; unclassified: **0**.
Records from supplementary systems: **100 of 300 (33.3%)**.

No strategy warnings: the corpus rests on more than one principal search system and supplementary systems do not dominate the identified records.

## Deduplication [Item 16]

Records were deduplicated with CorpusSLR v1.5.0 using a cascading procedure: (1) exact identifier matching in the order DOI -> PMID -> OpenAlex ID -> Scopus ID, with transitive closure over a union-find structure, so that a record sharing one identifier with a second and a different identifier with a third joins both; (2) blocking rounds on composite field keys; and (3) fuzzy matching of normalized titles (Ratcliff-Obershelp similarity >= 0.93, publication year within +/-1, first-author surname agreement). A conflicting identifier blocks a merge, and journal articles are kept separate from their conference abstracts. Stage counts: exact DOI match (normalized): n = 26. In total 26 of 300 records were removed as duplicates, leaving 274 unique records. Every pairwise decision, with its matching evidence, is available in the machine-readable deduplication report (CSV). [PRISMA-S Item 16]

### Cross-source overlap (duplicate pairs by source)

| |PubMed|Web of Science Core Collection|
|---|---|---|
|PubMed|-|26|
|Web of Science Core Collection|26|-|

### Publication-integrity check

1 of 274 records carry an integrity marker.

| Flag | Records | Meaning for the review |
|---|---:|---|
| `withdrawn` | 1 | must not enter synthesis; exclude and record the exclusion |

Records that should be excluded from synthesis:

- WITHDRAWN: Granular computing based machine learning in the era of big data (Crossref, DOI 10.1016/j.ins.2016.10.012)

*Detection reads the record's document type and title only. A publisher that retracts an article without amending either cannot be detected this way, so this is a lower bound on the retractions in the corpus, not a clearance. For an authoritative answer, check the DOIs against Crossref's retraction records or the Retraction Watch database, and report the date of the check -- retraction status changes after a search is run.*
