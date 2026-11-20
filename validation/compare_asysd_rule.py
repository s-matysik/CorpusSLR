"""Compare this package's decision logic with ASySD's published rule set.

What this is
------------
ASySD (Hair et al. 2023, BMC Biology 21:189) decides duplicate pairs with a
disjunction of 23 clauses over per-field Jaro-Winkler similarities, followed by
two demotion filters (mismatching DOI, year gap greater than one). The clause
set is transcribed here from the package's own source, ``R/internal.R``
(function ``identify_true_matches``), retrieved from
https://github.com/camaradesuk/ASySD.

What this is NOT
----------------
This is **not** a benchmark of ASySD the software. Three differences matter:

1. Only the automatic decision is compared. ASySD's workflow also builds a
   ``maybe_pairs`` set and routes it to *manual* deduplication in a Shiny app.
   ``--queue`` measures how much of the automatic shortfall that queue would
   put in front of a human, so the reader can see what the comparison omits.
2. The two procedures are NOT given the same candidate pairs. The transcribed
   ASySD rule decides the pairs returned by ``candidate_pairs()``, which uses
   some of this package's blocking keys. CorpusSLR receives all the records
   through ``deduplicate()`` and applies its own candidate selection, which
   includes further blocking rules. The comparison is therefore between two
   procedures, and a difference in candidate selection is part of what it
   measures. It does not isolate the decision rule. Giving both the same pairs
   would need a change to the package's candidate selection.
3. ISBN is absent from these journal corpora, so ASySD's four ISBN clauses
   cannot fire. They cannot fire on such corpora in the R package either.

On the biomedical gold standard the published ASySD F1 is 0.999 (from rounded
published values) and this package's is 0.9996 under the reference-label
convention. Nothing below should be read as a general claim of superiority. The
point of the exercise is the *shape* of the disagreement outside biomedicine,
which is where neither rule set was tuned.

The manual-queue columns count different things and must not be added:

* ``manual_queue_pairs``: candidate pairs that satisfy the ``maybe_pair``
  predicate. It includes pairs the automatic rule already accepts.
* ``manual_pairs_auto_accepted``: of those, the pairs the automatic rule accepts
  directly. ASySD removes these before manual review.
* ``manual_pairs_after_auto``: the remainder. It is an upper bound on the pairs
  a reviewer would see, because ASySD's R code also adds some conflicts and
  processes grouped pairs, which is not reproduced here.
* ``missed_in_manual_queue``: missed same-DOI pairs that satisfy the predicate,
  over ALL missed pairs, including those that were never generated as
  candidates.
* ``missed_in_candidates_and_queue``: the same, restricted to pairs that were
  generated as candidates, i.e. pairs this procedure would actually have put in
  front of a reviewer.

The number of decisions a reviewer would make in ASySD was not measured.

Usage
-----
    python validation/compare_asysd_rule.py            # writes the three CSVs
    python validation/compare_asysd_rule.py --check    # verify the committed CSVs

Requires ``jellyfish`` for Jaro-Winkler. It is a comparison-only dependency and
is deliberately not a dependency of the package.
"""

from __future__ import annotations

import argparse
import copy
import csv
import gzip
import itertools
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:                                     # pragma: no cover
    sys.path.insert(0, HERE)

from corpusslr import Record, deduplicate                    # noqa: E402
from corpusslr.dedup import _round_keys                      # noqa: E402
from corpusslr.validate import (clusters_from_decisions,     # noqa: E402
                                hide_identifiers, pair_metrics, truth_groups)

TRACKS = ("social", "stem", "nature_hum")

#: Document types that are not works and are excluded from scoring, matching
#: the fifteen-discipline evaluation in eval_domains_15.py.
NONWORK = {"peer-review", "dataset", "other", "component", "grant", "erratum",
           "editorial-material", "correction"}

