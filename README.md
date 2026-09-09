# CorpusSLR

**From one structured query to a PRISMA-documented corpus.**

CorpusSLR automates the *identification* phase of systematic literature
reviews: it runs one structured query against multiple bibliographic
databases, harmonizes and enriches the records, deduplicates them with a
fully auditable cascade, and emits the two documents reviewers ask for - 
a **PRISMA 2020 flow diagram** and a **PRISMA-S search-reporting appendix**.

## Why

- No single database achieves acceptable recall: only combinations of
  sources reach ~98% of included studies (Bramer et al., 2017,
  *Systematic Reviews*). Multi-source retrieval is a methodological
  requirement, not a convenience - yet it is still done by hand-merging
  exports.
- Only a subset of search systems qualifies as *principal* for evidence
  synthesis (Gusenbauer & Haddaway, 2020, *Research Synthesis Methods*).
  CorpusSLR flags each source accordingly and marks Crossref results as
  supplementary (non-reproducible boolean search).
- Database coverage is asymmetrically redundant: 99.11% of the journals
  indexed in Web of Science are also in Scopus, while Scopus is the larger
  list and Dimensions larger still - 82.22% more journals than WoS
  (Singh et al., 2021, *Scientometrics* 126:5113-5142). Overlap is therefore
  predictable in direction but not in size for any given topic, so CorpusSLR
  reports an empirical **cross-source overlap matrix** from its own
  deduplication decisions rather than assuming a coverage model.
- Metadata quality is heterogeneous (truncated Scopus abstracts,
  incomplete OpenAlex fields). CorpusSLR ships a per-source **data quality
  report** and an **abstract recovery** step that rebuilds full abstracts
  from the OpenAlex inverted index.
- PRISMA-S (Rethlefsen et al., 2021) requires reporting every source,
  platform, date, full strategy and the deduplication method. CorpusSLR
  records all of it automatically while you search and renders the
  appendix in one call.

## Features (v1.0)

### Retrieval

| Source | Access | Tier | Notes |
|---|---|---|---|
| Scopus | Search API (key + insttoken) | principal | `view="COMPLETE"` returns the full author array, keywords and abstracts; `STANDARD` gives one author and no abstract |
| Web of Science Core Collection | Starter API **or** file export | principal | API: 50 hits/page, no abstracts; export: tagged `.txt`/`.ciw`, RIS, BibTeX, CSV |
| PubMed/MEDLINE | E-utilities (free) | principal | `esearch` history + `efetch` XML, also `.nbib` |
| Embase | file export | principal | RIS with Elsevier tag mapping, CSV |
| Cochrane CENTRAL | file export | principal | RIS, `CN-` accession preserved |
| EBSCOhost (Business Source, PsycINFO, CINAHL, ERIC) | file export | principal | RIS, per-database attribution |
| ProQuest ABI/INFORM | file export | principal | RIS, CSV |
| IEEE Xplore | file export | principal | BibTeX, CSV |
| ACM Digital Library | file export | principal | BibTeX, EndNote XML |
| OpenAlex | free API | supplementary | abstracts as inverted index → reconstructed |
| Crossref | free REST API | supplementary | no reproducible boolean search |
| Semantic Scholar (S2AG) | free API | supplementary | relevance search, optional API key |
| arXiv | free Atom API | supplementary | preprints (PRISMA 2020 grey literature) |
| bioRxiv / medRxiv | free API | supplementary | date-window listing only, terms filtered locally |

One `SearchQuery` (blocks of OR-terms joined with AND, year range, document
types, languages) is compiled to the native syntax of every API backend;
unsupported filters raise explicit warnings that propagate into the PRISMA-S
appendix instead of failing silently.

#### Accessing the two principal APIs

Both require institutional credentials, and both fail in ways that are easy to
misread - the clients turn each into an explanatory error rather than an empty
result.

```python
# Scopus: the key alone is bound to the subscriber's IP range. Off campus it
# returns 401 with the same message as an invalid key, so pass the insttoken.
ScopusSource(api_key=KEY, insttoken=TOKEN, view="COMPLETE")
```

Offset paging is capped at `start + count <= 5000`; the client shrinks the last
page to fit and switches to cursor paging (`use_cursor=True`, the default) to
retrieve larger sets. Page size follows the view automatically - 200 records for
`STANDARD`, 25 for `COMPLETE`, the API maxima.

