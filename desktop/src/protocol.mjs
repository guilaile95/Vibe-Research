import path from 'node:path';
import { realpath, readFile } from 'node:fs/promises';

export const APP_ORIGIN = 'app://research';
export const CSP = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-src 'none'; frame-ancestors 'none'; form-action 'none'";
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.ico': 'image/x-icon', '.woff2': 'font/woff2' };
export function isAppURL(raw) {
  try { const url = new URL(raw); return url.protocol === 'app:' && url.hostname === 'research' && !url.port && !url.username && !url.password; }
  catch { return false; }
}
const headers = { 'Content-Security-Policy': CSP, 'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store' };
const failure = status => new Response('Desktop request unavailable', { status, headers });

export function createProtocolHandler({ frontend, backendPort, token, fetchImpl = fetch }) {
  return async request => {
    if (!isAppURL(request.url)) return failure(403);
    const url = new URL(request.url);
    if (url.pathname.startsWith('/api/')) {
      // Destination is fixed; renderer cannot select a host, credential or proxy header.
      const outgoing = new Headers({ Authorization: `Bearer ${token}` });
      for (const name of ['content-type', 'accept', 'if-match']) {
        if (request.headers.has(name)) outgoing.set(name, request.headers.get(name));
      }
      try {
        const options = { method: request.method, headers: outgoing, redirect: 'error', signal: request.signal };
        if (!['GET', 'HEAD'].includes(request.method)) { options.body = request.body; options.duplex = 'half'; }
        const result = await fetchImpl(`http://127.0.0.1:${backendPort}${url.pathname}${url.search}`, options);
        const responseHeaders = new Headers(headers);
        // Do not expose sidecar cookies, redirects, internal auth or diagnostic headers.
        for (const name of ['content-type', 'content-disposition']) {
          if (result.headers.has(name)) responseHeaders.set(name, result.headers.get(name));
        }
        return new Response(result.body, { status: result.status, headers: responseHeaders });
      } catch { return failure(502); }
    }
    if (!['GET', 'HEAD'].includes(request.method)) return failure(405);
    try {
      const decoded = decodeURIComponent(url.pathname);
      if (decoded.includes('\\') || decoded.includes('\0') || decoded.split('/').includes('..')) return failure(403);
      const root = await realpath(frontend);
      let candidate = path.resolve(root, `.${decoded}`);
      if (candidate !== root && !candidate.startsWith(`${root}${path.sep}`)) return failure(403);
      // Extensionless app routes use SPA fallback; missing assets remain 404.
      if (!path.extname(candidate)) candidate = path.join(root, 'index.html');
      const actual = await realpath(candidate);
      if (!actual.startsWith(`${root}${path.sep}`)) return failure(403);
      const content = request.method === 'HEAD' ? null : await readFile(actual);
      return new Response(content, { headers: { ...headers, 'Content-Type': TYPES[path.extname(actual)] || 'application/octet-stream' } });
    } catch { return failure(404); }
  };
}
