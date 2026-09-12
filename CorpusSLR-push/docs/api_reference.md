# API reference

Generated from the installed package (`corpusslr 1.0.0`) by `validation/generate_api_reference.py` -- every entry is introspected from the code, so a renamed or removed symbol cannot linger here. `tests/test_docs_examples.py` asserts that every public symbol appears.

For a narrative walkthrough see [`user_guide.md`](user_guide.md).

## Core data model

### `Record`

A single harmonized bibliographic record.

- `id_keys()` - Ordered (method, value) identifier keys for exact-match dedup.
- `merge_from(other: "'Record'") -> 'None'` - Fill blanks from *other*; keep the longer abstract; union ids.
- `richness() -> 'float'` - Heuristic completeness score used to pick the record to keep.
- `to_dict() -> 'dict'` - see source

Fields: `title`, `abstract`, `authors`, `year`, `journal`, `doi`, `pmid`, `openalex_id`, `scopus_id`, `issn`, `volume`, `issue`, `pages`, `doc_type`, `language`, `keywords`, `affiliations`, `url`, `open_access`, `cited_by`, `source`, `source_id`, `search_id`, `uid`, `provenance`, `raw`

### `Corpus`

Holds all retrieved records together with their retrieval provenance.

- `add_records(records: 'List[Record]', database: 'str', platform: 'str' = '', interface: 'str' = 'file export', query: 'str' = '', filters: 'str' = '', date_run: 'str' = '', notes: 'str' = '') -> 'SearchEvent'` - Register file-parsed records (WoS/RIS/nbib exports) as a search event.
- `add_search(result: 'SourceResult') -> 'SearchEvent'` - see source
- `get(uid: 'str') -> 'Optional[Record]'` - see source
- `identified_by_source() -> 'Dict[str, int]'` - see source
- `total_identified() -> 'int'` - see source

### `SearchQuery`

blocks: list of OR-groups, joined with AND.

- `compile_all() -> 'Dict[str, object]'` - see source
- `to_arxiv() -> 'str'` - arXiv Atom API query string (``search_query`` parameter).
- `to_crossref_params() -> 'Dict[str, str]'` - Crossref has no boolean field search: lossy 'query.bibliographic'.
- `to_openalex() -> 'str'` - see source
- `to_openalex_filters() -> 'Dict[str, str]'` - see source
- `to_pubmed() -> 'str'` - see source
- `to_scopus() -> 'str'` - see source
- `to_semanticscholar() -> 'Dict[str, str]'` - Semantic Scholar Graph API: relevance search, no boolean operators.
- `to_wos() -> 'str'` - Web of Science advanced-search string (Starter/Expanded API ``q``).

Fields: `blocks`, `years`, `doc_types`, `languages`, `title_only`, `warnings`

### `SearchEvent`

One executed search in one information source (PRISMA-S items 1-13).

Fields: `database`, `platform`, `interface`, `query`, `filters`, `date_run`, `records_retrieved`, `url`, `notes`, `search_id`

### `SourceResult`

Return type of every source/parser entry point.

Fields: `event`, `records`

## Retrieval (API clients)

### `ArxivSource`

Boolean search over arXiv metadata via the Atom API.

- `search(query: 'SearchQuery', max_results: 'int' = 1000) -> 'SourceResult'` - see source

### `BaseSource`

Abstract API source. Subclasses implement :meth:`search`.

- `search(query: 'SearchQuery', max_results: 'int' = 2000) -> 'SourceResult'` - see source

### `BiorxivSource`

bioRxiv preprints (life sciences).

- `estimate_cost(query: 'SearchQuery') -> 'dict'` - Report what an exhaustive search of this query's window would cost.
- `search(query: 'SearchQuery', max_results: 'int' = 1000, max_scanned: 'Optional[int]' = -1) -> 'SourceResult'` - Enumerate a posting-date window and filter it locally.

### `CrossrefSource`

Abstract API source. Subclasses implement :meth:`search`.

- `search(query: 'SearchQuery', max_results: 'int' = 2000) -> 'SourceResult'` - see source

### `MedrxivSource`

medRxiv preprints (health sciences).

- `estimate_cost(query: 'SearchQuery') -> 'dict'` - Report what an exhaustive search of this query's window would cost.
- `search(query: 'SearchQuery', max_results: 'int' = 1000, max_scanned: 'Optional[int]' = -1) -> 'SourceResult'` - Enumerate a posting-date window and filter it locally.

### `OpenAlexSource`

Abstract API source. Subclasses implement :meth:`search`.

