# Changelog

All notable changes to CorpusSLR are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Entries are derived from `AUDIT_REPORT.md`, which records the measurement behind
each accuracy figure quoted below. Deduplication accuracy is reported as the
record-level clustering F1 on the labelled *Diabetes* set published with ASySD
(Hair K, Bahor Z, Macleod M, Liao J, Sena ES, *BMC Biology* 21:189, 2023,
doi:10.1186/s12915-023-01686-z; bibliographic record verified via Crossref),
unless stated otherwise.

Where a figure is verifiable: the **current** release's confusion matrices are in
`validation/asysd_metrics.csv`, which can be regenerated with
`python validation/eval_asysd.py`. Figures for **superseded** releases (0.957,
0.993, 0.9964 and the end-to-end 0.870/0.981/0.9810/0.9829) are historical: they
were measured on code that no longer exists in the tree, so they are not
reproducible from the current checkout and are recorded in `AUDIT_REPORT.md`
rather than in a metrics file. They are kept because the trajectory is the
point; they should not be quoted as properties of the current version.

## [Unreleased]

Nothing yet.

## [1.0.0] - 2026-09-09

First public release. Nothing before this was published: the numbered entries
under *Pre-release development history* below are internal milestones from the
audit, hardening and validation work, kept because that trail is part of the
submission. They are not releases, and the version numbers they carry were
never distributed.

### Added

- Ten further references, each verified against its Crossref work record and
  recorded in `validation/references_verified.json`: the provenance of the
  EndNote and SRA-DM rows in the comparison table, which the article named
  without citing; concurrent work on the same problem; the screening tools
  that begin where this library ends; the methodology's use outside medicine;
  a second large-scale comparison of bibliographic sources; snowballing as an
  out-of-scope strategy; and the FAIR principles behind the reproducibility
  argument. Two of the ten DOIs recalled from memory were wrong - one resolved
  to an erratum for a different paper, the other returned HTTP 404 - and were
  corrected through Crossref's title search. The reference list now has
  sixteen entries, every one of them cited in the text.

- Six further references, all published in this journal and all verified
  against their Crossref records (ISSN 2352-7110 checked on each): EmbedSLR in
  its original and 2.0 releases, which read a Scopus-layout corpus and screen it
  by sentence embeddings and are therefore the immediate reuse path for this
  library's canonical output; the ReviQ and Buhos review workbenches, which
  administer protocol and screening around a corpus that is already assembled;
  TechMiner, as a consumer of the exported corpus; and BlockingPy, which places
  the blocking stage of the deduplication cascade in the general
  entity-resolution literature. The EmbedSLR citations are self-citations and
  are recorded as such in `validation/references_verified.json`. The Scopus
  section named EmbedSLR without citing it, the same omission the EndNote and
  SRA-DM rows had. The reference list now has twenty-two entries.

### Added

- `COVER_LETTER.md`, the submission letter. Every figure in it is read from a
  saved measurement file, and the file is now in the audited document list, so
  a figure in the letter cannot drift from the manuscript it accompanies.
  Verified by injecting a wrong test count: caught.
- `[project.urls]` gained Homepage, Documentation, Issues and Changelog. It
  carried only Repository, so the package index would have shown no link to the
  documentation site even though that site is live.

### Changed

- The distribution was examined before a first upload to the package index, and
  the source archive is not publishable as built: at 9.6 MB it is dominated by
  the evaluation corpora, and 4 MB of that is the ASySD gold standard, which is
  third-party data under that project's GPL-3.0 licence. Shipping it inside a
  package named and licensed MIT on a public index is a stronger act than
  keeping it in the repository under an attribution notice. Trimming the archive
  was measured rather than assumed: the same tree builds an archive of 2.3 MB,
  but five tests then fail, all of them assembling the reviewer package, the
  data package or the documentation site from inside the distribution, and the
  untrimmed archive passes 1991 with none failing. The wheel needs no trimming
  at all: it contains `corpusslr/` and the dist-info only, 233 KB, no validation
  data and no third-party file. So the index release is the wheel, and the
  source archive stays a repository artefact where
  `validation/THIRD_PARTY_DATA.md` governs the terms.

### Fixed

- The sentence under the gold-standard table contradicted the abstract and the
  table above it. Both said one missed duplicate and F1 0.9996; the sentence
  said four, and attributed 0.9996 to development milestone 1.3. Measured on
  the released code with `validation/eval_asysd.py`: TP 1260, FP 0, FN 1,
  F1 0.9996, so the abstract and the table were right and only the sentence was
  stale, left over from the state just after the `NA` identifier fix.
  Previously stated: four missed duplicates.
  The sentence now reports the measurement and
  the fix's own effect from `na_doi_fix_impact.csv` (one false positive and nine
  misses, to none and four). The same claim in different wording sat in
  `MANUSCRIPT.md`, from which the submitted Word file is generated, and was
  corrected there too.
- `paper/corpusslr_softwarex.tex` was absent from the audited document list, so
  no number in the submitted article had ever been checked against a
  measurement; only its markdown mirror was. That is how the contradiction
  survived. It is now audited, which surfaced no other disagreement, and a new
  rule reads the gold-standard miss count from the row measured on the released
  code and rejects any prose claiming a different one, in digits or in words,
  scoped to gold-standard context so the cross-disciplinary miss counts are not
  compared against it. Verified by reinjecting the exact defect: caught.
- `paper/README.md` stated the main text at the limit with no room left. The
  correction above shortened the article, so it is now 2981 words with 19 to
  spare. Previously stated: 3000 words of main text.
  Previously stated: a margin of 0 words.

### Fixed

- The validation data package told the journal that
  `labelled_test_set.csv` is redistributed "under CC BY 4.0". That was an
  unverified claim and it is wrong. The article is CC BY 4.0, but the article's
  licence does not cover the dataset; the Open Science Framework project the
  article names as the home of the data (`osf.io/c9evs`) was queried through
  the OSF API and neither it nor either of its two components declares a
  licence; and the copy actually used here was downloaded from
  `github.com/camaradesuk/ASySD`, whose repository is GPL-3.0. GPL-3.0 is
  therefore the only licence explicitly attached to a copy anyone here
  obtained, and both packaging notes now say so. `validation/THIRD_PARTY_DATA.md`
  records the provenance, the pinned upstream commit `49544ce33171`, the
  SHA-256 of the copy shipped, the citation, and a fetch command for anyone who
  would rather not receive the file at all. Two tests pin it: one requires the
  notice to state the licence, the checksum and the source, the other fails the
  build if any packaging note claims CC BY for the dataset again.

