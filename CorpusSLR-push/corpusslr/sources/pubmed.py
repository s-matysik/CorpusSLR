"""PubMed/MEDLINE client via NCBI E-utilities (esearch history + efetch XML)."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import List

from ..corpus import SourceResult
from ..query import SearchQuery
from ..record import Record
from .base import BaseSource

_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


def _text(el) -> str:
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


def parse_pubmed_xml(xml_text: str) -> List[Record]:
    """Parse a PubMed ``efetch`` XML response into records.

    Used by :class:`PubMedSource` and exposed separately because PubMed XML is
    also what a manual "Send to → File → XML" download produces, so a corpus can
    be built from a browser export without an API key.
    """
    root = ET.fromstring(xml_text)
    out: List[Record] = []
    for art in root.findall(".//PubmedArticle"):
        cit = art.find("MedlineCitation")
        if cit is None:
            continue
        pmid = _text(cit.find("PMID"))
        a = cit.find("Article")
        if a is None:
            continue
        title = _text(a.find("ArticleTitle"))
        abstract = " ".join(
            (("{}: ".format(t.get("Label")) if t.get("Label") else "") + _text(t))
            for t in a.findall("Abstract/AbstractText")).strip()
        authors = []
        for au in a.findall("AuthorList/Author"):
            ln, fn = _text(au.find("LastName")), _text(au.find("ForeName"))
            if ln:
                authors.append(f"{ln}, {fn}" if fn else ln)
            else:
                coll = _text(au.find("CollectiveName"))
                if coll:
                    authors.append(coll)
        journal = _text(a.find("Journal/Title"))
        issn = _text(a.find("Journal/ISSN"))
        ji = a.find("Journal/JournalIssue")
        year = None
        if ji is not None:
            y = _text(ji.find("PubDate/Year"))
            if not y:
                md = _text(ji.find("PubDate/MedlineDate"))
                y = md[:4] if md[:4].isdigit() else ""
            if y.isdigit():
                year = int(y)
        volume = _text(ji.find("Volume")) if ji is not None else ""
        issue = _text(ji.find("Issue")) if ji is not None else ""
        pages = _text(a.find("Pagination/MedlinePgn"))
        doi = ""
        for el in a.findall("ELocationID"):
            if el.get("EIdType") == "doi":
                doi = _text(el)
        if not doi:
            for el in art.findall("PubmedData/ArticleIdList/ArticleId"):
                if el.get("IdType") == "doi":
                    doi = _text(el)
        lang = _text(a.find("Language")).lower()
        ptypes = [_text(p).lower() for p in
                  a.findall("PublicationTypeList/PublicationType")]
        doc_type = ("review" if "review" in ptypes
                    else "article" if "journal article" in ptypes
                    else (ptypes[0] if ptypes else ""))
        kws = [_text(k) for k in cit.findall("KeywordList/Keyword")]
        kws += [_text(m.find("DescriptorName"))
                for m in cit.findall("MeshHeadingList/MeshHeading")]
        out.append(Record(title=title, abstract=abstract, authors=authors,
                          year=year, journal=journal, doi=doi, pmid=pmid,
                          issn=issn, volume=volume, issue=issue, pages=pages,
                          doc_type=doc_type, language=lang,
                          keywords=[k for k in kws if k],
                          source="PubMed", source_id=pmid))
    return out


class PubMedSource(BaseSource):
    name = "PubMed"
    platform = "NCBI Entrez"

    def __init__(self, email: str = "", api_key: str = "", **kw):
        super().__init__(mailto=email, **kw)
        self.email = email
        self.api_key = api_key
        self.min_interval = 0.12 if api_key else 0.36  # 10/s vs 3/s

    def _base_params(self) -> dict:
        p = {"db": "pubmed", "tool": "CorpusSLR"}
        if self.email:
            p["email"] = self.email
        if self.api_key:
            p["api_key"] = self.api_key
        return p

    def search(self, query: SearchQuery, max_results: int = 2000) -> SourceResult:
        term = query.to_pubmed()
        p = self._base_params()
        p.update({"term": term, "retmax": 0, "usehistory": "y"})
        r = self._get(_ESEARCH, params=p)
        root = ET.fromstring(r.text)
        count = int(_text(root.find("Count")) or 0)
        webenv = _text(root.find("WebEnv"))
        qkey = _text(root.find("QueryKey"))
        records: List[Record] = []
        step = 200
        for start in range(0, min(count, max_results), step):
            fp = self._base_params()
            fp.update({"query_key": qkey, "WebEnv": webenv,
                       "retstart": start,
                       "retmax": min(step, max_results - start),
                       "retmode": "xml"})
            fr = self._get(_EFETCH, params=fp)
            records += parse_pubmed_xml(fr.text)
            if len(records) >= max_results:
                records = records[:max_results]
                break
        ev = self._event(term, filters="E-utilities history server",
                         url=_ESEARCH,
                         notes=f"Count={count}; capped at max_results={max_results}")
        return SourceResult(event=ev, records=records)
