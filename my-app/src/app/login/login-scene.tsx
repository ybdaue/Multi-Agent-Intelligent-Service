"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode, RefObject } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Line } from "@react-three/drei";
import * as THREE from "three";
import { useTheme } from "next-themes";
import styles from "./login-scene.module.scss";

const RING_Y = -1.35;

/* ── 调色板 ────────────────────────────────────────────── */

interface Palette {
  bgTop: string;
  bgMid: string;
  bgBottom: string;
  bands: { head: string; tail: string }[];
  halos: { radius: number; color: string; opacity: number }[];
  extraRings: string[];
  nodeLine: string;
  nodeDot: string;
  star: string;
  glowStops: [number, string][];
  dotStops: [number, string][];
  /* 叠加混合只会往背景上“加白”，浅色底上加到头就是纯白，什么都看不见。
     所以浅色主题必须换成普通混合，让带子/光环的固有色真正落在浅底上。 */
  blending: THREE.Blending;
  /* 带子贴图的亮度落在 RGB 还是 alpha 上：加法混合靠 RGB 亮度叠加；
     浅色底的普通混合若还靠 RGB 压暗，蓝会被压成灰黑，必须改落在 alpha。 */
  bandAlpha: boolean;
  /** 是否保留两条很宽很淡的柔光带。浅色底上它们只会糊成灰雾，关掉 */
  wideBands: boolean;
  /** 光晕带外层柔光的强度系数 */
  glowBand: number;
  /** 地面大范围柔光的强度 */
  glowHalo: number;
  /** 闪烁星点色相：浅底上要压暗才看得见 */
  spriteHSL: { base: number; range: number; sat: number; light: number };
}

const DARK: Palette = {
  bgTop: "#05070f",
  bgMid: "#05070f",
  bgBottom: "#05070f",
  bands: [
    { head: "#4f46e5", tail: "#312e81" },
    { head: "#6366f1", tail: "#4c1d95" },
    { head: "#818cf8", tail: "#6d28d9" },
    { head: "#a855f7", tail: "#6366f1" },
    { head: "#e0e7ff", tail: "#38bdf8" },
    { head: "#f5f3ff", tail: "#60a5fa" },
  ],
  halos: [
    { radius: 1.44, color: "#60a5fa", opacity: 0.1 },
    { radius: 1.94, color: "#3b82f6", opacity: 0.14 },
    { radius: 2.44, color: "#6366f1", opacity: 0.18 },
    { radius: 2.93, color: "#6366f1", opacity: 0.12 },
    { radius: 3.28, color: "#a855f7", opacity: 0.16 },
    { radius: 4.38, color: "#7c3aed", opacity: 0.1 },
    { radius: 4.94, color: "#a855f7", opacity: 0.07 },
    { radius: 5.56, color: "#4338ca", opacity: 0.05 },
    { radius: 6.25, color: "#3b82f6", opacity: 0.04 },
  ],
  extraRings: ["#8b5cf6", "#dbeafe", "#93c5fd", "#c4b5fd"],
  nodeLine: "#4f7ff0",
  nodeDot: "#bfdbfe",
  star: "#818cf8",
  glowStops: [
    [0, "rgba(139,140,248,0.62)"],
    [0.3, "rgba(99,102,241,0.24)"],
    [0.62, "rgba(59,130,246,0.06)"],
    [1, "rgba(5,7,15,0)"],
  ],
  dotStops: [
    [0, "rgba(255,255,255,1)"],
    [0.22, "rgba(147,197,253,0.85)"],
    [1, "rgba(59,130,246,0)"],
  ],
  blending: THREE.AdditiveBlending,
  bandAlpha: false,
  wideBands: true,
  glowBand: 0.62,
  glowHalo: 0.7,
  spriteHSL: { base: 0.55, range: 0.08, sat: 0.6, light: 0.7 },
};

