"""Bridge between the browser page and the CorpusSLR package.

The page runs this module inside Pyodide, in a web worker. Every public
function takes and returns JSON text or plain strings, so the JavaScript side
never handles Python objects. The module adds no logic of its own to the
review: it calls the package for compiling, parsing, deduplicating, PRISMA and
export, and only adapts inputs and outputs.

Two things are specific to the browser:

* The package imports ``requests``, which cannot open sockets in a browser.
  :func:`install_requests_stub` registers a minimal stand-in when the real
  library is absent, and :class:`BrowserSession` serves the sources through an
  injectable ``transport``. In a worker the transport is a synchronous XHR, so
  the browser, not the page, enforces CORS. Databases that send no CORS header
  (Web of Science, arXiv) fail with a clear message and are used by importing
  an export file instead.
* Nothing is persisted. API keys are held in the arguments of one call and are
  never written to the module state, a file or the log.

The module is tested twice: as ordinary Python with an offline transport
(``tests/test_web_bridge.py``) and inside the real Pyodide runtime
(``app/test/run_pyodide_tests.mjs``).
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import types
from datetime import date
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import urlencode

#: Header names a browser refuses to let script set. Setting them is ignored at
#: best and an error at worst, so the session drops them before the request.
FORBIDDEN_HEADERS = frozenset(h.lower() for h in (
    "User-Agent", "Accept-Encoding", "Connection", "Content-Length", "Host",
    "Origin", "Referer", "Cookie", "Date", "Keep-Alive", "Upgrade", "Via"))

Transport = Callable[[str, str, Dict[str, str]], Tuple[int, str, Dict[str, str]]]


# ---------------------------------------------------------------------------
# requests stand-in
# ---------------------------------------------------------------------------
def install_requests_stub() -> bool:
    """Register a minimal ``requests`` module if the real one is absent.

    Returns True when a stub was installed. The package uses only
    ``Session``, ``RequestException``, ``HTTPError`` and the response
    attributes provided by :class:`Response`.
    """
    try:
        import requests  # noqa: F401
        return False
    except ImportError:
        pass
    mod = types.ModuleType("requests")

    class RequestException(IOError):
        pass

    class HTTPError(RequestException):
        pass

    mod.RequestException = RequestException
    mod.HTTPError = HTTPError
    mod.ConnectionError = type("ConnectionError", (RequestException,), {})
    mod.Timeout = type("Timeout", (RequestException,), {})
    mod.Response = Response
    mod.Session = BrowserSession
    exc = types.ModuleType("requests.exceptions")
    exc.RequestException, exc.HTTPError = RequestException, HTTPError
    mod.exceptions = exc
    sys.modules["requests"] = mod
    sys.modules["requests.exceptions"] = exc
    Response._http_error = HTTPError
    return True


class Response:
    """The subset of ``requests.Response`` the package reads."""

    _http_error: Any = None

    def __init__(self, status_code: int, text: str, url: str = "",
                 headers: Optional[Dict[str, str]] = None):
        self.status_code = status_code
        self.text = text
        self.url = url
        self.headers = headers or {}

    @property
    def content(self) -> bytes:
        return self.text.encode("utf-8")

    def json(self) -> Any:
        return json.loads(self.text)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError("HTTP %d for %s" % (self.status_code, self.url))


class BrowserSession:
    """``requests.Session`` look-alike that delegates to a transport."""

    #: Set after the first status-0 answer. A browser reports 0 for a CORS
    #: refusal and for no network alike, and neither is transient, so retrying
    #: only freezes the worker (measured: 49 s for Semantic Scholar).
    BLOCKED_MESSAGE = ("the browser blocked or could not complete the request "
                       "(no network, or the server sends no CORS header for this page)")

    def __init__(self, transport: Optional[Transport] = None):
        self.headers: Dict[str, str] = {}
        self.transport = transport or xhr_transport
        self.blocked = False
        #: (origin to replace, base address to put in its place). Used for the
        #: one API that sends no CORS header and is reached through a proxy.
        self.rewrite: Optional[Tuple[str, str]] = None

    def get(self, url: str, params: Any = None, headers: Optional[Dict[str, str]] = None,
            timeout: Any = None, **_ignored: Any) -> Response:
        import requests
        if self.blocked:
            raise requests.RequestException(self.BLOCKED_MESSAGE)
        if params:
            url += ("&" if "?" in url else "?") + urlencode(params, doseq=True)
        if self.rewrite and url.startswith(self.rewrite[0]):
            url = self.rewrite[1] + url[len(self.rewrite[0]):]
        merged = dict(self.headers)
        merged.update(headers or {})
        merged = {k: v for k, v in merged.items() if k.lower() not in FORBIDDEN_HEADERS}
        try:
            status, text, resp_headers = self.transport("GET", url, merged)
        except requests.RequestException:
            raise
        except Exception as exc:                                  # noqa: BLE001
            raise requests.RequestException("%s: %s" % (type(exc).__name__, exc))
        if status == 0:
            self.blocked = True
            raise requests.RequestException(self.BLOCKED_MESSAGE)
        return Response(status, text, url, resp_headers)


def xhr_transport(method: str, url: str, headers: Dict[str, str]):
    """Synchronous XHR; valid only inside a web worker."""
    from js import XMLHttpRequest  # type: ignore[import-not-found]
    xhr = XMLHttpRequest.new()
    xhr.open(method, url, False)
    for k, v in headers.items():
        xhr.setRequestHeader(k, v)
    xhr.send(None)
    return int(xhr.status), str(xhr.responseText or ""), {}


class _NoSleepWhenBlocked:
    """Stand-in for the ``time`` module inside the source modules.

    The sources back off with ``time.sleep`` between retries. That is right for
    a 429 or a 5xx, and pointless once the session knows the browser blocked the
    request, so the sleep is skipped from then on. Everything else is the real
    ``time`` module.
    """

    def __init__(self, session: "BrowserSession"):
        import time
        self._time, self._session = time, session

    def sleep(self, seconds: float) -> None:
        if not self._session.blocked:
            self._time.sleep(seconds)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._time, name)


class _patched_sleep:
    def __init__(self, session: "BrowserSession"):
        self.session, self.saved = session, []

    def __enter__(self):
        import time
        shim = _NoSleepWhenBlocked(self.session)
        for name, mod in list(sys.modules.items()):
            if name.startswith("corpusslr.sources") and getattr(mod, "time", None) is time:
                self.saved.append(mod)
                mod.time = shim
        return self

    def __exit__(self, *exc):
        import time
        for mod in self.saved:
            mod.time = time


# ---------------------------------------------------------------------------
# state
# ---------------------------------------------------------------------------
class _State:
    corpus = None
    result = None
    transport: Optional[Transport] = None


S = _State()

#: Browsers can reach these; Web of Science and arXiv send no CORS header.
LIVE_SOURCES = ("openalex", "crossref", "pubmed", "semanticscholar", "scopus",
                "biorxiv", "medrxiv")
#: Their APIs send no CORS header (measured), so they are reached through a proxy
#: the user runs. Value: the address the package calls, and the proxy route.
PROXY_ROUTES = {
    "wos": ("https://api.clarivate.com", "/wos"),
    "arxiv": ("http://export.arxiv.org", "/arxiv"),
}
PROXY_SOURCES = tuple(PROXY_ROUTES)
PROXY_NEEDED = (
    "This API sends no CORS header to any origin, so a browser page cannot read its "
    "answers. Enter the address of your own proxy (app/proxy/worker.js), or import "
    "an export file.")
SOURCE_LABELS = {
    "openalex": "OpenAlex", "crossref": "Crossref", "pubmed": "PubMed",
    "semanticscholar": "Semantic Scholar", "scopus": "Scopus",
    "biorxiv": "bioRxiv", "medrxiv": "medRxiv",
    "wos": "Web of Science", "arxiv": "arXiv",
}
ALL_SOURCES = ("scopus", "wos", "pubmed", "openalex", "crossref", "semanticscholar",
               "arxiv", "biorxiv", "medrxiv")


def _pkg():
    install_requests_stub()
    import corpusslr
    return corpusslr


def reset() -> str:
    pkg = _pkg()
    S.corpus = pkg.Corpus()
    S.result = None
    return json.dumps({"ok": True})


def _corpus():
    if S.corpus is None:
        reset()
    return S.corpus


def set_transport(transport: Optional[Transport]) -> None:
    """Replace the HTTP transport (used by the tests)."""
    S.transport = transport


def version() -> str:
    return _pkg().__version__


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------
def _query(spec: Dict[str, Any]):
    pkg = _pkg()
    blocks = [[t.strip() for t in b if str(t).strip()] for b in spec.get("blocks", [])]
    blocks = [b for b in blocks if b]
    if not blocks:
        raise ValueError("Enter at least one search term.")
    years = spec.get("years")
    years_t = None
    if years and years[0] and years[1]:
        a, b = int(years[0]), int(years[1])
        if a > b:
            raise ValueError("The first year is after the last year.")
        years_t = (a, b)
    return pkg.SearchQuery(blocks=blocks, years=years_t,
                           doc_types=list(spec.get("doc_types") or []),
                           languages=list(spec.get("languages") or []),
                           title_only=bool(spec.get("title_only")))


def compile_query(spec_json: str) -> str:
    """Compile the query for every supported database (no network)."""
    _pkg()
    from corpusslr import cli
    try:
        q = _query(json.loads(spec_json))
    except ValueError as exc:
        return json.dumps({"ok": False, "error": str(exc)})
    out = {}
    for alias in ALL_SOURCES:
        try:
            c = cli.compile_for(alias, q)
            out[alias] = {"label": SOURCE_LABELS[alias], "query": c["query"],
                          "filters": c.get("filters", ""),
                          "browser": alias in LIVE_SOURCES,
                          "via_proxy": alias in PROXY_SOURCES,
                          "note": PROXY_NEEDED if alias in PROXY_SOURCES else ""}
        except Exception as exc:                                  # noqa: BLE001
            out[alias] = {"label": SOURCE_LABELS[alias], "query": "", "filters": "",
                          "browser": alias in LIVE_SOURCES,
                          "via_proxy": alias in PROXY_SOURCES, "note": "",
                          "error": "%s: %s" % (type(exc).__name__, exc)}
    return json.dumps({"ok": True, "queries": out, "warnings": list(q.warnings)})


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------
def _build_source(alias: str, cred: Dict[str, str], email: str, session):
    pkg = _pkg()
    key = (cred.get("api_key") or "").strip()
    if alias == "openalex":
        return pkg.OpenAlexSource(mailto=email, session=session)
    if alias == "crossref":
        return pkg.CrossrefSource(mailto=email, session=session)
    if alias == "pubmed":
        return pkg.PubMedSource(email=email, api_key=key, session=session)
    if alias == "semanticscholar":
        return pkg.SemanticScholarSource(api_key=key, session=session)
    if alias in PROXY_ROUTES:
        if alias == "wos" and not key:
            raise ValueError("Web of Science needs an API key (the Expanded API).")
        origin, route = PROXY_ROUTES[alias]
        session.rewrite = (origin, _proxy_base(cred.get("proxy") or "") + route)
        if alias == "wos":
            return pkg.WosExpandedSource(api_key=key, mailto=email, session=session)
        return pkg.ArxivSource(mailto=email, session=session)
    if alias in ("biorxiv", "medrxiv"):
        cls = pkg.BiorxivSource if alias == "biorxiv" else pkg.MedrxivSource
        return cls(mailto=email, session=session)
    if alias == "scopus":
        if not key:
            raise ValueError("Scopus needs an API key.")
        return pkg.ScopusSource(api_key=key,
                                insttoken=(cred.get("insttoken") or "").strip(),
                                session=session)
    raise ValueError("unsupported source " + alias)


def _proxy_base(raw: str) -> str:
    """Validate the address of the user's own proxy and return it without a slash."""
    from urllib.parse import urlparse
    value = raw.strip().rstrip("/")
    if not value:
        raise ValueError(PROXY_NEEDED)
    u = urlparse(value)
    local = u.hostname in ("localhost", "127.0.0.1")
    if u.scheme != "https" and not (u.scheme == "http" and local):
        raise ValueError("The proxy address must start with https:// (a key must not "
                         "travel over plain http).")
    if not u.hostname or u.username or u.password or u.query or u.fragment:
        raise ValueError("The proxy address must be a plain address with no credentials, "
                         "query or fragment.")
    if u.hostname.endswith("clarivate.com"):
        raise ValueError("That is the Clarivate address itself, which a browser cannot "
                         "read. Enter the address of your own proxy.")
    return value