- `search(query: 'SearchQuery', max_results: 'int' = 2000) -> 'SourceResult'` - see source

### `PubMedSource`

Abstract API source. Subclasses implement :meth:`search`.

- `search(query: 'SearchQuery', max_results: 'int' = 2000) -> 'SourceResult'` - see source

### `ScopusSource`

Scopus Search API source with view-aware paging and error diagnostics.

- `page_size(max_results: 'Optional[int]' = None) -> 'int'` - Return the largest page size the API accepts for the active view.
- `search(query: 'SearchQuery', max_results: 'int' = 2000) -> 'SourceResult'` - Run one Scopus search and return records plus its PRISMA-S event.

### `SemanticScholarSource`

Relevance search over the Semantic Scholar Academic Graph.

- `search(query: 'SearchQuery', max_results: 'int' = 1000) -> 'SourceResult'` - see source

### `WosExpandedSource`

Search the Web of Science Core Collection through the Expanded API.

- `search(query: 'SearchQuery', max_results: 'int' = 2000) -> 'SourceResult'` - see source

### `WosStarterSource`

Search the Web of Science Core Collection through the Starter API.

- `search(query: 'SearchQuery', max_results: 'int' = 2000) -> 'SourceResult'` - Execute *query* against the Starter API and page through the hits.

## File-export parsers

### `decode_export(data: 'bytes', encoding: 'str' = 'auto', report: 'Optional[ParseReport]' = None, path: 'str' = '') -> 'str'`

Decode export *data* to text, sniffing the encoding when asked.

### `detect_bibtex_dialect(text: 'str') -> 'str'`

Identify the exporting platform from marker fields.

### `detect_csv_dialect(header_row) -> 'str'`

Return the vendor whose signature columns best match *header_row*.

### `detect_dialect(text: 'str') -> 'str'`

Identify the exporting platform from marker tags in the header.

### `detect_export_format(text: 'str') -> 'str'`

Identify a database export from its content, not its file name.

### `extract_table_rows(text: 'str', report: 'Optional[ParseReport]' = None) -> 'List[List[str]]'`

Return the cell grid of the data table in an HTML document.

### `looks_like_enw(text: 'str') -> 'bool'`

True when *text* is EndNote tagged rather than RIS, XML or BibTeX.

### `looks_like_html(text: 'str') -> 'bool'`

True when *text* is an HTML document rather than delimited text.

### `parse_arxiv_atom(xml_text: 'str') -> 'List[Record]'`

Parse an arXiv Atom feed into records (no HTTP, unit-testable).

### `parse_arxiv_atom_file(path: 'str', encoding: 'str' = 'utf-8-sig') -> 'List[Record]'`

Parse a saved Atom feed from disk (offline replication of a search).

### `parse_bibtex(text: 'str', source_name: 'str' = '', dialect: 'str' = 'auto', report: 'Optional[ParseReport]' = None) -> 'List[Record]'`

Parse BibTeX *text* into :class:`~corpusslr.record.Record` objects.

### `parse_bibtex_file(path: 'str', source_name: 'str' = '', dialect: 'str' = 'auto', encoding: 'str' = 'auto', report: 'Optional[ParseReport]' = None) -> 'List[Record]'`

Read *path* and parse it with :func:`parse_bibtex`.

### `parse_csv_export(text: 'str', dialect: 'str' = 'auto', source_name: 'str' = '', delimiter: 'Optional[str]' = None, report: 'Optional[ParseReport]' = None) -> 'List[Record]'`

Parse a CSV/TSV database export into records.

### `parse_csv_export_file(path: 'str', dialect: 'str' = 'auto', source_name: 'str' = '', encoding: 'str' = 'auto', delimiter: 'Optional[str]' = None, report: 'Optional[ParseReport]' = None) -> 'List[Record]'`

Read *path* and parse it with :func:`parse_csv_export`.

### `parse_csv_rows(rows: 'Sequence[Sequence[str]]', dialect: 'str' = 'auto', source_name: 'str' = '', report: 'Optional[ParseReport]' = None) -> 'List[Record]'`

Map an already-split cell grid onto records.

### `parse_endnote_xml(text: 'str', source_name: 'str' = '', report: 'Optional[ParseReport]' = None) -> 'List[Record]'`

Parse an EndNote XML export into records.

### `parse_endnote_xml_file(path: 'str', source_name: 'str' = '', encoding: 'str' = 'auto', report: 'Optional[ParseReport]' = None) -> 'List[Record]'`

Read *path* and parse it with :func:`parse_endnote_xml`.

