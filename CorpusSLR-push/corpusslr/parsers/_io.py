"""Byte-level input handling for the file-export parsers.

A reviewer exporting search results does not choose an encoding, and the
databases do not agree on one.  Observed in real exports:

* Scopus CSV and Web of Science plain text: UTF-8 **with** a BOM;
* Web of Science ``.ciw`` and some Ovid/Embase RIS: UTF-16 little-endian
  with a BOM (this is what "Save to Other File Formats -> Plain text" gives
  on Windows);
* EBSCOhost and ProQuest RIS: UTF-8 without a BOM, but occasionally
  Windows-1252 when the export is routed through an institutional proxy;
* legacy EndNote and older Cochrane Library downloads: Windows-1252 or
  ISO-8859-1.

Opening all of them with a fixed ``encoding="utf-8-sig"`` is what the parsers
used to do.  For UTF-16 input that does not raise -- it silently yields text
in which every character is separated by a NUL, so no tag line matches and
the parser returns **zero records without an error**.  That is the worst
possible failure mode for a systematic review: a source contributes 0
records to the PRISMA flow diagram and nothing anywhere says why.

:func:`sniff_encoding` therefore inspects the bytes: byte-order marks first
(they are decisive), then a UTF-16 test for BOM-less files exported on
Windows, then strict UTF-8, then the Windows-1252/Latin-1 fallbacks.  The
chosen encoding is reported back through :class:`~corpusslr.parsers._report.ParseReport`
so it can be stated in the PRISMA-S search appendix.

Genuinely non-text input (a PDF or XLSX picked by mistake in a file dialog)
is detected by :func:`looks_binary` and reported as ``unreadable`` rather
than parsed into garbage records.
"""
from __future__ import annotations

import csv
import re
from typing import List, Optional, Tuple

from ._report import ParseReport

__all__ = ["sniff_encoding", "decode_export", "read_export_bytes",
           "read_export_text", "looks_binary", "normalize_newlines",
           "csv_field_limit", "BINARY_SIGNATURES"]

#: Magic numbers of container formats that are sometimes handed to a text
#: parser by mistake.  ``PK\x03\x04`` covers XLSX/DOCX/ODS (all ZIP), which is
#: the realistic accident: the user exported "Excel" from Scopus and passed
#: the ``.xlsx`` to a CSV reader.
BINARY_SIGNATURES = (
    (b"%PDF-", "PDF"),
    (b"PK\x03\x04", "ZIP container (XLSX/DOCX/ODS)"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "OLE2 (legacy .xls/.doc)"),
    (b"\x1f\x8b", "gzip"),
    (b"BZh", "bzip2"),
    (b"\x89PNG", "PNG"),
    (b"\xff\xd8\xff", "JPEG"),
    (b"SQLite format 3\x00", "SQLite database"),
)

_BOMS = (
    (b"\x00\x00\xfe\xff", "utf-32-be"),
    (b"\xff\xfe\x00\x00", "utf-32-le"),
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xfe\xff", "utf-16-be"),
    (b"\xff\xfe", "utf-16-le"),
)

# Bytes that never occur in decoded export text.  Tab, LF, CR and FF are
# legitimate; the remaining C0 controls are not.
_CTRL = bytes(b for b in range(32) if b not in (9, 10, 12, 13))


def magic_kind(data: bytes) -> str:
    """Return the container format identified by a magic number, else ``""``.

    Checked before any encoding heuristic, because a PDF or ZIP payload is
    NUL-heavy and the BOM-less UTF-16 test would otherwise claim it.
    """
    for magic, label in BINARY_SIGNATURES:
        if data.startswith(magic):
            return label
    return ""


def control_byte_kind(data: bytes) -> str:
    """Flag input whose control-byte density rules out a text export.

    More than 5 % C0 control bytes (excluding tab, newline, carriage return
    and form feed) in the first 8 KiB means the input is not text.  This test
    must **not** be applied to UTF-16, which is NUL-padded by construction --
    callers consult :func:`sniff_encoding` first and skip it for a UTF-16 or
    UTF-32 verdict.
    """
    sample = data[:8192]
    ctrl = sum(sample.count(bytes([b])) for b in _CTRL)
    if ctrl and ctrl * 20 > len(sample):
        return "binary data ({} control bytes in {})".format(ctrl,
                                                             len(sample))
    return ""