def run_search(spec_json: str, sources_json: str, max_results: int = 100,
               email: str = "") -> str:
    """Search the chosen databases and add each result to the corpus.

    ``sources_json`` maps an alias to its credentials, for example
    ``{"openalex": {}, "scopus": {"api_key": "..."}}``. Keys are used for the
    calls of this invocation only.
    """
    _pkg()
    from corpusslr.sources.base import SourceError
    spec, creds = json.loads(spec_json), json.loads(sources_json)
    corpus = _corpus()
    try:
        q = _query(spec)
    except ValueError as exc:
        return json.dumps({"ok": False, "error": str(exc)})
    report = []
    for alias, cred in creds.items():
        label = SOURCE_LABELS.get(alias, alias)
        try:
            session = BrowserSession(S.transport)
            src = _build_source(alias, cred or {}, email, session)
            with _patched_sleep(session):
                res = src.search(q, max_results=int(max_results))
            corpus.add_search(res)
            report.append({"source": alias, "label": label, "ok": True,
                           "retrieved": len(res.records),
                           "hits": getattr(res.event, "hit_count", None)})
        except (SourceError, ValueError) as exc:
            report.append({"source": alias, "label": label, "ok": False,
                           "error": _scrub(str(exc), creds)})
        except Exception as exc:                                  # noqa: BLE001
            report.append({"source": alias, "label": label, "ok": False,
                           "error": _scrub("%s: %s" % (type(exc).__name__, exc), creds)})
    S.result = None
    return json.dumps({"ok": True, "report": report, "totals": _totals()})


