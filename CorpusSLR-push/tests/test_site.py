"""The documentation site, checked as an artefact rather than trusted.

`tools/build_site.py` renders the repository markdown to a static site that has
to satisfy four promises the build itself makes. Each promise gets a test, and
each test is paired with fault injection, because a check that has only ever
seen correct input has not been shown to detect anything:

* every source document becomes an HTML file with a `<title>`;
* every internal link resolves to a file, or to a fragment, that exists in the
  built site - a published dead cross-reference is a defect;
* nothing references an external domain, because the requirement is that the
  site renders opened straight from disk with no network at all;
* no long dash survives anywhere in the output, while `--dry-run` inside a
  code span survives intact, since a mangled command is a worse defect than a
  typographic one.

The converter itself is tested separately on the constructs the repository
uses: pipe tables with alignment, fenced code, nested lists, bold containing a
nested italic (which the first version of the converter got wrong and emitted
as literal asterisks), and inline code shielding markup from interpretation.

The whole module is offline by construction: it reads files and writes to a
pytest temporary directory. It is compatible with `pytest -p tools.no_network`,
under which any socket use would raise.
"""
import os
import re
import sys
from html.parser import HTMLParser

import pytest

import corpusslr

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from tools.build_site import (  # noqa: E402
    CSS, DASH_PATTERNS, EVIDENCE_OUTPUT, PAGES, SiteBuildError, build_site,
    collect_headings, find_dash_violations, markdown_to_html, normalize_dashes,
    render_inline, slugify)

#: Read from the package, never pinned: a release bump must not break
#: tests that are about the site, not about the version number.
_VERSION = corpusslr.__version__

#: Elements that carry no closing tag, so the well-formedness walker below
#: must not expect one.
VOID_ELEMENTS = frozenset(
    ("area", "base", "br", "col", "embed", "hr", "img", "input", "link",
     "meta", "param", "source", "track", "wbr"))

#: A rendered site must not reference any of these. `//` catches the
#: protocol-relative form, which is an external reference without a scheme.
EXTERNAL_PREFIXES = ("http://", "https://", "//", "data:", "ftp://")

#: Patterns that would mean the generator leaked a credential into a page.
#:
#: The useful signal is an *assignment of a key-shaped value*, not the name of
#: a parameter. The documentation legitimately writes `api_key=KEY` and
#: `ScopusSource(api_key="...")` as placeholders, and AUDIT_REPORT.md discusses
#: the `?apikey=` URL parameter by name; a scan on those substrings alone
#: reports all three and is therefore useless. Each pattern below requires at
#: least twelve characters of key-shaped value after the assignment, which no
#: placeholder in the repository satisfies, plus the `sk-` vendor prefix that
#: appears in real Elsevier and Clarivate keys.
SECRET_PATTERNS = (
    r"sk-live-[A-Za-z0-9_-]{8,}",
    r"(?i)(?:api[_-]?key|insttoken|apikey|token|secret|password)"
    r"\s*[=:]\s*[\"'][A-Za-z0-9_-]{12,}[\"']",
    r"(?i)(?:SCOPUS_API_KEY|SCOPUS_INSTTOKEN|WOS_API_KEY|S2_API_KEY)"
    r"\s*[=:]\s*[\"'][^\"']{8,}[\"']",
    r"AKIA[0-9A-Z]{16}",
    r"ghp_[A-Za-z0-9]{20,}",
)


def _secret_hits(text):
    """Every credential-shaped assignment in `text`."""
    hits = []
    for pattern in SECRET_PATTERNS:
        hits += [match.group(0) for match in re.finditer(pattern, text)]
    return hits


# ---------------------------------------------------------------------------
# Fixtures: the site is built once and inspected many times.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def site(tmp_path_factory):
    """Build the real site into a temporary directory.

    Module-scoped because the build copies the validation artefacts, and doing
    that once per test would dominate the suite's runtime for no extra
    coverage. The repository tree is never written to.
    """
    out = tmp_path_factory.mktemp("site")
    report = build_site(root=REPO, out_dir=out)
    return report, out


@pytest.fixture(scope="module")
def pages(site):
    """Map of output file name to its HTML text."""
    _report, out = site
    return {path.name: path.read_text(encoding="utf-8")
            for path in sorted(out.glob("*.html"))}


# ---------------------------------------------------------------------------
# One HTML file per document, each with a title
# ---------------------------------------------------------------------------

def test_every_source_document_produces_a_page(site):
    report, out = site
    expected = [page.output for page in PAGES] + [EVIDENCE_OUTPUT]
    assert report["pages"] == expected
    for name in expected:
        target = out / name
        assert target.is_file(), "%s was not written" % name
        assert target.stat().st_size > 0, "%s is empty" % name


def test_the_source_documents_named_by_the_generator_all_exist():
    """The page list is data, so a renamed document must fail loudly here.

    `build_site` raises on a missing source, but only when it is run. This
    test states the same requirement without a build, so the failure names the
    document rather than surfacing as a build error.
    """
    for page in PAGES:
        assert os.path.isfile(os.path.join(REPO, page.source)), \
            "%s is listed in PAGES but does not exist" % page.source


