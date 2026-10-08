import Phaser from 'phaser';
import { CameraController } from './camera/CameraController';
import { CowEntity } from './entities/CowEntity';
import { FarmEnvironmentLayer } from './environment/FarmEnvironmentLayer';
import { HerdController } from './simulation/behavior';
import { FarmNavigation } from './simulation/navigation';
import type { FarmDefinition } from './simulation/farm-config';
import type { AnimalState, FarmDemoCallbacks } from './types';

const MAX_ANIMALS = 100;
const STARTING_ANIMALS = 24;
export class FarmScene extends Phaser.Scene {
  private readonly callbacks: FarmDemoCallbacks;
  private readonly definition: FarmDefinition;
  private readonly requestedAnimalCount: number;
  private cows: CowEntity[] = [];
  private environment!: FarmEnvironmentLayer;
  private navigation!: FarmNavigation;
  private herd!: HerdController;
  private cameraController!: CameraController;
  private navGraphics!: Phaser.GameObjects.Graphics;
  private readonly navigationDebug = isLocalDevelopment() && new URLSearchParams(window.location.search).get('navDebug') === '1';
  private readonly farmDragDebug = isLocalDevelopment() && new URLSearchParams(window.location.search).get('farmDragDebug') === '1';
  private selectedId: string | null = null;
  private reducedMotion = false;
  private statePublishElapsed = 0;
  private pendingAnimalDrag: {
    index: number;
    startX: number;
    startY: number;
    offsetX: number;
    offsetY: number;
    dragging: boolean;
  } | null = null;
  ready = false;

  constructor(callbacks: FarmDemoCallbacks, definition: FarmDefinition, animalCount = STARTING_ANIMALS) {
    super('RioseFarmScene');
    this.callbacks = callbacks;
    this.definition = definition;
    this.requestedAnimalCount = Phaser.Math.Clamp(Math.floor(animalCount), 1, MAX_ANIMALS);
  }

  preload(): void { FarmEnvironmentLayer.preload(this, this.definition.id); }

  create(): void {
    this.reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
    this.cameras.main.setBackgroundColor('rgba(0,0,0,0)');
    this.environment = new FarmEnvironmentLayer(this, this.definition.id,
      this.definition.worldWidth, this.definition.worldHeight);
    this.cameraController = new CameraController(this, this.reducedMotion,
      this.definition.worldWidth, this.definition.worldHeight);
    this.events.once(Phaser.Scenes.Events.SHUTDOWN, this.onShutdown, this);
    this.environment.create(() => this.initializeFarm());
  }

  private initializeFarm(): void {
    this.navigation = new FarmNavigation(this.definition.navigation);
    this.herd = new HerdController(this.requestedAnimalCount, this.navigation, this.definition.pastureForAnimal,
      false, { ...this.definition.behavior, seed: this.definition.seed });
    this.cows = Array.from({ length: this.requestedAnimalCount }, (_, index) =>
      new CowEntity(this, index, this.definition.pastureForAnimal(index),
        (pointer) => this.onCowPointerDown(index, pointer), this.environment, this.definition.id));
    this.navGraphics = this.add.graphics().setDepth(9000).setVisible(this.navigationDebug);

    this.input.on('pointerdown', this.clearSelectionOnLandscape, this);
    this.input.on('pointermove', this.moveAnimalFromPointer, this);
    this.input.on('pointerup', this.finishAnimalDrag, this);
    this.input.on('pointerupoutside', this.finishAnimalDrag, this);
    this.input.keyboard?.on('keydown-ESC', () => this.selectAnimal(null));
    this.input.keyboard?.on('keydown-LEFT', (event: KeyboardEvent) => this.stepSelectionFromKey(event, -1));
    this.input.keyboard?.on('keydown-UP', (event: KeyboardEvent) => this.stepSelectionFromKey(event, -1));
    this.input.keyboard?.on('keydown-RIGHT', (event: KeyboardEvent) => this.stepSelectionFromKey(event, 1));
    this.input.keyboard?.on('keydown-DOWN', (event: KeyboardEvent) => this.stepSelectionFromKey(event, 1));
    this.callbacks.onStates?.(this.getAnimals());
    this.ready = true;
    this.callbacks.onReady?.();
    this.events.emit('farm-ready');
  }

  update(_time: number, delta: number): void {
    if (!this.ready) return;
    this.herd.update(delta, this.reducedMotion);
    const snapshots = this.herd.getStates(true);
    this.cows.forEach((cow, index) => cow.update(snapshots[index], delta, this.reducedMotion));
    if (this.navigationDebug) this.drawNavigationDebug();
    this.cameraController.update(delta);
    this.statePublishElapsed += delta;
    if (this.statePublishElapsed >= 500) {
      this.statePublishElapsed %= 500;
      const animals = this.getAnimals();
      if (this.farmDragDebug) {
        const host = this.game.canvas.parentElement;
        const camera = this.cameras.main;
        host?.setAttribute('data-farm-drag-state', JSON.stringify({
          animals: snapshots.map(({ x, y }) => {
            // Phaser renders world points relative to camera scroll and origin.
            return {
              x,
              y,
              screenX: camera.x + camera.width * camera.originX * (1 - camera.zoom) + (x - camera.scrollX) * camera.zoom,
              screenY: camera.y + camera.height * camera.originY * (1 - camera.zoom) + (y - 20 - camera.scrollY) * camera.zoom,
            };
          }),
        }));
      }
      this.callbacks.onStates?.(animals);
    }
  }

