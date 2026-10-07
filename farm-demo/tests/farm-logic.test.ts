import assert from 'node:assert/strict';
import test from 'node:test';
import { COW_SEPARATION_RADIUS, HerdController } from '../src/simulation/behavior';
import { MAP_HEIGHT, MAP_WIDTH, PASTURES, WORLD_HEIGHT, WORLD_WIDTH, pastureForAnimal } from '../src/simulation/farm-layout';
import { FarmNavigation } from '../src/simulation/navigation';

test('the authored walkability layer excludes the island edge, pond, barn and closed fences', () => {
  const navigation = new FarmNavigation();
  assert.ok(navigation.getWalkableCells().length > 1000);
  assert.equal(navigation.isWalkable(1500, 800), false, 'outside the grass island');
  assert.equal(navigation.isWalkable(395, 555), false, 'inside the pond');
  assert.equal(navigation.isWalkable(820, 450), false, 'inside the barn footprint');
  assert.equal(navigation.isWalkable(1082, 350), false, 'on a closed fence');
  assert.equal(navigation.isWalkable(1078, 540), true, 'the authored gate opening stays passable');
});

test('A* routes around water and simplifies only across validated walkable segments', () => {
  const navigation = new FarmNavigation();
  const route = navigation.findPath({ x: 180, y: 500 }, { x: 640, y: 555 });
  assert.ok(route && route.length >= 2, 'shore-side endpoints are reachable around the pond');
  for (let index = 0; index < route.length; index += 1) {
    assert.ok(navigation.isWalkable(route[index].x, route[index].y));
    if (index > 0) assert.ok(navigation.isWalkableSegment(route[index - 1], route[index]));
  }
  const penRoute = navigation.findPath({ x: 1080, y: 400 }, { x: 1100, y: 600 });
  assert.ok(penRoute, 'the paddock connects through its authored gate');
  for (let index = 1; index < penRoute.length; index += 1) {
    assert.ok(navigation.isWalkableSegment(penRoute[index - 1], penRoute[index]));
  }
});

test('all 100 deterministic spawns are on safe terrain and have natural spacing', () => {
  const navigation = new FarmNavigation();
  const herd = new HerdController(100, navigation, pastureForAnimal);
  const states = herd.getStates();
  assert.equal(states.length, 100);
  for (const state of states) {
    assert.ok(navigation.isWalkable(state.x, state.y));
    assert.ok(navigation.getConnectedRegionSize(state) >= 30, 'spawn avoids isolated one-cell terrain');
  }
  assertMinimumSpacing(states, COW_SEPARATION_RADIUS - 1);
});

test('targets stay in the cow’s connected walkable region when its pasture is separated', () => {
  const navigation = new FarmNavigation();
  const start = { x: 1300, y: 600 };
  const target = navigation.randomTarget(pastureForAnimal(0).bounds, () => 0.5, start);
  assert.ok(target);
  assert.equal(navigation.getConnectedRegion(start), navigation.getConnectedRegion(target));
  assert.ok(navigation.findPath(start, target));
});

test('movement is deterministic for the same herd and elapsed time', () => {
  const makeTrace = () => {
    const navigation = new FarmNavigation();
    const herd = new HerdController(24, navigation, pastureForAnimal);
    for (let step = 0; step < 300; step += 1) herd.update(50, false);
    return herd.getStates().map(({ status, x, y }) => ({ status, x: Number(x.toFixed(2)), y: Number(y.toFixed(2)) }));
  };
  assert.deepEqual(makeTrace(), makeTrace());
});

test('reduced motion keeps animal positions fixed', () => {
  const navigation = new FarmNavigation();
  const herd = new HerdController(24, navigation, pastureForAnimal);
  const before = herd.getStates();
  for (let step = 0; step < 200; step += 1) herd.update(50, true);
  assert.deepEqual(herd.getStates(), before);
});

test('the demo starts with a mixed herd and autonomous movement', () => {
  const navigation = new FarmNavigation();
  const herd = new HerdController(24, navigation, pastureForAnimal);
  const before = herd.getStates();
  assert.ok(before.some((animal) => animal.status === 'WALK'), 'some cows begin walking');
  assert.ok(before.some((animal) => animal.status === 'GRAZE'), 'some cows begin grazing');
  assert.ok(before.some((animal) => animal.status === 'REST' || animal.status === 'IDLE'), 'some cows begin resting');
  for (let step = 0; step < 20 * 8; step += 1) herd.update(50, false);
  const after = herd.getStates();
  assert.ok(after.some((animal, index) => Math.hypot(animal.x - before[index].x, animal.y - before[index].y) > 1),
    'the world advances without user input');
});

