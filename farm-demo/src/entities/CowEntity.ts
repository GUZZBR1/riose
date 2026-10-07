import Phaser from 'phaser';
import { AnimalBehavior, type BehaviorSnapshot } from '../simulation/behavior';
import { pastureOrdinal } from '../simulation/farm-layout';
import type { PastureZone } from '../simulation/farm-layout';
import type { AnimalState } from '../types';
import { FarmEnvironmentLayer } from '../environment/FarmEnvironmentLayer';

const COW_WIDTH = 58;
const COW_HEIGHT = 54;

export class CowEntity {
  readonly sprite: Phaser.GameObjects.Image;
  readonly behavior: AnimalBehavior;
  private readonly selection: Phaser.GameObjects.Ellipse;
  private readonly pasture: PastureZone;
  private snapshot: BehaviorSnapshot;
  private motionTime = 0;
  private hovered = false;

  constructor(
    private readonly scene: Phaser.Scene,
    readonly index: number,
    pasture: PastureZone,
    onSelect: () => void,
    environment: FarmEnvironmentLayer,
  ) {
    this.pasture = pasture;
    this.behavior = new AnimalBehavior(index, pasture, pastureOrdinal(index));
    this.snapshot = this.behavior.current;
    this.sprite = scene.add.image(this.snapshot.x, this.snapshot.y, environment.getCowTexture(index))
      .setDisplaySize(COW_WIDTH, COW_HEIGHT)
      .setOrigin(0.5, 0.82)
      .setDepth(this.snapshot.y + 2)
      .setData('farmCow', true)
      .setInteractive({ useHandCursor: true });
    this.sprite.on('pointerdown', (pointer: Phaser.Input.Pointer) => {
      pointer.event.stopPropagation();
      onSelect();
    });
    this.sprite.on('pointerover', () => this.setHovered(true));
    this.sprite.on('pointerout', () => this.setHovered(false));
    this.selection = scene.add.ellipse(this.snapshot.x, this.snapshot.y + 5, 54, 24, 0x334f36, 0.18)
      .setStrokeStyle(2, 0xe9ebc9, 0.86)
      .setDepth(this.snapshot.y + 1)
      .setVisible(false);
  }

  update(deltaMs: number, reducedMotion: boolean): void {
    this.snapshot = this.behavior.update(deltaMs, reducedMotion);
    if (!reducedMotion) this.motionTime += Math.min(deltaMs, 50);
    const { x, y, status, heading } = this.snapshot;
    const breathing = !reducedMotion && status === 'IDLE' ? Math.sin(this.motionTime * 0.002 + this.index) * 1.2 : 0;
    const grazing = !reducedMotion && status === 'GRAZE' ? Math.sin(this.motionTime * 0.006 + this.index) * 1.6 : 0;
    const walking = !reducedMotion && status === 'WALK' ? Math.abs(Math.sin(this.motionTime * 0.012 + this.index)) * 2 : 0;
    this.sprite.setPosition(x, y + breathing + grazing + walking).setDepth(y + 2);
    if (!reducedMotion && status === 'WALK') this.sprite.setFlipX(Math.cos(heading) < 0);
    this.selection.setPosition(x, y + 7).setDepth(y + 1);
  }

  setSelected(selected: boolean): void {
    this.selection.setVisible(selected);
    this.sprite.setAlpha(selected || this.hovered ? 1 : 0.96);
    this.sprite.setDepth(this.snapshot.y + (selected ? 5 : 2));
  }

  getState(): AnimalState {
    return {
      id: `animal-${this.index}`,
      label: `Animal ${this.index}`,
      status: this.snapshot.status,
      zone: this.pasture.name,
      estimatedPosition: { x: Math.round(this.snapshot.x), y: Math.round(this.snapshot.y) },
    };
  }

  destroy(): void {
    this.sprite.destroy();
    this.selection.destroy();
  }

  private setHovered(hovered: boolean): void {
    if (this.hovered === hovered) return;
    this.hovered = hovered;
    this.sprite.setAlpha(hovered ? 1 : 0.96);
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      this.sprite.setDisplaySize(COW_WIDTH, COW_HEIGHT);
      return;
    }
    this.scene.tweens.add({ targets: this.sprite, displayWidth: hovered ? COW_WIDTH + 5 : COW_WIDTH,
      displayHeight: hovered ? COW_HEIGHT + 4 : COW_HEIGHT, duration: 150, ease: 'Sine.easeOut' });
  }
}
