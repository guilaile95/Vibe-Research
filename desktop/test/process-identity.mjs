// Playwright starts Electron through cmd.exe on Windows. Its child-process PID
// identifies that shell; only evaluation in Electron's main process identifies
// the actual crash/cleanup target. This helper never launches or signals anything.
export async function electronMainPID(application) {
  const pid = await application.evaluate(() => process.pid);
  if (!Number.isSafeInteger(pid) || pid <= 0) throw new Error('Electron did not report a valid main-process PID');
  return pid;
}
