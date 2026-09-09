# CorpusSLR user guide

Every command and code block in this guide is executed by
`tests/test_docs_examples.py`, so an example that stops working fails the test
suite rather than misleading a reader.

## 1. Install

```bash
pip install corpusslr                 # core: requests only
pip install "corpusslr[docx]"         # adds the .docx PRISMA-S appendix
```

Python 3.9 or newer. The library has one required dependency (`requests`); the
test suite runs entirely offline.

## 2. The shape of a review

A systematic review's identification phase has four obligations, and CorpusSLR
maps one step onto each:

| obligation | step |
|---|---|
| search several databases with one strategy | `SearchQuery` compiled per database |
| record what was searched, where, when | `Corpus` of `SearchEvent`s |
| remove duplicates defensibly | `deduplicate()` with a decision log |
| report all of it | PRISMA 2020 diagram + PRISMA-S appendix |

## 3. First review, from Python

```python
from corpusslr import (Corpus, OpenAlexSource, SearchQuery, deduplicate,
                       prisma_s_markdown, to_screening_csv)

query = SearchQuery(
    blocks=[["artificial intelligence", "machine learning"],
            ["adoption", "acceptance"],
            ["SME", "small firm"]],
    years=(2015, 2026),
    doc_types=["article", "review"],
    languages=["en"],
)

# Blocks are AND-ed; terms inside a block are OR-ed. Inspect the compiled
# strategy before spending a quota - this string is what PRISMA-S item 8 asks
# you to publish.
print(query.to_scopus())
print(query.to_pubmed())
```

Retrieval, then provenance:

```python
corpus = Corpus()
result = OpenAlexSource(mailto="you@example.org").search(query, max_results=200)
corpus.add_search(result)          # records + the SearchEvent in one call
```

`add_search` is preferred over `add_records`: it carries the event the source
reports (database, platform, interface, the query as executed, the date, the hit
count), which is exactly what the appendix needs. Use `add_records` only for file
exports, where you supply that metadata yourself.

## 4. Databases without an API

Web of Science, Embase, EBSCOhost, ProQuest, Cochrane CENTRAL and the rest are
exported by hand and imported by file. Format and dialect are detected from
content, not from the extension - which is frequently wrong, since ProQuest
labels an HTML table `.xls` and the ACM Digital Library labels a tagged text
file "EndNote".

```python
from corpusslr import ParseReport, parse_ris_file

report = ParseReport()
records = parse_ris_file("embase_export.ris", report=report)
print(report.summary())
assert report.n_input == len(records) + report.n_rejected
```

**Always pass a `report`.** Every parser must reject some input - a stanza with
no title and no identifier carries nothing screenable - and the number you put in
the PRISMA diagram as "records identified" has to be reconcilable against the
file. Without a report, rejections are invisible.

## 5. Deduplication

```python
from corpusslr import deduplicate

res = deduplicate(corpus)
print(res.report.summary())
res.report.to_csv("dedup_decisions.csv")     # one row per merge, with evidence
```

The defaults are validated and need no tuning: the fuzzy threshold of 0.93 was
calibrated on a published gold standard and re-checked on four disciplines, where
the best threshold was never more than 0.006 F1 above it.

Parameters worth knowing:

| parameter | default | when to change it |
|---|---|---|
| `fuzzy_threshold` | 0.93 | lower only if your exports truncate titles |
| `year_tolerance` | 1 | raise for corpora mixing online-first and issue years |
| `separate_conference` | `True` | set `False` for one-record-per-study behaviour |
| `id_title_min` | 0.50 | 0.0 restores unconditional identifier matching |

Reading the report matters as much as running it:

```python
rep = res.report
rep.removed                  # how many records were merged away
rep.by_method                # which stage found each duplicate
rep.id_links_rejected        # shared identifiers refused as evidence
rep.by_locus                 # pairs separated by a differing field
rep.overlap                  # cross-source overlap, per database pair
```

`id_links_rejected` is not a warning: publishers assign one DOI to an entire
conference supplement, so a shared DOI is evidence only when the titles agree
too.

## 5a. The canonical output: Scopus CSV

