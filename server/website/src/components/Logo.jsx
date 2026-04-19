import { useId } from "react";

export function Logo({ size = 28 }) {
  const uid = useId();
  const gA = `logo-a-${uid}`;
  const gB = `logo-b-${uid}`;
  return (
    <svg width={size} height={size} viewBox="0 0 160 160" fill="none" style={{ display: "block" }}>
      <defs>
        <linearGradient id={gA} x1="0" y1="0" x2=".7" y2="1">
          <stop offset="0%" stopColor="#F2F2F2" />
          <stop offset="100%" stopColor="#7A7A7A" />
        </linearGradient>
        <linearGradient id={gB} x1="0" y1="1" x2="1" y2="0">
          <stop offset="0%" stopColor="#8A8A8A" />
          <stop offset="100%" stopColor="#D8D8D8" />
        </linearGradient>
      </defs>
      <path
        d="M80 18 L138 138 L118 138 L104 108 L56 108 L42 138 L22 138 Z M65 92 L95 92 L80 58 Z"
        fill={`url(#${gA})`}
        stroke={`url(#${gB})`}
        strokeWidth="1.2"
      />
    </svg>
  );
}