@pytest.mark.parametrize("name", [page.output for page in PAGES] + [EVIDENCE_OUTPUT])
def test_each_page_has_a_non_empty_title(pages, name):
    match = re.search(r"<title>(.*?)</title>", pages[name], re.S)
    assert match is not None, "%s has no <title> element" % name
    title = match.group(1).strip()
    assert title, "%s has an empty <title>" % name
    assert "CorpusSLR" in title, "%s title does not identify the project" % name


def test_a_title_is_escaped_rather_than_inserted_raw(tmp_path):
    """Heading text reaches `<title>`, so it has to be escaped on the way.

    A document whose H1 contains a markup character would otherwise emit a
    `<title>` that closes early and leaks the rest of the heading into the
    document head. The synthetic corpus below carries exactly that heading,
    because none of the real documents does and an unescaped title would
    therefore never be noticed.
    """
    root = tmp_path / "repo"
    (root / "corpusslr").mkdir(parents=True)
    (root / "corpusslr" / "__init__.py").write_text(
        '__version__ = "9.9.9"\n', encoding="utf-8")
    (root / "validation").mkdir()
    for page in PAGES:
        path = root / page.source
        path.parent.mkdir(parents=True, exist_ok=True)
        heading = page.nav_title
        if page.source == "docs/user_guide.md":
            heading = "Guide <script>x</script> & \"quoted\" 5 < 6"
        path.write_text("# %s\n\nBody.\n" % heading, encoding="utf-8")

    out = tmp_path / "site"
    build_site(root=root, out_dir=out)
    text = (out / "user_guide.html").read_text(encoding="utf-8")
    head = text.split("</head>")[0]
    assert "<script" not in head.lower(), "a title leaked a script element"
    title = re.search(r"<title>(.*?)</title>", text, re.S).group(1)
    assert "&lt;script&gt;" in title
    assert "&amp;" in title
    assert "<" not in title and ">" not in title


def test_the_title_names_the_release_exactly_once(pages):
    """A doubled version in a title is what happens when a document already

    carries it in its own H1. SUPPLEMENTARY.md does, so the generator has to
    detect that rather than append unconditionally.
    """
    for name, text in pages.items():
        title = re.search(r"<title>(.*?)</title>", text, re.S).group(1)
        assert title.count(_VERSION) <= 1, \
            "%s names the version %d times: %r" % (
                name, title.count(_VERSION), title)


@pytest.mark.parametrize("name", [page.output for page in PAGES] + [EVIDENCE_OUTPUT])
def test_each_page_declares_its_charset_and_viewport(pages, name):
    text = pages[name]
    assert '<meta charset="utf-8" />' in text
    assert 'name="viewport"' in text
    assert text.lstrip().startswith("<!DOCTYPE html>")


@pytest.mark.parametrize("name", [page.output for page in PAGES] + [EVIDENCE_OUTPUT])
def test_each_page_is_well_formed(pages, name):
    """Tags nest and close.

    A hand-written converter's characteristic failure is an unbalanced element
    - a `<li>` left open by a dedent, a `<table>` never closed when the rows
    run out - and a browser hides it by repairing the tree silently. The
    walker below does not repair.
    """
    class Walker(HTMLParser):
        def __init__(self):
            HTMLParser.__init__(self, convert_charrefs=True)
            self.stack = []
            self.errors = []

        def handle_starttag(self, tag, attrs):
            if tag not in VOID_ELEMENTS:
                self.stack.append((tag, self.getpos()))

        def handle_endtag(self, tag):
            if tag in VOID_ELEMENTS:
                return
            if not self.stack:
                self.errors.append("</%s> with nothing open at %r"
                                   % (tag, self.getpos()))
                return
            if self.stack[-1][0] != tag:
                self.errors.append(
                    "</%s> at %r closes <%s> opened at %r"
                    % (tag, self.getpos(), self.stack[-1][0], self.stack[-1][1]))
                self.stack.pop()
                return
            self.stack.pop()

    walker = Walker()
    walker.feed(pages[name])
    walker.close()
    assert not walker.errors, "%s: %s" % (name, walker.errors[:5])
    assert not walker.stack, \
        "%s leaves open: %s" % (name, [tag for tag, _ in walker.stack[:5]])


def test_the_wellformedness_walker_rejects_an_unbalanced_document():
    """Fault injection for the check above.

    Without this, a walker that never reported anything would pass every page.
    """
    class Walker(HTMLParser):
        def __init__(self):
            HTMLParser.__init__(self, convert_charrefs=True)
            self.stack = []
            self.errors = []

        def handle_starttag(self, tag, attrs):
            if tag not in VOID_ELEMENTS:
                self.stack.append(tag)

        def handle_endtag(self, tag):
            if tag in VOID_ELEMENTS:
                return
            if not self.stack or self.stack[-1] != tag:
                self.errors.append(tag)
                return
            self.stack.pop()

    walker = Walker()
    walker.feed("<div><ul><li>one</ul></div>")
    walker.close()
    assert walker.errors or walker.stack, \
        "the walker accepted a document with a <li> left open"


# ---------------------------------------------------------------------------
# Internal links resolve
# ---------------------------------------------------------------------------

def _links(text):
    return re.findall(r'href="([^"]+)"', text)


def _ids(text):
    return set(re.findall(r'id="([^"]+)"', text))


