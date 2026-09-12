"""Publication-integrity flags.

Every title form here was observed in a live corpus of 323 records retrieved
from Scopus, PubMed, Crossref and arXiv on a deep-learning/retinopathy query:
four records carried a retraction marker, including a retraction notice and the
retracted article it refers to, published five years apart in the same journal
(Crossref ``issued`` 2019 and 2024, verified at the source).

Note the trap in the DOIs themselves: the retracted article is
``10.1007/s00521-018-03974-0`` while Crossref records it as issued in 2019. The
year-like segment of a DOI is a minting artifact and is NOT the publication year
-- reading it as one is how this docstring first claimed a six-year gap.
"""
import json

import pytest

from corpusslr import (EXCLUDING_FLAGS, NOTICE_FLAGS, Record,
                       check_retractions_crossref, deduplicate, integrity_flag,
                       integrity_markdown, retraction_flags)

# Observed verbatim in the live corpus.
LIVE_TITLES = {
    "Retraction Note: An enhanced diabetic retinopathy detection and "
    "classification approach": "retraction_notice",
    "RETRACTED ARTICLE: An enhanced diabetic retinopathy detection and "
    "classification approach": "retracted",
    "Retracted: 3D Convolutional Neural Network Framework with Deep Learning":
        "retracted",
    "RETRACTED ARTICLE: Efficient diabetic retinopathy detection using "
    "convolutional neural network": "retracted",
}

OTHER_FORMS = {
    "Retraction: A study of things": "retraction_notice",
    "Retraction statement: A study of things": "retraction_notice",
    "WITHDRAWN: Preliminary results": "withdrawn",
    "Withdrawal notice: Preliminary results": "withdrawn",
    "Expression of Concern: A study of things": "concern",
    "Erratum: A study of things": "erratum",
    "Corrigendum to: A study of things": "erratum",
}

CLEAN = [
    "Deep learning for diabetic retinopathy screening",
    "A retrospective cohort of retinal imaging",          # 'retro', not 'retracted'
    "Concerning trends in retinal screening uptake",      # 'concerning', not a notice
    "Correction factors in optical coherence tomography",  # 'correction' mid-title
]


@pytest.mark.parametrize("title,expected", sorted(LIVE_TITLES.items()))
def test_titles_observed_in_a_live_corpus_are_flagged(title, expected):
    assert integrity_flag(Record(title=title)) == expected


@pytest.mark.parametrize("title,expected", sorted(OTHER_FORMS.items()))
def test_other_publisher_conventions_are_flagged(title, expected):
    assert integrity_flag(Record(title=title)) == expected


@pytest.mark.parametrize("title", CLEAN)
def test_ordinary_titles_are_not_flagged(title):
    """False positives cost a reviewer real time, so the words alone must not fire."""
    assert integrity_flag(Record(title=title)) is None


def test_document_type_is_authoritative_over_the_title():
    """A database that types a record as a retraction is making a statement."""
    rec = Record(title="An enhanced detection approach", doc_type="retraction")
    assert integrity_flag(rec) == "retraction_notice"
    rec2 = Record(title="An enhanced detection approach",
                  doc_type="Retracted Publication")
    assert integrity_flag(rec2) == "retracted"


def test_the_report_separates_studies_to_exclude_from_notices():
    """A retraction notice is a publication in its own right, not an excluded study."""
    recs = [Record(title=t, doi="10.5001/%d" % i)
            for i, t in enumerate(LIVE_TITLES)]
    recs += [Record(title=t, doi="10.5002/%d" % i) for i, t in enumerate(CLEAN)]
    rep = retraction_flags(recs)
    assert rep["n_records"] == len(recs)
    assert rep["n_flagged"] == len(LIVE_TITLES)
    assert len(rep["excluded_candidates"]) == 3
    assert len(rep["notices"]) == 1
    assert all(integrity_flag(r) in EXCLUDING_FLAGS
               for r in rep["excluded_candidates"])
    assert all(integrity_flag(r) in NOTICE_FLAGS for r in rep["notices"])


def test_the_report_states_the_limit_of_the_check():
    """Silence about recall would invite the check to be read as a clearance."""
    rep = retraction_flags([Record(title="A study")])
    assert "lower bound" in rep["caveat"]
    assert "Retraction Watch" in rep["caveat"] or "Crossref" in rep["caveat"]


