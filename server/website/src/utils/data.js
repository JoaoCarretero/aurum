export function genEquity() {
  const eq = [{ d: 0, v: 5000, dd: 0 }];
  let b = 5000, p = 5000;
  for (let d = 1; d <= 45; d++) {
    b += (Math.random() < 0.63 ? 1 : -1) * (Math.random() * 35 + 5) * (Math.random() * 2.5 + 1);
    p = Math.max(p, b);
    eq.push({ d, v: Math.round(b * 100) / 100, dd: Math.round((p - b) / p * 10000) / 100 });
  }
  return eq;
}

export function genTrades() {
  const syms = ["BTC", "ETH", "SOL", "NATGAS", "RED", "CL", "BEAT", "RIVER"];
  const strats = ["SM-1", "SV-5D", "FRC-13"];
  return Array.from({ length: 40 }, (_, i) => {
    const win = Math.random() < 0.63;
    return {
      id: i,
      sym: syms[i % syms.length],
      s: strats[i % 3],
      pnl: Math.round((win ? Math.random() * 40 + 5 : -(Math.random() * 25 + 3)) * 100) / 100,
      date: (() => { const d = new Date("2026-03-28"); d.setDate(d.getDate() - i); return d.toISOString().slice(0, 10); })(),
      hours: Math.round(Math.random() * 40 + 1),
    };
  });
}

export const STRATEGIES = [
  { id: "SM-1", name: "Systematic Momentum", color: "#7577D1" },
  { id: "SV-5D", name: "State Vector Model", color: "#C9A048" },
  { id: "FRC-13", name: "Funding Rate Capture", color: "#5AAF7A" },
];

export const ALLOCATIONS = [
  { id: "SM-1", name: "Systematic Momentum", color: "#7577D1", pct: 30 },
  { id: "SV-5D", name: "State Vector Model", color: "#C9A048", pct: 25 },
  { id: "FRC-13", name: "Funding Rate Capture", color: "#5AAF7A", pct: 45 },
];
