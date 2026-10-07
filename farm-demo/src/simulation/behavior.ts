import type { AnimalStatus, WorldPoint } from '../types';
import type { PastureZone } from './farm-layout';
import { FarmNavigation } from './navigation';

export const COW_SEPARATION_RADIUS = 31;
const WALK_SPEED_MIN = 15;
const WALK_SPEED_MAX = 20;
const ACCELERATION = 30;
const MAX_TURN_RATE = 2.2;

export interface BehaviorSnapshot {
  status: AnimalStatus;
  x: number;
  y: number;
  heading: number;
  target: WorldPoint | null;
  path: readonly WorldPoint[];
}

export interface NeighborPosition extends WorldPoint {
  id: number;
}

/** Deterministic, bounded animal state machine driven by the authored nav grid. */
export class AnimalBehavior {
  private dwellRemaining = 0;
  private speed = WALK_SPEED_MIN;
  private velocityX = 0;
  private velocityY = 0;
  private target: WorldPoint | null = null;
  private path: readonly WorldPoint[] = [];
  private pathIndex = 0;
  private stuckFor = 0;
  private targetDistance = Number.POSITIVE_INFINITY;
  private status: AnimalStatus;
  private x: number;
  private y: number;
  private previousX: number;
  private previousY: number;
  private heading: number;
  private randomState: number;
  private arrivedAtWater = false;

  constructor(
    readonly index: number,
    private readonly pasture: PastureZone,
    private readonly navigation: FarmNavigation,
    spawn: WorldPoint,
    private readonly stationary = false,
  ) {
    this.randomState = (0x9e3779b9 ^ Math.imul(index + 1, 0x85ebca6b)) >>> 0;
    this.x = spawn.x;
    this.y = spawn.y;
    this.previousX = spawn.x;
    this.previousY = spawn.y;
    this.heading = (this.random() * 2 - 1) * Math.PI;
    const place = index % 20;
    this.status = stationary
      ? (place < 14 ? 'GRAZE' : place < 19 ? 'REST' : 'IDLE')
      : (place < 11 ? 'GRAZE' : place < 15 ? 'REST' : place < 19 ? 'WALK' : 'IDLE');
    this.dwellRemaining = 4 + this.random() * 11;
    if (!stationary && this.status === 'WALK') this.chooseDestination();
  }

