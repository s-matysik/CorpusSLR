"""BibTeX parser: realistic vendor exports, LaTeX decoding, edge cases."""
import os

import pytest

from corpusslr import (Record, detect_bibtex_dialect, parse_bibtex,
                       parse_bibtex_file, to_bibtex)
from corpusslr.parsers.bibtex import _delatex

# --------------------------------------------------------------------------
# Fixtures modelled on real exports
# --------------------------------------------------------------------------

IEEE_BIB = r"""%% IEEE Xplore export -- 3 results
@ARTICLE{9876543,
  author={Kowalski, Jan and M{\"u}ller, Hans-J{\"o}rg and Wr{\'o}bel, {\L}ukasz},
  journal={IEEE Access},
  title={The {AI} Effect on {SME}s: A Survey---Part {II}},
  year={2024},
  volume={12},
  number={3},
  pages={114--128},
  keywords={Artificial intelligence;Small and medium enterprises;Surveys},
  doi={10.1109/ACCESS.2024.1234567},
  ISSN={2169-3536},
  abstract={We quantify the 50\% adoption gap \& its drivers.}}

@INPROCEEDINGS{8123456,
  author={Nguyen, Th{\d u}y and Andersson, {\AA}sa},
  booktitle={2022 IEEE International Conference on Big Data (Big Data)},
  title={Screening at scale},
  year={2022},
  pages={1--9},
  doi={10.1109/BigData.2022.9999999}}
"""

ACM_BIB = r"""@inproceedings{10.1145/3543873.3587537,
author = {Stra{\ss}er, J\"{o}rg and Novotn\'{y}, Petr},
title = {Retrieval Augmented Screening for Systematic Reviews},
year = {2023},
isbn = {9781450394192},
publisher = {Association for Computing Machinery},
address = {New York, NY, USA},
url = {https://doi.org/10.1145/3543873.3587537},
doi = {10.1145/3543873.3587537},
booktitle = {Companion Proceedings of the ACM Web Conference 2023},
pages = {1123--1131},
numpages = {9},
articleno = {117},
keywords = {systematic review, retrieval, screening},
location = {Austin, TX, USA},
series = {WWW '23 Companion}
}
"""

MIXED_BIB = r"""@string{jbr = "Journal of Business Research"}
@string{yr2020 = "2020"}

% a comment line that must be ignored: @article{ghost, title={Ghost}}
@comment{ @article{alsoghost, title = {Also ghost}} }

@phdthesis{nowak2022,
  author = "Anna Nowak",
  title  = "Adopcja sztucznej inteligencji w ma{\l}ych firmach",
  school = "Uniwersytet Warszawski",
  year   = 2022
}

@techreport{oecd2021,
  author = {{OECD}},
  title = {AI in business: a policy report},
  institution = {OECD},
  year = {2021}
}

@misc{lecun2024,
  author = {Yann LeCun and Yoshua Bengio},
  title = {Deep learning redux},
  eprint = {2401.00001},
  archivePrefix = {arXiv},
  year = {2024}
}

@book{handbook,
  title = jbr # " Handbook",
  author = {Smith, John and Doe, Jane},
  year = yr2020,
  publisher = {Elsevier}
}

@incollection{chap1,
  author = {van Beethoven, Ludwig},
  title = {A chapter},
  booktitle = {Big Book of Things},
  year = {2019},
  pages = {3--17}
}

@unpublished{wp1,
  author = {Garc{\'i}a, Mar{\'i}a},
  title = {Working paper on {LLM}s},
  year = {2025},
  note = {PMID: 39123456}
}
"""

SCOPUS_BIB = r"""@ARTICLE{2-s2.0-85123456789,
    author = {Kowalski, J. and Nowak, A.},
    title = {AI adoption in small firms},
    year = {2024},
    journal = {Journal of Business Research},
    volume = {170},
    pages = {114-128},
    doi = {10.1016/j.jbusres.2024.001},
    author_keywords = {artificial intelligence;  SME},
    note = {Cited by: 12},
    source = {Scopus}
}
"""


# --------------------------------------------------------------------------
# Dialect detection
# --------------------------------------------------------------------------