def test_a_notice_and_its_retracted_article_are_not_merged():
    """Merging them would hide the retraction behind the article it retracts."""
    notice = Record(title="Retraction Note: An enhanced diabetic retinopathy "
                          "detection and classification approach",
                    doi="10.1007/s00521-024-10040-5", year=2024,
                    journal="Neural Computing and Applications")
    article = Record(title="RETRACTED ARTICLE: An enhanced diabetic retinopathy "
                           "detection and classification approach",
                     doi="10.1007/s00521-018-03974-0", year=2019,
                     journal="Neural Computing and Applications")
    res = deduplicate([notice, article])
    assert res.report.after == 2, "the notice must survive as its own record"


def test_markdown_is_usable_in_a_methods_section():
    recs = [Record(title=t, doi="10.5001/%d" % i) for i, t in enumerate(LIVE_TITLES)]
    md = integrity_markdown(recs)
    assert "Publication-integrity check" in md
    assert "must not enter synthesis" in md
    assert "lower bound" in md


def test_markdown_says_so_when_nothing_is_flagged():
    md = integrity_markdown([Record(title="Deep learning for screening")])
    assert "No record" in md
    assert "lower bound" in md          # the caveat still applies


# ---------------------------------------------------------------------------
# The Crossref escalation path, against recorded responses. The two payloads
# reproduce what the live API returned for the retracted article and its notice.
# ---------------------------------------------------------------------------
class _Resp:
    def __init__(self, payload):
        self._p, self.status_code, self.headers = payload, 200, {}
        self.text = json.dumps(payload)

    def json(self):
        return self._p

    def raise_for_status(self):
        return None


class _Session:
    def __init__(self, by_doi):
        self.headers, self._by_doi, self.calls = {}, by_doi, []

    def get(self, url, params=None, headers=None, timeout=None, **kw):
        self.calls.append(url)
        doi = url.split("works/", 1)[-1]
        return _Resp({"message": self._by_doi.get(doi, {"type": "journal-article"})})


def test_crossref_reports_the_relation_rather_than_inferring_it():
    """updated-by marks the retracted article; update-to marks the notice."""
    article = Record(title="An enhanced approach", doi="10.1007/s00521-018-03974-0")
    notice = Record(title="Retraction Note", doi="10.1007/s00521-024-10040-5")
    session = _Session({
        "10.1007/s00521-018-03974-0": {
            "type": "journal-article",
            "updated-by": [{"type": "retraction", "DOI": "10.1007/s00521-024-10040-5"}]},
        "10.1007/s00521-024-10040-5": {
            "type": "journal-article",
            "update-to": [{"type": "retraction", "DOI": "10.1007/s00521-018-03974-0"}]},
    })
    out = check_retractions_crossref([article, notice], session=session)
    assert out["checked"] == 2
    assert out["retracted"] == {"10.1007/s00521-018-03974-0": ["retraction"]}
    assert out["notices"] == {"10.1007/s00521-024-10040-5": ["retraction"]}
    assert out["checked_on"]


def test_records_without_a_doi_are_reported_not_assumed_clean():
    rec = Record(title="A study with no identifier")
    out = check_retractions_crossref([rec], session=_Session({}))
    assert out["checked"] == 0
    assert out["unchecked_no_doi"] == [rec.uid]
    assert "could not be checked" in out["caveat"]


def test_a_clean_record_produces_no_finding():
    rec = Record(title="Deep learning for screening", doi="10.5001/clean")
    out = check_retractions_crossref([rec], session=_Session({}))
    assert out["checked"] == 1
    assert not out["retracted"] and not out["notices"]


def test_a_transport_failure_is_recorded_not_swallowed():
    """An unchecked record must never look like a checked-and-clean one."""
    class _Boom(_Session):
        def get(self, url, params=None, headers=None, timeout=None, **kw):
            raise OSError("connection reset")

    rec = Record(title="A study", doi="10.5001/x")
    out = check_retractions_crossref([rec], session=_Boom({}))
    assert out["checked"] == 0
    assert "10.5001/x" in out["errors"]
