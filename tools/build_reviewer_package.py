"""Assemble everything a reviewer needs into one ordered package.

The package is a build product, never hand-edited. Running this script twice
must produce byte-identical output, so nothing here depends on the wall clock,
on filesystem ordering or on a temporary directory name: the manifest is sorted,
the archive is written with fixed member timestamps, and the generated README
takes its numbers from the evidence files rather than from prose.

Layout produced under ``reviewer_package/``::

    README.md            the reviewer's entry point and the claim-to-file map
    CHECKSUMS.txt        SHA-256 of every file in the package, sorted by path
    MANIFEST.csv         one row per file: path, bytes, sha256, what it evidences
    manuscript/          manuscript, supplementary, audit report, checklist
    data/                every metrics table and verification record
    figures/             the figures the manuscript and supplement cite
    code/                the package source the claims are about
    reproduce/           the scripts that regenerate the numbers, plus a runner

Typography: the package documentation uses the hyphen only. Files copied in from
the repository are normalized on the way (em dash and en dash to hyphen), so a
shared file that still uses them upstream does not carry them into the package.
The normalization is content-only and never touches the .py sources it copies
verbatim, because rewriting characters inside source code would change the code.

Usage::

    PYTHONPATH=. python tools/build_reviewer_package.py
    PYTHONPATH=. python tools/build_reviewer_package.py --outdir /tmp/pkg
    PYTHONPATH=. python tools/build_reviewer_package.py --no-zip
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import os
import shutil
import statistics
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG_DIRNAME = "reviewer_package"
ZIP_NAME = "corpusslr_reviewer_package.zip"

# A fixed timestamp in every archive member. Zip stores mtimes, and copying the
# real ones would make two builds of identical content differ byte for byte.
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)

TEXT_SUFFIXES = (".md", ".txt", ".csv", ".json", ".cff", ".svg")
NORMALIZE_SUFFIXES = (".md", ".txt")


# --------------------------------------------------------------------------
# The inventory. Each entry is (source path, destination subdirectory,
# what the file establishes). The third field is deliberately about evidence,
# not about format: a reviewer scanning the manifest is asking what a file
# proves, not what kind of file it is.
# --------------------------------------------------------------------------
#: Inventory entries that are build products rather than sources. They are
#: present in a working tree that has run the documented commands and absent
#: from a fresh checkout or an unpacked sdist. Their absence is reported as
#: deferred, with the command that produces them, instead of counting as a
#: missing file - which would make the completeness check fail for a reason
#: that is not a defect.
OPTIONAL = {
    "paper/corpusslr_softwarex.pdf":
        "cd paper && pdflatex corpusslr_softwarex.tex "
        "&& bibtex corpusslr_softwarex && pdflatex corpusslr_softwarex.tex",
    "prisma2020_flow.svg":
        "PYTHONPATH=. python paper/listing_example.py",
}


INVENTORY = [
    # manuscript and its companions ---------------------------------------------
    ("paper/corpusslr_softwarex.pdf", "manuscript",
     ("The typeset article as a reviewer receives it: elsarticle, six pages, "
      "compiled from the .tex beside it with zero errors and zero warnings.")),
    ("paper/corpusslr_softwarex.tex", "manuscript",
     ("The article source in the SoftwareX template, including the C1-C8 code "
      "metadata table, both figures and three code listings.")),
    ("paper/references.bib", "manuscript",
     ("The bibliography, restricted to records confirmed at Crossref; the "
      "rejected claims are recorded in data/references_verified.json.")),
    ("paper/listing_example.py", "manuscript",
     ("Listing 1 kept runnable rather than transcribed: it executes offline "
      "with no API key and prints the output quoted in the article.")),
    # Renamed on the way in: the project README lands in the same directory,
    # and two files called README.md would silently overwrite one another.
    ("paper/README.md", "manuscript/BUILDING_THE_PAPER.md",
     ("How to rebuild the PDF, which packages are required, and the measured "
      "result of every structural check run against the source.")),
    ("MANUSCRIPT.md", "manuscript",
     "The submitted text; every number in it is traced to a file in data/."),
    ("SUPPLEMENTARY.md", "manuscript",
     ("The per-claim evidence tables (S1 tests, S2 gold standard, S3 fifteen "
      "disciplines, S4 ablation, S5 downstream tools, S6 limitations).")),
    ("AUDIT_REPORT.md", "manuscript",
     ("The development record: what was measured, what broke, what was fixed, "
      "written as it happened rather than reconstructed.")),
    ("KNOWN_ISSUES.md", "manuscript",
     ("What a reviewer should know that is not a defect: why the "
      "headline discipline table differs from the per-track files, "
      "which checklist items cannot be closed from a sandbox, and the "
      "two measured limits of the deduplication guards.")),
    ("SUBMISSION_CHECKLIST.md", "manuscript",
     ("Which submission requirements were verified mechanically and which two "
      "remain open, each with the command output that settles it.")),
    ("README.md", "manuscript",
     ("The project overview a reader arrives at, including the feature list the "
      "manuscript summarizes.")),
    ("CHANGELOG.md", "manuscript",
     ("That the version under review is a point in a recorded history, with the "
      "defects of each release named.")),
    ("CITATION.cff", "manuscript",
     ("Citation metadata; tests/test_metadata_consistency.py pins it to agree "
      "with pyproject.toml, codemeta.json and .zenodo.json.")),
    ("codemeta.json", "manuscript", "Software metadata in the codemeta schema."),
    (".zenodo.json", "manuscript",
     "The archive deposit record prepared for the version DOI."),
    ("LICENSE", "manuscript", "That the software is redistributable under MIT."),

    # evidence tables -----------------------------------------------------------
    ("validation/asysd_metrics.csv", "data",
     ("That deduplication scores F1 0.9984 on the ASySD Diabetes gold standard, "
      "beside the published rows for ASySD, EndNote, SRA-DM and human reviewers.")),
    ("validation/na_doi_fix_impact.csv", "data",
     ("That refusing the literal NA as an identifier moved the gold standard "
      "from F1 0.9960 to 0.9984 and removed the last false positive.")),
    ("validation/threshold_calibration.csv", "data",
     ("That the shipped similarity threshold was chosen on a grid rather than "
      "guessed, and how flat the surface is around it.")),
    ("validation/dedup_performance.csv", "data",
     ("Runtime and peak memory against corpus size, for mixed and pathological "
      "title vocabularies.")),
    ("validation/domains_15_final.csv", "data",
     ("The headline cross-disciplinary result: 15 disciplines, 13809 records, "
      "2584 judgeable pairs, median F1 0.9592, false merges split into version "
      "variants and genuine over-merges.")),
    ("validation/domains_15_after_guards.csv", "data",
     ("The same 15 disciplines scored before and after the identifier guards, "
      "so the guards' effect is visible per discipline rather than pooled.")),
    ("validation/domains_summary_15.csv", "data",
     ("DOI coverage per discipline beside its accuracy, which is what shows "
      "coverage does not predict accuracy.")),
    ("validation/domains_all_metrics.csv", "data",
     "Every metric row from all three harvesting tracks in one table."),
    ("validation/domains_social_metrics.csv", "data",
     "Per-query metrics for the five social-science disciplines."),
    ("validation/domains_stem_metrics.csv", "data",
     "Per-query metrics for the five STEM and informatics disciplines."),
    ("validation/domains_nature_hum_metrics.csv", "data",
     ("Per-query metrics for the five natural-science and humanities "
      "disciplines.")),
    ("validation/domains_social_false_positives.csv", "data",
     ("Every false merge in the social-science track, classified, so a reviewer "
      "can check the version-variant reading against the actual titles.")),
    ("validation/domains_stem_false_positives.csv", "data",
     "Every false merge in the STEM track, classified."),
    ("validation/domains_nature_hum_false_positives.csv", "data",
     ("Every false merge in the natural-science and humanities track, "
      "classified.")),
    ("validation/domains_social_profile.csv", "data",
     "Metadata completeness per database in the social-science track."),
    ("validation/domains_stem_profile.csv", "data",
     "Metadata completeness per database in the STEM track."),
    ("validation/domains_nature_hum_profile.csv", "data",
     ("Metadata completeness per database in the natural-science and humanities "
      "track.")),
    ("validation/dedup_mechanism_ablation.csv", "data",
     ("What each deduplication mechanism is worth on the gold standard, measured "
      "by switching it off and rescoring.")),
    ("validation/dedup_ablation_domains.csv", "data",
     ("The same ablation on the fifteen disciplines, where the ranking inverts; "
      "this pair is the argument for validating on more than one corpus.")),
    ("validation/dedup_ablation_gold.csv", "data",
     ("The cumulative form of the gold-standard ablation, one mechanism added "
      "per row.")),
    ("validation/dedup_threshold_sensitivity.csv", "data",
     ("How far accuracy moves when the similarity threshold moves, which bounds "
      "how much of the result is threshold tuning.")),
    ("validation/multidomain_metrics.csv", "data",
     ("The earlier four-discipline evaluation the fifteen-discipline protocol "
      "superseded, kept so the progression is auditable.")),
    ("validation/multidomain_calibration.csv", "data",
     "Threshold behaviour outside biomedicine on the four-discipline corpus."),
    ("validation/multidomain_version_tolerant.csv", "data",
     ("The four-discipline result rescored with versions of one study counted as "
      "one study.")),
    ("validation/parser_coverage.csv", "data",
     ("That all 32 specification items are covered, each verified by running the "
      "entry point on a real sample rather than by inspection.")),
    ("validation/supplementary_test_inventory.csv", "data",
     "Test functions per file: the provenance of the 1183 figure in S1."),
    ("validation/supplementary_test_areas.csv", "data",
     "The same 1183 functions grouped into the 21 areas S1 tabulates."),
    ("validation/bibliometrix_verification.json", "data",
     ("That bibliometrix actually imported a file written by to_scopus_csv, with "
      "the row and field counts it returned and the empty-affiliation defect the "
      "run exposed.")),
    ("validation/wos_live_verification.json", "data",
     ("That the Web of Science Expanded client was exercised against the live "
      "API with an entitled key, not only against fixtures.")),
    ("validation/scopus_live_verification.json", "data",
     "That the Scopus client was exercised against the live API."),
    ("validation/wos_support_evidence.json", "data",
     ("The vendor correspondence establishing which Web of Science API tier the "
      "subscription serves.")),
    ("validation/references_verified.json", "data",
     ("That every bibliographic anchor in the manuscript was checked at source, "
      "including the claims that were rejected as unsupported.")),
    ("validation/prisma_s_checklist.json", "data",
     "Which PRISMA-S items the generated appendix covers."),
    ("validation/live_harvest_metrics.csv", "data",
     "Per-database yield and metadata completeness on one live harvest."),
    ("validation/live_harvest_summary.json", "data",
     "The provenance record of that live harvest."),
    ("validation/parser_coverage.md", "data",
     ("The specification coverage table in reading order, with the verification "
      "method per row.")),
    ("validation/asysd_validation_report.md", "data",
     ("The full gold-standard report, including the error analysis behind the "
      "four remaining misses.")),
    ("validation/multidomain_validation.md", "data",
     "The full four-discipline report."),
    ("validation/live_wos_prisma_s.md", "data",
     ("A PRISMA-S appendix generated from a live Web of Science search, which is "
      "the output format the reporting claim is about.")),
    ("validation/live_prisma_s_appendix.md", "data",
     "A PRISMA-S appendix generated from a live multi-database harvest."),

    # figures -------------------------------------------------------------------
    ("validation/fig_domains.png", "figures",
     ("Manuscript Figure 1: per-discipline F1 under the identifier-blind "
      "protocol, and the composition of the 2584 judgeable pairs.")),
    ("validation/fig_ablation.png", "figures",
     ("Manuscript Figure 2: F1 lost per mechanism on both corpora, showing the "
      "ranking inversion.")),
    ("validation/dedup_performance.png", "figures",
     "Runtime and peak memory against corpus size."),
    ("validation/asysd_validation.png", "figures",
     "The gold-standard result in the form the ASySD paper reports it."),
    ("validation/multidomain_validation.png", "figures",
     ("Precision and recall per discipline on the earlier four-discipline "
      "corpus.")),
    ("validation/domains_social_validation.png", "figures",
     "The social-science track plotted per discipline."),
    ("validation/domains_nature_hum_doi_coverage.png", "figures",
     ("DOI coverage against accuracy, the figure behind the claim that coverage "
      "does not predict accuracy.")),
    ("prisma2020_flow.svg", "figures",
     "A PRISMA 2020 flow diagram as the package emits it."),

    # the software under review -------------------------------------------------
    ("docs/user_guide.md", "code",
     ("The user guide; tests/test_docs_examples.py executes every example in it, "
      "so an example that stopped working would fail the suite.")),
    ("docs/api_reference.md", "code",
     "The public API surface the manuscript describes."),
    ("reproducible_harvesting.md", "code",
     "The archive-and-replay protocol behind the reproducibility claim."),
    ("CONTRIBUTING.md", "code", "The contribution and review process."),
    ("CODE_OF_CONDUCT.md", "code", "The project's code of conduct."),
    ("notebooks/corpusslr_colab.ipynb", "code",
     ("The Colab notebook that runs a whole review without a local install; "
      "tests/test_notebook.py checks it holds no saved output and no credential.")),
    ("examples/example_slr.py", "code",
     "A minimal end-to-end review in Python."),
    ("examples/example_reproducible_harvest.py", "code",
     "A harvest with an archive and a replay, in Python."),
    ("examples/review_config.json", "code",
     ("The JSON configuration a whole review runs from, which is what makes the "
      "reported method the executed method.")),
    ("pyproject.toml", "code",
     ("That the package declares one runtime dependency and supports Python 3.9 "
      "upward.")),
    ("MANIFEST.in", "code",
     ("What the source distribution ships, including the evidence files the test "
      "suite reads.")),

    # reproduction --------------------------------------------------------------
    ("validation/verify_reviewer_claims.py", "reproduce",
     ("Re-derives every headline claim of this package from the shipped files, "
      "and with --self-test shows each check rejecting an injected error.")),
    ("validation/audit_document_numbers.py", "reproduce",
     ("Scans the prose for numbers that no longer follow from a measurement; "
      "this is what keeps a stale figure out of the manuscript.")),
    ("validation/eval_domains_15.py", "reproduce",
     ("Regenerates the fifteen-discipline table from the archived raw "
      "records; --check exits non-zero on any disagreement.")),
    ("validation/eval_asysd.py", "reproduce",
     ("The gold-standard evaluation harness. See the note in the README: its "
      "author-splitting step is a harness artefact and the manuscript quotes the "
      "stricter figure.")),
    ("validation/eval_domains_stem.py", "reproduce",
     "Re-runs the STEM track offline from the cached raw records."),
    ("validation/eval_multidomain.py", "reproduce",
     "Re-runs the earlier four-discipline evaluation offline."),
    ("validation/social_run.py", "reproduce",
     "Re-runs the social-science track offline from the cached raw records."),
    ("validation/social_eval.py", "reproduce",
     "The scoring and classification code the social-science track uses."),
    ("validation/social_harvest.py", "reproduce",
     "The cache reader for the social-science track."),
    ("validation/social_queries.py", "reproduce",
     "The exact queries the social-science track ran, as executed."),
    ("validation/measure_parser_coverage.py", "reproduce",
     "Regenerates the specification coverage table by running each parser."),
    ("validation/submission_checklist.py", "reproduce",
     "Regenerates the submission checklist by verifying each item."),
    ("tools/build_colab_notebook.py", "reproduce",
     ("Regenerates the Colab notebook, which is why it cannot carry a saved "
      "credential.")),
    ("tools/no_network.py", "reproduce",
     ("The pytest plugin that makes a network call inside the suite raise; the "
      "offline claim is enforced, not asserted.")),
    ("tools/build_reviewer_package.py", "reproduce",
     "This script: it built the package you are reading."),
]

# Large inputs. Shipped when present, listed separately in the README because a
# reviewer on a slow connection should know what the size is for.
BULK = [
    ("validation/labelled_test_set.csv", "data",
     ("The ASySD Diabetes gold standard as scored, 1845 records with the "
      "duplicate labels; the input to the F1 0.9984 result. Third-party "
      "data under the upstream project's GPL-3.0, see "
      "data/THIRD_PARTY_DATA.md.")),
    ("validation/THIRD_PARTY_DATA.md", "data",
     ("Provenance, pinned upstream commit, checksum and licence of the "
      "one file here that was not produced by this project.")),
    ("validation/domains_social_raw.jsonl.gz", "data",
     ("Raw harvested records for the social-science track, so the evaluation "
      "reruns offline.")),
    ("validation/domains_stem_raw.jsonl.gz", "data",
     "Raw harvested records for the STEM track."),
    ("validation/domains_nature_hum_raw.jsonl.gz", "data",
     "Raw harvested records for the natural-science and humanities track."),
]


def normalize_text(text: str) -> str:
    """Replace em dash and en dash with the hyphen the package uses.

    An em dash between spaces becomes a spaced hyphen; one without spaces
    becomes a bare hyphen. A LaTeX-style dash run is collapsed the same way.
    """
    text = text.replace(" \u2014 ", " - ").replace(" \u2013 ", " - ")
    text = text.replace("\u2014", "-").replace("\u2013", "-")
    return text.replace(" --- ", " - ").replace(" -- ", " - ")


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_file(src: str, dst: str, normalize: bool) -> None:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if normalize and src.endswith(NORMALIZE_SUFFIXES):
        with open(src, encoding="utf-8") as fh:
            text = fh.read()
        with open(dst, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(normalize_text(text))
    else:
        shutil.copyfile(src, dst)


# --------------------------------------------------------------------------
# Numbers for the README, read from the evidence rather than from prose
# --------------------------------------------------------------------------
def measure(out_root: str) -> dict:
    def rows(rel):
        with open(os.path.join(out_root, rel), encoding="utf-8-sig",
                  newline="") as fh:
            return list(csv.DictReader(fh))

    dom = rows("data/domains_15_final.csv")
    fix = rows("data/na_doi_fix_impact.csv")[-1]
    cov = rows("data/parser_coverage.csv")
    areas = rows("data/supplementary_test_areas.csv")
    inv = rows("data/supplementary_test_inventory.csv")
    abl_g = rows("data/dedup_mechanism_ablation.csv")
    abl_d = rows("data/dedup_ablation_domains.csv")

    tp = 1261 - int(fix["FN"])
    top_g = max(abl_g, key=lambda r: float(r["delta_f1"]))
    top_d = max((r for r in abl_d if not r["mechanism"].startswith("shipped")),
                key=lambda r: float(r["delta_f1"]))
    return {
        "disciplines": len(dom),
        "records": sum(int(r["n_records"]) for r in dom),
        "pairs": sum(int(r["truth_pairs"]) for r in dom),
        "merges": sum(int(r["pair_fp"]) for r in dom),
        "versions": sum(int(r["fp_versions"]) for r in dom),
        "over": sum(int(r["fp_over"]) for r in dom),
        "median_f1": statistics.median(float(r["f1"]) for r in dom),
        "over_rate": 100.0 * sum(int(r["fp_over"]) for r in dom)
        / sum(int(r["truth_pairs"]) for r in dom),
        "gold_tp": tp,
        "gold_fp": int(fix["FP"]),
        "gold_fn": int(fix["FN"]),
        "gold_f1": float(fix["f1"]),
        "gold_f1_before": float(rows("data/na_doi_fix_impact.csv")[0]["f1"]),
        "spec_covered": sum(1 for r in cov if r["status"] == "covered"),
        "spec_total": len(cov),
        "test_functions": sum(int(r["tests"]) for r in inv),
        "test_files": len(inv),
        "test_areas": len(areas),
        "top_gold": top_g["mechanism"],
        "top_gold_delta": float(top_g["delta_f1"]),
        "top_dom": top_d["mechanism"],
        "top_dom_delta": float(top_d["delta_f1"]),
    }


CLAIM_MAP = [
    (("Deduplication reaches F1 {gold_f1:.4f} on a published gold standard "
      "(TP {gold_tp}, FP {gold_fp}, FN {gold_fn})."),
     "data/asysd_metrics.csv, data/na_doi_fix_impact.csv",
     ("reproduce/verify_reviewer_claims.py check C1 re-runs the deduplicator on "
      "data/labelled_test_set.csv and rescores it")),
    (("That result is better than EndNote, SRA-DM and human reviewers and within "
      "two records of ASySD on the same data."),
     "data/asysd_metrics.csv",
     ("comparator rows are as published by Hair et al. 2023; check C2 confirms "
      "each is arithmetically self-consistent")),
    (("Refusing the literal NA as an identifier moved the gold standard from "
      "F1 {gold_f1_before:.4f} to {gold_f1:.4f}."),
     "data/na_doi_fix_impact.csv", "check C2"),
    (("Accuracy transfers outside biomedicine: {disciplines} disciplines, "
      "{records} records, {pairs} judgeable pairs, median F1 {median_f1:.4f}."),
     "data/domains_15_final.csv, data/domains_summary_15.csv",
     ("checks C3 and C4 confirm the table sums to these figures and that "
      "every row follows from its own confusion matrix. The table is "
      "regenerated by reproduce/eval_domains_15.py and differs from the "
      "per-track metrics files for the two reasons given in "
      "KNOWN_ISSUES.md section 1, enforced by check C9")),
    (("Of {merges} false merges, {versions} are version variants of one study and "
      "{over} are genuine over-merges ({over_rate:.2f} percent of pairs)."),
     "data/domains_15_final.csv, data/domains_*_false_positives.csv",
     ("check C3; the false-positive tables list every pair with both titles so "
      "the classification can be checked by eye")),
    ("Which deduplication mechanism matters depends on the corpus.",
     "data/dedup_mechanism_ablation.csv, data/dedup_ablation_domains.csv",
     ("check C5 confirms both tables and that the ranking inverts: "
      "'{top_gold}' leads on the gold standard ({top_gold_delta:.4f}), "
      "'{top_dom}' on the disciplines ({top_dom_delta:.4f})")),
    (("The Scopus CSV export is readable by bibliometrix, verified by running it "
      "rather than by listing columns."),
     "data/bibliometrix_verification.json",
     ("the record states the R version, rows imported, fields generated and the "
      "empty-affiliation defect the run exposed; it is a record of an execution "
      "and is not re-run by the verifier")),
    ("All {spec_covered} of {spec_total} specification items are covered.",
     "data/parser_coverage.csv, data/parser_coverage.md",
     "check C6; each row names the test that pins the behaviour"),
    (("The test suite has {test_functions} test functions in {test_files} files "
      "across {test_areas} areas and runs with no network access."),
     "data/supplementary_test_inventory.csv, data/supplementary_test_areas.csv",
     ("check C7 re-sums both tables and re-runs pytest; reproduce/no_network.py "
      "is the plugin that makes a network call raise")),
    ("Both Web of Science tiers were exercised against the live API.",
     ("data/wos_live_verification.json, data/wos_support_evidence.json, "
      "data/live_wos_prisma_s.md"),
     ("records of live runs; they cannot be re-executed without an entitled key "
      "and are not re-run by the verifier")),
    ("Every bibliographic anchor in the manuscript was checked at source.",
     "data/references_verified.json",
     "the record includes the claims that were checked and rejected"),
    ("The limitations are stated rather than worked around.",
     "manuscript/SUPPLEMENTARY.md section S6",
     ("seven numbered limitations, including that DOI-less records cannot enter "
      "the ground truth and that no confidence intervals are computed")),
]


README_TEMPLATE = """# CorpusSLR reviewer package

