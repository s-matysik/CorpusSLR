# Publishing CorpusSLR 1.0.0

This is the procedure for putting this working tree on GitHub, turning on
continuous integration and GitHub Pages, tagging the release and minting a DOI
through Zenodo. Every step is a command to paste, in order.

The repository is **not** under version control yet. That is deliberate: whose
account the code lives under, and when it becomes public, are your decisions,
not something a tool should make for you. Nothing below has been executed on
your behalf.

The target repository declared in the packaging metadata is

    https://github.com/s-matysik/CorpusSLR

read from `pyproject.toml` (`[project.urls] Repository`), `CITATION.cff`
(`repository-code`), `codemeta.json` (`codeRepository`, `issueTracker`,
`readme`) and `.zenodo.json` (`related_identifiers`). All five agree, and
`tests/test_metadata_consistency.py` fails if they ever stop agreeing. If you
publish under a different account or a different repository name, change it in
all of those files in the same commit, or that test will tell you which one you
missed.

Throughout, `REPO` is the working tree:

```bash
REPO="/Users/sebastianmatysik/!!!CorpusSLR/corpusslr"
cd "$REPO"
```

---

## 0. Confirm the tree is releasable before publishing anything

Run these first. All four have to pass. Publishing a tree that fails one of
them costs more to correct in public than it does to fix now.

```bash
cd "$REPO"

# 1. Full test suite. -p no:cacheprovider keeps pytest from writing a cache
#    directory into the tree; tools.no_network makes any socket use raise, so
#    a test that reaches a bibliographic API fails instead of passing quietly
#    on a machine that happens to be online.
PYTHONPATH=. python -m pytest tests -p no:cacheprovider -p tools.no_network -q

# 2. Static analysis. Both tools are configured in pyproject.toml, so this is
#    the same rule set the quality workflow applies.
python -m ruff check --no-cache .
python -m mypy corpusslr

# 3. Every number quoted in the documentation, re-derived from its source.
#    The run must end with the line saying the figures agree.
PYTHONPATH=. python validation/audit_document_numbers.py

# 4. Distributions build and their metadata is valid.
python -m pip install --upgrade build twine
python -m build
python -m twine check --strict dist/*
```

Measured on this tree, for comparison with what you see:

| check | result |
|---|---|
| `pytest tests` on Python 3.13 | 2119 passed |
| `pytest tests` on Python 3.9 | 2097 passed, 3 skipped |
| statement coverage | 98%, 7002 statements, 159 uncovered |
| `ruff check --no-cache .` | All checks passed |
| `mypy corpusslr` | no issues found in 40 source files |
| `audit_document_numbers.py` | all stated figures agree with their measurements |
| `twine check --strict` | PASSED |
| `tools/build_site.py` | 8 pages, 47 evidence files, no long dashes |

The three skips on Python 3.9 are two optional libraries absent from that
environment: PyYAML, which the CLI's YAML config tests need and which is
deliberately not a dependency, and python-docx, which writes the PRISMA-S
appendix as a `.docx` file. Neither is a behaviour difference.

Both totals include the 216 tests added with this release that guard the
publishing path itself: 109 in `tests/test_site.py` for the documentation-site
generator, and 107 in `tests/test_publishing.py` for the `.gitignore` contract,
this document and the Pages workflow.

Re-measure rather than trusting the table. These counts change whenever a test
is added, so if your run disagrees, your run is the fact and this table is
stale:

```bash
cd "$REPO"
PYTHONPATH=. python -m pytest tests -p no:cacheprovider -p tools.no_network \
  -o addopts="" -q | tail -1
```

---

## 1. Initialise the repository and make the first commit

### 1.1 The `.gitignore`

One already exists in the tree and covers everything below. Read it before you
commit, because what it excludes and what it deliberately does not are both
load-bearing. If you need to recreate it, this is the whole file:

