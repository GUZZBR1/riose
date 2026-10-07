import { Component, Suspense, useCallback, useEffect, useMemo, useRef, type ErrorInfo, type ReactNode, type RefObject } from 'react';
import { useFrame, useLoader, useThree, type ThreeEvent } from '@react-three/fiber';
import { CameraControls, useTexture } from '@react-three/drei';
import type CameraControlsImpl from 'camera-controls';
import * as THREE from 'three';
import { OBJLoader } from 'three/addons/loaders/OBJLoader.js';
import { mergeGeometries, mergeVertices } from 'three/addons/utils/BufferGeometryUtils.js';
import type { Anchor, SceneAnimal, Telemetry, TrajectoryPoint } from './types';
import { deterministicUnit, farmToWorld, farmWorldSize, SCENE_DEPTH, SCENE_WIDTH, terrainHeight, terrainNormal } from './world';

const COW_BASE = '/assets/farm/cow';
const SHOW_FARM_DIAGNOSTICS = import.meta.env.DEV || (
  new URLSearchParams(window.location.search).get('diagnostics') === '1'
  && /^(localhost|127\.0\.0\.1)$/.test(window.location.hostname)
);
const COW_FILES = ['torso', 'neck', 'head', 'ear', 'leg', 'hoof'] as const;
const COW_URLS = COW_FILES.map((name) => `${COW_BASE}/${name}.obj`);
const COW_TEXTURES = [`${COW_BASE}/cow_coat.png`, `${COW_BASE}/cow_skin.png`];
useLoader.preload(OBJLoader, COW_URLS);
useTexture.preload(COW_TEXTURES);
const fencePostGeometry = new THREE.CylinderGeometry(0.08, 0.1, 1, 8);
const fenceRailGeometry = new THREE.CylinderGeometry(0.07, 0.07, 1, 8);

type CowGeometryKey = 'torso' | 'neck' | 'head' | 'ear' | 'leg' | 'hoof' | 'tag' | 'tail'
  | 'coat-patch' | 'far-body' | 'far-neck' | 'far-head' | 'far-patch' | 'far-leg' | 'far-tag';
type CowPart = {
  key: CowGeometryKey;
  geometry: THREE.BufferGeometry;
  material: 'coat' | 'skin' | 'hoof' | 'tag' | 'patch';
  pose: THREE.Matrix4;
  legIndex?: number;
  hip?: [number, number, number];
  strideOffset?: number;
};

type CowLod = 0 | 1 | 2;

type HoofMotion = {
  x: number; y: number; z: number;
  previousX: number; previousY: number; previousZ: number;
  swingStartX: number; swingStartZ: number;
  swingEndX: number; swingEndZ: number;
  swinging: boolean;
};

type CowMotion = {
  x: number; z: number; previousX: number; previousZ: number;
  targetX: number; targetZ: number; lastEstimateX: number; lastEstimateZ: number;
  yaw: number; previousYaw: number; targetYaw: number;
  sample: number; phase: number; runId: string | null;
  gaitPhase: number; previousGaitPhase: number;
  speed: number; targetSpeed: number; accumulator: number;
  rootY: number; previousRootY: number;
  displayScale: number; lod: CowLod;
  feet: HoofMotion[];
};

class CowAssetBoundary extends Component<{ children: ReactNode; onError: (message: string) => void }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, _info: ErrorInfo) {
    console.error('[Riose] Cattle scene assets failed to load', error);
    this.props.onError(error.message || 'Unknown cattle asset error');
  }

  render() {
    return this.state.failed ? null : this.props.children;
  }
}

function objectGeometry(object: THREE.Object3D): THREE.BufferGeometry {
  object.updateMatrixWorld(true);
  const parts: THREE.BufferGeometry[] = [];
  object.traverse((node) => {
    const mesh = node as THREE.Mesh;
    if (!mesh.isMesh) return;
    const geometry = mesh.geometry.clone();
    geometry.applyMatrix4(mesh.matrixWorld);
    parts.push(geometry);
  });
  if (!parts.length) throw new Error('The project cattle mesh contains no geometry.');
  const merged = parts.length === 1 ? parts[0] : mergeGeometries(parts, false);
  if (!merged) throw new Error('The project cattle meshes could not be combined for instancing.');
  merged.computeVertexNormals();
  return merged;
}

function partMatrix(
  position: [number, number, number],
  rotation: [number, number, number] = [0, 0, 0],
  scale: [number, number, number] = [1, 1, 1],
): THREE.Matrix4 {
  return new THREE.Matrix4().compose(
    new THREE.Vector3(...position),
    new THREE.Quaternion().setFromEuler(new THREE.Euler(...rotation)),
    new THREE.Vector3(...scale),
  );
}

function Terrain({ lowQuality, onDoubleClick }: { lowQuality: boolean; onDoubleClick: (point: THREE.Vector3) => void }) {
  const geometry = useMemo(() => {
    const columns = lowQuality ? 48 : 128;
    const rows = lowQuality ? 36 : 96;
    const positions: number[] = [];
    const colors: number[] = [];
    const indices: number[] = [];
    const low = new THREE.Color('#64754e');
    const mid = new THREE.Color('#839361');
    const high = new THREE.Color('#a7ad79');
    for (let row = 0; row <= rows; row += 1) {
      const z = (row / rows - 0.5) * SCENE_DEPTH;
      for (let column = 0; column <= columns; column += 1) {
        const x = (column / columns - 0.5) * SCENE_WIDTH;
        positions.push(x, terrainHeight(x, z) - 0.08, z);
        const wave = 0.52 + 0.20 * Math.sin(x * 0.18) + 0.17 * Math.cos(z * 0.16) + 0.1 * Math.sin((x - z) * 0.31);
        const color = wave < 0.48 ? low.clone().lerp(mid, wave / 0.48) : mid.clone().lerp(high, Math.min(1, (wave - 0.48) / 0.52));
        colors.push(color.r, color.g, color.b);
        if (column < columns && row < rows) {
          const a = row * (columns + 1) + column;
          const b = a + columns + 1;
          indices.push(a, b, a + 1, b, b + 1, a + 1);
        }
      }
    }
    const result = new THREE.BufferGeometry();
    result.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    result.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
    result.setIndex(indices);
    result.computeVertexNormals();
    return result;
  }, [lowQuality]);

  return <mesh geometry={geometry} receiveShadow={!lowQuality} onDoubleClick={(event) => { event.stopPropagation(); onDoubleClick(event.point); }}>
    {lowQuality ? <meshLambertMaterial vertexColors /> : <meshStandardMaterial vertexColors roughness={1} />}
  </mesh>;
}

function Grass({ lowQuality }: { lowQuality: boolean }) {
  const ref = useRef<THREE.InstancedMesh>(null);
  const count = lowQuality ? 180 : 4600;
  const geometry = useMemo(() => {
    const result = new THREE.BufferGeometry();
    result.setAttribute('position', new THREE.Float32BufferAttribute([
      -0.07, 0, 0, 0.07, 0, 0, 0.015, 0.38, 0,
      0, 0, -0.07, 0, 0, 0.07, -0.035, 0.29, 0,
      -0.055, 0, -0.045, 0.055, 0, 0.045, 0.02, 0.32, 0,
    ], 3));
    result.setIndex([0, 1, 2, 3, 4, 5, 6, 7, 8]);
    result.computeVertexNormals();
    return result;
  }, []);
  const instances = useMemo(() => Array.from({ length: count }, (_, index) => {
    const cluster = index % 9;
    const centers = [[-33, -28], [-15, -32], [15, -31], [33, -26], [-34, 12], [-20, 32], [4, 30], [28, 32], [34, 4]];
    const [cx, cz] = centers[cluster];
    const x = THREE.MathUtils.clamp(cx + (deterministicUnit(index + 81) - 0.5) * 25, -SCENE_WIDTH / 2 + 2, SCENE_WIDTH / 2 - 2);
    const z = THREE.MathUtils.clamp(cz + (deterministicUnit(index + 734) - 0.5) * 22, -SCENE_DEPTH / 2 + 2, SCENE_DEPTH / 2 - 2);
    const scale = 0.55 + deterministicUnit(index + 411) * 1.1;
    const rotation = deterministicUnit(index + 912) * Math.PI;
    const tint = 0.22 + deterministicUnit(index + 641) * 0.12;
    return { x, z, scale, rotation, tint };
  }), [count]);
  useEffect(() => {
    if (!ref.current) return;
    const dummy = new THREE.Object3D();
    instances.forEach(({ x, z, scale, rotation, tint }, index) => {
      dummy.position.set(x, terrainHeight(x, z) + 0.06, z);
      dummy.rotation.set(0, rotation, 0);
      dummy.scale.setScalar(scale);
      dummy.updateMatrix();
      ref.current?.setMatrixAt(index, dummy.matrix);
      ref.current?.setColorAt(index, new THREE.Color().setHSL(tint, 0.28, 0.37 + tint * 0.35));
    });
    ref.current.instanceMatrix.needsUpdate = true;
    if (ref.current.instanceColor) ref.current.instanceColor.needsUpdate = true;
  }, [instances]);
  const material = useMemo(() => {
    if (lowQuality) return new THREE.MeshLambertMaterial({ color: '#ffffff', vertexColors: true, side: THREE.DoubleSide });
    const result = new THREE.MeshStandardMaterial({ color: '#ffffff', roughness: 1, vertexColors: true, side: THREE.DoubleSide });
    result.onBeforeCompile = (shader) => {
      shader.uniforms.uWindTime = { value: 0 };
      shader.vertexShader = shader.vertexShader.replace('#include <common>', '#include <common>\nuniform float uWindTime;');
      shader.vertexShader = shader.vertexShader.replace('#include <begin_vertex>', '#include <begin_vertex>\ntransformed.x += sin(uWindTime + instanceMatrix[3].x * 0.23 + instanceMatrix[3].z * 0.18) * max(position.y, 0.0) * 0.11;');
      result.userData.windShader = shader;
    };
    result.customProgramCacheKey = () => 'riose-grass-wind-v1';
    return result;
  }, [lowQuality]);
  useFrame((state) => {
    if (lowQuality) return;
    const shader = material.userData.windShader as { uniforms: { uWindTime: { value: number } } } | undefined;
    if (shader) shader.uniforms.uWindTime.value = state.clock.elapsedTime * 0.48;
  });
  return <instancedMesh ref={ref} args={[geometry, material, count]} frustumCulled={false} />;
}

