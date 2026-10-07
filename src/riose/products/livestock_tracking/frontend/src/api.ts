import type { AnimalEvent, FarmSnapshot, SimulationState, TrajectoryPoint } from './types';

type JsonRecord = Record<string, unknown>;

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function nonEmpty(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function optionalFinite(value: unknown): boolean {
  return value === null || value === undefined || finite(value);
}

export function validateFarmSnapshot(value: unknown): { snapshot: FarmSnapshot; issues: string[] } | null {
  if (!isRecord(value) || value.type !== 'snapshot' || value.evidence !== 'SIMULATED') return null;
  const issues: string[] = [];
  const list = (field: string): unknown[] | null => {
    const candidate = value[field];
    if (Array.isArray(candidate)) return candidate;
    issues.push(`${field}: expected an array`);
    return null;
  };
  const simulation = value.simulation;
  if (!isRecord(simulation)
    || !['empty', 'paused', 'playing', 'ended'].includes(String(simulation.status))
    || !finite(simulation.time_s) || !finite(simulation.start_s) || !finite(simulation.end_s)
    || !finite(simulation.speed) || !(simulation.run_id === null || typeof simulation.run_id === 'string')
    || simulation.evidence !== 'SIMULATED') {
    return null;
  }
  const animalsRaw = list('animals');
  const positionsRaw = list('positions');
  const anchorsRaw = list('anchors');
  const telemetryRaw = list('telemetry');
  const eventsRaw = list('events');
  const scenePositionsRaw = value.scene_positions === undefined ? [] : list('scene_positions');
  if (!animalsRaw || !positionsRaw || !anchorsRaw || !telemetryRaw || !eventsRaw || !scenePositionsRaw || !isRecord(value.metrics)) return null;
  if (value.scene_positions === undefined) issues.push('scene_positions: missing; legacy snapshot has no simulator pose channel');

  const filterRecords = <T,>(field: string, rows: unknown[], reason: (row: JsonRecord) => string | null): T[] => rows.flatMap((row, index) => {
    const issue = !isRecord(row) ? 'record must be an object' : reason(row);
    if (issue === null && isRecord(row)) return [row as T];
    const id = isRecord(row) ? (row.animal_id ?? row.tag_id ?? row.anchor_id ?? row.event_id ?? 'unknown') : 'unknown';
    issues.push(`${field}[${index}] id=${String(id)}: ${issue}`);
    return [];
  });
  const animals = filterRecords<FarmSnapshot['animals'][number]>('animals', animalsRaw, (row) =>
    !nonEmpty(row.animal_id) ? 'animal_id must be a non-empty string'
      : !nonEmpty(row.hardware_id) ? 'hardware_id must be a non-empty string'
        : row.name !== null && row.name !== undefined && typeof row.name !== 'string' ? 'name must be a string or null' : null);
  const positions = filterRecords<FarmSnapshot['positions'][number]>('positions', positionsRaw, (row) =>
    !finite(row.timestamp) ? 'timestamp must be finite'
      : !nonEmpty(row.tag_id) ? 'tag_id must be a non-empty string'
        : !optionalFinite(row.x) || !optionalFinite(row.y) ? 'x and y must be finite numbers or null'
          : !nonEmpty(row.method) ? 'method must be a non-empty string'
            : !optionalFinite(row.quality) ? 'quality must be finite or null' : !nonEmpty(row.status) ? 'status must be a non-empty string' : null);
  const scenePositions = filterRecords<NonNullable<FarmSnapshot['scene_positions']>[number]>('scene_positions', scenePositionsRaw, (row) =>
    !finite(row.timestamp) ? 'timestamp must be finite'
      : !nonEmpty(row.tag_id) ? 'tag_id must be a non-empty string'
        : !finite(row.x) || !finite(row.y) ? 'simulator x/y must both be finite numbers' : null);
  const anchors = filterRecords<FarmSnapshot['anchors'][number]>('anchors', anchorsRaw, (row) =>
    !nonEmpty(row.anchor_id) ? 'anchor_id must be a non-empty string'
      : !finite(row.x) || !finite(row.y) || !finite(row.height_m) ? 'x, y and height_m must be finite numbers'
        : !nonEmpty(row.kind) ? 'kind must be a non-empty string' : typeof row.enabled !== 'boolean' ? 'enabled must be boolean' : null);
  const telemetry = filterRecords<FarmSnapshot['telemetry'][number]>('telemetry', telemetryRaw, (row) =>
    !finite(row.timestamp) ? 'timestamp must be finite'
      : !nonEmpty(row.tag_id) || !nonEmpty(row.anchor_id) ? 'tag_id and anchor_id must be non-empty strings'
        : !optionalFinite(row.rssi_dbm) || !optionalFinite(row.snr_db) || !optionalFinite(row.imu_accel_norm_g) ? 'signal and IMU values must be finite or null'
          : typeof row.packet_received !== 'boolean' ? 'packet_received must be boolean'
            : row.behavior_state !== null && row.behavior_state !== undefined && typeof row.behavior_state !== 'string' ? 'behavior_state must be a string or null'
              : !nonEmpty(row.status) ? 'status must be a non-empty string' : null);
  const events = filterRecords<AnimalEvent>('events', eventsRaw, (row) =>
    !Number.isSafeInteger(row.event_id) ? 'event_id must be an integer'
      : !nonEmpty(row.animal_id) || !nonEmpty(row.event_type) ? 'animal_id and event_type must be non-empty strings'
        : !finite(row.timestamp) ? 'timestamp must be finite'
          : row.payload !== null && row.payload !== undefined && !isRecord(row.payload) ? 'payload must be an object or null' : null);
  const snapshot: FarmSnapshot = {
    type: 'snapshot',
    simulation: simulation as unknown as FarmSnapshot['simulation'],
    sample_period_s: finite(value.sample_period_s) ? value.sample_period_s : undefined,
    animals,
    positions,
    scene_positions: scenePositions,
    anchors,
    telemetry,
    events,
    metrics: value.metrics as FarmSnapshot['metrics'],
    evidence: 'SIMULATED',
  };
  return { snapshot, issues };
}

export function openFarmStream(
  onSnapshot: (snapshot: FarmSnapshot) => void,
  onConnection: (connected: boolean) => void,
  onError: (message: string) => void,
): () => void {
  let socket: WebSocket | null = null;
  let reconnectTimer = 0;
  let pollTimer = 0;
  let connectionTimer = 0;
  let messageTimer = 0;
  let delay = 500;
  let stopped = false;
  let hasSnapshot = false;
  let connected = false;
  let websocketSnapshotSeen = false;
  let previousIssueSignature = '';

  const reportSnapshot = (value: unknown): boolean => {
    const validated = validateFarmSnapshot(value);
    if (!validated) {
      console.error('[Riose] Rejected farm snapshot: invalid top-level schema or evidence label.');
      onError('The farm service returned an invalid snapshot schema.');
      return false;
    }
    const issueSignature = validated.issues.join('\n');
    if (issueSignature && issueSignature !== previousIssueSignature) {
      console.warn('[Riose] Farm snapshot records rejected by field validation:', validated.issues);
    }
    previousIssueSignature = issueSignature;
    try {
      onSnapshot(validated.snapshot);
      hasSnapshot = true;
      if (validated.issues.length === 0) onError('');
      return true;
    } catch (error) {
      console.error('[Riose] Could not apply farm snapshot', error);
      onError('The farm snapshot could not be applied.');
      return false;
    }
  };

  const bootstrapSnapshot = async () => {
    if (stopped) return;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch('/api/farm/snapshot', { signal: controller.signal, cache: 'no-store' });
      if (!response.ok) throw new Error(`Farm snapshot failed (${response.status}).`);
      const payload: unknown = await response.json();
      if (stopped || websocketSnapshotSeen) return;
      reportSnapshot(payload);
      if (!connected && !stopped && !pollTimer) {
        pollTimer = window.setInterval(() => { void bootstrapSnapshot(); }, 1500);
      }
    } catch (error) {
      if (!stopped && !hasSnapshot) {
        onError(error instanceof Error && error.name === 'AbortError'
          ? 'Farm connection timed out while loading animal positions.'
          : error instanceof Error ? error.message : 'Farm snapshot could not be loaded.');
      }
    } finally {
      window.clearTimeout(timeout);
    }
  };

  const connect = () => {
    if (stopped) return;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    try {
      socket = new WebSocket(`${protocol}//${window.location.host}/ws/farm`);
    } catch (error) {
      onConnection(false);
      onError(error instanceof Error ? error.message : 'Farm WebSocket could not be opened.');
      scheduleReconnect();
      return;
    }
    const activeSocket = socket;
    let socketHasSnapshot = false;
    connectionTimer = window.setTimeout(() => {
      if (activeSocket.readyState === WebSocket.CONNECTING) {
        onError('Farm WebSocket connection timed out; using snapshot fallback.');
        activeSocket.close();
      }
    }, 5000);
    activeSocket.onopen = () => {
      if (stopped || socket !== activeSocket) return;
      window.clearTimeout(connectionTimer);
      connected = true;
      delay = 500;
      onConnection(true);
      window.clearInterval(pollTimer);
      pollTimer = 0;
      messageTimer = window.setTimeout(() => {
        if (connected && !socketHasSnapshot) {
          onError('Farm WebSocket connected but sent no animal snapshot; using HTTP fallback.');
          activeSocket.close();
        }
      }, 5000);
    };
    activeSocket.onmessage = (event) => {
      if (stopped || socket !== activeSocket) return;
      window.clearTimeout(messageTimer);
      let payload: unknown;
      try {
        payload = JSON.parse(event.data);
      } catch (error) {
        console.error('[Riose] Could not parse farm snapshot', error);
        onError('The farm stream returned an invalid snapshot.');
      }
      if (payload !== undefined) {
        socketHasSnapshot = reportSnapshot(payload);
        if (socketHasSnapshot) {
          websocketSnapshotSeen = true;
          onError('');
        }
      }
      if (connected) {
        messageTimer = window.setTimeout(() => {
          onError('Farm WebSocket stopped sending updates; using HTTP fallback.');
          activeSocket.close();
        }, 5000);
      }
    };
    activeSocket.onerror = () => {
      if (stopped || socket !== activeSocket) return;
      connected = false;
      onConnection(false);
      if (!hasSnapshot) onError('Farm WebSocket failed; trying the HTTP snapshot fallback.');
    };
    activeSocket.onclose = () => {
      if (stopped || socket !== activeSocket) return;
      window.clearTimeout(connectionTimer);
      connected = false;
      websocketSnapshotSeen = false;
      onConnection(false);
      void bootstrapSnapshot();
      if (!stopped) scheduleReconnect();
    };
  };

  function scheduleReconnect() {
    if (stopped || reconnectTimer) return;
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = 0;
      connect();
    }, delay);
    delay = Math.min(delay * 1.7, 8000);
  }

  void bootstrapSnapshot();
  connect();
  return () => {
    stopped = true;
    window.clearTimeout(reconnectTimer);
    window.clearTimeout(connectionTimer);
    window.clearTimeout(messageTimer);
    window.clearInterval(pollTimer);
    socket?.close();
  };
}