def test_every_internal_link_points_at_something_that_exists(site, pages):
    """File targets and fragment targets, both checked.

    README.md links to `docs/user_guide.md#5a-the-canonical-output-scopus-csv`.
    Rewriting the file part without also producing that anchor would leave a
    link that lands on the right page at the wrong place, which no file-level
    check would catch.
    """
    _report, out = site
    ids_by_page = {name: _ids(text) for name, text in pages.items()}
    dangling = []
    for name, text in pages.items():
        for href in _links(text):
            if href.startswith(EXTERNAL_PREFIXES) or href.startswith("mailto:"):
                continue
            target, _, fragment = href.partition("#")
            target = target or name
            if not (out / target).exists():
                dangling.append("%s -> %s (no such file)" % (name, href))
            elif fragment and target.endswith(".html") \
                    and fragment not in ids_by_page.get(target, set()):
                dangling.append("%s -> %s (no such anchor)" % (name, href))
    assert not dangling, dangling


def test_the_link_check_detects_an_injected_dead_link(site, pages):
    """Fault injection for the resolver above.

    The same resolution logic is run against a page whose link has been
    rewritten to a file that was never generated, and against one whose
    fragment does not exist. Both must be reported.
    """
    _report, out = site
    ids_by_page = {name: _ids(text) for name, text in pages.items()}

    def resolve(name, href):
        target, _, fragment = href.partition("#")
        target = target or name
        if not (out / target).exists():
            return "missing file"
        if fragment and target.endswith(".html") \
                and fragment not in ids_by_page.get(target, set()):
            return "missing anchor"
        return None

    assert resolve("index.html", "user_guide.html") is None
    assert resolve("index.html", "no_such_page.html") == "missing file"
    assert resolve("index.html",
                   "user_guide.html#a-section-that-was-never-written") \
        == "missing anchor"


def test_an_unresolvable_source_link_fails_the_build(tmp_path):
    """A link to a document not published as a page must stop the build.

    The generator resolves links through a map built from PAGES; anything
    outside it is an unresolved reference. Warning about that and publishing
    anyway is how a dead link reaches a reader.
    """
    root = tmp_path / "repo"
    (root / "corpusslr").mkdir(parents=True)
    (root / "corpusslr" / "__init__.py").write_text(
        '__version__ = "9.9.9"\n', encoding="utf-8")
    (root / "validation").mkdir()
    for page in PAGES:
        path = root / page.source
        path.parent.mkdir(parents=True, exist_ok=True)
        body = "# %s\n\nBody text.\n" % page.nav_title
        if page.source == "README.md":
            body += "\nSee [the missing guide](docs/not_a_page.md).\n"
        path.write_text(body, encoding="utf-8")

    with pytest.raises(SiteBuildError) as excinfo:
        build_site(root=root, out_dir=tmp_path / "out")
    assert "unresolved" in str(excinfo.value)
    assert "not_a_page.md" in str(excinfo.value)


def test_the_navigation_bar_links_only_to_generated_pages(pages):
    generated = set(pages)
    for name, text in pages.items():
        nav = re.search(r'<nav class="site">(.*?)</nav>', text, re.S)
        assert nav is not None, "%s has no navigation bar" % name
        hrefs = set(re.findall(r'href="([^"]+)"', nav.group(1)))
        assert hrefs <= generated, \
            "%s navigates to pages that were not built: %s" % (name, hrefs - generated)
        assert len(hrefs) == len(PAGES) + 1


def test_every_page_marks_itself_as_the_current_navigation_entry(pages):
    for name, text in pages.items():
        nav = re.search(r'<nav class="site">(.*?)</nav>', text, re.S).group(1)
        current = re.findall(r'href="([^"]+)"[^>]*aria-current="page"', nav)
        assert current == [name], \
            "%s marks %r as current" % (name, current)


# ---------------------------------------------------------------------------
# Nothing external: the site has to work offline, opened from a file
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", [page.output for page in PAGES] + [EVIDENCE_OUTPUT])
def test_no_page_references_an_external_domain(pages, name):
    """The offline requirement, checked at the level it can be violated.

    Every `src` and `href` is inspected. An address appearing in the prose is
    fine and is rendered as monospace text; an address appearing as a
    *reference* is not, because opening the page without a network would then
    show a broken image or offer a link that cannot be followed.
    """
    text = pages[name]
    referenced = re.findall(r'(?:src|href)="([^"]+)"', text)
    external = [url for url in referenced if url.startswith(EXTERNAL_PREFIXES)]
    assert not external, "%s references %s" % (name, external)


@pytest.mark.parametrize("name", [page.output for page in PAGES] + [EVIDENCE_OUTPUT])
def test_no_page_loads_a_script_a_stylesheet_or_a_font(pages, name):
    """The stated build constraints, as assertions.

    No JavaScript, no external stylesheet, no web font, no CSS `url()` -
    which would be a fetch even when it points at a relative path, and there
    is nothing in this site that needs one.
    """
    text = pages[name]
    assert not re.search(r"<script", text, re.I), "%s contains a script" % name
    assert not re.search(r"<link[^>]+rel=[\"']stylesheet", text, re.I), \
        "%s links an external stylesheet" % name
    assert "@import" not in text, "%s imports a stylesheet" % name
    assert "@font-face" not in text, "%s declares a web font" % name
    assert not re.findall(r"url\(", text), "%s fetches a CSS resource" % name
    assert "<style>" in text, "%s has no inlined stylesheet" % name


