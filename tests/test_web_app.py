"""Structural guarantees of the browser application bundle.

The behaviour of the page is tested in ``app/test`` (Node, Pyodide, jsdom).
These tests cover what can be checked without a JavaScript runtime: that the
bundle is reproducible, that its manifest matches the files, that the page
loads only what the bundle contains, and that the source never stores a key or
builds HTML from data.
"""
import hashlib
import json
import os
import re
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import build_app                                             # noqa: E402

WEB = ROOT / "app" / "web"
WORKFLOWS = ROOT / ".github" / "workflows"
#: As in tests/test_publishing.py: the workflow files are a property of the
#: checkout, and a source distribution correctly does not package them.
requires_checkout_workflows = pytest.mark.skipif(
    not WORKFLOWS.is_dir(),
    reason="no .github/workflows: running from an unpacked sdist, which "
           "correctly does not package it")


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    out = tmp_path_factory.mktemp("app")
    manifest = build_app.build(out / "a", with_pyodide=False)
    build_app.build(out / "b", with_pyodide=False)
    return out, manifest


def test_the_package_zip_is_byte_for_byte_reproducible(bundle):
    out, _ = bundle
    assert (out / "a" / "corpusslr.zip").read_bytes() == (out / "b" / "corpusslr.zip").read_bytes()


def test_the_manifest_matches_every_file_and_the_package_version(bundle):
    out, manifest = bundle
    on_disk = {str(p.relative_to(out / "a")).replace(os.sep, "/")
               for p in (out / "a").rglob("*") if p.is_file()} - {"manifest.json"}
    assert on_disk == set(manifest["files"])
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((out / "a" / name).read_bytes()).hexdigest() == digest, name
    import corpusslr
    assert manifest["corpusslr"] == corpusslr.__version__
    assert json.loads((out / "a" / "manifest.json").read_text())["files"] == manifest["files"]


def test_the_zip_holds_the_package_and_nothing_else(bundle):
    out, _ = bundle
    names = zipfile.ZipFile(out / "a" / "corpusslr.zip").namelist()
    assert names and all(n.startswith("corpusslr/") and n.endswith(".py") for n in names)
    assert "corpusslr/__init__.py" in names
    assert not any("test" in n.split("/")[-1] for n in names)


def test_every_local_file_the_page_loads_is_in_the_bundle(bundle):
    out, _ = bundle
    html = (WEB / "index.html").read_text(encoding="utf-8")
    local = [u for u in re.findall(r'(?:src|href)="([^"#]+)"', html)
             if not re.match(r"^(https?:)?//", u) and not u.startswith("..")]
    assert "app.js" in local and "app.css" in local
    for u in local:
        assert (out / "a" / u).exists(), u
    for u in re.findall(r'(?:importScripts|fetch)\("([^"]+)"', (WEB / "worker.js").read_text()):
        assert u.startswith("pyodide/") or (out / "a" / u).exists(), u


def test_the_page_declares_a_restrictive_content_security_policy():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    csp = re.search(r'Content-Security-Policy" content="([^"]+)"', html).group(1)
    assert "default-src 'self'" in csp and "object-src 'none'" in csp
    assert "'unsafe-inline'" not in csp
    hosts = set(re.findall(r"https://[^\s;]+", csp))
    assert hosts == {"https://api.openalex.org", "https://api.crossref.org",
                     "https://eutils.ncbi.nlm.nih.gov", "https://api.semanticscholar.org",
                     "https://api.elsevier.com", "https://api.biorxiv.org"}


# --- source guards; each is shown below to catch the error it exists for -----
STORAGE = re.compile(r"localStorage|sessionStorage|indexedDB|document\.cookie|caches\.open")
HTML_SINKS = re.compile(r"\.innerHTML\s*=|\.outerHTML\s*=|insertAdjacentHTML|document\.write|\beval\(|new Function\(")


def _scan(pattern, text):
    code = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    code = re.sub(r"(?m)^\s*//.*$", "", code)
    return pattern.findall(code)


@pytest.mark.parametrize("path", [WEB / "app.js", WEB / "worker.js", ROOT / "app" / "proxy" / "worker.js"])
def test_the_page_stores_nothing_and_builds_no_html_from_data(path):
    text = path.read_text(encoding="utf-8")
    assert _scan(STORAGE, text) == [], "a key or a record must not be persisted"
    assert _scan(HTML_SINKS, text) == [], "data must be inserted as text"


@pytest.mark.parametrize("injected, pattern", [
    ('localStorage.setItem("k", key);', STORAGE),
    ('document.cookie = "k=" + key;', STORAGE),
    ('node.innerHTML = record.title;', HTML_SINKS),
    ('eval(reply);', HTML_SINKS),
])
def test_the_source_guards_catch_the_errors_they_exist_for(injected, pattern):
    clean = (WEB / "app.js").read_text(encoding="utf-8")
    assert _scan(pattern, clean) == []
    assert _scan(pattern, clean + "\n" + injected + "\n") != []


def test_a_comment_that_names_a_forbidden_call_is_not_a_violation():
    assert _scan(HTML_SINKS, "// never use innerHTML = here\n/* eval( */") == []


def test_the_app_files_contain_no_absolute_local_paths_and_no_long_dashes():
    for p in list((ROOT / "app" / "web").glob("*")) + list((ROOT / "app" / "py").glob("*.py")) \
            + list((ROOT / "app" / "test").glob("*.mjs")) + list((ROOT / "app" / "proxy").glob("*")):
        text = p.read_text(encoding="utf-8")
        assert "/Users/" not in text and "claude-science" not in text, p
        assert "\u2014" not in text and "\u2013" not in text, p


@requires_checkout_workflows
def test_the_documentation_site_stays_free_of_scripts_because_the_app_is_a_separate_root():
    """The site guard rejects any <script>. The app needs one, so it must be
    built and deployed under its own path, not inside the generated site."""
    wf = (WORKFLOWS / "pages.yml").read_text(encoding="utf-8")
    assert "tools/build_app.py" in wf
    assert re.search(r"site\s+--include='\*\.html'", wf) or "site --include" in wf
    assert "_pages/app" in wf
