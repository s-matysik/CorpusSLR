"""Build the CorpusSLR documentation site from the repository markdown.

Why this exists at all
----------------------
The published documentation is the same text a reviewer reads in the
repository, so the site is generated from those files rather than maintained
separately. A second copy of the user guide would drift from the first, and a
drifted accuracy figure is exactly the failure mode the number audit in
`validation/audit_document_numbers.py` exists to prevent.

Constraints this module is written under, all of them requirements rather
than preferences:

* Standard library only. The package itself depends on `requests` and nothing
  else, and a documentation build that needed a markdown library would be the
  one part of the release a user could not reproduce from a bare interpreter.
  The converter below is therefore hand-written and covers the subset of
  markdown the repository actually uses: ATX headings, fenced code, pipe
  tables with alignment, nested bullet and ordered lists, block quotes,
  horizontal rules, paragraphs, inline code, links, images, bold and italic.
  It is not a CommonMark implementation and does not try to be. The subset was
  chosen by scanning the six source documents for the constructs they contain,
  not by guessing.
* No external references. The site has to render correctly opened straight
  from disk with no network at all, so there is no CDN, no web font, no
  JavaScript and no stylesheet file: the CSS is inlined in a `<style>`
  element. This has one visible consequence, and it is deliberate: an
  `http://` or `https://` address appearing in the source text is rendered as
  monospace text rather than as a hyperlink. A clickable external link would
  be a reference to a domain the offline site cannot reach, so the addresses
  are shown in a form the reader can copy instead. Internal links between
  documents are rewritten to the generated file names and are checked, at
  build time, to point at a file or a fragment that exists.
* No long dashes. Every rendered text run is passed through
  `normalize_dashes()`, which maps the em dash, the en dash and the
  whitespace-delimited runs of two and three hyphens to a single hyphen. Code
  is excluded from that pass, because rewriting `--dry-run` inside a command
  would corrupt an instruction the reader is meant to paste.

  The literal long-dash forms are built from escapes and repetition below
  rather than typed out, so that the typography rule can be enforced on this
  module's own source as well as on its output. `tests/test_site.py` does
  exactly that.

Usage::

    python tools/build_site.py                 # writes ./site
    python tools/build_site.py --out /tmp/site # writes elsewhere
    python tools/build_site.py --clean         # remove the target first
"""
from __future__ import annotations

import argparse
import html
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

__all__ = [
    "SiteBuildError",
    "PAGES",
    "normalize_dashes",
    "find_dash_violations",
    "slugify",
    "render_inline",
    "markdown_to_html",
    "collect_headings",
    "build_site",
]

REPO_ROOT = Path(__file__).resolve().parent.parent


class SiteBuildError(RuntimeError):
    """A document could not be rendered, or a link in it does not resolve.

    Raised rather than warned about: a documentation site with a dead
    cross-reference is a defect that a build should not be allowed to publish
    quietly.
    """


class Page:
    """One source document and the HTML file it becomes."""

    def __init__(self, source: str, output: str, nav_title: str,
                 blurb: str = "") -> None:
        self.source = source
        self.output = output
        self.nav_title = nav_title
        self.blurb = blurb

    def __repr__(self) -> str:
        return "Page(%r -> %r)" % (self.source, self.output)


# The order here is the order of the navigation bar: what the package is,
# how to use it, what every symbol does, then the evidence documents.
PAGES: Tuple[Page, ...] = (
    Page("README.md", "index.html", "Overview",
         "What CorpusSLR does, which databases it reaches and what it emits."),
    Page("docs/user_guide.md", "user_guide.html", "User guide",
         "A review from the first query to the PRISMA appendix."),
    Page("docs/api_reference.md", "api_reference.html", "API reference",
         "Every public symbol, its arguments and its return value."),
    Page("SUPPLEMENTARY.md", "supplementary.html", "Supplementary",
         "The measured tables behind the accuracy figures."),
    Page("validation/multidomain_validation.md", "multidomain_validation.html",
         "Multi-domain study",
         "Identifier-blind deduplication accuracy across 15 disciplines."),
    Page("AUDIT_REPORT.md", "audit_report.html", "Audit report",
         "Defects found, what was changed and the regression test for each."),
    Page("CHANGELOG.md", "changelog.html", "Changelog",
         "Release history in Keep a Changelog form."),
)

# The evidence index is generated rather than converted, so it is listed
# separately from PAGES but appears in the same navigation bar.
EVIDENCE_OUTPUT = "evidence.html"
EVIDENCE_TITLE = "Evidence files"

# Validation artefacts are copied into the site so that a figure quoted in the
# supplementary material can be opened from the page that quotes it. One file
# is far larger than the rest: validation/labelled_test_set.csv is the ASySD
# input corpus at ~4 MB. It is regenerable and is named on the evidence page
# with its size instead of being copied, so the published site stays small
# enough to serve from Pages without becoming a data mirror.
EVIDENCE_MAX_BYTES = 1_000_000
EVIDENCE_PATTERNS: Tuple[str, ...] = ("*.csv", "*.json", "*.png")

# Files a document links to that are not themselves rendered as pages. They
# are copied verbatim into site/files/ and the links are rewritten.
COPIED_FILES: Tuple[str, ...] = (
    "examples/review_config.json",
    "examples/example_slr.py",
    "examples/example_reproducible_harvest.py",
    "notebooks/corpusslr_colab.ipynb",
)

# Figures shown inline on the evidence page.
FEATURED_FIGURES: Tuple[Tuple[str, str], ...] = (
    ("validation/fig_domains.png",
     "Per-domain deduplication F1 across the 15-discipline corpus."),
    ("validation/fig_ablation.png",
     "Mechanism ablation: contribution of each matching stage."),
)

