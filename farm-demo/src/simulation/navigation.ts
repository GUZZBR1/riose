import type { WorldPoint } from '../types';
import { MAP_HEIGHT, MAP_WIDTH, TILE_SIZE, type PastureZone } from './farm-layout';

/**
 * Authored navigation geometry for the isometric artwork. Coordinates are in
 * farm-world pixels and intentionally live in source rather than being inferred
 * from rendered image colors.
 */
export const NAV_CELL_SIZE = TILE_SIZE / 2;
export const NAV_WIDTH = (MAP_WIDTH * TILE_SIZE) / NAV_CELL_SIZE;
export const NAV_HEIGHT = (MAP_HEIGHT * TILE_SIZE) / NAV_CELL_SIZE;
export const COW_FOOTPRINT_RADIUS = 18;
const MIN_COW_REGION_CELLS = 30;

export type NavigationObstacle =
  | { kind: 'ellipse'; x: number; y: number; rx: number; ry: number }
  | { kind: 'rect'; x: number; y: number; width: number; height: number }
  | { kind: 'segment'; from: WorldPoint; to: WorldPoint; radius: number };

export interface NavigationInteractionPoint {
  kind: 'drink' | 'shade' | 'rest' | 'graze';
  point: WorldPoint;
  label: string;
}

/** Art-independent geometry and authored points for one farm's navigation. */
export interface FarmNavigationDefinition {
  worldWidth: number;
  worldHeight: number;
  tileSize: number;
  cellSize: number;
  islandWalkable: readonly WorldPoint[];
  blocked: readonly NavigationObstacle[];
  cowFootprintRadius?: number;
  minRegionCells?: number;
  /** Centers of deliberate openings in otherwise blocked fence geometry. */
  gates?: readonly WorldPoint[];
  /** Safe interaction points, authored on walkable ground beside props. */
  interactionPoints?: readonly NavigationInteractionPoint[];
}

const FARM01_ISLAND_WALKABLE: readonly WorldPoint[] = [
  { x: 110, y: 335 }, { x: 142, y: 251 }, { x: 230, y: 148 }, { x: 388, y: 126 },
  { x: 531, y: 221 }, { x: 677, y: 239 }, { x: 833, y: 268 }, { x: 928, y: 282 },
  { x: 1061, y: 316 }, { x: 1248, y: 288 }, { x: 1415, y: 326 }, { x: 1490, y: 386 },
  { x: 1482, y: 438 }, { x: 1405, y: 493 }, { x: 1426, y: 554 }, { x: 1418, y: 627 },
  { x: 1350, y: 683 }, { x: 1254, y: 708 }, { x: 1164, y: 699 }, { x: 1080, y: 740 },
  { x: 1006, y: 761 }, { x: 925, y: 731 }, { x: 837, y: 776 }, { x: 741, y: 766 },
  { x: 649, y: 737 }, { x: 522, y: 755 }, { x: 423, y: 724 }, { x: 311, y: 678 },
  { x: 228, y: 626 }, { x: 183, y: 560 }, { x: 104, y: 496 }, { x: 43, y: 428 },
  { x: 49, y: 375 },
];