def test_the_external_reference_check_detects_an_injected_cdn_link():
    """Fault injection for the two checks above."""
    injected = ('<html><head><link rel="stylesheet" '
                'href="https://cdn.example.org/style.css" />'
                '<script src="https://cdn.example.org/app.js"></script>'
                "</head><body><img src=\"//cdn.example.org/x.png\" /></body></html>")
    referenced = re.findall(r'(?:src|href)="([^"]+)"', injected)
    external = [url for url in referenced if url.startswith(EXTERNAL_PREFIXES)]
    assert len(external) == 3, external
    assert re.search(r"<script", injected, re.I)
    assert re.search(r"<link[^>]+rel=[\"']stylesheet", injected, re.I)


def test_the_stylesheet_itself_is_self_contained():
    assert "@import" not in CSS
    assert "@font-face" not in CSS
    assert not re.findall(r"url\(", CSS)
    assert "http" not in CSS


def test_the_site_renders_from_a_file_url(site):
    """Relative references only, so the tree can be opened from disk.

    A leading slash would resolve against the filesystem root when the page is
    opened as a `file://` URL, so an absolute path is a defect even though it
    works when served over HTTP.
    """
    _report, out = site
    for path in sorted(out.glob("*.html")):
        text = path.read_text(encoding="utf-8")
        for url in re.findall(r'(?:src|href)="([^"]+)"', text):
            if url.startswith("#") or url.startswith(EXTERNAL_PREFIXES):
                continue
            assert not url.startswith("/"), \
                "%s uses the absolute path %r" % (path.name, url)
            assert (out / url.partition("#")[0]).exists(), \
                "%s references %r which is not in the built tree" % (path.name, url)


def test_the_pages_marker_is_written(site):
    """GitHub Pages runs Jekyll unless told not to."""
    _report, out = site
    assert (out / ".nojekyll").is_file()


def test_referenced_assets_are_copied_into_the_site(site):
    _report, out = site
    evidence = (out / EVIDENCE_OUTPUT).read_text(encoding="utf-8")
    images = re.findall(r'<img src="([^"]+)"', evidence)
    assert images, "the evidence page shows no figure"
    for src in images:
        assert (out / src).is_file(), "%s was not copied" % src
    assert (out / "files").is_dir()
    assert (out / "assets").is_dir()
    assert (out / "files" / "review_config.json").is_file()


def test_the_large_validation_input_is_named_rather_than_published(site):
    """A 4 MB gold-standard corpus does not belong in a documentation site.

    It has to stay visible, though, so the evidence page names it with its
    size. Silently dropping an evidence file is the failure mode this guards.
    """
    report, out = site
    assert "labelled_test_set.csv" in report["evidence_skipped"]
    assert not (out / "files" / "labelled_test_set.csv").exists()
    evidence = (out / EVIDENCE_OUTPUT).read_text(encoding="utf-8")
    assert "labelled_test_set.csv" in evidence


# ---------------------------------------------------------------------------
# Typography: no long dash anywhere in the output, and code left alone
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", [page.output for page in PAGES] + [EVIDENCE_OUTPUT])
def test_no_long_dash_survives_into_the_generated_html(pages, name):
    """The user requirement, checked on the artefact rather than the source.

    The source documents contain 307 em dashes, 24 en dashes and both ASCII
    substitutes, so this is a transformation being verified, not an absence
    being restated.
    """
    violations = find_dash_violations(pages[name])
    assert not violations, \
        "%s: %s" % (name, ["line %d: %s in %r" % v for v in violations[:5]])


def test_the_dash_check_detects_every_form_it_claims_to():
    """Fault injection for the check above, one injected form at a time."""
    for label, needle in DASH_PATTERNS:
        page = "<p>a text%sb text</p>" % needle
        hits = find_dash_violations(page)
        assert hits, "the check missed an injected %s" % label
        assert any(name == label for _line, name, _text in hits), \
            "an injected %s was reported as %r" % (label, [h[1] for h in hits])
    assert find_dash_violations("<p>a - b, and a-b, and --dry-run</p>") == []


def test_an_injected_dash_fails_the_build(tmp_path):
    """The build must refuse to publish a page carrying a long dash.

    Reported rather than repaired: `normalize_dashes` runs on every text run,
    so a dash reaching the output means a rendering path bypassed it, and that
    is a defect in the generator rather than in the document.
    """
    root = tmp_path / "repo"
    (root / "corpusslr").mkdir(parents=True)
    (root / "corpusslr" / "__init__.py").write_text(
        '__version__ = "9.9.9"\n', encoding="utf-8")
    (root / "validation").mkdir()
    for page in PAGES:
        path = root / page.source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# %s\n\nBody text.\n" % page.nav_title, encoding="utf-8")

    # Sanity: the corpus above builds cleanly, so the failure below is caused
    # by the injection and not by the synthetic repository.
    build_site(root=root, out_dir=tmp_path / "clean")

    import tools.build_site as module
    original = module.normalize_dashes
    module.normalize_dashes = lambda text: text  # the bypass being simulated
    try:
        (root / "README.md").write_text(
            "# Overview\n\nA sentence \u2014 with an em dash.\n", encoding="utf-8")
        with pytest.raises(SiteBuildError) as excinfo:
            build_site(root=root, out_dir=tmp_path / "dirty")
        assert "long dashes" in str(excinfo.value)
    finally:
        module.normalize_dashes = original