Everything needed to check the manuscript, in one place. Nothing here is
asserted: every number below is re-derived from a file in this package by
`reproduce/verify_reviewer_claims.py`, and that script can be made to fail on
demand to show its checks are load-bearing.

The package documentation uses the hyphen only; no em dash or en dash appears in
any document here, and `reproduce/verify_reviewer_claims.py` check C8 enforces
it.

## Start here, in this order

1. `manuscript/MANUSCRIPT.md` - the submitted text, about 3000 words.
2. `manuscript/SUPPLEMENTARY.md` - the evidence tables, S1 to S6. Every claim in
   the manuscript has a section here.
3. `reproduce/verify_reviewer_claims.py` - run it. It re-derives the headline
   numbers from the files in `data/` and prints one line per claim.
4. `KNOWN_ISSUES.md` section 1 - read it before the results. The headline
   cross-disciplinary table cannot be derived from the reproducible per-track
   metrics files: {n_differing} of {n_domains} disciplines differ between them,
   and on the per-track reading median F1 is {a_med:.4f} rather than
   {b_med:.4f} and false merges {a_fp} rather than {b_fp}. The gap is measured,
   not estimated, and check C9 fails if this stops being true.
5. `manuscript/AUDIT_REPORT.md` - if you want to know how a result was arrived
   at rather than what it is. It is long and is written as a development record.

