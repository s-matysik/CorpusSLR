"""Reproducible harvesting: archive a live search, then replay it offline.

Demonstrates the full cycle that makes an API-native search auditable under
PRISMA-S:

1. **Harvest** the query against Crossref and Semantic Scholar, writing every
   raw HTTP response to a directory archive.
2. **Verify** the archive's integrity (all responses present and unmodified).
3. **Replay** the identical harvesting call against that archive with the
   network unused, and assert the record sets are field-for-field equal.
4. **Compare** two harvests of the same query to quantify database drift.

Both databases used here are open (no API key), so a reviewer can re-run
step 1 as well as steps 2-4.  Run::

    python examples/example_reproducible_harvest.py [output_dir]

Nothing but ``requests`` is required.  Deposit ``harvest_archive/`` next to the
manuscript: it is the evidence base of the search, and ``REPLAY.md`` tells a
reviewer how to use it.
"""
import os
import sys

from corpusslr import (Corpus, CrossrefSource, HarvestArchive, SearchQuery,
                       SemanticScholarSource, compare_harvests, deduplicate,
                       harvest, harvest_markdown, records_equal,
                       replay_harvest, verify_archive)

OUT = sys.argv[1] if len(sys.argv) > 1 else "harvest_demo"
ARCHIVE = os.path.join(OUT, "harvest_archive")
os.makedirs(OUT, exist_ok=True)

# Contact address: Crossref's polite pool. Optional, and never archived.
EMAIL = os.environ.get("CONTACT_EMAIL", "")
S2_KEY = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")

query = SearchQuery(
    blocks=[["artificial intelligence", "machine learning"],
            ["marketing"],
            ["adoption", "acceptance"]],
    years=(2020, 2023),
    doc_types=["article"],
)

# ---------------------------------------------------------------------------
# 1. Live harvest, archiving every raw response
# ---------------------------------------------------------------------------
print("1. Harvesting (live) into %s" % ARCHIVE)
archive = HarvestArchive.create(ARCHIVE)
harvests = []

cr = harvest(CrossrefSource(mailto=EMAIL), query, max_results=60,
             archive=archive)
harvests.append(cr)
print("   Crossref           %3d records  checksum %s  %d responses"
      % (len(cr.records), cr.checksum[:16], cr.manifest.n_responses))

# Semantic Scholar's unauthenticated pool is shared and throttled to roughly
# 1 request/s; the client spaces requests accordingly and retries on 429.
# A rate-limit failure must not lose the Crossref harvest, so it is caught -
# and the partial evidence stays in the archive either way.
try:
    s2 = harvest(SemanticScholarSource(api_key=S2_KEY), query,
                 max_results=60, archive=archive)
    harvests.append(s2)
    print("   Semantic Scholar   %3d records  checksum %s  %d responses"
          % (len(s2.records), s2.checksum[:16], s2.manifest.n_responses))
except Exception as exc:                      # noqa: BLE001 - rate limit
    print("   Semantic Scholar   skipped (%s: %s)"
          % (type(exc).__name__, str(exc)[:80]))

# ---------------------------------------------------------------------------
# 2. Integrity audit of the deposited evidence
# ---------------------------------------------------------------------------
problems = verify_archive(ARCHIVE)
print("\n2. Archive verification: %s"
      % ("OK - every response present and unmodified" if not problems
         else "; ".join(problems)))

# ---------------------------------------------------------------------------
# 3. Replay offline: the same call, served from the archive
# ---------------------------------------------------------------------------
print("\n3. Replaying from the archive (no network)")
for h in harvests:
    src = (CrossrefSource() if h.manifest.database == "Crossref"
           else SemanticScholarSource())
    rep = replay_harvest(src, query, ARCHIVE,
                         harvest_id=h.manifest.harvest_id)
    same = records_equal(h.records, rep.records)
    print("   %-18s %3d records  checksum match: %s  records equal: %s"
          % (h.manifest.database, len(rep.records),
             rep.checksum_matches, same))
    assert rep.checksum_matches and same, "replay diverged"

# ---------------------------------------------------------------------------
# 4. Drift: a second live harvest of the same query, differences quantified
# ---------------------------------------------------------------------------
print("\n4. Drift against a second live harvest of the same query")
second = harvest(CrossrefSource(mailto=EMAIL), query, max_results=60,
                 archive=os.path.join(OUT, "harvest_archive_rerun"))
diff = compare_harvests(cr, second, label_before="first run",
                        label_after="second run")
print("   " + diff.summary())
if diff.stable:
    print("   -> identical record set (relevance order is normalised away)")

# ---------------------------------------------------------------------------
# 5. Downstream: the harvest feeds the ordinary pipeline
# ---------------------------------------------------------------------------
corpus = Corpus()
for h in harvests:
    corpus.add_search(h.to_source_result())
result = deduplicate(corpus)
print("\n5. Pipeline: %d identified -> %d unique"
      % (corpus.total_identified(), len(result.records)))

with open(os.path.join(OUT, "harvest_appendix.md"), "w", encoding="utf-8") as fh:
    fh.write(harvest_markdown(harvests))
    fh.write("\n\n## Drift between the two runs\n\n")
    fh.write(diff.to_markdown())

with open(os.path.join(OUT, "REPLAY.md"), "w", encoding="utf-8") as fh:
    fh.write("""# How to reproduce this search

No API key and no database subscription are needed: the raw responses are in
`harvest_archive/`.

```bash
pip install corpusslr
python - <<'PY'
from corpusslr import (CrossrefSource, SearchQuery, replay_harvest,
                       verify_archive)

print(verify_archive("harvest_archive") or "archive intact")

query = SearchQuery(
    blocks=[["artificial intelligence", "machine learning"],
            ["marketing"], ["adoption", "acceptance"]],
    years=(2020, 2023), doc_types=["article"])

res = replay_harvest(CrossrefSource(), query, "harvest_archive",
                     harvest_id="H1")
print(len(res.records), "records; checksum matches:", res.checksum_matches)
PY
```

`checksum_matches: True` means you obtained exactly the record set the review
analysed.  To check how the database has changed since, re-run the live
harvest and diff the two manifests with `compare_harvests`.
""")
print("\nWrote: %s, %s, %s/" % (os.path.join(OUT, "harvest_appendix.md"),
                                os.path.join(OUT, "REPLAY.md"), ARCHIVE))