def test_command_line_flags_keep_their_double_hyphen(pages):
    """The one place a double hyphen must survive.

    `--dry-run` is an instruction the reader pastes into a shell. Normalizing
    it to `-dry-run` would publish a command that fails, so code is excluded
    from the dash pass and this test proves the exclusion is in effect.
    """
    import html as html_module
    found = {}
    for name, text in pages.items():
        for span in re.findall(r"<code[^>]*>(.*?)</code>", text, re.S):
            plain = html_module.unescape(span)
            for flag in re.findall(r"--[a-z][a-z-]+", plain):
                found.setdefault(flag, name)
    assert "--dry-run" in found, "the --dry-run flag lost its double hyphen"
    assert "--scopus" in found
    assert len(found) >= 8, sorted(found)


def test_the_normalizer_maps_each_form_to_a_single_hyphen():
    """The four forms, each mapped to one hyphen, plus what must not change.

    The ASCII runs are composed from `TWO` and `THREE` rather than written
    literally, so that this module's own source satisfies the typography rule
    it enforces. `test_this_test_module_has_no_long_dash` depends on that.
    """
    two = "-" * 2
    three = "-" * 3
    assert normalize_dashes("a \u2014 b") == "a - b"
    assert normalize_dashes("3.9\u20133.13") == "3.9-3.13"
    assert normalize_dashes("a " + two + " b") == "a - b"
    assert normalize_dashes("a " + three + " b") == "a - b"
    assert normalize_dashes("well-known") == "well-known"
    assert normalize_dashes("--dry-run") == "--dry-run"
    assert normalize_dashes("0.94\u20131.00 recall") == "0.94-1.00 recall"
    assert find_dash_violations(normalize_dashes(
        "a \u2014 b \u2013 c " + two + " d " + three + " e")) == []


def test_the_converter_removes_dashes_from_a_document_that_has_them():
    """Guards against the output check becoming vacuous.

    The output check asserts that no rendered page carries a long dash. That
    assertion proves nothing on its own if the sources are already clean, and
    they now are: tools/normalize_dashes.py was run across the repository, so
    counting dashes in the shipped documents is no longer evidence of anything.

    The property worth pinning is the converter's behaviour, not the current
    state of the tree, so this feeds it a document that does contain every
    forbidden form and asserts the rendered HTML contains none. It stays
    meaningful whether or not the repository is clean.
    """
    two = "-" * 2
    three = "-" * 3
    source = (
        "# Heading with an em dash \u2014 here\n\n"
        "A paragraph with an en dash 2015\u20132024 and a minus \u22120.0036.\n\n"
        "| column | value |\n|---|---|\n| range | 0.94\u20131.00 |\n\n"
        "- a bullet \u2014 with a break\n\n"
        "Text with a literal " + two + " and " + three + " run.\n\n"
        "```\ncorpusslr dedup --dry-run --export-format scopus\n```\n")
    assert source.count("\u2014") + source.count("\u2013") >= 3
    html, _headings, _unresolved = markdown_to_html(source)
    assert find_dash_violations(html) == [], (
        "the converter left a forbidden dash in the rendered page")
    assert "--dry-run" in html and "--export-format" in html, (
        "command-line flags inside a code block must survive untouched")


# ---------------------------------------------------------------------------
# No secrets
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", [page.output for page in PAGES] + [EVIDENCE_OUTPUT])
def test_no_page_carries_anything_credential_shaped(pages, name):
    hits = _secret_hits(pages[name])
    assert not hits, "%s contains %s" % (name, hits)


def test_the_generator_does_not_read_the_environment(monkeypatch, tmp_path):
    """A page cannot leak a key the generator never looks at.

    The check is behavioural rather than textual: credential-shaped variables
    are planted in the environment, the site is built, and every page is
    searched for the planted values. A generator that interpolated
    `os.environ` anywhere would fail here.
    """
    planted = {
        "SCOPUS_API_KEY": "sk-live-planted-scopus-0123456789",
        "SCOPUS_INSTTOKEN": "planted-insttoken-abcdef",
        "WOS_API_KEY": "planted-wos-key-987654",
        "S2_API_KEY": "planted-s2-key-135790",
        "CORPUSSLR_CONTACT_EMAIL": "planted@example.invalid",
    }
    for key, value in planted.items():
        monkeypatch.setenv(key, value)

    out = tmp_path / "site"
    build_site(root=REPO, out_dir=out)
    for path in sorted(out.glob("*.html")):
        text = path.read_text(encoding="utf-8")
        for key, value in planted.items():
            assert value not in text, \
                "%s leaked the value of %s" % (path.name, key)


