"""Render MANUSCRIPT.md and SUPPLEMENTARY.md as SoftwareX-styled .docx files.

Elsevier accepts Word for SoftwareX, and the journal's Word template is a
single-column manuscript in Times New Roman 12 pt with the required section
order and the C1-C9 "Code metadata" table before section 1. This script
produces that layout from the same markdown the LaTeX version is built from,
so the two cannot drift: both read MANUSCRIPT.md.

What is deliberately NOT attempted: reflowing the article into the journal's
two-column production layout. Elsevier typesets from the submitted manuscript,
and the author guidelines ask for single-column double-spaced text, so a
two-column Word file would be wrong rather than closer.

The converter is written on python-docx alone. Markdown support is limited to
what these two documents actually use, and anything unsupported raises instead
of being dropped silently - a heading or a table quietly missing from a
submitted manuscript is worse than a failed build.

Usage::

    PYTHONPATH=. python tools/build_docx.py
    PYTHONPATH=. python tools/build_docx.py --outdir /tmp/submission
"""
import argparse
import os
import re
import sys

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

#: The journal asks for Times New Roman; code and transcripts need a
#: fixed-width face so column alignment in quoted output survives.
# Measured from the journal's own accepted layout (BasketSLR, SoftwareX 2026),
# not chosen: Arial throughout, 11 pt body, 9.5 pt for the affiliation block and
# every caption, Consolas 9 pt for code. Word's Heading 1 carries all headings,
# including the title and the numbered subsections, so the outline is flat.
BODY_FONT = "Arial"
MONO_FONT = "Consolas"
BODY_PT = 11.0
CODE_PT = 9.0
CAPTION_PT = 9.5
AFFIL_PT = 9.5
HEADING_PT = 11.0
#: Body paragraphs in the reference layout use 1.05 line spacing and 6 pt after.
BODY_LINE_SPACING = 1.05
BODY_SPACE_AFTER = 6
#: Table body text shrinks with the column count, as it does in the reference.
TABLE_PT_BY_WIDTH = ((4, 9.0), (6, 8.5), (99, 8.0))


# --------------------------------------------------------------------------
# document setup
# --------------------------------------------------------------------------
def new_document():
    """A blank document carrying the reference layout's page and body setup.

    Letter paper with 1 inch margins and a single column, which is what the
    accepted article uses; the earlier version of this builder set A4 and
    double spacing, neither of which appears in the journal's own file.
    """
    doc = Document()
    for section in doc.sections:
        section.page_width = Inches(8.5)
        section.page_height = Inches(11.0)
        for attr in ("top_margin", "bottom_margin", "left_margin",
                     "right_margin"):
            setattr(section, attr, Inches(1.0))

    style = doc.styles["Normal"]
    style.font.name = BODY_FONT
    style.font.size = Pt(BODY_PT)
    # python-docx sets the Latin face only; without these the east-asian and
    # complex-script faces stay Calibri and Word may substitute mid-paragraph.
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.get_or_add_rFonts()
    for attr in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        rfonts.set(qn(attr), BODY_FONT)
    pf = style.paragraph_format
    pf.line_spacing = BODY_LINE_SPACING
    pf.space_after = Pt(BODY_SPACE_AFTER)
    return doc


def add_line_numbers(doc):
    """Continuous line numbers, as the reference layout carries them."""
    for section in doc.sections:
        ln = OxmlElement("w:lnNumType")
        ln.set(qn("w:countBy"), "1")
        ln.set(qn("w:restart"), "continuous")
        section._sectPr.append(ln)


# --------------------------------------------------------------------------
# inline markdown
# --------------------------------------------------------------------------
#: `code`, **bold**, *italic*, [text](target). Ordered so that a code span is
#: consumed first and its contents are never re-scanned for emphasis, which is
#: what markdown itself does.
_INLINE = re.compile(
    r"(?P<code>`[^`]+`)"
    r"|(?P<bold>\*\*[^*]+\*\*)"
    r"|(?P<italic>(?<!\*)\*(?!\*)[^*]+\*(?!\*))"
    r"|(?P<link>\[[^\]]+\]\([^)]+\))")