```bash
cd "$REPO"
cat > .gitignore <<'EOF'
# Byte-compiled and packaging artefacts
__pycache__/
*.py[cod]
*.egg-info/
build/
dist/
.eggs/

# Test, coverage and static-analysis caches
.pytest_cache/
.ruff_cache/
.mypy_cache/
.coverage
.coverage.*
coverage.xml
htmlcov/
.tmp/

# Virtual environments
.venv/
venv/
env/

# Editors and operating system
.DS_Store
.idea/
.vscode/
*.swp

# Local harvest archives and scratch outputs. An archive is the raw-response
# evidence for one specific review and is often large; API keys are stripped
# from recorded requests by redact_params(), so the reason to keep archives out
# of the repository is size and scope, not secrecy. Deposit them alongside the
# review instead. See reproducible_harvesting.md.
*.harvest/
harvest_archive/
dedup_report.csv

# The generated documentation site. Regenerable in under a second by
# `python tools/build_site.py`, and the GitHub Pages workflow builds it from the
# markdown on every push, so the committed tree carries the sources rather than
# the output.
site/

# Packaging scratch directory used by the release checks.
build_check/

# Nothing above excludes evidence. validation/*.csv, validation/*.json and
# validation/*.png are the provenance of every accuracy figure quoted in the
# documentation and in the manuscript, so they are tracked deliberately and
# must never be added here.
EOF
```

**What is excluded:** `__pycache__/`, `*.pyc`, `dist/`, `build/`,
`build_check/`, `.mypy_cache/`, `.ruff_cache/`, `.pytest_cache/`, `.venv/`,
`.coverage`, `coverage.xml`, `.DS_Store`, `*.egg-info/`, and `site/`.

**What is not excluded, on purpose:** everything under `validation/`. The CSV
metric tables, the JSON verification records and the PNG figures are the
provenance of every accuracy figure in the manuscript, the supplementary
material and the README. A reviewer who cannot open
`validation/domains_15_final.csv` cannot check the reported median F1 of
0.9592, and a claim that cannot be checked is not evidence. `MANUSCRIPT.md`,
`SUPPLEMENTARY.md`, `AUDIT_REPORT.md` and `SUBMISSION_CHECKLIST.md` are tracked
for the same reason.

Measured sizes of the largest files this leaves tracked:

| file | size |
|---|---:|
| `validation/multidomain_raw.jsonl.gz` | 4.06 MB |
| `validation/labelled_test_set.csv` | 3.98 MB |
| `validation/domains_stem_raw.jsonl.gz` | 2.53 MB |
| `validation/domains_nature_hum_raw.jsonl.gz` | 2.43 MB |
| `validation/domains_social_raw.jsonl.gz` | 2.06 MB |

All are well inside what Git handles comfortably, so they are committed rather
than put behind Git LFS. Total tracked size measured on this tree is 29.7 MB
across 196 files, of which 9.1 MB is a single reviewer-package archive; if you
would rather rebuild that archive than version it, exclude it before the first
commit and attach it to the GitHub release instead:

```bash
cd "$REPO"
du -sh . --exclude=.git 2>/dev/null || du -sh .
ls -la corpusslr_reviewer_package.zip 2>/dev/null && \
  echo "corpusslr_reviewer_package.zip" >> .gitignore
```

### 1.2 Initialise, commit

```bash
cd "$REPO"

git init
git branch -M main

# Identity, if it is not already set globally.
git config user.name "Sebastian Matysik"
git config user.email "you@example.org"   # the address you want in the history

git add -A

# Read what you are about to commit before you commit it. Two things to
# confirm: no cache directory slipped in, and everything under validation/ did.
git status --short | head -50
git diff --cached --stat | tail -5

# Nothing credential-shaped, in any file about to be committed. The pattern
# looks for an *assignment of a key-shaped value*, not for a parameter name:
# the documentation legitimately writes `api_key=KEY` and `api_key="..."` as
# placeholders, and a scan that fires on those is a scan you switch off within
# a week. Twelve characters of key-shaped value is the threshold; no
# placeholder in this tree reaches it.
#
# Driven from `git ls-files` rather than `git grep` with a pathspec, so the
# command needs no pathspec separator and stays readable.
git ls-files -z | xargs -0 grep -nEI \
  '(api[_-]?key|insttoken|apikey|token|secret|password)[[:space:]]*[=:][[:space:]]*["'"'"'][A-Za-z0-9_-]{12,}' \
  | grep -v '^tests/' \
  || echo "no credential-shaped assignment in any tracked file"

git commit -m "CorpusSLR 1.0.0

Identification phase of a systematic literature review: one structured query
compiled to the native syntax of multiple bibliographic databases, export
parsing for 7 file formats, cascading auditable deduplication, PRISMA 2020 flow
diagram and PRISMA-S appendix generated from the recorded audit trail.

2119 tests, 98% statement coverage, offline by construction. Deduplication
validated against the ASySD gold standard at F1 0.9996 and across 15
disciplines under an identifier-blind protocol at median F1 0.9592."
```

