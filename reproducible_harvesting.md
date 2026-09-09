# Reproducible harvesting in CorpusSLR

**Module:** `corpusslr/harvest.py` (CorpusSLR 1.2.0, archive format version 1)
**Measurements taken:** 16 August 2026, `api.crossref.org` and
`api.semanticscholar.org`, no API keys.

---

## 1. The problem: "repeatable" is two different claims

PRISMA-S (Rethlefsen et al., 2021, *Systematic Reviews* 10:39) requires that a
search be reported so that it can be repeated. For an API-native review this
requirement silently splits in two, and conflating them is what makes most
automated searches unauditable:

| Claim | Question it answers | What it needs |
|---|---|---|
| **Reproducibility** | Does re-running the analysis on the *same evidence* give the same corpus? | The raw responses, archived and checksummed |
| **Replicability** | Does re-running the query *against the live database* give the same corpus? | A quantified difference, because the answer is usually "no" |

Bibliographic databases grow daily, relevance rankings are re-tuned, records are
corrected and citation counters change hourly. A review that promises
"re-running this query returns our corpus" makes a claim it cannot keep. What it
*can* keep is: "here is the evidence we analysed, verifiably unmodified, and
here is exactly how the database has moved since."

CorpusSLR implements the first as a bit-level guarantee and the second as a
measurement.

---

## 2. Protocol

### 2.1 Harvest and archive

```python
from corpusslr import CrossrefSource, SearchQuery, harvest

query = SearchQuery(blocks=[["artificial intelligence"], ["marketing"],
                            ["adoption"]],
                    years=(2020, 2023), doc_types=["article"])

res = harvest(CrossrefSource(mailto=EMAIL), query, max_results=60,
              archive="harvest_archive")
print(res.checksum)          # deterministic corpus identifier
```

Every HTTP response is written to `harvest_archive/responses/NNNNNN.json` with
its request, status, UTC timestamp and body checksum; `manifest.json` indexes
them and records the harvest itself (query as sent, filters, package version,
date, record count, corpus checksum, per-record fingerprints).

Credentials never enter the archive. API keys and tokens are dropped entirely
and contact addresses stored as `<redacted>`, so the deposited directory is safe
to publish and replays for somebody who holds neither.

### 2.2 Verify

```python
from corpusslr import verify_archive
assert verify_archive("harvest_archive") == []
```

Checks that every indexed response file exists, parses, and hashes to the value
recorded in the manifest; that the sequence has no gaps; and that each harvest's
response count matches its manifest. An empty list is the statement a reviewer
needs - the evidence has not been edited since collection.

### 2.3 Replay offline

```python
from corpusslr import replay_harvest
rep = replay_harvest(CrossrefSource(), query, "harvest_archive")
assert rep.checksum_matches
```

The **same** `harvest()` function runs the **same** source client against the
archive, with `ReplaySession` standing in for the network. This is deliberate:
if the reviewer ran a different code path, the reproducibility claim would be
untestable. `ReplaySession` contains no HTTP machinery at all, so "no network
was used" is structural rather than promised.

Requests are matched on endpoint plus non-secret parameters and served in
recorded order, so cursor and offset paging replay along the identical path.

### 2.4 Quantify drift

```python
from corpusslr import compare_harvests
later = harvest(CrossrefSource(mailto=EMAIL), query, max_results=60,
                archive="harvest_archive_2026-12")
print(compare_harvests(res, later).summary())
```

Records are aligned on identity (DOI → PMID → provider id → normalized
title+year) and reported as **added / removed / changed**, with pure citation
count updates kept in a separate bucket. `compare_harvests` also accepts two
deposited manifests, so a reviewer can audit drift without re-running anything.

---

## 3. Design decisions that carry methodological weight

### 3.1 The checksum covers stable fields only

`records_checksum()` hashes the sorted per-record checksums of these fields:

```
doi, pmid, openalex_id, scopus_id, norm_title, year, norm_journal, issn,
volume, issue, pages, doc_type, language, first_author_surname, n_authors,
has_abstract
```

Deliberately **excluded**: `cited_by` and `open_access` (change without the
study changing), `url` (resolver churn), and the abstract *text* - only its
presence is hashed, so gaining an abstract shows up while re-wrapped whitespace
does not. Including a citation counter would make every re-harvest of an
unchanged corpus look like a different corpus, which is precisely the false
alarm that trains reviewers to ignore the check.

The checksum is order-independent by construction: per-record digests are sorted
before hashing, so two harvests that retrieved the same studies in a different
relevance ranking produce the same value. That is what makes it publishable as a
corpus identifier.

### 3.2 Canonical sort order

