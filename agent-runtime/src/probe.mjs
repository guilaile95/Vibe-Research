/** Bounded asynchronous process ownership, with no raw output in public errors. */
import { spawn } from "node:child_process";

export function runProbe(binary, args, { timeout = 1_200, maxBuffer = 64 * 1024, signal, spawnProcess = spawn, ...options } = {}) {
  return new Promise((resolve) => {
    let child, timer, stdout = "", stderr = "", bytes = 0, failure = null;
    let settled = false;
    const finish = (status, processSignal) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
      resolve({ status, signal: processSignal, stdout, stderr, error: failure });
    };
    const stop = (code) => {
      failure ??= Object.assign(new Error(code), { code });
      child?.kill("SIGKILL");
    };
    const abort = () => stop("ABORT_ERR");
    if (signal?.aborted) { failure = { code: "ABORT_ERR" }; finish(null); return; }
    try {
      child = spawnProcess(binary, args, { ...options, encoding: undefined, shell: false,
        windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
      const collect = (key) => (chunk) => {
        bytes += chunk.length;
        if (bytes > maxBuffer) { stop("MAX_BUFFER"); return; }
        if (key === "stdout") stdout += chunk.toString("utf8");
        else stderr += chunk.toString("utf8");
      };
      child.stdout.on("data", collect("stdout"));
      child.stderr.on("data", collect("stderr"));
      child.once("error", (error) => { failure = error; });
      child.once("close", finish); // Admission retained through actual process exit.
      signal?.addEventListener("abort", abort, { once: true });
      timer = setTimeout(() => stop("ETIMEDOUT"), timeout);
    } catch (error) { failure = error; finish(null); }
  });
}

export function awaitSignal(promise, signal) {
  if (!signal) return promise;
  return new Promise((resolve, reject) => {
    const abort = () => reject(signal.reason ?? new Error("aborted"));
    if (signal.aborted) { abort(); return; }
    signal.addEventListener("abort", abort, { once: true });
    Promise.resolve(promise).then(resolve, reject).finally(() => signal.removeEventListener("abort", abort));
  });
}
