// Tests the proxy's request handling with a scripted upstream. No network.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { handle } from "../proxy/worker.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const ORIGIN = "https://s-matysik.github.io";
const env = { ALLOWED_ORIGINS: ORIGIN + ", http://localhost:8000" };
const calls = [];
const upstream = async (url, init) => {
  calls.push({ url, headers: Object.fromEntries(init.headers.entries()), method: init.method });
  return new Response('{"QueryResult":{"RecordsFound":3}}', { status: 200,
    headers: { "content-type": "application/json", "x-req-reqperday-remaining": "29998", "set-cookie": "s=1", "x-internal": "no" } });
};
const req = (path_, init = {}) => new Request("https://proxy.example.workers.dev" + path_, init);

test("an allowed origin gets the upstream body with CORS headers and the quota headers exposed", async () => {
  calls.length = 0;
  const r = await handle(req("/wos/api/wos?databaseId=WOS&usrQuery=TS%3Dtest&count=1", { headers: { Origin: ORIGIN, "X-ApiKey": "K123", Accept: "application/json" } }), env, upstream);
  assert.equal(r.status, 200);
  assert.equal(r.headers.get("access-control-allow-origin"), ORIGIN);
  assert.equal(r.headers.get("vary"), "Origin");
  assert.equal(r.headers.get("x-req-reqperday-remaining"), "29998");
  assert.match(r.headers.get("access-control-expose-headers"), /x-req-reqperday-remaining/);
  assert.equal(r.headers.get("set-cookie"), null, "upstream cookies are not passed on");
  assert.equal(r.headers.get("x-internal"), null);
  assert.deepEqual(await r.json(), { QueryResult: { RecordsFound: 3 } });
  assert.equal(calls[0].url, "https://api.clarivate.com/api/wos?databaseId=WOS&usrQuery=TS%3Dtest&count=1");
});

test("only the key and the accept header are forwarded", async () => {
  calls.length = 0;
  await handle(req("/wos/api/wos?q=1", { headers: { Origin: ORIGIN, "X-ApiKey": "K123", Accept: "application/json", Cookie: "session=abc", Authorization: "Bearer zzz", "X-Forwarded-For": "1.2.3.4" } }), env, upstream);
  assert.deepEqual(Object.keys(calls[0].headers).sort(), ["accept", "x-apikey"]);
  assert.equal(calls[0].headers["x-apikey"], "K123");
});

test("the preflight is answered for an allowed origin and carries no wildcard", async () => {
  const r = await handle(req("/wos/api/wos", { method: "OPTIONS", headers: { Origin: ORIGIN, "Access-Control-Request-Method": "GET" } }), env, upstream);
  assert.equal(r.status, 204);
  assert.equal(r.headers.get("access-control-allow-origin"), ORIGIN);
  assert.match(r.headers.get("access-control-allow-headers"), /x-apikey/);
  assert.notEqual(r.headers.get("access-control-allow-origin"), "*");
});

test("another origin, a missing origin and an empty allow-list are refused without calling upstream", async () => {
  calls.length = 0;
  for (const [headers, e] of [[{ Origin: "https://evil.example" }, env], [{}, env], [{ Origin: ORIGIN }, {}], [{ Origin: ORIGIN }, { ALLOWED_ORIGINS: "" }]]) {
    const r = await handle(req("/wos/api/wos?q=1", { headers: { ...headers, "X-ApiKey": "K" } }), e, upstream);
    assert.equal(r.status, 403);
    assert.equal(r.headers.get("access-control-allow-origin"), null);
  }
  assert.equal(calls.length, 0);
});

test("arXiv is reached on its own route, without a key, and gets the same treatment", async () => {
  calls.length = 0;
  const r = await handle(req("/arxiv/api/query?search_query=all:test&max_results=1", { headers: { Origin: ORIGIN, Accept: "application/atom+xml", "X-ApiKey": "stray" } }), env, upstream);
  assert.equal(r.status, 200);
  assert.equal(r.headers.get("access-control-allow-origin"), ORIGIN);
  assert.equal(calls[0].url, "https://export.arxiv.org/api/query?search_query=all:test&max_results=1");
});

test("only GET on the two routes is served, and nothing can reach another path or host", async () => {
  calls.length = 0;
  assert.equal((await handle(req("/wos/api/wos", { method: "POST", body: "x", headers: { Origin: ORIGIN } }), env, upstream)).status, 405);
  for (const p of ["/", "/api/wos", "/wos/", "/wos/api/other", "/wos/api/wosx", "/arxiv/api/other", "/arxiv/", "/other/api/wos", "/wos//evil.example/api/wos"]) {
    const r = await handle(req(p, { headers: { Origin: ORIGIN } }), env, upstream);
    assert.equal(r.status, 404, p);
  }
  assert.equal(calls.length, 0);
  // a path that tries to climb out is normalised by the URL parser before routing
  const r = await handle(req("/wos/api/wos/../../../x", { headers: { Origin: ORIGIN } }), env, upstream);
  assert.equal(r.status, 404);
  assert.equal(calls.length, 0);
});

test("an upstream error status is passed through with CORS headers so the page can read it", async () => {
  const r = await handle(req("/wos/api/wos?q=1", { headers: { Origin: ORIGIN, "X-ApiKey": "bad" } }), env, async () => new Response("denied", { status: 401 }));
  assert.equal(r.status, 401);
  assert.equal(r.headers.get("access-control-allow-origin"), ORIGIN);
});

test("the worker source never logs or stores", () => {
  const src = fs.readFileSync(path.join(here, "..", "proxy", "worker.js"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
  assert.ok(!/console\.|KV|caches\.|localStorage|\.put\(/.test(src));
});