# A relative source path that a link may point at, mapped to its destination
# in the built site. Populated from PAGES and COPIED_FILES at build time; the
# directory entry is spelled out because a link to a directory listing has no
# equivalent in a static site and belongs on the evidence index instead.
EXTRA_LINK_MAP: Dict[str, str] = {
    "validation/": EVIDENCE_OUTPUT,
    "validation": EVIDENCE_OUTPUT,
}


# ---------------------------------------------------------------------------
# Typography
# ---------------------------------------------------------------------------

# Order matters. The em and en dash are single characters and are replaced
# first; the ASCII runs are then collapsed. The whitespace-delimited forms are
# handled before the word-internal form, so a spaced run of two hyphens
# becomes a spaced single hyphen rather than losing the leading space.
_EM_DASH = "\u2014"
_EN_DASH = "\u2013"
_HYPHEN = "-"
_TWO_HYPHENS = _HYPHEN * 2
_THREE_HYPHENS = _HYPHEN * 3
_DASH_RUN_SPACED = re.compile(r"\s+-{2,}\s+")
_DASH_RUN_INWORD = re.compile(r"(?<=\w)-{2,}(?=\w)")
_DASH_RUN_EDGE = re.compile(r"(?<!-)-{3,}(?!-)")


def normalize_dashes(text: str) -> str:
    """Map every long-dash form in `text` to a single hyphen.

    The user requirement is absolute: the hyphen is the only dash permitted in
    any text this project produces. Four forms have to be covered, because all
    four occur in the source documents: the em dash (307 occurrences), the en
    dash (24), and the spaced ASCII runs of two and three hyphens used where
    the source was written in plain text.

    Code is never passed through this function. `--dry-run` is an argument the
    reader pastes into a shell, and collapsing it to `-dry-run` would publish a
    command that does not work.

    >>> normalize_dashes("a \u2014 b")
    'a - b'
    >>> normalize_dashes("years 3.9\u20133.13")
    'years 3.9-3.13'
    >>> normalize_dashes("noise " + _TWO_HYPHENS + " yet done by hand")
    'noise - yet done by hand'
    >>> normalize_dashes("a " + _THREE_HYPHENS + " b")
    'a - b'
    >>> normalize_dashes("--dry-run")
    '--dry-run'
    """
    out = text.replace(_EM_DASH, "-").replace(_EN_DASH, "-")
    out = _DASH_RUN_SPACED.sub(" - ", out)
    out = _DASH_RUN_INWORD.sub("-", out)
    return _DASH_RUN_EDGE.sub("-", out)


# The control performed on the generated output. It is intentionally the
# literal set of forms the user named, so that a passing check means what the
# requirement says rather than what was convenient to implement.
DASH_PATTERNS: Tuple[Tuple[str, str], ...] = (
    ("em dash", _EM_DASH),
    ("en dash", _EN_DASH),
    ("spaced triple hyphen", " " + _THREE_HYPHENS + " "),
    ("spaced double hyphen", " " + _TWO_HYPHENS + " "),
)


def find_dash_violations(text: str) -> List[Tuple[int, str, str]]:
    """Return `(line_number, violation_name, line)` for every long dash found.

    An empty list means the text satisfies the typography requirement. The
    line is returned alongside the name so that a failure report shows the
    offending context instead of only a count.
    """
    hits: List[Tuple[int, str, str]] = []
    for lineno, line in enumerate(text.split("\n"), start=1):
        for name, needle in DASH_PATTERNS:
            if needle in line:
                hits.append((lineno, name, line.strip()))
    return hits


# ---------------------------------------------------------------------------
# Inline rendering
# ---------------------------------------------------------------------------

# Code spans are extracted before anything else happens to a text run, and put
# back last. Two consequences are load-bearing: markup characters inside a code
# span are never interpreted, and a table cell delimiter inside a code span is
# never mistaken for a cell boundary. One and two backtick fences are both
# supported because the repository uses both.
_CODE_SPAN = re.compile(r"(?P<fence>`{1,2})(?P<body>.+?)(?P=fence)", re.DOTALL)
_PLACEHOLDER = "\x00%d\x00"
_PLACEHOLDER_RE = re.compile(r"\x00(\d+)\x00")

_IMAGE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<url>[^)\s]+)(?:\s+\"[^\"]*\")?\)")
_LINK = re.compile(r"(?<!!)\[(?P<text>[^\]]*)\]\((?P<url>[^)\s]+)(?:\s+\"[^\"]*\")?\)")
# Bold has to tolerate a nested italic, because the source contains it:
# `**Removing the author list slightly *helps***` in the multi-domain study.
# A body of `[^*]+` cannot match that, and the first version of this converter
# emitted the literal asterisks into the page. The body below accepts a lone
# `*` (one not followed by another) and may end on a single `*`, so a closing
# run of three asterisks is split correctly: the first closes the italic and
# the last two close the bold. The italic pass then runs over the emitted body
# and turns the inner pair into <em>, giving <strong>A <em>B</em></strong>.
_BOLD = re.compile(r"\*\*(?P<body>(?:[^*]|\*(?!\*))+\*?)\*\*")
_ITALIC_STAR = re.compile(r"(?<!\*)\*(?P<body>[^*\n]+)\*(?!\*)")
_ITALIC_UNDER = re.compile(r"(?<![\w\\])_(?P<body>[^_\n]+)_(?![\w])")
_BARE_URL = re.compile(r"(?<![\"'=\w])(?P<url>https?://[^\s<>\"')\]]+)")
_EXTERNAL = re.compile(r"^(?:[a-zA-Z][a-zA-Z0-9+.-]*:|//)")


