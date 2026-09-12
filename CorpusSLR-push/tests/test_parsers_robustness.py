"""Property tests: no parser may raise, and none may lose a record silently.

Two invariants are asserted for every file-export parser against every
degenerate input a reviewer can realistically produce (a cancelled download,
a Windows UTF-16 export, a spreadsheet round-trip, a PDF picked by mistake):

**P1 -- no unhandled exception.**  An import step that dies on one bad file in
a directory of twenty cannot report how many records it found, so every parser
returns a list or an empty list, never a traceback.

**P2 -- every rejection is counted.**  Dropping a record is often correct;
dropping it *invisibly* corrupts the "records identified" box of the PRISMA
2020 flow diagram (Item 16a), and the reviewer has no way to notice.  So for
every input, ``report.n_input == len(records) + report.n_rejected``.

The inputs are generated combinatorially (format x corruption x encoding)
rather than written out one by one, so a new corruption mode is tested against
every parser at once.
"""
from __future__ import annotations

import os

import pytest

from corpusslr.parsers import (ParseReport, looks_binary, parse_bibtex,
                               parse_bibtex_file, parse_csv_export,
                               parse_csv_export_file, parse_endnote_xml,
                               parse_endnote_xml_file, parse_enw,
                               parse_enw_file, parse_nbib, parse_nbib_file,
                               parse_ris, parse_ris_file, parse_wos,
                               parse_wos_file, sniff_encoding)

# --------------------------------------------------------------------------
# One well-formed two-record sample per format, shaped like a real export
# --------------------------------------------------------------------------

RIS_EMBASE = """TY  - JOUR
TI  - Machine learning for early sepsis detection
AU  - Smith, J.
AU  - Doe, A.
T2  - Critical Care Medicine
JF  - Crit Care Med
PY  - 2022
VL  - 50
IS  - 3
SP  - e123
EP  - e130
DO  - 10.1097/CCM.0000000000005432
AN  - PMID:35123456
M3  - Article
DB  - Embase
ER  -

TY  - JOUR
TI  - Conference abstract on sepsis biomarkers
AU  - Rossi, M.
T2  - Intensive Care Medicine
PY  - 2021
AN  - L2015467890
M3  - Conference Abstract
DB  - Embase
ER  -
"""

WOS_TAGGED = """FN Clarivate Analytics Web of Science
VR 1.0
PT J
AU Kowalski, J
   Nowak, A
TI Bibliometric mapping of artificial intelligence research
SO SCIENTOMETRICS
DT Article
DI 10.1007/s11192-021-04001-1
PY 2021
VL 126
IS 4
BP 3011
EP 3035
PM 34567890
UT WOS:000654321000012
ER

PT J
AU Muller, H
TI Citation networks in evidence synthesis
SO JOURNAL OF INFORMETRICS
DT Review
DI 10.1016/j.joi.2022.101234
PY 2022
UT WOS:000765432100005
ER

EF
"""

NBIB_MEDLINE = """PMID- 35123456
OWN - NLM
STAT- MEDLINE
DP  - 2022 Mar
TI  - Machine learning for early sepsis detection.
PG  - e123-e130
AB  - Sepsis remains a leading cause of mortality.
FAU - Smith, John
AU  - Smith J
TA  - Crit Care Med
JT  - Critical care medicine
VI  - 50
IP  - 3
LA  - eng
PT  - Journal Article
MH  - Humans
MH  - Sepsis/*diagnosis
AID - 10.1097/CCM.0000000000005432 [doi]
IS  - 1530-0293 (Electronic)

PMID- 34567890
DP  - 2021
TI  - Citation networks in evidence synthesis.
TA  - J Informetr
LA  - eng
PT  - Review
"""

BIBTEX_IEEE = """@ARTICLE{9366721,
  author={Zhang, Wei and Ortiz, Luis},
  journal={IEEE Transactions on Signal Processing},
  title={Deep Learning for Signal Classification},
  year={2021},
  volume={69},
  number={4},
  pages={1024-1035},
  keywords={Signal processing;Neural networks},
  doi={10.1109/TSP.2021.3054321},
  ISSN={1941-0476}}

@INPROCEEDINGS{9414321,
  author={Ahmed, S. and Kaur, P.},
  booktitle={2021 IEEE International Conference on Acoustics, Speech and Signal Processing (ICASSP)},
  title={Attention Models for Audio Retrieval},
  year={2021},
  pages={4410-4414},
  doi={10.1109/ICASSP39728.2021.9414321}}
"""