def _scrub(text: str, creds: Dict[str, Dict[str, str]]) -> str:
    """Remove any credential value from an error message."""
    for cred in creds.values():
        for v in (cred or {}).values():
            if v and len(v) >= 6:
                text = text.replace(v, "***")
    return text


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------
def import_file(path: str, display_name: str = "", database: str = "",
                query_note: str = "") -> str:
    """Parse one export file already written to the virtual file system."""
    _pkg()
    from corpusslr import cli
    corpus = _corpus()
    try:
        recs, prov = cli.parse_export_file(path)
    except Exception as exc:                                      # noqa: BLE001
        return json.dumps({"ok": False, "name": display_name or os.path.basename(path),
                           "error": str(exc)})
    db = cli._database_for(prov, recs, explicit=database)
    corpus.add_records(recs, database=db, platform="", interface="file export",
                       query=query_note or "(export imported from file %s)"
                       % (display_name or os.path.basename(path)),
                       date_run=date.today().isoformat())
    S.result = None
    return json.dumps({
        "ok": True, "name": display_name or os.path.basename(path), "database": db,
        "format": prov.get("format"), "dialect": prov.get("dialect"),
        "records": len(recs), "n_input": prov.get("n_input"),
        "n_rejected": prov.get("n_rejected"),
        "rejection_reasons": prov.get("rejection_reasons") or {},
        "warnings": prov.get("warnings") or [], "totals": _totals()})


