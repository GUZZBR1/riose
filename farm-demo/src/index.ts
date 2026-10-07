import Phaser from 'phaser';
import { FarmScene } from './FarmScene';
import type { AnimalState, FarmDemoCallbacks, FarmDemoHandle } from './types';

export type { AnimalState, AnimalStatus, FarmDemoCallbacks, FarmDemoHandle, WorldPoint } from './types';

/** Mount the self-contained, client-only farm scene into an existing page region. */
export function mountFarmDemo(parent: HTMLElement, callbacks: FarmDemoCallbacks = {}): FarmDemoHandle {
  const host = document.createElement('div');
  host.className = 'riose-farm-canvas-host';
  Object.assign(host.style, {
    position: 'relative',
    width: '100%',
    height: '100%',
    minHeight: '420px',
    overflow: 'visible',
    touchAction: 'none',
  });
  parent.appendChild(host);

  const scene = new FarmScene(callbacks, callbacks.animalCount ?? 24);
  const initialWidth = Math.max(1, host.clientWidth);
  const initialHeight = Math.max(1, host.clientHeight);
  const game = new Phaser.Game({
    // Canvas keeps the transparent layered sprites crisp and stable on mobile.
    type: Phaser.CANVAS,
    parent: host,
    width: initialWidth,
    height: initialHeight,
    backgroundColor: 'rgba(0,0,0,0)',
    transparent: true,
    pixelArt: true,
    roundPixels: true,
    antialias: false,
    scale: {
      mode: Phaser.Scale.RESIZE,
      width: initialWidth,
      height: initialHeight,
      autoCenter: Phaser.Scale.CENTER_BOTH,
    },
    render: { pixelArt: true, antialias: false, roundPixels: true },
    input: { activePointers: 1 },
    scene: [scene],
  });

  let destroyed = false;
  const invokeWhenReady = (action: () => void): void => {
    if (destroyed) return;
    if (scene.ready) action();
    else scene.events.once('farm-ready', action);
  };

  return {
    focusAnimal(id: string): void { invokeWhenReady(() => scene.focusAnimal(id)); },
    selectAnimal(id: string | null): void { invokeWhenReady(() => scene.selectAnimal(id)); },
    getAnimals(): readonly AnimalState[] { return scene.ready ? scene.getAnimals() : []; },
    destroy(): void {
      if (destroyed) return;
      destroyed = true;
      scene.events.removeAllListeners('farm-ready');
      game.destroy(true);
      host.remove();
    },
  };
}