#: The separator row of a markdown table, e.g. "|---|---:|---:|".
_ALIGN_ROW = re.compile(r"^\|[\s:|-]+\|$")

#: A caption paragraph, written in markdown as "**Table 1.** ..." or
#: "**Figure 2.** ...". It is not body text: it prints at 9.5 pt, and a table
#: caption is moved below the table it labels.
_CAPTION_RE = re.compile(r"^\*\*(Table|Figure|Fig\.)\s*\d+\.?\*\*")

#: A reference-list entry, which opens with its bracketed number.
_REFERENCE_RE = re.compile(r"^\[\d+\]\s")


def add_runs(paragraph, text, base_size=BODY_PT):
    """Append `text` to `paragraph`, honouring inline markdown."""
    pos = 0
    for m in _INLINE.finditer(text):
        if m.start() > pos:
            paragraph.add_run(text[pos:m.start()])
        kind = m.lastgroup
        raw = m.group()
        if kind == "code":
            run = paragraph.add_run(raw[1:-1])
            run.font.name = MONO_FONT
            run.font.size = Pt(base_size - 1)
        elif kind == "bold":
            paragraph.add_run(raw[2:-2]).bold = True
        elif kind == "italic":
            paragraph.add_run(raw[1:-1]).italic = True
        else:
            label = raw[1:raw.index("]")]
            target = raw[raw.index("](") + 2:-1]
            run = paragraph.add_run(label)
            run.font.color.rgb = RGBColor(0x0B, 0x40, 0x8C)
            run.underline = True
            # The target is kept as text: a Word hyperlink field would be
            # stripped by most submission systems, and a reviewer needs the
            # URL visible on paper anyway.
            if target.startswith(("http", "www")) and target != label:
                paragraph.add_run(" (%s)" % target)
        # Advance past the match. Forgetting this appended the whole string a
        # second time after the loop, which showed up as duplicated text
        # inside every cell and paragraph that used inline markup.
        pos = m.end()
    if pos < len(text):
        paragraph.add_run(text[pos:])
    for run in paragraph.runs:
        if run.font.name is None:
            run.font.name = BODY_FONT
        if run.font.size is None:
            run.font.size = Pt(base_size)
    return paragraph


# --------------------------------------------------------------------------
# block markdown
# --------------------------------------------------------------------------
def add_heading(doc, level, text):
    """Every heading is Word's Heading 1, as in the reference layout.

    The reference file gives the title, "Abstract", "1. Motivation and
    significance" and "2.1. Software architecture" the same style and the same
    11 pt Arial: the visual hierarchy comes from the numbering, not from the
    type size. Keeping Heading 1 (rather than direct formatting) is what makes
    Word's navigation pane and the journal's own conversion tooling see the
    structure. The level argument is retained so callers need not change, but
    only the outline level varies with it.
    """
    p = doc.add_paragraph(style="Heading 1")
    pf = p.paragraph_format
    pf.space_before = Pt(12)
    pf.space_after = Pt(4)
    pf.line_spacing = 1.0
    pf.keep_with_next = True
    add_runs(p, text, base_size=HEADING_PT)
    for run in p.runs:
        run.font.name = BODY_FONT
        run.font.size = Pt(HEADING_PT)
        run.bold = True
        run.font.color.rgb = RGBColor(0, 0, 0)
    if level > 1:
        # The paragraph still reads as Heading 1 to Word; the outline level
        # keeps a sub-section from claiming top rank in the navigation pane.
        ppr = p._element.get_or_add_pPr()
        lvl = OxmlElement("w:outlineLvl")
        lvl.set(qn("w:val"), str(min(level - 1, 8)))
        ppr.append(lvl)
    return p


