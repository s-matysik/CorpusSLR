"""Scopus-format CSV export: round trip through the package's own parser.

The strongest available evidence that ``to_scopus_csv`` writes the format it
claims is that :func:`corpusslr.parse_csv_export` -- which was written to read
*real* Scopus downloads, independently of the exporter -- reads the file back
with its Scopus dialect auto-detected and reconstructs the identifying fields
unchanged.  Every test here is offline.
"""
import csv
import io
import os

import pytest

from corpusslr import (Record, SCOPUS_COLUMNS, deduplicate, detect_csv_dialect,
                       parse_csv_export, to_scopus_csv)
from corpusslr.export import (SURROGATE_EID_PREFIX, _SCOPUS_DOC_TYPE,
                              _split_pages, _surrogate_eid)
from corpusslr.parsers._util import (map_doc_type, normalize_author_name,
                                     split_authors)
from corpusslr.record import surname
from corpusslr.parsers.csv_exports import (
    _SURROGATE_EID_PREFIX as _PARSER_SURROGATE_PREFIX)

# Header row of a real Scopus CSV download (46 columns), transcribed here so
# the test fails if SCOPUS_COLUMNS ever drifts from the vendor layout rather
# than merely from itself.
REAL_SCOPUS_HEADER = (
    "Authors,Author full names,Author(s) ID,Title,Year,Source title,Volume,"
    "Issue,Art. No.,Page start,Page end,Page count,Cited by,DOI,Link,"
    "Affiliations,Authors with affiliations,Abstract,Author Keywords,"
    "Index Keywords,Molecular Sequence Numbers,Chemicals/CAS,Tradenames,"
    "Manufacturers,Funding Details,Funding Texts,References,"
    "Correspondence Address,Editors,Publisher,Sponsors,Conference name,"
    "Conference date,Conference location,Conference code,ISSN,ISBN,CODEN,"
    "PubMed ID,Language of Original Document,Abbreviated Source Title,"
    "Document Type,Publication Stage,Open Access,Source,EID")

#: Columns bibliometrix's ``convert2df(dbsource = "scopus")`` requires, and
#: the columns it needs for the analyses reviewers actually run
#: (co-word from keywords, citation counts, document types).
BIBLIOMETRIX_REQUIRED = ("Authors", "Title", "Year", "Source title", "DOI")
BIBLIOMETRIX_ANALYTIC = ("Author Keywords", "Index Keywords", "Abstract",
                         "Affiliations", "Cited by", "Document Type", "EID")
#: VOSviewer's Scopus reader: co-authorship, co-word and citation maps.
VOSVIEWER_REQUIRED = ("Authors", "Title", "Year", "Source title", "Cited by",
                      "Author Keywords", "Index Keywords", "Abstract", "EID",
                      "DOI", "Document Type", "Affiliations", "References")


def _rich() -> Record:
    return Record(
        title="Machine learning, \"deep\" nets and AI: a review",
        abstract="We examine adoption; drivers, barriers.",
        authors=["Kowalski, Jan", "Nowak, Anna", "Wrobel, Lukasz"],
        year=2024, journal="Journal of Business Research",
        doi="10.1016/j.jbusres.2024.001", pmid="38123456",
        scopus_id="2-s2.0-85123456789", issn="01482963", volume="170",
        issue="3", pages="114-128", doc_type="review", language="english",
        keywords=["artificial intelligence", "SME"],
        url="https://www.scopus.com/x", open_access=True, cited_by=12,
        source="Scopus", uid="u1")


def _minimal() -> Record:
    """One author, no DOI, no year -- the sparse end of a real corpus."""
    return Record(title="A single-author note", authors=["Smith, John"],
                  journal="Technovation", uid="u2")


def _write(records, tmp_path, name="corpus_scopus.csv"):
    path = str(tmp_path / name)
    assert to_scopus_csv(records, path) == path
    with open(path, encoding="utf-8") as fh:
        return path, fh.read()


# ---------------------------------------------------------------------------
# the column contract
# ---------------------------------------------------------------------------

def test_column_list_matches_a_real_scopus_header_exactly():
    """Name and order both, against a transcribed vendor header row."""
    assert list(SCOPUS_COLUMNS) == next(csv.reader([REAL_SCOPUS_HEADER]))
    assert len(SCOPUS_COLUMNS) == 46