def test_the_secret_scan_detects_a_planted_credential():
    """Fault injection for the textual scan above, in both directions.

    The negative cases matter as much as the positive ones: the scan has to
    fire on a planted key while staying silent on the placeholders the
    documentation actually contains, or it would be switched off within a
    week for crying wolf.
    """
    planted = (
        "<p>Set <code>SCOPUS_API_KEY = 'sk-live-abcdef0123456789'</code>.</p>",
        "<code>ScopusSource(api_key=\"7f3c9a1e4b8d2f6a0c5e\")</code>",
        "<code>insttoken: 'abcdef0123456789abcdef'</code>",
        "<code>AKIAIOSFODNN7EXAMPLE</code>",
    )
    for page in planted:
        assert _secret_hits(page), "the scan missed a planted key in %r" % page

    benign = (
        "<p>Set <code>SCOPUS_API_KEY</code> in the environment.</p>",
        "<code>ScopusSource(api_key=KEY, insttoken=TOKEN, view=\"COMPLETE\")</code>",
        "<code>ScopusSource(api_key=\"...\")</code>",
        "<p>the <code>?apikey=</code> URL parameter</p>",
        "<code>WosStarterSource(api_key=KEY)</code>",
    )
    for page in benign:
        assert _secret_hits(page) == [], \
            "the scan reported a false positive on %r" % page


# ---------------------------------------------------------------------------
# The markdown converter, on the constructs the repository uses
# ---------------------------------------------------------------------------

def test_a_pipe_table_becomes_a_table_with_the_declared_alignment():
    source = (
        "| area | files | tests |\n"
        "|---|---:|---:|\n"
        "| File-format parsers | 10 | 254 |\n"
        "| Command-line interface | 1 | 164 |\n"
    )
    html_out, _headings, unresolved = markdown_to_html(source)
    assert unresolved == []
    assert html_out.count("<tr>") == 3
    # Counted with the delimiter, because a bare "<th" also matches "<thead>".
    assert len(re.findall(r"<th[ >]", html_out)) == 3
    assert len(re.findall(r"<td[ >]", html_out)) == 6
    assert "<th>area</th>" in html_out
    assert '<th style="text-align:right">files</th>' in html_out
    assert '<td style="text-align:right">254</td>' in html_out
    assert "<thead>" in html_out and "<tbody>" in html_out


def test_a_table_cell_may_contain_a_pipe_inside_inline_code():
    """The row splitter has to respect code spans.

    README.md contains rows whose cells hold shell fragments, and a naive
    split on `|` would break them into extra columns. This is the shape that
    made the splitter protect code spans before splitting.
    """
    source = (
        "| command | flags |\n"
        "|---|---|\n"
        "| `export` | `--scopus a | b` is canonical |\n"
    )
    html_out, _headings, _unresolved = markdown_to_html(source)
    body = html_out.split("<tbody>")[1]
    assert body.count("<td") == 2, html_out
    assert "--scopus a | b" in body


def test_a_fenced_code_block_keeps_its_text_verbatim():
    source = (
        "Run it:\n\n"
        "```bash\n"
        "corpusslr run -c review_config.json --dry-run\n"
        "corpusslr export corpus.json --scopus out.csv  # a & b < c\n"
        "```\n"
    )
    html_out, _headings, _unresolved = markdown_to_html(source)
    assert '<pre><code class="language-bash">' in html_out
    assert "--dry-run" in html_out
    assert "&amp;" in html_out and "&lt;" in html_out
    assert "<em>" not in html_out


def test_a_code_block_is_not_dash_normalized():
    source = "```\nrun --flag a \u2014 b\n```\n"
    html_out, _headings, _unresolved = markdown_to_html(source)
    assert "--flag" in html_out
    # The em dash inside the block would violate the typography requirement,
    # so the build-level check reports it. That is the intended split of
    # responsibility: the converter never rewrites code, and the build refuses
    # to publish a document whose code carries a long dash.
    assert find_dash_violations(html_out)


def test_an_unterminated_code_fence_does_not_swallow_the_rest_silently():
    source = "# Title\n\n```python\nprint(1)\n"
    html_out, headings, _unresolved = markdown_to_html(source)
    assert headings[0][2] == "Title"
    assert "<pre><code" in html_out
    assert html_out.rstrip().endswith("</code></pre>")


def test_a_nested_list_nests():
    source = (
        "- top one\n"
        "  - nested a\n"
        "  - nested b\n"
        "- top two\n"
        "  1. ordered inner\n"
        "  2. ordered inner two\n"
        "- top three\n"
    )
    html_out, _headings, _unresolved = markdown_to_html(source)
    assert html_out.count("<ul>") == 2
    assert html_out.count("</ul>") == 2
    assert html_out.count("<ol>") == 1
    assert html_out.count("</ol>") == 1
    assert html_out.count("<li>") == 7
    assert html_out.count("</li>") == 7
    # The inner list opens inside the item that owns it.
    assert re.search(r"<li>top one\s*<ul>", html_out)
    assert re.search(r"<li>top two\s*<ol>", html_out)


