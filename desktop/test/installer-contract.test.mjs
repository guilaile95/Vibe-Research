// Pure source/configuration contracts. This file must never import or execute the installer helper.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const metadata = JSON.parse(fs.readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
const helper = fs.readFileSync(new URL('./install-smoke.mjs', import.meta.url), 'utf8');

test('installers do not autostart, preserve application data, and Linux launcher identity matches', () => {
  assert.equal(metadata.build.nsis.runAfterFinish, false);
  assert.equal(metadata.build.nsis.deleteAppDataOnUninstall, false);
  assert.equal(metadata.build.linux.syncDesktopName, true);
  assert.match(metadata.desktopName, /^[A-Za-z0-9.-]+\.desktop$/);
});
test('installer acceptance requires explicit native GitHub context before any command', () => {
  for (const key of ['CI', 'GITHUB_ACTIONS', 'RUNNER_OS', 'VR_DESKTOP_INSTALLER_ACCEPTANCE']) {
    const position = helper.indexOf(`process.env.${key}`);
    assert.ok(position >= 0 && position < helper.indexOf('const run ='), `${key} guard must precede process execution`);
  }
  assert.match(helper, /assert.equal\(status, ''/);
  assert.match(helper, /run-owned\.py/);
  assert.doesNotMatch(helper, /timeout:\s*600_000/);
  assert.match(helper, /watchdogCleanupFailed/);
  assert.match(helper, /installation state is uncertain/);
  assert.match(helper, /CI runner already has this package installed/);
  assert.match(helper, /CI runner already has Vibe Research installed/);
  assert.match(helper, /Refuse to touch an existing default user-data directory/);
  assert.doesNotMatch(helper, /apt-get', \['purge|Remove-Item.*APPDATA|chmod.*777|--no-sandbox/);
});