const LIGHT: Palette = {
  bgTop: "#eef1f4",
  bgMid: "#e1e5eb",
  bgBottom: "#cdd3db",
  /* 只留四条最细最亮的带子（对应 BAND_POINTS 里非 wide 的四条），
     颜色提饱和、去掉发灰的浅尾。 */
  bands: [
    { head: "#2563eb", tail: "#93c5fd" },
    { head: "#7c3aed", tail: "#c4b5fd" },
    { head: "#0ea5e9", tail: "#7dd3fc" },
    { head: "#3b82f6", tail: "#bfdbfe" },
  ],
  halos: [
    { radius: 1.44, color: "#f7f4ec", opacity: 0.42 },
    { radius: 1.94, color: "#0ea5e9", opacity: 0.4 },
    { radius: 2.44, color: "#38bdf8", opacity: 0.34 },
    { radius: 2.93, color: "#3b82f6", opacity: 0.26 },
    { radius: 3.28, color: "#f7f4ec", opacity: 0.26 },
    { radius: 4.38, color: "#0284c7", opacity: 0.18 },
    { radius: 4.94, color: "#60a5fa", opacity: 0.13 },
  ],
  extraRings: ["#f7f4ec", "#0ea5e9", "#3b82f6", "#38bdf8"],
  nodeLine: "#7c3aed",
  nodeDot: "#a78bfa",
  star: "#8b5cf6",
  glowStops: [
    [0, "rgba(247,244,236,0.46)"],
    [0.3, "rgba(14,165,233,0.2)"],
    [0.62, "rgba(186,230,253,0.07)"],
    [1, "rgba(255,255,255,0)"],
  ],
  dotStops: [
    [0, "rgba(255,255,255,1)"],
    [0.35, "rgba(247,244,236,0.5)"],
    [1, "rgba(247,244,236,0)"],
  ],
  blending: THREE.NormalBlending,
  bandAlpha: true,
  wideBands: false,
  glowBand: 0.38,
  glowHalo: 0.3,
  spriteHSL: { base: 0.72, range: 0.08, sat: 0.65, light: 0.52 },
};

function radialTexture(stops: [number, string][], size: number) {
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  const texture = new THREE.CanvasTexture(canvas);
  if (!ctx) return texture;

  const half = size / 2;
  const gradient = ctx.createRadialGradient(half, half, 0, half, half, half);
  for (const [offset, color] of stops) gradient.addColorStop(offset, color);
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, size, size);

  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

/* 光晕带的横截面：跨宽度高斯柔边 + 沿长度无缝流动的亮度脉动。
   色相只做极轻的偏冷处理，真正的配色交给每个带的顶点色。
   alpha 模式下亮度写进 alpha、RGB 留白，浅色底上色相才不会被压黑。 */
