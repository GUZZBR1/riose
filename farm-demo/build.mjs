import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const root = fileURLToPath(new URL('.', import.meta.url));
const output = resolve(
  root,
  '../src/riose/products/livestock_tracking/adapters/static/assets/farm-demo/farm-demo.js',
);

await build({
  entryPoints: [resolve(root, 'src/index.ts')],
  bundle: true,
  minify: true,
  legalComments: 'none',
  format: 'esm',
  platform: 'browser',
  target: 'es2020',
  outfile: output,
});
