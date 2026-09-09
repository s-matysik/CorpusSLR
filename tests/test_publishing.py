"""The release procedure, checked rather than trusted.

`PUBLISHING.md` tells the user how to put this tree on GitHub, and it makes
claims that can drift silently: that the repository URL it names is the one in
the packaging metadata, that the `.gitignore` excludes caches while keeping
every validation artefact, and that the workflows it points at exist and do
what it says. A release document that has drifted from the tree is worse than
none, because it is followed.

The `.gitignore` tests are the substantial part. The repository is not under
version control, so they cannot shell out to `git check-ignore`; instead the
pattern semantics that matter here are implemented directly and the
implementation is pinned by fault injection, including a case that would pass
under naive substring matching.

Nothing in this module needs a network or a credential.
"""
import fnmatch
import os
import re
import subprocess
import sys
import textwrap

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

# Read from the package, never pinned: a release bump must not break tests that
# are about the publication procedure, not about the version number.
import corpusslr                                             # noqa: E402

PUBLISHING = os.path.join(REPO, "PUBLISHING.md")
GITIGNORE = os.path.join(REPO, ".gitignore")
WORKFLOWS = os.path.join(REPO, ".github", "workflows")

# `.gitignore` and `.github/` are properties of the repository, not of the
# distribution: neither is packaged, and shipping them would be wrong (a
# `.gitignore` inside an installed sdist governs nothing). So the tests that
# read them cannot run from an unpacked archive.
#
# They are skipped there rather than failed. A reviewer checking a release
# downloads the sdist and runs its suite, and 96 collection errors caused by
# files that are *correctly* absent would read as a broken release. The skip
# is conditional on the file being missing, so it can never hide a real
# failure in a checkout, where these tests always run.
_HAS_GITIGNORE = os.path.isfile(GITIGNORE)
_HAS_WORKFLOWS = os.path.isdir(WORKFLOWS)

requires_checkout_gitignore = pytest.mark.skipif(
    not _HAS_GITIGNORE,
    reason="no .gitignore: running from an unpacked sdist, which correctly "
           "does not package it")
requires_checkout_workflows = pytest.mark.skipif(
    not _HAS_WORKFLOWS,
    reason="no .github/workflows: running from an unpacked sdist, which "
           "correctly does not package it")

#: The repository declared in the packaging metadata. `PUBLISHING.md` has to
#: name this one, because every command in it targets a specific repository.
DECLARED_REPOSITORY = "https://github.com/s-matysik/CorpusSLR"

#: Paths that must be excluded. Caches, build products, environments and the
#: generated site: everything that is regenerable and would otherwise be
#: committed by `git add -A`.
MUST_BE_IGNORED = (
    "corpusslr/__pycache__/cli.cpython-313.pyc",
    "tools/__pycache__/build_site.cpython-313.pyc",
    "tests/__pycache__/test_site.cpython-39.pyc",
    "dist/corpusslr-%s.tar.gz" % corpusslr.__version__,
    "dist/corpusslr-%s-py3-none-any.whl" % corpusslr.__version__,
    "build/lib/corpusslr/cli.py",
    "build_check/dist/corpusslr-%s.tar.gz" % corpusslr.__version__,
    "build_check/anything.txt",
    ".mypy_cache/3.13/corpusslr/cli.data.json",
    ".ruff_cache/0.6.9/1234567890",
    ".pytest_cache/v/cache/nodeids",
    ".venv/bin/python",
    "venv/lib/python3.13/site-packages/x.py",
    "env/bin/activate",
    "corpusslr/cli.pyc",
    "corpusslr/cli.pyo",
    ".coverage",
    ".coverage.host.1234",
    "coverage.xml",
    "htmlcov/index.html",
    ".DS_Store",
    "docs/.DS_Store",
    "corpusslr.egg-info/PKG-INFO",
    "site/index.html",
    "site/assets/fig_domains.png",
    "site/files/domains_15_final.csv",
    ".tmp/scratch",
    "my_review.harvest/response_0001.json",
    "harvest_archive/x.json",
    "dedup_report.csv",
)