Deduplication is not the end of a review; it is the hand-off to a bibliometric
analysis. The three tools reviewers use downstream - **bibliometrix** (R),
**VOSviewer** and **EmbedSLR** - all read the *Scopus CSV export* layout, so
that is what CorpusSLR writes by default once the corpus is deduplicated.

```python
from corpusslr import deduplicate, to_scopus_csv

res = deduplicate(corpus)
to_scopus_csv(res.records, "corpus_scopus.csv")
```

From the command line the file is produced by `dedup` itself - no second step:

```bash
corpusslr dedup corpus_raw.json -o corpus_unique.json -C out/
# out/corpus_scopus.csv   <- the bibliometrix / VOSviewer / EmbedSLR input
```

Pick a different format with `--export-format` (repeatable: `scopus`, `csv`,
`screening`, `ris`, `bibtex`), or suppress the export with `--no-export`:

```bash
corpusslr dedup corpus_raw.json -C out/ --export-format ris --export-format bibtex
corpusslr dedup corpus_raw.json -C out/ --no-export
corpusslr export corpus_unique.json --scopus my_corpus.csv   # any time, later
```

In R the file goes straight into bibliometrix:

```r
library(bibliometrix)
M <- convert2df("corpus_scopus.csv", dbsource = "scopus", format = "csv")
results <- biblioAnalysis(M)
```

In VOSviewer: *Create → Map from bibliographic data → Read data from
bibliographic database files → Scopus tab → corpus_scopus.csv*.

### What the file contains, and what it deliberately does not

All 46 columns of a genuine Scopus export are written, in the vendor's own
order (`corpusslr.SCOPUS_COLUMNS`), because `convert2df` addresses columns by
name and treats a *missing* column as an error while reporting an *empty* one
as missing data. Columns the unified record schema cannot fill - 
`Affiliations`, `Authors with affiliations`, `References`, the funding and
conference blocks, `Art. No.`, `CODEN`, `ISBN` - are written **empty and never
invented**. This has a consequence worth planning for: bibliometrix analyses
that need affiliations (country collaboration maps) or the reference list
(co-citation, historiographs) cannot run on a corpus assembled from sources
that do not supply those fields. Records harvested from Scopus or Web of
Science carry them; Crossref and arXiv records do not.

### The `EID` column is never empty, and why that matters

`convert2df` does not merely *read* the EID column - for the CSV format it
sets `id_field <- "UT"` (fed from `EID`) and applies
`duplicated(M[id_field])`, dropping every row whose value repeats. An empty
EID is a value like any other, so **a corpus from sources that assign no
Scopus identifier would collapse to a single record.** Measured: 20 records
with 20 distinct titles and 20 distinct DOIs but no EID produced
`Removed 19 duplicated documents` and one surviving row.

CorpusSLR therefore writes a *derived, namespaced* key when a record has no
Scopus identifier - `corpusslr:10.1016/j.jbusres.2024.001`, or a
`corpusslr:pmid:` / `corpusslr:openalex:` / `corpusslr:srcid:` /
`corpusslr:sha1:` fallback. It is deliberately impossible to mistake for a
real EID (`2-s2.0-…`), it is derived from the metadata rather than from the
corpus-local `uid` so the same work exported twice yields the same key, and
`parse_csv_export` strips it back out of `scopus_id` on re-import so a
surrogate is never treated as identifier evidence by the duplicate cascade.

### Which bibliometrix analyses a merged corpus can and cannot support

Measured on a real 14 302-record corpus exported through `to_scopus_csv` and
loaded with bibliometrix 5.5.0:

| analysis | status | why |
|---|---|---|
| `biblioAnalysis` / `summary` | works - 14 302 articles, 31 984 authors | core fields present |
| author collaboration network | works - 31 984 nodes | `AU` filled |
| author-keyword co-occurrence | works - 40 152 nodes | `DE` filled |
| index-keyword co-occurrence | **0 nodes** | `ID` empty: the record schema holds one merged keyword list |
| co-citation / historiograph | **0 nodes** | `CR` empty: reference lists are not retained |
| country / organisation collaboration | **unavailable** | `C1` empty: affiliations are not retained |
| page-count field (`PP`) | empty | bibliometrix maps `PP` from `Page count`, which is a length, not the range; the range itself is preserved in `Page start`/`Page end` |