### `parse_enw(text: 'str', source_name: 'str' = '', report: 'Optional[ParseReport]' = None) -> 'List[Record]'`

Parse EndNote tagged (``.enw``) *text* into records.

### `parse_enw_file(path: 'str', source_name: 'str' = '', encoding: 'str' = 'auto', report: 'Optional[ParseReport]' = None) -> 'List[Record]'`

Read and parse an EndNote tagged file, sniffing the encoding.

### `parse_export_file(path: 'str', fmt: 'str' = 'auto', dialect: 'str' = 'auto', encoding: 'str' = 'auto', source_name: 'str' = '') -> 'Tuple[List[Record], Dict[str, Any]]'`

Parse one exported file, detecting format and vendor dialect by content.

### `parse_html_table(text: 'str', dialect: 'str' = 'auto', source_name: 'str' = '', report: 'Optional[ParseReport]' = None) -> 'List[Record]'`

Parse an HTML-table export (ProQuest/WoS ``.xls``) into records.

### `parse_html_table_file(path: 'str', dialect: 'str' = 'auto', source_name: 'str' = '', encoding: 'str' = 'auto', report: 'Optional[ParseReport]' = None) -> 'List[Record]'`

Read and parse an HTML-table export file.

### `parse_nbib(text: 'str', source_name: 'str' = 'PubMed', report: 'Optional[ParseReport]' = None, strict_format: 'bool' = False) -> 'List[Record]'`

Parse a PubMed ``.nbib`` (MEDLINE tagged) export.

### `parse_nbib_file(path: 'str', source_name: 'str' = 'PubMed', encoding: 'str' = 'auto', report: 'Optional[ParseReport]' = None, strict_format: 'bool' = True) -> 'List[Record]'`

Read and parse a ``.nbib`` file, sniffing the encoding by default.

### `parse_preprint(item: 'dict', server: 'str' = '') -> 'Record'`

Map one Cold Spring Harbor ``collection`` entry onto a :class:`Record`.

### `parse_pubmed_xml(xml_text: 'str') -> 'List[Record]'`

Parse a PubMed ``efetch`` XML response into records.

### `parse_ris(text: 'str', dialect: 'str' = 'auto', source_name: 'str' = '', report: 'Optional[ParseReport]' = None) -> 'List[Record]'`

Parse a RIS export, detecting the vendor dialect from content.

### `parse_ris_file(path: 'str', dialect: 'str' = 'auto', source_name: 'str' = '', encoding: 'str' = 'auto', report: 'Optional[ParseReport]' = None) -> 'List[Record]'`

Read and parse an RIS file, sniffing the encoding by default.

### `parse_s2_paper(p: 'dict') -> 'Record'`

Map one S2AG ``paper`` object onto a :class:`Record`.

### `parse_wos(text: 'str', source_name: 'str' = 'Web of Science', report: 'Optional[ParseReport]' = None) -> 'List[Record]'`

Parse a Web of Science tagged export (``.txt`` / ``.ciw``).

### `parse_wos_expanded_record(rec: 'Dict[str, Any]') -> 'Record'`

Turn one ``REC`` node into a :class:`~corpusslr.record.Record`.

### `parse_wos_file(path: 'str', source_name: 'str' = 'Web of Science', encoding: 'str' = 'auto', report: 'Optional[ParseReport]' = None) -> 'List[Record]'`

Read and parse a WoS tagged export, sniffing the encoding by default.

### `parse_wos_hit(hit: 'dict', source_name: 'str' = 'Web of Science Core Collection', db: 'str' = 'WOS') -> 'Record'`

Map one Starter API ``hits[]`` object onto a :class:`Record`.

### `sniff_encoding(data: 'bytes') -> 'Tuple[str, List[str]]'`

Guess the text encoding of an export file.

### `ParseReport`

Mutable tally of what a parser accepted, rejected and warned about.

- `accept(n: 'int' = 1) -> 'None'` - Count *n* units as returned to the caller.
- `reason_counts() -> 'Dict[str, int]'` - Rejections tallied per reason, for a per-source import table.
- `reject(index: 'int', reason: 'str', detail: 'str' = '') -> 'None'` - Record one dropped unit.
- `saw(n: 'int' = 1) -> 'None'` - Count *n* input units as seen.
- `summary() -> 'str'` - One-line human-readable summary for a log or console report.
- `to_dict() -> 'Dict[str, Any]'` - Serialise for a harvest manifest or PRISMA-S appendix.
- `warn(message: 'str') -> 'None'` - Record a non-fatal observation.

### `ParseFormatMismatch`

Raised when a file is asked to be parsed as a format it plainly is not.

