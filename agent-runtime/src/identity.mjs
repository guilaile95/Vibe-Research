import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { readFile, lstat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const execute = promisify(execFile);
const DEFAULT_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

/** Startup-only public source identity. No login/config/SDK probes or private paths. */
export async function captureRuntimeIdentity({ root = DEFAULT_ROOT, run = execute } = {}) {
  const base = { service: "vibe-agent-runtime", version: "unknown", git_sha: null,
    source_state: "unknown", identity_scope: "STARTUP_SOURCE_SNAPSHOT" };
  try {
    const pkg = JSON.parse(await readFile(path.join(root, "agent-runtime/package.json"), "utf8"));
    if (typeof pkg.version === "string" && /^[0-9A-Za-z.+-]{1,64}$/.test(pkg.version)) base.version = pkg.version;
  } catch { /* Unknown is not healthy. */ }
  try {
    await lstat(path.join(root, ".git")); // Do not inherit an unrelated ancestor repository.
    const { stdout } = await run("git", ["--no-optional-locks", "-C", root, "status",
      "--porcelain=v2", "--branch", "--untracked-files=normal"],
    { timeout: 2000, maxBuffer: 1_000_000, encoding: "utf8", windowsHide: true });
    const lines = stdout.split(/\r?\n/);
    const sha = lines.find((line) => line.startsWith("# branch.oid "))?.slice(13);
    if (!/^[a-f0-9]{40}$/.test(sha ?? "")) return base;
    return { ...base, git_sha: sha,
      source_state: lines.some((line) => line && !line.startsWith("# ")) ? "modified" : "clean" };
  } catch { return base; }
}

// Call once at server construction/startup and reuse the Promise in the handler.
// A missing Git checkout is explicitly unknown, not the parent directory's SHA.
