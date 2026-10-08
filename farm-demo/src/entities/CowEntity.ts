import Phaser from 'phaser';
import type { BehaviorSnapshot } from '../simulation/behavior';
import type { PastureZone } from '../simulation/farm-layout';
import type { AnimalState } from '../types';
import { FarmEnvironmentLayer } from '../environment/FarmEnvironmentLayer';
import type { FarmId } from '../simulation/farm-config';

const COW_WIDTH: Record<FarmId, number> = { farm01: 58, farm02: 68 };
const COW_HEIGHT: Record<FarmId, number> = { farm01: 54, farm02: 66 };

export class CowEntity {
  readonly sprite: Phaser.GameObjects.Image;
  private readonly selection: Phaser.GameObjects.Ellipse;
  private readonly tagHalo: Phaser.GameObjects.Ellipse;
  private readonly tagMarker: Phaser.GameObjects.Rectangle;
  private readonly pasture: PastureZone;
  private snapshot: BehaviorSnapshot;
  private hovered = false;
  private walkPhase = 0;
  private lastX: number;
  private lastY: number;

  constructor(
    private readonly scene: Phaser.Scene,
    readonly index: number,
    pasture: PastureZone,
    onSelect: (pointer: Phaser.Input.Pointer) => void,
    environment: FarmEnvironmentLayer,
    private readonly farmId: FarmId,
  ) {
    this.pasture = pasture;
    this.snapshot = { status: 'GRAZE', ...pasture.waypoints[0], heading: 0, target: null, path: [] };
    this.lastX = this.snapshot.x;
    this.lastY = this.snapshot.y;
    this.sprite = scene.add.image(this.snapshot.x, this.snapshot.y, environment.getCowTexture(index))
      .setDisplaySize(COW_WIDTH[farmId], COW_HEIGHT[farmId])
      .setOrigin(0.5, 0.82)
      .setDepth(this.snapshot.y + 2)
      .setData('farmCow', true)
      .setInteractive({ cursor: 'grab' });
    this.sprite.on('pointerdown', (pointer: Phaser.Input.Pointer) => {
      pointer.event.stopPropagation();
      onSelect(pointer);
    });
    this.sprite.on('pointerover', () => this.setHovered(true));
    this.sprite.on('pointerout', () => this.setHovered(false));
    this.selection = scene.add.ellipse(this.snapshot.x, this.snapshot.y + 5, 54, 24, 0x334f36, 0.18)
      .setStrokeStyle(2, 0xe9ebc9, 0.86)
      .setDepth(this.snapshot.y + 1)
      .setVisible(false);
    this.tagHalo = scene.add.ellipse(this.snapshot.x, this.snapshot.y - 24, 19, 19, 0xf2d15b, 0.16)
      .setStrokeStyle(1, 0xe8bd38, 0.78)
      .setDepth(this.snapshot.y + 6)
      .setVisible(false);
    this.tagMarker = scene.add.rectangle(this.snapshot.x, this.snapshot.y - 24, 7, 11, 0xf0ca48, 1)
      .setStrokeStyle(1, 0x806824, 0.85)
      .setDepth(this.snapshot.y + 7)
      .setVisible(false);
  }

  update(snapshot: BehaviorSnapshot, _deltaMs: number, reducedMotion: boolean): void {
    const distanceMoved = Math.hypot(snapshot.x - this.lastX, snapshot.y - this.lastY);
    this.lastX = snapshot.x;
    this.lastY = snapshot.y;
    this.snapshot = snapshot;
    const { x, y } = this.snapshot;
    const walking = snapshot.status === 'WALK' && distanceMoved > 0.005 && !reducedMotion;
    if (walking) this.walkPhase += distanceMoved * (Math.PI * 2 / 23);
    const gaitLift = walking ? Math.abs(Math.sin(this.walkPhase)) * 1.15 : 0;
    this.sprite.setPosition(x, y - gaitLift)
      .setFlipX(Math.cos(snapshot.heading) < 0)
      .setDepth(y + 2);
    this.selection.setPosition(x, y + 7).setDepth(y + 1);
    const tagX = x + (this.sprite.flipX ? 23 : -23);
    const tagY = y - 24 - gaitLift;
    this.tagHalo.setPosition(tagX, tagY).setDepth(y + 6);
    this.tagMarker.setPosition(tagX, tagY).setDepth(y + 7);
  }

  setSelected(selected: boolean): void {
    this.selection.setVisible(selected);
    this.sprite.setAlpha(selected || this.hovered ? 1 : 0.96);
    this.sprite.setDepth(this.snapshot.y + (selected ? 5 : 2));
  }

  setDragging(dragging: boolean): void {
    if (this.sprite.input) this.sprite.input.cursor = dragging ? 'grabbing' : 'grab';
  }

  pulseIdentityTag(reducedMotion: boolean): void {
    this.scene.tweens.killTweensOf([this.selection, this.tagHalo, this.tagMarker]);
    this.selection.setVisible(true).setScale(1).setAlpha(0.86);
    this.tagHalo.setVisible(true).setScale(0.65).setAlpha(0.85);
    this.tagMarker.setVisible(true).setAlpha(1);
    const clearTag = () => {
      this.tagHalo.setVisible(false).setScale(1).setAlpha(0.16);
      this.tagMarker.setVisible(false).setAlpha(1);
      this.selection.setScale(1).setAlpha(0.86);
    };
    if (reducedMotion) {
      this.scene.time.delayedCall(1900, clearTag);
      return;
    }
    this.scene.tweens.add({ targets: this.selection, scaleX: 1.24, scaleY: 1.45, alpha: 0.25,
      duration: 360, yoyo: true, repeat: 2, ease: 'Sine.easeInOut' });
    this.scene.tweens.add({ targets: this.tagHalo, scaleX: 1.65, scaleY: 1.65, alpha: 0.06,
      duration: 460, yoyo: true, repeat: 2, ease: 'Sine.easeInOut', onComplete: clearTag });
  }

  getState(): AnimalState {
    return {
      id: `${this.farmId}-animal-${this.index}`,
      farmId: this.farmId,
      index: this.index,
      label: `Animal ${this.index + (this.farmId === 'farm02' ? 24 : 0)}`,
      status: this.snapshot.status,
      zone: this.pasture.name,
      estimatedPosition: { x: Math.round(this.snapshot.x), y: Math.round(this.snapshot.y) },
    };
  }

  destroy(): void {
    this.sprite.destroy();
    this.selection.destroy();
    this.tagHalo.destroy();
    this.tagMarker.destroy();
  }

  private setHovered(hovered: boolean): void {
    if (this.hovered === hovered) return;
    this.hovered = hovered;
    this.sprite.setAlpha(hovered ? 1 : 0.96);
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      this.sprite.setDisplaySize(COW_WIDTH[this.farmId], COW_HEIGHT[this.farmId]);
      return;
    }
    this.scene.tweens.add({ targets: this.sprite,
      displayWidth: hovered ? COW_WIDTH[this.farmId] + 5 : COW_WIDTH[this.farmId],
      displayHeight: hovered ? COW_HEIGHT[this.farmId] + 4 : COW_HEIGHT[this.farmId],
      duration: 150, ease: 'Sine.easeOut' });
  }
}
