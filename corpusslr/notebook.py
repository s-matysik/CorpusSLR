"""Helpers for the Google Colab notebook.

The notebook used to carry its own glue: menus built with ``input()``, a
hand-written configuration dictionary, JSON reading, file handling. A reviewer
of the first submission found that the notebook was mostly code around the
package, not the package. That glue now lives here, where it is tested, and the
notebook is left with the workflow itself: say which databases and which query,
compile it, run it, read the counts, write the files.

Nothing in this module reads a credential. API keys are typed into the
notebook's own ``getpass`` cell, which prints presence and never a value, and
reach the package only through environment variables, exactly as on the command
line.

    from corpusslr.notebook import make_config, run_review

Every function prints what it did in plain words and returns the value a script
would want, so the same calls work outside Colab.
"""
from __future__ import annotations

import json
import os
import shutil
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .cli import (DATABASES, _norm_db, build_query, compile_for,
                  credential_status, main as _cli_main, read_corpus,
                  validate_config)
from .export import to_scopus_csv

OUT_DIR = "corpusslr_review"


def list_databases() -> List[str]:
    """Print every database with what it needs, and return the aliases."""
    aliases = sorted(DATABASES)
    for alias in aliases:
        status = credential_status(alias)
        if not status["requires_credential"]:
            note = "free"
        elif status["credential_present"]:
            note = "key is set"
        else:
            note = "needs a key, would be skipped"
        print("{:<14} {:<34} {}".format(alias, DATABASES[alias]["label"], note))
    return aliases


def _resolve(databases: Iterable[str]) -> List[str]:
    picked: List[str] = []
    for name in databases:
        alias = _norm_db(name)
        if not alias:
            raise ValueError("unknown database {!r}; known: {}".format(
                name, ", ".join(sorted(DATABASES))))
        if alias not in picked:
            picked.append(alias)
    if not picked:
        raise ValueError("no database selected; known: {}".format(
            ", ".join(sorted(DATABASES))))
    return picked


def make_config(blocks: Sequence[Sequence[str]], databases: Iterable[str],
                years: Optional[Tuple[int, int]] = None,
                doc_types: Sequence[str] = (), out_dir: str = OUT_DIR,
                title: str = "Review run in Google Colab",
                max_results: int = 2000) -> Tuple[dict, str]:
    """Validate a query and write ``review.json``; return (config, path).

    ``blocks`` is a list of OR-groups that are ANDed together. A one-character
    term is refused, because it matches almost everything.
    """
    clean = [[t.strip() for t in block if t and t.strip()] for block in blocks]
    clean = [b for b in clean if b]
    if not clean:
        raise ValueError("the query has no terms")
    short = [t for b in clean for t in b if len(t) < 2]
    if short:
        raise ValueError("a one-character term matches almost everything: "
                         "{!r}".format(short[0]))
    config: Dict[str, object] = {
        "review": {"title": title},
        "query": {"blocks": clean},
        "databases": [{"name": a} for a in _resolve(databases)],
        "dedup": {},
        "enrich": {"recover_abstracts": True},
        "output": {"dir": out_dir,
                   "exports": ["csv", "screening", "ris", "bibtex"],
                   "svg": True},
        "max_results": max_results,
    }
    if years:
        config["query"]["years"] = [int(years[0]), int(years[1])]   # type: ignore[index]
    if doc_types:
        config["query"]["doc_types"] = [t.lower() for t in doc_types]  # type: ignore[index]
    # validate_config rejects a credential in the file and explains every
    # rejection in words
    config = validate_config(config, "this notebook")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "review.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(config, fh, ensure_ascii=False, indent=1, sort_keys=True)
    print("Wrote", path)
    return config, path


def show_queries(config: dict) -> Dict[str, str]:
    """Compile the query for every chosen database and print it, retrieving nothing."""
    query = build_query(config)
    compiled: Dict[str, str] = {}
    for spec in config["databases"]:
        out = compile_for(spec["name"], query)
        compiled[spec["name"]] = out["query"]
        print("=" * 70)
        print(DATABASES[spec["name"]]["label"])
        print(out["query"])
        if out.get("filters"):
            print("filters:", out["filters"])
    for warning in dict.fromkeys(query.warnings):
        print("\nwarning:", warning)
    return compiled


def run_review(config_path: str, out_dir: str = OUT_DIR) -> int:
    """Run the search, deduplication and exports; return the exit code."""
    code = _cli_main(["run", "-c", config_path, "-C", out_dir, "--keep-going"])
    if code == 0:
        print("\nSearch finished.")
    else:
        print("\nThe run stopped with code {}. The lines above say what failed: "
              "usually a missing API key, a query that matched nothing, or a "
              "database that is temporarily unavailable.".format(code))
    return code


def read_summary(out_dir: str = OUT_DIR) -> dict:
    """Print the PRISMA counts from the run summary and return it."""
    path = os.path.join(out_dir, "run_summary.json")
    if not os.path.isfile(path):
        print("No run summary yet; the search has not completed.")
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        summary = json.load(fh)
    print("records identified :", summary.get("identified"))
    for source, count in sorted((summary.get("identified_by_source") or {}).items()):
        print("   {:<22} {}".format(source, count))
    dedup = summary.get("dedup") or {}
    print("duplicates removed :", dedup.get("removed"))
    for rule, count in sorted((dedup.get("by_method") or {}).items()):
        print("   {:<22} {}".format(rule, count))
    print("unique records     :", dedup.get("after"))
    for failure in summary.get("failures") or []:
        print("not searched:", failure.get("database"), "--", failure.get("reason"))
    return summary


def write_scopus_csv(out_dir: str = OUT_DIR) -> str:
    """Write the deduplicated corpus in the Scopus column layout; return the path."""
    unique = os.path.join(out_dir, "corpus_unique.json")
    if not os.path.isfile(unique):
        raise FileNotFoundError("no deduplicated corpus in {}; run the search first"
                                .format(out_dir))
    corpus, _ = read_corpus(unique)
    path = os.path.join(out_dir, "corpus_scopus.csv")
    to_scopus_csv(corpus.records, path)
    print("Wrote {} ({} records)".format(path, len(corpus.records)))
    return path


def show_appendix(out_dir: str = OUT_DIR) -> str:
    """Print the generated PRISMA-S appendix and return its text."""
    path = os.path.join(out_dir, "prisma_s_appendix.md")
    if not os.path.isfile(path):
        print("No appendix yet; the search has not completed.")
        return ""
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    print(text)
    return text


def download_results(out_dir: str = OUT_DIR) -> str:
    """Zip the output folder and, in Colab, offer it for download."""
    archive = shutil.make_archive("corpusslr_results", "zip", out_dir)
    print("Created", archive, "({:.1f} KB)".format(os.path.getsize(archive) / 1024))
    try:
        from google.colab import files as colab_files
    except ImportError:
        print("Not running in Colab; the zip is in the working folder.")
    else:
        colab_files.download(archive)
    return archive