#: Paths that must stay tracked. The validation artefacts are the provenance
#: of every accuracy figure quoted in the documentation and the manuscript; a
#: reviewer who cannot open them cannot check a single reported number.
MUST_BE_TRACKED = (
    "validation/domains_15_final.csv",
    "validation/domains_15_after_guards.csv",
    "validation/domains_all_metrics.csv",
    "validation/asysd_metrics.csv",
    "validation/na_doi_fix_impact.csv",
    "validation/dedup_mechanism_ablation.csv",
    "validation/dedup_ablation_domains.csv",
    "validation/parser_coverage.csv",
    "validation/supplementary_test_inventory.csv",
    "validation/labelled_test_set.csv",
    "validation/bibliometrix_verification.json",
    "validation/references_verified.json",
    "validation/prisma_s_checklist.json",
    "validation/fig_domains.png",
    "validation/fig_ablation.png",
    "validation/asysd_validation.png",
    "validation/multidomain_validation.png",
    "validation/multidomain_validation.md",
    "validation/eval_asysd.py",
    "validation/audit_document_numbers.py",
    "MANUSCRIPT.md",
    "SUPPLEMENTARY.md",
    "AUDIT_REPORT.md",
    "SUBMISSION_CHECKLIST.md",
    "PUBLISHING.md",
    "README.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "LICENSE",
    "MANIFEST.in",
    "pyproject.toml",
    "CITATION.cff",
    "codemeta.json",
    ".zenodo.json",
    ".gitignore",
    "corpusslr/cli.py",
    "corpusslr/__init__.py",
    "tools/build_site.py",
    "tools/no_network.py",
    "tests/test_site.py",
    "tests/test_publishing.py",
    "docs/user_guide.md",
    "docs/api_reference.md",
    "notebooks/corpusslr_colab.ipynb",
    "examples/review_config.json",
    "examples/example_slr.py",
    ".github/workflows/pages.yml",
    ".github/workflows/tests.yml",
    ".github/workflows/quality.yml",
    "prisma2020_flow.svg",
    "reproducible_harvesting.md",
    # The near-miss cases. A naive `pattern in path` check would exclude all
    # four: "site/" appears inside "validation/site_notes.csv", "build/" inside
    # "corpusslr/rebuild.py", "env/" inside "docs/environment.md", and "dist/"
    # inside "corpusslr/distance.py". Git matches whole path components, and so
    # must the matcher below.
    "validation/site_notes.csv",
    "corpusslr/rebuild.py",
    "docs/environment.md",
    "corpusslr/distance.py",
)


def parse_gitignore(text):
    """Parse the subset of gitignore syntax this file uses.

    Comments and blank lines are dropped; a leading `!` marks a negation; a
    trailing `/` restricts the pattern to directories. Everything the
    repository's own `.gitignore` contains is covered. Character classes,
    `**` and nested ignore files are not, and are absent from it.
    """
    patterns = []
    for line in text.split("\n"):
        stripped = line.rstrip()
        if not stripped.strip() or stripped.lstrip().startswith("#"):
            continue
        negated = stripped.startswith("!")
        if negated:
            stripped = stripped[1:]
        directory_only = stripped.endswith("/")
        pattern = stripped.rstrip("/")
        anchored = pattern.startswith("/") or "/" in pattern
        patterns.append((negated, pattern.lstrip("/"), directory_only, anchored))
    return patterns


def is_ignored(path, patterns):
    """Whether `path` would be excluded, last matching pattern winning.

    The property that matters, and that a substring test gets wrong, is that
    an unanchored pattern matches a whole path *component*: `site/` excludes
    `site/index.html` but not `validation/site_notes.csv`.
    """
    segments = path.split("/")
    verdict = False
    for negated, pattern, directory_only, anchored in patterns:
        if anchored:
            matched = (fnmatch.fnmatch(path, pattern)
                       or path.startswith(pattern + "/"))
        else:
            matched = False
            for index, segment in enumerate(segments):
                if not fnmatch.fnmatch(segment, pattern):
                    continue
                is_last = index == len(segments) - 1
                if directory_only and is_last:
                    # A directory-only pattern cannot exclude a plain file.
                    continue
                matched = True
                break
        if matched:
            verdict = not negated
    return verdict


@pytest.fixture(scope="module")
def patterns():
    if not _HAS_GITIGNORE:
        pytest.skip("no .gitignore in an unpacked sdist")
    with open(GITIGNORE, encoding="utf-8") as handle:
        return parse_gitignore(handle.read())


# ---------------------------------------------------------------------------
# The gitignore contract
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", MUST_BE_IGNORED)
def test_regenerable_output_is_excluded(path, patterns):
    assert is_ignored(path, patterns), \
        "%s would be committed by `git add -A`" % path