```python
WosStarterSource(api_key=KEY)          # X-ApiKey header, 50 hits per page
```

The WoS Starter API returns no abstracts; pair it with `recover_abstracts()`.
Keep both secrets in the environment, never in code - Elsevier's terms require
the insttoken to stay server-side and off the URL.

### Parsers (dependency-free)

- **RIS** with vendor-dialect detection: Scopus, Embase, Cochrane CENTRAL,
  EBSCOhost, ProQuest, Web of Science, Zotero, generic - per-dialect tag
  mapping, journal-field priority and PMID/accession extraction.
- **Web of Science** tagged format (`.txt`/`.ciw`), **PubMed `.nbib`**.
- **BibTeX** with LaTeX decoding (accents, stroked letters, escaped literals)
  and IEEE Xplore / ACM dialects.
- **EndNote XML** (style-nested fields, `ref-type` mapping); complete
  `<record>` elements are recovered individually from a truncated file, so an
  interrupted download does not cost the records that arrived intact.
- **EndNote tagged** (`.enw`) - the format the ACM Digital Library actually
  emits from *Export Citation → EndNote*; `%B` supplies the proceedings name
  for conference papers and `%@` is split by shape so an ISBN is never written
  into the `issn` field.
- **Vendor CSV**: Scopus, Web of Science, IEEE Xplore, Dimensions, EBSCO,
  Embase, ProQuest - dialect detected from column headers.
- **HTML-table exports**: ProQuest and Web of Science label their export
  `.xls` but ship either TSV or an HTML `<table>`; the real shape is detected
  from the content and both route through the same vendor column mapping as
  the CSV path.
- **Encoding sniffing** on every `parse_*_file`: byte-order marks, BOM-less
  Windows UTF-16, then UTF-8 → cp1252 → latin-1. A file that is not text at
  all (a PDF or XLSX picked by mistake) is refused and reported rather than
  parsed into garbage records.
- **Auditable rejections** via the optional `report=ParseReport()` argument:
  every dropped input unit is counted with a reason
  (`no_content`/`empty`/`malformed`/`truncated`/`unreadable`), so
  `n_input == len(records) + n_rejected` and the "records identified" figure of
  a PRISMA 2020 flow diagram can be reconciled against the file it came from.

### Methodological instrumentation

- **Source registry** classifying every database as *principal* or
  *supplementary* after Gusenbauer & Haddaway (2020), with a strategy audit
  that warns when a review rests on supplementary sources alone.
- **Cascading deduplication** with a decision-level report: DOI → PMID →
  OpenAlex ID → Scopus ID (transitive, union-find) → multi-round blocking on
  composite field keys (title+pages, author+year+page, journal+volume+page)
  → fuzzy match on
  normalized titles (Ratcliff-Obershelp similarity, year tolerance,
  first-author agreement). Records carrying *conflicting* identifiers are
  never merged, so distinct works with near-identical titles are preserved.
  Merging keeps the richest record and unions identifiers.
- **PRISMA 2020 flow diagram** as dependency-free SVG (+ Markdown/dict), with
  arithmetic validation that rejects negative counts and unbalanced
  full-text accounting.
- **PRISMA-S appendix** in Markdown (or `.docx` with `python-docx`),
  including the source-tier classification and the deduplication method.
- **Data quality report** (field completeness per source) and **abstract
  recovery** via OpenAlex.
- **Exports**: CSV, screening CSV (ASReview/EmbedSLR-ready), RIS, BibTeX
  (entry type follows the document type; spreadsheet formula injection is
  neutralized in CSV output).
