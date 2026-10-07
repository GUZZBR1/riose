import assert from 'node:assert/strict';
import test from 'node:test';
import { AnimalBehavior } from '../src/simulation/behavior';
import { ANCHORS, MAP_HEIGHT, MAP_WIDTH, PASTURES, classifySignal, pastureForAnimal, pastureOrdinal } from '../src/simulation/farm-layout';

function traceAnimal(index: number, reducedMotion = false): Array<{ status: string; x: number; y: number }> {
  const behavior = new AnimalBehavior(index, pastureForAnimal(index));
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

test('the scene exposes four pasture zones and four fixed anchors', () => {
  assert.equal(PASTURES.length, 4);
  assert.equal(ANCHORS.length, 4);
  assert.deepEqual([MAP_WIDTH, MAP_HEIGHT], [64, 44]);
  for (let index = 0; index < 100; index += 1) {
    assert.ok(PASTURES.includes(pastureForAnimal(index)));
  }
});

test('signal strength is a qualitative estimate derived from scene anchor distance', () => {
  assert.equal(classifySignal(ANCHORS[0].x, ANCHORS[0].y), 'strong');
  assert.equal(classifySignal(1024, 704), 'moderate');
  assert.equal(classifySignal(-2000, -2000), 'edge');
});

test('herd members start in intentional, staggered clusters within the composed map', () => {
  const positions = Array.from({ length: 100 }, (_, index) => {
    const behavior = new AnimalBehavior(index, pastureForAnimal(index), pastureOrdinal(index));
    return behavior.current;
  });
  assert.ok(positions.every(({ x, y }) => x >= 0 && y >= 0 && x <= MAP_WIDTH * 32 && y <= MAP_HEIGHT * 32));
  assert.ok(new Set(positions.slice(0, 24).map(({ x, y }) => `${Math.round(x)},${Math.round(y)}`)).size > 18);
});