def looks_binary(data: bytes) -> str:
    """Return a description of the container format, or ``""`` for text.

    Magic number first, then control-byte density.  Note that raw UTF-16 text
    *is* flagged by the density test, so :func:`decode_export` applies the two
    halves separately rather than calling this function -- it is kept as the
    public convenience predicate for callers holding 8-bit text.
    """
    if not data:
        return ""
    return magic_kind(data) or control_byte_kind(data)


def _utf16_without_bom(data: bytes) -> Optional[str]:
    """Detect BOM-less UTF-16 by the NUL padding of ASCII-heavy text.

    In UTF-16 encoded ASCII every second byte is NUL, and which half carries
    the NUL identifies the endianness.  Requires at least four NULs in the
    sample so that a stray NUL in an otherwise 8-bit file does not trigger
    the branch.
    """
    sample = data[:4096]
    if sample.count(b"\x00") < 4:
        return None
    even = sum(1 for i in range(0, len(sample) - 1, 2) if sample[i] == 0)
    odd = sum(1 for i in range(1, len(sample), 2) if sample[i] == 0)
    pairs = max(1, len(sample) // 2)
    if odd > pairs * 0.4 and odd > even:
        return "utf-16-le"
    if even > pairs * 0.4 and even > odd:
        return "utf-16-be"
    return None


def sniff_encoding(data: bytes) -> Tuple[str, List[str]]:
    """Guess the text encoding of an export file.

    Returns ``(encoding, warnings)``.  The encoding name is always usable
    with :meth:`bytes.decode`; ``warnings`` explains any non-obvious choice
    so the parser can surface it in the parse report.

    Resolution order -- BOM, BOM-less UTF-16, strict UTF-8, Windows-1252,
    Latin-1 -- is chosen so that a correct guess is never overridden by a
    fallback: UTF-8 is self-validating, so a file that decodes cleanly as
    UTF-8 is treated as UTF-8, and only genuinely invalid byte sequences fall
    through to the single-byte code pages.
    """
    warnings: List[str] = []
    if not data:
        return "utf-8", warnings
    for bom, enc in _BOMS:
        if data.startswith(bom):
            return enc, warnings
    guess = _utf16_without_bom(data)
    if guess:
        warnings.append(
            "input decoded as {} (no byte-order mark); NUL-padded bytes are "
            "characteristic of a Windows UTF-16 export".format(guess))
        return guess, warnings
    try:
        data.decode("utf-8")
        return "utf-8", warnings
    except UnicodeDecodeError:
        pass
    try:
        data.decode("cp1252")
        warnings.append("input is not valid UTF-8; decoded as cp1252 "
                        "(Windows-1252)")
        return "cp1252", warnings
    except UnicodeDecodeError:
        pass
    warnings.append("input is neither valid UTF-8 nor cp1252; decoded as "
                    "latin-1, some characters may be wrong")
    return "latin-1", warnings


def normalize_newlines(text: str) -> str:
    """Convert CRLF and lone-CR line endings to LF.

    Classic Mac line endings still reach us from EndNote on macOS and from
    spreadsheet round-trips.  ``str.splitlines`` handles them, but the CSV
    module and any regex anchored with ``^``/``$`` do not, so normalising
    once at the input boundary is what keeps the parsers consistent.
    """
    if not text:
        return ""
    if "\r" not in text:
        return text
    return text.replace("\r\n", "\n").replace("\r", "\n")


def decode_export(data: bytes, encoding: str = "auto",
                  report: Optional[ParseReport] = None,
                  path: str = "") -> str:
    """Decode export *data* to text, sniffing the encoding when asked.

    ``encoding="auto"`` runs :func:`sniff_encoding`; any other value is used
    verbatim (so a caller who knows better keeps control).  Undecodable bytes
    are replaced rather than raising -- one corrupt character must not cost
    the whole file -- and the substitution is counted as a warning.

    A file detected as a binary container yields ``""`` plus an
    ``unreadable`` rejection, which is how a parser reports "this is not a
    text export" without raising at the caller.
    """
    if report is not None and path and not report.path:
        report.path = path
    if not data:
        if report is not None:
            report.encoding = report.encoding or "utf-8"
        return ""
    # A magic number is decisive and is tested FIRST: a PDF or ZIP payload is
    # NUL-heavy, so the BOM-less UTF-16 heuristic would otherwise claim it and
    # the file would be "decoded" into mojibake instead of being refused.
    kind = magic_kind(data)
    enc = encoding
    if not kind:
        if encoding == "auto":
            enc, warnings = sniff_encoding(data)
            if report is not None:
                for message in warnings:
                    report.warn(message)
        # The control-byte test is skipped for UTF-16/32, which is NUL-padded
        # by construction and would otherwise be misread as binary.
        if not enc.startswith("utf-16") and not enc.startswith("utf-32"):
            kind = control_byte_kind(data)
    if kind:
        if report is not None:
            report.encoding = ""
            report.saw(1)
            report.reject(0, "unreadable",
                          "input is not a text export: {}".format(kind))
            report.warn("refused to parse {} as text".format(kind))
        return ""
    text = data.decode(enc, errors="replace")
    if report is not None:
        report.encoding = enc
        n_bad = text.count("\ufffd")
        if n_bad:
            report.warn("{} undecodable byte(s) replaced with U+FFFD while "
                        "decoding as {}".format(n_bad, enc))
    return normalize_newlines(text)


def read_export_bytes(path: str) -> bytes:
    """Read a whole export file as bytes."""
    with open(path, "rb") as fh:
        return fh.read()


def read_export_text(path: str, encoding: str = "auto",
                     report: Optional[ParseReport] = None) -> str:
    """Read an export file and decode it, sniffing the encoding by default.

    This is the single input boundary shared by every ``parse_*_file``
    function, so that the file and in-memory code paths cannot drift apart --
    the defect class that produced the ``parse_csv_export`` text-input bug.
    """
    data = read_export_bytes(path)
    return decode_export(data, encoding=encoding, report=report, path=path)


class csv_field_limit(object):
    """Context manager raising :func:`csv.field_size_limit` temporarily.

    The stdlib CSV reader refuses fields larger than 131 072 characters and
    raises :exc:`_csv.Error`, which aborts the *entire* file.  Real exports do
    exceed it: a Scopus CSV row carrying a full abstract plus an author
    affiliation list for a 400-author physics paper runs past 200 kB, and an
    EBSCOhost row can embed the whole record as HTML.  Losing 5 000 records
    because one of them is long is not acceptable, so the limit is raised for
    the duration of the parse and restored afterwards (it is process-global
    state, so leaving it raised would be a side effect on the caller).
    """

    __slots__ = ("size", "_previous")

    def __init__(self, size: int = 64 * 1024 * 1024) -> None:
        self.size = int(size)
        self._previous = None  # type: Optional[int]

    def __enter__(self) -> "csv_field_limit":
        self._previous = csv.field_size_limit()
        try:
            csv.field_size_limit(self.size)
        except (OverflowError, ValueError):  # pragma: no cover - platform cap
            csv.field_size_limit(self._previous)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        # Returning None (rather than False) states that this context manager
        # never suppresses an exception -- a False-typed __exit__ tells a type
        # checker the manager *may* swallow errors raised inside the block.
        if self._previous is not None:
            csv.field_size_limit(self._previous)


_HTML_RE = re.compile(r"<\s*(html|table|!doctype)\b", re.I)


def looks_like_html(text: str) -> bool:
    """True when *text* is an HTML document rather than delimited text.

    ProQuest labels its spreadsheet export ``.xls`` but emits either TSV or
    an HTML ``<table>``; Web of Science did the same for years.  Callers use
    this to route the input to the HTML table reader instead of the CSV
    reader.
    """
    return bool(_HTML_RE.search(text[:4096]))