def add_body(doc, text):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    pf = p.paragraph_format
    pf.line_spacing = BODY_LINE_SPACING
    pf.space_after = Pt(BODY_SPACE_AFTER)
    add_runs(p, text)
    return p


def add_bullet(doc, text, ordered=False):
    p = doc.add_paragraph(style="List Number" if ordered else "List Bullet")
    pf = p.paragraph_format
    pf.space_after = Pt(3)
    pf.line_spacing = BODY_LINE_SPACING
    add_runs(p, text)
    for run in p.runs:
        run.font.name = BODY_FONT
    return p


def add_code_block(doc, lines):
    """A fixed-width, single-spaced, shaded block for code and transcripts."""
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.line_spacing_rule = WD_LINE_SPACING.SINGLE
    pf.space_before = Pt(6)
    pf.space_after = Pt(6)
    pf.left_indent = Inches(0.25)
    shade = OxmlElement("w:shd")
    shade.set(qn("w:val"), "clear")
    shade.set(qn("w:fill"), "F4F4F4")
    p._p.get_or_add_pPr().append(shade)
    for i, line in enumerate(lines):
        if i:
            p.add_run().add_break()
        run = p.add_run(line)
        run.font.name = MONO_FONT
        run.font.size = Pt(CODE_PT)
    return p


def _apply_table_borders(table):
    """Single hairline borders on every edge, matching the reference layout.

    The reference file carries them as direct table properties rather than
    through a named style, which is why its style name reads "Normal Table"
    while the printed table is fully ruled.
    """
    tbl_pr = table._element.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement("w:" + edge)
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), "4")          # 4 eighths of a point = 0.5 pt
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), "000000")
        borders.append(el)
    tbl_pr.append(borders)
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    tbl_pr.append(layout)


def table_font_pt(n_cols):
    """Body size for a table of this width, as the reference layout scales it."""
    for limit, size in TABLE_PT_BY_WIDTH:
        if n_cols <= limit:
            return size
    return TABLE_PT_BY_WIDTH[-1][1]


def add_table(doc, rows, alignments=None):
    """Render a markdown table: ruled, header bold and repeated across pages."""
    table = doc.add_table(rows=len(rows), cols=len(rows[0]))
    table.autofit = False
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _apply_table_borders(table)
    size = table_font_pt(len(rows[0]))
    for r, row in enumerate(rows):
        for c, cell_text in enumerate(row):
            cell = table.cell(r, c)
            cell.text = ""
            p = cell.paragraphs[0]
            pf = p.paragraph_format
            pf.line_spacing = 1.0
            pf.space_after = Pt(1)
            add_runs(p, cell_text, base_size=size)
            for run in p.runs:
                run.font.name = BODY_FONT
                run.font.size = Pt(size)
                if r == 0:
                    run.bold = True
            if alignments and c < len(alignments) and r > 0:
                p.alignment = alignments[c]
    tr_pr = table.rows[0]._tr.get_or_add_trPr()
    hdr = OxmlElement("w:tblHeader")
    hdr.set(qn("w:val"), "true")
    tr_pr.append(hdr)
    return table


def add_caption(doc, text):
    """A caption: plain 9.5 pt Arial, left aligned, no bold.

    The reference layout places the caption AFTER the object it describes, for
    figures and tables alike, and sets no bold anywhere in it.
    """
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.line_spacing = BODY_LINE_SPACING
    pf.space_before = Pt(0)
    pf.space_after = Pt(BODY_SPACE_AFTER)
    add_runs(p, text, base_size=CAPTION_PT)
    for run in p.runs:
        run.font.name = BODY_FONT
        run.font.size = Pt(CAPTION_PT)
        run.bold = False
    return p


def add_reference(doc, text):
    """One entry of the reference list: 9.5 pt Arial, left aligned, 3 pt after.

    The reference layout sets the bibliography a point and a half below body
    size and does not justify it, so a long DOI cannot open a line-wide gap.
    """
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.line_spacing = BODY_LINE_SPACING
    pf.space_after = Pt(3)
    add_runs(p, text, base_size=CAPTION_PT)
    for run in p.runs:
        run.font.name = BODY_FONT
        run.font.size = Pt(CAPTION_PT)
    return p


