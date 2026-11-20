"""The browser application's Python layer, tested offline.

The page calls these functions inside Pyodide. Here they run as ordinary
Python with a scripted transport, so no test reaches the network. The same
functions are run again inside the real Pyodide runtime by
``app/test/run_pyodide_tests.mjs``.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app", "py"))
import corpusslr_web as W                                    # noqa: E402

SECRET = "SECRETKEY-1234567890"

RIS = """TY  - JOUR
TI  - Deep learning for diabetic retinopathy screening
AU  - Kowalski, Jan
PY  - 2021
DO  - 10.1000/abc.123
JO  - Journal of Examples
ER  -

TY  - JOUR
TI  - Transfer learning in fundus photography
AU  - Nowak, Anna
PY  - 2023
DO  - 10.1000/tl.77
ER  -
"""


def _oa(*works):
    return json.dumps({"meta": {"count": len(works), "next_cursor": None},
                       "results": list(works)})


def _work(i, title, doi, year):
    return {"id": "https://openalex.org/W%d" % i, "doi": "https://doi.org/" + doi,
            "title": title, "publication_year": year, "type": "article",
            "authorships": [{"author": {"display_name": "Kowalski J"}}],
            "abstract_inverted_index": {"An": [0], "abstract": [1]}}


class Net:
    """Scripted transport that records every request."""

    def __init__(self, script=None):
        self.calls = []
        self.script = script or {}

    def __call__(self, method, url, headers):
        self.calls.append((method, url, dict(headers)))
        for host, reply in self.script.items():
            if host in url:
                return reply(url, headers) if callable(reply) else reply
        raise AssertionError("unexpected request to " + url)


@pytest.fixture(autouse=True)
def _fresh():
    W.reset()
    yield
    W.set_transport(None)


SPEC = {"blocks": [["deep learning"], ["diabetic retinopathy"]], "years": [2020, 2024],
        "doc_types": ["article"]}


def test_every_dialect_is_compiled_and_the_browser_reachable_ones_are_marked():
    r = json.loads(W.compile_query(json.dumps(SPEC)))
    assert r["ok"] and set(r["queries"]) == {
        "scopus", "wos", "pubmed", "openalex", "crossref", "semanticscholar", "arxiv"}
    assert r["queries"]["scopus"]["query"].startswith("TITLE-ABS-KEY(")
    assert r["queries"]["wos"]["browser"] is False and r["queries"]["wos"]["note"]
    assert r["queries"]["openalex"]["browser"] is True


@pytest.mark.parametrize("spec, fragment", [
    ({"blocks": [[], [" "]]}, "at least one"),
    ({"blocks": [["a"]], "years": [2024, 2020]}, "after the last"),
])
def test_an_invalid_query_is_reported_not_raised(spec, fragment):
    r = json.loads(W.compile_query(json.dumps(spec)))
    assert r["ok"] is False and fragment in r["error"]


def test_a_search_reaches_only_the_chosen_host_and_drops_forbidden_headers():
    net = Net({"api.openalex.org": (200, _oa(_work(1, "Deep learning for diabetic retinopathy screening", "10.1000/abc.123", 2021)), {})})
    W.set_transport(net)
    r = json.loads(W.run_search(json.dumps(SPEC), json.dumps({"openalex": {}}), 10, "me@example.org"))
    assert r["ok"] and r["report"][0]["ok"] and r["report"][0]["retrieved"] == 1
    assert net.calls and all("api.openalex.org" in c[1] for c in net.calls)
    for _m, _u, headers in net.calls:
        assert not {h.lower() for h in headers} & W.FORBIDDEN_HEADERS


def test_a_key_never_appears_in_an_error_message_or_in_the_module_state():
    net = Net({"api.elsevier.com": (401, "Invalid key " + SECRET, {})})
    W.set_transport(net)
    r = json.loads(W.run_search(json.dumps(SPEC), json.dumps({"scopus": {"api_key": SECRET}}), 5))
    rep = r["report"][0]
    assert rep["ok"] is False and SECRET not in json.dumps(r)
    assert SECRET not in repr(vars(W.S)) and SECRET not in repr(W.S.corpus.__dict__)


def test_status_zero_explains_cors_instead_of_a_bare_network_error():
    W.set_transport(Net({"api.openalex.org": (0, "", {})}))
    r = json.loads(W.run_search(json.dumps(SPEC), json.dumps({"openalex": {}}), 5))
    assert r["report"][0]["ok"] is False and "CORS" in r["report"][0]["error"]


@pytest.mark.parametrize("alias", ["wos", "arxiv"])
def test_databases_without_cors_are_refused_with_a_pointer_to_file_import(alias):
    W.set_transport(Net())
    r = json.loads(W.run_search(json.dumps(SPEC), json.dumps({alias: {}}), 5))
    assert r["report"][0]["ok"] is False and "import" in r["report"][0]["error"].lower()


def test_search_and_import_are_merged_and_every_output_is_produced(tmp_path):
    net = Net({"api.openalex.org": (200, _oa(
        _work(1, "Deep learning for diabetic retinopathy screening", "10.1000/ABC.123", 2021),
        _work(2, "A third, unrelated study of glaucoma", "10.1000/g.5", 2022)), {})})
    W.set_transport(net)
    W.run_search(json.dumps(SPEC), json.dumps({"openalex": {}}), 10)
    f = tmp_path / "scopus_like.ris"
    f.write_text(RIS, encoding="utf-8")
    imp = json.loads(W.import_file(str(f), "scopus_like.ris", database="Scopus"))
    assert imp["ok"] and imp["records"] == 2 and imp["n_input"] == imp["records"] + imp["n_rejected"]

    d = json.loads(W.run_dedup("{}"))
    assert (d["before"], d["after"], d["removed"]) == (4, 3, 1)
    assert d["by_method"].get("doi") == 1
    rows = json.loads(W.decisions())["rows"]
    assert len(rows) == 1 and rows[0]["method"] == "doi"
    assert json.loads(W.records())["deduplicated"] is True

    p = json.loads(W.prisma("{}"))
    assert p["ok"] and p["problems"] == [] and p["svg"].lstrip().startswith("<svg")
    assert p["screening_supplied"] is False and "screening" in p["note"]
    assert "OpenAlex" in W.prisma_s() and "Scopus" in W.prisma_s()
    assert W.audit() and W.quality()

    for fmt in ("scopus_csv", "csv", "screening_csv", "ris", "bibtex", "decisions_csv"):
        e = json.loads(W.export(fmt))
        assert e["ok"] and e["text"].strip(), fmt
    header = json.loads(W.export("scopus_csv"))["text"].splitlines()[0]
    assert header.count(",") + 1 >= 40


def test_an_unreadable_file_is_reported_with_its_name(tmp_path):
    f = tmp_path / "empty.ris"
    f.write_text("", encoding="utf-8")
    r = json.loads(W.import_file(str(f), "empty.ris"))
    assert r["ok"] is False and r["name"] == "empty.ris" and r["error"]


def test_deduplication_without_records_and_unknown_export_are_errors():
    assert json.loads(W.run_dedup("{}"))["ok"] is False
    assert json.loads(W.export("scopus_csv"))["ok"] is False


def test_the_requests_stub_is_installed_only_when_the_library_is_missing():
    import importlib
    saved = {k: sys.modules.pop(k) for k in list(sys.modules)
             if k == "requests" or k.startswith("requests.")}
    real_import = __import__

    def no_requests(name, *a, **k):
        if (name == "requests" or name.startswith("requests.")) and name not in sys.modules:
            raise ImportError("blocked for the test")
        return real_import(name, *a, **k)

    import builtins
    builtins.__import__ = no_requests
    try:
        assert W.install_requests_stub() is True
        stub = sys.modules["requests"]
        assert issubclass(stub.HTTPError, stub.RequestException)
        resp = stub.Response(404, "x", "u")
        with pytest.raises(stub.HTTPError):
            resp.raise_for_status()
    finally:
        builtins.__import__ = real_import
        for k in [k for k in sys.modules if k == "requests" or k.startswith("requests.")]:
            del sys.modules[k]
        sys.modules.update(saved)
        importlib.invalidate_caches()


def test_prisma_arithmetic_is_checked_only_when_screening_counts_are_given(tmp_path):
    f = tmp_path / "a.ris"
    f.write_text(RIS, encoding="utf-8")
    W.import_file(str(f), "a.ris", database="Scopus")
    W.run_dedup("{}")
    balanced = json.dumps({"records_excluded": 0, "studies_included": 2})
    assert json.loads(W.prisma(balanced))["problems"] == []
    unbalanced = json.dumps({"records_excluded": 0, "studies_included": 5})
    r = json.loads(W.prisma(unbalanced))
    assert r["screening_supplied"] is True and r["problems"], r


def test_the_export_bundle_holds_every_output_and_no_key(tmp_path):
    import base64
    import io
    import zipfile
    f = tmp_path / "a.ris"
    f.write_text(RIS, encoding="utf-8")
    W.import_file(str(f), "a.ris", database="Scopus")
    W.run_dedup("{}")
    r = json.loads(W.bundle_zip(json.dumps(SPEC), "{}"))
    assert r["ok"]
    z = zipfile.ZipFile(io.BytesIO(base64.b64decode(r["b64"])))
    names = set(z.namelist())
    assert {"README.txt", "prisma2020_flow.svg", "prisma_s_appendix.md",
            "corpusslr_scopus.csv", "corpusslr_decisions.csv", "compiled_queries.json",
            "strategy_audit.md", "data_quality.md"} <= names, names
    assert "1.2.0" in z.read("README.txt").decode()
    assert z.testzip() is None


def test_the_bundle_of_an_empty_session_is_an_error():
    assert json.loads(W.bundle_zip("{}", "{}"))["ok"] is False


@pytest.mark.parametrize("alias", ["openalex", "crossref", "pubmed", "semanticscholar", "scopus"])
def test_a_blocked_request_fails_after_one_call_and_without_waiting(alias):
    """Status 0 is a CORS refusal or no network. Retrying with a back-off froze
    the worker for up to 49 s (Semantic Scholar) before this was handled."""
    import time
    net = Net({"": (0, "", {})})
    W.set_transport(net)
    start = time.time()
    r = json.loads(W.run_search(json.dumps(SPEC), json.dumps({alias: {"api_key": "k123456"}}), 100))
    assert r["report"][0]["ok"] is False and "CORS" in r["report"][0]["error"]
    assert len(net.calls) == 1, len(net.calls)
    assert time.time() - start < 2.0


def test_the_sleep_shim_is_removed_after_the_search_and_real_back_off_is_kept(monkeypatch):
    """The suite replaces time.sleep globally, so the calls are recorded here
    instead of timed."""
    import time
    import corpusslr.sources.base as base
    slept = []
    monkeypatch.setattr("time.sleep", lambda s: slept.append(s))
    W.set_transport(Net({"": (0, "", {})}))
    W.run_search(json.dumps(SPEC), json.dumps({"openalex": {}}), 5)
    assert base.time is time
    assert slept == [], "a blocked search must not back off"
    session = W.BrowserSession(lambda m, u, h: (200, "{}", {}))
    shim = W._NoSleepWhenBlocked(session)
    shim.sleep(2)
    assert slept == [2], "an unblocked session still backs off"
    session.blocked = True
    shim.sleep(4)
    assert slept == [2]