#: ASySD forces these scores when a field is missing on BOTH sides. Note the
#: asymmetry: pages, volume and number score 1.0, so "neither record says" is
#: counted as agreement. That single policy is measured separately below,
#: because it is what admits most of the rule's false merges and, at the same
#: time, what buys it most of its recall.
BOTH_MISSING = {"abstract": 0.0, "pages": 1.0, "volume": 1.0, "number": 1.0,
                "doi": 0.0, "isbn": 0.0, "year": 0.0, "journal": 0.0}


def _data_path(name):
    for cand in (os.path.join(HERE, "validation", name),
                 os.path.join(os.path.dirname(os.path.abspath(__file__)), name)):
        if os.path.exists(cand):
            return cand
    return os.path.join(HERE, "validation", name)


def _jw(a, b):
    import jellyfish
    if a is None or b is None:
        return None
    a, b = str(a).strip(), str(b).strip()
    if not a or not b:
        return None
    return jellyfish.jaro_winkler_similarity(a, b)


def scores(a, b, strict_missing=False):
    """The nine per-field similarities ASySD computes for a pair."""
    raw = {"author": (a.authors[0] if a.authors else None,
                      b.authors[0] if b.authors else None),
           "title": (a.title, b.title), "abstract": (a.abstract, b.abstract),
           "year": (a.year, b.year), "pages": (a.pages, b.pages),
           "number": (a.issue, b.issue), "volume": (a.volume, b.volume),
           "journal": (a.journal, b.journal), "isbn": (None, None),
           "doi": (a.doi, b.doi)}
    out = {}
    for field, (x, y) in raw.items():
        value = _jw(x, y)
        if value is None:
            both_empty = (not str(x or "").strip()) and (not str(y or "").strip())
            if both_empty and strict_missing and field in ("pages", "volume",
                                                           "number"):
                value = 0.0
            else:
                value = BOTH_MISSING.get(field, 0.0) if both_empty else 0.0
        out[field] = value
    return out


def is_true_pair(s):
    """ASySD's 23-clause disjunction, transcribed from R/internal.R."""
    p, v, n, t = s["pages"], s["volume"], s["number"], s["title"]
    ab, au, j, i, d = (s["abstract"], s["author"], s["journal"], s["isbn"],
                       s["doi"])
    return (
        (p > .8 and v > .8 and t > .90 and ab > .90 and au > .50 and i > .99) or
        (p > .8 and v > .8 and t > .90 and ab > .90 and au > .50 and j > .6) or
        (p > .8 and n > .8 and t > .90 and ab > .90 and au > .50 and j > .6) or
        (v > .8 and n > .8 and t > .90 and ab > .90 and au > .50 and j > .6) or
        (v > .8 and n > .8 and t > .90 and ab > .90 and au > .8) or
        (v > .8 and p > .8 and t > .90 and ab > .9 and au > .8) or
        (p > .8 and n > .8 and t > .90 and ab > .9 and au > .8) or
        (d > .95 and au > .75 and t > .9) or
        (t > .80 and ab > .90 and v > .85 and j > .65 and au > .9) or
        (t > .90 and ab > .80 and v > .85 and j > .65 and au > .9) or
        (p > .8 and v > .8 and t > .90 and ab > .8 and au > .9 and j > .75) or
        (p > .8 and n > .8 and t > .90 and ab > .80 and au > .9 and j > .75) or
        (v > .8 and n > .8 and t > .90 and ab > .8 and au > .9 and j > .75) or
        (t > .9 and au > .9 and ab > .9 and j > .7) or
        (t > .9 and au > .9 and ab > .9 and i > .99) or
        (p > .9 and n > .9 and t > .90 and au > .80 and j > .6) or
        (n > .9 and v > .9 and t > .90 and au > .90 and i > .99) or
        (p > .9 and v > .9 and t > .90 and au > .80 and j > .6) or
        (p > .9 and n > .9 and t > .90 and au > .80 and i > .99) or
        (p > .8 and v > .8 and t > .95 and au > .80 and j > .9) or
        (n > .8 and v > .8 and t > .95 and au > .80 and j > .9) or
        (n > .8 and p > .8 and t > .95 and au > .80 and j > .9) or
        (p > .8 and v > .8 and t > .95 and au > .80 and i > .99))


