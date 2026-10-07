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
  waterPoint?: WorldPoint;
}

/** Waypoints follow the illustrated island's clearings, not a visible grid. */
export const PASTURES: readonly PastureZone[] = [
  {
    name: 'Willow meadow',
    bounds: { left: 6, top: 10, right: 19, bottom: 21 },
    waypoints: [point(8, 13), point(10, 11), point(14, 12), point(17, 15), point(16, 18), point(12, 20), point(8, 18)],
    waterPoint: point(11, 17),
  },
  {
    name: 'Long grass',
    bounds: { left: 23, top: 7, right: 39, bottom: 17 },
    waypoints: [point(25, 10), point(29, 8), point(34, 9), point(38, 11), point(36, 14), point(32, 16), point(27, 15)],
    waterPoint: point(35, 13),
  },
  {
    name: 'South meadow',
    bounds: { left: 13, top: 19, right: 28, bottom: 27 },
    waypoints: [point(15, 22), point(18, 20), point(23, 21), point(27, 23), point(25, 26), point(21, 26), point(17, 25)],
    waterPoint: point(25, 24),
  },
  {
    name: 'Creek paddock',
    bounds: { left: 29, top: 18, right: 42, bottom: 26 },
    waypoints: [point(31, 20), point(34, 19), point(39, 20), point(41, 23), point(38, 25), point(34, 25), point(30, 23)],
    waterPoint: point(39, 22),
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
