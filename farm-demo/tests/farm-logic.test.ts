import assert from 'node:assert/strict';
import test from 'node:test';
import { AnimalBehavior } from '../src/simulation/behavior';
import { MAP_HEIGHT, MAP_WIDTH, PASTURES, pastureForAnimal, pastureOrdinal } from '../src/simulation/farm-layout';

function traceAnimal(index: number, reducedMotion = false): Array<{ status: string; x: number; y: number }> {
  const behavior = new AnimalBehavior(index, pastureForAnimal(index), pastureOrdinal(index));
  const trace = [];
  for (let step = 0; step < 800; step += 1) {
    const state = behavior.update(50, reducedMotion);
    trace.push({ status: state.status, x: Number(state.x.toFixed(3)), y: Number(state.y.toFixed(3)) });
  }
  return trace;
}

test('the same animal follows the same movement and state sequence on every visit', () => {
  assert.deepEqual(traceAnimal(7), traceAnimal(7));
});

test('animals use staggered state schedules instead of moving in sync', () => {
  assert.notDeepEqual(traceAnimal(0), traceAnimal(1));
  for (const index of [0, 1, 7, 23, 99]) {
    const states = new Set(traceAnimal(index).map((step) => step.status));
    assert.ok(states.has('WALK'));
    assert.ok(states.has('GRAZE'));
  }
});

test('reduced motion freezes each animal at its deterministic starting position', () => {
  const first = traceAnimal(4, true);
  assert.ok(first.every((sample) => sample.x === first[0].x && sample.y === first[0].y));
});

test('the isometric diorama has four named meadow routes and room for 100 animals', () => {
  assert.equal(PASTURES.length, 4);
  assert.deepEqual([MAP_WIDTH * 32, MAP_HEIGHT * 32], [1536, 1024]);
  for (let index = 0; index < 100; index += 1) {
    assert.ok(PASTURES.includes(pastureForAnimal(index)));
  }
});

test('herd members start in intentional staggered clusters within the scene', () => {
  const positions = Array.from({ length: 100 }, (_, index) => {
    const behavior = new AnimalBehavior(index, pastureForAnimal(index), pastureOrdinal(index));
    return behavior.current;
  });
  assert.ok(positions.every(({ x, y }) => x >= 0 && y >= 0 && x <= MAP_WIDTH * 32 && y <= MAP_HEIGHT * 32));
  assert.ok(new Set(positions.slice(0, 24).map(({ x, y }) => `${Math.round(x)},${Math.round(y)}`)).size > 18);
});