def test_detect_dialects():
    assert detect_bibtex_dialect(IEEE_BIB) == "ieee"
    assert detect_bibtex_dialect(ACM_BIB) == "acm"
    assert detect_bibtex_dialect(SCOPUS_BIB) == "scopus"
    # MIXED_BIB carries an archivePrefix={arXiv} entry
    assert detect_bibtex_dialect(MIXED_BIB) == "arxiv"
    assert detect_bibtex_dialect("@article{a, title={T}, year={2020}}") \
        == "generic"
    assert detect_bibtex_dialect("") == "generic"


# --------------------------------------------------------------------------
# IEEE
# --------------------------------------------------------------------------

def test_ieee_entry_fields_and_latex_names():
    recs = parse_bibtex(IEEE_BIB)
    assert len(recs) == 2
    r = recs[0]
    assert r.title == "The AI Effect on SMEs: A Survey\u2014Part II"
    assert r.authors == ["Kowalski, Jan", "M\u00fcller, Hans-J\u00f6rg",
                         "Wr\u00f3bel, \u0141ukasz"]
    assert r.journal == "IEEE Access"
    assert r.year == 2024 and r.volume == "12" and r.issue == "3"
    assert r.pages == "114-128"
    assert r.doi == "10.1109/access.2024.1234567"
    assert r.issn == "2169-3536"
    assert r.doc_type == "article"
    assert r.keywords == ["Artificial intelligence",
                          "Small and medium enterprises", "Surveys"]
    assert r.abstract == "We quantify the 50% adoption gap & its drivers."
    assert r.source_id == "9876543"
    assert r.raw["dialect"] == "ieee"


def test_ieee_inproceedings_becomes_conference():
    r = parse_bibtex(IEEE_BIB)[1]
    assert r.doc_type == "conference"
    assert r.journal.startswith("2022 IEEE International Conference")
    assert r.authors == ["Nguyen, Th\u1ee5y", "Andersson, \u00c5sa"]


def test_latex_surnames_normalize_for_dedup():
    """A LaTeX-escaped surname must reduce to the same key as the plain one.

    This is the property the duplicate cascade relies on: the same paper
    exported from IEEE (LaTeX escapes) and from Scopus (Unicode) has to
    yield one surname, not two.
    """
    from corpusslr.record import surname
    latex = parse_bibtex(
        r"@article{a, title={T}, author={Wr{\'o}bel, {\L}ukasz "
        r"and M{\"u}ller, J{\"o}rg}}")[0]
    plain = parse_bibtex(
        "@article{b, title={T}, author={Wr\u00f3bel, \u0141ukasz "
        "and M\u00fcller, J\u00f6rg}}")[0]
    assert latex.authors == plain.authors
    assert [surname(a) for a in latex.authors] == ["wrobel", "muller"]
    r = parse_bibtex(IEEE_BIB)[0]
    assert surname(r.authors[2]) == "wrobel"


# --------------------------------------------------------------------------
# ACM
# --------------------------------------------------------------------------

def test_acm_entry():
    recs = parse_bibtex(ACM_BIB)
    assert len(recs) == 1
    r = recs[0]
    assert r.doc_type == "conference"
    assert r.authors == ["Stra\u00dfer, J\u00f6rg", "Novotn\u00fd, Petr"]
    assert r.pages == "1123-1131"
    assert r.doi == "10.1145/3543873.3587537"
    assert r.journal.startswith("Companion Proceedings")
    assert r.keywords == ["systematic review", "retrieval", "screening"]
    assert r.raw["fields"]["numpages"] == "9"
    assert r.raw["fields"]["articleno"] == "117"


def test_articleno_used_when_no_page_range():
    text = ACM_BIB.replace("pages = {1123--1131},\n", "")
    r = parse_bibtex(text)[0]
    assert r.pages == "117"


# --------------------------------------------------------------------------
# Entry types, strings, comments
# --------------------------------------------------------------------------

def test_entry_type_mapping_and_comment_skipping():
    recs = parse_bibtex(MIXED_BIB)
    by_title = {r.title: r for r in recs}
    assert "Ghost" not in by_title and "Also ghost" not in by_title
    assert by_title["Adopcja sztucznej inteligencji w ma\u0142ych firmach"] \
        .doc_type == "thesis"
    assert by_title["AI in business: a policy report"].doc_type == "report"
    assert by_title["Deep learning redux"].doc_type == "preprint"
    assert by_title["A chapter"].doc_type == "chapter"
    assert by_title["Working paper on LLMs"].doc_type == "preprint"


