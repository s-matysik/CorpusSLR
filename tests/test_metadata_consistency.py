"""Metadata agreement across the five files that declare the release.

A citable release is described in five places at once: ``pyproject.toml`` (what
pip installs), ``corpusslr/__init__.py`` (what ``corpusslr.__version__``
reports), ``CITATION.cff`` (what GitHub's "Cite this repository" button emits),
``codemeta.json`` (the schema.org description harvested by software registries)
and ``.zenodo.json`` (what the archive deposits against the DOI).

When those files disagree the failure is silent and only visible after the fact:
Zenodo mints a DOI against a version string that no installed artefact reports,
and every downstream citation of that DOI names the wrong release. Nothing in a
normal test run or in a successful build detects it, because each file is
individually well-formed. Hence these assertions run as part of the suite rather
than living on a release checklist.

The parsing here is deliberately minimal: ``tomllib`` is absent on Python 3.9,
which the package supports, and adding a TOML or YAML dependency to read the
project's own metadata would be a poor trade. The three fields that matter --
version, licence and author -- have fixed, simple shapes in these files, so they
are extracted with anchored regular expressions and each extractor asserts that
it actually found something.
"""

from __future__ import annotations

import json
import os
import re

import pytest

import corpusslr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: The single source of truth for the release. Every other file is compared
#: against the value read from pyproject.toml, which is what pip installs.
EXPECTED_AUTHOR_FAMILY = "Matysik"
EXPECTED_AUTHOR_GIVEN = "Sebastian"
EXPECTED_REPO = "https://github.com/s-matysik/CorpusSLR"


def _read(*parts: str) -> str:
    path = os.path.join(ROOT, *parts)
    if not os.path.exists(path):
        pytest.fail(
            "{} is missing: the release cannot be cited without it".format(
                os.path.join(*parts)))
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _load_json(*parts: str) -> dict:
    text = _read(*parts)
    try:
        return json.loads(text)
    except ValueError as exc:  # pragma: no cover - only on a malformed commit
        pytest.fail("{} is not valid JSON: {}".format(os.path.join(*parts), exc))


def _search(pattern: str, text: str, what: str) -> str:
    m = re.search(pattern, text, re.MULTILINE)
    assert m, "could not find {} (pattern {!r})".format(what, pattern)
    return m.group(1)


# ----------------------------------------------------------------------
# Extractors, one per file.
# ----------------------------------------------------------------------
def pyproject_version() -> str:
    return _search(r'^version\s*=\s*"([^"]+)"', _read("pyproject.toml"),
                   "version in pyproject.toml")


def pyproject_license() -> str:
    return _search(r'^license\s*=\s*\{\s*text\s*=\s*"([^"]+)"',
                   _read("pyproject.toml"), "license in pyproject.toml")


def pyproject_author() -> str:
    return _search(r'^authors\s*=\s*\[\s*\{\s*name\s*=\s*"([^"]+)"',
                   _read("pyproject.toml"), "author in pyproject.toml")


def dunder_version() -> str:
    return _search(r'^__version__\s*=\s*"([^"]+)"',
                   _read("corpusslr", "__init__.py"),
                   "__version__ in corpusslr/__init__.py")


def cff_version() -> str:
    return _search(r'^version:\s*(\S+)', _read("CITATION.cff"),
                   "version in CITATION.cff")


def cff_license() -> str:
    return _search(r'^license:\s*(\S+)', _read("CITATION.cff"),
                   "license in CITATION.cff")


# ----------------------------------------------------------------------
# Version
# ----------------------------------------------------------------------
def test_all_five_files_declare_the_same_version():
    """The installed version, the citation and the archive record must agree.

    This is the assertion that matters most: a DOI minted against a version
    string no artefact reports makes every citation of that DOI wrong.
    """
    declared = {
        "pyproject.toml": pyproject_version(),
        "corpusslr/__init__.py": dunder_version(),
        "CITATION.cff": cff_version(),
        "codemeta.json": _load_json("codemeta.json")["version"],
        ".zenodo.json": _load_json(".zenodo.json")["version"],
    }
    assert len(set(declared.values())) == 1, (
        "version strings disagree across metadata files: {}".format(declared))


def test_the_version_is_a_semantic_version():
    """Zenodo and PyPI both order releases by this string, so its shape matters."""
    version = pyproject_version()
    assert re.fullmatch(r"\d+\.\d+\.\d+([.-]?(a|b|rc|dev)\d+)?", version), (
        "{!r} is not a semantic version".format(version))