/** Collider placements align to the visible pond, buildings, trunks, props and fence art. */
const FARM01_BLOCKED: readonly NavigationObstacle[] = [
  // The image includes a grass bank; the collision ellipse tracks the visible water inside it.
  { kind: 'ellipse', x: 395, y: 555, rx: 174, ry: 80 },
  { kind: 'rect', x: 682, y: 408, width: 278, height: 102 }, // barn footprint
  { kind: 'rect', x: 1182, y: 594, width: 96, height: 76 }, // field shed
  { kind: 'ellipse', x: 500, y: 315, rx: 22, ry: 17 }, // pump base
  { kind: 'ellipse', x: 190, y: 350, rx: 18, ry: 15 },
  { kind: 'ellipse', x: 460, y: 295, rx: 16, ry: 14 },
  { kind: 'ellipse', x: 1260, y: 305, rx: 17, ry: 14 },
  { kind: 'ellipse', x: 1375, y: 495, rx: 17, ry: 14 },
  { kind: 'ellipse', x: 1280, y: 760, rx: 18, ry: 15 },
  { kind: 'ellipse', x: 360, y: 775, rx: 16, ry: 14 },
  { kind: 'ellipse', x: 1050, y: 785, rx: 17, ry: 15 },
  { kind: 'ellipse', x: 650, y: 240, rx: 15, ry: 13 },
  { kind: 'ellipse', x: 990, y: 270, rx: 17, ry: 15 },
  { kind: 'ellipse', x: 1080, y: 610, rx: 17, ry: 15 },
  { kind: 'ellipse', x: 515, y: 755, rx: 15, ry: 14 },
  { kind: 'ellipse', x: 720, y: 820, rx: 16, ry: 14 },
  { kind: 'ellipse', x: 1430, y: 660, rx: 15, ry: 13 },
  { kind: 'ellipse', x: 680, y: 510, rx: 22, ry: 13 }, // trough
  { kind: 'ellipse', x: 1170, y: 690, rx: 22, ry: 13 }, // trough
  { kind: 'ellipse', x: 940, y: 650, rx: 20, ry: 18 }, // hay
  { kind: 'ellipse', x: 585, y: 342, rx: 17, ry: 14 }, // feed bin
  // Pen edges; the south-east segment has a deliberate opening at its gate.
  { kind: 'segment', from: { x: 940, y: 315 }, to: { x: 1082, y: 350 }, radius: 8 },
  { kind: 'segment', from: { x: 1082, y: 350 }, to: { x: 1204, y: 420 }, radius: 8 },
  { kind: 'segment', from: { x: 1204, y: 420 }, to: { x: 1170, y: 510 }, radius: 8 },
  { kind: 'segment', from: { x: 1170, y: 510 }, to: { x: 1150, y: 518 }, radius: 8 },
  { kind: 'segment', from: { x: 1044, y: 550 }, to: { x: 1018, y: 548 }, radius: 8 },
  { kind: 'segment', from: { x: 1018, y: 548 }, to: { x: 895, y: 455 }, radius: 8 },
  { kind: 'segment', from: { x: 895, y: 455 }, to: { x: 940, y: 315 }, radius: 8 },
];

/** Default definition preserves the original Farm 01 `new FarmNavigation()` API. */
export const FARM01_NAVIGATION_DEFINITION: FarmNavigationDefinition = {
  worldWidth: MAP_WIDTH * TILE_SIZE,
  worldHeight: MAP_HEIGHT * TILE_SIZE,
  tileSize: TILE_SIZE,
  cellSize: NAV_CELL_SIZE,
  islandWalkable: FARM01_ISLAND_WALKABLE,
  blocked: FARM01_BLOCKED,
  cowFootprintRadius: COW_FOOTPRINT_RADIUS,
  minRegionCells: MIN_COW_REGION_CELLS,
  gates: [{ x: 1080, y: 538 }],
  interactionPoints: [
    { kind: 'drink', point: { x: 650, y: 465 }, label: 'pond edge' },
    { kind: 'drink', point: { x: 720, y: 555 }, label: 'meadow trough' },
  ],
};

const NEIGHBORS = [
  [-1, 0, 10], [1, 0, 10], [0, -1, 10], [0, 1, 10],
  [-1, -1, 14], [1, -1, 14], [-1, 1, 14], [1, 1, 14],
] as const;

export class FarmNavigation {
  private readonly columns: number;
  private readonly rows: number;
  private readonly clearanceRadius: number;
  private readonly minRegionCells: number;
  private readonly validCells: Uint8Array;
  private readonly componentByCell: Int32Array;
  private readonly points: WorldPoint[] = [];
  private readonly pointsByComponent = new Map<number, WorldPoint[]>();

  constructor(readonly definition: FarmNavigationDefinition = FARM01_NAVIGATION_DEFINITION) {
    if (!(definition.worldWidth > 0) || !(definition.worldHeight > 0) || !(definition.cellSize > 0) ||
        definition.islandWalkable.length < 3) {
      throw new Error('Farm navigation requires positive dimensions and an island polygon.');
    }
    this.columns = Math.ceil(definition.worldWidth / definition.cellSize);
    this.rows = Math.ceil(definition.worldHeight / definition.cellSize);
    this.clearanceRadius = (definition.cowFootprintRadius ?? COW_FOOTPRINT_RADIUS) + definition.cellSize * Math.SQRT1_2 + 1;
    this.minRegionCells = definition.minRegionCells ?? MIN_COW_REGION_CELLS;
    this.validCells = new Uint8Array(this.columns * this.rows);
    this.componentByCell = new Int32Array(this.columns * this.rows).fill(-1);
    for (let row = 0; row < this.rows; row += 1) {
      for (let col = 0; col < this.columns; col += 1) {
        const point = this.cellCenter(col, row);
        if (!this.hasCellClearance(point.x, point.y)) continue;
        this.validCells[this.cellIndex(col, row)] = 1;
        this.points.push(point);
      }
    }
    this.labelConnectedRegions();
  }