# ---------------------------------------------------------------------------
# deduplicate and read back
# ---------------------------------------------------------------------------
_DEDUP_PARAMS = {"fuzzy_threshold": float, "year_tolerance": int, "block_prefix": int,
                 "max_block": int, "id_title_min": float, "separate_by_locus": bool,
                 "blocking_rounds": bool, "round_title_min": float,
                 "allow_copublication": bool, "separate_conference": bool}


def _totals() -> Dict[str, Any]:
    c = _corpus()
    return {"identified": c.total_identified(), "by_source": c.identified_by_source(),
            "unique": len(S.result.records) if S.result is not None else None}


def run_dedup(params_json: str = "{}") -> str:
    pkg = _pkg()
    corpus = _corpus()
    if not corpus.records:
        return json.dumps({"ok": False,
                           "error": "There are no records yet. Search or import first."})
    raw = json.loads(params_json or "{}")
    kw = {k: _DEDUP_PARAMS[k](v) for k, v in raw.items() if k in _DEDUP_PARAMS}
    S.result = pkg.deduplicate(corpus, **kw)
    r = S.result.report
    return json.dumps({"ok": True, "before": r.before, "after": r.after,
                       "removed": r.removed, "by_method": dict(r.by_method),
                       "warnings": list(r.warnings()), "params": kw,
                       "totals": _totals()})


