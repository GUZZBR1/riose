import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib';
import * as THREE from 'three';

type AssemblyMode = 'exploded' | 'assembled';
type PartName = 'Upper housing' | 'Circuit board' | 'Power cell' | 'Lower housing';
type PartBounds = { min: THREE.Vector3; max: THREE.Vector3 };
type AssemblyBounds = Record<PartName, PartBounds>;

const PARTS: PartName[] = ['Upper housing', 'Circuit board', 'Power cell', 'Lower housing'];
const EXPLODED_GAP = 1.05;

function tagOutline(scale = 1): THREE.Shape {
  const shape = new THREE.Shape();
  const sx = (value: number) => value * scale;
  const sy = (value: number) => value * scale;
  shape.moveTo(sx(-0.14), sy(1.2));
  shape.bezierCurveTo(sx(-0.28), sy(1.2), sx(-0.35), sy(1.05), sx(-0.35), sy(0.78));
  shape.bezierCurveTo(sx(-0.36), sy(0.55), sx(-0.57), sy(0.44), sx(-0.78), sy(0.31));
  shape.bezierCurveTo(sx(-0.96), sy(0.2), sx(-1.02), sy(0.1), sx(-1.02), sy(-0.08));
  shape.lineTo(sx(-1.02), sy(-1.12));
  shape.bezierCurveTo(sx(-1.02), sy(-1.24), sx(-0.93), sy(-1.31), sx(-0.79), sy(-1.32));
  shape.lineTo(sx(0.75), sy(-1.32));
  shape.bezierCurveTo(sx(0.9), sy(-1.32), sx(1.01), sy(-1.25), sx(1.01), sy(-1.11));
  shape.lineTo(sx(1.01), sy(-0.08));
  shape.bezierCurveTo(sx(1.01), sy(0.1), sx(0.94), sy(0.2), sx(0.77), sy(0.31));
  shape.bezierCurveTo(sx(0.57), sy(0.44), sx(0.36), sy(0.55), sx(0.35), sy(0.78));
  shape.bezierCurveTo(sx(0.35), sy(1.05), sx(0.28), sy(1.2), sx(0.14), sy(1.2));
  shape.bezierCurveTo(sx(0.06), sy(1.2), sx(-0.06), sy(1.2), sx(-0.14), sy(1.2));
  return shape;
}

function eased(current: number, target: number, dt: number): number {
  return THREE.MathUtils.damp(current, target, 11, dt);
}

interface PartProps {
  name: PartName;
  selected: boolean;
  position: [number, number, number];
  reducedMotion: boolean;
  onSelect: (name: PartName) => void;
  onFocus: (name: PartName, point: THREE.Vector3) => void;
  onMeasure: (name: PartName, bounds: PartBounds) => void;
  children: ReactNode;
}

function InteractivePart({ name, selected, position, reducedMotion, onSelect, onFocus, onMeasure, children }: PartProps) {
  const group = useRef<THREE.Group>(null);
  const invalidate = useThree((state) => state.invalidate);
  const initialPosition = useRef(position);
  const [hovered, setHovered] = useState(false);

  useLayoutEffect(() => {
    const object = group.current;
    if (!object) return;
    object.updateWorldMatrix(true, true);
    const worldBounds = new THREE.Box3().setFromObject(object);
    const offset = new THREE.Vector3(...initialPosition.current);
    onMeasure(name, {
      min: worldBounds.min.sub(offset),
      max: worldBounds.max.sub(offset),
    });
  }, [name, onMeasure]);

  useEffect(() => { invalidate(); }, [invalidate, position, selected]);

  useFrame((_, dt) => {
    if (!group.current) return;
    const motion = reducedMotion ? 1 : dt;
    group.current.position.x = reducedMotion ? position[0] : eased(group.current.position.x, position[0], motion);
    group.current.position.y = reducedMotion ? position[1] : eased(group.current.position.y, position[1], motion);
    const targetZ = position[2] + (selected || hovered ? 0.055 : 0);
    group.current.position.z = reducedMotion ? targetZ : eased(group.current.position.z, targetZ, motion);
    const targetScale = selected || hovered ? 1.025 : 1;
    const scale = reducedMotion ? targetScale : eased(group.current.scale.x, targetScale, motion);
    group.current.scale.setScalar(scale);
    const unsettled = Math.abs(group.current.position.x - position[0]) > 0.001
      || Math.abs(group.current.position.y - position[1]) > 0.001
      || Math.abs(group.current.position.z - targetZ) > 0.001
      || Math.abs(group.current.scale.x - targetScale) > 0.001;
    if (unsettled) invalidate();
  });

  return <group
    ref={group}
    position={position}
    onClick={(event) => {
      event.stopPropagation();
      onSelect(name);
    }}
    onDoubleClick={(event) => { event.stopPropagation(); onFocus(name, event.point.clone()); }}
    onPointerOver={(event) => { event.stopPropagation(); setHovered(true); invalidate(); document.body.style.cursor = 'pointer'; }}
    onPointerOut={(event) => { event.stopPropagation(); setHovered(false); invalidate(); document.body.style.cursor = ''; }}
  >
    {children}
  </group>;
}