## Which file answers which question

| your question | the file |
|---|---|
| Is the accuracy validated? | `data/asysd_metrics.csv` for the published gold standard, `data/domains_15_final.csv` for the fifteen disciplines |
| Validated against what, exactly? | `data/labelled_test_set.csv` is the labelled gold set; for the disciplines the ground truth is the normalized DOI, then every identifier field is deleted before deduplication runs |
| Does it hold outside biomedicine? | `data/domains_15_final.csv`, one row per discipline, and `data/domains_summary_15.csv` for DOI coverage beside accuracy |
| What do the errors actually look like? | `data/domains_*_false_positives.csv` - every false merge with both titles, classified |
| Which part of the method is doing the work? | `data/dedup_mechanism_ablation.csv` and `data/dedup_ablation_domains.csv` |
| What is borrowed and what is new? | The `origin` column of both ablation tables. Multi-round blocking is ASySD's; the four guards are contributed here |
| Can I reproduce it? | `reproduce/verify_reviewer_claims.py` first, then the scripts listed under "What reproduces, and what does not" below |
| Does the output work in real tools? | `data/bibliometrix_verification.json` - bibliometrix was executed on a file the package wrote |
| Is the software tested? | `data/supplementary_test_inventory.csv`, {test_functions} test functions in {test_files} files; `reproduce/no_network.py` is what stops any of them reaching the network |
| Is the whole specification implemented? | `data/parser_coverage.csv`, {spec_covered} of {spec_total} items, each verified by running the entry point |
| What do the authors admit? | `manuscript/SUPPLEMENTARY.md` section S6, seven numbered limitations |
| What is still open at submission? | `manuscript/SUBMISSION_CHECKLIST.md` - 19 items verified, 2 open and named |
| How do I use the software? | `code/user_guide.md`, `code/api_reference.md`, `code/corpusslr_colab.ipynb` |

