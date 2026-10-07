export type Evidence = 'VALIDATED' | 'SIMULATED' | 'ASSUMED' | 'EXPERIMENTAL' | 'FUTURE';

export interface Animal {
  animal_id: string;
  hardware_id: string;
  name: string | null;
  sex?: string | null;
  breed?: string | null;
  weight_kg?: number | null;
  property_name?: string | null;
  lot?: string | null;
}

export interface Estimate {
  timestamp: number;
  tag_id: string;
  x: number | null;
  y: number | null;
  method: string;
  quality: number | null;
  status: Evidence;
}

export interface Anchor {
  anchor_id: string;
  x: number;
  y: number;
  height_m: number;
  kind: string;
  enabled: boolean;
}

export interface Telemetry {
  timestamp: number;
  tag_id: string;
  anchor_id: string;
  rssi_dbm: number | null;
  snr_db: number | null;
  packet_received: boolean;
  imu_accel_norm_g: number | null;
  behavior_state: string | null;
  status: Evidence;
}

export interface AnimalEvent {
  event_id: number;
  animal_id: string;
  event_type: string;
  timestamp: number;
  payload: Record<string, unknown> | null;
  hash?: string;
}

export interface SimulationState {
  status: 'empty' | 'paused' | 'playing' | 'ended';
  time_s: number;
  start_s: number;
  end_s: number;
  speed: number;
  run_id: string | null;
  evidence: 'SIMULATED';
}

export interface FarmSnapshot {
  type: 'snapshot';
  simulation: SimulationState;
  sample_period_s?: number;
  animals: Animal[];
  positions: Estimate[];
  scene_positions?: ScenePosition[];
  anchors: Anchor[];
  telemetry: Telemetry[];
  events: AnimalEvent[];
  metrics: Record<string, unknown> & {
    farm?: { width_m?: number; height_m?: number };
    evidence?: Evidence;
  };
  evidence: 'SIMULATED';
}

export interface ScenePosition {
  timestamp: number;
  tag_id: string;
  x: number;
  y: number;
}

export interface SceneAnimal extends Animal {
  estimate: Estimate | null;
  scenePosition: ScenePosition | null;
  movementState: string;
  lastSignalTimestamp: number | null;
  rssiDbm: number | null;
  snrDb: number | null;
  receivedLinks: number;
  orientation: number;
}

export interface TrajectoryPoint {
  timestamp: number;
  tag_id: string;
  x: number | null;
  y: number | null;
  quality: number | null;
  status: Evidence;
}