function ShrubClusters({ lowQuality }: { lowQuality: boolean }) {
  const ref = useRef<THREE.InstancedMesh>(null);
  const count = lowQuality ? 32 : 224;
  const plants = useMemo(() => Array.from({ length: count }, (_, index) => {
    const centers = [[-34, -30], [-30, 30], [32, -29], [35, 28], [-18, -36], [15, -37], [-36, 5], [36, 8]];
    const [cx, cz] = centers[index % centers.length];
    const x = THREE.MathUtils.clamp(cx + (deterministicUnit(index + 92) - 0.5) * 13, -39, 39);
    const z = THREE.MathUtils.clamp(cz + (deterministicUnit(index + 942) - 0.5) * 12, -39, 39);
    const scale = 0.3 + deterministicUnit(index + 31) * 0.6;
    return { x, z, scale, tint: deterministicUnit(index + 121) };
  }), [count]);
  useEffect(() => {
    const dummy = new THREE.Object3D();
    plants.forEach(({ x, z, scale, tint }, index) => {
      dummy.position.set(x, terrainHeight(x, z) + scale * 0.35, z);
      dummy.scale.set(scale * 1.2, scale * 0.76, scale);
      dummy.rotation.y = deterministicUnit(index + 44) * Math.PI;
      dummy.updateMatrix();
      ref.current?.setMatrixAt(index, dummy.matrix);
      ref.current?.setColorAt(index, new THREE.Color().setHSL(0.24 + tint * 0.1, 0.25 + tint * 0.16, 0.25 + tint * 0.12));
    });
    if (ref.current) {
      ref.current.instanceMatrix.needsUpdate = true;
      if (ref.current.instanceColor) ref.current.instanceColor.needsUpdate = true;
    }
  }, [plants]);
  return <instancedMesh ref={ref} args={[undefined as unknown as THREE.BufferGeometry, undefined as unknown as THREE.Material, count]} castShadow={!lowQuality}>
    <dodecahedronGeometry args={[0.72, lowQuality ? 0 : 1]} />{lowQuality ? <meshLambertMaterial vertexColors flatShading /> : <meshStandardMaterial vertexColors roughness={1} flatShading />}
  </instancedMesh>;
}

function FarmPaths() {
  const geometry = useMemo(() => {
    const routes = [
      { points: [[-39, 27], [-29, 24], [-17, 15], [-8, 9], [-2, 4], [0, 1]] as [number, number][], width: 0.24 },
      { points: [[0, 1], [9, 5], [17, 11], [23, 19], [31, 25], [39, 24]] as [number, number][], width: 0.2 },
      { points: [[-2, 3], [-8, -5], [-13, -13], [-19, -22], [-28, -30]] as [number, number][], width: 0.16 },
    ];
    const positions: number[] = [];
    const indices: number[] = [];
    let offset = 0;
    routes.forEach(({ points, width }) => {
      const curve = new THREE.CatmullRomCurve3(points.map(([x, z]) => new THREE.Vector3(x, 0, z)), false, 'centripetal');
      const segments = 96;
      for (let index = 0; index <= segments; index += 1) {
        const t = index / segments;
        const point = curve.getPointAt(t);
        const tangent = curve.getTangentAt(t);
        const perpendicular = new THREE.Vector3(-tangent.z, 0, tangent.x).normalize().multiplyScalar(width / 2);
        for (const direction of [-1, 1]) {
          const x = point.x + perpendicular.x * direction;
          const z = point.z + perpendicular.z * direction;
          positions.push(x, terrainHeight(x, z) + 0.025, z);
        }
        if (index < segments) {
          const a = offset + index * 2;
          indices.push(a, a + 1, a + 2, a + 1, a + 3, a + 2);
        }
      }
      offset += (segments + 1) * 2;
    });
    const result = new THREE.BufferGeometry();
    result.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    result.setIndex(indices);
    result.computeVertexNormals();
    return result;
  }, []);
  return <mesh geometry={geometry} receiveShadow><meshStandardMaterial color="#b8a982" roughness={1} side={THREE.DoubleSide} /></mesh>;
}

function TreeLine({ lowQuality }: { lowQuality: boolean }) {
  const trunks = useRef<THREE.InstancedMesh>(null);
  const crowns = useRef<THREE.InstancedMesh>(null);
  const count = lowQuality ? 24 : 96;
  const trees = useMemo(() => Array.from({ length: count }, (_, index) => {
    const groves = [[-32, -29], [-31, 27], [31, -28], [33, 27], [-3, -38], [1, 38], [-39, -3], [39, 3]];
    const [cx, cz] = groves[index % groves.length];
    const x = THREE.MathUtils.clamp(cx + (deterministicUnit(index + 21) - 0.5) * 15, -SCENE_WIDTH / 2 + 3, SCENE_WIDTH / 2 - 3);
    const z = THREE.MathUtils.clamp(cz + (deterministicUnit(index + 91) - 0.5) * 14, -SCENE_DEPTH / 2 + 3, SCENE_DEPTH / 2 - 3);
    if (Math.abs(x) < 12 && Math.abs(z) < 12) return null;
    const scale = 0.68 + deterministicUnit(index + 911) * 0.66;
    return { x, z, scale, yaw: deterministicUnit(index + 613) * Math.PI, phase: deterministicUnit(index + 27) * Math.PI * 2, tint: deterministicUnit(index + 824) };
  }).filter((tree): tree is NonNullable<typeof tree> => tree !== null), [count]);
  useEffect(() => {
    const dummy = new THREE.Object3D();
    trees.forEach(({ x, z, scale, yaw, tint }, index) => {
      const ground = terrainHeight(x, z);
      dummy.position.set(x, ground + 1.35 * scale, z);
      dummy.scale.set(scale, scale, scale);
      dummy.rotation.y = yaw;
      dummy.updateMatrix();
      trunks.current?.setMatrixAt(index, dummy.matrix);
      const color = new THREE.Color().setHSL(0.24 + tint * 0.1, 0.23 + tint * 0.14, 0.23 + tint * 0.1);
      crowns.current?.setColorAt(index * 2, color);
      crowns.current?.setColorAt(index * 2 + 1, color.clone().offsetHSL(0.01, 0.02, 0.06));
    });
    if (trunks.current) trunks.current.instanceMatrix.needsUpdate = true;
    if (crowns.current?.instanceColor) crowns.current.instanceColor.needsUpdate = true;
  }, [trees]);
  useFrame((state) => {
    if (lowQuality) return;
    const dummy = new THREE.Object3D();
    trees.forEach(({ x, z, scale, phase }, index) => {
      const ground = terrainHeight(x, z);
      const sway = Math.sin(state.clock.elapsedTime * 0.38 + phase) * 0.08 * scale;
      dummy.position.set(x + sway, ground + 3.1 * scale, z);
      dummy.scale.set(1.22 * scale, 1.55 * scale, 1.22 * scale);
      dummy.updateMatrix();
      crowns.current?.setMatrixAt(index * 2, dummy.matrix);
      dummy.position.set(x - 0.52 * scale + sway * 0.72, ground + 3.42 * scale, z + 0.18 * scale);
      dummy.scale.set(0.82 * scale, 1.05 * scale, 0.82 * scale);
      dummy.updateMatrix();
      crowns.current?.setMatrixAt(index * 2 + 1, dummy.matrix);
    });
    if (crowns.current) crowns.current.instanceMatrix.needsUpdate = true;
  });
  return <>
    <instancedMesh ref={trunks} args={[undefined as unknown as THREE.BufferGeometry, undefined as unknown as THREE.Material, trees.length]} castShadow>
      <cylinderGeometry args={[0.18, 0.34, 3, 6]} />{lowQuality ? <meshLambertMaterial color="#514b39" /> : <meshStandardMaterial color="#514b39" roughness={1} />}
    </instancedMesh>
    <instancedMesh ref={crowns} args={[undefined as unknown as THREE.BufferGeometry, undefined as unknown as THREE.Material, trees.length * 2]} castShadow receiveShadow>
      <icosahedronGeometry args={[1, lowQuality ? 0 : 1]} />{lowQuality ? <meshLambertMaterial color="#ffffff" vertexColors flatShading /> : <meshStandardMaterial color="#ffffff" vertexColors roughness={1} flatShading />}
    </instancedMesh>
  </>;
}

function Fence({ width, height }: { width: number; height: number }) {
  const posts = useRef<THREE.InstancedMesh>(null);
  const rails = useRef<THREE.InstancedMesh>(null);
  const [farmWidth, farmDepth] = farmWorldSize(width, height);
  const fencePosts = useMemo(() => {
    const items: Array<{ x: number; z: number; yaw: number }> = [];
    const halfWidth = farmWidth / 2;
    const halfDepth = farmDepth / 2;
    const across = Math.ceil(farmWidth / 3.5);
    for (let index = 0; index <= across; index += 1) {
      const x = -halfWidth + farmWidth * index / across;
      items.push({ x, z: -halfDepth, yaw: 0 }, { x, z: halfDepth, yaw: 0 });
    }
    const down = Math.ceil(farmDepth / 3.5);
    for (let index = 1; index < down; index += 1) {
      const z = -halfDepth + farmDepth * index / down;
      items.push({ x: -halfWidth, z, yaw: Math.PI / 2 }, { x: halfWidth, z, yaw: Math.PI / 2 });
    }
    return items;
  }, [farmWidth, farmDepth]);
  const fenceRails = useMemo(() => fencePosts.map(({ x, z, yaw }) => ({ x, z, yaw })), [fencePosts]);
  useEffect(() => {
    const dummy = new THREE.Object3D();
    fencePosts.forEach(({ x, z }, index) => {
      dummy.position.set(x, terrainHeight(x, z) + 0.72, z);
      dummy.scale.set(1, 1.44, 1);
      dummy.rotation.set(0, 0, 0);
      dummy.updateMatrix();
      posts.current?.setMatrixAt(index, dummy.matrix);
    });
    fenceRails.forEach(({ x, z, yaw }, index) => {
      dummy.rotation.set(0, yaw, Math.PI / 2);
      dummy.scale.set(1, 3.55, 1);
      for (let level = 0; level < 2; level += 1) {
        dummy.position.set(x, terrainHeight(x, z) + 0.48 + level * 0.56, z);
        dummy.updateMatrix();
        rails.current?.setMatrixAt(index * 2 + level, dummy.matrix);
      }
    });
    if (posts.current) posts.current.instanceMatrix.needsUpdate = true;
    if (rails.current) rails.current.instanceMatrix.needsUpdate = true;
  }, [fencePosts, fenceRails]);
  return <>
    <instancedMesh ref={posts} args={[fencePostGeometry, undefined as unknown as THREE.Material, fencePosts.length]} castShadow><meshStandardMaterial color="#75674f" roughness={0.91} /></instancedMesh>
    <instancedMesh ref={rails} args={[fenceRailGeometry, undefined as unknown as THREE.Material, fenceRails.length * 2]} castShadow><meshStandardMaterial color="#897b5d" roughness={0.91} /></instancedMesh>
  </>;
}