def _rec_row(r) -> Dict[str, Any]:
    au = list(r.authors or [])
    authors = "; ".join(au[:3]) + (" et al." if len(au) > 3 else "")
    return {"uid": r.uid, "title": r.title or "", "authors": authors,
            "year": r.year, "journal": r.journal or "", "doi": r.doi or "",
            "source": r.source or "", "doc_type": r.doc_type or "",
            "has_abstract": bool((r.abstract or "").strip())}


def records(limit: int = 5000) -> str:
    c = _corpus()
    recs = S.result.records if S.result is not None else c.records
    return json.dumps({"deduplicated": S.result is not None, "count": len(recs),
                       "rows": [_rec_row(r) for r in recs[:int(limit)]]})


def decisions() -> str:
    if S.result is None:
        return json.dumps({"rows": []})
    return json.dumps({"rows": [
        {"kept": d.kept_uid, "removed": d.removed_uid, "method": d.method,
         "score": round(float(d.score), 3), "key": d.key,
         "kept_source": d.kept_source, "removed_source": d.removed_source,
         "kept_title": d.kept_title, "removed_title": d.removed_title}
        for d in S.result.report.decisions]})


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------
def prisma(screening_json: str = "{}") -> str:
    """Build the PRISMA 2020 flow.

    As in the command line, the arithmetic is validated only when the screening
    counts are supplied; without them the identification and deduplication
    stages are real and the screening stages are reported as 0.
    """
    _pkg()
    from corpusslr import cli
    corpus = _corpus()
    if not corpus.records:
        return json.dumps({"ok": False, "error": "There are no records yet."})
    screening = json.loads(screening_json or "{}")
    flow = cli._build_flow(corpus, S.result, screening)
    problems = flow.validate() if screening else []
    return json.dumps({
        "ok": True, "problems": problems, "svg": flow.to_svg(),
        "markdown": flow.to_markdown(), "deduplicated": S.result is not None,
        "screening_supplied": bool(screening),
        "note": "" if screening else
        "No screening counts were entered, so the screening stages are shown as 0."})


def prisma_s() -> str:
    pkg = _pkg()
    return pkg.prisma_s_markdown(_corpus(), S.result)


def audit() -> str:
    pkg = _pkg()
    return pkg.audit_markdown(_corpus())


def quality() -> str:
    pkg = _pkg()
    c = _corpus()
    recs = S.result.records if S.result is not None else c.records
    return pkg.quality_markdown(recs)


def overlap() -> str:
    return S.result.report.overlap_markdown() if S.result is not None else ""


