/** Controlled CLI stand-in: no login, model call, credential read or network. */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { performance } from 'node:perf_hooks';
const repo = path.resolve(process.argv[2] || path.join(import.meta.dirname, '../..'));
const { AgentRuntime } = await import(pathToFileURL(path.join(repo, 'agent-runtime/src/runtime.mjs')));
const { runProbe } = await import(pathToFileURL(path.join(repo, 'agent-runtime/src/probe.mjs')));
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'vr-runtime-performance-'));
let probes = 0;
const runtime = new AgentRuntime({
  sourceEnv: { PATH: process.env.PATH, HOME: root, USERPROFILE: root, VR_DATA_DIR: root },
  probeProcess: async (_binary, args, options) => {
    probes++;
    const output = args[0] === '--version' ? 'codex-cli 0.149.0' : 'Logged in using ChatGPT';
    return runProbe(process.execPath, ['-e', `process.stdout.write(${JSON.stringify(output)})`], options);
  },
  codexFactory: () => { throw new Error('Model execution forbidden in performance harness'); },
});
const summarize = samples => ({ samples_ms: samples, p50_ms: [...samples].sort((a,b)=>a-b)[Math.floor(samples.length/2)], p95_ms: [...samples].sort((a,b)=>a-b)[Math.ceil(.95*samples.length)-1] });
async function measure(count, cold, burst) {
  const samples = [], startProbes = probes;
  for (let i = 0; i < count; i++) {
    if (cold) runtime.statusCache = null;
    const start = performance.now();
    const statuses = await Promise.all(Array.from({length: burst}, () => runtime.status()));
    samples.push(performance.now() - start);
    if (!statuses.every(s => s.authenticated && s.modelConnectivity === 'unknown' && !s.available)) throw new Error('Status contract drift');
  }
  return { ...summarize(samples), samples: count, concurrent_requests: burst, actual_probe_processes: probes - startProbes };
}
try {
  const results = {
    environment: 'isolated cloud Linux; synthetic CLI subprocess, no real provider or Codex auth',
    node: process.version,
    cold_status: await measure(25, true, 1),
    warm_status: await measure(100, false, 1),
    cold_twenty_request_burst: await measure(25, true, 20),
  };
  console.log(JSON.stringify(results, null, 2));
} finally {
  runtime.shutdown();
  // Only this harness's freshly created synthetic directory is removed.
  fs.rmSync(root, { recursive: true });
}
