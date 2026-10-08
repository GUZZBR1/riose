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

export interface AnimalBehaviorOptions {
  seed?: number;
  minimumTripDistance?: number;
  walkSpeedMin?: number;
  walkSpeedMax?: number;
  interactionChance?: number;
  interactionRoles?: Record<number, 'drink' | 'shade'>;
  interactionDwellMin?: number;
  interactionDwellMax?: number;
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
  private arrivalState: 'DRINK' | 'SHADE' | null = null;
  private manuallyControlled = false;
  private readonly options: Required<AnimalBehaviorOptions>;

  constructor(
    readonly index: number,
    private readonly pasture: PastureZone,
    private readonly navigation: FarmNavigation,
    spawn: WorldPoint,
    private readonly stationary = false,
    options: AnimalBehaviorOptions = {},
  ) {
    this.options = {
      seed: options.seed ?? 0,
      minimumTripDistance: options.minimumTripDistance ?? 90,
      walkSpeedMin: options.walkSpeedMin ?? WALK_SPEED_MIN,
      walkSpeedMax: options.walkSpeedMax ?? WALK_SPEED_MAX,
      interactionChance: options.interactionChance ?? 0.08,
      interactionRoles: options.interactionRoles ?? {},
      interactionDwellMin: options.interactionDwellMin ?? 12,
      interactionDwellMax: options.interactionDwellMax ?? 22,
    };
    this.randomState = (0x9e3779b9 ^ this.options.seed ^ Math.imul(index + 1, 0x85ebca6b)) >>> 0;
    this.x = spawn.x;
    this.y = spawn.y;
    this.previousX = spawn.x;
    this.previousY = spawn.y;
    this.heading = (this.random() * 2 - 1) * Math.PI;
    const place = this.random() * 100;
    this.status = stationary
      ? (place < 56 ? 'GRAZE' : place < 76 ? 'REST' : 'IDLE')
      : (place < 56 ? 'GRAZE' : place < 76 ? 'REST' : place < 96 ? 'WALK' : 'IDLE');
    this.dwellRemaining = 4 + this.random() * 11;
    if (!stationary) {
      const role = this.options.interactionRoles[index];
      if (!role || !this.chooseInteractionJourney(role)) {
        if (this.status === 'WALK') this.chooseDestination();
      }
    }
  }

