import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { build } from "esbuild";

// Exercise the real transport/dispatcher offline; no provider or browser.
const bundle = await build({
  entryPoints: [fileURLToPath(new URL("../src/lib/agents.ts", import.meta.url))],
  bundle: true, write: false, format: "esm", platform: "node",
  tsconfig: fileURLToPath(new URL("../tsconfig.json", import.meta.url)),
});
const { debateStream } = await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString("base64")}`);

test("debate stream preserves partial/empty/error status and separate gaps, including legacy events", async (t) => {
  t.mock.method(globalThis, "fetch", async () => new Response([
    { type: "dossier_progress", title: "部分", ok: false, loaded: 1, total: 5, status: "partial", truncated: true },
    { type: "dossier_progress", title: "空", ok: true, loaded: 2, total: 5, status: "empty", truncated: false },
    { type: "dossier_progress", title: "失败", ok: false, loaded: 3, total: 5, status: "error", truncated: false },
    { type: "dossier_progress", title: "返回", ok: true, loaded: 4, total: 5, status: "success", truncated: false },
    { type: "dossier_progress", title: "旧版", ok: true, loaded: 5, total: 5 },
    { type: "dossier", sections: [{ title: "部分", tool: "query_quote", status: "partial", truncated: true }], missing: ["失败"], partial: ["部分"] },
    { type: "dossier", sections: [], missing: [] },
    { type: "done" },
  ].map((event) => JSON.stringify(event)).join("\n") + "\n"));
  const previousStorage = globalThis.localStorage;
  globalThis.localStorage = { getItem: (key) => key === "vr-llm" ? JSON.stringify({ provider: "codex-subscription", model: "fixture", baseURL: "https://example.invalid", apiKey: "fixture" }) : null };
  t.after(() => { if (previousStorage === undefined) delete globalThis.localStorage; else globalThis.localStorage = previousStorage; });
  const progress = [], dossiers = [];
  await debateStream("600519", 1, {
    onDossierProgress: (...args) => progress.push(args),
    onDossierReady: (...args) => dossiers.push(args),
  });
  assert.deepEqual(progress[0], ["部分", false, 1, 5, "partial", true]);
  assert.deepEqual(progress.slice(1).map((args) => args[4]), ["empty", "error", "success", undefined]);
  assert.deepEqual(dossiers[0][1], ["失败"]);
  assert.deepEqual(dossiers[0][2], ["部分"]);
  assert.deepEqual(dossiers[1], [[], [], []]);
});

test("debate page explicitly labels limited and empty observations instead of complete badges", async () => {
  const source = await readFile(new URL("../src/pages/Debate.tsx", import.meta.url), "utf8");
  assert.match(source, /p\.status === "partial" \|\| p\.truncated[\s\S]*?<AlertTriangle/);
  assert.match(source, /p\.status === "success" \|\| \(!p\.status && p\.ok\)/);
  assert.match(source, /部分数据/);
  assert.match(source, /未取到记录/);
  assert.match(source, /已截断/);
  assert.match(source, /setPartial\(\[\]\)/);
  assert.match(source, /setPartial\(limited \|\| \[\]\)/);
});
