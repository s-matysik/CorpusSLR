"""The reviewer package must not promise anything it does not contain.

A package assembled by a script is only as trustworthy as the checks on the
script. The failures these tests are written against are the ones that actually
happen when a package is assembled by hand: the README names a file that was
never copied, a checksum is stale because a file changed after the manifest was
written, the zip and the directory drift apart, an API key rides along inside a
notebook or a config, and a rebuild produces a different archive so two
reviewers cannot compare hashes.

The package is built once per session into a temporary directory. Building into
the repository would race the other work streams and would leave a 13 MB tree
behind after the suite.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

import build_reviewer_package as brp  # noqa: E402

DASHES = ("\u2014", "\u2013")
DASH_RUNS = (" --- ", " -- ")
TEXT_SUFFIXES = (".md", ".txt", ".csv", ".json", ".py", ".ipynb", ".cff",
                 ".toml", ".in", ".svg")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("pkg")
    return brp.build(str(out), write_zip=True, quiet=True)


@pytest.fixture(scope="module")
def root(built):
    return built["root"]


def read(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def walk(root):
    for base, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(files):
            p = os.path.join(base, name)
            yield os.path.relpath(p, root).replace(os.sep, "/"), p


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------
# the package is complete
# --------------------------------------------------------------------------
def test_the_build_reports_no_missing_source_file(built):
    """Every path in the inventory exists in the repository.

    A silently skipped file is the failure mode that matters: the README would
    still list it, and the omission would only surface for the reviewer.
    """
    assert built["missing"] == [], (
        "inventory names files that are not in the repository: %s"
        % built["missing"])


def test_the_expected_subdirectories_are_present_and_non_empty(root):
    for sub in ("manuscript", "data", "figures", "code", "reproduce"):
        d = os.path.join(root, sub)
        assert os.path.isdir(d), "%s/ is missing from the package" % sub
        assert os.listdir(d), "%s/ is empty" % sub


def test_the_entry_point_documents_exist(root):
    for name in ("README.md", "CHECKSUMS.txt", "MANIFEST.csv",
                 "KNOWN_ISSUES.md"):
        assert os.path.exists(os.path.join(root, name)), name


def test_the_manuscript_and_supplementary_are_packaged(root):
    for name in ("MANUSCRIPT.md", "SUPPLEMENTARY.md", "AUDIT_REPORT.md",
                 "SUBMISSION_CHECKLIST.md"):
        assert os.path.exists(os.path.join(root, "manuscript", name)), name


def test_the_headline_evidence_tables_are_packaged(root):
    for name in ("domains_15_final.csv", "asysd_metrics.csv",
                 "dedup_mechanism_ablation.csv", "dedup_ablation_domains.csv",
                 "parser_coverage.csv", "bibliometrix_verification.json"):
        assert os.path.exists(os.path.join(root, "data", name)), name


def test_the_manuscript_figures_are_packaged(root):
    for name in ("fig_domains.png", "fig_ablation.png"):
        p = os.path.join(root, "figures", name)
        assert os.path.exists(p), name
        assert os.path.getsize(p) > 1024, "%s looks truncated" % name


def test_the_package_source_travels_with_the_claims(root):
    """A reviewer holds the code the manuscript is about, not a description."""
    src = os.path.join(root, "code", "corpusslr")
    assert os.path.isdir(src)
    modules = {n for _, p in walk(src) for n in [os.path.basename(p)]
               if n.endswith(".py")}
    for expected in ("dedup.py", "record.py", "export.py", "prisma_s.py",
                     "tui.py", "query.py"):
        assert expected in modules, "%s is missing from code/corpusslr" % expected


# --------------------------------------------------------------------------
# the README does not promise what the package does not hold
# --------------------------------------------------------------------------
def _readme_paths(text):
    """Every package-relative path the README mentions in backticks.

    Restricted to backticked tokens that look like a path inside the package,
    so ordinary prose and shell flags are not mistaken for promises.
    """
    out = set()
    for token in re.findall(r"`([^`]+)`", text):
        token = token.strip()
        if " " in token or not re.search(r"\.[A-Za-z0-9]+$", token):
            continue
        if token.startswith(("http", "-", "--")):
            continue
        head = token.split("/")[0]
        if head in ("manuscript", "data", "figures", "code", "reproduce") or \
                (("/" not in token) and token.isupper()):
            out.add(token)
    return out


def test_every_file_the_readme_names_is_in_the_package(root):
    """The README is a promise; this is the check that it is kept.

    Glob patterns are expanded rather than skipped, because
    `data/domains_*_false_positives.csv` promising nothing is exactly the
    failure this catches.
    """
    text = read(os.path.join(root, "README.md"))
    present = {rel for rel, _ in walk(root)}
    missing = []
    for token in sorted(_readme_paths(text)):
        if "*" in token:
            import fnmatch
            if not any(fnmatch.fnmatch(rel, token) for rel in present):
                missing.append(token)
        elif token not in present:
            missing.append(token)
    assert not missing, "README names files the package does not contain: %s" % missing


def test_the_readme_numbers_come_from_the_evidence_files(root):
    """The headline figures in the README agree with the tables in data/."""
    text = read(os.path.join(root, "README.md"))
    with open(os.path.join(root, "data", "domains_15_final.csv"),
              encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert str(sum(int(r["n_records"]) for r in rows)) in text
    assert str(sum(int(r["truth_pairs"]) for r in rows)) in text
    assert str(sum(int(r["pair_fp"]) for r in rows)) in text
    with open(os.path.join(root, "data", "parser_coverage.csv"),
              encoding="utf-8-sig", newline="") as fh:
        cov = list(csv.DictReader(fh))
    covered = sum(1 for r in cov if r["status"] == "covered")
    assert "%d of %d" % (covered, len(cov)) in text


def test_the_claim_map_covers_the_headline_results(root):
    text = read(os.path.join(root, "README.md"))
    table = text.split("Every manuscript claim")[1]
    for anchor in ("asysd_metrics.csv", "domains_15_final.csv",
                   "dedup_ablation_domains.csv", "parser_coverage.csv",
                   "bibliometrix_verification.json", "SUPPLEMENTARY.md"):
        assert anchor in table, "the claim map does not point at %s" % anchor


def test_the_readme_states_what_does_not_reproduce(root):
    """A package that only lists successes is not an honest one."""
    text = read(os.path.join(root, "README.md"))
    assert "Cannot be re-run here" in text
    assert "KNOWN_ISSUES.md" in text


def test_the_headline_table_divergence_is_disclosed_with_measured_figures(root):
    """The gap between the quoted table and the reproducible files is stated.

    domains_15_final.csv is what the manuscript quotes and it has no producing
    script, so the only defensible position is to measure the gap against the
    per-track metrics files and publish it. This test recomputes the gap here,
    independently of the builder, and requires both documents to carry the
    resulting figures.
    """
    def rows(name):
        with open(os.path.join(root, "data", name), encoding="utf-8-sig",
                  newline="") as fh:
            return list(csv.DictReader(fh))

    final = {r["domain"]: r for r in rows("domains_15_final.csv")}
    per = {}
    for track in ("social", "stem", "nature_hum"):
        for r in rows("domains_%s_metrics.csv" % track):
            if r.get("level") == "domain":
                per[r["domain"]] = r

    keys = ("n_records", "truth_pairs", "pair_tp", "pair_fp", "pair_fn")
    differing = [d for d in final
                 if any(final[d][k] != per[d][k] for k in keys)]
    per_fp = sum(int(r["pair_fp"]) for r in per.values())
    fin_fp = sum(int(r["pair_fp"]) for r in final.values())

    # The premise of the test: the two really do disagree. If a later change
    # makes them agree, this assertion is the signal to revisit the disclosure
    # rather than to leave a stale warning in the package.
    assert differing, ("the tables now agree; the disclosure in KNOWN_ISSUES.md "
                       "and README.md should be revisited")

    issues = read(os.path.join(root, "KNOWN_ISSUES.md"))
    readme = read(os.path.join(root, "README.md"))
    for doc, name in ((issues, "KNOWN_ISSUES.md"), (readme, "README.md")):
        assert "%d of %d" % (len(differing), len(final)) in doc, name
        assert str(per_fp) in doc and str(fin_fp) in doc, name
    assert "is not affected" not in issues, \
        "KNOWN_ISSUES.md still claims the headline table is not affected"


def test_the_disclosure_is_not_buried(root):
    """A caveat a reviewer only meets on page nine is not a disclosure."""
    readme = read(os.path.join(root, "README.md"))
    head = readme[:readme.index("## Which file answers which question")]
    assert "KNOWN_ISSUES.md" in head, \
        "the start-here list does not point at the known issues"
    issues = read(os.path.join(root, "KNOWN_ISSUES.md"))
    first = issues.index("## 1.")
    assert "headline table" in issues[first:first + 200], \
        "the divergence is not the first section of KNOWN_ISSUES.md"


# --------------------------------------------------------------------------
# integrity
# --------------------------------------------------------------------------
def test_every_checksum_matches_the_file_it_names(root):
    lines = read(os.path.join(root, "CHECKSUMS.txt")).splitlines()
    assert lines, "CHECKSUMS.txt is empty"
    bad = []
    for line in lines:
        digest, rel = line.split("  ", 1)
        p = os.path.join(root, rel)
        assert os.path.exists(p), "CHECKSUMS.txt names a missing file: %s" % rel
        if sha256(p) != digest:
            bad.append(rel)
    assert not bad, "checksum does not match the file: %s" % bad


def test_the_checksum_list_covers_every_file_in_the_package(root):
    listed = {line.split("  ", 1)[1]
              for line in read(os.path.join(root, "CHECKSUMS.txt")).splitlines()}
    present = {rel for rel, _ in walk(root)}
    # CHECKSUMS.txt cannot contain its own digest.
    assert present - listed == {"CHECKSUMS.txt"}, \
        "not covered by CHECKSUMS.txt: %s" % sorted(present - listed -
                                                    {"CHECKSUMS.txt"})


def test_a_tampered_file_is_caught_by_its_checksum(root, tmp_path):
    """The check above passes; this is the demonstration that it can fail."""
    import shutil
    work = tmp_path / "tampered"
    shutil.copytree(root, work)
    target = work / "data" / "domains_15_final.csv"
    with open(target, "a", encoding="utf-8") as fh:
        fh.write("stem,injected,1,1,1,0,0,0,0,0,0,0,0,0,1.0,1.0,1.0,1.0,1.0\n")
    listed = {line.split("  ", 1)[1]: line.split("  ", 1)[0]
              for line in read(str(work / "CHECKSUMS.txt")).splitlines()}
    rel = "data/domains_15_final.csv"
    assert sha256(str(target)) != listed[rel], \
        "appending a row to a packaged table did not change its checksum"


def test_the_manifest_agrees_with_the_files_on_disk(root):
    with open(os.path.join(root, "MANIFEST.csv"), encoding="utf-8",
              newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows
    for r in rows:
        p = os.path.join(root, r["path"])
        assert os.path.exists(p), "MANIFEST.csv names a missing file: %s" % r["path"]
        assert int(r["bytes"]) == os.path.getsize(p), r["path"]
        assert r["sha256"] == sha256(p), r["path"]


def test_every_manifest_row_says_what_the_file_establishes(root):
    with open(os.path.join(root, "MANIFEST.csv"), encoding="utf-8",
              newline="") as fh:
        rows = list(csv.DictReader(fh))
    thin = [r["path"] for r in rows if len(r["what it establishes"].strip()) < 20]
    assert not thin, "these manifest rows have no useful description: %s" % thin


# --------------------------------------------------------------------------
# the archive
# --------------------------------------------------------------------------
def test_the_zip_opens_and_holds_the_same_files(built, root):
    with zipfile.ZipFile(built["zip"]) as zf:
        assert zf.testzip() is None, "the archive is corrupt"
        names = {n.split("/", 1)[1] for n in zf.namelist()
                 if "/" in n and not n.endswith("/")}
    present = {rel for rel, _ in walk(root)}
    assert names == present, (
        "archive and directory differ: only in zip %s; only on disk %s"
        % (sorted(names - present)[:5], sorted(present - names)[:5]))


def test_zip_members_match_their_extracted_bytes(built, root):
    with zipfile.ZipFile(built["zip"]) as zf:
        for name in sorted(zf.namelist())[:40]:
            rel = name.split("/", 1)[1]
            with open(os.path.join(root, rel), "rb") as fh:
                assert zf.read(name) == fh.read(), rel


def test_the_archive_carries_no_absolute_or_escaping_paths(built):
    with zipfile.ZipFile(built["zip"]) as zf:
        for name in zf.namelist():
            assert not name.startswith("/"), name
            assert ".." not in name.split("/"), name
            assert name.startswith(brp.PKG_DIRNAME + "/"), name


# --------------------------------------------------------------------------
# determinism
# --------------------------------------------------------------------------
def test_two_builds_produce_byte_identical_archives(tmp_path):
    """Two reviewers must be able to compare hashes and get the same answer."""
    a = brp.build(str(tmp_path / "a"), write_zip=True, quiet=True)
    b = brp.build(str(tmp_path / "b"), write_zip=True, quiet=True)
    assert sha256(a["zip"]) == sha256(b["zip"])


def test_rebuilding_in_place_is_idempotent(tmp_path):
    out = str(tmp_path / "same")
    first = brp.build(out, write_zip=True, quiet=True)
    digest = sha256(first["zip"])
    checks = read(os.path.join(first["root"], "CHECKSUMS.txt"))
    second = brp.build(out, write_zip=True, quiet=True)
    assert sha256(second["zip"]) == digest
    assert read(os.path.join(second["root"], "CHECKSUMS.txt")) == checks


def test_no_generated_name_carries_a_timestamp(built, root):
    """A dated filename would make every build a different package."""
    stamp = re.compile(r"(19|20)\d{2}[-_]?\d{2}[-_]?\d{2}")
    named = [rel for rel, _ in walk(root) if stamp.search(os.path.basename(rel))]
    assert not named, "these packaged filenames embed a date: %s" % named
    assert not stamp.search(os.path.basename(built["zip"]))


def test_the_checksum_file_is_sorted(root):
    rels = [line.split("  ", 1)[1]
            for line in read(os.path.join(root, "CHECKSUMS.txt")).splitlines()]
    assert rels == sorted(rels), "CHECKSUMS.txt is not in sorted order"


# --------------------------------------------------------------------------
# no secrets
# --------------------------------------------------------------------------
# Patterns for the credential shapes this project can plausibly leak: the two
# bibliographic vendor keys it reads, plus the generic shapes that end up in a
# notebook when someone runs it with a real key pasted in.
SECRET_PATTERNS = [
    ("Scopus or WoS style 32-hex key",
     re.compile(r"\b[0-9a-f]{32}\b")),
    # The name may be quoted, as it is in JSON ("api_key": "..."), so an
    # optional closing quote sits between the name and the separator.
    ("assignment to an api key variable",
     re.compile(r"""(?ix) \b (api[_-]?key|apikey|insttoken|inst[_-]?token|
                 access[_-]?token|client[_-]?secret|secret[_-]?key|
                 password|passwd)
                 ["']? \s* [=:] \s* ['"][^'"\s]{12,}['"]""")),
    ("bearer token",
     re.compile(r"(?i)\bbearer\s+[A-Za-z0-9_\-\.]{20,}")),
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("OpenAI style key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]

# Placeholders and documented examples. Each is a literal the project uses on
# purpose; a pattern hit is only allowed when the matching line contains one.
# Deliberately narrow: broad allowances (a bare "abcdef", say) would silence the
# scanner on a real key that happened to contain those letters, which is the way
# a secret scan quietly stops working.
ALLOWED = (
    "YOUR_", "your_", "<your", "xxxxxxxx", "XXXXXXXX", "placeholder",
    "PLACEHOLDER", "example.com", "example.org", "getpass", "redact",
    "REDACT", "<redacted>", "dummy", "not-a-real-key",
)

# A 32-hex string is also the shape of a checksum, a request id and a record
# identifier. Those fields are named, so the exemption is keyed on the name
# rather than on the value: a key assigned to `api_key` is still caught.
NON_SECRET_HEX_FIELDS = re.compile(
    r"""(?ix) \b (request[_-]?id | correlation[_-]?id | sha256 | sha1 | md5 |
        checksum | digest | hash | etag | eid | uid | commit | revision)
        \b \s* ["']? \s* [=:]""")


def _secret_hits(path, rel):
    hits = []
    text = read(path)
    for i, line in enumerate(text.splitlines(), 1):
        if any(a in line for a in ALLOWED):
            continue
        for label, pat in SECRET_PATTERNS:
            m = pat.search(line)
            if not m:
                continue
            if label.endswith("32-hex key"):
                # A hex run inside the checksum list or the manifest is a
                # digest; those two files are checked for their own integrity.
                if rel in ("CHECKSUMS.txt", "MANIFEST.csv"):
                    continue
                if NON_SECRET_HEX_FIELDS.search(line):
                    continue
            hits.append("%s:%d %s" % (rel, i, label))
    return hits


def test_no_packaged_file_contains_a_credential(root):
    hits = []
    for rel, p in walk(root):
        if not rel.endswith(TEXT_SUFFIXES):
            continue
        hits.extend(_secret_hits(p, rel))
    assert not hits, "possible credential in the package: %s" % hits[:10]


@pytest.mark.parametrize("name,content,what", [
    ("planted.md", 'Set SCOPUS_API_KEY = "a3f9c21d84be07153c6d92ab4471fe08"\n',
     "a 32-hex vendor key"),
    ("planted.py", 'api_key = "sk-Qv7ZmT3rLpXk92WdYhNbGc41"\n',
     "an assignment to api_key"),
    ("planted.json", '{"insttoken": "7b19Kd0PmQz3XvTr8LcYuHnE"}\n',
     "an institutional token"),
    ("planted.txt", "Authorization: Bearer Rk29TvLmQp03XcYbNdHsWfZg41Ju\n",
     "a bearer token"),
    ("planted2.py", 'password = "Tr0ub4dor&3xKlmNpQrSt"\n',
     "a password assignment"),
    # Assembled from parts rather than written out: a literal of this shape
    # in a source file is itself what secret scanners are built to flag, and
    # a test fixture should not trip every tool that reads the repository.
    ("planted.cfg", "AK" + "IA" + "Q3RTUVWXYZ" + "012345" + "\n",
     "an AWS access key id"),
])
def test_the_secret_scanner_catches_a_planted_credential(tmp_path, name,
                                                         content, what):
    """The scan above passes; this shows it is not passing vacuously.

    One case per pattern, because a scanner is only worth what its weakest
    pattern catches, and a single demonstration would leave the others
    untested.
    """
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    assert _secret_hits(str(p), name), "the scanner did not catch %s" % what


def test_the_scanner_does_not_flag_a_request_id_or_a_checksum(tmp_path):
    """The exemptions are keyed on the field name, so they must be narrow."""
    ok = tmp_path / "fine.json"
    ok.write_text('{"request_id": "e053f523c089eb58a98e75481cc45f75"}\n',
                  encoding="utf-8")
    assert not _secret_hits(str(ok), "fine.json")
    bad = tmp_path / "notfine.json"
    bad.write_text('{"api_key": "e053f523c089eb58a98e75481cc45f75"}\n',
                   encoding="utf-8")
    assert _secret_hits(str(bad), "notfine.json"), \
        "the field-name exemption is too broad: it hid a key"


def test_the_packaged_notebook_carries_no_saved_output(root):
    """An executed notebook is where a pasted key would be stored."""
    p = os.path.join(root, "code", "corpusslr_colab.ipynb")
    with open(p, encoding="utf-8") as fh:
        nb = json.load(fh)
    for i, cell in enumerate(nb["cells"]):
        if cell["cell_type"] == "code":
            assert cell.get("outputs") == [], "cell %d carries output" % i
            assert cell.get("execution_count") is None, "cell %d was executed" % i


def test_the_packaged_config_has_no_key_field_filled_in(root):
    p = os.path.join(root, "code", "review_config.json")
    with open(p, encoding="utf-8") as fh:
        text = fh.read()
    assert not _secret_hits(p, "code/review_config.json"), text[:200]


# --------------------------------------------------------------------------
# typography
# --------------------------------------------------------------------------
def test_no_packaged_document_uses_a_dash_other_than_the_hyphen(root):
    findings = []
    for rel, p in walk(root):
        if not rel.endswith((".md", ".txt")):
            continue
        for i, line in enumerate(read(p).splitlines(), 1):
            for ch in DASHES:
                if ch in line:
                    findings.append("%s:%d" % (rel, i))
            for run in DASH_RUNS:
                if run in line:
                    findings.append("%s:%d (dash run)" % (rel, i))
    assert not findings, "long dashes in the package: %s" % findings[:15]


def test_the_dash_check_catches_an_injected_dash(tmp_path):
    """The scan above passes; this shows the pattern set actually matches."""
    from validation.verify_reviewer_claims import scan_dashes  # noqa: F401
    d = tmp_path / "docs"
    d.mkdir()
    (d / "bad.md").write_text("text \u2014 more text\n", encoding="utf-8")
    (d / "also_bad.md").write_text("range 1\u20135\n", encoding="utf-8")
    (d / "run.md").write_text("a -- b\n", encoding="utf-8")
    found = scan_dashes(str(d))
    assert len(found) == 3, found


def test_the_builder_normalizes_a_dash_out_of_a_copied_document():
    """Shared upstream files may still use long dashes; the copy must not."""
    got = brp.normalize_text("one \u2014 two, three\u2013four, five -- six")
    assert "\u2014" not in got and "\u2013" not in got and " -- " not in got
    assert got == "one - two, three-four, five - six"


# --------------------------------------------------------------------------
# the verifier the README tells the reviewer to run
# --------------------------------------------------------------------------
def test_the_verifier_is_packaged_and_re_derives_every_claim(root):
    script = os.path.join(root, "reproduce", "verify_reviewer_claims.py")
    assert os.path.exists(script)
    proc = subprocess.run(
        [sys.executable, script, "--root", root, "--no-suite"],
        capture_output=True, text=True, cwd=REPO,
        env=dict(os.environ, PYTHONPATH=REPO))
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-2000:]
    assert "AT LEAST ONE CLAIM" not in proc.stdout
    for cid in ("C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9"):
        assert re.search(r"^%s\s" % cid, proc.stdout, re.M), \
            "%s produced no line" % cid


