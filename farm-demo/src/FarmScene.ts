import Phaser from 'phaser';
import { CameraController } from './camera/CameraController';
import { CowEntity } from './entities/CowEntity';
import { FarmEnvironmentLayer } from './environment/FarmEnvironmentLayer';
import { HerdController } from './simulation/behavior';
import { MAP_HEIGHT, MAP_WIDTH, PASTURES, TILE_SIZE, WORLD_HEIGHT, WORLD_WIDTH, pastureForAnimal } from './simulation/farm-layout';
import { FarmNavigation, NAV_CELL_SIZE, NAV_HEIGHT, NAV_WIDTH } from './simulation/navigation';
import type { AnimalState, FarmDemoCallbacks } from './types';

const MAX_ANIMALS = 100;
const STARTING_ANIMALS = 24;
const ANIMALS_STATIONARY = true;

export class FarmScene extends Phaser.Scene {
  private readonly callbacks: FarmDemoCallbacks;
  private readonly requestedAnimalCount: number;
  private cows: CowEntity[] = [];
  private environment!: FarmEnvironmentLayer;
  private navigation!: FarmNavigation;
  private herd!: HerdController;
  private cameraController!: CameraController;
  private navGraphics!: Phaser.GameObjects.Graphics;
  private readonly navigationDebug = isLocalDevelopment() && new URLSearchParams(window.location.search).get('navDebug') === '1';
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
    this.navigation = new FarmNavigation();
    this.herd = new HerdController(this.requestedAnimalCount, this.navigation, pastureForAnimal, ANIMALS_STATIONARY);
    this.cows = Array.from({ length: this.requestedAnimalCount }, (_, index) =>
      new CowEntity(this, index, pastureForAnimal(index), () => this.selectAnimal(`animal-${index}`), this.environment));
    this.navGraphics = this.add.graphics().setDepth(9000).setVisible(this.navigationDebug);

    this.cameraController = new CameraController(this, this.reducedMotion);
    this.input.on('pointerdown', this.clearSelectionOnLandscape, this);
    this.input.keyboard?.on('keydown-ESC', () => this.selectAnimal(null));
    this.input.keyboard?.on('keydown-LEFT', (event: KeyboardEvent) => this.stepSelectionFromKey(event, -1));
    this.input.keyboard?.on('keydown-UP', (event: KeyboardEvent) => this.stepSelectionFromKey(event, -1));
    this.input.keyboard?.on('keydown-RIGHT', (event: KeyboardEvent) => this.stepSelectionFromKey(event, 1));
    this.input.keyboard?.on('keydown-DOWN', (event: KeyboardEvent) => this.stepSelectionFromKey(event, 1));
    this.callbacks.onStates?.(this.getAnimals());
    this.ready = true;
    this.callbacks.onReady?.();
    this.events.emit('farm-ready');
    this.events.once(Phaser.Scenes.Events.SHUTDOWN, this.onShutdown, this);
  }

  update(_time: number, delta: number): void {
    this.herd.update(delta, this.reducedMotion);
    const snapshots = this.herd.getStates(true);
    this.cows.forEach((cow, index) => cow.update(snapshots[index], delta, this.reducedMotion));
    if (this.navigationDebug) this.drawNavigationDebug();
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

  private drawNavigationDebug(): void {
    const graphics = this.navGraphics;
    graphics.clear();
    for (let row = 0; row < NAV_HEIGHT; row += 1) {
      for (let col = 0; col < NAV_WIDTH; col += 1) {
        const point = this.navigation.getCellCenter(col, row);
        graphics.fillStyle(this.navigation.isCellWalkable(col, row) ? 0x6aab6d : 0xd36b59, 0.16);
        graphics.fillRect(point.x - NAV_CELL_SIZE / 2, point.y - NAV_CELL_SIZE / 2, NAV_CELL_SIZE, NAV_CELL_SIZE);
      }
    }
    PASTURES.forEach((pasture, index) => {
      const bounds = pasture.bounds;
      graphics.lineStyle(2, [0x84b7a2, 0x88a7c2, 0xc6a66c, 0xb29bc8][index], 0.7);
      graphics.strokeRect(bounds.left * TILE_SIZE, bounds.top * TILE_SIZE,
        (bounds.right - bounds.left) * TILE_SIZE, (bounds.bottom - bounds.top) * TILE_SIZE);
    });
    for (const state of this.herd.getDebugStates()) {
      graphics.lineStyle(2, 0xeee9bd, 0.8);
      graphics.beginPath();
      graphics.moveTo(state.x, state.y);
      for (const point of state.path) graphics.lineTo(point.x, point.y);
      graphics.strokePath();
      if (state.target) {
        graphics.lineStyle(1, 0xf4c36c, 1);
        graphics.strokeCircle(state.target.x, state.target.y, 8);
      }
      graphics.lineStyle(1, 0x272d24, 0.85);
      graphics.strokeCircle(state.x, state.y, 18);
    }
  }

  private stepSelection(step: number): void {
    if (!this.cows.length) return;
    const current = this.selectedId ? Number(this.selectedId.slice('animal-'.length)) : (step > 0 ? -1 : 0);
    const next = (current + step + this.cows.length) % this.cows.length;
    this.selectAnimal(`animal-${next}`);
  }

  private stepSelectionFromKey(event: KeyboardEvent, step: number): void {
    if (event.repeat) return;
    event.preventDefault();
    this.stepSelection(step);
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
    this.navGraphics?.destroy();
  }
}

function isLocalDevelopment(): boolean {
  return ['localhost', '127.0.0.1', '::1'].includes(window.location.hostname);
}
