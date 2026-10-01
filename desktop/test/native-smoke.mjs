/** Native packaged-window acceptance on supported desktop or OS-matched CI runners. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { execFileSync, spawn } from 'node:child_process';
import { _electron as electron } from 'playwright';

if (process.platform === 'linux' && process.getuid?.() === 0) throw new Error('Native smoke must run as an ordinary non-root desktop user; sandbox bypass is prohibited');
const executablePath = path.resolve(process.argv[2] || (process.platform === 'win32'
  ? 'release/win-unpacked/Vibe Research.exe' : 'release/linux-unpacked/vibe-research'));
const profile = await fs.mkdtemp(path.join(os.tmpdir(), 'vibe-native-smoke-'));
const artifactDir = path.resolve('release/smoke');
await fs.mkdir(artifactDir, { recursive: true });
const environment = { ...process.env, VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH: '1', VIBE_NATIVE_INTEL_DISABLE_SCHEDULER: '1' };
delete environment.ELECTRON_RUN_AS_NODE;
function descendants(root) {
  const rows = process.platform === 'win32'
    ? JSON.parse(execFileSync('powershell.exe', ['-NoProfile', '-Command', 'Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId | ConvertTo-Json -Compress'], { encoding: 'utf8' })).map(p => [p.ProcessId, p.ParentProcessId])
    : execFileSync('ps', ['-e', '-o', 'pid=,ppid='], { encoding: 'utf8' }).trim().split('\n').map(line => line.trim().split(/\s+/).map(Number));
  const found = new Set([root]);
  let changed = true;
  while (changed) { changed = false; for (const [pid, parent] of rows) if (found.has(parent) && !found.has(pid)) { found.add(pid); changed = true; } }
  found.delete(root); return [...found];
}
function alive(pid) {
  try {
    process.kill(pid, 0);
    if (process.platform === 'linux') {
      const stat = execFileSync('ps', ['-o', 'stat=', '-p', String(pid)], { encoding: 'utf8' });
      if (stat.trim().startsWith('Z')) return false;
    }
    return true;
  } catch { return false; }
}
async function gone(pids) {
  const deadline = Date.now() + 20_000;
  while (pids.some(alive) && Date.now() < deadline) await new Promise(r => setTimeout(r, 100));
  assert.deepEqual(pids.filter(alive), [], 'owned services must not outlive desktop');
}
async function open() {
  const application = await electron.launch({ executablePath, args: [`--user-data-dir=${profile}`], env: environment, timeout: 60_000 });
  try {
  const page = await application.firstWindow({ timeout: 60_000 });
  // Fixture-only UI data. Read-only runtime-info/health still exercise real packaged backend.
  await page.route('**/api/**', route => {
    if (/\/api\/(runtime-info|health)(\?|$)/.test(route.request().url())) return route.continue();
    return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Native desktop offline fixture' }) });
  });
  await page.waitForURL('app://research/**', { timeout: 150_000 });
  await page.getByTestId('app-sidebar').waitFor({ state: 'visible', timeout: 30_000 });
  return { application, page };
  } catch (error) {
    await application.close().catch(() => { try { application.process().kill('SIGKILL'); } catch {} });
    throw error;
  }
}
let first;
try {
  first = await open();
  const { application, page } = first;
  assert.equal(await page.evaluate(() => typeof window.require), 'undefined');
  assert.equal(await page.evaluate(() => typeof window.process), 'undefined');
  assert.equal(await application.evaluate(({ app }) => app.commandLine.hasSwitch('no-sandbox')), false);
  const preferences = await application.evaluate(({ BrowserWindow }) => {
    const p = BrowserWindow.getAllWindows()[0].webContents.getLastWebPreferences();
    return { sandbox: p.sandbox, contextIsolation: p.contextIsolation, nodeIntegration: p.nodeIntegration };
  });
  assert.deepEqual(preferences, { sandbox: true, contextIsolation: true, nodeIntegration: false });
  const info = await page.evaluate(async () => (await fetch('/api/runtime-info')).json());
  assert.equal(info.data.service, 'vibe-research-api');
  assert.notEqual(info.data.version, 'unknown');
  await page.evaluate(() => localStorage.setItem('desktop-smoke-persistence', 'fixture'));
  await page.goto('app://research/settings');
  await page.getByTestId('app-sidebar').waitFor();
  await page.reload();
  await page.getByTestId('app-sidebar').waitFor();
  assert.equal(await page.evaluate(() => localStorage.getItem('desktop-smoke-persistence')), 'fixture');
  await page.screenshot({ path: path.join(artifactDir, 'settings.png'), fullPage: true });
  const second = spawn(executablePath, [`--user-data-dir=${profile}`], { env: environment, stdio: 'ignore' });
  await Promise.race([new Promise((resolve, reject) => { second.once('exit', code => code === 0 ? resolve() : reject(new Error(`Second instance exit ${code}`))); second.once('error', reject); }), new Promise((_, reject) => setTimeout(() => reject(new Error('Second instance did not exit')), 15_000))]);
  assert.equal(application.windows().length, 1);
  const owned = descendants(application.process().pid);
  assert.ok(owned.length >= 3, 'native runtime child tree present');
  await application.close(); first = null;
  await gone(owned);
  const restarted = await open(); first = restarted;
  assert.equal(await restarted.page.evaluate(() => localStorage.getItem('desktop-smoke-persistence')), 'fixture');
  const crashOwned = descendants(restarted.application.process().pid);
  process.kill(restarted.application.process().pid, 'SIGKILL'); first = null;
  await gone(crashOwned);
  await fs.writeFile(path.join(artifactDir, 'result.json'), JSON.stringify({ platform: process.platform, packagedWindow: true,
    sandbox: true, backend: true, fixtureOnly: true, navigationReload: true, singleInstance: true,
    persistence: true, normalCleanup: true, crashCleanup: true }, null, 2));
  console.log('Native packaged desktop fixture smoke passed');
} catch (error) {
  if (first) await first.page.screenshot({ path: path.join(artifactDir, 'failure.png'), fullPage: true }).catch(() => {});
  throw error;
} finally {
  if (first) await first.application.close().catch(() => {});
  await fs.rm(profile, { recursive: true, force: true, maxRetries: 8, retryDelay: 500 });
}
