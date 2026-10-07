import Phaser from 'phaser';

export class CameraController {
  private dragging = false;
  private lastX = 0;
  private lastY = 0;
  private target: { x: number; y: number } | null = null;
  private readonly reducedMotion: boolean;

  constructor(
    private readonly scene: Phaser.Scene,
    reducedMotion: boolean,
    private readonly worldWidth: number,
    private readonly worldHeight: number,
  ) {
    this.reducedMotion = reducedMotion;
    scene.input.on('pointerdown', this.pointerDown, this);
    scene.input.on('pointermove', this.pointerMove, this);
    scene.input.on('pointerup', this.pointerUp, this);
    scene.input.on('pointerupoutside', this.pointerUp, this);
    scene.input.on('wheel', this.wheel, this);
    scene.scale.on(Phaser.Scale.Events.RESIZE, this.resize, this);
    this.resize();
  }

  update(deltaMs: number): void {
    if (!this.target || this.reducedMotion) return;
    const camera = this.scene.cameras.main;
    const t = Math.min(1, deltaMs / 210);
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

  destroy(): void {
    this.scene.input.off('pointerdown', this.pointerDown, this);
    this.scene.input.off('pointermove', this.pointerMove, this);
    this.scene.input.off('pointerup', this.pointerUp, this);
    this.scene.input.off('pointerupoutside', this.pointerUp, this);
    this.scene.input.off('wheel', this.wheel, this);
    this.scene.scale.off(Phaser.Scale.Events.RESIZE, this.resize, this);
  }

  private resize(): void {
    const camera = this.scene.cameras.main;
    const zoom = Math.min(camera.width / this.worldWidth, camera.height / this.worldHeight) * 0.96;
    camera.setZoom(Phaser.Math.Clamp(zoom, 0.2, 1.2));
    this.clampToIllustration();
    camera.centerOn(this.worldWidth / 2, this.worldHeight / 2);
  }

  private clampToIllustration(): void {
    const camera = this.scene.cameras.main;
    const extraX = Math.max(0, (camera.width / camera.zoom - this.worldWidth) / 2);
    const extraY = Math.max(0, (camera.height / camera.zoom - this.worldHeight) / 2);
    camera.setBounds(-extraX, -extraY, this.worldWidth + extraX * 2, this.worldHeight + extraY * 2);
  }

  private pointerDown(pointer: Phaser.Input.Pointer): void {
    const hits = this.scene.input.hitTestPointer(pointer);
    if (hits.some((gameObject) => gameObject.getData('farmCow') === true)) return;
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
    const zoom = Phaser.Math.Clamp(camera.zoom * (dy > 0 ? 0.92 : 1.08), 0.2, 1.2);
    this.scene.tweens.killTweensOf(camera);
    if (this.reducedMotion) camera.setZoom(zoom);
    else this.scene.tweens.add({ targets: camera, zoom, duration: 220, ease: 'Sine.easeOut' });
    this.clampToIllustration();
  }
}
