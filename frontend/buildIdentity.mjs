import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { lstat, readFile } from "node:fs/promises";
import path from "node:path";

const execute = promisify(execFile);

export async function captureBuildIdentity(root, run = execute) {
  const result = { service: "vibe-research-frontend", git_sha: null, source_state: "unknown",
    identity_scope: "BUILD_SOURCE_SNAPSHOT" };
  try {
    await lstat(path.join(root, ".git"));
    const { stdout } = await run("git", ["--no-optional-locks", "-C", root, "status",
      "--porcelain=v2", "--branch", "--untracked-files=normal"],
    { timeout: 2000, maxBuffer: 1_000_000, encoding: "utf8", windowsHide: true });
    const lines = stdout.split(/\r?\n/);
    const sha = lines.find((line) => line.startsWith("# branch.oid "))?.slice(13);
    if (!/^[a-f0-9]{40}$/.test(sha ?? "")) return result;
    return { ...result, git_sha: sha,
      source_state: lines.some((line) => line && !line.startsWith("# ")) ? "modified" : "clean" };
  } catch {
    // The isolated Linux package builder supplies this allowlisted snapshot
    // before compiling copied tracked sources; it is not an environment secret.
    try {
      const supplied = JSON.parse(await readFile(path.join(root, ".vibe-build-source.json"), "utf8"));
      if (supplied.service === result.service && /^[a-f0-9]{40}$/.test(supplied.git_sha ?? "")
          && ["clean", "modified"].includes(supplied.source_state)) {
        return { ...result, git_sha: supplied.git_sha, source_state: supplied.source_state };
      }
    } catch { /* Unknown remains explicit. */ }
    return result;
  }
}

export function buildIdentityPlugin(identity) {
  const body = JSON.stringify(identity);
  const developmentBody = JSON.stringify({ ...identity, identity_scope: "DEV_SERVER_STARTUP_SNAPSHOT_NOT_IMMUTABLE_ASSETS" });
  return {
    name: "vibe-build-identity",
    generateBundle() { this.emitFile({ type: "asset", fileName: "vibe-build.json", source: body }); },
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (req.method !== "GET" || req.url?.split("?")[0] !== "/vibe-build.json") return next();
        res.setHeader("Content-Type", "application/json; charset=utf-8");
        res.setHeader("Cache-Control", "no-store");
        res.end(developmentBody);
      });
    },
  };
}