def test_the_verifier_self_test_rejects_every_injected_error():
    """A control that has never failed is not a control."""
    script = os.path.join(REPO, "validation", "verify_reviewer_claims.py")
    proc = subprocess.run(
        [sys.executable, script, "--self-test"],
        capture_output=True, text=True, cwd=REPO,
        env=dict(os.environ, PYTHONPATH=REPO))
    assert proc.returncode == 0, proc.stdout[-3000:]
    assert "NOT DETECTED" not in proc.stdout
    assert "every injected error was rejected" in proc.stdout


# --------------------------------------------------------------------------
# packaging hygiene
# --------------------------------------------------------------------------
def test_the_package_is_excluded_from_the_source_distribution():
    """The package is a product of the repository, not part of the release."""
    text = read(os.path.join(REPO, "MANIFEST.in"))
    assert re.search(r"^\s*prune\s+reviewer_package\s*$", text, re.M), \
        "MANIFEST.in does not prune reviewer_package/"
    assert re.search(r"^\s*exclude\s+corpusslr_reviewer_package\.zip\s*$",
                     text, re.M), \
        "MANIFEST.in does not exclude the archive"


def test_no_cache_or_editor_droppings_were_packaged(root):
    for rel, _ in walk(root):
        assert "__pycache__" not in rel, rel
        assert not rel.endswith((".pyc", ".pyo", ".DS_Store", ".swp")), rel