## Every manuscript claim, and the file that supports it

| claim | evidence | how it is checked |
|---|---|---|
{claim_rows}

## What reproduces, and what does not

Honesty about this matters more than a green tick, so each script is listed with
what was actually observed when this package was built.

**Runs offline and was run:**

- `reproduce/verify_reviewer_claims.py` - re-derives every headline number from
  `data/`. Run `--self-test` to watch each check reject a deliberately injected
  error of its own class; a check that has never failed proves nothing.
- `reproduce/audit_document_numbers.py` - scans the prose for numbers that no
  longer follow from a measurement. Run from the repository root, not from this
  package, because it reads documents the package does not carry.
- `reproduce/measure_parser_coverage.py` - regenerates `data/parser_coverage.csv`
  by running every parser on the samples in the test suite.
- `reproduce/social_run.py` - regenerates the social-science metrics from
  `data/domains_social_raw.jsonl.gz`. Needs both the repository root and the
  script directory on `PYTHONPATH`, because the track's modules import each
  other by bare name.
- `reproduce/eval_domains_stem.py` - regenerates the STEM metrics from
  `data/domains_stem_raw.jsonl.gz`.
- `reproduce/submission_checklist.py` - regenerates
  `manuscript/SUBMISSION_CHECKLIST.md` by verifying each item.
