"""Every Python example in docs/user_guide.md is executed here.

Documentation that is not executed is a promise, not a fact: three method names
in the first draft of the guide (``Corpus.add_result``,
``Corpus.counts_by_database``, ``HarvestArchive.harvest``) did not exist, and
only running the blocks revealed it. Blocks that would touch the network are
rewritten against a recorded response rather than skipped, so the flow a reader
follows is still the flow under test.
"""
import os
import re

import pytest

import corpusslr as C

_GUIDE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "docs", "user_guide.md")


def _blocks():
    with open(_GUIDE, encoding="utf-8") as fh:
        text = fh.read()
    return re.findall(r"```python\n(.*?)```", text, re.S)


def test_the_guide_ships_and_contains_examples():
    assert os.path.exists(_GUIDE), "docs/user_guide.md is missing"
    assert len(_blocks()) >= 6


def test_every_symbol_the_guide_imports_is_public():
    """A guide may only reference the documented public API."""
    imported = set()
    for src in _blocks():
        # Parenthesised imports may wrap across lines; a bare one ends at the
        # newline. Matching greedily past either bound swallows the following
        # statement, which is a bug in the test rather than in the guide.
        for m in re.finditer(r"from corpusslr import \(([^)]+)\)", src):
            imported |= {s.strip() for s in m.group(1).replace("\n", " ").split(",")
                         if s.strip()}
        for m in re.finditer(r"from corpusslr import ([^(\n]+)\n", src):
            imported |= {s.strip() for s in m.group(1).split(",") if s.strip()}
    assert imported, "no imports found in the guide"
    missing = sorted(s for s in imported if not hasattr(C, s))
    assert not missing, f"guide imports symbols that do not exist: {missing}"


def test_every_attribute_the_guide_reads_exists():
    """Catches a renamed method or report field before a reader does."""
    named = {
        (C.Corpus, "add_search"), (C.Corpus, "add_records"),
        (C.Corpus, "identified_by_source"), (C.Corpus, "total_identified"),
        (C.SearchQuery, "to_scopus"), (C.SearchQuery, "to_pubmed"),
        (C.PrismaFlow, "validate"), (C.PrismaFlow, "to_svg"),
        (C.ParseReport, "summary"),
        (C.HarvestArchive, "create"), (C.HarvestArchive, "open"),
    }
    missing = [f"{cls.__name__}.{attr}" for cls, attr in named
               if not hasattr(cls, attr)]
    assert not missing, f"guide names attributes that do not exist: {missing}"

    fields = set(C.PrismaFlow.__dataclass_fields__)
    documented = {"db_counts", "duplicates_removed", "dedup_by_method",
                  "records_excluded", "fulltext_exclusions", "studies_included",
                  "reports_included"}
    assert documented <= fields, f"guide passes unknown fields: {documented - fields}"

    for attr in ("removed", "by_method", "id_links_rejected", "by_locus",
                 "overlap", "summary", "to_csv"):
        assert hasattr(C.deduplicate([C.Record(title="A", doi="10.5001/a")]).report,
                       attr), f"DedupReport.{attr} is documented but absent"


def test_documented_dedup_parameters_are_real():
    import inspect
    params = set(inspect.signature(C.deduplicate).parameters)
    documented = {"fuzzy_threshold", "year_tolerance", "separate_conference",
                  "id_title_min"}
    assert documented <= params, f"undocumented rename: {documented - params}"


def test_query_compilation_example_runs():
    """Section 3: the compiled strategy a reader is told to publish."""
    query = C.SearchQuery(
        blocks=[["artificial intelligence", "machine learning"],
                ["adoption", "acceptance"],
                ["SME", "small firm"]],
        years=(2015, 2026), doc_types=["article", "review"], languages=["en"])
    scopus, pubmed = query.to_scopus(), query.to_pubmed()
    assert "TITLE-ABS-KEY" in scopus and "AND" in scopus
    assert "artificial intelligence" in pubmed
    # blocks AND-ed, terms OR-ed -- the property the guide states
    assert scopus.count(" AND ") >= 2
    assert " OR " in scopus


