// AURUM design tokens — Half-Life 2 / Source Engine VGUI palette.
// Imported 1:1 from core/ui/ui_palette.py (SSOT). Same aesthetic
// the launcher terminal uses: charcoal + HL2 orange + warm cream.

export const tokens = {
  // charcoal backgrounds
  bg: "#1B1B1B",       // slightly darker than panel, body
  bg2: "#242424",      // tab inactive
  bg3: "#2A2A2A",      // HL2 charcoal (panel)
  bg4: "#333333",      // hover surface
  bg5: "#4C4C4C",      // button

  // borders
  brd: "rgba(214,201,154,0.08)",       // cream at 8%
  brdStrong: "rgba(214,201,154,0.18)",
  brdAmber: "rgba(208,143,54,0.32)",
  brdAmberStrong: "rgba(208,143,54,0.55)",

  // text — warm cream
  t: "#D6C99A",        // primary — cream Source Engine
  t2: "#B0A17F",       // secondary cream-dim
  t3: "#8F8F8F",       // metadado
  t4: "#565656",       // quiet

  // amber — HL2 orange (primary accent)
  amber: "#D08F36",
  amberBright: "#F0A847",
  amberDim: "#8F7A45",
  amberBg: "rgba(208,143,54,0.08)",
  amberBgStrong: "rgba(208,143,54,0.18)",
  amberGlow: "rgba(208,143,54,0.42)",

  // status — HL2 HUD
  good: "#7FA84A",      // HP green
  goodBg: "rgba(127,168,74,0.12)",
  goodGlow: "rgba(127,168,74,0.38)",
  bad: "#C44535",       // damage red
  badBg: "rgba(196,69,53,0.12)",
  warn: "#E8C87A",      // yellow hazard
  warnBg: "rgba(232,200,122,0.10)",
  cyan: "#7FA0B0",      // steel pipe

  // panels
  glass: "rgba(214,201,154,0.02)",
  glass2: "rgba(214,201,154,0.04)",
  panel: "rgba(42,42,42,0.85)",
};

export const fonts = {
  display: "'Instrument Serif', Georgia, serif",
  body: "'Inter', system-ui, sans-serif",
  mono: "'Geist Mono', 'JetBrains Mono', ui-monospace, monospace",
};

export const ease = {
  out: [0.16, 1, 0.3, 1],
  inOut: [0.65, 0, 0.35, 1],
  smooth: [0.32, 0.72, 0, 1],
};