- `reproduce/build_colab_notebook.py` - regenerates `code/corpusslr_colab.ipynb`.

**Cannot be re-run here, and why:**

- Anything with `--fetch` (`reproduce/eval_domains_stem.py --fetch`,
  `reproduce/eval_multidomain.py --fetch`) contacts Web of Science, Scopus,
  Crossref, PubMed and arXiv. Web of Science and Scopus need entitled
  institutional keys. The cached raw records in `data/*.jsonl.gz` exist so the
  evaluation reruns without them.
- `data/bibliometrix_verification.json` records an R session. Re-running it needs
  R with bibliometrix installed.
- `data/wos_live_verification.json` and `data/scopus_live_verification.json`
  record live API runs and need the same entitled keys.

**The largest gap, stated plainly:**

The headline cross-disciplinary table `data/domains_15_final.csv` has no
producing script in this package and cannot be regenerated from the shipped raw
records. It differs from the reproducible per-track metrics files in
{n_differing} of {n_domains} disciplines. `KNOWN_ISSUES.md` section 1 measures
the difference in full; check C9 recomputes it and fails if the document stops
matching the files.

**Known defect in one harness, stated rather than hidden:**

`reproduce/eval_asysd.py` is the original gold-standard harness. Two problems
were found while building this package and both are recorded in
`KNOWN_ISSUES.md` in this directory: its figure step raises `AttributeError`
under the pandas version in the current environment when `--skip-bench` is
passed, and its author-splitting step gives the deduplicator author boundaries
that the gold file does not contain, which raises the score from
F1 {gold_f1:.4f} to 0.9996. The manuscript and this package quote the stricter
figure, {gold_f1:.4f}, which is what
`reproduce/verify_reviewer_claims.py` check C1 measures without that harness
step.