def test_header_row_written_is_the_column_list(tmp_path):
    _, text = _write([_rich()], tmp_path)
    header = next(csv.reader(io.StringIO(text)))
    assert header == list(SCOPUS_COLUMNS)


@pytest.mark.parametrize("column", BIBLIOMETRIX_REQUIRED)
def test_every_bibliometrix_mandatory_column_is_present(column, tmp_path):
    _, text = _write([_rich()], tmp_path)
    assert column in next(csv.reader(io.StringIO(text)))


@pytest.mark.parametrize("column",
                         BIBLIOMETRIX_ANALYTIC + VOSVIEWER_REQUIRED)
def test_every_analytic_column_is_present(column, tmp_path):
    _, text = _write([_rich()], tmp_path)
    assert column in next(csv.reader(io.StringIO(text)))


def test_written_file_is_recognised_as_scopus_by_the_dialect_detector(
        tmp_path):
    """The exporter and the reader agree without being told the vendor."""
    _, text = _write([_rich()], tmp_path)
    assert detect_csv_dialect(text.splitlines()[0]) == "scopus"


def test_dialect_is_detected_from_the_header_alone_not_the_data(tmp_path):
    _, text = _write([], tmp_path)
    assert detect_csv_dialect(text.splitlines()[0]) == "scopus"
    assert parse_csv_export(text) == []


# ---------------------------------------------------------------------------
# round trip
# ---------------------------------------------------------------------------

def test_round_trip_preserves_every_identifying_field(tmp_path):
    original = _rich()
    _, text = _write([original], tmp_path)
    back = parse_csv_export(text)          # dialect auto-detected
    assert len(back) == 1
    r = back[0]
    assert r.title == original.title
    assert r.authors == original.authors
    assert r.year == original.year
    assert r.journal == original.journal
    assert r.doi == original.doi
    assert r.abstract == original.abstract
    assert r.volume == original.volume
    assert r.issue == original.issue
    assert r.pages == original.pages
    assert r.issn == original.issn
    assert r.keywords == original.keywords
    assert r.doc_type == original.doc_type
    assert r.language == original.language
    assert r.cited_by == original.cited_by
    assert r.pmid == original.pmid
    assert r.scopus_id == original.scopus_id
    assert r.url == original.url
    assert r.open_access is True


def test_round_trip_of_a_title_with_a_comma_and_a_quote(tmp_path):
    """csv.writer quoting, checked through the reader rather than by eye."""
    rec = Record(title='Trust, "explainability", and AI: a study',
                 authors=["Doe, Jane"], year=2022, journal="AI & Society",
                 doi="10.5001/x")
    _, text = _write([rec], tmp_path)
    back = parse_csv_export(text)
    assert len(back) == 1
    assert back[0].title == 'Trust, "explainability", and AI: a study'
    assert back[0].journal == "AI & Society"


def test_round_trip_of_a_single_author_record(tmp_path):
    """One author must not be re-split by the comma in "Family, Given"."""
    rec = Record(title="A single-author note", authors=["Smith, John"],
                 year=2021, journal="Technovation", doi="10.5001/solo")
    _, text = _write([rec], tmp_path)
    back = parse_csv_export(text)
    assert back[0].authors == ["Smith, John"]


def test_round_trip_of_a_record_without_a_doi(tmp_path):
    rec = _minimal()
    _, text = _write([rec], tmp_path)
    back = parse_csv_export(text)
    assert len(back) == 1
    assert back[0].doi == ""
    assert back[0].title == rec.title
    assert back[0].year is None


def test_round_trip_of_a_multi_record_corpus_keeps_order_and_count(tmp_path):
    records = [_rich(), _minimal(),
               Record(title="Third paper", authors=["Ng, Andrew"], year=2020,
                      journal="Nature", doi="10.1038/x")]
    _, text = _write(records, tmp_path)
    back = parse_csv_export(text)
    assert [r.title for r in back] == [r.title for r in records]


@pytest.mark.parametrize("doc_type", sorted(_SCOPUS_DOC_TYPE))
def test_every_document_type_label_maps_back_onto_itself(doc_type, tmp_path):
    """The Scopus labels chosen must survive map_doc_type unchanged."""
    assert map_doc_type(_SCOPUS_DOC_TYPE[doc_type]) == doc_type
    _, text = _write([Record(title="T", doi="10.5001/{}".format(doc_type),
                             doc_type=doc_type)], tmp_path)
    assert parse_csv_export(text)[0].doc_type == doc_type