def add_figure(doc, path, caption=None, width_in=6.27):
    """Place the image where the text refers to it, caption underneath.

    A missing figure is fatal rather than skipped: a submitted manuscript whose
    figure silently did not make it into the file is worse than a failed build.
    """
    if not os.path.exists(path):
        raise SystemExit("figure not found, refusing to emit a manuscript "
                         "with a missing figure: %s" % path)
    doc.add_picture(path, width=Inches(width_in))
    holder = doc.paragraphs[-1]
    holder.alignment = WD_ALIGN_PARAGRAPH.CENTER
    holder.paragraph_format.space_after = Pt(2)
    holder.paragraph_format.line_spacing = 1.0
    if caption:
        add_caption(doc, caption)
    return holder


def _column_alignments(sep_row):
    """Per-column alignment from a markdown separator row, as Word enums.

    Returned as WD_ALIGN_PARAGRAPH members rather than strings: the caller
    assigns them straight to paragraph.alignment, and a string there raises
    only when that column is actually reached.
    """
    out = []
    for cell in [c.strip() for c in sep_row.strip().strip("|").split("|")]:
        if cell.startswith(":") and cell.endswith(":"):
            out.append(WD_ALIGN_PARAGRAPH.CENTER)
        elif cell.endswith(":"):
            out.append(WD_ALIGN_PARAGRAPH.RIGHT)
        else:
            out.append(WD_ALIGN_PARAGRAPH.LEFT)
    return out