  step(dt: number, neighbors: readonly NeighborPosition[]): void {
    if (this.stationary || this.manuallyControlled) return;
    this.previousX = this.x;
    this.previousY = this.y;

    if ((this.status === 'DRINK' || this.status === 'SHADE') && this.arrivalState) {
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

  beginManualMove(): void {
    this.manuallyControlled = true;
    this.velocityX = 0;
    this.velocityY = 0;
    this.target = null;
    this.path = [];
    this.pathIndex = 0;
    this.arrivalState = null;
    this.previousX = this.x;
    this.previousY = this.y;
  }

  moveManualTo(point: WorldPoint): void {
    if (!this.manuallyControlled) return;
    const dx = point.x - this.x;
    const dy = point.y - this.y;
    if (Math.hypot(dx, dy) > 0.01) this.heading = Math.atan2(dy, dx);
    this.x = point.x;
    this.y = point.y;
    this.previousX = point.x;
    this.previousY = point.y;
    this.status = 'IDLE';
  }

  endManualMove(): void {
    if (!this.manuallyControlled) return;
    this.manuallyControlled = false;
    this.status = 'GRAZE';
    this.dwellRemaining = 4;
    this.target = null;
    this.path = [];
    this.pathIndex = 0;
    this.velocityX = 0;
    this.velocityY = 0;
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
    const role = this.options.interactionRoles[this.index];
    if (role && this.random() < 0.78 && this.chooseInteractionJourney(role)) return;
    if (!role && this.random() < this.options.interactionChance && this.chooseInteractionJourney()) return;
    this.chooseDestination();
  }

  private chooseInteractionJourney(preferredKind?: 'drink' | 'shade'): boolean {
    const eligible = (this.navigation.definition.interactionPoints ?? []).filter((point) =>
      (point.kind === 'drink' || point.kind === 'shade') && (!preferredKind || point.kind === preferredKind) &&
      Math.hypot(point.point.x - this.x, point.point.y - this.y) > 58);
    if (!eligible.length) return false;
    const startIndex = Math.floor(this.random() * eligible.length);
    for (let offset = 0; offset < eligible.length; offset += 1) {
      const interaction = eligible[(startIndex + offset) % eligible.length];
      const route = this.navigation.findPath({ x: this.x, y: this.y }, interaction.point);
      if (!route?.length) continue;
      const safePoint = route[route.length - 1];
      this.status = 'WALK';
      this.target = safePoint;
      this.path = route;
      this.pathIndex = 0;
      this.targetDistance = Math.hypot(safePoint.x - this.x, safePoint.y - this.y);
      this.arrivalState = interaction.kind === 'shade' ? 'SHADE' : 'DRINK';
      this.speed = this.options.walkSpeedMin + this.random() * (this.options.walkSpeedMax - this.options.walkSpeedMin);
      return true;
    }
    return false;
  }

  private chooseDestination(): void {
    this.target = null;
    this.path = [];
    this.pathIndex = 0;
    this.stuckFor = 0;
    this.arrivalState = null;
    for (let attempt = 0; attempt < 24; attempt += 1) {
      const candidate = this.navigation.randomTarget(this.pasture.bounds, () => this.random(), { x: this.x, y: this.y });
      if (!candidate || Math.hypot(candidate.x - this.x, candidate.y - this.y) < this.options.minimumTripDistance) continue;
      const route = this.navigation.findPath({ x: this.x, y: this.y }, candidate);
      if (!route?.length) continue;
      this.status = 'WALK';
      this.target = candidate;
      this.path = route;
      this.pathIndex = 0;
      this.targetDistance = Math.hypot(candidate.x - this.x, candidate.y - this.y);
      this.speed = this.options.walkSpeedMin + this.random() * (this.options.walkSpeedMax - this.options.walkSpeedMin);
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
    if (this.arrivalState) {
      this.status = this.arrivalState;
      this.dwellRemaining = this.options.interactionDwellMin + this.random() *
        (this.options.interactionDwellMax - this.options.interactionDwellMin);
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
    this.arrivalState = null;
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
    this.arrivalState = null;
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
  private readonly manualMoveRegions = new Map<number, number>();

  constructor(
    count: number,
    private readonly navigation: FarmNavigation,
    pastureFor: (index: number) => PastureZone,
    private readonly stationary = false,
    private readonly options: AnimalBehaviorOptions = {},
  ) {
    for (let index = 0; index < count; index += 1) {
      const pasture = pastureFor(index);
      const spawn = navigation.findSpawn(pasture.bounds, () => this.seeded(index + 1, options.seed ?? 0), this.animals.map((animal) => animal.current));
      if (!spawn) throw new Error(`No safe farm spawn available for animal ${index}.`);
      this.animals.push(new AnimalBehavior(index, pasture, navigation, spawn, stationary, options));
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

  beginManualMove(index: number): boolean {
    const animal = this.animals[index];
    if (!animal) return false;
    this.manualMoveRegions.set(index, this.navigation.getConnectedRegion(animal.current));
    animal.beginManualMove();
    return true;
  }

  moveManualAnimal(index: number, point: WorldPoint): boolean {
    const animal = this.animals[index];
    const region = this.manualMoveRegions.get(index);
    if (!animal || region === undefined || !Number.isFinite(point.x) || !Number.isFinite(point.y)) return false;
    const start = animal.current;
    const distance = Math.hypot(point.x - start.x, point.y - start.y);
    const steps = Math.max(1, Math.ceil(distance / 4));
    let lastSafe = { x: start.x, y: start.y };
    for (let step = 1; step <= steps; step += 1) {
      const candidate = {
        x: start.x + (point.x - start.x) * step / steps,
        y: start.y + (point.y - start.y) * step / steps,
      };
      if (!this.navigation.isWalkable(candidate.x, candidate.y) ||
          this.navigation.getConnectedRegion(candidate) !== region ||
          !this.navigation.isWalkableSegment(lastSafe, candidate)) break;
      const overlaps = this.animals.some((other) => other.index !== index &&
        Math.hypot(candidate.x - other.current.x, candidate.y - other.current.y) < COW_SEPARATION_RADIUS - 1);
      if (overlaps) break;
      lastSafe = candidate;
    }
    if (Math.hypot(lastSafe.x - start.x, lastSafe.y - start.y) < 0.1) return false;
    animal.moveManualTo(lastSafe);
    return true;
  }

  endManualMove(index: number): void {
    const animal = this.animals[index];
    if (!animal || !this.manualMoveRegions.has(index)) return;
    animal.endManualMove();
    this.manualMoveRegions.delete(index);
  }

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

  private seeded(value: number, farmSeed: number): number {
    let seed = (value ^ farmSeed) >>> 0;
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