### Fixed

- The submission checklist's "CI executed on GitHub" item was a hardcoded
  `False` with a note explaining that a sandbox cannot run it. That made it
  unclosable: continuous integration has now run green on GitHub several times
  and the item still reported open, which is the same defect class as the two
  hardcoded verification entries found earlier. It now reads
  `validation/ci_run_verification.json`, written by the new
  `validation/record_ci_runs.py` from the GitHub Actions REST API, recording
  each workflow's latest conclusion with its run id and commit. Verified both
  ways: with all four workflows green the item closes (20 verified, 1 open),
  and flipping one recorded conclusion to `failure` reopens it. The recorder
  exits non-zero and writes nothing when the API is unreachable, so an absent
  network leaves the item open rather than ticking it on a guess.

### Fixed

- `paper/README.md` had drifted from the article it documents. Each figure it
  carried is below with what the artefact actually contains:

  - previously stated: six references; measured: 22.
  - previously stated: a six-page PDF; measured: 7 pages.
  - previously stated: six entries in the `.bbl`; measured: 22.
  - previously stated: 2656 words of main text; measured: 3000.
  - previously stated: a 344-word margin; measured: 0.
  - previously stated: thirteen injected faults; measured: 11 into the source
    plus one that recompiles the document.
  - the figure order predated the renumbering: Figure 1 is the ablation.

  Measured now, the bibliography has 22 entries, the
  article is 7 pages, the main text is exactly 3000 words with zero margin, the
  self-test injects 11 faults into the source plus one that recompiles the
  document, and Figure 1 is the ablation. The file also opened under the
  heading "SoftwareX manuscript" with a sentence fragment about the template,
  which made build documentation look like the submitted article; it now says
  what it is.

- The reason those drifted is that `paper/README.md` was not in the audited
  document list, so `validation/audit_document_numbers.py` never read it. It is
  now, together with four new rules that measure what it claims against the
  artefacts themselves: bibliography entries from `references.bib`, page count
  from the committed PDF (inflating the object streams with `zlib`, since
  pdflatex writes the page tree compressed and a regex over the raw bytes finds
  nothing), word count and margin from `count_words.py`, and the fault counts
  from the `FAULTS` table in `verify_tex.py`. All four were proved by
  injection. Two defects in the rules themselves were found and fixed while
  proving them: markdown emphasis between a number and its noun
  ("**N words** of main text") defeated the first pattern, and an unscoped
  "N pages" rule reported the documentation site's correct page count as a
  stale PDF claim, so the page rule now requires article context.

### Changed

- The deduplication section claimed that "every deduplicator treats a shared
  identifier as decisive". Read against ASySD's own source (`R/internal.R`,
  `identify_true_matches`) that is false: its DOI clause requires author and
  title agreement as well, and it already demotes pairs with a mismatching DOI
  or a year gap greater than one. The claim is withdrawn and the contribution
  restated as what it is, negative evidence of kinds that rule does not model
  (bibliographic locus, spreadsheet-mangled page fields, pseudo page ranges,
  conference against journal version, instalment markers).

### Added

- `validation/compare_asysd_rule.py`, which transcribes ASySD's 23-clause
  decision rule from its source and asks both rule sets about identical
  candidate pairs on the fifteen-discipline corpora. Median pairwise F1 0.9164
  against 0.9510, higher here in 13 of 15 disciplines, but the operating points
  differ rather than one dominating: median recall 0.861 against 0.964 at
  median precision 0.974 against 0.962. The script states in its own docstring
  what the comparison is not, and measures both caveats: 424 of the 473 pairs
  the published rule leaves behind (89.6%) fall in the set ASySD routes to
  *manual* review, 2,974 pairs for a human to inspect across these corpora; and
  its policy of scoring a field absent on both sides as agreement admits 68 of
  its 78 false merges here, yet forcing those to no-evidence would cost 575
  true pairs, so the policy buys recall rather than being a defect. Outputs:
  `asysd_rule_comparison.csv`, `asysd_manual_queue.csv`,
  `asysd_na_policy_mechanism.csv`, all reproducible with `--check`.

  One hypothesis was tested and dropped on the way: that ASySD's fuzzy DOI
  comparison (Jaro-Winkler above 0.95) would fuse identifiers differing by one
  character, as consecutive conference papers and book chapters do. Measured
  across all fifteen corpora it accounts for 0 of the 78 false merges, because
  the identifier-blind protocol removes the DOI before scoring, so that clause
  cannot fire at all. The finding is recorded rather than quietly discarded.

### Fixed

- The Colab notebook's install cell ran `pip install corpusslr` and then
  imported the package. Verified on a clean interpreter: while the release is
  not on a package index that install fails and the next line raises
  `ModuleNotFoundError`, so the notebook died on its first cell with an error
  that says nothing about what to do. It now tries the package index, then the
  source repository, and if neither resolves it exits with a message naming the
  local-copy alternative and pointing at the address in the code metadata
  table. Checked by running the generated cell with both sources made
  unresolvable.

- The notebook's name-chain test treated a function parameter as an undefined
  name, so it reported any cell defining a function that takes arguments. It
  now binds parameters; its fault-injection twin still catches a genuinely
  missing definition.

- `underscore.sty` in the article preamble. One added DOI contains underscores
  (10.1162/qss_a_00112); the bibliography style emits it as `\path{...}` inside
  `\href{...}{...}`, where url.sty's verbatim handling does not engage, so the
  underscore reached math mode and the build failed. Escaping it in the `.bib`
  would have put a backslash in the link target, so the package is loaded
  instead. The FAIR entry's 53-name author list is truncated after six with
  `and others`, which the style renders as *et al.* and which keeps the
  reference list from spilling further.

### Changed

- The version is 1.0.0 because this is the first release. Result labels that
  named a development version now name the release, and each was re-measured
  first: cluster-level F1 0.9996 (TP 1260, FP 0, FN 1) and end-to-end F1
  0.9853 (TP 1242, FP 18, FN 19) both hold on the released code.

---

## Pre-release development history