interface ModelProps {
  mode: AssemblyMode;
  selectedPart: PartName | null;
  onSelect: (name: PartName) => void;
  onFocus: (name: PartName, point: THREE.Vector3) => void;
  onFocusComplete: () => void;
  onReset: () => void;
  focusTarget: THREE.Vector3 | null;
  controls: React.RefObject<OrbitControlsImpl | null>;
  reducedMotion: boolean;
}

function AssemblyModel({ mode, selectedPart, onSelect, onFocus, onFocusComplete, onReset, focusTarget, controls, reducedMotion }: ModelProps) {
  const { camera, size, invalidate } = useThree();
  const measuredParts = useRef(new Map<PartName, PartBounds>());
  const [partBounds, setPartBounds] = useState<AssemblyBounds | null>(null);
  const initialFitApplied = useRef(false);
  const homeCamera = useRef<THREE.Vector3>(new THREE.Vector3(0, 0, 14));
  const homeTarget = useRef<THREE.Vector3>(new THREE.Vector3());
  const shapes = useMemo(() => ({ full: tagOutline(), board: tagOutline(0.64), lower: tagOutline(0.76) }), []);
  const geometry = useMemo(() => ({
    upper: new THREE.ExtrudeGeometry(shapes.full, { depth: 0.13, bevelEnabled: true, bevelSegments: 5, bevelSize: 0.025, bevelThickness: 0.02, curveSegments: 32 }),
    upperFace: new THREE.ShapeGeometry(tagOutline(0.965), 28),
    board: new THREE.ExtrudeGeometry(shapes.board, { depth: 0.06, bevelEnabled: true, bevelSegments: 3, bevelSize: 0.016, bevelThickness: 0.01, curveSegments: 24 }),
    lower: new THREE.ExtrudeGeometry(shapes.lower, { depth: 0.14, bevelEnabled: true, bevelSegments: 4, bevelSize: 0.022, bevelThickness: 0.018, curveSegments: 28 }),
    traces: [
      [[-0.52, -0.12], [-0.51, -0.38], [-0.46, -0.59], [-0.31, -0.76], [-0.08, -0.82], [0.2, -0.78], [0.48, -0.64], [0.49, -0.35]],
      [[-0.45, -0.12], [-0.44, -0.38], [-0.39, -0.57], [-0.25, -0.7], [-0.06, -0.75], [0.19, -0.7], [0.42, -0.59], [0.43, -0.35]],
      [[0.15, -0.28], [0.28, -0.28], [0.34, -0.33], [0.36, -0.51], [0.29, -0.6]],
      [[-0.2, -0.32], [-0.3, -0.32], [-0.36, -0.37], [-0.38, -0.53], [-0.28, -0.62]],
    ].map((coordinates, index) => {
      const route = new THREE.CatmullRomCurve3(coordinates.map(([x, y]) => new THREE.Vector3(x, y, 0.044 + index * 0.002)));
      return new THREE.TubeGeometry(route, 48, index < 2 ? 0.011 : 0.008, 6, false);
    }),
  }), [shapes]);
  const materials = useMemo(() => ({
    shell: new THREE.MeshStandardMaterial({ color: '#f1c91a', roughness: 0.54, metalness: 0.015, side: THREE.DoubleSide }),
    shellEdge: new THREE.MeshStandardMaterial({ color: '#dcae0b', roughness: 0.62, metalness: 0.02, side: THREE.DoubleSide }),
    board: new THREE.MeshStandardMaterial({ color: '#17583f', roughness: 0.68, metalness: 0.025, side: THREE.DoubleSide }),
    copper: new THREE.MeshStandardMaterial({ color: '#c89143', roughness: 0.36, metalness: 0.62 }),
    chip: new THREE.MeshStandardMaterial({ color: '#222724', roughness: 0.52, metalness: 0.08 }),
    battery: new THREE.MeshStandardMaterial({ color: '#bfc0bc', roughness: 0.32, metalness: 0.76 }),
    dark: new THREE.MeshStandardMaterial({ color: '#2d302c', roughness: 0.7, metalness: 0.04 }),
    cavity: new THREE.MeshStandardMaterial({ color: '#dfa90b', roughness: 0.7, metalness: 0.01, side: THREE.DoubleSide }),
  }), []);
  const shadowTexture = useMemo(() => {
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = 128;
    const context = canvas.getContext('2d');
    if (context) {
      const gradient = context.createRadialGradient(64, 64, 2, 64, 64, 62);
      gradient.addColorStop(0, 'rgba(63,57,39,0.23)');
      gradient.addColorStop(0.45, 'rgba(63,57,39,0.09)');
      gradient.addColorStop(1, 'rgba(63,57,39,0)');
      context.fillStyle = gradient;
      context.fillRect(0, 0, 128, 128);
    }
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    return texture;
  }, []);
  useEffect(() => () => shadowTexture.dispose(), [shadowTexture]);

  const onMeasure = useCallback((name: PartName, bounds: PartBounds) => {
    measuredParts.current.set(name, bounds);
    if (PARTS.every((part) => measuredParts.current.has(part))) {
      const next = Object.fromEntries(PARTS.map((part) => [part, measuredParts.current.get(part)!])) as AssemblyBounds;
      setPartBounds((previous) => {
        if (!previous) return next;
        const unchanged = PARTS.every((part) =>
          previous[part].min.distanceToSquared(next[part].min) < 1e-10
          && previous[part].max.distanceToSquared(next[part].max) < 1e-10,
        );
        return unchanged ? previous : next;
      });
    }
  }, []);

  const fallbackBounds = useMemo<AssemblyBounds>(() => ({
    'Upper housing': { min: new THREE.Vector3(-1.1, -1.4, -0.1), max: new THREE.Vector3(1.1, 1.3, 0.25) },
    'Circuit board': { min: new THREE.Vector3(-0.8, -0.9, -0.1), max: new THREE.Vector3(0.8, 0.8, 0.2) },
    'Power cell': { min: new THREE.Vector3(-0.4, -0.4, -0.4), max: new THREE.Vector3(0.4, 0.4, 0.4) },
    'Lower housing': { min: new THREE.Vector3(-0.9, -1.1, -0.1), max: new THREE.Vector3(0.9, 1, 0.2) },
  }), []);
  const bounds = partBounds ?? fallbackBounds;
  const explodedPositions = useMemo(() => {
    const values = {} as Record<PartName, [number, number, number]>;
    let previousBottom = 0;
    PARTS.forEach((name, index) => {
      const part = bounds[name];
      const localCenterY = (part.min.y + part.max.y) * 0.5;
      const halfHeight = (part.max.y - part.min.y) * 0.5;
      const worldCenterY = index === 0 ? 0 : previousBottom - EXPLODED_GAP - halfHeight;
      values[name] = [0, worldCenterY - localCenterY, 0.12];
      previousBottom = worldCenterY - halfHeight;
    });
    return values;
  }, [bounds]);
  const positions = useMemo(() => mode === 'exploded' ? explodedPositions : {
    'Upper housing': [0, 0, 0.15] as [number, number, number],
    'Circuit board': [0, 0, 0.03] as [number, number, number],
    'Power cell': [0, 0, -0.02] as [number, number, number],
    'Lower housing': [0, 0, -0.14] as [number, number, number],
  }, [explodedPositions, mode]);

  const framing = useMemo(() => {
    const box = new THREE.Box3();
    PARTS.forEach((name) => {
      const offset = new THREE.Vector3(...explodedPositions[name]);
      box.expandByPoint(bounds[name].min.clone().add(offset));
      box.expandByPoint(bounds[name].max.clone().add(offset));
    });
    const center = box.getCenter(new THREE.Vector3());
    const dimensions = box.getSize(new THREE.Vector3());
    const fov = THREE.MathUtils.degToRad(32);
    const aspect = Math.max(size.width / Math.max(size.height, 1), 0.45);
    // Include perspective depth and the 3/4 orbit angle in the fit margin.
    // A near-edge-to-edge fit made the top shell and lower housing appear
    // clipped, especially on narrow/mobile canvases.
    const fitHeight = dimensions.y * 0.62 / Math.tan(fov / 2);
    const fitWidth = dimensions.x * 0.62 / (Math.tan(fov / 2) * aspect);
    const distance = Math.max(fitHeight, fitWidth, 6.4);
    const direction = new THREE.Vector3(0.45, 0.28, 1).normalize();
    return { center, position: center.clone().addScaledVector(direction, distance) };
  }, [bounds, explodedPositions, size.height, size.width]);

  useEffect(() => {
    if (!partBounds) return;
    if (initialFitApplied.current) {
      // A resize may require a little more distance on a narrow viewport. Keep
      // the user's current target and orbit direction; never re-home the view.
      const target = controls.current?.target ?? homeTarget.current;
      const direction = camera.position.clone().sub(target);
      const currentDistance = direction.length();
      const fitDistance = framing.position.distanceTo(framing.center);
      if (currentDistance < fitDistance) {
        direction.normalize();
        camera.position.copy(target).addScaledVector(direction, fitDistance);
      }
      camera.updateProjectionMatrix();
      controls.current?.update();
      homeCamera.current.copy(framing.position);
      homeTarget.current.copy(framing.center);
      return;
    }
    camera.position.copy(framing.position);
    camera.lookAt(framing.center);
    camera.updateProjectionMatrix();
    if (controls.current) {
      controls.current.target.copy(framing.center);
      controls.current.update();
    }
    homeCamera.current.copy(framing.position);
    homeTarget.current.copy(framing.center);
    initialFitApplied.current = true;
  }, [camera, framing, controls]);

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() !== 'r' || /input|textarea|select/i.test((event.target as HTMLElement)?.tagName ?? '')) return;
      camera.position.copy(homeCamera.current);
      camera.lookAt(homeTarget.current);
      onReset();
      if (controls.current) {
        controls.current.target.copy(homeTarget.current);
        controls.current.update();
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [camera, controls, onReset]);

  useEffect(() => { invalidate(); }, [focusTarget, invalidate]);

  useFrame((_, dt) => {
    if (!controls.current || !focusTarget) return;
    const target = controls.current.target;
    target.lerp(focusTarget, 1 - Math.exp(-dt * 2.8));
    controls.current.update();
    if (target.distanceToSquared(focusTarget) < 0.0004) onFocusComplete();
    else invalidate();
  });

  const choose = (name: PartName) => onSelect(name);
  const focus = (name: PartName, point: THREE.Vector3) => {
    onSelect(name);
    onFocus(name, point);
  };
  return <>
    <ambientLight intensity={1.35} />
    <hemisphereLight args={['#fffdf4', '#98927a', 1.1]} />
    <directionalLight position={[-4, 6, 8]} intensity={2.4} color="#fff4d4" />
    <directionalLight position={[4, -1, 4]} intensity={0.75} color="#ffffff" />
    <directionalLight position={[1, 3, -5]} intensity={1.2} color="#fff7e8" />
    <mesh position={[0, 0.45, -0.48]} scale={[2.6, 0.88, 1]}>
      <planeGeometry args={[2, 2]} />
      <meshBasicMaterial map={shadowTexture} transparent depthWrite={false} opacity={0.38} />
    </mesh>
    <mesh position={[0, -0.78, -0.36]} scale={[1.65, 0.55, 1]}>
      <planeGeometry args={[2, 2]} />
      <meshBasicMaterial map={shadowTexture} transparent depthWrite={false} opacity={0.31} />
    </mesh>

    <InteractivePart name="Upper housing" selected={selectedPart === 'Upper housing'} position={positions['Upper housing']} reducedMotion={reducedMotion} onSelect={choose} onFocus={focus} onMeasure={onMeasure}>
      <mesh geometry={geometry.upper} material={materials.shell} position={[0, 0, -0.065]} castShadow receiveShadow />
      <mesh geometry={geometry.upperFace} material={materials.shell} position={[0, 0, 0.075]} />
      <mesh position={[0, 0.86, 0.115]}>
        <cylinderGeometry args={[0.3, 0.31, 0.09, 48]} />
        <meshStandardMaterial color="#e3b608" roughness={0.43} metalness={0.025} />
      </mesh>
      <mesh position={[0, 0.86, 0.172]}>
        <torusGeometry args={[0.19, 0.032, 12, 48]} />
        <meshStandardMaterial color="#cda20b" roughness={0.42} metalness={0.04} />
      </mesh>
      <mesh position={[0, 0.86, 0.18]}>
        <circleGeometry args={[0.135, 40]} />
        <meshStandardMaterial color="#262824" roughness={0.3} metalness={0.42} />
      </mesh>
    </InteractivePart>

    <InteractivePart name="Circuit board" selected={selectedPart === 'Circuit board'} position={positions['Circuit board']} reducedMotion={reducedMotion} onSelect={choose} onFocus={focus} onMeasure={onMeasure}>
      <mesh geometry={geometry.board} material={materials.board} position={[0, 0, -0.03]} castShadow receiveShadow />
      {geometry.traces.map((trace, index) => <mesh key={index} geometry={trace} material={materials.copper} />)}
      <mesh position={[-0.06, -0.42, 0.085]}>
        <boxGeometry args={[0.46, 0.35, 0.1]} />
        <meshStandardMaterial color="#343a35" roughness={0.42} metalness={0.09} />
      </mesh>
      <mesh position={[-0.06, -0.42, 0.14]}>
        <boxGeometry args={[0.34, 0.24, 0.03]} />
        <meshStandardMaterial color="#171b18" roughness={0.5} metalness={0.04} />
      </mesh>
      {[
        [-0.47, -0.25, 0.13, 0.09], [0.45, -0.32, 0.14, 0.1],
        [0.38, -0.72, 0.13, 0.09], [-0.3, -0.82, 0.12, 0.08],
      ].map(([x, y, w, h], index) => <mesh key={index} position={[x, y, 0.07]}>
        <boxGeometry args={[w, h, 0.055]} />
        <meshStandardMaterial color="#292f2b" roughness={0.5} metalness={0.1} />
      </mesh>)}
      {[-0.51, 0.51].map((x) => <mesh key={x} position={[x, -0.62, 0.05]}>
        <boxGeometry args={[0.045, 0.58, 0.018]} />
        <meshStandardMaterial color="#d3a252" roughness={0.36} metalness={0.62} />
      </mesh>)}
      {Array.from({ length: 9 }, (_, index) => -0.16 - index * 0.064).flatMap((y) => [-0.58, 0.58].map((x) => <mesh key={`${x}-${y}`} position={[x, y, 0.052]}>
        <boxGeometry args={[0.028, 0.018, 0.012]} />
        <meshStandardMaterial color="#d9ab5a" roughness={0.34} metalness={0.67} />
      </mesh>))}
    </InteractivePart>

    <InteractivePart name="Power cell" selected={selectedPart === 'Power cell'} position={positions['Power cell']} reducedMotion={reducedMotion} onSelect={choose} onFocus={focus} onMeasure={onMeasure}>
      <mesh position={[0, 0, 0]} rotation={[Math.PI / 2, 0, 0]} castShadow receiveShadow>
        <cylinderGeometry args={[0.39, 0.39, 0.2, 64, 1]} />
        <meshStandardMaterial color="#bfc0bc" roughness={0.3} metalness={0.72} />
      </mesh>
      <mesh position={[0, 0, 0.105]}>
        <torusGeometry args={[0.345, 0.018, 10, 64]} />
        <meshStandardMaterial color="#f0f0eb" roughness={0.24} metalness={0.8} />
      </mesh>
      <mesh position={[0, 0, 0.107]}>
        <circleGeometry args={[0.29, 56]} />
        <meshStandardMaterial color="#c9cac5" roughness={0.48} metalness={0.58} />
      </mesh>
    </InteractivePart>

    <InteractivePart name="Lower housing" selected={selectedPart === 'Lower housing'} position={positions['Lower housing']} reducedMotion={reducedMotion} onSelect={choose} onFocus={focus} onMeasure={onMeasure}>
      <mesh geometry={geometry.lower} material={materials.shellEdge} position={[0, 0, -0.07]} castShadow receiveShadow />
      <mesh geometry={geometry.lower} material={materials.cavity} position={[0, 0, 0.005]} scale={[0.91, 0.91, 0.9]} />
      <mesh position={[0, -0.45, 0.115]}>
        <circleGeometry args={[0.47, 48]} />
        <meshStandardMaterial color="#e8b510" roughness={0.62} metalness={0.01} />
      </mesh>
      <mesh position={[0, 0.86, 0.11]}>
        <cylinderGeometry args={[0.29, 0.3, 0.12, 48]} />
        <meshStandardMaterial color="#d9a50a" roughness={0.58} metalness={0.025} />
      </mesh>
      {[-0.58, 0.58].map((x) => <mesh key={x} position={[x, -0.54, 0.115]} rotation={[0, 0, x < 0 ? -0.17 : 0.17]}>
        <boxGeometry args={[0.08, 0.6, 0.07]} />
        <meshStandardMaterial color="#d6a20b" roughness={0.66} metalness={0.01} />
      </mesh>)}
    </InteractivePart>
    <OrbitControls
      ref={controls}
      makeDefault
      target={[0, -0.9, 0]}
      enablePan
      enableZoom
      enableDamping
      dampingFactor={reducedMotion ? 0 : 0.075}
      minPolarAngle={0.52}
      maxPolarAngle={2.2}
      rotateSpeed={0.46}
      panSpeed={0.48}
      zoomSpeed={0.65}
      minDistance={5.2}
      maxDistance={30}
    />
  </>;
}

