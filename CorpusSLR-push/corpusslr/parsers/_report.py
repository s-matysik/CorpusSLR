"""Accounting for records that a file-export parser did *not* return.

Every export parser has to reject some input: a stanza with neither title nor
identifier carries no screenable content, a truncated final record is
incomplete, a CSV row may be the blank filler that Excel appends.  Dropping
such input is correct; dropping it *silently* is not.  A PRISMA 2020 flow
diagram requires the number of records identified per source (Item 16a), and
that number is taken from the import step.  If a parser reads a 2 000-record
Embase file and returns 1 987 Records without saying so, the review reports
1 987 as "records identified" and the 13 lost records are unrecoverable and
invisible -- the reviewer has no way to know the count is wrong.

:class:`ParseReport` closes that hole.  Parsers accept an optional ``report``
argument; when one is supplied they record every rejected input unit together
with a machine-readable reason, so the caller can reconcile
``report.n_input == len(records) + report.n_rejected`` and put a defensible
number into the flow diagram.  When no report is passed the parsers behave
exactly as before, which keeps the argument backwards compatible.

Rejection reasons are a closed vocabulary so that they can be tabulated:

``no_content``
    The unit parsed but yielded neither a title nor a DOI/PMID/accession, so
    it cannot be screened or deduplicated.
``empty``
    The unit contained no recognisable fields at all (blank stanza, filler
    row).
``malformed``
    The unit could not be parsed (unbalanced BibTeX entry, XML element that
    the recovery pass could not repair).
``truncated``
    The input ended in the middle of the unit.
``unreadable``
    The whole input could not be decoded or is not text at all.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

__all__ = ["ParseReport", "REJECTION_REASONS"]

#: Closed vocabulary of rejection reasons (see module docstring).
REJECTION_REASONS = ("no_content", "empty", "malformed", "truncated",
                     "unreadable")


class ParseReport(object):
    """Mutable tally of what a parser accepted, rejected and warned about.

    The object is deliberately a plain class rather than a dataclass so that
    it behaves identically on Python 3.9 and can be extended by a caller that
    wants to attach its own bookkeeping.

    Attributes
    ----------
    fmt, dialect, encoding, path
        Provenance of the parsed input; filled in by the parser when known.
        These belong in the PRISMA-S search appendix (which file, exported
        from which platform, read as which encoding).
    n_input
        Number of input units the parser *saw* -- RIS stanzas, BibTeX
        entries, CSV data rows, XML ``<record>`` elements.  Always equals
        ``n_accepted + n_rejected``.
    n_accepted
        Number of :class:`~corpusslr.record.Record` objects returned.
    rejections
        One dict per rejected unit: ``{"index", "reason", "detail"}`` where
        ``index`` is the zero-based position of the unit in the input.
    warnings
        Non-fatal observations that do not cost a record (a replaced
        undecodable byte, an unknown vendor dialect, a raised field limit).
    """

    __slots__ = ("fmt", "dialect", "encoding", "path", "n_input",
                 "n_accepted", "rejections", "warnings")

    def __init__(self, fmt: str = "", dialect: str = "", encoding: str = "",
                 path: str = "") -> None:
        self.fmt = fmt
        self.dialect = dialect
        self.encoding = encoding
        self.path = path
        self.n_input = 0
        self.n_accepted = 0
        self.rejections: List[Dict[str, Any]] = []
        self.warnings: List[str] = []

    # -- recording -------------------------------------------------------
    def saw(self, n: int = 1) -> None:
        """Count *n* input units as seen."""
        self.n_input += n

    def accept(self, n: int = 1) -> None:
        """Count *n* units as returned to the caller."""
        self.n_accepted += n

    def reject(self, index: int, reason: str, detail: str = "") -> None:
        """Record one dropped unit.

        *reason* should be one of :data:`REJECTION_REASONS`; an unknown value
        is stored verbatim rather than raising, because losing the audit
        entry would be worse than an off-vocabulary label.
        """
        self.rejections.append({"index": int(index), "reason": str(reason),
                                "detail": str(detail)[:500]})

    def warn(self, message: str) -> None:
        """Record a non-fatal observation."""
        self.warnings.append(str(message))

    # -- derived ---------------------------------------------------------
    @property
    def n_rejected(self) -> int:
        return len(self.rejections)

    @property
    def balanced(self) -> bool:
        """True when every input unit was either returned or accounted for.

        A parser that fails this check is losing records silently, which is
        the defect this class exists to detect; the test suite asserts it for
        every parser and every fixture.
        """
        return self.n_input == self.n_accepted + self.n_rejected

    def reason_counts(self) -> Dict[str, int]:
        """Rejections tallied per reason, for a per-source import table."""
        counts: Dict[str, int] = {}
        for item in self.rejections:
            key = str(item.get("reason") or "")
            counts[key] = counts.get(key, 0) + 1
        return counts

    def to_dict(self) -> Dict[str, Any]:
        """Serialise for a harvest manifest or PRISMA-S appendix."""
        return {
            "format": self.fmt, "dialect": self.dialect,
            "encoding": self.encoding, "path": self.path,
            "n_input": self.n_input, "n_accepted": self.n_accepted,
            "n_rejected": self.n_rejected,
            "reason_counts": self.reason_counts(),
            "rejections": list(self.rejections),
            "warnings": list(self.warnings),
            "balanced": self.balanced,
        }

    def summary(self) -> str:
        """One-line human-readable summary for a log or console report."""
        parts = ["{} record(s) parsed".format(self.n_accepted)]
        if self.n_rejected:
            detail = ", ".join(
                "{}={}".format(k, v)
                for k, v in sorted(self.reason_counts().items()))
            parts.append("{} rejected ({})".format(self.n_rejected, detail))
        if self.fmt:
            label = self.fmt
            if self.dialect and self.dialect != "generic":
                label += "/" + self.dialect
            parts.append("format={}".format(label))
        if self.encoding:
            parts.append("encoding={}".format(self.encoding))
        if self.warnings:
            parts.append("{} warning(s)".format(len(self.warnings)))
        return "; ".join(parts)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<ParseReport {}>".format(self.summary())


def _ensure(report: Optional[ParseReport], fmt: str = "",
            dialect: str = "") -> ParseReport:
    """Return *report*, or a throwaway one, with provenance filled in.

    Internal helper so a parser can use the same code path whether or not the
    caller asked for accounting.
    """
    rep = report if report is not None else ParseReport()
    if fmt and not rep.fmt:
        rep.fmt = fmt
    if dialect and not rep.dialect:
        rep.dialect = dialect
    return rep
