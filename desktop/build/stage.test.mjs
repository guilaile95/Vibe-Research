import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, rmSync, symlinkSync, writeFileSync, readFileSync, lstatSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { allowedName, backendInput, frontendInput, agentInput, cleanBuildEnv, safeSource, copyBackend } from './stage.mjs';

test('private files and unsafe paths cannot become package inputs', () => {
  for (const name of ['../private.json', '/etc/passwd', 'frontend/.env.local', 'frontend/private/a.json', 'backend/x.db',
    'frontend/src/ai_credentials.json', 'frontend\\secret.js', 'frontend/node_modules/a.js', './frontend/a']) assert.equal(allowedName(name), false, name);
  assert.equal(allowedName('frontend/src/data/sectors.json'), true);
});
test('backend is an explicit static allowlist and top-level source only', () => {
  assert.equal(backendInput('backend/app.py'), true);
  assert.equal(backendInput('backend/data/signals_gpu_seed.json'), true);
  for (const name of ['backend/conftest.py', 'backend/tests/test_api.py', 'backend/data/secret.json', 'backend/portfolio.json']) assert.equal(backendInput(name), false);
  assert.equal(backendInput('frontend/src/data/sectors.json'), true);
});
test('frontend excludes existing output and tests, agent excludes unrelated files', () => {
  assert.equal(frontendInput('frontend/src/App.tsx'), true);
  assert.equal(frontendInput('frontend/dist/index.html'), false);
  assert.equal(frontendInput('frontend/tests/example.ts'), false);
  assert.equal(agentInput('agent-runtime/src/server.mjs'), true);
  assert.equal(agentInput('agent-runtime/test/example.mjs'), false);
  assert.equal(agentInput('agent-runtime/package-lock.json'), true);
});
test('build env does not inject Vite constants or alternate runtimes', () => {
  assert.deepEqual(cleanBuildEnv({ PATH: '/bin', VITE_API_KEY: 'secret', NODE_OPTIONS: '--require bad', PYTHONPATH: '/bad', PYTHONHOME: '/bad' }), { PATH: '/bin' });
});
test('source files cannot traverse symlinks', () => {
  const root = mkdtempSync(path.join(os.tmpdir(), 'vibe-stage-test-'));
  try {
    mkdirSync(path.join(root, 'frontend'));
    writeFileSync(path.join(root, 'frontend/index.html'), 'safe');
    assert.equal(safeSource(root, 'frontend/index.html'), path.join(root, 'frontend/index.html'));
    if (process.platform !== 'win32') {
      symlinkSync(path.join(root, 'frontend'), path.join(root, 'link'));
      assert.throws(() => safeSource(root, 'link/index.html'), /symlink/);
    }
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('backend library aliases survive deleting the original build directory', { skip: process.platform === 'win32' }, () => {
  const root = mkdtempSync(path.join(os.tmpdir(), 'vibe-relocation-test-'));
  try {
    const source = path.join(root, 'build/backend');
    const destination = path.join(root, 'resources/backend');
    mkdirSync(path.join(source, '_internal/numpy.libs'), { recursive: true });
    writeFileSync(path.join(source, '_internal/numpy.libs/libexample.so'), 'native-library-bytes');
    symlinkSync('numpy.libs/libexample.so', path.join(source, '_internal/libexample.so'));
    copyBackend(source, destination);
    rmSync(path.join(root, 'build'), { recursive: true });
    const alias = path.join(destination, '_internal/libexample.so');
    assert.equal(lstatSync(alias).isSymbolicLink(), false);
    assert.equal(readFileSync(alias, 'utf8'), 'native-library-bytes');
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('backend alias cannot collect an outside file', { skip: process.platform === 'win32' }, () => {
  const root = mkdtempSync(path.join(os.tmpdir(), 'vibe-alias-boundary-test-'));
  try {
    mkdirSync(path.join(root, 'build'));
    writeFileSync(path.join(root, 'outside.txt'), 'must-not-bundle');
    symlinkSync('../outside.txt', path.join(root, 'build/alias'));
    assert.throws(() => copyBackend(path.join(root, 'build'), path.join(root, 'out')), /escapes/);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