  step(dt: number, neighbors: readonly NeighborPosition[]): void {
    if (this.stationary) return;
    this.previousX = this.x;
    this.previousY = this.y;

    if (this.status === 'DRINK' && this.arrivedAtWater) {
      this.dwellRemaining -= dt;
      if (this.dwellRemaining <= 0) this.finishStop();
      return;
    }

    if (this.status !== 'WALK' && this.status !== 'DRINK') {
      this.dwellRemaining -= dt;
      if (this.dwellRemaining <= 0) this.beginNextJourney();
      return;
    }

    if (!this.target || !this.path.length) {
      this.finishStop();
      return;
    }

    const waypoint = this.path[this.pathIndex] ?? this.target;
    const dx = waypoint.x - this.x;
    const dy = waypoint.y - this.y;
    const distance = Math.hypot(dx, dy);
    if (distance < 5) {
      this.pathIndex += 1;
      if (this.pathIndex >= this.path.length || Math.hypot(this.target.x - this.x, this.target.y - this.y) < 8) {
        this.arrive();
        return;
      }
    }

    const desiredHeading = Math.atan2(dy, dx);
    this.heading = rotateToward(this.heading, desiredHeading, MAX_TURN_RATE * dt);
    const nearby = neighbors.filter((neighbor) => neighbor.id !== this.index);
    const separation = this.separation(nearby);
    const steeringX = Math.cos(this.heading) + separation.x;
    const steeringY = Math.sin(this.heading) + separation.y;
    const steeringLength = Math.hypot(steeringX, steeringY) || 1;
    const desiredX = (steeringX / steeringLength) * this.speed;
    const desiredY = (steeringY / steeringLength) * this.speed;
    this.velocityX = approach(this.velocityX, desiredX, ACCELERATION * dt);
    this.velocityY = approach(this.velocityY, desiredY, ACCELERATION * dt);

    const velocityLength = Math.hypot(this.velocityX, this.velocityY);
    if (velocityLength > this.speed) {
      this.velocityX = (this.velocityX / velocityLength) * this.speed;
      this.velocityY = (this.velocityY / velocityLength) * this.speed;
    }
    let next: WorldPoint | null = { x: this.x + this.velocityX * dt, y: this.y + this.velocityY * dt };
    if (!this.canOccupy(next, nearby)) next = this.findSafeStep(nearby, dt);

    if (!next) {
      this.velocityX = approach(this.velocityX, 0, ACCELERATION * dt * 2);
      this.velocityY = approach(this.velocityY, 0, ACCELERATION * dt * 2);
      this.stuckFor += dt;
      if (this.stuckFor > 1.8) this.restAfterBlockedRoute();
      return;
    }

    const moved = Math.hypot(next.x - this.x, next.y - this.y);
    this.x = next.x;
    this.y = next.y;
    const remaining = this.target ? Math.hypot(this.target.x - this.x, this.target.y - this.y) : 0;
    if (this.target && this.targetDistance - remaining > 0.15) {
      this.stuckFor = 0;
      this.targetDistance = remaining;
    } else {
      this.stuckFor += dt;
    }
    if (moved > 0.01) {
      this.heading = rotateToward(this.heading, Math.atan2(next.y - this.previousY, next.x - this.previousX), MAX_TURN_RATE * dt);
    }
    if (this.stuckFor > 1.8) this.restAfterBlockedRoute();
  }

  get current(): BehaviorSnapshot {
    return { status: this.status, x: this.x, y: this.y, heading: this.heading, target: this.target, path: this.path };
  }

  interpolated(alpha: number): BehaviorSnapshot {
    return {
      ...this.current,
      x: this.previousX + (this.x - this.previousX) * alpha,
      y: this.previousY + (this.y - this.previousY) * alpha,
    };
  }

  private beginNextJourney(): void {
    this.stuckFor = 0;
    if (this.pasture.drinkPoint && this.random() < 0.08) {
      const point = this.pasture.drinkPoint;
      const route = this.navigation.findPath({ x: this.x, y: this.y }, point);
      if (route?.length) {
        const safeWaterPoint = route[route.length - 1];
        this.status = 'WALK';
        this.target = safeWaterPoint;
        this.path = route;
        this.pathIndex = 0;
        this.targetDistance = Math.hypot(safeWaterPoint.x - this.x, safeWaterPoint.y - this.y);
        this.arrivedAtWater = true;
        this.speed = WALK_SPEED_MIN + this.random() * (WALK_SPEED_MAX - WALK_SPEED_MIN);
        return;
      }
    }
    this.chooseDestination();
  }

  private chooseDestination(): void {
    this.target = null;
    this.path = [];
    this.pathIndex = 0;
    this.stuckFor = 0;
    this.arrivedAtWater = false;
    for (let attempt = 0; attempt < 24; attempt += 1) {
      const candidate = this.navigation.randomTarget(this.pasture.bounds, () => this.random(), { x: this.x, y: this.y });
      if (!candidate || Math.hypot(candidate.x - this.x, candidate.y - this.y) < 90) continue;
      const route = this.navigation.findPath({ x: this.x, y: this.y }, candidate);
      if (!route?.length) continue;
      this.status = 'WALK';
      this.target = candidate;
      this.path = route;
      this.pathIndex = 0;
      this.targetDistance = Math.hypot(candidate.x - this.x, candidate.y - this.y);
      this.speed = WALK_SPEED_MIN + this.random() * (WALK_SPEED_MAX - WALK_SPEED_MIN);
      return;
    }
    // No teleport fallback: stay safely in place and try again after a short rest.
    this.status = 'REST';
    this.dwellRemaining = 2 + this.random() * 2;
  }