export async function postSimulationControl(action: 'start' | 'pause' | 'reset' | 'speed', speed?: number): Promise<SimulationState> {
  const response = await fetch('/api/simulation/control', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, ...(speed === undefined ? {} : { speed }) }),
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Simulation control failed (${response.status}).`);
  }
  return response.json() as Promise<SimulationState>;
}

export async function createDemoSimulation(input: {
  width_m: number;
  height_m: number;
  animal_count: number;
  anchors: Array<{ anchor_id: string; x: number; y: number; height_m: number; kind: string; enabled: boolean }>;
}): Promise<string> {
  const response = await fetch('/api/simulation/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      ...input,
      anchor_count: input.anchors.length,
      duration_s: 360,
      // Keep the demo's RF estimate cadence responsive enough for live visual
      // interpolation; the simulator integrates motion independently at 30 Hz.
      sample_period_s: 2,
      seed: 7,
      packet_loss_probability: 0.05,
      method: 'weighted_centroid',
    }),
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Farm simulation could not be prepared (${response.status}).`);
  }
  const result = await response.json() as { run_id?: string };
  if (!result.run_id) throw new Error('The farm simulator did not return a run ID.');
  return result.run_id;
}

export async function loadTrajectory(animalId: string, runId?: string | null): Promise<TrajectoryPoint[]> {
  const runQuery = runId ? `&run_id=${encodeURIComponent(runId)}` : '';
  const response = await fetch(`/api/animals/${encodeURIComponent(animalId)}/trajectory?limit=500${runQuery}`);
  if (!response.ok) throw new Error(`Trajectory unavailable (${response.status}).`);
  return response.json() as Promise<TrajectoryPoint[]>;
}

