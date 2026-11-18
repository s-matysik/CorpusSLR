"""Validate the query compiler against hand-written reference queries.

A reviewer noted that translating one structured query into the syntax of each
database is a central function and that no validation of the generated queries
was presented. This script supplies two layers.

1. Syntax (offline, runs in the test suite). Every compiled string must have
   balanced parentheses and quotation marks, carry the requested year bounds
   and contain every search phrase. These are necessary conditions; they cannot
   show that a database reads the string as intended.

2. Semantics (live, ``--live``). For each case a reference query was written by
   hand, independently of the compiler, from the vendor's search documentation,
   in the way a librarian would write it (``[tiab]`` rather than
   ``[Title/Abstract]``, ``PUBYEAR AFT`` rather than ``PUBYEAR >``). Both the
   compiled and the reference string are run against the same service on the
   same day and the numbers of hits are compared. Equal counts are evidence
   that the database reads the two strings as the same search; unequal counts
   locate a translation defect. This is the criterion Clark et al. (2020) used
   for the Polyglot Search Translator, whose translations were scored against a
   reference translation by the number of records they retrieve.

Limits, stated because they matter. Equal counts do not prove equal result
sets (two different searches can retrieve the same number of records), and the
reference queries were written by the author of the compiler, so a shared
misunderstanding of a database would pass. Databases are queried at one moment,
so a drift in the index between the two calls of one case would show as a
difference; each case therefore queries the pair back to back. Only PubMed,
Scopus and Web of Science are covered, the three with an API this project holds
access to. No query is run against Polyglot, which is an interactive service
and translates from PubMed or Ovid MEDLINE syntax, a different input than a
structured specification.

Credentials come from the environment only (``SCOPUS_API_KEY``,
``SCOPUS_INSTTOKEN``, ``WOS_API_KEY``) and are never written anywhere.

    PYTHONPATH=. python validation/validate_query_compiler.py --live
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "query_compiler_validation.csv")

#: id, description, structured specification, hand-written reference per database
CASES = (
    ("Q01", "one block, two phrases",
     dict(blocks=[["machine learning", "deep learning"]]),
     dict(pubmed='("machine learning"[tiab] OR "deep learning"[tiab])',
          scopus='TITLE-ABS-KEY("machine learning" OR "deep learning")',
          wos='TS=("machine learning" OR "deep learning")')),
    ("Q02", "two blocks joined by AND, year range",
     dict(blocks=[["machine learning", "deep learning"], ["systematic review", "meta-analysis"]],
          years=(2015, 2024)),
     dict(pubmed='("machine learning"[tiab] OR "deep learning"[tiab]) AND '
                 '("systematic review"[tiab] OR "meta-analysis"[tiab]) AND 2015:2024[dp]',
          scopus='TITLE-ABS-KEY("machine learning" OR "deep learning") AND '
                 'TITLE-ABS-KEY("systematic review" OR "meta-analysis") AND '
                 'PUBYEAR AFT 2014 AND PUBYEAR BEF 2025',
          wos='TS=(("machine learning" OR "deep learning") AND '
              '("systematic review" OR "meta-analysis")) AND PY=(2015-2024)')),
    ("Q03", "title field only",
     dict(blocks=[["machine learning", "deep learning"], ["systematic review"]],
          years=(2018, 2022), title_only=True),
     dict(pubmed='("machine learning"[ti] OR "deep learning"[ti]) AND "systematic review"[ti] '
                 'AND 2018:2022[dp]',
          scopus='TITLE("machine learning" OR "deep learning") AND TITLE("systematic review") '
                 'AND PUBYEAR AFT 2017 AND PUBYEAR BEF 2023',
          wos='TI=(("machine learning" OR "deep learning") AND "systematic review") '
              'AND PY=(2018-2022)')),
    ("Q04", "hyphen and capitals in terms",
     dict(blocks=[["COVID-19", "SARS-CoV-2"], ["vaccine hesitancy"]], years=(2021, 2023)),
     dict(pubmed='("COVID-19"[tiab] OR "SARS-CoV-2"[tiab]) AND "vaccine hesitancy"[tiab] '
                 'AND 2021:2023[dp]',
          scopus='TITLE-ABS-KEY("COVID-19" OR "SARS-CoV-2") AND TITLE-ABS-KEY("vaccine hesitancy") '
                 'AND PUBYEAR AFT 2020 AND PUBYEAR BEF 2024',
          wos='TS=(("COVID-19" OR "SARS-CoV-2") AND "vaccine hesitancy") AND PY=(2021-2023)')),
    ("Q05", "apostrophe inside a phrase",
     dict(blocks=[["Alzheimer's disease"], ["biomarker"]], years=(2015, 2020)),
     dict(pubmed='"Alzheimer\'s disease"[tiab] AND biomarker[tiab] AND 2015:2020[dp]',
          scopus='TITLE-ABS-KEY("Alzheimer\'s disease") AND TITLE-ABS-KEY(biomarker) '
                 'AND PUBYEAR AFT 2014 AND PUBYEAR BEF 2021',
          wos='TS=("Alzheimer\'s disease" AND biomarker) AND PY=(2015-2020)')),
    ("Q06", "non-ASCII letter",
     dict(blocks=[["Schr\u00f6dinger equation"], ["numerical method"]], years=(2010, 2020)),
     dict(pubmed='"Schr\u00f6dinger equation"[tiab] AND "numerical method"[tiab] AND 2010:2020[dp]',
          scopus='TITLE-ABS-KEY("Schr\u00f6dinger equation") AND TITLE-ABS-KEY("numerical method") '
                 'AND PUBYEAR AFT 2009 AND PUBYEAR BEF 2021',
          wos='TS=("Schr\u00f6dinger equation" AND "numerical method") AND PY=(2010-2020)')),
    ("Q07", "document type and language",
     dict(blocks=[["climate change"], ["adaptation"]], years=(2015, 2020),
          doc_types=["review"], languages=["english"]),
     dict(pubmed='"climate change"[tiab] AND adaptation[tiab] AND 2015:2020[dp] AND review[pt] '
                 'AND english[la]',
          scopus='TITLE-ABS-KEY("climate change") AND TITLE-ABS-KEY(adaptation) '
                 'AND PUBYEAR AFT 2014 AND PUBYEAR BEF 2021 AND DOCTYPE(re) AND LANGUAGE(english)',
          wos='TS=("climate change" AND adaptation) AND PY=(2015-2020) AND DT=Review '
              'AND LA=English')),
    ("Q08", "single term, no filters",
     dict(blocks=[["bibliometrics"]]),
     dict(pubmed='bibliometrics[tiab]', scopus='TITLE-ABS-KEY(bibliometrics)',
          wos='TS=(bibliometrics)')),
    ("Q09", "three blocks",
     dict(blocks=[["diabetes", "diabetic"], ["metformin"], ["cardiovascular"]],
          years=(2012, 2022)),
     dict(pubmed='(diabetes[tiab] OR diabetic[tiab]) AND metformin[tiab] AND cardiovascular[tiab] '
                 'AND 2012:2022[dp]',
          scopus='TITLE-ABS-KEY(diabetes OR diabetic) AND TITLE-ABS-KEY(metformin) AND '
                 'TITLE-ABS-KEY(cardiovascular) AND PUBYEAR AFT 2011 AND PUBYEAR BEF 2023',
          wos='TS=((diabetes OR diabetic) AND metformin AND cardiovascular) AND PY=(2012-2022)')),
    ("Q10", "truncation inside a quoted phrase",
     dict(blocks=[["econom*"], ["growth"]], years=(2019, 2021)),
     dict(pubmed='econom*[tiab] AND growth[tiab] AND 2019:2021[dp]',
          scopus='TITLE-ABS-KEY(econom*) AND TITLE-ABS-KEY(growth) AND PUBYEAR AFT 2018 '
                 'AND PUBYEAR BEF 2022',
          wos='TS=(econom* AND growth) AND PY=(2019-2021)')),
    ("Q11", "phrase of three words and a synonym block",
     dict(blocks=[["systematic literature review", "scoping review"], ["software", "tool"]],
          years=(2019, 2023)),
     dict(pubmed='("systematic literature review"[tiab] OR "scoping review"[tiab]) AND '
                 '(software[tiab] OR tool[tiab]) AND 2019:2023[dp]',
          scopus='TITLE-ABS-KEY("systematic literature review" OR "scoping review") AND '
                 'TITLE-ABS-KEY(software OR tool) AND PUBYEAR AFT 2018 AND PUBYEAR BEF 2024',
          wos='TS=(("systematic literature review" OR "scoping review") AND '
              '(software OR tool)) AND PY=(2019-2023)')),
    ("Q12", "a single year",
     dict(blocks=[["research data management"]], years=(2020, 2020)),
     dict(pubmed='"research data management"[tiab] AND 2020[dp]',
          scopus='TITLE-ABS-KEY("research data management") AND PUBYEAR IS 2020',
          wos='TS=("research data management") AND PY=(2020)')),
)

COMPILERS = {"pubmed": "to_pubmed", "scopus": "to_scopus", "wos": "to_wos"}


def build(spec):
    from corpusslr import SearchQuery
    return SearchQuery(**spec)


def syntax_problems(db, text, spec):
    """Necessary conditions only; see the module docstring."""
    bad = []
    if text.count("(") != text.count(")"):
        bad.append("unbalanced parentheses")
    if text.count('"') % 2:
        bad.append("unbalanced quotation marks")
    for block in spec["blocks"]:
        for phrase in block:
            if phrase not in text:
                bad.append("phrase missing: %s" % phrase)
    years = spec.get("years")
    if years:
        for y in years:
            if str(y) not in text and str(y - 1) not in text and str(y + 1) not in text:
                bad.append("year bound %s not expressed" % y)
    if re.search(r"\b(AND|OR)\s*(AND|OR)\b", text) or re.search(r"\(\s*\)", text):
        bad.append("empty operand")
    return bad


# --- live counters: raw HTTP on purpose, so the package's own clients are not
# --- part of what is being tested ---------------------------------------------
def _count_pubmed(session, query):
    r = session.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                    params={"db": "pubmed", "term": query, "retmax": 0, "retmode": "json"},
                    timeout=(10, 30))
    r.raise_for_status()
    data = r.json()["esearchresult"]
    if "ERROR" in data:
        raise RuntimeError(data["ERROR"])
    warn = "; ".join(data.get("warninglist", {}).get("outputmessages", [])
                     + data.get("errorlist", {}).get("phrasesnotfound", []))
    return int(data["count"]), warn


def _count_scopus(session, query):
    key = os.environ["SCOPUS_API_KEY"]
    headers = {"X-ELS-APIKey": key, "Accept": "application/json"}
    if os.environ.get("SCOPUS_INSTTOKEN"):
        headers["X-ELS-Insttoken"] = os.environ["SCOPUS_INSTTOKEN"]
    r = session.get("https://api.elsevier.com/content/search/scopus",
                    params={"query": query, "count": 1}, headers=headers, timeout=(10, 30))
    if r.status_code == 400:
        raise RuntimeError("Scopus rejected the query: " + r.text[:120].replace("\n", " "))
    r.raise_for_status()
    return int(r.json()["search-results"]["opensearch:totalResults"]), ""


def _count_wos(session, query):
    r = session.get("https://api.clarivate.com/api/wos",
                    params={"databaseId": "WOS", "usrQuery": query, "count": 1,
                            "firstRecord": 1},
                    headers={"X-ApiKey": os.environ["WOS_API_KEY"], "Accept": "application/json"},
                    timeout=(10, 40))
    if r.status_code in (400, 500):
        raise RuntimeError("Web of Science rejected the query: " + r.text[:120].replace("\n", " "))
    r.raise_for_status()
    return int(r.json()["QueryResult"]["RecordsFound"]), ""


COUNTERS = {"pubmed": _count_pubmed, "scopus": _count_scopus, "wos": _count_wos}


def run(live, databases=None):
    import requests
    session = requests.Session() if live else None
    rows = []
    for cid, desc, spec, refs in CASES:
        q = build(spec)
        for db, meth in COMPILERS.items():
            if databases and db not in databases:
                continue
            compiled = getattr(q, meth)()
            row = {"case": cid, "description": desc, "database": db,
                   "compiled": compiled, "reference": refs[db],
                   "syntax_problems": "; ".join(syntax_problems(db, compiled, spec)) or "none",
                   "count_compiled": "", "count_reference": "", "difference": "",
                   "agreement": "", "note": ""}
            if live:
                try:
                    a, wa = COUNTERS[db](session, compiled)
                    b, wb = COUNTERS[db](session, refs[db])
                    row.update(count_compiled=a, count_reference=b, difference=a - b,
                               agreement="equal" if a == b else "DIFFERENT",
                               note="; ".join(x for x in (wa, wb) if x))
                except Exception as exc:                         # noqa: BLE001
                    row.update(agreement="ERROR", note=str(exc)[:200])
                print('  %s %-7s %s' % (cid, db, row['agreement']), flush=True)
                time.sleep(0.4)
            rows.append(row)
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--databases", nargs="+", choices=sorted(COMPILERS),
                    help="restrict the run (default: all three)")
    args = ap.parse_args(argv)
    rows = run(args.live, args.databases)
    with open(args.out, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    bad = [r for r in rows if r["syntax_problems"] != "none"]
    print("%d compiled strings, %d with syntax problems" % (len(rows), len(bad)))
    if args.live:
        eq = sum(1 for r in rows if r["agreement"] == "equal")
        print("live: %d equal, %d different, %d errors"
              % (eq, sum(r["agreement"] == "DIFFERENT" for r in rows),
                 sum(r["agreement"] == "ERROR" for r in rows)))
        for r in rows:
            if r["agreement"] in ("DIFFERENT", "ERROR"):
                print("  %s %-7s %s  compiled=%s reference=%s %s"
                      % (r["case"], r["database"], r["agreement"], r["count_compiled"],
                         r["count_reference"], r["note"][:90]))
    return 1 if bad else 0


if __name__ == "__main__":                                  # pragma: no cover
    sys.exit(main())
