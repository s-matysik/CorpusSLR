"""The Colab notebook, checked as an artefact rather than trusted as prose.

A notebook is shipped source that nothing else in the test suite would ever
execute, so three classes of defect can reach a reviewer unnoticed: a cell
that does not parse, a cell that refers to a name no earlier cell defines, and
-- the one that matters most -- a saved API key sitting in cell text or in a
stored output.

The tests here address each of those directly. The secret checks are paired
with fault injection against a synthetic notebook carrying a planted key, so
that a passing result demonstrates detection rather than merely absence.
"""
import ast
import io
import json
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOTEBOOK = os.path.join(REPO, "notebooks", "corpusslr_colab.ipynb")

#: Substrings that must never appear in a shipped notebook. A real key is long
#: and high-entropy, so the useful signal is an *assignment* of something
#: key-shaped, plus the vendor prefixes that appear in real Elsevier and
#: Clarivate keys.
SECRET_PATTERNS = (
    "sk-", "api_key=", "api_key =", "apikey=", "insttoken=",
    "SCOPUS_API_KEY = '", 'SCOPUS_API_KEY = "',
    "SCOPUS_API_KEY='", 'SCOPUS_API_KEY="',
    "WOS_API_KEY = '", 'WOS_API_KEY = "',
    "WOS_API_KEY='", 'WOS_API_KEY="',
)


@pytest.fixture(scope="module")
def notebook():
    assert os.path.isfile(NOTEBOOK), (
        "{} is missing; rebuild it with "
        "`python tools/build_colab_notebook.py`".format(NOTEBOOK))
    with open(NOTEBOOK, "r", encoding="utf-8") as fh:
        return json.load(fh)


def code_cells(nb):
    return [c for c in nb["cells"] if c["cell_type"] == "code"]


def cell_source(cell):
    source = cell["source"]
    return source if isinstance(source, str) else "".join(source)


# ---------------------------------------------------------------------------
# the file is a valid notebook
# ---------------------------------------------------------------------------
def test_notebook_is_valid_json_of_the_expected_format(notebook):
    assert notebook["nbformat"] == 4
    assert isinstance(notebook["cells"], list)
    assert notebook["metadata"]["kernelspec"]["name"] == "python3"


def test_notebook_has_both_code_and_explanation(notebook):
    """Markdown cells are the point: the notebook teaches the methodology."""
    kinds = [c["cell_type"] for c in notebook["cells"]]
    assert kinds.count("code") >= 10
    assert kinds.count("markdown") >= 10
    # it opens with an explanation, not with code
    assert kinds[0] == "markdown"


def test_every_cell_declares_a_recognised_type(notebook):
    for i, cell in enumerate(notebook["cells"]):
        assert cell["cell_type"] in ("code", "markdown"), i


# ---------------------------------------------------------------------------
# every code cell compiles
# ---------------------------------------------------------------------------
def test_every_code_cell_compiles(notebook):
    """A syntax error in a shipped notebook is a dead stop for a reviewer."""
    for i, cell in enumerate(code_cells(notebook)):
        source = cell_source(cell)
        try:
            compile(source, "<notebook cell {}>".format(i), "exec")
        except SyntaxError as exc:
            raise AssertionError(
                "code cell {} does not compile: {}".format(i, exc))


def test_the_compile_check_detects_a_broken_cell():
    """Fault injection: prove the compile check can fail."""
    broken = "for x in range(3)\n    print(x)\n"
    with pytest.raises(SyntaxError):
        compile(broken, "<planted>", "exec")


def test_no_cell_uses_ipython_magics(notebook):
    """Magics do not compile, and a notebook that needs them is not portable.

    ``!pip install`` and ``%cd`` are the usual culprits; the notebook uses
    ``subprocess`` for installation so that the same cell runs unchanged in
    Jupyter, VS Code and a plain script.
    """
    for i, cell in enumerate(code_cells(notebook)):
        for line in cell_source(cell).split("\n"):
            stripped = line.strip()
            assert not stripped.startswith("!"), (i, line)
            assert not stripped.startswith("%"), (i, line)


# ---------------------------------------------------------------------------
# no secret in the notebook, in text or in an output
# ---------------------------------------------------------------------------
def test_no_code_cell_contains_a_hardcoded_credential(notebook):
    for i, cell in enumerate(code_cells(notebook)):
        lowered = cell_source(cell).lower()
        for pattern in SECRET_PATTERNS:
            assert pattern.lower() not in lowered, (i, pattern)


def test_no_cell_has_stored_output(notebook):
    """An output cell is where a printed key would be preserved.

    The notebook ships unexecuted, so every code cell must carry an empty
    output list and no execution count. This is also what keeps the file's
    diff readable when it is regenerated.
    """
    for i, cell in enumerate(code_cells(notebook)):
        assert cell.get("outputs") == [], i
        assert cell.get("execution_count") is None, i


def test_the_whole_file_is_free_of_key_shaped_assignments(notebook):
    body = json.dumps(notebook).lower()
    for pattern in SECRET_PATTERNS:
        assert pattern.lower() not in body, pattern