function bandTexture(alphaMode: boolean, width = 512, height = 128) {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  const texture = new THREE.CanvasTexture(canvas);
  if (!ctx) return texture;

  const image = ctx.createImageData(width, height);
  for (let y = 0; y < height; y++) {
    const v = y / (height - 1);
    const edge = Math.exp(-Math.pow((v - 0.5) / 0.26, 2));
    for (let x = 0; x < width; x++) {
      const u = x / width;
      const flow =
        0.55 +
        0.45 *
          (0.55 * Math.sin(2 * Math.PI * u) +
            0.3 * Math.sin(4 * Math.PI * u + 1.7) +
            0.15 * Math.sin(6 * Math.PI * u + 3.1));
      const brightness = edge * Math.max(0, flow);
      const i = (y * width + x) * 4;
      if (alphaMode) {
        image.data[i] = 255;
        image.data[i + 1] = 255;
        image.data[i + 2] = 255;
        image.data[i + 3] = 255 * brightness;
      } else {
        image.data[i] = 255 * brightness * 0.94;
        image.data[i + 1] = 255 * brightness * 0.96;
        image.data[i + 2] = 255 * brightness;
        image.data[i + 3] = 255;
      }
    }
  }
  ctx.putImageData(image, 0, 0);

  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.ClampToEdgeWrapping;
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function useScenePrefs() {
  const [prefs, setPrefs] = useState({ reduced: false, low: false });

  useEffect(() => {
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const small = window.matchMedia("(max-width: 768px)").matches;
    const weak = (navigator.hardwareConcurrency ?? 8) <= 4;
    const sync = () => setPrefs({ reduced: motion.matches, low: small || weak });

    sync();
    motion.addEventListener("change", sync);
    return () => motion.removeEventListener("change", sync);
  }, []);

  return prefs;
}

// ── 光晕带（ribbon + 流动贴图）─────────────────────────────

type BandSpec = {
  points: [number, number, number][];
  halfWidth: number;
  opacity: number;
  head: string;
  tail: string;
  speed: number;
  taper?: [number, number];
  wide?: boolean;
};

const BAND_POINTS: Omit<BandSpec, "head" | "tail">[] = [
  {
    points: [
      [14, 7.6, -7.5],
      [7.5, 4.9, -3.6],
      [0, 1.4, -0.4],
      [-10, -3.4, 2.8],
    ],
    halfWidth: 1.8,
    opacity: 0.14,
    speed: 0.075,
    taper: [2.0, 0.5],
    wide: true,
  },
  {
    points: [
      [13.5, 6.8, -7],
      [6.6, 3.9, -3],
      [-1.2, 0.6, 0.4],
      [-11, -4.2, 3.4],
    ],
    halfWidth: 0.9,
    opacity: 0.22,
    speed: 0.105,
    taper: [2.2, 0.5],
    wide: true,
  },
  {
    points: [
      [13, 7.4, -6.4],
      [7, 5.2, -2.6],
      [0.4, 2.2, 0.6],
      [-9.5, -2.2, 3],
    ],
    halfWidth: 0.45,
    opacity: 0.3,
    speed: 0.14,
    taper: [2.6, 0.4],
  },
  {
    points: [
      [12.6, 6.2, -6.8],
      [6.2, 3.4, -2.2],
      [-1.6, 0.2, 0.8],
      [-10.5, -4.6, 3.6],
    ],
    halfWidth: 0.3,
    opacity: 0.4,
    speed: 0.175,
    taper: [2.8, 0.35],
  },
  {
    points: [
      [12.4, 7, -7.2],
      [6.4, 4.6, -3.2],
      [-0.6, 1.6, 0.2],
      [-9, -2.8, 2.6],
    ],
    halfWidth: 0.16,
    opacity: 0.72,
    speed: 0.215,
    taper: [3.0, 0.3],
  },
  {
    points: [
      [12.8, 5.6, -6.2],
      [6.8, 3.2, -2.4],
      [0.2, 0.4, 0.6],
      [-9.8, -3.8, 3.2],
    ],
    halfWidth: 0.1,
    opacity: 0.82,
    speed: 0.25,
    taper: [3.2, 0.25],
  },
];

function buildRibbonGeometry(spec: BandSpec) {
  const curve = new THREE.CatmullRomCurve3(
    spec.points.map((p) => new THREE.Vector3(...p)),
  );
  const segments = 72;
  const positions: number[] = [];
  const uvs: number[] = [];
  const colors: number[] = [];
  const indices: number[] = [];

  const up = new THREE.Vector3(0, 0, 1);
  const fallbackUp = new THREE.Vector3(0, 1, 0);
  const tangent = new THREE.Vector3();
  const side = new THREE.Vector3();
  const prevSide = new THREE.Vector3(1, 0, 0);
  const point = new THREE.Vector3();
  const headColor = new THREE.Color(spec.head);
  const tailColor = new THREE.Color(spec.tail);
  const color = new THREE.Color();

  for (let i = 0; i <= segments; i++) {
    const f = i / segments;
    curve.getPointAt(f, point);
    curve.getTangentAt(f, tangent);

    side.crossVectors(tangent, up);
    if (side.lengthSq() < 1e-6) side.crossVectors(tangent, fallbackUp);
    if (side.lengthSq() < 1e-6) side.copy(prevSide);
    if (i > 0 && side.dot(prevSide) < 0) side.negate();
    side.normalize();
    prevSide.copy(side);

    const [taperS, taperE] = spec.taper ?? [1, 1];
    const half = spec.halfWidth * (taperS + f * (taperE - taperS));
    positions.push(
      point.x - side.x * half, point.y - side.y * half, point.z - side.z * half,
      point.x + side.x * half, point.y + side.y * half, point.z + side.z * half,
    );
    uvs.push(f, 0, f, 1);

    /* 头尾渐隐落在 alpha 上，RGB 保持固有色。这样加法混合的贡献
       仍是 色×fade（和压暗 RGB 等价），普通混合则只是逐渐透明。 */
    color.copy(headColor).lerp(tailColor, f);
    const fade = Math.pow(1 - f, 1.2);
    colors.push(color.r, color.g, color.b, fade, color.r, color.g, color.b, fade);

    if (i < segments) {
      const a = i * 2;
      indices.push(a, a + 1, a + 2, a + 1, a + 3, a + 2);
    }
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute("uv", new THREE.Float32BufferAttribute(uvs, 2));
  geometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 4));
  geometry.setIndex(indices);
  geometry.computeBoundingSphere();
  return geometry;
}

