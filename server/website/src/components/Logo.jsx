import { useId } from "react";

// AURUM mark — chevron "A" with HL2 amber gradient.
// Industrial Source Engine feel: sharp angles, warm metal, subtle
// depth. Designed to sit against charcoal backgrounds.
export function Logo({ size = 28 }) {
  const uid = useId();
  const fill = `logo-fill-${uid}`;
  const edge = `logo-edge-${uid}`;
  const glow = `logo-glow-${uid}`;
  return (
    <svg width={size} height={size} viewBox="0 0 160 160" fill="none" style={{ display: "block" }}>
      <defs>
        <linearGradient id={fill} x1="0.2" y1="0" x2="0.8" y2="1">
          <stop offset="0%" stopColor="#F0A847" />
          <stop offset="55%" stopColor="#D08F36" />
          <stop offset="100%" stopColor="#8F7A45" />
        </linearGradient>
        <linearGradient id={edge} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#F0A847" />
          <stop offset="100%" stopColor="#8F7A45" />
        </linearGradient>
        <filter id={glow} x="-30%" y="-30%" width="160%" height="160%">
          <feGaussianBlur stdDeviation="3" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      <path
        d="M80 18 L138 138 L116 138 L104 110 L56 110 L44 138 L22 138 Z M66 92 L94 92 L80 58 Z"
        fill={`url(#${fill})`}
        stroke={`url(#${edge})`}
        strokeWidth="1.4"
        strokeLinejoin="miter"
        filter={`url(#${glow})`}
      />
      <path
        d="M80 18 L138 138 L116 138 L104 110 L56 110 L44 138 L22 138 Z"
        fill="none"
        stroke="rgba(255,220,140,0.35)"
        strokeWidth="0.6"
      />
    </svg>
  );
}