  isWalkable(x: number, y: number): boolean {
    if (!Number.isFinite(x) || !Number.isFinite(y) || x < 0 || y < 0 ||
        x >= this.definition.worldWidth || y >= this.definition.worldHeight) return false;
    return this.cellIsValid(Math.floor(x / this.definition.cellSize), Math.floor(y / this.definition.cellSize));
  }

  isWalkableSegment(from: WorldPoint, to: WorldPoint): boolean {
    const distance = Math.hypot(to.x - from.x, to.y - from.y);
    const steps = Math.max(1, Math.ceil(distance / 5));
    const startRegion = this.componentAt(from);
    if (startRegion < 0 || this.componentAt(to) !== startRegion) return false;
    for (let step = 0; step <= steps; step += 1) {
      const t = step / steps;
      const point = { x: from.x + (to.x - from.x) * t, y: from.y + (to.y - from.y) * t };
      if (!this.isWalkable(point.x, point.y) || this.componentAt(point) !== startRegion) return false;
    }
    return true;
  }

  randomTarget(bounds: PastureZone['bounds'], random: () => number, from?: WorldPoint): WorldPoint | null {
    const component = from ? this.componentAt(from) : -1;
    const regionPoints = component >= 0 ? this.pointsByComponent.get(component) ?? [] : this.points;
    const farEnough = (point: WorldPoint) => !from || Math.hypot(point.x - from.x, point.y - from.y) >= 90;
    const candidates = regionPoints.filter((point) => farEnough(point) &&
      point.x >= bounds.left * this.definition.tileSize && point.x <= bounds.right * this.definition.tileSize &&
      point.y >= bounds.top * this.definition.tileSize && point.y <= bounds.bottom * this.definition.tileSize,
    );
    // If the assigned paddock is disconnected by authored terrain, stay in the
    // cow's connected walkable region instead of retrying unreachable targets.
    const reachable = candidates.length ? candidates : regionPoints.filter(farEnough);
    if (!reachable.length) return null;
    return reachable[Math.min(reachable.length - 1, Math.floor(random() * reachable.length))];
  }

  getConnectedRegion(point: WorldPoint): number { return this.componentAt(point); }

  getConnectedRegionSize(point: WorldPoint): number {
    return this.pointsByComponent.get(this.componentAt(point))?.length ?? 0;
  }

  findSpawn(bounds: PastureZone['bounds'], random: () => number, occupied: readonly WorldPoint[]): WorldPoint | null {
    const eligible = this.points.filter((point) => this.getConnectedRegionSize(point) >= this.minRegionCells);
    const candidates = eligible.filter((point) =>
      point.x >= bounds.left * this.definition.tileSize && point.x <= bounds.right * this.definition.tileSize &&
      point.y >= bounds.top * this.definition.tileSize && point.y <= bounds.bottom * this.definition.tileSize,
    );
    const start = Math.floor(random() * Math.max(1, candidates.length));
    for (let offset = 0; offset < candidates.length; offset += 1) {
      const point = candidates[(start + offset) % candidates.length];
      if (occupied.every((other) => Math.hypot(point.x - other.x, point.y - other.y) >= 36)) return point;
    }
    // If a zone is full, use any safe, unoccupied cell rather than spawning invalidly.
    const fallbackStart = Math.floor(random() * eligible.length);
    for (let offset = 0; offset < eligible.length; offset += 1) {
      const point = eligible[(fallbackStart + offset) % eligible.length];
      if (occupied.every((other) => Math.hypot(point.x - other.x, point.y - other.y) >= 36)) return point;
    }
    return null;
  }

