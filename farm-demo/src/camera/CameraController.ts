import Phaser from 'phaser';

export class CameraController {
  private dragging = false;
  private lastX = 0;
  private lastY = 0;
  private target: { x: number; y: number; view: 'animal' | 'overview'; zoom: number | null } | null = null;
  private viewMode: 'animal' | 'overview' = 'overview';
  private overviewZoom = 1;
  private selectedZoom = 1;
  private readonly reducedMotion: boolean;
  private initialized = false;

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
    scene.scale.on(Phaser.Scale.Events.RESIZE, this.resize, this);
    this.resize();
  }

  update(deltaMs: number): void {
    if (!this.target || this.reducedMotion) return;
    const camera = this.scene.cameras.main;
    const t = 1 - Math.exp(-Math.min(deltaMs, 50) / 230);
    const center = this.getCenter();
    // The selected zoom is captured at click time. The context rail changes the
    // canvas width while it opens; recomputing fit on each resize made the
    // camera chase a moving zoom target and visibly pulse during selection.
    const targetZoom = this.target.view === 'animal' && this.target.zoom !== null
      ? this.target.zoom
      : this.overviewZoom;
    const nextZoom = camera.zoomX + (targetZoom - camera.zoomX) * t;
    camera.setZoom(nextZoom);
    this.clampToIllustration();
    const desired = this.clampCenter(this.target.x, this.target.y);
    this.setCenter(
      center.x + (desired.x - center.x) * t,
      center.y + (desired.y - center.y) * t,
    );
    const current = this.getCenter();
    if (Math.abs(desired.x - current.x) < 1 && Math.abs(desired.y - current.y) < 1 &&
        Math.abs(targetZoom - camera.zoomX) < 0.002) {
      this.setCenter(desired.x, desired.y);
      camera.setZoom(targetZoom);
      this.clampToIllustration();
      this.target = null;
    }
  }

  focus(x: number, y: number): void {
    this.viewMode = 'animal';
    this.selectedZoom = this.focusZoom(x, y);
    if (this.reducedMotion) {
      this.target = null;
      this.scene.cameras.main.setZoom(this.selectedZoom);
      this.clampToIllustration();
      const target = this.clampCenter(x, y);
      this.setCenter(target.x, target.y);
    } else this.target = { x, y, view: 'animal', zoom: this.selectedZoom };
  }

  showOverview(): void {
    this.viewMode = 'overview';
    const target = { x: this.worldWidth / 2, y: this.worldHeight / 2, view: 'overview' as const, zoom: null };
    if (this.reducedMotion) {
      this.target = null;
      this.scene.cameras.main.setZoom(this.overviewZoom);
      this.clampToIllustration();
      this.setCenter(target.x, target.y);
    } else this.target = target;
  }

  cancelFocus(): void {
    this.target = null;
    this.viewMode = 'overview';
    this.selectedZoom = this.overviewZoom;
  }

  destroy(): void {
    this.scene.input.off('pointerdown', this.pointerDown, this);
    this.scene.input.off('pointermove', this.pointerMove, this);
    this.scene.input.off('pointerup', this.pointerUp, this);
    this.scene.input.off('pointerupoutside', this.pointerUp, this);
    this.scene.scale.off(Phaser.Scale.Events.RESIZE, this.resize, this);
  }

  private resize(): void {
    const camera = this.scene.cameras.main;
    const previousCenter = this.initialized ? this.getCenter() : { x: this.worldWidth / 2, y: this.worldHeight / 2 };
    const zoom = Math.min(camera.width / this.worldWidth, camera.height / this.worldHeight) * 0.96;
    this.overviewZoom = Phaser.Math.Clamp(zoom, 0.2, 1.2);
    if (!this.initialized || !this.target) camera.setZoom(this.viewMode === 'animal' ? this.selectedZoom : this.overviewZoom);
    this.clampToIllustration();
    this.setCenter(previousCenter.x, previousCenter.y);
    this.initialized = true;
  }

  private focusZoom(x: number, y: number): number {
    const camera = this.scene.cameras.main;
    // Zoom enough to let the selected cow move toward the center of the
    // viewport, while keeping a hard cap so edge animals remain in context.
    const horizontalRoom = Math.max(1, 2 * Math.min(x, this.worldWidth - x));
    const verticalRoom = Math.max(1, 2 * Math.min(y, this.worldHeight - y));
    const centerableZoom = Math.max(camera.width / horizontalRoom, camera.height / verticalRoom);
    return Phaser.Math.Clamp(Math.max(this.overviewZoom * 1.2, centerableZoom), 0.2, 1.05);
  }

  private getCenter(): { x: number; y: number } {
    const camera = this.scene.cameras.main;
    return {
      x: camera.scrollX + camera.width / 2,
      y: camera.scrollY + camera.height / 2,
    };
  }

  private setCenter(x: number, y: number): void {
    const camera = this.scene.cameras.main;
    const center = this.clampCenter(x, y);
    camera.setScroll(center.x - camera.width / 2, center.y - camera.height / 2);
  }

  private clampCenter(x: number, y: number): { x: number; y: number } {
    const camera = this.scene.cameras.main;
    const viewWidth = camera.width / camera.zoomX;
    const viewHeight = camera.height / camera.zoomY;
    const extraX = Math.max(0, (viewWidth - this.worldWidth) / 2);
    const extraY = Math.max(0, (viewHeight - this.worldHeight) / 2);
    const left = -extraX + viewWidth * camera.originX;
    const right = this.worldWidth + extraX - viewWidth * (1 - camera.originX);
    const top = -extraY + viewHeight * camera.originY;
    const bottom = this.worldHeight + extraY - viewHeight * (1 - camera.originY);
    return {
      x: Phaser.Math.Clamp(x, Math.min(left, right), Math.max(left, right)),
      y: Phaser.Math.Clamp(y, Math.min(top, bottom), Math.max(top, bottom)),
    };
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
    // Keep ordinary pointer and touch gestures available to the page. Panning
    // is an intentional Shift + primary-button gesture, never a normal drag.
    const event = pointer.event as MouseEvent | undefined;
    if (!event?.shiftKey || event.button !== 0) return;
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
}