  selectAnimal(id: string | null): void {
    this.setSelectedAnimal(id, true);
  }

  private setSelectedAnimal(id: string | null, focus: boolean): void {
    const selected = id ? this.cowById(id) : undefined;
    if (id && !selected) return;
    this.selectedId = selected ? id : null;
    for (const cow of this.cows) cow.setSelected(cow === selected);
    const state = selected?.getState() ?? null;
    this.callbacks.onSelect?.(state);
    if (state && focus) this.cameraController.focus(state.estimatedPosition.x, state.estimatedPosition.y);
    else this.cameraController.cancelFocus();
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
    const { columns, rows } = this.navigation.getGridSize();
    const cellSize = this.definition.navigation.cellSize;
    for (let row = 0; row < rows; row += 1) {
      for (let col = 0; col < columns; col += 1) {
        const point = this.navigation.getCellCenter(col, row);
        graphics.fillStyle(this.navigation.isCellWalkable(col, row) ? 0x6aab6d : 0xd36b59, 0.16);
        graphics.fillRect(point.x - cellSize / 2, point.y - cellSize / 2, cellSize, cellSize);
      }
    }
    Array.from({ length: 3 }, (_, index) => this.definition.pastureForAnimal(index)).forEach((pasture, index) => {
      const bounds = pasture.bounds;
      const tile = this.definition.tileSize;
      graphics.lineStyle(2, [0x84b7a2, 0x88a7c2, 0xc6a66c, 0xb29bc8][index % 4], 0.7);
      graphics.strokeRect(bounds.left * tile, bounds.top * tile,
        (bounds.right - bounds.left) * tile, (bounds.bottom - bounds.top) * tile);
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
    const current = this.selectedId ? this.cowById(this.selectedId)?.index ?? -1 : (step > 0 ? -1 : 0);
    const next = (current + step + this.cows.length) % this.cows.length;
    this.selectAnimal(`${this.definition.id}-animal-${next}`);
  }

  private stepSelectionFromKey(event: KeyboardEvent, step: number): void {
    if (event.repeat) return;
    event.preventDefault();
    this.stepSelection(step);
  }

  private onCowPointerDown(index: number, pointer: Phaser.Input.Pointer): void {
    const id = `${this.definition.id}-animal-${index}`;
    const event = pointer.event;
    if (!(event instanceof MouseEvent) || pointer.button !== 0) {
      this.pendingAnimalDrag = null;
      this.setSelectedAnimal(id, true);
      return;
    }
    this.pendingAnimalDrag = {
      index,
      startX: event.clientX,
      startY: event.clientY,
      offsetX: 0,
      offsetY: 0,
      dragging: false,
    };
  }

  private moveAnimalFromPointer(pointer: Phaser.Input.Pointer): void {
    const drag = this.pendingAnimalDrag;
    if (!drag || !pointer.isDown) return;
    const event = pointer.event as MouseEvent;
    if (!drag.dragging) {
      const distance = Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY);
      if (distance < 6) return;
      drag.dragging = this.herd.beginManualMove(drag.index);
      if (!drag.dragging) return;
      this.selectedId = `${this.definition.id}-animal-${drag.index}`;
      this.cows.forEach((cow, index) => cow.setSelected(index === drag.index));
      this.cows[drag.index].setDragging(true);
      this.cameraController.cancelFocus();
      const position = this.herd.getStates()[drag.index];
      drag.offsetX = position.x - pointer.worldX;
      drag.offsetY = position.y - pointer.worldY;
    }
    this.herd.moveManualAnimal(drag.index, {
      x: pointer.worldX + drag.offsetX,
      y: pointer.worldY + drag.offsetY,
    });
  }

  private finishAnimalDrag(): void {
    const drag = this.pendingAnimalDrag;
    if (!drag) return;
    this.pendingAnimalDrag = null;
    if (drag.dragging) {
      this.herd.endManualMove(drag.index);
      this.cows[drag.index]?.setDragging(false);
      this.setSelectedAnimal(`${this.definition.id}-animal-${drag.index}`, false);
      this.callbacks.onStates?.(this.getAnimals());
      return;
    }
    this.setSelectedAnimal(`${this.definition.id}-animal-${drag.index}`, true);
  }

  private clearSelectionOnLandscape(pointer: Phaser.Input.Pointer): void {
    const hits = this.input.hitTestPointer(pointer);
    if (!hits.some((object) => object.getData('farmCow') === true)) this.selectAnimal(null);
  }

  private cowById(id: string): CowEntity | undefined {
    const prefix = `${this.definition.id}-animal-`;
    if (!id.startsWith(prefix)) return undefined;
    const index = Number(id.slice(prefix.length));
    return Number.isInteger(index) && index >= 0 && index < this.cows.length ? this.cows[index] : undefined;
  }

  private onShutdown(): void {
    this.input.off('pointerdown', this.clearSelectionOnLandscape, this);
    this.input.off('pointermove', this.moveAnimalFromPointer, this);
    this.input.off('pointerup', this.finishAnimalDrag, this);
    this.input.off('pointerupoutside', this.finishAnimalDrag, this);
    this.cameraController?.destroy();
    this.cows.forEach((cow) => cow.destroy());
    this.environment?.destroy();
    this.navGraphics?.destroy();
  }
}

function isLocalDevelopment(): boolean {
  return ['localhost', '127.0.0.1', '::1'].includes(window.location.hostname);
}