@pytest.mark.parametrize("pages,expected", [
    ("114-128", ("114", "128")),
    ("1", ("1", "")),
    ("", ("", "")),
    ("e0123456", ("e0123456", "")),
    ("S12-S18", ("S12", "S18")),
    ("1-2-3", ("1-2-3", "")),
])
def test_page_range_is_split_into_the_two_scopus_columns(pages, expected):
    assert _split_pages(pages) == expected


@pytest.mark.parametrize("pages", ["114-128", "1", "e0123456", "S12-S18"])
def test_page_range_round_trips(pages, tmp_path):
    _, text = _write([Record(title="T", doi="10.5001/p", pages=pages)], tmp_path)
    assert parse_csv_export(text)[0].pages == pages


# ---------------------------------------------------------------------------
# never invent data
# ---------------------------------------------------------------------------

def test_columns_with_no_counterpart_in_the_record_are_left_empty(tmp_path):
    """Affiliations, references and funding are not synthesised."""
    path, text = _write([_rich()], tmp_path)
    with open(path, encoding="utf-8", newline="") as fh:
        row = next(csv.DictReader(fh))
    for column in ("Affiliations", "Authors with affiliations", "References",
                   "Funding Details", "Funding Texts", "Correspondence "
                   "Address", "Editors", "Publisher", "Sponsors",
                   "Conference name", "Conference date", "Conference "
                   "location", "Conference code", "ISBN", "CODEN",
                   "Art. No.", "Page count", "Publication Stage",
                   "Molecular Sequence Numbers", "Chemicals/CAS",
                   "Tradenames", "Manufacturers", "Author(s) ID",
                   "Abbreviated Source Title", "Index Keywords"):
        assert row[column] == "", column


def test_a_sparse_record_yields_empty_cells_not_placeholders(tmp_path):
    path, _ = _write([_minimal()], tmp_path)
    with open(path, encoding="utf-8", newline="") as fh:
        row = next(csv.DictReader(fh))
    assert row["Title"] == "A single-author note"
    for column in ("Year", "DOI", "Abstract", "Cited by", "ISSN", "Volume",
                   "Issue", "Page start", "Page end", "Author Keywords",
                   "Document Type", "Open Access", "PubMed ID",
                   "Language of Original Document", "Link"):
        assert row[column] == "", column
    # EID is the one column that is deliberately never empty: bibliometrix
    # deduplicates a Scopus CSV on it.  It carries a derived surrogate, not
    # invented Scopus metadata.
    assert row["EID"].startswith(SURROGATE_EID_PREFIX)
    assert all(v == "" or v is None
               for k, v in row.items()
               if k not in ("Title", "Authors", "Author full names",
                            "Source title", "Source", "EID"))


def test_missing_year_is_empty_not_zero(tmp_path):
    path, _ = _write([Record(title="No year", doi="10.5001/ny")], tmp_path)
    with open(path, encoding="utf-8", newline="") as fh:
        assert next(csv.DictReader(fh))["Year"] == ""


def test_missing_citation_count_is_empty_not_zero(tmp_path):
    """cited_by=None means unknown; writing 0 would assert "never cited"."""
    path, _ = _write([Record(title="T", doi="10.5001/c", cited_by=None)],
                     tmp_path)
    with open(path, encoding="utf-8", newline="") as fh:
        assert next(csv.DictReader(fh))["Cited by"] == ""
    path2, _ = _write([Record(title="T", doi="10.5001/c", cited_by=0)],
                      tmp_path, name="zero.csv")
    with open(path2, encoding="utf-8", newline="") as fh:
        assert next(csv.DictReader(fh))["Cited by"] == "0"


def test_closed_access_is_empty_because_scopus_only_marks_open(tmp_path):
    path, _ = _write([Record(title="T", doi="10.5001/oa", open_access=False)],
                     tmp_path)
    with open(path, encoding="utf-8", newline="") as fh:
        assert next(csv.DictReader(fh))["Open Access"] == ""