for (const count of [1, 24, 100]) {
  test(`${count} animals remain navigable through ten simulated minutes`, () => {
    const navigation = new FarmNavigation();
    const herd = new HerdController(count, navigation, pastureForAnimal);
    const moved = new Set<number>();
    const stillWalkFrames = new Array<number>(count).fill(0);
    const checkedRoutes = new Map<number, string>();
    let sawWalk = false;
    let sawGraze = false;
    let sawRest = false;

    for (let step = 0; step < 10 * 60 * 20; step += 1) {
      const before = herd.getStates();
      herd.update(50, false);
      const states = herd.getStates();
      for (let index = 0; index < states.length; index += 1) {
        const state = states[index];
        assert.ok(Number.isFinite(state.x) && Number.isFinite(state.y));
        assert.ok(navigation.isWalkable(state.x, state.y), `animal ${index} left safe walkable cells at step ${step}`);
        assert.ok(navigation.isWalkableSegment(before[index], state), `animal ${index} crossed blocked terrain`);
        sawWalk ||= state.status === 'WALK';
        sawGraze ||= state.status === 'GRAZE';
        sawRest ||= state.status === 'REST' || state.status === 'IDLE';
        if (Math.hypot(state.x - before[index].x, state.y - before[index].y) > 0.1) moved.add(index);
        if (state.status === 'WALK') {
          assert.ok(state.target, `walking animal ${index} has a target`);
          assert.ok(state.path.length > 0, `walking animal ${index} has a route`);
          assert.ok(navigation.isWalkable(state.target.x, state.target.y), `animal ${index} target is walkable`);
          assert.equal(navigation.getConnectedRegion(state), navigation.getConnectedRegion(state.target),
            `animal ${index} target left its connected terrain region`);
          const routeKey = JSON.stringify({ target: state.target, path: state.path });
          if (checkedRoutes.get(index) !== routeKey) {
            assert.ok(navigation.findPath({ x: state.x, y: state.y }, state.target),
              `animal ${index} target remains reachable: ${JSON.stringify({ state, targetRegion: navigation.getConnectedRegion(state.target) })}`);
            for (let waypoint = 1; waypoint < state.path.length; waypoint += 1) {
              assert.ok(navigation.isWalkableSegment(state.path[waypoint - 1], state.path[waypoint]),
                `animal ${index} route crosses blocked terrain`);
            }
            checkedRoutes.set(index, routeKey);
          }
          stillWalkFrames[index] = Math.hypot(state.x - before[index].x, state.y - before[index].y) < 0.03
            ? stillWalkFrames[index] + 1 : 0;
          assert.ok(stillWalkFrames[index] <= 50,
            `animal ${index} remained stuck at step ${step}: ${JSON.stringify({ before: before[index], state, still: stillWalkFrames[index] })}`);
        } else {
          stillWalkFrames[index] = 0;
        }
      }
      assertMinimumSpacing(states, COW_SEPARATION_RADIUS - 1);
    }

    assert.ok(sawWalk && sawGraze && sawRest, 'FSM exercised walk, graze and rest states');
    assert.equal(moved.size, count, 'every animal eventually moved');
  });
}

test('navigation dimensions and authored grazing zones remain aligned to the scene', () => {
  assert.deepEqual([MAP_WIDTH * 32, MAP_HEIGHT * 32], [WORLD_WIDTH, WORLD_HEIGHT]);
  assert.equal(PASTURES.length, 4);
  for (let index = 0; index < 100; index += 1) assert.ok(PASTURES.includes(pastureForAnimal(index)));
});

function assertMinimumSpacing(states: readonly { x: number; y: number }[], minimum: number): void {
  const cellSize = minimum;
  const buckets = new Map<string, number[]>();
  states.forEach((state, index) => {
    const cellX = Math.floor(state.x / cellSize);
    const cellY = Math.floor(state.y / cellSize);
    for (let dy = -1; dy <= 1; dy += 1) {
      for (let dx = -1; dx <= 1; dx += 1) {
        for (const otherIndex of buckets.get(`${cellX + dx}:${cellY + dy}`) ?? []) {
          const other = states[otherIndex];
          assert.ok(Math.hypot(state.x - other.x, state.y - other.y) >= minimum,
            `animals ${index} and ${otherIndex} overlapped`);
        }
      }
    }
    const key = `${cellX}:${cellY}`;
    const bucket = buckets.get(key) ?? [];
    bucket.push(index);
    buckets.set(key, bucket);
  });
}
