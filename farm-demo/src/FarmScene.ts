import Phaser from 'phaser';
import { CameraController } from './camera/CameraController';
import { CowEntity } from './entities/CowEntity';
import { ANCHORS, WORLD_HEIGHT, WORLD_WIDTH, pastureForAnimal } from './simulation/farm-layout';
import type { AnimalState, FarmDemoCallbacks, FarmMode } from './types';

const FARM_MAP = '/assets/farm-demo/farm-map.json';
const FARM_TILES = '/assets/farm-demo/farm-tiles.png';
const CATTLE_ATLAS = '/assets/farm-demo/cattle-atlas.png';
const FARM_DIORAMA = '/assets/farm-demo/diorama.png';
const MAX_ANIMALS = 100;
const STARTING_ANIMALS = 24;

export class FarmScene extends Phaser.Scene {
  private readonly callbacks: FarmDemoCallbacks;
  private readonly requestedAnimalCount: number;
  private cows: CowEntity[] = [];
  private anchors: Phaser.GameObjects.Container[] = [];
  private ambience: Phaser.GameObjects.GameObject[] = [];
  private mode: FarmMode = 'overview';
  private selectedId: string | null = null;
  private cameraController!: CameraController;
  private tilemap!: Phaser.Tilemaps.Tilemap;
  private modeGraphics!: Phaser.GameObjects.Graphics;
  private reducedMotion = false;
  private statePublishElapsed = 0;
  ready = false;

  constructor(callbacks: FarmDemoCallbacks, animalCount = STARTING_ANIMALS) {
    super('RioseFarmScene');
    this.callbacks = callbacks;
    this.requestedAnimalCount = Phaser.Math.Clamp(Math.floor(animalCount), 1, MAX_ANIMALS);
  }

  preload(): void {
    this.load.tilemapTiledJSON('farm-map', FARM_MAP);
    this.load.image('farm-tiles', FARM_TILES);
    this.load.spritesheet('cattle-atlas', CATTLE_ATLAS, { frameWidth: 32, frameHeight: 32 });
    this.load.image('farm-diorama', FARM_DIORAMA);
  }

  create(): void {
    this.reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
    this.cameras.main.setBackgroundColor('#91a975');
    this.renderTilemap();
    this.add.image(0, 0, 'farm-diorama').setOrigin(0, 0).setDepth(40);
    this.addPondGlimmers(285, 220);
    this.addChimneyBreath(972, 266);
    this.createAnchorNodes();
    this.modeGraphics = this.add.graphics().setDepth(9000);
    this.cows = Array.from({ length: this.requestedAnimalCount }, (_, index) => {
      const cow = new CowEntity(this, index, pastureForAnimal(index), () => this.selectAnimal(`animal-${index}`));
      return cow;
    });
    this.cameraController = new CameraController(this, this.reducedMotion);
    this.input.keyboard?.on('keydown-ESC', () => this.selectAnimal(null));
    this.callbacks.onStates?.(this.getAnimals());
    this.ready = true;
    this.events.emit('farm-ready');
    this.events.once(Phaser.Scenes.Events.SHUTDOWN, this.onShutdown, this);
  }

  update(_time: number, delta: number): void {
    for (const cow of this.cows) cow.update(delta, this.reducedMotion);
    if (this.mode === 'track' && this.selectedId) {
      const tracked = this.cowById(this.selectedId);
      if (tracked) this.cameraController.focus(tracked.getState().estimatedPosition.x, tracked.getState().estimatedPosition.y);
    }
    this.cameraController.update(delta);
    this.drawModeOverlay();
    this.statePublishElapsed += delta;
    if (this.statePublishElapsed >= 500) {
      this.statePublishElapsed %= 500;
      this.callbacks.onStates?.(this.getAnimals());
    }
  }

  setMode(mode: FarmMode): void {
    this.mode = mode;
    if (mode === 'overview') this.cameraController?.setOverview();
    if (mode === 'track' && this.selectedId) this.focusAnimal(this.selectedId);
  }

  selectAnimal(id: string | null): void {
    const selected = id ? this.cowById(id) : undefined;
    if (id && !selected) return;
    this.selectedId = selected ? id : null;
    for (const cow of this.cows) cow.setSelected(cow === selected);
    this.callbacks.onSelect?.(selected?.getState() ?? null);
    if (selected && this.mode === 'track') this.focusAnimal(selected.getState().id);
  }

  focusAnimal(id: string): void {
    const cow = this.cowById(id);
    if (!cow) return;
    const { x, y } = cow.getState().estimatedPosition;
    this.cameraController.focus(x, y);
  }

  resetView(): void {
    this.selectedId = null;
    this.mode = 'overview';
    for (const cow of this.cows) cow.setSelected(false);
    this.callbacks.onSelect?.(null);
    this.cameraController.reset();
  }

  zoomBy(factor: number): void {
    this.cameraController.zoomBy(factor);
  }

  getAnimals(): readonly AnimalState[] { return this.cows.map((cow) => cow.getState()); }

