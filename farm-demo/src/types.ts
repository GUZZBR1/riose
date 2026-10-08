export type AnimalStatus = 'IDLE' | 'GRAZE' | 'WALK' | 'DRINK' | 'REST' | 'SHADE';

export interface WorldPoint {
  x: number;
  y: number;
}

/** Display-safe state for the client-only farm illustration. */
export interface AnimalState {
  /** Stable client key. This is not an RFID, tag, or product record ID. */
  id: string;
  farmId: 'farm01' | 'farm02';
  index: number;
  label: string;
  status: AnimalStatus;
  zone: string;
  /** Position in the illustrated demo world. */
  estimatedPosition: WorldPoint;
}

export interface FarmDemoCallbacks {
  onSelect?: (animal: AnimalState | null) => void;
  onStates?: (animals: readonly AnimalState[]) => void;
  animalCount?: number;
  farmId?: 'farm01' | 'farm02';
  onReady?: () => void;
}

export interface FarmDemoHandle {
  focusAnimal(id: string): void;
  selectAnimal(id: string | null): void;
  pulseAnimalIdentity(id: string): boolean;
  markAnimalIdentity(id: string, mode: 'pending' | 'preview' | 'confirmed' | 'none'): boolean;
  getAnimalScreenPosition(id: string): { x: number; y: number } | null;
  getAnimals(): readonly AnimalState[];
  setActive(active: boolean): void;
  destroy(): void;
}
