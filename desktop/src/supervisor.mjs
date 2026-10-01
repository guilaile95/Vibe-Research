import path from 'node:path';
import readline from 'node:readline';
import { spawnOwned, stopOwned } from './processes.mjs';

const [resources, data] = process.argv.slice(2);
const children = [];
let stopping = false;
const send = value => process.stdout.write(`${JSON.stringify(value)}\n`);
async function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  await Promise.all(children.map(child => stopOwned(child)));
  process.exit(code);
}
process.stdin.resume();
process.stdin.once('end', () => void stop());
process.stdin.once('error', () => void stop(1));
process.once('SIGTERM', () => void stop());
process.once('SIGINT', () => void stop());
process.once('uncaughtException', () => { send({ type: 'failure', code: 'SUPERVISOR_FAILED' }); void stop(1); });
process.once('unhandledRejection', () => { send({ type: 'failure', code: 'SUPERVISOR_FAILED' }); void stop(1); });

async function start(command, args, env, service) {
  if (stopping) throw new Error('Stopping');
  const child = spawnOwned(command, args, { env, cwd: data });
  children.push(child);
  // Never persist or forward service output: responses may contain private data.
  child.stderr.resume();
  return await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('Startup timeout')), 120_000);
    const lines = readline.createInterface({ input: child.stdout });
    lines.on('line', line => {
      try {
        const value = JSON.parse(line);
        if (value.type === 'listening' && value.service === service &&
            Number.isInteger(value.port) && value.port > 0 && value.port < 65536) {
          clearTimeout(timeout); resolve(value.port);
        }
      } catch { /* Unstructured backend diagnostics are intentionally discarded. */ }
    });
    child.once('error', () => { clearTimeout(timeout); reject(new Error('Launch failed')); });
    child.once('exit', () => {
      clearTimeout(timeout);
      reject(new Error('Service exited'));
      if (!stopping) { send({ type: 'failure', code: 'SERVICE_EXITED' }); void stop(1); }
    });
  });
}
try {
  const suffix = process.platform === 'win32' ? '.exe' : '';
  const env = { ...process.env, VR_DATA_DIR: data, VR_AGENT_RUNTIME_PORT: '0', VR_DESKTOP_RUNTIME: '1' };
  const agentPort = await start(path.join(resources, 'node', `node${suffix}`),
    [path.join(resources, 'agent-runtime', 'src', 'server.mjs')], env, 'agent');
  const backendPort = await start(path.join(resources, 'backend', `vibe-backend${suffix}`), [],
    { ...env, VR_AGENT_RUNTIME_URL: `http://127.0.0.1:${agentPort}`, VR_DESKTOP_BACKEND_PORT: '0' }, 'backend');
  if (!stopping) send({ type: 'ready', backendPort, agentPort });
} catch {
  send({ type: 'failure', code: 'STARTUP_FAILED' });
  await stop(1);
}
