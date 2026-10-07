export type AnimalStatus = 'IDLE' | 'GRAZE' | 'WALK' | 'DRINK';

export interface WorldPoint {
  x: number;
  y: number;
}

/** Display-safe state for the client-only farm illustration. */
export interface AnimalState {
  /** Stable client key. This is not an RFID, tag, or product record ID. */
  id: string;
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
}

export interface FarmDemoHandle {
  focusAnimal(id: string): void;
  selectAnimal(id: string | null): void;
  getAnimals(): readonly AnimalState[];
  destroy(): void;
}