def test_string_definitions_and_concatenation():
    recs = parse_bibtex(MIXED_BIB)
    book = [r for r in recs if r.doc_type == "book"][0]
    assert book.title == "Journal of Business Research Handbook"
    assert book.year == 2020
    assert book.authors == ["Smith, John", "Doe, Jane"]


def test_quoted_values_and_plain_name_order():
    recs = parse_bibtex(MIXED_BIB)
    thesis = [r for r in recs if r.doc_type == "thesis"][0]
    assert thesis.authors == ["Nowak, Anna"]
    lecun = [r for r in recs if r.title == "Deep learning redux"][0]
    assert lecun.authors == ["LeCun, Yann", "Bengio, Yoshua"]


def test_particle_surname_kept_together():
    r = [x for x in parse_bibtex(MIXED_BIB) if x.title == "A chapter"][0]
    assert r.authors == ["van Beethoven, Ludwig"]


def test_pmid_from_note():
    r = [x for x in parse_bibtex(MIXED_BIB)
         if x.title == "Working paper on LLMs"][0]
    assert r.pmid == "39123456"
    assert r.authors == ["Garc\u00eda, Mar\u00eda"]


def test_corporate_author_braced():
    r = [x for x in parse_bibtex(MIXED_BIB)
         if x.doc_type == "report"][0]
    assert r.authors == ["OECD"]


# --------------------------------------------------------------------------
# Scopus BibTeX
# --------------------------------------------------------------------------

def test_scopus_bibtex_cited_by_and_keywords():
    r = parse_bibtex(SCOPUS_BIB)[0]
    assert r.raw["dialect"] == "scopus"
    assert r.cited_by == 12
    assert r.keywords == ["artificial intelligence", "SME"]
    assert r.authors == ["Kowalski, J.", "Nowak, A."]
    assert r.pages == "114-128"


# --------------------------------------------------------------------------
# LaTeX decoding table
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    (r"Kowalsk{\'i}", "Kowalsk\u00ed"),
    (r"M{\"o}ller", "M\u00f6ller"),
    (r"Stra{\ss}e", "Stra\u00dfe"),
    (r"{\l}ukasiewicz", "\u0142ukasiewicz"),
    (r"{\L}ukasz", "\u0141ukasz"),
    (r"Bj{\o}rn", "Bj\u00f8rn"),
    (r"{\AA}sa", "\u00c5sa"),
    (r"Sm{\aa}", "Sm\u00e5"),
    (r"Fran\c{c}ois", "Fran\u00e7ois"),
    (r"Dvo\v{r}\'{a}k", "Dvo\u0159\u00e1k"),
    (r"Erd{\H o}s", "Erd\u0151s"),
    (r"L{\k a}ka", "L\u0105ka"),
    (r"Research \& Development", "Research & Development"),
    (r"50\% growth", "50% growth"),
    (r"pages 10--20", "pages 10\u201320"),
    (r"a---b", "a\u2014b"),
    (r"a \textendash{} b", "a \u2013 b"),
    (r"\emph{important} result", "important result"),
    (r"{The {AI} Effect}", "The AI Effect"),
    (r"$\alpha$-blockers", "\u03b1-blockers"),
    (r"C\c{s}", "C\u015f"),
    (r"\v{S}koda", "\u0160koda"),
    (r"", ""),
])
def test_delatex_table(raw, expected):
    assert _delatex(raw) == expected


def test_delatex_unknown_command_keeps_argument():
    assert _delatex(r"\somethingweird{kept text}") == "kept text"


# --------------------------------------------------------------------------
# Edge cases
# --------------------------------------------------------------------------

def test_empty_and_whitespace_input():
    assert parse_bibtex("") == []
    assert parse_bibtex("   \n\n ") == []
    assert parse_bibtex("no entries here at all") == []


def test_entry_without_title_or_doi_is_dropped():
    assert parse_bibtex("@article{x, year = {2020}}") == []


def test_unbalanced_braces_do_not_raise():
    recs = parse_bibtex("@article{trunc, title = {An unfinished title")
    assert len(recs) == 1
    assert recs[0].title == "An unfinished title"


def test_parenthesised_entry_body():
    recs = parse_bibtex("@article(par1, title = {Paren body}, year = {2001})")
    assert recs[0].title == "Paren body" and recs[0].year == 2001


