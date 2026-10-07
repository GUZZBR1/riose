"""Deterministic 2D farm and herd movement model.

All coordinates produced here belong to the simulation's ground-truth channel.
They are never copied into RFObservation records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import math
import random
from time import perf_counter_ns
from typing import Mapping, Sequence

from ..domain.contracts import FarmConfig, GroundTruth


SIMULATION_FIXED_DT_S = 1.0 / 30.0
SPATIAL_CELL_M = 16.0
ORCA_TIME_HORIZON_S = 3.0

# Provisional capsule footprint, measured against the assembled OBJ proportions
# in frontend/src/scene.tsx. The source OBJ files have no calibrated units, so
# these dimensions are assumptions pending physical model calibration.
CATTLE_CAPSULE_HALF_LENGTH_M = 0.88
CATTLE_CAPSULE_RADIUS_M = 0.56
CATTLE_CLEARANCE_M = 0.18
CATTLE_BOUNDING_RADIUS_M = CATTLE_CAPSULE_HALF_LENGTH_M + CATTLE_CAPSULE_RADIUS_M
COLLISION_RADIUS_M = CATTLE_BOUNDING_RADIUS_M + CATTLE_CLEARANCE_M / 2
class Behavior(StrEnum):
    GRAZING = "GRAZING"
    WALKING = "WALKING"
    RESTING = "RESTING"
    RUNNING = "RUNNING"
    DRINKING = "DRINKING"
    GROUP_MOVEMENT = "GROUP_MOVEMENT"


BEHAVIOR_SPEED_MPS = {
    Behavior.GRAZING: 0.0,
    Behavior.WALKING: 0.66,
    Behavior.RUNNING: 1.25,
    Behavior.DRINKING: 0.05,
    Behavior.GROUP_MOVEMENT: 0.54,
    Behavior.RESTING: 0.0,
}


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

# The browser scene is composed in an 84 m illustrative square. Keep this
# physical movement layout separate from DEFAULT_OBSTACLES, which also feeds RF
# propagation and must not be shifted by visual asset changes.
DEFAULT_COLLISION_OBSTACLES = (
    Obstacle(427.0, 464.0, 559.0, 583.0, "barn"),
    Obstacle(180.0, 120.0, 240.0, 880.0, "trees"),
    Obstacle(760.0, 120.0, 820.0, 880.0, "vegetation"),
    Obstacle(152.0, 687.0, 205.0, 719.0, "trough"),
    # Thin no-pass segments correspond to the visible internal paddock fences.
    # Their gaps remain traversable, matching the rendered farm layout.
    Obstacle(237.0, 131.0, 240.0, 357.0, "fence"),
    Obstacle(237.0, 417.0, 240.0, 869.0, "fence"),
    Obstacle(677.0, 131.0, 680.0, 274.0, "fence"),
    Obstacle(677.0, 333.0, 680.0, 869.0, "fence"),
    Obstacle(237.0, 308.0, 429.0, 311.0, "fence"),
    Obstacle(511.0, 308.0, 680.0, 311.0, "fence"),
    Obstacle(237.0, 713.0, 393.0, 716.0, "fence"),
    Obstacle(452.0, 713.0, 680.0, 716.0, "fence"),
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
    heading: float = 0.0
    preferred_speed_scale: float = 1.0
    perception_range_m: float = 13.0
    social_spacing_m: float = 0.32
    rng: random.Random = field(default_factory=random.Random, repr=False, compare=False)


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
                 escape_targets: Mapping[str, tuple[float, float]] | None = None,
                 *, collision_obstacles: Sequence[Obstacle] | None = None):
        self.config = config
        self.obstacles = tuple(DEFAULT_OBSTACLES if obstacles is None else obstacles)
        if collision_obstacles is not None:
            self.collision_obstacles = tuple(collision_obstacles)
        elif obstacles is not None:
            self.collision_obstacles = tuple(obstacles)
        else:
            scale_x, scale_y = config.width_m / 1000.0, config.height_m / 1000.0
            self.collision_obstacles = tuple(
                Obstacle(o.x_min * scale_x, o.y_min * scale_y,
                         o.x_max * scale_x, o.y_max * scale_y, o.kind)
                for o in DEFAULT_COLLISION_OBSTACLES
            )
        self._expanded_collision_obstacles = tuple(
            Obstacle(o.x_min - COLLISION_RADIUS_M, o.y_min - COLLISION_RADIUS_M,
                     o.x_max + COLLISION_RADIUS_M, o.y_max + COLLISION_RADIUS_M, o.kind)
            for o in self.collision_obstacles
        )
        self._collision_obstacle_grid: dict[tuple[int, int], list[int]] = {}
        for obstacle_index, obstacle in enumerate(self._expanded_collision_obstacles):
            min_x, min_y = self._cell(obstacle.x_min, obstacle.y_min)
            max_x, max_y = self._cell(obstacle.x_max, obstacle.y_max)
            for cell_x in range(min_x, max_x + 1):
                for cell_y in range(min_y, max_y + 1):
                    self._collision_obstacle_grid.setdefault((cell_x, cell_y), []).append(obstacle_index)
        self.escape_targets = dict(escape_targets or {})
        self.rng = random.Random(config.seed)
        self._fixed_steps = 0
        self._time_accumulator = 0.0
        self._diagnostics = {
            "collision_events": 0,
            "max_penetration_m": 0.0,
            "residual_overlap_m": 0.0,
            "blocked_animals": set(),
            "moving_animals": 0,
            "grazing_seconds": 0.0,
            "step_durations_ns": [],
        }
        self.states = self._initial_states()

    @property
    def diagnostics(self) -> dict[str, object]:
        timings = self._diagnostics["step_durations_ns"]
        ordered = sorted(timings)  # type: ignore[arg-type]
        def percentile(value: float) -> float:
            if not ordered:
                return 0.0
            return ordered[min(len(ordered) - 1, math.ceil((len(ordered) - 1) * value))] / 1_000_000
        return {
            "collision_events": self._diagnostics["collision_events"],
            "max_penetration_m": self._diagnostics["max_penetration_m"],
            "residual_overlap_m": self._diagnostics["residual_overlap_m"],
            "blocked_animals": len(self._diagnostics["blocked_animals"]),
            "moving_animals": self._diagnostics["moving_animals"],
            "grazing_seconds": round(float(self._diagnostics["grazing_seconds"]), 2),
            "simulation_step_ms_p95": round(percentile(.95), 4),
            "simulation_step_ms_p99": round(percentile(.99), 4),
        }

    def _valid_point(self, x: float, y: float, margin: float = COLLISION_RADIUS_M) -> bool:
        if x < margin or y < margin or x > self.config.width_m - margin or y > self.config.height_m - margin:
            return False
        if math.isclose(margin, COLLISION_RADIUS_M):
            candidates = self._collision_obstacle_grid.get(self._cell(x, y), ())
            obstacles = (self.collision_obstacles[index] for index in candidates)
        else:
            obstacles = iter(self.collision_obstacles)
        for obstacle in obstacles:
            nearest_x = max(obstacle.x_min, min(x, obstacle.x_max))
            nearest_y = max(obstacle.y_min, min(y, obstacle.y_max))
            if math.hypot(x - nearest_x, y - nearest_y) < margin:
                return False
        return True

    def _random_point(self, margin: float = COLLISION_RADIUS_M) -> tuple[float, float]:
        for _ in range(10_000):
            x = self.rng.uniform(margin, self.config.width_m - margin)
            y = self.rng.uniform(margin, self.config.height_m - margin)
            if self._valid_point(x, y, margin):
                return x, y
        raise ValueError("farm has no valid collision-free placement region for cattle")

    def _wander_target(self, x: float, y: float, minimum: float, maximum: float,
                       rng: random.Random | None = None) -> tuple[float, float]:
        """Sample a nearby destination so ordinary movement stays local and pasture-like."""
        maximum = min(maximum, math.hypot(self.config.width_m, self.config.height_m) * 0.3)
        minimum = min(minimum, maximum)
        source = rng or self.rng
        for _ in range(32):
            # Uniform area sampling avoids overpopulating the inner part of the radius.
            distance = math.sqrt(source.uniform(minimum * minimum, maximum * maximum))
            angle = source.uniform(-math.pi, math.pi)
            target_x = max(0.0, min(self.config.width_m, x + math.cos(angle) * distance))
            target_y = max(0.0, min(self.config.height_m, y + math.sin(angle) * distance))
            if (self._valid_point(target_x, target_y)
                    and math.hypot(target_x - x, target_y - y) > 2
                    and not self._segment_hits_obstacle(x, y, target_x, target_y, CATTLE_BOUNDING_RADIUS_M)):
                return target_x, target_y
        return x, y

    @staticmethod
    def _cell(x: float, y: float) -> tuple[int, int]:
        return math.floor(x / SPATIAL_CELL_M), math.floor(y / SPATIAL_CELL_M)

    def _candidate_indices(self, grid: dict[tuple[int, int], list[int]], x: float, y: float,
                           reach: float) -> list[int]:
        cell_x, cell_y = self._cell(x, y)
        radius = math.ceil(reach / SPATIAL_CELL_M)
        result: list[int] = []
        for gx in range(cell_x - radius, cell_x + radius + 1):
            for gy in range(cell_y - radius, cell_y + radius + 1):
                result.extend(grid.get((gx, gy), ()))
        return result

    def _segment_hits_obstacle(self, ax: float, ay: float, bx: float, by: float, margin: float) -> bool:
        if math.isclose(margin, COLLISION_RADIUS_M):
            min_x, min_y = self._cell(min(ax, bx), min(ay, by))
            max_x, max_y = self._cell(max(ax, bx), max(ay, by))
            candidates: set[int] = set()
            for cell_x in range(min_x, max_x + 1):
                for cell_y in range(min_y, max_y + 1):
                    candidates.update(self._collision_obstacle_grid.get((cell_x, cell_y), ()))
            obstacles = (self._expanded_collision_obstacles[index] for index in sorted(candidates))
        else:
            obstacles = (Obstacle(o.x_min - margin, o.y_min - margin,
                                  o.x_max + margin, o.y_max + margin, o.kind)
                         for o in self.collision_obstacles)
        for expanded in obstacles:
            if segment_crosses_obstacle(ax, ay, bx, by, expanded):
                return True
        return False

    @staticmethod
    def _capsule_segment(state: AnimalState) -> tuple[float, float, float, float]:
        dx = math.cos(state.heading) * CATTLE_CAPSULE_HALF_LENGTH_M
        dy = math.sin(state.heading) * CATTLE_CAPSULE_HALF_LENGTH_M
        return state.x - dx, state.y - dy, state.x + dx, state.y + dy

    @staticmethod
    def _segment_closest_points(a: tuple[float, float, float, float],
                                b: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        ax, ay, bx, by = a
        cx, cy, dx, dy = b
        ux, uy = bx - ax, by - ay
        vx, vy = dx - cx, dy - cy
        wx, wy = ax - cx, ay - cy
        aa, bb, cc = ux * ux + uy * uy, ux * vx + uy * vy, vx * vx + vy * vy
        dd, ee = ux * wx + uy * wy, vx * wx + vy * wy
        denom = aa * cc - bb * bb
        s = max(0.0, min(1.0, (bb * ee - cc * dd) / denom)) if denom > 1e-12 else 0.0
        t = max(0.0, min(1.0, (bb * s + ee) / cc)) if cc > 1e-12 else 0.0
        s = max(0.0, min(1.0, (bb * t - dd) / aa)) if aa > 1e-12 else 0.0
        return ax + ux * s, ay + uy * s, cx + vx * t, cy + vy * t

    @classmethod
    def _capsule_clearance(cls, first: AnimalState, second: AnimalState) -> tuple[float, float, float]:
        p1x, p1y, p2x, p2y = cls._segment_closest_points(cls._capsule_segment(first), cls._capsule_segment(second))
        dx, dy = p1x - p2x, p1y - p2y
        distance = math.hypot(dx, dy)
        return distance - 2 * CATTLE_CAPSULE_RADIUS_M, dx, dy

    def _initial_states(self) -> list[AnimalState]:
        states: list[AnimalState] = []
        # Seed the herd in several loose clusters rather than uniformly scattering it.
        clusters = max(1, math.ceil(self.config.animal_count / 25))
        centers = [self._random_point() for _ in range(clusters)]
        for i in range(self.config.animal_count):
            animal_rng = random.Random(self.config.seed * 1_000_003 + (i + 1) * 97_409)
            cx, cy = centers[i % clusters]
            for _ in range(1000):
                x, y = self.rng.gauss(cx, min(45.0, self.config.width_m / 10)), self.rng.gauss(cy, min(45.0, self.config.height_m / 10))
                if self._valid_point(x, y) and all(
                    math.hypot(x - placed.x, y - placed.y) >= 2 * COLLISION_RADIUS_M
                    for placed in states
                ):
                    break
            else:
                for _ in range(5000):
                    x, y = self._random_point()
                    if all(math.hypot(x - placed.x, y - placed.y) >= 2 * COLLISION_RADIUS_M
                           for placed in states):
                        break
                else:
                    raise ValueError("farm cannot fit the requested herd without overlapping cattle")
            activity = animal_rng.random()
            if activity < 0.62:
                behavior = Behavior.GRAZING
                duration = animal_rng.uniform(90, 300)
                goal_x, goal_y = self._wander_target(x, y, 12, 55, animal_rng)
            elif activity < 0.81:
                behavior, duration = Behavior.RESTING, animal_rng.uniform(45, 180)
                goal_x, goal_y = x, y
            elif activity < 0.98:
                behavior, duration = Behavior.WALKING, animal_rng.uniform(60, 210)
                goal_x, goal_y = self._wander_target(x, y, 45, 125, animal_rng)
            else:
                behavior, duration = Behavior.DRINKING, animal_rng.uniform(50, 150)
                goal_x, goal_y = self._wander_target(x, y, 4, 20, animal_rng)
            heading = animal_rng.uniform(-math.pi, math.pi)
            states.append(AnimalState(f"tag-{i + 1:04d}", x, y, 0.0, 0.0, behavior,
                                      goal_x, goal_y, duration, heading=heading,
                                      preferred_speed_scale=animal_rng.uniform(0.92, 1.08),
                                      perception_range_m=animal_rng.uniform(11.0, 16.0),
                                      social_spacing_m=animal_rng.uniform(0.24, 0.48),
                                      rng=animal_rng))
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
        draw = state.rng.random()
        if draw < 0.01:
            state.behavior = Behavior.RUNNING
            duration = state.rng.uniform(20, 90)
        elif draw < 0.19:
            state.behavior = Behavior.RESTING
            duration = state.rng.uniform(45, 210)
        elif draw < 0.25:
            state.behavior = Behavior.DRINKING
            duration = state.rng.uniform(50, 180)
        elif draw < 0.48:
            state.behavior = Behavior.WALKING
            duration = state.rng.uniform(60, 240)
        else:
            state.behavior = Behavior.GRAZING
            duration = state.rng.uniform(90, 360)
        if state.behavior == Behavior.RESTING:
            state.goal_x, state.goal_y = state.x, state.y
        elif state.behavior in (Behavior.WALKING, Behavior.GROUP_MOVEMENT, Behavior.RUNNING):
            state.goal_x, state.goal_y = self._wander_target(state.x, state.y, 45, 150, state.rng)
        else:
            state.goal_x, state.goal_y = self._wander_target(state.x, state.y, 8, 45, state.rng)
        state.behavior_until_s = t + duration

    def _step(self, t: float, dt: float) -> None:
        """Advance a deterministic 30 Hz controller; output cadence is independent."""
        if dt <= 0:
            return
        self._time_accumulator += dt
        steps = int((self._time_accumulator + 1e-10) / SIMULATION_FIXED_DT_S)
        for _ in range(steps):
            self._time_accumulator -= SIMULATION_FIXED_DT_S
            self._fixed_steps += 1
            self._step_once(self._fixed_steps * SIMULATION_FIXED_DT_S, SIMULATION_FIXED_DT_S)

    def _obstacle_hit(self, x: float, y: float, nx: float, ny: float) -> bool:
        return self._segment_hits_obstacle(x, y, nx, ny, COLLISION_RADIUS_M)

    def _preferred_velocity(self, state: AnimalState, speed: float, dt: float) -> tuple[float, float]:
        dx, dy = state.goal_x - state.x, state.goal_y - state.y
        distance = math.hypot(dx, dy)
        if distance < 0.8 or speed <= 0:
            return 0.0, 0.0
        braking_speed = min(speed, math.sqrt(max(0.0, 2.0 * 0.22 * distance)))
        # Per-animal stochastic bias avoids repeated paths without changing the goal.
        wander = state.rng.uniform(-0.055, 0.055)
        angle = math.atan2(dy, dx) + wander
        preferred_speed = braking_speed * state.rng.uniform(0.94, 1.0)
        return math.cos(angle) * preferred_speed, math.sin(angle) * preferred_speed

    def _safe_velocity(self, index: int, preferred: tuple[float, float], speed_limit: float,
                       neighbors: list[int], snapshot: list[tuple[float, float, float, float]],
                       dt: float) -> tuple[float, float]:
        """Reciprocal velocity-obstacle candidate search with turn-rate limits.

        Each animal chooses a nearby velocity using the same reciprocal share of
        predicted collision correction. A hard positional projection follows it.
        """
        state = self.states[index]
        px, py = preferred
        preferred_mag = math.hypot(px, py)
        preferred_angle = math.atan2(py, px) if preferred_mag > 1e-5 else state.heading
        max_turn = 0.85 * dt
        turn_error = math.atan2(math.sin(preferred_angle - state.heading), math.cos(preferred_angle - state.heading))
        reachable_heading = state.heading + max(-max_turn, min(max_turn, turn_error))
        candidates: list[tuple[float, float]] = [(0.0, 0.0)]
        for angle_offset in (-max_turn, 0.0, max_turn):
            angle = reachable_heading + angle_offset
            for speed_fraction in (1.0, 0.62):
                candidates.append((math.cos(angle) * min(preferred_mag, speed_limit) * speed_fraction,
                                   math.sin(angle) * min(preferred_mag, speed_limit) * speed_fraction))

        x, y, vx, vy = snapshot[index]
        neighbor_data = []
        for other_index in neighbors:
            if other_index == index:
                continue
            other_state = self.states[other_index]
            ox, oy, ovx, ovy = snapshot[other_index]
            rx, ry = ox - x, oy - y
            if math.hypot(rx, ry) > max(state.perception_range_m, other_state.perception_range_m):
                continue
            required = 2.0 * COLLISION_RADIUS_M + (state.social_spacing_m + other_state.social_spacing_m) / 2
            neighbor_data.append((rx, ry, ovx, ovy, required))
        best = (0.0, 0.0)
        best_cost = math.inf
        for cvx, cvy in candidates:
            mag = math.hypot(cvx, cvy)
            if mag > speed_limit and mag > 0:
                cvx *= speed_limit / mag
                cvy *= speed_limit / mag
            cost = math.hypot(cvx - px, cvy - py) * 1.6
            if mag < 0.04 and preferred_mag > 0.05:
                cost += 1.25
            # Reciprocal velocity-obstacle penalty over a short prediction horizon.
            for rx, ry, ovx, ovy, required in neighbor_data:
                rvx, rvy = cvx - ovx, cvy - ovy
                denominator = rvx * rvx + rvy * rvy
                closest_t = 0.0 if denominator < 1e-9 else max(0.0, min(ORCA_TIME_HORIZON_S,
                    -(rx * rvx + ry * rvy) / denominator))
                gap = math.hypot(rx + rvx * closest_t, ry + rvy * closest_t)
                if gap < required:
                    urgency = 1.0 + max(0.0, required - math.hypot(rx, ry)) / required
                    cost += ((required - gap) / required) ** 2 * 18.0 * urgency
            # Preserve some progress when the safe set is narrow; zero velocity
            # is only preferred when every moving candidate is less safe.
            cost += max(0.0, preferred_mag - mag) * 0.16
            if cost < best_cost:
                best_cost, best = cost, (cvx, cvy)
        return best

    def _step_once(self, t: float, dt: float) -> None:
        started = perf_counter_ns()
        for state in self.states:
            self._choose_behavior(state, t)

        # Snapshot + spatial hash make every animal solve from the same state.
        snapshot = [(s.x, s.y, s.vx, s.vy) for s in self.states]
        grid: dict[tuple[int, int], list[int]] = {}
        for index, state in enumerate(self.states):
            grid.setdefault(self._cell(state.x, state.y), []).append(index)
        max_speed = 2.0
        reach = ORCA_TIME_HORIZON_S * (max_speed * 2.0) + 2 * COLLISION_RADIUS_M + 0.5
        velocities: list[tuple[float, float]] = [(0.0, 0.0)] * len(self.states)
        old_positions = [(s.x, s.y) for s in self.states]
        next_positions: list[tuple[float, float]] = [(s.x, s.y) for s in self.states]

        for index, state in enumerate(self.states):
            if state.behavior == Behavior.RESTING:
                preferred = (0.0, 0.0)
            else:
                preferred = self._preferred_velocity(state, BEHAVIOR_SPEED_MPS[state.behavior], dt)
            neighbors = self._candidate_indices(grid, state.x, state.y, reach)
            limit = max(BEHAVIOR_SPEED_MPS[state.behavior] * state.preferred_speed_scale, math.hypot(*preferred))
            safe_vx, safe_vy = self._safe_velocity(index, preferred, max(limit, 0.1), neighbors, snapshot, dt)
            # Acceleration-limited integration prevents instant starts/stops.
            dvx, dvy = safe_vx - state.vx, safe_vy - state.vy
            dv = math.hypot(dvx, dvy)
            max_dv = (0.45 if math.hypot(*preferred) < math.hypot(state.vx, state.vy) else 0.30) * dt
            if dv > max_dv and dv > 0:
                dvx *= max_dv / dv
                dvy *= max_dv / dv
            velocities[index] = (state.vx + dvx, state.vy + dvy)

        for index, state in enumerate(self.states):
            vx, vy = velocities[index]
            nx, ny = state.x + vx * dt, state.y + vy * dt
            if state.tag_id in self.escape_targets:
                # Preserve the explicit adversarial escape test hook.
                nx, ny = state.x + vx * dt, state.y + vy * dt
            elif not self._valid_point(nx, ny, COLLISION_RADIUS_M) or self._obstacle_hit(state.x, state.y, nx, ny):
                nx, ny = state.x, state.y
                vx = vy = 0.0
                self._diagnostics["blocked_animals"].add(state.tag_id)
            state.vx, state.vy = vx, vy
            next_positions[index] = (nx, ny)

        # Hard non-penetration constraint on conservative circular bounds around
        # the provisional oriented-capsule body. Iterate to settle dense pairs.
        required = 2.0 * COLLISION_RADIUS_M
        for _ in range(4):
            moved = False
            for i, first in enumerate(self.states):
                fx, fy = next_positions[i]
                for j in self._candidate_indices(grid, fx, fy, required + 0.5):
                    if j <= i:
                        continue
                    sx, sy = next_positions[j]
                    dx, dy = sx - fx, sy - fy
                    distance = math.hypot(dx, dy)
                    penetration = required - distance
                    if penetration <= 0:
                        continue
                    self._diagnostics["collision_events"] += 1
                    self._diagnostics["max_penetration_m"] = max(
                        float(self._diagnostics["max_penetration_m"]), penetration)
                    if distance < 1e-8:
                        angle = (i * 2.399963229728653) % (2 * math.pi)
                        nx, ny = math.cos(angle), math.sin(angle)
                    else:
                        nx, ny = dx / distance, dy / distance
                    correction = penetration / 2 + 1e-3
                    proposed_i = (fx - nx * correction, fy - ny * correction)
                    proposed_j = (sx + nx * correction, sy + ny * correction)
                    if (self._valid_point(*proposed_i, COLLISION_RADIUS_M)
                            and self._valid_point(*proposed_j, COLLISION_RADIUS_M)):
                        next_positions[i], next_positions[j] = proposed_i, proposed_j
                        moved = True
                    else:
                        # Do not push a body through an obstacle to solve another contact.
                        next_positions[i] = old_positions[i]
                        next_positions[j] = old_positions[j]
                        self.states[i].vx = self.states[i].vy = 0.0
                        self.states[j].vx = self.states[j].vy = 0.0
                        self._diagnostics["blocked_animals"].update((first.tag_id, self.states[j].tag_id))
            if not moved:
                break

        moving = 0
        for index, state in enumerate(self.states):
            old_x, old_y = old_positions[index]
            state.x, state.y = next_positions[index]
            speed = math.hypot(state.vx, state.vy)
            if speed > 0.035:
                desired_heading = math.atan2(state.vy, state.vx)
                turn = math.atan2(math.sin(desired_heading - state.heading), math.cos(desired_heading - state.heading))
                turn = max(-0.85 * dt, min(0.85 * dt, turn))
                state.heading += turn
                moving += 1
            else:
                state.vx *= math.exp(-dt * 3.0)
                state.vy *= math.exp(-dt * 3.0)
            if state.behavior == Behavior.GRAZING:
                self._diagnostics["grazing_seconds"] = float(self._diagnostics["grazing_seconds"]) + dt
        residual = 0.0
        for index, state in enumerate(self.states):
            for other_index in self._candidate_indices(grid, state.x, state.y, required + 0.5):
                if other_index <= index:
                    continue
                other = self.states[other_index]
                residual = max(residual, required - math.hypot(state.x - other.x, state.y - other.y))
        self._diagnostics["residual_overlap_m"] = max(float(self._diagnostics["residual_overlap_m"]), residual)
        self._diagnostics["moving_animals"] = moving
        samples = self._diagnostics["step_durations_ns"]
        samples.append(perf_counter_ns() - started)
        if len(samples) > 6000:
            del samples[:len(samples) - 6000]

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