  private arrive(): void {
    this.velocityX = 0;
    this.velocityY = 0;
    this.path = [];
    this.pathIndex = 0;
    if (this.arrivedAtWater) {
      this.status = 'DRINK';
      this.dwellRemaining = 4 + this.random() * 4;
      return;
    }
    this.status = this.random() < 0.74 ? 'GRAZE' : 'REST';
    this.dwellRemaining = 5 + this.random() * 14;
    this.target = null;
  }

  private finishStop(): void {
    this.status = this.random() < 0.62 ? 'GRAZE' : this.random() < 0.58 ? 'REST' : 'IDLE';
    this.dwellRemaining = 5 + this.random() * 15;
    this.target = null;
    this.path = [];
    this.pathIndex = 0;
    this.velocityX = 0;
    this.velocityY = 0;
    this.arrivedAtWater = false;
  }

  private restAfterBlockedRoute(): void {
    this.status = 'REST';
    this.dwellRemaining = 2 + this.random() * 3;
    this.target = null;
    this.path = [];
    this.pathIndex = 0;
    this.stuckFor = 0;
    this.targetDistance = Number.POSITIVE_INFINITY;
    this.velocityX = 0;
    this.velocityY = 0;
    this.arrivedAtWater = false;
  }

  private separation(neighbors: readonly NeighborPosition[]): WorldPoint {
    let x = 0;
    let y = 0;
    for (const neighbor of neighbors) {
      const dx = this.x - neighbor.x;
      const dy = this.y - neighbor.y;
      const distance = Math.hypot(dx, dy);
      if (distance <= 0 || distance >= COW_SEPARATION_RADIUS) continue;
      const strength = (COW_SEPARATION_RADIUS - distance) / COW_SEPARATION_RADIUS;
      x += (dx / distance) * strength * 1.4;
      y += (dy / distance) * strength * 1.4;
    }
    return { x, y };
  }

  private canOccupy(point: WorldPoint, neighbors: readonly NeighborPosition[]): boolean {
    if (!this.navigation.isWalkable(point.x, point.y) ||
        this.navigation.getConnectedRegion(point) !== this.navigation.getConnectedRegion({ x: this.x, y: this.y }) ||
        !this.navigation.isWalkableSegment({ x: this.x, y: this.y }, point)) return false;
    return neighbors.every((neighbor) => neighbor.id === this.index ||
      Math.hypot(point.x - neighbor.x, point.y - neighbor.y) >= COW_SEPARATION_RADIUS - 1);
  }

  private findSafeStep(neighbors: readonly NeighborPosition[], dt: number): WorldPoint | null {
    const baseAngle = this.heading;
    const distance = Math.max(0.2, Math.min(this.speed * dt * 0.65, 0.7));
    for (const offset of [0.45, -0.45, 0.9, -0.9, 1.35, -1.35, Math.PI]) {
      const angle = baseAngle + offset;
      const candidate = { x: this.x + Math.cos(angle) * distance, y: this.y + Math.sin(angle) * distance };
      if (!this.canOccupy(candidate, neighbors)) continue;
      this.heading = rotateToward(baseAngle, angle, MAX_TURN_RATE * dt);
      return candidate;
    }
    return null;
  }

  private random(): number {
    this.randomState = (Math.imul(this.randomState, 1664525) + 1013904223) >>> 0;
    return this.randomState / 0x100000000;
  }
}

/** Fixed-rate herd update and spatial hash; independent of render-frame cadence. */
export class HerdController {
  private readonly animals: AnimalBehavior[] = [];
  private accumulator = 0;
  private readonly fixedStep = 1 / 20;
  private readonly cellSize = 48;
  private readonly spatialHash = new Map<string, NeighborPosition[]>();

