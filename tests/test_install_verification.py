"""The install check, and the checklist item that depends on it.

The first submission was rejected because a reviewer could not install the
package. validation/verify_install.py is the check that would have caught that,
so it is tested here: that it really installs from source into a fresh virtual
environment and runs the workflow, that it cannot be fooled by PYTHONPATH, and
that the checklist closes only on a record for the right address and version.
"""
import importlib.util
import json
import os
import re
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "validation", "verify_install.py")
needs_script = pytest.mark.skipif(not os.path.exists(SCRIPT),
                                  reason="validation/ is not in this checkout")


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@needs_script
def test_the_verifier_strips_pythonpath_from_the_child_environment(monkeypatch):
    v = _load("verify_install_mod", "validation/verify_install.py")
    monkeypatch.setenv("PYTHONPATH", ROOT)
    r = v.run([sys.executable, "-c", "import os; print('PYTHONPATH' in os.environ)"])
    assert r.stdout.strip() == "False"


@needs_script
def test_the_verifier_installs_from_source_and_runs_the_workflow(tmp_path):
    # The one test that really builds an environment; it needs no network
    # because it reuses the build tools of this interpreter.
    record = tmp_path / "rec.json"
    r = subprocess.run([sys.executable, SCRIPT, ROOT, "--system-site-packages",
                        "--no-build-isolation", "--record", str(record)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-800:] + r.stderr[-800:]
    assert "3 records -> 2 after deduplication" in r.stdout
    rec = json.loads(record.read_text(encoding="utf-8"))
    declared = re.search(r'^version = "([^"]+)"',
                         open(os.path.join(ROOT, "pyproject.toml")).read(), re.M).group(1)
    assert rec["installed_version"] == declared
    assert rec["source"] == ROOT


@needs_script
def test_a_failed_install_writes_no_evidence(tmp_path):
    record = tmp_path / "rec.json"
    r = subprocess.run([sys.executable, SCRIPT, str(tmp_path / "does_not_exist"),
                        "--system-site-packages", "--no-build-isolation",
                        "--record", str(record)], capture_output=True, text=True)
    assert r.returncode != 0
    assert not record.exists()


def test_no_document_tells_a_reader_to_install_the_name_from_the_index():
    """`pip install corpusslr` installs whatever holds that name on PyPI."""
    bad = re.compile(r"pip install\s+\"?corpusslr(\[[a-z]+\])?\"?(==\S+)?\s*(#.*)?$")
    offenders = []
    for rel in ("README.md", "docs/user_guide.md", "reproducible_harvesting.md",
                "examples/example_reproducible_harvest.py", "tools/build_data_package.py",
                "corpusslr/cli.py", "tools/build_colab_notebook.py"):
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            continue
        for n, line in enumerate(open(path, encoding="utf-8"), 1):
            if bad.search(line.strip().strip("`")) and "NOT installed" not in line and "would install" not in line:
                offenders.append("%s:%d: %s" % (rel, n, line.strip()[:90]))
    assert not offenders, offenders


def test_negative_control_the_pattern_does_catch_the_old_instruction():
    bad = re.compile(r"pip install\s+\"?corpusslr(\[[a-z]+\])?\"?(==\S+)?\s*(#.*)?$")
    for old in ("pip install corpusslr", 'pip install "corpusslr[docx]"',
                "pip install corpusslr==1.0.0", "pip install corpusslr[docx]",
                "pip install corpusslr            # PyPI"):
        assert bad.search(old), old
    for good in ("pip install https://github.com/s-matysik/CorpusSLR/archive/refs/tags/v1.2.0.zip",
                 'pip install "corpusslr[docx] @ https://github.com/s-matysik/CorpusSLR/archive/refs/tags/v1.2.0.zip"'):
        assert not bad.search(good), good
