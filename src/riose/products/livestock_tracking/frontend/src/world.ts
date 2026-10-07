export const SCENE_WIDTH = 84;
export const SCENE_DEPTH = 84;

export function terrainHeight(x: number, z: number): number {
  return 1.15 * Math.sin(x * 0.072) * Math.cos(z * 0.084)
    + 0.68 * Math.sin((x + z) * 0.051)
    + 0.32 * Math.cos((x - z) * 0.14);
}

export function terrainNormal(x: number, z: number): [number, number, number] {
  const epsilon = 0.12;
  const dx = (terrainHeight(x + epsilon, z) - terrainHeight(x - epsilon, z)) / (2 * epsilon);
  const dz = (terrainHeight(x, z + epsilon) - terrainHeight(x, z - epsilon)) / (2 * epsilon);
  const length = Math.hypot(dx, 1, dz);
  return [-dx / length, 1 / length, -dz / length];
}

export function farmWorldSize(width: number, height: number): [number, number] {
  const scale = Math.min(SCENE_WIDTH / Math.max(width, 1), SCENE_DEPTH / Math.max(height, 1));
  return [width * scale, height * scale];
}

export function farmToWorld(x: number, z: number, width: number, height: number): [number, number, number] {
  const scale = Math.min(SCENE_WIDTH / Math.max(width, 1), SCENE_DEPTH / Math.max(height, 1));
  const worldX = (x - width / 2) * scale;
  const worldZ = (z - height / 2) * scale;
  return [worldX, terrainHeight(worldX, worldZ), worldZ];
}

export function deterministicUnit(seed: number): number {
  const value = Math.sin(seed * 127.1 + 311.7) * 43758.5453123;
  return value - Math.floor(value);
}
