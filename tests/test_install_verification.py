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


@needs_script
@pytest.mark.parametrize("source, version, closed", [
    ("https://github.com/s-matysik/CorpusSLR/archive/refs/tags/v9.9.9.zip", "9.9.9", True),
    ("https://github.com/s-matysik/CorpusSLR/archive/refs/tags/v9.9.9.zip", "9.9.8", False),
    ("https://github.com/s-matysik/CorpusSLR/archive/refs/tags/v9.9.8.zip", "9.9.9", False),
    (".", "9.9.9", False),
])
def test_the_checklist_closes_only_on_a_record_for_the_declared_release(
        tmp_path, source, version, closed):
    (tmp_path / "validation").mkdir()
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "9.9.9"\n')
    (tmp_path / "validation" / "install_verification.json").write_text(
        json.dumps({"source": source, "installed_version": version,
                    "python": "3.13", "verified_on": "2026-01-01T00:00:00Z"}))
    mod = _load("submission_checklist_mod", "validation/submission_checklist.py")
    ok, note = mod.install_item(str(tmp_path))
    assert ok is closed, note


@needs_script
def test_without_a_record_the_item_stays_open(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "9.9.9"\n')
    mod = _load("submission_checklist_mod", "validation/submission_checklist.py")
    ok, note = mod.install_item(str(tmp_path))
    assert ok is False and "verify_install.py" in note


def test_no_document_tells_a_reader_to_install_the_name_from_the_index():
    """`pip install corpusslr` installs whatever holds that name on PyPI."""
    bad = re.compile(r"pip install\s+\"?corpusslr(\[[a-z]+\])?\"?(==\S+)?\s*(#.*)?$")
    offenders = []
    for rel in ("README.md", "docs/user_guide.md", "reproducible_harvesting.md",
                "examples/example_reproducible_harvest.py", "COVER_LETTER.md",
                "MANUSCRIPT.md", "SUPPLEMENTARY.md", "tools/build_data_package.py",
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


def test_every_markdown_file_the_document_builder_reads_ships_in_the_sdist():
    """COVER_LETTER.md was read by tools/build_docx.py but missing from MANIFEST.in.

    The suite passed in a checkout and failed in the unpacked sdist, which is how
    a reviewer or packager runs it; CI caught it on the first push of the release.
    """
    builder = os.path.join(ROOT, "tools", "build_docx.py")
    manifest = os.path.join(ROOT, "MANIFEST.in")
    if not (os.path.exists(builder) and os.path.exists(manifest)):
        pytest.fail("tools/build_docx.py or MANIFEST.in is not in this tree")
    read = set(re.findall(r'os\.path\.join\(HERE,\s*"([A-Za-z_]+\.md)"\)',
                          open(builder, encoding="utf-8").read()))
    assert read, "the pattern found no markdown file; the guard would be vacuous"
    listed = set(re.findall(r"^include\s+(\S+\.md)\s*$",
                            open(manifest, encoding="utf-8").read(), re.M))
    # The submission documents are kept by the author outside the repository
    # (removed from it on 2026-11-20), so the sdist does not ship them.
    local_only = {"COVER_LETTER.md", "MANUSCRIPT.md", "SUPPLEMENTARY.md"}
    assert read - local_only <= listed, sorted(read - local_only - listed)


def test_negative_control_the_manifest_guard_sees_a_missing_file():
    manifest_text = "include README.md\ninclude MANUSCRIPT.md\n"
    listed = set(re.findall(r"^include\s+(\S+\.md)\s*$", manifest_text, re.M))
    assert "COVER_LETTER.md" not in listed
