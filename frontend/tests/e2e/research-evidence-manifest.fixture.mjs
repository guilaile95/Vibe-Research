import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { readFileSync, readdirSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

/** Bind browser evidence to its actual checkout and production assets, not a claimed SHA. */
export function researchEvidenceManifest(moduleUrl) {
  const root = fileURLToPath(new URL('../../../', moduleUrl));
  const dist = fileURLToPath(new URL('../../dist/', moduleUrl));
  const git = (...args) => execFileSync('git', args, { cwd: root, encoding: 'utf8' }).trim();
  const files = [];
  const visit = path => {
    for (const item of readdirSync(path, { withFileTypes: true })) {
      const file = join(path, item.name);
      if (item.isDirectory()) visit(file);
      else files.push({ path: relative(dist, file), sha256: createHash('sha256').update(readFileSync(file)).digest('hex') });
    }
  };
  visit(dist); files.sort((a, b) => a.path.localeCompare(b.path));
  return { checkoutSha: git('rev-parse', 'HEAD'), checkoutTree: git('rev-parse', 'HEAD^{tree}'), sourceClean: !git('status', '--porcelain', '--', 'frontend/src', 'frontend/tests'), fixture: 'synthetic-only/native-indexeddb/no-real-model-or-market', files };
}