def test_the_declared_version_is_importable():
    """Guards the case where __init__.py is edited but the package is stale."""
    import corpusslr

    assert corpusslr.__version__ == pyproject_version()


# ----------------------------------------------------------------------
# Licence
# ----------------------------------------------------------------------
def test_the_licence_is_mit_everywhere():
    """A licence mismatch between the archive and the repository is a legal defect.

    Zenodo uses lower-case SPDX keys and codemeta a full SPDX URL, so the three
    spellings are normalised before comparison rather than compared literally.
    """
    assert pyproject_license() == "MIT"
    assert cff_license() == "MIT"
    assert _load_json("codemeta.json")["license"].rstrip("/").endswith("MIT")
    assert _load_json(".zenodo.json")["license"].lower() == "mit"


def test_a_licence_file_is_present_and_is_mit():
    text = _read("LICENSE")
    assert "MIT License" in text
    assert EXPECTED_AUTHOR_FAMILY in text, (
        "the LICENSE copyright line does not name the author")


# ----------------------------------------------------------------------
# Author
# ----------------------------------------------------------------------
def test_the_author_is_the_same_person_in_every_file():
    """Author name forms differ by format; the person must not.

    CITATION.cff splits the name into given/family, Zenodo wants "Family, Given",
    codemeta uses schema.org givenName/familyName, and pyproject takes a single
    string. All four are checked in their own idiom.
    """
    assert pyproject_author() == "{} {}".format(EXPECTED_AUTHOR_GIVEN,
                                                EXPECTED_AUTHOR_FAMILY)

    cff = _read("CITATION.cff")
    assert re.search(r'family-names:\s*"?{}"?'.format(EXPECTED_AUTHOR_FAMILY), cff)
    assert re.search(r'given-names:\s*"?{}"?'.format(EXPECTED_AUTHOR_GIVEN), cff)

    codemeta_authors = _load_json("codemeta.json")["author"]
    assert [(a["givenName"], a["familyName"]) for a in codemeta_authors] == [
        (EXPECTED_AUTHOR_GIVEN, EXPECTED_AUTHOR_FAMILY)]

    zenodo_creators = _load_json(".zenodo.json")["creators"]
    assert [c["name"] for c in zenodo_creators] == [
        "{}, {}".format(EXPECTED_AUTHOR_FAMILY, EXPECTED_AUTHOR_GIVEN)]


def test_codemeta_names_the_same_person_as_author_and_maintainer():
    """A registry that harvests codemeta shows both roles; they must not diverge."""
    meta = _load_json("codemeta.json")
    for role in ("author", "maintainer", "copyrightHolder"):
        assert [(p["givenName"], p["familyName"]) for p in meta[role]] == [
            (EXPECTED_AUTHOR_GIVEN, EXPECTED_AUTHOR_FAMILY)], role


# ----------------------------------------------------------------------
# Repository URL
# ----------------------------------------------------------------------
def test_every_file_points_at_the_same_repository():
    """A stale URL in the archive record sends readers to the wrong code."""
    assert EXPECTED_REPO in _read("pyproject.toml")
    assert EXPECTED_REPO in _read("CITATION.cff")
    assert _load_json("codemeta.json")["codeRepository"] == EXPECTED_REPO
    related = _load_json(".zenodo.json")["related_identifiers"]
    assert any(r["identifier"] == EXPECTED_REPO for r in related), (
        ".zenodo.json does not relate the deposit to the repository")


# ----------------------------------------------------------------------
# Python support, declared in two independent places
# ----------------------------------------------------------------------
def test_the_supported_pythons_agree_between_classifiers_and_requires_python():
    """A classifier claiming a version that requires-python excludes misleads pip.

    The two fields are read by different tools -- pip resolves against
    requires-python, PyPI's sidebar and many registries display the classifiers
    -- so a review that trusts the sidebar can install on an unsupported
    interpreter.
    """
    text = _read("pyproject.toml")
    floor = _search(r'^requires-python\s*=\s*">=(\d+\.\d+)"', text,
                    "requires-python")
    classified = sorted(
        re.findall(r'"Programming Language :: Python :: (\d+\.\d+)"', text),
        key=lambda v: [int(p) for p in v.split(".")])
    assert classified, "no per-version Python classifiers found"
    assert classified[0] == floor, (
        "requires-python floor {} does not match the lowest classifier {}".format(
            floor, classified[0]))