Everything below records work done before the first release. It is
retained as an audit trail; the figures in each entry were correct for the
state of the code at that milestone and are not claims about 1.0.0.

## [1.7.3] - 2026-09-08

The submission documents were reformatted to the layout of an accepted
SoftwareX article supplied as a reference, and doing so surfaced four
substantive defects in the manuscript itself.

### Changed

- `tools/build_docx.py` now reproduces the reference layout measured from the
  journal's own file rather than a guessed one: Letter paper, Arial 11 pt body,
  1.05 line spacing, a flat outline in which the title and every numbered
  subsection share Word's Heading 1, a title page with superscript affiliation
  markers, captions printed BELOW their object at 9.5 pt, ruled tables whose
  body size scales with the column count, and the reference list at 9.5 pt.
  The previous version set A4, double spacing, a serif face, graded heading
  sizes and centred front matter, none of which appears in the reference.
- Author affiliation is stated: University of Szczecin, Institute of
  Management, Doctoral School, with a corresponding-author line and contact
  address. It propagates to `CITATION.cff`, `codemeta.json` and `.zenodo.json`;
  the article previously read "Independent researcher".
- Figures are placed at the point where the text refers to them, not collected
  at the end of the file.

### Fixed

- The gold-standard result in the article was a release out of date: it stated
  F1 0.9984 with 4 false negatives, measured before separator-less author lists
  were handled in `split_authors`. Measured now by
  `validation/eval_asysd.py`: **F1 0.9996, FP 0, FN 1, TP 1260**. Corrected in
  the abstract, the results table and the conclusions, and recorded in
  `validation/asysd_metrics.csv` under the current version.
- Figure numbering in `MANUSCRIPT.md` was swapped relative to the captions and
  to the typeset article, two captions described figures that do not exist, and
  a literal `[ref]` placeholder stood in the prose.
- The Word version carried two of the article's four tables. The ablation and
  fifteen-discipline tables are now built from
  `validation/dedup_mechanism_ablation.csv`,
  `validation/dedup_ablation_domains.csv` and
  `validation/domains_15_final.csv`, so both versions of the submission carry
  the same evidence under the same numbering.
- The prose claimed 8 API clients; the code has ten client classes, nine of
  them selectable from the command line, which is what the article already
  said.
- The reference list had no in-text citations, its numbering disagreed with the
  compiled bibliography, and it omitted every article title. It now follows the
  `.bbl` numbering, carries titles and DOIs, and every entry is cited.
- `validation/audit_document_numbers.py` did not scan `SUPPLEMENTARY.md`, a
  document submitted alongside the article, nor `PUBLISHING.md`: twelve stale
  figures were found the moment they were added. Its adjacency rule now reads
  the noun after a number across markdown emphasis and a line break, because
  "collects **2114**\ncases" was invisible to a line-scoped rule, and it
  distinguishes a count of test functions from a count of collected cases by
  measuring both. Widening the context window to the paragraph was tried and
  reverted: it flagged statement counts, publication years and pair counts.
- An em dash in `validation/dedup_ablation_domains.csv` would have reached a
  manuscript table; the dash checker does not scan data files by design.

## [1.7.2] - 2026-09-08

The submission set: a Word manuscript and supplement, the validation data as a
standalone upload, and the exact tree to push. Four defects the assembly work
exposed.

### Added

- `tools/build_docx.py`: renders MANUSCRIPT.md and SUPPLEMENTARY.md as
  SoftwareX-styled `.docx` (Times New Roman 12 pt, single column, continuous
  line numbers, the C1-C9 code metadata table before section 1). Title,
  author, affiliation, abstract and keywords are read from the typeset
  article, so the Word and LaTeX submissions cannot disagree. 13 tests read
  the produced files back rather than trusting the build report.
- `tools/build_data_package.py`: the validation data as the upload that
  accompanies the article - 26 files, 12.5 MB, every entry declaring which
  table or figure it supports, SHA-256 per file, and a build that FAILS when a
  document cites a validation file the package neither contains nor records a
  reason for omitting. Two builds are byte-identical.
- `tools/build_push_tree.py`: writes the tree to commit, with `.gitignore`
  applied and its patterns read from that file rather than restated, for
  environments where a repository cannot be initialised in place. Refuses to
  emit a tree missing any file the first commit must carry.
- `KNOWN_ISSUES.md`: four disclosures, chief among them why the headline
  fifteen-discipline table differs from the per-track metrics files. Check C9
  in `verify_reviewer_claims.py` had been silently SKIPPING because the file
  did not exist; the disclosure now exists and the check re-derives every
  figure in it.
- `validation/eval_domains_15.py`: regenerates `domains_15_final.csv` from the
  archived raw records and exits non-zero on disagreement. The table behind
  the headline accuracy figures previously had no producing script, so it
  could not be reproduced and appeared inconsistent with the per-track files
  for undocumented reasons.

### Fixed

- **The article and the supplement were outside the version gate.** After
  1.7.1 the C1 metadata row, the CLI transcript quoted in Listing 2 and the
  supplement's own title all still read 1.7.0 - the three places a reviewer
  looks. Three tests now pin them to the package version, each proven against
  an injected stale version.
- **The manuscript's metadata block stated version 1.4.0**, eleven releases
  behind, and is now generated from the same C1-C9 table as the article.
- **All four figure references in MANUSCRIPT.md were broken**: two were
  notebook artifact markers that resolve only in a viewer, and two named
  files that do not exist. They now point at the two figures on disk with the
  captions the typeset article uses.
- The docx converter appended every string containing inline markup twice (a
  run-position bug), and split emphasis that wrapped across a list item's
  lines into literal asterisks. Both are pinned by tests.
- `validation/eval_asysd.py --skip-bench` aborted while generating the
  performance figure from an empty frame, after the accuracy metrics were
  already written.

### Testing

- 2111 tests on Python 3.13, 2095 + 4 skipped on 3.9 (two optional libraries
  absent in that environment, not a behaviour difference). Coverage 98 %,
  ruff 0, mypy 0, `twine check --strict` passes.

## [1.7.1] - 2026-09-08

Submission deliverables and three defects the work of assembling them exposed.

### Added

