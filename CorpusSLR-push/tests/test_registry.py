"""Tests for the principal/supplementary registry and strategy audit."""
import pytest

from corpusslr import Corpus, Record, SearchEvent, SourceResult
from corpusslr.sources.registry import (PRINCIPAL, SOURCE_TIER, SUPPLEMENTARY,
                                        UNKNOWN, audit_markdown,
                                        audit_strategy, canonical_source,
                                        classify_source)


def _corpus(*specs):
    """Build a corpus from (database_name, n_records) pairs."""
    c = Corpus()
    for name, n in specs:
        c.add_search(SourceResult(event=SearchEvent(database=name),
                                  records=[Record(title="t%d" % i)
                                           for i in range(n)]))
    return c


def _codes(audit):
    return [w["code"] for w in audit["warnings"]]


# ------------------------------------------------------------ classification
@pytest.mark.parametrize("name", [
    "Scopus", "scopus", "  SCOPUS  ", "Elsevier Scopus",
    "Web of Science", "Web of Science Core Collection", "WoS", "wos",
    "Web of Knowledge", "SCI-EXPANDED", "Social Sciences Citation Index",
    "PubMed", "MEDLINE", "pubmed/medline", "NCBI Entrez", "PMC",
    "Embase", "Excerpta Medica",
    "Cochrane CENTRAL", "Cochrane Library",
    "Central Register of Controlled Trials",
    "PsycINFO", "psycinfo", "CINAHL", "ERIC",
    "EBSCOhost Business Source Premier", "Business Source Complete",
    "ProQuest ABI/INFORM", "ABI/INFORM Global", "ProQuest",
    "IEEE Xplore", "IEEE", "IEL",
    "ACM Digital Library", "ACM DL",
])
def test_principal_variants(name):
    assert classify_source(name) == PRINCIPAL


@pytest.mark.parametrize("name", [
    "Crossref", "crossref", "Cross Ref",
    "OpenAlex", "openalex", "Open Alex",
    "Semantic Scholar", "semantic scholar", "S2AG", "Allen Institute for AI",
    "arXiv", "arxiv", "ARXIV",
    "bioRxiv", "biorxiv", "bio rxiv",
    "medRxiv", "medrxiv",
    "Google Scholar", "google scholar", "Publish or Perish",
    "Dimensions", "Digital Science Dimensions",
    "Lens.org", "lens",
])
def test_supplementary_variants(name):
    assert classify_source(name) == SUPPLEMENTARY


@pytest.mark.parametrize("name", ["", None, "   ", "My Institutional Repo",
                                  "Handsearching", "Unknown Database 42"])
def test_unknown_names(name):
    assert classify_source(name) == UNKNOWN


def test_canonical_source_resolves_to_registry_keys():
    assert canonical_source("WoS") == "Web of Science Core Collection"
    assert canonical_source("pubmed") == "PubMed/MEDLINE"
    assert canonical_source("S2AG") == "Semantic Scholar"
    assert canonical_source("nothing here") == ""
    assert canonical_source(None) == ""


def test_every_registry_key_classifies_as_its_own_tier():
    for name, tier in SOURCE_TIER.items():
        assert classify_source(name) == tier, name


def test_registry_has_both_tiers_and_no_stray_values():
    assert set(SOURCE_TIER.values()) == {PRINCIPAL, SUPPLEMENTARY}
    assert sum(1 for v in SOURCE_TIER.values() if v == PRINCIPAL) >= 9


def test_client_names_match_the_registry():
    """The names the API clients write into SearchEvent must classify."""
    from corpusslr.sources.arxiv import ArxivSource
    from corpusslr.sources.crossref import CrossrefSource
    from corpusslr.sources.openalex import OpenAlexSource
    from corpusslr.sources.preprints import BiorxivSource, MedrxivSource
    from corpusslr.sources.pubmed import PubMedSource
    from corpusslr.sources.scopus import ScopusSource
    from corpusslr.sources.semanticscholar import SemanticScholarSource

    assert classify_source(ScopusSource.name) == PRINCIPAL
    assert classify_source(PubMedSource.name) == PRINCIPAL
    for cls in (CrossrefSource, OpenAlexSource, SemanticScholarSource,
                ArxivSource, BiorxivSource, MedrxivSource):
        assert classify_source(cls.name) == SUPPLEMENTARY, cls.name


# -------------------------------------------------------------------- audit
def test_audit_counts_and_groups():
    a = audit_strategy(_corpus(("Scopus", 10), ("WoS", 5), ("OpenAlex", 3)))
    assert a["principal"] == ["Scopus", "Web of Science Core Collection"]
    assert a["supplementary"] == ["OpenAlex"]
    assert a["records"][PRINCIPAL] == 15
    assert a["records"][SUPPLEMENTARY] == 3
    assert a["total_records"] == 18
    assert a["n_principal"] == 2
    assert abs(a["supplementary_share"] - 3 / 18) < 1e-9