- `add_note(object, /)` - Exception.add_note(note) -- add a note to the exception
- `with_traceback(object, /)` - Exception.with_traceback(tb) -- set self.__traceback__ to tb and return self.

### `REJECTION_REASONS`

Module-level tuple, 5 entries.

## Deduplication

### `deduplicate(corpus: 'Corpus | List[Record]', fuzzy_threshold: 'float' = 0.93, year_tolerance: 'int' = 1, block_prefix: 'int' = 10, max_block: 'int' = 400, id_title_min: 'float' = 0.5, separate_by_locus: 'bool' = True, blocking_rounds: 'bool' = True, round_title_min: 'float' = 0.7, allow_copublication: 'bool' = True, separate_conference: 'bool' = True) -> 'DedupResult'`

Cascading deduplication: identifiers first, then fuzzy title matching.

### `DedupResult`

DedupResult(records: 'List[Record]', report: 'DedupReport')

Fields: `records`, `report`

### `DedupReport`

DedupReport(before: 'int' = 0, after: 'int' = 0, decisions: 'List[DedupDecision]' = <factory>, by_method: 'Dict[str, int]' = <factory>, overlap: 'Dict[Tuple[str, str], int]' = <factory>, id_links_rejected: 'int' = 0, oversized_blocks_skipped: 'int' = 0, records_without_candidates: 'int' = 0, round_candidates: 'int' = 0, copublication_merges: 'int' = 0, by_locus: 'Dict[str, int]' = <factory>)

- `overlap_markdown() -> 'str'` - see source
- `summary() -> 'str'` - see source
- `to_csv(path: 'str') -> 'str'` - see source
- `warnings() -> 'List[str]'` - Conditions that may have degraded recall, for the audit trail.

Fields: `before`, `after`, `decisions`, `by_method`, `overlap`, `id_links_rejected`, `oversized_blocks_skipped`, `records_without_candidates`, `round_candidates`, `copublication_merges`, `by_locus`

### `normalize_doi(doi: 'Optional[str]') -> 'str'`

Normalize a DOI: lowercase, percent-decode, strip resolver prefixes.

### `normalize_title(title: 'Optional[str]') -> 'str'`

Aggressive title normalization for fuzzy duplicate detection.

## Reporting (PRISMA / PRISMA-S)

### `PrismaFlow`

PrismaFlow(db_counts: 'Dict[str, int]' = <factory>, duplicates_removed: 'int' = 0, dedup_by_method: 'Dict[str, int]' = <factory>, automation_excluded: 'int' = 0, other_excluded: 'int' = 0, records_excluded: 'int' = 0, reports_not_retrieved: 'int' = 0, fulltext_exclusions: 'Dict[str, int]' = <factory>, studies_included: 'int' = 0, reports_included: 'Optional[int]' = None)

- `counts() -> 'Dict[str, object]'` - see source
- `from_dedup(corpus: 'Corpus', result: 'DedupResult') -> "'PrismaFlow'"` - see source
- `set_screening(records_excluded: 'int', reports_not_retrieved: 'int' = 0, fulltext_exclusions: 'Optional[Dict[str, int]]' = None, studies_included: 'int' = 0, reports_included: 'Optional[int]' = None, automation_excluded: 'int' = 0, other_excluded: 'int' = 0) -> "'PrismaFlow'"` - see source
- `to_markdown() -> 'str'` - see source
- `to_svg(path: 'Optional[str]' = None) -> 'str'` - see source
- `validate() -> 'List[str]'` - Return every arithmetic inconsistency in the flow (empty = valid).

Fields: `db_counts`, `duplicates_removed`, `dedup_by_method`, `automation_excluded`, `other_excluded`, `records_excluded`, `reports_not_retrieved`, `fulltext_exclusions`, `studies_included`, `reports_included`

### `prisma`

Module-level module.

### `prisma_s`

Module-level module.

### `prisma_s_appendix(corpus: 'Corpus', result: 'Optional[DedupResult]' = None, path: 'str' = 'prisma_s_appendix.md', fuzzy_threshold: 'float' = 0.93, year_tolerance: 'int' = 1) -> 'str'`

Write the appendix to *path* (.md, or .docx if python-docx present).

### `prisma_s_markdown(corpus: 'Corpus', result: 'Optional[DedupResult]' = None, fuzzy_threshold: 'float' = 0.93, year_tolerance: 'int' = 1) -> 'str'`

Render the PRISMA-S search-reporting appendix as Markdown.

## Source registry

### `classify_source(name: 'Optional[str]') -> 'str'`

