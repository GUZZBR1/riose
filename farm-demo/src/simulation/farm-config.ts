import { MAP_HEIGHT, MAP_WIDTH, PASTURES, TILE_SIZE, WORLD_HEIGHT, WORLD_WIDTH, pastureForAnimal, type PastureZone } from './farm-layout';
import { FARM02_NAVIGATION, farm02PastureForAnimal } from './farm02-navigation';
import { FARM01_NAVIGATION_DEFINITION, type FarmNavigationDefinition } from './navigation';
import type { AnimalBehaviorOptions } from './behavior';

export type FarmId = 'farm01' | 'farm02';

export interface FarmDefinition {
  id: FarmId;
  label: string;
  worldWidth: number;
  worldHeight: number;
  tileSize: number;
  animalCount: number;
  seed: number;
  navigation: FarmNavigationDefinition;
  pastureForAnimal(index: number): PastureZone;
  cattle: 'dairy' | 'nelore';
  behavior: AnimalBehaviorOptions;
}

export const FARM_DEFINITIONS: Record<FarmId, FarmDefinition> = {
  farm01: {
    id: 'farm01',
    label: 'Farm 01',
    worldWidth: WORLD_WIDTH,
    worldHeight: WORLD_HEIGHT,
    tileSize: TILE_SIZE,
    animalCount: 24,
    seed: 0x1978a1,
    navigation: FARM01_NAVIGATION_DEFINITION,
    pastureForAnimal,
    cattle: 'dairy',
    behavior: { minimumTripDistance: 90, walkSpeedMin: 15, walkSpeedMax: 20, interactionChance: 0.08 },
  },
  farm02: {
    id: 'farm02',
    label: 'Farm 02 — Cerrado',
    worldWidth: FARM02_NAVIGATION.worldWidth,
    worldHeight: FARM02_NAVIGATION.worldHeight,
    tileSize: FARM02_NAVIGATION.tileSize,
    animalCount: 24,
    seed: 0x024c3a,
    navigation: FARM02_NAVIGATION,
    pastureForAnimal: farm02PastureForAnimal,
    cattle: 'nelore',
    behavior: {
      minimumTripDistance: 170,
      walkSpeedMin: 13,
      walkSpeedMax: 18,
      interactionChance: 0.2,
      interactionRoles: { 0: 'drink', 12: 'drink', 4: 'shade', 10: 'shade', 16: 'shade', 22: 'shade' },
      interactionDwellMin: 18,
      interactionDwellMax: 30,
    },
  },
};

export function isFarmId(value: unknown): value is FarmId {
  return value === 'farm01' || value === 'farm02';
}

export const FARM01_LAYOUT_SIZE = { width: MAP_WIDTH, height: MAP_HEIGHT } as const;