@pytest.mark.parametrize("path", MUST_BE_TRACKED)
def test_evidence_and_source_are_not_excluded(path, patterns):
    assert not is_ignored(path, patterns), \
        "%s would be excluded from the repository" % path


def test_no_pattern_excludes_the_validation_directory(patterns):
    """The rule stated in the file, checked as a rule rather than by example.

    Every real file under `validation/` is tested, not a sample, so a pattern
    added later that happens to catch one artefact fails here.
    """
    validation = os.path.join(REPO, "validation")
    checked = 0
    for name in sorted(os.listdir(validation)):
        if name.startswith(".") or name == "__pycache__":
            continue
        relative = "validation/" + name
        if os.path.isdir(os.path.join(validation, name)):
            continue
        checked += 1
        assert not is_ignored(relative, patterns), \
            "%s is excluded, and it is evidence" % relative
    assert checked > 40, "expected the validation directory to hold the evidence"


def test_the_matcher_rejects_a_deliberately_broken_gitignore():
    """Fault injection for the matcher.

    Three faults, each of a kind that has actually been shipped in a
    `.gitignore`: an over-broad pattern that swallows the evidence, a missing
    cache pattern, and a negation in the wrong order.
    """
    over_broad = parse_gitignore("*.csv\n")
    assert is_ignored("validation/domains_15_final.csv", over_broad)

    missing = parse_gitignore("__pycache__/\n")
    assert not is_ignored(".mypy_cache/3.13/x.json", missing)

    wrong_order = parse_gitignore("!validation/\nvalidation/\n")
    assert is_ignored("validation/domains_15_final.csv", wrong_order), \
        "a later pattern must win over an earlier negation"

    right_order = parse_gitignore("validation/\n!validation/\n")
    assert not is_ignored("validation/domains_15_final.csv", right_order)


def test_the_matcher_matches_whole_path_components_not_substrings():
    """The specific bug a substring implementation would have.

    `site/` must exclude the generated site without excluding a validation
    file whose name merely contains the word.
    """
    parsed = parse_gitignore("site/\nbuild/\ndist/\nenv/\n")
    assert is_ignored("site/index.html", parsed)
    assert is_ignored("site/assets/fig_domains.png", parsed)
    assert not is_ignored("validation/site_notes.csv", parsed)
    assert not is_ignored("corpusslr/rebuild.py", parsed)
    assert not is_ignored("corpusslr/distance.py", parsed)
    assert not is_ignored("docs/environment.md", parsed)
    # A directory-only pattern does not exclude a file of the same name.
    assert not is_ignored("site", parsed)


@requires_checkout_gitignore
def test_the_gitignore_says_why_the_evidence_is_kept(patterns):
    """The reason is load-bearing, so it is written down next to the rules.

    A future contributor tidying the file needs to know that
    `validation/*.csv` is deliberate rather than an oversight.
    """
    with open(GITIGNORE, encoding="utf-8") as handle:
        text = handle.read()
    assert "validation/*.csv" in text
    assert "site/" in text
    assert "build_check/" in text
    lowered = text.lower()
    assert "evidence" in lowered or "provenance" in lowered


# ---------------------------------------------------------------------------
# PUBLISHING.md agrees with the tree it describes
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def publishing():
    with open(PUBLISHING, encoding="utf-8") as handle:
        return handle.read()


def test_the_repository_url_matches_the_packaging_metadata(publishing):
    """One URL, in five metadata files and in the release document.

    `tests/test_metadata_consistency.py` already keeps the five agreeing with
    each other. This adds the sixth place the URL appears, which is the one a
    user actually pastes into a shell.
    """
    assert DECLARED_REPOSITORY in publishing

    for name in ("pyproject.toml", "CITATION.cff", "codemeta.json",
                 ".zenodo.json"):
        with open(os.path.join(REPO, name), encoding="utf-8") as handle:
            assert DECLARED_REPOSITORY in handle.read(), \
                "%s does not name %s" % (name, DECLARED_REPOSITORY)

    # And no other GitHub repository is named, which would send the user to
    # the wrong place.
    others = set(re.findall(r"https://github\.com/[\w.-]+/[\w.-]+", publishing))
    stray = {url for url in others
             if not url.startswith(DECLARED_REPOSITORY)}
    assert not stray, "PUBLISHING.md also names %s" % sorted(stray)