ENDNOTE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<xml><records>
<record>
<ref-type name="Journal Article">17</ref-type>
<contributors><authors>
<author>Kowalski, Jan</author><author>Nowak, Anna</author>
</authors></contributors>
<titles><title>Bibliometric mapping of AI research</title>
<secondary-title>Scientometrics</secondary-title></titles>
<dates><year>2021</year></dates>
<volume>126</volume><pages>3011-3035</pages>
<electronic-resource-num>10.1007/s11192-021-04001-1</electronic-resource-num>
<accession-num>WOS:000654321000012</accession-num>
</record>
<record>
<ref-type name="Conference Proceedings">10</ref-type>
<contributors><authors><author>Ahmed, Sara</author></authors></contributors>
<titles><title>Attention models for audio retrieval</title>
<secondary-title>ICASSP 2021</secondary-title></titles>
<dates><year>2021</year></dates>
<electronic-resource-num>10.1109/ICASSP39728.2021.9414321</electronic-resource-num>
</record>
</records></xml>
"""

CSV_SCOPUS = ('Authors,Title,Year,Source title,Volume,Issue,Page start,'
              'Page end,Cited by,DOI,Link,Author Keywords,Index Keywords,'
              'Document Type,EID\n'
              '"Kowalski J.; Nowak A.","Bibliometric mapping of AI research",'
              '2021,"Scientometrics",126,4,3011,3035,42,'
              '"10.1007/s11192-021-04001-1",'
              '"https://www.scopus.com/inward/record.uri?eid=2-s2.0-85100",'
              '"bibliometrics; artificial intelligence","Data mining",'
              '"Article","2-s2.0-85100000001"\n'
              '"Muller H.","Citation networks in evidence synthesis",2022,'
              '"Journal of Informetrics",16,1,,,7,"10.1016/j.joi.2022.101234",'
              ',"citation analysis",,"Review","2-s2.0-85100000002"\n')

ENW_ACM = """%0 Conference Paper
%A Chen, Wei
%T Neural retrieval for systematic review screening
%B Proceedings of CIKM '23
%D 2023
%P 1123-1132
%R 10.1145/3583780.3614999

%0 Journal Article
%A Nowak, Anna
%T Screening automation in evidence synthesis
%J ACM Transactions on Information Systems
%D 2024
%R 10.1145/3640000

