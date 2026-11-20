"""Assemble the browser application into a static directory.

The application is a separate root from the documentation site. The site is
built without JavaScript and with no external reference, and CI enforces both;
a page that runs Python in the browser cannot satisfy the first rule, so it is
not part of that site. It is published under ``/app/`` and has its own checks
(``tests/test_web_app.py``): every file it loads comes from its own directory,
and a Content-Security-Policy restricts the pages it may talk to.

The bundle contains

* the page (``app/web``): HTML, CSS and two scripts, no framework, no CDN;
* ``corpusslr.zip``: the package source at this commit, so the page runs the
  version it documents (zipped deterministically);
* ``corpusslr_web.py``: the bridge, ``app/py``;
* ``pyodide/``: the Pyodide runtime, copied from the pinned npm package
  (``app/package-lock.json``), so a visit makes no request to a CDN;
* ``manifest.json``: the version, the Pyodide version and the SHA-256 of every
  file, so what is served can be compared with what was built.

    python tools/build_app.py --out app/dist [--no-pyodide]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
APP = REPO / "app"
PYODIDE_FILES = ("pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm",
                 "python_stdlib.zip", "pyodide-lock.json")
FIXED_TIME = (2026, 1, 1, 0, 0, 0)


def read_version() -> str:
    text = (REPO / "corpusslr" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__\s*=\s*"([^"]+)"', text).group(1)


def zip_package(dest: Path) -> None:
    """Zip corpusslr/ deterministically: sorted names, fixed timestamps."""
    pkg = REPO / "corpusslr"
    files = sorted(p for p in pkg.rglob("*.py") if "__pycache__" not in p.parts)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in files:
            info = zipfile.ZipInfo(str(p.relative_to(REPO)).replace(os.sep, "/"), FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, p.read_bytes())


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(out: Path, with_pyodide: bool = True) -> dict:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for src in sorted((APP / "web").glob("*")):
        if src.is_file():
            shutil.copy2(src, out / src.name)
    shutil.copy2(APP / "py" / "corpusslr_web.py", out / "corpusslr_web.py")
    zip_package(out / "corpusslr.zip")
    pyodide_version = ""
    if with_pyodide:
        pj = json.loads((APP / "node_modules" / "pyodide" / "package.json").read_text())
        pyodide_version = pj["version"]
        (out / "pyodide").mkdir()
        for name in PYODIDE_FILES:
            shutil.copy2(APP / "node_modules" / "pyodide" / name, out / "pyodide" / name)
    (out / ".nojekyll").write_text("", encoding="utf-8")
    files = {str(p.relative_to(out)).replace(os.sep, "/"): sha256(p)
             for p in sorted(out.rglob("*")) if p.is_file() and p.name != "manifest.json"}
    manifest = {"corpusslr": read_version(), "pyodide": pyodide_version, "files": files}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=str(APP / "dist"))
    ap.add_argument("--no-pyodide", action="store_true",
                    help="skip the runtime (used by tests that do not execute it)")
    args = ap.parse_args(argv)
    m = build(Path(args.out), with_pyodide=not args.no_pyodide)
    print("built %d files, corpusslr %s, pyodide %s -> %s"
          % (len(m["files"]), m["corpusslr"], m["pyodide"] or "(none)", args.out))
    return 0


if __name__ == "__main__":                                  # pragma: no cover
    sys.exit(main())
