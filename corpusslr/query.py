"""Single structured query compiled to native syntax of each database.

A :class:`SearchQuery` is a conjunction of OR-blocks (the classic three-block
SLR pattern: technology AND phenomenon AND unit of analysis), plus year range,
document types and languages.  One definition -> identical logic in Scopus,
OpenAlex, PubMed and Crossref, which removes the most common methodological
inconsistency in multi-database SLR searches.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

_SCOPUS_DOCTYPE = {"article": "ar", "review": "re", "conference": "cp",
                   "chapter": "ch", "book": "bk", "editorial": "ed",
                   "letter": "le", "note": "no"}
_PUBMED_DOCTYPE = {"article": "journal article", "review": "review",
                   "conference": "congress", "book": "book"}
_OPENALEX_DOCTYPE = {"article": "article", "review": "review",
                     "conference": "article", "chapter": "book-chapter",
                     "book": "book", "preprint": "preprint"}
_CROSSREF_DOCTYPE = {"article": "journal-article", "review": "journal-article",
                     "conference": "proceedings-article",
                     "chapter": "book-chapter", "book": "book"}
_S2_DOCTYPE = {"article": "JournalArticle", "review": "Review",
               "conference": "Conference", "book": "Book",
               "chapter": "BookSection", "editorial": "Editorial",
               "letter": "LettersAndComments"}
_PUBMED_LANG = {"en": "english", "pl": "polish", "de": "german",
                "fr": "french", "es": "spanish", "it": "italian",
                "pt": "portuguese", "ru": "russian", "zh": "chinese"}
#: Scopus ``LANGUAGE()`` values: English names of languages, not ISO codes.
#: Measured against the live Search API, an ISO code is not translated and not
#: rejected - ``LANGUAGE(ja)`` matched 0 records where ``LANGUAGE(japanese)``
#: matched 1, ``LANGUAGE(de)`` 0 against ``LANGUAGE(german)`` 17 and
#: ``LANGUAGE(zh)`` 0 against ``LANGUAGE(chinese)`` 258, all on the same base
#: query.  An unmapped code therefore silently reduces the whole search to
#: zero hits, which is the most damaging failure mode a query compiler can
#: have: the reviewer sees an empty result set and no error.  The map is
#: deliberately wider than the PubMed one it previously borrowed.
_SCOPUS_LANG = {"en": "english", "pl": "polish", "de": "german",
                "fr": "french", "es": "spanish", "it": "italian",
                "pt": "portuguese", "ru": "russian", "zh": "chinese",
                "ja": "japanese", "nl": "dutch", "cs": "czech",
                "tr": "turkish", "uk": "ukrainian", "ko": "korean",
                "ar": "arabic", "fa": "persian", "he": "hebrew",
                "hu": "hungarian", "sv": "swedish", "no": "norwegian",
                "da": "danish", "fi": "finnish", "el": "greek",
                "ro": "romanian", "sk": "slovak", "sl": "slovenian",
                "hr": "croatian", "sr": "serbian", "bg": "bulgarian",
                "ca": "catalan", "et": "estonian", "lt": "lithuanian",
                "lv": "latvian", "th": "thai", "vi": "vietnamese",
                "id": "indonesian", "ms": "malay", "hi": "hindi"}

#: Web of Science ``DT=`` values.  WoS uses full descriptive labels rather
#: than codes, and "Proceedings Paper" (not "Conference Paper") is the Core
#: Collection label for conference contributions.
_WOS_DOCTYPE = {"article": "Article", "review": "Review",
                "conference": "Proceedings Paper",
                "chapter": "Book Chapter", "book": "Book",
                "editorial": "Editorial Material", "letter": "Letter"}
#: Web of Science ``LA=`` values: English names of languages, not ISO codes.
_WOS_LANG = {"en": "English", "pl": "Polish", "de": "German",
             "fr": "French", "es": "Spanish", "it": "Italian",
             "pt": "Portuguese", "ru": "Russian", "zh": "Chinese",
             "ja": "Japanese", "nl": "Dutch", "cs": "Czech",
             "tr": "Turkish", "uk": "Ukrainian", "ko": "Korean"}


def _clean(term: str) -> str:
    return term.replace('"', "").replace(",", " ").strip()


@dataclass
class SearchQuery:
    """blocks: list of OR-groups, joined with AND."""

    blocks: List[List[str]]
    years: Optional[Tuple[int, int]] = None
    doc_types: List[str] = field(default_factory=list)
    languages: List[str] = field(default_factory=list)
    title_only: bool = False
    warnings: List[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    def _warn(self, message: str) -> None:
        """Record a compilation warning once.

        The compile methods are idempotent by contract and callers legitimately
        invoke them more than once (compile_all(), then a per-source client).
        Appending unconditionally made the list grow on every call, and those
        warnings are reported verbatim in the PRISMA-S appendix.
        """
        if message not in self.warnings:
            self.warnings.append(message)

    # ------------------------------------------------------------------
    def _or_group(self, terms: List[str], quote: bool = True) -> str:
        parts = []
        for t in terms:
            t = _clean(t)
            if not t:
                continue
            parts.append(f'"{t}"' if quote else t)
        return " OR ".join(parts)

    # ------------------------------------------------------------------
    def to_scopus(self) -> str:
        f = "TITLE" if self.title_only else "TITLE-ABS-KEY"
        clauses = [f"{f}({self._or_group(b)})" for b in self.blocks if b]
        if self.years:
            y1, y2 = self.years
            # parenthesized so the two PUBYEAR bounds bind together: emitted
            # bare, they mix with the OR-joined DOCTYPE clause and silently
            # change the query's meaning, which breaks reproducibility of the
            # reported search string (PRISMA-S Item 8)
            clauses.append(f"(PUBYEAR > {y1 - 1} AND PUBYEAR < {y2 + 1})")
        dts = [f"DOCTYPE({_SCOPUS_DOCTYPE[d]})" for d in self.doc_types
               if d in _SCOPUS_DOCTYPE]
        for d in self.doc_types:
            if d not in _SCOPUS_DOCTYPE:
                self._warn(f"Scopus: unsupported doc_type '{d}' ignored")
        if dts:
            clauses.append("(" + " OR ".join(dts) + ")")
        if self.languages:
            names = []
            for lang in self.languages:
                key = str(lang).strip().lower()
                if key in _SCOPUS_LANG:
                    names.append(_SCOPUS_LANG[key])
                elif len(key) > 3:
                    # Already a language name rather than a code: Scopus accepts
                    # any name it knows and matching is case-insensitive
                    # (LANGUAGE(English) and LANGUAGE(english) both returned
                    # 18435 hits on the same query), so pass it through.
                    names.append(key)
                else:
                    # A two/three-letter code outside the map would compile to
                    # a clause matching zero records and silently empty the
                    # whole search; dropping it keeps the search valid and the
                    # loss of the restriction is reported to the PRISMA-S
                    # appendix instead.
                    self._warn(
                        f"Scopus: language code '{lang}' has no known "
                        f"LANGUAGE() name; the clause was omitted because an "
                        f"untranslated code matches zero records and would "
                        f"silently empty the entire search - restrict this "
                        f"language during screening instead")
            names = list(dict.fromkeys(names))
            if names:
                langs = " OR ".join(names)
                clauses.append(f"LANGUAGE({langs})")
        return " AND ".join(f"({c})" if " OR " in c and not c.startswith("(")
                            else c for c in clauses)

    # ------------------------------------------------------------------
    def to_openalex_filters(self) -> Dict[str, str]:
        f: Dict[str, str] = {}
        expr = " AND ".join(f"({self._or_group(b)})" for b in self.blocks if b)
        key = "title.search" if self.title_only else "title_and_abstract.search"
        f[key] = expr
        if self.years:
            f["from_publication_date"] = f"{self.years[0]}-01-01"
            f["to_publication_date"] = f"{self.years[1]}-12-31"
        types = []
        for d in self.doc_types:
            if d in _OPENALEX_DOCTYPE:
                types.append(_OPENALEX_DOCTYPE[d])
            else:
                self._warn(f"OpenAlex: unsupported doc_type '{d}' ignored")
        if types:
            f["type"] = "|".join(dict.fromkeys(types))
        if self.languages:
            f["language"] = "|".join(self.languages)
        return f

    def to_openalex(self) -> str:
        return ",".join(f"{k}:{v}" for k, v in self.to_openalex_filters().items())

    # ------------------------------------------------------------------
    def to_pubmed(self) -> str:
        tag = "[Title]" if self.title_only else "[Title/Abstract]"
        clauses = []
        for b in self.blocks:
            terms = [f'"{_clean(t)}"{tag}' for t in b if _clean(t)]
            if terms:
                clauses.append("(" + " OR ".join(terms) + ")")
        if self.years:
            clauses.append(f"{self.years[0]}:{self.years[1]}[dp]")
        dts = []
        for d in self.doc_types:
            if d in _PUBMED_DOCTYPE:
                dts.append(f'"{_PUBMED_DOCTYPE[d]}"[pt]')
            else:
                self._warn(f"PubMed: unsupported doc_type '{d}' ignored")
        if dts:
            clauses.append("(" + " OR ".join(dts) + ")")
        if self.languages:
            ls = [f"{_PUBMED_LANG.get(lang, lang)}[la]"
                  for lang in self.languages]
            clauses.append("(" + " OR ".join(ls) + ")")
        return " AND ".join(clauses)

    # ------------------------------------------------------------------
    def to_crossref_params(self) -> Dict[str, str]:
        """Crossref has no boolean field search: lossy 'query.bibliographic'."""
        terms = " ".join(_clean(t) for b in self.blocks for t in b[:3])
        self._warn(
            "Crossref: boolean logic not supported by the API; "
            "query flattened to relevance search - treat Crossref as a "
            "supplementary source (Gusenbauer & Haddaway, 2020).")
        params = {"query.bibliographic": terms}
        filters = []
        if self.years:
            filters.append(f"from-pub-date:{self.years[0]}-01-01")
            filters.append(f"until-pub-date:{self.years[1]}-12-31")
        types = []
        for d in self.doc_types:
            if d in _CROSSREF_DOCTYPE:
                types.append(f"type:{_CROSSREF_DOCTYPE[d]}")
            else:
                self._warn(f"Crossref: unsupported doc_type '{d}' ignored")
        filters += list(dict.fromkeys(types))
        if self.languages:
            self._warn("Crossref: language filter not reliable; ignored")
        if filters:
            params["filter"] = ",".join(filters)
        return params

    # ------------------------------------------------------------------
    def to_semanticscholar(self) -> Dict[str, str]:
        """Semantic Scholar Graph API: relevance search, no boolean operators.

        The ``/paper/search`` endpoint applies its own relevance ranking to a
        plain term string; parentheses, quoted phrases and ``AND``/``OR`` are
        not honoured as boolean operators.  The block structure is therefore
        flattened exactly as for Crossref, and the loss is recorded in
        :attr:`warnings` so that it reaches the PRISMA-S appendix instead of
        being silently presented as a reproducible search.
        """
        terms = " ".join(_clean(t) for b in self.blocks for t in b[:3]
                         if _clean(t))
        self._warn(
            "Semantic Scholar: the Graph API /paper/search endpoint has no "
            "boolean field syntax; the query was flattened to a relevance "
            "search and the result set is ranked, not exhaustive - report it "
            "as a supplementary source (Gusenbauer & Haddaway, 2020).")
        params: Dict[str, str] = {"query": terms}
        if self.years:
            params["year"] = "{}-{}".format(self.years[0], self.years[1])
        types = []
        for d in self.doc_types:
            if d in _S2_DOCTYPE:
                types.append(_S2_DOCTYPE[d])
            else:
                self._warn(
                    "Semantic Scholar: unsupported doc_type '%s' ignored" % d)
        if types:
            params["publicationTypes"] = ",".join(dict.fromkeys(types))
        if self.title_only:
            self._warn(
                "Semantic Scholar: title-only restriction is not supported by "
                "the search endpoint; the query also matches abstracts.")
        if self.languages:
            self._warn(
                "Semantic Scholar: no language filter in the API; "
                "restrict languages during screening.")
        return params

    # ------------------------------------------------------------------
    def to_arxiv(self) -> str:
        """arXiv Atom API query string (``search_query`` parameter).

        arXiv supports prefixed fields and boolean operators, so the block
        structure survives: each OR-group becomes a parenthesised disjunction
        over ``all:`` (or ``ti:`` when :attr:`title_only`), and the groups are
        joined with ``AND``.  Date, language and document-type limits have no
        counterpart in the API and are reported as warnings; year filtering is
        applied client-side by :class:`corpusslr.sources.arxiv.ArxivSource`.
        """
        field_prefix = "ti" if self.title_only else "all"
        clauses = []
        for b in self.blocks:
            terms = ['{}:"{}"'.format(field_prefix, _clean(t))
                     for t in b if _clean(t)]
            if terms:
                clauses.append("(" + " OR ".join(terms) + ")")
        if self.doc_types:
            self._warn(
                "arXiv: no document-type filter (every record is a preprint); "
                "doc_types ignored.")
        if self.languages:
            self._warn(
                "arXiv: no language filter in the API; language was not "
                "restricted at search time.")
        if self.years:
            self._warn(
                "arXiv: the Atom API has no reliable publication-year filter; "
                "the year range is applied client-side after retrieval.")
        return " AND ".join(clauses)

    # ------------------------------------------------------------------
    def to_wos(self) -> str:
        """Web of Science advanced-search string (Starter/Expanded API ``q``).

        Web of Science is a *principal* search system in the sense of
        Gusenbauer & Haddaway (2020): it supports field-tagged boolean queries,
        so the block structure survives compilation intact and the emitted
        string is the reproducible search of PRISMA-S Item 8.

        Field choice follows the same title/abstract/keyword logic as the
        Scopus compiler: ``TS=`` ("Topic") searches title, abstract, author
        keywords and Keywords Plus, and is the WoS counterpart of
        ``TITLE-ABS-KEY``; ``TI=`` restricts to the title when
        :attr:`title_only` is set.  Unlike Scopus, WoS requires the field tag
        to be repeated on every clause - ``TS=(...) AND TS=(...)`` - because a
        bare parenthesised group after ``AND`` inherits no field and is
        interpreted against the default index.  Year, document type and
        language are expressed as their own tagged clauses (``PY=``, ``DT=``,
        ``LA=``), which is what makes them visible in the search string a
        reviewer copies into the appendix rather than hidden UI refinements.

        Note that ``DT=`` and ``LA=`` take WoS's own descriptive labels
        ("Proceedings Paper", "English"), not codes or ISO tags; document
        types outside :data:`_WOS_DOCTYPE` and language codes outside
        :data:`_WOS_LANG` are reported through :meth:`_warn` so the omission
        reaches the PRISMA-S appendix.
        """
        tag = "TI" if self.title_only else "TS"
        clauses = []
        for b in self.blocks:
            group = self._or_group(b)
            if group:
                clauses.append("{}=({})".format(tag, group))
        if self.years:
            y1, y2 = self.years
            clauses.append("PY={}-{}".format(y1, y2))
        dts = []
        for d in self.doc_types:
            if d in _WOS_DOCTYPE:
                dts.append(_WOS_DOCTYPE[d])
            else:
                self._warn(
                    "Web of Science: unsupported doc_type '{}' ignored".format(d))
        if dts:
            clauses.append("DT=({})".format(" OR ".join(dict.fromkeys(dts))))
        langs = []
        for lang in self.languages:
            if lang in _WOS_LANG:
                langs.append(_WOS_LANG[lang])
            else:
                # An unmapped code is passed through: WoS accepts any language
                # name it knows, and silently dropping the restriction would
                # widen the search beyond what the protocol declares.
                langs.append(str(lang))
                self._warn(
                    "Web of Science: language code '{}' not in the ISO->WoS "
                    "name map; passed through verbatim - verify it against "
                    "the WoS language list".format(lang))
        if langs:
            clauses.append("LA=({})".format(" OR ".join(dict.fromkeys(langs))))
        return " AND ".join(clauses)

    # ------------------------------------------------------------------
    def compile_all(self) -> Dict[str, object]:
        out: Dict[str, object] = {
            "scopus": self.to_scopus(),
            "wos": self.to_wos(),
            "openalex": self.to_openalex(),
            "pubmed": self.to_pubmed(),
            "crossref": self.to_crossref_params(),
            "semanticscholar": self.to_semanticscholar(),
            "arxiv": self.to_arxiv(),
        }
        out["warnings"] = list(dict.fromkeys(self.warnings))
        return out