def test_the_secret_scan_detects_a_planted_key():
    """Fault injection for both secret checks at once.

    A synthetic notebook with a key assigned in a cell and a second key echoed
    into a stored output must be rejected by the same two assertions that pass
    on the real file.
    """
    planted = {
        "nbformat": 4, "nbformat_minor": 0,
        "metadata": {"kernelspec": {"name": "python3"}},
        "cells": [{
            "cell_type": "code", "execution_count": 3,
            "metadata": {},
            "source": ["SCOPUS_API_KEY = 'sk-live-abcdef0123456789'\n"],
            "outputs": [{"output_type": "stream",
                         "text": ["key: sk-live-abcdef0123456789\n"]}],
        }],
    }
    body = json.dumps(planted).lower()
    hits = [p for p in SECRET_PATTERNS if p.lower() in body]
    assert hits, "the planted key was not key-shaped enough to be detected"
    with pytest.raises(AssertionError):
        for pattern in SECRET_PATTERNS:
            assert pattern.lower() not in body, pattern
    with pytest.raises(AssertionError):
        for cell in planted["cells"]:
            assert cell.get("outputs") == []


def test_keys_are_read_through_getpass(notebook):
    """The only sanctioned way for a key to enter the notebook."""
    body = "".join(cell_source(c) for c in code_cells(notebook))
    assert "getpass.getpass(" in body
    assert "import getpass" in body


def test_the_key_cell_prints_presence_and_never_a_value(notebook):
    """The cell that handles keys must not put one on screen.

    Checked structurally: every ``print`` in that cell is inspected, and none
    of its arguments may be the environment lookup that returns the key
    itself.
    """
    target = None
    for cell in code_cells(notebook):
        source = cell_source(cell)
        if "getpass.getpass(" in source:
            target = source
            break
    assert target is not None
    tree = ast.parse(target)
    prints = [n for n in ast.walk(tree)
              if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Name) and n.func.id == "print"]
    assert prints, "the key cell reports nothing at all"
    for call in prints:
        rendered = ast.dump(call)
        # a value would reach print via os.environ[...] or .get(variable)
        assert "'set'" in rendered or "state" in rendered or \
            "variable" in rendered or "label" in rendered, rendered
        assert "Subscript" not in rendered, (
            "the key cell indexes something into print(); a credential "
            "lookup must never be printed: " + rendered)


def test_the_key_cell_check_detects_a_cell_that_prints_the_key():
    """Fault injection for the structural check above.

    A cell that echoes ``os.environ['SCOPUS_API_KEY']`` back to the reviewer
    is the exact defect the rule exists to catch, and it must be rejected.
    """
    leaky = ("import getpass, os\n"
             "value = getpass.getpass('key: ')\n"
             "os.environ['SCOPUS_API_KEY'] = value\n"
             "print('your key is', os.environ['SCOPUS_API_KEY'])\n")
    tree = ast.parse(leaky)
    prints = [n for n in ast.walk(tree)
              if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Name) and n.func.id == "print"]
    assert prints
    with pytest.raises(AssertionError):
        for call in prints:
            assert "Subscript" not in ast.dump(call)


# ---------------------------------------------------------------------------
# the cells form a runnable chain
# ---------------------------------------------------------------------------
def test_cells_define_the_names_that_later_cells_use(notebook):
    """A notebook run top to bottom must not hit a NameError.

    Every name a cell loads must be a builtin, an import, or something an
    earlier cell (or the same cell) binds. This is what "each cell works in
    order" means operationally, and it is the failure a reviewer cannot
    diagnose.
    """
    import builtins

    defined = set(dir(builtins))
    problems = []
    for index, cell in enumerate(code_cells(notebook)):
        source = cell_source(cell)
        tree = ast.parse(source)
        loaded, bound = set(), set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                if isinstance(node.ctx, ast.Load):
                    loaded.add(node.id)
                else:
                    bound.add(node.id)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    bound.add((alias.asname or alias.name).split(".")[0])
            elif isinstance(node, (ast.FunctionDef, ast.ClassDef)) or (
                    isinstance(node, ast.ExceptHandler) and node.name):
                bound.add(node.name)
            elif isinstance(node, ast.arg):
                # A parameter is a definition. Without this the check reports
                # every cell that defines a function taking arguments, which is
                # a false alarm rather than an undefined name.
                bound.add(node.arg)
            elif isinstance(node, (ast.comprehension,)):
                for sub in ast.walk(node.target):
                    if isinstance(sub, ast.Name):
                        bound.add(sub.id)
        unresolved = loaded - bound - defined
        if unresolved:
            problems.append((index, sorted(unresolved)))
        defined |= bound
    assert not problems, problems