def test_open_access_marker_round_trips_as_true(tmp_path):
    _, text = _write([Record(title="T", doi="10.5001/oa2", open_access=True)],
                     tmp_path)
    assert parse_csv_export(text)[0].open_access is True


def test_an_unknown_doc_type_is_passed_through_not_guessed(tmp_path):
    path, _ = _write([Record(title="T", doi="10.5001/d", doc_type="dataset")],
                     tmp_path)
    with open(path, encoding="utf-8", newline="") as fh:
        assert next(csv.DictReader(fh))["Document Type"] == "dataset"


# ---------------------------------------------------------------------------
# the EID column: bibliometrix deduplicates on it
# ---------------------------------------------------------------------------
# convert2df(dbsource = "scopus", format = "csv") sets id_field <- "UT" (fed
# from EID) and drops every row whose value repeats.  An empty EID is a value
# like any other, so a corpus from sources that assign no Scopus identifier
# would collapse to one record.  Measured before the surrogate existed: 20
# distinct records -> "Removed 19 duplicated documents" -> 1 row.

def _no_id_corpus(n=20):
    """n records with distinct titles and DOIs but no Scopus identifier."""
    return [Record(title="Distinct paper number {}".format(i),
                   authors=["Author{}, A".format(i)], year=2000 + i,
                   journal="Journal {}".format(i),
                   doi="10.1234/paper.{}".format(i), doc_type="article")
            for i in range(1, n + 1)]


def test_every_eid_is_unique_when_no_record_has_a_scopus_id(tmp_path):
    records = _no_id_corpus()
    assert all(r.scopus_id == "" for r in records)
    path, _ = _write(records, tmp_path)
    with open(path, encoding="utf-8", newline="") as fh:
        eids = [row["EID"] for row in csv.DictReader(fh)]
    assert len(eids) == 20
    assert all(eids)
    assert len(set(eids)) == 20


def test_the_eid_column_is_never_empty(tmp_path):
    """Even a record with no identifier and no title text gets a key."""
    path, _ = _write([Record(title="", doi="10.1234/only-a-doi"),
                      Record(title="Only a title"),
                      Record(title="", doi="", pmid="123456")], tmp_path)
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    # the record with neither title nor DOI is dropped by the reader, but
    # every row that IS written carries a key
    assert rows
    assert all(row["EID"] for row in rows)


def test_a_real_scopus_id_is_used_verbatim_not_replaced(tmp_path):
    path, _ = _write([_rich()], tmp_path)
    with open(path, encoding="utf-8", newline="") as fh:
        assert next(csv.DictReader(fh))["EID"] == "2-s2.0-85123456789"


def test_the_surrogate_cannot_be_mistaken_for_a_scopus_eid(tmp_path):
    """It must not look like 2-s2.0-<digits>; fabricating one is the sin."""
    path, _ = _write(_no_id_corpus(3), tmp_path)
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            assert row["EID"].startswith(SURROGATE_EID_PREFIX)
            assert not row["EID"].startswith("2-s2.0-")


def test_the_surrogate_is_not_read_back_as_a_scopus_identifier(tmp_path):
    """A shared scopus_id is strong dedup evidence; a surrogate is not one."""
    _, text = _write(_no_id_corpus(3), tmp_path)
    back = parse_csv_export(text)
    assert len(back) == 3
    assert all(r.scopus_id == "" for r in back)
    # it survives as the record id, so provenance is not lost
    assert all(r.source_id.startswith(SURROGATE_EID_PREFIX) for r in back)


def test_the_two_declarations_of_the_surrogate_prefix_agree():
    """The parser copies the constant; the copy must not drift."""
    assert _PARSER_SURROGATE_PREFIX == SURROGATE_EID_PREFIX


def test_the_surrogate_is_stable_across_two_independent_exports(tmp_path):
    """Same work, two corpora: the key must match so a re-import merges."""
    rec = Record(title="A paper", authors=["A, B"], year=2020,
                 doi="10.1234/stable", uid="R000001")
    twin = Record(title="A paper", authors=["A, B"], year=2020,
                  doi="10.1234/stable", uid="R000999")   # different uid
    p1, _ = _write([rec], tmp_path, name="a.csv")
    p2, _ = _write([twin], tmp_path, name="b.csv")
    keys = []
    for p in (p1, p2):
        with open(p, encoding="utf-8", newline="") as fh:
            keys.append(next(csv.DictReader(fh))["EID"])
    assert keys[0] == keys[1]


