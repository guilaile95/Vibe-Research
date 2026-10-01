/** Real installer roundtrip, restricted to disposable OS-matched x64 CI runners. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import { constants } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { cleanupInOrder, uncertainProcessFailure } from './cleanup-policy.mjs';

assert.equal(process.env.CI, 'true', 'Installer acceptance is restricted to disposable CI=true runners');
assert.equal(process.env.VR_DESKTOP_INSTALLER_ACCEPTANCE, '1', 'Installer acceptance requires explicit opt-in');
assert.ok(['linux', 'win32'].includes(process.platform), 'Installer acceptance supports Linux and Windows only');
assert.equal(process.arch, 'x64', 'Installer acceptance requires an x64 runner');
assert.equal(process.env.GITHUB_ACTIONS, 'true', 'Installer acceptance requires a disposable GitHub Actions runner');
assert.equal(process.env.RUNNER_OS, process.platform === 'linux' ? 'Linux' : 'Windows', 'Runner OS must match the native installer');
if (process.platform === 'linux') assert.notEqual(process.getuid?.(), 0, 'Run as an ordinary non-root user; never bypass the sandbox');

const desktop = fileURLToPath(new URL('..', import.meta.url));
const release = path.join(desktop, 'release');
const artifactDir = path.join(release, 'smoke-installed');
const packageName = 'vibe-research-desktop';
const markerName = 'desktop-smoke-persistence.json';
const watchdog = path.join(desktop, 'test', 'run-owned.py');
let watchdogCleanupFailed = false;
const run = (file, args, options = {}) => {
  if (watchdogCleanupFailed) throw new Error('Further commands blocked after uncertain owned cleanup');
  const privileged = process.platform === 'linux' && file === 'sudo';
  const executable = privileged ? 'sudo' : process.platform === 'win32' ? 'python' : 'python3';
  const wrapped = privileged
    ? ['-n', '/usr/bin/python3', watchdog, '600', ...args]
    : [watchdog, '600', file, ...args];
  try {
    // The watchdog owns the timeout and waits for its entire process tree to
    // stop. An outer sync timeout would race uninstall/fixture cleanup.
    return execFileSync(executable, wrapped, { cwd: desktop, stdio: 'inherit', ...options });
  } catch (error) {
    if (uncertainProcessFailure(error)) watchdogCleanupFailed = true;
    throw error;
  }
};
const output = (file, args) => run(file, args, { stdio: ['ignore', 'pipe', 'pipe'], encoding: 'utf8' }).trim();
const exists = async target => fs.lstat(target).then(() => true, error => {
  if (error.code === 'ENOENT') return false;
  throw error;
});
const installers = (await fs.readdir(release, { withFileTypes: true }))
  .filter(entry => entry.isFile() && (process.platform === 'linux' ? /\.deb$/i : /\.exe$/i).test(entry.name)
    && !/uninstall/i.test(entry.name)).map(entry => path.join(release, entry.name));
assert.equal(installers.length, 1, `Expected exactly one installer, found: ${installers.join(', ')}`);
// Refuse to replace an unrelated/pre-existing installation on a misconfigured runner.
if (process.platform === 'linux') {
  let status = '';
  try { status = output('dpkg-query', ['-W', '-f=${db:Status-Status}', packageName]); }
  catch (error) { if (error.status !== 1) throw error; }
  assert.equal(status, '', 'CI runner already has this package installed or registered; every preexisting state is refused');
  assert.equal(output('dpkg-deb', ['-f', installers[0], 'Package']), packageName);
  assert.equal(output('dpkg-deb', ['-f', installers[0], 'Architecture']), 'amd64');
}
if (process.platform === 'win32') {
  run('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command',
    "$ErrorActionPreference='Stop'; $roots=@('HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall', 'HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall', 'HKLM:\\Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall'); foreach ($root in $roots) { if (Test-Path $root) { foreach ($key in Get-ChildItem -LiteralPath $root) { $app=Get-ItemProperty -LiteralPath $key.PSPath; if ($app.DisplayName -like 'Vibe Research*') { throw 'CI runner already has Vibe Research installed' } } } }"]);
}
const appDataBase = process.platform === 'win32' ? process.env.APPDATA
  : (process.env.XDG_CONFIG_HOME || path.join(os.homedir(), '.config'));
assert.ok(appDataBase && path.isAbsolute(appDataBase), 'Default app data base must be absolute');
const defaultData = path.join(appDataBase, 'Vibe Research');
assert.equal(await exists(defaultData), false, 'Refuse to touch an existing default user-data directory');
const ownTemp = await fs.mkdtemp(path.join(os.tmpdir(), 'vibe-installer-roundtrip-'));
const installDir = path.join(ownTemp, 'Vibe Research 安装测试');
const profile = path.join(ownTemp, 'Chromium 用户数据 profile');
const defaultSentinel = path.join(defaultData, 'installer-smoke-owned-sentinel.json');
const sentinelContents = JSON.stringify({ fixture: true, owner: path.basename(ownTemp) });
let ownsDefaultData = false;
const smokeEnv = {
  ...process.env,
  VR_DESKTOP_SMOKE_PROFILE: profile,
  VR_DESKTOP_SMOKE_KEEP_PROFILE: '1',
  VR_DESKTOP_SMOKE_ARTIFACT_DIR: artifactDir,
  VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH: '1',
  VIBE_NATIVE_INTEL_DISABLE_SCHEDULER: '1',
};
delete smokeEnv.ELECTRON_RUN_AS_NODE;

async function waitAbsent(target) {
  const deadline = Date.now() + 60_000;
  while (await exists(target)) {
    assert.ok(Date.now() < deadline, `Uninstaller left installed executable present: ${target}`);
    await new Promise(resolve => setTimeout(resolve, 250));
  }
}
async function filesUnder(root) {
  const result = [];
  for (const entry of await fs.readdir(root, { withFileTypes: true })) {
    const target = path.join(root, entry.name);
    assert.ok(!entry.isSymbolicLink(), `Unexpected symlink in owned CI directory: ${target}`);
    if (entry.isDirectory()) result.push(...await filesUnder(target));
    else if (entry.isFile()) result.push(target);
  }
  return result;
}
async function profileSnapshot() {
  const marker = await fs.readFile(path.join(profile, markerName));
  assert.ok(marker.length > 0, 'Persistence marker must be nonempty');
  const localStorage = path.join(profile, 'Partitions', 'vibe-desktop', 'Local Storage');
  const files = await filesUnder(localStorage);
  assert.ok(files.length > 0, 'Chromium Local Storage must exist');
  const snapshot = { [markerName]: createHash('sha256').update(marker).digest('hex') };
  let bytes = 0;
  for (const file of files.sort()) {
    const contents = await fs.readFile(file);
    bytes += contents.length;
    snapshot[path.relative(profile, file)] = createHash('sha256').update(contents).digest('hex');
  }
  assert.ok(bytes > 0, 'Chromium Local Storage must contain persisted data');
  return snapshot;
}
async function verifyLinuxInstallation() {
  const entries = output('dpkg', ['-L', packageName]).split('\n').filter(Boolean);
  const candidates = [];
  for (const entry of entries.filter(entry => path.basename(entry) === 'vibe-research')) {
    if ((await fs.lstat(entry)).isFile()) candidates.push(entry);
  }
  assert.equal(candidates.length, 1, 'Package must contain exactly one installed executable');
  const executable = candidates[0];
  assert.ok(path.isAbsolute(executable));
  assert.ok((await fs.stat(executable)).isFile());
  await fs.access(executable, constants.X_OK);
  for (const entry of entries) {
    const stat = await fs.stat(entry);
    assert.equal(stat.uid, 0, `Installed path must be root-owned: ${entry}`);
    assert.equal(stat.mode & 0o022, 0, `Installed path must not be group/world-writable: ${entry}`);
    if (stat.isFile()) {
      let writable = false;
      try { await fs.access(entry, constants.W_OK); writable = true; }
      catch (error) { if (!['EACCES', 'EPERM', 'EROFS'].includes(error.code)) throw error; }
      assert.equal(writable, false, `Installed file must not be writable by smoke user: ${entry}`);
    }
  }
  return executable;
}
function nsis(executable, lastArgument) {
  // Start-Process joins ArgumentList without quoting: NSIS requires /D= and _?=
  // to be the final, unquoted command-line tail, even with spaces/Unicode.
  run('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command',
    "$ErrorActionPreference='Stop'; $p=Start-Process -FilePath $env:VR_SMOKE_NSIS_EXE -ArgumentList @('/S', $env:VR_SMOKE_NSIS_TAIL) -Wait -PassThru; exit $p.ExitCode"],
  { env: { ...process.env, VR_SMOKE_NSIS_EXE: executable, VR_SMOKE_NSIS_TAIL: lastArgument } });
}
function readonlyTree(enabled) {
  run('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command',
    "$ErrorActionPreference='Stop'; Get-ChildItem -LiteralPath $env:VR_SMOKE_INSTALL_DIR -Recurse -File | ForEach-Object { if ($env:VR_SMOKE_READONLY -eq '1') { $_.Attributes=$_.Attributes -bor [System.IO.FileAttributes]::ReadOnly } else { $_.Attributes=$_.Attributes -band (-bnot [System.IO.FileAttributes]::ReadOnly) } }"],
  { env: { ...process.env, VR_SMOKE_INSTALL_DIR: installDir, VR_SMOKE_READONLY: enabled ? '1' : '0' } });
}
let installAttempted = false;
let installState = 'not-started';
let uninstalled = false;
let executable;
let readonlyApplied = false;
async function restoreAttributes() {
  if (readonlyApplied && await exists(installDir)) readonlyTree(false);
  readonlyApplied = false;
}
async function uninstall() {
  if (!installAttempted || uninstalled) return;
  if (process.platform === 'linux') run('sudo', ['apt-get', 'remove', '-y', packageName]);
  else if (await exists(installDir)) {
    await restoreAttributes();
    const uninstallers = (await fs.readdir(installDir, { withFileTypes: true }))
      .filter(entry => entry.isFile() && /^uninstall.*\.exe$/i.test(entry.name));
    assert.equal(uninstallers.length, 1, 'Expected the installed app’s own NSIS uninstaller');
    // _?= prevents NSIS spawning a temporary copy and exiting early. It also
    // leaves the uninstaller itself behind; only our generated temp tree is cleaned later.
    nsis(path.join(installDir, uninstallers[0].name), `_?=${installDir}`);
  }
  else if (installState === 'uncertain') throw new Error('Installer failed or timed out before its directory appeared; installation state is uncertain');
  if (executable) await waitAbsent(executable);
  uninstalled = true;
}
let failure;
try {
  await fs.mkdir(artifactDir, { recursive: true });
  await fs.mkdir(profile);
  await fs.mkdir(appDataBase, { recursive: true });
  // Non-recursive creation still fails closed if another actor created app data.
  await fs.mkdir(defaultData);
  ownsDefaultData = true;
  await fs.writeFile(defaultSentinel, sentinelContents, { flag: 'wx' });
  installAttempted = true;
  installState = 'running';
  if (process.platform === 'linux') {
    run('sudo', ['apt-get', 'install', '-y', installers[0]]);
    installState = 'installed';
    executable = await verifyLinuxInstallation();
  } else {
    assert.equal(await exists(installDir), false);
    nsis(installers[0], `/D=${installDir}`);
    installState = 'installed';
    executable = path.join(installDir, 'Vibe Research.exe');
    assert.ok((await fs.stat(executable)).isFile(), 'NSIS must install the executable at the requested Unicode path');
    await filesUnder(installDir); // Reject symlinks before recursive attribute changes.
    readonlyApplied = true; // Restore even if setting attributes partially fails.
    readonlyTree(true);
  }
  const smokeArgs = [path.join(desktop, 'test', 'native-smoke.mjs'), executable];
  if (process.platform === 'linux') run('xvfb-run', ['-a', process.execPath, ...smokeArgs], { env: smokeEnv });
  else run(process.execPath, smokeArgs, { env: smokeEnv });
  const before = await profileSnapshot();
  await uninstall();
  const after = await profileSnapshot();
  assert.equal(await fs.readFile(defaultSentinel, 'utf8'), sentinelContents,
    'Normal uninstall must preserve the default app-data directory too');
  assert.deepEqual(after, before, 'Normal uninstall must preserve marker and Chromium profile data unchanged');
  const result = { platform: process.platform, installedWindow: true, normalUninstall: true, dataPreserved: true };
  await fs.writeFile(path.join(artifactDir, 'install-result.json'), JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify(result));
} catch (error) {
  if (installState === 'running') installState = 'uncertain';
  failure = error;
} finally {
  const cleanup = await cleanupInOrder([
    restoreAttributes,
    uninstall,
    async () => {
      if (!ownsDefaultData) return;
      if (await exists(defaultSentinel)) {
        assert.equal(await fs.readFile(defaultSentinel, 'utf8'), sentinelContents,
          'Refuse to delete a changed default-data sentinel');
        await fs.unlink(defaultSentinel);
      }
      // Never recursively delete default app data: retain unexpected contents.
      await fs.rmdir(defaultData).catch(error => {
        if (!['ENOENT', 'ENOTEMPTY', 'EEXIST'].includes(error.code)) throw error;
      });
    },
    async () => {
      // Preserve evidence instead of deleting a still-registered application.
      if (!installAttempted || uninstalled) await fs.rm(ownTemp, { recursive: true, force: true, maxRetries: 8, retryDelay: 500 });
    },
  ], () => watchdogCleanupFailed);
  if (cleanup.uncertain) throw new AggregateError([failure, ...cleanup.errors].filter(Boolean),
    'Owned process cleanup could not be verified; remaining installation and fixture state retained');
  if (failure || cleanup.errors.length) throw new AggregateError([failure, ...cleanup.errors].filter(Boolean), 'Installer acceptance failed');
}