def test_parse_report_invariant_example_runs(tmp_path):
    """Section 4: the invariant the guide tells the reader to assert."""
    ris = tmp_path / "embase_export.ris"
    ris.write_text(
        "TY  - JOUR\nTI  - A study of things\nAU  - Nowak, A\nPY  - 2024\n"
        "DO  - 10.5001/a\nER  - \n\n"
        "TY  - JOUR\nPY  - 2024\nER  - \n",          # no title, no identifier
        encoding="utf-8")
    report = C.ParseReport()
    records = C.parse_ris_file(str(ris), report=report)
    assert isinstance(report.summary(), str)
    assert report.n_input == len(records) + report.n_rejected


def test_deduplication_and_reporting_example_runs(tmp_path):
    """Sections 5 and 6, as one flow -- which is how a reader meets them."""
    corpus = C.Corpus()
    dup = {"title": "Artificial intelligence adoption in small firms",
           "doi": "10.5001/x", "year": 2024, "authors": ["Kowalski, J"]}
    corpus.add_records([C.Record(**dup), C.Record(title="Another study",
                                                 doi="10.5001/y", year=2023)],
                       database="Web of Science Core Collection",
                       platform="Clarivate", query="q", date_run="2026-01-01")
    corpus.add_records([C.Record(**dup)], database="Scopus", platform="Elsevier",
                       query="q", date_run="2026-01-01")

    res = C.deduplicate(corpus)
    assert res.report.removed == 1
    assert isinstance(res.report.summary(), str)
    out = tmp_path / "dedup_decisions.csv"
    res.report.to_csv(str(out))
    assert out.read_text(encoding="utf-8").count("\n") >= 2

    flow = C.PrismaFlow(
        db_counts=corpus.identified_by_source(),
        duplicates_removed=res.report.removed,
        dedup_by_method=dict(res.report.by_method),
        records_excluded=1,
        fulltext_exclusions={"wrong population": 1},
        studies_included=0, reports_included=0)
    assert flow.validate() == [], flow.validate()
    svg = tmp_path / "prisma_flow.svg"
    flow.to_svg(str(svg))
    assert svg.read_text(encoding="utf-8").lstrip().startswith("<")

    appendix = C.prisma_s_markdown(corpus, res)
    assert "PRISMA-S" in appendix and "Web of Science" in appendix


def test_harvest_replay_example_runs(tmp_path):
    """Section 7, against a recorded response instead of the live API."""
    payload = {"meta": {"count": 1, "next_cursor": None}, "results": [{
        "id": "https://openalex.org/W1", "doi": "https://doi.org/10.5001/oa",
        "title": "Machine learning for credit risk", "publication_year": 2023,
        "type": "article", "authorships": [{"author": {"display_name": "A Nowak"}}],
        "primary_location": {"source": {"display_name": "Journal of Finance"}},
        "biblio": {"volume": "78", "first_page": "1", "last_page": "30"},
        "cited_by_count": 5, "ids": {}}]}

    class _R:
        status_code, headers, text = 200, {}, ""

        def json(self):
            return payload

        def raise_for_status(self):
            return None

    class _S:
        headers = {}

        def get(self, url, params=None, headers=None, timeout=None, **kw):
            return _R()

    query = C.SearchQuery(blocks=[["machine learning"]], years=(2020, 2026))
    path = str(tmp_path / "harvest_2026-08")
    archive = C.HarvestArchive.create(path)
    src = C.OpenAlexSource(session=_S())
    res = C.harvest(src, query, archive=archive)
    assert res.records

    assert C.verify_archive(path) == []
    replayed = C.replay_harvest(C.OpenAlexSource(session=_S()), query, path)
    assert replayed.checksum == res.checksum


@pytest.mark.parametrize("claim", [
    "No thesaurus expansion",
    "No screening",
    "No true Excel parsing",
])
def test_the_limitations_section_states_each_known_boundary(claim):
    with open(_GUIDE, encoding="utf-8") as fh:
        assert claim in fh.read()


# --------------------------------------------------------------------------
# The API reference is generated from introspection, so its value depends on it
# staying in step with the package. A symbol added to the public API without a
# reference entry fails here rather than being discovered by a reader.
# --------------------------------------------------------------------------
_API_REF = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "docs", "api_reference.md")


def test_the_api_reference_ships():
    assert os.path.exists(_API_REF), "docs/api_reference.md is missing"