function PastureFences() {
  const posts = useRef<THREE.InstancedMesh>(null);
  const rails = useRef<THREE.InstancedMesh>(null);
  const segments = useMemo(() => {
    const lines = [
      { from: [-22, -31] as [number, number], to: [-22, -12] as [number, number] },
      { from: [-22, -7] as [number, number], to: [-22, 31] as [number, number] },
      { from: [15, -31] as [number, number], to: [15, -19] as [number, number] },
      { from: [15, -14] as [number, number], to: [15, 31] as [number, number] },
      { from: [-22, -16] as [number, number], to: [-6, -16] as [number, number] },
      { from: [1, -16] as [number, number], to: [15, -16] as [number, number] },
      { from: [-22, 18] as [number, number], to: [-9, 18] as [number, number] },
      { from: [-4, 18] as [number, number], to: [15, 18] as [number, number] },
    ];
    const result: Array<{ x: number; z: number; yaw: number; span: number }> = [];
    for (const line of lines) {
      const dx = line.to[0] - line.from[0];
      const dz = line.to[1] - line.from[1];
      const distance = Math.hypot(dx, dz);
      const count = Math.ceil(distance / 3.5);
      for (let index = 0; index <= count; index += 1) {
        const t = index / count;
        result.push({ x: line.from[0] + dx * t, z: line.from[1] + dz * t, yaw: Math.atan2(dz, dx), span: distance / count });
      }
    }
    return result;
  }, []);
  useEffect(() => {
    const dummy = new THREE.Object3D();
    segments.forEach(({ x, z, yaw, span }, index) => {
      dummy.position.set(x, terrainHeight(x, z) + 0.57, z);
      dummy.scale.set(1, 1.14, 1);
      dummy.rotation.set(0, 0, 0);
      dummy.updateMatrix();
      posts.current?.setMatrixAt(index, dummy.matrix);
      for (let level = 0; level < 2; level += 1) {
        dummy.position.set(x, terrainHeight(x, z) + 0.42 + level * 0.48, z);
        dummy.scale.set(1, span + 0.08, 1);
        dummy.rotation.set(0, -yaw, Math.PI / 2);
        dummy.updateMatrix();
        rails.current?.setMatrixAt(index * 2 + level, dummy.matrix);
      }
    });
    if (posts.current) posts.current.instanceMatrix.needsUpdate = true;
    if (rails.current) rails.current.instanceMatrix.needsUpdate = true;
  }, [segments]);
  return <>
    <instancedMesh ref={posts} args={[fencePostGeometry, undefined as unknown as THREE.Material, segments.length]} castShadow><meshStandardMaterial color="#75674f" roughness={0.91} /></instancedMesh>
    <instancedMesh ref={rails} args={[fenceRailGeometry, undefined as unknown as THREE.Material, segments.length * 2]} castShadow><meshStandardMaterial color="#897b5d" roughness={0.91} /></instancedMesh>
  </>;
}

function Barn() {
  return <group position={[-0.8, terrainHeight(-0.8, 2), 2]}>
    <mesh position={[0, 2.05, 0]} castShadow receiveShadow><boxGeometry args={[11, 4.1, 10]} /><meshStandardMaterial color="#8c5740" roughness={0.94} /></mesh>
    <mesh position={[-3.4, 4.78, 0]} rotation={[0, 0, -0.22]} castShadow receiveShadow><boxGeometry args={[7.7, 0.2, 10.6]} /><meshStandardMaterial color="#5d5f56" roughness={0.88} /></mesh>
    <mesh position={[3.4, 4.78, 0]} rotation={[0, 0, 0.22]} castShadow receiveShadow><boxGeometry args={[7.7, 0.2, 10.6]} /><meshStandardMaterial color="#5d5f56" roughness={0.88} /></mesh>
    <mesh position={[0, 1.45, 5.03]} castShadow><boxGeometry args={[3.6, 2.8, 0.08]} /><meshStandardMaterial color="#493a31" roughness={0.95} /></mesh>
    <mesh position={[0, 0.2, 5.1]}><boxGeometry args={[4, 0.16, 0.08]} /><meshStandardMaterial color="#d8c3a0" /></mesh>
    <mesh position={[7.2, 0.55, -3.8]} rotation={[0, 0, -0.1]}><boxGeometry args={[0.25, 1.1, 0.25]} /><meshStandardMaterial color="#6b6d62" /></mesh>
  </group>;
}

function FarmStructures() {
  return <>
    <Barn />
    <group position={[-27, terrainHeight(-27, 17), 17]}>
      <mesh position={[0, 0.5, 0]}><boxGeometry args={[4.2, 1, 2.4]} /><meshStandardMaterial color="#343b35" roughness={0.65} /></mesh>
      <mesh position={[0, 1.2, -0.35]}><cylinderGeometry args={[0.75, 0.75, 0.5, 20]} /><meshStandardMaterial color="#728b84" metalness={0.15} roughness={0.25} /></mesh>
    </group>
    <group position={[23, terrainHeight(23, 20), 20]}>
      <mesh position={[0, 0.35, 0]} castShadow><boxGeometry args={[4.8, 0.7, 1.6]} /><meshStandardMaterial color="#6a7862" metalness={0.18} roughness={0.4} /></mesh>
      <mesh position={[0, 0.74, 0]}><boxGeometry args={[4.4, 0.08, 1.35]} /><meshStandardMaterial color="#aab9aa" metalness={0.23} roughness={0.26} /></mesh>
    </group>
    <group position={[18, terrainHeight(18, -21), -21]}>
      <mesh position={[0, 0.65, 0]} castShadow><boxGeometry args={[7, 1.3, 4.5]} /><meshStandardMaterial color="#aaa897" roughness={0.9} /></mesh>
      <mesh position={[0, 1.55, 0]} rotation={[0, 0, Math.PI / 2]}><coneGeometry args={[5.2, 2.3, 4]} /><meshStandardMaterial color="#6f716b" roughness={0.92} /></mesh>
    </group>
  </>;
}