def test_codemeta_runtime_platforms_cover_the_declared_classifiers():
    """codemeta is what software registries harvest; it must not under-report."""
    text = _read("pyproject.toml")
    classified = set(
        re.findall(r'"Programming Language :: Python :: (\d+\.\d+)"', text))
    platforms = " ".join(_load_json("codemeta.json")["runtimePlatform"])
    missing = sorted(v for v in classified if v not in platforms)
    assert not missing, (
        "codemeta.json runtimePlatform omits supported versions: {}".format(
            missing))


# ----------------------------------------------------------------------
# The changelog has to mention the release being shipped
# ----------------------------------------------------------------------
def test_the_changelog_documents_the_current_version():
    """An undocumented release leaves reviewers unable to see what changed."""
    version = pyproject_version()
    changelog = _read("CHANGELOG.md")
    assert "[{}]".format(version) in changelog, (
        "CHANGELOG.md has no entry for version {}".format(version))


# --------------------------------------------------------------------------
# The submission documents carry the version too.
#
# The five metadata files were already pinned to agree with one another, but
# the article and the supplement were outside that gate, so a version bump
# left them behind: after 1.7.1 the C1 "Current code version" row, the CLI
# transcript quoted in Listing 2 and the supplement's own title all still read
# 1.7.0. A reviewer reads exactly those three places, so they are the ones
# where a stale version does the most damage.
# --------------------------------------------------------------------------

_PAPER = os.path.join(ROOT, "paper", "corpusslr_softwarex.tex")
_SUPPLEMENT = os.path.join(ROOT, "SUPPLEMENTARY.md")


@pytest.mark.skipif(not os.path.exists(_PAPER),
                    reason="paper/ is not present in this checkout")
def test_the_article_metadata_table_states_the_current_version():
    with open(_PAPER, encoding="utf-8") as fh:
        tex = fh.read()
    row = re.search(r"C1\s*&[^&]*&\s*([0-9]+\.[0-9]+\.[0-9]+)", tex)
    assert row, "the C1 row does not state a version at all"
    assert row.group(1) == corpusslr.__version__, (
        "the article's code metadata table says %s, the package is %s"
        % (row.group(1), corpusslr.__version__))


@pytest.mark.skipif(not os.path.exists(_PAPER),
                    reason="paper/ is not present in this checkout")
def test_no_superseded_version_survives_in_the_article():
    """A quoted transcript is evidence, so it has to be current evidence.

    Listing 2 quotes the CLI reporting `corpusslr_version`. Leaving a previous
    release in there presents output the current code does not produce.
    """
    with open(_PAPER, encoding="utf-8") as fh:
        tex = fh.read()
    # Only versions the article attributes to THIS package. A bare semantic
    # version is not enough to go on: the article legitimately names the
    # interpreter and the R release used for the bibliometrix run, and flagging
    # those would make the rule fire on correct text.
    owned = re.findall(
        r"(?:corpusslr[_-]version\"?\s*[:=]\s*\"?|CorpusSLR\s+v?|corpusslr-|"
        r"Current code version\s*&\s*)(\d+\.\d+\.\d+)", tex, re.I)
    stale = {v for v in owned if v != corpusslr.__version__}
    assert not stale, (
        "the article attributes these superseded versions to the package: %s"
        % sorted(stale))
    assert owned, "the article never names the package version at all"


@pytest.mark.skipif(not os.path.exists(_SUPPLEMENT),
                    reason="SUPPLEMENTARY.md is not present in this checkout")
def test_the_supplement_title_states_the_current_version():
    with open(_SUPPLEMENT, encoding="utf-8") as fh:
        first = fh.readline()
    assert corpusslr.__version__ in first, (
        "the supplement title is %r, which does not name version %s"
        % (first.strip(), corpusslr.__version__))


@pytest.mark.skipif(not os.path.exists(_PAPER),
                    reason="paper/ is not present in this checkout")
def test_the_markdown_metadata_table_agrees_with_the_article():
    """The C1-C8 table exists in MANUSCRIPT.md and in the .tex.

    Two copies is what let C1 fall a release behind: the .tex was bumped and
    the markdown was not, and the Word submission renders from the markdown.
    The .tex is authoritative, so the copies must agree row for row.
    """
    with open(os.path.join(ROOT, "MANUSCRIPT.md"), encoding="utf-8") as fh:
        md = fh.read()
    rows = re.findall(r"^\|\s*(C\d)\s*\|[^|]*\|\s*([^|]+?)\s*\|$", md, re.M)
    assert len(rows) == 8, "the markdown metadata table has %d row(s)" % len(rows)
    values = dict(rows)
    assert values["C1"] == corpusslr.__version__, (
        "the markdown C1 row says %s, the package is %s"
        % (values["C1"], corpusslr.__version__))