Return ``"principal"``, ``"supplementary"`` or ``"unknown"``.

### `canonical_source(name: 'Optional[str]') -> 'str'`

Resolve a free-form database name to its canonical registry key.

### `source_evidence(name: 'Optional[str]') -> 'str'`

Return how a source's tier is evidenced (see :data:`SOURCE_EVIDENCE`).

### `source_note(name: 'Optional[str]') -> 'str'`

Return the methods-section caveat for *name*, or ``""`` if none applies.

### `SOURCE_TIER`

Module-level dict, 21 entries.

### `SOURCE_EVIDENCE`

Module-level dict, 21 entries.

### `SOURCE_NOTES`

Module-level dict, 8 entries.

## Export

### `to_bibtex(records: 'Iterable[Record]', path: 'str') -> 'str'`

Write records as BibTeX, returning the path written.

### `to_csv(records: 'Iterable[Record]', path: 'str', columns: 'List[str] | None' = None) -> 'str'`

Write records to CSV, returning the path written.

### `to_ris(records: 'Iterable[Record]', path: 'str') -> 'str'`

Write records as RIS, returning the path written.

### `to_scopus_csv(records: 'Iterable[Record]', path: 'str') -> 'str'`

Write records as a Scopus CSV export, returning the path written.

### `to_screening_csv(records: 'Iterable[Record]', path: 'str') -> 'str'`

Write the columns a screening tool needs, returning the path written.

## Reproducible harvesting

### `HarvestArchive`

Directory of raw API responses plus a ``manifest.json`` index.

- `add_harvest(manifest: 'HarvestManifest') -> 'None'` - Register (or replace) a harvest manifest in this archive.
- `add_response(url: 'str', params: 'Optional[dict]', status_code: 'int', text: 'str' = '', payload: 'Any' = None, headers: 'Optional[dict]' = None, harvest_id: 'str' = 'H1', authenticated: 'bool' = False) -> 'Dict[str, Any]'` - Write one HTTP response to disk and index it.
- `create(path: 'str', package_version: 'str' = '') -> "'HarvestArchive'"` - Open *path* for writing, creating it if needed.
- `harvest_ids() -> 'List[str]'` - see source
- `load_response(entry: 'Dict[str, Any]', verify: 'bool' = True) -> 'ArchivedResponse'` - Materialize one archived response, checking its checksum.
- `manifest(harvest_id: 'Optional[str]' = None) -> 'HarvestManifest'` - Return one harvest manifest; the only one if *harvest_id* is None.
- `next_harvest_id() -> 'str'` - see source
- `open(path: 'str') -> "'HarvestArchive'"` - Open an existing archive read-only (used for replay and audit).
- `resolve_harvest_id(database: 'str' = '') -> 'Optional[str]'` - Pick the harvest to replay: the only one, or the one for *database*.
- `response_index(harvest_id: 'Optional[str]' = None) -> 'List[Dict[str, Any]]'` - see source
- `verify(harvest_id: 'Optional[str]' = None) -> 'List[str]'` - Integrity audit; returns a list of human-readable problems.
- `write_manifest() -> 'str'` - Serialize the manifest; returns its path.

### `HarvestDiff`

Explicit, countable difference between two harvests of one query.

- `summary() -> 'str'` - see source
- `to_dict() -> 'Dict[str, Any]'` - see source
- `to_markdown(limit: 'int' = 20) -> 'str'` - Drift table for a PRISMA-S appendix or a revision cover letter.

Fields: `added`, `removed`, `changed`, `citation_updates`, `unchanged`, `n_before`, `n_after`, `checksum_before`, `checksum_after`, `label_before`, `label_after`

### `HarvestError`

Archive is unusable, incomplete, tampered with, or replay diverged.

- `add_note(object, /)` - Exception.add_note(note) -- add a note to the exception
- `with_traceback(object, /)` - Exception.with_traceback(tb) -- set self.__traceback__ to tb and return self.

### `HarvestManifest`

Everything needed to cite, audit and repeat one harvest.

- `from_dict(d: 'dict') -> "'HarvestManifest'"` - see source
- `to_dict() -> 'Dict[str, Any]'` - see source
- `to_markdown() -> 'str'` - Reproducibility statement for a methods section or appendix.

Fields: `harvest_id`, `database`, `platform`, `interface`, `url`, `query`, `filters`, `compiled_params`, `max_results`, `package`, `package_version`, `harvested_at`, `mode`, `authenticated`, `api_version`, `n_responses`, `n_records`, `n_with_doi`, `checksum`, `checksum_algorithm`, `checksum_fields`, `volatile_fields`, `warnings`, `notes`, `record_index`

