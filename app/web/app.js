/* CorpusSLR Web: page logic.
 *
 * The page never handles Python objects. It sends operation names and JSON text
 * to the engine and receives JSON text back. In the browser the engine is a web
 * worker running Pyodide; the tests supply an engine that runs the same Python
 * in Node, so the same page code is exercised end to end.
 *
 * Every string that comes from data (titles, error messages, file names) is
 * inserted with textContent, never as HTML. The PRISMA diagram is shown through
 * an <img> with a data: URL, in which a browser does not run scripts.
 */
(function () {
  "use strict";

  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  function el(tag, attrs, children) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      var v = attrs[k];
      if (v === null || v === undefined || v === false) return;
      if (k === "text") n.textContent = v;
      else if (k === "class") n.className = v;
      else n.setAttribute(k, v);
    });
    (children || []).forEach(function (c) {
      if (c === "" || c === null || c === undefined) return;
      n.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return n;
  }
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }

  // ---------------------------------------------------------------- engine
  function workerEngine() {
    var w = new Worker("worker.js");
    var pending = {}, seq = 0;
    w.onmessage = function (ev) {
      var p = pending[ev.data.id]; delete pending[ev.data.id];
      if (!p) return;
      if (ev.data.ok) p.resolve(ev.data.result); else p.reject(new Error(ev.data.error));
    };
    function send(op, args, transfer) {
      return new Promise(function (resolve, reject) {
        var id = ++seq; pending[id] = { resolve: resolve, reject: reject };
        w.postMessage({ id: id, op: op, args: args }, transfer || []);
      });
    }
    return {
      boot: function () { return send("boot", []); },
      call: function (op) { return send(op, Array.prototype.slice.call(arguments, 1)).then(function (t) { return JSON.parse(t); }); },
      text: function (op) { return send(op, Array.prototype.slice.call(arguments, 1)); },
      write: function (name, buf) { return send("write", [name, buf], [buf]); }
    };
  }
  var engine = window.CORPUSSLR_ENGINE || null;

  // ---------------------------------------------------------------- state
  var state = { blocks: [[], []], ready: false, tab: "records", rows: null, decisions: null, last: {}, total: 0 };
  var SOURCES = [
    { id: "openalex", label: "OpenAlex", keys: [], note: "No key needed." },
    { id: "crossref", label: "Crossref", keys: [], note: "No key needed. Relevance search; treat as supplementary." },
    { id: "pubmed", label: "PubMed", keys: [{ k: "api_key", label: "NCBI API key (optional)" }], note: "A key raises the rate limit." },
    { id: "semanticscholar", label: "Semantic Scholar", keys: [{ k: "api_key", label: "API key (optional)" }], note: "Relevance search; treat as supplementary." },
    { id: "scopus", label: "Scopus", keys: [{ k: "api_key", label: "Elsevier API key" }, { k: "insttoken", label: "Institutional token (optional)" }], note: "Requires a key." }
  ];
  var BLOCKED = [
    { id: "wos", label: "Web of Science", note: "The API does not allow requests from a browser page. Export from Web of Science and import the file." },
    { id: "arxiv", label: "arXiv", note: "The API does not allow requests from a browser page. Import an arXiv export file." }
  ];

  // ---------------------------------------------------------------- helpers
  function setStatus(kind, text) {
    var s = $("#engine"); s.className = "status " + kind; $("#engine-text").textContent = text;
  }
  function enable(ids, on) { ids.forEach(function (i) { $(i).disabled = !on; }); }
  function fail(container, message) { container.appendChild(el("div", { class: "item err", text: message })); }
  function show(step) {
    $$("#steps button").forEach(function (b) { b.classList.toggle("on", b.getAttribute("data-step") === step); });
    ["query", "collect", "dedup", "report"].forEach(function (s) { $("#step-" + s).classList.toggle("hidden", s !== step); });
    $("#hero").classList.toggle("hidden", step !== "query");
    if (step !== "query" && window.scrollTo) { try { window.scrollTo(0, 0); } catch (e) { /* not available in tests */ } }
  }
  function spec() {
    var y1 = parseInt($("#y1").value, 10), y2 = parseInt($("#y2").value, 10);
    return {
      blocks: state.blocks,
      years: (y1 && y2) ? [y1, y2] : null,
      doc_types: $$("input[name=dt]:checked").map(function (c) { return c.value; }),
      title_only: $("#title-only").checked
    };
  }
  function download(name, mime, data) {
    var blob = new Blob([data], { type: mime });
    var a = el("a", { href: URL.createObjectURL(blob), download: name });
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 2000);
  }
  function b64bytes(b64) {
    var bin = atob(b64), out = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  // ---------------------------------------------------------------- query
  function renderBlocks() {
    var root = $("#blocks"); clear(root);
    state.blocks.forEach(function (terms, bi) {
      var chips = el("div", { class: "chips" });
      terms.forEach(function (t, ti) {
        chips.appendChild(el("span", { class: "chip" }, [t, el("button", {
          type: "button", "aria-label": "Remove " + t, text: "\u00d7", "data-b": bi, "data-t": ti
        })]));
      });
      var input = el("input", { class: "term", type: "text", placeholder: bi === 0 ? "e.g. deep learning" : "add a term", "aria-label": "Term for concept " + (bi + 1), "data-b": bi });
      root.appendChild(el("div", { class: "block" }, [
        el("span", { class: "tag", text: bi === 0 ? "" : "AND" }), chips, input,
        state.blocks.length > 1 ? el("button", { type: "button", class: "rm", "aria-label": "Remove concept " + (bi + 1), "data-rm": bi, text: "Remove" }) : null
      ]));
    });
  }
  function addTerm(bi, value) {
    var v = value.trim(); if (!v) return;
    if (state.blocks[bi].indexOf(v) === -1) state.blocks[bi].push(v);
    renderBlocks(); compile();
  }
  var compileTimer = null;
  function compile() { clearTimeout(compileTimer); compileTimer = setTimeout(doCompile, 150); }
  function doCompile() {
    var out = $("#compiled"); clear(out);
    if (!state.ready) return Promise.resolve();
    if (!state.blocks.some(function (b) { return b.length; })) return Promise.resolve();
    return engine.call("compile_query", JSON.stringify(spec())).then(function (r) {
      clear(out);
      if (!r.ok) { out.appendChild(el("div", { class: "notice", text: r.error })); return; }
      r.warnings.forEach(function (w) { out.appendChild(el("div", { class: "notice", text: w })); });
      Object.keys(r.queries).forEach(function (k) {
        var q = r.queries[k];
        var head = el("header", {}, [el("span", { text: q.label }), el("span", {}, [
          el("span", { class: "badge " + (q.browser ? "live" : "file"), text: q.browser ? "searchable here" : "import export file" }), " ",
          el("button", { type: "button", class: "copy", "data-copy": k, text: "Copy" })])]);
        var body = q.error ? "Could not be compiled: " + q.error : (q.query + (q.filters ? "\n\nfilters: " + q.filters : ""));
        out.appendChild(el("div", { class: "q" }, [head, el("pre", { text: body, id: "q-" + k })]));
      });
    }).catch(function (e) { out.appendChild(el("div", { class: "notice err", text: e.message })); });
  }

  // ---------------------------------------------------------------- sources
  function renderSources() {
    var root = $("#sources"); clear(root);
    SOURCES.forEach(function (s) {
      var box = el("div", { class: "src" }, [el("div", { class: "row" }, [
        el("label", {}, [el("input", { type: "checkbox", "data-src": s.id, checked: s.id === "openalex" ? "checked" : null }), s.label]),
        el("span", { class: "small", text: s.note })])]);
      if (s.keys.length) {
        var keys = el("div", { class: "key" + (s.keys.length === 1 ? " one" : "") });
        s.keys.forEach(function (k) {
          keys.appendChild(el("label", {}, [k.label, el("input", { type: "password", autocomplete: "off", spellcheck: "false", "data-key": s.id + ":" + k.k })]));
        });
        box.appendChild(keys);
      }
      root.appendChild(box);
    });
    BLOCKED.forEach(function (s) {
      root.appendChild(el("div", { class: "src off" }, [el("div", { class: "row" }, [
        el("label", {}, [el("input", { type: "checkbox", disabled: "disabled" }), s.label]),
        el("span", { class: "badge file", text: "file import only" })]), el("p", { class: "small", text: s.note })]));
    });
  }
  function chosenSources() {
    var out = {};
    $$("input[data-src]").filter(function (c) { return c.checked; }).forEach(function (c) {
      var id = c.getAttribute("data-src"), cred = {};
      $$("input[data-key]").forEach(function (k) {
        var parts = k.getAttribute("data-key").split(":"), v = k.value.trim();
        if (parts[0] === id && v) cred[parts[1]] = v;
      });
      out[id] = cred;
    });
    return out;
  }
  function wipeKeys() { $$("input[data-key]").forEach(function (k) { k.value = ""; }); }

  function renderTotals(t) {
    var root = $("#totals"); clear(root);
    if (!t) return;
    root.appendChild(el("div", { class: "stat" }, [el("b", { text: String(t.identified) }), el("span", { text: "records identified" })]));
    Object.keys(t.by_source || {}).sort().forEach(function (k) {
      root.appendChild(el("div", { class: "stat" }, [el("b", { text: String(t.by_source[k]) }), el("span", { text: k })]));
    });
    enable(["#run-dedup", "#make-report"], t.identified > 0);
  }

  function search() {
    var chosen = chosenSources(), out = $("#search-report"); clear(out);
    if (!Object.keys(chosen).length) return fail(out, "Choose at least one database.");
    if (!state.blocks.some(function (b) { return b.length; })) return fail(out, "Enter a query in step 1 first.");
    $("#run-search").disabled = true;
    out.appendChild(el("div", { class: "notice", text: "Searching. A large request can take a minute." }));
    return engine.call("run_search", JSON.stringify(spec()), JSON.stringify(chosen),
      parseInt($("#max").value, 10) || 100, $("#email").value.trim()).then(function (r) {
      clear(out);
      if (!r.ok) fail(out, r.error);
      (r.report || []).forEach(function (x) {
        var item = el("div", { class: "item" + (x.ok ? "" : " err") });
        item.appendChild(el("b", { text: x.label + ": " }));
        item.appendChild(document.createTextNode(x.ok
          ? x.retrieved + " records retrieved" + (x.hits != null ? " of about " + x.hits : "") : x.error));
        out.appendChild(item);
      });
      if (r.totals) renderTotals(r.totals);
      wipeKeys();
    }).catch(function (e) { clear(out); fail(out, e.message); }).then(function () { $("#run-search").disabled = false; });
  }

  // ---------------------------------------------------------------- import
  function readFile(f) {
    if (f.arrayBuffer) return f.arrayBuffer();
    return new Promise(function (res, rej) { var r = new FileReader(); r.onload = function () { res(r.result); }; r.onerror = rej; r.readAsArrayBuffer(f); });
  }
  function importFiles(list) {
    var out = $("#import-report"), db = $("#db-name").value.trim(), chain = Promise.resolve();
    Array.prototype.slice.call(list).forEach(function (f) {
      chain = chain.then(function () { return readFile(f); }).then(function (buf) {
        return engine.write(f.name.replace(/[^\w.\- ]+/g, "_"), buf);
      }).then(function (path) {
        return engine.call("import_file", path, f.name, db, "");
      }).then(function (r) {
        var item = el("div", { class: "item" + (r.ok ? "" : " err") }, [el("b", { text: r.name + ": " })]);
        if (r.ok) {
          item.appendChild(document.createTextNode(r.records + " records as " + r.database +
            " (" + (r.format || "?") + (r.dialect ? ", " + r.dialect : "") + ")" + (r.n_rejected ? "; " + r.n_rejected + " rejected" : "")));
          out.appendChild(item);
          (r.warnings || []).forEach(function (w) { out.appendChild(el("div", { class: "item warn", text: w })); });
          renderTotals(r.totals);
        } else {
          item.appendChild(document.createTextNode(r.error)); out.appendChild(item);
        }
      }).catch(function (e) { fail(out, f.name + ": " + e.message); });
    });
    return chain;
  }

  // ---------------------------------------------------------------- dedup
  function dedup() {
    var out = $("#dedup-summary"); clear(out);
    var params = { fuzzy_threshold: parseFloat($("#p-fuzzy").value) || 0.93, year_tolerance: parseInt($("#p-year").value, 10) };
    if (isNaN(params.year_tolerance)) params.year_tolerance = 1;
    return engine.call("run_dedup", JSON.stringify(params)).then(function (r) {
      if (!r.ok) return fail(out, r.error);
      var pct = r.before ? Math.round(100 * r.after / r.before) : 0;
      [["before", "identified"], ["removed", "duplicates removed"], ["after", "unique records"]].forEach(function (p) {
        out.appendChild(el("div", { class: "stat" }, [el("b", { text: String(r[p[0]]) }), el("span", { text: p[1] })]));
      });
      Object.keys(r.by_method).sort().forEach(function (m) {
        out.appendChild(el("div", { class: "stat" }, [el("b", { text: String(r.by_method[m]) }), el("span", { text: "merged by " + m })]));
      });
      out.appendChild(el("div", { class: "bar", role: "img", "aria-label": pct + " percent of records remain" }, [el("i", { style: "width:" + pct + "%" })]));
      r.warnings.forEach(function (w) { out.appendChild(el("div", { class: "notice", text: w })); });
      renderTotals(r.totals);
      return loadTables();
    }).catch(function (e) { fail(out, e.message); });
  }
  function loadTables() {
    return Promise.all([engine.call("records", 5000), engine.call("decisions")]).then(function (a) {
      state.rows = a[0].rows; state.decisions = a[1].rows; state.total = a[0].count; drawTable();
    });
  }
  function drawTable() {
    var q = $("#filter").value.trim().toLowerCase();
    var head = $("#table thead"), body = $("#table tbody"); clear(head); clear(body);
    var cols, rows;
    if (state.tab === "records") {
      cols = [["title", "Title"], ["authors", "Authors"], ["year", "Year"], ["source", "Source"], ["doi", "DOI"]];
      rows = state.rows || [];
    } else {
      cols = [["method", "Method"], ["score", "Score"], ["kept_title", "Kept"], ["removed_title", "Removed"], ["removed_source", "From"]];
      rows = state.decisions || [];
    }
    head.appendChild(el("tr", {}, cols.map(function (c) { return el("th", { text: c[1] }); })));
    var shown = 0, matched = 0;
    rows.forEach(function (r) {
      if (q && JSON.stringify(r).toLowerCase().indexOf(q) === -1) return;
      matched++;
      if (shown >= 500) return;
      shown++;
      body.appendChild(el("tr", {}, cols.map(function (c) {
        var v = r[c[0]]; v = v == null ? "" : String(v);
        if (c[0] === "method") return el("td", {}, [el("span", { class: "pill", text: v })]);
        return el("td", { class: c[0].indexOf("title") >= 0 ? "t" : "", text: v });
      })));
    });
    var what = state.tab === "records" ? "records" : "merges";
    $("#table-note").textContent = (q ? matched + " of " + rows.length : rows.length) + " " + what +
      (matched > shown ? "; showing the first " + shown : "");
  }

  // ---------------------------------------------------------------- reports
  function screening() {
    var map = { records_excluded: "#s-excl", reports_not_retrieved: "#s-nr", studies_included: "#s-inc" }, s = {}, any = false;
    Object.keys(map).forEach(function (k) { var v = $(map[k]).value; if (v !== "") { s[k] = parseInt(v, 10); any = true; } });
    var ft = $("#s-ft").value;
    if (ft !== "") { s.fulltext_exclusions = { "excluded at full text": parseInt(ft, 10) }; any = true; }
    if (any && s.records_excluded == null) s.records_excluded = 0;
    return any ? s : {};
  }
  function box(title, node) { return el("div", { class: "rep" }, [el("header", { text: title }), el("div", { class: "body" }, [node])]); }
  function pre(text) { return el("pre", { text: text }); }
  function reports() {
    var out = $("#report-out"); clear(out);
    var scr = JSON.stringify(screening());
    return Promise.all([engine.call("prisma", scr), engine.text("prisma_s"), engine.text("audit"), engine.text("quality"), engine.text("overlap")]).then(function (a) {
      var p = a[0], wrap = el("div", { class: "reports" });
      if (!p.ok) return fail(out, p.error);
      if (p.note) wrap.appendChild(el("div", { class: "notice", text: p.note }));
      p.problems.forEach(function (x) { wrap.appendChild(el("div", { class: "notice err", text: "PRISMA arithmetic: " + x })); });
      wrap.appendChild(box("PRISMA 2020 flow diagram", el("img", { alt: "PRISMA 2020 flow diagram", src: "data:image/svg+xml;charset=utf-8," + encodeURIComponent(p.svg) })));
      wrap.appendChild(box("PRISMA-S search appendix", pre(a[1])));
      wrap.appendChild(box("Search strategy audit", pre(a[2])));
      wrap.appendChild(box("Data quality of the records", pre(a[3])));
      if (a[4]) wrap.appendChild(box("Overlap between databases", pre(a[4])));
      out.appendChild(wrap);
      state.last = { svg: p.svg, appendix: a[1] };
      drawDownloads();
    }).catch(function (e) { fail(out, e.message); });
  }
  var FORMATS = [["scopus_csv", "Scopus CSV", "for bibliometrix, VOSviewer, EmbedSLR"], ["csv", "CSV", "all fields"],
    ["screening_csv", "Screening CSV", "title, abstract, DOI"], ["ris", "RIS", "for reference managers"],
    ["bibtex", "BibTeX", "for LaTeX"], ["decisions_csv", "Merge log", "every deduplication decision"]];
  function drawDownloads() {
    var root = $("#downloads"); clear(root);
    root.appendChild(el("button", { type: "button", class: "all", "data-bundle": "1" }, ["Everything (zip)", el("small", { text: "exports, diagram, appendix, audit, queries" })]));
    FORMATS.forEach(function (f) {
      root.appendChild(el("button", { type: "button", "data-fmt": f[0] }, [f[1], el("small", { text: f[2] })]));
    });
    if (state.last.svg) root.appendChild(el("button", { type: "button", "data-svg": "1" }, ["PRISMA diagram (SVG)", el("small", { text: "vector, for the manuscript" })]));
    root.appendChild(el("button", { type: "button", "data-md": "1" }, ["PRISMA-S appendix", el("small", { text: "Markdown" })]));
  }
  function bundle() {
    return engine.call("bundle_zip", JSON.stringify(spec()), JSON.stringify(screening())).then(function (r) {
      if (!r.ok) return fail($("#report-out"), r.error);
      download(r.filename, "application/zip", b64bytes(r.b64));
    });
  }

  // ---------------------------------------------------------------- demo
  var DEMO_QUERY = [["deep learning", "convolutional neural network"], ["diabetic retinopathy"]];
  var DEMO_A = "TY  - JOUR\nTI  - Deep learning for diabetic retinopathy screening\nAU  - Kowalski, Jan\nPY  - 2021\nDO  - 10.1000/abc.123\nJO  - Journal of Examples\nER  -\n\nTY  - JOUR\nTI  - Convolutional networks for retinal image grading\nAU  - Nowak, Anna\nPY  - 2022\nDO  - 10.1000/xyz.9\nER  -\n";
  var DEMO_B = "TY  - JOUR\nTI  - Deep learning for diabetic retinopathy screening\nAU  - Kowalski, J.\nPY  - 2021\nDO  - https://doi.org/10.1000/ABC.123\nER  -\n\nTY  - JOUR\nTI  - Transfer learning in fundus photography\nAU  - Wisniewski, Piotr\nPY  - 2023\nDO  - 10.1000/tl.77\nER  -\n";
  function demo() {
    state.blocks = DEMO_QUERY.map(function (b) { return b.slice(); });
    $("#y1").value = 2020; $("#y2").value = 2024;
    renderBlocks();
    var files = [["scopus_example.ris", DEMO_A, "Scopus"], ["wos_example.ris", DEMO_B, "Web of Science"]];
    var out = $("#import-report"); clear(out);
    var chain = engine.call("reset").then(doCompile);
    files.forEach(function (f) {
      chain = chain.then(function () { return engine.write(f[0], new TextEncoder().encode(f[1]).buffer); })
        .then(function (p) { return engine.call("import_file", p, f[0], f[2], ""); })
        .then(function (r) {
          out.appendChild(el("div", { class: "item" }, [el("b", { text: r.name + ": " }), r.records + " records as " + r.database]));
          renderTotals(r.totals);
        });
    });
    return chain.then(function () { show("dedup"); return dedup(); });
  }

  // ---------------------------------------------------------------- wiring
  function wire() {
    $("#steps").addEventListener("click", function (e) { var s = e.target.getAttribute && e.target.getAttribute("data-step"); if (s) show(s); });
    $("#blocks").addEventListener("keydown", function (e) {
      if (e.target.classList.contains("term") && (e.key === "Enter" || e.key === ",")) {
        e.preventDefault(); addTerm(parseInt(e.target.getAttribute("data-b"), 10), e.target.value);
      }
    });
    $("#blocks").addEventListener("focusout", function (e) {
      if (e.target.classList && e.target.classList.contains("term") && e.target.value.trim()) addTerm(parseInt(e.target.getAttribute("data-b"), 10), e.target.value);
    });
    $("#blocks").addEventListener("click", function (e) {
      var t = e.target;
      if (t.getAttribute("data-t") !== null) { state.blocks[+t.getAttribute("data-b")].splice(+t.getAttribute("data-t"), 1); renderBlocks(); compile(); }
      if (t.getAttribute("data-rm") !== null) { state.blocks.splice(+t.getAttribute("data-rm"), 1); renderBlocks(); compile(); }
    });
    $("#add-block").addEventListener("click", function () { state.blocks.push([]); renderBlocks(); });
    ["#y1", "#y2", "#title-only"].forEach(function (s) { $(s).addEventListener("change", compile); });
    $$("input[name=dt]").forEach(function (c) { c.addEventListener("change", compile); });
    $("#compiled").addEventListener("click", function (e) {
      var k = e.target.getAttribute && e.target.getAttribute("data-copy");
      if (k && navigator.clipboard) navigator.clipboard.writeText($("#q-" + k).textContent).then(function () { e.target.textContent = "Copied"; setTimeout(function () { e.target.textContent = "Copy"; }, 1200); });
    });
    $("#run-search").addEventListener("click", search);
    var drop = $("#drop"), input = $("#files");
    drop.addEventListener("click", function () { input.click(); });
    drop.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
    ["dragover", "dragenter"].forEach(function (n) { drop.addEventListener(n, function (e) { e.preventDefault(); drop.classList.add("over"); }); });
    ["dragleave", "drop"].forEach(function (n) { drop.addEventListener(n, function () { drop.classList.remove("over"); }); });
    drop.addEventListener("drop", function (e) { e.preventDefault(); importFiles(e.dataTransfer.files); });
    input.addEventListener("change", function () { importFiles(input.files); });
    $("#run-dedup").addEventListener("click", dedup);
    $("#dd-tabs").addEventListener("click", function (e) {
      var t = e.target.getAttribute && e.target.getAttribute("data-t");
      if (t) { state.tab = t; $$("#dd-tabs button").forEach(function (b) { b.classList.toggle("on", b === e.target); }); drawTable(); }
    });
    $("#filter").addEventListener("input", drawTable);
    $("#make-report").addEventListener("click", reports);
    $("#downloads").addEventListener("click", function (e) {
      var b = e.target.closest ? e.target.closest("button") : e.target; if (!b) return;
      if (b.getAttribute("data-bundle")) return bundle();
      if (b.getAttribute("data-svg")) return download("prisma2020_flow.svg", "image/svg+xml", state.last.svg);
      if (b.getAttribute("data-md")) return download("prisma_s_appendix.md", "text/markdown", state.last.appendix);
      var f = b.getAttribute("data-fmt");
      if (f) engine.call("export", f).then(function (r) { if (r.ok) download(r.filename, r.mime, r.text); else fail($("#report-out"), r.error); });
    });
    $("#load-demo").addEventListener("click", demo);
  }

  function start() {
    renderBlocks(); renderSources(); wire();
    if (!engine) engine = workerEngine();
    setStatus("", "Loading Python engine (about 14 MB, once)");
    return Promise.resolve(engine.boot()).then(function (v) {
      state.ready = true; $("#ver").textContent = v; $("#ver2").textContent = v;
      setStatus("ready", "Engine ready, package " + v);
      enable(["#load-demo", "#run-search"], true);
      return doCompile();
    }).catch(function (e) {
      setStatus("fail", "The Python engine did not start");
      var n = $("#main"); n.insertBefore(el("p", { class: "notice err", text: "The engine could not be loaded: " + e.message + ". The page needs a current browser with WebAssembly and web workers." }), n.firstChild);
    });
  }
  window.CORPUSSLR_READY = start();
})();
