import { readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const root = fileURLToPath(new URL('.', import.meta.url));
const output = resolve(root, '../src/riose/products/livestock_tracking/adapters/static/assets/animal-tokenization.bundle.js');

await build({
  entryPoints: [resolve(root, 'src/animal-tokenization.js')],
  bundle: true,
  minify: true,
  legalComments: 'none',
  format: 'esm',
  target: 'es2022',
  outfile: output,
});

const bundle = await readFile(output, 'utf8');
await writeFile(output, `${bundle.split('\n').map((line) => line.trimEnd()).join('\n').trimEnd()}\n`);