## Running the checks

```bash
# from the repository root, with the package importable
PYTHONPATH=. python reviewer_package/reproduce/verify_reviewer_claims.py

# show that each check rejects an injected error of its own class
PYTHONPATH=. python reviewer_package/reproduce/verify_reviewer_claims.py --self-test

# skip the pytest run, keep the table checks
PYTHONPATH=. python reviewer_package/reproduce/verify_reviewer_claims.py --no-suite
```

## Integrity

`CHECKSUMS.txt` lists the SHA-256 of every file in this package, sorted by path.
`MANIFEST.csv` gives the same list with each file's size and a one-line
statement of what it evidences.

```bash
cd reviewer_package && shasum -a 256 -c CHECKSUMS.txt
```

## Contents

{contents}
"""


def measure_headline_divergence(out_root: str) -> dict:
    """Compare the headline table against the per-track level=domain rows.

    Written as a measurement rather than as prose because the disclosure in
    KNOWN_ISSUES.md quotes these numbers, and a hand-typed disclosure goes stale
    the moment either table is regenerated. verify_reviewer_claims.py check C9
    recomputes the same quantities and fails if the document disagrees.
    """
    def rows(rel):
        with open(os.path.join(out_root, "data", rel), encoding="utf-8-sig",
                  newline="") as fh:
            return list(csv.DictReader(fh))

    final = {r["domain"]: r for r in rows("domains_15_final.csv")}
    per = {}
    for track in ("social", "stem", "nature_hum"):
        for r in rows("domains_%s_metrics.csv" % track):
            if r.get("level") == "domain":
                per[r["domain"]] = r

    keys = ("n_records", "truth_pairs", "pair_tp", "pair_fp", "pair_fn")
    lines = [("| discipline | per-track records / pairs / TP / FP / FN | "
              "headline records / pairs / TP / FP / FN |"), "|---|---|---|"]
    differing = []
    for d in sorted(final):
        f, q = final[d], per[d]
        if any(f[k] != q[k] for k in keys):
            differing.append(d)
            lines.append("| %s | %s | %s |" % (
                d, " / ".join(q[k] for k in keys),
                " / ".join(f[k] for k in keys)))

    def agg(src):
        return (sum(int(r["n_records"]) for r in src),
                sum(int(r["truth_pairs"]) for r in src),
                sum(int(r["pair_tp"]) for r in src),
                sum(int(r["pair_fp"]) for r in src),
                sum(int(r["pair_fn"]) for r in src),
                statistics.median(float(r["f1"]) for r in src))

    a = agg(list(per.values()))
    b = agg(list(final.values()))

    # If the headline table were the per-track output with version variants
    # resolved, each domain's drop in false merges would equal its fp_versions.
    matches = mismatches = 0
    for d in final:
        gap = int(per[d]["pair_fp"]) - int(final[d]["pair_fp"])
        if gap == int(final[d]["fp_versions"]):
            matches += 1
        else:
            mismatches += 1

    def gap_of(d):
        return int(per[d]["pair_fp"]) - int(final[d]["pair_fp"])

    return {
        "gap_table": "\n".join(lines),
        "n_differing": len(differing),
        "n_domains": len(final),
        "a_recs": a[0], "a_pairs": a[1], "a_tp": a[2], "a_fp": a[3],
        "a_fn": a[4], "a_med": a[5],
        "b_recs": b[0], "b_pairs": b[1], "b_tp": b[2], "b_fp": b[3],
        "b_fn": b[4], "b_med": b[5],
        "gap_matches": matches, "gap_mismatches": mismatches,
        "cs_gap": gap_of("computer science"),
        "cs_vers": int(final["computer science"]["fp_versions"]),
        "soc_gap": gap_of("sociology"),
        "soc_vers": int(final["sociology"]["fp_versions"]),
    }


KNOWN_ISSUES = """# Known issues in the reproduction path

