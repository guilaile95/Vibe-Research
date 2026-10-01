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
const requestedProfile = process.env.VR_DESKTOP_SMOKE_PROFILE;
const profile = requestedProfile ? path.resolve(requestedProfile) : await fs.mkdtemp(path.join(os.tmpdir(), 'Vibe Research 测试-'));
if (requestedProfile) {
  const lexical = path.relative(path.resolve(os.tmpdir()), profile);
  if (!lexical || lexical === '..' || lexical.startsWith(`..${path.sep}`) || path.isAbsolute(lexical)) throw new Error('Smoke profile must be inside the system temp directory');
  await fs.mkdir(profile, { recursive: true });
  const root = await fs.realpath(os.tmpdir());
  const actual = await fs.realpath(profile);
  const relative = path.relative(root, actual);
  if (!relative || relative === '..' || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative) || (await fs.readdir(profile)).length) {
    throw new Error('Smoke profile must be a fresh empty directory inside the system temp directory');
  }
}
const keepProfile = !!requestedProfile && process.env.VR_DESKTOP_SMOKE_KEEP_PROFILE === '1';
const artifactDir = path.resolve(process.env.VR_DESKTOP_SMOKE_ARTIFACT_DIR || 'release/smoke');
await fs.mkdir(artifactDir, { recursive: true });
const environment = { ...process.env, VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH: '1', VIBE_NATIVE_INTEL_DISABLE_SCHEDULER: '1' };
delete environment.ELECTRON_RUN_AS_NODE;
let stage = 'initialize';
const pageErrors = [];
const consoleErrors = [];
const knownPids = new Set();
async function progress(value) {
  stage = value;
  console.log(`[desktop-smoke] ${value}`);
  await fs.writeFile(path.join(artifactDir, 'progress.json'), JSON.stringify({ stage, platform: process.platform }, null, 2));
}
function survivingRoles() {
  const pids = [...knownPids].filter(alive);
  if (!pids.length) return [];
  try {
    if (process.platform === 'win32') {
      const filter = pids.map(pid => `ProcessId=${pid}`).join(' OR ');
      const raw = execFileSync('powershell.exe', ['-NoProfile', '-Command', `Get-CimInstance Win32_Process -Filter '${filter}' | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress`], { encoding: 'utf8', timeout: 10_000 });
      const parsed = JSON.parse(raw || '[]');
      return (Array.isArray(parsed) ? parsed : [parsed]).map(row => ({ pid: row.ProcessId, name: row.Name,
        type: /--type=([^ ]+)/.exec(row.CommandLine || '')?.[1] || 'main-or-service' }));
    }
    return pids.map(pid => ({ pid }));
  } catch { return pids.map(pid => ({ pid })); }
}
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
const knownOwned = new WeakMap();
async function closeBounded(application) {
  const processHandle = application.process();
  const owned = new Set([processHandle.pid, ...(knownOwned.get(application) || [])]);
  try { for (const pid of descendants(processHandle.pid)) owned.add(pid); } catch {}
  let timer;
  try {
    await Promise.race([
      application.close(),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('Desktop close exceeded 20 seconds')), 20_000); }),
    ]);
    await gone([...owned]);
  } catch (error) {
    try { processHandle.kill('SIGKILL'); } catch {}
    await gone([...owned]);
    throw error;
  } finally { clearTimeout(timer); }
}
async function open(label) {
  await progress(`${label}: launch`);
  const application = await electron.launch({ executablePath, args: [`--user-data-dir=${profile}`], env: environment, timeout: 60_000 });
  try {
  application.process().stderr?.on('data', data => process.stderr.write(data));
  const page = await application.firstWindow({ timeout: 60_000 });
  knownPids.add(application.process().pid);
  knownOwned.set(application, descendants(application.process().pid));
  page.on('pageerror', error => pageErrors.push(error.message));
  page.on('console', message => {
    if (message.type() !== 'error') return;
    const text = message.text();
    const url = message.location().url || '';
    if (/503/.test(text) && (!url || url.includes('/api/'))) return; // explicit fixture failures only
    consoleErrors.push({ text, url });
  });
  // Fixture-only UI data. Read-only runtime-info/health still exercise real packaged backend.
  await page.route('**/api/**', route => {
    if (/\/api\/(runtime-info|health)(\?|$)/.test(route.request().url())) return route.continue();
    return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Native desktop offline fixture' }) });
  });
  await page.waitForURL('app://research/**', { timeout: 150_000 });
  await page.getByTestId('app-sidebar').waitFor({ state: 'visible', timeout: 30_000 });
  knownOwned.set(application, [...new Set([...knownOwned.get(application), ...descendants(application.process().pid)])]);
  for (const pid of knownOwned.get(application)) knownPids.add(pid);
  await progress(`${label}: window and sidebar loaded`);
  return { application, page };
  } catch (error) {
    console.error(`[desktop-smoke] primary open failure at ${stage}: ${error.stack || error}`);
    await fs.writeFile(path.join(artifactDir, 'failure.json'), JSON.stringify({ stage, error: String(error), pageErrors, consoleErrors }, null, 2));
    await closeBounded(application).catch(cleanup => console.error(`[desktop-smoke] cleanup: ${cleanup}`));
    throw error;
  }
}
let first;
let second;
let primaryFailure;
let result;
try {
  first = await open('first');
  const { application, page } = first;
  await progress('checking renderer sandbox and real backend bridge');
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
  await progress('loading Settings content');
  await page.goto('app://research/settings');
  await page.getByTestId('wave5-global-ai-notice').waitFor({ state: 'visible', timeout: 30_000 });
  await page.reload();
  await page.getByTestId('wave5-global-ai-notice').waitFor({ state: 'visible', timeout: 30_000 });
  await page.evaluate(() => document.fonts.ready);
  assert.deepEqual(pageErrors, [], 'No renderer exceptions');
  assert.deepEqual(consoleErrors, [], 'No unexpected renderer console errors');
  assert.equal(await page.evaluate(() => localStorage.getItem('desktop-smoke-persistence')), 'fixture');
  await page.screenshot({ path: path.join(artifactDir, 'settings.png'), fullPage: true });
  await progress('checking second instance exits');
  second = spawn(executablePath, [`--user-data-dir=${profile}`], { env: environment, stdio: 'ignore' });
  knownPids.add(second.pid);
  let secondTimer;
  try {
    await Promise.race([new Promise((resolve, reject) => { second.once('exit', code => code === 0 ? resolve() : reject(new Error(`Second instance exit ${code}`))); second.once('error', reject); }),
      new Promise((_, reject) => { secondTimer = setTimeout(() => reject(new Error('Second instance did not exit')), 15_000); })]);
  } finally { clearTimeout(secondTimer); }
  assert.equal(application.windows().length, 1);
  const owned = descendants(application.process().pid);
  for (const pid of owned) knownPids.add(pid);
  assert.ok(owned.length >= 3, 'native runtime child tree present');
  await progress('normal close and descendant cleanup');
  await closeBounded(application); first = null;
  await gone(owned);
  const restarted = await open('restart'); first = restarted;
  assert.equal(await restarted.page.evaluate(() => localStorage.getItem('desktop-smoke-persistence')), 'fixture');
  const crashOwned = descendants(restarted.application.process().pid);
  for (const pid of crashOwned) knownPids.add(pid);
  await progress('forced main-process crash and descendant cleanup');
  process.kill(restarted.application.process().pid, 'SIGKILL'); first = null;
  await gone(crashOwned);
  result = { platform: process.platform, packagedWindow: true,
    sandbox: true, backend: true, fixtureOnly: true, settingsReady: true, navigationReload: true,
    singleInstance: true, persistence: true, normalCleanup: true, crashCleanup: true };
  await fs.writeFile(path.join(profile, 'desktop-smoke-persistence.json'), JSON.stringify({ fixture: true, persistence: 'kept' }));
} catch (error) {
  primaryFailure = error;
  console.error(`[desktop-smoke] PRIMARY FAILURE at ${stage}: ${error.stack || error}`);
  await fs.writeFile(path.join(artifactDir, 'failure.json'), JSON.stringify({ stage, error: String(error),
    pageErrors, consoleErrors, survivingProcesses: survivingRoles() }, null, 2));
  if (first) await first.page.screenshot({ path: path.join(artifactDir, 'failure.png'), fullPage: true, timeout: 5000 }).catch(() => {});
} finally {
  const cleanupErrors = [];
  if (second && second.exitCode === null) {
    try { second.kill('SIGKILL'); await gone([second.pid]); } catch (error) { cleanupErrors.push(String(error)); }
  }
  if (first) await closeBounded(first.application).catch(error => cleanupErrors.push(String(error)));
  if (!keepProfile && !cleanupErrors.length) {
    await fs.rm(profile, { recursive: true, force: true, maxRetries: 8, retryDelay: 500 }).catch(error => cleanupErrors.push(String(error)));
  }
  if (cleanupErrors.length) {
    console.error(`[desktop-smoke] CLEANUP ERRORS: ${cleanupErrors.join('; ')}`);
    await fs.writeFile(path.join(artifactDir, 'cleanup-errors.json'), JSON.stringify({ cleanupErrors, survivingProcesses: survivingRoles() }, null, 2));
    primaryFailure ||= new Error(cleanupErrors.join('; '));
  }
}
if (primaryFailure) throw primaryFailure;
await fs.writeFile(path.join(artifactDir, 'result.json'), JSON.stringify(result, null, 2));
await progress('complete');
console.log('Native packaged desktop fixture smoke passed');