def accept(a, b, strict_missing=False):
    """True-pair decision including ASySD's two demotion filters."""
    s = scores(a, b, strict_missing=strict_missing)
    if not is_true_pair(s):
        return False
    d = s["doi"]
    if not (d == 0 or d > 0.99 or (s["title"] > 0.9 and s["abstract"] > 0.9
                                   and (s["journal"] > 0.9 or s["isbn"] > 0.9))):
        return False
    if a.year and b.year and abs(int(a.year) - int(b.year)) > 1:
        return False
    return True


def maybe_pair(a, b):
    """The set ASySD routes to MANUAL deduplication rather than deciding."""
    s = scores(a, b)
    t, ab, au, j, i, d = (s["title"], s["abstract"], s["author"], s["journal"],
                          s["isbn"], s["doi"])
    if not ((t > .85 and au > .75) or (t > .80 and ab > .80) or
            (t > .80 and i > .99) or (t > .80 and j > .80)):
        return False
    if not (d > .99 or d == 0):
        return False
    if a.year and b.year and abs(int(a.year) - int(b.year)) > 1:
        return False
    return True


def to_record(d, i):
    return Record(uid="r%d" % i, title=d.get("title") or "",
                  abstract=d.get("abstract") or "",
                  authors=list(d.get("authors") or []), year=d.get("year"),
                  journal=d.get("journal") or "",
                  volume=str(d.get("volume") or ""),
                  issue=str(d.get("issue") or ""),
                  pages=str(d.get("pages") or ""), doi=d.get("doi") or "",
                  doc_type=d.get("doc_type") or "",
                  source=d.get("source") or d.get("_db") or "")


def load_domains():
    domains = {}
    for slug in TRACKS:
        with gzip.open(_data_path("domains_%s_raw.jsonl.gz" % slug), "rt",
                       encoding="utf-8") as handle:
            for line in handle:
                d = json.loads(line)
                if (d.get("doc_type") or "").lower() in NONWORK:
                    continue
                domains.setdefault(d.get("_domain") or d.get("domain"),
                                   []).append(d)
    return domains


def candidate_pairs(records, cap=400):
    """Pairs both rule sets are asked about: this package's blocking keys."""
    buckets = {}
    for index, record in enumerate(records):
        for key in _round_keys(record):
            buckets.setdefault(key, []).append(index)
    pairs = set()
    for members in buckets.values():
        if 1 < len(members) <= cap:
            pairs.update(itertools.combinations(sorted(members), 2))
    return pairs


def clusters_from_pairs(uids, accepted):
    parent = {u: u for u in uids}

    def find(u):
        while parent[u] != u:
            parent[u] = parent[parent[u]]
            u = parent[u]
        return u

    for a, b in accepted:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    groups = {}
    for u in uids:
        groups.setdefault(find(u), []).append(u)
    return list(groups.values())


