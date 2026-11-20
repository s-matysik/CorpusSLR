// Runs Pyodide and the CorpusSLR package off the page's main thread.
// Synchronous XMLHttpRequest is allowed here and nowhere else, which is why the
// Python layer uses it: the package is written against a blocking HTTP client.
/* global loadPyodide */
importScripts("pyodide/pyodide.js");

let py = null;
let W = null;

async function boot() {
  py = await loadPyodide({ indexURL: "pyodide/" });
  const zip = await (await fetch("corpusslr.zip")).arrayBuffer();
  py.unpackArchive(zip, "zip", { extractDir: "/lib" });
  const bridge = await (await fetch("corpusslr_web.py")).text();
  py.FS.writeFile("/lib/corpusslr_web.py", bridge);
  py.runPython("import sys; sys.path.insert(0, '/lib')");
  W = py.pyimport("corpusslr_web");
  py.FS.mkdirTree("/upload");
  return W.version();
}

self.onmessage = async (ev) => {
  const { id, op, args } = ev.data;
  try {
    let result;
    if (op === "boot") {
      result = await boot();
    } else if (op === "write") {
      const [name, buffer] = args;
      py.FS.writeFile("/upload/" + name, new Uint8Array(buffer));
      result = "/upload/" + name;
    } else {
      result = W[op](...args);
    }
    self.postMessage({ id, ok: true, result });
  } catch (err) {
    // Python exceptions carry the traceback; the page shows only the last line.
    const text = String(err && err.message ? err.message : err).trim().split("\n").filter(Boolean).pop();
    self.postMessage({ id, ok: false, error: text });
  }
};