EXPORTS = {
    "scopus_csv": ("to_scopus_csv", "corpusslr_scopus.csv", "text/csv"),
    "csv": ("to_csv", "corpusslr_records.csv", "text/csv"),
    "screening_csv": ("to_screening_csv", "corpusslr_screening.csv", "text/csv"),
    "ris": ("to_ris", "corpusslr_records.ris", "application/x-research-info-systems"),
    "bibtex": ("to_bibtex", "corpusslr_records.bib", "application/x-bibtex"),
}


def export(fmt: str) -> str:
    """Write the corpus in one format and return {filename, mime, text}."""
    pkg = _pkg()
    c = _corpus()
    recs = S.result.records if S.result is not None else c.records
    if not recs:
        return json.dumps({"ok": False, "error": "There are no records yet."})
    if fmt == "decisions_csv":
        if S.result is None:
            return json.dumps({"ok": False, "error": "Run deduplication first."})
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "d.csv")
            S.result.report.to_csv(p)
            with open(p, encoding="utf-8") as fh:
                text = fh.read()
        return json.dumps({"ok": True, "filename": "corpusslr_decisions.csv",
                           "mime": "text/csv", "text": text})
    if fmt not in EXPORTS:
        return json.dumps({"ok": False, "error": "unknown format " + fmt})
    fn, name, mime = EXPORTS[fmt]
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, name)
        getattr(pkg, fn)(recs, p)
        with open(p, encoding="utf-8", newline="") as fh:
            text = fh.read()
    return json.dumps({"ok": True, "filename": name, "mime": mime, "text": text})


# ---------------------------------------------------------------------------
# bundle
# ---------------------------------------------------------------------------
def bundle_zip(spec_json: str = "{}", screening_json: str = "{}") -> str:
    """Everything the session produced, as one zip (base64), for the methods file.

    The archive holds the exports, the PRISMA diagram and appendix, the strategy
    audit, the data-quality report, the decision log, the compiled queries and a
    README that states the package version and the date. It never contains an
    API key, because keys are not kept anywhere to be written.
    """
    import base64
    import zipfile
    c = _corpus()
    if not c.records:
        return json.dumps({"ok": False, "error": "There are no records yet."})
    parts: Dict[str, str] = {}
    for fmt in EXPORTS:
        e = json.loads(export(fmt))
        if e.get("ok"):
            parts[e["filename"]] = e["text"]
    if S.result is not None:
        e = json.loads(export("decisions_csv"))
        if e.get("ok"):
            parts[e["filename"]] = e["text"]
        parts["deduplication_overlap.md"] = overlap()
    p = json.loads(prisma(screening_json))
    if p.get("ok"):
        parts["prisma2020_flow.svg"] = p["svg"]
        parts["prisma2020_flow.md"] = p["markdown"]
    parts["prisma_s_appendix.md"] = prisma_s()
    parts["strategy_audit.md"] = audit()
    parts["data_quality.md"] = quality()
    spec = json.loads(spec_json or "{}")
    if spec.get("blocks"):
        parts["compiled_queries.json"] = compile_query(spec_json)
        parts["query_spec.json"] = json.dumps(spec, indent=1)
    tot = _totals()
    parts["README.txt"] = (
        "CorpusSLR web application export\n"
        "package version: %s\ndate: %s\nrecords identified: %s\n"
        "unique after deduplication: %s\nsources: %s\n\n"
        "Produced in the browser by the CorpusSLR package; no data left the\n"
        "browser except requests to the databases that were searched.\n"
        % (version(), date.today().isoformat(), tot["identified"],
           tot["unique"] if tot["unique"] is not None else "(not run)",
           ", ".join("%s %d" % kv for kv in sorted(tot["by_source"].items()))))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(parts):
            z.writestr(name, parts[name])
    return json.dumps({"ok": True, "filename": "corpusslr_export.zip",
                       "b64": base64.b64encode(buf.getvalue()).decode("ascii"),
                       "files": sorted(parts)})
