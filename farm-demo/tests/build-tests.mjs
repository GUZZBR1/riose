import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const root = fileURLToPath(new URL('..', import.meta.url));
const output = resolve(root, '.test-build');
await mkdir(output, { recursive: true });
await build({
  entryPoints: [resolve(root, 'tests/farm-logic.test.ts')],
  bundle: true,
  platform: 'node',
  format: 'esm',
  target: 'node20',
  outfile: resolve(output, 'farm-logic.test.mjs'),
});