### `HarvestResult`

Records in canonical order plus the provenance needed to publish them.

- `to_source_result() -> 'SourceResult'` - Adapt to the package-wide return type for ``Corpus.add_search``.
- `write_manifest(path: 'str') -> 'str'` - Write the standalone manifest JSON (for a data-availability deposit).

Fields: `records`, `event`, `manifest`, `archive_path`, `mode`, `checksum_matches`, `recorded_checksum`

### `ReplaySession`

Offline ``requests.Session`` stand-in served from a :class:`HarvestArchive`.

- `get(url, params=None, headers=None, timeout=None, **kw)` - see source

### `compare_harvests(before, after, label_before: 'str' = '', label_after: 'str' = '') -> 'HarvestDiff'`

Quantify the drift between two harvests of the same query.

### `harvest(source, query, max_results: 'Optional[int]' = None, archive=None, replay: 'bool' = False, harvest_id: 'Optional[str]' = None, package_version: 'str' = '', notes: 'str' = '', verify: 'bool' = True, strict: 'bool' = True) -> 'HarvestResult'`

Run one reproducible harvest - live with archiving, or offline from archive.

### `harvest_markdown(results: 'Sequence[HarvestResult]') -> 'str'`

Reproducibility appendix for one or more harvests.

### `replay_harvest(source, query, archive, **kw) -> 'HarvestResult'`

Convenience wrapper: :func:`harvest` with ``replay=True``.

### `verify_archive(archive, harvest_id: 'Optional[str]' = None) -> 'List[str]'`

Integrity audit of an archive given as a path or object.

## Validation protocol

### `validate`

Module-level module.

### `validate_config(data: 'Any', origin: 'str' = 'config') -> 'Dict[str, Any]'`

Check a configuration object and return it normalised.

## Other public symbols

### `ARCHIVE_VERSION`

Module-level int.

### `ArchivedResponse`

Minimal ``requests.Response`` stand-in served from the archive.

- `json()` - see source
- `raise_for_status()` - see source

### `CHECKSUM_FIELDS`

Module-level tuple, 16 entries.

### `CORPUS_FORMAT`

Module-level str, 18 entries.

### `CREDENTIAL_ENV`

Module-level dict, 9 entries.

### `CliError`

A failure that must be reported as a message, not a traceback.

- `add_note(object, /)` - Exception.add_note(note) -- add a note to the exception
- `with_traceback(object, /)` - Exception.with_traceback(tb) -- set self.__traceback__ to tb and return self.

### `ConfigError`

The configuration file is unusable; the message names the fix.

- `add_note(object, /)` - Exception.add_note(note) -- add a note to the exception
- `with_traceback(object, /)` - Exception.with_traceback(tb) -- set self.__traceback__ to tb and return self.

### `DATABASES`

Module-level dict, 9 entries.

### `DataError`

Inputs were understood but the data or a remote service failed.

- `add_note(object, /)` - Exception.add_note(note) -- add a note to the exception
- `with_traceback(object, /)` - Exception.with_traceback(tb) -- set self.__traceback__ to tb and return self.

### `EXCLUDING_FLAGS`

Module-level frozenset, 2 entries.

### `NOTICE_FLAGS`

Module-level frozenset, 3 entries.

### `PERTURBATIONS`

Module-level dict, 7 entries.

### `RecordingSession`

``requests.Session`` proxy that archives every response it forwards.

- `get(url, params=None, headers=None, timeout=None, **kw)` - see source

### `ReviewSettings`

The answers collected so far, and the configuration they imply.

- `as_config() -> 'Dict[str, Any]'` - The review configuration these answers describe.
- `database_summary() -> 'str'` - see source
- `file_summary() -> 'str'` - see source
- `missing() -> 'List[str]'` - What still has to be answered before a run can start.
- `query_summary() -> 'str'` - see source

### `SCOPUS_COLUMNS`

Module-level tuple, 46 entries.

### `SourceError`

Unspecified run-time error.

- `add_note(object, /)` - Exception.add_note(note) -- add a note to the exception
- `with_traceback(object, /)` - Exception.with_traceback(tb) -- set self.__traceback__ to tb and return self.

### `TuiInterface`

The menu loop.