def run():
    domains = load_domains()
    comparison, queue_rows, policy_rows = [], [], []
    for domain in sorted(domains):
        full = [to_record(d, i) for i, d in enumerate(domains[domain])]
        truth = truth_groups(full)
        blind = hide_identifiers([copy.deepcopy(r) for r in full])
        uids = [r.uid for r in blind]
        position = {u: i for i, u in enumerate(uids)}
        candidates = candidate_pairs(blind)

        accepted_idx = {(x, y) for x, y in candidates
                        if accept(blind[x], blind[y])}
        accepted = [(uids[x], uids[y]) for x, y in accepted_idx]
        theirs = pair_metrics(clusters_from_pairs(uids, accepted), truth)
        result = deduplicate([copy.deepcopy(r) for r in blind])
        ours = pair_metrics(clusters_from_decisions(result.report.decisions, uids),
                            truth)
        comparison.append(dict(
            domain=domain, records=len(blind), candidate_pairs=len(candidates),
            **{"asysd_rule_" + k: v for k, v in theirs.items()},
            **{"ours_" + k: v for k, v in ours.items()}))

        their_pairs = {tuple(sorted(p))
                       for c in clusters_from_pairs(uids, accepted)
                       for p in itertools.combinations(sorted(c), 2)}
        judged = {tuple(sorted(p))
                  for p in itertools.combinations(sorted(truth), 2)}
        same = {p for p in judged if truth[p[0]] == truth[p[1]]}
        missed = same - their_pairs
        in_queue = sum(1 for u, v in missed
                       if maybe_pair(blind[position[u]], blind[position[v]]))
        in_cand_queue = sum(
            1 for u, v in missed
            if tuple(sorted((position[u], position[v]))) in candidates
            and maybe_pair(blind[position[u]], blind[position[v]]))
        manual = [(x, y) for x, y in candidates
                  if maybe_pair(blind[x], blind[y])]
        queue_rows.append(dict(
            domain=domain, asysd_rule_missed=len(missed),
            missed_in_manual_queue=in_queue,
            missed_in_candidates_and_queue=in_cand_queue,
            recoverable_share=round(in_queue / len(missed), 4) if missed else None,
            manual_queue_pairs=len(manual),
            manual_pairs_auto_accepted=sum(1 for p in manual
                                           if p in accepted_idx),
            manual_pairs_after_auto=sum(1 for p in manual
                                        if p not in accepted_idx)))

        false_merges = (their_pairs & judged) - same
        true_merges = their_pairs & same
        def prevented(pairs):
            return sum(1 for u, v in pairs
                       if not is_true_pair(scores(blind[position[u]],
                                                  blind[position[v]],
                                                  strict_missing=True)))
        policy_rows.append(dict(
            domain=domain, asysd_rule_fp=len(false_merges),
            asysd_rule_tp=len(true_merges),
            fp_prevented_by_strict_missing=prevented(false_merges),
            tp_lost_by_strict_missing=prevented(true_merges),
            fp_with_both_pages_present_and_different=sum(
                1 for u, v in false_merges
                if str(blind[position[u]].pages or "").strip()
                and str(blind[position[v]].pages or "").strip()
                and str(blind[position[u]].pages) != str(blind[position[v]].pages))))
    return comparison, queue_rows, policy_rows


OUTPUTS = (("asysd_rule_comparison.csv", 0),
           ("asysd_manual_queue.csv", 1),
           ("asysd_na_policy_mechanism.csv", 2))


def write(tables, outdir=None):
    for name, index in OUTPUTS:
        rows = tables[index]
        path = os.path.join(outdir or os.path.join(HERE, "validation"), name)
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print("wrote %s (%d rows)" % (path, len(rows)))


def check(tables):
    problems = []
    for name, index in OUTPUTS:
        path = _data_path(name)
        if not os.path.exists(path):
            problems.append((name, "missing"))
            continue
        with open(path, encoding="utf-8") as handle:
            committed = {r["domain"]: r for r in csv.DictReader(handle)}
        for row in tables[index]:
            was = committed.get(row["domain"])
            if was is None:
                problems.append((name, "no row for " + row["domain"]))
                continue
            for key, value in row.items():
                if value is None:
                    continue
                before = was.get(key, "")
                if isinstance(value, float):
                    if before == "" or abs(float(before) - value) > 5e-4:
                        problems.append((name, row["domain"], key, before, value))
                elif str(value) != before:
                    problems.append((name, row["domain"], key, before, value))
    if problems:
        print("recomputation disagrees with the committed CSVs:")
        for p in problems[:20]:
            print("  ", p)
        return 1
    print("all three CSVs reproduce from the archived records")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--outdir", default=None)
    args = parser.parse_args(argv)
    tables = run()
    if args.check:
        return check(tables)
    write(tables, args.outdir)
    return 0


if __name__ == "__main__":                                   # pragma: no cover
    sys.exit(main())
