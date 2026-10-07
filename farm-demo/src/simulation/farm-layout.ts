import type { WorldPoint } from '../types';

export const TILE_SIZE = 32;
export const MAP_WIDTH = 48;
export const MAP_HEIGHT = 32;
export const WORLD_WIDTH = MAP_WIDTH * TILE_SIZE;
export const WORLD_HEIGHT = MAP_HEIGHT * TILE_SIZE;

export interface PastureZone {
  name: string;
  bounds: { left: number; top: number; right: number; bottom: number };
  waypoints: readonly WorldPoint[];
  /** Safe interaction point on grass beside a visible trough or pond edge. */
  drinkPoint?: WorldPoint;
}

/** Waypoints follow the illustrated island's clearings, not a visible grid. */
export const PASTURES: readonly PastureZone[] = [
  {
    name: 'Willow meadow',
    bounds: { left: 5, top: 9, right: 20, bottom: 22 },
    waypoints: [point(8, 13), point(10, 11), point(14, 12), point(17, 15), point(16, 18), point(12, 20), point(8, 18)],
    drinkPoint: { x: 650, y: 465 },
  },
  {
    name: 'Long grass',
    bounds: { left: 20, top: 7, right: 39, bottom: 18 },
    waypoints: [point(25, 10), point(29, 8), point(34, 9), point(38, 11), point(36, 14), point(32, 16), point(27, 15)],
    drinkPoint: { x: 720, y: 555 },
  },
  {
    name: 'South meadow',
    bounds: { left: 10, top: 18, right: 28, bottom: 28 },
    waypoints: [point(15, 22), point(18, 20), point(23, 21), point(27, 23), point(25, 26), point(21, 26), point(17, 25)],
    drinkPoint: { x: 420, y: 680 },
  },
  {
    name: 'Creek paddock',
    bounds: { left: 28, top: 17, right: 42, bottom: 28 },
    waypoints: [point(31, 20), point(34, 19), point(39, 20), point(41, 23), point(38, 25), point(34, 25), point(30, 23)],
    drinkPoint: { x: 1224, y: 690 },
  },
];

const HERD_DISTRIBUTION = [0, 1, 1, 0, 2, 1, 0, 1, 3, 1, 0, 2,
  1, 0, 1, 1, 3, 0, 1, 2, 1, 0, 1, 3] as const;

export function point(tileX: number, tileY: number): WorldPoint {
  return { x: (tileX + 0.5) * TILE_SIZE, y: (tileY + 0.5) * TILE_SIZE };
}

export function pastureForAnimal(index: number): PastureZone {
  return PASTURES[HERD_DISTRIBUTION[index % HERD_DISTRIBUTION.length]];
}

export function pastureOrdinal(index: number): number {
  const zone = pastureForAnimal(index);
  let ordinal = 0;
  for (let previous = 0; previous < index; previous += 1) {
    if (pastureForAnimal(previous) === zone) ordinal += 1;
  }
  return ordinal;
}
