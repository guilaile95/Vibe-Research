/**
 * Codex page-chat isolation.
 *
 * Adapted from simonlin1212/Vibe-Research@b65ad42d02e5adc45d494a842c50afe4d79d2fe9
 * (`orchestrator/src/chat.ts`, `orchestrator/src/runner.ts`,
 * `orchestrator/src/skills_isolation.ts`) under the MIT license.
 * The current product keeps only the Codex page-context boundary: no research
 * runner, MCP tools, shell, web, apps, plugins, skills or multi-agent surface.
 */
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";

export const CHAT_FEATURES = Object.freeze({
  shell_tool: false,
  unified_exec: false,
  view_image: false,
  multi_agent: false,
  multi_agent_v2: false,
  apps: false,
  enable_mcp_apps: false,
  plugins: false,
  tool_suggest: false,
  standalone_web_search: false,
  code_mode: false,
});

const ENV_ALLOWLIST = Object.freeze([
  "PATH", "PATHEXT", "SYSTEMROOT", "SystemRoot", "WINDIR", "COMSPEC",
  "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
  "LANG", "LC_ALL", "LC_CTYPE", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
  "http_proxy", "https_proxy", "no_proxy", "SSL_CERT_FILE", "SSL_CERT_DIR",
]);

const PLATFORM_TRIPLES = Object.freeze({
  "darwin-arm64": "aarch64-apple-darwin",
  "darwin-x64": "x86_64-apple-darwin",
  "linux-x64": "x86_64-unknown-linux-musl",
  "linux-arm64": "aarch64-unknown-linux-musl",
  "win32-x64": "x86_64-pc-windows-msvc",
  "win32-arm64": "aarch64-pc-windows-msvc",
});

export function assertSupportedNode(version = process.versions.node) {
  const [major, minor] = String(version).split(".").map(Number);
  if (!Number.isInteger(major) || !Number.isInteger(minor) || major < 22 || (major === 22 && minor < 6)) {
    throw new Error(`Vibe Agent Runtime requires Node.js >=22.6; received ${version}`);
  }
}

export function resolveDataRoot(env = process.env) {
  const configured = String(env.VR_DATA_DIR ?? "").trim();
  return path.resolve(configured || path.join(os.homedir(), ".vibe-research"));
}

export function runtimePaths(env = process.env) {
  const root = path.join(resolveDataRoot(env), "agent-runtime");
  return {
    root,
    codexHome: path.join(root, "codex-home"),
    sessions: path.join(root, "sessions"),
  };
}

export function engineEnv(codexHome, source = process.env) {
  const env = {};
  for (const key of ENV_ALLOWLIST) {
    const value = source[key];
    if (typeof value === "string" && value) env[key] = value;
  }
  env.CODEX_HOME = path.resolve(codexHome);
  return env;
}

export function resolveBundledCodexBinary() {
  const require = createRequire(import.meta.url);
  const codexPackage = require.resolve("@openai/codex/package.json");
  const key = `${process.platform}-${process.arch}`;
  const triple = PLATFORM_TRIPLES[key];
  if (!triple) throw new Error(`Unsupported Codex platform: ${key}`);
  const platformPackage = `@openai/codex-${key}`;
  const platformJson = require.resolve(`${platformPackage}/package.json`, {
    paths: [path.dirname(codexPackage)],
  });
  const binary = path.join(
    path.dirname(platformJson), "vendor", triple, "bin",
    process.platform === "win32" ? "codex.exe" : "codex",
  );
  if (!fs.existsSync(binary)) throw new Error("Bundled Codex binary is missing");
  return binary;
}

function parseMcpList(stdout) {
  let parsed;
  try {
    parsed = JSON.parse(String(stdout || "[]"));
  } catch {
    throw new Error("Unable to verify effective Codex MCP configuration");
  }
  if (!Array.isArray(parsed) || parsed.some((item) => !item || typeof item.name !== "string")) {
    throw new Error("Unable to verify effective Codex MCP configuration");
  }
  return [...new Set(parsed.map((item) => item.name))].sort();
}

export function effectiveMcpNames({ binary, codexHome, cwd, sourceEnv = process.env, run = spawnSync }) {
  const result = run(binary, [
    "-c", "features.apps=false",
    "-c", "features.enable_mcp_apps=false",
    "-c", "features.plugins=false",
    "mcp", "list", "--json",
  ], {
    cwd,
    env: engineEnv(codexHome, sourceEnv),
    encoding: "utf8",
    timeout: 20_000,
    windowsHide: true,
  });
  if (result.error || result.status !== 0) {
    throw new Error("Unable to verify effective Codex MCP configuration");
  }
  return parseMcpList(result.stdout);
}

function tomlValue(value) {
  if (typeof value === "string") return JSON.stringify(value);
  if (typeof value === "boolean" || typeof value === "number") return String(value);
  if (Array.isArray(value)) return `[${value.map(tomlValue).join(", ")}]`;
  if (value && typeof value === "object") {
    return `{${Object.entries(value).map(([key, child]) => `${JSON.stringify(key)} = ${tomlValue(child)}`).join(", ")}}`;
  }
  throw new Error("Unsupported Codex configuration value");
}

export function mcpDisableOverride(names) {
  const servers = Object.fromEntries(names.map((name) => [name, { enabled: false }]));
  return `mcp_servers=${tomlValue(servers)}`;
}

function walkSkillFiles(root, out, visited, depth = 0) {
  if (depth > 8 || !fs.existsSync(root)) return;
  const real = fs.realpathSync(root);
  if (visited.has(real)) return;
  visited.add(real);
  for (const entry of fs.readdirSync(real, { withFileTypes: true })) {
    const child = path.join(real, entry.name);
    if (entry.isDirectory() || entry.isSymbolicLink()) {
      walkSkillFiles(child, out, visited, depth + 1);
    } else if (entry.isFile() && entry.name === "SKILL.md") {
      out.add(fs.realpathSync(child));
    }
  }
}

export function foreignSkillFiles(codexHome) {
  const out = new Set();
  const visited = new Set();
  walkSkillFiles(path.join(os.homedir(), ".agents", "skills"), out, visited);
  walkSkillFiles(path.join(codexHome, "skills"), out, visited);
  return [...out].sort();
}

export function isolatedCodexOptions({ binary, codexHome, cwd, sourceEnv = process.env }) {
  const env = engineEnv(codexHome, sourceEnv);
  const mcpNames = effectiveMcpNames({ binary, codexHome, cwd, sourceEnv });
  const skills = foreignSkillFiles(codexHome);
  return {
    env,
    codexPathOverride: binary,
    config: {
      features: CHAT_FEATURES,
      shell_environment_policy: {
        ignore_default_excludes: false,
        exclude: ["CODEX_API_KEY", "*KEY*", "*SECRET*", "*TOKEN*", "*PASSWORD*"],
      },
      skills: {
        bundled: { enabled: false },
        max_context_tokens: 1_000,
        config: skills.map((skillPath) => ({ path: skillPath, enabled: false })),
      },
    },
    configOverrides: [mcpDisableOverride(mcpNames)],
  };
}