If `git status --short` shows anything under `__pycache__/`, `.mypy_cache/`,
`.ruff_cache/`, `dist/` or `build_check/`, stop: the `.gitignore` was added
after those files were staged. Clear the index and stage again:

```bash
git rm -r --cached . -q && git add -A && git status --short | head -30
```

---

## 2. Create the repository on GitHub and push

### 2.1 With the `gh` CLI (fewer steps)

```bash
cd "$REPO"

# Authenticate once, if you have not already.
gh auth status || gh auth login

# Creates the repository under your account, adds it as `origin` and pushes.
# Use --private if you would rather make it public later; Pages on a private
# repository needs a paid plan, so publish the documentation only once the
# repository is public.
gh repo create s-matysik/CorpusSLR \
  --public \
  --source . \
  --remote origin \
  --description "From one structured query to a PRISMA-documented corpus: multi-database retrieval, export parsing, auditable deduplication, PRISMA 2020 and PRISMA-S reporting." \
  --push

# Topics, so the repository is findable.
gh repo edit s-matysik/CorpusSLR --add-topic systematic-literature-review \
  --add-topic prisma --add-topic deduplication --add-topic bibliometrics \
  --add-topic evidence-synthesis --add-topic meta-research \
  --add-topic scopus --add-topic openalex --add-topic pubmed --add-topic python
```

### 2.2 Without the CLI

Create an **empty** repository named `CorpusSLR` under the `s-matysik` account
at <https://github.com/new>. Do not let GitHub add a README, a licence or a
`.gitignore`: the tree already has all three, and an initial commit on the
remote turns the first push into a merge you do not need. Then:

```bash
cd "$REPO"
git remote add origin https://github.com/s-matysik/CorpusSLR.git
git push -u origin main
```

### 2.3 Confirm the push

```bash
git remote -v
git log --oneline -1
gh repo view s-matysik/CorpusSLR --json name,visibility,defaultBranchRef
```

---

## 3. Turn on GitHub Actions

Three workflows are already in `.github/workflows/`:

| file | what it does |
|---|---|
| `tests.yml` | full suite on Python 3.9, 3.10, 3.11, 3.12 and 3.13 with the socket layer stubbed, coverage floor 95%, wheel and sdist build, `twine check --strict`, wheel import in a clean interpreter, suite re-run from the unpacked sdist, metadata consistency |
| `quality.yml` | `ruff check --no-cache .` and `mypy corpusslr`, both configured in `pyproject.toml` |
| `pages.yml` | builds the documentation site and deploys it to Pages |

Actions is enabled by default on a new public repository, so the first push
already started `tests.yml` and `quality.yml`. Watch them:

```bash
gh run list --limit 10
gh run watch                          # the run in progress
gh run view --log-failed              # only the failing steps, if any
```

If Actions was disabled on the account, enable it under
**Settings, then Actions, then General**, choose *Allow all actions and
reusable workflows*, and set **Workflow permissions** to *Read repository
contents and packages permissions*. The workflows need no secrets: no test
touches the network and no job needs a credential.

The `SUBMISSION_CHECKLIST.md` item *CI executed on GitHub* closes here. It is
the one check that a sandbox genuinely cannot perform, because it is a claim
about runner behaviour, action resolution and matrix expansion rather than
about the code. Confirm all five matrix legs are green before you tag:

```bash
gh run list --workflow tests.yml --limit 1 --json conclusion,headSha
```

---

## 4. Turn on GitHub Pages

`pages.yml` publishes the site produced by `tools/build_site.py`. The generator
uses the standard library only, renders the markdown with its own converter,
inlines the CSS and emits no JavaScript, so the published pages work with no
network at all. Pages must be told to take its content from the workflow rather
than from a branch:

```bash
# Set the source to GitHub Actions. Once, per repository.
gh api -X POST repos/s-matysik/CorpusSLR/pages \
  -f 'build_type=workflow' \
  || gh api -X PUT repos/s-matysik/CorpusSLR/pages -f 'build_type=workflow'
```

Or in the interface: **Settings, then Pages**, and under *Build and deployment*
set **Source** to *GitHub Actions*. Do not pick *Deploy from a branch*; there
is no `gh-pages` branch and `site/` is not committed.

Then run the deployment and check it:

```bash
gh workflow run pages.yml
gh run watch --workflow pages.yml

# The published address.
gh api repos/s-matysik/CorpusSLR/pages --jq .html_url
```

