export type FarmMode = 'overview' | 'signals' | 'coverage' | 'track';
export type AnimalStatus = 'IDLE' | 'GRAZE' | 'WALK' | 'DRINK';
export type SignalLevel = 'strong' | 'moderate' | 'edge';

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
  /** Estimated map coordinate in world pixels, not a physical measurement. */
  estimatedPosition: WorldPoint;
  /** Deterministic visual estimate relative to the demo's anchor layout. */
  signalLevel: SignalLevel;
}

export interface FarmDemoCallbacks {
  onSelect?: (animal: AnimalState | null) => void;
  onStates?: (animals: readonly AnimalState[]) => void;
  animalCount?: number;
}

export interface FarmDemoHandle {
  setMode(mode: FarmMode): void;
  focusAnimal(id: string): void;
  selectAnimal(id: string | null): void;
  resetView(): void;
  zoomBy(factor: number): void;
  getAnimals(): readonly AnimalState[];
  destroy(): void;
}

export interface Anchor {
  id: string;
  x: number;
  y: number;
}
