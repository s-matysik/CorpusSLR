# Cover letter

To the Editors of SoftwareX

Dear Editors,

I am submitting **CorpusSLR: from one structured query to a PRISMA-documented
corpus** for consideration as an Original Software Publication.

## What the software does that existing tools do not

A systematic literature review begins with a multi-database search, and the
databases disagree about query syntax, field semantics, paging and export
format. Established review software addresses the stage *after* retrieval:
screening, ranking, extraction. The stage before it, where the disagreements
are paid for in manual work or in silently lost records, is still handled by
spreadsheets and reference managers. CorpusSLR covers that stage as one
library: a single structured query compiles to each database's syntax, records
arrive through native APIs or through parsed file exports where no open API
exists, deduplication is cascading and fully auditable, and the PRISMA 2020
flow diagram and the PRISMA-S search appendix are generated from recorded
provenance rather than reconstructed afterwards.

The reporting instrumentation is the part I would ask reviewers to weigh most
heavily. PRISMA-S requires the platform, the interface, the date run, the
strategy as executed and the number of records per database. Those facts exist
only while the search is running, which is why appendices are usually written
from memory. Here they are recorded as the search happens, and the appendix is
a build product.

## Relation to ASySD, and why this is not a patch to it

Deduplication invites direct comparison with ASySD (Hair et al. 2023), and the
manuscript makes that comparison in the form that survives scrutiny rather than
the form that flatters. I transcribed ASySD's published decision rule from its
own source and asked both rule sets about identical candidate pairs across
fifteen disciplines. Median pairwise F1 was 0.9510 for this implementation
against 0.9164 for that rule, higher here in 13 of 15 fields. Neither rule
dominates, and the manuscript says so: they sit at different operating points,
median recall 0.964 against 0.861, and ASySD routes 89.6% of what its automatic
rule misses to a manual review queue, which on this corpus is 2,974 pairs for a
human to inspect. Its policy of scoring a field absent on both sides as
agreement admits 68 false merges but buys 575 true pairs, so it is a deliberate
recall device, not a defect. The mechanism this work borrows from ASySD is
credited as such in the manuscript, in the ablation table and in the source
code.

The contribution to deduplication is therefore stated narrowly: typed,
logged *negative* evidence, separators that refuse a merge the positive
evidence would otherwise allow, each derived from a failure observed in a real
corpus. On the published ASySD *Diabetes* gold standard the result is TP 1260,
FP 0, FN 1, F1 0.9996, against ASySD's two misses on the same data.

This is not a pull request to ASySD because the scope differs: ASySD
deduplicates, in R, a corpus the user has already assembled. CorpusSLR
assembles it, from ten databases in two retrieval modes, and documents the
assembly to PRISMA-S. Deduplication is one stage of that chain, not the
product.

## Evidence accompanying the submission

Everything stated in the manuscript is measured and reproducible without
network access:

- a published biomedical gold standard, and a cross-disciplinary
  identifier-blind study of fifteen disciplines (2,584 judgeable pairs, median
  F1 0.9592) built to answer the objection that accuracy on one biomedical
  benchmark says nothing about a review in history or logistics;
- specification coverage measured by execution, 32 of 32 requirements, each
  entry point run against a sample reproducing a real vendor export rather than
  asserted to exist;
- interoperability verified by executing the downstream tool, not by declaring
  a format: the merged corpus written in Scopus export layout imports into
  `bibliometrix` with 597 of 597 records, 57 generated fields and a 986 x 986
  institutional collaboration network;
- a lossless round trip through the package's own parser on a real 597-record
  vendor export, 7,761 field comparisons, zero mismatches;
- 2121 offline tests, no network access anywhere in the suite, on Python 3.9
  through 3.13.

The validation data are packaged separately for review, with a manifest mapping
each file to the table or figure it supports. One file in that package is
third-party: the ASySD gold standard, redistributed unmodified under the
upstream project's licence, with provenance, pinned commit and checksum
recorded.

## Declarations

The software is MIT-licensed, the repository is public, and the version
archived for this submission is deposited with a DOI recorded in the code
metadata table. The author declares no competing interests. The manuscript has
not been published elsewhere and is not under consideration by another journal.

I would be glad to suggest reviewers with backgrounds in information science,
evidence synthesis methodology or research software engineering, and I welcome
reviewers connected to the tools discussed above: the comparison was written to
be checked.

Yours sincerely,

Sebastian Matysik
University of Szczecin
