"""The Word submission is generated, so what it contains is testable.

Elsevier accepts Word for SoftwareX, and a manuscript that silently loses a
table, a figure or the code metadata block is worse than one that fails to
build. These tests read the produced .docx back rather than trusting the
build report, because the report counts what the converter believed it wrote.

Offline throughout: no network, no LaTeX run, no Word.
"""
from __future__ import annotations

import os
import re
import sys
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import corpusslr                                             # noqa: E402

docx = pytest.importorskip("docx", reason="python-docx is an optional extra")
build_docx = pytest.importorskip(
    "tools.build_docx", reason="tools/ is not present in this checkout")

PAPER = os.path.join(ROOT, "paper", "corpusslr_softwarex.tex")
needs_paper = pytest.mark.skipif(
    not os.path.exists(PAPER), reason="paper/ is not present in this checkout")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = str(tmp_path_factory.mktemp("docx"))
    man, man_counts = build_docx.build_manuscript(out)
    sup, sup_counts = build_docx.build_supplementary(out)
    return {"manuscript": man, "supplement": sup,
            "manuscript_counts": man_counts,
            "supplement_counts": sup_counts}


def _text(path):
    return "\n".join(p.text for p in docx.Document(path).paragraphs)


def _images(path):
    with zipfile.ZipFile(path) as zf:
        return [n for n in zf.namelist() if n.startswith("word/media/")]


# --------------------------------------------------------------------------
# front matter
# --------------------------------------------------------------------------
@needs_paper
def test_the_front_matter_comes_from_the_article_not_from_prose():
    """Five fields a submitted manuscript cannot be missing."""
    fm = build_docx.front_matter()
    for key in ("title", "author", "affiliation", "abstract", "keywords"):
        assert fm[key], "front matter has no %s" % key
    assert "\\" not in fm["title"] + fm["keywords"], "LaTeX markup survived"
    assert ", " in fm["keywords"] and " , " not in fm["keywords"]


@needs_paper
def test_the_manuscript_opens_with_title_author_abstract_and_keywords(built):
    """The front matter must read in the journal's own order and typography."""
    doc = docx.Document(built["manuscript"])
    paras = [p for p in doc.paragraphs if p.text.strip()]
    assert paras[0].style.name == "Heading 1"
    assert "CorpusSLR" in paras[0].text
    assert "Matysik" in paras[1].text
    # The affiliation is a real institution, read from the article; a
    # submission with no affiliation is returned by the editorial office.
    assert "University" in paras[2].text, paras[2].text
    labels = [p.text.strip() for p in paras[:10]]
    assert "Abstract" in labels and "Keywords" in labels, labels
    corr = [p.text for p in paras[:8] if p.text.startswith("* Corresponding")]
    assert corr, [p.text[:40] for p in paras[:8]]
    mail = [p.text for p in paras[:8] if p.text.startswith("E-mail address")]
    assert mail and "@" in mail[0], mail


def test_the_layout_matches_the_journals_accepted_article(built):
    """Page, font and spacing are measured from the journal's own file.

    These are not stylistic preferences: they were read off an accepted
    SoftwareX article, and drifting from them is what makes a submission look
    unlike the journal's template.
    """
    doc = docx.Document(built["manuscript"])
    section = doc.sections[0]
    assert round(section.page_width.inches, 2) == 8.5
    assert round(section.page_height.inches, 2) == 11.0
    for attr in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        assert round(getattr(section, attr).inches, 2) == 1.0, attr
    normal = doc.styles["Normal"]
    assert normal.font.name == "Arial"
    assert normal.font.size.pt == 11.0
    # Continuous line numbers, which the journal asks for on review copies.
    from docx.oxml.ns import qn as _qn
    ln = section._sectPr.find(_qn("w:lnNumType"))
    assert ln is not None
    assert ln.get(_qn("w:countBy")) == "1"
    assert ln.get(_qn("w:restart")) == "continuous"
    # A flat outline: the title and every numbered subsection share one style.
    styles = {p.style.name for p in doc.paragraphs if p.text.strip()
              and p.style.name.startswith("Heading")}
    assert styles == {"Heading 1"}, styles
    body = [p for p in doc.paragraphs
            if p.style.name == "Normal" and p.text.strip()
            and p.alignment is not None and int(p.alignment) == 3]
    assert len(body) > 20, len(body)
    assert {round(p.paragraph_format.line_spacing, 2) for p in body[:8]} == {1.05}