Records are returned sorted by DOI, then normalized title, year and provider id
 - never in the order the API returned them. Section 4.1 shows why this is not
cosmetic.

### 3.3 A failed harvest still leaves usable evidence

A harvest that dies half-way (exhausted rate-limit retries, network loss,
interrupt) has already written response files. Those are closed out with an
explicit `mode: "aborted"` manifest entry recording the failure, so the archive
still passes `verify_archive()` and the failed attempts remain available as
evidence of what the API answered. An aborted harvest **refuses to replay** as
if it were complete - a truncated corpus that looks whole is worse than an
error.

---

## 4. Measured stability

Unless a row is marked **[offline harness]**, all figures below are from live
calls on 16 August 2026 with the query `artificial intelligence marketing
adoption`, filtered to journal articles published 2020-2023 (Crossref
`total-results` = 234 430). Rows marked **[offline harness]** measure the
*client's own* throttle and retry behaviour against scripted responses
(`FakeSession`, no network): pacing and backoff are properties of CorpusSLR, so
they are measured deterministically rather than by deliberately provoking 429s
on a shared public pool.

### 4.1 Crossref: stable *set*, unstable *order*

Repeated identical requests returned the same 40 records - but not in the same
order.

| Measurement | Result |
|---|---|
| Same record set across runs | yes (40/40, Jaccard 1.0) |
| Same wire order across two runs | **no** - 4 of 40 positions differed, first divergence at position 8 |
| Order census, 5 repeats (rows=40) | only **2 of 5** runs matched the reference order; positions differing per run: 0, 4, 2, 0, 2 |
| Set identical in all 5 repeats | yes (40 unique DOIs each) |
| Cursor paging (3 pages × 5), repeated | same 15 DOIs, **different order**; cursor tokens differed between runs |
| `offset` paging (3 pages × 5), repeated | same 15 DOIs in the **same** order |
| Records with a DOI | 100/100 (100%) |
| `total-results` drift over ~1 min | none (234 430 → 234 430) |
| Advertised rate limit | `X-Rate-Limit-Limit: 1` per `1s` |
| API version reported | `message-version: 1.0.0` (captured into the manifest) |

**This is the empirical justification for §3.2.** Crossref's relevance ranking
reshuffles near-tied records between calls, and its cursor tokens are not
stable across runs. Without a canonical sort, two harvests of an *identical*
corpus would produce different checksums, different CSV/RIS exports and a
spurious diff - the reproducibility check would fail on records that never
changed. With the sort applied, both runs yielded the identical checksum
`2ddd22aa14959e32…`, and `compare_harvests` reported 40 unchanged, 0 added,
0 removed.

Note also that raw response bytes differed between two identical requests
(timestamps and ranking order in the body), which is why the corpus checksum is
computed over parsed bibliographic fields and not over the wire payload.

### 4.2 Semantic Scholar: severe keyless rate limiting

| Measurement | Result |
|---|---|
| Successful keyless harvest (20 records) | 20 records, **20/20 with DOI**, 1 response, 1.72 s wall |
| Replay of that archive | `checksum_matches: True`, records field-for-field equal, 0.002 s, `verify_archive() == []` |
| Records with a DOI (100-record sample) | 96/100 (96%) |
| 429 responses during probing | 20 in probe 1; 30 in probe 2 (3 s spacing, 5 retries) - **all** small-page probes failed |
| Attempts at 150 s spacing after saturation | 4 consecutive harvests, **all** refused (3 × 429 each) |
| Cross-run drift for Semantic Scholar | **not measurable** - only one keyless harvest succeeded (see §6.7) |
| Client `min_interval` (keyless) **[offline harness]** | 1.1 s → measured 1.36 req/s over 3 pages |
| Client `min_interval` (with key) **[offline harness]** | 0.11 s |
| Retry on 429 **[offline harness]** | works: 429 → 429 → 200 succeeded in 6.0 s (backoff 2¹ + 2² s) |
| Retry budget exhausted | raises `SourceError` after 3 attempts, archive closed as `aborted` and still verifiable (observed both live and offline) |
| API version published | none - recorded in the manifest as "not published by the API" |

The unauthenticated pool is shared across all anonymous clients, so its
available capacity depends on global load, not only on your own pacing. During
this session it was saturated: after a 240 s cool-down a single 20-record
harvest succeeded immediately (1.72 s), while a second attempt 90 s later was
refused with three consecutive 429s (both live). The retry-on-429 path and the
`min_interval` throttle both work as specified - verified against scripted
responses, since deliberately provoking a 429 cascade on a shared public pool
would be impolite - but what they cannot do is manufacture capacity the pool is
not granting.