function CowHerd({ animals, selectedId, onSelect, width, height, lowQuality, paused, playbackSpeed, runId, onReady }: {
  animals: SceneAnimal[];
  selectedId: string | null;
  onSelect: (animal: SceneAnimal) => void;
  width: number;
  height: number;
  lowQuality: boolean;
  paused: boolean;
  playbackSpeed: number;
  runId: string | null;
  onReady: () => void;
}) {
  const camera = useThree((state) => state.camera);
  const cameraWorldPosition = useMemo(() => new THREE.Vector3(), []);
  const objects = useLoader(OBJLoader, COW_URLS);
  const [coat, skin] = useTexture(COW_TEXTURES);
  const instanced = useRef(new Map<string, THREE.InstancedMesh>());
  const farInstanced = useRef(new Map<string, THREE.InstancedMesh>());
  const contactShadows = useRef<THREE.InstancedMesh>(null);
  const clickTargets = useRef<THREE.InstancedMesh>(null);
  const clickTargetGeometry = useMemo(() => new THREE.SphereGeometry(0.42, 6, 4), []);
  const clickTargetMaterial = useMemo(() => new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, colorWrite: false, depthWrite: false }), []);
  const rootObject = useMemo(() => new THREE.Object3D(), []);
  const farRootObject = useMemo(() => new THREE.Object3D(), []);
  const rootBasis = useMemo(() => new THREE.Matrix4(), []);
  const surfaceNormal = useMemo(() => new THREE.Vector3(), []);
  const forward = useMemo(() => new THREE.Vector3(), []);
  const lateral = useMemo(() => new THREE.Vector3(), []);
  const localPosition = useMemo(() => new THREE.Vector3(), []);
  const localRotation = useMemo(() => new THREE.Quaternion(), []);
  const localScale = useMemo(() => new THREE.Vector3(), []);
  const localEuler = useMemo(() => new THREE.Euler(), []);
  const pivotOut = useMemo(() => new THREE.Matrix4(), []);
  const pivotRotation = useMemo(() => new THREE.Matrix4(), []);
  const pivotIn = useMemo(() => new THREE.Matrix4(), []);
  const animatedPose = useMemo(() => new THREE.Matrix4(), []);
  const inverseRoot = useMemo(() => new THREE.Matrix4(), []);
  const instanceMatrix = useMemo(() => new THREE.Matrix4(), []);
  const farInstanceMatrix = useMemo(() => new THREE.Matrix4(), []);
  const contactMatrix = useMemo(() => new THREE.Matrix4(), []);
  const contactPosition = useMemo(() => new THREE.Vector3(), []);
  const contactQuaternion = useMemo(() => new THREE.Quaternion(), []);
  const contactScale = useMemo(() => new THREE.Vector3(), []);
  const clickScale = useMemo(() => new THREE.Vector3(1, 1, 1), []);
  const clickQuaternion = useMemo(() => new THREE.Quaternion(), []);
  const clickMatrix = useMemo(() => new THREE.Matrix4(), []);
  const localQuaternion = useMemo(() => new THREE.Quaternion(), []);
  const contactGeometry = useMemo(() => {
    const geometry = new THREE.CircleGeometry(1, 16);
    geometry.rotateX(-Math.PI / 2);
    return geometry;
  }, []);
  const contactMaterial = useMemo(() => new THREE.MeshBasicMaterial({ color: '#34392d', transparent: true, opacity: lowQuality ? 0.08 : 0.15, depthWrite: false }), [lowQuality]);
  const motion = useRef(new Map<string, CowMotion>());
  const readySent = useRef(false);
  const motionDiagnostics = useRef({ lastReportedAt: 0, simulationSteps: 0 });
  const frustum = useMemo(() => new THREE.Frustum(), []);
  const viewProjection = useMemo(() => new THREE.Matrix4(), []);
  const visibilityPoint = useMemo(() => new THREE.Vector3(), []);
  const coatColorSignature = useRef('');
  const geometries = useMemo(() => {
    const source = Object.fromEntries(COW_FILES.map((key, index) => [key, objectGeometry(objects[index])])) as Record<typeof COW_FILES[number], THREE.BufferGeometry>;
    if (lowQuality) {
      // Keep the project's cattle silhouette on weak/software renderers too;
      // weld duplicate vertices for indexed draws rather than swapping the herd
      // for generic sphere/cylinder placeholders.
      for (const key of COW_FILES) source[key] = mergeVertices(source[key]);
    }
    const neckPose = partMatrix([0.55, 0, 1.2], [0, 0.3, 0]);
    const headPose = neckPose.clone().multiply(partMatrix([0.43, 0, 0.34]));
    const ears = [-1, 1].map((side) => headPose.clone().multiply(partMatrix([-0.05, side * 0.22, 0.2])));
    const legs: Array<[number, number]> = [[0.43, 0.22], [0.43, -0.22], [-0.48, 0.22], [-0.48, -0.22]];
    const strideOffsets = [0, Math.PI, Math.PI, 0];
    const markings = new THREE.SphereGeometry(1, lowQuality ? 8 : 14, lowQuality ? 6 : 10);
    const parts: CowPart[] = [
      { key: 'torso', geometry: source.torso, material: 'coat', pose: partMatrix([0, 0, 1.03]) },
      // The source texture is useful close up, but its low resolution and UV
      // projection do not read from the field overview. These shallow patches
      // give the shared mesh a clear bovine coat pattern at every distance.
      { key: 'coat-patch', geometry: markings, material: 'patch', pose: partMatrix([-0.24, 0, 1.365], [0, 0.06, 0], [0.29, 0.17, 0.035]) },
      { key: 'coat-patch', geometry: markings, material: 'patch', pose: partMatrix([-0.3, 0.265, 1.13], [0, 0.1, 0], [0.24, 0.055, 0.17]) },
      { key: 'coat-patch', geometry: markings, material: 'patch', pose: partMatrix([-0.3, -0.265, 1.13], [0, -0.1, 0], [0.24, 0.055, 0.17]) },
      { key: 'neck', geometry: source.neck, material: 'coat', pose: neckPose },
      { key: 'head', geometry: source.head, material: 'coat', pose: headPose },
      ...[-1, 1].map((side) => ({
        key: 'ear' as const, geometry: source.ear, material: 'skin' as const,
        pose: ears[side > 0 ? 1 : 0],
      })),
      ...legs.map(([x, z], legIndex) => ({
        key: 'leg' as const, geometry: source.leg, material: 'coat' as const,
        pose: partMatrix([x, z, 0.72]), legIndex, hip: [x, z, 0.69] as [number, number, number], strideOffset: strideOffsets[legIndex],
      })),
      ...legs.map(([x, z], legIndex) => ({
        key: 'hoof' as const, geometry: source.hoof, material: 'hoof' as const,
        pose: partMatrix([x + 0.015, z, 0.05]), legIndex, hip: [x, z, 0.69] as [number, number, number], strideOffset: strideOffsets[legIndex],
      })),
      {
        key: 'tag',
        geometry: (() => { const tag = new THREE.CylinderGeometry(0.075, 0.075, 0.045, 12); tag.rotateX(Math.PI / 2); return tag; })(),
        material: 'tag',
        pose: ears[1].clone().multiply(partMatrix([-0.01, 0.1, 0.02])),
      },
      {
        key: 'tail',
        geometry: new THREE.CylinderGeometry(0.035, 0.055, 0.82, 7),
        material: 'coat',
        pose: partMatrix([-0.88, 0, 1.18], [0, 0, Math.PI / 2]),
      },
    ];
    return parts;
  }, [objects, lowQuality]);

  const farParts = useMemo<CowPart[]>(() => {
    const sphere = new THREE.SphereGeometry(1, lowQuality ? 8 : 10, lowQuality ? 6 : 8);
    const leg = new THREE.CylinderGeometry(0.055, 0.065, 0.48, 6);
    leg.rotateX(Math.PI / 2);
    const tag = new THREE.SphereGeometry(0.105, 7, 5);
    const legs: Array<[number, number]> = [[0.43, 0.2], [0.43, -0.2], [-0.46, 0.2], [-0.46, -0.2]];
    return [
      { key: 'far-body', geometry: sphere, material: 'coat', pose: partMatrix([0, 0, 1.03], [0, 0, 0], [0.72, 0.31, 0.36]) },
      { key: 'far-patch', geometry: sphere, material: 'patch', pose: partMatrix([-0.22, 0, 1.365], [0, 0.05, 0], [0.32, 0.2, 0.035]) },
      { key: 'far-patch', geometry: sphere, material: 'patch', pose: partMatrix([-0.28, 0.27, 1.12], [0, 0.08, 0], [0.25, 0.055, 0.18]) },
      { key: 'far-patch', geometry: sphere, material: 'patch', pose: partMatrix([-0.28, -0.27, 1.12], [0, -0.08, 0], [0.25, 0.055, 0.18]) },
      { key: 'far-neck', geometry: sphere, material: 'coat', pose: partMatrix([0.58, 0, 1.25], [0, -0.15, 0], [0.2, 0.15, 0.3]) },
      { key: 'far-head', geometry: sphere, material: 'coat', pose: partMatrix([0.84, 0, 1.46], [0, 0, 0], [0.25, 0.17, 0.19]) },
      ...legs.map(([x, side]) => ({
        key: 'far-leg' as const, geometry: leg, material: 'hoof' as const,
        pose: partMatrix([x, side, 0.36]),
      })),
      { key: 'far-tag', geometry: tag, material: 'tag', pose: partMatrix([0.9, 0.18, 1.55]) },
    ];
  }, [lowQuality]);

  useEffect(() => {
    coat.colorSpace = THREE.SRGBColorSpace;
    skin.colorSpace = THREE.SRGBColorSpace;
    coat.needsUpdate = true;
    skin.needsUpdate = true;
  }, [coat, skin]);

  const materials = useMemo(() => lowQuality ? {
    coat: new THREE.MeshLambertMaterial({ map: coat, color: '#f3f0e8' }),
    skin: new THREE.MeshLambertMaterial({ map: skin, color: '#d4b4a5' }),
    hoof: new THREE.MeshLambertMaterial({ color: '#373a35' }),
    tag: new THREE.MeshLambertMaterial({ color: '#f0cf19' }),
    patch: new THREE.MeshLambertMaterial({ color: '#292a27' }),
  } : {
    coat: new THREE.MeshStandardMaterial({ map: coat, color: '#f3f0e8', roughness: 0.96 }),
    skin: new THREE.MeshStandardMaterial({ map: skin, color: '#d4b4a5', roughness: 0.9 }),
    hoof: new THREE.MeshStandardMaterial({ color: '#373a35', roughness: 0.92 }),
    tag: new THREE.MeshStandardMaterial({ color: '#f0cf19', roughness: 0.54, metalness: 0.12 }),
    patch: new THREE.MeshStandardMaterial({ color: '#292a27', roughness: 0.94 }),
  }, [coat, skin, lowQuality]);
  const farMaterials = useMemo(() => ({
    coat: lowQuality
      ? new THREE.MeshLambertMaterial({ color: '#f3f0e8' })
      : new THREE.MeshStandardMaterial({ color: '#f3f0e8', roughness: 0.9 }),
    skin: lowQuality
      ? new THREE.MeshLambertMaterial({ color: '#b58f80' })
      : new THREE.MeshStandardMaterial({ color: '#b58f80', roughness: 0.85 }),
    hoof: lowQuality
      ? new THREE.MeshLambertMaterial({ color: '#343630' })
      : new THREE.MeshStandardMaterial({ color: '#343630', roughness: 0.9 }),
    tag: lowQuality
      ? new THREE.MeshLambertMaterial({ color: '#ebc919' })
      : new THREE.MeshStandardMaterial({ color: '#ebc919', roughness: 0.6 }),
    patch: lowQuality
      ? new THREE.MeshLambertMaterial({ color: '#292a27' })
      : new THREE.MeshStandardMaterial({ color: '#292a27', roughness: 0.94 }),
  }), [lowQuality]);
  useEffect(() => () => {
    Object.values(farMaterials).forEach((material) => material.dispose());
  }, [farMaterials]);

  useEffect(() => {
    const signature = animals.map((animal) => animal.animal_id).join('|');
    if (signature === coatColorSignature.current) return;
    coatColorSignature.current = signature;
    const color = new THREE.Color();
    const paintInstances = (parts: CowPart[], meshes: Map<string, THREE.InstancedMesh>) => {
      parts.forEach((part, partIndex) => {
        if (part.material !== 'coat' && part.material !== 'patch') return;
        const mesh = meshes.get(`${part.key}-${partIndex}`);
        if (!mesh) return;
        animals.forEach((animal, animalIndex) => {
          const variation = deterministicPhase(animal.animal_id) / (Math.PI * 2);
          if (part.material === 'patch') color.setHSL(0.12, 0.025, 0.13 + variation * 0.055);
          else color.setHSL(0.09 + variation * 0.012, 0.06 + variation * 0.035,
            lowQuality ? 0.82 + variation * 0.08 : 0.92 + variation * 0.045);
          mesh.setColorAt(animalIndex, color);
        });
        if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
      });
    };
    paintInstances(geometries, instanced.current);
    paintInstances(farParts, farInstanced.current);
  }, [animals, geometries, farParts, lowQuality]);

  const handles = (event: ThreeEvent<MouseEvent>) => {
    event.stopPropagation();
    if (event.instanceId === undefined) return;
    const animal = animals[event.instanceId];
    if (animal) onSelect(animal);
  };

  useFrame((frame, delta) => {
    const renderTime = frame.clock.elapsedTime;
    const animationStartedAt = performance.now();
    // OBJ proportions are treated as provisional metres and share the farm's
    // position scale so visual footprints agree with server-side collision size.
    const modelScale = Math.min(SCENE_WIDTH / Math.max(width, 1), SCENE_DEPTH / Math.max(height, 1)) * (lowQuality ? 0.92 : 1);
    const longitudinalScale = 1.0;
    const strideLength = modelScale * 0.82;
    const fixedDt = 1 / 30;
    const maxCatchUpSteps = 3;
    const diagonalOffsets = [0, Math.PI, Math.PI, 0];
    let movingCows = 0;
    let plantedHooves = 0;
    let totalHooves = 0;
    let simulationSteps = 0;
    let visibleAnimalCenters = 0;
    // A resumed tab can deliver a multi-second R3F delta. Rebase by dropping
    // that interval; never consume it as accumulated movement.
    const frameDelta = delta > 0.25 ? 0 : Math.min(delta, 0.1);
    camera.updateMatrixWorld();
    viewProjection.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse);
    frustum.setFromProjectionMatrix(viewProjection);
    camera.getWorldPosition(cameraWorldPosition);
    for (let index = 0; index < animals.length; index += 1) {
      const animal = animals[index];
      const pose = animal.scenePosition;
      // The visible herd follows the simulator's separate scene-position channel.
      // RF estimates may be missing; they must not gate physical scene entities.
      if (!pose || !Number.isFinite(pose.x) || !Number.isFinite(pose.y)) continue;
      const [targetX, , targetZ] = farmToWorld(pose.x, pose.y, width, height);
      visibilityPoint.set(targetX, terrainHeight(targetX, targetZ) + 0.8, targetZ);
      if (frustum.containsPoint(visibilityPoint)) visibleAnimalCenters += 1;
      const individualScale = 0.92 + deterministicPhase(animal.animal_id) / (Math.PI * 2) * 0.12;
      // Choose detail from each animal's projected size, rather than camera
      // distance from world origin. The display scale is a smooth visual LOD
      // aid only; simulator coordinates and collision footprints stay intact.
      const viewDistance = cameraWorldPosition.distanceTo(
        localPosition.set(targetX, terrainHeight(targetX, targetZ) + 0.8, targetZ),
      );
      const fov = THREE.MathUtils.degToRad((camera as THREE.PerspectiveCamera).fov ?? 42);
      const projectedBodyPixels = Math.max(0.1, (modelScale * individualScale * 1.55 * frame.size.height)
        / (2 * Math.max(viewDistance, 0.1) * Math.tan(fov / 2)));
      const targetLod: CowLod = selectedId === animal.animal_id || projectedBodyPixels >= 32 ? 0
        : projectedBodyPixels >= 10 ? 1 : 2;
      const scaledLegibility = THREE.MathUtils.clamp(17 / projectedBodyPixels, 1, 5.3);
      const initialAnimalScale = modelScale * individualScale * scaledLegibility;
      const state = animal.movementState;
      const stationary = /REST|IDLE/i.test(state);
      const grazing = /GRAZ/i.test(state);
      const isRunning = /RUN/i.test(state);
      let current: CowMotion | undefined = motion.current.get(animal.animal_id);
      if (!current) {
        const yaw = deterministicPhase(animal.animal_id);
        const rootY = terrainHeight(targetX, targetZ);
        const feet = HOOF_OFFSETS.map(([front, side]) => {
          const x = targetX + (front * longitudinalScale * Math.cos(yaw) + side * Math.sin(yaw)) * initialAnimalScale;
          const z = targetZ + (-front * longitudinalScale * Math.sin(yaw) + side * Math.cos(yaw)) * initialAnimalScale;
          const y = terrainHeight(x, z) + 0.05 * initialAnimalScale;
          return { x, y, z, previousX: x, previousY: y, previousZ: z,
            swingStartX: x, swingStartZ: z, swingEndX: x, swingEndZ: z, swinging: false };
        });
        current = {
          x: targetX, z: targetZ, previousX: targetX, previousZ: targetZ,
          targetX, targetZ, lastEstimateX: targetX, lastEstimateZ: targetZ,
          yaw, previousYaw: yaw, targetYaw: yaw, sample: pose.timestamp,
          phase: deterministicPhase(animal.animal_id), runId, gaitPhase: 0, previousGaitPhase: 0,
          speed: 0, targetSpeed: 0, accumulator: 0, rootY, previousRootY: rootY,
          displayScale: scaledLegibility, lod: targetLod, feet,
        };
        motion.current.set(animal.animal_id, current);
      }

      // Hysteresis and damping prevent visible LOD flicker while the camera
      // crosses a threshold or moves around a grazing animal.
      const lod = current.lod;
      if (targetLod < lod) {
        const promoteAt = lod === 2 ? 12 : 35;
        if (projectedBodyPixels >= promoteAt || selectedId === animal.animal_id) current.lod = targetLod;
      } else if (targetLod > lod) {
        const demoteBelow = lod === 0 ? 28 : 8.5;
        if (projectedBodyPixels < demoteBelow && selectedId !== animal.animal_id) current.lod = targetLod;
      }
      const displayDelta = Math.min(delta, 0.05);
      current.displayScale = THREE.MathUtils.damp(current.displayScale, scaledLegibility, 8, displayDelta);
      const animalScale = modelScale * individualScale * current.displayScale;
      const scaledStride = strideLength * individualScale;

      const runChanged = current.runId !== runId;
      if (runChanged) {
        current.x = current.previousX = current.targetX = current.lastEstimateX = targetX;
        current.z = current.previousZ = current.targetZ = current.lastEstimateZ = targetZ;
        current.sample = pose.timestamp;
        current.runId = runId;
        current.speed = current.targetSpeed = 0;
        current.accumulator = 0;
        current.gaitPhase = current.previousGaitPhase = 0;
        current.yaw = current.previousYaw = current.targetYaw = deterministicPhase(animal.animal_id);
        current.rootY = current.previousRootY = terrainHeight(targetX, targetZ);
        current.feet.forEach((foot, footIndex) => {
          const [front, side] = HOOF_OFFSETS[footIndex];
          foot.x = foot.previousX = targetX + (front * longitudinalScale * Math.cos(current.yaw) + side * Math.sin(current.yaw)) * animalScale;
          foot.z = foot.previousZ = targetZ + (-front * longitudinalScale * Math.sin(current.yaw) + side * Math.cos(current.yaw)) * animalScale;
          foot.y = foot.previousY = terrainHeight(foot.x, foot.z) + 0.05 * animalScale;
          foot.swinging = false;
        });
      } else if (pose.timestamp !== current.sample) {
        const sampleDelta = pose.timestamp - current.sample;
        const estimateDx = targetX - current.lastEstimateX;
        const estimateDz = targetZ - current.lastEstimateZ;
        const estimateDistance = Math.hypot(estimateDx, estimateDz);
        const displaySeconds = sampleDelta / Math.max(playbackSpeed, 0.1);
        current.targetX = targetX;
        current.targetZ = targetZ;
        current.lastEstimateX = targetX;
        current.lastEstimateZ = targetZ;
        current.sample = pose.timestamp;
        if (stationary || sampleDelta <= 0 || estimateDistance < 0.008) {
          current.targetSpeed = 0;
        } else {
          current.targetYaw = Math.atan2(-estimateDz, estimateDx);
          // Speed comes only from successive simulator-provided estimates.
          current.targetSpeed = THREE.MathUtils.clamp(estimateDistance / Math.max(displaySeconds, 1e-3), 0, isRunning ? 1.05 : 0.82);
        }
      }
      if (stationary) current.targetSpeed = 0;

      // Fixed 30 Hz locomotion/controller clock; rendering only interpolates its
      // two most recent states. Catch-up is bounded and excess time is dropped.
      current.accumulator = Math.min(0.1, current.accumulator + (paused ? 0 : frameDelta));
      let steps = 0;
      while (!paused && current.accumulator >= fixedDt && steps < maxCatchUpSteps) {
        current.previousX = current.x;
        current.previousZ = current.z;
        current.previousYaw = current.yaw;
        current.previousRootY = current.rootY;
        current.previousGaitPhase = current.gaitPhase;
        current.feet.forEach((foot) => {
          foot.previousX = foot.x; foot.previousY = foot.y; foot.previousZ = foot.z;
        });

        const offsetX = current.targetX - current.x;
        const offsetZ = current.targetZ - current.z;
        const remaining = Math.hypot(offsetX, offsetZ);
        let distanceTravelled = 0;
        if (remaining > 0.025 && current.targetSpeed > 0.005) {
          const wantedYaw = Math.atan2(-offsetZ, offsetX);
          const error = shortestAngle(current.yaw, wantedYaw);
          current.targetYaw = wantedYaw;
          const turnLimit = (isRunning ? 1.25 : 0.88) * fixedDt;
          current.yaw += Math.sign(error) * Math.min(Math.abs(error), turnLimit);
          const aligned = Math.abs(error) < 0.65;
          const desiredSpeed = aligned ? current.targetSpeed : 0;
          const rate = desiredSpeed > current.speed ? 0.72 : 1.15;
          current.speed += THREE.MathUtils.clamp(desiredSpeed - current.speed, -rate * fixedDt, rate * fixedDt);
          if (aligned && current.speed > 0.002) {
            distanceTravelled = Math.min(remaining, current.speed * fixedDt);
            const forwardX = Math.cos(current.yaw);
            const forwardZ = -Math.sin(current.yaw);
            current.x += forwardX * distanceTravelled;
            current.z += forwardZ * distanceTravelled;
            if (remaining - distanceTravelled < 0.018) {
              current.x = current.targetX;
              current.z = current.targetZ;
              current.speed = current.targetSpeed = 0;
            }
          }
        } else {
          current.speed = Math.max(0, current.speed - 1.15 * fixedDt);
        }

        const moving = distanceTravelled > 0.00001;
        if (moving) current.gaitPhase += distanceTravelled / scaledStride * Math.PI * 2;
        else if (current.feet.some((foot) => foot.swinging)) current.gaitPhase += 8 * fixedDt;
        const sineYaw = Math.sin(current.yaw);
        const cosineYaw = Math.cos(current.yaw);
        current.feet.forEach((foot, footIndex) => {
          const [front, side] = HOOF_OFFSETS[footIndex];
          const phase = (((current.gaitPhase + diagonalOffsets[footIndex]) % (Math.PI * 2)) + Math.PI * 2) % (Math.PI * 2) / (Math.PI * 2);
          const swing = phase >= 0.62;
          if (swing && !foot.swinging) {
            foot.swinging = true;
            foot.swingStartX = foot.x;
            foot.swingStartZ = foot.z;
            const hipForward = front * longitudinalScale * animalScale;
            const hipSide = side * animalScale;
            const baseX = current.x + hipForward * cosineYaw + hipSide * sineYaw;
            const baseZ = current.z - hipForward * sineYaw + hipSide * cosineYaw;
            foot.swingEndX = baseX + cosineYaw * scaledStride * 0.62;
            foot.swingEndZ = baseZ - sineYaw * scaledStride * 0.62;
          }
          if (swing && foot.swinging) {
            const progress = THREE.MathUtils.clamp((phase - 0.62) / 0.38, 0, 1);
            const eased = progress * progress * (3 - 2 * progress);
            foot.x = THREE.MathUtils.lerp(foot.swingStartX, foot.swingEndX, eased);
            foot.z = THREE.MathUtils.lerp(foot.swingStartZ, foot.swingEndZ, eased);
            foot.y = terrainHeight(foot.x, foot.z) + 0.05 * animalScale + Math.sin(progress * Math.PI) * 0.13 * animalScale;
          } else {
            if (foot.swinging) {
              foot.x = foot.swingEndX;
              foot.z = foot.swingEndZ;
              foot.swinging = false;
            }
            // In stance the hoof remains fixed in world XZ; only terrain height
            // is sampled again, so the hoof cannot treadmill with the body.
            foot.y = terrainHeight(foot.x, foot.z) + 0.05 * animalScale;
          }
        });

        const groundTarget = terrainHeight(current.x, current.z);
        current.rootY += (groundTarget - current.rootY) * 0.18;
        current.accumulator -= fixedDt;
        steps += 1;
      }
      simulationSteps += steps;
      motionDiagnostics.current.simulationSteps += steps;
      if (steps === maxCatchUpSteps && current.accumulator >= fixedDt) current.accumulator %= fixedDt;

      const alpha = paused ? 1 : THREE.MathUtils.clamp(current.accumulator / fixedDt, 0, 1);
      const renderX = THREE.MathUtils.lerp(current.previousX, current.x, alpha);
      const renderZ = THREE.MathUtils.lerp(current.previousZ, current.z, alpha);
      const renderYaw = current.previousYaw + shortestAngle(current.previousYaw, current.yaw) * alpha;
      const renderY = THREE.MathUtils.lerp(current.previousRootY, current.rootY, alpha);
      const normalTuple = terrainNormal(renderX, renderZ);
      if (current.speed > 0.015 && current.targetSpeed > 0.015) movingCows += 1;
      for (const foot of current.feet) {
        totalHooves += 1;
        if (!foot.swinging) plantedHooves += 1;
      }
      surfaceNormal.set(normalTuple[0], normalTuple[1], normalTuple[2]);
      forward.set(Math.cos(renderYaw), 0, -Math.sin(renderYaw))
        .addScaledVector(surfaceNormal, -Math.cos(renderYaw) * normalTuple[0] + Math.sin(renderYaw) * normalTuple[2]).normalize();
      lateral.crossVectors(surfaceNormal, forward).normalize();
      rootBasis.makeBasis(forward, lateral, surfaceNormal);
      rootObject.position.set(renderX, renderY, renderZ);
      rootObject.quaternion.setFromRotationMatrix(rootBasis);
      rootObject.scale.set(animalScale * longitudinalScale, animalScale, animalScale);
      rootObject.updateMatrix();
      inverseRoot.copy(rootObject.matrix).invert();

      contactMatrix.compose(
        contactPosition.set(renderX, renderY + 0.008, renderZ),
        contactQuaternion,
        contactScale.set(animalScale * longitudinalScale * 1.05, 1, animalScale * 0.42),
      );
      contactShadows.current?.setMatrixAt(index, contactMatrix);
      clickScale.set(1, 1, 1);
      clickMatrix.compose(
        localPosition.set(renderX, renderY + animalScale * 0.75, renderZ),
        clickQuaternion.copy(rootObject.quaternion),
        clickScale,
      );
      clickTargets.current?.setMatrixAt(index, clickMatrix);

      const detailMeshScale = current.lod === 2 ? 0 : 1;
      for (let partIndex = 0; partIndex < geometries.length; partIndex += 1) {
        const part = geometries[partIndex];
        const mesh = instanced.current.get(`${part.key}-${partIndex}`);
        if (!mesh) continue;
        if (!detailMeshScale) {
          instanceMatrix.makeScale(0, 0, 0);
          mesh.setMatrixAt(index, instanceMatrix);
          continue;
        }
        if (part.legIndex !== undefined && part.hip) {
          const foot = current.feet[part.legIndex];
          const footWorld = localPosition.set(
            THREE.MathUtils.lerp(foot.previousX, foot.x, alpha),
            THREE.MathUtils.lerp(foot.previousY, foot.y, alpha),
            THREE.MathUtils.lerp(foot.previousZ, foot.z, alpha),
          ).applyMatrix4(inverseRoot);
          const down = Math.max(0.16, part.hip[2] - footWorld.z);
          const hipAngle = THREE.MathUtils.clamp(Math.atan2(-(footWorld.x - part.hip[0]), down), -0.58, 0.58);
          pivotOut.makeTranslation(...part.hip);
          pivotIn.makeTranslation(-part.hip[0], -part.hip[1], -part.hip[2]);
          localEuler.set(0, hipAngle, 0);
          pivotRotation.makeRotationFromEuler(localEuler);
          animatedPose.copy(pivotOut).multiply(pivotRotation).multiply(pivotIn).multiply(part.pose);
        } else if (part.key === 'head' && (grazing || /DRINK/i.test(state))) {
          part.pose.decompose(localPosition, localRotation, localScale);
          const forage = 0.5 + 0.5 * Math.sin(renderTime * 0.48 + current.phase);
          const dip = /DRINK/i.test(state) ? 0.23 : 0.11 + forage * 0.1;
          localPosition.z -= dip * 0.42;
          localEuler.set(0, -dip, 0);
          localQuaternion.setFromEuler(localEuler);
          localRotation.multiply(localQuaternion);
          animatedPose.compose(localPosition, localRotation, localScale);
        } else if (part.key === 'tail') {
          part.pose.decompose(localPosition, localRotation, localScale);
          const swish = Math.sin(renderTime * 0.7 + current.phase * 1.4) * 0.11;
          localEuler.set(0, 0, swish);
          localQuaternion.setFromEuler(localEuler);
          localRotation.multiply(localQuaternion);
          animatedPose.compose(localPosition, localRotation, localScale);
        } else {
          animatedPose.copy(part.pose);
        }
        instanceMatrix.multiplyMatrices(rootObject.matrix, animatedPose);
        mesh.setMatrixAt(index, instanceMatrix);
      }
      farRootObject.position.copy(rootObject.position);
      farRootObject.quaternion.copy(rootObject.quaternion);
      farRootObject.scale.set(animalScale * longitudinalScale, animalScale, animalScale);
      farRootObject.updateMatrix();
      for (let partIndex = 0; partIndex < farParts.length; partIndex += 1) {
        const part = farParts[partIndex];
        const mesh = farInstanced.current.get(`${part.key}-${partIndex}`);
        if (!mesh) continue;
        if (current.lod !== 2) {
          farInstanceMatrix.makeScale(0, 0, 0);
        } else {
          farInstanceMatrix.multiplyMatrices(farRootObject.matrix, part.pose);
        }
        mesh.setMatrixAt(index, farInstanceMatrix);
      }
    }
    instanced.current.forEach((mesh) => { mesh.instanceMatrix.needsUpdate = true; });
    farInstanced.current.forEach((mesh) => { mesh.instanceMatrix.needsUpdate = true; });
    if (contactShadows.current) contactShadows.current.instanceMatrix.needsUpdate = true;
    if (clickTargets.current) clickTargets.current.instanceMatrix.needsUpdate = true;
    if (!readySent.current) {
      readySent.current = true;
      requestAnimationFrame(onReady);
    }
    if (renderTime - motionDiagnostics.current.lastReportedAt > 1) {
      const viewport = document.querySelector<HTMLElement>('.farm-viewport');
      if (viewport) {
        viewport.dataset.fixedStepHz = '30';
        viewport.dataset.movingCows = String(movingCows);
        viewport.dataset.plantedHooves = `${plantedHooves}/${totalHooves}`;
        if (SHOW_FARM_DIAGNOSTICS) {
          viewport.dataset.animalMeshes = String(animals.length);
          viewport.dataset.validAnimalPositions = String(animals.reduce((count, animal) => count + Number(
            Boolean(animal.scenePosition && Number.isFinite(animal.scenePosition.x) && Number.isFinite(animal.scenePosition.y)),
          ), 0));
          viewport.dataset.simulationStepsLastFrame = String(simulationSteps);
          const sampleSeconds = Math.max(renderTime - motionDiagnostics.current.lastReportedAt, 0.001);
          viewport.dataset.simulationUpdatesHz = String(Math.round(
            motionDiagnostics.current.simulationSteps / Math.max(animals.length, 1) / sampleSeconds * 10,
          ) / 10);
          viewport.dataset.visibleAnimalCenters = String(visibleAnimalCenters);
          viewport.dataset.animationUpdateMs = (performance.now() - animationStartedAt).toFixed(2);
        }
        motionDiagnostics.current.simulationSteps = 0;
      }
      motionDiagnostics.current.lastReportedAt = renderTime;
    }
  });

  const partRefs = geometries.map((part, index) => ({ part, index }));
  return <>
    <instancedMesh ref={(node) => {
      if (node) { node.instanceMatrix.setUsage(THREE.DynamicDrawUsage); contactShadows.current = node; }
      else contactShadows.current = null;
    }} args={[contactGeometry, contactMaterial, Math.max(1, animals.length)]} frustumCulled={false} />
    <instancedMesh ref={(node) => {
      if (node) { node.instanceMatrix.setUsage(THREE.DynamicDrawUsage); clickTargets.current = node; }
      else clickTargets.current = null;
    }} args={[clickTargetGeometry, clickTargetMaterial, Math.max(1, animals.length)]}
      count={animals.length} frustumCulled={false} onClick={handles} />
    {partRefs.map(({ part, index }) => {
      const objectKey = `${part.key}-${index}`;
      return <instancedMesh
        key={objectKey}
        ref={(node) => {
          if (node) {
            node.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
            instanced.current.set(objectKey, node);
          } else instanced.current.delete(objectKey);
        }}
        args={[part.geometry, materials[part.material], Math.max(1, animals.length)]}
        count={animals.length}
        frustumCulled={false}
        castShadow={!lowQuality}
        receiveShadow={!lowQuality}
        onClick={handles}
        onPointerOver={() => { document.body.style.cursor = 'pointer'; }}
        onPointerOut={() => { document.body.style.cursor = ''; }}
      />;
    })}
    {farParts.map((part, index) => {
      const objectKey = `${part.key}-${index}`;
      return <instancedMesh
        key={objectKey}
        ref={(node) => {
          if (node) {
            node.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
            farInstanced.current.set(objectKey, node);
          } else farInstanced.current.delete(objectKey);
        }}
        args={[part.geometry, farMaterials[part.material], Math.max(1, animals.length)]}
        count={animals.length}
        frustumCulled={false}
        castShadow={!lowQuality}
        receiveShadow={!lowQuality}
        onClick={handles}
        onPointerOver={() => { document.body.style.cursor = 'pointer'; }}
        onPointerOut={() => { document.body.style.cursor = ''; }}
      />;
    })}
    {selectedId && animals.find((animal) => animal.animal_id === selectedId)?.scenePosition && (
      <SelectionRing animal={animals.find((animal) => animal.animal_id === selectedId)!} width={width} height={height} />
    )}
  </>;
}

