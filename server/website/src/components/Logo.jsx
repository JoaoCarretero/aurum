import { C } from '../theme';

export default function IngotLogo({ size = 24 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 160 160" fill="none" style={{ display: "block" }}>
      <defs>
        <linearGradient id="iga" x1="0" y1="0" x2=".7" y2="1">
          <stop offset="0%" stopColor="#E8CC5A" />
          <stop offset="100%" stopColor="#8A6E1F" />
        </linearGradient>
        <linearGradient id="igb" x1="1" y1="0" x2=".2" y2="1">
          <stop offset="0%" stopColor="#BF9B30" stopOpacity=".85" />
          <stop offset="100%" stopColor="#5C4A15" stopOpacity=".6" />
        </linearGradient>
      </defs>
      <path d="M80 14 L42 142 L62 142 L72 104 L88 104 L98 142 L118 142 Z" fill="url(#iga)" />
      <path d="M80 14 L118 142 L98 142 L88 104 L80 58 Z" fill="url(#igb)" />
      <path d="M80 58 L68 104 L92 104 Z" fill={C.bg} />
    </svg>
  );
}