  findPath(start: WorldPoint, target: WorldPoint): WorldPoint[] | null {
    const startCell = this.nearestCell(start);
    const targetCell = this.nearestCell(target);
    if (startCell < 0 || targetCell < 0) return null;
    if (startCell === targetCell) return [this.cellCenter(...this.cellCoords(targetCell))];

    const size = this.validCells.length;
    const previous = new Int32Array(size).fill(-1);
    const score = new Float64Array(size).fill(Number.POSITIVE_INFINITY);
    const closed = new Uint8Array(size);
    const open = new MinHeap();
    score[startCell] = 0;
    open.push(startCell, this.heuristic(startCell, targetCell));

    while (open.size) {
      const current = open.pop();
      if (current < 0 || closed[current]) continue;
      if (current === targetCell) return this.simplify(this.reconstruct(previous, current));
      closed[current] = 1;
      const [col, row] = this.cellCoords(current);
      for (const [dx, dy, cost] of NEIGHBORS) {
        const nextCol = col + dx;
        const nextRow = row + dy;
        if (!this.cellIsValid(nextCol, nextRow)) continue;
        if (dx !== 0 && dy !== 0 &&
            (!this.cellIsValid(col + dx, row) || !this.cellIsValid(col, row + dy))) continue;
        const next = this.cellIndex(nextCol, nextRow);
        if (closed[next]) continue;
        const nextScore = score[current] + cost;
        if (nextScore >= score[next]) continue;
        previous[next] = current;
        score[next] = nextScore;
        open.push(next, nextScore + this.heuristic(next, targetCell));
      }
    }
    return null;
  }

  getWalkableCells(): readonly WorldPoint[] { return this.points; }

  isCellWalkable(col: number, row: number): boolean { return this.cellIsValid(col, row); }

  getCellSize(): number { return this.definition.cellSize; }
  getGridSize(): { columns: number; rows: number } { return { columns: this.columns, rows: this.rows }; }

  getCellCenter(col: number, row: number): WorldPoint { return this.cellCenter(col, row); }

  private isBaseWalkable(x: number, y: number): boolean {
    if (x < 0 || y < 0 || x >= this.definition.worldWidth || y >= this.definition.worldHeight) return false;
    if (!pointInPolygon({ x, y }, this.definition.islandWalkable)) return false;
    return !this.definition.blocked.some((obstacle) => collides(obstacle, x, y));
  }

  private hasCellClearance(x: number, y: number): boolean {
    if (!this.isBaseWalkable(x, y)) return false;
    // Erode the authored polygon by the body radius plus half a nav-cell diagonal.
    // Any position inside an accepted cell then retains full body clearance.
    for (let sample = 0; sample < 24; sample += 1) {
      const angle = (sample / 24) * Math.PI * 2;
      if (!this.isBaseWalkable(x + Math.cos(angle) * this.clearanceRadius,
        y + Math.sin(angle) * this.clearanceRadius)) return false;
    }
    return true;
  }

  private nearestCell(point: WorldPoint): number {
    const col = Math.floor(point.x / this.definition.cellSize);
    const row = Math.floor(point.y / this.definition.cellSize);
    if (this.cellIsValid(col, row)) return this.cellIndex(col, row);
    for (let radius = 1; radius < 12; radius += 1) {
      for (let dy = -radius; dy <= radius; dy += 1) {
        for (let dx = -radius; dx <= radius; dx += 1) {
          if (Math.max(Math.abs(dx), Math.abs(dy)) !== radius) continue;
          if (this.cellIsValid(col + dx, row + dy)) return this.cellIndex(col + dx, row + dy);
        }
      }
    }
    return -1;
  }

  private componentAt(point: WorldPoint): number {
    const cell = this.nearestCell(point);
    return cell < 0 ? -1 : this.componentByCell[cell];
  }

  private labelConnectedRegions(): void {
    let component = 0;
    const queue = new Int32Array(this.validCells.length);
    for (let start = 0; start < this.validCells.length; start += 1) {
      if (!this.validCells[start] || this.componentByCell[start] >= 0) continue;
      let head = 0;
      let tail = 0;
      queue[tail++] = start;
      this.componentByCell[start] = component;
      const componentPoints: WorldPoint[] = [];
      while (head < tail) {
        const current = queue[head++];
        const [col, row] = this.cellCoords(current);
        componentPoints.push(this.cellCenter(col, row));
        for (const [dx, dy] of NEIGHBORS) {
          const nextCol = col + dx;
          const nextRow = row + dy;
          if (!this.cellIsValid(nextCol, nextRow)) continue;
          if (dx !== 0 && dy !== 0 &&
              (!this.cellIsValid(col + dx, row) || !this.cellIsValid(col, row + dy))) continue;
          const next = this.cellIndex(nextCol, nextRow);
          if (this.componentByCell[next] >= 0) continue;
          this.componentByCell[next] = component;
          queue[tail++] = next;
        }
      }
      this.pointsByComponent.set(component, componentPoints);
      component += 1;
    }
  }