function LightBands({ low, palette }: { low: boolean; palette: Palette }) {
  const bands = useMemo(() => {
    const showWide = palette.wideBands && !low;
    const specs = BAND_POINTS.filter((s) => showWide || !s.wide);
    return specs.map((pt, i) => {
      const full: BandSpec = { ...pt, head: palette.bands[i].head, tail: palette.bands[i].tail };
      return {
        spec: full,
        geometry: buildRibbonGeometry(full),
        glowGeometry: buildRibbonGeometry({
          ...full,
          halfWidth: full.halfWidth * (full.wide ? 2.4 : 3.2),
        }),
        texture: bandTexture(palette.bandAlpha),
      };
    });
  }, [low, palette]);

  useEffect(
    () => () =>
      bands.forEach((band) => {
        band.geometry.dispose();
        band.glowGeometry.dispose();
        band.texture.dispose();
      }),
    [bands],
  );

  const flow = useRef<{ texture: THREE.Texture; speed: number }[]>([]);
  useEffect(() => {
    flow.current = bands.map((band) => ({
      texture: band.texture,
      speed: band.spec.speed,
    }));
  }, [bands]);

  useFrame((_, delta) => {
    for (const item of flow.current) {
      const offset = item.texture.offset;
      offset.x -= item.speed * delta;
      if (offset.x < -1) offset.x += 1;
    }
  });

  return (
    <group>
      {bands.map((band, i) => (
        <group key={i}>
          <mesh geometry={band.glowGeometry}>
            <meshBasicMaterial
              map={band.texture}
              vertexColors
              transparent
              opacity={band.spec.opacity * palette.glowBand}
              side={THREE.DoubleSide}
              blending={palette.blending}
              depthWrite={false}
              toneMapped={false}
            />
          </mesh>
          <mesh geometry={band.geometry}>
            <meshBasicMaterial
              map={band.texture}
              vertexColors
              transparent
              opacity={band.spec.opacity}
              side={THREE.DoubleSide}
              blending={palette.blending}
              depthWrite={false}
              toneMapped={false}
            />
          </mesh>
        </group>
      ))}
    </group>
  );
}

// ── 地面雷达环 ─────────────────────────────────────────────

