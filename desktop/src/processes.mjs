import { spawn } from 'node:child_process';

// Only children spawned by this supervisor can be registered and terminated.
export function spawnOwned(command, args, options = {}) {
  return spawn(command, args, {
    ...options, windowsHide: true, detached: process.platform !== 'win32',
    stdio: ['ignore', 'pipe', 'pipe'],
  });
}

export async function stopOwned(child, platform = process.platform) {
  if (!child?.pid) return;
  if (platform === 'win32') {
    // The enclosing Windows Job Object is the final crash-safety boundary.
    await new Promise(resolve => {
      const killer = spawn('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'],
        { windowsHide: true, stdio: 'ignore' });
      killer.once('error', resolve);
      killer.once('exit', resolve);
    });
    return;
  }
  const signal = value => { try { process.kill(-child.pid, value); } catch (error) { if (error.code !== 'ESRCH') throw error; } };
  signal('SIGTERM');
  // Group may outlive its leader. Always reap remaining descendants too.
  await new Promise(resolve => setTimeout(resolve, 700));
  signal('SIGKILL');
}