  private cellIsValid(col: number, row: number): boolean {
    if (col < 0 || row < 0 || col >= this.columns || row >= this.rows) return false;
    return this.validCells[this.cellIndex(col, row)] === 1;
  }

  private cellIndex(col: number, row: number): number { return row * this.columns + col; }
  private cellCoords(index: number): [number, number] { return [index % this.columns, Math.floor(index / this.columns)]; }
  private cellCenter(col: number, row: number): WorldPoint {
    return { x: (col + 0.5) * this.definition.cellSize, y: (row + 0.5) * this.definition.cellSize };
  }

  private heuristic(a: number, b: number): number {
    const [ax, ay] = this.cellCoords(a);
    const [bx, by] = this.cellCoords(b);
    const dx = Math.abs(ax - bx);
    const dy = Math.abs(ay - by);
    return 10 * (dx + dy) - 6 * Math.min(dx, dy);
  }

  private reconstruct(previous: Int32Array, end: number): WorldPoint[] {
    const path: WorldPoint[] = [];
    for (let current = end; current >= 0; current = previous[current]) {
      path.push(this.cellCenter(...this.cellCoords(current)));
      if (previous[current] === -1) break;
    }
    return path.reverse();
  }

  private simplify(path: WorldPoint[]): WorldPoint[] {
    if (path.length <= 2) return path;
    const result = [path[0]];
    let anchor = 0;
    while (anchor < path.length - 1) {
      let farthest = anchor + 1;
      for (let candidate = anchor + 2; candidate < path.length; candidate += 1) {
        if (!this.isWalkableSegment(path[anchor], path[candidate])) break;
        farthest = candidate;
      }
      result.push(path[farthest]);
      anchor = farthest;
    }
    return result;
  }
}

function pointInPolygon(point: WorldPoint, polygon: readonly WorldPoint[]): boolean {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i, i += 1) {
    const a = polygon[i];
    const b = polygon[j];
    const crosses = (a.y > point.y) !== (b.y > point.y) &&
      point.x < ((b.x - a.x) * (point.y - a.y)) / (b.y - a.y) + a.x;
    if (crosses) inside = !inside;
  }
  return inside;
}

function collides(obstacle: NavigationObstacle, x: number, y: number): boolean {
  if (obstacle.kind === 'ellipse') {
    const dx = (x - obstacle.x) / obstacle.rx;
    const dy = (y - obstacle.y) / obstacle.ry;
    return dx * dx + dy * dy <= 1;
  }
  if (obstacle.kind === 'rect') {
    return x >= obstacle.x && x <= obstacle.x + obstacle.width &&
      y >= obstacle.y && y <= obstacle.y + obstacle.height;
  }
  const dx = obstacle.to.x - obstacle.from.x;
  const dy = obstacle.to.y - obstacle.from.y;
  const lengthSquared = dx * dx + dy * dy;
  const t = lengthSquared === 0 ? 0 : Math.max(0, Math.min(1,
    ((x - obstacle.from.x) * dx + (y - obstacle.from.y) * dy) / lengthSquared,
  ));
  const nearestX = obstacle.from.x + t * dx;
  const nearestY = obstacle.from.y + t * dy;
  return Math.hypot(x - nearestX, y - nearestY) <= obstacle.radius;
}

class MinHeap {
  private readonly values: Array<{ index: number; priority: number }> = [];
  get size(): number { return this.values.length; }
  push(index: number, priority: number): void {
    this.values.push({ index, priority });
    let child = this.values.length - 1;
    while (child > 0) {
      const parent = Math.floor((child - 1) / 2);
      if (this.values[parent].priority <= priority) break;
      this.values[child] = this.values[parent];
      child = parent;
    }
    this.values[child] = { index, priority };
  }
  pop(): number {
    if (!this.values.length) return -1;
    const first = this.values[0].index;
    const last = this.values.pop()!;
    if (this.values.length) {
      let parent = 0;
      while (true) {
        const left = parent * 2 + 1;
        const right = left + 1;
        if (left >= this.values.length) break;
        const child = right < this.values.length && this.values[right].priority < this.values[left].priority ? right : left;
        if (this.values[child].priority >= last.priority) break;
        this.values[parent] = this.values[child];
        parent = child;
      }
      this.values[parent] = last;
    }
    return first;
  }
}
