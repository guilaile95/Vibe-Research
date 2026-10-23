import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { captureBuildIdentity, buildIdentityPlugin } from "../buildIdentity.mjs";

test("build identity rejects an ancestor Git checkout and records modified sources", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "vibe-build-identity-"));
  let calls = 0;
  const run = async () => { calls++; return { stdout: `# branch.oid ${"a".repeat(40)}\n1 M. changed\n` }; };
  assert.equal((await captureBuildIdentity(root, run)).git_sha, null);
  assert.equal(calls, 0);
  await writeFile(path.join(root, ".git"), "synthetic gitdir");
  const identity = await captureBuildIdentity(root, run);
  assert.equal(identity.git_sha, "a".repeat(40));
  assert.equal(identity.source_state, "modified");
  assert.equal(calls, 1);
  assert.equal((await captureBuildIdentity(root, async () => { throw new Error("SYNTHETIC_SECRET"); })).source_state, "unknown");
});

test("build metadata is emitted once and HMR metadata does not claim immutable assets", () => {
  const identity = { service: "vibe-research-frontend", git_sha: "a".repeat(40), source_state: "clean", identity_scope: "BUILD_SOURCE_SNAPSHOT" };
  const plugin = buildIdentityPlugin(identity);
  let asset;
  plugin.generateBundle.call({ emitFile(value) { asset = value; } });
  assert.equal(asset.fileName, "vibe-build.json");
  assert.deepEqual(JSON.parse(asset.source), identity);
  let middleware;
  plugin.configureServer({ middlewares: { use(value) { middleware = value; } } });
  let body;
  middleware({ method: "GET", url: "/vibe-build.json" }, { setHeader() {}, end(value) { body = value; } }, () => assert.fail("handled identity route"));
  assert.equal(JSON.parse(body).identity_scope, "DEV_SERVER_STARTUP_SNAPSHOT_NOT_IMMUTABLE_ASSETS");
  let forwarded = false;
  middleware({ method: "GET", url: "/other" }, {}, () => { forwarded = true; });
  assert.equal(forwarded, true);
});
