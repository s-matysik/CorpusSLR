"""Produce the exact tree to commit and push, with the ignore rules applied.

Some environments will not let a repository be initialised in place (a
sandbox, a locked-down share, a directory already inside another repository),
so this writes a clean copy of everything that belongs in the first commit and
nothing that does not. Running `git init && git add . && git commit` inside the
result gives the same content as running them in the working tree would, minus
the build products.

The ignore decision is taken from `.gitignore` rather than from a second list
kept here, so the two cannot disagree. Patterns supported are the ones the
file actually uses: directory suffixes, leading-slash anchors, and `*` globs.

Usage::

    PYTHONPATH=. python tools/build_push_tree.py
    PYTHONPATH=. python tools/build_push_tree.py --outdir /tmp/push --no-zip
"""
import argparse
import fnmatch
import os
import shutil
import sys
import zipfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import corpusslr                                             # noqa: E402

TREE_DIRNAME = "CorpusSLR-push"

#: Always excluded, whether or not .gitignore mentions them. A version-control
#: directory from some other repository must never be copied into the tree
#: that is about to become a new repository.
ALWAYS_SKIP = {".git", ".hg", ".svn", "__pycache__", ".pytest_cache",
               ".mypy_cache", ".ruff_cache", ".venv", "node_modules",
               ".DS_Store", TREE_DIRNAME}

#: Files that must be in the first commit. Absence is a build failure rather
#: than a warning: a repository published without a licence or without the
#: citation metadata is a defective publication, not an incomplete one.
REQUIRED = [
    "README.md", "LICENSE", "CITATION.cff", "codemeta.json", ".zenodo.json",
    "pyproject.toml", "MANIFEST.in", "CHANGELOG.md", "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md", "PUBLISHING.md", ".gitignore",
    "KNOWN_ISSUES.md",
    "corpusslr/__init__.py", "tests/conftest.py",
    ".github/workflows/tests.yml", ".github/workflows/quality.yml",
    ".github/workflows/pages.yml",
    "paper/corpusslr_softwarex.tex", "paper/references.bib",
    "docs/user_guide.md", "docs/api_reference.md",
    "validation/eval_asysd.py", "validation/eval_domains_15.py",
]


def read_ignore_patterns(root):
    """Parse .gitignore into (pattern, dir_only) pairs."""
    path = os.path.join(root, ".gitignore")
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith(("#", "!")):
                # Negations are not supported; the file uses none, and
                # pretending otherwise would silently include something.
                continue
            dir_only = line.endswith("/")
            out.append((line.rstrip("/").lstrip("/"), dir_only))
    return out


def is_ignored(rel, patterns, is_dir):
    """Match a repository-relative path against the parsed patterns.

    Two pattern shapes appear in the file and behave differently:

    * a pattern containing a slash is anchored, so ``paper/docx`` matches that
      directory and everything beneath it, but nothing else;
    * a bare name matches any path component, which is how ``__pycache__``
      excludes the directory wherever it appears.

    The earlier version returned False for a FILE beneath an anchored
    directory pattern. The build happened to be correct anyway because the
    walk prunes the directory before reaching its files, so the fault was
    invisible until a path was tested directly.
    """
    rel = rel.replace(os.sep, "/").strip("/")
    parts = rel.split("/")
    for pattern, dir_only in patterns:
        if "/" in pattern:
            # Anchored, and it may carry a glob: "paper/docx" names a
            # directory and everything under it, while "paper/*.aux" names
            # files. Matching only the literal prefix let every LaTeX
            # intermediate through.
            if (rel == pattern or rel.startswith(pattern + "/")
                    or fnmatch.fnmatch(rel, pattern)
                    or fnmatch.fnmatch(rel, pattern + "/*")):
                return True
            continue
        # A bare name. For a directory-only pattern it must match a directory,
        # which for a file path means one of its parent components.
        candidates = parts if is_dir else parts[:-1]
        if any(fnmatch.fnmatch(c, pattern) for c in candidates):
            return True
        if not dir_only and fnmatch.fnmatch(parts[-1], pattern):
            return True
    return False


def build(outdir, write_zip=True, quiet=False):
    root = os.path.join(outdir, TREE_DIRNAME)
    if os.path.exists(root):
        shutil.rmtree(root)
    os.makedirs(root)

    patterns = read_ignore_patterns(HERE)
    if not patterns:
        # Without the ignore rules every build product would be staged for the
        # first commit, silently. Refusing is the only safe answer: a tree
        # that looks right and carries the caches is worse than no tree.
        raise SystemExit(
            "no ignore rules found at {}; refusing to emit a tree that would "
            "stage every build product".format(os.path.join(HERE, ".gitignore")))
    copied, skipped = [], []
    for base, dirs, files in os.walk(HERE):
        rel_base = os.path.relpath(base, HERE)
        rel_base = "" if rel_base == "." else rel_base
        keep = []
        for d in sorted(dirs):
            rel = os.path.join(rel_base, d) if rel_base else d
            if d in ALWAYS_SKIP or is_ignored(rel, patterns, True):
                skipped.append(rel + "/")
            else:
                keep.append(d)
        dirs[:] = keep
        for name in sorted(files):
            rel = os.path.join(rel_base, name) if rel_base else name
            if name in ALWAYS_SKIP or is_ignored(rel, patterns, False):
                skipped.append(rel)
                continue
            dst = os.path.join(root, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.join(base, name), dst)
            copied.append(rel)

    absent = [r for r in REQUIRED if not os.path.exists(os.path.join(root, r))]
    if absent:
        raise SystemExit(
            "the tree is missing files the first commit must contain:\n  "
            + "\n  ".join(absent))

    # A tree that still carries someone else's version-control directory would
    # break `git init` in a way that is hard to diagnose later.
    stray = [r for r in copied if ".git/" in r.replace(os.sep, "/")]
    if stray:
        raise SystemExit("version-control data leaked into the tree: %s"
                         % stray[:5])

    zip_path = None
    if write_zip:
        zip_path = os.path.join(outdir, TREE_DIRNAME + ".zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel in sorted(copied):
                info = zipfile.ZipInfo(("%s/%s" % (TREE_DIRNAME, rel))
                                       .replace(os.sep, "/"),
                                       date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                with open(os.path.join(root, rel), "rb") as fh:
                    zf.writestr(info, fh.read())

    total = sum(os.path.getsize(os.path.join(root, r)) for r in copied)
    result = {"root": root, "zip": zip_path, "files": len(copied),
              "skipped": len(skipped), "bytes": total,
              "version": corpusslr.__version__}
    if not quiet:
        print("wrote %s (%d files, %.1f MB; %d path(s) left out by .gitignore)"
              % (root, len(copied), total / 1e6, len(skipped)))
        if zip_path:
            print("wrote %s (%.1f MB)"
                  % (zip_path, os.path.getsize(zip_path) / 1e6))
        print("first commit would carry version %s" % corpusslr.__version__)
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--outdir", default=HERE)
    ap.add_argument("--no-zip", action="store_true")
    args = ap.parse_args(argv)
    build(args.outdir, write_zip=not args.no_zip)
    return 0


if __name__ == "__main__":                       # pragma: no cover
    sys.exit(main())