def test_every_public_symbol_has_a_reference_entry():
    with open(_API_REF, encoding="utf-8") as fh:
        text = fh.read()
    public = list(getattr(C, "__all__", None)
                  or [x for x in dir(C) if not x.startswith("_")])
    assert public, "the package exposes no public API"
    missing = sorted(n for n in public if "### `" + n not in text)
    assert not missing, f"public symbols absent from the API reference: {missing}"


def test_the_reference_states_the_version_it_was_generated_from():
    with open(_API_REF, encoding="utf-8") as fh:
        text = fh.read()
    assert C.__version__ in text, (
        "the reference does not name the version it describes, so a reader "
        "cannot tell whether it is current")


def test_every_public_callable_has_a_docstring():
    """An undocumented public entry point is an API-reference gap by definition."""
    import inspect
    undocumented = []
    for name in (getattr(C, "__all__", None)
                 or [x for x in dir(C) if not x.startswith("_")]):
        obj = getattr(C, name)
        if (inspect.isclass(obj) or inspect.isfunction(obj)) and not inspect.getdoc(obj):
            undocumented.append(name)
    assert not undocumented, f"public API without docstrings: {undocumented}"


# --------------------------------------------------------------------------
# The shipped examples call live APIs, so they cannot be executed here. What can
# be verified without a network is that they would not fail on a name: that they
# parse, and that every symbol and attribute they reference exists.
# --------------------------------------------------------------------------
_EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "examples")


def _example_files():
    if not os.path.isdir(_EXAMPLES):
        return []
    return sorted(os.path.join(_EXAMPLES, f) for f in os.listdir(_EXAMPLES)
                  if f.endswith(".py"))


def test_the_examples_ship():
    assert _example_files(), "examples/ contains no Python examples"


@pytest.mark.parametrize("path", _example_files(),
                         ids=[os.path.basename(p) for p in _example_files()])
def test_each_example_parses(path):
    import ast
    with open(path, encoding="utf-8") as fh:
        ast.parse(fh.read(), filename=path)


@pytest.mark.parametrize("path", _example_files(),
                         ids=[os.path.basename(p) for p in _example_files()])
def test_each_example_only_imports_symbols_that_exist(path):
    import ast
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("corpusslr"):
            used |= {a.name for a in node.names}
    assert used, f"{os.path.basename(path)} imports nothing from corpusslr"
    missing = sorted(n for n in used if not hasattr(C, n))
    assert not missing, f"{os.path.basename(path)} imports missing symbols: {missing}"


@pytest.mark.parametrize("path", _example_files(),
                         ids=[os.path.basename(p) for p in _example_files()])
def test_each_example_only_touches_attributes_that_exist(path):
    """A renamed method in an example is a bug report waiting to be filed."""
    import ast
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    import inspect

    # Only names that are the imported CLASS itself can be checked statically.
    # A lowercase local (``corpus``, ``query``) shadows nothing in the package,
    # and resolving it against ``corpusslr`` hits the same-named SUBMODULE
    # (corpusslr.corpus), whose attributes are unrelated -- that made the first
    # version of this test report every valid call as missing.
    imported_classes = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("corpusslr"):
            for a in node.names:
                obj = getattr(C, a.name, None)
                if inspect.isclass(obj):
                    imported_classes[a.asname or a.name] = obj

    bad = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.value.id in imported_classes
                and not hasattr(imported_classes[node.value.id], node.attr)):
            bad.append(f"{node.value.id}.{node.attr}")
    assert not bad, f"{os.path.basename(path)} uses missing attributes: {sorted(set(bad))}"


def test_the_example_config_is_the_one_the_cli_documents():
    """examples/review_config.json must validate, and ship (MANIFEST.in)."""
    path = os.path.join(_EXAMPLES, "review_config.json")
    assert os.path.exists(path), "examples/review_config.json is missing"
    import json
    with open(path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    assert cfg, "the example configuration is empty"
    # no secret may sit in a file meant to be published as supplementary material
    flat = json.dumps(cfg).lower()
    for forbidden in ("api_key", "apikey", "insttoken", "password"):
        assert forbidden not in flat, (
            f"the example configuration contains {forbidden!r}; keys belong in "
            "the environment because this file is deposited with the review")