The empty ones are honest missing data, not a formatting defect: filling them
would mean inventing affiliations and reference lists. If your review needs a
country-collaboration map, harvest from Scopus or Web of Science, which supply
those fields, and note that CorpusSLR's unified record schema does not yet
carry them.

Three conversions are lossy in the direction the format itself is lossy, and
are documented rather than hidden:

* `open_access=False` becomes an empty cell - a Scopus export marks open
  access and says nothing about closed access, so reading the file back yields
  "unknown", not `False`.
* keywords are written to `Author Keywords` only. A `Record` holds one merged
  keyword list; writing it into `Index Keywords` as well would assert that
  Scopus indexed those terms.
* `Source` carries the record's own provenance (`Crossref`, `PubMed`, …), not
  the constant `Scopus` a real download prints there. A merged corpus is not a
  Scopus download and must not claim to be one.

Every cell is neutralised against spreadsheet formula injection: a title
beginning `=`, `+`, `-` or `@` is prefixed with an apostrophe, so it stays
readable but cannot execute when the corpus is opened in Excel or Sheets.

## 6. Reporting

```python
from corpusslr import PrismaFlow, prisma_s_markdown

flow = PrismaFlow(
    db_counts=corpus.identified_by_source(),
    duplicates_removed=res.report.removed,
    dedup_by_method=dict(res.report.by_method),
    records_excluded=850,
    fulltext_exclusions={"wrong population": 40, "no empirical data": 25},
    studies_included=63,
    reports_included=63,
)
problems = flow.validate()          # arithmetic that cannot hold is listed here
assert not problems, problems
flow.to_svg("prisma_flow.svg")

open("prisma_s.md", "w").write(prisma_s_markdown(corpus, res))
```

`validate()` is not decoration. It rejects negative counts and checks the
full-text balance unconditionally, including when zero studies were included - a
review that includes nothing still has to account for what it assessed.

The appendix reports the principal/supplementary classification of every source,
and flags any tier that does not rest directly on the assessment it cites, so the
methods section can attribute the classification accurately.

## 7. Reproducibility for a reviewer

```python
from corpusslr import HarvestArchive, replay_harvest, verify_archive

from corpusslr import harvest

archive = HarvestArchive.create("harvest_2026-08")
res = harvest(OpenAlexSource(mailto="you@example.org"), query,
              archive=archive)

print(verify_archive("harvest_2026-08"))     # [] means manifest + checksums agree
replayed = replay_harvest(OpenAlexSource(), query, "harvest_2026-08")
assert replayed.checksum == res.checksum     # offline, no API call
```

The checksum is independent of record order and of citation counts, so a replay
months later still matches even though the databases have moved on. Deposit the
archive with the review and a reviewer can confirm the corpus is the one you
describe.

## 8. Credentials

Keys live in the environment, never in a configuration file and never in a log:

```bash
export SCOPUS_API_KEY=...        # Scopus Search API
export SCOPUS_INSTTOKEN=...      # required off the subscriber's IP range
export WOS_API_KEY=...           # Web of Science Starter API
```

OpenAlex, Crossref, PubMed, arXiv, bioRxiv and medRxiv need no key. Supplying a
contact address to the keyless services is polite and raises your rate limit;
CorpusSLR records that an address was sent, since it is part of the request as
executed.

## 9. What this library does not do

- **No thesaurus expansion.** Blocks are compiled literally: no MeSH or Emtree
  explosion, no stemming. A librarian-designed strategy will outperform a
  compiled one in biomedical databases; use CorpusSLR to execute and document a
  strategy, not to design one.
- **No screening.** Export a screening CSV and use ASReview, Rayyan or
  EmbedSLR. CorpusSLR ends where title/abstract screening begins.
- **No true Excel parsing.** `.xlsx` and legacy OLE2 `.xls` are detected and
  reported as unreadable rather than mis-parsed; export CSV instead.
- **bioRxiv/medRxiv are not boolean-searchable.** Their API lists a date window;
  query terms are applied locally as substring matches, which is recorded in the
  search event and therefore in the appendix.