def test_name_variants_are_merged_into_one_canonical_row():
    a = audit_strategy(_corpus(("Web of Science", 4), ("WoS", 6)))
    assert a["principal"] == ["Web of Science Core Collection"]
    assert a["records_by_source"]["Web of Science Core Collection"] == 10
    entry = a["per_source"]["Web of Science Core Collection"]
    assert entry["searches"] == 2
    assert sorted(entry["names_seen"]) == ["Web of Science", "WoS"]


def test_warning_no_principal_is_critical():
    a = audit_strategy(_corpus(("OpenAlex", 10), ("Crossref", 5)))
    assert "no_principal" in _codes(a)
    w = [x for x in a["warnings"] if x["code"] == "no_principal"][0]
    assert w["level"] == "critical"
    assert "Gusenbauer" in w["message"]
    assert "single_principal" not in _codes(a)


def test_warning_single_principal_cites_bramer():
    a = audit_strategy(_corpus(("Scopus", 100)))
    codes = _codes(a)
    assert "single_principal" in codes
    assert "no_principal" not in codes
    w = [x for x in a["warnings"] if x["code"] == "single_principal"][0]
    assert w["level"] == "warning"
    assert "Bramer" in w["message"] and "98.3" in w["message"]
    assert "Systematic Reviews 6:245" in w["message"]
    assert "Scopus" in w["message"]


def test_no_single_principal_warning_with_two_principals():
    a = audit_strategy(_corpus(("Scopus", 50), ("Embase", 50)))
    assert "single_principal" not in _codes(a)
    assert "no_principal" not in _codes(a)


def test_warning_supplementary_majority():
    a = audit_strategy(_corpus(("Scopus", 10), ("Embase", 10),
                               ("OpenAlex", 30)))
    assert "supplementary_majority" in _codes(a)
    w = [x for x in a["warnings"]
         if x["code"] == "supplementary_majority"][0]
    assert "60.0%" in w["message"]


def test_no_majority_warning_at_exactly_half():
    a = audit_strategy(_corpus(("Scopus", 10), ("Embase", 10),
                               ("OpenAlex", 20)))
    assert "supplementary_majority" not in _codes(a)


def test_warning_unclassified_source():
    a = audit_strategy(_corpus(("Scopus", 10), ("Embase", 10),
                               ("Lab Notebook", 1)))
    assert "unclassified_source" in _codes(a)
    assert a["unknown"] == ["Lab Notebook"]
    assert a["records"][UNKNOWN] == 1


def test_empty_corpus_is_handled():
    a = audit_strategy(Corpus())
    assert a["total_records"] == 0
    assert a["supplementary_share"] == 0.0
    assert "no_principal" in _codes(a)
    assert a["per_source"] == {}


def test_zero_record_searches_do_not_divide_by_zero():
    a = audit_strategy(_corpus(("Scopus", 0), ("OpenAlex", 0)))
    assert a["total_records"] == 0
    assert a["supplementary_share"] == 0.0
    assert "supplementary_majority" not in _codes(a)


def test_unnamed_source_is_labelled():
    a = audit_strategy(_corpus(("", 2)))
    assert a["unknown"] == ["(unnamed source)"]


def test_audit_accepts_any_object_with_searches():
    class Stub:
        searches = [SearchEvent(database="Scopus", records_retrieved=7)]
    a = audit_strategy(Stub())
    assert a["records"][PRINCIPAL] == 7


# ----------------------------------------------------------------- markdown
def test_audit_markdown_table_and_ordering():
    md = audit_markdown(_corpus(("OpenAlex", 30), ("Scopus", 10),
                                ("Embase", 20)))
    assert "## Search-system classification" in md
    assert "Gusenbauer & Haddaway" in md
    # principal rows precede supplementary rows
    assert md.index("| Embase | principal") < md.index("| OpenAlex | supplementary")
    # within a tier, larger record counts first
    assert md.index("| Embase | principal") < md.index("| Scopus | principal")
    assert "| Scopus | principal | 1 | 10 | 16.7% |" in md
    # 30 of 60 records is exactly half, so no majority warning fires
    assert "No strategy warnings" in md


def test_audit_markdown_renders_warning_level():
    md = audit_markdown(_corpus(("Scopus", 10), ("Embase", 10),
                                ("OpenAlex", 40)))
    assert "### Strategy warnings" in md
    assert "**WARNING**" in md
    assert "66.7%" in md


