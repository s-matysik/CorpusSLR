// Drives the real page (index.html + app.js) in jsdom, with the real Python
// package running in Pyodide underneath. jsdom is not a browser: layout, CSS and
// the web worker are not exercised. What is exercised is every handler, every
// piece of text the page builds from data, and the round trip to the package.
import { test, before } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";
import { loadPyodide } from "pyodide";

const here = path.dirname(fileURLToPath(import.meta.url));
const dist = process.env.APP_DIST || path.join(here, "..", "dist");
const bytes = (b) => new Uint8Array(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength));

let dom, win, doc, py, W;
const downloads = [];
const xhrLog = [];
let xhrReply = () => ({ status: 200, body: "{}" });

function $(s) { return doc.querySelector(s); }
async function settle(ms = 40) { await new Promise((r) => setTimeout(r, ms)); }
async function until(fn, label, tries = 200) {
  for (let i = 0; i < tries; i++) { if (fn()) return; await settle(25); }
  assert.fail("timed out waiting for " + label);
}
function click(sel) { $(sel).dispatchEvent(new win.MouseEvent("click", { bubbles: true })); }
function type(sel, value) { const n = $(sel); n.value = value; n.dispatchEvent(new win.Event("input", { bubbles: true })); n.dispatchEvent(new win.Event("change", { bubbles: true })); }
function addTerm(blockIndex, term) {
  const input = doc.querySelectorAll("#blocks input.term")[blockIndex];
  input.value = term;
  input.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
}

before(async () => {
  py = await loadPyodide();
  py.unpackArchive(bytes(fs.readFileSync(path.join(dist, "corpusslr.zip"))), "zip", { extractDir: "/lib" });
  py.FS.writeFile("/lib/corpusslr_web.py", bytes(fs.readFileSync(path.join(dist, "corpusslr_web.py"))));
  py.runPython("import sys; sys.path.insert(0, '/lib')");
  W = py.pyimport("corpusslr_web");
  py.FS.mkdirTree("/upload");

  globalThis.XMLHttpRequest = class {
    open(m, u) { this.u = u; this.h = {}; }
    setRequestHeader(k, v) { this.h[k] = v; }
    send() { xhrLog.push({ url: this.u, headers: this.h }); const r = xhrReply(this.u); this.status = r.status; this.responseText = r.body; }
  };

  const html = fs.readFileSync(path.join(dist, "index.html"), "utf8").replace(/<script[^>]*app\.js[^>]*><\/script>/, "");
  dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true, url: "https://s-matysik.github.io/CorpusSLR/app/" });
  win = dom.window; doc = win.document;
  win.scrollTo = () => {};
  win.URL.createObjectURL = (blob) => { return "blob:test/" + downloads.length; };
  win.URL.revokeObjectURL = () => {};
  win.HTMLAnchorElement.prototype.click = function () { downloads.push({ name: this.getAttribute("download"), href: this.getAttribute("href") }); };
  win.TextEncoder = TextEncoder;
  win.Blob = class { constructor(parts, opts) { this.parts = parts; this.type = opts && opts.type; } };
  win.CORPUSSLR_ENGINE = {
    boot: async () => W.version(),
    call: async (op, ...a) => JSON.parse(W[op](...a)),
    text: async (op, ...a) => W[op](...a),
    write: async (name, buf) => { py.FS.writeFile("/upload/" + name, new Uint8Array(buf)); return "/upload/" + name; },
  };
  win.eval(fs.readFileSync(path.join(dist, "app.js"), "utf8"));
  await win.CORPUSSLR_READY;
});

test("the page starts, reports the package version and enables the demo", async () => {
  assert.match($("#engine").className, /ready/);
  assert.equal($("#ver").textContent, JSON.parse(fs.readFileSync(path.join(dist, "manifest.json"), "utf8")).corpusslr);
  assert.equal($("#load-demo").disabled, false);
  assert.equal(doc.querySelectorAll("#sources input[data-src]").length, 9, "all nine databases are selectable");
  assert.equal(doc.querySelectorAll("#sources .src.off").length, 0, "none is shown as import-only");
  const ids = [...doc.querySelectorAll("#sources input[data-src]")].map((n) => n.getAttribute("data-src")).sort();
  assert.deepEqual(ids, ["arxiv", "biorxiv", "crossref", "medrxiv", "openalex", "pubmed", "scopus", "semanticscholar", "wos"]);
});