def _split_row(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def render(doc, markdown, figure_root, skip_headings=()):
    """Walk the markdown and emit it. Returns counts for verification."""
    counts = {"headings": 0, "paragraphs": 0, "tables": 0, "figures": 0,
              "code_blocks": 0, "bullets": 0, "captions": 0,
              "references": 0}
    lines = markdown.replace("\r\n", "\n").split("\n")
    i = 0
    para = []
    #: A table caption is written above its table in markdown and printed
    #: below it in this layout, so it waits here until the table is emitted.
    pending = {"table_caption": None}

    def flush():
        if para:
            add_body(doc, " ".join(para))
            counts["paragraphs"] += 1
            del para[:]

    def take_paragraph(start):
        """Collect the wrapped lines of one paragraph starting at *start*."""
        out, k = [], start
        while k < len(lines):
            nxt = lines[k].strip()
            if not nxt or nxt.startswith(("#", "|", "```", "![")):
                break
            out.append(nxt)
            k += 1
        return " ".join(out), k

    def emit_pending_table_caption():
        if pending["table_caption"]:
            add_caption(doc, pending["table_caption"])
            counts["captions"] = counts.get("captions", 0) + 1
            pending["table_caption"] = None

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            flush()
            i += 1
            block = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            add_code_block(doc, block)
            counts["code_blocks"] += 1
            i += 1
            continue

        m = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if m:
            flush()
            text = m.group(2).strip()
            if text in skip_headings:
                # Skip the heading and everything under it until the next
                # heading of the same or higher level.
                depth = len(m.group(1))
                i += 1
                while i < len(lines):
                    m2 = re.match(r"^(#{1,4})\s+", lines[i].strip())
                    if m2 and len(m2.group(1)) <= depth:
                        break
                    i += 1
                continue
            add_heading(doc, len(m.group(1)), text)
            counts["headings"] += 1
            i += 1
            continue

        fig = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$", stripped)
        if fig:
            flush()
            alt, target = fig.group(1), fig.group(2)
            add_figure(doc, os.path.join(figure_root, os.path.basename(target)),
                       alt or None)
            counts["figures"] += 1
            i += 1
            if alt:
                counts["captions"] += 1
            else:
                # The caption is the next paragraph, written as
                # "**Figure N.** ...". Rendering it as body text would print
                # it at 11 pt justified instead of 9.5 pt.
                j = i
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines) and _CAPTION_RE.match(lines[j].strip()):
                    text, j = take_paragraph(j)
                    add_caption(doc, text)
                    counts["captions"] += 1
                    i = j
            continue

        if (stripped.startswith("|") and i + 1 < len(lines)
                and _ALIGN_ROW.match(lines[i + 1].strip())):
            flush()
            header = _split_row(stripped)
            aligns = _column_alignments(lines[i + 1])
            rows = [header]
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_split_row(lines[i].strip()))
                i += 1
            add_table(doc, rows, aligns)
            counts["tables"] += 1
            emit_pending_table_caption()
            continue

        if _REFERENCE_RE.match(stripped):
            flush()
            text, i = take_paragraph(i)
            add_reference(doc, text)
            counts["references"] = counts.get("references", 0) + 1
            continue

        if _CAPTION_RE.match(stripped) and stripped.startswith("**Table"):
            flush()
            text, i = take_paragraph(i)
            # Held, not emitted: the table it belongs to comes next.
            pending["table_caption"] = text
            continue

        b = re.match(r"^[-*]\s+(.*)$", stripped)
        n = re.match(r"^\d+\.\s+(.*)$", stripped)
        # A list starts a block. Matching one mid-paragraph silently deleted
        # content from the submitted document: a sentence wrapped as
        # "... ours higher in 13 of\n15. Neither dominates; ..." had its
        # continuation read as item 15 of an ordered list, and the marker "15."
        # was consumed, so the Word file read "higher in 13 of" and ran
        # straight into the next sentence. Any wrapped line beginning with a
        # number and a period, a year or a count, was exposed to this. The
        # buffer being empty means the previous line was blank or a block
        # boundary, which is where a list may legitimately begin.
        if (b or n) and para:
            b = n = None
        if b or n:
            flush()
            item = [(b or n).group(1)]
            i += 1
            # A wrapped item continues on the following lines. Treating each
            # as its own paragraph split emphasis across blocks, so a bold
            # span opened on one line and closed on the next reached the
            # document as literal asterisks.
            while i < len(lines):
                nxt = lines[i].strip()
                if (not nxt or nxt.startswith(("#", "|", "```", "!["))
                        or re.match(r"^[-*]\s+\S", nxt)
                        or re.match(r"^\d+\.\s+\S", nxt)
                        or (nxt.startswith("---") and set(nxt) <= set("- "))):
                    break
                item.append(nxt)
                i += 1
            add_bullet(doc, " ".join(item), ordered=bool(n))
            counts["bullets"] += 1
            continue

        if stripped.startswith("---") and set(stripped) <= set("- "):
            flush()
            i += 1
            continue

        if not stripped:
            flush()
            i += 1
            continue

        para.append(stripped)
        i += 1

    flush()
    # A caption whose table never arrived is still printed: losing it
    # silently would leave a table in the submission unlabelled.
    emit_pending_table_caption()
    return counts


# --------------------------------------------------------------------------
# the two documents
# --------------------------------------------------------------------------
def _unlatex(s):
    s = " ".join(s.split())
    s = re.sub(r"\\(?:texttt|emph|textbf|url)\{([^}]*)\}", r"\1", s)
    s = (s.replace("\\&", "&").replace("\\%", "%")
          .replace("\\,", " ").replace("\\_", "_"))
    # \sep is written surrounded by spaces, so a bare substitution leaves
    # " , " between keywords.
    s = re.sub(r"\s*\\sep\s*", ", ", s)
    return s.strip()


