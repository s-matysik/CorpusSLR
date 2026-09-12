% CorpusSLR - SoftwareX manuscript draft
% Generated 2026-08-19 from measured values; every number in this
% file is taken from validation/*.csv or from a live measurement recorded in the
% audit report. Do not edit numbers by hand - regenerate.

# CorpusSLR: from one structured query to a PRISMA-compliant, deduplicated corpus

## Metadata

| Nr | Code metadata description | Value |
|---|---|---|
| C1 | Current code version | 1.0.0 |
| C2 | Permanent link to code/repository used for this code version | https://github.com/s-matysik/CorpusSLR |
| C3 | Permanent link to Reproducible Capsule | notebooks/corpusslr_colab.ipynb in the repository, a 26-cell Google Colab notebook running the whole workflow |
| C4 | Legal Code License | MIT License |
| C5 | Code versioning system used | git |
| C6 | Software code languages, tools, and services used | Python (>= 3.9) |
| C7 | Compilation requirements, operating environments and dependencies | Pure Python, no compilation. Runtime dependency: requests >= 2.28. Optional: python-docx >= 1.1 for the .docx appendix. Development: pytest, pytest-cov. OS independent |
| C8 | If available, link to developer documentation/manual | docs/user_guide.md and docs/api_reference.md in the repository |
| C9 | Support email for questions | Via the repository issue tracker |

## 1. Motivation and significance

A systematic literature review stands or falls on its search, in medicine and equally in fields that adopted the method later, such as software engineering [1]. Two decades of
methodological work have established that a search resting on a single
bibliographic database does not achieve acceptable recall: in a prospective
sample of 58 published reviews covering 1,746 relevant references,
Bramer et al. [2] found that adequate recall required the
*combination* of Embase, MEDLINE, Web of Science Core Collection and Google
Scholar, which together reached 98.3% overall recall and 100% recall in 72% of
the reviews. Sixteen per cent of included references (291 articles) were found
in one database only. The same study estimated that roughly 60% of published
reviews fail to retrieve 95% of the available relevant literature, mostly
because they omit important databases.

Automation is already used by review teams [3], but the established tools address the stage after retrieval: screening applications such as Rayyan [4] and libraries such as revtools [5] take a corpus as given, and review workbenches administer the protocol and the screening decisions around a corpus that is already assembled [6,7].

Multi-database searching is a methodological requirement, not a convenience, and it is where the practical work lies: the databases disagree about query syntax, field semantics, pagination and export format, and a review team pays for each disagreement in manual effort or in silently lost records.

The systems also differ in what they cover and how selectively: Singh et al. [8] report that 99.11% of the journals indexed in Web of Science are also indexed in Scopus, so the two are far from interchangeable and the containment is markedly asymmetric; a comparison of five sources at scale reports the same kind of disagreement [9].

Reporting requirements have tightened in parallel. PRISMA 2020 [10] requires a flow diagram accounting for every
record from identification to inclusion, and its search extension PRISMA-S [11] requires each database to be reported with
its platform and interface, the date it was run, the full strategy as executed,
the per-database result counts, and a description of the deduplication method.
Assembling that appendix by hand, after the fact, from screening spreadsheets is
error-prone and is a common source of reviewer objections.

CorpusSLR addresses the whole chain in one dependency-light library (Table 1): one
structured query object compiles to each database's own syntax, records arrive
through native APIs or through parsers for the file exports of databases that
have no open API, deduplication is cascading and fully auditable, and the
PRISMA 2020 diagram and PRISMA-S appendix are generated from the recorded
provenance rather than reconstructed afterwards.

## 2. Software description

### 2.1 Architecture

A `SearchQuery` holds blocks of synonyms, a year range, document types and
languages, and compiles to Scopus, PubMed, OpenAlex, Crossref, Semantic Scholar,
arXiv and Web of Science syntax. Anything it cannot express faithfully in a
given dialect produces a warning that is carried into the PRISMA-S appendix, so
that a compilation compromise is reported rather than hidden.

A `Corpus` records every `SearchEvent` - database, platform, interface, query as
executed, date, hit count - because these are exactly the PRISMA-S items. Records
are normalised `Record` dataclasses: DOIs are lowercased, percent-decoded and
stripped of resolver prefixes; titles are transliterated before Unicode
decomposition so that stroked and ligature letters (ł, ø, ß, đ) survive
normalisation instead of collapsing into gaps.

### 2.2 Retrieval and parsing

Ten API client classes cover the systems reachable programmatically, nine of which are selectable as databases from the command line; databases without an open API are supported through their file exports, which is where most of the engineering effort sits - encodings, dialects and vendor quirks that quietly drop records.

Import accounting is a correctness property: every parser maintains the invariant that inputs read equals records returned plus rejections counted with a reason, so the number entering a PRISMA diagram can be reconciled against the file it came from. Four silent-loss defects were found this way - a UTF-16 export yielding zero records, a truncated tagged export losing the whole file, one oversized field aborting a table, and a preprint client stopping after the first page.

The source registry classifies each database as principal or supplementary
following Gusenbauer and Haddaway [12], and records *how* each
classification is evidenced: named in their principal list, inherited from an
access platform they assessed, or - for IEEE Xplore - following
discipline-specific guidance that their assessment does not support. A strategy
audit warns when a corpus rests on no principal system, on exactly one, or is
dominated by supplementary records, and emits reporting notes for tiers that
need qualification in the methods section.

### 2.3 Deduplication: what is standard and what is not

The core is textbook and is not claimed as a contribution: DOI normalization,
title-token blocking, Ratcliff-Obershelp similarity, union-find for transitive
closure. Multi-round blocking is taken from ASySD [13]; blocking itself is a general entity-resolution device, available as a standalone package [14]. The problem is under active attention elsewhere [15] and credited as such in
the source.

What is new is *negative evidence*: typed, logged separators that refuse a
merge the positive evidence would otherwise allow. The contrast with ASySD
is specific rather than rhetorical. Read from its source, its rule decides a
pair by a disjunction of 23 clauses over per-field Jaro-Winkler
similarities, and it already carries two separators of its own, a
mismatching DOI and a year gap greater than one; its DOI clause also
requires author and title agreement, so a shared identifier is not decisive
there either. What it does not model is the bibliographic locus, page fields
mangled by a spreadsheet round trip, pseudo page ranges, a conference
version against a journal version, or the instalment markers of a recurring
publication. Each separator below was derived from a failure observed in a
real corpus rather than postulated:

Transcribing that rule set and asking both about identical candidate pairs
(`validation/compare_asysd_rule.py`) quantifies it across the fifteen
disciplines: median pairwise F1 0.9164 against 0.9510, ours higher in 13 of
15. Neither dominates; the operating points differ, median recall 0.861
against 0.964 at median precision 0.974 against 0.962. Two caveats bound
that. Only the automatic decision is compared, and 424 of the 473 pairs the
published rule leaves behind (89.6%) fall in the set it routes to manual
review, 2,974 pairs for a human to inspect here. Its scoring of a field
absent on both sides as agreement admits 68 of its 78 false merges, but
forcing those to no-evidence would cost 575 true pairs, so that policy buys
recall rather than being a defect. On the biomedical gold standard the two
sit within 0.0006 F1, so this is about where each rule was tuned, not a
ranking.

1. **A missing-value literal is not an identifier.** Exports write "no DOI" as
   a literal - R writes `NA`, others `N/A`, `NULL`, `-`. Accepting those as
   identifiers makes every such record a duplicate of every other. In the ASySD
   Diabetes file, 492 of 1,845 records (26.7%) shared the key `na`.
2. **A shared identifier is refused when the records sit at different places in
   the volume** (locus guard). One conference-supplement DOI can span an entire
   session of distinct abstracts.
3. **Conflicting identifiers block a merge**, so a paper's Part 1 and Part 2 are
   not fused when a fuzzy title match would otherwise join them.
4. **A title that is only an identifier does not drive similarity.** Some
   publishers deposit the DOI into the title field; two such strings from one
   issue differ in their last digits and score ~0.95.
5. **Instalments of a recurring publication are separated** by the marker naming
   the instalment - the only thing distinguishing consecutive quarters of an
   agency report series.

Each guard's contribution is measured by disabling it and rescoring (Table 2, Figure 1),
and the measurement itself carries the finding: **which guard matters depends on
the corpus**. On the biomedical gold standard the title-guarded identifier match
dominates; on the fifteen-discipline corpora the locus guard is worth an order
of magnitude more (ΔF1 0.024 against 0.001). A package validated on one
benchmark would have shipped the wrong defaults.

**Table 2.** Contribution of each deduplication mechanism, measured by switching it off and rescoring. Values are F1 lost relative to the shipped defaults, on the ASySD gold standard and on the fifteen-discipline corpus. The ranking inverts between them, which is the argument for validating on more than one benchmark. Data: measurements in `validation/dedup_mechanism_ablation.csv` and `validation/dedup_ablation_domains.csv`.

| Mechanism | Origin | dF1 gold | dF1 15 disciplines |
|---|---|---:|---:|
| identifier guarded by title | this work | 0.0028 | 0.0000 |
| shared-locus guard | this work | 0.0012 | 0.0242 |
| multi-round blocking | ASySD [13] | 0.0008 | 0.0028 |
| conflicting-identifier override | this work | 0.0004 | 0.0000 |
| conference/article separation | this work | 0.0004 | 0.0000 |

![](fig_ablation.png)

**Figure 1.** Contribution of each deduplication mechanism, measured by
switching it off and rescoring. Bars are F1 lost. Multi-round blocking (†) is
borrowed from ASySD; the other four are contributed here. The ranking inverts
between the two corpora, which is the argument for validating on more than one.

### 2.4 Reporting and reproducibility

Outputs are the PRISMA 2020 flow diagram (SVG), the PRISMA-S appendix (Markdown
or .docx), a per-source metadata completeness report, an empirical cross-source
overlap matrix, the full deduplication decision log, and exports to CSV,
screening CSV, RIS and BibTeX. A harvest layer archives raw API responses with a
manifest and an order-independent checksum, so that a reviewer can replay a
search and verify that the corpus is the one the review describes.

### 2.5 The canonical output: Scopus CSV

A review does not end at a deduplicated corpus; it continues into screening and
bibliometric analysis, and those tools read one dialect. CorpusSLR therefore
writes the merged corpus in Scopus export layout (46 columns, the vendor order,
verified byte-identical against the header of four real Scopus downloads), which
is the input format of bibliometrix, VOSviewer and
EmbedSLR [16,17] alike. The last of these is the immediate reuse
path: it screens a Scopus-layout corpus by sentence embeddings, so this
library's output is its input with no intermediate conversion.
Bibliographic analysis of the same file is served by packages such as
TechMiner [18].

The claim is verified by execution rather than by column list.
`bibliometrix::convert2df(dbsource="scopus")` imported a 14,302-record corpus
written by `to_scopus_csv()` as 14,302 rows with no record dropped, and
`biblioAnalysis()` reported 31,984 authors on it. Doing this found a defect that
a column-presence check cannot see: bibliometrix keys record identity on `EID`
and applies `duplicated()` to it, so an *empty* EID makes every record a repeat
of the first. Twenty distinct records collapsed to one. CorpusSLR now mints a
deterministic surrogate EID from the record's identifiers, and the same twenty
survive as twenty.

Columns with no counterpart in the harvested metadata - index keywords,
references - are written empty rather than invented. An empty column is missing
data the analyst can see; a fabricated affiliation or reference list is a false
finding inside someone else's co-citation network.

### 2.6 Two interfaces for researchers who do not write Python

`python -m corpusslr` opens a guided terminal menu built on the standard library
alone: no curses, no third-party console library, no ANSI colour, 80 columns.
It walks the user through database selection, query construction, API keys
(read with `getpass`, stored 0600, never echoed), a dry-run plan, retrieval and
export. A Colab notebook covers the same workflow in 26 cells for users without
a local Python installation.

## 3. Illustrative examples

### 3.1 Deduplication against a published gold standard

The deduplication was evaluated on the labelled *Diabetes* set of
Hair et al. [13] (1,845 records, 1,261 duplicates, 584 unique
works), the benchmark that study uses for ASySD, EndNote [19], SRA-DM [20] and human
reviewers (Table 3).

**Table 3.** Deduplication accuracy on the ASySD *Diabetes* gold standard
(N = 1,845). Rows for other tools are as published by Hair et al. (2023) on the
same data; recall and F1 for those rows are recomputed from their published
confusion matrices, since the paper reports precision and F1 only.

| Method | FP | FN | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|
| **CorpusSLR 1.0** | **0** | **1** | **1.0000** | **0.9992** | **0.9996** |
| ASySD | 0 | 2 | 1.000 | 0.9984 | 0.999 |
| EndNote | 0 | 43 | 1.000 | 0.9659 | 0.983 |
| SRA-DM | 70 | 114 | 0.942 | 0.9096 | 0.926 |
| Human reviewers | 3 | 368 | 0.997 | 0.7082 | 0.828 |

The 1.7 row is below the 0.9996 reported for 1.3, and the difference is informative: rejecting the literal `NA` as an identifier removed 492 spurious links, and four true duplicates previously merged *through* them must now be found on title evidence alone. The earlier figure was partly an artefact.

Comparator rows are as published; precision and F1 are their reported values,
recall is recomputed from their confusion matrices because the source does not
tabulate it. CorpusSLR finds one more true duplicate than ASySD with no false
positives. Its remaining error is a cluster the gold standard splits between a
journal article and its conference abstract.

Two of the five error classes fixed to reach this level were not threshold
problems but normalisation defects that no amount of tuning would have removed:
percent-encoded DOIs creating a second identity for the same work, and page
fields carrying an article length rather than a location.

### 3.2 Transfer across fifteen disciplines

Accuracy measured on one biomedical benchmark says nothing about a review in
history or logistics, and no labelled duplicate set exists for most fields. The
protocol therefore builds ground truth from the one arbiter every database
agrees on - the normalized DOI - and then **deletes every identifier field**, so
deduplication must reconstruct the clusters from title, authors, year and
bibliographic coordinates alone.

Fifteen disciplines were harvested live from four databases, two queries each:
13,809 records and 2,584 judgeable pairs. Median pairwise F1 is 0.9592 and every
discipline scores above 0.85 (Table 4, Figure 2, left).

What the errors are matters more than the aggregate. Of 154 false merges, 141
are version variants of one study - a preprint and its published article, two
revisions of one deposit, two editions of a chapter - and only **13 are genuine
over-merges, 0.50% of judgeable pairs** (Figure 2, right). Cochrane treats
versions of one study as one study, so counting them as errors measures the
arbiter, not the implementation. Both figures are reported because the choice
belongs to the review team.

**Table 4.** Identifier-blind deduplication across fifteen disciplines, on 13,809 records harvested live from four databases. Pairs are judged against the normalized DOI after every identifying field is removed. *F1 versions* treats versions of one study as one study, as Cochrane does. Data: measurements in `validation/domains_15_final.csv`, reproduced by `validation/eval_domains_15.py --check`.

| Discipline | Track | N | Pairs | Precision | Recall | F1 | F1 versions |
|---|---|---:|---:|---:|---:|---:|---:|
| Economics | social | 831 | 230 | 0.7627 | 0.9783 | 0.8572 | 0.9890 |
| Software engineering | stem | 617 | 149 | 0.8896 | 0.9195 | 0.9043 | 0.9547 |
| Transport | social | 891 | 182 | 0.8985 | 0.9725 | 0.9340 | 0.9806 |
| Business informatics | stem | 1053 | 102 | 0.9320 | 0.9412 | 0.9366 | 0.9600 |
| History | nature_hum | 819 | 102 | 0.9694 | 0.9314 | 0.9500 | 0.9500 |
| Geography | nature_hum | 889 | 105 | 0.9798 | 0.9238 | 0.9510 | 0.9557 |
| Marketing | social | 895 | 171 | 0.9697 | 0.9357 | 0.9524 | 0.9639 |
| Logistics | social | 893 | 195 | 0.9543 | 0.9641 | 0.9592 | 0.9817 |
| Chemistry | stem | 914 | 105 | 0.9537 | 0.9810 | 0.9672 | 0.9904 |
| Computer science | stem | 1187 | 66 | 0.9429 | 1.0000 | 0.9706 | 0.9925 |
| Physics | stem | 1193 | 319 | 0.9750 | 0.9781 | 0.9765 | 0.9858 |
| Political science | nature_hum | 841 | 119 | 0.9914 | 0.9664 | 0.9787 | 0.9829 |
| Management | social | 715 | 242 | 1.0000 | 0.9587 | 0.9789 | 0.9789 |
| Sociology | nature_hum | 880 | 153 | 1.0000 | 0.9608 | 0.9800 | 0.9800 |
| Biology | nature_hum | 1191 | 344 | 0.9912 | 0.9855 | 0.9883 | 0.9927 |

![](fig_domains.png)

**Figure 2.** Deduplication across fifteen disciplines, evaluated
identifier-blind on 13,809 live records from four databases. *Left:* pairwise F1
per discipline; the filled marker scores against the DOI arbiter, the open
marker treats versions of one study as one study, and the gap between them is a
definition rather than an error. *Right:* composition of the 2,584 judgeable
pairs - of 154 false merges, 141 are version variants and 13 are genuine
over-merges. Colour marks the harvesting track, not a performance grouping.


The variation is almost entirely in precision (0.76-1.00) rather than recall
(0.91-1.00), and it tracks publishing culture, not subject matter: economics
scores lowest because its literature circulates as NBER and SSRN working papers
before publication. Coverage of the DOI arbiter runs from 74.3% (computer science, much of whose literature sits on arXiv without a DOI) to 99.2% (biology), and does not predict accuracy: computer science scores F1 0.9706, history 0.9500 at 93.2%. Coverage limits how much of a corpus can be *judged*, not how well it is deduplicated.

### 3.3 Scale

On synthetic corpora with 20% planted cross-source duplicates, deduplication
processes 60,000 records in 25.3 s at 310 MB
peak (422 us per record); a pathological corpus in which
every title shares a stock opening takes 9.6 s and
109 MB. Unit cost rises 62%
over a tenfold increase in corpus size, so scaling is close to linear but not
exactly so. The cost is dominated by title comparison, and memoising the
normalized title is what makes it tractable: measured against a recomputing
implementation it is worth 7.0-8.0x on both mixed- and narrow-vocabulary corpora,
with identical output. An exact length bound on the similarity ratio is also
applied before the matcher runs; measured separately it is within noise of 1x,
and it is retained because it can only reject pairs the matcher would reject
anyway, not as a speed-up Data: measurements in
`validation/dedup_performance.csv`.

On one live query (2026-08-19), metadata completeness differed sharply by database: Scopus 97/100 with a DOI and 99/100 with an abstract, PubMed 100/100 and 100/100, Crossref 100/100 but only 50/100 with an abstract, arXiv 4/23 with a DOI and 23/23 with an abstract.

Running the retrieval layer against the live services exposed three defects offline tests cannot reach: the Scopus client defaulted to the leaner response view, which returns one author and no abstracts at all, making title/abstract screening impossible; the preprint client had no scan budget, so a selective query over a multi-year window became an hours-long full-archive crawl; and the Web of Science client addressed the Starter API while an entitled subscription serves Expanded.

## 4. Impact

The immediate impact is compliance work that currently consumes reviewer and
author time. The PRISMA-S appendix is generated from recorded provenance, so the
database-platform-interface triple, the executed strategy, the dates and the
per-database counts cannot drift from what was actually run. Deduplication
performs at the level of the best published tool while producing an auditable
decision log, which converts "duplicates were removed in EndNote" into a
reportable, checkable method.

The second impact is methodological guardrails. The registry makes the
principal/supplementary distinction operational rather than advisory: a corpus
built only from supplementary systems raises a critical warning at the point
where it can still be fixed. To our knowledge this classification has not been
automated in a review-support library before.

The third is reproducibility, in the sense of the FAIR principles [21], at two levels. A harvest archive with a manifest and an order-independent checksum lets a reviewer replay a search and confirm the corpus. And a whole review - search, parse, deduplicate, diagram, appendix - runs from one JSON configuration through the command-line interface, so the reported method is the method that executed. A dry-run mode compiles the per-database queries with a configuration checksum before any request is made, which is the artefact PRISMA-S Item 8 asks for and the one reviewers most often cannot produce.

## 5. Conclusions

CorpusSLR covers the span from a structured query to a PRISMA-compliant,
deduplicated, auditable corpus, with deduplication validated against a published
gold standard and across four disciplines. Both Web of Science clients are exercised against the live service: the Expanded API returned an abstract on 100/100 records where Starter returns none.

Its limitations are stated plainly:
 the social-science arms are small (67 and 116 evaluable
pairs, no confidence intervals), citation-based strategies such as snowballing [22] are outside its scope, and thesaurus expansion (MeSH,
Emtree) is not performed, so a librarian-designed strategy still outperforms a
compiled one in biomedical databases.

## Acknowledgements / Declaration of competing interest

The evaluation rests on the labelled deduplication benchmark published by the ASySD authors, whose decision to release it openly is what made an external comparison possible. Clarivate granted the Web of Science Expanded API entitlement used to verify that client against the live service.

## Data availability

All data underlying the results are public. The software, the evaluation scripts and the measurement tables are in the repository given in C2. The validation data are additionally packaged for review as `corpusslr_validation_data.zip`, whose manifest maps each file to the table or figure it supports. One file is third-party: the ASySD *Diabetes* gold standard, redistributed unmodified from `github.com/camaradesuk/ASySD` under that project's GPL-3.0 licence, with provenance, pinned commit and checksum recorded in `validation/THIRD_PARTY_DATA.md`. The corpora harvested for the cross-disciplinary study are archived as compressed record dumps, so every number reported here recomputes without network access.

## References

[1] Kitchenham B, Pearl Brereton O, Budgen D, Turner M, Bailey J, Linkman S. Systematic literature reviews in software engineering - A systematic literature review. Information and Software Technology 51(1):7-15 (2009). doi:10.1016/j.infsof.2008.09.009

[2] Bramer WM, Rethlefsen ML, Kleijnen J, Franco OH. Optimal database combinations for literature searches in systematic reviews: a prospective exploratory study. Systematic Reviews 6(1):245 (2017). doi:10.1186/s13643-017-0644-y

[3] van Altena A, Spijker R, Olabarriaga S. Usage of automation tools in systematic reviews. Research Synthesis Methods 10(1):72-82 (2019). doi:10.1002/jrsm.1335

[4] Ouzzani M, Hammady H, Fedorowicz Z, Elmagarmid A. Rayyan - a web and mobile app for systematic reviews. Systematic Reviews 5(1):210 (2016). doi:10.1186/s13643-016-0384-4

[5] Westgate MJ. revtools: An R package to support article screening for evidence synthesis. Research Synthesis Methods 10(4):606-614 (2019). doi:10.1002/jrsm.1374

[6] Bustos Navarrete C, Morales Malverde MG, Salcedo Lagos P, Díaz Mujica A. Buhos: A web-based systematic literature review management software. SoftwareX 7:360-372 (2018). doi:10.1016/j.softx.2018.10.004

[7] Haindl P. ReviQ: A systematic literature review workbench. SoftwareX 35:102814 (2026). doi:10.1016/j.softx.2026.102814

[8] Singh VK, Singh P, Karmakar M, Leta J, Mayr P. The journal coverage of Web of Science, Scopus and Dimensions: a comparative analysis. Scientometrics 126(6):5113-5142 (2021). doi:10.1007/s11192-021-03948-5

[9] Visser M, van Eck NJ, Waltman L. Large-scale comparison of bibliographic data sources: Scopus, Web of Science, Dimensions, Crossref, and Microsoft Academic. Quantitative Science Studies 2(1):20-41 (2021). doi:10.1162/qss_a_00112

[10] Page MJ, McKenzie JE, Bossuyt PM, Boutron I, Hoffmann TC, Mulrow CD, et al. The PRISMA 2020 statement: an updated guideline for reporting systematic reviews. BMJ 372:n71 (2021). doi:10.1136/bmj.n71

[11] Rethlefsen ML, Kirtley S, Waffenschmidt S, Ayala AP, Moher D, Page MJ, Koffel JB. PRISMA-S: an extension to the PRISMA statement for reporting literature searches in systematic reviews. Systematic Reviews 10(1):39 (2021). doi:10.1186/s13643-020-01542-z

[12] Gusenbauer M, Haddaway NR. Which academic search systems are suitable for systematic reviews or meta-analyses? Evaluating retrieval qualities of Google Scholar, PubMed, and 26 other resources. Research Synthesis Methods 11(2):181-217 (2020). doi:10.1002/jrsm.1378

[13] Hair K, Bahor Z, Macleod M, Liao J, Sena ES. The Automated Systematic Search Deduplicator (ASySD): a rapid, open-source, interoperable tool to remove duplicate citations in biomedical systematic reviews. BMC Biology 21(1):189 (2023). doi:10.1186/s12915-023-01686-z

[14] Strojny T, Beręsewicz M. BlockingPy: approximate nearest neighbours for blocking of records for entity resolution. SoftwareX 34:102583 (2026). doi:10.1016/j.softx.2026.102583

[15] Forbes C, Greenwood H, Carter M, Clark J. Automation of duplicate record detection for systematic reviews: Deduplicator. Systematic Reviews 13(1):206 (2024). doi:10.1186/s13643-024-02619-9

[16] Matysik S, Wiśniewska J, Frankowski PK. EmbedSLR: an open-source python framework for efficient embedding-based screening and bibliometric validation in systematic literature review. SoftwareX 32:102416 (2025). doi:10.1016/j.softx.2025.102416

[17] Matysik S, Wiśniewska J, Frankowski PK. Version 2.0 - EmbedSLR: An open-source python framework for efficient embedding-based screening and bibliometric validation in systematic literature review. SoftwareX 34:102563 (2026). doi:10.1016/j.softx.2026.102563

[18] Velasquez JD. TechMiner: Analysis of bibliographic datasets using Python. SoftwareX 23:101457 (2023). doi:10.1016/j.softx.2023.101457

[19] Bramer WM, Giustini D, de Jonge GB, Holland L, Bekhuis T. De-duplication of database search results for systematic reviews in EndNote. Journal of the Medical Library Association : JMLA 104(3):240-243 (2016). doi:10.3163/1536-5050.104.3.014

[20] Rathbone J, Carter M, Hoffmann T, Glasziou P. Better duplicate detection for systematic reviewers: evaluation of Systematic Review Assistant-Deduplication Module. Systematic Reviews 4(1):6 (2015). doi:10.1186/2046-4053-4-6

[21] Wilkinson MD, Dumontier M, Aalbersberg IJ, Appleton G, Axton M, Baak A, et al. The FAIR Guiding Principles for scientific data management and stewardship. Scientific Data 3(1):160018 (2016). doi:10.1038/sdata.2016.18

[22] Wohlin C. Guidelines for snowballing in systematic literature studies and a replication in software engineering. Proceedings of the 18th International Conference on Evaluation and Assessment in Software Engineering 1-10 (2014). doi:10.1145/2601248.2601268