def test_captions_sit_below_their_object_at_caption_size(built):
    """The reference layout prints the caption after the object, at 9.5 pt.

    A table caption is written above its table in the markdown source, so this
    also pins the reordering rather than trusting it.
    """
    from docx.oxml.ns import qn as _qn
    from docx.table import Table as _Table
    from docx.text.paragraph import Paragraph as _P
    doc = docx.Document(built["manuscript"])
    seq = []
    for child in doc.element.body.iterchildren():
        if child.tag == _qn("w:p"):
            p = _P(child, doc)
            if p._element.findall(".//" + _qn("a:blip")):
                seq.append(("image", p))
            elif re.match(r"^(Table|Figure)\s*\d+\.", p.text.strip()):
                seq.append(("caption", p))
        elif child.tag == _qn("w:tbl"):
            seq.append(("table", _Table(child, doc)))
    kinds = [k for k, _ in seq]
    assert kinds.count("caption") >= 3, kinds
    for n, (kind, obj) in enumerate(seq):
        if kind != "caption":
            continue
        assert n > 0 and seq[n - 1][0] in ("image", "table"), (n, kinds)
        sizes = {r.font.size.pt for r in obj.runs if r.font.size}
        assert sizes == {9.5}, (obj.text[:40], sizes)
        assert not any(r.bold for r in obj.runs), obj.text[:40]


def test_the_reference_list_is_set_at_caption_size(built):
    doc = docx.Document(built["manuscript"])
    refs = [p for p in doc.paragraphs if re.match(r"^\[\d+\]\s", p.text.strip())]
    assert len(refs) >= 6, len(refs)
    for p in refs:
        sizes = {r.font.size.pt for r in p.runs if r.font.size}
        assert sizes == {9.5}, (p.text[:40], sizes)


def test_the_provenance_comment_is_not_manuscript_text(built):
    """The '%' note at the top of the markdown is an editing note.

    It read "SoftwareX manuscript draft / Generated ... Do not edit numbers by
    hand", which is not something to submit.
    """
    text = _text(built["manuscript"])
    assert "Do not edit numbers by hand" not in text
    assert "manuscript draft" not in text
    assert not text.lstrip().startswith("%")


# --------------------------------------------------------------------------
# nothing is silently dropped
# --------------------------------------------------------------------------
def test_the_code_metadata_table_is_present_and_current(built):
    tables = docx.Document(built["manuscript"]).tables
    assert tables, "the manuscript has no tables at all"
    meta = tables[0]
    labels = [meta.rows[i].cells[0].text.strip() for i in range(1, len(meta.rows))]
    assert labels == ["C%d" % k for k in range(1, 10)], labels
    version_cell = meta.rows[1].cells[-1].text.strip()
    assert version_cell == corpusslr.__version__, (
        "C1 says %s, the package is %s" % (version_cell, corpusslr.__version__))


def test_the_manuscript_carries_its_results_table(built):
    """The gold-standard comparison, not just the metadata block."""
    tables = docx.Document(built["manuscript"]).tables
    assert len(tables) >= 2, "only %d table(s) rendered" % len(tables)
    headers = [" ".join(c.text.strip() for c in t.rows[0].cells) for t in tables]
    assert any("F1" in h for h in headers), headers


