import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";

import { AgentRuntime, RuntimeError } from "../src/runtime.mjs";
import {
  CHAT_FEATURES,
  effectiveMcpNames,
  engineEnv,
  isolatedCodexOptions,
  mcpDisableOverride,
  resolveBundledCodexBinary,
} from "../src/security.mjs";

function tempDir(t, name) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), `${name}-`));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return dir;
}

test("effective MCP isolation uses the real Codex config and ignores inactive profiles", (t) => {
  const root = tempDir(t, "vibe-mcp");
  const codexHome = path.join(root, "codex-home");
  const cwd = path.join(root, "session");
  fs.mkdirSync(codexHome, { recursive: true });
  fs.mkdirSync(cwd, { recursive: true });
  fs.writeFileSync(path.join(codexHome, "config.toml"), [
    "[mcp_servers.active]",
    'url = "https://active.invalid/mcp"',
    "[profiles.legacy.mcp_servers.dormant]",
    'url = "https://inactive.invalid/mcp"',
    "",
  ].join("\n"));

  const binary = resolveBundledCodexBinary();
  const names = effectiveMcpNames({ binary, codexHome, cwd });
  assert.deepEqual(names, ["active"]);
  const override = mcpDisableOverride(names);
  assert.match(override, /"active"\s*=\s*\{\s*"enabled"\s*=\s*false\s*\}/);
  assert.doesNotMatch(override, /dormant/);

  const parsed = spawnSync(binary, ["-c", override, "mcp", "list", "--json"], {
    cwd,
    env: engineEnv(codexHome),
    encoding: "utf8",
    timeout: 20_000,
    windowsHide: true,
  });
  assert.equal(parsed.status, 0, String(parsed.stderr || parsed.error?.message || "config parse failed"));
  const servers = JSON.parse(String(parsed.stdout || "[]"));
  assert.deepEqual(servers.map((item) => [item.name, item.enabled]), [["active", false]]);
});

test("MCP discovery fails closed when the exact engine cannot prove effective config", () => {
  assert.throws(
    () => effectiveMcpNames({
      binary: "codex",
      codexHome: "C:/tmp/codex-home",
      cwd: "C:/tmp/session",
      run: () => ({ status: 1, stderr: "sensitive detail" }),
    }),
    /Unable to verify effective Codex MCP configuration/,
  );
});

test("page chat reuses one isolated thread and never creates formal authority state", async (t) => {
  const dataRoot = tempDir(t, "vibe-agent-data");
  const prompts = [];
  const threadOptions = [];
  let startCount = 0;
  let codexOptions = null;
  const codexFactory = (options) => {
    codexOptions = options;
    return {
      startThread(optionsForThread) {
        startCount += 1;
        threadOptions.push(optionsForThread);
        return {
          async runStreamed(prompt) {
            prompts.push(prompt);
            return {
              events: (async function* () {
                yield { type: "item.completed", item: { type: "agent_message", text: "页面草稿" } };
                yield { type: "turn.completed", usage: {} };
              })(),
            };
          },
        };
      },
    };
  };
  const runtime = new AgentRuntime({ sourceEnv: { ...process.env, VR_DATA_DIR: dataRoot }, codexFactory });
  t.after(() => runtime.shutdown());
  runtime.status = () => ({ installed: true, authenticated: true, available: true, status: "ready" });

  const events = [];
  await runtime.chat({
    session: "stock-600519",
    message: "概括风险",
    context: "证券代码：600519",
    onEvent: (event) => events.push(event),
  });
  await runtime.chat({
    session: "stock-600519",
    message: "继续",
    context: "证券代码：600519",
  });

  assert.equal(startCount, 1);
  assert.match(prompts[0], /NON_AUTHORITATIVE_AI_DRAFT/);
  assert.match(prompts[0], /证券代码：600519/);
  assert.equal(prompts[1].includes("NON_AUTHORITATIVE_AI_DRAFT"), false, "preamble is sent once per thread");
  assert.deepEqual(threadOptions[0], {
    workingDirectory: threadOptions[0].workingDirectory,
    sandboxMode: "read-only",
    skipGitRepoCheck: true,
    networkAccessEnabled: false,
    approvalPolicy: "never",
    webSearchMode: "disabled",
  });
  assert.deepEqual(codexOptions.config.features, CHAT_FEATURES);
  assert.equal(codexOptions.config.skills.bundled.enabled, false);
  assert.ok(codexOptions.config.skills.config.every((entry) => entry.enabled === false));
  assert.match(codexOptions.configOverrides[0], /^mcp_servers=/);
  assert.equal(events.at(-1).classification, "NON_AUTHORITATIVE_AI_DRAFT");
  assert.deepEqual(fs.readdirSync(dataRoot), ["agent-runtime"]);
});

test("any completed tool item fails closed and discards the session", async (t) => {
  const dataRoot = tempDir(t, "vibe-agent-tool-violation");
  let starts = 0;
  const runtime = new AgentRuntime({
    sourceEnv: { ...process.env, VR_DATA_DIR: dataRoot },
    codexFactory: () => ({
      startThread() {
        starts += 1;
        return {
          async runStreamed() {
            return {
              events: (async function* () {
                yield { type: "item.completed", item: { type: "command_execution" } };
              })(),
            };
          },
        };
      },
    }),
  });
  t.after(() => runtime.shutdown());
  runtime.status = () => ({ installed: true, authenticated: true, available: true, status: "ready" });

  await assert.rejects(
    runtime.chat({ session: "page-one", message: "x", context: "y" }),
    (error) => error instanceof RuntimeError && error.code === "TOOL_SURFACE_VIOLATION",
  );
  await assert.rejects(
    runtime.chat({ session: "page-one", message: "x", context: "y" }),
    (error) => error instanceof RuntimeError && error.code === "TOOL_SURFACE_VIOLATION",
  );
  assert.equal(starts, 2, "a violated thread must never be reused");
});