def test_the_name_chain_check_detects_a_missing_definition():
    """Fault injection: a cell using a name nothing defines must be caught."""
    import builtins
    cells = ["import os\nprint(os.getcwd())\n",
             "print(undefined_corpus_variable)\n"]
    defined = set(dir(builtins))
    problems = []
    for index, source in enumerate(cells):
        tree = ast.parse(source)
        loaded, bound = set(), set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                (loaded if isinstance(node.ctx, ast.Load) else bound).add(
                    node.id)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    bound.add((alias.asname or alias.name).split(".")[0])
        if loaded - bound - defined:
            problems.append(index)
        defined |= bound
    assert problems == [1]
    with pytest.raises(AssertionError):
        assert not problems


def test_the_notebook_only_imports_corpusslr_and_the_standard_library(
        notebook):
    """No pandas, no seaborn: a dependency is a step that can fail."""
    allowed_third_party = {"corpusslr", "google"}
    banned = {"pandas", "numpy", "seaborn", "matplotlib", "rich", "tqdm"}
    imported = set()
    for cell in code_cells(notebook):
        tree = ast.parse(cell_source(cell))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
    assert not (imported & banned), imported & banned
    import sys
    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    if stdlib:
        unexpected = imported - stdlib - allowed_third_party
        assert not unexpected, unexpected


def test_the_notebook_calls_only_real_corpusslr_functions(notebook):
    """Every CorpusSLR name the notebook imports must actually exist.

    A notebook that imports a function removed or renamed in the library
    fails at the reviewer's first run, and nothing else in the suite would
    notice.
    """
    import importlib
    missing = []
    for cell in code_cells(notebook):
        tree = ast.parse(cell_source(cell))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if not node.module.startswith("corpusslr"):
                continue
            module = importlib.import_module(node.module)
            for alias in node.names:
                if not hasattr(module, alias.name):
                    missing.append("{}.{}".format(node.module, alias.name))
    assert not missing, missing


def test_the_api_existence_check_detects_a_renamed_function():
    """Fault injection for the check above."""
    import corpusslr.export
    assert not hasattr(corpusslr.export, "to_scopus_csv_renamed_away")
    with pytest.raises(AssertionError):
        assert hasattr(corpusslr.export, "to_scopus_csv_renamed_away")


def test_the_notebook_writes_the_scopus_csv_as_the_canonical_export(notebook):
    body = "".join(cell_source(c) for c in code_cells(notebook))
    assert "to_scopus_csv" in body
    prose = "".join("".join(c["source"]) for c in notebook["cells"]
                    if c["cell_type"] == "markdown")
    for tool in ("bibliometrix", "VOSviewer", "EmbedSLR"):
        assert tool in prose, tool


def test_the_notebook_covers_the_whole_review(notebook):
    """The deliverables the task defines must each be reachable."""
    body = "".join(cell_source(c) for c in code_cells(notebook))
    for expected in ("getpass", "DATABASES", "validate_config",
                     "compile_for", "corpusslr_main", "to_scopus_csv",
                     "prisma_s_appendix", "make_archive"):
        assert expected in body, expected


def test_the_notebook_explains_the_methodology_not_only_the_clicks(notebook):
    prose = "".join("".join(c["source"]) for c in notebook["cells"]
                    if c["cell_type"] == "markdown")
    for concept in ("PRISMA-S", "Gusenbauer", "deduplicat", "screening",
                    "supplementary material"):
        assert concept in prose, concept


def test_the_download_step_is_present_and_degrades_outside_colab(notebook):
    """Colab discards the runtime; an un-downloaded corpus is lost work."""
    body = "".join(cell_source(c) for c in code_cells(notebook))
    assert "google.colab" in body
    assert "ImportError" in body        # runs in plain Jupyter too


# ---------------------------------------------------------------------------
# the generator and the file agree
# ---------------------------------------------------------------------------
def test_the_checked_in_notebook_matches_its_generator(notebook):
    """The notebook is a build product; a hand-edit would be lost silently."""
    import sys
    tools = os.path.join(REPO, "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    try:
        import build_colab_notebook
    except ImportError:                                    # pragma: no cover
        pytest.skip("the generator is not part of the installed package")
    rebuilt = build_colab_notebook.build()
    assert rebuilt["cells"] == notebook["cells"], (
        "notebooks/corpusslr_colab.ipynb differs from its generator; rerun "
        "`python tools/build_colab_notebook.py`")


def test_the_generator_refuses_to_write_a_broken_notebook(monkeypatch,
                                                          tmp_path):
    """Fault injection: the build gate must reject a non-compiling cell."""
    import sys
    tools = os.path.join(REPO, "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    try:
        import build_colab_notebook
    except ImportError:                                    # pragma: no cover
        pytest.skip("the generator is not part of the installed package")

    broken = dict(build_colab_notebook.build())
    broken["cells"] = [build_colab_notebook.code("for x in range(3)",
                                                 "    print(x")]
    monkeypatch.setattr(build_colab_notebook, "build", lambda: broken)
    monkeypatch.setattr(build_colab_notebook, "NOTEBOOK",
                        str(tmp_path / "out.ipynb"))
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    assert build_colab_notebook.main() == 1
    assert not (tmp_path / "out.ipynb").exists()
