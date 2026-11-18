"""Time and memory of the deduplication on synthetic corpora, reproducibly.

What this replaces. The article quoted "60 000 records in 25.3 s at 310 MB"
from `dedup_performance.csv`. That file was measured with `tracemalloc` running,
which slows the interpreter, so time and memory came from one distorted run;
it was measured on a development version; it stated no hardware; and nothing in
the repository regenerated it. A reviewer asked for the processor, the memory,
the operating system, the interpreter, the way memory was measured, the number
of repetitions and the statistic reported. This script produces all of them.

Method
------
* The corpora are the two generators of `eval_asysd.py`, read from its source so
  there is one definition: ``realistic`` (20 % planted cross-source duplicates
  without identifiers, stock title openings plus a rare numeric token, so only
  the fuzzy stage can find them) and ``pathological`` (every title opens with
  the same seven words, the worst case for token blocking).
* Time is wall-clock `time.perf_counter()` around `deduplicate()` alone, with
  corpus construction excluded and tracemalloc OFF. Each repetition runs in a
  fresh interpreter so one run cannot warm the next. The statistic reported is
  the median of REPEATS runs, with the minimum and maximum beside it.
* Memory is measured separately, once per size, with `tracemalloc` ON: the peak
  of Python allocations made during `deduplicate()`, excluding the corpus
  itself. Peak resident set size of the whole process is recorded too, because
  tracemalloc does not see allocations made outside the Python allocator.
* The environment is written to `dedup_benchmark_environment.json`.

Usage:  PYTHONPATH=. python validation/benchmark_dedup.py
        PYTHONPATH=. python validation/benchmark_dedup.py --repeats 3 --sizes 6000 60000
"""
from __future__ import annotations

import argparse
import ast
import csv
import json
import os
import platform
import statistics
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SIZES = (6000, 15000, 30000, 60000)
REPEATS = 5
SCENARIOS = ("realistic", "pathological", "stock_stems")
#: The stress scenario is superlinear at small n and saturates at the block cap,
#: so it is measured on its own, smaller grid and fewer repetitions.
STRESS_SIZES = (500, 1000, 2000, 4000, 8000)
STRESS_REPEATS = 3


def synth_zipf_titles(n, dup_frac=0.20, seed=11):
    """Bibliographic-looking corpus: Zipfian vocabulary, perturbed duplicates.

    The two generators taken from eval_asysd.py are deliberately extreme (one
    repeats a few hundred title stems, the other opens every title identically),
    and the figure the article quoted came from a generator that no longer
    exists in the repository. This one is the representative case: a vocabulary
    of 4000 word forms drawn with Zipf weights, titles of 7 to 14 words, 3000
    distinct journals, and duplicates that carry the perturbations real
    exports introduce (case, punctuation, a dropped article, an initial-only
    author form). Duplicates have no identifier, so only the fuzzy stage can
    find them.
    """
    import random
    from corpusslr import Record
    rng = random.Random(seed)
    syll = ["ba", "ke", "ri", "mo", "tu", "la", "ne", "so", "di", "pa", "gu", "ve",
            "an", "or", "el", "ic", "ax", "um"]
    # sorted() BEFORE the slice: a set has no defined order, so slicing it first
    # made the corpus depend on PYTHONHASHSEED and differ between processes.
    vocab = sorted({"".join(rng.choice(syll) for _ in range(rng.randint(2, 4)))
                    for _ in range(9000)})[:4000]
    weights = [1.0 / (k + 1) for k in range(len(vocab))]
    journals = ["Journal of %s %s" % (rng.choice(vocab).title(), rng.choice(vocab).title())
                for _ in range(3000)]
    surnames = [rng.choice(vocab).title() for _ in range(6000)]
    n_uni = int(round(n / (1 + dup_frac)))
    base = []
    for _ in range(n_uni):
        words = rng.choices(vocab, weights, k=rng.randint(7, 14))
        base.append(dict(
            title=" ".join(words).capitalize(),
            year=rng.randrange(1998, 2025),
            authors=["%s A." % rng.choice(surnames), "%s B." % rng.choice(surnames)],
            journal=rng.choice(journals), source="pubmed"))
    out = [Record(uid="U%07d" % i, **b) for i, b in enumerate(base)]
    truth = {"U%07d" % i: "U%07d" % i for i in range(n_uni)}
    for j in range(n - n_uni):
        k = rng.randrange(n_uni)
        b = dict(base[k], source="scopus")
        words = b["title"].split(" ")
        roll = rng.random()
        if roll < 0.35:
            b["title"] = b["title"].lower()
        elif roll < 0.6 and len(words) > 8:
            del words[rng.randrange(len(words))]
            b["title"] = " ".join(words)
        elif roll < 0.8:
            b["title"] = b["title"] + "."
        b["authors"] = [a.replace(" A.", ", A") .replace(" B.", ", B") for a in b["authors"]]
        r = Record(uid="D%07d" % j, **b)
        truth[r.uid] = "U%07d" % k
        out.append(r)
    rng.shuffle(out)
    return out, truth