- `ask(prompt: 'str', default: 'str' = '') -> 'str'` - Read one line.  End of input is a request to quit, not a crash.
- `ask_secret(prompt: 'str') -> 'str'` - Read a credential without echoing it.
- `banner() -> 'None'` - see source
- `confirm(prompt: 'str', default: 'bool' = False) -> 'bool'` - see source
- `menu() -> 'str'` - see source
- `pause() -> 'None'` - see source
- `raw(text: 'str') -> 'None'` - Print a pre-formatted line (a table row) without rewrapping.
- `row(label: 'str', value: 'str') -> 'None'` - Print a ``label : value`` status row, wrapping long values.
- `rule(char: 'str' = '-') -> 'None'` - see source
- `run() -> 'int'` - The whole session.  Returns a process exit code.
- `say(text: 'str' = '') -> 'None'` - Print one wrapped paragraph.  No escape sequences, ever.
- `screen_check() -> 'None'` - see source
- `screen_databases() -> 'None'` - see source
- `screen_files() -> 'None'` - see source
- `screen_help() -> 'None'` - see source
- `screen_keys() -> 'None'` - see source
- `screen_output() -> 'None'` - see source
- `screen_query() -> 'None'` - see source
- `screen_run() -> 'None'` - see source
- `screen_settings() -> 'None'` - see source
- `status() -> 'None'` - see source
- `verbatim(text: 'str', indent: 'str' = '    ') -> 'None'` - Print *text* wrapped only at spaces, never truncated or hyphenated.

### `VOLATILE_FIELDS`

Module-level tuple, 2 entries.

### `apply_perturbation(record: 'Record', name: 'str', rng: 'Optional[random.Random]' = None) -> 'Optional[Record]'`

Return a perturbed deep copy of *record*, or ``None`` if out of scope.

### `audit_markdown(corpus) -> 'str'`

Render :func:`audit_strategy` as a Markdown section for the appendix.

### `audit_strategy(corpus) -> 'dict'`

Audit a corpus's source mix against Gusenbauer & Haddaway (2020).

### `build_parser() -> 'argparse.ArgumentParser'`

Construct the argument parser (exposed so that it can be tested).

### `check_retractions_crossref(records: 'Iterable[Record]', session=None, mailto: 'str' = '', max_records: 'Optional[int]' = None) -> 'Dict[str, object]'`

Verify retraction status against Crossref's structured relations.

### `cli`

Module-level module.

### `cli_main(argv: 'Optional[Sequence[str]]' = None, session: 'Any' = None, stdout=None, stderr=None) -> 'int'`

Run the CLI and return a process exit code.

### `clusters_from_decisions(decisions: 'Iterable', all_uids: 'Sequence[str]') -> 'List[List[str]]'`

Rebuild the transitive closure of merge decisions as explicit clusters.

### `config_checksum(config: 'Dict[str, Any]') -> 'str'`

SHA-256 over the canonicalised configuration.

### `config_home() -> 'str'`

Directory holding the credentials file and saved settings.

### `corpus`

Module-level module.

### `corpus_from_dict(payload: 'Dict[str, Any]', origin: 'str' = 'corpus') -> 'Tuple[Corpus, Optional[DedupResult]]'`

Rebuild a corpus and any recorded dedup from :func:`corpus_to_dict`.

### `corpus_profile(records: 'Sequence[Record]') -> 'Dict[str, float]'`

Metadata-completeness profile of a record set.

### `corpus_to_dict(corpus: 'Corpus', result: 'Optional[DedupResult]' = None) -> 'Dict[str, Any]'`

Serialise a corpus with its full retrieval provenance.

### `credential_slots() -> 'List[Dict[str, Any]]'`

The credential fields the interface offers, derived from the CLI.

### `credentials_path() -> 'str'`

Path of the private credentials file.

### `dedup`

Module-level module.

### `enrich`

Module-level module.

### `excel_mangle_pages(value: 'str') -> 'str'`

Render a page range as the date a spreadsheet would turn it into.

### `export`

Module-level module.

### `hide_identifiers(records: 'Iterable[Record]', fields: 'Sequence[str]' = ('doi', 'pmid', 'openalex_id', 'scopus_id', 'url', 'source_id')) -> 'List[Record]'`

Return deep copies of *records* with every identifier field emptied.

### `integrity`

Module-level module.

### `integrity_flag(record: 'Record') -> 'Optional[str]'`

Return the integrity flag for one record, or ``None``.

### `integrity_markdown(records: 'Iterable[Record]') -> 'str'`

Render the integrity check as Markdown for a PRISMA-S appendix.

### `is_identifier_only_title(title: 'Optional[str]') -> 'bool'`

True when *title* carries an identifier and no bibliographic content.

### `load_config(path: 'str') -> 'Dict[str, Any]'`

Read and validate a review configuration from JSON (or YAML).