The site will be at <https://s-matysik.github.io/CorpusSLR/>.

Build it locally first if you want to see exactly what gets published:

```bash
cd "$REPO"
python tools/build_site.py --clean
open site/index.html          # Linux: xdg-open site/index.html
```

That writes eight pages into `site/`: the overview, the user guide, the API
reference, the supplementary material, the multi-domain validation study, the
audit report, the changelog and an evidence index listing every metric table
and figure. The workflow re-runs `tests/test_site.py` before deploying and
fails the deployment if an internal link does not resolve, if any page
references an external domain, or if a long dash reaches the output.

---

## 5. Tag v1.0.0 and cut the release

Tag only a commit whose CI is green, because the tag is what Zenodo archives
and a DOI cannot be repointed afterwards.

```bash
cd "$REPO"

# Confirm the version the tag will claim is the version the package reports.
grep -n '^version' pyproject.toml
python -c "import corpusslr; print(corpusslr.__version__)"
grep -n '^version' CITATION.cff
python -c "import json; print(json.load(open('codemeta.json'))['version'], json.load(open('.zenodo.json'))['version'])"

# All four must print 1.0.0. This is also enforced by
# tests/test_metadata_consistency.py, which the metadata job runs.
PYTHONPATH=. python -m pytest tests/test_metadata_consistency.py -q -p no:cacheprovider

git tag -a v1.0.0 -m "CorpusSLR 1.0.0

Scopus CSV as the canonical post-deduplication export, verified by loading it
with bibliometrix::convert2df: all 14 302 records of a real Scopus export
survive the round trip, and biblioAnalysis reports 14 302 articles.
Deduplication F1 0.9996 on the ASySD Diabetes gold standard after the NA-DOI
fix (FP 0, FN 1) and median F1 0.9592 across 15 disciplines, identifier-blind.
2119 tests on Python 3.13, 98% statement coverage, no network access in any
test."

git push origin v1.0.0
```

Then the release. Attach the built distributions so a reader can install the
exact reviewed artefact:

```bash
python -m build          # if dist/ is not already current
python -m twine check --strict dist/*

gh release create v1.0.0 \
  dist/corpusslr-1.0.0-py3-none-any.whl \
  dist/corpusslr-1.0.0.tar.gz \
  --title "CorpusSLR 1.0.0" \
  --notes-file - <<'EOF'
From one structured query to a PRISMA-documented corpus.

One structured query is compiled to the native syntax of multiple bibliographic
databases, records from APIs and file exports are harmonized and enriched,
duplicates are removed by a cascading auditable procedure, and the PRISMA 2020
flow diagram together with the PRISMA-S search-reporting appendix is generated
from the recorded audit trail.

Measured on this tag:

- 2119 tests pass on Python 3.13; on Python 3.9, 2097 pass and 4 skip because
  PyYAML and python-docx are absent there. Statement coverage 98% of 7002
  statements, 159 uncovered. No test can reach the network: the suite runs with
  the standard-library connect primitives replaced by raising stubs.
- Deduplication on the ASySD Diabetes gold standard: F1 0.9996 with FP 0 and
  FN 1 after the NA-DOI fix, up from F1 0.9960 with FP 1 and FN 9 in 1.6.0.
  Before-and-after confusion matrices in validation/na_doi_fix_impact.csv; the
  full comparison against the four methods published by Hair et al. (2023) is
  in validation/asysd_metrics.csv.
- Median F1 0.9592 across 15 disciplines under an identifier-blind protocol,
  over 13 809 records and 2584 evaluated pairs, ranging from 0.8572 in
  economics to 0.9883 in biology. Of 154 false merges, 141 are version
  variants of the same work and 13 are genuine over-merges, which is 0.50% of
  evaluated pairs. Per-domain figures in validation/domains_15_final.csv.
- The Scopus CSV export loaded by bibliometrix 5.5.0 without modification: all
  14 302 records of a real Scopus export survive the round trip through
  to_scopus_csv, with 1 mismatch in 257 436 field comparisons, and
  biblioAnalysis reports 14 302 articles and 31 984 authors. A second run on a
  live three-database corpus generated 57 bibliometrix fields; record in
  validation/bibliometrix_verification.json.
- Specification coverage 32 of 32 items, each established by running the entry
  point. Table in validation/parser_coverage.csv.

Dependencies: the Python standard library and requests. python-docx is optional
and used only to write the PRISMA-S appendix as a .docx file. Python 3.9 to
3.13.

Documentation: https://s-matysik.github.io/CorpusSLR/
EOF

gh release view v1.0.0
```

