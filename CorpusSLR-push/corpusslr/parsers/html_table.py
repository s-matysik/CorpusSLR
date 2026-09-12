"""Reader for spreadsheet exports that are really HTML or TSV.

ProQuest (ABI/INFORM, Dissertations & Theses) offers an export labelled
"XLS", and Web of Science offered the same for years.  The file is **not** an
Excel workbook.  Depending on the platform version it is one of:

1. tab-separated text with a ``.xls`` extension -- readable by the CSV
   parser once the delimiter is sniffed;
2. an HTML document whose single ``<table>`` holds the records, with the
   header in the first ``<tr>`` -- what this module reads;
3. a genuine OLE2/ZIP workbook, which cannot be read without a third-party
   dependency (see ``limitations``).

Excel opens all three, which is why the mislabelling survives; a reviewer who
passes case 2 to a CSV reader gets either zero records or one garbage record
per line of markup.  Detecting the real shape from the *content* rather than
the extension is therefore the only safe behaviour, and it costs no
dependency: :mod:`html.parser` is stdlib.

The parser is deliberately minimal -- it extracts a rectangular cell grid and
hands it to :func:`corpusslr.parsers.csv_exports.parse_csv_rows`, so the
vendor column mapping, dialect detection and field normalisation are shared
with the CSV path and cannot drift.  Nested tables (ProQuest wraps the data
table in a layout table) are handled by tracking table depth and keeping the
table with the most rows.
"""
from __future__ import annotations

from html.parser import HTMLParser
from typing import List, Optional

from ..record import Record
from ._io import looks_like_html, read_export_text
from ._report import ParseReport, _ensure

__all__ = ["parse_html_table", "parse_html_table_file", "extract_table_rows",
           "looks_like_html"]

_SKIP_CONTENT = ("script", "style")
_BREAKS = ("br", "p", "div", "li")


class _TableExtractor(HTMLParser):
    """Collect every ``<table>`` in the document as a list of row lists."""

    def __init__(self) -> None:
        HTMLParser.__init__(self, convert_charrefs=True)
        self.tables: List[List[List[str]]] = []
        self._stack: List[List[List[str]]] = []
        self._row: Optional[List[str]] = None
        self._cell: Optional[List[str]] = None
        self._skip = 0

    # -- structure -------------------------------------------------------
    def handle_starttag(self, tag, attrs) -> None:
        tag = tag.lower()
        if tag in _SKIP_CONTENT:
            self._skip += 1
            return
        if tag == "table":
            self._flush_cell()
            self._flush_row()
            self._stack.append([])
        elif tag == "tr":
            self._flush_row()
            self._row = []
        elif tag in ("td", "th"):
            self._flush_cell()
            if self._row is None:
                self._row = []
            self._cell = []
        elif tag in _BREAKS and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag) -> None:
        tag = tag.lower()
        if tag in _SKIP_CONTENT:
            self._skip = max(0, self._skip - 1)
            return
        if tag in ("td", "th"):
            self._flush_cell()
        elif tag == "tr":
            self._flush_cell()
            self._flush_row()
        elif tag == "table":
            self._flush_cell()
            self._flush_row()
            if self._stack:
                table = self._stack.pop()
                if table:
                    self.tables.append(table)

    def handle_data(self, data) -> None:
        if self._skip or self._cell is None:
            return
        self._cell.append(data)

    # -- buffers ---------------------------------------------------------
    def _flush_cell(self) -> None:
        if self._cell is None:
            return
        text = " ".join("".join(self._cell).split())
        if self._row is None:
            self._row = []
        self._row.append(text)
        self._cell = None

    def _flush_row(self) -> None:
        if self._row is None:
            return
        row, self._row = self._row, None
        if not any(c.strip() for c in row):
            return
        if self._stack:
            self._stack[-1].append(row)

    def close(self) -> None:
        HTMLParser.close(self)
        self._flush_cell()
        self._flush_row()
        # An unclosed <table> (truncated download) still yields its rows.
        while self._stack:
            table = self._stack.pop()
            if table:
                self.tables.append(table)


def extract_table_rows(text: str,
                       report: Optional[ParseReport] = None
                       ) -> List[List[str]]:
    """Return the cell grid of the data table in an HTML document.

    When the document contains several tables -- ProQuest nests the data table
    inside a layout table -- the one with the most rows wins, and a tie is
    broken by column count.  Rows are padded to the width of the header so
    that a short final row from a truncated download does not shift columns.
    """
    extractor = _TableExtractor()
    try:
        extractor.feed(text)
        extractor.close()
    except Exception as exc:  # pragma: no cover - html.parser is tolerant
        if report is not None:
            report.warn("HTML parse stopped early: {}: {}".format(
                type(exc).__name__, exc))
    tables = [t for t in extractor.tables if len(t) >= 2]
    if not tables:
        if report is not None and extractor.tables:
            report.warn("HTML document contains {} table(s) but none with a "
                        "header row and at least one data row"
                        .format(len(extractor.tables)))
        return []
    tables.sort(key=lambda t: (len(t), max(len(r) for r in t)), reverse=True)
    grid = tables[0]
    if report is not None and len(tables) > 1:
        report.warn("HTML document contains {} tables; used the largest "
                    "({} rows)".format(len(tables), len(grid)))
    width = len(grid[0])
    out: List[List[str]] = []
    for row in grid:
        if len(row) < width:
            row = list(row) + [""] * (width - len(row))
        out.append(row)
    return out


def parse_html_table(text: str, dialect: str = "auto", source_name: str = "",
                     report: Optional[ParseReport] = None) -> List[Record]:
    """Parse an HTML-table export (ProQuest/WoS ``.xls``) into records.

    Column mapping is delegated to
    :func:`corpusslr.parsers.csv_exports.parse_csv_rows`, so an HTML export
    and the CSV export of the same search produce identical records and
    deduplicate against each other.
    """
    from .csv_exports import parse_csv_rows  # local: avoids a circular import

    rep = _ensure(report, "html-table")
    rows = extract_table_rows(text, report=rep)
    if not rows:
        return []
    return parse_csv_rows(rows, dialect=dialect, source_name=source_name,
                          report=rep)


def parse_html_table_file(path: str, dialect: str = "auto",
                          source_name: str = "", encoding: str = "auto",
                          report: Optional[ParseReport] = None
                          ) -> List[Record]:
    """Read and parse an HTML-table export file."""
    rep = _ensure(report, "html-table")
    text = read_export_text(path, encoding=encoding, report=rep)
    if not text:
        return []
    return parse_html_table(text, dialect=dialect, source_name=source_name,
                            report=rep)