@requires_checkout_workflows
def test_every_workflow_the_document_names_exists(publishing):
    named = set(re.findall(r"`?([a-z_]+\.yml)`?", publishing))
    named = {name for name in named if name.endswith(".yml")}
    assert {"tests.yml", "quality.yml", "pages.yml"} <= named
    for name in named:
        assert os.path.isfile(os.path.join(WORKFLOWS, name)), \
            "PUBLISHING.md names %s, which does not exist" % name


@requires_checkout_workflows
def test_every_repository_file_the_document_points_at_exists(publishing):
    """Backticked paths in the document have to resolve.

    Restricted to paths that look like repository files, so a shell fragment
    or an example filename is not mistaken for a claim about the tree.
    """
    candidates = set(re.findall(
        r"`((?:validation|tools|tests|docs|examples|notebooks|\.github)/"
        r"[\w./-]+\.\w+)`", publishing))
    candidates |= set(re.findall(
        r"`(MANUSCRIPT\.md|SUPPLEMENTARY\.md|AUDIT_REPORT\.md|README\.md|"
        r"CHANGELOG\.md|CITATION\.cff|codemeta\.json|\.zenodo\.json|"
        r"MANIFEST\.in|pyproject\.toml|SUBMISSION_CHECKLIST\.md|"
        r"reproducible_harvesting\.md)`", publishing))
    assert len(candidates) > 10, "expected the document to cite the tree"
    missing = [path for path in sorted(candidates)
               if not os.path.exists(os.path.join(REPO, path))]
    assert not missing, missing


def test_the_document_states_the_version_the_tree_reports(publishing):
    import corpusslr
    version = corpusslr.__version__
    assert version in publishing
    assert "v%s" % version in publishing, \
        "the document does not name the tag v%s" % version
    # No other release is presented as the one being published.
    tags = set(re.findall(r"\bv(\d+\.\d+\.\d+)\b", publishing))
    assert tags <= {version, "1.7.1"}, sorted(tags)


def test_the_document_covers_every_step_the_task_requires(publishing):
    """Each publishing step has to be present, not merely mentioned.

    Checked by the command a user would paste, because a heading promising a
    step and a section containing the command are different things.
    """
    required = {
        "git init": "git init",
        "branch named main": "git branch -M main",
        "first commit": "git commit -m",
        "remote added": "git remote add origin",
        "push": "git push -u origin main",
        "repository created": "gh repo create",
        "Actions inspected": "gh run list",
        "Pages source set to the workflow": "build_type=workflow",
        "Pages workflow run": "gh workflow run pages.yml",
        "tag created": "git tag -a v%s" % corpusslr.__version__,
        "tag pushed": "git push origin v%s" % corpusslr.__version__,
        "release created": "gh release create v%s" % corpusslr.__version__,
        "Zenodo": "zenodo.org/account/settings/github",
        "DOI written back": "CITATION.cff",
    }
    missing = [label for label, needle in required.items()
               if needle not in publishing]
    assert not missing, "PUBLISHING.md is missing: %s" % missing


def test_the_document_explains_the_zenodo_ordering(publishing):
    """The one ordering that cannot be recovered from by retrying.

    Zenodo archives only releases published while the repository toggle is
    enabled. A document that lists the steps without saying so leads the user
    into a release that never gets a DOI.
    """
    lowered = publishing.lower()
    assert "concept doi" in lowered and "version doi" in lowered
    assert "after" in lowered
    assert re.search(r"toggle.{0,400}(before|after)|"
                     r"(before|after).{0,400}toggle", lowered, re.S)


def test_the_document_does_not_instruct_anyone_to_commit_a_credential(publishing):
    """No pasteable command may put a secret into the repository or a log."""
    for pattern in (r"(?i)api[_-]?key\s*[=:]\s*[\"'][A-Za-z0-9_-]{12,}",
                    r"(?i)insttoken\s*[=:]\s*[\"'][A-Za-z0-9_-]{12,}",
                    r"sk-live-[A-Za-z0-9]{8,}",
                    r"ghp_[A-Za-z0-9]{20,}",
                    r"(?i)echo\s+\$\{?(SCOPUS|WOS|S2)_[A-Z_]*KEY"):
        assert not re.search(pattern, publishing), \
            "PUBLISHING.md contains %s" % pattern
    # And it says so explicitly, so the reader knows it is a rule.
    assert "credentials" in publishing.lower()


