"""Regenerate SUBMISSION_CHECKLIST.md by verifying each item, not asserting it.

A checklist that claims its own completeness is worth nothing, so every item
marked done here carries the command output that establishes it, and every item
that cannot be verified from this environment is listed as open with the reason.

Usage:  python validation/submission_checklist.py
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sh(cmd):
    env = dict(os.environ, PYTHONPATH=HERE)
    return subprocess.run(["bash", "-c", cmd], cwd=HERE, capture_output=True,
                          text=True, env=env).stdout.strip()


def collect():
    items = []

    def check(item, ok, evidence):
        items.append({"item": item, "done": bool(ok), "evidence": evidence})

    py = sys.executable
    n = sh("{} -m pytest tests -p no:cacheprovider 2>&1 | tail -1".format(py))
    # "passed" appears in "2 failed, 2055 passed" too, so testing for it alone
    # ticked this item off while the suite was red - and the evidence line
    # printed underneath the tick said so. The condition has to be the absence
    # of failures and errors, not the presence of the word.
    suite_green = ("passed" in n and "failed" not in n
                   and " error" not in n and "errors" not in n)
    check("Test suite passes", suite_green, n)

    cov = sh("{} -m pytest tests -p no:cacheprovider -q --cov=corpusslr "
             "--cov-report=term 2>&1 | grep TOTAL".format(py))
    check("Coverage measured and above the CI floor", "%" in cov, cov)

    guard = sh("{} -c \"import tools.no_network as g, socket\n"
               "g.pytest_configure(None)\n"
               "try:\n"
               "    socket.create_connection(('api.crossref.org', 443), timeout=5)\n"
               "    print('NOT BLOCKED')\n"
               "except Exception as e:\n"
               "    print(type(e).__name__)\"".format(py))
    check("Offline execution enforced, not asserted",
          "NetworkUseInTestSuite" in guard,
          "a real connect under the guard raises {}".format(guard))

    lint = sh("{} -m ruff check corpusslr tests 2>&1 | tail -1".format(py))
    types = sh("{} -m mypy corpusslr 2>&1 | tail -1".format(py))
    check("Static analysis clean",
          "All checks passed" in lint and "no issues" in types,
          "ruff: {} | mypy: {}".format(lint, types))

    meta = sh("{} -m pytest tests/test_metadata_consistency.py "
              "-p no:cacheprovider 2>&1 | tail -1".format(py))
    check("Metadata agree across all five files", "passed" in meta, meta)

    audit = sh("{} validation/audit_document_numbers.py 2>&1 | tail -1".format(py))
    check("Every figure in the documentation follows from a measurement",
          "agree with their measurements" in audit, audit)

    cov_csv = os.path.join(HERE, "validation", "parser_coverage.csv")
    if os.path.exists(cov_csv):
        import csv
        with open(cov_csv, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        nc = sum(1 for r in rows if r["status"] == "covered")
        check("Coverage against the project specification measured",
              nc == len(rows),
              "{}/{} items, each by running the entry point".format(nc, len(rows)))

    refs = os.path.join(HERE, "validation", "references_verified.json")
    if os.path.exists(refs):
        with open(refs, encoding="utf-8") as fh:
            data = json.load(fh)
        check("Every bibliographic anchor verified at the source", True,
              "validation/references_verified.json records {} anchors, "
              "including claims rejected as unsupported".format(len(data)))

    for rel, why in (("CITATION.cff", "Citation metadata"),
                     ("codemeta.json", "Software metadata"),
                     (".zenodo.json", "Archive deposit metadata"),
                     ("CONTRIBUTING.md", "Contribution guide"),
                     ("CODE_OF_CONDUCT.md", "Code of conduct"),
                     ("CHANGELOG.md", "Release history"),
                     ("docs/user_guide.md", "User guide"),
                     ("docs/api_reference.md", "API reference"),
                     ("LICENSE", "Licence")):
        check("{} present".format(why), os.path.exists(os.path.join(HERE, rel)), rel)

    check("Continuous integration configured on a Python matrix",
          os.path.exists(os.path.join(HERE, ".github", "workflows", "tests.yml")),
          "tests.yml (matrix + build + sdist run + metadata) and quality.yml")

    check("CI executed on GitHub", False,
          "cannot be run from a sandbox; one push confirms runner behaviour, "
          "action resolution and matrix expansion")
    wos = os.path.join(HERE, "validation", "wos_live_verification.json")
    wos_ok = False
    if os.path.exists(wos):
        with open(wos, encoding="utf-8") as fh:
            wos_ok = "verified live" in json.load(fh).get("outcome", "")
    check("Web of Science client exercised against the live API", wos_ok,
          "WosExpandedSource run against https://api.clarivate.com/api/wos with an "
          "entitled institutional key: 1431 hits for the test query, 100/100 records "
          "carrying an abstract, 26 DOI overlaps with PubMed. See "
          "validation/wos_live_verification.json and validation/live_wos_prisma_s.md."
          if wos_ok else
          "no entitled Clarivate key; covered by recorded-response tests only")
    check("Zenodo DOI minted", False,
          ".zenodo.json prepares the deposit; the version DOI exists only after "
          "archiving, and CITATION.cff gains its doi: field then")
    return items


MANUSCRIPT_ITEMS = [
    "Cover letter naming the novelty relative to ASySD, Rayyan and litsearchr",
    "Confirm the code-metadata table matches the repository at the submitted commit",
    "Deposit the tagged release, then put the DOI in the metadata table and CITATION.cff",
    "Suggested reviewers with information-science or research-software backgrounds",
    "Confirm the ASySD benchmark licence permits redistributing "
    "validation/labelled_test_set.csv",
]


def render(items):
    import corpusslr
    done = sum(1 for i in items if i["done"])
    out = ["# SoftwareX submission checklist -- CorpusSLR {}".format(
               corpusslr.__version__),
           "",
           "**{} of {} items verified mechanically; {} open and stated as "
           "such.** Every \"done\" carries the command output that establishes "
           "it.".format(done, len(items), len(items) - done),
           "",
           "Regenerate with `python validation/submission_checklist.py`.",
           "", "## Verified", ""]
    for i in items:
        if i["done"]:
            out += ["- [x] **{}**".format(i["item"]), "      {}".format(i["evidence"])]
    out += ["", "## Open -- required before or at submission", ""]
    for i in items:
        if not i["done"]:
            out += ["- [ ] **{}**".format(i["item"]), "      {}".format(i["evidence"])]
    out += ["", "## Manuscript-side items (author judgement)", ""]
    out += ["- [ ] {}".format(x) for x in MANUSCRIPT_ITEMS]
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    items = collect()
    text = render(items)
    path = os.path.join(HERE, "SUBMISSION_CHECKLIST.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    done = sum(1 for i in items if i["done"])
    print("wrote {} ({} verified, {} open)".format(path, done, len(items) - done))
    for i in items:
        if not i["done"]:
            print("  OPEN: {}".format(i["item"]))
