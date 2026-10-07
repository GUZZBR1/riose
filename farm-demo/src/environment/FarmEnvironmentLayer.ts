import Phaser from 'phaser';
import { WORLD_HEIGHT, WORLD_WIDTH } from '../simulation/farm-layout';
import type { FarmId } from '../simulation/farm-config';

const ASSET_ROOT = '/assets/farm-demo/isometric';
const CERRADO_ROOT = '/assets/farm-demo/cerrado';
const NELore_ROOT = '/assets/farm-demo/nelore';

export const FARM_ASSETS = {
  island: `${ASSET_ROOT}/island-base.webp`,
  path: `${ASSET_ROOT}/winding-path.webp`,
  water: `${ASSET_ROOT}/pond-creek.webp`,
  barn: `${ASSET_ROOT}/barn.webp`,
  trees: ['tree-oak', 'tree-apple', 'tree-willow', 'bush', 'flowers', 'rocks'],
  props: ['trough', 'hay', 'gate', 'field-shed', 'water-pump', 'feed-bin'],
  fences: ['fence-straight', 'fence-diagonal', 'fence-gate-open', 'fence-corner', 'fence-end', 'fence-gate-closed'],
} as const;

const cowAssets = Array.from({ length: 6 }, (_, index) => `cow-${index}`);
const decorAssets = [...FARM_ASSETS.trees, ...FARM_ASSETS.props, ...FARM_ASSETS.fences];

/** Loads independent art layers and composes them as a small isometric world. */
export class FarmEnvironmentLayer {
  private readonly objects: Phaser.GameObjects.Image[] = [];

  constructor(private readonly scene: Phaser.Scene, private readonly farmId: FarmId,
    private readonly worldWidth: number, private readonly worldHeight: number) {}

  static preload(scene: Phaser.Scene, farmId: FarmId): void {
    if (farmId === 'farm02') {
      scene.load.image('cerrado-diorama', `${CERRADO_ROOT}/cerrado-diorama.webp`);
      return;
    }
    scene.load.image('farm-island', FARM_ASSETS.island);
  }

  /** Paint the land first, then load the scene's interactive and decorative layers in batches. */
  create(onInteractiveReady: () => void): void {
    if (this.farmId === 'farm02') {
      const diorama = this.scene.add.image(this.worldWidth / 2, this.worldHeight / 2, 'cerrado-diorama')
        .setDisplaySize(this.worldWidth, this.worldHeight)
        .setOrigin(0.5)
        .setDepth(-100);
      this.objects.push(diorama);
      this.loadBatch(cowAssets.map((_, index) => [`nelore-${index}`, `${NELore_ROOT}/nelore-${index}.png`]), onInteractiveReady);
      return;
    }
    this.add('farm-island', this.worldWidth / 2, this.worldHeight / 2, this.worldWidth, this.worldHeight, -100, 0.5);
    const core: Array<[string, string]> = [
      ['farm-path', FARM_ASSETS.path], ['farm-water', FARM_ASSETS.water], ['farm-barn', FARM_ASSETS.barn],
      ...cowAssets.map((asset) => [asset, `${ASSET_ROOT}/${asset}.png`] as [string, string]),
    ];
    this.loadBatch(core, () => {
      this.addFarm01Core();
      onInteractiveReady();
      this.loadBatch(decorAssets.map((asset) => [asset, `${ASSET_ROOT}/${asset}.png`]), () => this.addFarm01Decorations());
    });
  }

  private addFarm01Core(): void {
    this.add('farm-path', 790, 620, 1170, 390, -60, 0.5);
    this.add('farm-water', 395, 555, 410, 205, 550, 0.78);
    this.add('farm-barn', 820, 462, 350, 262, 466, 0.86);
  }

  private addFarm01Decorations(): void {
    const trees: ReadonlyArray<[string, number, number, number, number]> = [
      ['tree-oak', 190, 350, 152, 150], ['tree-apple', 460, 295, 122, 100],
      ['tree-willow', 1260, 305, 132, 122], ['tree-oak', 1375, 495, 126, 124],
      ['tree-willow', 1280, 760, 138, 128], ['tree-apple', 360, 775, 120, 98],
      ['tree-oak', 1050, 785, 128, 126], ['tree-willow', 650, 240, 118, 110],
      ['bush', 625, 510, 112, 108], ['bush', 990, 270, 106, 108],
      ['bush', 1080, 610, 114, 108], ['bush', 515, 755, 100, 106],
      ['flowers', 480, 485, 88, 100], ['flowers', 1010, 760, 82, 96],
      ['rocks', 720, 820, 96, 104], ['rocks', 1430, 660, 88, 98],
    ];
    for (const [key, x, y, width, height] of trees) this.add(key, x, y, width, height, y + 10);

    const fences: ReadonlyArray<[string, number, number, number, number, number]> = [
      ['fence-straight', 940, 315, 150, 116, 0], ['fence-straight', 1082, 350, 150, 116, 0],
      ['fence-diagonal', 1204, 420, 136, 136, 0], ['fence-straight', 1170, 510, 150, 116, 0],
      ['fence-straight', 1018, 548, 150, 116, 0], ['fence-corner', 895, 455, 130, 100, 0],
      ['fence-gate-open', 1080, 538, 156, 150, 0], ['fence-end', 920, 555, 116, 86, 0],
    ];
    for (const [key, x, y, width, height, rotation] of fences) {
      this.add(key, x, y, width, height, y + 2, 0.84).setRotation(rotation);
    }

    const props: ReadonlyArray<[string, number, number, number, number]> = [
      ['trough', 680, 510, 86, 74], ['trough', 1170, 690, 86, 74],
      ['hay', 940, 650, 94, 90], ['feed-bin', 585, 342, 76, 64],
      ['gate', 855, 460, 130, 116], ['hay', 705, 775, 84, 78],
    ];
    for (const [key, x, y, width, height] of props) this.add(key, x, y, width, height, y + 5, 0.9);
  }

  private loadBatch(assets: Array<[string, string]>, onComplete: () => void): void {
    const loader = this.scene.load;
    loader.once(Phaser.Loader.Events.COMPLETE, onComplete);
    for (const [key, url] of assets) loader.image(key, url);
    loader.start();
  }

  private add(key: string, x: number, y: number, width: number, height: number, depth: number, originY = 1): Phaser.GameObjects.Image {
    const image = this.scene.add.image(x, y, key)
      .setDisplaySize(width, height)
      .setOrigin(0.5, originY)
      .setDepth(depth);
    this.objects.push(image);
    return image;
  }

  getCowTexture(index: number): string {
    return this.farmId === 'farm02' ? `nelore-${index % 6}` : cowAssets[index % cowAssets.length];
  }

  destroy(): void { this.objects.forEach((object) => object.destroy()); }
}