"""

#: ``(label, text_parser, file_parser, sample, expected_records)``
FORMATS = [
    ("ris", parse_ris, parse_ris_file, RIS_EMBASE, 2),
    ("wos", parse_wos, parse_wos_file, WOS_TAGGED, 2),
    ("nbib", parse_nbib, parse_nbib_file, NBIB_MEDLINE, 2),
    ("bibtex", parse_bibtex, parse_bibtex_file, BIBTEX_IEEE, 2),
    ("endnote_xml", parse_endnote_xml, parse_endnote_xml_file,
     ENDNOTE_XML, 2),
    ("csv", parse_csv_export, parse_csv_export_file, CSV_SCOPUS, 2),
    ("enw", parse_enw, parse_enw_file, ENW_ACM, 2),
]

IDS = [f[0] for f in FORMATS]


# --------------------------------------------------------------------------
# Baseline: the well-formed samples parse, and the accounting balances
# --------------------------------------------------------------------------

@pytest.mark.parametrize("label,parse,_pf,sample,expected", FORMATS, ids=IDS)
def test_wellformed_sample_parses_and_balances(label, parse, _pf, sample,
                                               expected):
    rep = ParseReport()
    recs = parse(sample, report=rep)
    assert len(recs) == expected, label
    assert rep.n_rejected == 0
    assert rep.balanced
    assert all(r.title for r in recs)


# --------------------------------------------------------------------------
# P1/P2 across corruption modes
# --------------------------------------------------------------------------

def _corruptions(sample: str):
    """Realistic ways an export file arrives damaged."""
    return {
        "empty": "",
        "whitespace_only": "   \n\n\t\n",
        "truncated_half": sample[:len(sample) // 2],
        "truncated_quarter": sample[:max(1, len(sample) // 4)],
        "truncated_one_char": sample[:1],
        "header_only": sample.splitlines()[0] if sample.splitlines() else "",
        "crlf": sample.replace("\n", "\r\n"),
        "cr_only": sample.replace("\n", "\r"),
        "mixed_newlines": sample.replace("\n", "\r\n", 3).replace("\n", "\r",
                                                                 2),
        "no_trailing_newline": sample.rstrip("\n"),
        "bom_prefixed": "\ufeff" + sample,
        "nul_injected": sample[:40] + "\x00\x00" + sample[40:],
        "very_long_field": sample.replace("2021", "2021" + "x" * 200000, 1),
        "duplicated": sample + "\n" + sample,
        "binary_garbage": "\x00\x01\x02\x03\xff\xfe PK\x03\x04 \x00\x00",
        "html_page": "<html><body><h1>Access denied</h1></body></html>",
        "wrong_format_json": '{"error": "quota exceeded", "records": []}',
        "only_separators": ";;;\n,,,\n\t\t\t\n",
        "single_field_no_value": "TY  - \nTI  - \nER  - \n",
    }


@pytest.mark.parametrize("label,parse,_pf,sample,_e", FORMATS, ids=IDS)
def test_p1_no_parser_raises_on_corrupted_input(label, parse, _pf, sample,
                                                _e):
    for name, text in _corruptions(sample).items():
        try:
            recs = parse(text)
        except Exception as exc:  # pragma: no cover - this is the assertion
            pytest.fail("{} raised {} on {!r} input: {}".format(
                label, type(exc).__name__, name, exc))
        assert isinstance(recs, list), "{}/{}".format(label, name)


@pytest.mark.parametrize("label,parse,_pf,sample,_e", FORMATS, ids=IDS)
def test_p2_every_rejection_is_counted(label, parse, _pf, sample, _e):
    for name, text in _corruptions(sample).items():
        rep = ParseReport()
        recs = parse(text, report=rep)
        assert rep.n_input == len(recs) + rep.n_rejected, (
            "{}/{}: saw {} input unit(s) but returned {} and rejected {} "
            "-- {} record(s) lost silently".format(
                label, name, rep.n_input, len(recs), rep.n_rejected,
                rep.n_input - len(recs) - rep.n_rejected))
        assert rep.balanced


@pytest.mark.parametrize("label,parse,_pf,sample,_e", FORMATS, ids=IDS)
def test_records_missing_a_title_are_never_returned_empty(label, parse, _pf,
                                                          sample, _e):
    """A returned Record must carry something screenable."""
    for name, text in _corruptions(sample).items():
        for rec in parse(text):
            assert (rec.title or rec.doi or rec.pmid or rec.source_id), (
                "{}/{} returned a record with no title and no identifier"
                .format(label, name))


@pytest.mark.parametrize("label,parse,_pf,sample,expected", FORMATS, ids=IDS)
def test_long_field_does_not_cost_the_other_records(label, parse, _pf, sample,
                                                    expected):
    """A 200 kB field must not abort the file.

    The stdlib CSV reader raises ``_csv.Error`` above 131 072 characters,
    which used to discard every record in the file.
    """
    padded = sample.replace("2021", "2021" + "y" * 200000, 1)
    rep = ParseReport()
    recs = parse(padded, report=rep)
    assert len(recs) == expected, label
    assert rep.balanced


# --------------------------------------------------------------------------
# Encoding matrix -- the file path
# --------------------------------------------------------------------------

ENCODINGS = [
    ("utf-8", b""),
    ("utf-8", b"\xef\xbb\xbf"),          # BOM written explicitly
    ("utf-16", b""),                     # codec emits its own BOM
    ("utf-16-le", b"\xff\xfe"),
    ("utf-16-be", b"\xfe\xff"),
    ("cp1252", b""),
    ("latin-1", b""),
]


@pytest.mark.parametrize("label,_p,parse_file,sample,expected", FORMATS,
                         ids=IDS)
@pytest.mark.parametrize("encoding,bom",
                         ENCODINGS,
                         ids=[("%s%s" % (e, "+bom" if b else ""))
                              for e, b in ENCODINGS])
def test_every_encoding_is_read_from_disk(label, _p, parse_file, sample,
                                          expected, encoding, bom, tmp_path):
    """A UTF-16 export must not silently yield zero records.

    This is the regression test for the defect that made a Windows Ovid/WoS
    export parse to nothing: a fixed ``encoding="utf-8-sig"`` decoded UTF-16
    into NUL-separated characters that matched no tag.
    """
    path = os.path.join(str(tmp_path), "export_{}_{}".format(label, encoding))
    with open(path, "wb") as fh:
        fh.write(bom + sample.encode(encoding, errors="replace"))
    rep = ParseReport()
    recs = parse_file(path, report=rep)
    assert len(recs) == expected, (
        "{} read as {} yielded {} of {} records (encoding detected: {})"
        .format(label, encoding, len(recs), expected, rep.encoding))
    assert rep.balanced


@pytest.mark.parametrize("label,_p,parse_file,sample,expected", FORMATS,
                         ids=IDS)
def test_non_ascii_survives_the_roundtrip(label, _p, parse_file, sample,
                                          expected, tmp_path):
    """Polish diacritics must not be mangled into '?' by the sniffer."""
    text = sample.replace("Kowalski", "Kowalczyk-Żółć").replace(
        "Nowak", "Nowák")
    for encoding in ("utf-8", "utf-16", "cp1252"):
        path = os.path.join(str(tmp_path), "dia_{}_{}".format(label, encoding))
        with open(path, "wb") as fh:
            fh.write(text.encode(encoding, errors="replace"))
        recs = parse_file(path)
        assert len(recs) == expected
        if encoding != "cp1252":       # cp1252 cannot represent Ż
            blob = " ".join(" ".join(r.authors) + r.title for r in recs)
            if "Kowalczyk" in text:
                assert "\ufffd" not in blob, (label, encoding)


@pytest.mark.parametrize("label,_p,parse_file,_s,_e", FORMATS, ids=IDS)
def test_empty_file_on_disk_yields_no_records(label, _p, parse_file, _s, _e,
                                             tmp_path):
    path = os.path.join(str(tmp_path), "empty_{}".format(label))
    open(path, "wb").close()
    rep = ParseReport()
    assert parse_file(path, report=rep) == []
    assert rep.balanced


@pytest.mark.parametrize("label,_p,parse_file,_s,_e", FORMATS, ids=IDS)
def test_binary_file_is_refused_and_counted_not_parsed(label, _p, parse_file,
                                                       _s, _e, tmp_path):
    """A PDF or XLSX handed to a text parser is reported, not read as text."""
    for payload, kind in ((b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n" + b"\x00" * 400,
                           "PDF"),
                          (b"PK\x03\x04\x14\x00" + b"\x00" * 400, "ZIP")):
        path = os.path.join(str(tmp_path), "bin_{}_{}".format(label, kind))
        with open(path, "wb") as fh:
            fh.write(payload)
        rep = ParseReport()
        recs = parse_file(path, report=rep)
        assert recs == [], "{} parsed a {} as text".format(label, kind)
        assert rep.n_rejected == 1
        assert rep.rejections[0]["reason"] == "unreadable"
        assert rep.balanced


# --------------------------------------------------------------------------
# The text-input path must agree with the file path
# --------------------------------------------------------------------------

@pytest.mark.parametrize("label,parse,parse_file,sample,expected", FORMATS,
                         ids=IDS)
def test_text_and_file_paths_agree(label, parse, parse_file, sample, expected,
                                   tmp_path):
    """``parse_x(text)`` and ``parse_x_file(path)`` must return the same thing.

    The two paths drifting apart is exactly the defect class that made
    ``parse_csv_export(text)`` fail on every dialect while the file path
    worked, so it is asserted for every format and every line ending.
    """
    for newline in ("\n", "\r\n", "\r"):
        text = sample.replace("\n", newline)
        path = os.path.join(str(tmp_path), "agree_{}".format(label))
        with open(path, "wb") as fh:
            fh.write(text.encode("utf-8"))
        from_text = parse(text)
        from_file = parse_file(path)
        assert len(from_text) == len(from_file) == expected, (
            "{} with {!r}: text={} file={}".format(
                label, newline, len(from_text), len(from_file)))
        assert [r.title for r in from_text] == [r.title for r in from_file]
        assert [r.doi for r in from_text] == [r.doi for r in from_file]


# --------------------------------------------------------------------------
# Encoding sniffer and binary detector, directly
# --------------------------------------------------------------------------

@pytest.mark.parametrize("encoding,expected", [
    ("utf-8", "utf-8"),
    ("utf-8-sig", "utf-8-sig"),
    ("utf-16", None),          # codec picks the endianness; BOM decides
    ("utf-16-le", "utf-16-le"),
    ("utf-16-be", "utf-16-be"),
])
def test_sniff_encoding_identifies_bom_and_utf16(encoding, expected):
    data = ("TY  - JOUR\nTI  - Sniffer test\nER  - \n"
            .encode(encoding))
    got, _warnings = sniff_encoding(data)
    if expected is None:
        assert got.startswith("utf-16")
    else:
        assert got == expected


def test_sniff_encoding_detects_bomless_utf16():
    data = ("TY  - JOUR\nTI  - No byte order mark here at all\nER  - \n"
            .encode("utf-16-le"))
    got, warnings = sniff_encoding(data)
    assert got == "utf-16-le"
    assert any("byte-order mark" in w for w in warnings)


def test_sniff_encoding_falls_back_to_cp1252_then_latin1():
    # 0x93/0x94 are curly quotes in cp1252 and invalid UTF-8.
    got, warnings = sniff_encoding(b"TI  - \x93quoted title\x94\n")
    assert got == "cp1252"
    assert any("cp1252" in w for w in warnings)
    # 0x81 is undefined in cp1252 -> latin-1.
    got2, warnings2 = sniff_encoding(b"TI  - \x81\x8d undefined\n")
    assert got2 == "latin-1"
    assert any("latin-1" in w for w in warnings2)


def test_sniff_encoding_prefers_utf8_when_valid():
    assert sniff_encoding("TI  - Żółć\n".encode("utf-8"))[0] == "utf-8"


def test_looks_binary_identifies_containers_and_passes_text():
    assert "PDF" in looks_binary(b"%PDF-1.7\ntrailer")
    assert "ZIP" in looks_binary(b"PK\x03\x04rest")
    assert looks_binary(b"TY  - JOUR\nTI  - Plain text\n") == ""
    assert looks_binary(b"") == ""
    assert looks_binary(b"\x01\x02\x03\x04\x05\x06\x07\x08" * 20) != ""


def test_looks_binary_does_not_flag_utf16_text():
    """UTF-16 is NUL-heavy by construction and must not be called binary."""
    from corpusslr.parsers._io import decode_export
    data = ("TY  - JOUR\nTI  - UTF-16 is text\nER  - \n"
            .encode("utf-16"))
    rep = ParseReport()
    text = decode_export(data, report=rep)
    assert "UTF-16 is text" in text
    assert rep.n_rejected == 0


# --------------------------------------------------------------------------
# ParseReport itself
# --------------------------------------------------------------------------

def test_parse_report_accounting_and_serialisation():
    rep = ParseReport(fmt="ris", dialect="embase")
    rep.saw(3)
    rep.accept(2)
    rep.reject(2, "no_content", "no title")
    rep.warn("something odd")
    assert rep.balanced
    assert rep.n_rejected == 1
    assert rep.reason_counts() == {"no_content": 1}
    payload = rep.to_dict()
    assert payload["n_input"] == 3 and payload["n_accepted"] == 2
    assert payload["balanced"] is True
    assert "2 record(s) parsed" in rep.summary()
    assert "embase" in rep.summary()


def test_parse_report_detects_an_imbalance():
    rep = ParseReport()
    rep.saw(5)
    rep.accept(3)          # 2 lost, none rejected
    assert rep.balanced is False


def test_parsers_work_without_a_report_argument():
    """The report is opt-in; omitting it must not change behaviour."""
    for _label, parse, _pf, sample, expected in FORMATS:
        assert len(parse(sample)) == expected


# --------------------------------------------------------------------------
# CSV recovery branches
# --------------------------------------------------------------------------

def test_csv_rows_with_no_usable_header_are_rejected():
    from corpusslr.parsers import parse_csv_rows
    rep = ParseReport()
    recs = parse_csv_rows([["", "", ""], ["a", "b", "c"]], report=rep)
    assert recs == []
    assert rep.reason_counts() == {"malformed": 2}
    assert rep.balanced


def test_csv_rows_empty_grid_returns_nothing():
    from corpusslr.parsers import parse_csv_rows
    assert parse_csv_rows([]) == []
    assert parse_csv_rows([None]) == []


def test_csv_rows_short_row_is_padded_not_shifted():
    """A truncated final row must not shift its cells into other columns."""
    from corpusslr.parsers import parse_csv_rows
    rows = [["Title", "Authors", "Year", "DOI"],
            ["Full record", "Smith, J", "2024", "10.5001/a"],
            ["Truncated record", "Doe, A"]]
    recs = parse_csv_rows(rows)
    assert [r.title for r in recs] == ["Full record", "Truncated record"]
    assert recs[1].year is None and recs[1].doi == ""


def test_csv_row_with_an_unbalanced_quote_does_not_discard_the_file():
    """One malformed row must not cost the rows that follow it."""
    text = ('Title,Authors,Year,DOI\n'
            '"Good record one","Smith, J",2024,10.5001/a\n'
            '"unbalanced ,quote,2023,10.5001/b\n'
            '"Good record two","Doe, A",2022,10.5001/c\n')
    rep = ParseReport()
    recs = parse_csv_export(text, report=rep)
    assert "Good record one" in [r.title for r in recs]
    assert rep.balanced


def test_csv_empty_row_object_is_counted():
    from corpusslr.parsers.csv_exports import _rows_to_records
    rep = ParseReport()
    recs = _rows_to_records([{}, {"Title": "Kept"}],
                            {"title": "Title"}, "generic", "", rep)
    assert [r.title for r in recs] == ["Kept"]
    assert rep.reason_counts() == {"empty": 1}
    assert rep.balanced


def test_open_access_column_false_values():
    from corpusslr.parsers.csv_exports import _open_access
    assert _open_access("Gold") is True
    assert _open_access("closed") is False
    assert _open_access("subscription") is False
    assert _open_access("") is None
    assert _open_access("maybe") is None


def test_csv_field_limit_is_restored_after_the_parse():
    """The CSV field limit is process-global state, so it must be restored."""
    import csv as _csv
    before = _csv.field_size_limit()
    parse_csv_export(CSV_SCOPUS.replace("2021", "2021" + "z" * 200000, 1))
    assert _csv.field_size_limit() == before



# --------------------------------------------------------------------------
# Forcing a format the file is not. MEDLINE and RIS share the ``XX  - value``
# tag shape, so parse_nbib() on a RIS export used to return records carrying a
# title and no identifier: an import that looks successful, keeps the PRISMA
# count right, and then silently fails to deduplicate.
# --------------------------------------------------------------------------
_RIS_EXPORT = ("TY  - JOUR\nTI  - Artificial intelligence adoption in firms\n"
               "AU  - Kowalski, Jan\nPY  - 2024\nDO  - 10.1016/j.x\nER  - \n")

_NBIB_EXPORT = ("PMID- 33333333\nTI  - Machine learning for glycaemic control\n"
                "PT  - Journal Article\nLID - 10.1007/s00125-020-05100-z [doi]\n"
                "FAU - Kowalski, Jan\nJT  - Diabetologia\nDP  - 2020\n")


def test_ris_parsed_as_nbib_is_refused_when_the_format_was_requested():
    """A caller who names the format gets an error, not a stripped record."""
    from corpusslr import ParseFormatMismatch, parse_nbib
    with pytest.raises(ParseFormatMismatch) as exc:
        parse_nbib(_RIS_EXPORT, strict_format=True)
    assert "RIS" in str(exc.value)
    assert "parse_ris" in str(exc.value)


def test_the_tolerant_default_keeps_the_no_raise_contract():
    """Robustness contract wins by default: damaged input never raises."""
    from corpusslr import ParseReport, parse_nbib
    rep = ParseReport()
    recs = parse_nbib(_RIS_EXPORT, report=rep)
    assert isinstance(recs, list)
    assert rep.n_input == len(recs) + rep.n_rejected


def test_naming_a_file_as_nbib_is_strict_by_default(tmp_path):
    from corpusslr import ParseFormatMismatch, parse_nbib_file
    p = tmp_path / "actually_ris.nbib"
    p.write_text(_RIS_EXPORT, encoding="utf-8")
    with pytest.raises(ParseFormatMismatch):
        parse_nbib_file(str(p))
    assert isinstance(parse_nbib_file(str(p), strict_format=False), list)


def test_a_real_nbib_export_still_parses_with_its_identifiers():
    from corpusslr import parse_nbib
    recs = parse_nbib(_NBIB_EXPORT)
    assert len(recs) == 1
    assert recs[0].doi == "10.1007/s00125-020-05100-z"
    assert recs[0].pmid == "33333333"


def test_the_marker_check_does_not_fire_on_er_inside_a_field():
    """'ER stress' in an abstract is not a RIS record terminator."""
    from corpusslr import parse_nbib
    recs = parse_nbib(_NBIB_EXPORT + "AB  - We compared ER stress markers.\n")
    assert len(recs) == 1
    assert recs[0].pmid == "33333333"


def test_the_defect_this_guards_would_have_produced_identifierless_records():
    """Documents the failure mode: title present, every identifier lost."""
    from corpusslr import parse_nbib
    recs = parse_nbib(_RIS_EXPORT)           # tolerant path, as before the fix
    assert recs, "the tolerant path still returns something"
    assert all(r.title for r in recs), "the title survives"
    assert not any(r.doi or r.pmid for r in recs), (
        "this is the defect: RIS spells the identifier DO, MEDLINE reads "
        "LID/AID, so every identifier is lost while the import looks fine")