function deterministicPhase(id: string): number {
  let hash = 0;
  for (const char of id) hash = (hash * 31 + char.charCodeAt(0)) | 0;
  return (Math.abs(hash) % 1000) / 1000 * Math.PI * 2;
}

function shortestAngle(from: number, to: number): number {
  return Math.atan2(Math.sin(to - from), Math.cos(to - from));
}

function SelectionRing({ animal, width, height }: { animal: SceneAnimal; width: number; height: number }) {
  const [x, y, z] = farmToWorld(animal.scenePosition!.x, animal.scenePosition!.y, width, height);
  const worldScale = Math.min(SCENE_WIDTH / Math.max(width, 1), SCENE_DEPTH / Math.max(height, 1));
  return <mesh position={[x, y + 0.05, z]} scale={[worldScale * 1.65, 1, worldScale * 1.65]} rotation={[-Math.PI / 2, 0, 0]}>
    <ringGeometry args={[0.85, 1.04, 36]} />
    <meshBasicMaterial color="#e8d05d" transparent opacity={0.95} side={THREE.DoubleSide} />
  </mesh>;
}

function AnchorNodes({ anchors, width, height, onSelect }: {
  anchors: Anchor[];
  width: number;
  height: number;
  onSelect: (anchor: Anchor) => void;
}) {
  return <group>
    {anchors.map((anchor) => {
      const [x, y, z] = farmToWorld(anchor.x, anchor.y, width, height);
      return <group key={anchor.anchor_id} position={[x, y, z]} onClick={(event) => { event.stopPropagation(); onSelect(anchor); }}>
        <mesh position={[0, 0.14, 0]} rotation={[Math.PI / 2, 0, 0]} castShadow><cylinderGeometry args={[0.2, 0.24, 0.28, 10]} /><meshStandardMaterial color="#e8e7dc" metalness={0.28} roughness={0.42} /></mesh>
        <mesh position={[0, Math.min(3.4, Math.max(1.6, anchor.height_m)), 0]} castShadow><cylinderGeometry args={[0.055, 0.07, Math.min(3.4, Math.max(1.6, anchor.height_m)), 8]} /><meshStandardMaterial color="#596357" metalness={0.18} roughness={0.7} /></mesh>
        <mesh position={[0, 3.45, 0]}><sphereGeometry args={[0.15, 12, 8]} /><meshStandardMaterial color="#d8bf51" emissive="#685c24" emissiveIntensity={0.24} /></mesh>
      </group>;
    })}
  </group>;
}

