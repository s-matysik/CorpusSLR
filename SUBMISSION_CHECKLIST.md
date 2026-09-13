# SoftwareX submission checklist -- CorpusSLR 1.0.0

**20 of 21 items verified mechanically; 1 open and stated as such.** Every "done" carries the command output that establishes it.

Regenerate with `python validation/submission_checklist.py`.

## Verified

- [x] **Test suite passes**
      2117 passed in 16.65s
- [x] **Coverage measured and above the CI floor**
      TOTAL                                   7006    159    98%
- [x] **Offline execution enforced, not asserted**
      a real connect under the guard raises NetworkUseInTestSuite
- [x] **Static analysis clean**
      ruff: All checks passed! | mypy: Success: no issues found in 40 source files
- [x] **Metadata agree across all five files**
      15 passed in 0.35s
- [x] **Every figure in the documentation follows from a measurement**
      all stated figures agree with their measurements
- [x] **Coverage against the project specification measured**
      32/32 items, each by running the entry point
- [x] **Every bibliographic anchor verified at the source**
      validation/references_verified.json records 22 anchors, including claims rejected as unsupported
- [x] **Citation metadata present**
      CITATION.cff
- [x] **Software metadata present**
      codemeta.json
- [x] **Archive deposit metadata present**
      .zenodo.json
- [x] **Contribution guide present**
      CONTRIBUTING.md
- [x] **Code of conduct present**
      CODE_OF_CONDUCT.md
- [x] **Release history present**
      CHANGELOG.md
- [x] **User guide present**
      docs/user_guide.md
- [x] **API reference present**
      docs/api_reference.md
- [x] **Licence present**
      LICENSE
- [x] **Continuous integration configured on a Python matrix**
      tests.yml (matrix + build + sdist run + metadata) and quality.yml
- [x] **CI executed on GitHub**
      all workflows green on s-matysik/CorpusSLR: pages success, pages build and deployment success, quality success, tests success
- [x] **Web of Science client exercised against the live API**
      WosExpandedSource run against https://api.clarivate.com/api/wos with an entitled institutional key: 1431 hits for the test query, 100/100 records carrying an abstract, 26 DOI overlaps with PubMed. See validation/wos_live_verification.json and validation/live_wos_prisma_s.md.

## Open -- required before or at submission

- [ ] **Zenodo DOI minted**
      .zenodo.json prepares the deposit; the version DOI exists only after archiving, and CITATION.cff gains its doi: field then

## Manuscript-side items (author judgement)

- [ ] Cover letter naming the novelty relative to ASySD, Rayyan and litsearchr
- [ ] Confirm the code-metadata table matches the repository at the submitted commit
- [ ] Deposit the tagged release, then put the DOI in the metadata table and CITATION.cff
- [ ] Suggested reviewers with information-science or research-software backgrounds
- [ ] Confirm the ASySD benchmark licence permits redistributing validation/labelled_test_set.csv