### `load_credentials() -> 'Dict[str, str]'`

Read the stored credentials, returning ``{}`` when there are none.

### `looks_binary(data: 'bytes') -> 'str'`

Return a description of the container format, or ``""`` for text.

### `pair_metrics(clusters: 'Iterable[Sequence[str]]', truth: 'Dict[str, str]') -> 'Dict[str, float]'`

Pairwise precision/recall/F1 over co-membership, scored on *truth* only.

### `parsers`

Module-level module.

### `quality`

Module-level module.

### `quality_csv(records: 'Iterable[Record]', path: 'str') -> 'str'`

Write the per-source completeness table to CSV, returning the path.

### `quality_markdown(records: 'Iterable[Record]') -> 'str'`

Render the per-source completeness table as Markdown.

### `quality_report(records: 'Iterable[Record]') -> 'Dict[str, Dict[str, float]]'`

Per-source metadata completeness, as the fraction of records with a field.

### `query`

Module-level module.

### `read_corpus(path: 'str') -> 'Tuple[Corpus, Optional[DedupResult]]'`

Read a corpus JSON written by :func:`write_corpus`.

### `read_export_text(path: 'str', encoding: 'str' = 'auto', report: 'Optional[ParseReport]' = None) -> 'str'`

Read an export file and decode it, sniffing the encoding by default.

### `reconstruct_abstract(inverted: 'Optional[dict]') -> 'str'`

Rebuild plain text from OpenAlex ``abstract_inverted_index``.

### `record`

Module-level module.

### `record_checksum(rec: 'Record') -> 'str'`

SHA-256 over the stable bibliographic identity of one record.

### `record_diff_fields(a: 'Record', b: 'Record', ignore: 'Sequence[str]' = ('uid', 'search_id', 'provenance')) -> 'List[str]'`

Names of fields whose values differ between two records.

### `record_fingerprint(rec: 'Record') -> 'Dict[str, Any]'`

Compact per-record entry stored in the manifest.

### `record_key(rec: 'Record') -> 'str'`

Identity key used to align two harvests, strongest evidence first.

### `record_metrics(clusters: 'Iterable[Sequence[str]]', truth: 'Dict[str, str]') -> 'Dict[str, float]'`

Record-level metrics in the ASySD convention, for comparability.

### `records_checksum(records: 'Sequence[Record]') -> 'str'`

Order-independent checksum of a record set.

### `records_equal(a: 'Sequence[Record]', b: 'Sequence[Record]', ignore: 'Sequence[str]' = ('uid', 'search_id', 'provenance')) -> 'bool'`

Field-by-field equality of two record sequences (not object identity).

### `recover_abstracts(records: 'Iterable[Record]', mailto: 'str' = '', min_len: 'int' = 250, batch: 'int' = 25, session: 'requests.Session | None' = None, sleep: 'float' = 0.15) -> 'Dict[str, int]'`

Fill missing/short abstracts from OpenAlex by DOI. Returns stats.

### `redact_params(params: 'Optional[dict]') -> 'Dict[str, str]'`

Return request parameters safe to archive.

### `request_key(url: 'str', params: 'Optional[dict]' = None) -> 'str'`

Stable identifier of one HTTP request, ignoring credentials.

### `retraction_flags(records: 'Iterable[Record]') -> 'Dict[str, object]'`

Flag integrity events across a corpus and report what was found.

### `save_credentials(values: 'Dict[str, str]') -> 'str'`

Write *values* with owner-only permissions, returning the path.

### `sort_records(records: 'Iterable[Record]') -> 'List[Record]'`

Return records in a canonical, relevance-independent order.

### `sources`

Module-level module.

### `truth_groups(records: 'Iterable[Record]') -> 'Dict[str, str]'`

Map ``uid -> normalized DOI`` for records whose DOI is present.

### `tui`

Module-level module.

### `tui_main(argv: 'Optional[Sequence[str]]' = None, stdin: 'Any' = None, stdout: 'Any' = None, getpass_fn: 'Optional[Callable[..., str]]' = None, runner: 'Optional[Callable[..., int]]' = None) -> 'int'`

Start the guided interface and return a process exit code.

### `wos_doc_type(types: 'Optional[list]', source_types: 'Optional[list]' = None) -> 'str'`

Map Web of Science ``types``/``sourceTypes`` onto the CorpusSLR vocabulary.

### `write_corpus(corpus: 'Corpus', path: 'str', result: 'Optional[DedupResult]' = None) -> 'str'`

Write the corpus and its audit trail to *path* as JSON.