function RFLinks({ animals, anchors, telemetry, width, height }: {
  animals: SceneAnimal[];
  anchors: Anchor[];
  telemetry: Telemetry[];
  width: number;
  height: number;
}) {
  const geometry = useMemo(() => {
    const positions: number[] = [];
    const colors: number[] = [];
    const animalsByHardware = new Map(animals.map((animal) => [animal.hardware_id, animal]));
    const anchorsById = new Map(anchors.map((anchor) => [anchor.anchor_id, anchor]));
    for (const report of telemetry) {
      const animal = animalsByHardware.get(report.tag_id);
      const anchor = anchorsById.get(report.anchor_id);
      if (!animal?.estimate || animal.estimate.x == null || animal.estimate.y == null
        || !anchor || !report.packet_received || report.rssi_dbm == null) continue;
      const [ax, ay, az] = farmToWorld(animal.estimate.x!, animal.estimate.y!, width, height);
      const [bx, by, bz] = farmToWorld(anchor.x, anchor.y, width, height);
      positions.push(ax, ay + 1.35, az, bx, by + anchor.height_m, bz);
      const signal = THREE.MathUtils.clamp((report.rssi_dbm + 110) / 80, 0, 1);
      const color = new THREE.Color().setHSL(0.03 + signal * 0.29, 0.68, 0.48 + signal * 0.12);
      colors.push(color.r, color.g, color.b, color.r, color.g, color.b);
    }
    const result = new THREE.BufferGeometry();
    result.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    result.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
    return result;
  }, [animals, anchors, telemetry, width, height]);
  return <lineSegments geometry={geometry}><lineBasicMaterial vertexColors transparent opacity={0.52} depthWrite={false} /></lineSegments>;
}