- **Scopus CSV as the canonical output** (`to_scopus_csv`, and the default of
  `corpusslr dedup`): the deduplicated corpus is written in the 46-column
  Scopus export layout that `bibliometrix::convert2df(dbsource = "scopus")`,
  VOSviewer and EmbedSLR all read, so a merged multi-database corpus goes into
  a bibliometric analysis without a hand-written conversion. Columns the
  unified schema cannot fill (`Affiliations`, `References`, funding,
  conference) are written **empty, never invented**. Verified by round trip
  through the package's own Scopus parser on a real 14 302-record Scopus
  export: 257 436 field comparisons (18 identifying fields × 14 302 records)
  with **1 mismatch (0.0004 %)** - an abstract beginning with `-`, which
  acquires the leading apostrophe of the CSV-injection defence (bounded at one
  apostrophe; measured stable over four export/re-import cycles). The file was
  then **loaded for real** with
  `bibliometrix::convert2df(dbsource = "scopus", format = "csv")`
  (bibliometrix 5.5.0, R): all 14 302 records survive and `biblioAnalysis`
  reports 14 302 articles / 31 984 authors. Two pre-existing defects were
  found *by* this verification and fixed - a non-idempotent author normaliser
  that corrupted the surname the duplicate cascade compares (31/14 302
  records), and an empty `EID` column, which bibliometrix deduplicates on:
  20 distinct records collapsed to 1 before the fix. See
  [the user guide](docs/user_guide.md#5a-the-canonical-output-scopus-csv).

### Reproducible harvesting

PRISMA-S asks that a search be reportable so it can be repeated. For an
API-native review that is two separate claims, and CorpusSLR treats them
separately:

- **Reproducibility** - a third party re-runs the analysis on the *archived
  evidence* and obtains the identical corpus. `harvest()` writes every raw HTTP
  response to a directory archive (request, status, UTC timestamp, body
  checksum, `manifest.json` index), and the *same* function replays that archive
  with the network unused.
- **Replicability** - the query is re-run against the *live* database later and
  the difference is counted rather than hidden (`compare_harvests()`).

```python
from corpusslr import (CrossrefSource, SearchQuery, compare_harvests, harvest,
                       replay_harvest, verify_archive)

query = SearchQuery(blocks=[["artificial intelligence"], ["marketing"]],
                    years=(2020, 2023), doc_types=["article"])

# 1. Harvest live; every response is archived as evidence.
res = harvest(CrossrefSource(mailto=EMAIL), query, max_results=60,
              archive="harvest_archive")
print(res.checksum)                     # deterministic corpus identifier

# 2. A reviewer verifies and replays it - no API key, no network.
assert verify_archive("harvest_archive") == []
rep = replay_harvest(CrossrefSource(), query, "harvest_archive")
assert rep.checksum_matches

# 3. Six months later: how far has the database moved?
later = harvest(CrossrefSource(mailto=EMAIL), query, max_results=60,
                archive="harvest_archive_2026-12")
print(compare_harvests(res, later).summary())
```

The corpus checksum is deliberately **order-independent** and computed over
*stable* bibliographic fields only (DOI, PMID, normalized title, year, journal,
volume/issue/pages, document type, first-author surname, author count, abstract
presence). Citation counts and open-access flags are excluded and reported
separately, so a re-harvest of an unchanged corpus yields the identical
checksum instead of a false drift alarm. Records are returned in a canonical
order (DOI, then normalized title) rather than in API ranking order.

Why that matters, measured live: repeated identical Crossref requests returned
the **same 40 records in a different order** - only 2 of 5 repeats matched the
reference ordering, and cursor tokens differed between runs. Without the
canonical sort, two harvests of an identical corpus would produce different
checksums and a spurious diff. Credentials never enter the archive (API keys
dropped, contact addresses redacted), so a deposited archive is safe to publish
and replays for somebody holding neither. A harvest that dies mid-way - for
instance on Semantic Scholar's aggressively throttled keyless pool - is closed
out as `mode: "aborted"`, keeping the failed attempts as evidence while refusing
to replay as though it were complete.

See `reproducible_harvesting.md` for the full protocol, the measured stability
figures and a copy-paste "how to repeat this harvest" section for reviewers, and
`examples/example_reproducible_harvest.py` for the complete cycle.

## Install

```bash
pip install corpusslr            # PyPI
pip install corpusslr[docx]      # + .docx appendix support
```

## Command line: one configuration file, one command

Installing the package also installs a `corpusslr` command. It exists because
the two properties a review is judged on - that the search can be *repeated*
(PRISMA-S Items 8, 9 and 13) and that the reported numbers can be *recomputed* - are
properties of an executable artefact, not of prose. Writing the strategy as
data and running it as one command makes both checkable, and it lets the
information specialist who owns the search run it without editing Python.

Describe the review once:

```json
{
  "review": {"title": "AI adoption in SMEs"},

  "query": {
    "blocks": [
      ["artificial intelligence", "machine learning"],
      ["adoption", "acceptance", "implementation"],
      ["SME", "small business", "small firm"]
    ],
    "years": [2015, 2026],
    "doc_types": ["article", "review"],
    "languages": ["en"]
  },

  "databases": [
    {"name": "scopus", "max_results": 2000, "view": "STANDARD"},
    {"name": "openalex", "max_results": 2000},
    {"name": "pubmed", "max_results": 1000},
    {"name": "crossref", "max_results": 500}
  ],

  "files": [
    {"path": "exports/wos_export.txt",
     "database": "Web of Science Core Collection", "platform": "Clarivate",
     "query": "TS=((\"artificial intelligence\") AND (adoption) AND (SME))",
     "date_run": "2026-08-10"},
    {"path": "exports/embase.ris", "database": "Embase",
     "platform": "Elsevier", "date_run": "2026-08-10"}
  ],

  "enrich": {"recover_abstracts": true},
  "dedup": {"fuzzy_threshold": 0.93, "year_tolerance": 1},

  "screening": {
    "records_excluded": 812,
    "reports_not_retrieved": 6,
    "fulltext_exclusions": {"wrong population": 41, "not empirical": 17},
    "studies_included": 64
  },

  "output": {"dir": "review_output", "exports": ["csv", "screening", "ris"]}
}
```

Design the strategy before spending a single API call - `--dry-run` compiles
the query into each backend's native syntax and retrieves nothing:

```bash
export CORPUSSLR_CONTACT_EMAIL=you@uni.edu     # politeness contact
export SCOPUS_API_KEY=...                      # + SCOPUS_INSTTOKEN off campus

corpusslr check   -c review_config.json        # validate, show the plan
corpusslr run     -c review_config.json --dry-run
corpusslr run     -c review_config.json        # the whole review
```

`corpusslr run` produces, in `output.dir`:

| file | what it is |
|------|------------|
| `corpus_raw.json` | every retrieved record + the per-database search events |
| `corpus_unique.json` | the deduplicated corpus with the dedup report attached |
| `dedup_report.csv` | one row per merge decision, with its matching evidence |
| `overlap.md` | cross-source redundancy matrix |
| `prisma2020_flow.svg` | PRISMA 2020 flow diagram (no third-party renderer) |
| `prisma_s_appendix.md` | PRISMA-S appendix: sources, strategies as run, dates, dedup |
| `quality.md`, `quality.csv` | metadata completeness per source |
| `source_audit.md` | principal/supplementary audit after Gusenbauer & Haddaway (2020) |
| `corpus.csv`, `screening.csv`, `corpus.ris` | exports; `screening.csv` feeds ASReview/EmbedSLR |
| `run_summary.json` | every count, the package version and the configuration's SHA-256 |

That last file is what ties a manuscript to its evidence: the checksum of the
configuration that produced the numbers. An edited strategy that was never
re-run shows up as a mismatch instead of going unnoticed.

### Subcommands

| command | does | notes |
|---------|------|-------|
| `check` | validate the configuration, print the compiled plan | no network, no credentials |
| `search` | query the API databases, write a corpus | `--dry-run`, `--keep-going` |
| `parse` | import RIS / BibTeX / CSV / `.nbib` / EndNote XML / WoS tagged | format **and** vendor dialect detected from content, not the extension |
| `dedup` | deduplicate with a full decision log, writing the Scopus CSV | `--fuzzy-threshold`, `--overlap`, `--export-format`, `--no-export` |
| `prisma` | PRISMA 2020 SVG + PRISMA-S appendix | refuses a flow whose arithmetic fails |
| `export` | Scopus CSV / CSV / screening CSV / RIS / BibTeX | `--scopus` is the canonical bibliometrix / VOSviewer input |
| `quality` | per-source metadata completeness | Markdown or `--json` |
| `harvest` | retrieve one database, archiving every raw response | the evidence base |
| `replay` | re-run the archive offline and verify the checksum | no credentials, no network; `--compare` quantifies drift |
| `run` | all of the above from one configuration file | |
| `tui` | guided interface: answers the questions instead of reading a configuration file | standard library only; also `python -m corpusslr.tui` |

Steps also compose, since each writes a corpus the next one reads:

```bash
corpusslr parse exports/*.ris exports/wos_export.txt -o raw.json
corpusslr dedup raw.json -o unique.json --report dedup_report.csv
corpusslr prisma unique.json --records-excluded 812 --studies-included 64 \
          --exclude "wrong population=41" --exclude "not empirical=17"
corpusslr export unique.json --screening screening.csv
```

### Conventions the CLI holds to

- **Exit codes a shell script can branch on**: `0` success, `1` user error
  (bad configuration, unknown database, missing credential or input file),
  `2` data error (unidentifiable export, corrupt archive, failed integrity
  check, API failure, PRISMA flow that does not balance), `3` internal defect.
- **Data on stdout, progress on stderr** - `corpusslr quality unique.json >
  quality.md` and `corpusslr run -c cfg.json | jq .dedup` both work.
  Warnings that change what the numbers *mean* (a skipped database, an
  overflowed blocking bucket) survive `--quiet`.
- **API keys only from the environment** - never from the configuration file,
  never in a log, never in a harvest archive. The file is safe to deposit as
  supplementary material; only the *presence* of a credential is ever
  reported. `SCOPUS_API_KEY` (+ `SCOPUS_INSTTOKEN`), `WOS_API_KEY`,
  `SEMANTIC_SCHOLAR_API_KEY`, `NCBI_API_KEY`, `CORPUSSLR_CONTACT_EMAIL`.
- **Errors explain the remedy.** A missing Scopus key names the variable to
  export and the off-campus insttoken cause; an unrecognised export names the
  formats and the `--format` override; a misspelled `dedup` key is *rejected*
  rather than defaulted, because a threshold that silently reverted would make
  the reported parameters false.
- **Reproducible retrieval**: `corpusslr harvest --archive DIR` stores every
  raw response, and `corpusslr replay --archive DIR` re-derives the identical
  record set offline with no credentials at all - the check a reviewer can run.

A complete example configuration ships as
[`examples/review_config.json`](examples/review_config.json).

## Quickstart

```python
from corpusslr import (SearchQuery, Corpus, ScopusSource, OpenAlexSource,
                       PubMedSource, CrossrefSource, recover_abstracts,
                       deduplicate, PrismaFlow, prisma_s_appendix,
                       quality_markdown, to_screening_csv)

query = SearchQuery(
    blocks=[["artificial intelligence", "machine learning"],
            ["adoption", "implementation"],
            ["SME", "small firm", "small business"]],
    years=(2015, 2026), doc_types=["article", "review"], languages=["en"])

corpus = Corpus()
corpus.add_search(ScopusSource(api_key="...").search(query, max_results=2000))
corpus.add_search(OpenAlexSource(mailto="you@uni.edu").search(query))
corpus.add_search(PubMedSource(email="you@uni.edu").search(query))
corpus.add_search(CrossrefSource(mailto="you@uni.edu").search(query, max_results=500))

recover_abstracts(corpus.records, mailto="you@uni.edu")   # fix truncated abstracts
print(quality_markdown(corpus.records))                    # per-source completeness

result = deduplicate(corpus)                               # auditable cascade
result.report.to_csv("dedup_report.csv")
print(result.report.summary())
print(result.report.overlap_markdown())                    # cross-source redundancy

flow = PrismaFlow.from_dedup(corpus, result)
flow.set_screening(records_excluded=812, reports_not_retrieved=6,
                   fulltext_exclusions={"wrong population": 41,
                                        "not empirical": 17},
                   studies_included=64)
assert flow.validate() == []
flow.to_svg("prisma2020_flow.svg")

prisma_s_appendix(corpus, result, "prisma_s_appendix.md")
to_screening_csv(result.records, "screening.csv")          # ASReview / EmbedSLR
```

Adding file exports from databases without an open API:

```python
from corpusslr import parse_wos_file, parse_ris_file

corpus.add_records(parse_wos_file("wos_export.txt"),
                   database="Web of Science Core Collection",
                   platform="Clarivate", interface="Web interface export",
                   query="TS=(...)", date_run="2026-08-10")
corpus.add_records(parse_ris_file("embase.ris"),        # dialect auto-detected
                   database="Embase", platform="Elsevier",
                   interface="Web interface export", date_run="2026-08-10")
```

## Validation

Deduplication is validated on two levels: a published biomedical gold standard
(below) and an identifier-blind cross-disciplinary study covering biomedicine,
computer science, management and economics (7,440 records harvested from 5
databases, 7,187 evaluated after document-type curation - 
see [`validation/multidomain_validation.md`](validation/multidomain_validation.md)).
The cross-disciplinary study found that the 0.93 default needs no per-discipline
tuning (argmax gain ≤0.006 in every field) and that the biomedical arm is not the
strongest, so the defaults are not fitted to biomedical conventions.

Deduplication is validated against the ASySD gold-standard *Diabetes* dataset
(N = 1845; 1261 true duplicates, 584 unique), the benchmark published with
Hair et al. (2023, *BMC Biology* 21:189). Metrics are computed at record level
following that paper's definition; the implementation is verified by recomputing
the paper's own "Human" row from the dataset's reviewer decisions (F1 0.826 vs
0.828 published).

Two metrics are reported, because they answer different questions. *Clustering*
asks whether the right records were identified as duplicates - the property the
published comparators were scored on. *End-to-end* additionally requires the
surviving record to be the copy the reviewers kept, which is stricter than the
published figures.

| method | metric | FP | FN | F1 |
|---|---|---:|---:|---:|
| **CorpusSLR 1.0** | clustering | **0** | **1** | **0.9996** |
| ASySD | published | 0 | 2 | 0.999 |
| **CorpusSLR 1.0** | end-to-end | 18 | 19 | **0.9853** |
| EndNote | published | 0 | 43 | 0.983 |
| SRA-DM | published | 70 | 114 | 0.926 |
| human reviewers | published | 3 | 368 | 0.828 |

CorpusSLR 1.0 matches ASySD's precision (no false positives) and finds one more
true duplicate than it does. Under an assignment rule that does not require
exactly one gold-marked keeper per cluster - two groups in the benchmark have
none or two - the clustering is exactly right: F1 1.0000, no errors on 1845
records.

Five mechanisms account for the improvement over 1.1 (F1 0.993), each correcting
a distinct class of error found by inspecting every residual mistake:

| mechanism | error it fixes | FP | FN |
|---|---|---:|---:|
| 1.1 mechanisms only | - | 10 | 8 |
| + locus guard | one supplement-wide DOI spanning many abstracts | 2 | 6 |
| + multi-round blocking | title truncated by an export | 2 | 4 |
| + DOI percent-decoding | `%28`/`%29` from a URL-serialised PII | 2 | 3 |
| + co-publication override | one work with two publisher DOIs | 2 | 2 |
| + conference/article split | abstract and article are separate reports | **0** | **1** |

Measured as a single-pass ablation on 1.0.0, switching one mechanism on per row.
Two further repairs act at normalization and cannot be switched off by
parameter, so they are present in every row: spreadsheet-damaged page ranges
(`11-Sep` and `Nov-19` are one range; 38 of 1845 records) and article-number
padding (`137960` = `e0137960`).

The last one follows Cochrane and ASySD practice; set
`separate_conference=False` for one-record-per-study behaviour.

The end-to-end figure assumes records are added in search order, as a reference
manager would: the surviving record is the first copy encountered, which matches
the reviewers' choice in 98% of clusters. That metric is inherently
order-dependent, because the gold standard marks the copy from the
first-searched database as the one to keep - 0.9853 in search order, 0.840 when
the input is grouped by duplicate cluster, and 0.715 (mean of three seeds) when
it is randomly shuffled. No data is lost in any ordering: empty fields are
filled from the removed copies and conflicting fields are resolved by majority
across the cluster.

Deduplication scales close to linearly: 60 000 records take 9.6 s (titles
sharing one opening) to 25.3 s (mixed vocabulary), peaking at 109 MB and 310 MB.
Cost per record is not perfectly flat - it grows 1.11x (shared opening) to 1.62x
(mixed vocabulary) as the corpus goes from 6 000 to 60 000 records, because a
larger corpus puts more records in each token block. Two mechanisms keep the fuzzy
stage off the critical path, and their contributions are very different when
measured separately: memoising the normalized title is worth **7.0-8.0x**
(7.14x at 6 000 records with mixed vocabulary, 7.24x at 4 000 with a narrow
one), while the exact length bound that rejects a pair before the sequence
matcher runs is **within noise of 1x** on both corpus shapes - it is retained
because it is a proven necessary condition that cannot change a result, not
because it is a measured speed-up. Full report,
reproduction script and the calibration and performance data are in
[`validation/`](validation/).

```bash
python -m pytest tests -q                 # 2111 offline tests, 98% coverage
python validation/eval_asysd.py --gold validation/labelled_test_set.csv
```

## If you would rather not write a configuration file

Two entry points exist for reviewers who do not write Python. Both produce the
same `review.json` that `corpusslr run -c` consumes, so a review started from
either is afterwards indistinguishable from one written by hand - rerunnable,
diffable and depositable. Both read API keys through `getpass` and never write
one into a configuration file, a report or a log.

**A guided terminal menu.** Choose databases from a numbered list, type the
query as blocks, set keys, inspect the plan, run:

```bash
corpusslr tui            # or: python -m corpusslr.tui
```

Standard library only - no `curses`, no `rich`, no ANSI colour, wrapped to 78
columns, so it works over `ssh` into a minimal container and with a screen
reader. Keys are stored at `$XDG_CONFIG_HOME/corpusslr/credentials.json` with
mode `0600` and are injected into the environment only while a run is
executing. Errors say what to do next; a reviewer never has to read a Python
traceback to continue.

**A Google Colab notebook.** [`notebooks/corpusslr_colab.ipynb`](notebooks/corpusslr_colab.ipynb)
walks through a whole review cell by cell - install, keys, databases, query,
plan, run, counts, Scopus CSV, PRISMA-S appendix, download - with markdown
cells explaining *why* each step matters, so it teaches the methodology rather
than only automating the clicks. It ships unexecuted: every code cell carries
an empty output list, because a stored output is where a printed key would be
preserved. Regenerate it with `python tools/build_colab_notebook.py`.

## Documentation

[`docs/user_guide.md`](docs/user_guide.md) walks through a complete review:
compiling one strategy to each database's syntax, importing file exports with a
reconcilable record count, deduplicating with a decision log, and producing the
PRISMA 2020 diagram and PRISMA-S appendix. Every example in it is executed by
`tests/test_docs_examples.py`, so a documented call that stops working fails the
suite. The guide's last section states what the library deliberately does not do
 - thesaurus expansion, screening, `.xlsx` parsing - so the boundary is explicit
before you build a protocol on it.

## Roadmap (v2.0)

Web of Science Expanded API (abstracts, 100 hits/page) and Scopus Advanced view; native Embase
(Elsevier API) retrieval; controlled-vocabulary expansion (MeSH, Emtree);
citation-based snowballing; screening-decision import from ASReview and
Rayyan; validation on the remaining ASySD gold-standard datasets
(Neuroimaging, Cardiac, Depression, SRSR).

## Cite

See `CITATION.cff`. A software paper describing CorpusSLR has been
submitted to *SoftwareX*.

## Development, testing and citation metadata

Continuous integration runs on every push and pull request:

| Workflow | What it checks |
|---|---|
| `.github/workflows/tests.yml` | Full suite on Python 3.9, 3.10, 3.11, 3.12 and 3.13, with the `docx` extra installed so the PRISMA-S `.docx` test runs rather than being skipped; coverage measured with a 95 % floor; `python -m build` plus `twine check --strict`; the built wheel installed into a clean interpreter and imported; the suite re-run from the unpacked sdist |
| `.github/workflows/quality.yml` | `ruff check` and `mypy`, both configured in `pyproject.toml` so a local run matches CI |

The suite is offline by construction and by enforcement: `tools/no_network.py`
replaces the standard library's socket connect primitives with raising stubs, so
a test that reaches a bibliographic API fails instead of passing on a machine
that happens to be online.

Two CLI tests covering the optional YAML configuration format skip unless PyYAML
is present. PyYAML is deliberately not a dependency - the CLI reads JSON
configuration from the standard library - so those two tests are skipped in CI as
well; install PyYAML locally if you are changing that code path.

```sh
python -m pip install -e ".[docx,dev]"
python -m pytest tests                                  # offline, deterministic
PYTHONPATH=. python -m pytest tests -p tools.no_network  # with the network blocked
python -m ruff check . && python -m mypy corpusslr       # both report nothing
```

Version, licence, author and repository URL are declared in five files - 
`pyproject.toml`, `corpusslr/__init__.py`, `CITATION.cff`, `codemeta.json` and
`.zenodo.json` - and `tests/test_metadata_consistency.py` fails if any of them
disagree. A release whose metadata has drifted mints a DOI against a version
string that no installed artefact reports, which makes every later citation of
that DOI wrong.

`CHANGELOG.md` documents the version history in
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) form; `CONTRIBUTING.md`
describes the conventions, including why Python 3.9 support is a hard
requirement and why no test may touch the network.

## License

MIT © 2026 Sebastian Matysik