def code_metadata_rows():
    """The C1-C9 table, parsed from the article.

    The same table also sits in MANUSCRIPT.md, and keeping two copies is what
    let the C1 row fall a release behind: the .tex was bumped and the markdown
    was not. The .tex is the version the journal typesets, so it wins, and the
    markdown copy is checked against it by a test rather than rendered here.
    """
    path = os.path.join(HERE, "paper", "corpusslr_softwarex.tex")
    with open(path, encoding="utf-8") as fh:
        tex = fh.read()
    start = tex.find("Code metadata")
    if start < 0:
        raise SystemExit("the article has no code metadata table")
    seg = tex[start:tex.index("\\end{table}", start)]
    flat = re.sub(r"\s*\n\s*", " ", seg)
    rows = []
    for m in re.finditer(r"(C\d)\s*&\s*(.+?)\s*&\s*(.+?)\s*\\\\", flat):
        rows.append((m.group(1), _unlatex(m.group(2)), _unlatex(m.group(3))))
    if len(rows) != 9:
        raise SystemExit("expected C1-C9, parsed %d row(s)" % len(rows))
    return rows


def front_matter():
    """Title, author, affiliation, abstract and keywords, read from the .tex.

    The markdown carries none of these - it starts at the title heading - but
    a submitted manuscript needs all five, so they are taken from the typeset
    article, which is the version the journal receives. Reading them rather
    than restating them keeps the Word and LaTeX submissions in agreement.
    """
    path = os.path.join(HERE, "paper", "corpusslr_softwarex.tex")
    if not os.path.exists(path):
        raise SystemExit("cannot build front matter: %s is absent" % path)
    with open(path, encoding="utf-8") as fh:
        tex = fh.read()
    head = tex[:tex.find("\\section")]

    def grab(pattern, what):
        m = re.search(pattern, head, re.S)
        if not m:
            raise SystemExit(
                "the article has no %s, and a submitted manuscript needs one; "
                "refusing to invent it" % what)
        return _unlatex(m.group(1))

    def optional(pattern):
        m = re.search(pattern, tex, re.S)
        return _unlatex(m.group(1)) if m else None

    # \author{...} may carry a \corref marker; it belongs to the layout, not
    # to the name, so it is stripped here rather than printed after the author.
    # The capture must survive one level of nesting: \author{Name\corref{cor1}}
    # closes with an inner brace first, so a non-greedy .+? stops there and
    # drags half of the macro into the printed name.
    author_raw = grab(r"\\author\[[^\]]*\]\{((?:[^{}]|\{[^{}]*\})*)\}", "author")
    author = re.sub(r"\\?corref\s*\{?[a-z0-9]*\}?", "", author_raw).strip(" ,")
    return {
        "title": grab(r"\\title\{(.+?)\}\s*\n", "title"),
        "author": author,
        "affiliation": grab(r"\\address\[[^\]]*\]\{(.+?)\}", "affiliation"),
        "abstract": grab(r"\\begin\{abstract\}(.+?)\\end\{abstract\}", "abstract"),
        "keywords": grab(r"\\begin\{keyword\}(.+?)\\end\{keyword\}", "keywords"),
        "corresponding": optional(r"\\cortext\[[^\]]*\]\{(.+?)\}"),
        "email": optional(r"\\ead\{(.+?)\}")}


def add_front_matter(doc, fm):
    """Title, author with superscript markers, affiliation and correspondence.

    Laid out as the reference article does: everything left aligned, the title
    in Heading 1, the author line at body size with superscript affiliation and
    correspondence markers, then the affiliation, the corresponding-author line
    and the e-mail line at 9.5 pt. Nothing here is invented - each field is
    read from the article source, and a missing one is fatal.
    """
    add_heading(doc, 1, fm["title"])

    author = doc.add_paragraph()
    pf = author.paragraph_format
    pf.space_before = Pt(6)
    pf.space_after = Pt(4)
    pf.line_spacing = BODY_LINE_SPACING
    run = author.add_run(fm["author"])
    run.font.name = BODY_FONT
    run.font.size = Pt(BODY_PT)
    marker = author.add_run("a,*" if fm.get("corresponding") else "a")
    marker.font.name = BODY_FONT
    marker.font.size = Pt(BODY_PT)
    marker.font.superscript = True

    aff = doc.add_paragraph()
    aff.paragraph_format.space_after = Pt(2)
    aff.paragraph_format.line_spacing = BODY_LINE_SPACING
    tag = aff.add_run("a")
    tag.font.superscript = True
    for r in (tag, aff.add_run(" " + fm["affiliation"])):
        r.font.name = BODY_FONT
        r.font.size = Pt(AFFIL_PT)

    lines = []
    if fm.get("corresponding"):
        lines.append("* " + fm["corresponding"])
    if fm.get("email"):
        family = fm["author"].split()[-1]
        initial = fm["author"][0]
        lines.append("E-mail address: %s (%s. %s)"
                     % (fm["email"], initial, family))
    for text in lines:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.line_spacing = BODY_LINE_SPACING
        r = p.add_run(text)
        r.font.name = BODY_FONT
        r.font.size = Pt(AFFIL_PT)

    for label, key in (("Abstract", "abstract"), ("Keywords", "keywords")):
        add_heading(doc, 1, label)
        add_body(doc, fm[key])