function GroundAnchor({
  anchorRef,
  children,
}: {
  anchorRef: RefObject<HTMLDivElement | null>;
  children: ReactNode;
}) {
  const camera = useThree((state) => state.camera);
  const gl = useThree((state) => state.gl);
  const group = useRef<THREE.Group>(null);
  const current = useRef(new THREE.Vector3());
  const desired = useRef<THREE.Vector3 | null>(null);
  const canvasRect = useRef<DOMRect | null>(null);
  const tick = useRef(0);
  const ready = useRef(false);

  const plane = useMemo(
    () => new THREE.Plane(new THREE.Vector3(0, 1, 0), -RING_Y),
    [],
  );
  const ray = useMemo(() => new THREE.Raycaster(), []);
  const ndc = useMemo(() => new THREE.Vector2(), []);
  const hitPoint = useMemo(() => new THREE.Vector3(), []);

  useEffect(() => {
    const measure = () => {
      canvasRect.current = gl.domElement.getBoundingClientRect();
    };
    measure();

    const observer = new ResizeObserver(measure);
    observer.observe(gl.domElement);
    if (anchorRef.current) observer.observe(anchorRef.current);
    window.addEventListener("resize", measure);

    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [anchorRef, gl]);

  useFrame((_, delta) => {
    const node = group.current;
    const target = anchorRef.current;
    const rect = canvasRect.current;
    if (!node || !target || !rect) return;

    if (tick.current++ % 8 === 0) {
      const box = target.getBoundingClientRect();
      const nx = (box.left + box.width / 2 - rect.left) / rect.width;
      const ny = (box.bottom - rect.top) / rect.height;
      ndc.set(nx * 2 - 1, -(ny * 2 - 1));
      ray.setFromCamera(ndc, camera);

      const hit = ray.ray.intersectPlane(plane, hitPoint);
      if (hit) {
        hit.x = THREE.MathUtils.clamp(hit.x, -7, 7);
        hit.z = THREE.MathUtils.clamp(hit.z, -9, 5);
        desired.current = hit.clone();
      }
    }

    if (!desired.current) return;
    if (current.current.lengthSq() === 0) current.current.copy(desired.current);
    current.current.lerp(desired.current, 1 - Math.exp(-delta * 4));
    node.position.copy(current.current);

    if (!ready.current) {
      ready.current = true;
      node.visible = true;
    }
  });

  return <group ref={group} visible={false}>{children}</group>;
}

function GlowCircle({
  radius,
  color,
  opacity,
  blending,
  segments = 180,
}: {
  radius: number;
  color: string;
  opacity: number;
  blending: THREE.Blending;
  segments?: number;
}) {
  const coreThickness = 0.04;
  const glowWidth = Math.max(radius * 0.18, 0.35);
  const midGlowWidth = Math.max(radius * 0.45, 0.7);

  return (
    <group>
      {/* 最外层大范围柔光 */}
      <mesh rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[radius - midGlowWidth, radius + midGlowWidth, segments]} />
        <meshBasicMaterial
          color={color}
          transparent
          opacity={opacity * 0.12}
          side={THREE.DoubleSide}
          blending={blending}
          depthWrite={false}
          toneMapped={false}
        />
      </mesh>
      {/* 中层光晕 */}
      <mesh rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[radius - glowWidth, radius + glowWidth, segments]} />
        <meshBasicMaterial
          color={color}
          transparent
          opacity={opacity * 0.45}
          side={THREE.DoubleSide}
          blending={blending}
          depthWrite={false}
          toneMapped={false}
        />
      </mesh>
      {/* 内核亮线 */}
      <mesh rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[radius - coreThickness, radius + coreThickness, segments]} />
        <meshBasicMaterial
          color={color}
          transparent
          opacity={opacity}
          side={THREE.DoubleSide}
          blending={blending}
          depthWrite={false}
          toneMapped={false}
        />
      </mesh>
    </group>
  );
}

function HaloRing({ glow, low, palette }: { glow: THREE.Texture; low: boolean; palette: Palette }) {
  const group = useRef<THREE.Group>(null);

  useFrame(({ clock }) => {
    if (group.current) {
      group.current.scale.setScalar(0.92 + Math.sin(clock.elapsedTime * 0.8) * 0.08);
    }
  });

  const circles = low ? palette.halos.slice(0, 5) : palette.halos;
  const [r1, r2, r3, r4] = palette.extraRings;

  return (
    <group>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.02, 0]}>
        <planeGeometry args={[18, 18]} />
        <meshBasicMaterial
          map={glow}
          transparent
          opacity={low ? palette.glowHalo * 0.72 : palette.glowHalo}
          blending={palette.blending}
          depthWrite={false}
          toneMapped={false}
        />
      </mesh>
      <mesh position={[0, 0.35, 0]}>
        <planeGeometry args={[10.8, 4.1]} />
        <meshBasicMaterial
          map={glow}
          transparent
          opacity={palette.glowHalo * 0.45}
          blending={palette.blending}
          depthWrite={false}
          toneMapped={false}
        />
      </mesh>

      <group ref={group} position={[0, 0, 0]}>
        {circles.map((circle) => (
            <GlowCircle key={circle.radius} {...circle} blending={palette.blending} />
        ))}

        <mesh rotation={[-Math.PI / 2, 0, 0]}>
          <ringGeometry args={[3.68, 3.75, 200]} />
          <meshBasicMaterial
            color={r1}
            transparent
            opacity={0.85}
            side={THREE.DoubleSide}
            blending={palette.blending}
            depthWrite={false}
            toneMapped={false}
          />
        </mesh>
        <mesh rotation={[-Math.PI / 2, 0, 0]}>
          <ringGeometry args={[3.58, 3.85, 128, 1, -Math.PI * 0.75, Math.PI * 0.5]} />
          <meshBasicMaterial
            color={r2}
            transparent
            opacity={0.9}
            side={THREE.DoubleSide}
            blending={palette.blending}
            depthWrite={false}
            toneMapped={false}
          />
        </mesh>

        <mesh rotation={[-Math.PI / 2, 0, 0]}>
          <ringGeometry args={[2.95, 2.98, 160]} />
          <meshBasicMaterial
            color={r3}
            transparent
            opacity={0.22}
            side={THREE.DoubleSide}
            blending={palette.blending}
            depthWrite={false}
            toneMapped={false}
          />
        </mesh>
        <mesh rotation={[-Math.PI / 2, 0, 0]}>
          <ringGeometry args={[4.1, 4.13, 160]} />
          <meshBasicMaterial
            color={r4}
            transparent
            opacity={0.16}
            side={THREE.DoubleSide}
            blending={palette.blending}
            depthWrite={false}
            toneMapped={false}
          />
        </mesh>
      </group>
    </group>
  );
}

