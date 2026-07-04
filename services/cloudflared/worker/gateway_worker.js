const COOKIE_NAME = "cloudflared_gate";
const COOKIE_MAX_AGE = 60 * 60 * 24 * 365;

function cookieValue(header, name) {
  if (!header) return "";
  const parts = header.split(";");
  for (const part of parts) {
    const [rawKey, ...rawValue] = part.trim().split("=");
    if (rawKey === name) return rawValue.join("=");
  }
  return "";
}

function cleanRequestUrl(requestUrl) {
  const url = new URL(requestUrl);
  url.searchParams.delete("key");
  return url;
}

function expectedKey(env) {
  return env.GATEWAY_KEY || "";
}

function isAuthorized(request, env) {
  const expected = expectedKey(env);
  if (!expected) return true;
  const url = new URL(request.url);
  const queryKey = url.searchParams.get("key") || "";
  if (queryKey && queryKey === expected) return true;
  const headerKey = request.headers.get("x-cloudflared-key") || "";
  if (headerKey && headerKey === expected) return true;
  const cookieKey = cookieValue(request.headers.get("cookie"), COOKIE_NAME);
  return cookieKey === expected;
}

function hasQueryKey(request, env) {
  const expected = expectedKey(env);
  if (!expected) return false;
  const url = new URL(request.url);
  return (url.searchParams.get("key") || "") === expected;
}

function accessDenied() {
  return new Response("Acceso protegido", {
    status: 403,
    headers: {"content-type": "text/plain; charset=utf-8", "cache-control": "no-store"},
  });
}

function tunnelNotReady() {
  return new Response("Tunel todavia no preparado", {
    status: 503,
    headers: {"content-type": "text/plain; charset=utf-8", "cache-control": "no-store"},
  });
}

async function currentTunnelUrl(env) {
  const key = env.KV_KEY_CURRENT_URL || "current_url";
  const value = await env.TUNNEL_STATE.get(key);
  return (value || "").trim().replace(/\/+$/, "");
}

function copyForwardHeaders(request) {
  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("cf-connecting-ip");
  headers.delete("cf-ipcountry");
  headers.delete("cf-ray");
  headers.delete("cf-visitor");
  headers.set("x-cloudflared-gateway", "worker");
  return headers;
}

function targetUrl(baseUrl, requestUrl) {
  const cleanUrl = cleanRequestUrl(requestUrl);
  const base = new URL(baseUrl);
  base.pathname = cleanUrl.pathname;
  base.search = cleanUrl.search;
  return base.toString();
}

function rewriteResponseHeaders(headers, request, targetBase) {
  const out = new Headers(headers);
  out.delete("content-security-policy");
  out.delete("content-security-policy-report-only");
  const location = out.get("location");
  if (location) {
    try {
      const current = new URL(request.url);
      const target = new URL(location, targetBase);
      const base = new URL(targetBase);
      if (target.origin === base.origin) {
        target.protocol = current.protocol;
        target.host = current.host;
        out.set("location", target.toString());
      }
    } catch (_) {}
  }
  return out;
}

async function proxy(request, env) {
  if (!isAuthorized(request, env)) return accessDenied();
  const tunnel = await currentTunnelUrl(env);
  if (!tunnel) return tunnelNotReady();
  const init = {method: request.method, headers: copyForwardHeaders(request), redirect: "manual"};
  if (request.method !== "GET" && request.method !== "HEAD") init.body = request.body;
  const response = await fetch(targetUrl(tunnel, request.url), init);
  const headers = rewriteResponseHeaders(response.headers, request, tunnel);
  if (hasQueryKey(request, env)) {
    headers.append("set-cookie", `${COOKIE_NAME}=${expectedKey(env)}; Max-Age=${COOKIE_MAX_AGE}; Path=/; Secure; HttpOnly; SameSite=Lax`);
  }
  return new Response(response.body, {status: response.status, statusText: response.statusText, headers});
}

export default {
  fetch(request, env) {
    return proxy(request, env);
  },
};
