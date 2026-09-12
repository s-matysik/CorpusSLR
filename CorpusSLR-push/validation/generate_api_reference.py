"""Generate docs/api_reference.md from the installed package by introspection.

Hand-written reference documentation drifts: a renamed symbol lingers, a removed
one is still described. Generating it means the reference cannot describe a
package that does not exist, and tests/test_docs_examples.py then asserts that
every public symbol has an entry.

Usage:  python validation/generate_api_reference.py
"""
import inspect
import os

import corpusslr as C

GROUPS = [
    ("Core data model", ["Record", "Corpus", "SearchQuery", "SearchEvent",
                         "SourceResult"]),
    ("Retrieval (API clients)", None),          # filled by suffix
    ("File-export parsers", None),
    ("Deduplication", ["deduplicate", "DedupResult", "DedupReport",
                       "DedupDecision", "normalize_doi", "normalize_title"]),
    ("Reporting (PRISMA / PRISMA-S)", None),
    ("Source registry", ["classify_source", "canonical_source", "source_evidence",
                         "source_note", "SOURCE_TIER", "SOURCE_EVIDENCE",
                         "SOURCE_NOTES"]),
    ("Export", None),
    ("Reproducible harvesting", None),
    ("Validation protocol", None),
]


def _public():
    return list(getattr(C, "__all__", None)
                or [x for x in dir(C) if not x.startswith("_")])


def _resolve(title, names, public):
    if names is not None:
        return names
    if title.startswith("Retrieval"):
        return [n for n in public if n.endswith("Source")]
    if title.startswith("File-export"):
        return ([n for n in public
                 if n.startswith(("parse_", "detect_", "looks_like_", "sniff_",
                                  "decode_", "extract_"))]
                + ["ParseReport", "ParseFormatMismatch", "REJECTION_REASONS"])
    if title.startswith("Reporting"):
        return [n for n in public if n.lower().startswith("prisma")]
    if title == "Export":
        return [n for n in public if n.startswith("to_")]
    if title.startswith("Reproducible"):
        return [n for n in public
                if "harvest" in n.lower() or "replay" in n.lower()
                or n in ("verify_archive", "compare_harvests")]
    if title.startswith("Validation"):
        return [n for n in public
                if n.startswith(("evaluate", "validate")) or "Blind" in n]
    return []


def _first_line(obj):
    doc = inspect.getdoc(obj) or ""
    return doc.strip().split("\n\n")[0].replace("\n", " ").strip()


def build():
    public = _public()
    groups = [(t, [n for n in dict.fromkeys(_resolve(t, ns, public))
                   if hasattr(C, n)]) for t, ns in GROUPS]
    placed = {n for _, ns in groups for n in ns}
    groups.append(("Other public symbols",
                   sorted(n for n in public if n not in placed)))

    out = ["# API reference", "",
           "Generated from the installed package (`corpusslr {}`) by "
           "`validation/generate_api_reference.py` -- every entry is "
           "introspected from the code, so a renamed or removed symbol cannot "
           "linger here. `tests/test_docs_examples.py` asserts that every "
           "public symbol appears.".format(C.__version__), "",
           "For a narrative walkthrough see [`user_guide.md`](user_guide.md).",
           ""]
    for title, names in groups:
        if not names:
            continue
        out += ["## " + title, ""]
        for n in names:
            obj = getattr(C, n)
            if inspect.isclass(obj):
                out += ["### `{}`".format(n), "",
                        _first_line(obj) or "_(no docstring)_"]
                methods = [(m, getattr(obj, m)) for m in dir(obj)
                           if not m.startswith("_")
                           and callable(getattr(obj, m, None))]
                if methods:
                    out.append("")
                    for m, fn in methods:
                        try:
                            sig = (str(inspect.signature(fn))
                                   .replace("self, ", "").replace("(self)", "()"))
                        except (TypeError, ValueError):
                            sig = "(...)"
                        out.append("- `{}{}` - {}".format(
                            m, sig, _first_line(fn) or "see source"))
                if hasattr(obj, "__dataclass_fields__"):
                    out += ["", "Fields: " + ", ".join(
                        "`{}`".format(f) for f in obj.__dataclass_fields__)]
            elif callable(obj):
                try:
                    sig = str(inspect.signature(obj))
                except (TypeError, ValueError):
                    sig = "(...)"
                out += ["### `{}{}`".format(n, sig), "",
                        _first_line(obj) or "_(no docstring)_"]
            else:
                size = (", {} entries".format(len(obj))
                        if hasattr(obj, "__len__") else "")
                out += ["### `{}`".format(n), "",
                        "Module-level {}{}.".format(type(obj).__name__, size)]
            out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(here, "docs", "api_reference.md")
    text = build()
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    missing = [n for n in _public() if "### `" + n not in text]
    print("wrote {} ({} public symbols, {} missing)".format(
        path, len(_public()), len(missing)))