def test_two_different_works_never_share_a_surrogate(tmp_path):
    """Without a DOI the key falls back to title+year, which must separate."""
    records = [Record(title="First work", year=2020),
               Record(title="Second work", year=2020),
               Record(title="First work", year=2021)]
    path, _ = _write(records, tmp_path)
    with open(path, encoding="utf-8", newline="") as fh:
        eids = [row["EID"] for row in csv.DictReader(fh)]
    assert len(set(eids)) == 3


def test_the_surrogate_is_derived_not_taken_from_the_corpus_local_uid(
        tmp_path):
    """uid is sequential per corpus, so it would collide across corpora."""
    rec = Record(title="A paper", year=2020, doi="10.1234/derived",
                 uid="R000001")
    path, _ = _write([rec], tmp_path)
    with open(path, encoding="utf-8", newline="") as fh:
        eid = next(csv.DictReader(fh))["EID"]
    assert "R000001" not in eid
    assert eid == SURROGATE_EID_PREFIX + "10.1234/derived"


@pytest.mark.parametrize("record,expected", [
    (Record(title="T", doi="10.1234/abc"), "corpusslr:10.1234/abc"),
    (Record(title="T", pmid="38123456"), "corpusslr:pmid:38123456"),
    (Record(title="T", source_id="WOS:000123"), "corpusslr:srcid:WOS:000123"),
])
def test_surrogate_prefers_the_strongest_identifier_available(record,
                                                              expected):
    assert _surrogate_eid(record) == expected


def test_surrogate_falls_back_to_a_title_year_digest():
    key = _surrogate_eid(Record(title="No identifiers here", year=2020))
    assert key.startswith(SURROGATE_EID_PREFIX + "sha1:")
    assert len(key.split(":")[-1]) == 16


def test_negative_control_an_empty_eid_column_collapses_the_corpus(tmp_path):
    """The control that makes the EID tests mean something.

    Reproduce the bug deliberately -- blank the EID column of a correct
    export -- and confirm that deduplicating on that column, which is exactly
    what convert2df does, destroys the corpus.  If this assertion ever fails,
    the surrogate has stopped being necessary and the tests above are no
    longer testing anything.
    """
    records = _no_id_corpus()
    path, _ = _write(records, tmp_path)
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    i_eid = rows[0].index("EID")
    # correct export: bibliometrix's rule keeps every record
    keys = [r[i_eid] for r in rows[1:]]
    assert len(set(keys)) == len(rows) - 1 == 20
    # injured export: EID blanked, as it was before the surrogate
    for r in rows[1:]:
        r[i_eid] = ""
    injured = [r[i_eid] for r in rows[1:]]
    assert len(set(injured)) == 1          # 20 records -> 1 survivor
    assert len(injured) - len(set(injured)) == 19


# ---------------------------------------------------------------------------
# author-name idempotency: the bug this round trip discovered
# ---------------------------------------------------------------------------
# A round trip re-normalises every author name.  normalize_author_name was not
# a fixed point on a name whose comma separates a SUFFIX rather than family
# from given ("Lynch J.G., Jr." -- Scopus and Embase both write this), so the
# second pass produced a different string and, worse, surname() read the
# initials instead of the family name.  Measured on a real 14 302-record
# Scopus export: 31 records affected, 10 in first-author position.

@pytest.mark.parametrize("name", [
    "Lynch J.G., Jr.", "Gutsche R.E., Jr.", "Rose R.L.", "Kowalski, Jan",
    "Kowalski J.", "Jan Kowalski", "Ludwig van Beethoven",
    "van Beethoven, Ludwig", "Smith, John, III", "King, Martin Luther, Jr.",
    "Smith, Jr.", "Doe", "Netemeyer R.G.",
])
def test_author_normalisation_is_a_fixed_point(name):
    once = normalize_author_name(name)
    assert normalize_author_name(once) == once


@pytest.mark.parametrize("name,expected", [
    ("Lynch J.G., Jr.", "lynch"),
    ("Gutsche R.E., Jr.", "gutsche"),
    ("King, Martin Luther, Jr.", "king"),
    ("Rose R.L.", "rose"),
])
def test_a_suffixed_name_yields_the_family_name_not_the_initials(name,
                                                                 expected):
    """surname() feeds the duplicate cascade's first-author agreement test."""
    assert surname(normalize_author_name(name)) == expected