export function HardwareAssembly() {
  const [mode, setMode] = useState<AssemblyMode>('exploded');
  const [selectedPart, setSelectedPart] = useState<PartName | null>(null);
  const [focusTarget, setFocusTarget] = useState<THREE.Vector3 | null>(null);
  const controls = useRef<OrbitControlsImpl>(null);
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const selectPart = (name: PartName) => setSelectedPart(name);
  const focusPart = (_name: PartName, point: THREE.Vector3) => setFocusTarget(point.clone());
  const clearInteraction = useCallback(() => {
    setSelectedPart(null);
    setFocusTarget(null);
  }, []);
  useEffect(() => {
    const clearSelection = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setSelectedPart(null);
        setFocusTarget(null);
      }
    };
    window.addEventListener('keydown', clearSelection);
    return () => window.removeEventListener('keydown', clearSelection);
  }, []);

  return <>
    <div className="hardware-viewer" aria-label="Interactive exploded Riose ear tag model">
    <Canvas
      className="hardware-canvas"
      frameloop="demand"
      onPointerMissed={clearInteraction}
      camera={{ position: [2.2, 1.1, 12.7], fov: 32, near: 0.1, far: 50 }}
      dpr={[1, 1.5]}
      gl={{ alpha: true, antialias: true, powerPreference: 'low-power' }}
      onCreated={({ gl, scene, camera }) => {
        scene.background = null;
        camera.lookAt(0, -0.9, 0);
        camera.updateProjectionMatrix();
        gl.setClearColor(0x000000, 0);
        gl.outputColorSpace = THREE.SRGBColorSpace;
        gl.toneMapping = THREE.NeutralToneMapping;
        gl.toneMappingExposure = 1.06;
      }}
      fallback={<div className="hardware-webgl-fallback">Interactive product view requires WebGL.</div>}
    >
      <AssemblyModel
        mode={mode}
        selectedPart={selectedPart}
        onSelect={selectPart}
        onFocus={focusPart}
        onFocusComplete={() => setFocusTarget(null)}
        onReset={clearInteraction}
        focusTarget={focusTarget}
        controls={controls}
        reducedMotion={reducedMotion}
      />
    </Canvas>
    </div>
    <div className="hardware-state-switch" role="group" aria-label="Assembly state">
      <button type="button" aria-pressed={mode === 'exploded'} onClick={() => { setMode('exploded'); setFocusTarget(null); }}>Exploded</button>
      <button type="button" aria-pressed={mode === 'assembled'} onClick={() => { setMode('assembled'); setFocusTarget(null); }}>Assembled</button>
    </div>
  </>;
}
