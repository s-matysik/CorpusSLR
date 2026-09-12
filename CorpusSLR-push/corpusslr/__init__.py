"""CorpusSLR: from one structured query to a PRISMA-documented corpus.

API-native retrieval (Scopus, OpenAlex, PubMed, Crossref, Semantic Scholar,
arXiv, bioRxiv/medRxiv), export parsers (Web of Science tagged, universal RIS
with vendor dialects incl. Embase/Cochrane CENTRAL/EBSCOhost/ProQuest, PubMed
.nbib, BibTeX, EndNote XML, vendor CSV), a principal/supplementary source
registry after Gusenbauer & Haddaway (2020), cascading auditable
deduplication, PRISMA 2020 flow diagram and a PRISMA-S search-reporting
appendix.
"""
__version__ = "1.0.0"

from .record import is_identifier_only_title, Record, normalize_doi, normalize_title           # noqa: F401
from .corpus import Corpus, SearchEvent, SourceResult                 # noqa: F401
from .query import SearchQuery                                        # noqa: F401
from .sources.base import BaseSource, SourceError                     # noqa: F401
from .sources.scopus import ScopusSource                              # noqa: F401
from .sources.openalex import OpenAlexSource, reconstruct_abstract    # noqa: F401
from .sources.pubmed import PubMedSource, parse_pubmed_xml            # noqa: F401
from .sources.crossref import CrossrefSource                          # noqa: F401
from .sources.semanticscholar import (SemanticScholarSource,          # noqa: F401
                                      parse_s2_paper)
from .sources.arxiv import (ArxivSource, parse_arxiv_atom,            # noqa: F401
                            parse_arxiv_atom_file)
from .sources.preprints import (BiorxivSource, MedrxivSource,         # noqa: F401
                                parse_preprint)
from .sources.wos import (WosStarterSource, parse_wos_hit,            # noqa: F401
                          wos_doc_type)
from .sources.wos_expanded import (WosExpandedSource,                 # noqa: F401
                                   parse_wos_expanded_record)
from .sources.registry import (SOURCE_TIER, classify_source,          # noqa: F401
                               canonical_source, audit_strategy,
                               audit_markdown, SOURCE_EVIDENCE,
                               SOURCE_NOTES, source_evidence, source_note)
from .parsers.ris import parse_ris, parse_ris_file, detect_dialect    # noqa: F401
from .parsers.wos import parse_wos, parse_wos_file                    # noqa: F401
from .parsers.nbib import ParseFormatMismatch, parse_nbib, parse_nbib_file                 # noqa: F401
from .parsers.bibtex import (parse_bibtex, parse_bibtex_file,         # noqa: F401
                             detect_bibtex_dialect)
from .parsers.endnote import (parse_endnote_xml,                      # noqa: F401
                              parse_endnote_xml_file)
from .parsers.csv_exports import (parse_csv_export,                   # noqa: F401
                                  parse_csv_export_file,
                                  detect_csv_dialect)
from .dedup import deduplicate, DedupResult, DedupReport              # noqa: F401
from .enrich import recover_abstracts                                 # noqa: F401
from .prisma import PrismaFlow                                        # noqa: F401
from .prisma_s import prisma_s_appendix, prisma_s_markdown            # noqa: F401
from .quality import quality_report, quality_markdown, quality_csv    # noqa: F401
from .integrity import (EXCLUDING_FLAGS, NOTICE_FLAGS,  # noqa: F401
                        check_retractions_crossref, integrity_flag,
                        integrity_markdown, retraction_flags)
from .export import to_csv, to_ris, to_bibtex, to_screening_csv       # noqa: F401
from .export import to_scopus_csv, SCOPUS_COLUMNS                     # noqa: F401,E501
from .harvest import (harvest, replay_harvest, verify_archive,        # noqa: F401
                      HarvestArchive, HarvestManifest, HarvestResult,
                      HarvestDiff, HarvestError, RecordingSession,
                      ReplaySession, ArchivedResponse, compare_harvests,
                      records_checksum, record_checksum, record_key,
                      record_fingerprint, records_equal, record_diff_fields,
                      sort_records, harvest_markdown, request_key,
                      redact_params, CHECKSUM_FIELDS, VOLATILE_FIELDS,
                      ARCHIVE_VERSION)
from .validate import (hide_identifiers, truth_groups,                # noqa: F401
                       clusters_from_decisions, pair_metrics,
                       record_metrics, corpus_profile, PERTURBATIONS,
                       apply_perturbation, excel_mangle_pages)
from .cli import (main as cli_main, build_parser, load_config,             # noqa: F401,E501
                  validate_config, config_checksum, detect_export_format,
                  parse_export_file, corpus_to_dict, corpus_from_dict,
                  write_corpus, read_corpus, CliError, ConfigError,
                  DataError, DATABASES, CREDENTIAL_ENV, CORPUS_FORMAT)
from .parsers.enw import (parse_enw, parse_enw_file,                   # noqa: F401,E501
                          looks_like_enw)
from .parsers.html_table import (parse_html_table,                     # noqa: F401,E501
                                 parse_html_table_file,
                                 extract_table_rows, looks_like_html)
from .parsers.csv_exports import parse_csv_rows                        # noqa: F401,E501
from .parsers._report import ParseReport, REJECTION_REASONS            # noqa: F401,E501
from .parsers._io import (sniff_encoding, decode_export,               # noqa: F401,E501
                          read_export_text, looks_binary)
from .tui import (main as tui_main, Interface as TuiInterface,         # noqa: F401,E501
                  ReviewSettings, config_home, credentials_path,
                  credential_slots, load_credentials, save_credentials)
