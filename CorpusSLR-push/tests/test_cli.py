"""Command-line interface: every subcommand, offline.

The CLI is exercised through ``main(argv)`` rather than a subprocess: it runs
in-process (so it is measured by coverage), it is fast, and the fake HTTP
session can be injected through the documented ``session=`` seam, which keeps
the guarantee that no test opens a socket.

What is asserted, beyond "it does not crash":

* exit codes, because shell scripts and CI branch on them (0 success,
  1 user error, 2 data error);
* the error *messages*, because an unexplained failure in a review tool costs
  a reviewer hours -- each check pins the remedy the message must name;
* the separation of stdout (data) from stderr (progress), so redirection works;
* that credentials never reach stdout, stderr or any written artefact;
* the arithmetic identities that tie the stages together -- records identified
  = sum per source, identified - duplicates = unique, and the PRISMA flow
  balance -- since those are the numbers that end up in a manuscript.
"""
import io
import json
import os

import pytest

from conftest import FakeResponse, FakeSession

from corpusslr import __version__
from corpusslr.cli import (CORPUS_FORMAT, DATABASES, EXIT_DATA, EXIT_OK,
                           EXIT_USAGE, ConfigError, DataError,
                           config_checksum, corpus_from_dict, corpus_to_dict,
                           detect_export_format, main, validate_config)


# ----------------------------------------------------------------- harness ---
class Run:
    """Result of one in-process CLI invocation."""

    def __init__(self, code, out, err):
        self.code = code
        self.out = out
        self.err = err

    @property
    def json(self):
        return json.loads(self.out)

    def __repr__(self):                       # pragma: no cover - debugging
        return "<Run code={} out={!r} err={!r}>".format(
            self.code, self.out[:200], self.err[:200])


def cli(*argv, **kw):
    """Invoke the CLI in-process, capturing both streams separately."""
    out, err = io.StringIO(), io.StringIO()
    code = main([str(a) for a in argv], session=kw.get("session"),
                stdout=out, stderr=err)
    return Run(code, out.getvalue(), err.getvalue())


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """No credential may leak in from the developer's own shell."""
    for name in ("SCOPUS_API_KEY", "ELSEVIER_API_KEY", "SCOPUS_INSTTOKEN",
                 "ELSEVIER_INSTTOKEN", "WOS_API_KEY", "CLARIVATE_API_KEY",
                 "SEMANTIC_SCHOLAR_API_KEY", "S2_API_KEY", "NCBI_API_KEY",
                 "PUBMED_API_KEY", "CORPUSSLR_CONTACT_EMAIL",
                 "CONTACT_EMAIL"):
        monkeypatch.delenv(name, raising=False)


# ------------------------------------------------------------- fixture data ---
RIS_EMBASE = """TY  - JOUR
DB  - Embase
TI  - Artificial intelligence adoption in small firms
AU  - Kowalski, Jan
AU  - Nowak, Anna
PY  - 2024
JO  - Journal of Business Research
DO  - 10.1016/j.jbusres.2024.01001
VL  - 170
SP  - 100
EP  - 115
AB  - We study AI adoption among SMEs using a survey of 400 firms.
ER  -

TY  - JOUR
DB  - Embase
TI  - Machine learning acceptance among SME managers
AU  - Smith, John
PY  - 2023
JO  - Technovation
DO  - 10.1016/j.technovation.2023.5555
ER  -
"""

WOS_TAGGED = """FN Clarivate Analytics Web of Science
VR 1.0
PT J
AU Kowalski, J
   Nowak, A
TI Artificial intelligence adoption in small firms
SO JOURNAL OF BUSINESS RESEARCH
DI 10.1016/j.jbusres.2024.01001
PY 2024
VL 170
BP 100
EP 115
DT Article
ER

PT J
AU Brown, Alice
TI Deep learning for demand forecasting in retail
SO EUROPEAN JOURNAL OF OPERATIONAL RESEARCH
DI 10.1016/j.ejor.2022.7777
PY 2022
DT Article
ER

EF
"""

NBIB = """PMID- 40123456
TI  - Machine learning acceptance among SME managers
AB  - A study of managerial acceptance.
FAU - Smith, John
DP  - 2023
TA  - Technovation
PT  - Journal Article
AID - 10.1016/j.technovation.2023.5555 [doi]
"""

BIBTEX = """@article{kowalski2024,
  author = {Kowalski, Jan and Nowak, Anna},
  title = {Artificial intelligence adoption in small firms},
  journal = {Journal of Business Research},
  year = {2024},
  doi = {10.1016/j.jbusres.2024.01001},
  author_keywords = {AI; SME}
}
"""

SCOPUS_CSV = ('Authors,Title,Year,Source title,Volume,Issue,Page start,'
              'Page end,Cited by,DOI,Link,Author Keywords,Index Keywords,'
              'Document Type,EID,Language of Original Document\n'
              '"Kowalski J., Nowak A.",'
              '"Artificial intelligence adoption in small firms",2024,'
              '"Journal of Business Research",170,2,100,115,10,'
              '10.1016/j.jbusres.2024.01001,,"AI; SME","adoption",'
              'Article,2-s2.0-85001,English\n')

ENDNOTE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<xml><records>
<record>
 <ref-type name="Journal Article">17</ref-type>
 <titles><title><style face="normal">Machine learning acceptance among SME
 managers</style></title><secondary-title>Technovation</secondary-title>
 </titles>
 <contributors><authors><author>Smith, John</author></authors></contributors>
 <dates><year>2023</year></dates>
 <electronic-resource-num>10.1016/j.technovation.2023.5555</electronic-resource-num>