function ObservedCoverage({ animals, width, height }: { animals: SceneAnimal[]; width: number; height: number }) {
  const ref = useRef<THREE.InstancedMesh>(null);
  const items = animals.filter((animal) => animal.estimate?.x != null && animal.estimate.y != null && animal.receivedLinks > 0);
  useEffect(() => {
    const dummy = new THREE.Object3D();
    items.forEach((animal, index) => {
      const [x, y, z] = farmToWorld(animal.estimate!.x!, animal.estimate!.y!, width, height);
      dummy.position.set(x, y + 0.08, z);
      dummy.rotation.set(-Math.PI / 2, 0, 0);
      dummy.scale.setScalar(0.35 + Math.min(4, animal.receivedLinks) * 0.11);
      dummy.updateMatrix();
      ref.current?.setMatrixAt(index, dummy.matrix);
      const strength = Math.min(1, Math.max(0, (animal.rssiDbm ?? -120) + 110) / 75);
      ref.current?.setColorAt(index, new THREE.Color().setHSL(0.02 + strength * 0.32, 0.72, 0.48));
    });
    if (ref.current) {
      ref.current.instanceMatrix.needsUpdate = true;
      if (ref.current.instanceColor) ref.current.instanceColor.needsUpdate = true;
    }
  }, [items, width, height]);
  return <instancedMesh ref={ref} args={[undefined as unknown as THREE.BufferGeometry, undefined as unknown as THREE.Material, Math.max(1, items.length)]} count={items.length}>
    <circleGeometry args={[1, 20]} /><meshBasicMaterial vertexColors transparent opacity={0.72} depthWrite={false} side={THREE.DoubleSide} />
  </instancedMesh>;
}

function PositionMarkers({ animals, width, height, uncertainty }: {
  animals: SceneAnimal[];
  width: number;
  height: number;
  uncertainty: boolean;
}) {
  const ref = useRef<THREE.InstancedMesh>(null);
  const items = animals.filter((animal) => animal.estimate?.x != null && animal.estimate.y != null);
  useEffect(() => {
    const dummy = new THREE.Object3D();
    items.forEach((animal, index) => {
      const [x, y, z] = farmToWorld(animal.estimate!.x!, animal.estimate!.y!, width, height);
      const quality = THREE.MathUtils.clamp(animal.estimate?.quality ?? 0, 0, 1);
      const radius = uncertainty ? 0.8 + (1 - quality) * 2.6 : 0.16;
      dummy.position.set(x, y + (uncertainty ? 0.06 : 0.12), z);
      dummy.rotation.set(-Math.PI / 2, 0, 0);
      dummy.scale.setScalar(radius);
      dummy.updateMatrix();
      ref.current?.setMatrixAt(index, dummy.matrix);
      ref.current?.setColorAt(index, new THREE.Color(uncertainty ? '#d7c76f' : '#faf9f0'));
    });
    if (ref.current) {
      ref.current.instanceMatrix.needsUpdate = true;
      if (ref.current.instanceColor) ref.current.instanceColor.needsUpdate = true;
    }
  }, [items, width, height, uncertainty]);
  return <instancedMesh ref={ref} args={[undefined as unknown as THREE.BufferGeometry, undefined as unknown as THREE.Material, Math.max(1, items.length)]} count={items.length}>
    <ringGeometry args={[uncertainty ? 0.92 : 0.01, 1, 20]} />
    <meshBasicMaterial vertexColors transparent opacity={uncertainty ? 0.28 : 0.74} depthWrite={false} side={THREE.DoubleSide} />
  </instancedMesh>;
}

function TrackingLine({ points, width, height }: { points: TrajectoryPoint[]; width: number; height: number }) {
  const geometry = useMemo(() => {
    const vertices: number[] = [];
    // Keep a short local trace at close zoom; long simulator history remains
    // available in the animal record and does not overwhelm the field view.
    for (const point of points.slice(-6)) {
      if (point.x == null || point.y == null) continue;
      const [x, ground, z] = farmToWorld(point.x, point.y, width, height);
      vertices.push(x, ground + 0.14, z);
    }
    const result = new THREE.BufferGeometry();
    result.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
    return result;
  }, [points, width, height]);
  const material = useMemo(() => new THREE.LineBasicMaterial({ color: '#d6c75b', transparent: true, opacity: 0.38 }), []);
  const line = useMemo(() => new THREE.Line(geometry, material), [geometry, material]);
  return <primitive object={line} />;
}

const WORLD_UP = new THREE.Vector3(0, 1, 0);
const HOOF_OFFSETS: Array<[number, number]> = [[0.43, 0.22], [0.43, -0.22], [-0.48, 0.22], [-0.48, -0.22]];

function fitFarmCamera(controls: CameraControlsImpl, width: number, height: number, aspect: number, animate: boolean): void {
  const [farmWidth, farmDepth] = farmWorldSize(width, height);
  const halfWidth = Math.max(SCENE_WIDTH / 2, farmWidth / 2);
  const halfDepth = Math.max(SCENE_DEPTH / 2, farmDepth / 2);
  const bounds = new THREE.Box3(
    new THREE.Vector3(-halfWidth, -2.6, -halfDepth),
    new THREE.Vector3(halfWidth, 10, halfDepth),
  );
  const target = new THREE.Vector3(0, 1.1, 0);
  const direction = new THREE.Vector3(1, 1.15, 1).normalize();
  const right = new THREE.Vector3().crossVectors(direction, WORLD_UP).normalize();
  const screenUp = new THREE.Vector3().crossVectors(right, direction).normalize();
  const verticalTan = Math.tan(THREE.MathUtils.degToRad(21));
  const horizontalTan = verticalTan * Math.max(0.35, aspect);
  let distance = 0;
  for (const x of [bounds.min.x, bounds.max.x]) {
    for (const y of [bounds.min.y, bounds.max.y]) {
      for (const z of [bounds.min.z, bounds.max.z]) {
        const offset = new THREE.Vector3(x, y, z).sub(target);
        const forwardDepth = offset.dot(direction);
        distance = Math.max(
          distance,
          forwardDepth + Math.abs(offset.dot(right)) / horizontalTan,
          forwardDepth + Math.abs(offset.dot(screenUp)) / verticalTan,
        );
      }
    }
  }
  distance *= 1.08;
  const position = target.clone().addScaledVector(direction, distance);
  controls.setLookAt(position.x, position.y, position.z, target.x, target.y, target.z, animate);
}

