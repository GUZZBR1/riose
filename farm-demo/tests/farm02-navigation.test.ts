import assert from 'node:assert/strict';
import test from 'node:test';
import {
  FARM01_NAVIGATION_DEFINITION,
  FarmNavigation,
  type FarmNavigationDefinition,
} from '../src/simulation/navigation';
import { FARM02_NAVIGATION, FARM02_PASTURES, farm02PastureForAnimal } from '../src/simulation/farm02-navigation';

test('the shared navigation API keeps Farm 01 as its default and accepts a distinct Cerrado definition', () => {
  const farm01 = new FarmNavigation();
  const cerradoDefinition: FarmNavigationDefinition = FARM02_NAVIGATION;
  const farm02 = new FarmNavigation(cerradoDefinition);

  assert.equal(farm01.definition, FARM01_NAVIGATION_DEFINITION);
  assert.deepEqual(farm01.getGridSize(), { columns: 96, rows: 64 });
  assert.deepEqual(farm02.getGridSize(), { columns: 112, rows: 72 });
  assert.ok(FARM02_NAVIGATION.worldWidth > FARM01_NAVIGATION_DEFINITION.worldWidth);
  assert.ok(FARM02_NAVIGATION.worldHeight > FARM01_NAVIGATION_DEFINITION.worldHeight);
  assert.ok(farm02.getWalkableCells().length > farm01.getWalkableCells().length);
});

test('Cerrado bounds, water, buildings, handling structures and fences are represented separately from art', () => {
  const navigation = new FarmNavigation(FARM02_NAVIGATION);
  assert.ok(navigation.getWalkableCells().length > 2500, 'the open ranch has broad walkable pasture after zebu clearance erosion');
  assert.equal(navigation.isWalkable(1791, 1151), false, 'outer map corner is beyond the authored island');
  assert.equal(navigation.isWalkable(402, 485), false, 'reservoir is blocked');
  assert.equal(navigation.isWalkable(1300, 350), false, 'utility shed is blocked');
  assert.equal(navigation.isWalkable(1470, 440), false, 'handling race is blocked');
  assert.equal(navigation.isWalkable(1400, 450), false, 'closed corral fence is blocked');
  assert.equal(navigation.isWalkable(1500, 560), false, 'closed south corral fence is blocked');
  assert.equal(navigation.isWalkable(1575, 560), true, 'the authored corral gate remains walkable');
});

test('the explicit Cerrado corral gate connects both sides through a valid A* route', () => {
  const navigation = new FarmNavigation(FARM02_NAVIGATION);
  const inside = { x: 1575, y: 490 };
  const outside = { x: 1575, y: 625 };
  assert.ok(navigation.isWalkable(inside.x, inside.y));
  assert.ok(navigation.isWalkable(outside.x, outside.y));
  const route = navigation.findPath(inside, outside);
  assert.ok(route && route.length > 1, 'the open gate connects the corral to the grazing land');
  for (let index = 1; index < route.length; index += 1) {
    assert.ok(navigation.isWalkableSegment(route[index - 1], route[index]), 'simplified route stays on walkable cells');
  }
  assert.equal(
    navigation.getConnectedRegion(inside),
    navigation.getConnectedRegion(outside),
    'both sides belong to the same reachable terrain region through the gate',
  );
});

test('Cerrado interaction points and pasture sampling targets use walkable reachable cells', () => {
  const navigation = new FarmNavigation(FARM02_NAVIGATION);
  assert.ok(FARM02_PASTURES.length >= 3, 'the ranch exposes multiple authored grazing zones');
  for (const pasture of FARM02_PASTURES) {
    for (const waypoint of pasture.waypoints) {
      assert.ok(navigation.isWalkable(waypoint.x, waypoint.y), `${pasture.name} waypoint ${JSON.stringify(waypoint)} is walkable`);
    }
  }
  for (const interaction of FARM02_NAVIGATION.interactionPoints ?? []) {
    assert.ok(navigation.isWalkable(interaction.point.x, interaction.point.y), `${interaction.label} point is walkable`);
    const route = navigation.findPath(interaction.point, { x: 1575, y: 490 });
    assert.ok(route, `${interaction.label} point reaches the ranch network`);
  }
  for (let index = 0; index < 9; index += 1) {
    const pasture = farm02PastureForAnimal(index);
    assert.ok(FARM02_PASTURES.includes(pasture));
    const spawn = navigation.findSpawn(pasture.bounds, () => 0.37, []);
    assert.ok(spawn, `${pasture.name} has valid spawn cells`);
    assert.ok(navigation.isWalkable(spawn.x, spawn.y));
    const target = navigation.randomTarget(pasture.bounds, () => 0.61, spawn);
    assert.ok(target, `${pasture.name} can sample a reachable destination`);
    assert.ok(navigation.findPath(spawn, target));
  }
});