def _protect_code(text: str, store: List[str]) -> str:
    """Replace every code span in `text` with an opaque placeholder.

    The rendered `<code>` element is appended to `store`; the returned string
    contains placeholders in its place. Calling this on already-protected text
    is a no-op, which is what lets a table row be protected once and its cells
    rendered individually afterwards.
    """
    def repl(match: "re.Match[str]") -> str:
        store.append("<code>%s</code>" % html.escape(match.group("body")))
        return _PLACEHOLDER % (len(store) - 1)

    return _CODE_SPAN.sub(repl, text)


def _restore_code(text: str, store: Sequence[str]) -> str:
    def repl(match: "re.Match[str]") -> str:
        index = int(match.group(1))
        if index >= len(store):
            raise SiteBuildError("code placeholder %d has no stored span" % index)
        return store[index]

    return _PLACEHOLDER_RE.sub(repl, text)


def _strip_markup(text: str) -> str:
    """Reduce an inline run to its plain text, for titles and slugs."""
    out = _CODE_SPAN.sub(lambda m: m.group("body"), text)
    out = _IMAGE.sub(lambda m: m.group("alt"), out)
    out = _LINK.sub(lambda m: m.group("text"), out)
    out = _BOLD.sub(lambda m: m.group("body"), out)
    out = _ITALIC_STAR.sub(lambda m: m.group("body"), out)
    out = _ITALIC_UNDER.sub(lambda m: m.group("body"), out)
    return out.strip()


def slugify(text: str) -> str:
    """Turn heading text into a URL fragment.

    Deliberately the same rule the repository's own cross-references already
    assume: lowercase, markup stripped, every run of non-alphanumeric
    characters folded to one hyphen. `README.md` links to
    `docs/user_guide.md#5a-the-canonical-output-scopus-csv`, and that fragment
    has to keep resolving after conversion.

    >>> slugify("## 5a. The canonical output: Scopus CSV".lstrip("# "))
    '5a-the-canonical-output-scopus-csv'
    """
    plain = normalize_dashes(_strip_markup(text)).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", plain).strip("-")
    return slug or "section"


def render_inline(text: str, store: Optional[List[str]] = None,
                  link_map: Optional[Dict[str, str]] = None,
                  unresolved: Optional[List[str]] = None) -> str:
    """Render one inline text run to HTML.

    The pipeline is fixed and each step exists for a reason:

    1. code spans out, so their contents are never reinterpreted;
    2. dash normalization, on text only;
    3. HTML escaping, before any tag of ours is inserted, so that a literal
       `<record>` in the prose cannot become an element;
    4. images, then links (link targets rewritten through `link_map`);
    5. already-emitted anchors out of the way, then bare addresses rendered as
       monospace text rather than as links, because the site must not reference
       a domain it cannot reach offline;
    6. bold before italic, since `**` would otherwise be eaten by the single
       asterisk rule;
    7. code spans back in.
    """
    own_store = store is None
    code_store: List[str] = [] if store is None else store
    out = _protect_code(text, code_store)
    out = normalize_dashes(out)
    out = html.escape(out, quote=False)

    tag_store: List[str] = []

    def _stash(rendered: str) -> str:
        tag_store.append(rendered)
        return "\x01%d\x01" % (len(tag_store) - 1)

    def _image(match: "re.Match[str]") -> str:
        url = _resolve_link(match.group("url"), link_map, unresolved)
        alt = normalize_dashes(_strip_markup(match.group("alt")))
        if _EXTERNAL.match(url):
            # An external image would be a network fetch. Show the address.
            return _stash("<code>%s</code>" % html.escape(url, quote=True))
        return _stash('<img src="%s" alt="%s" />'
                      % (html.escape(url, quote=True), html.escape(alt, quote=True)))

    def _link(match: "re.Match[str]") -> str:
        raw_url = match.group("url")
        label = match.group("text")
        if _EXTERNAL.match(raw_url):
            # Rendered as text plus the address, so nothing points off-site.
            shown = label if label else raw_url
            return _stash("%s (<code>%s</code>)"
                          % (shown, html.escape(raw_url, quote=True))
                          if label else "<code>%s</code>"
                          % html.escape(raw_url, quote=True))
        url = _resolve_link(raw_url, link_map, unresolved)
        return _stash('<a href="%s">%s</a>'
                      % (html.escape(url, quote=True), label))

    out = _IMAGE.sub(_image, out)
    out = _LINK.sub(_link, out)
    out = _BARE_URL.sub(
        lambda m: _stash("<code>%s</code>" % html.escape(m.group("url"), quote=True)),
        out)
    out = _BOLD.sub(lambda m: "<strong>%s</strong>" % m.group("body"), out)
    out = _ITALIC_STAR.sub(lambda m: "<em>%s</em>" % m.group("body"), out)
    out = _ITALIC_UNDER.sub(lambda m: "<em>%s</em>" % m.group("body"), out)

    out = re.sub(r"\x01(\d+)\x01", lambda m: tag_store[int(m.group(1))], out)
    if own_store:
        out = _restore_code(out, code_store)
    return out


def _resolve_link(url: str, link_map: Optional[Dict[str, str]],
                  unresolved: Optional[List[str]]) -> str:
    """Rewrite a repository-relative link to its place in the built site."""
    if _EXTERNAL.match(url) or url.startswith("#"):
        return url
    if link_map is None:
        return url
    target, _, fragment = url.partition("#")
    key = target.lstrip("./")
    if key in link_map:
        mapped = link_map[key]
        return mapped + ("#" + fragment if fragment else "")
    if not target and fragment:
        return "#" + fragment
    if unresolved is not None:
        unresolved.append(url)
    return url


