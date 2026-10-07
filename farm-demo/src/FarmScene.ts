import Phaser from 'phaser';
import { CameraController } from './camera/CameraController';
import { CowEntity } from './entities/CowEntity';
import { FarmEnvironmentLayer } from './environment/FarmEnvironmentLayer';
import { pastureForAnimal } from './simulation/farm-layout';
import type { AnimalState, FarmDemoCallbacks } from './types';

const MAX_ANIMALS = 100;
const STARTING_ANIMALS = 24;

export class FarmScene extends Phaser.Scene {
  private readonly callbacks: FarmDemoCallbacks;
  private readonly requestedAnimalCount: number;
  private cows: CowEntity[] = [];
  private environment!: FarmEnvironmentLayer;
  private cameraController!: CameraController;
  private selectedId: string | null = null;
  private reducedMotion = false;
  private statePublishElapsed = 0;
  ready = false;

  constructor(callbacks: FarmDemoCallbacks, animalCount = STARTING_ANIMALS) {
    super('RioseFarmScene');
    this.callbacks = callbacks;
    this.requestedAnimalCount = Phaser.Math.Clamp(Math.floor(animalCount), 1, MAX_ANIMALS);
  }

  preload(): void { FarmEnvironmentLayer.preload(this); }

  create(): void {
    this.reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
    this.cameras.main.setBackgroundColor('rgba(0,0,0,0)');
    this.environment = new FarmEnvironmentLayer(this);
    this.environment.create();
    this.cows = Array.from({ length: this.requestedAnimalCount }, (_, index) =>
      new CowEntity(this, index, pastureForAnimal(index), () => this.selectAnimal(`animal-${index}`), this.environment));

    this.cameraController = new CameraController(this, this.reducedMotion);
    this.input.on('pointerdown', this.clearSelectionOnLandscape, this);
    this.input.keyboard?.on('keydown-ESC', () => this.selectAnimal(null));
    this.input.keyboard?.on('keydown-LEFT', () => this.stepSelection(-1));
    this.input.keyboard?.on('keydown-UP', () => this.stepSelection(-1));
    this.input.keyboard?.on('keydown-RIGHT', () => this.stepSelection(1));
    this.input.keyboard?.on('keydown-DOWN', () => this.stepSelection(1));
    this.callbacks.onStates?.(this.getAnimals());
    this.ready = true;
    this.events.emit('farm-ready');
    this.events.once(Phaser.Scenes.Events.SHUTDOWN, this.onShutdown, this);
  }

  update(_time: number, delta: number): void {
    for (const cow of this.cows) cow.update(delta, this.reducedMotion);
    this.cameraController.update(delta);
    this.statePublishElapsed += delta;
    if (this.statePublishElapsed >= 500) {
      this.statePublishElapsed %= 500;
      this.callbacks.onStates?.(this.getAnimals());
    }
  }

  selectAnimal(id: string | null): void {
    const selected = id ? this.cowById(id) : undefined;
    if (id && !selected) return;
    this.selectedId = selected ? id : null;
    for (const cow of this.cows) cow.setSelected(cow === selected);
    const state = selected?.getState() ?? null;
    this.callbacks.onSelect?.(state);
    if (state) this.cameraController.focus(state.estimatedPosition.x, state.estimatedPosition.y);
  }

  focusAnimal(id: string): void {
    const cow = this.cowById(id);
    if (!cow) return;
    const { x, y } = cow.getState().estimatedPosition;
    this.cameraController.focus(x, y);
  }

  getAnimals(): readonly AnimalState[] { return this.cows.map((cow) => cow.getState()); }

  private stepSelection(step: number): void {
    if (!this.cows.length) return;
    const current = this.selectedId ? Number(this.selectedId.slice('animal-'.length)) : (step > 0 ? -1 : 0);
    const next = (current + step + this.cows.length) % this.cows.length;
    this.selectAnimal(`animal-${next}`);
  }

  private clearSelectionOnLandscape(pointer: Phaser.Input.Pointer): void {
    const hits = this.input.hitTestPointer(pointer);
    if (!hits.some((object) => object.getData('farmCow') === true)) this.selectAnimal(null);
  }

  private cowById(id: string): CowEntity | undefined {
    const index = Number(id.slice('animal-'.length));
    return Number.isInteger(index) && index >= 0 && index < this.cows.length ? this.cows[index] : undefined;
  }

  private onShutdown(): void {
    this.input.off('pointerdown', this.clearSelectionOnLandscape, this);
    this.cameraController?.destroy();
    this.cows.forEach((cow) => cow.destroy());
    this.environment?.destroy();
  }
}