**Practical consequence for a review protocol:** treat keyless Semantic Scholar
as best-effort and archive it - an aborted harvest is recorded as such rather
than silently returning a short corpus. For a real search, obtain an API key
(`min_interval` drops to 0.11 s) or budget for retries across a longer window.

### 4.3 Cross-database DOI coverage

DOI presence is the precondition for meaningful cross-database deduplication.
In 100-record samples of the same query: Crossref **100/100** (100%, by
construction - Crossref is a DOI registry), Semantic Scholar **96/100** (96%).
Only **6 DOIs** were shared between the two 100-record relevance-ranked samples,
which illustrates why both are classified as *supplementary* sources: their
top-ranked slices of the same query barely intersect, so neither can be treated
as an exhaustive result set.

### 4.4 Archive cost

A 40-record Crossref harvest archived to 676 KB (1 response, full raw JSON
including abstracts and reference lists). Replay took 12 ms versus ~1 s for the
live call. Archives of this size are trivially depositable alongside a
manuscript.

---

## 5. For the reviewer: how to repeat this harvest

You need neither an API key nor a database subscription. The archive holds the
raw responses.

```bash
pip install corpusslr
```

```python
from corpusslr import CrossrefSource, SearchQuery, replay_harvest, verify_archive

# 1. Confirm the evidence has not been modified since collection.
print(verify_archive("harvest_archive") or "archive intact")

# 2. Rebuild the query exactly as reported in the appendix.
query = SearchQuery(blocks=[["artificial intelligence"], ["marketing"],
                            ["adoption"]],
                    years=(2020, 2023), doc_types=["article"])

# 3. Replay it offline.
res = replay_harvest(CrossrefSource(), query, "harvest_archive",
                     harvest_id="H1")
print(len(res.records), "records")
print("checksum matches the published value:", res.checksum_matches)
```

`checksum_matches: True` means you hold exactly the record set the review
analysed. `verify_archive()` returning `[]` means the evidence is byte-identical
to what the API returned.

To check how the database has moved since publication, re-run the live harvest
and diff the manifests:

```python
from corpusslr import compare_harvests, harvest
now = harvest(CrossrefSource(mailto="you@example.org"), query, max_results=60,
              archive="harvest_archive_replication")
diff = compare_harvests("harvest_archive", now,
                        label_before="original", label_after="today")
print(diff.summary())
print(diff.to_markdown())
```

A non-empty `added` list is the expected, healthy result - databases grow. What
matters is that the growth is counted rather than assumed away. If `removed` or
`changed` is non-empty, individual records were retracted, corrected or
re-indexed, and each is listed with the fields that moved.

---

## 6. Limitations

1. **Replay proves the analysis, not the search.** It guarantees that the
   archived responses yield the reported corpus. It cannot prove the API would
   have returned those responses to anybody else at that moment - relevance
   ranking is proprietary and, as §4.1 shows, not even order-stable for the same
   caller.
2. **Neither source supports boolean field search.** Both are *supplementary*
   under Gusenbauer & Haddaway (2020); the block structure is flattened to a
   relevance query and the loss is carried into the PRISMA-S appendix. Archiving
   makes such a search auditable; it does not make it exhaustive.
3. **Semantic Scholar publishes no API version**, so a change in its ranking or
   schema cannot be attributed to a version bump from the manifest alone.
4. **Records without any identifier** align across harvests on normalized title
   plus year. A retitled record therefore appears as one removal plus one
   addition rather than a change.
5. **Abstract text is outside the checksum** (only its presence is hashed).
   Re-wrapped or lightly edited abstracts will not register as drift; if abstract
   wording matters to your screening, diff the raw archives.
6. **Archive size scales with the raw payload**, not the record count. Crossref
   responses embed reference lists, so large harvests produce large archives
   (~17 KB per record here); compress the directory before deposit.
7. **Semantic Scholar's live cross-run stability is unmeasured here.** Only one
   keyless harvest completed; four further attempts at 150 s spacing were all
   refused with 429. The order-stability question answered for Crossref in §4.1
   therefore remains open for Semantic Scholar, and the canonical sort is
   applied to it on the same precautionary grounds rather than on measured
   evidence. Re-run §4.2 with an API key to close this gap.

---

## References

- Gusenbauer, M., & Haddaway, N. R. (2020). Which academic search systems are
  suitable for systematic reviews or meta-analyses? *Research Synthesis
  Methods*, 11(2), 181-217.
- Rethlefsen, M. L., Kirtley, S., Waffenschmidt, S., et al. (2021). PRISMA-S: an
  extension to the PRISMA statement for reporting literature searches in
  systematic reviews. *Systematic Reviews*, 10, 39.
