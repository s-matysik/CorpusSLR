# Third-party data redistributed here

This package is MIT-licensed, and everything in it was written for this project
with one exception, recorded below. The exception is data, not code, and it
carries the terms of the project it came from rather than this one.

## `validation/labelled_test_set.csv`

| | |
|---|---|
| What it is | The ASySD *Diabetes* gold standard: 1845 records with duplicate labels, the benchmark the deduplication result is scored against |
| Obtained from | `https://github.com/camaradesuk/ASySD`, path `tests/testthat/labelled_test_set.csv` |
| Upstream commit touching the file | `49544ce33171`, 2022-10-14 |
| SHA-256 of the copy here | `cc84d80163de15a412e6a2a1cff75f8c3369c85834476eeab0d6c2b49b52e45e` |
| Licence of the source repository | **GPL-3.0** |
| Citation | Hair K, Bahor Z, Macleod M, Liao J, Sena ES. The Automated Systematic Search Deduplicator (ASySD): a rapid, open-source, interoperable tool to remove duplicate citations in biomedical systematic reviews. *BMC Biology* 21:189, 2023. doi:10.1186/s12915-023-01686-z |

### Why the licence is stated as GPL-3.0 and not CC BY

The *article* is CC BY 4.0, and an earlier version of the packaging note in
`tools/build_data_package.py` said the file was redistributed under CC BY 4.0
on that basis. That was wrong, and it was corrected after checking rather than
after being challenged. The article's licence covers the article. The article
names the Open Science Framework project `https://osf.io/c9evs/` as the home of
the datasets, and the OSF node and both of its components were queried through
the OSF API: none of the three declares a licence. The copy actually used here
was downloaded from the GitHub repository, and that repository declares
GPL-3.0. So GPL-3.0 is the only licence explicitly attached to a copy anyone
here obtained, and it is what this notice states.

### What that means for reuse

The file is redistributed unmodified, with attribution, for the sole purpose of
making the published evaluation reproducible. Whether GPL-3.0 copyleft reaches
a labelled dataset at all is a question this notice does not attempt to settle;
recording the provenance and the upstream terms is what is in this project's
power. Anyone reusing the file should treat it as covered by the upstream
project's terms, cite the paper above, and not treat the MIT licence of this
package as extending to it.

If you would rather not redistribute it, delete it and fetch it directly:

```bash
curl -L -o validation/labelled_test_set.csv \
  https://raw.githubusercontent.com/camaradesuk/ASySD/49544ce33171/tests/testthat/labelled_test_set.csv
shasum -a 256 validation/labelled_test_set.csv
```

The checksum above is what that command should produce.
