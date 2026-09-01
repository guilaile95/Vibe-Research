import http from "node:http";
import { pathToFileURL } from "node:url";

import { AgentRuntime, RuntimeError } from "./runtime.mjs";

const HOST = "127.0.0.1";
const DEFAULT_PORT = 8911;
const MAX_BODY_BYTES = 1_000_000;

function json(res, status, body) {
  const text = JSON.stringify(body);
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(text),
    "cache-control": "no-store",
  });
  res.end(text);
}

async function readJson(req) {
  const chunks = [];
  let bytes = 0;
  for await (const chunk of req) {
    bytes += chunk.length;
    if (bytes > MAX_BODY_BYTES) throw new RuntimeError("BAD_REQUEST", 413);
    chunks.push(chunk);
  }
  if (!chunks.length) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw new RuntimeError("BAD_REQUEST", 400);
  }
}

export function createAgentServer(runtime = new AgentRuntime()) {
  return http.createServer(async (req, res) => {
    const url = new URL(req.url ?? "/", `http://${HOST}`);
    try {
      if (req.method === "GET" && url.pathname === "/health") {
        return json(res, 200, { ok: true, service: "vibe-agent-runtime", runtime: "Codex Subscription" });
      }
      if (req.method === "GET" && url.pathname === "/status") {
        return json(res, 200, runtime.status());
      }
      if (req.method === "POST" && url.pathname === "/login") {
        await readJson(req);
        return json(res, 202, runtime.login());
      }
      if (req.method === "POST" && url.pathname === "/cancel") {
        const body = await readJson(req);
        return json(res, 200, runtime.cancel(body.session));
      }
      if (req.method === "POST" && (url.pathname === "/chat" || url.pathname === "/continue")) {
        const body = await readJson(req);
        const controller = new AbortController();
        let finished = false;
        req.once("aborted", () => controller.abort());
        res.once("close", () => { if (!finished) controller.abort(); });
        res.writeHead(200, {
          "content-type": "application/x-ndjson; charset=utf-8",
          "cache-control": "no-store",
          "x-content-type-options": "nosniff",
        });
        try {
          await runtime.chat({
            session: body.session,
            message: body.message,
            context: body.context,
            signal: controller.signal,
            onEvent: (event) => res.write(`${JSON.stringify(event)}\n`),
          });
        } catch (error) {
          const safe = error instanceof RuntimeError ? error : new RuntimeError("CHAT_FAILED", 502);
          if (!res.destroyed) res.write(`${JSON.stringify({ type: "error", code: safe.code, message: safe.message })}\n`);
        } finally {
          finished = true;
          if (!res.destroyed) res.end();
        }
        return;
      }
      return json(res, 404, { error: "NOT_FOUND" });
    } catch (error) {
      const safe = error instanceof RuntimeError ? error : new RuntimeError("RUNTIME_UNAVAILABLE", 503);
      if (!res.headersSent) return json(res, safe.status, { error: safe.code, message: safe.message });
      if (!res.destroyed) res.end();
    }
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const runtime = new AgentRuntime();
  const server = createAgentServer(runtime);
  const port = Number.parseInt(process.env.VR_AGENT_RUNTIME_PORT || String(DEFAULT_PORT), 10);
  server.listen(port, HOST, () => {
    process.stdout.write(`vibe-agent-runtime ready on http://${HOST}:${port}\n`);
  });
  const stop = () => {
    runtime.shutdown();
    server.close(() => process.exit(0));
  };
  process.once("SIGINT", stop);
  process.once("SIGTERM", stop);
}
