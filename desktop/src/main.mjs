import { app, BrowserWindow, dialog, protocol, session, shell } from 'electron';
import { spawn } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import readline from 'node:readline';
import { fileURLToPath } from 'node:url';
import { APP_ORIGIN, createProtocolHandler, isAppURL } from './protocol.mjs';

protocol.registerSchemesAsPrivileged([{ scheme: 'app', privileges: {
  standard: true, secure: true, supportFetchAPI: true, corsEnabled: true, stream: true,
} }]);
app.enableSandbox();
app.setName('Vibe Research');
app.setPath('userData', path.resolve(app.commandLine.getSwitchValue('user-data-dir') || path.join(app.getPath('appData'), 'Vibe Research')));
app.setAppUserModelId('org.viberesearch.desktop');
const here = path.dirname(fileURLToPath(import.meta.url));
let window;
let supervisor;
let quitting = false;
let stopped = false;
let failed = false;

function serviceEnvironment(data) {
  const env = {};
  // Avoid loading user PYTHONPATH/NODE_OPTIONS, external credentials, or legacy
  // data-dir overrides into the desktop distribution.
  for (const key of ['PATH', 'PATHEXT', 'SystemRoot', 'SYSTEMROOT', 'WINDIR', 'COMSPEC',
    'HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'TEMP', 'TMP', 'TMPDIR',
    'LANG', 'LC_ALL', 'LC_CTYPE', 'DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY',
    'XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS', 'XDG_CURRENT_DESKTOP',
    'VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH', 'VIBE_NATIVE_INTEL_DISABLE_SCHEDULER', 'HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY',
    'http_proxy', 'https_proxy', 'no_proxy', 'SSL_CERT_FILE', 'SSL_CERT_DIR']) {
    if (process.env[key]) env[key] = process.env[key];
  }
  return { ...env, VR_DATA_DIR: data, VR_REPORTS_DIR: path.join(data, 'reports'),
    VIBE_RESEARCH_REVIEW_DB: path.join(data, 'review.db'),
    VIBE_RESEARCH_NEWS_RADAR_CACHE: path.join(data, '.cache', 'radar.json'),
    VR_API_KEY: randomBytes(32).toString('hex'),
    VR_AGENT_RUNTIME_TOKEN: randomBytes(32).toString('hex'),
    VR_ALLOW_ORIGINS: 'http://127.0.0.1', VR_TRUSTED_HOSTS: '127.0.0.1',
    PYTHONNOUSERSITE: '1', PYTHONDONTWRITEBYTECODE: '1',
  };
}

function stop() {
  if (quitting) return;
  quitting = true;
  if (!supervisor || stopped) { app.quit(); return; }
  // Closing the ownership pipe triggers cleanup even if Electron crashes.
  // Do not kill the supervisor before it has reaped its children.
  supervisor.stdin.end();
}
function fail() {
  if (failed || quitting) return;
  failed = true;
  dialog.showErrorBox('Vibe Research 启动失败',
    '本地服务未能启动或已停止。请关闭后重试。数据仍保存在本机用户目录。若问题持续，请检查安装包完整性及系统支持版本。');
  stop();
}

async function launch(resources, data, env) {
  const suffix = process.platform === 'win32' ? '.exe' : '';
  const node = path.join(resources, 'node', `node${suffix}`);
  const script = app.isPackaged
    ? path.join(process.resourcesPath, 'app.asar.unpacked', 'src', 'supervisor.mjs')
    : path.join(here, 'supervisor.mjs');
  const args = [script, resources, data];
  // The native wrapper places its full Windows process tree in a kill-on-close
  // Job Object before starting Node; no global process/port killing.
  const command = path.join(resources, 'backend', `vibe-backend${suffix}`);
  supervisor = spawn(command, ['--desktop-supervisor', node, ...args],
    { env, cwd: data, windowsHide: true, stdio: ['pipe', 'pipe', 'ignore'] });
  supervisor.stdin.on('error', () => { if (!quitting) fail(); });
  return await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('STARTUP_TIMEOUT')), 150_000);
    const lines = readline.createInterface({ input: supervisor.stdout });
    lines.on('line', line => {
      try {
        const value = JSON.parse(line);
        if (value.type === 'ready' && Number.isInteger(value.backendPort) &&
            value.backendPort > 0 && value.backendPort < 65536) {
          clearTimeout(timer); resolve(value);
        } else if (value.type === 'failure') { reject(new Error('SERVICE_FAILED')); fail(); }
      } catch { /* Never display raw subprocess output. */ }
    });
    supervisor.once('error', () => { clearTimeout(timer); stopped = true; reject(new Error('LAUNCH_FAILED')); fail(); });
    supervisor.once('exit', () => {
      clearTimeout(timer); stopped = true; reject(new Error('SERVICE_EXITED'));
      if (quitting) app.quit(); else fail();
    });
  });
}