export async function loadAnimalEvents(animalId: string): Promise<AnimalEvent[]> {
  const response = await fetch('/api/events?limit=1000');
  if (!response.ok) throw new Error(`Event history unavailable (${response.status}).`);
  const events = await response.json() as AnimalEvent[];
  return events.filter((event) => event.animal_id === animalId).slice(0, 12);
}

export interface DigitalAssetState {
  status: string;
  evidence: string;
  asset_address?: string | null;
  explorer_url?: string | null;
  valid?: boolean;
}

interface AssetTokenizationModule {
  getAnimalAsset(animalId: string): Promise<DigitalAssetState>;
  mintAnimalAsset(animalId: string): Promise<DigitalAssetState>;
  assetExplorerUrl(address: string): string;
}

let assetModule: Promise<AssetTokenizationModule> | null = null;
async function tokenization(): Promise<AssetTokenizationModule> {
  const runtimeUrl = '/assets/animal-tokenization.bundle.js';
  assetModule ??= import(/* @vite-ignore */ runtimeUrl) as Promise<AssetTokenizationModule>;
  return assetModule;
}

export async function getDigitalAsset(animalId: string): Promise<DigitalAssetState> {
  const module = await tokenization();
  return module.getAnimalAsset(animalId);
}

export async function createDigitalAsset(animalId: string): Promise<DigitalAssetState> {
  const module = await tokenization();
  return module.mintAnimalAsset(animalId);
}

export async function digitalAssetExplorer(address: string): Promise<string> {
  const module = await tokenization();
  return module.assetExplorerUrl(address);
}
