"""Dependency-free BibTeX parser for database exports.

BibTeX is the export format of last resort for the databases that have no
open API -- IEEE Xplore, the ACM Digital Library, SpringerLink, dblp -- and
it is the format most likely to corrupt a systematic review silently.  Two
properties matter for evidence synthesis and are the reason this parser
exists instead of a thin ``regex`` over ``field = {value}``:

1. **Brace-aware value scanning.**  A title such as
   ``{The {AI} Effect on {SME}s}`` cannot be read with a non-recursive
   pattern; truncating it at the first ``}`` produces a different
   normalized title and therefore a missed duplicate.
2. **LaTeX de-escaping.**  Exports encode diacritics as control sequences
   (``Kowalsk{\\'i}``, ``M{\\"u}ller``, ``Wr{\\'o}bel``, ``{\\l}ukasiewicz``).
   :func:`corpusslr.record.normalize_title` transliterates *Unicode*
   diacritics, but it cannot see through LaTeX markup, so an un-decoded
   record fails surname comparison against the same record retrieved from
   Scopus or PubMed.  :func:`_delatex` resolves the accent commands to
   composed Unicode before the record is built.

The parser also tolerates the things real files contain and specifications
do not: ``@string`` abbreviations and ``#`` concatenation, ``%`` comments,
``@comment`` blocks, parenthesised entry bodies, unquoted numeric values,
duplicate field names and unbalanced trailing braces.

Recognised dialects (see :func:`detect_bibtex_dialect`): ``ieee``, ``acm``,
``scopus``, ``wos``, ``arxiv``, ``generic``.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Optional, Tuple

from ..record import Record
from ._util import (clean_pages, collapse_ws, map_doc_type,
                    normalize_author_name, parse_int, parse_year,
                    split_keywords)

from ._io import read_export_text
from ._report import ParseReport, _ensure

__all__ = ["parse_bibtex", "parse_bibtex_file", "detect_bibtex_dialect"]

# ---------------------------------------------------------------------------
# LaTeX decoding
# ---------------------------------------------------------------------------

# Combining marks for the accent control sequences.  Composing the mark and
# then normalizing with NFC yields the precomposed character when one exists
# ("e" + U+0301 -> "e-acute") and a decomposed-but-correct string otherwise.
_ACCENTS = {
    "'": "\u0301", "`": "\u0300", "^": "\u0302", '"': "\u0308",
    "~": "\u0303", "=": "\u0304", ".": "\u0307",
    "u": "\u0306", "v": "\u030C", "H": "\u030B", "c": "\u0327",
    "k": "\u0328", "r": "\u030A", "b": "\u0331", "d": "\u0323",
}

# Standalone letter and symbol commands.
_LATEX_TOKENS = {
    "ss": "\u00df", "SS": "SS", "l": "\u0142", "L": "\u0141",
    "o": "\u00f8", "O": "\u00d8", "ae": "\u00e6", "AE": "\u00c6",
    "oe": "\u0153", "OE": "\u0152", "aa": "\u00e5", "AA": "\u00c5",
    "i": "i", "j": "j", "dh": "\u00f0", "DH": "\u00d0",
    "th": "\u00fe", "TH": "\u00de", "dj": "\u0111", "DJ": "\u0110",
    "ng": "\u014b", "NG": "\u014a",
    "textendash": "\u2013", "textemdash": "\u2014",
    "textquotesingle": "'", "textquotedblleft": "\u201c",
    "textquotedblright": "\u201d", "textquoteleft": "\u2018",
    "textquoteright": "\u2019", "textbackslash": "\\",
    "textasciitilde": "~", "textasciicircum": "^",
    "textbullet": "\u2022", "textdegree": "\u00b0",
    "textregistered": "\u00ae", "texttrademark": "\u2122",
    "textcopyright": "\u00a9", "copyright": "\u00a9",
    "textless": "<", "textgreater": ">", "textbar": "|",
    "textpm": "\u00b1", "textmu": "\u00b5",
    "textperiodcentered": "\u00b7", "textellipsis": "\u2026",
    "ldots": "\u2026", "dots": "\u2026", "pounds": "\u00a3",
    "euro": "\u20ac", "S": "\u00a7", "P": "\u00b6",
    "alpha": "\u03b1", "beta": "\u03b2", "gamma": "\u03b3",
    "delta": "\u03b4", "epsilon": "\u03b5", "lambda": "\u03bb",
    "mu": "\u03bc", "pi": "\u03c0", "sigma": "\u03c3", "tau": "\u03c4",
    "phi": "\u03c6", "omega": "\u03c9", "Delta": "\u0394",
    "Sigma": "\u03a3", "Omega": "\u03a9", "Gamma": "\u0393",
    "times": "\u00d7", "div": "\u00f7", "pm": "\u00b1",
    "leq": "\u2264", "geq": "\u2265", "neq": "\u2260",
    "approx": "\u2248", "to": "\u2192", "rightarrow": "\u2192",
    "infty": "\u221e", "degree": "\u00b0", "checkmark": "\u2713",
}

# Commands whose brace argument is kept verbatim.
_WRAPPERS = ("emph", "textit", "textbf", "textrm", "textsf", "texttt",
             "textsc", "textsl", "textup", "textnormal", "mbox", "hbox",
             "text", "mathrm", "mathit", "mathbf", "url", "path", "lowercase",
             "uppercase", "MakeLowercase", "MakeUppercase", "acro", "acs")

_LB, _RB, _BS = "\x01", "\x02", "\x03"
# Escaped literals must survive the math-mode/brace cleanup further down, so
# they are parked on private code points and restored last. Without this a
# legitimately escaped '\$' (a price, a currency symbol) is stripped together
# with real math-mode delimiters.
_ESC_PLACEHOLDER = {"&": "\x04", "%": "\x05", "$": "\x06",
                    "#": "\x07", "_": "\x08"}

_ACC_BRACE = re.compile(r"\\([`'^\"~=.])\s*\{\s*\\?([A-Za-z])\s*\}")
_ACC_PLAIN = re.compile(r"\\([`'^\"~=.])\s*\\?([A-Za-z])")
_ACC_CMD_BRACE = re.compile(r"\\([uvHckrbd])\s*\{\s*\\?([A-Za-z])\s*\}")
_ACC_CMD_PLAIN = re.compile(r"\\([uvHckrbd])\s+\\?([A-Za-z])(?![A-Za-z])")
_TOKEN_RE = re.compile(
    r"\\(" + "|".join(sorted((re.escape(k) for k in _LATEX_TOKENS),
                             key=len, reverse=True)) + r")(?![A-Za-z])")
_WRAPPER_RE = re.compile(
    r"\\(?:" + "|".join(_WRAPPERS) + r")\s*\{([^{}]*)\}")
_HREF_RE = re.compile(r"\\href\s*\{[^{}]*\}\s*\{([^{}]*)\}")
_GENERIC_CMD_ARG = re.compile(r"\\[A-Za-z]+\s*\{([^{}]*)\}")
_LEFTOVER_CMD = re.compile(r"\\[A-Za-z]+\*?")


def _accent(match) -> str:
    mark = _ACCENTS.get(match.group(1), "")
    base = match.group(2)
    if base in ("i", "j"):  # \'{\i} -- dotless i carries the accent
        base = base
    return base + mark


def _delatex(text: Optional[str]) -> str:
    """Decode LaTeX markup in *text* to plain Unicode.

    Deliberately lossy in one direction only: unknown control sequences are
    dropped but their brace argument is kept, so an unrecognised macro never
    deletes words from a title.
    """
    if not text:
        return ""
    s = str(text)
    if "\\" not in s and "{" not in s and "$" not in s:
        if "--" in s:
            s = s.replace("---", "\u2014").replace("--", "\u2013")
        return collapse_ws(s)
    # protect escaped literals before any brace handling
    s = s.replace("\\\\", _BS).replace("\\{", _LB).replace("\\}", _RB)
    for esc, holder in _ESC_PLACEHOLDER.items():
        s = s.replace("\\" + esc, holder)
    s = s.replace("\\ ", " ").replace("\\,", " ").replace("\\;", " ")
    # accents, repeatedly: \c{\'{c}} style nesting occurs in Balkan names
    for _ in range(4):
        before = s
        s = _ACC_BRACE.sub(_accent, s)
        s = _ACC_CMD_BRACE.sub(_accent, s)
        s = _ACC_CMD_PLAIN.sub(_accent, s)
        s = _ACC_PLAIN.sub(_accent, s)
        if s == before:
            break
    s = _TOKEN_RE.sub(lambda m: _LATEX_TOKENS[m.group(1)], s)
    s = _HREF_RE.sub(r"\1", s)
    for _ in range(4):
        before = s
        s = _WRAPPER_RE.sub(r"\1", s)
        s = _GENERIC_CMD_ARG.sub(r"\1", s)
        if s == before:
            break
    s = s.replace("---", "\u2014").replace("--", "\u2013")
    s = _LEFTOVER_CMD.sub("", s)
    s = s.replace("$", "").replace("{", "").replace("}", "")
    s = s.replace(_LB, "{").replace(_RB, "}").replace(_BS, " ")
    for esc, holder in _ESC_PLACEHOLDER.items():
        s = s.replace(holder, esc)
    s = unicodedata.normalize("NFC", s)
    return collapse_ws(s)


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

_VALUE_CHARS = set("abcdefghijklmnopqrstuvwxyz"
                   "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.:/+")
_NAME_CHARS = set("abcdefghijklmnopqrstuvwxyz"
                  "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_+:")


def _skip_ws(text: str, i: int) -> int:
    n = len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
        elif c == "%":
            j = text.find("\n", i)
            i = n if j < 0 else j + 1
        else:
            break
    return i


def _read_braced(text: str, i: int) -> Tuple[str, int]:
    """Read a ``{...}`` group starting at *i*; tolerates an unbalanced tail."""
    n, start, depth = len(text), i, 0
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n:
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i + 1
        i += 1
    return text[start + 1:], n


def _read_quoted(text: str, i: int) -> Tuple[str, int]:
    n, depth = len(text), 0
    i += 1
    buf: List[str] = []
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n:
            buf.append(text[i:i + 2])
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth = max(0, depth - 1)
        elif c == '"' and depth == 0:
            return "".join(buf), i + 1
        buf.append(c)
        i += 1
    return "".join(buf), n


def _read_value(text: str, i: int, strings: Dict[str, str]) -> Tuple[str, int]:
    """Read one (possibly ``#``-concatenated) field value."""
    n = len(text)
    parts: List[str] = []
    while True:
        i = _skip_ws(text, i)
        if i >= n:
            break
        c = text[i]
        if c == "{":
            val, i = _read_braced(text, i)
            parts.append(val)
        elif c == '"':
            val, i = _read_quoted(text, i)
            parts.append(val)
        else:
            j = i
            while j < n and text[j] in _VALUE_CHARS:
                j += 1
            if j == i:
                break
            tok = text[i:j]
            i = j
            parts.append(strings.get(tok.lower(), tok))
        i = _skip_ws(text, i)
        if i < n and text[i] == "#":
            i += 1
            continue
        break
    return "".join(parts), i


def _parse_body(text: str, i: int, closer: str,
                strings: Dict[str, str]) -> Tuple[Dict[str, str], int]:
    fields: Dict[str, str] = {}
    n = len(text)
    while True:
        i = _skip_ws(text, i)
        if i >= n:
            return fields, n
        c = text[i]
        if c in "})":
            return fields, i + 1
        if c == ",":
            i += 1
            continue
        j = i
        while j < n and text[j] in _NAME_CHARS:
            j += 1
        name = text[i:j].strip().lower()
        if not name:
            i += 1
            continue
        i = _skip_ws(text, j)
        if i < n and text[i] == "=":
            val, i = _read_value(text, i + 1, strings)
            if name in fields and val:
                fields[name] = fields[name] + " ; " + val
            elif name not in fields:
                fields[name] = val


def _in_line_comment(text: str, pos: int) -> bool:
    """True when *pos* sits after an unescaped ``%`` on its own line."""
    start = text.rfind("\n", 0, pos) + 1
    i = start
    while i < pos:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "%":
            return True
        i += 1
    return False


def _scan(text: str) -> List[Tuple[str, str, Dict[str, str]]]:
    """Return ``[(entry_type, citekey, fields), ...]`` for *text*."""
    text = text.replace("\ufeff", "")
    strings: Dict[str, str] = {}
    out: List[Tuple[str, str, Dict[str, str]]] = []
    n, i = len(text), 0
    while True:
        at = text.find("@", i)
        if at < 0:
            break
        if _in_line_comment(text, at):
            # "% ... @article{ghost}" -- a commented-out entry in the header
            # block that vendors prepend to exports.
            i = at + 1
            continue
        j = at + 1
        while j < n and text[j].isalpha():
            j += 1
        etype = text[at + 1:j].lower()
        k = _skip_ws(text, j)
        if not etype or k >= n or text[k] not in "{(":
            i = max(at + 1, j)
            continue
        closer = "}" if text[k] == "{" else ")"
        if etype in ("comment", "preamble"):
            if text[k] == "{":
                _, i = _read_braced(text, k)
            else:
                depth, i = 1, k + 1
                while i < n and depth:
                    if text[i] == "(":
                        depth += 1
                    elif text[i] == ")":
                        depth -= 1
                    i += 1
            continue
        if etype == "string":
            f, i = _parse_body(text, k + 1, closer, strings)
            for key, val in f.items():
                strings[key] = val
            continue
        m = k + 1
        while m < n and text[m] not in ",})":
            m += 1
        citekey = text[k + 1:m].strip()
        start = m + 1 if (m < n and text[m] == ",") else m
        f, i = _parse_body(text, start, closer, strings)
        out.append((etype, citekey, f))
    return out


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------

def _split_names(value: str) -> List[str]:
    """Split a BibTeX ``author``/``editor`` value on brace-level-0 ``and``."""
    value = collapse_ws(value)
    if not value:
        return []
    parts: List[str] = []
    buf: List[str] = []
    depth, i, n = 0, 0, len(value)
    while i < n:
        c = value[i]
        if c == "\\" and i + 1 < n:
            buf.append(value[i:i + 2])
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth = max(0, depth - 1)
        if depth == 0 and value[i:i + 5].lower() == " and ":
            parts.append("".join(buf))
            buf = []
            i += 5
            continue
        buf.append(c)
        i += 1
    parts.append("".join(buf))
    out: List[str] = []
    for p in parts:
        p = _delatex(p).strip(" ,;")
        if not p or p.lower() in ("others", "et al.", "et al"):
            continue
        out.append(normalize_author_name(p))
    return [a for a in out if a]


# ---------------------------------------------------------------------------
# Types and dialects
# ---------------------------------------------------------------------------

_ENTRY_TYPE = {
    "article": "article", "inproceedings": "conference",
    "conference": "conference", "proceedings": "conference",
    "incollection": "chapter", "inbook": "chapter",
    "book": "book", "booklet": "book", "collection": "book",
    "phdthesis": "thesis", "mastersthesis": "thesis", "thesis": "thesis",
    "techreport": "report", "manual": "report",
    "unpublished": "preprint", "misc": "", "online": "", "electronic": "",
    "www": "", "patent": "", "dataset": "", "software": "",
}

_DOI_IN_URL = re.compile(r"(10\.\d{4,9}/[^\s{}\"'<>]+)", re.I)
_CITED_BY_RE = re.compile(r"cited\s+by\s*:?\s*(\d+)", re.I)
_PMID_RE = re.compile(r"(?:pmid|pubmed)[:\s]*(\d{5,9})", re.I)


def detect_bibtex_dialect(text: str) -> str:
    """Identify the exporting platform from marker fields.

    ``scopus`` is tested first because a Scopus export of an IEEE or ACM
    paper carries the publisher's name in ``journal``/``publisher`` and would
    otherwise be misread as a native IEEE/ACM export.
    """
    head = text[:40000]
    low = head.lower()
    if ("author_keywords" in low or _CITED_BY_RE.search(low)
            or re.search(r"source\s*=\s*[{\"]scopus", low)
            or "www.scopus.com" in low):
        return "scopus"
    if ("numpages" in low or "articleno" in low
            or "association for computing machinery" in low
            or "acm.org" in low or "@inproceedings{10.1145/" in low
            or re.search(r"doi\s*=\s*[{\"]10\.1145/", low)):
        return "acm"
    if ("ieee" in low and ("keywords" in low or "booktitle" in low
                           or "issn" in low)) or "ieeexplore" in low:
        return "ieee"
    if "unique-id" in low and "wos:" in low:
        return "wos"
    if "archiveprefix" in low and "arxiv" in low:
        return "arxiv"
    return "generic"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_bibtex(text: str, source_name: str = "",
                 dialect: str = "auto",
                 report: Optional[ParseReport] = None) -> List[Record]:
    """Parse BibTeX *text* into :class:`~corpusslr.record.Record` objects.

    An entry is kept when it has a title or a DOI; entries carrying neither are
    discarded, because a ``@string`` definition or a malformed stub has no
    screenable content and would inflate the PRISMA "records identified" count.
    Passing a :class:`~corpusslr.parsers._report.ParseReport` records each
    discarded entry with a reason, so the count that *is* reported can be
    reconciled against the file.
    """
    rep = _ensure(report, "bibtex")
    if not text:
        return []
    if dialect == "auto":
        dialect = detect_bibtex_dialect(text)
    rep.dialect = rep.dialect or dialect
    n_at = text.count("@")
    out: List[Record] = []
    entries = _scan(text)
    for _index, (etype, citekey, f) in enumerate(entries):
        rep.saw()
        def g(*names: str) -> str:
            for nm in names:
                if f.get(nm):
                    return f[nm]
            return ""

        title = _delatex(g("title", "titre"))
        doc_type = _ENTRY_TYPE.get(etype, "")
        if not doc_type:
            doc_type = map_doc_type(g("type", "documenttype", "doc_type"))
        note = g("note", "annote")
        if (g("archiveprefix", "eprinttype").lower() == "arxiv"
                or "arxiv" in g("journal", "booktitle", "eprint").lower()):
            doc_type = doc_type or "preprint"
            if etype == "misc":
                doc_type = "preprint"

        url = collapse_ws(g("url", "ee", "link", "howpublished"))
        url = url.replace("\\", "")
        doi = collapse_ws(g("doi")).replace("\\", "")
        if not doi and url:
            m = _DOI_IN_URL.search(url)
            if m and "doi.org" in url.lower():
                doi = m.group(1)

        pages = clean_pages(_delatex(g("pages", "page")))
        if not pages and g("articleno"):
            pages = collapse_ws(g("articleno"))

        journal = _delatex(g("journal", "journaltitle", "booktitle",
                             "series", "publisher"))

        keywords = split_keywords(_delatex(g("keywords", "author_keywords",
                                             "keyword", "index_keywords")))

        pmid = ""
        for cand in (g("pmid"), note, g("eprint")):
            if not cand:
                continue
            if cand.strip().isdigit() and len(cand.strip()) in (7, 8):
                pmid = cand.strip()
                break
            m = _PMID_RE.search(cand)
            if m:
                pmid = m.group(1)
                break

        cited = None
        m = _CITED_BY_RE.search(note)
        if m:
            cited = parse_int(m.group(1))

        authors = _split_names(g("author"))
        if not authors:
            authors = _split_names(g("editor"))

        rec = Record(
            title=title,
            abstract=_delatex(g("abstract")),
            authors=authors,
            year=parse_year(g("year", "date", "issue_date", "urldate")),
            journal=journal,
            doi=doi,
            pmid=pmid,
            issn=collapse_ws(g("issn")),
            volume=collapse_ws(_delatex(g("volume"))),
            issue=collapse_ws(_delatex(g("number", "issue"))),
            pages=pages,
            doc_type=doc_type,
            language=collapse_ws(g("language", "langid")).lower(),
            keywords=keywords,
            url=url,
            cited_by=cited,
            source=source_name or "BibTeX/{}".format(dialect),
            source_id=citekey,
            raw={"dialect": dialect, "entry_type": etype,
                 "key": citekey, "fields": dict(f)},
        )
        if rec.title or rec.doi:
            out.append(rec)
        elif not f:
            rep.reject(_index, "empty",
                       "@{} entry has no fields".format(etype))
        else:
            rep.reject(_index, "no_content",
                       "@{} entry has no title and no DOI; fields present: "
                       .format(etype) + ",".join(sorted(f)[:12]))
    rep.accept(len(out))
    # An unbalanced brace makes the scanner stop early and swallow the rest of
    # the file. Comparing the number of scanned entries against the number of
    # '@' sigils is a cheap detector, and it is the only signal the caller
    # would otherwise get that records went missing.
    if n_at > len(entries):
        rep.warn("input contains {} '@' sigil(s) but only {} parseable "
                 "entr(ies); the file may be truncated or contain an "
                 "unbalanced brace".format(n_at, len(entries)))
    return out


def parse_bibtex_file(path: str, source_name: str = "",
                      dialect: str = "auto",
                      encoding: str = "auto",
                      report: Optional[ParseReport] = None) -> List[Record]:
    """Read *path* and parse it with :func:`parse_bibtex`.

    ``encoding="auto"`` sniffs the byte-order mark; IEEE Xplore and ACM both
    emit UTF-8, but a BibTeX file re-saved from a Windows reference manager
    can arrive as UTF-16 or Windows-1252.
    """
    rep = _ensure(report, "bibtex")
    text = read_export_text(path, encoding=encoding, report=rep)
    if not text:
        return []
    return parse_bibtex(text, source_name=source_name, dialect=dialect,
                        report=rep)