def _stdlib_names():
    """Standard-library module names, on 3.9 as well as 3.10+.

    sys.stdlib_module_names arrived in 3.10 and the package supports 3.9, so on
    3.9 the set is derived from the interpreter's own stdlib directory. Falling
    back to skipping the test would remove the check on exactly the interpreter
    where a stray third-party import is most likely to matter.
    """
    names = getattr(sys, "stdlib_module_names", None)
    if names:
        return set(names)
    import distutils.sysconfig as sc
    lib = sc.get_python_lib(standard_lib=True)
    out = set(sys.builtin_module_names)
    for entry in os.listdir(lib):
        if entry.endswith(".py"):
            out.add(entry[:-3])
        elif os.path.isdir(os.path.join(lib, entry)) and \
                entry not in ("site-packages", "lib-dynload", "__pycache__"):
            out.add(entry)
    for entry in os.listdir(os.path.join(lib, "lib-dynload")) \
            if os.path.isdir(os.path.join(lib, "lib-dynload")) else []:
        out.add(entry.split(".")[0])
    return out


def test_the_builder_imports_nothing_outside_the_standard_library():
    """Python 3.9, stdlib only: the package must build anywhere."""
    src = read(os.path.join(REPO, "tools", "build_reviewer_package.py"))
    imported = set(re.findall(r"^\s*import\s+([A-Za-z_][\w]*)", src, re.M))
    imported |= set(re.findall(r"^\s*from\s+([A-Za-z_][\w]*)", src, re.M))
    allowed = _stdlib_names() | {"__future__"}
    assert imported <= allowed, "non-stdlib imports: %s" % sorted(imported - allowed)


def test_the_verifier_imports_only_stdlib_and_the_package_itself():
    src = read(os.path.join(REPO, "validation", "verify_reviewer_claims.py"))
    top = set(re.findall(r"^\s*import\s+([A-Za-z_][\w]*)", src, re.M))
    top |= set(re.findall(r"^\s*from\s+([A-Za-z_][\w]*)", src, re.M))
    # The verifier reaches for two sibling scripts by design: the builder's dash
    # normalizer, so the self-test's baseline matches a real build, and the
    # inventory measurement, so C7 compares like with like. Both are in this
    # repository and neither is a third-party dependency.
    allowed = _stdlib_names() | {"__future__", "corpusslr",
                                 "build_reviewer_package",
                                 "measure_test_inventory"}
    assert top <= allowed, "unexpected imports: %s" % sorted(top - allowed)