def _list_depths(html_out):
    """Nesting depth of each list item, keyed by its text.

    Tag counts are not enough to check nesting. A dedent handler that closes
    one level instead of all of them still emits balanced, well-formed markup:
    the item simply ends up in the wrong list. This walker records the list
    depth at which each item actually sits, which is the property that breaks.
    """
    depths = {}

    class Walker(HTMLParser):
        def __init__(self):
            HTMLParser.__init__(self, convert_charrefs=True)
            self.depth = 0
            self.pending = None

        def handle_starttag(self, tag, attrs):
            if tag in ("ul", "ol"):
                self.depth += 1
            elif tag == "li":
                self.pending = self.depth

        def handle_endtag(self, tag):
            if tag in ("ul", "ol"):
                self.depth -= 1

        def handle_data(self, data):
            if self.pending is not None and data.strip():
                depths[data.strip()] = self.pending
                self.pending = None

    walker = Walker()
    walker.feed(html_out)
    walker.close()
    return depths


def test_a_list_dedenting_two_levels_at_once_closes_both():
    """The dedent has to unwind every level it skipped.

    Written against nesting depth rather than tag counts, because a handler
    that closes only the innermost level produces balanced output in which
    `d` is nested inside the list `c` belongs to. Counting tags cannot see
    that; this can.
    """
    source = (
        "- a\n"
        "  - b\n"
        "    - c\n"
        "- d\n"
    )
    html_out, _headings, _unresolved = markdown_to_html(source)
    assert html_out.count("<ul>") == html_out.count("</ul>") == 3
    assert html_out.count("<li>") == html_out.count("</li>") == 4
    assert html_out.rstrip().endswith("</ul>")
    depths = _list_depths(html_out)
    assert depths == {"a": 1, "b": 2, "c": 3, "d": 1}, depths


def test_a_nested_list_places_each_item_at_its_own_depth():
    source = (
        "- top one\n"
        "  - nested a\n"
        "- top two\n"
        "  1. ordered inner\n"
        "- top three\n"
    )
    html_out, _headings, _unresolved = markdown_to_html(source)
    depths = _list_depths(html_out)
    assert depths == {"top one": 1, "nested a": 2, "top two": 1,
                      "ordered inner": 2, "top three": 1}, depths


def test_an_ordered_list_is_rendered_as_an_ordered_list():
    source = "1. first\n2. second\n3. third\n"
    html_out, _headings, _unresolved = markdown_to_html(source)
    assert html_out.startswith("<ol>")
    assert html_out.count("<li>") == 3
    assert "<ul>" not in html_out


def test_bold_italic_inline_code_and_nested_emphasis():
    assert render_inline("**bold**") == "<strong>bold</strong>"
    assert render_inline("*italic*") == "<em>italic</em>"
    assert render_inline("_italic_") == "<em>italic</em>"
    assert render_inline("`code`") == "<code>code</code>"
    # The case the first version of the converter got wrong: bold whose body
    # contains an italic, which appears in validation/multidomain_validation.md
    # and was emitted as literal asterisks.
    assert render_inline("**slightly *helps***") == \
        "<strong>slightly <em>helps</em></strong>"
    assert "*" not in render_inline("**slightly *helps***")


def test_inline_code_shields_markup_from_interpretation():
    assert render_inline("`**not bold**`") == "<code>**not bold**</code>"
    assert render_inline("`<record>`") == "<code>&lt;record&gt;</code>"
    assert render_inline("`a | b`") == "<code>a | b</code>"


def test_literal_angle_brackets_in_prose_are_escaped_not_rendered():
    """`<record>` appears unfenced in README.md and must not become an element."""
    out = render_inline("the <record> element and 5 < 6")
    assert "&lt;record&gt;" in out
    assert "<record>" not in out


def test_a_python_signature_with_star_args_is_left_alone():
    """`**kw` is not bold, and turning it into one would corrupt the API page."""
    out = render_inline("`get(url, params=None, **kw)` - see source")
    assert "**kw" in out
    assert "<strong>" not in out


def test_a_heading_gets_the_fragment_the_repository_already_links_to():
    assert slugify("5a. The canonical output: Scopus CSV") == \
        "5a-the-canonical-output-scopus-csv"
    assert slugify("What the file contains, and what it deliberately does not") == \
        "what-the-file-contains-and-what-it-deliberately-does-not"
    assert slugify("`EID` is never empty") == "eid-is-never-empty"
    assert slugify("Result \u2014 shipped defaults") == "result-shipped-defaults"


def test_repeated_heading_text_gets_distinct_fragments():
    """CHANGELOG.md repeats `### Fixed` under every release."""
    source = "## 1.7.0\n\n### Fixed\n\n## 1.6.0\n\n### Fixed\n"
    html_out, headings, _unresolved = markdown_to_html(source)
    slugs = [slug for _level, slug, _text in headings]
    assert len(slugs) == len(set(slugs)), slugs
    assert "fixed" in slugs and "fixed-1" in slugs
    assert html_out.count('id="fixed"') == 1


def test_a_horizontal_rule_is_a_rule_and_not_a_heading_underline():
    """AUDIT_REPORT.md uses `---` as a separator 13 times, always after a blank
    line, so it is a rule rather than a setext underline."""
    source = "Paragraph one.\n\n---\n\nParagraph two.\n"
    html_out, headings, _unresolved = markdown_to_html(source)
    assert "<hr />" in html_out
    assert headings == []
    assert html_out.count("<p>") == 2


def test_a_block_quote_is_rendered_as_one():
    source = "> quoted line one\n> quoted line two\n"
    html_out, _headings, _unresolved = markdown_to_html(source)
    assert html_out.startswith("<blockquote>")
    assert html_out.rstrip().endswith("</blockquote>")
    assert "quoted line one quoted line two" in html_out