// ── 增强星座节点网络 ──────────────────────────────────────

const NODE_PATHS: [number, number, number][][] = [
  [
    [-8.5, -0.7, 2.6],
    [-4, 0.5, 1.1],
    [0.5, -0.9, 2.1],
    [4.6, -0.1, 1],
    [8.5, -1.1, 2.6],
  ],
  [
    [-7.5, 0.7, 1.1],
    [-3, -0.4, 2.4],
    [1.5, 0.6, 1.5],
    [6.2, 0.1, 2.8],
  ],
  [
    [-9, -1.1, 3.8],
    [-4.5, -0.8, 2.9],
    [0, 0.3, 3.4],
    [4.5, -0.7, 3.8],
    [9, 0.2, 3.1],
  ],
  [
    [-9.5, 0.3, 4.2],
    [-5.2, -0.5, 3.8],
    [0.8, 0.4, 4.6],
    [5.6, -0.3, 4],
    [10, 0.6, 4.5],
  ],
  [
    [-8.2, 0.8, 1.8],
    [-3.8, -0.2, 3],
    [1.2, 0.5, 2.4],
    [5.8, -0.4, 3.2],
    [9.2, 0.3, 2.2],
  ],
];

function mulberry32(seed: number) {
  let s = seed | 0;
  return () => {
    s = (s + 0x6d2b79f5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function NodeGraph({ dot, low, palette }: { dot: THREE.Texture; low: boolean; palette: Palette }) {
  const group = useRef<THREE.Group>(null);
  const pivotRef = useRef<THREE.Group>(null);
  const lineMaterial = useRef<THREE.LineBasicMaterial>(null);
  const dotMaterial = useRef<THREE.PointsMaterial>(null);
  const glowGroup = useRef<THREE.Group>(null);

  type BrightStar = {
    pos: [number, number, number];
    phase: number;
    speed: number;
    baseScale: number;
    hue: number;
  };
  const starSprites = useRef<(THREE.Sprite | null)[]>([]);

  const { curves, positions, stars } = useMemo(() => {
    const perPath = low ? 14 : 26;
    const built: THREE.Vector3[][] = [];
    const flat: number[] = [];
    const stars: BrightStar[] = [];
    const rng = mulberry32(42);

    for (const path of NODE_PATHS) {
      const curve = new THREE.CatmullRomCurve3(
        path.map((p) => new THREE.Vector3(...p)),
      );
      const points = curve.getPoints(perPath);
      built.push(points);

      for (const pt of points) {
        flat.push(pt.x, pt.y, pt.z);

        if (rng() < 0.15) {
          stars.push({
            pos: [pt.x, pt.y, pt.z],
            phase: rng() * Math.PI * 2,
            speed: 0.7 + rng() * 1.3,
            baseScale: 0.18 + rng() * 0.28,
            hue: rng(),
          });
        }
      }
    }

    return {
      curves: built,
      positions: new Float32Array(flat),
      stars,
    };
  }, [low]);

  useFrame(({ clock }) => {
    const t = clock.elapsedTime;

    if (pivotRef.current) pivotRef.current.rotation.y = t * 0.018;

    if (lineMaterial.current) {
      lineMaterial.current.opacity = 0.18 + Math.sin(t * 0.9) * 0.08;
    }

    if (dotMaterial.current) {
      dotMaterial.current.opacity = 0.7 + Math.sin(t * 1.6) * 0.2;
    }

    for (let i = 0; i < starSprites.current.length; i++) {
      const sprite = starSprites.current[i];
      const star = stars[i];
      if (!sprite || !star) continue;
      const s = star.baseScale * (0.55 + 0.45 * Math.sin(t * star.speed + star.phase));
      sprite.scale.set(s, s, 1);
    }
  });

  return (
    <group ref={pivotRef} position={[-4, 0, 0]}>
      <group ref={group}>
      {curves.map((points, i) => (
        <Line
          key={`line-${i}`}
          points={points}
          color={palette.nodeLine}
          transparent
          opacity={0.22}
          lineWidth={1}
          depthWrite={false}
          blending={palette.blending}
          toneMapped={false}
        />
      ))}

      <points>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" args={[positions, 3]} />
        </bufferGeometry>
        <pointsMaterial
          ref={dotMaterial}
          map={dot}
          size={0.14}
          sizeAttenuation
          color={palette.nodeDot}
          transparent
          opacity={0.75}
          blending={palette.blending}
          depthWrite={false}
          toneMapped={false}
        />
      </points>

      <group ref={glowGroup}>
        {stars.map((star, i) => (
          <sprite
            key={i}
            ref={(el) => { starSprites.current[i] = el; }}
            position={star.pos}
            scale={[star.baseScale, star.baseScale, 1]}
          >
            <spriteMaterial
              map={dot}
              color={new THREE.Color().setHSL(
                palette.spriteHSL.base + star.hue * palette.spriteHSL.range,
                palette.spriteHSL.sat,
                palette.spriteHSL.light,
              )}
              transparent
              opacity={0.95}
              blending={palette.blending}
              depthWrite={false}
              toneMapped={false}
            />
          </sprite>
        ))}
      </group>
    </group>
    </group>
  );
}

// ── 背景深空星场 ──────────────────────────────────────────

function StarField({
  low,
  palette,
  dot,
}: {
  low: boolean;
  palette: Palette;
  dot: THREE.Texture;
}) {
  const count = low ? 220 : 700;

  const { positions, colors, drift, phases, speeds } = useMemo(() => {
    const pos = new Float32Array(count * 3);
    const col = new Float32Array(count * 4);
    const drift = new Float32Array(count);
    const phases = new Float32Array(count);
    const speeds = new Float32Array(count);
    for (let i = 0; i < count; i++) {
      pos[i * 3] = (Math.random() - 0.5) * 50;
      /* pow<1 把分布推向上方，顶部星更密 */
      pos[i * 3 + 1] = -8 + Math.pow(Math.random(), 0.62) * 14;
      pos[i * 3 + 2] = (Math.random() - 0.5) * 25 - 8;
      col[i * 4] = 1;
      col[i * 4 + 1] = 1;
      col[i * 4 + 2] = 1;
      col[i * 4 + 3] = 0.5;
      drift[i] = 0.08 + Math.random() * 0.32;
      phases[i] = Math.random() * Math.PI * 2;
      speeds[i] = 0.4 + Math.random() * 1.4;
    }
    return { positions: pos, colors: col, drift, phases, speeds };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [low]);

  const posRef = useRef<THREE.BufferAttribute>(null);
  const colRef = useRef<THREE.BufferAttribute>(null);

  useFrame(({ clock }, delta) => {
    const t = clock.elapsedTime;

    const posAttr = posRef.current;
    if (posAttr) {
      const arr = posAttr.array as Float32Array;
      for (let i = 0; i < count; i++) {
        let x = arr[i * 3] + drift[i] * delta;
        if (x > 25) x -= 50;
        arr[i * 3] = x;
      }
      posAttr.needsUpdate = true;
    }

    const colAttr = colRef.current;
    if (colAttr) {
      const arr = colAttr.array as Float32Array;
      for (let i = 0; i < count; i++) {
        const twinkle = 0.5 + 0.5 * Math.sin(t * speeds[i] + phases[i]);
        arr[i * 4 + 3] = 0.22 + 0.68 * twinkle;
      }
      colAttr.needsUpdate = true;
    }
  });

  return (
    <points>
      <bufferGeometry>
        <bufferAttribute ref={posRef} attach="attributes-position" args={[positions, 3]} />
        <bufferAttribute ref={colRef} attach="attributes-color" args={[colors, 4]} />
      </bufferGeometry>
      <pointsMaterial
        map={dot}
        size={0.06}
        color={palette.star}
        vertexColors
        transparent
        blending={palette.blending}
        depthWrite={false}
        toneMapped={false}
      />
    </points>
  );
}

// ── 帧率限制（减轻 GPU 负载，消除输入延迟） ──────────────

function FpsLimiter({ fps = 30 }) {
  const { invalidate } = useThree();

  useEffect(() => {
    let rafId: number;
    let last = 0;
    const interval = 1000 / fps;

    const tick = (now: number) => {
      if (now - last >= interval) {
        last = now - ((now - last) % interval);
        invalidate();
      }
      rafId = requestAnimationFrame(tick);
    };
    rafId = requestAnimationFrame(tick);

    return () => cancelAnimationFrame(rafId);
  }, [fps, invalidate]);

  return null;
}

// ── 场景 ────────────────────────────────────────────────────

function Scene({
  low,
  reduced,
  anchorRef,
  palette,
}: {
  low: boolean;
  reduced: boolean;
  anchorRef: RefObject<HTMLDivElement | null>;
  palette: Palette;
}) {
  const textures = useMemo(
    () => ({
      glow: radialTexture(palette.glowStops, 256),
      dot: radialTexture(palette.dotStops, 64),
    }),
    [palette],
  );

  const bgTexture = useMemo(() => {
    const canvas = document.createElement("canvas");
    canvas.width = 2;
    canvas.height = 256;
    const ctx = canvas.getContext("2d");
    if (!ctx) return new THREE.CanvasTexture(canvas);

    const gradient = ctx.createLinearGradient(0, 0, 0, 256);
    gradient.addColorStop(0, palette.bgTop);
    gradient.addColorStop(0.5, palette.bgMid);
    gradient.addColorStop(1, palette.bgBottom);
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, 2, 256);

    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    return texture;
  }, [palette]);

  useEffect(
    () => () => {
      textures.glow.dispose();
      textures.dot.dispose();
      bgTexture.dispose();
    },
    [textures, bgTexture],
  );

  return (
    <>
      <primitive attach="background" object={bgTexture} />
      {!reduced && <FpsLimiter fps={30} />}
      <LightBands low={low} palette={palette} />
      <StarField low={low} palette={palette} dot={textures.dot} />
      <GroundAnchor anchorRef={anchorRef}>
        <HaloRing glow={textures.glow} low={low || reduced} palette={palette} />
      </GroundAnchor>
      <NodeGraph dot={textures.dot} low={low} palette={palette} />
    </>
  );
}

export default function LoginScene({
  anchorRef,
}: {
  anchorRef: RefObject<HTMLDivElement | null>;
}) {
  const { reduced, low } = useScenePrefs();
  const { theme } = useTheme();
  const palette = theme === "dark" ? DARK : LIGHT;

  return (
    <div className={styles.scene} aria-hidden="true">
      <Canvas
        dpr={[1, 1.2]}
        frameloop={reduced ? "demand" : "demand"}
        gl={{ antialias: false, alpha: false }}
        camera={{ fov: 45, position: [0, 2.2, 8.6], near: 0.1, far: 60 }}
      >
        <Scene low={low} reduced={reduced} anchorRef={anchorRef} palette={palette} />
      </Canvas>
    </div>
  );
}