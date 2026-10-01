import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { readdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const directory = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../release');
const names = (await readdir(directory)).filter(name => /\.(deb|tar\.gz|exe)$/.test(name)).sort();
if (!names.length) throw new Error('No installers to checksum');
const lines = [];
for (const name of names) {
  const hash = createHash('sha256');
  for await (const chunk of createReadStream(path.join(directory, name))) hash.update(chunk);
  lines.push(`${hash.digest('hex')}  ${name}`);
}
await writeFile(path.join(directory, 'SHA256SUMS'), lines.join('\n') + '\n');
console.log(lines.join('\n'));