# ---------------------------------------------------------------------------
# Block rendering
# ---------------------------------------------------------------------------

_ATX = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<body>.*?)\s*#*\s*$")
_FENCE = re.compile(r"^(?P<indent>\s*)(?P<fence>```|~~~)(?P<info>[^\s`~]*)\s*$")
_HRULE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
_LIST_ITEM = re.compile(
    r"^(?P<indent>\s*)(?P<marker>[-*+]|\d+[.)])\s+(?P<body>.*)$")
_TABLE_ALIGN = re.compile(r"^\s*\|?(?:\s*:?-{2,}:?\s*\|)+\s*:?-{2,}:?\s*\|?\s*$")
_QUOTE = re.compile(r"^\s*>\s?(?P<body>.*)$")


class _Renderer:
    """Converts one markdown document into HTML fragments.

    Written as a class only so that the heading slug counter and the
    unresolved-link list are shared across the whole document without being
    threaded through every method as an argument.
    """

    def __init__(self, link_map: Optional[Dict[str, str]] = None) -> None:
        self.link_map = link_map
        self.slug_counts: Dict[str, int] = {}
        self.unresolved: List[str] = []
        self.headings: List[Tuple[int, str, str]] = []

    # ..... helpers .....
    def inline(self, text: str, store: Optional[List[str]] = None) -> str:
        return render_inline(text, store=store, link_map=self.link_map,
                             unresolved=self.unresolved)

    def unique_slug(self, text: str) -> str:
        base = slugify(text)
        seen = self.slug_counts.get(base, 0)
        self.slug_counts[base] = seen + 1
        return base if seen == 0 else "%s-%d" % (base, seen)

    # ..... blocks .....
    def render(self, lines: Sequence[str]) -> str:
        parts: List[str] = []
        i = 0
        total = len(lines)
        while i < total:
            line = lines[i]
            if not line.strip():
                i += 1
                continue
            fence = _FENCE.match(line)
            if fence:
                block, i = self._code_block(lines, i, fence)
                parts.append(block)
                continue
            atx = _ATX.match(line)
            if atx:
                parts.append(self._heading(atx))
                i += 1
                continue
            if _HRULE.match(line):
                parts.append("<hr />")
                i += 1
                continue
            if self._is_table_start(lines, i):
                block, i = self._table(lines, i)
                parts.append(block)
                continue
            if _QUOTE.match(line):
                block, i = self._quote(lines, i)
                parts.append(block)
                continue
            if _LIST_ITEM.match(line):
                block, i = self._list(lines, i)
                parts.append(block)
                continue
            block, i = self._paragraph(lines, i)
            parts.append(block)
        return "\n".join(parts)

    def _heading(self, match: "re.Match[str]") -> str:
        level = len(match.group("hashes"))
        body = match.group("body")
        slug = self.unique_slug(body)
        plain = normalize_dashes(_strip_markup(body))
        self.headings.append((level, slug, plain))
        return '<h%d id="%s">%s</h%d>' % (level, slug, self.inline(body), level)

    def _code_block(self, lines: Sequence[str], start: int,
                    fence: "re.Match[str]") -> Tuple[str, int]:
        marker = fence.group("fence")
        info = fence.group("info").strip()
        indent = len(fence.group("indent"))
        body: List[str] = []
        i = start + 1
        while i < len(lines):
            candidate = lines[i]
            if candidate.strip().startswith(marker) and not candidate.strip()[len(marker):].strip():
                i += 1
                break
            body.append(candidate[indent:] if candidate[:indent].strip() == "" else candidate)
            i += 1
        # Code is escaped but never dash-normalized: a command has to stay
        # runnable, and `--dry-run` is not a typographic dash.
        text = html.escape("\n".join(body))
        cls = ' class="language-%s"' % html.escape(info, quote=True) if info else ""
        return "<pre><code%s>%s</code></pre>" % (cls, text), i

    def _is_table_start(self, lines: Sequence[str], i: int) -> bool:
        if "|" not in lines[i]:
            return False
        if i + 1 >= len(lines):
            return False
        return bool(_TABLE_ALIGN.match(lines[i + 1]))

    @staticmethod
    def _split_row(row: str, store: List[str]) -> List[str]:
        """Split a table row into cells, code spans already protected.

        Protecting the row before splitting is what makes a cell such as
        ``| `export` | Scopus CSV / RIS | `--scopus` is canonical |`` split on
        the three real delimiters rather than on a pipe that happens to sit
        inside a code span.
        """
        protected = _protect_code(row, store)
        stripped = protected.strip()
        if stripped.startswith("|"):
            stripped = stripped[1:]
        if stripped.endswith("|"):
            stripped = stripped[:-1]
        return [cell.strip() for cell in stripped.split("|")]

    @staticmethod
    def _alignments(row: str) -> List[str]:
        cells = row.strip().strip("|").split("|")
        out: List[str] = []
        for cell in cells:
            spec = cell.strip()
            if spec.startswith(":") and spec.endswith(":"):
                out.append("center")
            elif spec.endswith(":"):
                out.append("right")
            else:
                out.append("")
        return out

    def _table(self, lines: Sequence[str], start: int) -> Tuple[str, int]:
        store: List[str] = []
        header = self._split_row(lines[start], store)
        aligns = self._alignments(lines[start + 1])
        rows: List[List[str]] = []
        i = start + 2
        while i < len(lines) and lines[i].strip() and "|" in lines[i]:
            rows.append(self._split_row(lines[i], store))
            i += 1

        def cell(tag: str, text: str, index: int) -> str:
            align = aligns[index] if index < len(aligns) else ""
            style = ' style="text-align:%s"' % align if align else ""
            return "<%s%s>%s</%s>" % (tag, style, self.inline(text, store), tag)

        out = ["<div class=\"table-wrap\">", "<table>", "<thead>", "<tr>"]
        out += [cell("th", text, n) for n, text in enumerate(header)]
        out += ["</tr>", "</thead>", "<tbody>"]
        for row in rows:
            out.append("<tr>")
            out += [cell("td", text, n) for n, text in enumerate(row)]
            out.append("</tr>")
        out += ["</tbody>", "</table>", "</div>"]
        return _restore_code("\n".join(out), store), i

    def _quote(self, lines: Sequence[str], start: int) -> Tuple[str, int]:
        body: List[str] = []
        i = start
        while i < len(lines):
            match = _QUOTE.match(lines[i])
            if match is None:
                if lines[i].strip() and body:
                    body.append(lines[i].strip())
                    i += 1
                    continue
                break
            body.append(match.group("body"))
            i += 1
        inner = self.render(body)
        return "<blockquote>%s</blockquote>" % inner, i

    def _list(self, lines: Sequence[str], start: int) -> Tuple[str, int]:
        """Render a run of list items, nesting by indentation.

        Nesting is driven by a stack of (indent, tag) pairs rather than by
        recursion over slices, so a list that dedents by two levels at once
        closes both of them. The repository's own documents are flat lists, but
        the converter is tested on nested input because a documentation page
        added later should not silently render as a flat list.
        """
        items: List[Tuple[int, bool, List[str]]] = []
        i = start
        while i < len(lines):
            line = lines[i]
            match = _LIST_ITEM.match(line)
            if match:
                indent = len(match.group("indent").expandtabs(4))
                ordered = match.group("marker")[0] not in "-*+"
                items.append((indent, ordered, [match.group("body")]))
                i += 1
                continue
            if not line.strip():
                # A blank line continues the list only if an indented item or
                # continuation follows; otherwise the list ends here.
                nxt = i + 1
                while nxt < len(lines) and not lines[nxt].strip():
                    nxt += 1
                if nxt < len(lines) and (_LIST_ITEM.match(lines[nxt])
                                         or lines[nxt].startswith(("  ", "\t"))):
                    i = nxt
                    continue
                break
            if items and line.startswith((" ", "\t")):
                items[-1][2].append(line.strip())
                i += 1
                continue
            break

        out: List[str] = []
        stack: List[Tuple[int, str]] = []
        for indent, ordered, body in items:
            tag = "ol" if ordered else "ul"
            while stack and indent < stack[-1][0]:
                out.append("</li>")
                out.append("</%s>" % stack.pop()[1])
            if not stack or indent > stack[-1][0]:
                stack.append((indent, tag))
                out.append("<%s>" % tag)
            else:
                out.append("</li>")
            out.append("<li>%s" % self.inline(" ".join(body)))
        while stack:
            out.append("</li>")
            out.append("</%s>" % stack.pop()[1])
        return "\n".join(out), i

    def _paragraph(self, lines: Sequence[str], start: int) -> Tuple[str, int]:
        body: List[str] = []
        i = start
        while i < len(lines):
            line = lines[i]
            if not line.strip() or _ATX.match(line) or _FENCE.match(line) \
                    or _HRULE.match(line) or _LIST_ITEM.match(line) \
                    or _QUOTE.match(line) or self._is_table_start(lines, i):
                break
            body.append(line.strip())
            i += 1
        return "<p>%s</p>" % self.inline(" ".join(body)), i