async function waitBackend(port, token) {
  const deadline = Date.now() + 120_000;
  while (!quitting && Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/runtime-info`, {
        headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(1500), redirect: 'error',
      });
      if (response.ok && (await response.json()).data?.service === 'vibe-research-api') return;
    } catch { /* Imports and startup may take several seconds on a first launch. */ }
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  throw new Error('BACKEND_NOT_READY');
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => { if (window) { if (window.isMinimized()) window.restore(); window.show(); window.focus(); } });
  app.on('before-quit', event => { if (!stopped && supervisor) { event.preventDefault(); stop(); } });
  app.on('window-all-closed', stop);
  app.whenReady().then(async () => {
    fs.mkdirSync(app.getPath('userData'), { recursive: true, mode: 0o700 });
    if (process.platform !== 'win32') fs.chmodSync(app.getPath('userData'), 0o700);
    const data = path.join(app.getPath('userData'), 'research-data');
    fs.mkdirSync(data, { recursive: true, mode: 0o700 });
    if (process.platform !== 'win32') fs.chmodSync(data, 0o700);
    const resources = app.isPackaged ? process.resourcesPath : path.join(here, '..', 'resources');
    const env = serviceEnvironment(data);
    const isolated = session.fromPartition('persist:vibe-desktop');
    isolated.setPermissionRequestHandler((_webContents, _permission, callback) => callback(false));
    isolated.setPermissionCheckHandler(() => false);
    isolated.on('will-download', (_event, item) => {
      // Standard native save dialog; do not run or auto-open downloaded files.
      item.setSaveDialogOptions({ title: '保存 Vibe Research 导出文件' });
    });
    window = new BrowserWindow({ width: 1380, height: 900, minWidth: 960, minHeight: 640,
      title: 'Vibe Research', backgroundColor: '#f8fafc', autoHideMenuBar: true,
      webPreferences: { session: isolated, contextIsolation: true, nodeIntegration: false,
        sandbox: true, webSecurity: true, allowRunningInsecureContent: false,
        webviewTag: false, navigateOnDragDrop: false, spellcheck: false },
    });
    window.webContents.on('will-attach-webview', event => event.preventDefault());
    const external = async raw => {
      let url; try { url = new URL(raw); } catch { return; }
      if (url.protocol !== 'https:' || url.username || url.password) return;
      const answer = await dialog.showMessageBox(window, { type: 'question', buttons: ['取消', '打开浏览器'],
        defaultId: 0, cancelId: 0, title: '打开外部链接', message: `在系统浏览器中打开 ${url.hostname}？` });
      if (answer.response === 1 && !quitting) await shell.openExternal(url.href);
    };
    window.webContents.setWindowOpenHandler(({ url }) => { void external(url); return { action: 'deny' }; });
    window.webContents.on('will-navigate', (event, url) => { if (!isAppURL(url)) { event.preventDefault(); void external(url); } });
    window.webContents.on('will-redirect', (event, url) => { if (!isAppURL(url)) event.preventDefault(); });
    window.webContents.on('render-process-gone', fail);
    await window.loadFile(path.join(here, 'loading.html'));
    const { backendPort } = await launch(resources, data, env);
    await waitBackend(backendPort, env.VR_API_KEY);
    if (quitting) return;
    isolated.protocol.handle('app', createProtocolHandler({ frontend: path.join(resources, 'frontend'), backendPort, token: env.VR_API_KEY }));
    await window.loadURL(`${APP_ORIGIN}/`);
  }).catch(fail);
}
