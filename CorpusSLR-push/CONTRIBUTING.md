# Contributing to CorpusSLR

CorpusSLR is used to produce the identification phase of published systematic
reviews. A defect here does not raise an exception in someone's notebook - it
silently changes how many studies a review reports finding, and it does so
months before anyone reads the manuscript. The conventions below follow from
that, and the most important of them is the first.

## The rules that matter most

1. **No test may touch the network.** Every source client is exercised against
   the HTTP doubles in `tests/conftest.py`. This is not a style preference: a
   suite that reaches live APIs produces results that depend on the day it ran,
   which destroys the reproducibility claim the package exists to support. The
   rule is enforced mechanically - `tools/no_network.py` replaces the standard
   library's socket connect primitives with raising stubs, and continuous
   integration runs the whole suite under it.
2. **The code must run on Python 3.9.** `requires-python` is `>=3.9` and the
   test matrix runs there, because institutional research environments are slow
   to upgrade and a reviewer who cannot install the package cannot check it.
3. **Every accuracy figure in documentation must come from a measurement.** The
   numbers in `README.md`, `AUDIT_REPORT.md` and `CHANGELOG.md` trace to a file
   under `validation/`. Do not write a figure you have not computed, and do not
   round one in a direction that flatters the package.

## Running the tests

The suite is offline, deterministic and takes a few seconds.

```sh
python -m pip install -e ".[docx,dev]"
python -m pytest tests
```

`python-docx` is optional at run time, but install it for development: without
it the PRISMA-S `.docx` test is skipped, and a skipped test silently stops
covering `prisma_s.py`.

To reproduce what continuous integration does, including the network guard and
the coverage floor:

```sh
PYTHONPATH=. python -m pytest tests \
  -p tools.no_network \
  --cov=corpusslr --cov-report=term-missing --cov-fail-under=95
```

Coverage currently stands at 98 %. The floor in CI is 95 %, which leaves room
for a legitimately hard-to-reach branch without letting a whole module go
untested.

### Testing on Python 3.9

If your default interpreter is newer, create a 3.9 environment before opening a
pull request. A change that uses `match`, `tomllib`, `str.removeprefix` or the
`dict | dict` operator passes on your machine and fails for a third of the
matrix. Every module begins with `from __future__ import annotations`, which is
what makes modern annotation syntax safe on 3.9 - keep that line when adding a
module.

## Static analysis

Both tools are configured in `pyproject.toml`, so your local run and CI apply
the same rules:

```sh
python -m ruff check .
python -m mypy corpusslr
```

Both are expected to report nothing. The configuration blocks record why each
rule set was chosen; two points are worth restating here.

**The ruff selection excludes rules that would reflow existing code** - 
formatting, import ordering, and pyupgrade's annotation rewrites. The package
is a released instrument whose published accuracy figures are tied to specific
revisions, and a mass reflow would bury behavioural changes in review noise.
`UP` in particular cannot be applied at all while 3.9 is supported, since it
rewrites annotations to 3.10+ syntax. Two rules are excluded with a stated
reason rather than silently: `B904` (28 sites where a `requests` exception is
deliberately not chained, because `SourceError` carries the message the user
needs) and `B023` (8 sites where a helper defined inside a per-record loop is
called only within the iteration that defines it, so late binding cannot
manifest).

**mypy runs at its defaults plus `check_untyped_defs`**, not `--strict`. The
distinction is deliberate. `--disallow-untyped-defs` reports 70 findings that
all say "this function lacks annotations"; `check_untyped_defs` instead makes
mypy analyse the bodies of unannotated functions, so the gate catches genuine
type contradictions across the whole package - an `int` assigned to a `str`
field, a nullable `Match` dereferenced without a guard. Both of those were real
defects found when the level was first enabled. `python_version` is pinned to
`3.10` only because mypy 2.x refuses to target 3.9; the 3.9 guarantee is
enforced by running the suite on the 3.9 interpreter itself.

## Writing tests

- Put the expected behaviour in the test, then make the code satisfy it. If the
  library does not yet behave correctly, mark the test `xfail(strict=True)` with
  the reason. A strict marker fails the run once the test starts passing, which
  forces the marker to be removed and makes it impossible to leave a known
  defect quietly marked. The suite currently contains **no** `xfail`.
- `tests/conftest.py` provides `FakeSession` and `FakeResponse`. `FakeSession`
  takes either a list of responses or a callable `(url, params, headers)`, and
  records every call in `.calls`, so you can assert on the request that was
  made, not only on the parsed result. The `no_sleep` fixture neutralises
  rate-limit delays.
- When you verify behaviour against a live API, do it ad hoc and then translate
  the finding into a double. Record what you measured in `AUDIT_REPORT.md` - the
  measured API limits documented there (Scopus page-size maxima, the offset
  ceiling, the `LANGUAGE()` name requirement) are all findings that no offline
  test could have produced, and they are the reason the doubles are accurate.

## Dependencies

The runtime dependency set is the standard library plus `requests`, with
`python-docx` optional. Please do not add YAML, CLI-framework, validation or
data-frame libraries: a package a librarian can install behind an institutional
proxy is worth more here than one that saves the maintainer a few lines. Parsers
are dependency-free by design (`ElementTree`, `re`, `csv`).

## Public API and docstrings

- Export new public symbols in `corpusslr/__init__.py` with `# noqa: F401`,
  **appending lines** rather than rewriting the file.
- Docstrings on public functions explain the *methodological* justification, not
  just the mechanics. They are read by people deciding whether a procedure is
  defensible in a review protocol, and their content is reused in the
  manuscript. Where a choice constrains what the software can claim - bioRxiv
  exposing date windows rather than search, Crossref flattening boolean logic - 
  say so in the docstring and make sure the limitation reaches
  `SearchEvent.notes`, so it also reaches the PRISMA-S appendix.
- Write in English, like the rest of the code.

## Release metadata

Version, licence, author and repository URL are declared in five places:
`pyproject.toml`, `corpusslr/__init__.py`, `CITATION.cff`, `codemeta.json` and
`.zenodo.json`. They are checked by `tests/test_metadata_consistency.py`,
because a release whose metadata disagrees mints a DOI against a version string
no installed artefact reports - and every later citation of that DOI is then
wrong. When bumping a version, update all five and add a `CHANGELOG.md` entry
in Keep a Changelog form; the test requires an entry for the current version.

## Pull requests

Before opening one:

- `python -m pytest tests` passes, on 3.9 as well as your default interpreter
- `python -m ruff check .` and `python -m mypy corpusslr` report nothing
- new behaviour has a test; a repaired defect has a regression test
- `CHANGELOG.md` records the change under `[Unreleased]`
- any figure you added to documentation traces to a file under `validation/`

Describe what you measured, not only what you changed. For a change to
deduplication, report the effect on the ASySD benchmark (`validation/eval_asysd.py`)
and on the multi-domain protocol (`validation/eval_multidomain.py`) - an
accuracy change with no measurement behind it cannot be reviewed.

## Reporting a defect

Open an issue with the record or export that triggers it, reduced to the
smallest input that still reproduces the behaviour, plus your Python version.
For deduplication defects the useful report is the *pair* of records that were
or were not merged, since the decision is always about a pair. Please redact any
licensed full-text content; bibliographic metadata alone is enough to reproduce
almost every defect found so far.