function CameraFocus({ controlRef, animal, anchors, width, height, mode, modeRevision, onCameraReady }: {
  controlRef: RefObject<CameraControlsImpl | null>;
  animal: SceneAnimal | null;
  anchors: Anchor[];
  width: number;
  height: number;
  mode: SceneMode;
  modeRevision: number;
  onCameraReady: () => void;
}) {
  const size = useThree((state) => state.size);
  const cameraReady = useRef(false);
  const trackingReady = useRef(false);
  const trackingZooming = useRef(false);
  const trackedTarget = useMemo(() => new THREE.Vector3(), []);
  const liveTarget = useMemo(() => new THREE.Vector3(), []);
  const livePosition = useMemo(() => new THREE.Vector3(), []);
  const cameraOffset = useMemo(() => new THREE.Vector3(), []);
  const focusOffset = useMemo(() => new THREE.Vector3(), []);
  const anchorKey = anchors.map((anchor) => `${anchor.anchor_id}:${anchor.x}:${anchor.y}`).join('|');
  useFrame((_, delta) => {
    const controls = controlRef.current;
    if (!controls || !trackingReady.current || mode !== 'track' || !animal?.scenePosition) return;
    const [x, ground, z] = farmToWorld(animal.scenePosition.x, animal.scenePosition.y, width, height);
    // Aim at the animal's body center rather than its feet. This keeps the
    // close camera from making foreground fence rails dominate the frame.
    liveTarget.set(x, ground + 0.72, z);
    controls.getTarget(trackedTarget);
    controls.getPosition(livePosition);
    if (SHOW_FARM_DIAGNOSTICS) {
      const viewport = document.querySelector<HTMLElement>('.farm-viewport');
      if (viewport) viewport.dataset.cameraDistance = livePosition.distanceTo(trackedTarget).toFixed(2);
    }
    cameraOffset.copy(livePosition).sub(trackedTarget);
    const follow = 1 - Math.exp(-Math.max(0, Math.min(delta, 0.1)) * 4.2);
    trackedTarget.lerp(liveTarget, follow);
    if (trackingZooming.current) {
      cameraOffset.lerp(focusOffset, 1 - Math.exp(-Math.max(0, Math.min(delta, 0.1)) * 3.5));
      if (cameraOffset.distanceToSquared(focusOffset) < 0.0025) trackingZooming.current = false;
    }
    livePosition.copy(trackedTarget).add(cameraOffset);
    // Follow through the actual frame loop instead of restarting camera easing
    // every time a new RF estimate arrives.
    controls.setLookAt(
      livePosition.x, livePosition.y, livePosition.z,
      trackedTarget.x, trackedTarget.y, trackedTarget.z,
      false,
    );
  });
  useEffect(() => {
    const controls = controlRef.current;
    if (SHOW_FARM_DIAGNOSTICS) {
      const viewport = document.querySelector<HTMLElement>('.farm-viewport');
      if (viewport) {
        viewport.dataset.cameraMode = mode;
        viewport.dataset.trackHasPose = String(Boolean(animal?.scenePosition));
      }
    }
    if (!controls) return;
    const [farmWidth, farmDepth] = farmWorldSize(width, height);
    if (mode === 'overview') {
      trackingReady.current = false;
      trackingZooming.current = false;
      fitFarmCamera(controls, width, height, size.width / Math.max(size.height, 1), cameraReady.current);
      if (!cameraReady.current) {
        cameraReady.current = true;
        onCameraReady();
      }
      return;
    }
    if (mode === 'rf' || mode === 'coverage') {
      trackingReady.current = false;
      trackingZooming.current = false;
      const center = anchors.length
        ? anchors.reduce((sum, anchor) => {
          const [x, , z] = farmToWorld(anchor.x, anchor.y, width, height);
          return [sum[0] + x / anchors.length, sum[1] + z / anchors.length];
        }, [0, 0])
        : [0, 0];
      if (mode === 'coverage') {
        controls.setLookAt(center[0] + 0.05, Math.max(farmWidth, farmDepth) * 1.12, center[1] + 0.05, center[0], 0, center[1], true);
      } else {
        controls.setLookAt(center[0] + 29, 33, center[1] + 31, center[0], 0, center[1], true);
      }
      if (!cameraReady.current) {
        cameraReady.current = true;
        onCameraReady();
      }
      return;
    }
    if (mode === 'track' && animal?.scenePosition) {
      // Keep a farm-context individual view. At the previous ~2 m distance,
      // nearby fence rails filled most of the viewport and hid the selected cow.
      const trackDistance = Math.max(4.8, Math.max(farmWidth, farmDepth) * 0.018);
      trackingReady.current = false;
      // Keep enough pasture around the selected cow for context while framing
      // the actual animal at an individual inspection scale in a large farm.
      focusOffset.set(trackDistance * 0.58, trackDistance * 0.62, trackDistance * 0.58);
      if (SHOW_FARM_DIAGNOSTICS) {
        const viewport = document.querySelector<HTMLElement>('.farm-viewport');
        if (viewport) viewport.dataset.cameraFocusIssued = 'true';
      }
      trackingReady.current = true;
      trackingZooming.current = true;
      if (!cameraReady.current) {
        cameraReady.current = true;
        onCameraReady();
      }
    }
  }, [mode, modeRevision, animal?.animal_id, controlRef, anchorKey, width, height, size.width, size.height, onCameraReady]);
  return null;
}

type SceneMode = 'overview' | 'rf' | 'coverage' | 'track';

export interface ScenePerformance {
  fps: number;
  drawCalls: number;
  triangles: number;
  frameStalls: number;
  maxFrameMs: number;
  p95FrameMs: number;
  p99FrameMs: number;
}

export interface FarmSceneProps {
  animals: SceneAnimal[];
  anchors: Anchor[];
  telemetry: Telemetry[];
  selected: SceneAnimal | null;
  width: number;
  height: number;
  lowQuality: boolean;
  paused: boolean;
  runId: string | null;
  playbackSpeed: number;
  onFirstFrame: () => void;
  onAssetError: (message: string) => void;
  onCameraReady: () => void;
  showLinks: boolean;
  showCoverage: boolean;
  showEstimates: boolean;
  showUncertainty: boolean;
  selectedTrack: TrajectoryPoint[];
  trackEnabled: boolean;
  mode: SceneMode;
  modeRevision: number;
  onSelectAnimal: (animal: SceneAnimal) => void;
  onSelectAnchor: (anchor: Anchor) => void;
  onClearSelection: () => void;
  controlsRef: React.RefObject<CameraControlsImpl | null>;
  onPerformance: (performance: ScenePerformance) => void;
}

export function FarmScene(props: FarmSceneProps) {
  const {
    animals, anchors, telemetry, selected, width, height, lowQuality, paused, runId, playbackSpeed, onFirstFrame, onAssetError, onCameraReady,
    showLinks, showCoverage, showEstimates, showUncertainty, selectedTrack,
    trackEnabled, mode, modeRevision, onSelectAnimal, onSelectAnchor, onClearSelection, controlsRef, onPerformance,
  } = props;
  const frameStats = useRef({ elapsed: 0, frames: 0, lastSent: 0, frameStalls: 0, maxFrameMs: 0, samples: [] as number[] });
  const firstFrameSent = useRef(false);
  const herdReady = useRef(false);
  useFrame((state, delta) => {
    if (!firstFrameSent.current && herdReady.current) {
      firstFrameSent.current = true;
      requestAnimationFrame(onFirstFrame);
    }
    const stats = frameStats.current;
    stats.elapsed += delta;
    stats.frames += 1;
    const frameMs = delta * 1000;
    stats.samples.push(frameMs);
    if (stats.samples.length > 240) stats.samples.shift();
    if (frameMs > 50) stats.frameStalls += 1;
    stats.maxFrameMs = Math.max(stats.maxFrameMs, frameMs);
    const now = performance.now();
    if (now - stats.lastSent > 800) {
      const ordered = [...stats.samples].sort((a, b) => a - b);
      const percentile = (fraction: number) => ordered.length ? Math.round(ordered[Math.min(ordered.length - 1, Math.ceil(ordered.length * fraction) - 1)] * 10) / 10 : 0;
      onPerformance({
        fps: Math.round(stats.frames / Math.max(stats.elapsed, 0.001)),
        drawCalls: state.gl.info.render.calls,
        triangles: state.gl.info.render.triangles,
        frameStalls: stats.frameStalls,
        maxFrameMs: Math.round(stats.maxFrameMs * 10) / 10,
        p95FrameMs: percentile(0.95),
        p99FrameMs: percentile(0.99),
      });
      stats.elapsed = 0;
      stats.frames = 0;
      stats.frameStalls = 0;
      stats.maxFrameMs = 0;
      stats.lastSent = now;
    }
  });

  const widthM = Math.max(1, width);
  const heightM = Math.max(1, height);
  const focusRegion = useCallback((point: THREE.Vector3) => {
    const distance = Math.max(15, Math.min(30, Math.max(widthM, heightM) * 0.32));
    const ground = terrainHeight(point.x, point.z);
    controlsRef.current?.setLookAt(point.x + distance * 0.68, ground + distance * 0.82, point.z + distance * 0.68, point.x, ground, point.z, true);
  }, [controlsRef, widthM, heightM]);
  return <>
    <color attach="background" args={['#e8e7df']} />
    <fog attach="fog" args={['#e8e7df', 280, 520]} />
    <hemisphereLight args={['#fffdf4', '#718064', 1.65]} />
    <directionalLight position={[-22, 30, 16]} intensity={2.2} castShadow={!lowQuality}
      shadow-mapSize-width={lowQuality ? 512 : 1536} shadow-mapSize-height={lowQuality ? 512 : 1536}
      shadow-camera-left={-48} shadow-camera-right={48} shadow-camera-top={42} shadow-camera-bottom={-42} />
    <directionalLight position={[18, 12, -18]} intensity={0.5} color="#dce6ed" />
    <mesh position={[0, -4, 0]} rotation={[-Math.PI / 2, 0, 0]} receiveShadow><planeGeometry args={[640, 640]} /><meshStandardMaterial color="#e8e7df" roughness={1} /></mesh>
    <Terrain lowQuality={lowQuality} onDoubleClick={focusRegion} />
    <Grass lowQuality={lowQuality} />
    <TreeLine lowQuality={lowQuality} />
    <ShrubClusters lowQuality={lowQuality} />
    <FarmPaths />
    <Fence width={widthM} height={heightM} />
    <PastureFences />
    <FarmStructures />
    <CowAssetBoundary onError={(message) => {
      herdReady.current = true;
      onAssetError(message);
    }}>
      <Suspense fallback={null}>
        <CowHerd animals={animals} selectedId={selected?.animal_id ?? null} onSelect={onSelectAnimal}
          width={widthM} height={heightM} lowQuality={lowQuality} paused={paused} playbackSpeed={playbackSpeed} runId={runId}
          onReady={() => { herdReady.current = true; }} />
      </Suspense>
    </CowAssetBoundary>
    <AnchorNodes anchors={anchors} width={widthM} height={heightM} onSelect={onSelectAnchor} />
    {showLinks && <RFLinks animals={animals} anchors={anchors} telemetry={telemetry} width={widthM} height={heightM} />}
    {showCoverage && <ObservedCoverage animals={animals} width={widthM} height={heightM} />}
    {showEstimates && <PositionMarkers animals={animals} width={widthM} height={heightM} uncertainty={false} />}
    {showUncertainty && <PositionMarkers animals={animals} width={widthM} height={heightM} uncertainty />}
    {trackEnabled && selectedTrack.length > 1 && <TrackingLine points={selectedTrack} width={widthM} height={heightM} />}
    <CameraFocus controlRef={controlsRef} animal={selected} anchors={anchors} width={widthM} height={heightM} mode={mode} modeRevision={modeRevision} onCameraReady={onCameraReady} />
    <CameraControls ref={controlsRef} makeDefault minDistance={Math.max(4.2, Math.min(SCENE_WIDTH / widthM, SCENE_DEPTH / heightM) * 4.4)} maxDistance={Math.max(650, Math.hypot(...farmWorldSize(widthM, heightM)) * 4)} smoothTime={0.78} dollySpeed={0.62} truckSpeed={1.05} />
    <mesh position={[0, -0.9, 0]} rotation={[-Math.PI / 2, 0, 0]} onClick={onClearSelection} visible={false}>
      <planeGeometry args={[SCENE_WIDTH, SCENE_DEPTH]} /><meshBasicMaterial transparent opacity={0} />
    </mesh>
  </>;
}
