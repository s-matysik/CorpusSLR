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
    assert r["ok"]
    assert r["queries"]["scopus"]["query"].startswith("TITLE-ABS-KEY(")
    assert set(r["queries"]) == {"scopus", "wos", "pubmed", "openalex", "crossref",
                                 "semanticscholar", "arxiv", "biorxiv", "medrxiv"}
    assert all(v["query"] for v in r["queries"].values()), "every database compiles"
    direct = {k for k, v in r["queries"].items() if v["browser"]}
    proxied = {k for k, v in r["queries"].items() if v["via_proxy"]}
    assert direct == {"openalex", "crossref", "pubmed", "semanticscholar", "scopus",
                      "biorxiv", "medrxiv"}
    assert proxied == {"wos", "arxiv"} and not (direct & proxied)
    assert all("proxy" in r["queries"][k]["note"] for k in proxied)
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


@pytest.mark.parametrize("cred, fragment", [
    ({"api_key": SECRET}, "proxy"),                                   # no proxy at all
    ({"api_key": SECRET, "proxy": "http://example.org"}, "https"),    # key over plain http
    ({"api_key": SECRET, "proxy": "https://api.clarivate.com"}, "Clarivate"),
    ({"api_key": SECRET, "proxy": "https://user:pw@p.example.org"}, "credentials"),
    ({"api_key": SECRET, "proxy": "https://p.example.org/?k=1"}, "query"),
    ({"proxy": "https://p.example.org"}, "key"),                      # no key
])
def test_web_of_science_refuses_an_unsafe_or_missing_proxy_without_any_request(cred, fragment):
    net = Net()
    W.set_transport(net)
    r = json.loads(W.run_search(json.dumps(SPEC), json.dumps({"wos": cred}), 5))
    assert r["report"][0]["ok"] is False and fragment.lower() in r["report"][0]["error"].lower()
    assert net.calls == [] and SECRET not in json.dumps(r)


def _wos_page(n):
    from test_wos_expanded import _payload, _rec
    recs = [_rec({"seq_no": 1, "role": "author", "full_name": "Smith, A"}, doi="10.5001/p%d" % i,
                 uid="WOS:%04d" % i) for i in range(n)]
    return json.dumps(_payload(recs, found=n))


def test_a_web_of_science_search_goes_through_the_proxy_and_never_to_clarivate():
    net = Net({"proxy.example.workers.dev": (200, _wos_page(2), {})})
    W.set_transport(net)
    cred = {"api_key": SECRET, "proxy": "https://proxy.example.workers.dev/"}
    r = json.loads(W.run_search(json.dumps(SPEC), json.dumps({"wos": cred}), 10))
    assert r["report"][0]["ok"] and r["report"][0]["retrieved"] == 2, r
    assert net.calls and all(c[1].startswith("https://proxy.example.workers.dev/wos/api/wos") for c in net.calls)
    assert not any("clarivate.com" in c[1] for c in net.calls)
    # the key travels in the header the proxy forwards, never in the address
    assert all(c[2].get("X-ApiKey") == SECRET and SECRET not in c[1] for c in net.calls)
    assert SECRET not in json.dumps(r)
    assert W.S.corpus.identified_by_source() == {"Web of Science Core Collection": 2}


def test_a_proxy_error_message_never_contains_the_key():
    net = Net({"proxy.example.workers.dev": (401, "bad key " + SECRET, {})})
    W.set_transport(net)
    cred = {"api_key": SECRET, "proxy": "https://proxy.example.workers.dev"}
    r = json.loads(W.run_search(json.dumps(SPEC), json.dumps({"wos": cred}), 5))
    assert r["report"][0]["ok"] is False and SECRET not in json.dumps(r)


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


ARXIV_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
  <opensearch:totalResults>1</opensearch:totalResults>
  <entry><id>http://arxiv.org/abs/2401.01234v2</id><published>2024-01-02T18:00:00Z</published>
    <title>Deep learning for retinopathy</title><summary>Abstract text.</summary>
    <author><name>Jan Kowalski</name></author><arxiv:doi>10.1000/arxiv.test</arxiv:doi></entry>