</record>
</records></xml>
"""

OPENALEX_PAGE = {"meta": {"count": 2, "next_cursor": None}, "results": [
    {"id": "https://openalex.org/W1",
     "doi": "https://doi.org/10.1016/j.jbusres.2024.01001",
     "display_name": "Artificial intelligence adoption in small firms",
     "publication_year": 2024, "type": "article", "language": "en",
     "primary_location": {"source": {
         "display_name": "Journal of Business Research",
         "issn_l": "0148-2963"}},
     "authorships": [{"author": {"display_name": "Jan Kowalski"}}],
     "abstract_inverted_index": {"AI": [0], "adoption": [1], "study": [2]},
     "cited_by_count": 11, "biblio": {}},
    {"id": "https://openalex.org/W2", "doi": "https://doi.org/10.5001/oa-only",
     "display_name": "An OpenAlex only study of machine learning acceptance",
     "publication_year": 2022, "type": "article", "language": "en",
     "authorships": [{"author": {"display_name": "Ida Unique"}}],
     "biblio": {}}]}

CROSSREF_PAGE = {"status": "ok", "message-version": "1.0.0", "message": {
    "total-results": 1, "message-version": "1.0.0", "items": [
        {"DOI": "10.5001/crossref-only",
         "title": ["A Crossref only paper about artificial intelligence"],
         "type": "journal-article", "container-title": ["Technovation"],
         "issued": {"date-parts": [[2021, 5, 1]]},
         "author": [{"family": "Brown", "given": "Alice"}],
         "language": "en", "is-referenced-by-count": 4,
         "abstract": "<jats:p>An abstract long enough to keep.</jats:p>"}]}}


def api_session():
    """FakeSession answering OpenAlex and Crossref, 404 for anything else."""
    def responder(url, params, headers):
        if "openalex" in url:
            return FakeResponse(payload=OPENALEX_PAGE)
        if "crossref" in url:
            return FakeResponse(payload=CROSSREF_PAGE)
        return FakeResponse(status_code=404, payload={"error": "unexpected"})
    return FakeSession(responder)


def write(path, text):
    with open(str(path), "w", encoding="utf-8") as fh:
        fh.write(text)
    return str(path)


def write_config(tmp_path, **overrides):
    """A minimal valid configuration, overridable per test."""
    cfg = {
        "query": {"blocks": [["artificial intelligence", "machine learning"],
                             ["adoption", "acceptance"]],
                  "years": [2015, 2026],
                  "doc_types": ["article", "review"],
                  "languages": ["en"]},
        "databases": ["openalex", {"name": "crossref", "max_results": 300}],
        "output": {"dir": str(tmp_path / "out")},
    }
    cfg.update(overrides)
    path = tmp_path / "review.json"
    write(path, json.dumps(cfg))
    return str(path)


# ============================================================== plumbing ====
def test_version_and_help_exit_zero():
    assert cli("--version").code == EXIT_OK
    assert cli("--help").code == EXIT_OK
    assert cli("run", "--help").code == EXIT_OK


def test_no_subcommand_is_a_usage_error():
    assert cli().code == 2                      # argparse's own usage code


def test_unknown_subcommand_is_a_usage_error():
    assert cli("nosuchcommand").code == 2


# ========================================================== configuration ====
def test_missing_config_file_names_the_remedy(tmp_path):
    r = cli("check", "-c", str(tmp_path / "absent.json"))
    assert r.code == EXIT_USAGE
    assert "does not exist" in r.err
    assert "examples/review_config.json" in r.err


def test_invalid_json_explains_the_usual_causes(tmp_path):
    path = write(tmp_path / "bad.json", '{"query": {"blocks": [["ai"]],},}')
    r = cli("check", "-c", path)
    assert r.code == EXIT_USAGE
    assert "not valid JSON" in r.err
    assert "trailing comma" in r.err


def test_config_must_be_an_object(tmp_path):
    path = write(tmp_path / "list.json", '[1, 2, 3]')
    r = cli("check", "-c", path)
    assert r.code == EXIT_USAGE
    assert "must be an object" in r.err


def test_missing_query_section_shows_an_example(tmp_path):
    path = write(tmp_path / "c.json", json.dumps({"databases": ["openalex"]}))
    r = cli("check", "-c", path)
    assert r.code == EXIT_USAGE
    assert '"query"' in r.err and "blocks" in r.err


def test_empty_blocks_are_rejected(tmp_path):
    path = write(tmp_path / "c.json",
                 json.dumps({"query": {"blocks": []},
                             "databases": ["openalex"]}))
    r = cli("check", "-c", path)
    assert r.code == EXIT_USAGE
    assert "empty" in r.err and "At least one block" in r.err


def test_block_with_only_empty_terms_is_rejected(tmp_path):
    path = write(tmp_path / "c.json",
                 json.dumps({"query": {"blocks": [["ai"], ["  ", ""]]},
                             "databases": ["openalex"]}))
    r = cli("check", "-c", path)
    assert r.code == EXIT_USAGE
    assert "no non-empty term" in r.err


def test_unknown_database_lists_the_available_ones(tmp_path):
    path = write(tmp_path / "c.json",
                 json.dumps({"query": {"blocks": [["ai"]]},
                             "databases": ["embase"]}))
    r = cli("check", "-c", path)
    assert r.code == EXIT_USAGE
    for alias in ("scopus", "openalex", "pubmed", "crossref", "wos"):
        assert alias in r.err
    # Embase has no open API: the message must point at the file-export route
    # rather than leaving the reviewer thinking the database is unsupported.
    assert "file export" in r.err


def test_database_aliases_are_accepted(tmp_path):
    path = write(tmp_path / "c.json",
                 json.dumps({"query": {"blocks": [["ai"]]},
                             "databases": ["Web of Science", "MEDLINE",
                                           "Semantic Scholar"]}))
    r = cli("check", "-c", path)
    assert r.code == EXIT_OK
    labels = [d["database"] for d in r.json["databases"]]
    assert labels == ["Web of Science Core Collection", "PubMed/MEDLINE",
                      "Semantic Scholar"]


def test_database_listed_twice_is_rejected_with_the_reason(tmp_path):
    path = write(tmp_path / "c.json",
                 json.dumps({"query": {"blocks": [["ai"]]},
                             "databases": ["openalex", "OpenAlex"]}))
    r = cli("check", "-c", path)
    assert r.code == EXIT_USAGE
    assert "twice" in r.err and "double-count" in r.err


def test_misspelled_dedup_key_is_rejected_not_ignored(tmp_path):
    path = write(tmp_path / "c.json",
                 json.dumps({"query": {"blocks": [["ai"]]},
                             "databases": ["openalex"],
                             "dedup": {"fuzy_threshold": 0.9}}))
    r = cli("check", "-c", path)
    assert r.code == EXIT_USAGE
    assert "fuzy_threshold" in r.err
    assert "fuzzy_threshold" in r.err            # the allowed-key list


def test_contradictory_dedup_thresholds_are_explained(tmp_path):
    path = write(tmp_path / "c.json",
                 json.dumps({"query": {"blocks": [["ai"]]},
                             "databases": ["openalex"],
                             "dedup": {"fuzzy_threshold": 0.5,
                                       "id_title_min": 0.9}}))
    r = cli("check", "-c", path)
    assert r.code == EXIT_USAGE
    assert "id_title_min" in r.err and "cascade" in r.err


def test_similarity_outside_the_unit_interval_is_rejected(tmp_path):
    path = write(tmp_path / "c.json",
                 json.dumps({"query": {"blocks": [["ai"]]},
                             "databases": ["openalex"],
                             "dedup": {"fuzzy_threshold": 93}}))
    r = cli("check", "-c", path)
    assert r.code == EXIT_USAGE
    assert "similarity ratio" in r.err and "0.93" in r.err


def test_reversed_year_range_is_rejected_with_the_fix(tmp_path):
    path = write(tmp_path / "c.json",
                 json.dumps({"query": {"blocks": [["ai"]],
                                       "years": [2026, 2015]},
                             "databases": ["openalex"]}))
    r = cli("check", "-c", path)
    assert r.code == EXIT_USAGE
    assert "[2015, 2026]" in r.err


def test_malformed_year_range_is_rejected(tmp_path):
    path = write(tmp_path / "c.json",
                 json.dumps({"query": {"blocks": [["ai"]], "years": 2015},
                             "databases": ["openalex"]}))
    assert cli("check", "-c", path).code == EXIT_USAGE


def test_implausible_years_are_rejected(tmp_path):
    path = write(tmp_path / "c.json",
                 json.dumps({"query": {"blocks": [["ai"]],
                                       "years": [1200, 2500]},
                             "databases": ["openalex"]}))
    r = cli("check", "-c", path)
    assert r.code == EXIT_USAGE
    assert "1500-2100" in r.err


def test_negative_screening_count_is_rejected(tmp_path):
    path = write_config(tmp_path, screening={"records_excluded": -5})
    r = cli("check", "-c", path)
    assert r.code == EXIT_USAGE
    assert "non-negative" in r.err


def test_unknown_export_format_lists_the_available_ones(tmp_path):
    path = write_config(tmp_path, output={"exports": ["xlsx"]})
    r = cli("check", "-c", path)
    assert r.code == EXIT_USAGE
    assert "xlsx" in r.err and "bibtex" in r.err


def test_nothing_to_retrieve_is_rejected(tmp_path):
    path = write(tmp_path / "c.json",
                 json.dumps({"query": {"blocks": [["ai"]]},
                             "databases": [], "files": []}))
    r = cli("check", "-c", path)
    assert r.code == EXIT_USAGE
    assert "nothing to retrieve" in r.err


@pytest.mark.parametrize("key", ["api_key", "insttoken", "mailto", "password"])
def test_credentials_in_the_config_are_refused(tmp_path, key):
    """A configuration file is meant to be deposited; it must stay clean."""
    path = write(tmp_path / "c.json",
                 json.dumps({"query": {"blocks": [["ai"]]},
                             "databases": ["openalex"], key: "secret-value"}))
    r = cli("check", "-c", path)
    assert r.code == EXIT_USAGE
    assert "environment variables only" in r.err
    assert "secret-value" not in r.err          # never echo the value


def test_yaml_without_pyyaml_says_so(tmp_path, monkeypatch):
    path = write(tmp_path / "c.yaml", "query:\n  blocks: [[ai]]\n")
    import builtins
    real_import = builtins.__import__

    def no_yaml(name, *a, **kw):
        if name == "yaml":
            raise ImportError("no yaml")
        return real_import(name, *a, **kw)
    monkeypatch.setattr(builtins, "__import__", no_yaml)
    r = cli("check", "-c", path)
    assert r.code == EXIT_USAGE
    assert "PyYAML" in r.err and "JSON" in r.err


def test_config_checksum_is_stable_and_ignores_key_order():
    a = {"query": {"blocks": [["ai"]]}, "databases": ["openalex"]}
    b = {"databases": ["openalex"], "query": {"blocks": [["ai"]]}}
    assert config_checksum(a) == config_checksum(b)
    assert config_checksum(a) != config_checksum(
        {"query": {"blocks": [["ml"]]}, "databases": ["openalex"]})
    # Internal bookkeeping must not change the identity of the strategy.
    c = dict(a)
    c["_path"] = "/somewhere/else.json"
    assert config_checksum(c) == config_checksum(a)


def test_validate_config_is_usable_as_a_library_function():
    cfg = validate_config({"query": {"blocks": [["ai"]]},
                           "databases": ["openalex"]})
    assert cfg["databases"] == [{"name": "openalex"}]
    with pytest.raises(ConfigError):
        validate_config({"query": {"blocks": [["ai"]]}, "databases": ["nope"]})


# ================================================================= check ====
def test_check_reports_the_plan_on_stdout(tmp_path):
    r = cli("check", "-c", write_config(tmp_path))
    assert r.code == EXIT_OK
    plan = r.json
    assert plan["valid"] is True
    assert [d["database"] for d in plan["databases"]] == ["OpenAlex",
                                                          "Crossref"]
    # The compiled query is the substance of PRISMA-S Item 8.
    assert "artificial intelligence" in plan["databases"][0]["query"]
    assert plan["config"]["corpusslr_version"] == __version__
    assert len(plan["config"]["config_sha256"]) == 64
    # Progress belongs on stderr, never in the data product.
    assert "is valid" in r.err


def test_check_warns_about_a_missing_credential(tmp_path):
    path = write_config(tmp_path, databases=["scopus", "openalex"])
    r = cli("check", "-c", path)
    assert r.code == EXIT_OK                     # a warning is not a failure
    assert any("SCOPUS_API_KEY" in w for w in r.json["warnings"])
    scopus = [d for d in r.json["databases"] if d["database"] == "Scopus"][0]
    assert scopus["credential_present"] is False
    assert scopus["requires_credential"] is True


def test_check_reports_credential_presence_without_the_value(tmp_path,
                                                             monkeypatch):
    monkeypatch.setenv("SCOPUS_API_KEY", "SUPER-SECRET-KEY")
    path = write_config(tmp_path, databases=["scopus"])
    r = cli("check", "-c", path)
    assert r.code == EXIT_OK
    scopus = r.json["databases"][0]
    assert scopus["credential_present"] is True
    assert "SUPER-SECRET-KEY" not in r.out
    assert "SUPER-SECRET-KEY" not in r.err


def test_check_warns_when_no_principal_source_is_configured(tmp_path):
    r = cli("check", "-c", write_config(tmp_path))
    assert any("principal" in w for w in r.json["warnings"])


def test_check_detects_a_configured_export_file(tmp_path):
    ris = write(tmp_path / "e.ris", RIS_EMBASE)
    path = write_config(tmp_path, databases=[],
                        files=[{"path": ris, "database": "Embase"}])
    r = cli("check", "-c", path)
    assert r.code == EXIT_OK
    assert r.json["files"][0]["format"] == "ris"
    assert r.json["files"][0]["exists"] is True


def test_check_warns_about_a_missing_export_file(tmp_path):
    path = write_config(tmp_path, databases=[],
                        files=[{"path": str(tmp_path / "gone.ris")}])
    r = cli("check", "-c", path)
    assert r.code == EXIT_OK
    assert any("does not exist" in w for w in r.json["warnings"])


# ================================================================ search ====
def test_search_dry_run_compiles_every_query_and_fetches_nothing(tmp_path):
    session = api_session()
    r = cli("search", "-c", write_config(tmp_path), "--dry-run",
            session=session)
    assert r.code == EXIT_OK
    assert session.calls == []                   # the point of a dry run
    payload = r.json
    assert payload["dry_run"] is True
    labels = [d["database"] for d in payload["databases"]]
    assert labels == ["OpenAlex", "Crossref"]
    # Each backend gets its own native syntax, and Crossref's inability to
    # express boolean logic is surfaced rather than hidden.
    assert "OR" in payload["databases"][0]["query"]
    assert any("boolean" in w for w in payload["query_warnings"])
    assert not os.path.exists(str(tmp_path / "out" / "corpus_raw.json"))


def test_search_dry_run_needs_no_credentials(tmp_path):
    path = write_config(tmp_path, databases=["scopus", "wos"])
    r = cli("search", "-c", path, "--dry-run")
    assert r.code == EXIT_OK
    assert all(d["credential_present"] is False for d in r.json["databases"])


def test_search_writes_a_corpus_with_its_provenance(tmp_path):
    out = str(tmp_path / "corpus.json")
    r = cli("search", "-c", write_config(tmp_path), "-o", out,
            session=api_session())
    assert r.code == EXIT_OK
    assert r.json["identified"] == 3
    assert r.json["identified_by_source"] == {"OpenAlex": 2, "Crossref": 1}
    with open(out, encoding="utf-8") as fh:
        payload = json.load(fh)
    assert payload["format"] == CORPUS_FORMAT
    assert payload["corpusslr_version"] == __version__
    assert len(payload["records"]) == 3
    # PRISMA-S needs the per-search event, not just the records.
    assert {s["database"] for s in payload["searches"]} == {"OpenAlex",
                                                            "Crossref"}
    assert all(s["query"] for s in payload["searches"])
    assert all(s["date_run"] for s in payload["searches"])


def test_search_data_goes_to_stdout_progress_to_stderr(tmp_path):
    r = cli("search", "-c", write_config(tmp_path), session=api_session())
    assert r.code == EXIT_OK
    json.loads(r.out)                            # stdout is valid JSON alone
    assert "searching OpenAlex" in r.err


def test_search_quiet_silences_progress_but_not_warnings(tmp_path,
                                                         monkeypatch):
    """``-q`` hides progress; a diagnostic that changes the numbers survives."""
    monkeypatch.setenv("CORPUSSLR_CONTACT_EMAIL", "reviewer@example.org")
    r = cli("search", "-c", write_config(tmp_path), "-q",
            session=api_session())
    assert r.code == EXIT_OK
    assert r.err == ""
    assert r.json["identified"] == 3
    # Without a contact address the warning is still emitted under -q.
    monkeypatch.delenv("CORPUSSLR_CONTACT_EMAIL")
    noisy = cli("search", "-c", write_config(tmp_path), "-q",
                session=api_session())
    assert noisy.code == EXIT_OK
    assert "warning:" in noisy.err
    assert "searching" not in noisy.err


def test_search_max_results_overrides_the_config(tmp_path):
    r = cli("search", "-c", write_config(tmp_path), "--dry-run",
            "--max-results", "7")
    assert all(d["max_results"] == 7 for d in r.json["databases"])


def test_search_without_a_credential_fails_with_a_remedy(tmp_path):
    path = write_config(tmp_path, databases=["scopus"])
    r = cli("search", "-c", path, session=api_session())
    assert r.code == EXIT_USAGE
    assert "SCOPUS_API_KEY" in r.err
    assert "SCOPUS_INSTTOKEN" in r.err           # the off-campus cause
    assert "Traceback" not in r.err


def test_search_keep_going_records_the_gap(tmp_path):
    path = write_config(tmp_path, databases=["scopus", "openalex"])
    r = cli("search", "-c", path, "--keep-going", session=api_session())
    assert r.code == EXIT_OK
    assert r.json["identified"] == 2
    assert r.json["failures"][0]["database"] == "Scopus"
    assert r.json["failures"][0]["reason"] == "missing credential"


def test_search_reports_an_api_failure_as_a_data_error(tmp_path):
    session = FakeSession(lambda u, p, h: FakeResponse(
        status_code=500, payload={"error": "upstream"}))
    path = write_config(tmp_path, databases=["openalex"])
    r = cli("search", "-c", path, session=session)
    assert r.code == EXIT_DATA
    assert "Traceback" not in r.err


def test_search_with_only_file_sources_is_a_usage_error(tmp_path):
    ris = write(tmp_path / "e.ris", RIS_EMBASE)
    path = write_config(tmp_path, databases=[], files=[{"path": ris}])
    r = cli("search", "-c", path)
    assert r.code == EXIT_USAGE
    assert "corpusslr parse" in r.err


# ================================================================= parse ====
@pytest.mark.parametrize("name,text,fmt,expect_db", [
    ("embase.ris", RIS_EMBASE, "ris", "Embase"),
    ("wos.txt", WOS_TAGGED, "wos", "Web of Science Core Collection"),
    ("pubmed.nbib", NBIB, "nbib", "PubMed/MEDLINE"),
    ("scopus.bib", BIBTEX, "bibtex", "Scopus"),
    ("scopus.csv", SCOPUS_CSV, "csv", "Scopus"),
    ("library.xml", ENDNOTE_XML, "endnote", None),
])
def test_parse_detects_format_by_content(tmp_path, name, text, fmt, expect_db):
    path = write(tmp_path / name, text)
    r = cli("parse", path, "-o", str(tmp_path / "c.json"))
    assert r.code == EXIT_OK, r.err
    entry = r.json["files"][0]
    assert entry["format"] == fmt
    assert entry["n_records"] >= 1
    if expect_db:
        assert entry["database"] == expect_db


def test_parse_ignores_a_misleading_extension(tmp_path):
    """Extensions are unreliable; a RIS file named .txt must still parse."""
    path = write(tmp_path / "definitely_not_ris.txt", RIS_EMBASE)
    r = cli("parse", path, "-o", str(tmp_path / "c.json"))
    assert r.code == EXIT_OK
    assert r.json["files"][0]["format"] == "ris"
    assert r.json["files"][0]["dialect"] == "embase"


def test_detect_export_format_covers_every_family():
    assert detect_export_format(RIS_EMBASE) == "ris"
    assert detect_export_format(WOS_TAGGED) == "wos"
    assert detect_export_format(NBIB) == "nbib"
    assert detect_export_format(BIBTEX) == "bibtex"
    assert detect_export_format(SCOPUS_CSV) == "csv"
    assert detect_export_format(ENDNOTE_XML) == "endnote"
    assert detect_export_format("") == ""
    assert detect_export_format("prose with no structure at all") == ""


def test_parse_records_the_dialect_for_the_appendix(tmp_path):
    path = write(tmp_path / "e.ris", RIS_EMBASE)
    r = cli("parse", path, "-o", str(tmp_path / "c.json"))
    assert r.json["files"][0]["dialect"] == "embase"


def test_parse_reconciles_the_record_count(tmp_path):
    """n_input must equal n_records + n_rejected: PRISMA counts depend on it."""
    path = write(tmp_path / "e.ris", RIS_EMBASE)
    r = cli("parse", path, "-o", str(tmp_path / "c.json"))
    entry = r.json["files"][0]
    assert entry["n_input"] == entry["n_records"] + entry["n_rejected"]


def test_parse_unrecognisable_file_is_a_data_error(tmp_path):
    path = write(tmp_path / "junk.dat", "prose with no structure whatsoever\n")
    r = cli("parse", path, "-o", str(tmp_path / "c.json"))
    assert r.code == EXIT_DATA
    assert "cannot identify the export format" in r.err
    assert "--format" in r.err                   # the override


def test_parse_empty_file_is_a_data_error(tmp_path):
    path = write(tmp_path / "empty.ris", "   \n")
    r = cli("parse", path, "-o", str(tmp_path / "c.json"))
    assert r.code == EXIT_DATA
    assert "empty" in r.err


def test_parse_missing_file_is_a_usage_error(tmp_path):
    r = cli("parse", str(tmp_path / "absent.ris"))
    assert r.code == EXIT_USAGE
    assert "does not exist" in r.err


def test_parse_forced_format_that_contradicts_the_content_is_reported(tmp_path):
    """The tagged parsers overlap, so a wrong --format must not pass silently.

    Feeding a RIS file to the MEDLINE reader does return records -- it reads
    the ``TI  - `` lines -- but the DOIs are gone, and a corpus without DOIs
    deduplicates on titles alone. The mismatch is therefore surfaced.
    """
    path = write(tmp_path / "e.ris", RIS_EMBASE)
    r = cli("parse", path, "--format", "nbib", "-o", str(tmp_path / "c.json"))
    assert r.code == EXIT_OK
    entry = r.json["files"][0]
    assert entry["format"] == "nbib"
    assert entry["detected_format"] == "ris"
    assert entry["format_forced"] is True
    assert any("contradicts" in w for w in entry["warnings"])
    assert "contradicts" in r.err


def test_parse_forced_format_on_an_unparseable_file_is_a_data_error(tmp_path):
    path = write(tmp_path / "junk.dat", "prose with no structure whatsoever\n")
    r = cli("parse", path, "--format", "bibtex",
            "-o", str(tmp_path / "c.json"))
    assert r.code == EXIT_DATA
    assert "no records" in r.err


def test_parse_without_inputs_is_a_usage_error():
    r = cli("parse")
    assert r.code == EXIT_USAGE
    assert "no input files" in r.err


def test_parse_carries_the_prisma_s_metadata(tmp_path):
    path = write(tmp_path / "e.ris", RIS_EMBASE)
    out = str(tmp_path / "c.json")
    r = cli("parse", path, "-o", out, "--database", "Embase",
            "--platform", "Elsevier", "--interface", "Ovid",
            "--query", "TS=(ai AND adoption)", "--date-run", "2026-08-10")
    assert r.code == EXIT_OK
    with open(out, encoding="utf-8") as fh:
        event = json.load(fh)["searches"][0]
    assert event["database"] == "Embase"
    assert event["platform"] == "Elsevier"
    assert event["interface"] == "Ovid"
    assert event["query"] == "TS=(ai AND adoption)"
    assert event["date_run"] == "2026-08-10"


def test_parse_appends_and_keeps_record_ids_unique(tmp_path):
    ris = write(tmp_path / "e.ris", RIS_EMBASE)
    wos = write(tmp_path / "w.txt", WOS_TAGGED)
    out = str(tmp_path / "c.json")
    assert cli("parse", ris, "-o", out).code == EXIT_OK
    r = cli("parse", wos, "--append", out)
    assert r.code == EXIT_OK
    assert r.json["identified"] == 4
    with open(out, encoding="utf-8") as fh:
        payload = json.load(fh)
    uids = [rec["uid"] for rec in payload["records"]]
    assert len(uids) == len(set(uids)) == 4
    assert [s["search_id"] for s in payload["searches"]] == ["S1", "S2"]


def test_parse_multiple_files_in_one_call(tmp_path):
    ris = write(tmp_path / "e.ris", RIS_EMBASE)
    nbib = write(tmp_path / "p.nbib", NBIB)
    r = cli("parse", ris, nbib, "-o", str(tmp_path / "c.json"))
    assert r.code == EXIT_OK
    assert len(r.json["files"]) == 2
    assert r.json["identified"] == 3


def test_parse_uses_the_config_files_section(tmp_path):
    ris = write(tmp_path / "e.ris", RIS_EMBASE)
    path = write_config(tmp_path, databases=[],
                        files=[{"path": ris, "database": "Embase",
                                "date_run": "2026-08-10"}])
    r = cli("parse", "-c", path, "-o", str(tmp_path / "c.json"))
    assert r.code == EXIT_OK
    assert r.json["identified_by_source"] == {"Embase": 2}


# ================================================================= dedup ====
def _parsed_corpus(tmp_path):
    """Embase + WoS sharing one DOI: 4 records, 1 true duplicate."""
    ris = write(tmp_path / "e.ris", RIS_EMBASE)
    wos = write(tmp_path / "w.txt", WOS_TAGGED)
    out = str(tmp_path / "raw.json")
    assert cli("parse", ris, "-o", out, "--database", "Embase").code == EXIT_OK
    assert cli("parse", wos, "--append", out, "--database",
               "Web of Science Core Collection").code == EXIT_OK
    return out


def test_dedup_removes_the_shared_doi_and_logs_the_decision(tmp_path):
    raw = _parsed_corpus(tmp_path)
    out = str(tmp_path / "unique.json")
    report = str(tmp_path / "report.csv")
    r = cli("dedup", raw, "-o", out, "--report", report)
    assert r.code == EXIT_OK
    assert r.json["before"] == 4
    assert r.json["after"] == 3
    assert r.json["removed"] == 1
    assert r.json["by_method"] == {"doi": 1}
    # before - removed == after: the identity the PRISMA diagram relies on.
    assert r.json["before"] - r.json["removed"] == r.json["after"]
    import csv
    with open(report, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1
    assert rows[0]["method"] == "doi"
    assert rows[0]["kept_uid"] and rows[0]["removed_uid"]


def test_dedup_result_carries_the_report_into_the_corpus_file(tmp_path):
    raw = _parsed_corpus(tmp_path)
    out = str(tmp_path / "unique.json")
    cli("dedup", raw, "-o", out, "-C", str(tmp_path))
    with open(out, encoding="utf-8") as fh:
        payload = json.load(fh)
    assert payload["dedup"]["removed"] == 1
    assert payload["dedup"]["by_method"] == {"doi": 1}
    # The search events must survive, or the flow diagram loses its per-source
    # "records identified" counts.
    assert len(payload["searches"]) == 2


def test_dedup_parameters_are_reported_and_honoured(tmp_path):
    raw = _parsed_corpus(tmp_path)
    r = cli("dedup", raw, "-o", str(tmp_path / "u.json"), "-C", str(tmp_path),
            "--fuzzy-threshold", "0.99", "--year-tolerance", "0")
    assert r.code == EXIT_OK
    assert r.json["parameters"]["fuzzy_threshold"] == 0.99
    assert r.json["parameters"]["year_tolerance"] == 0


def test_dedup_config_parameters_are_applied(tmp_path):
    raw = _parsed_corpus(tmp_path)
    cfg = write_config(tmp_path, dedup={"fuzzy_threshold": 0.88,
                                        "year_tolerance": 2})
    r = cli("dedup", raw, "-c", cfg, "-o", str(tmp_path / "u.json"),
            "-C", str(tmp_path))
    assert r.json["parameters"]["fuzzy_threshold"] == 0.88
    assert r.json["parameters"]["year_tolerance"] == 2


def test_dedup_writes_the_overlap_matrix(tmp_path):
    raw = _parsed_corpus(tmp_path)
    overlap = str(tmp_path / "overlap.md")
    r = cli("dedup", raw, "-o", str(tmp_path / "u.json"), "-C", str(tmp_path),
            "--overlap", overlap)
    assert r.code == EXIT_OK
    with open(overlap, encoding="utf-8") as fh:
        text = fh.read()
    assert "Embase" in text and "Web of Science" in text


def test_dedup_writes_the_scopus_csv_by_default(tmp_path):
    """The canonical hand-off: dedup alone produces a bibliometrix input."""
    raw = _parsed_corpus(tmp_path)
    out_dir = tmp_path / "o"
    r = cli("dedup", raw, "-o", str(tmp_path / "u.json"), "-C", str(out_dir))
    assert r.code == EXIT_OK
    assert r.json["exports"] == {"scopus": str(out_dir / "corpus_scopus.csv")}
    import csv
    from corpusslr import SCOPUS_COLUMNS, detect_csv_dialect
    with open(str(out_dir / "corpus_scopus.csv"), encoding="utf-8",
              newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == list(SCOPUS_COLUMNS)
    assert detect_csv_dialect(rows[0]) == "scopus"
    # one row per unique record, and the count agrees with the dedup report
    assert len(rows) - 1 == r.json["after"] == 3


def test_dedup_export_format_can_be_overridden(tmp_path):
    raw = _parsed_corpus(tmp_path)
    out_dir = tmp_path / "o"
    r = cli("dedup", raw, "-o", str(tmp_path / "u.json"), "-C", str(out_dir),
            "--export-format", "ris", "--export-format", "bibtex")
    assert r.code == EXIT_OK
    assert set(r.json["exports"]) == {"ris", "bibtex"}
    assert not os.path.exists(str(out_dir / "corpus_scopus.csv"))


def test_dedup_export_can_be_suppressed(tmp_path):
    raw = _parsed_corpus(tmp_path)
    out_dir = tmp_path / "o"
    r = cli("dedup", raw, "-o", str(tmp_path / "u.json"), "-C", str(out_dir),
            "--no-export")
    assert r.code == EXIT_OK
    assert "exports" not in r.json
    assert not os.path.exists(str(out_dir / "corpus_scopus.csv"))


def test_dedup_missing_corpus_is_a_usage_error(tmp_path):
    r = cli("dedup", str(tmp_path / "absent.json"))
    assert r.code == EXIT_USAGE
    assert "corpusslr search" in r.err


def test_dedup_of_a_non_corpus_json_is_a_data_error(tmp_path):
    path = write(tmp_path / "other.json", json.dumps({"format": "something/1"}))
    r = cli("dedup", path)
    assert r.code == EXIT_DATA
    assert "not a CorpusSLR corpus" in r.err


def test_dedup_of_broken_json_is_a_data_error(tmp_path):
    path = write(tmp_path / "broken.json", "{not json")
    r = cli("dedup", path)
    assert r.code == EXIT_DATA


def test_dedup_of_an_empty_corpus_is_a_data_error(tmp_path):
    path = write(tmp_path / "empty.json",
                 json.dumps({"format": CORPUS_FORMAT, "searches": [],
                             "records": []}))
    r = cli("dedup", path)
    assert r.code == EXIT_DATA
    assert "no records" in r.err


# ================================================================ prisma ====
def _unique_corpus(tmp_path):
    raw = _parsed_corpus(tmp_path)
    out = str(tmp_path / "unique.json")
    assert cli("dedup", raw, "-o", out, "-C", str(tmp_path),
               "-q").code == EXIT_OK
    return out


def test_prisma_writes_the_diagram_and_the_appendix(tmp_path):
    unique = _unique_corpus(tmp_path)
    svg = str(tmp_path / "flow.svg")
    appendix = str(tmp_path / "appendix.md")
    r = cli("prisma", unique, "--svg", svg, "--appendix", appendix,
            "--records-excluded", "1", "--studies-included", "2")
    assert r.code == EXIT_OK
    with open(svg, encoding="utf-8") as fh:
        svg_text = fh.read()
    assert svg_text.startswith("<?xml") or svg_text.lstrip().startswith("<svg")
    assert "Records identified" in svg_text or "identified" in svg_text.lower()
    with open(appendix, encoding="utf-8") as fh:
        md = fh.read()
    assert "PRISMA-S" in md
    assert "Embase" in md and "Web of Science" in md
    # The as-run strategy and the dedup account are what reviewers ask for.
    assert "Deduplication" in md
    # The flow summary goes to stdout so it can be pasted into a manuscript.
    assert "Records identified from databases (n = 4)" in r.out


def test_prisma_flow_arithmetic_is_enforced(tmp_path):
    """An impossible diagram must fail loudly: it would misreport the review."""
    unique = _unique_corpus(tmp_path)
    r = cli("prisma", unique, "--svg", str(tmp_path / "f.svg"),
            "--appendix", str(tmp_path / "a.md"),
            "--records-excluded", "1", "--studies-included", "99")
    assert r.code == EXIT_DATA
    assert "does not balance" in r.err


def test_prisma_no_strict_downgrades_the_imbalance_to_a_warning(tmp_path):
    unique = _unique_corpus(tmp_path)
    r = cli("prisma", unique, "--svg", str(tmp_path / "f.svg"),
            "--appendix", str(tmp_path / "a.md"), "--no-strict",
            "--records-excluded", "1", "--studies-included", "99")
    assert r.code == EXIT_OK
    assert "does not balance" in r.err
    assert os.path.exists(str(tmp_path / "f.svg"))


def test_prisma_without_screening_counts_warns_and_still_documents(tmp_path):
    unique = _unique_corpus(tmp_path)
    r = cli("prisma", unique, "--svg", str(tmp_path / "f.svg"),
            "--appendix", str(tmp_path / "a.md"))
    assert r.code == EXIT_OK
    assert "no screening counts" in r.err
    assert "Records identified from databases (n = 4)" in r.out


def test_prisma_full_text_exclusions_from_the_command_line(tmp_path):
    unique = _unique_corpus(tmp_path)
    r = cli("prisma", unique, "--svg", str(tmp_path / "f.svg"),
            "--appendix", str(tmp_path / "a.md"),
            "--records-excluded", "1",
            "--exclude", "wrong population=1", "--studies-included", "1")
    assert r.code == EXIT_OK
    assert "wrong population" in r.out


def test_prisma_malformed_exclude_is_a_usage_error(tmp_path):
    unique = _unique_corpus(tmp_path)
    r = cli("prisma", unique, "--exclude", "wrong population")
    assert r.code == EXIT_USAGE
    assert "reason=count" in r.err
    r = cli("prisma", unique, "--exclude", "reason=many")
    assert r.code == EXIT_USAGE
    assert "not an integer" in r.err


def test_prisma_screening_counts_come_from_the_config(tmp_path):
    unique = _unique_corpus(tmp_path)
    cfg = write_config(tmp_path,
                       screening={"records_excluded": 1,
                                  "studies_included": 2})
    r = cli("prisma", unique, "-c", cfg, "-C", str(tmp_path / "o"))
    assert r.code == EXIT_OK
    assert "Studies included in review (n = 2)" in r.out


def test_prisma_writes_the_source_tier_audit(tmp_path):
    unique = _unique_corpus(tmp_path)
    audit = str(tmp_path / "audit.md")
    r = cli("prisma", unique, "--audit", audit, "--svg",
            str(tmp_path / "f.svg"), "--appendix", str(tmp_path / "a.md"),
            "--records-excluded", "1", "--studies-included", "2")
    assert r.code == EXIT_OK
    with open(audit, encoding="utf-8") as fh:
        text = fh.read().lower()
    assert "principal" in text


def test_prisma_needs_search_events(tmp_path):
    path = write(tmp_path / "flat.json",
                 json.dumps({"format": CORPUS_FORMAT, "searches": [],
                             "records": [{"title": "T", "uid": "R000001"}]}))
    r = cli("prisma", path)
    assert r.code == EXIT_DATA
    assert "no search events" in r.err


# ================================================================ export ====
def test_export_writes_every_requested_format(tmp_path):
    unique = _unique_corpus(tmp_path)
    r = cli("export", unique,
            "--csv", str(tmp_path / "c.csv"),
            "--screening", str(tmp_path / "s.csv"),
            "--ris", str(tmp_path / "c.ris"),
            "--bibtex", str(tmp_path / "c.bib"))
    assert r.code == EXIT_OK
    for name in ("c.csv", "s.csv", "c.ris", "c.bib"):
        assert os.path.getsize(str(tmp_path / name)) > 0
    assert set(r.json["written"]) == {"csv", "screening", "ris", "bibtex"}


def test_export_screening_csv_has_the_asreview_columns(tmp_path):
    unique = _unique_corpus(tmp_path)
    path = str(tmp_path / "s.csv")
    cli("export", unique, "--screening", path)
    import csv
    with open(path, encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        rows = list(reader)
    assert header == ["record_id", "title", "abstract", "authors", "year",
                      "doi"]
    assert len(rows) == 3


def test_export_scopus_flag_writes_a_parseable_scopus_csv(tmp_path):
    unique = _unique_corpus(tmp_path)
    path = str(tmp_path / "s_scopus.csv")
    r = cli("export", unique, "--scopus", path)
    assert r.code == EXIT_OK
    assert r.json["written"] == {"scopus": path}
    from corpusslr import parse_csv_export
    with open(path, encoding="utf-8") as fh:
        back = parse_csv_export(fh.read())
    assert len(back) == 3
    assert all(r.title for r in back)


def test_export_without_a_config_includes_the_scopus_csv(tmp_path):
    """No config, no flags: the canonical format is among the defaults."""
    unique = _unique_corpus(tmp_path)
    r = cli("export", unique, "-C", str(tmp_path / "d"))
    assert r.code == EXIT_OK
    assert "scopus" in r.json["written"]
    assert os.path.exists(str(tmp_path / "d" / "corpus_scopus.csv"))
    # and it is written FIRST: the console log must show the canonical
    # hand-off before every auxiliary format, not merely before one of them
    log = r.err + r.out
    order = [(log.index(name), name) for name in
             ("corpus_scopus.csv", "corpus.csv", "screening.csv")]
    assert [name for _, name in sorted(order)][0] == "corpus_scopus.csv"
    assert sorted(order) == order


def test_export_scopus_is_an_accepted_config_format(tmp_path):
    unique = _unique_corpus(tmp_path)
    cfg = write_config(tmp_path, output={"dir": str(tmp_path / "out2"),
                                         "exports": ["scopus"]})
    r = cli("export", unique, "-c", cfg)
    assert r.code == EXIT_OK
    assert set(r.json["written"]) == {"scopus"}


def test_export_defaults_to_the_config_formats(tmp_path):
    unique = _unique_corpus(tmp_path)
    cfg = write_config(tmp_path,
                       output={"dir": str(tmp_path / "out"),
                               "exports": ["csv", "bibtex"]})
    r = cli("export", unique, "-c", cfg)
    assert r.code == EXIT_OK
    assert set(r.json["written"]) == {"csv", "bibtex"}
    assert os.path.exists(str(tmp_path / "out" / "corpus.csv"))
    assert os.path.exists(str(tmp_path / "out" / "corpus.bib"))


def test_export_format_flag_is_repeatable(tmp_path):
    unique = _unique_corpus(tmp_path)
    r = cli("export", unique, "-C", str(tmp_path / "o"),
            "--format", "ris", "--format", "csv")
    assert r.code == EXIT_OK
    assert set(r.json["written"]) == {"ris", "csv"}


def test_export_explicit_columns(tmp_path):
    unique = _unique_corpus(tmp_path)
    path = str(tmp_path / "c.csv")
    cli("export", unique, "--csv", path, "--columns", "uid,title,doi")
    with open(path, encoding="utf-8") as fh:
        assert fh.readline().strip() == "uid,title,doi"


def test_export_of_an_empty_corpus_is_a_data_error(tmp_path):
    path = write(tmp_path / "empty.json",
                 json.dumps({"format": CORPUS_FORMAT, "searches": [],
                             "records": []}))
    assert cli("export", path).code == EXIT_DATA


# =============================================================== quality ====
def test_quality_prints_a_markdown_table_per_source(tmp_path):
    unique = _unique_corpus(tmp_path)
    r = cli("quality", unique)
    assert r.code == EXIT_OK
    assert "| source |" in r.out
    assert "Embase" in r.out
    assert "pct_doi" in r.out


def test_quality_json_and_csv(tmp_path):
    unique = _unique_corpus(tmp_path)
    csv_path = str(tmp_path / "q.csv")
    r = cli("quality", unique, "--json", "--csv", csv_path)
    assert r.code == EXIT_OK
    assert "Embase" in r.json["report"]
    assert r.json["report"]["Embase"]["n"] == 2
    assert os.path.getsize(csv_path) > 0


def test_quality_source_labels_match_the_prisma_databases(tmp_path):
    """The completeness table and the flow diagram must name one source once."""
    unique = _unique_corpus(tmp_path)
    q = cli("quality", unique, "--json").json["report"]
    p = cli("prisma", unique, "--svg", str(tmp_path / "f.svg"),
            "--appendix", str(tmp_path / "a.md"), "--records-excluded", "1",
            "--studies-included", "2")
    assert p.code == EXIT_OK
    for source in q:
        assert source in p.out


# =============================================== harvest / replay ===========
def _harvest_config(tmp_path):
    return write_config(tmp_path, databases=[{"name": "crossref",
                                              "max_results": 50}],
                        harvest={"archive": str(tmp_path / "archive")})


def test_harvest_archives_every_response(tmp_path):
    cfg = _harvest_config(tmp_path)
    archive = str(tmp_path / "archive")
    r = cli("harvest", "-c", cfg, "--database", "crossref",
            "--archive", archive, "--manifest", str(tmp_path / "m.json"),
            "--markdown", str(tmp_path / "h.md"),
            "-o", str(tmp_path / "harvested.json"),
            session=FakeSession(lambda u, p, h: FakeResponse(
                payload=CROSSREF_PAGE)))
    assert r.code == EXIT_OK
    assert r.json["database"] == "Crossref"
    assert r.json["records"] == 1
    assert r.json["responses"] >= 1
    assert len(r.json["checksum"]) == 64
    assert os.path.exists(os.path.join(archive, "manifest.json"))
    assert os.path.isdir(os.path.join(archive, "responses"))
    assert os.path.getsize(str(tmp_path / "m.json")) > 0
    assert os.path.getsize(str(tmp_path / "h.md")) > 0


def test_replay_reproduces_the_harvest_without_network_or_credentials(tmp_path):
    cfg = _harvest_config(tmp_path)
    archive = str(tmp_path / "archive")
    live = cli("harvest", "-c", cfg, "--database", "crossref",
               "--archive", archive,
               session=FakeSession(lambda u, p, h: FakeResponse(
                   payload=CROSSREF_PAGE)))
    assert live.code == EXIT_OK
    # No session at all: a socket would raise, so this proves replay is offline.
    replay = cli("replay", "-c", cfg, "--archive", archive,
                 "-o", str(tmp_path / "replayed.json"))
    assert replay.code == EXIT_OK
    assert replay.json["checksum_matches"] is True
    assert replay.json["checksum"] == live.json["checksum"]
    assert replay.json["integrity_problems"] == []
    assert replay.json["records"] == live.json["records"]


def test_replay_of_a_directory_that_is_not_an_archive_is_a_data_error(tmp_path):
    cfg = _harvest_config(tmp_path)
    empty = tmp_path / "not_an_archive"
    empty.mkdir()
    r = cli("replay", "-c", cfg, "--archive", str(empty))
    assert r.code == EXIT_DATA
    assert "not a CorpusSLR harvest archive" in r.err


def test_replay_detects_a_tampered_archive(tmp_path):
    """Editing an archived response must break the integrity audit."""
    cfg = _harvest_config(tmp_path)
    archive = str(tmp_path / "archive")
    assert cli("harvest", "-c", cfg, "--database", "crossref",
               "--archive", archive,
               session=FakeSession(lambda u, p, h: FakeResponse(
                   payload=CROSSREF_PAGE))).code == EXIT_OK
    responses = os.path.join(archive, "responses")
    victim = os.path.join(responses, sorted(os.listdir(responses))[0])
    with open(victim, encoding="utf-8") as fh:
        body = fh.read()
    write(victim, body.replace("Crossref only", "TAMPERED"))
    r = cli("replay", "-c", cfg, "--archive", archive)
    assert r.code == EXIT_DATA
    assert "integrity" in r.err.lower() or "checksum" in r.err.lower()


def test_harvest_without_an_archive_is_a_usage_error(tmp_path):
    cfg = write_config(tmp_path, databases=["crossref"])
    r = cli("harvest", "-c", cfg, "--database", "crossref")
    assert r.code == EXIT_USAGE
    assert "--archive" in r.err


def test_harvest_unknown_database_is_a_usage_error(tmp_path):
    cfg = _harvest_config(tmp_path)
    r = cli("harvest", "-c", cfg, "--database", "embase",
            "--archive", str(tmp_path / "a"))
    assert r.code == EXIT_USAGE
    assert "unknown database" in r.err


def test_replay_needs_a_database_when_the_archive_holds_several(tmp_path):
    cfg = write_config(tmp_path,
                       databases=[{"name": "crossref"}, {"name": "openalex"}],
                       harvest={"archive": str(tmp_path / "archive")})
    archive = str(tmp_path / "archive")
    assert cli("harvest", "-c", cfg, "--database", "crossref",
               "--archive", archive,
               session=FakeSession(lambda u, p, h: FakeResponse(
                   payload=CROSSREF_PAGE))).code == EXIT_OK
    assert cli("harvest", "-c", cfg, "--database", "openalex",
               "--archive", archive,
               session=FakeSession(lambda u, p, h: FakeResponse(
                   payload=OPENALEX_PAGE))).code == EXIT_OK
    r = cli("replay", "-c", cfg, "--archive", archive)
    assert r.code == EXIT_USAGE
    assert "--database" in r.err
    # Naming it resolves the ambiguity.
    ok = cli("replay", "-c", cfg, "--archive", archive,
             "--database", "openalex")
    assert ok.code == EXIT_OK
    assert ok.json["database"] == "OpenAlex"


def test_replay_reports_drift_against_a_second_archive(tmp_path):
    cfg = _harvest_config(tmp_path)
    first = str(tmp_path / "a1")
    second = str(tmp_path / "a2")
    assert cli("harvest", "-c", cfg, "--database", "crossref",
               "--archive", first,
               session=FakeSession(lambda u, p, h: FakeResponse(
                   payload=CROSSREF_PAGE))).code == EXIT_OK
    grown = json.loads(json.dumps(CROSSREF_PAGE))
    grown["message"]["items"].append(
        {"DOI": "10.5001/newly-indexed",
         "title": ["A newly indexed article about machine learning"],
         "type": "journal-article", "container-title": ["Journal C"],
         "issued": {"date-parts": [[2026, 1, 1]]},
         "author": [{"family": "Late", "given": "Arrival"}], "language": "en"})
    grown["message"]["total-results"] = 2
    assert cli("harvest", "-c", cfg, "--database", "crossref",
               "--archive", second,
               session=FakeSession(lambda u, p, h: FakeResponse(
                   payload=grown))).code == EXIT_OK
    drift_md = str(tmp_path / "drift.md")
    r = cli("replay", "-c", cfg, "--archive", first, "--compare", second,
            "--drift-markdown", drift_md)
    assert r.code == EXIT_OK
    assert r.json["drift"]["n_added"] == 1
    assert os.path.getsize(drift_md) > 0


# =================================================================== run ====
def _full_config(tmp_path, **over):
    ris = write(tmp_path / "embase.ris", RIS_EMBASE)
    wos = write(tmp_path / "wos.txt", WOS_TAGGED)
    cfg = {
        "review": {"title": "AI adoption in SMEs"},
        "query": {"blocks": [["artificial intelligence", "machine learning"],
                             ["adoption", "acceptance"]],
                  "years": [2015, 2026], "doc_types": ["article", "review"],
                  "languages": ["en"]},
        "databases": ["openalex", {"name": "crossref", "max_results": 300}],
        "files": [{"path": ris, "database": "Embase", "platform": "Elsevier",
                   "date_run": "2026-08-10"},
                  {"path": wos, "database": "Web of Science Core Collection",
                   "platform": "Clarivate", "date_run": "2026-08-10"}],
        "enrich": {"recover_abstracts": False},
        "dedup": {"fuzzy_threshold": 0.93},
        "output": {"dir": str(tmp_path / "out"),
                   "exports": ["csv", "screening", "ris"]},
    }
    cfg.update(over)
    return write(tmp_path / "review.json", json.dumps(cfg))


def test_run_executes_the_whole_review_from_one_file(tmp_path):
    """The claim the CLI exists to support: one config, one command."""
    cfg = _full_config(tmp_path, screening={
        "records_excluded": 1, "studies_included": 2,
        "fulltext_exclusions": {"wrong population": 2}})
    r = cli("run", "-c", cfg, session=api_session())
    assert r.code == EXIT_OK, r.err
    s = r.json
    # 2 OpenAlex + 1 Crossref + 2 Embase + 2 WoS
    assert s["identified"] == 7
    assert s["identified_by_source"] == {
        "OpenAlex": 2, "Crossref": 1, "Embase": 2,
        "Web of Science Core Collection": 2}
    assert sum(s["identified_by_source"].values()) == s["identified"]
    assert s["dedup"]["before"] == 7
    assert s["dedup"]["after"] == 5
    assert s["dedup"]["removed"] == 2
    assert s["prisma"]["prisma_valid"] is True
    counts = s["prisma"]["counts"]
    assert counts["identified"] == 7
    assert counts["records_screened"] == 5
    assert counts["studies_included"] == 2

    out = tmp_path / "out"
    for name in ("corpus_raw.json", "corpus_unique.json", "dedup_report.csv",
                 "overlap.md", "prisma2020_flow.svg", "prisma_s_appendix.md",
                 "quality.md", "quality.csv", "source_audit.md",
                 "run_summary.json", "corpus.csv", "screening.csv",
                 "corpus.ris"):
        assert (out / name).exists(), name
        assert (out / name).stat().st_size > 0, name

    with open(str(out / "run_summary.json"), encoding="utf-8") as fh:
        saved = json.load(fh)
    assert saved["identified"] == 7
    assert saved["config"]["config_sha256"] == s["config"]["config_sha256"]
    assert saved["config"]["corpusslr_version"] == __version__


def test_run_is_reproducible_for_the_same_inputs(tmp_path):
    """Two runs of one configuration must agree on every reported number."""
    cfg = _full_config(tmp_path, screening={
        "records_excluded": 1, "studies_included": 2,
        "fulltext_exclusions": {"wrong population": 2}})
    first = cli("run", "-c", cfg, "-q", session=api_session()).json
    second = cli("run", "-c", cfg, "-q", session=api_session()).json
    assert first["identified"] == second["identified"]
    assert first["identified_by_source"] == second["identified_by_source"]
    assert first["dedup"] == second["dedup"]
    assert first["prisma"]["counts"] == second["prisma"]["counts"]
    assert first["config"]["config_sha256"] == second["config"]["config_sha256"]


def test_run_dry_run_writes_nothing(tmp_path):
    cfg = _full_config(tmp_path)
    session = api_session()
    r = cli("run", "-c", cfg, "--dry-run", session=session)
    assert r.code == EXIT_OK
    assert session.calls == []
    assert r.json["dry_run"] is True
    assert len(r.json["databases"]) == 2
    assert all(f["exists"] for f in r.json["files"])
    assert not (tmp_path / "out" / "corpus_raw.json").exists()


def test_run_stops_on_an_unbalanced_prisma_flow(tmp_path):
    cfg = _full_config(tmp_path, screening={"records_excluded": 1,
                                            "studies_included": 99})
    r = cli("run", "-c", cfg, session=api_session())
    assert r.code == EXIT_DATA
    assert "does not balance" in r.err


def test_run_keep_going_records_a_missing_credential(tmp_path):
    # 2 OpenAlex + 2 Embase + 2 WoS = 6 identified; the shared DOI
    # 10.1016/j.jbusres.2024.01001 appears in all three, so 2 are removed and
    # 4 unique records reach screening.
    cfg = _full_config(tmp_path,
                       databases=["scopus", "openalex"],
                       screening={"records_excluded": 1,
                                  "studies_included": 1,
                                  "fulltext_exclusions": {"other": 2}})
    r = cli("run", "-c", cfg, "--keep-going", session=api_session())
    assert r.code == EXIT_OK, r.err
    assert r.json["failures"][0]["database"] == "Scopus"
    assert r.json["identified"] == 6
    assert r.json["dedup"]["after"] == 4
    assert r.json["prisma"]["prisma_valid"] is True
    # The gap is on the record, not swallowed.
    with open(str(tmp_path / "out" / "run_summary.json"), encoding="utf-8") as fh:
        assert json.load(fh)["failures"][0]["reason"] == "missing credential"


def test_run_dedup_override_from_the_command_line(tmp_path):
    cfg = _full_config(tmp_path, screening={
        "records_excluded": 1, "studies_included": 2,
        "fulltext_exclusions": {"wrong population": 2}})
    r = cli("run", "-c", cfg, "--fuzzy-threshold", "0.99",
            session=api_session())
    assert r.code == EXIT_OK
    assert r.json["dedup"]["parameters"]["fuzzy_threshold"] == 0.99


def test_run_output_prefix_is_applied(tmp_path):
    cfg = _full_config(tmp_path,
                       output={"dir": str(tmp_path / "out"), "prefix": "rev1",
                               "exports": ["csv"]},
                       screening={"records_excluded": 1,
                                  "studies_included": 2,
                                  "fulltext_exclusions": {"x": 2}})
    r = cli("run", "-c", cfg, session=api_session())
    assert r.code == EXIT_OK
    assert (tmp_path / "out" / "rev1_corpus_unique.json").exists()
    assert (tmp_path / "out" / "rev1_run_summary.json").exists()


def test_run_out_dir_flag_overrides_the_config(tmp_path):
    cfg = _full_config(tmp_path, screening={
        "records_excluded": 1, "studies_included": 2,
        "fulltext_exclusions": {"x": 2}})
    elsewhere = str(tmp_path / "elsewhere")
    r = cli("run", "-c", cfg, "-C", elsewhere, session=api_session())
    assert r.code == EXIT_OK
    assert os.path.exists(os.path.join(elsewhere, "run_summary.json"))


def test_run_recovers_abstracts_when_configured(tmp_path):
    """Abstract recovery is wired in and reported, not silently skipped."""
    def responder(url, params, headers):
        if "openalex" in url and "filter" in str(params):
            return FakeResponse(payload=OPENALEX_PAGE)
        if "openalex" in url:
            return FakeResponse(payload={"results": []})
        if "crossref" in url:
            return FakeResponse(payload=CROSSREF_PAGE)
        return FakeResponse(payload={"results": []})
    cfg = _full_config(tmp_path, enrich={"recover_abstracts": True},
                       screening={"records_excluded": 1,
                                  "studies_included": 2,
                                  "fulltext_exclusions": {"x": 2}})
    r = cli("run", "-c", cfg, session=FakeSession(responder))
    assert r.code == EXIT_OK
    assert "abstract_recovery" in r.json


def test_run_no_enrich_skips_recovery(tmp_path):
    cfg = _full_config(tmp_path, enrich={"recover_abstracts": True},
                       screening={"records_excluded": 1,
                                  "studies_included": 2,
                                  "fulltext_exclusions": {"x": 2}})
    r = cli("run", "-c", cfg, "--no-enrich", session=api_session())
    assert r.code == EXIT_OK
    assert "abstract_recovery" not in r.json


def test_run_with_no_records_at_all_is_a_data_error(tmp_path):
    empty_oa = {"meta": {"count": 0, "next_cursor": None}, "results": []}
    empty_cr = {"status": "ok", "message-version": "1.0.0",
                "message": {"total-results": 0, "items": [],
                            "message-version": "1.0.0"}}

    def responder(url, params, headers):
        if "openalex" in url:
            return FakeResponse(payload=empty_oa)
        return FakeResponse(payload=empty_cr)
    cfg = write_config(tmp_path, output={"dir": str(tmp_path / "out")})
    r = cli("run", "-c", cfg, session=FakeSession(responder))
    assert r.code == EXIT_DATA
    assert "no records identified" in r.err


# ================================================ credential hygiene ========
def test_no_credential_ever_reaches_stdout_stderr_or_an_artefact(
        tmp_path, monkeypatch):
    """The strongest property to hold: secrets stay in the environment."""
    secret = "SCOPUS-SECRET-DO-NOT-LEAK"
    token = "INSTTOKEN-DO-NOT-LEAK"
    monkeypatch.setenv("SCOPUS_API_KEY", secret)
    monkeypatch.setenv("SCOPUS_INSTTOKEN", token)
    monkeypatch.setenv("CORPUSSLR_CONTACT_EMAIL", "reviewer@example.org")
    scopus_page = {"search-results": {"opensearch:totalResults": "1",
                                      "entry": [
        {"dc:identifier": "SCOPUS_ID:85001",
         "dc:title": "Artificial intelligence adoption in small firms",
         "prism:doi": "10.1016/j.jbusres.2024.01001",
         "prism:coverDate": "2024-01-01", "dc:creator": "Kowalski J.",
         "prism:publicationName": "Journal of Business Research",
         "subtypeDescription": "Article", "citedby-count": "10"}]}}

    def responder(url, params, headers):
        # The key must travel in the header, never in the URL parameters.
        assert secret not in json.dumps(params)
        if "scopus" in url or "serial" in url:
            return FakeResponse(payload=scopus_page)
        if "openalex" in url:
            return FakeResponse(payload=OPENALEX_PAGE)
        return FakeResponse(payload={"results": []})

    cfg = _full_config(tmp_path, databases=["scopus", "openalex"], files=[],
                       screening={"records_excluded": 1,
                                  "studies_included": 1,
                                  "fulltext_exclusions": {"x": 0}})
    r = cli("run", "-c", cfg, "-v", session=FakeSession(responder))
    assert r.code == EXIT_OK, r.err
    for blob in (r.out, r.err):
        assert secret not in blob
        assert token not in blob
    out = tmp_path / "out"
    for name in os.listdir(str(out)):
        with open(str(out / name), encoding="utf-8", errors="replace") as fh:
            body = fh.read()
        assert secret not in body, name
        assert token not in body, name


def test_harvest_archive_holds_no_credentials(tmp_path, monkeypatch):
    """A reviewer replays the archive; it must contain nothing subscriber-bound."""
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "S2-SECRET-KEY")
    monkeypatch.setenv("CORPUSSLR_CONTACT_EMAIL", "reviewer@example.org")
    page = {"total": 1, "data": [
        {"paperId": "p1", "title": "A paper about artificial intelligence",
         "year": 2021, "externalIds": {"DOI": "10.5001/s2"},
         "authors": [{"name": "Jan Kowalski"}],
         "publicationTypes": ["JournalArticle"],
         "venue": "Journal of Testing", "abstract": "An abstract."}]}
    cfg = write_config(tmp_path, databases=["semanticscholar"],
                       harvest={"archive": str(tmp_path / "archive")})
    archive = str(tmp_path / "archive")
    r = cli("harvest", "-c", cfg, "--database", "semanticscholar",
            "--archive", archive,
            session=FakeSession(lambda u, p, h: FakeResponse(payload=page)))
    assert r.code == EXIT_OK
    for root, _dirs, names in os.walk(archive):
        for name in names:
            with open(os.path.join(root, name), encoding="utf-8",
                      errors="replace") as fh:
                body = fh.read()
            assert "S2-SECRET-KEY" not in body
            assert "reviewer@example.org" not in body


# =========================================== serialization round trip =======
def test_corpus_round_trip_preserves_records_and_provenance(tmp_path):
    from corpusslr import Corpus, Record
    corpus = Corpus()
    corpus.add_records([Record(title="A study", doi="10.5001/a", year=2020,
                               authors=["Kowalski, Jan"], abstract="Abs"),
                        Record(title="Another study", doi="10.5001/b",
                               year=2021)],
                       database="Embase", platform="Elsevier",
                       query="ai AND adoption", date_run="2026-08-10")
    payload = corpus_to_dict(corpus)
    restored, result = corpus_from_dict(payload)
    assert result is None
    assert len(restored.records) == 2
    assert [r.uid for r in restored.records] == [r.uid for r in corpus.records]
    assert restored.identified_by_source() == {"Embase": 2}
    assert restored.searches[0].query == "ai AND adoption"
    assert restored.searches[0].date_run == "2026-08-10"
    # A record added after a round trip must not collide with a restored uid.
    restored.add_records([Record(title="Third", doi="10.5001/c")],
                         database="Crossref")
    uids = [r.uid for r in restored.records]
    assert len(uids) == len(set(uids))


def test_corpus_round_trip_preserves_the_dedup_report(tmp_path):
    from corpusslr import Corpus, Record, deduplicate
    corpus = Corpus()
    corpus.add_records([Record(title="Shared study of AI", doi="10.5001/x",
                               year=2020)], database="Embase")
    corpus.add_records([Record(title="Shared study of AI", doi="10.5001/x",
                               year=2020)], database="Scopus")
    result = deduplicate(corpus)
    payload = corpus_to_dict(corpus, result)
    _restored, restored_result = corpus_from_dict(payload)
    assert restored_result is not None
    assert restored_result.report.removed == result.report.removed
    assert restored_result.report.by_method == dict(result.report.by_method)
    assert restored_result.report.overlap == result.report.overlap


def test_corpus_from_dict_rejects_a_future_format():
    with pytest.raises(DataError):
        corpus_from_dict({"format": "corpusslr/corpus-99", "records": []})


def test_corpus_from_dict_rejects_a_malformed_record():
    with pytest.raises(DataError):
        corpus_from_dict({"format": CORPUS_FORMAT, "records": ["not a dict"]})


def test_corpus_from_dict_ignores_unknown_record_fields():
    corpus, _ = corpus_from_dict(
        {"format": CORPUS_FORMAT, "searches": [],
         "records": [{"title": "T", "uid": "R000001",
                      "some_future_field": 42}]})
    assert corpus.records[0].title == "T"


# =================================================== internal error path ====
def test_an_unexpected_error_becomes_exit_three_not_a_traceback(
        tmp_path, monkeypatch):
    import corpusslr.cli as cli_mod

    def boom(*a, **kw):
        raise RuntimeError("a defect nobody anticipated")
    monkeypatch.setattr(cli_mod, "build_query", boom)
    r = cli("check", "-c", write_config(tmp_path))
    assert r.code == 3
    assert "internal error" in r.err
    assert "Traceback" not in r.err
    assert "issues" in r.err                      # where to report it


def test_traceback_flag_reraises_for_a_bug_report(tmp_path, monkeypatch):
    import corpusslr.cli as cli_mod

    def boom(*a, **kw):
        raise RuntimeError("a defect nobody anticipated")
    monkeypatch.setattr(cli_mod, "build_query", boom)
    with pytest.raises(RuntimeError):
        cli("check", "-c", write_config(tmp_path), "--traceback")


def test_keyboard_interrupt_is_reported_as_130(tmp_path, monkeypatch):
    import corpusslr.cli as cli_mod

    def interrupt(*a, **kw):
        raise KeyboardInterrupt
    monkeypatch.setattr(cli_mod, "build_query", interrupt)
    r = cli("check", "-c", write_config(tmp_path))
    assert r.code == 130
    assert "interrupted" in r.err


# ==================================================== registry coherence ====
def test_every_configurable_database_is_in_the_source_registry():
    """A database the CLI offers must classify as principal or supplementary."""
    from corpusslr.sources.registry import classify_source
    for alias, spec in DATABASES.items():
        tier = classify_source(spec["label"])
        assert tier in ("principal", "supplementary"), (alias, tier)


def test_every_database_can_be_built_when_its_credential_is_present(
        monkeypatch):
    from corpusslr.cli import build_source
    monkeypatch.setenv("SCOPUS_API_KEY", "k")
    monkeypatch.setenv("WOS_API_KEY", "k")
    for alias in DATABASES:
        source = build_source(alias, {}, session=FakeSession([]))
        assert source.name == DATABASES[alias]["label"] or source.name


def test_dry_run_compiles_a_query_for_every_database(tmp_path):
    path = write_config(tmp_path, databases=sorted(DATABASES))
    r = cli("search", "-c", path, "--dry-run")
    assert r.code == EXIT_OK
    assert len(r.json["databases"]) == len(DATABASES)
    for row in r.json["databases"]:
        assert row["query"], row["database"]


# ================================================== remaining edge paths ====
def test_verbose_prints_the_per_database_filters(tmp_path):
    r = cli("search", "-c", write_config(tmp_path), "--dry-run", "-v")
    assert r.code == EXIT_OK
    assert "filters:" in r.err


def test_unreadable_config_is_a_usage_error(tmp_path):
    """A directory where a file is expected must not raise a traceback."""
    d = tmp_path / "adirectory.json"
    d.mkdir()
    r = cli("check", "-c", str(d))
    assert r.code == EXIT_USAGE
    assert "Traceback" not in r.err


def test_malformed_yaml_is_reported_as_such(tmp_path):
    pytest.importorskip("yaml")
    path = write(tmp_path / "c.yaml", "query:\n  blocks: [[ai\n   bad: -\n")
    r = cli("check", "-c", path)
    assert r.code == EXIT_USAGE
    assert "YAML" in r.err


def test_valid_yaml_config_is_accepted(tmp_path):
    pytest.importorskip("yaml")
    path = write(tmp_path / "c.yaml",
                 "query:\n"
                 "  blocks:\n"
                 "    - [artificial intelligence, machine learning]\n"
                 "    - [adoption]\n"
                 "  years: [2015, 2026]\n"
                 "databases: [openalex]\n")
    r = cli("check", "-c", path)
    assert r.code == EXIT_OK
    assert r.json["databases"][0]["database"] == "OpenAlex"


def test_single_character_term_is_rejected(tmp_path):
    path = write(tmp_path / "c.json",
                 json.dumps({"query": {"blocks": [["a"]]},
                             "databases": ["openalex"]}))
    r = cli("check", "-c", path)
    assert r.code == EXIT_USAGE
    assert "too short" in r.err


def test_non_integer_year_is_rejected(tmp_path):
    path = write(tmp_path / "c.json",
                 json.dumps({"query": {"blocks": [["ai"]],
                                       "years": ["recent", "now"]},
                             "databases": ["openalex"]}))
    r = cli("check", "-c", path)
    assert r.code == EXIT_USAGE
    assert "two integers" in r.err


def test_non_boolean_title_only_is_rejected(tmp_path):
    path = write(tmp_path / "c.json",
                 json.dumps({"query": {"blocks": [["ai"]], "title_only": "yes"},
                             "databases": ["openalex"]}))
    assert cli("check", "-c", path).code == EXIT_USAGE


def test_bad_max_results_values_are_rejected(tmp_path):
    for value in (0, -10, "many", True):
        path = write(tmp_path / "c.json",
                     json.dumps({"query": {"blocks": [["ai"]]},
                                 "databases": [{"name": "openalex",
                                                "max_results": value}]}))
        r = cli("check", "-c", path)
        assert r.code == EXIT_USAGE, value
        assert "positive integer" in r.err


def test_top_level_max_results_is_validated_and_applied(tmp_path):
    path = write(tmp_path / "c.json",
                 json.dumps({"query": {"blocks": [["ai"]]},
                             "databases": ["openalex"], "max_results": 0}))
    assert cli("check", "-c", path).code == EXIT_USAGE
    path = write(tmp_path / "ok.json",
                 json.dumps({"query": {"blocks": [["ai"]]},
                             "databases": ["openalex"], "max_results": 42}))
    r = cli("search", "-c", path, "--dry-run")
    assert r.json["databases"][0]["max_results"] == 42


def test_invalid_scopus_view_is_rejected(tmp_path):
    path = write(tmp_path / "c.json",
                 json.dumps({"query": {"blocks": [["ai"]]},
                             "databases": [{"name": "scopus",
                                            "view": "EVERYTHING"}]}))
    r = cli("check", "-c", path)
    assert r.code == EXIT_USAGE
    assert "STANDARD" in r.err and "COMPLETE" in r.err


def test_files_entry_may_be_a_bare_path_string(tmp_path):
    ris = write(tmp_path / "e.ris", RIS_EMBASE)
    path = write(tmp_path / "c.json",
                 json.dumps({"query": {"blocks": [["ai"]]},
                             "databases": [], "files": [ris]}))
    r = cli("parse", "-c", path, "-o", str(tmp_path / "c2.json"))
    assert r.code == EXIT_OK
    assert r.json["identified"] == 2


def test_files_entry_without_a_path_is_rejected(tmp_path):
    path = write(tmp_path / "c.json",
                 json.dumps({"query": {"blocks": [["ai"]]},
                             "databases": [], "files": [{"database": "Embase"}]}))
    r = cli("check", "-c", path)
    assert r.code == EXIT_USAGE
    assert 'no "path"' in r.err


def test_bad_dedup_integer_options_are_rejected(tmp_path):
    for name, value in (("year_tolerance", -1), ("max_block", 0),
                        ("block_prefix", 0), ("year_tolerance", "one")):
        path = write(tmp_path / "c.json",
                     json.dumps({"query": {"blocks": [["ai"]]},
                                 "databases": ["openalex"],
                                 "dedup": {name: value}}))
        assert cli("check", "-c", path).code == EXIT_USAGE, (name, value)


def test_non_numeric_similarity_is_rejected(tmp_path):
    path = write(tmp_path / "c.json",
                 json.dumps({"query": {"blocks": [["ai"]]},
                             "databases": ["openalex"],
                             "dedup": {"fuzzy_threshold": "high"}}))
    r = cli("check", "-c", path)
    assert r.code == EXIT_USAGE
    assert "between 0 and 1" in r.err


def test_non_boolean_dedup_switch_is_rejected(tmp_path):
    path = write(tmp_path / "c.json",
                 json.dumps({"query": {"blocks": [["ai"]]},
                             "databases": ["openalex"],
                             "dedup": {"separate_conference": "yes"}}))
    assert cli("check", "-c", path).code == EXIT_USAGE


def test_fulltext_exclusions_must_be_counts(tmp_path):
    path = write_config(tmp_path,
                        screening={"fulltext_exclusions": {"reason": "many"}})
    r = cli("check", "-c", path)
    assert r.code == EXIT_USAGE
    assert "non-negative integer" in r.err
    path = write_config(tmp_path,
                        screening={"fulltext_exclusions": ["a", "b"]})
    assert cli("check", "-c", path).code == EXIT_USAGE


def test_bad_appendix_format_is_rejected(tmp_path):
    path = write_config(tmp_path, output={"appendix": "pdf"})
    r = cli("check", "-c", path)
    assert r.code == EXIT_USAGE
    assert "python-docx" in r.err


def test_unknown_enrich_key_is_rejected(tmp_path):
    path = write_config(tmp_path, enrich={"recover_abstract": True})
    assert cli("check", "-c", path).code == EXIT_USAGE


def test_wos_missing_key_names_the_clarivate_portal(tmp_path):
    path = write_config(tmp_path, databases=["wos"])
    r = cli("search", "-c", path)
    assert r.code == EXIT_USAGE
    assert "WOS_API_KEY" in r.err
    assert "Clarivate" in r.err


def test_build_source_rejects_an_unknown_alias():
    from corpusslr.cli import build_source
    with pytest.raises(ConfigError):
        build_source("notadatabase", {})


def test_parse_arxiv_atom_export(tmp_path):
    atom = ("<?xml version='1.0' encoding='UTF-8'?>"
            "<feed xmlns='http://www.w3.org/2005/Atom'>"
            "<entry><id>http://arxiv.org/abs/2401.00001v1</id>"
            "<title>A preprint about machine learning adoption</title>"
            "<summary>An abstract.</summary>"
            "<published>2024-01-01T00:00:00Z</published>"
            "<author><name>Jan Kowalski</name></author>"
            "</entry></feed>")
    path = write(tmp_path / "arxiv.xml", atom)
    r = cli("parse", path, "-o", str(tmp_path / "c.json"))
    assert r.code == EXIT_OK
    assert r.json["files"][0]["format"] == "arxiv-atom"
    assert r.json["identified_by_source"] == {"arXiv": 1}


def test_detect_export_format_on_unrecognised_xml():
    assert detect_export_format("<?xml version='1.0'?><other><thing/></other>") \
        == ""


def test_parse_file_without_a_recognisable_database_falls_back(tmp_path):
    """A generic RIS with no vendor marker still imports, labelled honestly."""
    generic = ("TY  - JOUR\nTI  - A generic reference with no vendor marker\n"
               "AU  - Author, An\nPY  - 2020\nER  -\n")
    path = write(tmp_path / "generic.ris", generic)
    r = cli("parse", path, "-o", str(tmp_path / "c.json"))
    assert r.code == EXIT_OK
    assert r.json["files"][0]["format"] == "ris"
    assert r.json["identified"] == 1


def test_corpus_from_dict_rejects_a_non_object():
    with pytest.raises(DataError):
        corpus_from_dict(["not", "a", "dict"])


def test_read_corpus_of_an_unreadable_path_is_an_error(tmp_path):
    d = tmp_path / "dir.json"
    d.mkdir()
    r = cli("dedup", str(d))
    assert r.code in (EXIT_USAGE, EXIT_DATA)
    assert "Traceback" not in r.err


def test_output_paths_create_missing_directories(tmp_path):
    unique = _unique_corpus(tmp_path)
    deep = str(tmp_path / "a" / "b" / "c" / "out.csv")
    r = cli("export", unique, "--csv", deep)
    assert r.code == EXIT_OK
    assert os.path.exists(deep)


def test_max_block_override_is_reported(tmp_path):
    raw = _parsed_corpus(tmp_path)
    r = cli("dedup", raw, "-o", str(tmp_path / "u.json"), "-C", str(tmp_path),
            "--max-block", "10")
    assert r.code == EXIT_OK
    assert r.json["parameters"]["max_block"] == 10


def test_search_source_error_is_recorded_under_keep_going(tmp_path):
    session = FakeSession(lambda u, p, h: FakeResponse(
        status_code=500, payload={"error": "upstream"}))
    path = write_config(tmp_path, databases=["openalex"])
    r = cli("search", "-c", path, "--keep-going", session=session)
    assert r.code == EXIT_DATA           # nothing retrieved at all
    assert "every source failed" in r.err


def test_check_reports_an_unreadable_export_file(tmp_path):
    """A directory listed as an export must be a warning, not a crash."""
    d = tmp_path / "notafile.ris"
    d.mkdir()
    path = write_config(tmp_path, databases=[], files=[{"path": str(d)}])
    r = cli("check", "-c", path)
    assert r.code == EXIT_OK
    assert r.json["files"][0]["format"] == ""
    assert r.json["files"][0]["exists"] is False
    assert any("not a readable file" in w for w in r.json["warnings"])


def test_quality_of_an_empty_corpus_is_a_data_error(tmp_path):
    path = write(tmp_path / "empty.json",
                 json.dumps({"format": CORPUS_FORMAT, "searches": [],
                             "records": []}))
    assert cli("quality", path).code == EXIT_DATA


def test_harvest_source_error_is_a_data_error(tmp_path):
    cfg = _harvest_config(tmp_path)
    session = FakeSession(lambda u, p, h: FakeResponse(
        status_code=500, payload={"error": "upstream"}))
    r = cli("harvest", "-c", cfg, "--database", "crossref",
            "--archive", str(tmp_path / "a"), session=session)
    assert r.code == EXIT_DATA
    assert "Traceback" not in r.err


def test_replay_no_strict_keeps_going_after_tampering(tmp_path):
    cfg = _harvest_config(tmp_path)
    archive = str(tmp_path / "archive")
    assert cli("harvest", "-c", cfg, "--database", "crossref",
               "--archive", archive,
               session=FakeSession(lambda u, p, h: FakeResponse(
                   payload=CROSSREF_PAGE))).code == EXIT_OK
    responses = os.path.join(archive, "responses")
    victim = os.path.join(responses, sorted(os.listdir(responses))[0])
    with open(victim, encoding="utf-8") as fh:
        body = fh.read()
    write(victim, body.replace("Crossref only", "TAMPERED"))
    r = cli("replay", "-c", cfg, "--archive", archive, "--no-strict")
    assert r.code == EXIT_OK
    assert r.json["integrity_problems"]


def test_replay_of_an_empty_archive_directory_is_a_data_error(tmp_path):
    cfg = _harvest_config(tmp_path)
    r = cli("replay", "-c", cfg, "--archive", str(tmp_path / "never_created"))
    assert r.code == EXIT_DATA


def test_replay_unknown_database_is_a_usage_error(tmp_path):
    cfg = _harvest_config(tmp_path)
    r = cli("replay", "-c", cfg, "--archive", str(tmp_path / "a"),
            "--database", "embase")
    assert r.code == EXIT_USAGE
    assert "unknown database" in r.err


def test_run_survives_a_failing_abstract_recovery(tmp_path):
    """Enrichment is a convenience; its failure must not lose the corpus."""
    import corpusslr.cli as cli_mod

    def boom(*a, **kw):
        raise RuntimeError("recovery service unavailable")
    cfg = _full_config(tmp_path, enrich={"recover_abstracts": True},
                       screening={"records_excluded": 1,
                                  "studies_included": 2,
                                  "fulltext_exclusions": {"x": 2}})
    original = cli_mod.recover_abstracts
    cli_mod.recover_abstracts = boom
    try:
        r = cli("run", "-c", cfg, session=api_session())
    finally:
        cli_mod.recover_abstracts = original
    assert r.code == EXIT_OK
    assert "error" in r.json["abstract_recovery"]
    assert "recovery service unavailable" in r.err
    assert r.json["dedup"]["after"] == 5


@pytest.mark.parametrize("exc,expected", [
    ("SourceError", EXIT_DATA),
    ("HarvestError", EXIT_DATA),
    ("FileNotFoundError", EXIT_USAGE),
    ("PermissionError", EXIT_DATA),
    ("IsADirectoryError", EXIT_DATA),
])
def test_every_expected_failure_maps_to_a_documented_exit_code(
        tmp_path, monkeypatch, exc, expected):
    """Shell scripts branch on these codes, so each mapping is pinned."""
    import corpusslr.cli as cli_mod
    from corpusslr.harvest import HarvestError
    from corpusslr.sources.base import SourceError
    kinds = {"SourceError": SourceError("upstream refused"),
             "HarvestError": HarvestError("archive unusable"),
             "FileNotFoundError": FileNotFoundError(2, "missing", "some.file"),
             "PermissionError": PermissionError(13, "denied", "some.file"),
             "IsADirectoryError": IsADirectoryError(21, "is a dir", "somedir")}

    def boom(*a, **kw):
        raise kinds[exc]
    monkeypatch.setattr(cli_mod, "build_query", boom)
    r = cli("check", "-c", write_config(tmp_path))
    assert r.code == expected
    assert "Traceback" not in r.err
    assert "error" in r.err


def test_parse_of_a_file_the_parser_chokes_on_is_a_data_error(tmp_path,
                                                             monkeypatch):
    """A parser exception must surface as a data error, not a traceback."""
    import corpusslr.parsers.ris as ris_mod

    def boom(*a, **kw):
        raise ValueError("unbalanced stanza")
    monkeypatch.setattr(ris_mod, "parse_ris", boom)
    path = write(tmp_path / "e.ris", RIS_EMBASE)
    r = cli("parse", path, "-o", str(tmp_path / "c.json"))
    assert r.code == EXIT_DATA
    assert "could not be parsed" in r.err
    assert "Traceback" not in r.err


def test_export_rejects_an_unknown_configured_format(tmp_path, monkeypatch):
    """A format that slips past config validation still fails cleanly."""
    import corpusslr.cli as cli_mod
    unique = _unique_corpus(tmp_path)
    monkeypatch.setattr(cli_mod, "_EXPORT_FORMATS",
                        cli_mod._EXPORT_FORMATS + ("xlsx",))
    cfg = write_config(tmp_path, output={"dir": str(tmp_path / "o"),
                                        "exports": ["xlsx"]})
    r = cli("export", unique, "-c", cfg)
    assert r.code == EXIT_USAGE
    assert "unknown export format" in r.err


def test_appendix_falls_back_to_markdown_without_python_docx(tmp_path,
                                                            monkeypatch):
    """A .docx request without the optional extra must degrade, not fail."""
    import corpusslr.cli as cli_mod
    unique = _unique_corpus(tmp_path)

    def md_only(corpus, result, path, **kw):
        # Mimic prisma_s_appendix's documented fallback: it rewrites the
        # extension to .md when python-docx is absent.
        actual = path[:-5] + ".md" if path.lower().endswith(".docx") else path
        write(actual, "# appendix\n")
        return actual
    monkeypatch.setattr(cli_mod, "prisma_s_appendix", md_only)
    cfg = write_config(tmp_path, output={"dir": str(tmp_path / "o"),
                                        "appendix": "docx"},
                       screening={"records_excluded": 1,
                                  "studies_included": 2})
    r = cli("prisma", unique, "-c", cfg)
    assert r.code == EXIT_OK
    assert "python-docx is not installed" in r.err
    assert os.path.exists(str(tmp_path / "o" / "prisma_s_appendix.md"))


def test_database_specific_notes_and_options_reach_the_client(tmp_path):
    """Per-database options in the config must actually configure the client."""
    from corpusslr.cli import build_source
    source = build_source("scopus", {"view": "COMPLETE"},
                          session=FakeSession([]), require_credentials=False)
    assert source.view == "COMPLETE"
    wos = build_source("wos", {"db": "WOS", "sort_field": "LD+D"},
                       session=FakeSession([]), require_credentials=False)
    assert wos.db == "WOS"


def test_parse_falls_back_to_the_records_own_source_label(tmp_path):
    """A CSV from an unrecognised vendor still gets a source name."""
    generic_csv = ("Title,Authors,Year,Journal,DOI\n"
                   '"A study from an unknown vendor","Author, An",2020,'
                   '"Journal of Testing",10.5001/unknown\n')
    path = write(tmp_path / "unknown.csv", generic_csv)
    r = cli("parse", path, "-o", str(tmp_path / "c.json"))
    assert r.code == EXIT_OK
    assert r.json["files"][0]["format"] == "csv"
    assert r.json["identified"] == 1
    assert list(r.json["identified_by_source"])[0]


def test_the_example_config_shipped_with_the_package_is_valid():
    """The documented example must never drift out of validity.

    A missing file is a failure, not a skip. Skipping made this test pass
    vacuously from an unpacked sdist -- which is precisely the situation it
    exists to check, since MANIFEST.in shipped only ``examples/*.py`` and left
    ``review_config.json`` out of the distribution. A reviewer who unpacked the
    release and ran the suite saw a green run and a config that was not there.
    """
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(here, "examples", "review_config.json")
    assert os.path.exists(path), (
        "examples/review_config.json is missing from this checkout; if this is "
        "an unpacked sdist, MANIFEST.in is not shipping it")
    r = cli("check", "-c", path)
    assert r.code == EXIT_OK, r.err
    assert r.json["valid"] is True


def test_auto_detection_preserves_identifiers_a_forced_format_would_lose(tmp_path):
    """The counterpart to test_parse_forced_format_that_contradicts_the_content.

    That test asserts the forced mismatch is *warned* about rather than refused,
    which keeps --format usable as an override. This one pins the reason the
    warning matters: left to detect the format, the same file keeps the DOI that
    the MEDLINE reader would silently drop, because RIS spells it ``DO`` while
    MEDLINE reads ``LID``/``AID``.
    """
    ris = ("TY  - JOUR\nTI  - Artificial intelligence adoption in firms\n"
           "AU  - Kowalski, Jan\nPY  - 2024\nDO  - 10.1016/j.x\nER  - \n")
    path = write(tmp_path / "export.ris", ris)

    forced = cli("parse", path, "--format", "nbib", "-o", str(tmp_path / "a.json"))
    assert forced.code == EXIT_OK
    assert any("contradicts" in w for w in forced.json["files"][0]["warnings"])

    out = tmp_path / "b.json"
    auto = cli("parse", path, "-o", str(out))
    assert auto.code == EXIT_OK
    assert auto.json["files"][0]["format"] == "ris"
    import json as _j
    corpus = _j.loads(out.read_text(encoding="utf-8"))
    recs = corpus["records"] if isinstance(corpus, dict) else corpus
    assert [x.get("doi") for x in recs] == ["10.1016/j.x"], (
        "auto-detection must keep the identifier the forced path loses")