- `paper/`: the article in the SoftwareX template (`elsarticle`), compiled to a
  six-page PDF with 0 errors and 0 warnings, with the C1-C9 code metadata
  table, both figures, three listings and a Crossref-verified bibliography.
  `paper/verify_tex.py` runs 8 structural checks and proves each one against 13
  injected faults; `paper/listing_example.py` keeps Listing 1 executable rather
  than transcribed.
- `PUBLISHING.md`: the publication procedure as commands to paste - `git init`,
  `.gitignore`, first commit, remote, push, Actions, Pages, the `v1.7.1` tag and
  release, and the Zenodo hook for the DOI.
- `tools/build_site.py` and `.github/workflows/pages.yml`: a GitHub Pages site
  built by a markdown-to-HTML converter written on the standard library alone.
  8 pages, 0 external references, no JavaScript, works opened from a file.
- `tools/build_reviewer_package.py`: the reviewer package as a script product -
  134 files in five directories, SHA-256 for every file, a claim-to-evidence
  table, and a zip whose two builds are byte-identical.
- `tools/normalize_dashes.py`: the house typography rule (the hyphen is the
  only dash) enforced across the repository, with `--check` for CI.
- `validation/eval_domains_15.py`: regenerates `domains_15_final.csv` from the
  archived raw records and documents why it differs from the per-track files
  (three guards added after those runs, plus the scoring population).

### Fixed

- **File exports lost every affiliation.** `Record.affiliations` was populated
  by the API clients but no CSV dialect map listed the column, so importing
  from a vendor export dropped the addresses. Measured on a real 597-record
  Scopus export: 595 rows carried affiliations, 0 survived the parse, and
  bibliometrix's institutional collaboration network returned "Matrix is
  empty!!". After adding the column to all six dialect maps: 592/597 carry
  affiliations and the network resolves to 986 institutions.
- **An author list exported with no separator became one mangled author.**
  "Adeli K.Lewis G. F." is two authors - the initial's period doubles as the
  separator - and the whole author column of the ASySD gold standard is in that
  form. Cluster-level F1 on that benchmark: 0.9984 (TP 1257, FN 4) before,
  **0.9996** (TP 1260, FN 1) after. The higher figure was previously reachable
  only by preprocessing the file inside the evaluation harness, which the
  package's own users do not have.
- `validation/eval_asysd.py --skip-bench` aborted in figure generation on an
  empty performance frame after the accuracy metrics were already written.

### Changed

- Every document, docstring and comment uses the hyphen only; 517 em dashes,
  en dashes and minus signs across 19 files were replaced. One of those
  replacements broke a regular expression - a character class matching the
  three page-range separators collapsed to a range - which is why the class is
  now spelled with escapes and the interpreter is run with warnings as errors
  over every module.

### Testing

- 2057 tests on Python 3.13, 2054 + 3 skipped on 3.9 (two optional libraries
  absent in that environment, not a behaviour difference). Coverage 98 %,
  ruff 0, mypy 0 and `twine check --strict` passes. From an unpacked source
  archive the suite reports 1959 passed and 98 skipped: the skips are
  entirely `tests/test_publishing.py`, which reads `.gitignore` and
  `.github/workflows/` - files a source distribution correctly does not
  package. Zero failures in all three runs.

## [1.7.0] - 2026-09-07

Scopus-format export as the canonical result, two interfaces for researchers who
do not write Python, and a fifteen-discipline validation that found three
silent-data-loss defects.

### Added

- `to_scopus_csv()`: the deduplicated corpus is written in Scopus export format,
  the input dialect bibliometrix, VOSviewer and EmbedSLR all read. Verified by
  execution, not assertion: `bibliometrix::convert2df(dbsource="scopus")`
  imported a file written from a live 180-record three-database corpus as 166
  rows and 57 fields, and `biblioAnalysis` ran on it.
- `Record.affiliations`, populated from the Web of Science Expanded addresses
  node and unioned when two copies merge. bibliometrix derives its institutional
  collaboration network (`C1` -> `AU_UN`) from this field: before the change the
  network was empty ("Matrix is empty!!"), after it the same corpus yields a
  156-institution network.
- `corpusslr/tui.py` and `python -m corpusslr`: a guided terminal interface on
  the standard library alone -- no curses, no third-party console library, no
  ANSI colour, 80 columns. API keys are read with `getpass` and stored 0600.
- `notebooks/corpusslr_colab.ipynb`: 26 cells running a complete review in
  Google Colab. Keys are typed hidden and never saved into the notebook.
- `is_identifier_only_title()` and `period_markers()`, the two guards below.

### Fixed

- **A missing-value literal in the DOI field acted as a shared identifier.**
  `normalize_doi()` returned any unrecognised string unchanged, so R's `NA`,
  and `N/A`, `NULL`, `none`, `-` from other exports, all became identifiers --
  and a shared identifier is the strongest evidence the cascade has. On the
  ASySD Diabetes file, whose missing DOIs are the literal `NA`, 492 of 1845
  records (26.7%) shared the single key `na`. A value without the registered
  DOI shape is now rejected. Gold-standard accuracy: F1 0.9960 -> **0.9984**,
  false positives 1 -> **0**.
- **A title that is only an identifier drove fuzzy matching.** Some publishers
  deposit the DOI into the title field; two such titles from one journal issue
  differ in their last digits and score ~0.95. Observed live: four separate
  papers from one issue of *Journal of Social Development in Africa* collapsed
  into one record. Such titles no longer contribute title similarity -- the
  identifier is still parsed into the DOI field, where it belongs.
- **Instalments of a recurring publication merged.** Agency quarterlies, annual
  reports and survey waves share a title verbatim and differ only in the marker
  naming the instalment, so fuzzy matching cannot separate them. On a live
  transport corpus, the rule eliminates 19 false merges (39 -> 20 over 182
  judgeable pairs), all of them consecutive quarters of
  one U.S. Department of Energy report series. English-only by construction;
  the limitation is documented at `period_markers`.

### Validation

- Fifteen disciplines (economics, marketing, management, logistics, transport,
  computer science, software engineering, business informatics, physics,
  chemistry, biology, geography, sociology, political science, history), two
  queries each, 13,809 records from four databases, evaluated
  identifier-blind. Median pairwise F1 **0.9592**; every discipline
  above 0.85. Of 154 false merges across
  2,584 judgeable pairs, 141 are
  version variants of one study and **13** are genuine
  over-merges (0.50% of pairs).
