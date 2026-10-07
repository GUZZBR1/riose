import type { Anchor, WorldPoint } from '../types';

export const TILE_SIZE = 32;
export const MAP_WIDTH = 48;
export const MAP_HEIGHT = 32;
export const WORLD_WIDTH = MAP_WIDTH * TILE_SIZE;
export const WORLD_HEIGHT = MAP_HEIGHT * TILE_SIZE;

/** Layout aligns to the supplied 48 x 32 tile authored map. */
export const ANCHORS: readonly Anchor[] = [
  { id: 'anchor-northwest', x: 10.5 * TILE_SIZE, y: 8.5 * TILE_SIZE },
  { id: 'anchor-northeast', x: 37.5 * TILE_SIZE, y: 8.5 * TILE_SIZE },
  { id: 'anchor-southwest', x: 10.5 * TILE_SIZE, y: 24.5 * TILE_SIZE },
  { id: 'anchor-southeast', x: 37.5 * TILE_SIZE, y: 24.5 * TILE_SIZE },
];

export interface PastureZone {
  name: string;
  bounds: { left: number; top: number; right: number; bottom: number };
  waypoints: readonly WorldPoint[];
  waterPoint?: WorldPoint;
}

// Named areas and destinations are fixed so repeat visits tell the same story.
export const PASTURES: readonly PastureZone[] = [
  {
    name: 'West pasture',
    bounds: { left: 3, top: 3, right: 20, bottom: 14 },
    waypoints: [point(5, 5), point(9, 5), point(14, 6), point(17, 10), point(12, 12), point(6, 10)],
    waterPoint: point(18, 12),
  },
  {
    name: 'East pasture',
    bounds: { left: 27, top: 3, right: 44, bottom: 14 },
    waypoints: [point(29, 5), point(34, 5), point(41, 6), point(42, 10), point(36, 12), point(30, 10)],
    waterPoint: point(29, 12),
  },
  {
    name: 'South pasture',
    bounds: { left: 5, top: 18, right: 20, bottom: 29 },
    waypoints: [point(6, 20), point(11, 19), point(17, 21), point(18, 26), point(13, 28), point(7, 26)],
    waterPoint: point(18, 19),
  },
  {
    name: 'Lower pasture',
    bounds: { left: 27, top: 18, right: 43, bottom: 29 },
    waypoints: [point(29, 20), point(35, 19), point(41, 21), point(42, 26), point(36, 28), point(30, 26)],
    waterPoint: point(29, 19),
  },
];

export function point(tileX: number, tileY: number): WorldPoint {
  return { x: (tileX + 0.5) * TILE_SIZE, y: (tileY + 0.5) * TILE_SIZE };
}

export function pastureForAnimal(index: number): PastureZone {
  return PASTURES[index % PASTURES.length];
}

export function classifySignal(x: number, y: number): 'strong' | 'moderate' | 'edge' {
  let nearest = Number.POSITIVE_INFINITY;
  for (const anchor of ANCHORS) nearest = Math.min(nearest, Math.hypot(x - anchor.x, y - anchor.y));
  // Broad, qualitative bands are illustrative only; no RF values are generated.
  if (nearest < 310) return 'strong';
  if (nearest < 560) return 'moderate';
  return 'edge';
}
