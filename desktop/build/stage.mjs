/** Native-host-only staging. Run from any cwd with Node >=22.6, Git, npm and Python. */
import { spawnSync } from 'node:child_process';
import { chmodSync, copyFileSync, cpSync, existsSync, lstatSync, mkdirSync, mkdtempSync, readdirSync, renameSync, rmSync, writeFileSync, realpathSync, statSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const STATIC = new Set(['backend/news_sources.json', 'backend/top_risk_config.yaml',
  'backend/data/cn_a_share_trade_calendar_v01.json', 'backend/data/signals_gpu_seed.json',
  'frontend/package.json', 'frontend/src/data/sectors.json']);
const FORBIDDEN = new Set(['private', '.git', 'node_modules', '__pycache__', '.cache', 'user-data',
  'portfolio.json', 'account_profile.json', 'ai_credentials.json', 'my-watchlist.json']);
export function allowedName(name) {
  return typeof name === 'string' && !path.isAbsolute(name) && !name.includes('\\') &&
    name.split('/').every(p => p && p !== '.' && p !== '..' && !FORBIDDEN.has(p.toLowerCase()) &&
      !p.toLowerCase().startsWith('.env') && !/\.(pem|key|secret|sqlite|db)$/i.test(p));
}
export function backendInput(name) {
  return allowedName(name) && (STATIC.has(name) || /^backend\/[^/]+\.py$/.test(name) && !name.endsWith('/conftest.py'));
}
export function frontendInput(name) {
  return allowedName(name) && name.startsWith('frontend/') && !name.startsWith('frontend/dist/') &&
    !name.startsWith('frontend/tests/') && !name.endsWith('.tsbuildinfo');
}
export function agentInput(name) {
  return allowedName(name) && (['agent-runtime/package.json', 'agent-runtime/package-lock.json'].includes(name) || name.startsWith('agent-runtime/src/'));
}
function run(command, args, options = {}) {
  const result = spawnSync(command, args, { cwd: ROOT, stdio: 'inherit', ...options });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${command} failed (${result.status ?? result.signal})`);
  return result;
}
export function safeSource(root, name) {
  if (!allowedName(name)) throw new Error(`Rejected package path: ${name}`);
  let current = root;
  for (const part of name.split('/')) {
    current = path.join(current, part);
    if (lstatSync(current).isSymbolicLink()) throw new Error(`Rejected source symlink: ${name}`);
  }
  if (!lstatSync(current).isFile()) throw new Error(`Not a regular source file: ${name}`);
  return current;
}
function copyInputs(names, dest) {
  for (const name of names) {
    const source = safeSource(ROOT, name);
    const target = path.join(dest, name);
    mkdirSync(path.dirname(target), { recursive: true });
    copyFileSync(source, target);
  }
}
export function cleanBuildEnv(env = process.env) {
  return Object.fromEntries(Object.entries(env).filter(([key]) => !/^(VITE_|NODE_OPTIONS$|PYTHONPATH$|PYTHONHOME$)/i.test(key)));
}
function validateTree(root, relative = '') {
  for (const entry of readdirSync(path.join(root, relative), { withFileTypes: true })) {
    const name = relative ? `${relative}/${entry.name}` : entry.name;
    if (!allowedName(name) || entry.isSymbolicLink()) throw new Error(`Rejected frontend build output: ${name}`);
    if (entry.isDirectory()) validateTree(root, name);
  }
}
export function copyBackend(source, destination) {
  // Materialize PyInstaller aliases explicitly: some Node/platform fs.cp
  // implementations preserve links even with dereference:true.
  const root = realpathSync(source);
  const visit = (from, to, ancestors) => {
    const real = realpathSync(from);
    const relative = path.relative(root, real);
    if (relative.startsWith(`..${path.sep}`) || relative === '..' || path.isAbsolute(relative)) {
      throw new Error('Backend library link escapes the build output');
    }
    const stat = statSync(real);
    if (stat.isDirectory()) {
      if (ancestors.has(real)) throw new Error('Cyclic backend directory alias');
      mkdirSync(to, { recursive: true });
      const next = new Set([...ancestors, real]);
      for (const name of readdirSync(real)) visit(path.join(real, name), path.join(to, name), next);
    } else if (stat.isFile()) {
      copyFileSync(real, to);
      chmodSync(to, stat.mode & 0o777);
    } else {
      throw new Error('Backend build contains a non-regular file');
    }
  };
  visit(source, destination, new Set());
}
export function main(args = process.argv.slice(2)) {
  const win = process.platform === 'win32';
  if (!['linux', 'win32'].includes(process.platform) || process.arch !== 'x64') throw new Error('Build on Linux x64 or Windows x64; cross-compilation is unsupported');
  const [major, minor] = process.versions.node.split('.').map(Number);
  if (major < 22 || major === 22 && minor < 6) throw new Error('Node >=22.6 is required');
  const pythonIndex = args.indexOf('--python');
  if (args.some((arg, i) => arg !== '--check' && arg !== '--python' && !(pythonIndex >= 0 && i === pythonIndex + 1)) || pythonIndex >= 0 && !args[pythonIndex + 1]) throw new Error('Usage: node desktop/build/stage.mjs [--check] [--python PATH]');
  const python = pythonIndex >= 0 ? args[pythonIndex + 1] : win ? 'python' : 'python3.11';
  const env = { ...cleanBuildEnv(), PIP_DISABLE_PIP_VERSION_CHECK: '1' };
  run(python, ['-c', `import sys,platform; assert sys.version_info[:2] == ${win ? '(3,12)' : '(3,11)'}, 'Wrong Python version'; assert platform.machine().lower() in ('x86_64','amd64'), 'x64 Python required'`], { env });
  const npm = win ? 'npm.cmd' : 'npm';
  // Windows .cmd commands require cmd.exe. Paths originate locally, never renderer input.
  const npmRun = (arguments_, cwd) => run(npm, arguments_, { cwd, env, shell: win });
  npmRun(['--version'], ROOT);
  const tracked = run('git', ['ls-files', '-z'], { stdio: ['ignore', 'pipe', 'inherit'] }).stdout.toString('utf8').split('\0').filter(Boolean);
  const backendNames = tracked.filter(backendInput);
  for (const required of STATIC) if (!backendNames.includes(required)) throw new Error(`Required tracked input missing: ${required}`);
  if (args.includes('--check')) {
    console.log(`Native build prerequisites passed; ${backendNames.length} backend inputs, ${tracked.filter(frontendInput).length} frontend inputs`);
    return;
  }
  const temp = mkdtempSync(path.join(os.tmpdir(), 'vibe-desktop-build-'));
  const output = path.join(ROOT, 'desktop/resources');
  const pending = path.join(ROOT, 'desktop/.resources-staging');
  if (existsSync(pending)) throw new Error('Another build or stale desktop/.resources-staging exists; inspect it before removing');
  mkdirSync(pending);
  try {
    const source = path.join(temp, 'source');
    copyInputs(backendNames, source);
    const frontendStage = path.join(temp, 'web');
    copyInputs(tracked.filter(frontendInput), frontendStage);
    npmRun(['ci', '--include=dev', '--no-audit', '--no-fund'], path.join(frontendStage, 'frontend'));
    npmRun(['run', 'build'], path.join(frontendStage, 'frontend'));
    const dist = path.join(frontendStage, 'frontend/dist');
    validateTree(dist);
    cpSync(dist, path.join(pending, 'frontend'), { recursive: true });
    copyInputs(tracked.filter(agentInput), pending);
    npmRun(['ci', '--omit=dev', '--include=optional', '--no-audit', '--no-fund'], path.join(pending, 'agent-runtime'));
    mkdirSync(path.join(pending, 'node'));
    const node = path.join(pending, 'node', win ? 'node.exe' : 'node');
    copyFileSync(process.execPath, node);
    // Retrieve the exact Node release's full license, including vendored notices.
    const nodeLicenseUrl = `https://raw.githubusercontent.com/nodejs/node/v${process.versions.node}/LICENSE`;
    run(python, ['-c', "import pathlib,sys,urllib.request; data=urllib.request.urlopen(sys.argv[1],timeout=60).read(); assert b'Node.js' in data and len(data)>1000; pathlib.Path(sys.argv[2]).write_bytes(data)",
      nodeLicenseUrl, path.join(pending, 'node/LICENSE')], { env });
    copyFileSync(safeSource(ROOT, 'LICENSE'), path.join(pending, 'LICENSE'));
    if (!win) chmodSync(node, 0o755);
    // Construction resolves the SDK's host-native optional binary without
    // starting Codex, making network calls, or reading user credentials.
    run(node, ['--input-type=module', '-e', "import { Codex } from '@openai/codex-sdk'; new Codex();"],
      { cwd: path.join(pending, 'agent-runtime'), env });
    const buildHome = path.join(temp, 'build-home');
    mkdirSync(buildHome);
    const venv = path.join(temp, 'venv');
    run(python, ['-m', 'venv', venv], { env });
    const buildPython = path.join(venv, win ? 'Scripts/python.exe' : 'bin/python');
    const lock = path.join(ROOT, 'backend', win ? 'requirements-dev-windows-py312.lock.txt' : 'requirements-linux-py311.lock.txt');
    run(buildPython, ['-m', 'pip', 'install', '-r', lock, 'PyInstaller==6.16.0', 'setuptools==80.9.0', 'backports.tarfile==1.2.0'], { env });
    run(buildPython, ['-m', 'PyInstaller', '--noconfirm', '--clean', '--distpath', path.join(temp, 'dist'),
      '--workpath', path.join(temp, 'pyinstaller'), path.join(ROOT, 'desktop/build/backend.spec')],
      { env: { ...env, VR_DESKTOP_STAGE_SOURCE: source, PYINSTALLER_CONFIG_DIR: path.join(temp, 'pyinstaller-cache'), HOME: buildHome, USERPROFILE: buildHome } });
    copyBackend(path.join(temp, 'dist/vibe-backend'), path.join(pending, 'backend'));
    writeFileSync(path.join(pending, 'build-manifest.json'), JSON.stringify({ platform: process.platform,
      arch: process.arch, node: process.versions.node, backendInputs: backendNames }, null, 2) + '\n');
    rmSync(output, { recursive: true, force: true });
    renameSync(pending, output);
    console.log(`Standalone resources ready: ${output}`);
  } finally {
    rmSync(temp, { recursive: true, force: true });
    rmSync(pending, { recursive: true, force: true });
  }
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { main(); } catch (error) { console.error(error.message); process.exitCode = 1; }
}