- The three guards above raised nine of fifteen disciplines and lowered none;
  median F1 0.9500 -> 0.9592.

### Testing

- 2057 tests on Python 3.13, 2054 + 3 skipped on 3.9 (two optional libraries
  absent in that environment, not a behaviour difference). Coverage 98 %,
  ruff 0, mypy 0.

## [1.6.0] - 2026-09-07

### Added

- `WosExpandedSource`: a client for the Clarivate **Expanded** API
  (`https://api.clarivate.com/api/wos`), verified against the live service with
  an entitled institutional key. The existing `WosStarterSource` speaks the
  Starter API, which is a different service: a key issued for one is refused by
  the other, and the response shapes differ.

  The reason this matters is not coverage but screenability. The Starter plan
  returns **no abstracts at all**; on a live query the Expanded client returned
  an abstract on 100/100 records and more than one author on 99/100. A corpus
  without abstracts cannot be screened on title and abstract, which is the step
  the whole review depends on.

  Live verification (2026-09-07, query
  `TS=("deep learning" OR "convolutional neural network") AND TS=("diabetic
  retinopathy") AND PY=2020-2024 AND DT=(Article)`): 1431 hits reported by WoS,
  100 records retrieved, 26 DOI overlaps with PubMed on a 300-record
  three-database corpus. Recorded in `validation/wos_live_verification.json`
  with the generated appendix in `validation/live_wos_prisma_s.md`.

- The Expanded client reports observed quota headers and abstract coverage in
  its search event, so both reach the PRISMA-S appendix.

### Fixed

- The Starter client's HTTP 403 diagnosis named database entitlement as the
  cause. Measured against the live gateway, the common cause is a key issued
  for a different Clarivate product, and the message now says so first,
  together with the status code each failure mode actually returns: an
  unprovisioned account gets 401 "Not authorized for product: WWS" on Expanded
  and 403 on Starter, while an invalid key gets a bare 401. A 403 is therefore
  never a mistyped key.

### Notes on parsing

Every node in an Expanded response is a dict when singular and a list when
plural - `names.name`, `titles.title`, `identifiers.identifier`, `doctypes`,
`abstracts.abstract`. A single-author record whose `names.name` is a dict will,
if treated as a list, yield its field names as authors. The offline fixtures
include a real single-author record (Akhtar, Salman) for exactly this reason.

### Test suite

- Test suite at that release: 1511 tests on Python 3.13, 1508 + 3 skipped on 3.9 (two optional libraries
  absent in that environment), coverage 98 %. 20 of the new tests cover the
  Expanded client.

## [1.5.0] - 2026-08-19

Three defects found by running the retrieval layer against the live APIs for the
first time. Everything before this release was validated against recorded
responses, which cannot show what a real service actually returns.

### Changed

- **`ScopusSource(view=...)` now defaults to `"auto"`, selecting `COMPLETE` when
  an `insttoken` is supplied and `STANDARD` otherwise.** Measured live on one
  query: `STANDARD` returned **one author per record and zero abstracts across
  100 records**, `COMPLETE` returned up to 10 authors and an abstract for every
  record. Deduplication survived the difference (title matching carries it), but
  title/abstract screening is impossible on an abstract-free corpus - so the old
  default silently degraded the review for every caller who held an entitlement
  and did not know to ask for it. An explicitly named view is never overridden.

### Added

- **Scan budget for the preprint clients (`BiorxivSource`, `MedrxivSource`),
  default `MAX_SCANNED = 1500`, reported as a coverage limit in the search
  event.** The Cold Spring Harbor API offers date-window listing with no query
  interface, so a selective query on a wide window degenerates into a
  full-archive crawl: measured live, `2018-01-01/2024-12-31` on bioRxiv reports
  `messages.total == 335,871` at 30 records per request and ~1.6 s per request - 
  **11,196 requests, about five hours**, for one `search()` call that looked like
  any other. Reaching the budget is disclosed as a *coverage limit*, not applied
  silently, because a truncated search reported as complete misleads the review.
- **`estimate_cost()` on the preprint clients**, answering from one cheap
  request: records in the window, requests for an exhaustive search, a seconds
  estimate, and the coverage the default budget would give (0.45 % for the
  window above). The trade-off is a planning decision, not something to discover
  as a hang.
- **`corpusslr.integrity`: publication-integrity flags.** A live 323-record
  corpus contained **four records carrying a retraction marker** - three
  retracted studies and one retraction notice - and the package modelled
  retraction status not at all. `retraction_flags()` flags rather than filters,
  separating studies that must not enter synthesis from notices about other work,
  and states its own limit: detection reads document type and title, so it is a
  lower bound, not a clearance. `check_retractions_crossref()` is the
  authoritative escalation, reading Crossref's structured `update-to` /
  `updated-by` relations; on the live pair it confirmed the title-based flags
  exactly. The check is rendered into the PRISMA-S appendix whether or not
  anything was found, since "no records flagged" and "check omitted" must not
  look alike to a reviewer.

### Fixed

- `retraction_flags()` keyed its report by `Record.uid`, which is empty until a
  record passes through deduplication - so four flagged records collapsed onto
  one key and three flags were lost. The report is keyed by input position, with
  `flagged_uids` alongside for deduplicated corpora.

### Notes

- Test suite at that release: 1,491 tests on Python 3.13, 1488 + 3 skipped on 3.9 (two optional
  libraries absent from that environment), coverage 98 %.
- OpenAlex was not exercised in this round: the platform requires an API key for
  every request and none was available, so those steps were skipped rather than
  called anonymously. Semantic Scholar returned HTTP 429 throughout. Web of
  Science remains unverified against the live API for want of a Clarivate key.

## [1.4.0] - 2026-08

Submission-readiness release: repository infrastructure, a command-line
interface, source and parser coverage measured against the project
specification, and three defects in the scientific record itself.

### Added


### Added

- Continuous integration (`.github/workflows/tests.yml`): the full suite on
  Python 3.9, 3.10, 3.11, 3.12 and 3.13, coverage measurement with a 95 %
  floor, `python -m build` plus `twine check --strict`, and an install-the-wheel
  import check in a clean interpreter.
- A pytest plugin (`tools/no_network.py`) that replaces the standard-library
  socket connect primitives with raising stubs, so the claim that the suite runs
  offline is enforced by the suite rather than asserted in prose.