def _generators():
    """The corpus generators of eval_asysd.py, compiled from its source."""
    with open(os.path.join(HERE, "eval_asysd.py"), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    wanted_names = {"STOCK", "TOPIC", "CTX"}
    wanted_funcs = {"synth_realistic", "synth_shared_prefix"}
    body = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) in wanted_names for t in node.targets):
            body.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in wanted_funcs:
            body.append(node)
    module = ast.Module(body=body, type_ignores=[])
    import random
    from corpusslr import Record
    ns = {"random": random, "Record": Record}
    exec(compile(module, "eval_asysd.py", "exec"), ns)
    return {"realistic": synth_zipf_titles,
            "pathological": ns["synth_shared_prefix"],
            "stock_stems": ns["synth_realistic"]}


def _one(scenario, n, memory):
    """Run in a child interpreter: one measurement, printed as JSON."""
    import gc
    import resource
    import time
    from corpusslr import deduplicate
    recs, _truth = _generators()[scenario](n)
    gc.collect()
    peak_traced = None
    if memory:
        import tracemalloc
        tracemalloc.start()
    t0 = time.perf_counter()
    result = deduplicate(recs)
    seconds = time.perf_counter() - t0
    if memory:
        peak_traced = tracemalloc.get_traced_memory()[1] / 1e6
        tracemalloc.stop()
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_mb = rss / 1e6 if sys.platform == "darwin" else rss / 1e3
    print(json.dumps({"seconds": seconds, "peak_traced_mb": peak_traced,
                      "peak_rss_mb": rss_mb, "after": result.report.after,
                      "removed": result.report.removed}))


def _child(scenario, n, memory):
    code = ("import sys; sys.path.insert(0, %r); sys.path.insert(0, %r); "
            "import benchmark_dedup as b; b._one(%r, %d, %r)"
            % (REPO, HERE, scenario, n, memory))
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, cwd=REPO)
    if out.returncode:
        raise SystemExit("benchmark child failed:\n" + out.stderr[-800:])
    return json.loads(out.stdout.strip().split("\n")[-1])


def _sysctl(name):
    try:
        return subprocess.run(["sysctl", "-n", name], capture_output=True,
                              text=True).stdout.strip()
    except OSError:
        return ""


def environment():
    """Hardware and software the numbers belong to."""
    import corpusslr
    cpu = _sysctl("machdep.cpu.brand_string")
    mem = _sysctl("hw.memsize")
    if not cpu and os.path.exists("/proc/cpuinfo"):
        with open("/proc/cpuinfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("model name"):
                    cpu = line.split(":", 1)[1].strip()
                    break
    if not mem and os.path.exists("/proc/meminfo"):
        with open("/proc/meminfo", encoding="utf-8") as fh:
            kb = int(fh.readline().split()[1])
        mem = str(kb * 1024)
    return {
        "processor": cpu or platform.processor() or "unknown",
        "logical_cores": os.cpu_count(),
        "ram_gib": round(int(mem) / 2 ** 30, 1) if mem.isdigit() else None,
        "operating_system": platform.platform(),
        "python": "%s %s" % (platform.python_implementation(),
                             platform.python_version()),
        "corpusslr": corpusslr.__version__,
        "time_measurement": "time.perf_counter() around deduplicate(), "
                            "tracemalloc off, corpus construction excluded",
        "memory_measurement": "tracemalloc peak of allocations made during "
                              "deduplicate() (separate run), and peak resident "
                              "set size of the whole process",
        "repetitions": REPEATS,
        "statistic": "median of the repetitions, with minimum and maximum",
    }


def main(argv=None):
    global REPEATS
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repeats", type=int, default=REPEATS)
    ap.add_argument("--sizes", type=int, nargs="+", default=list(SIZES))
    ap.add_argument("--outdir", default=HERE)
    args = ap.parse_args(argv)
    REPEATS = args.repeats

    rows = []
    for scenario in SCENARIOS:
        stress = scenario == "stock_stems"
        grid = STRESS_SIZES if stress else args.sizes
        reps = min(REPEATS, STRESS_REPEATS) if stress else REPEATS
        for n in grid:
            runs = [_child(scenario, n, memory=False) for _ in range(reps)]
            mem = _child(scenario, n, memory=True)
            secs = [r["seconds"] for r in runs]
            row = {"scenario": scenario, "n": n, "repeats": reps,
                   "seconds_median": round(statistics.median(secs), 2),
                   "seconds_min": round(min(secs), 2),
                   "seconds_max": round(max(secs), 2),
                   "us_per_record": round(1e6 * statistics.median(secs) / n, 1),
                   "peak_traced_mb": round(mem["peak_traced_mb"], 1),
                   "peak_rss_mb": round(max(r["peak_rss_mb"] for r in runs), 1),
                   "after": runs[0]["after"], "removed": runs[0]["removed"]}
            rows.append(row)
            print(row, flush=True)

    env = environment()
    env["repetitions"] = REPEATS
    with open(os.path.join(args.outdir, "dedup_benchmark.csv"), "w",
              encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(args.outdir, "dedup_benchmark_environment.json"), "w",
              encoding="utf-8") as fh:
        json.dump(env, fh, indent=1)
        fh.write("\n")
    print(json.dumps(env, indent=1))
    return 0


if __name__ == "__main__":                              # pragma: no cover
    raise SystemExit(main())