</feed>"""

BIORXIV_PAGE = json.dumps({
    "messages": [{"status": "ok", "interval": "x", "cursor": 0, "count": 1, "total": 1}],
    "collection": [{"doi": "10.1101/2024.01.01.123456", "title": "Deep learning for diabetic retinopathy",
                    "authors": "Kowalski, J.", "date": "2024-03-15", "version": "1",
                    "type": "new results", "category": "bioinformatics",
                    "abstract": "Deep learning applied to diabetic retinopathy.", "server": "biorxiv"}]})


def test_arxiv_goes_through_the_proxy_on_its_own_route_and_never_to_arxiv_directly():
    net = Net({"proxy.example.workers.dev": (200, ARXIV_FEED, {})})
    W.set_transport(net)
    cred = {"proxy": "https://proxy.example.workers.dev"}
    r = json.loads(W.run_search(json.dumps(SPEC), json.dumps({"arxiv": cred}), 10))
    assert r["report"][0]["ok"] and r["report"][0]["retrieved"] == 1, r
    assert net.calls and all(c[1].startswith("https://proxy.example.workers.dev/arxiv/api/query")
                             for c in net.calls), [c[1] for c in net.calls]
    assert not any("arxiv.org" in c[1].split("/arxiv/")[0] for c in net.calls)
    assert not any(c[1].startswith(("http://export.arxiv.org", "https://export.arxiv.org"))
                   for c in net.calls)


def test_arxiv_needs_a_proxy_but_no_key():
    net = Net()
    W.set_transport(net)
    r = json.loads(W.run_search(json.dumps(SPEC), json.dumps({"arxiv": {}}), 5))
    assert r["report"][0]["ok"] is False and "proxy" in r["report"][0]["error"].lower()
    assert net.calls == []


def test_the_two_proxied_databases_use_separate_routes_in_one_search():
    net = Net({"/wos/api/wos": (200, _wos_page(1), {}), "/arxiv/api/query": (200, ARXIV_FEED, {})})
    W.set_transport(net)
    p = {"proxy": "https://proxy.example.workers.dev"}
    r = json.loads(W.run_search(json.dumps(SPEC), json.dumps(
        {"wos": dict(p, api_key=SECRET), "arxiv": p}), 10))
    assert [x["ok"] for x in r["report"]] == [True, True], r
    assert W.S.corpus.identified_by_source() == {"Web of Science Core Collection": 1, "arXiv": 1}
    urls = [c[1] for c in net.calls]
    assert any("/wos/api/wos" in u for u in urls) and any("/arxiv/api/query" in u for u in urls)


@pytest.mark.parametrize("alias, label", [("biorxiv", "bioRxiv"), ("medrxiv", "medRxiv")])
def test_the_preprint_servers_are_called_directly_without_a_proxy_or_key(alias, label):
    net = Net({"api.biorxiv.org": (200, BIORXIV_PAGE, {})})
    W.set_transport(net)
    r = json.loads(W.run_search(json.dumps(SPEC), json.dumps({alias: {}}), 10))
    assert r["report"][0]["ok"], r
    assert net.calls and all(c[1].startswith("https://api.biorxiv.org/details/" + alias)
                             for c in net.calls), [c[1] for c in net.calls]
    assert r["report"][0]["retrieved"] == 1
    assert list(W.S.corpus.identified_by_source()) == [label]


def test_every_entry_point_installs_the_requests_stand_in_before_importing_the_package():
    """The page's worker happens to call version() first, which hid an import that
    ran before the stand-in existed. Each entry point must work as the first call
    on a runtime that has no requests library."""
    import subprocess
    here = os.path.dirname(__file__)
    calls = {"compile": "W.compile_query(json.dumps(SPEC))",
             "search": "W.run_search(json.dumps(SPEC), '{}', 5)",
             "prisma": "W.prisma('{}')"}
    for name, expr in calls.items():
        src = (
            "import builtins, json, sys\n"
            "sys.path[:0] = [%r, %r]\n"
            "real = builtins.__import__\n"
            "def no_req(n, *a, **k):\n"
            "    if (n == 'requests' or n.startswith('requests.')) and 'requests' not in sys.modules:\n"
            "        raise ImportError('no requests here')\n"
            "    return real(n, *a, **k)\n"
            "builtins.__import__ = no_req\n"
            "import corpusslr_web as W\n"
            "SPEC = %r\n"
            "print(type(json.loads(%s)['ok']).__name__)\n"
        ) % (os.path.join(here, "..", "app", "py"), os.path.join(here, ".."), SPEC, expr)
        r = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True,
                           cwd=os.path.join(here, ".."))
        assert r.returncode == 0 and r.stdout.strip() == "bool", (name, r.stderr[-600:])