def test_numeric_unquoted_values():
    r = parse_bibtex("@article{n, title={T}, year=1999, volume=7, pages=3}")[0]
    assert r.year == 1999 and r.volume == "7" and r.pages == "3"


def test_duplicate_field_names_are_kept_joined():
    r = parse_bibtex("@article{d, title={T}, keywords={a}, keywords={b}}")[0]
    assert r.keywords == ["a", "b"]


def test_doi_recovered_from_url_field():
    r = parse_bibtex(
        "@article{u, title={T}, url={https://doi.org/10.1234/abc.def}}")[0]
    assert r.doi == "10.1234/abc.def"


def test_url_without_doi_domain_does_not_yield_doi():
    r = parse_bibtex(
        "@article{u2, title={T}, url={https://example.org/10.1234/x}}")[0]
    assert r.doi == ""


def test_bom_and_crlf():
    text = "\ufeff@article{b,\r\n title = {BOM title},\r\n year = {2020}\r\n}\r\n"
    r = parse_bibtex(text)[0]
    assert r.title == "BOM title" and r.year == 2020


def test_percent_comment_inside_entry_is_skipped():
    text = "@article{c,\n  % stray comment\n  title = {Real title},\n" \
           "  year = {2020}\n}"
    r = parse_bibtex(text)[0]
    assert r.title == "Real title"


def test_source_name_override():
    recs = parse_bibtex(IEEE_BIB, source_name="IEEE Xplore")
    assert all(r.source == "IEEE Xplore" for r in recs)


def test_explicit_dialect_overrides_detection():
    r = parse_bibtex(IEEE_BIB, dialect="acm")[0]
    assert r.raw["dialect"] == "acm"


def test_parse_bibtex_file(tmp_path):
    p = tmp_path / "export.bib"
    p.write_text(IEEE_BIB, encoding="utf-8")
    recs = parse_bibtex_file(str(p))
    assert len(recs) == 2 and recs[0].year == 2024


def test_parse_bibtex_file_with_bom(tmp_path):
    p = tmp_path / "bom.bib"
    p.write_text("\ufeff" + ACM_BIB, encoding="utf-8")
    assert len(parse_bibtex_file(str(p))) == 1


def test_parse_bibtex_file_latin1_fallback(tmp_path):
    p = tmp_path / "latin1.bib"
    p.write_bytes("@article{l, title={Caf\u00e9 study}, year={2020}}"
                  .encode("latin-1"))
    recs = parse_bibtex_file(str(p))
    assert len(recs) == 1 and "study" in recs[0].title


# --------------------------------------------------------------------------
# Round trip with the exporter
# --------------------------------------------------------------------------

def test_roundtrip_export_then_parse(tmp_path):
    src = [
        Record(title="AI adoption in small firms", authors=["Kowalski, Jan",
                                                            "Nowak, Anna"],
               year=2024, journal="Journal of Business Research",
               doi="10.1016/j.jbusres.2024.001", volume="170",
               issue="3", pages="114-128", issn="0148-2963",
               abstract="Short abstract."),
        Record(title="Screening at scale", authors=["Nguyen, Thuy"],
               year=2022, doi="10.1109/bigdata.2022.9999999"),
    ]
    path = str(tmp_path / "out.bib")
    to_bibtex(src, path)
    back = parse_bibtex_file(path)
    assert len(back) == 2
    for orig, got in zip(src, back):
        assert got.title == orig.title
        assert got.authors == orig.authors
        assert got.year == orig.year
        assert got.doi == orig.doi
    assert back[0].journal == "Journal of Business Research"
    assert back[0].pages == "114-128"


@pytest.mark.parametrize("title", [
    "A 50% adoption gap", "The file_name convention", "Topic #1 in AI",
    "Approx ~5% growth", "x^2 scaling", "R&D spending",
    "The {AI} effect literally",
])
def test_roundtrip_special_characters(tmp_path, title):
    """Characters that are LaTeX-special must survive export -> re-import."""
    path = str(tmp_path / "sp.bib")
    to_bibtex([Record(title=title, year=2024, authors=["Smith, John"],
                      doi="10.5001/sp")], path)
    back = parse_bibtex_file(path)
    assert len(back) == 1 and back[0].title == title