def test_headings_are_collected_with_their_levels():
    source = "# One\n\n## Two\n\n### Three\n\nText.\n"
    headings = collect_headings(source)
    assert [(level, text) for level, _slug, text in headings] == \
        [(1, "One"), (2, "Two"), (3, "Three")]


def test_a_contents_list_appears_only_on_a_long_page(pages):
    """Six or more second and third level headings, or no contents list.

    A four-heading page does not need one, and the API reference at 175
    headings would be swamped by a full-depth list, so only levels 2 and 3 are
    listed.
    """
    assert '<div class="toc">' in pages["api_reference.html"]
    assert '<div class="toc">' in pages["user_guide.html"]
    for name, text in pages.items():
        if '<div class="toc">' not in text:
            continue
        toc = re.search(r'<div class="toc">(.*?)</div>', text, re.S).group(1)
        entries = re.findall(r'href="#([^"]+)"', toc)
        assert len(entries) >= 6, "%s has a contents list with %d entries" \
            % (name, len(entries))
        ids = _ids(text)
        assert all(entry in ids for entry in entries), \
            "%s contents list points at a missing anchor" % name


def test_an_empty_document_produces_a_page_rather_than_a_crash():
    html_out, headings, unresolved = markdown_to_html("")
    assert html_out == ""
    assert headings == []
    assert unresolved == []


def test_a_link_to_a_published_document_is_rewritten_to_its_page():
    link_map = {"docs/user_guide.md": "user_guide.html"}
    out = render_inline("see [the guide](docs/user_guide.md#5a-x)",
                        link_map=link_map)
    assert 'href="user_guide.html#5a-x"' in out


def test_an_external_link_is_rendered_as_text_with_its_address():
    """No off-site reference, and the address stays readable.

    CHANGELOG.md links to keepachangelog.com. The site must not point at it,
    because it has to work offline, but dropping the address would lose
    information the reader may want.
    """
    out = render_inline("[Keep a Changelog](https://keepachangelog.com/en/1.1.0/)")
    assert "href=" not in out
    assert "keepachangelog.com/en/1.1.0/" in out
    assert "Keep a Changelog" in out


def test_a_bare_address_in_prose_is_shown_but_not_linked():
    out = render_inline("compare at https://github.com/s-matysik/CorpusSLR/releases")
    assert "href=" not in out
    assert "github.com/s-matysik/CorpusSLR/releases" in out
    assert "<code>" in out


# ---------------------------------------------------------------------------
# The build report is data the caller can act on
# ---------------------------------------------------------------------------

def test_the_build_report_carries_measured_counts(site):
    report, _out = site
    assert report["version"] == _VERSION
    assert report["unresolved_links"] == {}
    assert report["dash_violations"] == {}
    assert report["evidence_copied"] > 30
    headings = report["headings"]
    assert headings["api_reference.html"] > 100
    assert all(count > 0 for count in headings.values())


def test_the_version_shown_on_the_page_is_the_package_version(pages):
    import corpusslr
    for name, text in pages.items():
        assert corpusslr.__version__ in text, \
            "%s does not name the package version" % name


def test_building_twice_into_the_same_directory_is_idempotent(tmp_path):
    out = tmp_path / "site"
    first = build_site(root=REPO, out_dir=out)
    before = {path.name: path.read_bytes() for path in sorted(out.glob("*.html"))}
    second = build_site(root=REPO, out_dir=out, clean=True)
    after = {path.name: path.read_bytes() for path in sorted(out.glob("*.html"))}
    assert first["pages"] == second["pages"]
    assert before == after


def test_the_command_line_entry_point_reports_what_it_wrote(tmp_path, capsys):
    from tools.build_site import main
    code = main(["--out", str(tmp_path / "site"), "--clean"])
    assert code == 0
    out = capsys.readouterr().out
    assert "wrote 8 pages" in out
    assert "index.html" in out
    assert "no long dashes" in out
    assert find_dash_violations(out) == []


def test_the_entry_point_returns_a_failure_code_on_a_broken_build(tmp_path, capsys):
    root = tmp_path / "repo"
    (root / "corpusslr").mkdir(parents=True)
    (root / "corpusslr" / "__init__.py").write_text(
        '__version__ = "9.9.9"\n', encoding="utf-8")
    (root / "validation").mkdir()
    (root / "README.md").write_text("# Overview\n", encoding="utf-8")
    from tools.build_site import main
    code = main(["--root", str(root), "--out", str(tmp_path / "site")])
    assert code == 1
    assert "site build failed" in capsys.readouterr().err


def test_the_generator_source_itself_has_no_long_dash():
    """The typography requirement covers the code that enforces it.

    The generator's own docstrings and comments are text this project
    produces, so they are held to the same rule. The literal dash characters
    the module has to name are defined as escapes rather than written out,
    which is why this can be checked mechanically.
    """
    path = os.path.join(REPO, "tools", "build_site.py")
    text = open(path, encoding="utf-8").read()
    assert find_dash_violations(text) == []


def test_this_test_module_has_no_long_dash():
    path = os.path.abspath(__file__)
    text = open(path, encoding="utf-8").read()
    assert find_dash_violations(text) == []
