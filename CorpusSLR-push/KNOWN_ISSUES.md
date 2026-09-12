# Known issues and disclosures

Things a reader or reviewer should know that are not defects to be fixed, but
properties of the evidence that would otherwise have to be inferred.

## 1. The headline discipline table differs from the per-track metrics files

`validation/domains_15_final.csv` is the table the article and Supplement S3
quote. `validation/domains_*_metrics.csv` are the per-track files produced
while the evaluation was being run. They disagree, and the disagreement is
deliberate:

| quantity | per-track files | headline table |
|---|---:|---:|
| disciplines whose row differs | - | 11 of 15 |
| false merges, pooled | 228 | 154 |
| judgeable pairs, pooled | 2634 | 2584 |
| median F1 | 0.9500 | 0.9592 |

Two causes, both intended:

1. **Three guards were added after the per-track runs.** Rejecting a
   missing-value literal in the DOI field, refusing fuzzy matches on a title
   that is only an identifier, and separating instalments of a recurring
   publication. Those guards are what removes false merges, so the per-track
   numbers are the state *before* them and the headline table the state
   *after*. This is why the pooled false-merge count falls.
2. **The scoring population is narrower in the headline table.** Crossref is
   capped at 300 records per discipline and non-work document types (peer
   reviews, datasets, errata, editorials) are excluded, so a few disciplines
   report fewer judgeable pairs.

`validation/eval_domains_15.py` regenerates the headline table from the
archived raw records and exits non-zero on any disagreement, so the table is
reproducible rather than a recorded snapshot:

```
PYTHONPATH=. python validation/eval_domains_15.py --check
```

`validation/verify_reviewer_claims.py` re-derives every figure in the table
above from the shipped files, so this disclosure cannot drift from the data.

## 2. Two checklist items cannot be closed from a sandbox

`SUBMISSION_CHECKLIST.md` leaves *CI executed on GitHub* and *Zenodo DOI
minted* open. Both need an action outside this environment: one push to
trigger the workflows, and one archive deposit to mint the version DOI.
Everything else in that checklist is verified mechanically.

## 3. The source distribution skips part of the test suite

Run from an unpacked source archive, the suite reports fewer passes than the
repository does. The difference is entirely `tests/test_publishing.py`, which
reads `.gitignore` and `.github/workflows/` - files a source distribution
correctly does not package. Zero failures either way.

## 4. The serial-publication guard is English-only

`period_markers()` recognises instalment markers such as "Part II", "Wave 3"
and "Annual Report 2019" in English. A non-English title carrying the same
structure is not separated, so two instalments of a non-English serial can
merge. Measured on the fifteen-discipline corpus the guard fires on 28 of
3,193 pairs, so the exposure is small, but it is a real limit rather than an
oversight.
