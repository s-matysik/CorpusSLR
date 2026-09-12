"""Record the outcome of the GitHub Actions runs as evidence.

The submission checklist needs to know whether continuous integration has
actually run on GitHub, and that cannot be established from the working tree:
the workflows exist there whether or not a runner ever executed them. Asserting
it in the checklist is what this replaces -- the item was a hardcoded False and
could never close, however many green runs there were.

This queries the public Actions API, takes the most recent run of each
workflow, and writes what it found to validation/ci_run_verification.json. The
checklist then reads that file, so the checklist itself stays offline and the
tick rests on a recorded measurement with run ids and commit hashes anyone can
re-check against the repository.

Usage:
    python validation/record_ci_runs.py [--repo owner/name]
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_REPO = "s-matysik/CorpusSLR"
OUT = os.path.join(HERE, "validation", "ci_run_verification.json")


def fetch(repo, timeout=30):
    url = ("https://api.github.com/repos/%s/actions/runs?per_page=20" % repo)
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def build(repo, data):
    latest = {}
    for run in data.get("workflow_runs", []):
        latest.setdefault(run["name"], run)
    record = {
        "verified_on": datetime.datetime.now(datetime.timezone.utc)
                       .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repository": repo,
        "method": ("read from the GitHub Actions REST API, not asserted: the "
                   "conclusion of the most recent run of each workflow, with "
                   "the commit each ran against"),
        "total_runs": data.get("total_count"),
        "workflows": {name: {"conclusion": run.get("conclusion"),
                             "run_id": run.get("id"),
                             "head_sha": (run.get("head_sha") or "")[:12],
                             "created_at": run.get("created_at")}
                      for name, run in sorted(latest.items())},
    }
    record["all_succeeded"] = bool(record["workflows"]) and all(
        w["conclusion"] == "success" for w in record["workflows"].values())
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=DEFAULT_REPO)
    args = parser.parse_args(argv)
    try:
        data = fetch(args.repo)
    except (urllib.error.URLError, OSError) as exc:
        # Not a silent pass: without a reachable API there is no evidence, and
        # the checklist item stays open rather than being ticked on a guess.
        print("could not reach the Actions API: %s" % exc)
        return 1
    record = build(args.repo, data)
    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=1, ensure_ascii=False)
        handle.write("\n")
    print("wrote %s" % OUT)
    for name, workflow in sorted(record["workflows"].items()):
        print("  %-28s %s" % (name, workflow["conclusion"]))
    print("all succeeded: %s" % record["all_succeeded"])
    return 0 if record["all_succeeded"] else 1


if __name__ == "__main__":                                   # pragma: no cover
    sys.exit(main())
