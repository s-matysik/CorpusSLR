"""Command-line interface: one configuration file, one reproducible review.

Why a CLI at all, when the library is complete?  Because the two properties a
systematic review is judged on -- that a third party can *repeat* the search
(PRISMA-S, Rethlefsen et al., 2021, *Systematic Reviews* 10:39, Items 8, 9, 13)
and that the reported numbers can be *recomputed* -- are properties of an
executable artefact, not of prose.  A Python script that a reviewer must read,
adapt and rerun is a weaker guarantee than a declarative configuration plus a
single command, for three concrete reasons:

1. **The search strategy becomes data.**  Blocks of search terms, the year
   window, document types, languages, the list of databases and every
   deduplication parameter live in one JSON file that can be deposited
   alongside the manuscript, diffed between protocol and execution, and cited.
   Nothing about the strategy is expressed only as control flow.
2. **The whole review is one command.**  ``corpusslr run -c review.json``
   performs retrieval, file-export import, abstract recovery, deduplication,
   the PRISMA 2020 flow diagram, the PRISMA-S appendix and the screening
   exports, and writes a run summary recording the package version, the
   configuration checksum and every per-stage count.  Re-running it is how the
   numbers in the manuscript are verified.
3. **Non-programmers can run it.**  Most reviews are conducted by domain
   experts and information specialists, not developers.  A tool that requires
   editing Python excludes exactly the people who own the search strategy.

Design commitments that follow from being a scientific instrument:

*Credentials only from the environment.*  API keys and institutional tokens
are read from environment variables and never accepted in the configuration
file, never echoed, and never written to any output -- so a configuration file
is safe to deposit as supplementary material.  Only the *presence* of a
credential is ever reported.

*Data on stdout, progress on stderr.*  Every command writes its data product
to stdout (a JSON summary, or Markdown where that is the product) and all
progress and diagnostics to stderr, so ``corpusslr ... > result.json`` is
always valid and pipelines compose.

*Exit codes a shell script can branch on.*  ``0`` success, ``1`` user error
(bad configuration, unknown database, missing credential, missing input file),
``2`` data error (unrecognisable export, corrupt archive, failed integrity
check, API failure, arithmetically impossible PRISMA flow), ``3`` internal
error.  User-facing failures print an explanation and a remedy, never a
traceback; ``--traceback`` restores the traceback for bug reports.

*No new dependencies.*  ``argparse`` and the standard library only; YAML
configurations are read when PyYAML happens to be installed, and JSON always.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import __version__
from .corpus import Corpus, SearchEvent
from .dedup import DedupReport, DedupResult, deduplicate
from .enrich import recover_abstracts
from .export import (to_bibtex, to_csv, to_ris, to_scopus_csv,
                     to_screening_csv)
from .harvest import (HarvestArchive, HarvestError, compare_harvests, harvest,
                      harvest_markdown, verify_archive)
from .prisma import PrismaFlow
from .prisma_s import prisma_s_appendix
from .quality import quality_csv, quality_markdown, quality_report
from .query import SearchQuery
from .record import Record
from .sources.base import SourceError
from .sources.registry import audit_markdown, canonical_source

__all__ = [
    "main", "build_parser", "load_config", "validate_config",
    "config_checksum",
    "CliError", "ConfigError", "DataError", "detect_export_format",
    "parse_export_file", "corpus_to_dict", "corpus_from_dict", "write_corpus",
    "read_corpus", "DATABASES", "CREDENTIAL_ENV", "CORPUS_FORMAT",
    "EXIT_OK", "EXIT_USAGE", "EXIT_DATA", "EXIT_INTERNAL",
]

#: Success.
EXIT_OK = 0
#: The user asked for something impossible: malformed configuration, unknown
#: database, absent credential, missing input path, contradictory options.
EXIT_USAGE = 1
#: The inputs were understood but the data failed: an export whose format
#: cannot be identified, an archive that fails its integrity audit, a replay
#: whose checksum diverges, an API error, a PRISMA flow that does not balance.
EXIT_DATA = 2
#: A defect in CorpusSLR itself; rerun with ``--traceback`` and report it.
EXIT_INTERNAL = 3

#: Version tag written into every corpus JSON file.  A reader that finds an
#: unknown major format refuses to guess rather than silently mis-parsing an
#: audit trail.
CORPUS_FORMAT = "corpusslr/corpus-1"


class CliError(Exception):
    """A failure that must be reported as a message, not a traceback."""

    exit_code = EXIT_USAGE


class ConfigError(CliError):
    """The configuration file is unusable; the message names the fix."""

    exit_code = EXIT_USAGE


class DataError(CliError):
    """Inputs were understood but the data or a remote service failed."""

    exit_code = EXIT_DATA


# ---------------------------------------------------------------------------
# database registry
# ---------------------------------------------------------------------------
#: Databases the CLI can query through an API, keyed by the alias used in the
#: configuration file.  ``label`` is the canonical database name that reaches
#: the PRISMA-S appendix, ``tier`` is the Gusenbauer & Haddaway (2020)
#: classification carried by :mod:`corpusslr.sources.registry`, and
#: ``keyless`` marks the sources a reviewer without any institutional
#: subscription can rerun -- which is what makes a replay of the search
#: independently verifiable.
DATABASES: Dict[str, Dict[str, Any]] = {
    "scopus": {"label": "Scopus", "keyless": False},
    "wos": {"label": "Web of Science Core Collection", "keyless": False},
    "pubmed": {"label": "PubMed/MEDLINE", "keyless": True},
    "openalex": {"label": "OpenAlex", "keyless": True},
    "crossref": {"label": "Crossref", "keyless": True},
    "semanticscholar": {"label": "Semantic Scholar", "keyless": True},
    "arxiv": {"label": "arXiv", "keyless": True},
    "biorxiv": {"label": "bioRxiv", "keyless": True},
    "medrxiv": {"label": "medRxiv", "keyless": True},
}

#: Spelling variants accepted for ``databases`` entries.  Reviewers write the
#: database name the way their institution does; rejecting "Web of Science"
#: because the alias is ``wos`` would be pedantry, not validation.
_DB_ALIASES = {
    "elsevierscopus": "scopus",
    "webofscience": "wos", "webofsciencecorecollection": "wos",
    "woscc": "wos", "clarivate": "wos", "wosstarter": "wos",
    "medline": "pubmed", "pubmedmedline": "pubmed", "ncbi": "pubmed",
    "entrez": "pubmed",
    "openalexapi": "openalex", "ourresearch": "openalex",
    "crossrefrest": "crossref",
    "semanticscholarapi": "semanticscholar", "s2": "semanticscholar",
    "s2ag": "semanticscholar", "allenai": "semanticscholar",
    "arxivorg": "arxiv",
    "biorxivorg": "biorxiv", "medrxivorg": "medrxiv",
}

#: Environment variables consulted per database: ``required`` (any one of the
#: alternatives must be set) and ``optional`` (raises the rate limit or
#: unlocks off-campus access).  The values are never read into any artefact --
#: :func:`credential_status` reports presence only.
CREDENTIAL_ENV: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "scopus": {"required": ("SCOPUS_API_KEY", "ELSEVIER_API_KEY"),
               "optional": ("SCOPUS_INSTTOKEN", "ELSEVIER_INSTTOKEN")},
    "wos": {"required": ("WOS_API_KEY", "CLARIVATE_API_KEY"),
            "optional": ()},
    "semanticscholar": {"required": (),
                        "optional": ("SEMANTIC_SCHOLAR_API_KEY",
                                     "S2_API_KEY")},
    "pubmed": {"required": (), "optional": ("NCBI_API_KEY", "PUBMED_API_KEY")},
    "openalex": {"required": (), "optional": ()},
    "crossref": {"required": (), "optional": ()},
    "arxiv": {"required": (), "optional": ()},
    "biorxiv": {"required": (), "optional": ()},
    "medrxiv": {"required": (), "optional": ()},
}

#: Environment variables searched, in order, for the politeness contact
#: address that Crossref, OpenAlex and NCBI ask for.  Deliberately *not*
#: configurable inline: a configuration file is meant to be deposited as
#: supplementary material, and a personal address should not travel with it.
CONTACT_ENV = ("CORPUSSLR_CONTACT_EMAIL", "CONTACT_EMAIL")

#: Recognised configuration sections.  An unknown key is an error rather than
#: a silent no-op: a typo in ``dedup`` would otherwise leave the reviewer
#: believing a threshold was applied when the default was used instead.
_CONFIG_KEYS = ("review", "query", "databases", "files", "dedup", "enrich",
                "screening", "output", "harvest", "max_results")
_QUERY_KEYS = ("blocks", "years", "doc_types", "languages", "title_only")
_DEDUP_KEYS = ("fuzzy_threshold", "year_tolerance", "block_prefix",
               "max_block", "id_title_min", "separate_by_locus",
               "blocking_rounds", "round_title_min", "allow_copublication",
               "separate_conference")
_OUTPUT_KEYS = ("dir", "prefix", "exports", "appendix", "svg", "quality_csv")
#: Export formats, canonical one first.  ``scopus`` writes the Scopus CSV
#: export layout, which is what ``bibliometrix::convert2df(dbsource =
#: "scopus")``, VOSviewer and EmbedSLR read, so it is the default hand-off
#: after deduplication; the others remain available by name.
_EXPORT_FORMATS = ("scopus", "csv", "screening", "ris", "bibtex")
_FILE_KEYS = ("path", "database", "platform", "interface", "query", "filters",
              "date_run", "notes", "format", "dialect", "encoding")
_SCREENING_KEYS = ("records_excluded", "reports_not_retrieved",
                   "fulltext_exclusions", "studies_included",
                   "reports_included", "automation_excluded", "other_excluded")


def _norm_db(name: str) -> str:
    """Resolve a user-written database name to a :data:`DATABASES` alias."""
    key = re.sub(r"[^a-z0-9]", "", str(name).lower())
    key = _DB_ALIASES.get(key, key)
    return key if key in DATABASES else ""


def _available_databases() -> str:
    return ", ".join(sorted(DATABASES))


# ---------------------------------------------------------------------------
# console
# ---------------------------------------------------------------------------
class _Console:
    """Progress to stderr, data to stdout -- never the other way round."""

    def __init__(self, quiet: bool = False, verbose: bool = False,
                 stream=None, out=None) -> None:
        self.quiet = quiet
        self.verbose = verbose
        self.stream = stream if stream is not None else sys.stderr
        self.out = out if out is not None else sys.stdout

    def info(self, message: str) -> None:
        if not self.quiet:
            self.stream.write(message + "\n")
            self.stream.flush()

    def detail(self, message: str) -> None:
        if self.verbose and not self.quiet:
            self.stream.write("  " + message + "\n")

    def warn(self, message: str) -> None:
        """Warnings survive ``--quiet``.

        ``-q`` silences progress, not diagnostics: a skipped database or a
        deduplication bucket that overflowed changes what the numbers mean, so
        suppressing it would let a quiet batch run look clean while reporting a
        degraded corpus.
        """
        self.stream.write("warning: " + message + "\n")

    def data(self, text: str) -> None:
        self.out.write(text + ("" if text.endswith("\n") else "\n"))
        self.out.flush()

    def json(self, payload: Dict[str, Any]) -> None:
        self.data(json.dumps(payload, ensure_ascii=False, indent=1,
                             sort_keys=True))


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------
def load_config(path: str) -> Dict[str, Any]:
    """Read and validate a review configuration from JSON (or YAML).

    JSON is the contract because it needs no dependency and because a review
    protocol deposited as supplementary material should be readable by any
    tool.  YAML is accepted when PyYAML is already installed, purely as a
    convenience for hand-editing; the semantics are identical.
    """
    if not os.path.isfile(path):
        raise ConfigError(
            "configuration file {!r} does not exist. Write one (see "
            "examples/review_config.json in the CorpusSLR repository) or pass "
            "--config with the right path.".format(path))
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            text = fh.read()
    except OSError as exc:
        raise ConfigError("cannot read {!r}: {}".format(path, exc))

    if path.lower().endswith((".yaml", ".yml")):
        try:
            import yaml            # optional; never a declared dependency
        except ImportError:
            raise ConfigError(
                "{!r} looks like YAML but PyYAML is not installed. CorpusSLR "
                "depends on the standard library only, so either install "
                "PyYAML (pip install pyyaml) or convert the file to JSON."
                .format(path))
        try:
            data = yaml.safe_load(text)
        except Exception as exc:                       # noqa: BLE001
            raise ConfigError("{} is not valid YAML: {}".format(path, exc))
    else:
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise ConfigError(
                "{} is not valid JSON: {}. Common causes: a trailing comma, "
                "single quotes instead of double quotes, or a comment "
                "(JSON has none).".format(path, exc))
    cfg = validate_config(data, origin=path)
    cfg["_path"] = os.path.abspath(path)
    cfg["_checksum"] = config_checksum(data)
    return cfg


def config_checksum(config: Dict[str, Any]) -> str:
    """SHA-256 over the canonicalised configuration.

    Written into every run summary so that a reported corpus can be tied to
    the exact strategy that produced it: an edited search that was never
    re-run is then visible as a checksum mismatch rather than invisible.
    """
    payload = {k: v for k, v in (config or {}).items()
               if not str(k).startswith("_")}
    canon = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _require_type(value: Any, kinds, label: str, hint: str = "") -> Any:
    if not isinstance(value, kinds):
        names = {list: "a list", dict: "an object", str: "a string",
                 bool: "true/false", int: "an integer",
                 float: "a number"}
        want = names.get(kinds if not isinstance(kinds, tuple) else kinds[0],
                         "a different type")
        raise ConfigError("{} must be {}, got {}{}".format(
            label, want, type(value).__name__,
            ". " + hint if hint else ""))
    return value


def _unknown_keys(section: Dict[str, Any], allowed: Sequence[str],
                  label: str) -> None:
    unknown = [k for k in section if k not in allowed]
    if unknown:
        raise ConfigError(
            "unknown key(s) {} in {}. Allowed keys: {}. (An unrecognised key "
            "would be silently ignored, so it is rejected instead -- a typo "
            "in a threshold must not look like a working setting.)".format(
                ", ".join(repr(k) for k in sorted(unknown)), label,
                ", ".join(allowed)))


def validate_config(data: Any, origin: str = "config") -> Dict[str, Any]:
    """Check a configuration object and return it normalised.

    Validation is deliberately strict and verbose.  A systematic review is
    executed once and reported for years; a threshold silently defaulted
    because of a misspelled key, or a database counted twice because it was
    listed under two names, corrupts numbers that reviewers will treat as
    facts.  Every rejection therefore names both what is wrong and what to
    write instead.
    """
    cfg = _require_type(data, dict, "{}: the configuration".format(origin),
                        "The top level is an object with sections such as "
                        '"query", "databases", "output".')
    # Checked first, and before the generic unknown-key rejection, so that a
    # credential sitting in the file gets the explanation it needs rather than
    # a bare "unknown key".
    review_section = cfg.get("review")
    for banned in ("api_key", "apikey", "key", "insttoken", "token",
                   "password", "email", "contact_email", "mailto"):
        if banned in cfg or (isinstance(review_section, dict)
                             and banned in review_section):
            raise ConfigError(
                "the configuration contains {!r}. Credentials and contact "
                "addresses are read from environment variables only ({}), so "
                "that a configuration file can be deposited as supplementary "
                "material without leaking them. Remove the key and export the "
                "variable instead.".format(banned, ", ".join(CONTACT_ENV)))
    _unknown_keys(cfg, _CONFIG_KEYS + ("_path", "_checksum"), origin)

    # -- query -------------------------------------------------------------
    if "query" not in cfg:
        raise ConfigError(
            '{}: no "query" section. It is the search strategy and cannot be '
            'defaulted, e.g.: "query": {{"blocks": [["artificial '
            'intelligence", "machine learning"], ["adoption"]], "years": '
            "[2015, 2026]}}".format(origin))
    q = _require_type(cfg["query"], dict, '"query"')
    _unknown_keys(q, _QUERY_KEYS, '"query"')
    blocks = _require_type(q.get("blocks", []), list, '"query.blocks"')
    if not blocks:
        raise ConfigError(
            '"query.blocks" is empty. Each block is a list of synonyms '
            "combined with OR; the blocks are combined with AND. At least one "
            "block is required.")
    norm_blocks: List[List[str]] = []
    for i, block in enumerate(blocks):
        block = _require_type(block, list, '"query.blocks"[{}]'.format(i))
        terms = [str(t).strip() for t in block if str(t).strip()]
        if not terms:
            raise ConfigError(
                '"query.blocks"[{}] contains no non-empty term. Remove the '
                "block or fill it in -- an empty block would widen the query "
                "to everything.".format(i))
        for t in terms:
            if len(t) < 2:
                raise ConfigError(
                    '"query.blocks"[{}] contains the term {!r}, which is too '
                    "short to be a search term.".format(i, t))
        norm_blocks.append(terms)
    q["blocks"] = norm_blocks

    if q.get("years") is not None:
        years = q["years"]
        if isinstance(years, (list, tuple)) and len(years) == 2:
            try:
                y1, y2 = int(years[0]), int(years[1])
            except (TypeError, ValueError):
                raise ConfigError(
                    '"query.years" must be two integers [from, to], got {!r}.'
                    .format(years))
            if y1 > y2:
                raise ConfigError(
                    '"query.years" is [{}, {}]: the first year must not be '
                    "later than the second. Write [{}, {}] if that is what "
                    "you meant.".format(y1, y2, y2, y1))
            if y1 < 1500 or y2 > 2100:
                raise ConfigError(
                    '"query.years" is [{}, {}], outside the plausible range '
                    "1500-2100.".format(y1, y2))
            q["years"] = [y1, y2]
        else:
            raise ConfigError(
                '"query.years" must be a two-element list [from, to], e.g. '
                "[2015, 2026]; got {!r}.".format(years))
    for name in ("doc_types", "languages"):
        if name in q:
            vals = _require_type(q[name], list, '"query.{}"'.format(name))
            q[name] = [str(v).strip() for v in vals if str(v).strip()]
    if "title_only" in q:
        _require_type(q["title_only"], bool, '"query.title_only"')

    # -- databases ---------------------------------------------------------
    dbs = _require_type(cfg.get("databases", []) or [], list, '"databases"')
    norm_dbs: List[Dict[str, Any]] = []
    seen: Dict[str, int] = {}
    for i, entry in enumerate(dbs):
        if isinstance(entry, str):
            entry = {"name": entry}
        entry = _require_type(entry, dict, '"databases"[{}]'.format(i),
                              'Write either "openalex" or {"name": '
                              '"openalex", "max_results": 2000}.')
        _unknown_keys(entry, ("name", "max_results", "view", "db",
                              "sort_field", "harvest_id", "notes"),
                      '"databases"[{}]'.format(i))
        alias = _norm_db(entry.get("name", ""))
        if not alias:
            raise ConfigError(
                'unknown database {!r} in "databases"[{}]. Available: {}. '
                "Databases without an open API (Embase, Cochrane CENTRAL, "
                "EBSCOhost, ProQuest, IEEE Xplore, ACM) are imported as file "
                'exports through the "files" section instead.'.format(
                    entry.get("name", ""), i, _available_databases()))
        if alias in seen:
            raise ConfigError(
                "database {!r} is listed twice (entries {} and {}). Querying "
                "one database twice would double-count it in the PRISMA "
                '"records identified" total; merge the entries or give one of '
                "them a different name.".format(alias, seen[alias], i))
        seen[alias] = i
        if "max_results" in entry:
            mr = entry["max_results"]
            if not isinstance(mr, int) or isinstance(mr, bool) or mr <= 0:
                raise ConfigError(
                    '"databases"[{}].max_results must be a positive integer, '
                    "got {!r}.".format(i, mr))
        if alias == "scopus" and "view" in entry:
            view = str(entry["view"]).upper()
            if view not in ("STANDARD", "COMPLETE"):
                raise ConfigError(
                    "Scopus view must be 'STANDARD' or 'COMPLETE', got {!r}. "
                    "COMPLETE returns abstracts but requires the matching "
                    "institutional entitlement.".format(entry["view"]))
            entry["view"] = view
        entry["name"] = alias
        norm_dbs.append(entry)
    cfg["databases"] = norm_dbs

    # -- file exports ------------------------------------------------------
    files = _require_type(cfg.get("files", []) or [], list, '"files"')
    norm_files: List[Dict[str, Any]] = []
    for i, entry in enumerate(files):
        if isinstance(entry, str):
            entry = {"path": entry}
        entry = _require_type(entry, dict, '"files"[{}]'.format(i))
        _unknown_keys(entry, _FILE_KEYS, '"files"[{}]'.format(i))
        if not str(entry.get("path", "")).strip():
            raise ConfigError('"files"[{}] has no "path".'.format(i))
        norm_files.append(entry)
    cfg["files"] = norm_files

    if not norm_dbs and not norm_files:
        raise ConfigError(
            'nothing to retrieve: both "databases" and "files" are empty. Add '
            "at least one API database (available: {}) or one exported file."
            .format(_available_databases()))

    # -- deduplication -----------------------------------------------------
    dd = _require_type(cfg.get("dedup", {}) or {}, dict, '"dedup"')
    _unknown_keys(dd, _DEDUP_KEYS, '"dedup"')
    for name in ("fuzzy_threshold", "round_title_min", "id_title_min"):
        if name in dd:
            try:
                val = float(dd[name])
            except (TypeError, ValueError):
                raise ConfigError(
                    '"dedup.{}" must be a number between 0 and 1, got {!r}.'
                    .format(name, dd[name]))
            if not 0.0 < val <= 1.0:
                raise ConfigError(
                    '"dedup.{}" is {}; it is a similarity ratio and must lie '
                    "in (0, 1]. The validated default is {}.".format(
                        name, val,
                        {"fuzzy_threshold": 0.93, "round_title_min": 0.7,
                         "id_title_min": 0.5}[name]))
            dd[name] = val
    if "fuzzy_threshold" in dd and "id_title_min" in dd \
            and dd["id_title_min"] > dd["fuzzy_threshold"]:
        raise ConfigError(
            '"dedup.id_title_min" ({}) exceeds "dedup.fuzzy_threshold" ({}). '
            "id_title_min is the *weaker* title check that guards an "
            "identifier match, so setting it above the fuzzy threshold makes "
            "identifier matching stricter than title matching, which inverts "
            "the cascade.".format(dd["id_title_min"], dd["fuzzy_threshold"]))
    for name in ("year_tolerance", "block_prefix", "max_block"):
        if name in dd:
            val = dd[name]
            if not isinstance(val, int) or isinstance(val, bool) or val < 0:
                raise ConfigError(
                    '"dedup.{}" must be a non-negative integer, got {!r}.'
                    .format(name, val))
            if name in ("block_prefix", "max_block") and val == 0:
                raise ConfigError(
                    '"dedup.{}" must be greater than 0.'.format(name))
    for name in ("separate_by_locus", "blocking_rounds", "allow_copublication",
                 "separate_conference"):
        if name in dd:
            _require_type(dd[name], bool, '"dedup.{}"'.format(name))
    cfg["dedup"] = dd

    # -- enrichment --------------------------------------------------------
    en = _require_type(cfg.get("enrich", {}) or {}, dict, '"enrich"')
    _unknown_keys(en, ("recover_abstracts", "min_len"), '"enrich"')
    if "recover_abstracts" in en:
        _require_type(en["recover_abstracts"], bool,
                      '"enrich.recover_abstracts"')
    cfg["enrich"] = en

    # -- screening counts --------------------------------------------------
    sc = _require_type(cfg.get("screening", {}) or {}, dict, '"screening"')
    _unknown_keys(sc, _SCREENING_KEYS, '"screening"')
    for name in ("records_excluded", "reports_not_retrieved",
                 "studies_included", "reports_included",
                 "automation_excluded", "other_excluded"):
        if name in sc and sc[name] is not None:
            val = sc[name]
            if not isinstance(val, int) or isinstance(val, bool) or val < 0:
                raise ConfigError(
                    '"screening.{}" must be a non-negative integer, got {!r}.'
                    .format(name, val))
    if "fulltext_exclusions" in sc:
        fx = _require_type(sc["fulltext_exclusions"], dict,
                           '"screening.fulltext_exclusions"',
                           'Write {"wrong population": 41, "not empirical": '
                           "17}.")
        for reason, n in fx.items():
            if not isinstance(n, int) or isinstance(n, bool) or n < 0:
                raise ConfigError(
                    '"screening.fulltext_exclusions"[{!r}] must be a '
                    "non-negative integer, got {!r}.".format(reason, n))
    cfg["screening"] = sc

    # -- output ------------------------------------------------------------
    out = _require_type(cfg.get("output", {}) or {}, dict, '"output"')
    _unknown_keys(out, _OUTPUT_KEYS, '"output"')
    exports = out.get("exports")
    if exports is not None:
        exports = _require_type(exports, list, '"output.exports"')
        bad = [e for e in exports if str(e).lower() not in _EXPORT_FORMATS]
        if bad:
            raise ConfigError(
                'unknown export format(s) {} in "output.exports". Available: '
                "{}.".format(", ".join(repr(b) for b in bad),
                             ", ".join(_EXPORT_FORMATS)))
        out["exports"] = [str(e).lower() for e in exports]
    if "appendix" in out:
        ap = str(out["appendix"]).lower()
        if ap not in ("md", "docx"):
            raise ConfigError(
                '"output.appendix" must be "md" or "docx", got {!r}. The '
                ".docx writer needs the optional python-docx extra "
                "(pip install corpusslr[docx]).".format(out["appendix"]))
        out["appendix"] = ap
    if "svg" in out:
        _require_type(out["svg"], bool, '"output.svg"')
    cfg["output"] = out

    # -- harvest -----------------------------------------------------------
    hv = _require_type(cfg.get("harvest", {}) or {}, dict, '"harvest"')
    _unknown_keys(hv, ("archive", "notes"), '"harvest"')
    cfg["harvest"] = hv

    if "max_results" in cfg:
        mr = cfg["max_results"]
        if not isinstance(mr, int) or isinstance(mr, bool) or mr <= 0:
            raise ConfigError(
                '"max_results" must be a positive integer, got {!r}.'
                .format(mr))

    rv = _require_type(cfg.get("review", {}) or {}, dict, '"review"')
    _unknown_keys(rv, ("title", "protocol", "registration", "notes",
                       "authors"), '"review"')
    cfg["review"] = rv
    return cfg


def build_query(cfg: Dict[str, Any]) -> SearchQuery:
    """Build the :class:`~corpusslr.query.SearchQuery` described by *cfg*."""
    q = cfg["query"]
    years = q.get("years")
    return SearchQuery(
        blocks=[list(b) for b in q["blocks"]],
        years=(int(years[0]), int(years[1])) if years else None,
        doc_types=list(q.get("doc_types") or []),
        languages=list(q.get("languages") or []),
        title_only=bool(q.get("title_only", False)),
    )


# ---------------------------------------------------------------------------
# credentials
# ---------------------------------------------------------------------------
def _env_first(names: Sequence[str]) -> Tuple[str, str]:
    for name in names:
        value = (os.environ.get(name) or "").strip()
        if value:
            return name, value
    return "", ""


def credential_status(alias: str) -> Dict[str, Any]:
    """Report which credentials for *alias* are set -- presence only.

    The values are never returned, logged or written to an artefact: a run
    summary that is meant to be deposited must be able to state that a
    subscription key was used without disclosing it.
    """
    spec = CREDENTIAL_ENV.get(alias, {"required": (), "optional": ()})
    req_name, req_val = _env_first(spec["required"])
    opt_name, opt_val = _env_first(spec["optional"])
    return {
        "database": DATABASES[alias]["label"],
        "requires_credential": bool(spec["required"]),
        "credential_present": bool(req_val),
        "credential_variable": req_name or (spec["required"][0]
                                            if spec["required"] else ""),
        "optional_present": bool(opt_val),
        "optional_variable": opt_name or (spec["optional"][0]
                                          if spec["optional"] else ""),
        "keyless": bool(DATABASES[alias]["keyless"]),
    }


def _missing_credential_message(alias: str) -> str:
    spec = CREDENTIAL_ENV.get(alias, {"required": (), "optional": ()})
    label = DATABASES[alias]["label"]
    variants = " or ".join(spec["required"])
    extra = ""
    if alias == "scopus":
        extra = (" An Elsevier key is bound to the subscribing institution's "
                 "IP range; from outside it also needs SCOPUS_INSTTOKEN. Ask "
                 "your library for both.")
    elif alias == "wos":
        extra = (" A Web of Science Starter API key is issued through the "
                 "Clarivate developer portal by your institution.")
    return ("{} requires an API key, and none of the environment variables {} "
            "is set. Export it before running (never put it in the "
            "configuration file):\n    export {}=...\n{}"
            "Or drop {!r} from \"databases\", or pass --keep-going to skip "
            "unavailable sources and record the gap in the run summary."
            .format(label, variants, spec["required"][0],
                    extra.strip() + "\n" if extra else "", alias))


def _contact_email(console: Optional[_Console] = None) -> str:
    name, value = _env_first(CONTACT_ENV)
    if not value and console is not None:
        console.warn(
            "no contact address in {}; Crossref, OpenAlex and NCBI ask for "
            "one and throttle anonymous clients harder. Export "
            "CORPUSSLR_CONTACT_EMAIL to identify yourself politely."
            .format(" or ".join(CONTACT_ENV)))
    del name
    return value


def build_source(alias: str, spec: Optional[Dict[str, Any]] = None,
                 session: Any = None, email: str = "",
                 require_credentials: bool = True):
    """Instantiate the source client for *alias*, credentials from the env.

    *session* injects a preconfigured ``requests``-style session -- the seam
    every :class:`~corpusslr.sources.base.BaseSource` already supports.  It is
    what an institutional proxy, a custom retry policy or an offline archive
    replay is threaded through, and what lets the CLI be exercised with no
    network at all.
    """
    spec = dict(spec or {})
    if alias not in DATABASES:
        raise ConfigError("unknown database {!r}; available: {}".format(
            alias, _available_databases()))
    cred = CREDENTIAL_ENV.get(alias, {"required": (), "optional": ()})
    _, key = _env_first(cred["required"])
    _, opt = _env_first(cred["optional"])
    if cred["required"] and not key and require_credentials:
        raise ConfigError(_missing_credential_message(alias))
    kw: Dict[str, Any] = {}
    if session is not None:
        kw["session"] = session

    if alias == "scopus":
        from .sources.scopus import ScopusSource
        return ScopusSource(api_key=key, insttoken=opt,
                            view=str(spec.get("view", "STANDARD")).upper(),
                            mailto=email, **kw)
    if alias == "wos":
        from .sources.wos import WosStarterSource
        return WosStarterSource(api_key=key, db=str(spec.get("db", "WOS")),
                                sort_field=str(spec.get("sort_field", "")),
                                mailto=email, **kw)
    if alias == "pubmed":
        from .sources.pubmed import PubMedSource
        return PubMedSource(email=email, api_key=opt, **kw)
    if alias == "openalex":
        from .sources.openalex import OpenAlexSource
        return OpenAlexSource(mailto=email, **kw)
    if alias == "crossref":
        from .sources.crossref import CrossrefSource
        return CrossrefSource(mailto=email, **kw)
    if alias == "semanticscholar":
        from .sources.semanticscholar import SemanticScholarSource
        return SemanticScholarSource(api_key=opt, mailto=email, **kw)
    if alias == "arxiv":
        from .sources.arxiv import ArxivSource
        return ArxivSource(mailto=email, **kw)
    if alias == "biorxiv":
        from .sources.preprints import BiorxivSource
        return BiorxivSource(mailto=email, **kw)
    from .sources.preprints import MedrxivSource
    return MedrxivSource(mailto=email, **kw)


def compile_for(alias: str, query: SearchQuery) -> Dict[str, str]:
    """Return the query as *alias* will actually receive it.

    This is the payload of ``--dry-run`` and the substance of PRISMA-S Item 8
    ("full search strategies as run"): the reviewer sees the native syntax of
    every backend, including the filters that a given API cannot express,
    before a single request is sent.
    """
    if alias == "scopus":
        return {"query": query.to_scopus(), "filters": "in-query limits"}
    if alias == "wos":
        return {"query": query.to_wos(), "filters": "in-query limits"}
    if alias == "openalex":
        filters = query.to_openalex_filters()
        return {"query": query.to_openalex(),
                "filters": "; ".join("{}={}".format(k, v)
                                     for k, v in sorted(filters.items())
                                     if k != "title_and_abstract.search")}
    if alias == "pubmed":
        return {"query": query.to_pubmed(), "filters": "in-query limits"}
    if alias == "crossref":
        params = dict(query.to_crossref_params())
        return {"query": str(params.get("query.bibliographic", "")),
                "filters": str(params.get("filter", ""))}
    if alias == "semanticscholar":
        params = query.to_semanticscholar()
        return {"query": str(params.get("query", "")),
                "filters": "; ".join(
                    "{}={}".format(k, params[k])
                    for k in ("year", "publicationTypes") if k in params)}
    if alias == "arxiv":
        return {"query": query.to_arxiv(), "filters": "in-query limits"}
    from .sources.preprints import render_local_filter
    return {"query": render_local_filter(query),
            "filters": "server API returns a date window; the query is "
                       "applied locally to every record"}


# ---------------------------------------------------------------------------
# corpus serialization
# ---------------------------------------------------------------------------
def corpus_to_dict(corpus: Corpus,
                   result: Optional[DedupResult] = None) -> Dict[str, Any]:
    """Serialise a corpus with its full retrieval provenance.

    The subcommands are separate steps of one review, so what passes between
    them has to carry more than records: the per-database search events (which
    database, which platform, which interface, which query, which date, how
    many records) are what the PRISMA 2020 flow diagram and the PRISMA-S
    appendix are built from, and they cannot be recovered from a record list.
    Record ``uid``s are preserved verbatim so that the deduplication decision
    log stays joinable to the exports after a round trip.
    """
    payload: Dict[str, Any] = {
        "format": CORPUS_FORMAT,
        "corpusslr_version": __version__,
        "created_at": _dt.datetime.now(_dt.timezone.utc)
                         .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "searches": [
            {"search_id": ev.search_id, "database": ev.database,
             "platform": ev.platform, "interface": ev.interface,
             "query": ev.query, "filters": ev.filters,
             "date_run": ev.date_run,
             "records_retrieved": ev.records_retrieved,
             "url": ev.url, "notes": ev.notes}
            for ev in corpus.searches],
        "records": [],
    }
    for rec in corpus.records:
        d = rec.to_dict()
        if rec.raw:
            d["raw"] = rec.raw
        payload["records"].append(d)
    if result is not None:
        rep = result.report
        payload["dedup"] = {
            "before": rep.before, "after": rep.after, "removed": rep.removed,
            "by_method": dict(rep.by_method),
            "by_locus": dict(rep.by_locus),
            "overlap": [[a, b, n]
                        for (a, b), n in sorted(rep.overlap.items())],
            "id_links_rejected": rep.id_links_rejected,
            "oversized_blocks_skipped": rep.oversized_blocks_skipped,
            "records_without_candidates": rep.records_without_candidates,
            "copublication_merges": rep.copublication_merges,
            "warnings": rep.warnings(),
            "n_decisions": len(rep.decisions),
        }
    return payload


def corpus_from_dict(payload: Dict[str, Any],
                     origin: str = "corpus") -> Tuple[Corpus,
                                                      Optional[DedupResult]]:
    """Rebuild a corpus and any recorded dedup from :func:`corpus_to_dict`.

    Records are restored with their original ``uid`` and ``search_id`` instead
    of being re-registered, because re-registering would renumber them and
    break every identifier already written into a decision log, a screening
    export or a manuscript table.
    """
    if not isinstance(payload, dict):
        raise DataError("{}: expected a JSON object, got {}".format(
            origin, type(payload).__name__))
    fmt = str(payload.get("format") or "")
    if fmt and not fmt.startswith("corpusslr/corpus-"):
        raise DataError(
            "{}: {!r} is not a CorpusSLR corpus file (format={!r})".format(
                origin, origin, fmt))
    if fmt and fmt != CORPUS_FORMAT:
        raise DataError(
            "{}: corpus format {!r} is not understood by CorpusSLR {} (this "
            "build reads {!r}); upgrade the package.".format(
                origin, fmt, __version__, CORPUS_FORMAT))
    corpus = Corpus()
    for d in payload.get("searches") or []:
        ev = SearchEvent(database=str(d.get("database") or ""),
                         platform=str(d.get("platform") or ""),
                         interface=str(d.get("interface") or "API"),
                         query=str(d.get("query") or ""),
                         filters=str(d.get("filters") or ""),
                         date_run=str(d.get("date_run") or ""),
                         url=str(d.get("url") or ""),
                         notes=str(d.get("notes") or ""))
        ev.search_id = str(d.get("search_id") or
                           "S{}".format(len(corpus.searches) + 1))
        ev.records_retrieved = int(d.get("records_retrieved") or 0)
        corpus.searches.append(ev)

    fields = set(Record.__dataclass_fields__)                  # noqa: SLF001
    max_uid = 0
    for i, d in enumerate(payload.get("records") or []):
        if not isinstance(d, dict):
            raise DataError(
                "{}: records[{}] is {}, expected an object".format(
                    origin, i, type(d).__name__))
        kw = {k: v for k, v in d.items() if k in fields}
        try:
            rec = Record(**kw)
        except TypeError as exc:
            raise DataError("{}: records[{}] cannot be read: {}".format(
                origin, i, exc))
        corpus.records.append(rec)
        m = re.match(r"^R(\d+)$", rec.uid or "")
        if m:
            max_uid = max(max_uid, int(m.group(1)))
    corpus._uid = max_uid                                      # noqa: SLF001

    result = None
    dd = payload.get("dedup")
    if isinstance(dd, dict):
        rep = DedupReport(before=int(dd.get("before") or 0),
                          after=int(dd.get("after") or len(corpus.records)))
        rep.by_method = {str(k): int(v)
                         for k, v in (dd.get("by_method") or {}).items()}
        rep.by_locus = {str(k): int(v)
                        for k, v in (dd.get("by_locus") or {}).items()}
        for row in dd.get("overlap") or []:
            if isinstance(row, (list, tuple)) and len(row) == 3:
                rep.overlap[(str(row[0]), str(row[1]))] = int(row[2])
        rep.id_links_rejected = int(dd.get("id_links_rejected") or 0)
        rep.oversized_blocks_skipped = int(
            dd.get("oversized_blocks_skipped") or 0)
        rep.records_without_candidates = int(
            dd.get("records_without_candidates") or 0)
        rep.copublication_merges = int(dd.get("copublication_merges") or 0)
        result = DedupResult(records=list(corpus.records), report=rep)
    return corpus, result


def write_corpus(corpus: Corpus, path: str,
                 result: Optional[DedupResult] = None) -> str:
    """Write the corpus and its audit trail to *path* as JSON."""
    payload = corpus_to_dict(corpus, result)
    _ensure_parent(path)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1, sort_keys=True)
    return path


def read_corpus(path: str) -> Tuple[Corpus, Optional[DedupResult]]:
    """Read a corpus JSON written by :func:`write_corpus`."""
    if not os.path.isfile(path):
        raise ConfigError(
            "corpus file {!r} does not exist. Produce one first with "
            "'corpusslr search' or 'corpusslr parse'.".format(path))
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            payload = json.load(fh)
    except ValueError as exc:
        raise DataError("{} is not valid JSON: {}".format(path, exc))
    except OSError as exc:
        raise DataError("cannot read {}: {}".format(path, exc))
    return corpus_from_dict(payload, origin=path)


def _ensure_parent(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)


# ---------------------------------------------------------------------------
# export-format detection
# ---------------------------------------------------------------------------
#: Formats :func:`detect_export_format` can name, in probe order.
_FORMAT_LABELS = ("nbib", "ris", "wos", "bibtex", "endnote", "arxiv-atom",
                  "csv")


def detect_export_format(text: str) -> str:
    """Identify a database export from its content, not its file name.

    Extensions are unreliable in exactly the situations that matter: Embase
    and Cochrane CENTRAL both deliver ``.txt``, EBSCOhost writes RIS as
    ``.ris`` and as ``.txt``, Web of Science tagged exports arrive as ``.txt``
    or ``.ciw``, EndNote XML is often saved as ``.txt`` by a browser, and a
    reviewer who renames a file to keep track of it must not thereby change
    how it is parsed.  Detection therefore keys on structural markers:

    ``nbib``
        A ``PMID- `` tag, which no other tagged format uses.
    ``ris``
        The mandatory ``TY  - `` opening tag with an ``ER  -`` terminator.
    ``wos``
        Clarivate's ``FN``/``VR`` header, or two-letter tags with no ``-``
        separator plus an ``ER`` terminator.
    ``bibtex``
        An ``@entrytype{`` head.
    ``endnote``
        XML with a ``<records>``/``<record>`` body (EndNote, and the Zotero,
        Mendeley, Rayyan and Covidence exports that reuse the schema).
    ``arxiv-atom``
        An Atom ``<feed>`` carrying the arXiv namespace.
    ``csv``
        A delimited header row with at least two recognisable columns.

    Returns ``""`` when nothing matches, so the caller can fail with a
    message rather than mis-parse the file.
    """
    if not text:
        return ""
    head = text.replace("\ufeff", "").lstrip()[:20000]
    if not head:
        return ""
    # 1. MEDLINE/nbib: PMID- is unique to it.
    if re.search(r"^PMID\s*-\s*\d+", head, re.M):
        return "nbib"
    # 2. RIS: "TY  - " is mandatory and starts every reference.
    if re.search(r"^TY\s{1,2}-\s*\S", head, re.M):
        return "ris"
    # 3. BibTeX.
    if re.search(r"^\s*@[A-Za-z]+\s*[{(]", head, re.M):
        return "bibtex"
    # 4. XML families.
    low = head.lower()
    if head.startswith("<") or low.startswith("<?xml"):
        if "<records>" in low or "<record>" in low or "<ref-type" in low:
            return "endnote"
        if "<feed" in low and ("arxiv.org" in low or "arxiv" in low):
            return "arxiv-atom"
        if "<records" in low:
            return "endnote"
        return ""
    # 5. Web of Science tagged: two-letter tags, no separator.
    if re.search(r"^(FN|VR)\s+\S", head, re.M) \
            or (re.search(r"^ER\s*$", head, re.M)
                and re.search(r"^(PT|TI|AU|SO)\s{1,3}\S", head, re.M)):
        return "wos"
    # 6. Delimited text: a header row with at least two fields.
    first = head.splitlines()[0] if head.splitlines() else ""
    for delim in (",", ";", "\t"):
        if first.count(delim) >= 1:
            import csv as _csv
            try:
                cells = next(_csv.reader([first], delimiter=delim), [])
            except Exception:                                  # noqa: BLE001
                cells = []
            named = [c for c in cells if re.search(r"[A-Za-z]", c or "")]
            if len(cells) >= 2 and len(named) >= 2:
                return "csv"
    return ""


def parse_export_file(path: str, fmt: str = "auto", dialect: str = "auto",
                      encoding: str = "auto", source_name: str = "") -> Tuple[
                          List[Record], Dict[str, Any]]:
    """Parse one exported file, detecting format and vendor dialect by content.

    Returns the records and a provenance dict (format, dialect, encoding,
    accepted/rejected counts where the parser reports them).  The counts
    matter methodologically: "records identified" in the PRISMA flow comes
    from this step, so a record the parser had to drop must be visible rather
    than merely absent.
    """
    from .parsers._io import read_export_text
    from .parsers._report import ParseReport

    if not os.path.isfile(path):
        raise ConfigError(
            "input file {!r} does not exist (checked as {!r}).".format(
                path, os.path.abspath(path)))
    report = ParseReport(path=path)
    try:
        text = read_export_text(path, encoding=encoding, report=report)
    except (OSError, ValueError) as exc:
        raise DataError("cannot read {}: {}".format(path, exc))
    if not text.strip():
        raise DataError("{} is empty; nothing to parse.".format(path))

    sniffed = detect_export_format(text)
    forced = bool(fmt and fmt != "auto")
    detected = fmt if forced else sniffed
    mismatch = ""
    if forced and sniffed and sniffed != detected:
        # ``--format`` must stay usable -- it exists for exports whose markers
        # are missing. But the tagged parsers are deliberately forgiving, and
        # some accept each other's input: the MEDLINE reader will happily take
        # a RIS ``TI  - `` line and return a title-only record with no DOI. The
        # result is a corpus that looks parsed and is silently stripped of the
        # identifiers deduplication depends on, so the contradiction is
        # reported rather than resolved in favour of the flag.
        mismatch = ("forced --format {} contradicts the detected format {}; "
                    "the {} parser is forgiving enough to return records from "
                    "a {} file while dropping most fields. Check the output, "
                    "or drop --format and let the content decide.".format(
                        detected, sniffed, detected, sniffed))
    if not detected:
        preview = " ".join(text.split())[:120]
        raise DataError(
            "cannot identify the export format of {}. CorpusSLR recognises {} "
            "by content (not by extension); the file starts with: {!r}. If "
            "the format is right but the markers are missing, force it with "
            "--format.".format(path, ", ".join(_FORMAT_LABELS), preview))
    if detected not in _FORMAT_LABELS:
        raise ConfigError("unknown --format {!r}; available: {}".format(
            detected, ", ".join(_FORMAT_LABELS)))

    kw: Dict[str, Any] = {}
    if source_name:
        kw["source_name"] = source_name
    try:
        if detected == "ris":
            from .parsers.ris import detect_dialect, parse_ris
            used = dialect if dialect and dialect != "auto" \
                else detect_dialect(text)
            records = parse_ris(text, dialect=used, report=report, **kw)
        elif detected == "nbib":
            from .parsers.nbib import parse_nbib
            used = ""
            # MEDLINE and RIS share the ``XX  - value`` tag shape, so forcing
            # --format nbib on a RIS export yields records with a title and no
            # identifier: the import looks fine, the PRISMA count is right, and
            # nothing deduplicates. When the user named the format, refuse the
            # mismatch instead. Auto-detection never lands here on a RIS file.
            records = _call_parser(parse_nbib, text, report, kw)
        elif detected == "wos":
            from .parsers.wos import parse_wos
            used = ""
            records = _call_parser(parse_wos, text, report, kw)
        elif detected == "bibtex":
            from .parsers.bibtex import detect_bibtex_dialect, parse_bibtex
            used = dialect if dialect and dialect != "auto" \
                else detect_bibtex_dialect(text)
            records = _call_parser(parse_bibtex, text, report, kw,
                                   dialect=used)
        elif detected == "endnote":
            from .parsers.endnote import parse_endnote_xml
            used = ""
            records = _call_parser(parse_endnote_xml, text, report, kw)
        elif detected == "arxiv-atom":
            from .sources.arxiv import parse_arxiv_atom
            used = ""
            records = parse_arxiv_atom(text)
        else:
            from .parsers.csv_exports import (detect_csv_dialect,
                                              parse_csv_export)
            used = dialect if dialect and dialect != "auto" \
                else detect_csv_dialect(text)
            records = _call_parser(parse_csv_export, text, report, kw,
                                   dialect=used)
    except DataError:
        raise
    except Exception as exc:                                   # noqa: BLE001
        raise DataError(
            "{} was identified as {} but could not be parsed: {}: {}".format(
                path, detected, type(exc).__name__, exc))

    if not records:
        raise DataError(
            "{} was identified as {} but yielded no records. Either the "
            "export is empty, or the format guess is wrong -- override it "
            "with --format {}.".format(path, detected,
                                       "|".join(_FORMAT_LABELS)))
    if not report.fmt:
        report.fmt = detected
    if used and not report.dialect:
        report.dialect = used
    if mismatch:
        report.warn(mismatch)
    provenance = {
        "path": path, "format": detected, "dialect": used or "",
        "detected_format": sniffed, "format_forced": forced,
        "encoding": report.encoding or encoding,
        "n_records": len(records),
        "n_input": report.n_input, "n_rejected": report.n_rejected,
        "rejection_reasons": report.reason_counts(),
        "warnings": list(report.warnings),
    }
    return records, provenance


def _call_parser(func, text: str, report, kw: Dict[str, Any], **extra):
    """Call a parser, passing ``report=`` only when it accepts one.

    The export parsers gained record-level accounting at different times; a
    parser that does not take a ``report`` argument must still be usable
    rather than crash the import.
    """
    import inspect

    params = inspect.signature(func).parameters
    call_kw = dict(kw)
    call_kw.update({k: v for k, v in extra.items() if k in params})
    if "report" in params:
        call_kw["report"] = report
    return func(text, **call_kw)


def _database_for(provenance: Dict[str, Any], records: List[Record],
                  explicit: str = "") -> str:
    """Best database name for a parsed file: explicit > dialect > format.

    Naming the database is PRISMA-S Item 1 and it drives the principal/
    supplementary classification, so the canonical registry name is preferred
    over the parser's internal label ("RIS/embase" is not a database).
    """
    if explicit:
        return explicit
    for candidate in (provenance.get("dialect") or "",
                      records[0].source if records else ""):
        canon = canonical_source(candidate)
        if canon:
            return canon
    if provenance.get("format") == "nbib":
        return "PubMed/MEDLINE"
    if provenance.get("format") == "arxiv-atom":
        return "arXiv"
    if records and records[0].source:
        return records[0].source
    return "file export"


# ---------------------------------------------------------------------------
# shared command helpers
# ---------------------------------------------------------------------------
def _dedup_kwargs(cfg: Dict[str, Any], args: Any) -> Dict[str, Any]:
    kw = {k: v for k, v in (cfg.get("dedup") or {}).items()
          if k in _DEDUP_KEYS}
    if getattr(args, "fuzzy_threshold", None) is not None:
        kw["fuzzy_threshold"] = args.fuzzy_threshold
    if getattr(args, "year_tolerance", None) is not None:
        kw["year_tolerance"] = args.year_tolerance
    if getattr(args, "max_block", None) is not None:
        kw["max_block"] = args.max_block
    return kw


def _out_dir(cfg: Dict[str, Any], args: Any) -> str:
    """Output dir: the ``-C`` flag, else ``output.dir``, else the CWD."""
    out = (getattr(args, "out_dir", None)
           or (cfg.get("output") or {}).get("dir") or ".")
    if out and not os.path.isdir(out):
        os.makedirs(out, exist_ok=True)
    return out


def _named(cfg: Dict[str, Any], out_dir: str, name: str) -> str:
    prefix = str((cfg.get("output") or {}).get("prefix") or "").strip()
    if prefix:
        name = "{}_{}".format(prefix, name)
    return os.path.join(out_dir, name)


def _resolve_max_results(cfg: Dict[str, Any], spec: Dict[str, Any],
                         override: Optional[int]) -> int:
    if override is not None:
        return int(override)
    if spec.get("max_results") is not None:
        return int(spec["max_results"])
    if cfg.get("max_results") is not None:
        return int(cfg["max_results"])
    return 2000


def _run_searches(cfg: Dict[str, Any], query: SearchQuery, corpus: Corpus,
                  console: _Console, session: Any = None,
                  max_results: Optional[int] = None,
                  keep_going: bool = False) -> Tuple[List[Dict[str, Any]],
                                                     List[Dict[str, Any]]]:
    """Query every configured API database into *corpus*.

    A source that fails is never silently dropped: without ``--keep-going``
    the command stops, and with it the failure is recorded in the run summary,
    because a review whose Scopus leg quietly returned nothing reports a
    complete-looking corpus that is missing a principal database.
    """
    email = _contact_email(console)
    done: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []
    for spec in cfg.get("databases") or []:
        alias = spec["name"]
        label = DATABASES[alias]["label"]
        cap = _resolve_max_results(cfg, spec, max_results)
        console.info("searching {} (max {} records)...".format(label, cap))
        try:
            source = build_source(alias, spec, session=session, email=email)
            result = source.search(query, max_results=cap)
        except ConfigError as exc:
            if not keep_going:
                raise
            console.warn("{} skipped: {}".format(
                label, str(exc).splitlines()[0]))
            failed.append({"database": label, "reason": "missing credential",
                           "message": str(exc).splitlines()[0]})
            continue
        except SourceError as exc:
            if not keep_going:
                raise DataError("{} failed: {}".format(label, exc))
            console.warn("{} failed: {}".format(label, exc))
            failed.append({"database": label, "reason": "source error",
                           "message": str(exc)})
            continue
        except Exception as exc:                               # noqa: BLE001
            if not keep_going:
                raise DataError("{} failed: {}: {}".format(
                    label, type(exc).__name__, exc))
            console.warn("{} failed: {}: {}".format(
                label, type(exc).__name__, exc))
            failed.append({"database": label, "reason": type(exc).__name__,
                           "message": str(exc)})
            continue
        event = corpus.add_search(result)
        console.info("  {}: {} records".format(label, event.records_retrieved))
        done.append({"database": label, "search_id": event.search_id,
                     "records": event.records_retrieved,
                     "query": event.query, "date_run": event.date_run,
                     "tier_keyless": bool(DATABASES[alias]["keyless"])})
    return done, failed


def _parse_files(cfg: Dict[str, Any], corpus: Corpus, console: _Console,
                 entries: Optional[List[Dict[str, Any]]] = None) -> List[
                     Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for entry in (entries if entries is not None else cfg.get("files") or []):
        path = str(entry["path"])
        console.info("parsing {}...".format(path))
        records, prov = parse_export_file(
            path,
            fmt=str(entry.get("format") or "auto"),
            dialect=str(entry.get("dialect") or "auto"),
            encoding=str(entry.get("encoding") or "auto"),
            source_name=str(entry.get("database") or ""))
        database = _database_for(prov, records,
                                str(entry.get("database") or ""))
        # Every record in one export file comes from one database, so its
        # ``source`` is set to the resolved database name. The parsers'
        # own defaults name the format instead ("RIS/embase", "Web of
        # Science" for the tagged reader), and leaving those in place would
        # make the per-source quality report and the exports disagree with
        # the PRISMA "records identified" table for the same search. The
        # format, dialect and encoding stay recorded in the search-event note
        # and in the per-file provenance, so nothing is lost.
        for rec in records:
            rec.source = database
        event = corpus.add_records(
            records, database=database,
            platform=str(entry.get("platform") or ""),
            interface=str(entry.get("interface") or "web interface export"),
            query=str(entry.get("query") or ""),
            filters=str(entry.get("filters") or ""),
            date_run=str(entry.get("date_run") or ""),
            notes=str(entry.get("notes")
                      or "imported from {} ({}{})".format(
                          os.path.basename(path), prov["format"],
                          "/" + prov["dialect"] if prov["dialect"] else "")))
        console.info("  {}: {} records ({}{}{})".format(
            database, len(records), prov["format"],
            "/" + prov["dialect"] if prov["dialect"] else "",
            ", {} rejected".format(prov["n_rejected"])
            if prov["n_rejected"] else ""))
        # Parser warnings are not progress chatter: a replaced undecodable
        # byte, an unrecognised vendor dialect or a forced format that
        # contradicts the content all change what the parsed records contain.
        for warning in prov["warnings"]:
            console.warn("{}: {}".format(os.path.basename(path), warning))
        prov = dict(prov)
        prov["database"] = database
        prov["search_id"] = event.search_id
        out.append(prov)
    return out


def _screening_from(cfg: Dict[str, Any], args: Any) -> Dict[str, Any]:
    """Merge screening counts from the configuration and the command line."""
    sc = dict(cfg.get("screening") or {})
    mapping = (("records_excluded", "records_excluded"),
               ("reports_not_retrieved", "reports_not_retrieved"),
               ("studies_included", "studies_included"),
               ("reports_included", "reports_included"),
               ("automation_excluded", "automation_excluded"),
               ("other_excluded", "other_excluded"))
    for attr, key in mapping:
        val = getattr(args, attr, None)
        if val is not None:
            sc[key] = val
    for item in getattr(args, "exclude", None) or []:
        if "=" not in item:
            raise ConfigError(
                "--exclude expects 'reason=count', got {!r} (e.g. --exclude "
                "'wrong population=41').".format(item))
        reason, _, count = item.partition("=")
        try:
            n = int(count)
        except ValueError:
            raise ConfigError(
                "--exclude {!r}: {!r} is not an integer.".format(item, count))
        if n < 0:
            raise ConfigError(
                "--exclude {!r}: the count must not be negative.".format(item))
        sc.setdefault("fulltext_exclusions", {})
        sc["fulltext_exclusions"][reason.strip()] = n
    return sc


def _build_flow(corpus: Corpus, result: Optional[DedupResult],
                screening: Dict[str, Any]) -> PrismaFlow:
    removed = result.report.removed if result is not None else 0
    by_method = dict(result.report.by_method) if result is not None else {}
    flow = PrismaFlow(db_counts=corpus.identified_by_source(),
                      duplicates_removed=removed, dedup_by_method=by_method)
    if screening:
        flow.set_screening(
            records_excluded=int(screening.get("records_excluded") or 0),
            reports_not_retrieved=int(
                screening.get("reports_not_retrieved") or 0),
            fulltext_exclusions={
                str(k): int(v) for k, v in
                (screening.get("fulltext_exclusions") or {}).items()},
            studies_included=int(screening.get("studies_included") or 0),
            reports_included=(int(screening["reports_included"])
                              if screening.get("reports_included") is not None
                              else None),
            automation_excluded=int(screening.get("automation_excluded") or 0),
            other_excluded=int(screening.get("other_excluded") or 0))
    return flow


def _write_prisma(flow: PrismaFlow, corpus: Corpus,
                  result: Optional[DedupResult], cfg: Dict[str, Any],
                  out_dir: str, console: _Console, screening: Dict[str, Any],
                  svg_path: str = "", appendix_path: str = "",
                  strict: bool = True) -> Dict[str, Any]:
    written: Dict[str, Any] = {}
    if screening:
        problems = flow.validate()
        if problems:
            message = ("the PRISMA 2020 flow does not balance:\n  - "
                       + "\n  - ".join(problems)
                       + "\nFix the screening counts; a diagram whose "
                         "arithmetic fails would misreport the review.")
            if strict:
                raise DataError(message)
            console.warn(message)
        written["prisma_valid"] = not problems
        written["prisma_problems"] = problems
    else:
        console.warn(
            "no screening counts supplied (config \"screening\" block, or "
            "--records-excluded/--studies-included/--exclude), so the "
            "identification and deduplication stages are documented and the "
            "screening stages are reported as 0. Add the counts from your "
            "screening tool for a complete PRISMA 2020 diagram.")
        written["prisma_valid"] = None
        written["prisma_problems"] = []

    appendix_fmt = str((cfg.get("output") or {}).get("appendix") or "md")
    if (cfg.get("output") or {}).get("svg", True):
        path = svg_path or _named(cfg, out_dir, "prisma2020_flow.svg")
        _ensure_parent(path)
        flow.to_svg(path)
        written["flow_svg"] = path
        console.info("wrote {}".format(path))
    dedup_cfg = cfg.get("dedup") or {}
    path = appendix_path or _named(
        cfg, out_dir, "prisma_s_appendix.{}".format(appendix_fmt))
    _ensure_parent(path)
    actual = prisma_s_appendix(
        corpus, result, path,
        fuzzy_threshold=float(dedup_cfg.get("fuzzy_threshold", 0.93)),
        year_tolerance=int(dedup_cfg.get("year_tolerance", 1)))
    written["prisma_s_appendix"] = actual
    if actual != path:
        console.warn(
            "python-docx is not installed, so the appendix was written as "
            "Markdown ({}) instead of .docx; install corpusslr[docx] for a "
            "Word appendix.".format(actual))
    console.info("wrote {}".format(actual))
    written["counts"] = flow.counts()
    return written


def _write_exports(records: List[Record], cfg: Dict[str, Any], out_dir: str,
                   console: _Console,
                   formats: Optional[Sequence[str]] = None) -> Dict[str, str]:
    formats = list(formats or (cfg.get("output") or {}).get("exports")
                   or ["scopus", "csv", "screening"])
    written: Dict[str, str] = {}
    for fmt in formats:
        if fmt == "scopus":
            path = _named(cfg, out_dir, "corpus_scopus.csv")
            to_scopus_csv(records, path)
        elif fmt == "csv":
            path = _named(cfg, out_dir, "corpus.csv")
            to_csv(records, path)
        elif fmt == "screening":
            path = _named(cfg, out_dir, "screening.csv")
            to_screening_csv(records, path)
        elif fmt == "ris":
            path = _named(cfg, out_dir, "corpus.ris")
            to_ris(records, path)
        elif fmt == "bibtex":
            path = _named(cfg, out_dir, "corpus.bib")
            to_bibtex(records, path)
        else:
            raise ConfigError("unknown export format {!r}; available: {}"
                              .format(fmt, ", ".join(_EXPORT_FORMATS)))
        written[fmt] = path
        console.info("wrote {}".format(path))
    return written


def _decisions_csv(result: DedupResult, path: str, console: _Console) -> str:
    _ensure_parent(path)
    result.report.to_csv(path)
    console.info("wrote {}".format(path))
    return path


def _utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _provenance(cfg: Dict[str, Any]) -> Dict[str, Any]:
    return {"corpusslr_version": __version__,
            "python": "{}.{}.{}".format(*sys.version_info[:3]),
            "run_at": _utcnow(),
            "config_path": cfg.get("_path", ""),
            "config_sha256": cfg.get("_checksum", "")}


# ---------------------------------------------------------------------------
# subcommands
# ---------------------------------------------------------------------------
def cmd_check(args: Any, console: _Console) -> int:
    """Validate a configuration and print the plan it implies."""
    cfg = load_config(args.config)
    query = build_query(cfg)
    plan: Dict[str, Any] = {"config": _provenance(cfg), "valid": True,
                            "databases": [], "files": [], "warnings": []}
    for spec in cfg.get("databases") or []:
        alias = spec["name"]
        entry = credential_status(alias)
        entry.update(compile_for(alias, query))
        entry["max_results"] = _resolve_max_results(cfg, spec, None)
        plan["databases"].append(entry)
        if entry["requires_credential"] and not entry["credential_present"]:
            plan["warnings"].append(
                "{}: {} is not set; the search would fail (or be skipped with "
                "--keep-going)".format(entry["database"],
                                       entry["credential_variable"]))
    for entry in cfg.get("files") or []:
        path = str(entry["path"])
        # ``format`` is always present in the report, even when the probe
        # cannot run: a caller reading the plan should not have to distinguish
        # "unreadable" from "key absent".
        item: Dict[str, Any] = {"path": path, "exists": os.path.isfile(path),
                                "format": ""}
        if item["exists"]:
            try:
                from .parsers._io import read_export_text
                item["format"] = detect_export_format(
                    read_export_text(path, encoding=str(
                        entry.get("encoding") or "auto")))
            except Exception as exc:                           # noqa: BLE001
                item["format"] = ""
                item["error"] = "{}: {}".format(type(exc).__name__, exc)
            if not item["format"]:
                plan["warnings"].append(
                    "{}: export format not recognised; set \"format\" "
                    "explicitly".format(path))
        elif os.path.exists(path):
            item["error"] = "not a regular file"
            plan["warnings"].append(
                "{}: exists but is not a readable file (a directory?)".format(
                    path))
        else:
            plan["warnings"].append("{}: file does not exist".format(path))
        plan["files"].append(item)
    if query.warnings:
        plan["query_warnings"] = list(dict.fromkeys(query.warnings))
    if not _env_first(CONTACT_ENV)[1]:
        plan["warnings"].append(
            "no contact address in {}".format(" or ".join(CONTACT_ENV)))
    principal = [d for d in plan["databases"] if not d["keyless"]]
    if not principal:
        plan["warnings"].append(
            "no principal search system among the API databases (Scopus, Web "
            "of Science); Gusenbauer & Haddaway (2020) recommend at least one "
            "principal source, importable as a file export if the API is not "
            "available")
    plan["output_dir"] = (cfg.get("output") or {}).get("dir") or "."
    plan["dedup"] = cfg.get("dedup") or {}
    console.info("configuration {} is valid".format(args.config))
    for warning in plan["warnings"]:
        console.warn(warning)
    console.json(plan)
    return EXIT_OK


def cmd_search(args: Any, console: _Console) -> int:
    """Query the configured API databases and write a corpus."""
    cfg = load_config(args.config)
    query = build_query(cfg)
    if not cfg.get("databases"):
        raise ConfigError(
            'no API databases in "databases"; "corpusslr search" has nothing '
            'to query. Use "corpusslr parse" for file exports.')

    if args.dry_run:
        payload: Dict[str, Any] = {"dry_run": True, "config": _provenance(cfg),
                                   "databases": []}
        for spec in cfg["databases"]:
            alias = spec["name"]
            compiled = compile_for(alias, query)
            status = credential_status(alias)
            row = {"database": status["database"],
                   "max_results": _resolve_max_results(
                       cfg, spec, args.max_results),
                   "credential_present": status["credential_present"],
                   "credential_variable": status["credential_variable"]}
            row.update(compiled)
            payload["databases"].append(row)
            console.info("{}: {}".format(status["database"],
                                         compiled["query"]))
            if compiled.get("filters"):
                console.detail("filters: " + compiled["filters"])
        payload["query_warnings"] = list(dict.fromkeys(query.warnings))
        for warning in payload["query_warnings"]:
            console.warn(warning)
        console.info("dry run: nothing was retrieved")
        console.json(payload)
        return EXIT_OK

    corpus = Corpus()
    searched, failed = _run_searches(cfg, query, corpus, console,
                                     session=args._session,
                                     max_results=args.max_results,
                                     keep_going=args.keep_going)
    if not corpus.records and failed:
        raise DataError(
            "no records retrieved; every source failed ({}).".format(
                "; ".join(f["database"] for f in failed)))
    out_path = args.out or _named(cfg, _out_dir(cfg, args), "corpus_raw.json")
    write_corpus(corpus, out_path)
    console.info("wrote {} ({} records)".format(out_path, len(corpus.records)))
    console.json({"command": "search", "config": _provenance(cfg),
                  "corpus": out_path,
                  "identified": corpus.total_identified(),
                  "identified_by_source": corpus.identified_by_source(),
                  "searches": searched, "failures": failed,
                  "query_warnings": list(dict.fromkeys(query.warnings))})
    return EXIT_OK


def cmd_parse(args: Any, console: _Console) -> int:
    """Import database exports, detecting format and dialect by content."""
    cfg = {"output": {}} if not args.config else load_config(args.config)
    entries: List[Dict[str, Any]] = []
    for path in args.paths:
        entries.append({"path": path, "database": args.database or "",
                        "platform": args.platform or "",
                        "interface": args.interface or
                        "web interface export",
                        "query": args.query or "",
                        "date_run": args.date_run or "",
                        "format": args.format, "dialect": args.dialect,
                        "encoding": args.encoding})
    if not entries and args.config:
        entries = list(cfg.get("files") or [])
    if not entries:
        raise ConfigError(
            "no input files: pass one or more paths, or a --config with a "
            '"files" section.')

    corpus = Corpus()
    if args.append:
        corpus, _ = read_corpus(args.append)
        console.info("appending to {} ({} records)".format(
            args.append, len(corpus.records)))
    parsed = _parse_files(cfg, corpus, console, entries=entries)
    out_path = args.out or args.append or _named(cfg, _out_dir(cfg, args),
                                                 "corpus_raw.json")
    write_corpus(corpus, out_path)
    console.info("wrote {} ({} records)".format(out_path, len(corpus.records)))
    console.json({"command": "parse", "corpus": out_path,
                  "files": parsed,
                  "identified": corpus.total_identified(),
                  "identified_by_source": corpus.identified_by_source()})
    return EXIT_OK


def cmd_dedup(args: Any, console: _Console) -> int:
    """Deduplicate a corpus, writing the unique set and the decision log."""
    cfg = {"output": {}} if not args.config else load_config(args.config)
    corpus, _ = read_corpus(args.corpus)
    if not corpus.records:
        raise DataError("{} contains no records.".format(args.corpus))
    kw = _dedup_kwargs(cfg, args)
    console.info("deduplicating {} records{}...".format(
        len(corpus.records),
        " ({})".format(", ".join("{}={}".format(k, v)
                                 for k, v in sorted(kw.items())))
        if kw else ""))
    result = deduplicate(corpus, **kw)
    for line in result.report.summary().splitlines():
        console.info(line)
    for warning in result.report.warnings():
        console.warn(warning)

    out_dir = _out_dir(cfg, args)
    out_path = args.out or _named(cfg, out_dir, "corpus_unique.json")
    unique = Corpus()
    unique.searches = list(corpus.searches)
    unique.records = list(result.records)
    write_corpus(unique, out_path, result=result)
    console.info("wrote {} ({} unique records)".format(out_path,
                                                       len(result.records)))
    report_path = args.report or _named(cfg, out_dir, "dedup_report.csv")
    _decisions_csv(result, report_path, console)
    payload = {"command": "dedup", "corpus": out_path,
               "report": report_path,
               "before": result.report.before, "after": result.report.after,
               "removed": result.report.removed,
               "by_method": dict(result.report.by_method),
               "warnings": result.report.warnings(),
               "parameters": kw}
    # The deduplicated set is what goes into a bibliometric analysis, and the
    # format those tools read is the Scopus CSV export, so it is written here
    # by default rather than requiring a second "corpusslr export" call.
    # --export-format selects a different one; --no-export suppresses it.
    if not args.no_export:
        payload["exports"] = _write_exports(
            result.records, cfg, out_dir, console,
            formats=args.export_format or ["scopus"])
    if args.overlap:
        _ensure_parent(args.overlap)
        with open(args.overlap, "w", encoding="utf-8") as fh:
            fh.write(result.report.overlap_markdown() + "\n")
        payload["overlap"] = args.overlap
        console.info("wrote {}".format(args.overlap))
    console.json(payload)
    return EXIT_OK


def cmd_prisma(args: Any, console: _Console) -> int:
    """Render the PRISMA 2020 flow diagram and the PRISMA-S appendix."""
    cfg = {"output": {}} if not args.config else load_config(args.config)
    corpus, result = read_corpus(args.corpus)
    if not corpus.searches:
        raise DataError(
            "{} records no search events, so the PRISMA flow has no "
            '"records identified" per source. Produce the corpus with '
            '"corpusslr search"/"corpusslr parse".'.format(args.corpus))
    screening = _screening_from(cfg, args)
    flow = _build_flow(corpus, result, screening)
    out_dir = _out_dir(cfg, args)
    written = _write_prisma(flow, corpus, result, cfg, out_dir, console,
                            screening, svg_path=args.svg or "",
                            appendix_path=args.appendix or "",
                            strict=not args.no_strict)
    console.data(flow.to_markdown())
    if args.audit:
        _ensure_parent(args.audit)
        with open(args.audit, "w", encoding="utf-8") as fh:
            fh.write(audit_markdown(corpus) + "\n")
        written["audit"] = args.audit
        console.info("wrote {}".format(args.audit))
    console.info("PRISMA counts: identified={} duplicates={} included={}"
                 .format(flow.identified, flow.duplicates_removed,
                         flow.studies_included))
    return EXIT_OK


def cmd_export(args: Any, console: _Console) -> int:
    """Write CSV / screening CSV / RIS / BibTeX from a corpus."""
    cfg = {"output": {}} if not args.config else load_config(args.config)
    corpus, _ = read_corpus(args.corpus)
    if not corpus.records:
        raise DataError("{} contains no records.".format(args.corpus))
    written: Dict[str, str] = {}
    explicit = [(args.scopus, "scopus"), (args.csv, "csv"),
                (args.screening, "screening"),
                (args.ris, "ris"), (args.bibtex, "bibtex")]
    if any(path for path, _ in explicit):
        for path, fmt in explicit:
            if not path:
                continue
            _ensure_parent(path)
            if fmt == "scopus":
                to_scopus_csv(corpus.records, path)
            elif fmt == "csv":
                to_csv(corpus.records, path,
                       columns=[c.strip() for c in args.columns.split(",")]
                       if args.columns else None)
            elif fmt == "screening":
                to_screening_csv(corpus.records, path)
            elif fmt == "ris":
                to_ris(corpus.records, path)
            else:
                to_bibtex(corpus.records, path)
            written[fmt] = path
            console.info("wrote {}".format(path))
    else:
        written = _write_exports(corpus.records, cfg, _out_dir(cfg, args),
                                 console, formats=args.format or None)
    console.json({"command": "export", "records": len(corpus.records),
                  "written": written})
    return EXIT_OK


def cmd_quality(args: Any, console: _Console) -> int:
    """Per-source metadata-completeness report."""
    cfg = {"output": {}} if not args.config else load_config(args.config)
    corpus, _ = read_corpus(args.corpus)
    if not corpus.records:
        raise DataError("{} contains no records.".format(args.corpus))
    if args.csv:
        _ensure_parent(args.csv)
        quality_csv(corpus.records, args.csv)
        console.info("wrote {}".format(args.csv))
    if args.json:
        console.json({"command": "quality",
                      "report": quality_report(corpus.records),
                      "csv": args.csv or ""})
    else:
        console.data(quality_markdown(corpus.records))
    del cfg
    return EXIT_OK


def cmd_harvest(args: Any, console: _Console) -> int:
    """Retrieve one database while archiving every raw HTTP response."""
    cfg = load_config(args.config)
    query = build_query(cfg)
    alias = _norm_db(args.database)
    if not alias:
        raise ConfigError("unknown database {!r}; available: {}".format(
            args.database, _available_databases()))
    archive = args.archive or (cfg.get("harvest") or {}).get("archive")
    if not archive:
        raise ConfigError(
            "no archive directory: pass --archive DIR or set "
            '"harvest": {"archive": "DIR"} in the configuration. The archive '
            "is the evidence a reviewer replays without credentials.")
    spec = {}
    for entry in cfg.get("databases") or []:
        if entry["name"] == alias:
            spec = entry
            break
    cap = _resolve_max_results(cfg, spec, args.max_results)
    email = _contact_email(console)
    source = build_source(alias, spec, session=args._session, email=email)
    console.info("harvesting {} into {} (max {})...".format(
        DATABASES[alias]["label"], archive, cap))
    try:
        result = harvest(source, query, max_results=cap, archive=archive,
                         harvest_id=args.harvest_id or None,
                         notes=args.notes or
                         (cfg.get("harvest") or {}).get("notes", ""))
    except HarvestError as exc:
        raise DataError("harvest failed: {}".format(exc))
    except SourceError as exc:
        raise DataError("{} failed: {}".format(DATABASES[alias]["label"], exc))
    manifest = result.manifest
    console.info("  {} records, checksum {}".format(
        len(result.records), result.checksum[:16]))
    payload = {"command": "harvest", "config": _provenance(cfg),
               "database": DATABASES[alias]["label"],
               "archive": result.archive_path,
               "harvest_id": manifest.harvest_id if manifest else "",
               "records": len(result.records),
               "checksum": result.checksum,
               "responses": manifest.n_responses if manifest else 0,
               "authenticated": bool(manifest.authenticated) if manifest
               else False,
               "warnings": list(manifest.warnings) if manifest else []}
    if args.manifest:
        _ensure_parent(args.manifest)
        result.write_manifest(args.manifest)
        payload["manifest"] = args.manifest
        console.info("wrote {}".format(args.manifest))
    if args.markdown:
        _ensure_parent(args.markdown)
        with open(args.markdown, "w", encoding="utf-8") as fh:
            fh.write(harvest_markdown([result]) + "\n")
        payload["markdown"] = args.markdown
        console.info("wrote {}".format(args.markdown))
    if args.out:
        corpus = Corpus()
        corpus.add_search(result.to_source_result())
        write_corpus(corpus, args.out)
        payload["corpus"] = args.out
        console.info("wrote {}".format(args.out))
    console.json(payload)
    return EXIT_OK


def cmd_replay(args: Any, console: _Console) -> int:
    """Re-run an archived harvest offline and verify it reproduces exactly."""
    cfg = load_config(args.config)
    query = build_query(cfg)
    alias = _norm_db(args.database) if args.database else ""
    if args.database and not alias:
        raise ConfigError("unknown database {!r}; available: {}".format(
            args.database, _available_databases()))
    if not alias:
        try:
            arch = HarvestArchive.open(args.archive)
        except HarvestError as exc:
            raise DataError(str(exc))
        labels = [m.database for m in arch.harvests]
        candidates = [a for a in DATABASES
                      if DATABASES[a]["label"] in labels]
        if len(candidates) != 1:
            raise ConfigError(
                "{} holds {} harvest(s) ({}); name the one to replay with "
                "--database.".format(args.archive, len(labels),
                                     ", ".join(labels) or "none"))
        alias = candidates[0]

    problems = []
    try:
        problems = verify_archive(args.archive)
    except HarvestError as exc:
        raise DataError("{} cannot be audited: {}".format(args.archive, exc))
    if problems:
        message = ("{} failed its integrity audit:\n  - ".format(args.archive)
                   + "\n  - ".join(problems[:5]))
        if not args.no_strict:
            raise DataError(message)
        console.warn(message)

    spec = {}
    for entry in cfg.get("databases") or []:
        if entry["name"] == alias:
            spec = entry
            break
    # Replay never opens a socket, so credentials are irrelevant by design:
    # that is precisely what makes the archive independently verifiable.
    source = build_source(alias, spec, session=None, email="",
                          require_credentials=False)
    console.info("replaying {} from {}...".format(
        DATABASES[alias]["label"], args.archive))
    try:
        # ``verify`` follows ``strict`` deliberately. With the default strict
        # replay, a stored body whose bytes disagree with its manifest
        # checksum is refused outright: serving it would present tampered or
        # truncated data as verified evidence. With --no-strict the reviewer
        # has explicitly asked to look at a damaged archive anyway -- to see
        # how far it diverges, or to salvage a harvest that was interrupted --
        # so the bodies are served and every integrity problem is reported in
        # ``integrity_problems`` instead of stopping the command.
        result = harvest(source, query, archive=args.archive, replay=True,
                         harvest_id=args.harvest_id or None,
                         verify=not args.no_strict,
                         strict=not args.no_strict)
    except HarvestError as exc:
        raise DataError("replay failed: {}".format(exc))
    matches = result.checksum_matches
    console.info("  {} records, checksum {} ({})".format(
        len(result.records), result.checksum[:16],
        "matches the recorded harvest" if matches
        else "DIVERGED from the recorded harvest"))
    payload = {"command": "replay", "config": _provenance(cfg),
               "database": DATABASES[alias]["label"],
               "archive": args.archive,
               "records": len(result.records),
               "checksum": result.checksum,
               "recorded_checksum": result.recorded_checksum,
               "checksum_matches": matches,
               "integrity_problems": problems}
    if args.out:
        corpus = Corpus()
        corpus.add_search(result.to_source_result())
        write_corpus(corpus, args.out)
        payload["corpus"] = args.out
        console.info("wrote {}".format(args.out))
    if args.compare:
        diff = compare_harvests(args.archive, args.compare,
                               label_before=args.archive,
                               label_after=args.compare)
        payload["drift"] = diff.to_dict()
        console.info(diff.summary())
        if args.drift_markdown:
            _ensure_parent(args.drift_markdown)
            with open(args.drift_markdown, "w", encoding="utf-8") as fh:
                fh.write(diff.to_markdown() + "\n")
            payload["drift_markdown"] = args.drift_markdown
            console.info("wrote {}".format(args.drift_markdown))
    console.json(payload)
    if matches is False and not args.no_strict:
        raise DataError(
            "the replayed record set does not match the checksum recorded at "
            "harvest time; the archive or the package version differs from "
            "the one that produced it.")
    return EXIT_OK


def cmd_tui(args: Any, console: _Console) -> int:
    """Start the guided interface, which asks instead of being configured.

    The subcommand is a thin door onto :mod:`corpusslr.tui`: the interface
    writes the same configuration file this CLI consumes, so a review started
    by answering questions is afterwards indistinguishable from one written by
    hand -- rerunnable with ``corpusslr run -c``, and depositable.
    """
    from .tui import main as tui_main
    del args
    return int(tui_main(stdout=console.stream))


def cmd_run(args: Any, console: _Console) -> int:
    """Execute the whole review described by one configuration file."""
    cfg = load_config(args.config)
    query = build_query(cfg)
    out_dir = _out_dir(cfg, args)
    summary: Dict[str, Any] = {"command": "run", "config": _provenance(cfg),
                               "output_dir": out_dir}

    if args.dry_run:
        summary["dry_run"] = True
        summary["databases"] = []
        for spec in cfg.get("databases") or []:
            alias = spec["name"]
            row = credential_status(alias)
            row.update(compile_for(alias, query))
            row["max_results"] = _resolve_max_results(cfg, spec,
                                                      args.max_results)
            summary["databases"].append(row)
            console.info("{}: {}".format(row["database"], row["query"]))
        summary["files"] = [{"path": e["path"],
                             "exists": os.path.isfile(str(e["path"]))}
                            for e in cfg.get("files") or []]
        summary["query_warnings"] = list(dict.fromkeys(query.warnings))
        console.info("dry run: nothing was retrieved or written")
        console.json(summary)
        return EXIT_OK

    corpus = Corpus()
    searched, failed = _run_searches(cfg, query, corpus, console,
                                     session=args._session,
                                     max_results=args.max_results,
                                     keep_going=args.keep_going)
    parsed = _parse_files(cfg, corpus, console)
    if not corpus.records:
        raise DataError(
            "no records identified: every API source failed or returned "
            "nothing and no file export was configured.")
    summary["searches"] = searched
    summary["failures"] = failed
    summary["files"] = parsed
    summary["identified"] = corpus.total_identified()
    summary["identified_by_source"] = corpus.identified_by_source()
    summary["query_warnings"] = list(dict.fromkeys(query.warnings))

    raw_path = _named(cfg, out_dir, "corpus_raw.json")
    write_corpus(corpus, raw_path)
    summary["corpus_raw"] = raw_path
    console.info("wrote {} ({} records)".format(raw_path, len(corpus.records)))

    enrich_cfg = cfg.get("enrich") or {}
    if enrich_cfg.get("recover_abstracts") and not args.no_enrich:
        email = _contact_email(console)
        console.info("recovering missing abstracts...")
        try:
            stats = recover_abstracts(
                corpus.records, mailto=email,
                min_len=int(enrich_cfg.get("min_len", 250)),
                session=args._session)
            summary["abstract_recovery"] = stats
            console.info("  {}".format(stats))
        except Exception as exc:                               # noqa: BLE001
            console.warn("abstract recovery failed ({}: {}); continuing with "
                         "the abstracts as retrieved".format(
                             type(exc).__name__, exc))
            summary["abstract_recovery"] = {"error": str(exc)}

    quality_path = _named(cfg, out_dir, "quality.md")
    with open(quality_path, "w", encoding="utf-8") as fh:
        fh.write(quality_markdown(corpus.records) + "\n")
    summary["quality_markdown"] = quality_path
    console.info("wrote {}".format(quality_path))
    if (cfg.get("output") or {}).get("quality_csv", True):
        path = _named(cfg, out_dir, "quality.csv")
        quality_csv(corpus.records, path)
        summary["quality_csv"] = path
        console.info("wrote {}".format(path))

    kw = _dedup_kwargs(cfg, args)
    console.info("deduplicating {} records...".format(len(corpus.records)))
    result = deduplicate(corpus, **kw)
    for line in result.report.summary().splitlines():
        console.info(line)
    for warning in result.report.warnings():
        console.warn(warning)
    summary["dedup"] = {"before": result.report.before,
                        "after": result.report.after,
                        "removed": result.report.removed,
                        "by_method": dict(result.report.by_method),
                        "warnings": result.report.warnings(),
                        "parameters": kw}

    unique = Corpus()
    unique.searches = list(corpus.searches)
    unique.records = list(result.records)
    unique_path = _named(cfg, out_dir, "corpus_unique.json")
    write_corpus(unique, unique_path, result=result)
    summary["corpus_unique"] = unique_path
    console.info("wrote {} ({} unique records)".format(unique_path,
                                                       len(result.records)))
    summary["dedup_report"] = _decisions_csv(
        result, _named(cfg, out_dir, "dedup_report.csv"), console)
    overlap_path = _named(cfg, out_dir, "overlap.md")
    with open(overlap_path, "w", encoding="utf-8") as fh:
        fh.write(result.report.overlap_markdown() + "\n")
    summary["overlap_markdown"] = overlap_path
    console.info("wrote {}".format(overlap_path))

    screening = _screening_from(cfg, args)
    flow = _build_flow(unique, result, screening)
    summary["prisma"] = _write_prisma(flow, unique, result, cfg, out_dir,
                                      console, screening,
                                      strict=not args.no_strict)
    summary["exports"] = _write_exports(result.records, cfg, out_dir, console)
    audit_path = _named(cfg, out_dir, "source_audit.md")
    with open(audit_path, "w", encoding="utf-8") as fh:
        fh.write(audit_markdown(unique) + "\n")
    summary["source_audit"] = audit_path
    console.info("wrote {}".format(audit_path))

    summary_path = _named(cfg, out_dir, "run_summary.json")
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=1, sort_keys=True)
    summary["run_summary"] = summary_path
    console.info("wrote {}".format(summary_path))
    console.info("done: {} identified -> {} unique".format(
        corpus.total_identified(), len(result.records)))
    console.json(summary)
    return EXIT_OK


# ---------------------------------------------------------------------------
# argument parser
# ---------------------------------------------------------------------------
_EPILOG = """\
exit codes:
  0  success
  1  user error (bad configuration, unknown database, missing credential or
     input file)
  2  data error (unrecognisable export, corrupt archive, failed integrity
     check, API failure, PRISMA flow that does not balance)
  3  internal error -- rerun with --traceback and report it

credentials are read from the environment only, never from the configuration
file: SCOPUS_API_KEY (+ SCOPUS_INSTTOKEN off campus), WOS_API_KEY,
SEMANTIC_SCHOLAR_API_KEY, NCBI_API_KEY, and CORPUSSLR_CONTACT_EMAIL for the
politeness contact address Crossref, OpenAlex and NCBI ask for.
"""


def _add_config(parser: argparse.ArgumentParser,
                required: bool = True) -> None:
    parser.add_argument("-c", "--config", required=required,
                        metavar="FILE",
                        help="review configuration (JSON; YAML if PyYAML is "
                             "installed)")


def _common_parent() -> argparse.ArgumentParser:
    """Global flags, repeated on every subcommand.

    ``corpusslr prisma corpus.json -q -C out`` is the order most people type,
    and plain argparse rejects it because the global options were consumed
    before the subcommand.  The flags are therefore declared a second time on
    each subparser with ``default=argparse.SUPPRESS``, so an option given
    after the subcommand sets the value and an option omitted there leaves the
    value parsed before it untouched -- both positions work and neither
    silently overrides the other with a default.
    """
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-q", "--quiet", action="store_true",
                        default=argparse.SUPPRESS,
                        help=argparse.SUPPRESS)
    common.add_argument("-v", "--verbose", action="store_true",
                        default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    common.add_argument("--traceback", action="store_true",
                        default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    common.add_argument("-C", "--out-dir", metavar="DIR",
                        default=argparse.SUPPRESS,
                        help='output directory (overrides "output.dir")')
    return common


def _add_dedup_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--fuzzy-threshold", type=float, default=None,
                        metavar="R",
                        help="normalized-title similarity required for a "
                             "fuzzy duplicate (validated default 0.93)")
    parser.add_argument("--year-tolerance", type=int, default=None,
                        metavar="N",
                        help="allowed publication-year difference (default 1)")
    parser.add_argument("--max-block", type=int, default=None, metavar="N",
                        help="maximum blocking-bucket size (default 400)")


def _add_screening_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--records-excluded", type=int, default=None,
                        metavar="N", help="title/abstract exclusions")
    parser.add_argument("--reports-not-retrieved", type=int, default=None,
                        metavar="N",
                        help="full texts that could not be obtained")
    parser.add_argument("--studies-included", type=int, default=None,
                        metavar="N", help="studies included in the review")
    parser.add_argument("--reports-included", type=int, default=None,
                        metavar="N", help="reports of the included studies")
    parser.add_argument("--automation-excluded", type=int, default=None,
                        metavar="N",
                        help="records removed before screening by automation")
    parser.add_argument("--other-excluded", type=int, default=None,
                        metavar="N",
                        help="records removed before screening for other "
                             "reasons")
    parser.add_argument("--exclude", action="append", metavar="REASON=N",
                        help="full-text exclusion reason and count; "
                             "repeatable")
    parser.add_argument("--no-strict", action="store_true",
                        help="report an unbalanced PRISMA flow as a warning "
                             "instead of failing with exit code 2")


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser (exposed so that it can be tested)."""
    parser = argparse.ArgumentParser(
        prog="corpusslr",
        description="From one structured query to a PRISMA-documented corpus.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version",
                        version="corpusslr {}".format(__version__))
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="suppress progress output on stderr")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="more detail on stderr")
    parser.add_argument("--traceback", action="store_true",
                        help="show the Python traceback for unexpected errors")
    parser.add_argument("-C", "--out-dir", metavar="DIR", default=None,
                        help='output directory (overrides "output.dir")')
    common = _common_parent()
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    p = sub.add_parser("check", parents=[common],
                       help="validate a configuration and show the "
                            "plan it implies")
    _add_config(p)
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("search", parents=[common],
                       help="query the configured API databases")
    _add_config(p)
    p.add_argument("-o", "--out", metavar="FILE", default=None,
                   help="corpus JSON to write (default "
                        "<output.dir>/corpus_raw.json)")
    p.add_argument("--max-results", type=int, default=None, metavar="N",
                   help="cap per database, overriding the configuration")
    p.add_argument("--dry-run", action="store_true",
                   help="compile and print the query for every database "
                        "without retrieving anything")
    p.add_argument("--keep-going", action="store_true",
                   help="skip sources that fail or lack credentials and "
                        "record the gap in the summary")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("parse", parents=[common],
                       help="import exported files (RIS, BibTeX, CSV, "
                            "nbib, EndNote XML, WoS tagged)")
    p.add_argument("paths", nargs="*", metavar="FILE",
                   help="export files; format and dialect detected by content")
    _add_config(p, required=False)
    p.add_argument("-o", "--out", metavar="FILE", default=None,
                   help="corpus JSON to write")
    p.add_argument("--append", metavar="FILE", default=None,
                   help="add the records to an existing corpus JSON")
    p.add_argument("--database", default="", metavar="NAME",
                   help="database name for the PRISMA-S appendix "
                        "(default: inferred from the detected dialect)")
    p.add_argument("--platform", default="", metavar="NAME",
                   help="platform/vendor, e.g. Clarivate, Ovid, EBSCOhost")
    p.add_argument("--interface", default="", metavar="TEXT",
                   help="how the search was run (default 'web interface "
                        "export')")
    p.add_argument("--query", default="", metavar="TEXT",
                   help="the strategy as run in that interface (PRISMA-S "
                        "Item 8)")
    p.add_argument("--date-run", default="", metavar="YYYY-MM-DD",
                   help="date the search was executed (PRISMA-S Item 13)")
    p.add_argument("--format", default="auto",
                   choices=("auto",) + _FORMAT_LABELS,
                   help="force the format instead of detecting it")
    p.add_argument("--dialect", default="auto", metavar="NAME",
                   help="force the vendor dialect (RIS/BibTeX/CSV)")
    p.add_argument("--encoding", default="auto", metavar="NAME",
                   help="force the input encoding")
    p.set_defaults(func=cmd_parse)

    p = sub.add_parser("dedup", parents=[common],
                       help="deduplicate a corpus with a full decision log")
    p.add_argument("corpus", metavar="CORPUS.json")
    _add_config(p, required=False)
    p.add_argument("-o", "--out", metavar="FILE", default=None,
                   help="unique corpus JSON to write")
    p.add_argument("--report", metavar="FILE", default=None,
                   help="per-decision CSV log (default dedup_report.csv)")
    p.add_argument("--overlap", metavar="FILE", default=None,
                   help="write the cross-source overlap matrix as Markdown")
    p.add_argument("--export-format", action="append", choices=_EXPORT_FORMATS,
                   help="format of the deduplicated export; repeatable "
                        "(default: scopus, i.e. the Scopus CSV layout read "
                        "by bibliometrix, VOSviewer and EmbedSLR)")
    p.add_argument("--no-export", action="store_true",
                   help="write only the corpus JSON and the decision log")
    _add_dedup_options(p)
    p.set_defaults(func=cmd_dedup)

    p = sub.add_parser("prisma", parents=[common],
                       help="PRISMA 2020 flow diagram (SVG) and PRISMA-S "
                            "appendix")
    p.add_argument("corpus", metavar="CORPUS.json")
    _add_config(p, required=False)
    p.add_argument("--svg", metavar="FILE", default=None,
                   help="flow diagram path (default prisma2020_flow.svg)")
    p.add_argument("--appendix", metavar="FILE", default=None,
                   help="PRISMA-S appendix path (.md, or .docx with "
                        "python-docx)")
    p.add_argument("--audit", metavar="FILE", default=None,
                   help="write the principal/supplementary source audit")
    _add_screening_options(p)
    p.set_defaults(func=cmd_prisma)

    p = sub.add_parser("export", parents=[common],
                       help="Scopus CSV / CSV / screening CSV / RIS / BibTeX")
    p.add_argument("corpus", metavar="CORPUS.json")
    _add_config(p, required=False)
    p.add_argument("--format", action="append", choices=_EXPORT_FORMATS,
                   help="export format; repeatable (default: the "
                        '"output.exports" configuration, else Scopus CSV)')
    p.add_argument("--scopus", metavar="FILE", default=None,
                   help="Scopus-format CSV for bibliometrix/VOSviewer/"
                        "EmbedSLR")
    p.add_argument("--csv", metavar="FILE", default=None)
    p.add_argument("--screening", metavar="FILE", default=None,
                   help="screening CSV for ASReview/EmbedSLR")
    p.add_argument("--ris", metavar="FILE", default=None)
    p.add_argument("--bibtex", metavar="FILE", default=None)
    p.add_argument("--columns", metavar="A,B,C", default=None,
                   help="explicit CSV column list")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("quality", parents=[common],
                       help="per-source metadata completeness")
    p.add_argument("corpus", metavar="CORPUS.json")
    _add_config(p, required=False)
    p.add_argument("--csv", metavar="FILE", default=None,
                   help="also write the report as CSV")
    p.add_argument("--json", action="store_true",
                   help="emit JSON on stdout instead of a Markdown table")
    p.set_defaults(func=cmd_quality)

    p = sub.add_parser("tui", parents=[common],
                       help="guided interface: answer questions instead of "
                            "writing a configuration file")
    p.set_defaults(func=cmd_tui)

    p = sub.add_parser("harvest", parents=[common],
                       help="retrieve one database while archiving every "
                            "raw response")
    _add_config(p)
    p.add_argument("--database", required=True, metavar="NAME")
    p.add_argument("--archive", metavar="DIR", default=None,
                   help='archive directory (or "harvest.archive")')
    p.add_argument("--max-results", type=int, default=None, metavar="N")
    p.add_argument("--harvest-id", default="", metavar="ID",
                   help="identifier for this harvest inside the archive")
    p.add_argument("--notes", default="", metavar="TEXT")
    p.add_argument("--manifest", metavar="FILE", default=None,
                   help="write the standalone manifest JSON for a deposit")
    p.add_argument("--markdown", metavar="FILE", default=None,
                   help="write the reproducibility appendix as Markdown")
    p.add_argument("-o", "--out", metavar="FILE", default=None,
                   help="also write the records as a corpus JSON")
    p.set_defaults(func=cmd_harvest)

    p = sub.add_parser("replay", parents=[common],
                       help="re-run an archived harvest offline and verify "
                            "it reproduces exactly")
    _add_config(p)
    p.add_argument("--archive", required=True, metavar="DIR")
    p.add_argument("--database", default="", metavar="NAME",
                   help="which harvest to replay (optional when the archive "
                        "holds exactly one)")
    p.add_argument("--harvest-id", default="", metavar="ID")
    p.add_argument("-o", "--out", metavar="FILE", default=None,
                   help="write the replayed records as a corpus JSON")
    p.add_argument("--compare", metavar="DIR", default=None,
                   help="quantify the drift against a second archive")
    p.add_argument("--drift-markdown", metavar="FILE", default=None,
                   help="write the drift report as Markdown")
    p.add_argument("--no-strict", action="store_true",
                   help="report integrity or checksum divergence as a "
                        "warning instead of failing")
    p.set_defaults(func=cmd_replay)

    p = sub.add_parser("run", parents=[common],
                       help="the whole review from one configuration file")
    _add_config(p)
    p.add_argument("--max-results", type=int, default=None, metavar="N")
    p.add_argument("--dry-run", action="store_true",
                   help="validate, compile every query and write nothing")
    p.add_argument("--keep-going", action="store_true",
                   help="continue when a source fails or lacks credentials")
    p.add_argument("--no-enrich", action="store_true",
                   help="skip abstract recovery even if the configuration "
                        "enables it")
    _add_dedup_options(p)
    _add_screening_options(p)
    p.set_defaults(func=cmd_run)
    return parser


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------
def main(argv: Optional[Sequence[str]] = None, session: Any = None,
         stdout=None, stderr=None) -> int:
    """Run the CLI and return a process exit code.

    Parameters
    ----------
    argv:
        Argument list without the program name; ``None`` reads ``sys.argv``.
    session:
        Optional ``requests``-style session handed to every API client -- the
        seam for an institutional proxy, a custom retry policy, or running the
        whole pipeline against recorded responses with no network at all.
    stdout, stderr:
        Streams for the data product and for progress; default to the real
        ones.  Passing them makes the interface testable in-process, which is
        also how its coverage is measured.
    """
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:                 # argparse already explained why
        return int(exc.code or 0)
    console = _Console(quiet=args.quiet, verbose=args.verbose,
                       stream=stderr, out=stdout)
    args._session = session
    try:
        return int(args.func(args, console))
    except CliError as exc:
        console.stream.write("corpusslr {}: error: {}\n".format(
            args.command, exc))
        return int(getattr(exc, "exit_code", EXIT_USAGE))
    except SourceError as exc:
        console.stream.write("corpusslr {}: error: {}\n".format(
            args.command, exc))
        return EXIT_DATA
    except HarvestError as exc:
        console.stream.write("corpusslr {}: error: {}\n".format(
            args.command, exc))
        return EXIT_DATA
    except FileNotFoundError as exc:
        console.stream.write(
            "corpusslr {}: error: {} not found\n".format(
                args.command, exc.filename or exc))
        return EXIT_USAGE
    except (IsADirectoryError, PermissionError, OSError) as exc:
        console.stream.write("corpusslr {}: error: {}\n".format(
            args.command, exc))
        return EXIT_DATA
    except KeyboardInterrupt:
        console.stream.write("\ncorpusslr: interrupted\n")
        return 130
    except Exception as exc:                                   # noqa: BLE001
        if args.traceback:
            raise
        console.stream.write(
            "corpusslr {}: internal error: {}: {}\n"
            "This is a defect in CorpusSLR {}. Rerun with --traceback and "
            "report it at https://github.com/s-matysik/CorpusSLR/issues\n"
            .format(args.command, type(exc).__name__, exc, __version__))
        return EXIT_INTERNAL


if __name__ == "__main__":                                 # pragma: no cover
    sys.exit(main())
