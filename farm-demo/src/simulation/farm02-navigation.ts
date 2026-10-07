import type { WorldPoint } from '../types';
import type { PastureZone } from './farm-layout';
import type { FarmNavigationDefinition } from './navigation';

const TILE = 32;
const CELL = TILE / 2;
const WIDTH_TILES = 56;
const HEIGHT_TILES = 36;

/**
 * Farm 02's Cerrado navigation is authored independently from its artwork.
 * Coordinates are world pixels; bounds in FARM02_PASTURES use tile coordinates,
 * matching the shared PastureZone contract.
 */
const CERRADO_ISLAND: readonly WorldPoint[] = [
  { x: 118, y: 358 }, { x: 165, y: 270 }, { x: 302, y: 174 },
  { x: 520, y: 126 }, { x: 751, y: 152 }, { x: 1000, y: 130 },
  { x: 1280, y: 178 }, { x: 1516, y: 230 }, { x: 1665, y: 344 },
  { x: 1733, y: 500 }, { x: 1695, y: 677 }, { x: 1610, y: 827 },
  { x: 1460, y: 962 }, { x: 1240, y: 1032 }, { x: 1025, y: 1010 },
  { x: 824, y: 1065 }, { x: 602, y: 1037 }, { x: 405, y: 1077 },
  { x: 230, y: 985 }, { x: 128, y: 827 }, { x: 68, y: 655 },
  { x: 52, y: 493 },
];

/** Fence / hardscape collision geometry; the 90px south corral opening is the gate. */
const CERRADO_BLOCKED: FarmNavigationDefinition['blocked'] = [
  // Reservoir and water point, with walkable bank interactions below.
  { kind: 'ellipse', x: 402, y: 485, rx: 112, ry: 58 },
  { kind: 'ellipse', x: 760, y: 690, rx: 22, ry: 16 }, // ranch water pump
  // Utility shed and handling structures.
  { kind: 'rect', x: 1120, y: 318, width: 278, height: 134 },
  { kind: 'rect', x: 1440, y: 404, width: 50, height: 70 }, // handling race
  // Isolated native tree trunks / rock clusters.
  { kind: 'ellipse', x: 122, y: 264, rx: 25, ry: 19 },
  { kind: 'ellipse', x: 490, y: 248, rx: 23, ry: 18 },
  { kind: 'ellipse', x: 1027, y: 620, rx: 27, ry: 20 },
  { kind: 'ellipse', x: 1388, y: 596, rx: 25, ry: 20 },
  { kind: 'ellipse', x: 1340, y: 92, rx: 28, ry: 19 },
  { kind: 'ellipse', x: 560, y: 788, rx: 24, ry: 18 },
  { kind: 'ellipse', x: 280, y: 641, rx: 26, ry: 18 },
  // Open-air corral beside the utility shed, with a single broad south gate.
  { kind: 'segment', from: { x: 1400, y: 350 }, to: { x: 1680, y: 350 }, radius: 9 },
  { kind: 'segment', from: { x: 1680, y: 350 }, to: { x: 1680, y: 560 }, radius: 9 },
  { kind: 'segment', from: { x: 1680, y: 560 }, to: { x: 1650, y: 560 }, radius: 9 },
  { kind: 'segment', from: { x: 1500, y: 560 }, to: { x: 1400, y: 560 }, radius: 9 },
  { kind: 'segment', from: { x: 1400, y: 560 }, to: { x: 1400, y: 350 }, radius: 9 },
  // Long, broken perimeter lines follow the broad paddock boundaries.
  { kind: 'segment', from: { x: 240, y: 880 }, to: { x: 580, y: 905 }, radius: 7 },
  { kind: 'segment', from: { x: 365, y: 420 }, to: { x: 790, y: 385 }, radius: 7 },
];

export const FARM02_NAVIGATION: FarmNavigationDefinition = {
  worldWidth: WIDTH_TILES * TILE,
  worldHeight: HEIGHT_TILES * TILE,
  tileSize: TILE,
  cellSize: CELL,
  islandWalkable: CERRADO_ISLAND,
  blocked: CERRADO_BLOCKED,
  // The zebu sprite has a broader silhouette; inset more than the dairy field
  // so the displayed body and shadow stay visibly inside the irregular island.
  cowFootprintRadius: 44,
  minRegionCells: 40,
  gates: [{ x: 1575, y: 560 }],
  interactionPoints: [
    { kind: 'drink', point: { x: 580, y: 485 }, label: 'reservoir bank' },
    { kind: 'drink', point: { x: 835, y: 690 }, label: 'well-side water point' },
    { kind: 'shade', point: { x: 550, y: 330 }, label: 'north shade tree' },
    { kind: 'shade', point: { x: 960, y: 548 }, label: 'central shade tree' },
    { kind: 'rest', point: { x: 1010, y: 820 }, label: 'open pasture rest point' },
  ],
};

/** Broad authored grazing zones; the southern fence leaves an explicit gate gap. */
export const FARM02_PASTURES: readonly PastureZone[] = [
  {
    name: 'North range',
    bounds: { left: 5, top: 6, right: 34, bottom: 24 },
    waypoints: [{ x: 580, y: 660 }, { x: 700, y: 500 }, { x: 850, y: 620 }, { x: 500, y: 600 }],
    drinkPoint: { x: 580, y: 485 },
  },
  {
    name: 'Central range',
    bounds: { left: 22, top: 7, right: 50, bottom: 30 },
    waypoints: [{ x: 850, y: 350 }, { x: 1210, y: 540 }, { x: 1460, y: 830 }, { x: 1080, y: 910 }],
    drinkPoint: { x: 580, y: 485 },
  },
  {
    name: 'South range',
    bounds: { left: 5, top: 20, right: 36, bottom: 33 },
    waypoints: [{ x: 430, y: 740 }, { x: 690, y: 960 }, { x: 960, y: 940 }, { x: 650, y: 980 }],
    drinkPoint: { x: 580, y: 485 },
  },
];

export function farm02PastureForAnimal(index: number): PastureZone {
  return FARM02_PASTURES[index % FARM02_PASTURES.length];
}