def markdown_to_html(text: str, link_map: Optional[Dict[str, str]] = None
                     ) -> Tuple[str, List[Tuple[int, str, str]], List[str]]:
    """Convert a markdown document to an HTML fragment.

    Returns the fragment, the heading list as `(level, slug, plain_text)` and
    the list of links that could not be resolved against `link_map`.
    """
    renderer = _Renderer(link_map=link_map)
    body = renderer.render(text.replace("\r\n", "\n").split("\n"))
    return body, renderer.headings, renderer.unresolved


def collect_headings(text: str) -> List[Tuple[int, str, str]]:
    """Heading list for a document, without rendering it."""
    return markdown_to_html(text)[1]


# ---------------------------------------------------------------------------
# Page assembly
# ---------------------------------------------------------------------------

# Inlined on purpose: a stylesheet file would be a second request, and the
# requirement is that the page renders opened straight from disk. System font
# stacks are named rather than fetched, so there is no web font either.
CSS = """
:root {
  --ink: #1a1c1f;
  --muted: #5b6270;
  --rule: #d8dce3;
  --accent: #1f4e79;
  --code-bg: #f4f5f7;
  --page: #ffffff;
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  background: var(--page);
  color: var(--ink);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
               "Helvetica Neue", Arial, sans-serif;
  font-size: 16px;
  line-height: 1.62;
}
header.site {
  border-bottom: 1px solid var(--rule);
  padding: 1.1rem 1.4rem 0.9rem;
}
header.site .brand {
  font-size: 1.05rem;
  font-weight: 700;
  letter-spacing: 0.01em;
  color: var(--accent);
  text-decoration: none;
}
header.site .tagline {
  color: var(--muted);
  font-size: 0.86rem;
  margin-top: 0.15rem;
}
nav.site { margin-top: 0.7rem; }
nav.site a {
  color: var(--ink);
  display: inline-block;
  font-size: 0.86rem;
  margin: 0.15rem 0.9rem 0.15rem 0;
  text-decoration: none;
  border-bottom: 2px solid transparent;
  padding-bottom: 2px;
}
nav.site a:hover { border-bottom-color: var(--rule); }
nav.site a[aria-current="page"] {
  border-bottom-color: var(--accent);
  color: var(--accent);
  font-weight: 600;
}
main {
  margin: 0 auto;
  max-width: 54rem;
  padding: 1.6rem 1.4rem 4rem;
}
h1, h2, h3, h4, h5, h6 { line-height: 1.28; margin: 1.9rem 0 0.7rem; }
h1 { font-size: 1.85rem; margin-top: 0.4rem; }
h2 { font-size: 1.4rem; border-bottom: 1px solid var(--rule); padding-bottom: 0.3rem; }
h3 { font-size: 1.13rem; }
h4, h5, h6 { font-size: 1rem; }
p { margin: 0.75rem 0; }
a { color: var(--accent); }
ul, ol { margin: 0.6rem 0; padding-left: 1.5rem; }
li { margin: 0.22rem 0; }
li > ul, li > ol { margin: 0.22rem 0; }
code {
  background: var(--code-bg);
  border-radius: 3px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.87em;
  padding: 0.1em 0.34em;
  word-break: break-word;
}
pre {
  background: var(--code-bg);
  border: 1px solid var(--rule);
  border-radius: 5px;
  overflow-x: auto;
  padding: 0.85rem 1rem;
}
pre code { background: none; font-size: 0.83rem; padding: 0; word-break: normal; }
blockquote {
  border-left: 3px solid var(--rule);
  color: var(--muted);
  margin: 0.9rem 0;
  padding: 0.1rem 0 0.1rem 1rem;
}
hr { border: none; border-top: 1px solid var(--rule); margin: 2rem 0; }
.table-wrap { overflow-x: auto; margin: 1rem 0; }
table { border-collapse: collapse; font-size: 0.9rem; width: 100%; }
th, td {
  border: 1px solid var(--rule);
  padding: 0.4rem 0.6rem;
  text-align: left;
  vertical-align: top;
}
th { background: var(--code-bg); font-weight: 600; }
img { max-width: 100%; height: auto; }
.toc {
  background: var(--code-bg);
  border: 1px solid var(--rule);
  border-radius: 5px;
  font-size: 0.88rem;
  margin: 1.2rem 0 1.8rem;
  padding: 0.8rem 1rem;
}
.toc p { font-weight: 600; margin: 0 0 0.4rem; }
.toc ul { list-style: none; margin: 0; padding-left: 0; }
.toc ul ul { padding-left: 1rem; }
.toc a { text-decoration: none; }
.toc a:hover { text-decoration: underline; }
.cards { display: block; margin: 1.2rem 0; }
.card {
  border: 1px solid var(--rule);
  border-radius: 5px;
  margin: 0.6rem 0;
  padding: 0.7rem 0.9rem;
}
.card a { font-weight: 600; text-decoration: none; }
.card p { color: var(--muted); font-size: 0.88rem; margin: 0.2rem 0 0; }
figure { margin: 1.4rem 0; }
figcaption { color: var(--muted); font-size: 0.86rem; margin-top: 0.4rem; }
footer.site {
  border-top: 1px solid var(--rule);
  color: var(--muted);
  font-size: 0.83rem;
  margin: 0 auto;
  max-width: 54rem;
  padding: 1.2rem 1.4rem 2.4rem;
}
@media (prefers-color-scheme: dark) {
  :root {
    --ink: #e6e8eb;
    --muted: #a3abb8;
    --rule: #333941;
    --accent: #7fb2e0;
    --code-bg: #1c2026;
    --page: #14171b;
  }
}
"""

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>%(title)s</title>
<meta name="description" content="%(description)s" />
<meta name="generator" content="tools/build_site.py, standard library only" />
<style>%(css)s</style>
</head>
<body>
<header class="site">
<a class="brand" href="index.html">CorpusSLR %(version)s</a>
<div class="tagline">From one structured query to a PRISMA-documented corpus.</div>
<nav class="site">%(nav)s</nav>
</header>
<main>
%(body)s
</main>
<footer class="site">
<p>%(footer)s</p>
</footer>
</body>
</html>
"""


def _nav_html(current: str) -> str:
    entries = [(page.output, page.nav_title) for page in PAGES]
    entries.append((EVIDENCE_OUTPUT, EVIDENCE_TITLE))
    out: List[str] = []
    for href, label in entries:
        mark = ' aria-current="page"' if href == current else ""
        out.append('<a href="%s"%s>%s</a>' % (href, mark, html.escape(label)))
    return "\n".join(out)


def _toc_html(headings: Sequence[Tuple[int, str, str]]) -> str:
    """A contents list for pages long enough to need one.

    Only levels 2 and 3 are listed: the API reference has 175 headings and a
    full-depth contents list would be longer than the page it introduces.
    """
    listed = [h for h in headings if h[0] in (2, 3)]
    if len(listed) < 6:
        return ""
    out = ['<div class="toc">', "<p>On this page</p>", "<ul>"]
    depth = 2
    for level, slug, text in listed:
        while depth < level:
            out.append("<ul>")
            depth += 1
        while depth > level:
            out.append("</ul>")
            depth -= 1
        out.append('<li><a href="#%s">%s</a></li>' % (slug, html.escape(text)))
    while depth > 2:
        out.append("</ul>")
        depth -= 1
    out += ["</ul>", "</div>"]
    return "\n".join(out)


def _read_version(root: Path) -> str:
    """Read the version from the package rather than restating it.

    Restating it here would create a fifth place where the version lives, and
    tests/test_metadata_consistency.py already exists because four was one too
    many.
    """
    init = root / "corpusslr" / "__init__.py"
    if init.exists():
        match = re.search(r"^__version__\s*=\s*[\"']([^\"']+)[\"']",
                          init.read_text(encoding="utf-8"), re.M)
        if match:
            return match.group(1)
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        match = re.search(r"^version\s*=\s*[\"']([^\"']+)[\"']",
                          pyproject.read_text(encoding="utf-8"), re.M)
        if match:
            return match.group(1)
    raise SiteBuildError("cannot determine the package version")


def _document_title(headings: Sequence[Tuple[int, str, str]], fallback: str) -> str:
    for level, _slug, text in headings:
        if level == 1:
            return text
    return fallback


def render_page(body: str, title: str, description: str, nav_current: str,
                version: str, footer: str) -> str:
    """Wrap a rendered fragment in the page shell."""
    return _HTML_TEMPLATE % {
        "title": html.escape(normalize_dashes(title), quote=True),
        "description": html.escape(normalize_dashes(description), quote=True),
        "css": CSS,
        "nav": _nav_html(nav_current),
        "body": body,
        "version": html.escape(version, quote=True),
        "footer": normalize_dashes(footer),
    }


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def _human_size(size: int) -> str:
    if size < 1024:
        return "%d B" % size
    if size < 1024 * 1024:
        return "%.1f kB" % (size / 1024.0)
    return "%.2f MB" % (size / (1024.0 * 1024.0))


def _build_link_map(root: Path, out_dir: Path) -> Dict[str, str]:
    link_map: Dict[str, str] = {}
    for page in PAGES:
        link_map[page.source] = page.output
        # A sibling reference such as `user_guide.md` from inside docs/.
        link_map[Path(page.source).name] = page.output
    for rel in COPIED_FILES:
        if (root / rel).exists():
            link_map[rel] = "files/" + Path(rel).name
            link_map[Path(rel).name] = "files/" + Path(rel).name
    link_map.update(EXTRA_LINK_MAP)
    del out_dir  # signature kept symmetrical with the callers below
    return link_map


def _copy_evidence(root: Path, out_dir: Path) -> Tuple[List[Tuple[str, int, str]],
                                                       List[Tuple[str, int]]]:
    """Copy validation artefacts into the site.

    Returns `(copied, skipped)`, where copied entries are
    `(name, size, destination)` and skipped entries are `(name, size)` for the
    files held back by `EVIDENCE_MAX_BYTES`.
    """
    src_dir = root / "validation"
    files_dir = out_dir / "files"
    assets_dir = out_dir / "assets"
    files_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    copied: List[Tuple[str, int, str]] = []
    skipped: List[Tuple[str, int]] = []
    seen: set = set()
    for pattern in EVIDENCE_PATTERNS:
        for path in sorted(src_dir.glob(pattern)):
            if path.name in seen:
                continue
            seen.add(path.name)
            size = path.stat().st_size
            if size > EVIDENCE_MAX_BYTES:
                skipped.append((path.name, size))
                continue
            target_dir = assets_dir if path.suffix == ".png" else files_dir
            shutil.copy2(path, target_dir / path.name)
            rel = "%s/%s" % (target_dir.name, path.name)
            copied.append((path.name, size, rel))

    for rel in COPIED_FILES:
        source = root / rel
        if source.exists():
            shutil.copy2(source, files_dir / source.name)
    return copied, skipped


def _evidence_body(root: Path, copied: Sequence[Tuple[str, int, str]],
                   skipped: Sequence[Tuple[str, int]]) -> str:
    parts: List[str] = ['<h1 id="evidence-files">Evidence files</h1>']
    parts.append(
        "<p>Every accuracy figure quoted in the documentation is computed by a "
        "script in <code>validation/</code> and written to one of the files "
        "below. They are published with the site so that a reader can check a "
        "number without cloning the repository. The scripts run offline; none "
        "of them contacts a bibliographic API.</p>")

    for rel, caption in FEATURED_FIGURES:
        name = Path(rel).name
        if (root / rel).exists():
            parts.append(
                '<figure><img src="assets/%s" alt="%s" />'
                '<figcaption>%s</figcaption></figure>'
                % (html.escape(name, quote=True),
                   html.escape(normalize_dashes(caption), quote=True),
                   html.escape(normalize_dashes(caption))))

    groups = (
        (".csv", "Recomputed metric tables"),
        (".json", "Verification records"),
        (".png", "Figures"),
    )
    for suffix, label in groups:
        rows = [entry for entry in copied if entry[0].endswith(suffix)]
        if not rows:
            continue
        parts.append('<h2 id="%s">%s</h2>' % (slugify(label), html.escape(label)))
        parts.append('<div class="table-wrap"><table><thead><tr>'
                     "<th>file</th><th style=\"text-align:right\">size</th>"
                     "</tr></thead><tbody>")
        for name, size, dest in rows:
            parts.append('<tr><td><a href="%s"><code>%s</code></a></td>'
                         '<td style="text-align:right">%s</td></tr>'
                         % (html.escape(dest, quote=True), html.escape(name),
                            _human_size(size)))
        parts.append("</tbody></table></div>")

    if skipped:
        parts.append('<h2 id="not-published-here">Not published here</h2>')
        parts.append(
            "<p>These inputs are held back from the site because of size. They "
            "ship in the source distribution and in the Zenodo deposit, and "
            "each is regenerable by the script that consumes it.</p>")
        parts.append('<div class="table-wrap"><table><thead><tr><th>file</th>'
                     '<th style="text-align:right">size</th></tr></thead><tbody>')
        for name, size in skipped:
            parts.append('<tr><td><code>validation/%s</code></td>'
                         '<td style="text-align:right">%s</td></tr>'
                         % (html.escape(name), _human_size(size)))
        parts.append("</tbody></table></div>")

    parts.append('<h2 id="worked-examples">Worked examples</h2>')
    parts.append("<ul>")
    for rel in COPIED_FILES:
        if (root / rel).exists():
            name = Path(rel).name
            parts.append('<li><a href="files/%s"><code>%s</code></a></li>'
                         % (html.escape(name, quote=True), html.escape(rel)))
    parts.append("</ul>")
    return "\n".join(parts)


def _index_cards() -> str:
    parts = ['<div class="cards">']
    for page in PAGES[1:]:
        parts.append('<div class="card"><a href="%s">%s</a><p>%s</p></div>'
                     % (page.output, html.escape(page.nav_title),
                        html.escape(normalize_dashes(page.blurb))))
    parts.append('<div class="card"><a href="%s">%s</a>'
                 "<p>Recomputed metric tables, verification records and figures.</p>"
                 "</div>" % (EVIDENCE_OUTPUT, EVIDENCE_TITLE))
    parts.append("</div>")
    return "\n".join(parts)


def build_site(root: Optional[Path] = None, out_dir: Optional[Path] = None,
               clean: bool = False) -> Dict[str, object]:
    """Render the whole site and return a report about what was written.

    The report is what the test suite asserts on, so it carries counts rather
    than being printed and discarded: written files, headings per page,
    unresolved links and any dash violation found in the output.
    """
    root = Path(root) if root is not None else REPO_ROOT
    out_dir = Path(out_dir) if out_dir is not None else root / "site"
    if clean and out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    version = _read_version(root)
    link_map = _build_link_map(root, out_dir)
    copied, skipped = _copy_evidence(root, out_dir)

    footer = ("CorpusSLR %s, MIT licence. Generated from the repository "
              "markdown by tools/build_site.py using the standard library "
              "only; no external requests, no JavaScript." % version)

    written: List[str] = []
    headings_by_page: Dict[str, List[Tuple[int, str, str]]] = {}
    unresolved: Dict[str, List[str]] = {}
    missing_sources: List[str] = []

    for page in PAGES:
        source = root / page.source
        if not source.exists():
            missing_sources.append(page.source)
            continue
        text = source.read_text(encoding="utf-8")
        body, headings, bad = markdown_to_html(text, link_map=link_map)
        if bad:
            unresolved[page.output] = sorted(set(bad))
        toc = _toc_html(headings)
        extra = _index_cards() if page.output == "index.html" else ""
        title_text = _document_title(headings, page.nav_title)
        # SUPPLEMENTARY.md opens with "Supplementary material - CorpusSLR
        # 1.7.0", so appending the version unconditionally produced a title
        # that named the release twice.
        if page.output == "index.html":
            full_title = "CorpusSLR %s documentation" % version
        elif version in title_text:
            full_title = title_text
        else:
            full_title = "%s - CorpusSLR %s" % (title_text, version)
        page_html = render_page(
            body="\n".join(part for part in (extra, toc, body) if part),
            title=full_title,
            description=page.blurb or title_text,
            nav_current=page.output,
            version=version,
            footer=footer,
        )
        (out_dir / page.output).write_text(page_html, encoding="utf-8")
        written.append(page.output)
        headings_by_page[page.output] = headings

    evidence_html = render_page(
        body=_evidence_body(root, copied, skipped),
        title="Evidence files - CorpusSLR %s" % version,
        description="Recomputed metric tables, verification records and figures.",
        nav_current=EVIDENCE_OUTPUT,
        version=version,
        footer=footer,
    )
    (out_dir / EVIDENCE_OUTPUT).write_text(evidence_html, encoding="utf-8")
    written.append(EVIDENCE_OUTPUT)

    # GitHub Pages runs Jekyll by default, which drops files and directories
    # beginning with an underscore. Nothing here starts with one today, but the
    # marker costs one empty file and removes a class of surprise later.
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")

    dash_hits: Dict[str, List[Tuple[int, str, str]]] = {}
    for name in written:
        hits = find_dash_violations((out_dir / name).read_text(encoding="utf-8"))
        if hits:
            dash_hits[name] = hits

    if missing_sources:
        raise SiteBuildError("source documents missing: %s"
                             % ", ".join(missing_sources))
    if unresolved:
        raise SiteBuildError("unresolved internal links: %r" % unresolved)
    if dash_hits:
        raise SiteBuildError("long dashes in generated HTML: %r" % dash_hits)

    return {
        "out_dir": str(out_dir),
        "version": version,
        "pages": written,
        "headings": {name: len(items) for name, items in headings_by_page.items()},
        "evidence_copied": len(copied),
        "evidence_skipped": [name for name, _ in skipped],
        "unresolved_links": unresolved,
        "dash_violations": dash_hits,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the CorpusSLR documentation site (standard library only).")
    parser.add_argument("--out", default=None,
                        help="output directory (default: ./site next to the repository)")
    parser.add_argument("--root", default=None,
                        help="repository root (default: the parent of tools/)")
    parser.add_argument("--clean", action="store_true",
                        help="remove the output directory before building")
    parser.add_argument("--quiet", action="store_true",
                        help="print nothing on success")
    args = parser.parse_args(argv)

    try:
        report = build_site(root=args.root, out_dir=args.out, clean=args.clean)
    except SiteBuildError as err:
        print("site build failed: %s" % err, file=sys.stderr)
        return 1

    if not args.quiet:
        pages = report["pages"]
        assert isinstance(pages, list)
        print("wrote %d pages to %s" % (len(pages), report["out_dir"]))
        for name in pages:
            print("  %s" % name)
        print("evidence files copied: %s" % report["evidence_copied"])
        skipped = report["evidence_skipped"]
        assert isinstance(skipped, list)
        if skipped:
            print("held back for size: %s" % ", ".join(skipped))
        print("no long dashes in the generated HTML")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