  private renderTilemap(): void {
    const map = this.tilemap = this.make.tilemap({ key: 'farm-map' });
    const tilesets = map.tilesets.map((tileSet) => map.addTilesetImage(
      tileSet.name,
      'farm-tiles',
      tileSet.tileWidth || 32,
      tileSet.tileHeight || 32,
      tileSet.tileMargin,
      tileSet.tileSpacing,
      tileSet.firstgid,
    )).filter((tileset): tileset is Phaser.Tilemaps.Tileset => Boolean(tileset));

    let depth = 0;
    for (const layerName of ['ground']) {
      if (!tilesets.length) continue;
      const layer = map.createLayer(layerName, tilesets, 0, 0);
      layer?.setDepth(depth++ * 10);
      layer?.setCullPadding(2, 2);
    }
    this.add.rectangle(WORLD_WIDTH / 2, WORLD_HEIGHT / 2, WORLD_WIDTH, WORLD_HEIGHT, 0x789465)
      .setDepth(-1);
  }

  private addPondGlimmers(x: number, y: number): void {
    const points = [[-40, -5], [8, -27], [45, 20]];
    points.forEach(([dx, dy], index) => {
      const glimmer = this.add.rectangle(x + dx, y + dy, 9 + (index % 2) * 4, 2, 0xd6e4a4, 0.55)
        .setDepth(y + 30 + index);
      if (!this.reducedMotion) {
        this.tweens.add({ targets: glimmer, alpha: 0.12, scaleX: 0.55,
          duration: 1500 + index * 430, delay: index * 390, yoyo: true, repeat: -1, ease: 'Sine.easeInOut' });
      }
      this.ambience.push(glimmer);
    });
  }

  private addChimneyBreath(x: number, y: number): void {
    const smoke = this.add.rectangle(x, y, 4, 4, 0xf0e7d0, 0.45).setDepth(y + 1);
    if (!this.reducedMotion) {
      this.tweens.add({ targets: smoke, y: y - 20, alpha: 0, scale: 1.6,
        duration: 2800, repeat: -1, delay: 700, ease: 'Sine.easeOut' });
    }
    this.ambience.push(smoke);
  }

  private createAnchorNodes(): void {
    this.anchors = ANCHORS.map((anchor, index) => {
      const glow = this.add.circle(0, 0, 13, 0xdde2a7, 0.13);
      const outer = this.add.circle(0, 0, 5, 0xf1e4bd, 0.88).setStrokeStyle(1, 0x506f54, 0.68);
      const core = this.add.circle(0, 0, 1.5, 0x456c58, 0.95);
      const stem = this.add.rectangle(0, 7, 1.5, 5, 0x506f54, 0.72);
      return this.add.container(anchor.x, anchor.y, [glow, outer, stem, core])
        .setDepth(anchor.y + 20)
        .setName(`anchor-${index + 1}`);
    });
  }

  private drawModeOverlay(): void {
    const graphics = this.modeGraphics;
    graphics.clear();
    if (this.mode === 'coverage') {
      ANCHORS.forEach((anchor, index) => {
        const color = index % 2 ? 0xa0c3a2 : 0xc8ca8b;
        graphics.fillStyle(color, 0.045);
        graphics.fillCircle(anchor.x, anchor.y, 620);
        graphics.lineStyle(1.5, color, 0.15);
        graphics.strokeCircle(anchor.x, anchor.y, 620);
        graphics.lineStyle(1, color, 0.1);
        graphics.strokeCircle(anchor.x, anchor.y, 390);
      });
      return;
    }
    if (this.mode === 'signals') {
      for (const cow of this.cows) {
        const state = cow.getState();
        const anchor = this.nearestAnchor(state.estimatedPosition.x, state.estimatedPosition.y);
        const selected = state.id === this.selectedId;
        const color = state.signalLevel === 'strong' ? 0x8dbb80 : state.signalLevel === 'moderate' ? 0xd1b36b : 0x97a49a;
        graphics.lineStyle(selected ? 2 : 1, color, selected ? 0.68 : 0.2);
        graphics.lineBetween(state.estimatedPosition.x, state.estimatedPosition.y, anchor.x, anchor.y);
        if (selected) {
          graphics.fillStyle(color, 0.22);
          graphics.fillCircle(state.estimatedPosition.x, state.estimatedPosition.y, 20);
        }
      }
      return;
    }
    if (this.mode === 'track' && this.selectedId) {
      const state = this.cowById(this.selectedId)?.getState();
      if (state) {
        graphics.lineStyle(2, 0x415e4b, 0.48);
        graphics.strokeCircle(state.estimatedPosition.x, state.estimatedPosition.y, 24);
      }
    }
  }

  private nearestAnchor(x: number, y: number): { x: number; y: number } {
    return ANCHORS.reduce((nearest, anchor) =>
      Math.hypot(x - anchor.x, y - anchor.y) < Math.hypot(x - nearest.x, y - nearest.y) ? anchor : nearest,
    ANCHORS[0]);
  }

  private cowById(id: string): CowEntity | undefined {
    const index = Number(id.slice('animal-'.length));
    return Number.isInteger(index) && index >= 0 && index < this.cows.length ? this.cows[index] : undefined;
  }

  private onShutdown(): void {
    this.cameraController?.destroy();
    this.cows.forEach((cow) => cow.destroy());
    this.anchors.forEach((anchor) => anchor.destroy(true));
    this.ambience.forEach((object) => object.destroy());
    this.modeGraphics?.destroy();
  }
}
