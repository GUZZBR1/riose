"""Deterministic 2D farm and herd movement model.

All coordinates produced here belong to the simulation's ground-truth channel.
They are never copied into RFObservation records.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
import random
from typing import Mapping, Sequence

from ..domain.contracts import FarmConfig, GroundTruth


class Behavior(StrEnum):
    GRAZING = "GRAZING"
    WALKING = "WALKING"
    RESTING = "RESTING"
    RUNNING = "RUNNING"
    DRINKING = "DRINKING"
    GROUP_MOVEMENT = "GROUP_MOVEMENT"


@dataclass(frozen=True, slots=True)
class Obstacle:
    """Axis-aligned rectangle used by movement and RF propagation."""

    x_min: float
    y_min: float
    x_max: float
    y_max: float
    kind: str = "vegetation"
    attenuation_db: float | None = None

    def contains(self, x: float, y: float) -> bool:
        return self.x_min <= x <= self.x_max and self.y_min <= y <= self.y_max


DEFAULT_OBSTACLES = (
    Obstacle(420.0, 350.0, 580.0, 650.0, "barn", 22.0),
    Obstacle(180.0, 120.0, 240.0, 880.0, "trees", 8.0),
    Obstacle(760.0, 120.0, 820.0, 880.0, "vegetation", 5.0),
    Obstacle(640.0, 690.0, 720.0, 770.0, "reservoir", 12.0),
)


@dataclass(slots=True)
class AnimalState:
    tag_id: str
    x: float
    y: float
    vx: float
    vy: float
    behavior: Behavior
    goal_x: float
    goal_y: float
    behavior_until_s: float
    last_speed: float = 0.0


@dataclass(frozen=True, slots=True)
class MotionFeatures(Mapping[str, float | str]):
    """Compact, private sensor features aligned with one ground-truth sample.

    String indexing preserves the old dict-like access used by callers while
    avoiding one four-entry dictionary allocation for every animal/time pair.
    """

    timestamp_s: float
    tag_id: str
    imu_accel_norm_g: float
    behavior_state: str

    def __getitem__(self, key: str) -> float | str:
        if key == "timestamp_s":
            return self.timestamp_s
        if key == "tag_id":
            return self.tag_id
        if key == "imu_accel_norm_g":
            return self.imu_accel_norm_g
        if key == "behavior_state":
            return self.behavior_state
        raise KeyError(key)

    def __iter__(self):
        return iter(("timestamp_s", "tag_id", "imu_accel_norm_g", "behavior_state"))

    def __len__(self) -> int:
        return 4


def _inside_any(x: float, y: float, obstacles: Sequence[Obstacle]) -> bool:
    return any(o.contains(x, y) for o in obstacles)


def _point_segment_distance(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    denom = dx * dx + dy * dy
    if denom == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / denom))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def segment_crosses_obstacle(ax: float, ay: float, bx: float, by: float, obstacle: Obstacle) -> bool:
    """Return whether a line segment intersects a rectangle (Liang–Barsky)."""
    dx, dy = bx - ax, by - ay
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, ax - obstacle.x_min), (dx, obstacle.x_max - ax),
                 (-dy, ay - obstacle.y_min), (dy, obstacle.y_max - ay)):
        if p == 0:
            if q < 0:
                return False
            continue
        r = q / p
        if p < 0:
            if r > t1:
                return False
            t0 = max(t0, r)
        else:
            if r < t0:
                return False
            t1 = min(t1, r)
    return t0 <= t1


class FarmSimulator:
    """Seeded, correlated grazing/herding movement for a rectangular property."""

    def __init__(self, config: FarmConfig, obstacles: Sequence[Obstacle] | None = None,
                 escape_targets: Mapping[str, tuple[float, float]] | None = None):
        self.config = config
        self.obstacles = tuple(DEFAULT_OBSTACLES if obstacles is None else obstacles)
        self.escape_targets = dict(escape_targets or {})
        self.rng = random.Random(config.seed)
        self.states = self._initial_states()

    def _valid_point(self, x: float, y: float) -> bool:
        return not _inside_any(x, y, self.obstacles)

    def _random_point(self) -> tuple[float, float]:
        for _ in range(1000):
            x = self.rng.uniform(0.0, self.config.width_m)
            y = self.rng.uniform(0.0, self.config.height_m)
            if self._valid_point(x, y):
                return x, y
        return self.config.width_m / 2, self.config.height_m / 2

    def _initial_states(self) -> list[AnimalState]:
        states: list[AnimalState] = []
        # Seed the herd in several loose clusters rather than uniformly scattering it.
        clusters = max(1, math.ceil(self.config.animal_count / 25))
        centers = [self._random_point() for _ in range(clusters)]
        for i in range(self.config.animal_count):
            cx, cy = centers[i % clusters]
            for _ in range(100):
                x, y = self.rng.gauss(cx, min(45.0, self.config.width_m / 10)), self.rng.gauss(cy, min(45.0, self.config.height_m / 10))
                if 0 <= x <= self.config.width_m and 0 <= y <= self.config.height_m and self._valid_point(x, y):
                    break
            else:
                x, y = self._random_point()
            states.append(AnimalState(f"tag-{i + 1:04d}", x, y, 0.0, 0.0, Behavior.GRAZING,
                                      x, y, self.rng.uniform(180, 900)))
        return states

    def _choose_behavior(self, state: AnimalState, t: float) -> None:
        if state.tag_id in self.escape_targets:
            state.behavior = Behavior.WALKING
            state.goal_x, state.goal_y = self.escape_targets[state.tag_id]
            state.behavior_until_s = math.inf
            return
        # Group movement is a shared herd-level event; other states are per animal.
        if t < state.behavior_until_s:
            return
        draw = self.rng.random()
        if draw < 0.025:
            state.behavior = Behavior.RUNNING
            duration = self.rng.uniform(20, 90)
        elif draw < 0.10:
            state.behavior = Behavior.RESTING
            duration = self.rng.uniform(120, 600)
        elif draw < 0.16:
            state.behavior = Behavior.DRINKING
            duration = self.rng.uniform(60, 180)
        elif draw < 0.48:
            state.behavior = Behavior.WALKING
            duration = self.rng.uniform(90, 420)
        else:
            state.behavior = Behavior.GRAZING
            duration = self.rng.uniform(180, 900)
        state.goal_x = self.rng.uniform(0, self.config.width_m)
        state.goal_y = self.rng.uniform(0, self.config.height_m)
        if _inside_any(state.goal_x, state.goal_y, self.obstacles):
            state.goal_x, state.goal_y = self._random_point()
        state.behavior_until_s = t + duration

    def _step(self, t: float, dt: float) -> None:
        # A synchronized movement wave is occasional and spatially correlated.
        herd_event = (int(t // 1800) != int((t - dt) // 1800) and self.rng.random() < 0.35)
        if herd_event:
            heading = self.rng.uniform(-math.pi, math.pi)
            target_x = self.config.width_m * (0.5 + 0.38 * math.cos(heading))
            target_y = self.config.height_m * (0.5 + 0.38 * math.sin(heading))
            for state in self.states:
                state.behavior = Behavior.GROUP_MOVEMENT
                state.goal_x, state.goal_y = target_x, target_y
                state.behavior_until_s = t + self.rng.uniform(180, 540)

        for state in self.states:
            self._choose_behavior(state, t)
            if state.behavior == Behavior.RESTING:
                decay = math.exp(-dt / 8.0)
                state.vx *= decay
                state.vy *= decay
            else:
                dx, dy = state.goal_x - state.x, state.goal_y - state.y
                distance = math.hypot(dx, dy)
                speeds = {Behavior.GRAZING: 0.12, Behavior.WALKING: 0.8,
                          Behavior.RUNNING: 2.8, Behavior.DRINKING: 0.08,
                          Behavior.GROUP_MOVEMENT: 0.65, Behavior.RESTING: 0.0}
                speed = speeds[state.behavior]
                if distance > 1:
                    desired_vx, desired_vy = speed * dx / distance, speed * dy / distance
                    # Turn gradually, and add bounded local variation to avoid lockstep.
                    alpha = min(1.0, dt / 20.0)
                    state.vx += alpha * (desired_vx - state.vx) + self.rng.gauss(0, 0.025)
                    state.vy += alpha * (desired_vy - state.vy) + self.rng.gauss(0, 0.025)
            nx = state.x + state.vx * dt
            ny = state.y + state.vy * dt
            if state.tag_id not in self.escape_targets:
                nx = max(0.0, min(self.config.width_m, nx))
                ny = max(0.0, min(self.config.height_m, ny))
            if any(segment_crosses_obstacle(state.x, state.y, nx, ny, o) for o in self.obstacles):
                # Reflect at the edge: reverse the component with the largest obstacle overlap.
                state.vx *= -0.55
                state.vy *= -0.55
                nx = max(0.0, min(self.config.width_m, state.x + state.vx * dt))
                ny = max(0.0, min(self.config.height_m, state.y + state.vy * dt))
                if _inside_any(nx, ny, self.obstacles):
                    nx, ny = state.x, state.y
                    state.vx = state.vy = 0.0
            state.x, state.y = nx, ny

    def generate(self) -> tuple[tuple[GroundTruth, ...], tuple[MotionFeatures, ...]]:
        """Return truth samples and private sensor-motion features by sample."""
        truth: list[GroundTruth] = []
        motion: list[MotionFeatures] = []
        dt_sample = self.config.sample_period_s
        steps = max(1, math.ceil(self.config.duration_s / dt_sample))
        for step in range(steps):
            timestamp = min(step * dt_sample, self.config.duration_s)
            if step:
                self._step(timestamp, dt_sample)
            for s in self.states:
                truth.append(GroundTruth(timestamp, s.tag_id, s.x, s.y))
                speed = math.hypot(s.vx, s.vy)
                # Simulated IMU magnitude proxy, noisy but not a coordinate-derived feature.
                accel = max(0.0, abs(speed - s.last_speed) / max(dt_sample, 1e-6) + self.rng.gauss(0, 0.015))
                motion.append(MotionFeatures(
                    timestamp, s.tag_id,
                    max(0.75, min(2.5, 1.0 + accel)), s.behavior.value,
                ))
                s.last_speed = speed
        return tuple(truth), tuple(motion)