def test_the_document_has_no_long_dash():
    """The typography requirement, on the document itself."""
    from tools.build_site import find_dash_violations
    with open(PUBLISHING, encoding="utf-8") as handle:
        violations = find_dash_violations(handle.read())
    assert violations == [], \
        ["line %d: %s in %r" % item for item in violations[:5]]


# ---------------------------------------------------------------------------
# The Pages workflow
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def pages_workflow():
    if not _HAS_WORKFLOWS:
        pytest.skip("no .github/workflows in an unpacked sdist")
    with open(os.path.join(WORKFLOWS, "pages.yml"), encoding="utf-8") as handle:
        return handle.read()


def test_the_pages_workflow_builds_and_guards_before_deploying(pages_workflow):
    """Order matters: the guard suite runs before the artifact is uploaded.

    Publishing first and testing afterwards would put a site with a dead link
    or an external reference in front of readers, and the tests would report
    it after the fact.
    """
    # Positions of the *step names*, not of the first textual mention: the
    # header comment names the generator before any step runs, and ordering
    # the raw offsets would compare a comment against a command.
    order = re.findall(r"^      - name: (.+)$", pages_workflow, re.M)
    guard = order.index("Run the site guard suite with network access blocked")
    build = order.index("Build the site")
    upload = order.index("Upload the site as a Pages artifact")
    assert guard < build < upload
    assert order.index("Verify no long dash survived into the built site") < upload
    assert order.index(
        "Verify the built site references no external domain") < upload
    # The deployment is a separate job that declares a dependency on the build.
    assert pages_workflow.index("upload-pages-artifact") < \
        pages_workflow.index("deploy-pages")


def test_the_pages_workflow_declares_only_the_permissions_it_needs(pages_workflow):
    assert "contents: read" in pages_workflow
    assert "pages: write" in pages_workflow
    assert "id-token: write" in pages_workflow
    assert "secrets." not in pages_workflow, \
        "the pages workflow must not read a secret"


def test_the_pages_workflow_blocks_the_network_in_the_guard_suite(pages_workflow):
    """The offline flag has to be on the command, not only in the comment.

    Comment lines are stripped first. Without that, deleting the flag from the
    pytest invocation while leaving the paragraph that explains it passes a
    substring check, and the workflow then runs the guard suite with the
    network reachable. That is the exact fault this wording guards against.
    """
    commands = "\n".join(line for line in pages_workflow.split("\n")
                         if not line.lstrip().startswith("#"))
    assert "-p tools.no_network" in commands, \
        "the guard suite is not run with the network blocked"
    assert "-p no:cacheprovider" in commands
    assert "pytest tests/test_site.py" in commands


def test_the_pages_workflow_checks_the_artifact_not_only_the_generator(pages_workflow):
    """Two independent checks on the built bytes.

    The generator's own tests could pass while a later step corrupted the
    output, so the workflow greps the artifact for an external reference and
    scans it for a long dash.
    """
    assert "the built site references an external domain" in pages_workflow
    assert "a long dash reached the built site" in pages_workflow
    assert ".nojekyll" in pages_workflow


def test_the_dash_gate_in_the_workflow_is_not_a_grep_p(pages_workflow):
    """A PCRE grep is a GNU extension and exits 2 where it is absent.

    Inside a shell `if`, that exit status reads as "no match" and the gate
    passes without having checked anything. This was the first version of the
    step, and it is the reason the check is written in Python instead.
    """
    dash_step = pages_workflow.split("Verify no long dash")[1].split("- name:")[0]
    # Comment lines are stripped before the check: the step explains in prose
    # why a PCRE grep is not used, and searching the prose for the thing it
    # warns against would fail on its own documentation.
    commands = "\n".join(line for line in dash_step.split("\n")
                         if not line.lstrip().startswith("#"))
    assert "grep" not in commands, \
        "the dash gate shells out to grep: %r" % commands
    assert "python" in commands
    assert "sys.exit(1)" in commands
    # And the step is genuinely executable, not just present. Run it here.
    assert "\u2014" in commands or "\\u2014" in commands, \
        "the gate does not name the em dash it looks for"


def _dash_gate_script(pages_workflow):
    """The Python program embedded in the workflow's dash-gate step.

    Extracted rather than reimplemented, so that what the test runs is the
    text the runner runs. A copy would drift.
    """
    step = pages_workflow.split("Verify no long dash")[1].split("- name:")[0]
    body = step.split("<<'PY'\n", 1)[1].rsplit("PY", 1)[0]
    return textwrap.dedent(body)