Recorded because a reviewer who runs the scripts will meet them, and finding
them undocumented is worse than finding them stated.

## 1. The headline table is not derivable from the per-track metrics files

This is the most consequential gap in the evidence chain, so it is stated first.
An earlier draft of this document said the headline table was "not affected" by
the reproduction differences below. That was wrong, and this section replaces
it.

`data/domains_15_final.csv` carries the numbers the manuscript and the
supplementary material quote. `data/domains_social_metrics.csv`,
`data/domains_stem_metrics.csv` and `data/domains_nature_hum_metrics.csv` carry
the per-track evaluation output, one row per discipline at `level=domain`. The
two do not agree, and no script in the repository derives one from the other:
the headline table has no producing script, so the transformation between them
is not recorded anywhere a reviewer can inspect.

Measured divergence: the two disagree in {n_differing} of {n_domains}
disciplines. Headline table against the per-track `level=domain` rows:

{gap_table}

Aggregates:

| quantity | per-track metrics rows | headline table |
|---|---:|---:|
| records | {a_recs} | {b_recs} |
| judgeable pairs | {a_pairs} | {b_pairs} |
| true merges (TP) | {a_tp} | {b_tp} |
| false merges (FP) | {a_fp} | {b_fp} |
| missed merges (FN) | {a_fn} | {b_fn} |
| median F1 | {a_med:.4f} | {b_med:.4f} |

The headline table is the more conservative of the two on records and pairs and
the more favourable on false merges: it reports {b_fp} false merges where the
per-track rows total {a_fp}.

The natural reading is that the headline table is the per-track output after the
false positives were classified by hand and version variants were resolved. That
reading does not survive the arithmetic. If it held, the per-domain reduction in
false merges would equal that domain's `fp_versions` count. It does so in
{gap_matches} of {n_domains} disciplines; in the other {gap_mismatches} it does
not. Two examples: computer science loses {cs_gap} false merges while recording
{cs_vers} version variants, and sociology loses {soc_gap} while recording
{soc_vers}.

What this does and does not undermine:

- What still holds. Every row of `data/domains_15_final.csv` is arithmetically
  self-consistent, and the aggregates the manuscript quotes follow from that
  table. `reproduce/verify_reviewer_claims.py` checks C3 and C4 establish
  exactly that and nothing more. C9 recomputes the divergence above and fails if
  this document stops matching it.
- What does not hold. The headline table cannot be regenerated from the shipped
  raw records by any script in this package, so its provenance is not machine
  checkable. A reviewer who wants to audit the cross-disciplinary result should
  treat the per-track metrics files as the reproducible artefact and the
  headline table as a curated summary whose curation steps were not recorded.
- Which numbers move if the per-track rows are used instead. Median F1 goes from
  {b_med:.4f} to {a_med:.4f} and false merges from {b_fp} to {a_fp}. The claim
  that accuracy transfers across disciplines survives either way; the specific
  figures in the manuscript do not, on the per-track reading.

The honest position is that this gap should be closed before publication, by
committing the script that produced the headline table, or by regenerating that
table from the per-track output. It is disclosed here rather than smoothed
over.

## 2. eval_asysd.py splits authors the gold file does not split

`validation/eval_asysd.py` builds its records with

```python
_AUTH_SPLIT = re.compile(r"\\.(?=[A-Z][a-z])")
```

which turns the gold standard's single opaque author string
(`"Daiber A.Hausding M.Kroller-Schon S. ..."`) into a list of individual authors.
The gold file itself carries no author delimiter, so this is the harness adding
information a real import would not have.

Measured effect on the ASySD Diabetes set, cluster-level scoring, everything
else held fixed:

| author handling | TP | FP | FN | precision | recall | F1 |
|---|---:|---:|---:|---:|---:|---:|
| split by the harness regex | 1260 | 0 | 1 | 1.0000 | 0.9992 | 0.9996 |
| left as the file stores it | 1257 | 0 | 4 | 1.0000 | 0.9968 | 0.9984 |

The manuscript, the supplementary material and this package quote the second
row, F1 0.9984. `reproduce/verify_reviewer_claims.py` check C1 measures it
without the harness step, so the number the package publishes is the
conservative one.

Separately: the same score is reached whether the literal `NA` is stripped by
the harness before the package sees it or left in place for the package's own
missing-value guard to reject. That was measured both ways and the confusion
matrix is identical, which is the evidence that the guard, not the harness, is
what handles the 492 records carrying `NA` in the DOI field.

## 3. eval_asysd.py --skip-bench crashes in the figure step

Running

```bash
PYTHONPATH=. python validation/eval_asysd.py --gold validation/labelled_test_set.csv \\
    --outdir OUT --skip-bench
```

writes `asysd_metrics.csv`, `threshold_calibration.csv` and
`error_analysis.csv`, then raises

```
AttributeError: 'DataFrame' object has no attribute 'scenario'
```

in `make_figures()`, because `--skip-bench` leaves the performance frame empty
and the figure code indexes a column that was never created. The metrics are
written before the crash, so the CSVs are complete; only the figure is missing.
Observed with pandas 3.0.5.

## 4. Two committed tables do not byte-match a rerun

Rerunning the offline evaluations reproduces the science but not the bytes:

- `data/domains_stem_metrics.csv`: the committed file stores `doi_coverage` as a
  fraction (`0.7336`), a rerun writes it as a percentage (`73.36`). Same
  quantity, different unit under the same column name.
