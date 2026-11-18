"""Check that a given source of the package installs and works from nothing.

A reviewer of the first submission could not install the package, so the
software was never assessed. This script is the check that would have caught
it, and it is the one to run before a submission and again on the exact address
given in the article. It builds a fresh virtual environment, installs the
package from SOURCE, and then does what a reviewer would do first:

1. import the package and print its version,
2. run the ``corpusslr`` command,
3. run a short workflow with no network: parse two RIS exports that hold the
   same article, deduplicate, and write the PRISMA flow numbers and the
   canonical Scopus-layout CSV.

SOURCE is anything ``pip install`` accepts: a directory, a wheel, a source
archive, a ``git+https://`` address or an archive URL such as
``https://github.com/s-matysik/CorpusSLR/archive/refs/tags/v1.1.0.zip``.

    python validation/verify_install.py .
    python validation/verify_install.py https://github.com/s-matysik/CorpusSLR/archive/refs/tags/v1.1.0.zip

Exit status 0 only if every step succeeded. ``--system-site-packages`` and
``--no-build-isolation`` exist for machines with no route to the package index
(a sandbox); on an ordinary machine neither is needed and neither is the default.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import platform
import subprocess
import sys
import tempfile
import textwrap

SMOKE = textwrap.dedent('''
    import os, sys, tempfile
    import corpusslr as C
    from corpusslr import parse_ris_file, deduplicate, to_scopus_csv

    d = tempfile.mkdtemp()
    a, b = os.path.join(d, "a.ris"), os.path.join(d, "b.ris")
    open(a, "w").write("TY  - JOUR\\nTI  - Machine learning in SMEs\\nAU  - Kowalski, J\\n"
                       "PY  - 2021\\nT2  - J Business\\nDO  - 10.1000/x.1\\nER  - \\n")
    open(b, "w").write("TY  - JOUR\\nTI  - Machine Learning in SMEs\\nAU  - Kowalski, J.\\n"
                       "PY  - 2021\\nT2  - J Business\\nDO  - 10.1000/X.1\\nER  - \\n"
                       "TY  - JOUR\\nTI  - A different article\\nAU  - Nowak, A\\nPY  - 2020\\nER  - \\n")
    recs = parse_ris_file(a) + parse_ris_file(b)
    res = deduplicate(recs)
    out = os.path.join(d, "out.csv")
    to_scopus_csv(res.records, out)
    n_cols = len(open(out, encoding="utf-8-sig").readline().split(","))
    assert len(recs) == 3 and len(res.records) == 2, (len(recs), len(res.records))
    print("version", C.__version__, "| 3 records -> 2 after deduplication |",
          n_cols, "columns in the export")
''')


def run(cmd, **kw):
    # PYTHONPATH and PYTHONHOME would let the package be found without having
    # been installed (or stop it being found), which is the one thing this
    # script exists to rule out. Measured: with PYTHONPATH=. the Python 3.9 run
    # reported an import failure for a correctly installed wheel.
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    return subprocess.run(cmd, capture_output=True, text=True, env=env, **kw)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source")
    ap.add_argument("--extra", default="", help='extras, e.g. "docx"')
    ap.add_argument("--system-site-packages", action="store_true")
    ap.add_argument("--no-build-isolation", action="store_true")
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--record", metavar="FILE",
                    help="on success, write the outcome here as evidence (JSON)")
    args = ap.parse_args(argv)

    root = tempfile.mkdtemp(prefix="corpusslr_install_")
    venv = os.path.join(root, "venv")
    cmd = [args.python, "-m", "venv", venv]
    if args.system_site_packages:
        cmd.insert(3, "--system-site-packages")
    r = run(cmd)
    if r.returncode:
        print("could not create a virtual environment:\n" + r.stderr[-600:])
        return 2
    py = os.path.join(venv, "bin", "python")
    spec = args.source + ("[%s]" % args.extra if args.extra else "")
    pip = [py, "-m", "pip", "install", "--quiet", "--disable-pip-version-check"]
    if args.no_build_isolation:
        # A virtual environment seeds its own, old setuptools (58 on Python
        # 3.9), which cannot read the [project] table and builds an empty
        # "UNKNOWN" package. Without a route to the package index the build
        # tools of the invoking interpreter are the only current ones, so the
        # wheel is built with those and the venv only installs it.
        wheeldir = os.path.join(root, "wheel")
        w = run([args.python, "-m", "pip", "wheel", "--quiet", "--no-build-isolation",
                 "--no-deps", "--no-index", "-w", wheeldir, args.source])
        if w.returncode:
            print("1. build wheel      : FAILED\n" + w.stderr[-900:])
            return 1
        spec = os.path.join(wheeldir, sorted(os.listdir(wheeldir))[0])
        print("   wheel built      :", os.path.basename(spec))
        pip += ["--no-index", "--no-deps"]
    r = run(pip + [spec])
    print("1. pip install      :", "ok" if r.returncode == 0 else "FAILED")
    if r.returncode:
        print(r.stderr[-1200:])
        return 1
    r = run([py, "-c", "import corpusslr; print(corpusslr.__version__)"], cwd=root)
    print("2. import           :", r.stdout.strip() if r.returncode == 0 else "FAILED\n" + r.stderr[-600:])
    if r.returncode:
        return 1
    version = r.stdout.strip()
    exe = os.path.join(venv, "bin", "corpusslr")
    r = run([exe, "--version"], cwd=root)
    print("3. corpusslr command:", r.stdout.strip() if r.returncode == 0 else "FAILED\n" + r.stderr[-600:])
    if r.returncode:
        return 1
    r = run([py, "-c", SMOKE], cwd=root)
    print("4. offline workflow :", r.stdout.strip() if r.returncode == 0 else "FAILED\n" + r.stderr[-900:])
    if r.returncode == 0 and args.record:
        # Written only after every step has passed, so the file exists only as
        # evidence of a real success; the submission checklist reads it.
        with open(args.record, "w", encoding="utf-8") as fh:
            json.dump({
                "source": args.source,
                "installed_version": version,
                "python": platform.python_version(),
                "platform": platform.platform(),
                "verified_on": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "steps": ["pip install", "import", "corpusslr --version", "offline workflow"],
                "outcome": "installed and ran from source in a fresh virtual environment",
            }, fh, indent=1)
            fh.write("\n")
    return r.returncode


if __name__ == "__main__":                                  # pragma: no cover
    sys.exit(main())