- Static-analysis workflow (`.github/workflows/quality.yml`) running ruff and
  mypy, with both tools configured in `pyproject.toml` so a local run and CI
  apply the same rules.
- Citation and archiving metadata: `codemeta.json` (schema.org
  `SoftwareSourceCode`) and `.zenodo.json`, required to mint a persistent DOI.
- `tests/test_metadata_consistency.py`: asserts that version, licence, author
  and repository URL agree across `pyproject.toml`, `corpusslr/__init__.py`,
  `CITATION.cff`, `codemeta.json` and `.zenodo.json`. A release whose metadata
  files disagree produces an archive record that cites the wrong version, so
  this is a test rather than a release-checklist item.
- `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), issue and
  pull-request templates.

### Changed

- `PrismaFlow.to_markdown()` and `HarvestResult.to_source_result()` now read
  their mapping-valued inputs through explicitly typed locals; behaviour is
  unchanged.
- `HarvestResult.to_source_result()` raises `HarvestError` when the harvest
  carries no search event, instead of constructing a `SourceResult` with a
  missing event. A harvest that never reached the API cannot be registered as a
  search without contributing a blank row to the PRISMA counts.

### Fixed

- Static-analysis findings repaired without behavioural change: 165 ruff
  findings and 28 mypy errors brought to zero. The substantive ones were an
  unguarded `Match` object dereferenced in `parsers/endnote.py`, a `bool(m)`
  test that did not guard the following `m.group(1)` in `dedup.py`, and a
  `__exit__` typed as returning `bool` in `parsers/_io.py`, which told callers
  the context manager might swallow exceptions raised inside the block.
- The PRISMA-S appendix now describes the deduplication actually performed.
  Until 1.4.0 it named only the identifier cascade and the fuzzy stage,
  understating the method by transitive closure, blocking rounds, the
  conflicting-identifier block and conference/article separation - mechanisms
  that decide real merges - and it now reports the count of each guard that
  fired, so item 16 reflects the run rather than a simplified description.
- Command-line interface (`corpusslr`): the whole review - search, parse,
  deduplicate, PRISMA diagram and PRISMA-S appendix, exports, harvest and
  replay - driven from one configuration file, so a review is reproducible by a
  single command rather than a Python script.
- Parsers for the tagged `.enw` that the ACM Digital Library labels "EndNote"
  (previously yielded zero records, since `parse_endnote_xml` expects XML) and
  for the HTML table ProQuest exports under an `.xls` extension. CSV dialects
  for Embase and ProQuest.
- `ParseReport`: every parser now accounts for its input, maintaining
  `inputs read == records returned + rejections counted`, each rejection with a
  reason. The "records identified" figure of a PRISMA flow diagram can be
  reconciled against the source file, which was previously impossible.
- Encoding detection for file exports (`parsers/_io.py`): BOM and BOM-less
  UTF-16, UTF-8, cp1252 and latin-1, with `encoding="auto"` the default.
- `SOURCE_EVIDENCE`, `SOURCE_NOTES`, `source_evidence()` and `source_note()`:
  the provenance of each principal/supplementary classification, and the caveat
  a methods section should carry when a tier does not rest directly on the cited
  assessment.
- `docs/user_guide.md`: a complete walkthrough from one strategy to the PRISMA-S
  appendix, with every example executed by `tests/test_docs_examples.py` - three
  method names in the first draft did not exist, and only running the blocks
  revealed it.
- `validation/measure_parser_coverage.py`: coverage against the specification is
  measured by running every entry point on a sample reproducing a real vendor
  export - 32 of 32 items, with each API client parsing a recorded response into
  records carrying identifiers.

### Fixed

- **Silent total data loss on UTF-16 exports.** Every `parse_*_file` hard-coded
  `encoding="utf-8-sig"`. A UTF-16 export - what Web of Science and OVID produce
  via "Save to Other File Formats → Plain text" on Windows - decoded without
  raising into text interleaved with NULs, so no tag matched and the file
  yielded zero records with no error.
- **Silent total data loss on a truncated EndNote XML export.** An interrupted
  download made `ET.fromstring` raise and the parser return `[]`, discarding
  every complete record along with the incomplete tail.
- **Whole-file loss on one long field.** `parse_csv_export` aborted with
  `_csv.Error: field larger than field limit` when an abstract plus a
  400-author affiliation list exceeded 200 kB, losing all remaining records.
- **`parse_csv_export(text)` failed on every dialect.** `io.StringIO(text,
  newline="")` - the `open()` recipe from the csv documentation, which does not
  transfer to an in-memory string - left the line terminators in the buffer.
  Text input now handles LF, CRLF and CR and preserves newlines inside quoted
  fields; `detect_csv_dialect` accepts a whole export, not only a header line.
- **bioRxiv/medRxiv paging stopped after the first page**, because the client
  treated a short page as the last one while the server returns 30 records per
  page rather than the documented 100. A date window holding 220 records
  reported 30, understating the PRISMA count sevenfold.
- **Six PRISMA-S item numbers were wrong**, including dates cited as item 10
  (item 10 is *Search filters*; dates are item 13) and per-database record
  counts as item 13 (they are item 15). The appendix pointed reviewers at the
  wrong checklist rows. `tests/test_prisma_s_items.py` now checks every cited
  number against the checklist and against the subject of the item.
- **IEEE Xplore was classified as principal citing Gusenbauer & Haddaway
  (2020)**, whose list of 14 principal systems does not include it. The tier is
  retained as a documented field-convention choice for engineering and computing
  reviews, and the appendix now says so rather than attributing it to them.
- **`examples/review_config.json` was absent from the distribution**
  (`MANIFEST.in` shipped only `examples/*.py`), and the test that validates it
  skipped rather than failed - so the check passed vacuously in the one place it
  mattered, an unpacked sdist. The file ships and the test now fails if it is
  missing.
- **A RIS export parsed as MEDLINE lost every identifier silently.** The two
  formats share the `XX  - value` tag shape, so `parse_nbib` on a RIS file
  returned records carrying a title and nothing else (RIS spells the identifier
  `DO`; MEDLINE reads `LID`/`AID`) - an import that looks successful, keeps the
  PRISMA count right, and then deduplicates nothing. `parse_nbib_file` now
  raises `ParseFormatMismatch`, while `parse_nbib` stays tolerant by default so
  the no-raise robustness contract holds; the CLI warns and reports
  `detected_format` rather than refusing, keeping `--format` usable as an
  override.
- `parse_ris` and `parse_nbib` discarded records carrying an identifier but no
  title, though such a record is screenable and deduplicable.
- `parse_wos` returned contentless records for stanzas with neither title nor
  identifier, inflating "records identified".
- A malformed CSV row (one unbalanced quote) aborted iteration and discarded
  every subsequent row; rows are now read individually and counted as
  `malformed`.
- A latent `AttributeError` in `parsers/endnote.py` (an unguarded second
  `.search()` dereference) and an `Optional` violation in
  `HarvestResult.to_source_result()` that would have registered a blank search
  row in the PRISMA counts.
- README reported the Web of Science / Scopus overlap asymmetry without figures;
  it now quotes the published values (99.11 % of WoS journals are in Scopus).
  A "~34 % in the other direction" figure that appeared in the project
  specification is not supported by the cited source - deriving it from that
  paper's own published ratios gives ~81 % - and is not used.

### Changed

- Static analysis: ruff from 165 findings to zero and mypy from 28 errors to
  zero, without behavioural change; both are blocking in CI.
- Robustness is verified rather than asserted: 133 parser-by-corruption
  combinations and 49 parser-by-encoding round-trips, with no unhandled
  exception and no unaccounted record loss.
- Test suite at that release: 981 → 1491 tests, coverage 98 %.

## [1.3.0] - 2026-08

Deduplication accuracy above the published ASySD result, a Scopus client
verified against the live API, and reproducible harvesting.

### Added

- `corpusslr/harvest.py` - reproducible harvesting for PRISMA-S: an archive of
  raw API responses with checksums, replay of an analysis **without network
  access**, a deterministic corpus checksum over bibliographic fields
  (excluding citation counts, which drift), and drift detection between
  harvests. Measured against the live Crossref API: the same record set is
  returned in an unstable order (2 of 5 runs matched the reference order) and
  cursor tokens differ between runs, so canonical sorting is a precondition for
  a repeatable checksum. With it, two independent harvests produced identical
  checksums.
- `corpusslr/validate.py` - the identifier-blind validation protocol as part of
  the package rather than a one-off script (45 tests).

### Changed

- Public API grew from 87 to 96 symbols.
- Deduplication F1 improved from 0.9964 to **0.9996** (FP 0, FN 1), above the
  published ASySD figure of 0.9990 (FP 0, FN 2). Under an assignment rule
  independent of the metric's own convention the grouping is exact (F1 1.0000).
  Reached by diagnosing each remaining error separately rather than tuning a
  threshold; five disjoint error classes, four of them domain-independent
  normalisation defects.

### Fixed

- **DOI percent-encoding**: a DOI serialised from a URL writes Elsevier PII
  parentheses as `%28`/`%29`; `normalize_doi()` now percent-decodes, guarded
  against double decoding.
- **Page ranges destroyed by spreadsheets**: Excel turns `11-9` into `11-Sep`
  and `11-19` into `Nov-19` - 38 of 1845 records in the benchmark. Recovering
  the original is ambiguous (`Sep-11` is either 9-11 or 11-9), so
  `excel_mangled_pages()` treats such a value as **unknown**: an unreadable
  page never blocks a merge.
- **Prefixed article numbers**: `137960` and `e0137960` denote the same item;
  comparison is now on digits.
- **Two publisher DOIs for one work**: `_copublication_evidence()` overrides the
  conflicting-identifier block, but only on agreement of title (≥ 0.99), year,
  first page and author. An exhaustive check of all pairs found 4 matches, all
  true duplicates, no distinct pairs.
- **Conference abstract versus article**: the gold standard and Cochrane treat a
  conference abstract and the article as two reports of one study. A broad
  signature would have split 110 pairs to fix 1 and was rejected; the adopted
  rule requires the absence of both a DOI and pages on the conference side.
- **Scopus `LANGUAGE()` accepted English language names, not ISO codes**, and an
  unrecognised value **emptied the entire search with no error message** - a
  review would have returned zero records unnoticed. Measured metadata
  completeness (50 records, COMPLETE view): DOI 98 %, abstract 96 %, ISSN 96 %,
  keywords 88 %, `prism:pageRange` only 22 % (backfilled from `article-number`
  to 100 %). The STANDARD view returns no authors, keywords or abstracts at all,
  so it is unusable for screening without abstract recovery.
- Deduplication cost regression removed: the accuracy mechanisms of this release
  had raised the cost to 6459 µs/record. Profiling identified expensive title
  matching over all ~44 candidate pairs per record and an unmemoised
  `norm_title` (299 428 recomputations at 6 000 records). Memoisation plus an
  exact length bound brought it to **238 µs/record with no change in accuracy**.
  Measured separately afterwards, the two contribute very unequally:
  memoisation is worth 7.0x-8.0x, while the length bound is within noise of 1x
  and is retained only because it is an exact necessary condition that cannot
  alter a result. The end-to-end ~27x therefore also reflects the surrounding
  blocking work, not the length bound.

## [1.2.0] - 2026-08

Web of Science API access and multi-pass blocking in deduplication.

### Added

- `corpusslr/sources/wos.py` - `WosStarterSource` for the Web of Science Starter
  API (`X-ApiKey` header, 50 hits per page, guarded pagination),
  `parse_wos_hit()` testable without HTTP, and mapping of `uid` (`WOS:...`) and
  `MEDLINE:12345678`-style PMIDs into the identifier cascade. Before this
  release WoS was reachable only through the file-export parser, which is a gap
  rather than a design decision for a database the registry classifies as
  principal. Starter returns no abstracts; the PRISMA-S event carries a note and
  points to `recover_abstracts()`.
- `SearchQuery.to_wos()` (`TS=`/`TI=`, `PY=`, `DT=`, `LA=` syntax).
- Cursor-based Scopus pagination, which bypasses the `start+count ≤ 5000` offset
  limit (verified: 450 unique records across 5 pages).
- Multi-pass blocking in deduplication, addressing a limitation recorded in
  1.1.0: a **locus guard** (`separate_by_locus`), where a shared identifier does
  not link items differing in first page, or in volume and year - the signature
  of a conference supplement (FP 10 → 2); and **blocking rounds**
  (`blocking_rounds`), where candidates from exact agreement on a field
  combination (`author+year+pages`, `journal+volume+pages` and three others) are
  judged by a more permissive title threshold, because combination agreement is
  independent evidence (FN 8 → 6).

### Changed

- API sources: 9 → 10. Tests: 592 → 734. Coverage held at 98 %.
- Deduplication F1: 0.9929 → **0.9964** (FP 2, FN 7), halving the distance to
  ASySD and ahead of EndNote (0.983) and SRA-DM (0.926). The end-to-end metric
  improves far less (0.9810 → 0.9829) because it is dominated by the choice of
  which copy to retain, which these techniques do not affect.
- `sources/scopus.py`: 93 → 494 lines, 100 % coverage, 54 tests.
- Blocking-round bucket cap set to 25: without it, 60 000 records consumed
  1.25 GB and 33 s; with it, 101 MB and 8.4 s at identical accuracy.

### Fixed

Four defects in the Scopus client, each verified against the live API with
institutional access (key plus insttoken); the client had never been run against
the real API before this release.

- Only `dc:creator` was retrieved, giving one author instead of the full list,
  which directly corrupts surname comparison in deduplication and the export.
  The COMPLETE view now parses the `author` array: **17 authors instead of 1** on
  the control record, plus keywords and a 1694-character abstract.
- The `start+count ≤ 5000` limit was not handled, so a larger corpus ended the
  paging loop with HTTP 400. The last page is now trimmed to the limit with an
  explicit note in the PRISMA-S event.
- `count=25` was used where 200 is permitted, costing eight times the requests.
  Page size is now matched to the view (200 for STANDARD, 25 for COMPLETE - the
  measured API maxima).
- Permission errors were not distinguished: a 401 from outside the institutional
  network looked like a bad key. Elsevier returns an identical message for both,
  confirmed empirically, so the error text now names both causes and points to
  `insttoken`.

## [1.1.0] - 2026-08

Audit release: 17 defects repaired, sources and parsers extended, deduplication
independently validated.

### Added

- API sources: Semantic Scholar (S2AG; relevance search, optional key, flagged
  as **non-reproducible syntax** in `SearchEvent.notes`), arXiv (Atom API,
  3-second `min_interval` per the terms of use), bioRxiv and medRxiv (the API
  exposes **date windows only**, not full-text search, so term filtering is
  local - documented in the docstring and in the event note).
- Export parsers: BibTeX (LaTeX decoding, IEEE Xplore and ACM dialects), EndNote
  XML, vendor CSV for five providers (Scopus, WoS, IEEE Xplore, Dimensions,
  EBSCO), and RIS extended to Embase, Cochrane CENTRAL, EBSCOhost (distinguishing
  Business Source, PsycINFO, CINAHL, ERIC) and ProQuest ABI/INFORM.
- `sources/registry.py` - principal/supplementary classification after
  Gusenbauer & Haddaway (2020). `audit_strategy()` warns when a review rests
  only on supplementary sources, has a single principal source, or draws most of
  its records from supplementary systems; the result enters the PRISMA-S
  appendix.

### Changed

- Package: 2740 statements → 5250 lines across 28 modules. Tests: 47 → **592**,
  all offline. Coverage: 87 % → **98 %**. API sources: 4 → 9. File parsers: 3
  formats → **7**.
- Deduplication F1: 0.957 → **0.993**; end-to-end (including the choice of copy
  to retain) 0.870 → **0.981**.
- 60 000 records with titles sharing a common prefix: did not finish in 12
  minutes → **5.2 s**.

### Fixed

Seventeen defects, each with a regression test. In descending order of
methodological consequence:

- **False-positive merging despite conflicting identifiers.** The fuzzy stage
  merged records with **different DOIs/PMIDs** when titles were similar: "…part
  1" with "…part 2", "trial of drug X" with "trial of drug Y". In a systematic
  review that is the silent loss of a distinct study. `_conflicting_ids()` now
  blocks the merge regardless of title similarity.
- **False positives from a shared conference-supplement DOI**, found only during
  validation against the ASySD gold standard: publishers assign one DOI to an
  entire supplement of conference abstracts. In the Diabetes set, 21 DOIs
  covered 140 records describing different works (one DOI covered 11 records
  with 6 titles, maximum title similarity 0.47). **91 % of all false positives
  arose in the identifier stage, not the fuzzy stage** - the opposite of what
  intuition suggests. The `id_title_min=0.50` parameter now requires title
  similarity ≥ 0.50 when an identifier is shared by **three or more** records.
  The multiplicity condition is necessary: an unconditional guard breaks
  transitive closure, because the normal cross-database case (same DOI, subtitle
  present in one database and absent in the other) would be rejected. False
  positives 66 → 10.
- **No transitive closure in the identifier cascade**: a record sharing a DOI
  with one record and a PMID with another describes the same work, but
  first-matching-cluster assignment did not join all three.
- **Performance degenerating to quadratic behaviour** on titles with a common
  prefix.
- **Silent skipping of the fuzzy stage on bucket overflow.**
- **Unstable and inferior choice of the record to retain.**
- **Title normalisation destroying barred letters and ligatures.**
- **PRISMA flow validation with a gap**; **audit trail losing identifiers**;
  **unguarded pagination loops**; **abstract enrichment using its own weaker DOI
  normalisation**; **CSV export vulnerable to formula injection**; **BibTeX
  export escaping and entry type**; **query-compilation warnings accumulating**;
  **unparenthesised year clause in the Scopus query**; **incorrect ProQuest
  dialect detection**; **documentation and code disagreements**.

## [0.1.0] - 2026-08 (development milestone, was labelled 1.0.0)

Initial release: 4 API sources, 3 export formats with 8 RIS dialects, cascading
deduplication, PRISMA 2020 flow diagram, PRISMA-S appendix. 47 tests,
deduplication F1 0.957 on the ASySD Diabetes gold standard.

[Unreleased]: https://github.com/s-matysik/CorpusSLR/compare/v1.3.0...HEAD
[1.3.0]: https://github.com/s-matysik/CorpusSLR/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/s-matysik/CorpusSLR/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/s-matysik/CorpusSLR/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/s-matysik/CorpusSLR/releases/tag/v1.0.0