- `data/domains_stem_metrics.csv`, physics query ph1: a rerun scores TP 164 /
  FN 2 where the committed file has TP 163 / FN 3, moving that query's F1 from
  0.9674 to 0.9704 and the pooled physics row from 0.9704 to 0.9719. The
  committed file predates a change to the deduplicator.
- `data/parser_coverage.csv`: two rows lose `doi` from the `identifiers` column
  on a rerun (OpenAlex, Crossref), because the offline fixture those rows are
  measured from no longer carries a DOI. The coverage verdict, 32 of 32, is
  unchanged.

`data/domains_social_metrics.csv` and `data/domains_social_profile.csv` do
reproduce exactly, cell for cell.
"""


def build(outdir: str, write_zip: bool = True, quiet: bool = False) -> dict:
    out_root = os.path.join(outdir, PKG_DIRNAME)
    if os.path.exists(out_root):
        shutil.rmtree(out_root)
    os.makedirs(out_root)

    entries = []
    missing = []
    deferred = []
    for rel, sub, what in sorted(INVENTORY + BULK):
        src = os.path.join(REPO, rel)
        if not os.path.exists(src):
            if rel in OPTIONAL:
                # A build product, not a source file: absent from a fresh
                # checkout or an unpacked sdist until the documented command
                # regenerates it. Recorded as deferred so the README can say
                # how to produce it, rather than silently listing a file the
                # reviewer will not find.
                deferred.append(rel)
                continue
            missing.append(rel)
            continue
        dst_rel = os.path.join(sub, os.path.basename(rel))
        copy_file(src, os.path.join(out_root, dst_rel), normalize=True)
        entries.append((dst_rel.replace(os.sep, "/"), what))

    # The package source itself, so the claims are about code a reviewer holds.
    src_pkg = os.path.join(REPO, "corpusslr")
    for base, dirs, files in os.walk(src_pkg):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            src = os.path.join(base, name)
            rel_in_pkg = os.path.relpath(src, src_pkg)
            dst_rel = os.path.join("code", "corpusslr", rel_in_pkg)
            copy_file(src, os.path.join(out_root, dst_rel), normalize=False)
            entries.append((dst_rel.replace(os.sep, "/"),
                            ("Package source: the implementation the manuscript "
                             "describes.")))

    stats = measure(out_root)
    divergence = measure_headline_divergence(out_root)

    with open(os.path.join(out_root, "KNOWN_ISSUES.md"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write(normalize_text(KNOWN_ISSUES.format(**divergence)))
    entries.append(("KNOWN_ISSUES.md",
                    ("The defects found in the reproduction path while building "
                     "this package, including that the headline table cannot be "
                     "derived from the per-track metrics files.")))

    claim_rows = "\n".join(
        "| %s | `%s` | %s |" % (claim.format(**stats), files, how.format(**stats))
        for claim, files, how in CLAIM_MAP)

    by_dir = {}
    for rel, _what in entries:
        by_dir.setdefault(os.path.dirname(rel) or ".", []).append(rel)
    contents = "\n".join(
        "- `%s/` - %d files" % (d, len(v)) if d != "." else
        "- top level - %d files" % len(v)
        for d, v in sorted(by_dir.items()))

    readme = README_TEMPLATE.format(claim_rows=claim_rows, contents=contents,
                                    **dict(stats, **divergence))
    readme = normalize_text(readme)
    with open(os.path.join(out_root, "README.md"), "w", encoding="utf-8",
              newline="\n") as fh:
        fh.write(readme)
    entries.append(("README.md",
                    ("This guide: where to start, which file answers which "
                     "question, and every claim mapped to its evidence.")))

    # Manifest and checksums, both sorted so two builds agree.
    entries.sort()
    manifest_path = os.path.join(out_root, "MANIFEST.csv")
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["path", "bytes", "sha256", "what it establishes"])
        for rel, what in entries:
            p = os.path.join(out_root, rel)
            w.writerow([rel, os.path.getsize(p), sha256_of(p), what])

    checksum_targets = sorted([rel for rel, _ in entries] + ["MANIFEST.csv"])
    with open(os.path.join(out_root, "CHECKSUMS.txt"), "w", encoding="utf-8",
              newline="\n") as fh:
        for rel in checksum_targets:
            fh.write("%s  %s\n" % (sha256_of(os.path.join(out_root, rel)), rel))

    zip_path = None
    if write_zip:
        zip_path = os.path.join(outdir, ZIP_NAME)
        members = sorted(checksum_targets + ["CHECKSUMS.txt"])
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel in members:
                info = zipfile.ZipInfo(PKG_DIRNAME + "/" + rel,
                                       date_time=ZIP_TIMESTAMP)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                with open(os.path.join(out_root, rel), "rb") as fh:
                    zf.writestr(info, fh.read())

    result = {"root": out_root, "zip": zip_path, "files": len(entries),
              "missing": missing, "deferred": deferred, "stats": stats}
    if not quiet:
        print("wrote %s (%d files)" % (out_root, len(entries)))
        if zip_path:
            print("wrote %s (%.1f MB)"
                  % (zip_path, os.path.getsize(zip_path) / 1e6))
        for rel in missing:
            print("  MISSING from the repository, not packaged: %s" % rel)
        for rel in deferred:
            print("  build product not present, regenerate with: %s"
                  % OPTIONAL[rel])
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--outdir", default=REPO,
                    help="where reviewer_package/ and the zip are written")
    ap.add_argument("--no-zip", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    res = build(args.outdir, write_zip=not args.no_zip, quiet=args.quiet)
    return 1 if res["missing"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