  constructor(
    count: number,
    private readonly navigation: FarmNavigation,
    pastureFor: (index: number) => PastureZone,
    private readonly stationary = false,
  ) {
    for (let index = 0; index < count; index += 1) {
      const pasture = pastureFor(index);
      const spawn = navigation.findSpawn(pasture.bounds, () => this.seeded(index + 1), this.animals.map((animal) => animal.current));
      if (!spawn) throw new Error(`No safe farm spawn available for animal ${index}.`);
      this.animals.push(new AnimalBehavior(index, pasture, navigation, spawn, stationary));
    }
  }

  update(deltaMs: number, reducedMotion: boolean): void {
    if (reducedMotion || this.stationary) return;
    this.accumulator = Math.min(this.accumulator + Math.min(deltaMs, 100) / 1000, 0.25);
    while (this.accumulator >= this.fixedStep) {
      this.rebuildSpatialHash();
      for (const animal of this.animals) {
        const before = animal.current;
        animal.step(this.fixedStep, this.neighborsFor(before));
        this.updateSpatialHash(animal.index, before, animal.current);
      }
      this.accumulator -= this.fixedStep;
    }
  }

  getStates(interpolated = false): readonly BehaviorSnapshot[] {
    return this.animals.map((animal) => interpolated ? animal.interpolated(this.interpolationAlpha) : animal.current);
  }

  getDebugStates(): readonly BehaviorSnapshot[] { return this.getStates(); }

  get interpolationAlpha(): number { return this.accumulator / this.fixedStep; }

  private rebuildSpatialHash(): void {
    this.spatialHash.clear();
    for (const animal of this.animals) {
      const point = animal.current;
      const key = this.hashKey(point.x, point.y);
      const cell = this.spatialHash.get(key) ?? [];
      cell.push({ id: animal.index, x: point.x, y: point.y });
      this.spatialHash.set(key, cell);
    }
  }

  private updateSpatialHash(id: number, before: WorldPoint, after: WorldPoint): void {
    const oldKey = this.hashKey(before.x, before.y);
    const oldBucket = this.spatialHash.get(oldKey);
    if (oldBucket) {
      const index = oldBucket.findIndex((neighbor) => neighbor.id === id);
      if (index >= 0) oldBucket.splice(index, 1);
      if (!oldBucket.length) this.spatialHash.delete(oldKey);
    }
    const newKey = this.hashKey(after.x, after.y);
    const newBucket = this.spatialHash.get(newKey) ?? [];
    newBucket.push({ id, x: after.x, y: after.y });
    this.spatialHash.set(newKey, newBucket);
  }

  private neighborsFor(point: WorldPoint): NeighborPosition[] {
    const [cellX, cellY] = this.hashCoords(point.x, point.y);
    const neighbors: NeighborPosition[] = [];
    for (let dy = -1; dy <= 1; dy += 1) {
      for (let dx = -1; dx <= 1; dx += 1) neighbors.push(...(this.spatialHash.get(`${cellX + dx}:${cellY + dy}`) ?? []));
    }
    return neighbors;
  }

  private hashKey(x: number, y: number): string {
    const [cellX, cellY] = this.hashCoords(x, y);
    return `${cellX}:${cellY}`;
  }

  private hashCoords(x: number, y: number): [number, number] {
    return [Math.floor(x / this.cellSize), Math.floor(y / this.cellSize)];
  }

  private seeded(value: number): number {
    let seed = value >>> 0;
    seed = (Math.imul(seed ^ (seed >>> 16), 0x45d9f3b) ^ 0x9e3779b9) >>> 0;
    seed = (Math.imul(seed ^ (seed >>> 16), 0x45d9f3b) ^ 0x9e3779b9) >>> 0;
    return ((seed ^ (seed >>> 16)) >>> 0) / 0x100000000;
  }
}

function approach(value: number, target: number, amount: number): number {
  return value < target ? Math.min(target, value + amount) : Math.max(target, value - amount);
}

function rotateToward(current: number, target: number, maxStep: number): number {
  let delta = ((target - current + Math.PI * 3) % (Math.PI * 2)) - Math.PI;
  delta = Math.max(-maxStep, Math.min(maxStep, delta));
  return current + delta;
}