def test_a_suffixed_author_round_trips_through_the_scopus_export(tmp_path):
    rec = Record(title="Consumer trust", doi="10.1234/suffix",
                 authors=split_authors("Netemeyer R.G.; Lynch J.G., Jr."))
    _, text = _write([rec], tmp_path)
    back = parse_csv_export(text)
    assert back[0].authors == rec.authors
    assert back[0].first_author_surname == rec.first_author_surname


def test_negative_control_a_non_idempotent_normaliser_is_detected(tmp_path):
    """The control for the two tests above.

    Simulate the old behaviour -- return the family part unchanged when the
    suffix consumed the given name -- and confirm that the fixed-point and
    surname assertions actually fail on it.  A passing idempotency test proves
    nothing unless it can fail.
    """
    def old_normalise(name):
        """The pre-fix code path, reproduced for the control."""
        parts = [p.strip() for p in name.split(",") if p.strip()]
        family = parts[0]
        given = [p for p in parts[1:]
                 if p.lower().rstrip(".") not in ("jr", "sr", "iii")]
        return "{}, {}".format(family, " ".join(given)) if given else family

    injured = old_normalise("Lynch J.G., Jr.")
    assert injured == "Lynch J.G."
    # not a fixed point: the assertion that now passes would have failed
    assert normalize_author_name(injured) != injured
    # and the surname was the initials, not the family name
    assert surname(injured) == "j g"
    assert surname(normalize_author_name(injured)) == "lynch"


# ---------------------------------------------------------------------------
# spreadsheet-formula neutralisation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lead", ["=", "+", "-", "@"])
def test_formula_leading_characters_are_neutralised(lead, tmp_path):
    title = lead + "cmd|' /C calc'!A0"
    path, _ = _write([Record(title=title, doi="10.5001/f")], tmp_path)
    with open(path, encoding="utf-8", newline="") as fh:
        cell = next(csv.DictReader(fh))["Title"]
    assert cell == "'" + title
    assert not cell.startswith(lead)


def test_neutralisation_covers_the_author_and_keyword_cells(tmp_path):
    rec = Record(title="T", doi="10.5001/n", authors=["=SUM(A1)"],
                 keywords=["@risk"], journal="-Journal")
    path, _ = _write([rec], tmp_path)
    with open(path, encoding="utf-8", newline="") as fh:
        row = next(csv.DictReader(fh))
    assert row["Authors"].startswith("'=")
    assert row["Author Keywords"].startswith("'@")
    assert row["Source title"].startswith("'-")


# ---------------------------------------------------------------------------
# negative controls: the round-trip check must fail on a broken export
# ---------------------------------------------------------------------------

def test_round_trip_check_detects_a_dropped_column(tmp_path):
    """A column removed from the header must be caught, not tolerated."""
    original = _rich()
    _, text = _write([original], tmp_path)
    rows = list(csv.reader(io.StringIO(text)))
    keep = [i for i, c in enumerate(rows[0]) if c != "DOI"]
    broken = io.StringIO()
    csv.writer(broken).writerows([[r[i] for i in keep] for r in rows])
    injured = parse_csv_export(broken.getvalue(), dialect="scopus")
    assert injured[0].doi != original.doi
    assert injured[0].doi == ""


def test_round_trip_check_detects_a_renamed_column(tmp_path):
    """Rename "Source title" and the venue is lost -- the check must see it."""
    original = _rich()
    _, text = _write([original], tmp_path)
    broken = text.replace("Source title", "Journal Name Xyz", 1)
    injured = parse_csv_export(broken, dialect="scopus")
    assert injured[0].journal != original.journal
    assert injured[0].journal == ""


def test_round_trip_check_detects_swapped_columns(tmp_path):
    """Swap two data cells and the identity assertions must fail."""
    original = _rich()
    _, text = _write([original], tmp_path)
    rows = list(csv.reader(io.StringIO(text)))
    i_title = rows[0].index("Title")
    i_journal = rows[0].index("Source title")
    rows[1][i_title], rows[1][i_journal] = (rows[1][i_journal],
                                            rows[1][i_title])
    broken = io.StringIO()
    csv.writer(broken).writerows(rows)
    injured = parse_csv_export(broken.getvalue(), dialect="scopus")
    assert injured[0].title == original.journal
    assert injured[0].journal == original.title
    assert injured[0].title != original.title