def test_audit_markdown_critical_warning_rendered():
    md = audit_markdown(_corpus(("arXiv", 5)))
    assert "**CRITICAL**" in md


def test_audit_markdown_clean_corpus_says_so():
    md = audit_markdown(_corpus(("Scopus", 40), ("Embase", 40),
                                ("OpenAlex", 5)))
    assert "No strategy warnings" in md
    assert "### Strategy warnings" not in md


def test_audit_markdown_empty_corpus():
    md = audit_markdown(Corpus())
    assert "(no searches recorded)" in md
    assert "**CRITICAL**" in md


def test_prisma_s_appendix_embeds_the_audit():
    from corpusslr import prisma_s_markdown
    md = prisma_s_markdown(_corpus(("Scopus", 3), ("Semantic Scholar", 9)))
    assert "## Search-system classification" in md
    assert "**WARNING**" in md
    # the section sits between the strategies and the deduplication section
    assert md.index("## Search-system classification") < \
        md.index("## Deduplication")


# --------------------------------------------------------------------------
# Provenance of the tier assignments.  The registry cites Gusenbauer &
# Haddaway (2020); a reviewer checking that citation must find each entry
# there, or find the registry saying plainly that it does not.
# --------------------------------------------------------------------------
from corpusslr import (SOURCE_EVIDENCE, SOURCE_NOTES, source_evidence,
                       source_note)

# The 14 principal systems named in Gusenbauer & Haddaway (2020), section 6.
PUBLISHED_PRINCIPAL = {
    "acm digital library", "base", "clinicaltrials.gov", "cochrane library",
    "ebscohost", "ovid", "proquest", "pubmed", "sciencedirect", "scopus",
    "trid", "virtual health library", "web of science", "wiley online library"}


def test_every_registry_entry_declares_its_evidence_level():
    """No tier may be assigned without recording how it is evidenced."""
    missing = set(SOURCE_TIER) - set(SOURCE_EVIDENCE)
    assert not missing, f"entries without provenance: {sorted(missing)}"
    allowed = {"listed", "platform", "field-convention", "not-principal",
               "not-assessed"}
    bad = {k: v for k, v in SOURCE_EVIDENCE.items() if v not in allowed}
    assert not bad, bad


def test_principal_entries_not_in_the_published_list_are_flagged():
    """A principal tier the cited paper does not support must not claim it does."""
    for name, tier in SOURCE_TIER.items():
        if tier != "principal":
            continue
        ev = SOURCE_EVIDENCE[name]
        if ev == "listed":
            low = name.lower()
            assert any(p.split("(")[0].strip() in low or low.startswith(p[:6])
                       for p in PUBLISHED_PRINCIPAL), \
                f"{name} claims 'listed' but is not in the published set"
        else:
            assert ev in ("platform", "field-convention"), (name, ev)
            assert SOURCE_NOTES.get(name), \
                f"{name} needs a methods-section caveat explaining its tier"


def test_ieee_xplore_tier_does_not_claim_gusenbauer_support():
    """IEEE Xplore is a field-convention choice, not their finding."""
    assert SOURCE_TIER["IEEE Xplore"] == "principal"
    assert source_evidence("IEEE Xplore") == "field-convention"
    note = source_note("ieee xplore")
    assert "did not include it" in note and "field-convention" in note


def test_source_note_and_evidence_accept_name_variants():
    assert source_evidence("WoS") == "listed"
    assert source_evidence("web of science core collection") == "listed"
    assert source_evidence("Embase (OVID)") == "platform"
    assert source_note("Embase")
    assert source_evidence("nonexistent database") == ""
    assert source_note(None) == ""


def test_audit_notes_when_a_tier_is_only_platform_evidenced():
    from corpusslr import Corpus, Record
    c = Corpus()
    c.add_records([Record(title="A", doi="10.5001/a")], database="Embase",
                  interface="OVID", query="q", date_run="2026-01-01")
    c.add_records([Record(title="B", doi="10.5001/b")], database="Scopus",
                  interface="API", query="q", date_run="2026-01-01")
    a = audit_strategy(c)
    # A reporting note is not a strategy defect, so it must not appear among
    # the warnings -- otherwise every well-built search looks flawed.
    assert "tier_provenance" not in {w["code"] for w in a["warnings"]}
    note = [n for n in a["notes"] if n["code"] == "tier_provenance"][0]
    assert "Embase" in note["message"] and "Scopus" not in note["sources"]
    md = audit_markdown(c)
    assert "Reporting notes" in md and "OVID" in md


def test_google_scholar_records_that_it_was_assessed_and_rejected():
    assert SOURCE_TIER["Google Scholar"] == "supplementary"
    assert source_evidence("Google Scholar") == "not-principal"
    assert "not reproducible" in source_note("Google Scholar")