def test_both_figures_are_embedded_not_just_referenced(built):
    imgs = _images(built["manuscript"])
    assert len(imgs) == 2, "expected two figures, embedded %d" % len(imgs)


def test_every_source_block_reaches_the_manuscript(built):
    """Compare the converter's own counts against the markdown it read.

    A dropped heading or table would otherwise be invisible: the build prints
    what it wrote, not what it was given.
    """
    with open(os.path.join(ROOT, "MANUSCRIPT.md"), encoding="utf-8") as fh:
        src = build_docx.strip_provenance_comments(fh.read())
    src = re.sub(r"^#\s+.*\n", "", src, count=1)

    # The builder drops the markdown "## Metadata" heading and emits the code
    # metadata table from the article instead, under two headings of its own.
    # The expected total therefore is: every source heading, minus the one
    # that is skipped, plus the two that are injected.
    # The builder drops the markdown "## Metadata" heading and emits the code
    # metadata table from the article under a single "Metadata" heading of its
    # own: every source heading, minus the one skipped, plus the one injected.
    headings = len(re.findall(r"^#{1,4}\s+\S", src, re.M)) - 1 + 1
    figures = len(re.findall(r"^!\[[^\]]*\]\([^)]+\)\s*$", src, re.M))
    counts = built["manuscript_counts"]
    assert counts["headings"] == headings, (counts["headings"], headings)
    assert counts["figures"] == figures, (counts["figures"], figures)


# --------------------------------------------------------------------------
# inline rendering
# --------------------------------------------------------------------------
def test_inline_markup_is_not_duplicated(built):
    """A run-position bug appended every marked-up string a second time.

    It surfaced as "notebooks/x.ipynb`notebooks/x.ipynb ..." inside a table
    cell, which a reader would see as corruption rather than as a converter
    fault, so it is pinned here.
    """
    for key in ("manuscript", "supplement"):
        doc = docx.Document(built[key])
        cells = [c.text.strip() for t in doc.tables for r in t.rows for c in r.cells]
        for value in cells + [p.text.strip() for p in doc.paragraphs]:
            if len(value) >= 30:
                head = value[:15]
                assert head not in value[15:], "%s: duplicated %r" % (key, head)


def test_no_markdown_syntax_survives_into_the_documents(built):
    for key in ("manuscript", "supplement"):
        text = _text(built[key])
        for token in ("**", "](", "```"):
            assert token not in text, "%s still contains %r" % (key, token)


def test_code_spans_are_rendered_in_a_fixed_width_face(built):
    doc = docx.Document(built["manuscript"])
    fonts = {r.font.name for p in doc.paragraphs for r in p.runs if r.font.name}
    assert build_docx.MONO_FONT in fonts, sorted(fonts)
    assert build_docx.BODY_FONT in fonts, sorted(fonts)


# --------------------------------------------------------------------------
# the supplement
# --------------------------------------------------------------------------
def test_the_supplement_names_the_current_version(built):
    first = [p.text.strip() for p in
             docx.Document(built["supplement"]).paragraphs if p.text.strip()][0]
    assert corpusslr.__version__ in first, first


def test_the_supplement_keeps_all_of_its_evidence_tables(built):
    src = open(os.path.join(ROOT, "SUPPLEMENTARY.md"), encoding="utf-8").read()
    expected = len(re.findall(r"^\|.*\n\|[\s:|-]+\|", src, re.M))
    got = len(docx.Document(built["supplement"]).tables)
    assert got == expected, "%d table(s) in the source, %d rendered" % (
        expected, got)


# --------------------------------------------------------------------------
# a missing figure must fail the build
# --------------------------------------------------------------------------
def test_a_missing_figure_stops_the_build(tmp_path):
    """Emitting a manuscript with a hole where a figure belongs is worse
    than emitting nothing, so add_figure raises."""
    doc = build_docx.new_document()
    with pytest.raises(SystemExit):
        build_docx.add_figure(doc, str(tmp_path / "absent.png"), "caption")
