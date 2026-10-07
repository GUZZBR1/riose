import type { Anchor, WorldPoint } from '../types';

export const TILE_SIZE = 32;
export const MAP_WIDTH = 64;
export const MAP_HEIGHT = 44;
export const WORLD_WIDTH = MAP_WIDTH * TILE_SIZE;
export const WORLD_HEIGHT = MAP_HEIGHT * TILE_SIZE;

/** Layout aligns to the supplied 48 x 32 tile authored map. */
export const ANCHORS: readonly Anchor[] = [
  { id: 'anchor-willow', x: 17.5 * TILE_SIZE, y: 8.5 * TILE_SIZE },
  { id: 'anchor-east-field', x: 51.5 * TILE_SIZE, y: 10.5 * TILE_SIZE },
  { id: 'anchor-south-meadow', x: 15.5 * TILE_SIZE, y: 36.5 * TILE_SIZE },
  { id: 'anchor-creek', x: 49.5 * TILE_SIZE, y: 36.5 * TILE_SIZE },
];

export interface PastureZone {
  name: string;
  bounds: { left: number; top: number; right: number; bottom: number };
  waypoints: readonly WorldPoint[];
  waterPoint?: WorldPoint;
}

// Uneven paddock sizes and waypoint rhythms make the herd feel gathered in places.
export const PASTURES: readonly PastureZone[] = [
  {
    name: 'Willow meadow',
    bounds: { left: 4, top: 11, right: 21, bottom: 29 },
    waypoints: [point(7, 17), point(9, 14), point(14, 14), point(18, 18), point(18, 22), point(15, 26), point(10, 26), point(7, 22)],
    waterPoint: point(18, 22),
  },
  {
    name: 'Long grass',
    bounds: { left: 29, top: 7, right: 57, bottom: 25 },
    waypoints: [point(33, 12), point(38, 10), point(44, 11), point(51, 13), point(53, 17), point(48, 22), point(41, 21), point(34, 18)],
    waterPoint: point(52, 19),
  },
  {
    name: 'South meadow',
    bounds: { left: 18, top: 28, right: 37, bottom: 41 },
    waypoints: [point(22, 32), point(26, 30), point(31, 31), point(34, 35), point(32, 38), point(27, 38), point(22, 35)],
    waterPoint: point(33, 36),
  },
  {
    name: 'Creek paddock',
    bounds: { left: 40, top: 26, right: 57, bottom: 39 },
    waypoints: [point(44, 29), point(48, 28), point(53, 31), point(53, 35), point(50, 37), point(45, 35), point(42, 32)],
    waterPoint: point(54, 34),
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

export function classifySignal(x: number, y: number): 'strong' | 'moderate' | 'edge' {
  let nearest = Number.POSITIVE_INFINITY;
  for (const anchor of ANCHORS) nearest = Math.min(nearest, Math.hypot(x - anchor.x, y - anchor.y));
  // Broad, qualitative bands are illustrative only; no RF values are generated.
  if (nearest < 420) return 'strong';
  if (nearest < 760) return 'moderate';
  return 'edge';
}
