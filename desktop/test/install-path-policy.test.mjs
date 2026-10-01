import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import os from 'node:os';
import { requiresProtectedPermissions } from './install-path-policy.mjs';
const root = path.join(os.tmpdir(), 'fixture-install', 'Vibe Research');

test('application tree directories remain subject to strict permission checks', () => {
  for (const entry of [root, path.join(root, 'resources'), path.join(root, 'resources', 'backend')]) {
    assert.equal(requiresProtectedPermissions(entry, true, root), true);
  }
});
test('only shared directories outside the package-owned application tree are excluded', () => {
  for (const entry of [path.dirname(root), path.parse(root).root, `${root}-other`]) {
    assert.equal(requiresProtectedPermissions(entry, true, root), false);
  }
});
test('all package files including external desktop entries and icons remain checked', () => {
  for (const entry of [path.join(root, 'vibe-research'), path.join(os.tmpdir(), 'share', 'applications', 'vibe.desktop'), path.join(os.tmpdir(), 'icons', 'vibe.png')]) {
    assert.equal(requiresProtectedPermissions(entry, false, root), true);
  }
});

test('directory symlink targets never receive the shared-directory exemption', () => {
  assert.equal(requiresProtectedPermissions(path.join(os.tmpdir(), 'shared-directory-link'), true, root, true), true);
});