def test_round_trip_check_detects_an_unquoted_comma(tmp_path):
    """Writing the title raw instead of quoted shifts every later column."""
    original = _rich()
    _, text = _write([original], tmp_path)
    broken = text.replace('"{}"'.format(original.title.replace('"', '""')),
                          original.title.replace('"', ""), 1)
    assert broken != text
    injured = parse_csv_export(broken, dialect="scopus")
    assert injured[0].title != original.title


# ---------------------------------------------------------------------------
# file-level properties
# ---------------------------------------------------------------------------

def test_empty_corpus_writes_a_header_only_file(tmp_path):
    path, text = _write([], tmp_path)
    assert os.path.exists(path)
    assert text.splitlines() == [",".join(
        c if "," not in c else '"{}"'.format(c) for c in SCOPUS_COLUMNS)]


def test_every_row_has_exactly_46_cells(tmp_path):
    path, _ = _write([_rich(), _minimal()], tmp_path)
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.reader(fh):
            assert len(row) == 46


def test_file_is_utf8_and_preserves_diacritics(tmp_path):
    rec = Record(title="Wp\u0142yw sztucznej inteligencji",
                 authors=["Wr\u00f3bel, \u0141ukasz"], doi="10.5001/pl")
    path, _ = _write([rec], tmp_path)
    with open(path, "rb") as fh:
        raw = fh.read()
    assert "Wp\u0142yw".encode("utf-8") in raw
    assert not raw.startswith(b"\xef\xbb\xbf")   # no BOM, plain UTF-8
    with open(path, encoding="utf-8") as fh:
        back = parse_csv_export(fh.read())
    assert back[0].title == rec.title
    assert back[0].authors == rec.authors


# --------------------------------------------------------------------------
# Affiliations.
#
# bibliometrix reads C1 from the "Affiliations" column and derives AU_UN, the
# institutional collaboration network, from it. Web of Science Expanded and
# Scopus both return addresses, so leaving the column empty costs the reviewer
# a whole analysis while the export still looks complete. Verified end to end:
# with the column populated, bibliometrix built a 156 x 156 institution network
# from 60 affiliated records; with it empty the same call returned "Matrix is
# empty!!".
# --------------------------------------------------------------------------
def test_affiliations_reach_the_scopus_column(tmp_path):
    rec = Record(title="A study", authors=["Chen, Wei"], year=2024,
                 journal="J Test", doi="10.5001/aff",
                 affiliations=["Chengdu Univ Informat Sci & Technol, Chengdu, China",
                               "Univ Georgia, Athens, GA, USA"])
    path = str(tmp_path / "s.csv")
    to_scopus_csv([rec], path)
    with open(path, encoding="utf-8-sig") as fh:
        row = next(csv.DictReader(fh))
    assert row["Affiliations"] == (
        "Chengdu Univ Informat Sci & Technol, Chengdu, China; "
        "Univ Georgia, Athens, GA, USA")


def test_a_record_without_affiliations_leaves_the_column_empty(tmp_path):
    """Never invent an affiliation: an empty column is missing data, a
    fabricated one is a false finding in someone's collaboration analysis."""
    path = str(tmp_path / "s.csv")
    to_scopus_csv([Record(title="No address", year=2024, doi="10.5001/x")], path)
    with open(path, encoding="utf-8-sig") as fh:
        assert next(csv.DictReader(fh))["Affiliations"] == ""


def test_merging_two_copies_unions_their_affiliations():
    """One database may carry addresses the other omits; the surviving record
    should end up with both rather than whichever copy happened to win."""
    a = Record(title="Same work", year=2024, doi="10.5001/same",
               affiliations=["Univ A, City, Country"])
    b = Record(title="Same work", year=2024, doi="10.5001/same",
               affiliations=["Univ B, Town, Country"])
    merged = deduplicate([a, b]).records[0]
    assert set(merged.affiliations) == {"Univ A, City, Country",
                                        "Univ B, Town, Country"}