If you would rather not attach files from the shell, create the release in the
interface from the existing tag: **Releases, then Draft a new release**, choose
`v1.0.0`, and upload the two files from `dist/`.

### Publishing to PyPI, if you want the package installable by name

Optional and independent of the DOI. Test it on TestPyPI first, because a
version once uploaded to PyPI cannot be replaced:

```bash
python -m twine upload --repository testpypi dist/*
python -m pip install --index-url https://test.pypi.org/simple/ --no-deps corpusslr
python -c "import corpusslr; print(corpusslr.__version__)"

# Then the real index.
python -m twine upload dist/*
```

Use an API token as the password, with `__token__` as the username. Do not put
the token in a shell command, in a file inside the repository, or in a CI
variable you have not scoped to a single project; `twine` will prompt for it,
and `~/.pypirc` with mode 600 is the usual place to keep it.

---

## 6. Connect Zenodo and mint the DOI

`.zenodo.json` is already in the tree, so the deposit is populated from it
rather than typed into a form.

1. Sign in at <https://zenodo.org> with the GitHub account that owns the
   repository.
2. Open <https://zenodo.org/account/settings/github/> and press
   **Sync now** if `CorpusSLR` is not listed.
3. Switch the toggle next to `s-matysik/CorpusSLR` **on**.
4. Only then publish a release. Zenodo archives releases created **after** the
   toggle was switched on; a release published before that is not picked up.
   If you already cut `v1.0.0` at step 5, either publish a `v1.0.0` after
   enabling the toggle, or archive the tag manually by uploading
   `dist/corpusslr-1.0.0.tar.gz` to a new Zenodo deposit and filling it from
   `.zenodo.json`.
5. Zenodo issues two DOIs: a **concept DOI** that always resolves to the newest
   version, and a **version DOI** for `v1.0.0` specifically. Cite the version
   DOI in the manuscript, because that is the artefact the reviewers read.

```bash
# The badge and both DOIs, once the archive exists.
gh api repos/s-matysik/CorpusSLR/releases/tags/v1.0.0 --jq .html_url
# Then read the DOIs from the Zenodo record page for the release.
```

### After the DOI exists, put it in the metadata

Two files gain a field. Do both in one commit, so no released state ever
carries one without the other:

```bash
cd "$REPO"

# CITATION.cff: add the version DOI as an identifier.
#   identifiers:
#     - type: doi
#       value: 10.5281/zenodo.XXXXXXX
#       description: "Archived v1.0.0"

# codemeta.json: add the same DOI.
#   "identifier": "https://doi.org/10.5281/zenodo.XXXXXXX"

PYTHONPATH=. python -m pytest tests/test_metadata_consistency.py -q -p no:cacheprovider
PYTHONPATH=. python validation/audit_document_numbers.py

git add CITATION.cff codemeta.json
git commit -m "Record the Zenodo version DOI for v1.0.0 in the citation metadata"
git push
```

This closes the `SUBMISSION_CHECKLIST.md` item *Zenodo DOI minted*, and with it
the second of the two items that could not be verified from a sandbox.

Add the badge to `README.md` if you want it visible. Append the line to the
existing badge block rather than rewriting the file:

```markdown
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.XXXXXXX.svg)](https://doi.org/10.5281/zenodo.XXXXXXX)
```

---

## 7. Order of operations, and why

The steps are sequenced rather than parallel, and two of the orderings matter:

1. Checks before the first push. A tree that fails its own suite is cheaper to
   fix before there is a public history than after.
2. First push, which starts `tests.yml` and `quality.yml`.
3. Pages source set to *GitHub Actions*, then `pages.yml` run. Setting the
   source afterwards leaves a successful build with nothing published.
4. Green CI confirmed on all five interpreters.
5. Tag and release, **after** the Zenodo toggle is on. This is the ordering
   that is easy to get wrong: Zenodo only archives releases created while the
   toggle is enabled, and a release published before it was switched on has to
   be archived by hand.
6. DOI written back into `CITATION.cff` and `codemeta.json`.

---

## 8. Verification after each step

