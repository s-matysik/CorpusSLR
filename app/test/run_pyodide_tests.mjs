// Runs the page's Python layer inside the real Pyodide runtime, in Node.
// It uses the same bundle the page serves (built by tools/build_app.py), the
// same zip of the package and the same bridge module, so a failure here is a
// failure the browser would show. Nothing in this file touches the network:
// HTTP is a scripted XMLHttpRequest placed on globalThis, which is exactly the
// object the bridge's transport reads in a worker.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadPyodide } from "pyodide";

const here = path.dirname(fileURLToPath(import.meta.url));
const dist = process.env.APP_DIST || path.join(here, "..", "dist");
const SECRET = "SECRETKEY-1234567890";

const RIS = `TY  - JOUR
TI  - Deep learning for diabetic retinopathy screening
AU  - Kowalski, Jan
PY  - 2021
DO  - 10.1000/abc.123
ER  -

TY  - JOUR
TI  - Transfer learning in fundus photography
AU  - Nowak, Anna
PY  - 2023
DO  - 10.1000/tl.77
ER  -
`;

const SPEC = { blocks: [["deep learning"], ["diabetic retinopathy"]], years: [2020, 2024], doc_types: ["article"] };

// A scripted XMLHttpRequest. Each instance records what the bridge asked for.
const requests = [];
let reply = () => ({ status: 200, body: "{}" });
globalThis.XMLHttpRequest = class {
  open(method, url, async) { this.method = method; this.url = url; this.async = async; this.h = {}; }
  setRequestHeader(k, v) { this.h[k] = v; }
  send() {
    requests.push({ method: this.method, url: this.url, async: this.async, headers: this.h });
    const r = reply(this.url, this.h);
    this.status = r.status; this.responseText = r.body;
  }
};

// Pyodide accepts a plain Uint8Array, not a Node Buffer subclass.
const bytes = (buf) => new Uint8Array(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength));

let py, W;
const call = (fn, ...args) => JSON.parse(W[fn](...args));

test("the runtime starts and the package imports with the requests stand-in", async () => {
  py = await loadPyodide();
  const zip = fs.readFileSync(path.join(dist, "corpusslr.zip"));
  py.unpackArchive(bytes(zip), "zip", { extractDir: "/lib" });
  py.FS.writeFile("/lib/corpusslr_web.py", bytes(fs.readFileSync(path.join(dist, "corpusslr_web.py"))));
  py.runPython("import sys; sys.path.insert(0, '/lib')");
  W = py.pyimport("corpusslr_web");
  const v = W.version();
  const manifest = JSON.parse(fs.readFileSync(path.join(dist, "manifest.json"), "utf8"));
  assert.equal(v, manifest.corpusslr);
  assert.equal(py.runPython("import requests; requests.__name__"), "requests");
  assert.equal(py.runPython("import requests; hasattr(requests, 'Session')"), true);
});

test("a query compiles to every dialect inside the browser runtime", () => {
  const r = call("compile_query", JSON.stringify(SPEC));
  assert.equal(r.ok, true);
  assert.deepEqual(Object.keys(r.queries).sort(),
    ["arxiv", "crossref", "openalex", "pubmed", "scopus", "semanticscholar", "wos"]);
  assert.match(r.queries.scopus.query, /^TITLE-ABS-KEY\(/);
});

test("a live search goes through the synchronous XHR, with forbidden headers dropped", () => {
  requests.length = 0;
  reply = () => ({ status: 200, body: JSON.stringify({
    meta: { count: 1, next_cursor: null },
    results: [{ id: "https://openalex.org/W1", doi: "https://doi.org/10.1000/abc.123",
      title: "Deep learning for diabetic retinopathy screening", publication_year: 2021,
      type: "article", authorships: [{ author: { display_name: "Kowalski J" } }],
      abstract_inverted_index: { An: [0], abstract: [1] } }] }) });
  W.reset();
  const r = call("run_search", JSON.stringify(SPEC), JSON.stringify({ openalex: {} }), 10, "me@example.org");
  assert.equal(r.report[0].ok, true, JSON.stringify(r));
  assert.equal(r.report[0].retrieved, 1);
  assert.ok(requests.length >= 1);
  for (const q of requests) {
    assert.equal(q.async, false, "must be synchronous inside a worker");
    assert.match(q.url, /^https:\/\/api\.openalex\.org\//);
    assert.ok(!Object.keys(q.headers).some((k) => k.toLowerCase() === "user-agent"));
  }
});

test("status 0 from the browser is explained as a CORS or network block", () => {
  reply = () => ({ status: 0, body: "" });
  const r = call("run_search", JSON.stringify(SPEC), JSON.stringify({ crossref: {} }), 5);
  assert.equal(r.report[0].ok, false);
  assert.match(r.report[0].error, /CORS/);
});

test("a blocked request fails after one call instead of retrying", () => {
  requests.length = 0;
  reply = () => ({ status: 0, body: "" });
  const t0 = Date.now();
  const r = call("run_search", JSON.stringify(SPEC), JSON.stringify({ semanticscholar: {} }), 100);
  assert.equal(r.report[0].ok, false);
  assert.equal(requests.length, 1);
  assert.ok(Date.now() - t0 < 3000, "took " + (Date.now() - t0) + " ms");
});

test("a key echoed by the server never reaches the page", () => {
  reply = () => ({ status: 401, body: "Invalid key " + SECRET });
  const r = call("run_search", JSON.stringify(SPEC), JSON.stringify({ scopus: { api_key: SECRET } }), 5);
  assert.equal(r.report[0].ok, false);
  assert.ok(!JSON.stringify(r).includes(SECRET));
});

test("an uploaded file is parsed, merged with the search, deduplicated and exported", () => {
  reply = () => ({ status: 200, body: JSON.stringify({
    meta: { count: 1, next_cursor: null },
    results: [{ id: "https://openalex.org/W1", doi: "https://doi.org/10.1000/ABC.123",
      title: "Deep learning for diabetic retinopathy screening", publication_year: 2021,
      type: "article", authorships: [], abstract_inverted_index: { An: [0] } }] }) });
  W.reset();
  call("run_search", JSON.stringify(SPEC), JSON.stringify({ openalex: {} }), 10);
  py.FS.mkdirTree("/upload");
  py.FS.writeFile("/upload/export.ris", new TextEncoder().encode(RIS));
  const imp = call("import_file", "/upload/export.ris", "export.ris", "Scopus", "");
  assert.equal(imp.ok, true, JSON.stringify(imp));
  assert.equal(imp.records, 2);
  const d = call("run_dedup", "{}");
  assert.deepEqual([d.before, d.after, d.removed], [3, 2, 1]);
  const p = call("prisma", "{}");
  assert.equal(p.ok, true);
  assert.match(p.svg.trimStart(), /^<svg/);
  for (const fmt of ["scopus_csv", "csv", "screening_csv", "ris", "bibtex", "decisions_csv"]) {
    const e = call("export", fmt);
    assert.equal(e.ok, true, fmt);
    assert.ok(e.text.trim().length > 0, fmt);
  }
  assert.match(W.prisma_s(), /OpenAlex/);
});

test("a UTF-16 export, which silently yielded no records before 1.1, is read", () => {
  W.reset();
  const raw = Buffer.concat([Buffer.from([0xff, 0xfe]), Buffer.from(RIS, "utf16le")]);
  py.FS.writeFile("/upload/utf16.ris", bytes(raw));
  const imp = call("import_file", "/upload/utf16.ris", "utf16.ris", "", "");
  assert.equal(imp.ok, true, JSON.stringify(imp));
  assert.equal(imp.records, 2);
});