test("typing terms builds the query and shows nine compiled dialects", async () => {
  addTerm(0, "deep learning"); addTerm(0, "neural network"); addTerm(1, "retinopathy");
  type("#y1", "2020"); type("#y2", "2024");
  await until(() => doc.querySelectorAll("#compiled .q").length === 9, "nine compiled queries");
  assert.equal(doc.querySelectorAll("#blocks .chip").length, 3);
  assert.match($("#q-scopus").textContent, /TITLE-ABS-KEY\("deep learning"/);
  assert.match($("#q-pubmed").textContent, /retinopathy/);
  assert.equal(doc.querySelectorAll("#compiled .badge.file").length, 2);
  // removing a term recompiles
  doc.querySelector("#blocks .chip button").dispatchEvent(new win.MouseEvent("click", { bubbles: true }));
  await settle(300);
  assert.equal(doc.querySelectorAll("#blocks .chip").length, 2);
});

test("a live search reports the count and wipes the key fields afterwards", async () => {
  xhrLog.length = 0;
  xhrReply = () => ({ status: 200, body: JSON.stringify({ meta: { count: 1, next_cursor: null }, results: [{
    id: "https://openalex.org/W9", doi: "https://doi.org/10.1000/live.1", title: "A live record", publication_year: 2022,
    type: "article", authorships: [], abstract_inverted_index: { x: [0] } }] }) });
  click("#steps [data-step=collect]");
  await until(() => !$("#step-collect").classList.contains("hidden"), "collect panel");
  $("#sources input[data-key='scopus:api_key']").value = "SECRETKEY-1234567890";
  click("#run-search");
  await until(() => /1 records retrieved/.test($("#search-report").textContent), "search report");
  assert.ok(xhrLog.length >= 1 && xhrLog.every((x) => x.url.startsWith("https://api.openalex.org/")), "only the chosen host was called");
  assert.equal($("#sources input[data-key='scopus:api_key']").value, "", "keys are cleared after a search");
  assert.ok(!doc.body.textContent.includes("SECRETKEY-1234567890"));
  assert.equal($("#totals .stat b").textContent, "1");
});

test("a blocked request is explained, not shown as a bare network error", async () => {
  xhrReply = () => ({ status: 0, body: "" });
  $("#sources input[data-src=openalex]").checked = false;
  $("#sources input[data-src=crossref]").checked = true;
  click("#run-search");
  await until(() => /CORS/.test($("#search-report").textContent), "CORS explanation");
  $("#sources input[data-src=crossref]").checked = false;
  $("#sources input[data-src=openalex]").checked = true;
});

const WOS_BODY = JSON.stringify({ QueryResult: { RecordsFound: 1, RecordsSearched: 9 }, Data: { Records: { records: { REC: [{
  UID: "WOS:000111", static_data: { summary: { pub_info: { pubyear: 2023, pubtype: "Journal" },
    titles: { title: [{ type: "source", content: "J Test" }, { type: "item", content: "Deep learning for retinopathy in WoS" }] },
    names: { name: { seq_no: 1, role: "author", full_name: "Smith, A" } }, doctypes: { doctype: "Article" } },
    fullrecord_metadata: { abstracts: { abstract: { abstract_text: { p: "Abstract." } } } } },
  dynamic_data: { cluster_related: { identifiers: { identifier: [{ type: "doi", value: "10.5001/wos.1" }] } } } }] } } } });
const ARXIV_BODY = `<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom" xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"><opensearch:totalResults>1</opensearch:totalResults><entry><id>http://arxiv.org/abs/2401.00001v1</id><published>2024-01-02T00:00:00Z</published><title>Deep learning for retinopathy on arXiv</title><summary>S</summary><author><name>J Kowalski</name></author></entry></feed>`;
const BIORXIV_BODY = JSON.stringify({ messages: [{ status: "ok", interval: "x", cursor: 0, count: 1, total: 1 }], collection: [{
  doi: "10.1101/2024.03.15.000001", title: "Deep learning for retinopathy on bioRxiv", authors: "Kowalski, J.", date: "2024-03-15",
  version: "1", type: "new results", category: "bioinformatics", abstract: "Deep learning for retinopathy.", server: "biorxiv" }] });

test("Web of Science and arXiv go through the proxy field, bioRxiv goes direct, and the key is wiped but the address is kept", async () => {
  xhrLog.length = 0;
  const PROXY = "https://proxy.example.workers.dev";
  xhrReply = (url) => url.includes("/wos/api/wos") ? { status: 200, body: WOS_BODY }
    : url.includes("/arxiv/api/query") ? { status: 200, body: ARXIV_BODY }
    : url.startsWith("https://api.biorxiv.org/") ? { status: 200, body: BIORXIV_BODY } : { status: 404, body: "" };
  click("#steps [data-step=collect]");
  $("#sources input[data-src=openalex]").checked = false;
  for (const id of ["wos", "arxiv", "biorxiv"]) $("#sources input[data-src=" + id + "]").checked = true;
  $("#sources input[data-key='wos:api_key']").value = "WOSSECRET-1234567890";
  type("#proxy", PROXY + "/");
  click("#run-search");
  await until(() => doc.querySelectorAll("#search-report .item").length >= 3 || /retrieved/.test($("#search-report").textContent), "three reports");
  await until(() => !$("#run-search").disabled, "search finished");
  const text = $("#search-report").textContent;
  assert.ok(!/error|blocked|needs/i.test(text.replace(/0 errors/i, "")), text);
  const urls = xhrLog.map((x) => x.url);
  assert.ok(urls.some((u) => u.startsWith(PROXY + "/wos/api/wos")), "wos via proxy: " + urls);
  assert.ok(urls.some((u) => u.startsWith(PROXY + "/arxiv/api/query")), "arxiv via proxy");
  assert.ok(urls.some((u) => u.startsWith("https://api.biorxiv.org/details/biorxiv")), "biorxiv direct");
  assert.ok(!urls.some((u) => /^https?:\/\/(api\.clarivate\.com|export\.arxiv\.org)/.test(u)), "neither blocked host is called directly");
  assert.ok(urls.every((u) => !u.includes("WOSSECRET")), "the key is not in any address");
  assert.ok(xhrLog.filter((x) => x.url.includes("/wos/")).every((x) => x.headers["X-ApiKey"] === "WOSSECRET-1234567890"));
  assert.equal($("#sources input[data-key='wos:api_key']").value, "", "the key is wiped");
  assert.equal($("#proxy").value, PROXY + "/", "the address is not a secret and stays");
  assert.ok(!doc.body.textContent.includes("WOSSECRET"));
  const by = [...doc.querySelectorAll("#totals .stat")].map((n) => n.textContent);
  for (const label of ["Web of Science Core Collection", "arXiv", "bioRxiv"]) assert.ok(by.some((t) => t.includes(label)), label + " in " + by);
  for (const id of ["wos", "arxiv", "biorxiv"]) $("#sources input[data-src=" + id + "]").checked = false;
  $("#sources input[data-src=openalex]").checked = true;
});

test("Web of Science and arXiv without a proxy address are explained and call nothing", async () => {
  xhrLog.length = 0;
  type("#proxy", "");
  $("#sources input[data-src=openalex]").checked = false;
  for (const id of ["wos", "arxiv"]) $("#sources input[data-src=" + id + "]").checked = true;
  $("#sources input[data-key='wos:api_key']").value = "WOSSECRET-1234567890";
  click("#run-search");
  await until(() => /proxy/i.test($("#search-report").textContent), "proxy explanation");
  await until(() => !$("#run-search").disabled, "search finished");
  assert.equal(xhrLog.length, 0, "no request without a proxy");
  assert.ok(!doc.body.textContent.includes("WOSSECRET"));
  $("#sources input[data-key='wos:api_key']").value = "";
  for (const id of ["wos", "arxiv"]) $("#sources input[data-src=" + id + "]").checked = false;
  $("#sources input[data-src=openalex]").checked = true;
});

test("the example loads, deduplicates and shows the merge with its evidence", async () => {
  click("#steps [data-step=query]");
  click("#load-demo");
  await until(() => $("#dedup-summary .stat") && doc.querySelectorAll("#table tbody tr").length > 0, "demo result");
  const stats = [...doc.querySelectorAll("#dedup-summary .stat b")].map((b) => b.textContent);
  assert.deepEqual(stats.slice(0, 3), ["4", "1", "3"]);
  assert.equal(doc.querySelectorAll("#table tbody tr").length, 3);
  click("#dd-tabs [data-t=decisions]");
  assert.equal(doc.querySelectorAll("#table tbody tr").length, 1);
  assert.equal($("#table .pill").textContent, "doi");
  click("#dd-tabs [data-t=records]");
  type("#filter", "fundus");
  assert.equal(doc.querySelectorAll("#table tbody tr").length, 1);
  type("#filter", "");
});

test("reports render the diagram as an image and arithmetic errors are shown", async () => {
  click("#steps [data-step=report]");
  click("#make-report");
  await until(() => $("#report-out img"), "report image");
  assert.match($("#report-out img").getAttribute("src"), /^data:image\/svg\+xml/);
  assert.match($("#report-out").textContent, /PRISMA-S search appendix/);
  assert.match($("#report-out").textContent, /No screening counts were entered/);
  type("#s-inc", "50");
  click("#make-report");
  await until(() => /PRISMA arithmetic/.test($("#report-out").textContent), "arithmetic warning");
  type("#s-inc", "");
});

test("every download button produces a file with the right name", async () => {
  click("#make-report");
  await until(() => doc.querySelectorAll("#downloads button").length >= 8, "download buttons");
  downloads.length = 0;
  for (const b of doc.querySelectorAll("#downloads button")) b.dispatchEvent(new win.MouseEvent("click", { bubbles: true }));
  await until(() => downloads.length >= 9, "all downloads");
  const names = downloads.map((d) => d.name).sort();
  for (const n of ["corpusslr_export.zip", "corpusslr_scopus.csv", "corpusslr_records.csv", "corpusslr_screening.csv",
    "corpusslr_records.ris", "corpusslr_records.bib", "corpusslr_decisions.csv", "prisma2020_flow.svg", "prisma_s_appendix.md"]) {
    assert.ok(names.includes(n), "missing " + n + " in " + names.join(","));
  }
});

test("markup in a record title is shown as text and never becomes an element", async () => {
  const evil = "TY  - JOUR\nTI  - <img src=x onerror=alert(1)> Injected title\nAU  - <b>Bold</b>, Author\nPY  - 2020\nDO  - 10.1000/evil.1\nER  -\n";
  const file = { name: "evil.ris", arrayBuffer: async () => new TextEncoder().encode(evil).buffer };
  click("#steps [data-step=collect]");
  const input = $("#files");
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  input.dispatchEvent(new win.Event("change", { bubbles: true }));
  await until(() => /evil\.ris/.test($("#import-report").textContent), "import report");
  click("#steps [data-step=dedup]"); click("#run-dedup");
  await until(() => /Injected title/.test($("#table").textContent), "evil row");
  assert.equal(doc.querySelectorAll("#table img").length, 0);
  assert.equal(doc.querySelectorAll("#table b").length, 0);
  assert.ok($("#table").textContent.includes("<img src=x onerror=alert(1)>"));
});

test("a file that cannot be parsed is named in the error", async () => {
  const bad = { name: "empty.ris", arrayBuffer: async () => new ArrayBuffer(0) };
  click("#steps [data-step=collect]");
  const input = $("#files");
  Object.defineProperty(input, "files", { value: [bad], configurable: true });
  input.dispatchEvent(new win.Event("change", { bubbles: true }));
  await until(() => $("#import-report .item.err"), "error item");
  assert.match($("#import-report .item.err").textContent, /empty\.ris/);
});

test("the shipped page references nothing outside its own directory", () => {
  const html = fs.readFileSync(path.join(dist, "index.html"), "utf8");
  const css = fs.readFileSync(path.join(dist, "app.css"), "utf8");
  const refs = [...html.matchAll(/(?:src|href)="([^"]+)"/g)].map((m) => m[1]).filter((u) => /^(https?:)?\/\//.test(u));
  // Two outside links are allowed and both are plain anchors, not loaded resources:
  // the credit to Pyodide and the instructions for the user's own proxy.
  const ALLOWED = ["https://pyodide.org", "https://github.com/s-matysik/CorpusSLR/tree/main/app/proxy"];
  assert.deepEqual(refs.filter((u) => !ALLOWED.includes(u)), [], "only the two documented links may point outside");
  assert.ok(!/<(script|link|img|iframe)[^>]+(src|href)="https?:/i.test(html), "no outside resource is loaded");
  assert.ok(!/url\(\s*['"]?https?:/.test(css) && !/@import/.test(css));
  assert.ok(/Content-Security-Policy/.test(html) && /object-src 'none'/.test(html));
});