def test_roundtrip_dollar_sign_in_title(tmp_path):
    title = "Cost in $US markets"
    path = str(tmp_path / "usd.bib")
    to_bibtex([Record(title=title, year=2024, doi="10.5001/usd")], path)
    assert parse_bibtex_file(path)[0].title == title


def test_roundtrip_backslash_in_title(tmp_path):
    title = "C:\\path\\to\\thing"
    path = str(tmp_path / "bs.bib")
    to_bibtex([Record(title=title, year=2024, doi="10.5001/bs")], path)
    assert parse_bibtex_file(path)[0].title == title


def test_roundtrip_nonascii_names(tmp_path):
    src = [Record(title="Uczenie maszynowe", year=2023,
                  authors=["Wr\u00f3bel, \u0141ukasz", "M\u00fcller, J\u00f6rg"],
                  doi="10.5001/pl")]
    path = str(tmp_path / "pl.bib")
    to_bibtex(src, path)
    back = parse_bibtex_file(path)
    assert back[0].authors == src[0].authors


def test_exported_file_is_utf8(tmp_path):
    path = str(tmp_path / "enc.bib")
    to_bibtex([Record(title="\u0141\u00f3d\u017a study", year=2020)], path)
    assert os.path.getsize(path) > 0
    with open(path, encoding="utf-8") as fh:
        assert "\u0141\u00f3d\u017a" in fh.read()


# --------------------------------------------------------------------------
# Entry-type fidelity (to_bibtex must not flatten every record to @article)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("doc_type,entry_type", [
    ("article", "@article"),
    ("review", "@article"),
    ("conference", "@inproceedings"),
    ("chapter", "@incollection"),
    ("book", "@book"),
    ("thesis", "@phdthesis"),
    ("report", "@techreport"),
    ("preprint", "@misc"),
])
def test_bibtex_entry_type_follows_doc_type(tmp_path, doc_type, entry_type):
    path = str(tmp_path / f"{doc_type}.bib")
    to_bibtex([Record(title="T", doc_type=doc_type, year=2024,
                      journal="Venue", authors=["Smith, A"])], path)
    assert entry_type in open(path, encoding="utf-8").read()


@pytest.mark.parametrize("doc_type", ["conference", "chapter"])
def test_proceedings_venue_goes_to_booktitle(tmp_path, doc_type):
    path = str(tmp_path / "v.bib")
    to_bibtex([Record(title="T", doc_type=doc_type, year=2024,
                      journal="Proc. of Something", authors=["Smith, A"])], path)
    text = open(path, encoding="utf-8").read()
    assert "booktitle = {Proc. of Something}" in text
    assert "journal =" not in text
    assert parse_bibtex(text)[0].journal == "Proc. of Something"


def test_bibtex_roundtrip_preserves_keywords_language_and_pmid(tmp_path):
    src = Record(title="T", authors=["Smith, A"], year=2024, journal="J",
                 keywords=["alpha", "beta"], language="en", pmid="12345678",
                 doi="10.5001/x")
    path = str(tmp_path / "meta.bib")
    to_bibtex([src], path)
    text = open(path, encoding="utf-8").read()
    assert "keywords = {alpha; beta}" in text
    assert "language = {en}" in text
    assert "PMID: 12345678" in text
    back = parse_bibtex(text)[0]
    assert back.keywords == ["alpha", "beta"] and back.language == "en"


@pytest.mark.parametrize("doc_type", ["article", "review", "conference",
                                      "chapter", "book", "thesis", "report",
                                      "preprint"])
def test_bibtex_roundtrip_preserves_doc_type(tmp_path, doc_type):
    """The parsed doc_type must come back, not just the entry-type marker.

    '@misc' is ambiguous (preprint, dataset, software), so a preprint used to
    round-trip into an empty doc_type and silently lost its grey-literature
    status in the PRISMA count.
    """
    path = str(tmp_path / f"rt_{doc_type}.bib")
    to_bibtex([Record(title="T", doc_type=doc_type, year=2024,
                      journal="Venue", authors=["Smith, A"])], path)
    back = parse_bibtex(open(path, encoding="utf-8").read())[0]
    # 'review' has no distinct BibTeX entry type and normalizes to article
    assert back.doc_type == ("article" if doc_type == "review" else doc_type)
