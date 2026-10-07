import type { AnimalStatus } from '../types';
import type { PastureZone } from './farm-layout';

export interface BehaviorSnapshot {
  status: AnimalStatus;
  x: number;
  y: number;
  heading: number;
}

/** A per-animal deterministic schedule; no shared/random update cadence. */
export class AnimalBehavior {
  private elapsed = 0;
  private waypointIndex: number;
  private status: AnimalStatus;
  private x: number;
  private y: number;
  private heading: number;
  private readonly phase: number;

  constructor(private readonly index: number, private readonly pasture: PastureZone) {
    this.phase = (index * 1.731) % 9;
    this.heading = [-Math.PI / 2, 0, Math.PI / 2, Math.PI][index % 4];
    this.waypointIndex = index % pasture.waypoints.length;
    const start = pasture.waypoints[this.waypointIndex];
    this.x = start.x + ((index % 3) - 1) * 9;
    this.y = start.y + ((Math.floor(index / 3) % 3) - 1) * 8;
    this.status = this.statusAt(this.phase);
  }

  update(deltaMs: number, reducedMotion: boolean): BehaviorSnapshot {
    if (reducedMotion) return this.snapshot();
    const dt = Math.min(deltaMs, 50) / 1000;
    this.elapsed += dt;
    const cycle = (this.elapsed + this.phase) % 22;
    this.status = this.statusAt(cycle);

    if (this.status === 'WALK' || this.status === 'DRINK') {
      const target = this.status === 'DRINK' && this.pasture.waterPoint
        ? this.pasture.waterPoint
        : this.pasture.waypoints[(this.waypointIndex + 1) % this.pasture.waypoints.length];
      const dx = target.x - this.x;
      const dy = target.y - this.y;
      const distance = Math.hypot(dx, dy);
      this.heading = Math.atan2(dy, dx);
      const speed = this.status === 'DRINK' ? 17 : 13 + (this.index % 4) * 1.25;
      const step = Math.min(distance, dt * speed);
      if (distance > 0.5) {
        this.x += (dx / distance) * step;
        this.y += (dy / distance) * step;
      }
      if (distance < 5) this.waypointIndex = (this.waypointIndex + 1) % this.pasture.waypoints.length;
    }
    return this.snapshot();
  }

  get current(): BehaviorSnapshot { return this.snapshot(); }

  private snapshot(): BehaviorSnapshot {
    return { status: this.status, x: this.x, y: this.y, heading: this.heading };
  }

  private statusAt(time: number): AnimalStatus {
    const t = ((time % 22) + 22) % 22;
    // Staggered dwell windows keep the herd from changing state together.
    const offset = (this.index * 2.37) % 7;
    const shifted = (t + offset) % 22;
    if (shifted < 7.2) return 'GRAZE';
    if (shifted < 9.1) return 'WALK';
    if (shifted < 11.2 && this.pasture.waterPoint) return 'DRINK';
    if (shifted < 13.4) return 'IDLE';
    if (shifted < 16.8) return 'WALK';
    if (shifted < 20.2) return 'GRAZE';
    return 'IDLE';
  }
}