def strip_provenance_comments(md):
    """Drop the leading ``%`` note that records how the file is generated.

    It is a note to whoever edits the markdown, not manuscript text, and
    rendering it put "SoftwareX manuscript draft / Generated ... Do not edit
    numbers by hand" at the top of the submitted document.
    """
    lines = md.split("\n")
    k = 0
    while k < len(lines) and (lines[k].startswith("%") or not lines[k].strip()):
        k += 1
    return "\n".join(lines[k:])


def build_manuscript(outdir):
    with open(os.path.join(HERE, "MANUSCRIPT.md"), encoding="utf-8") as fh:
        src = fh.read()
    src = strip_provenance_comments(src)
    doc = new_document()
    add_line_numbers(doc)
    add_front_matter(doc, front_matter())
    # The markdown repeats the title as its H1; the title page above already
    # carries it, so the duplicate heading is dropped.
    src = re.sub(r"^#\s+.*\n", "", src, count=1)
    # SoftwareX asks for the code metadata table before section 1. It is
    # emitted from the article rather than from the markdown copy, so a
    # version bump cannot leave the Word submission a release behind.
    # One "Metadata" heading followed by the table, as the reference layout
    # has it. The third column is headed "Metadata" there, not "Value".
    add_heading(doc, 1, "Metadata")
    rows = [("Nr", "Code metadata description", "Metadata")] + code_metadata_rows()
    add_table(doc, [list(r) for r in rows])
    counts = render(doc, src, os.path.join(HERE, "paper", "figures"),
                    skip_headings=("Metadata",))
    counts["tables"] += 1
    counts["headings"] += 1
    if counts["tables"] < 2:
        raise SystemExit(
            "expected at least the code metadata table and one results table, "
            "rendered %d - refusing to emit a manuscript missing a table"
            % counts["tables"])
    path = os.path.join(outdir, "CorpusSLR_SoftwareX_manuscript.docx")
    doc.save(path)
    return path, counts


def build_supplementary(outdir):
    with open(os.path.join(HERE, "SUPPLEMENTARY.md"), encoding="utf-8") as fh:
        src = fh.read()
    # Single-spaced: the supplement is an evidence appendix of dense tables,
    # and double spacing makes those unreadable rather than more reviewable.
    doc = new_document()
    counts = render(doc, src, os.path.join(HERE, "paper", "figures"))
    path = os.path.join(outdir, "CorpusSLR_SoftwareX_supplementary.docx")
    doc.save(path)
    return path, counts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--outdir", default=os.path.join(HERE, "paper", "docx"))
    args = ap.parse_args(argv)
    os.makedirs(args.outdir, exist_ok=True)

    for build in (build_manuscript, build_supplementary):
        path, counts = build(args.outdir)
        print("wrote %s (%s)"
              % (os.path.relpath(path, HERE),
                 ", ".join("%s %d" % (k, v) for k, v in sorted(counts.items())
                           if v)))
    return 0


if __name__ == "__main__":                       # pragma: no cover
    sys.exit(main())