```bash
# The commit exists and the remote has it.
git log --oneline -3 && git ls-remote --heads origin

# All workflows, most recent run each.
gh run list --limit 5 --json workflowName,conclusion,createdAt

# The five test legs, individually.
gh run list --workflow tests.yml --limit 1 --json jobs --jq '.[0].jobs[]?.name'

# Pages is live and the index is served.
curl -sSf -o /dev/null -w '%{http_code}\n' https://s-matysik.github.io/CorpusSLR/

# The tag, the release and its assets.
git ls-remote --tags origin | grep v1.0.0
gh release view v1.0.0 --json tagName,assets --jq '{tag: .tagName, assets: [.assets[].name]}'

# The installed wheel reports the version the tag claims.
python -m venv /tmp/verify && /tmp/verify/bin/pip install -q dist/*.whl
/tmp/verify/bin/python -c "import corpusslr; print(corpusslr.__version__)"
```

---

## 9. What not to publish

- **No credentials, anywhere.** No test needs one, no workflow needs one, and
  nothing in the tree reads one at import time. The `git grep` in step 1.2
  checks for credential-shaped assignments in tracked files;
  `tests/test_notebook.py` and `tests/test_site.py` both scan for planted keys
  and are paired with fault injection, so a passing result there means
  detection was demonstrated rather than merely absent.
- **No harvest archives.** A `*.harvest/` directory is the raw-response
  evidence for one specific review and belongs with that review's deposit, not
  in the tool's repository. API keys are stripped from recorded requests by
  `redact_params()`, so the reason is size and scope rather than secrecy. See
  `reproducible_harvesting.md`.
- **No `site/`.** It is generated, and `pages.yml` regenerates it on every
  push to `main`.
- **No caches.** `.mypy_cache/`, `.ruff_cache/`, `.pytest_cache/`,
  `__pycache__/` and `build_check/` are excluded; `git status --short` after
  staging is where you confirm it.

---

## 10. If something goes wrong

| symptom | cause | fix |
|---|---|---|
| `git push` rejected, non-fast-forward | GitHub created an initial commit when the repository was made | `git pull --rebase origin main` then push again, or recreate the repository empty |
| Pages workflow green, site 404 | Pages source still set to a branch | set **Source** to *GitHub Actions* (step 4), then re-run `pages.yml` |
| Pages deployment fails on permissions | workflow permissions restricted on the account | `pages.yml` already declares `pages: write` and `id-token: write`; enable *Read and write permissions* under Settings, Actions, General |
| `tests.yml` fails only on Python 3.9 | a 3.10+ construct reached the package | reproduce with the 3.9 interpreter locally; `requires-python` is `>=3.9` and the matrix is what enforces it |
| `twine check` reports a metadata error | `README.md` gained markup the renderer rejects | `python -m twine check --strict dist/*` names the offending line |
| Zenodo shows no record after the release | toggle was switched on after the release was published | publish a new release, or archive the tag by hand (step 6) |
| `test_metadata_consistency.py` fails after editing the DOI | one of the five metadata files was missed | the failure names the file and the field |

---

## 11. One-shot script

Everything up to the release, in a single block. Read it before running it; it
stops at the first failure.

```bash
#!/usr/bin/env bash
set -euo pipefail

REPO="/Users/sebastianmatysik/!!!CorpusSLR/corpusslr"
GH_REPO="s-matysik/CorpusSLR"
cd "$REPO"

echo "== checks =="
PYTHONPATH=. python -m pytest tests -p no:cacheprovider -p tools.no_network -q
python -m ruff check --no-cache .
python -m mypy corpusslr
PYTHONPATH=. python validation/audit_document_numbers.py
python tools/build_site.py --clean
python -m build
python -m twine check --strict dist/*

echo "== repository =="
git init
git branch -M main
git add -A
git status --short | head -40
git commit -m "CorpusSLR 1.0.0"

echo "== push =="
gh repo create "$GH_REPO" --public --source . --remote origin --push

echo "== pages =="
gh api -X POST "repos/$GH_REPO/pages" -f 'build_type=workflow' \
  || gh api -X PUT "repos/$GH_REPO/pages" -f 'build_type=workflow'
gh workflow run pages.yml

echo "== wait for CI, then tag manually =="
gh run list --limit 5
echo "when tests.yml is green on all five interpreters, and the Zenodo toggle"
echo "is on, run:"
echo "  git tag -a v1.0.0 -m 'CorpusSLR 1.0.0' && git push origin v1.0.0"
echo "  gh release create v1.0.0 dist/* --title 'CorpusSLR 1.0.0'"
```
