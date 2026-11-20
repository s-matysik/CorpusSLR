/* Minimal CORS proxy for the two databases whose APIs a browser cannot read.
 *
 * Why it exists: api.clarivate.com (Web of Science) and export.arxiv.org (arXiv)
 * answer a request, but neither sends an Access-Control-Allow-Origin header to
 * any origin (measured), so a browser refuses to hand the response to a page.
 * A server-side hop that adds the header is the only way a static page can use
 * them. The other seven databases need no proxy.
 *
 * What it does, and nothing else:
 *   - accepts GET (and the OPTIONS preflight) from the origins listed in the
 *     ALLOWED_ORIGINS variable and refuses every other origin;
 *   - serves two routes only, /wos/api/wos -> https://api.clarivate.com/api/wos
 *     and /arxiv/api/query -> https://export.arxiv.org/api/query;
 *   - passes on the X-ApiKey and Accept headers and drops everything else,
 *     cookies and authorization included;
 *   - returns the upstream body and status with CORS headers for the caller.
 *
 * It does not log, store or inspect the key or the response. The key passes
 * through whoever runs this worker, so run your own; do not use a proxy that
 * someone else operates.
 *
 * Deploy (Cloudflare Workers, free tier): see app/proxy/wrangler.toml and the
 * "Web of Science and arXiv" part of the README.
 */
const ROUTES = {
  "/wos/": { origin: "https://api.clarivate.com", path: "/api/wos" },
  "/arxiv/": { origin: "https://export.arxiv.org", path: "/api/query" },
};
const FORWARD_REQUEST = ["x-apikey", "accept"];
const EXPOSE = ["x-req-reqperday-remaining", "x-req-reqpersec-remaining", "x-rec-amtpermonth-remaining", "content-type"];

function corsHeaders(origin) {
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "x-apikey, accept",
    "Access-Control-Expose-Headers": EXPOSE.join(", "),
    "Access-Control-Max-Age": "600",
    "Vary": "Origin",
  };
}

function route(pathname) {
  for (const prefix of Object.keys(ROUTES)) {
    if (pathname.indexOf(prefix) !== 0) continue;
    const r = ROUTES[prefix], rest = pathname.slice(prefix.length - 1);
    if (rest === r.path || rest.indexOf(r.path + "/") === 0) return r.origin + rest;
  }
  return null;
}

export async function handle(request, env, fetchImpl) {
  const doFetch = fetchImpl || fetch;
  const allowed = String((env && env.ALLOWED_ORIGINS) || "").split(",").map((s) => s.trim()).filter(Boolean);
  const origin = request.headers.get("Origin") || "";
  if (!allowed.length || allowed.indexOf(origin) === -1) {
    return new Response("origin not allowed", { status: 403 });
  }
  const url = new URL(request.url);
  if (request.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: corsHeaders(origin) });
  }
  if (request.method !== "GET") {
    return new Response("method not allowed", { status: 405, headers: corsHeaders(origin) });
  }
  const target = route(url.pathname);
  if (!target) {
    return new Response("not found", { status: 404, headers: corsHeaders(origin) });
  }
  const out = new Headers();
  FORWARD_REQUEST.forEach((name) => { const v = request.headers.get(name); if (v) out.set(name, v); });
  const upstream = await doFetch(target + url.search, { method: "GET", headers: out, redirect: "manual" });
  const headers = new Headers(corsHeaders(origin));
  EXPOSE.forEach((name) => { const v = upstream.headers.get(name); if (v) headers.set(name, v); });
  return new Response(upstream.body, { status: upstream.status, headers });
}

export default { fetch: (request, env) => handle(request, env) };
