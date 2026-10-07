import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('../src/api.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText;
const api = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);

function snapshot(count = 100) {
  const animals = Array.from({ length: count }, (_, index) => ({
    animal_id: `cow-${index + 1}`,
    hardware_id: `tag-${String(index + 1).padStart(4, '0')}`,
    name: `Cow ${index + 1}`,
  }));
  return {
    type: 'snapshot',
    simulation: {
      status: 'playing', time_s: 10, start_s: 0, end_s: 300, speed: 5,
      run_id: 'demo-run', evidence: 'SIMULATED',
    },
    animals,
    positions: [],
    scene_positions: animals.map((animal, index) => ({
      timestamp: 10,
      tag_id: animal.hardware_id,
      x: 20 + index,
      y: 30 + index,
    })),
    anchors: Array.from({ length: 8 }, (_, index) => ({
      anchor_id: `anchor-${index + 1}`, x: index, y: index, height_m: 2,
      kind: 'receiver', enabled: true,
    })),
    telemetry: [],
    events: [],
    metrics: { farm: { width_m: 1000, height_m: 1000 } },
    evidence: 'SIMULATED',
  };
}

test('accepts the configured herd with finite simulator positions and anchors', () => {
  const parsed = api.validateFarmSnapshot(snapshot());
  assert.ok(parsed);
  assert.equal(parsed.snapshot.animals.length, 100);
  assert.equal(parsed.snapshot.scene_positions.length, 100);
  assert.equal(parsed.snapshot.anchors.length, 8);
  assert.ok(parsed.snapshot.scene_positions.every((pose) => Number.isFinite(pose.x) && Number.isFinite(pose.y)));
  assert.deepEqual(parsed.issues, []);
});

test('rejects only the invalid position record and reports its identity and reason', () => {
  const payload = snapshot();
  payload.scene_positions[0].x = Number.NaN;
  const parsed = api.validateFarmSnapshot(payload);
  assert.ok(parsed);
  assert.equal(parsed.snapshot.animals.length, 100);
  assert.equal(parsed.snapshot.scene_positions.length, 99);
  assert.match(parsed.issues[0], /scene_positions\[0\] id=tag-0001: simulator x\/y must both be finite numbers/);
});

test('rejects an invalid top-level payload instead of treating it as a ready snapshot', () => {
  assert.equal(api.validateFarmSnapshot({ ...snapshot(), type: 'unexpected' }), null);
});