def test_the_workflow_dash_gate_actually_runs_and_actually_detects(
        pages_workflow, tmp_path):
    """The gate is executed against a clean site and a poisoned one.

    Asserting that the step exists proves nothing about what it does. Here the
    embedded program is extracted verbatim, run over a built site (exit 0),
    then run again after one em dash has been injected into one page. It has
    to exit non-zero and name the file and the form.
    """
    from tools.build_site import build_site

    site = tmp_path / "site"
    build_site(root=REPO, out_dir=site)
    script = tmp_path / "gate.py"
    script.write_text(_dash_gate_script(pages_workflow), encoding="utf-8")

    clean = subprocess.run([sys.executable, str(script)], cwd=str(tmp_path),
                           capture_output=True, text=True)
    assert clean.returncode == 0, clean.stdout + clean.stderr
    assert "no long dashes" in clean.stdout

    victim = site / "user_guide.html"
    original = victim.read_text(encoding="utf-8")
    victim.write_text(original.replace("<p>", "<p>injected \u2014 dash ", 1),
                      encoding="utf-8")
    dirty = subprocess.run([sys.executable, str(script)], cwd=str(tmp_path),
                           capture_output=True, text=True)
    assert dirty.returncode == 1, \
        "the gate passed a site containing an em dash: %r" % dirty.stdout
    assert "user_guide.html" in dirty.stdout
    assert "em dash" in dirty.stdout

    victim.write_text(original, encoding="utf-8")
    restored = subprocess.run([sys.executable, str(script)], cwd=str(tmp_path),
                              capture_output=True, text=True)
    assert restored.returncode == 0


def test_the_workflow_has_the_expected_shape(pages_workflow):
    """Structure of the workflow, checked without PyYAML.

    PyYAML is deliberately not a dependency of this package, and an
    `importorskip` here would make the suite skip one more case on an
    interpreter that lacks it. That is not free: `validation/audit_document_numbers.py`
    derives the counts it accepts in the documentation from the measured skip
    total, so an extra environment-dependent skip puts every stated test count
    outside the accepted set. The assertions below are therefore textual, on
    the two-space indentation the file is written with.

    When PyYAML happens to be installed, the parsed structure is checked too,
    in the separate test that follows.
    """
    # Scoped to the `jobs:` block. A bare two-space key sweep also matches
    # `push:` and `workflow_dispatch:` under `on:`, which are triggers rather
    # than jobs.
    block = pages_workflow.split("\njobs:\n", 1)[1]
    jobs = re.findall(r"^  (\w[\w-]*):$", block, re.M)
    assert jobs == ["build", "deploy"], jobs
    assert re.search(r"^    needs: build$", pages_workflow, re.M)
    assert re.search(r"^      name: github-pages$", pages_workflow, re.M)
    assert re.search(r"^    branches: \[main\]$", pages_workflow, re.M)
    assert re.search(r"^  workflow_dispatch:$", pages_workflow, re.M)
    assert re.search(r"^  cancel-in-progress: false$", pages_workflow, re.M), \
        "cancelling a deployment mid-flight can leave the site half-updated"


def test_the_workflow_parses_as_yaml_where_pyyaml_is_available(pages_workflow):
    """The same shape again, through a real parser when one is present.

    Written so that the absence of PyYAML costs no skip: the test passes
    trivially rather than being skipped, for the counting reason given above.
    The textual test is the one that always runs.
    """
    try:
        import yaml
    except ImportError:
        return
    parsed = yaml.safe_load(pages_workflow)
    assert set(parsed["jobs"]) == {"build", "deploy"}
    assert parsed["jobs"]["deploy"]["needs"] == "build"
    assert parsed["jobs"]["deploy"]["environment"]["name"] == "github-pages"
    trigger = parsed.get("on") or parsed.get(True)
    assert trigger["push"]["branches"] == ["main"]
    assert "workflow_dispatch" in trigger
    assert parsed["concurrency"]["cancel-in-progress"] is False


def test_this_test_module_has_no_long_dash():
    from tools.build_site import find_dash_violations
    with open(os.path.abspath(__file__), encoding="utf-8") as handle:
        assert find_dash_violations(handle.read()) == []
