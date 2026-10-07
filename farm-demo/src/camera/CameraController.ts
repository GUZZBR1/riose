import Phaser from 'phaser';
import { WORLD_HEIGHT, WORLD_WIDTH } from '../simulation/farm-layout';

export class CameraController {
  private dragging = false;
  private lastX = 0;
  private lastY = 0;
  private target: { x: number; y: number } | null = null;
  private readonly reducedMotion: boolean;

  constructor(private readonly scene: Phaser.Scene, reducedMotion: boolean) {
    this.reducedMotion = reducedMotion;
    const camera = scene.cameras.main;
    camera.setBounds(0, 0, WORLD_WIDTH, WORLD_HEIGHT);
    camera.setZoom(this.overviewZoom());
    camera.centerOn(WORLD_WIDTH / 2, WORLD_HEIGHT / 2);
    scene.input.on('pointerdown', this.pointerDown, this);
    scene.input.on('pointermove', this.pointerMove, this);
    scene.input.on('pointerup', this.pointerUp, this);
    scene.input.on('pointerupoutside', this.pointerUp, this);
    scene.input.on('wheel', this.wheel, this);
  }

  update(deltaMs: number): void {
    if (!this.target || this.reducedMotion) return;
    const camera = this.scene.cameras.main;
    const t = Math.min(1, deltaMs / 220);
    camera.scrollX += (this.target.x - camera.scrollX - camera.width / 2) * t;
    camera.scrollY += (this.target.y - camera.scrollY - camera.height / 2) * t;
    if (Math.abs(this.target.x - (camera.scrollX + camera.width / 2)) < 1 &&
        Math.abs(this.target.y - (camera.scrollY + camera.height / 2)) < 1) this.target = null;
  }

  focus(x: number, y: number): void {
    const camera = this.scene.cameras.main;
    if (this.reducedMotion) camera.centerOn(x, y);
    else this.target = { x, y };
  }

  setOverview(): void {
    const camera = this.scene.cameras.main;
    const zoom = this.overviewZoom();
    if (this.reducedMotion) camera.setZoom(zoom).centerOn(WORLD_WIDTH / 2, WORLD_HEIGHT / 2);
    else {
      this.scene.tweens.add({ targets: camera, zoom, duration: 280, ease: 'Sine.easeOut' });
      this.focus(WORLD_WIDTH / 2, WORLD_HEIGHT / 2);
    }
  }

  reset(): void {
    this.target = null;
    this.scene.cameras.main.setZoom(this.overviewZoom()).centerOn(WORLD_WIDTH / 2, WORLD_HEIGHT / 2);
  }

  zoomBy(factor: number): void {
    if (!Number.isFinite(factor) || factor <= 0) return;
    const camera = this.scene.cameras.main;
    camera.setZoom(Phaser.Math.Clamp(camera.zoom * factor, 0.38, 1.8));
  }

  destroy(): void {
    this.scene.input.off('pointerdown', this.pointerDown, this);
    this.scene.input.off('pointermove', this.pointerMove, this);
    this.scene.input.off('pointerup', this.pointerUp, this);
    this.scene.input.off('pointerupoutside', this.pointerUp, this);
    this.scene.input.off('wheel', this.wheel, this);
  }

  private pointerDown(pointer: Phaser.Input.Pointer): void {
    const hits = this.scene.input.hitTestPointer(pointer);
    if (hits.some((gameObject) => gameObject instanceof Phaser.GameObjects.Sprite)) return;
    this.dragging = true;
    this.lastX = pointer.x;
    this.lastY = pointer.y;
    this.target = null;
  }

  private pointerMove(pointer: Phaser.Input.Pointer): void {
    if (!this.dragging || !pointer.isDown) return;
    const camera = this.scene.cameras.main;
    camera.scrollX -= (pointer.x - this.lastX) / camera.zoom;
    camera.scrollY -= (pointer.y - this.lastY) / camera.zoom;
    this.lastX = pointer.x;
    this.lastY = pointer.y;
  }

  private pointerUp(): void { this.dragging = false; }

  private wheel(_pointer: Phaser.Input.Pointer, _objects: Phaser.GameObjects.GameObject[], _dx: number, dy: number): void {
    const camera = this.scene.cameras.main;
    camera.setZoom(Phaser.Math.Clamp(camera.zoom * (dy > 0 ? 0.92 : 1.08), 0.55, 1.8));
  }

  private overviewZoom(): number {
    const { width, height } = this.scene.scale;
    // Fill the stage's short axis: width on desktop, height on phones. This
    // crops the map gently instead of leaving an empty band beside/below it.
    const scale = width / height >= WORLD_WIDTH / WORLD_HEIGHT
      ? width / WORLD_WIDTH * 0.98
      : height / WORLD_HEIGHT * 0.94;
    return Phaser.Math.Clamp(scale, 0.38, 0.86);
  }
}
