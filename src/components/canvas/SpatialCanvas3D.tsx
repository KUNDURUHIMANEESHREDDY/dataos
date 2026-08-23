"use client";

import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { OrbitControls, Text, Line } from "@react-three/drei";
import { useRef, useMemo, useState } from "react";
import * as THREE from "three";
import { useSpatialStore } from "@/hooks/useSpatialStore";

const TYPE_COLORS: Record<string, string> = {
  source: "#0d9488",
  dataset: "#0d9488",
  entity: "#8b5cf6",
  relation: "#f59e0b",
  analysis: "#3b82f6",
  agent: "#ec4899",
};

function computePositions(objects: any[], edges: any[]) {
  const positions: Record<string, [number, number, number]> = {};
  const n = objects.length;
  if (n === 0) return positions;

  // Sphereical distribution
  const radius = Math.max(2, Math.sqrt(n) * 1.2);
  objects.forEach((obj, i) => {
    const phi = Math.acos(1 - (2 * (i + 0.5)) / n);
    const theta = Math.PI * (1 + Math.sqrt(5)) * i;
    positions[obj.id] = [
      radius * Math.sin(phi) * Math.cos(theta),
      radius * Math.sin(phi) * Math.sin(theta),
      radius * Math.cos(phi),
    ];
  });
  return positions;
}

function GraphEdges({ edges, positions }: { edges: any[]; positions: Record<string, [number, number, number]> }) {
  const selectedIds = useSpatialStore((s) => s.selectedIds);
  const lines = useMemo(() => {
    return edges
      .filter((e) => positions[e.source] && positions[e.target])
      .map((e) => ({
        key: e.id,
        points: [positions[e.source], positions[e.target]],
        selected: selectedIds.includes(e.source) || selectedIds.includes(e.target),
      }));
  }, [edges, positions, selectedIds]);

  return (
    <>
      {lines.map((l) => (
        <Line
          key={l.key}
          points={l.points}
          color={l.selected ? "#0d9488" : "#999999"}
          lineWidth={l.selected ? 2 : 0.8}
          transparent
          opacity={l.selected ? 0.8 : 0.25}
          dashed={!l.selected}
          dashSize={0.3}
          gapSize={0.2}
        />
      ))}
    </>
  );
}

function GraphNode({
  obj,
  position,
}: {
  obj: any;
  position: [number, number, number];
}) {
  const meshRef = useRef<THREE.Mesh>(null);
  const selectedIds = useSpatialStore((s) => s.selectedIds);
  const hoveredId = useSpatialStore((s) => s.hoveredId);
  const selectObject = useSpatialStore((s) => s.selectObject);
  const setHovered = useSpatialStore((s) => s.setHovered);
  const [hovered, setHoverLocal] = useState(false);

  const isSelected = selectedIds.includes(obj.id);
  const isHovered = hoveredId === obj.id;
  const color = TYPE_COLORS[obj.type] || "#666666";
  const scale = isSelected ? 1.3 : isHovered ? 1.15 : 1;

  useFrame(() => {
    if (meshRef.current) {
      const s = meshRef.current.scale.x;
      const target = scale;
      meshRef.current.scale.setScalar(s + (target - s) * 0.1);
    }
  });

  return (
    <group position={position}>
      <mesh
        ref={meshRef}
        onClick={(e) => {
          e.stopPropagation();
          selectObject(obj.id, e.nativeEvent.ctrlKey || e.nativeEvent.metaKey);
        }}
        onPointerEnter={(e) => {
          e.stopPropagation();
          setHovered(obj.id);
          setHoverLocal(true);
          document.body.style.cursor = "pointer";
        }}
        onPointerLeave={() => {
          setHovered(null);
          setHoverLocal(false);
          document.body.style.cursor = "default";
        }}
      >
        <sphereGeometry args={[0.35, 32, 32]} />
        <meshStandardMaterial
          color={color}
          emissive={isSelected ? color : "#000000"}
          emissiveIntensity={isSelected ? 0.4 : isHovered ? 0.2 : 0}
          roughness={0.3}
          metalness={0.1}
          transparent
          opacity={0.9}
        />
      </mesh>
      {isSelected && (
        <mesh>
          <ringGeometry args={[0.5, 0.58, 64]} />
          <meshBasicMaterial color={color} transparent opacity={0.3} side={THREE.DoubleSide} />
        </mesh>
      )}
      <Text
        position={[0, 0.55, 0]}
        fontSize={0.18}
        color="#333333"
        anchorX="center"
        anchorY="bottom"
        font="/fonts/PlusJakartaSans-SemiBold.woff"
        maxWidth={2}
      >
        {obj.name.length > 14 ? obj.name.slice(0, 12) + "..." : obj.name}
      </Text>
      <Text
        position={[0, -0.55, 0]}
        fontSize={0.12}
        color="#999999"
        anchorX="center"
        anchorY="top"
      >
        {obj.type}
      </Text>
    </group>
  );
}

function Scene() {
  const objects = useSpatialStore((s) => s.objects);
  const edges = useSpatialStore((s) => s.edges);
  const positions = useMemo(() => computePositions(objects, edges), [objects, edges]);

  return (
    <>
      <ambientLight intensity={0.6} />
      <directionalLight position={[5, 5, 5]} intensity={0.8} />
      <pointLight position={[-5, -5, -5]} intensity={0.3} />
      <OrbitControls
        enableDamping
        dampingFactor={0.05}
        minDistance={2}
        maxDistance={20}
        enablePan
      />
      <GraphEdges edges={edges} positions={positions} />
      {objects.map((obj) => (
        <GraphNode key={obj.id} obj={obj} position={positions[obj.id] || [0, 0, 0]} />
      ))}
      <gridHelper args={[20, 40, "#e0e0e0", "#f0f0f0"]} position={[0, -4, 0]} />
    </>
  );
}

export default function SpatialCanvas3D() {
  return (
    <div className="w-full h-full" style={{ background: "linear-gradient(180deg, #f8f8fc 0%, #eeeeee 100%)" }}>
      <Canvas camera={{ position: [0, 0, 6], fov: 50 }} dpr={[1, 2]}>
        <Scene />
      </Canvas>
    </div>
  );
}
