// Static data — performance metrics, engine registry, principles.
// All numbers grounded in docs/audits/2026-04-16_oos_verdict.md.
// The site reports honest OOS figures, including inflation admissions.

export const SITE = {
  name: "AURUM",
  tagline: "The tape reads itself.",
  description:
    "AURUM is a systematic quant platform for crypto perpetual futures — nine engines, one orchestrator, three layers of risk.",
  email: "admin@aurum.finance",
  version: "v4.0",
  year: new Date().getFullYear(),
};

// Engine registry with honest OOS status classification.
export const ENGINES = [
  {
    name: "CITADEL",
    tag: "Systematic momentum",
    interval: "15m",
    inspiration: "Citadel LLC",
    concept: "Ω fractal 5D, multi-timeframe regime gating, Kelly sizing with aggregate notional cap.",
    status: "active",
    verdict: "EDGE REAL",
    metrics: {
      sharpe_oos: 5.677,
      sharpe_oos_alt: 2.921,
      sharpe_baseline: 3.007,
      sortino_oos: 8.606,
      trades_oos: 240,
      winrate_oos: 0.608,
      maxdd_oos: 0.032,
    },
  },
  {
    name: "JUMP",
    tag: "Order flow / microstructure",
    interval: "1h",
    inspiration: "Jump Trading",
    concept: "CVD divergence, imbalance detection, liquidation absorption — OOS outperformed in-sample.",
    status: "active",
    verdict: "ROBUSTO",
    metrics: {
      sharpe_oos: 3.15,
      sharpe_insample: 2.06,
      sortino_oos: 6.156,
      sortino_insample: 7.84,
      trades_oos: 110,
      winrate_oos: 0.636,
      maxdd_oos: 0.0165,
    },
  },
  {
    name: "RENAISSANCE",
    tag: "Harmonic Bayesian",
    interval: "15m",
    inspiration: "Renaissance Technologies",
    concept: "Gartley/Butterfly patterns with entropy filter and Hurst validation.",
    status: "active-moderate",
    verdict: "EDGE MODERADO",
    metrics: {
      sharpe_oos: 2.421,
      sharpe_claimed: 5.65,
      sortino_oos: 2.352,
      winrate_oos: 0.7566,
      maxdd_oos: 0.0172,
      inflation_note: "In-sample claim was inflated ~57%. Real Sharpe ~2.4, not 5.65.",
    },
  },
  {
    name: "JANE STREET",
    tag: "Cross-venue arbitrage",
    interval: "1m",
    inspiration: "Jane Street",
    concept: "Delta-neutral futures-spot basis capture across venues.",
    status: "active-arb",
    verdict: "ARB",
  },
  {
    name: "MILLENNIUM",
    tag: "Multi-strategy orchestrator",
    interval: "meta",
    inspiration: "Millennium Management",
    concept: "Pod orchestration — allocates capital across CITADEL, JUMP, RENAISSANCE with correlation and drawdown gates.",
    status: "orchestrator",
    verdict: "META",
  },
];

// Engines that failed OOS and were archived. The graveyard is methodology.
export const ARCHIVED = [
  { name: "DE SHAW", reason: "Engle-Granger cointegration — no edge OOS." },
  { name: "BRIDGEWATER", reason: "Macro contrarian — suspected implementation bug in signal construction." },
  { name: "KEPOS", reason: "Hawkes intensity — insufficient sample in candle data (η never reaches 0.95)." },
  { name: "MEDALLION", reason: "Berlekamp-Laufer 7-signal attempt — no edge surfaced." },
  { name: "GRAHAM", reason: "4h value — honest overfit. Archived." },
];

// Anti-overfit protocol — five principles.
export const ANTI_OVERFIT = [
  {
    num: "01",
    title: "Mechanism before iteration",
    body: "A one-paragraph hypothesis written before code. No defensible mechanism, no engine.",
  },
  {
    num: "02",
    title: "Split before code",
    body: "Train / test / holdout dates hardcoded at the top of each engine. They do not move.",
  },
  {
    num: "03",
    title: "Closed grid",
    body: "N pre-registered configurations committed before any sweep runs. No on-the-fly additions.",
  },
  {
    num: "04",
    title: "DSR mandatory",
    body: "Sharpe reported without a Deflated Sharpe Ratio haircut for n_trials is disguised fiction.",
  },
  {
    num: "05",
    title: "Honor the stop rule",
    body: "Failed a gate? Archive. No universe reshuffle, no one-more-iter. Three archives in a row = review the method, not the engine.",
  },
];

// The seven mandamentos, translated for the investor-facing surface.
export const PRINCIPLES = [
  {
    num: "I",
    title: "The disk tests itself",
    body: "Walk-forward, Monte Carlo, ablation. If it does not survive the Solve, it does not exist.",
  },
  {
    num: "II",
    title: "Noise is the adversary",
    body: "Overfitting is misinformation. Regularization, out-of-sample, Monte Carlo — discrimination is constant.",
  },
  {
    num: "III",
    title: "The kill-switch is sacred",
    body: "Three layers of protection. Drawdown velocity, exposure limits, anomaly detection. Hubris kills capital.",
  },
  {
    num: "IV",
    title: "Information over matter",
    body: "Focus on process, never on an isolated outcome. Expected value is computable; results are sampled from it.",
  },
  {
    num: "V",
    title: "The laser is sovereign",
    body: "No external dependency for critical decisions. Data, signal, sizing, risk — all read by our own code.",
  },
  {
    num: "VI",
    title: "The spiral is continuous",
    body: "Walk-forward never stops. The tape rewrites itself; the engines walk forward with it.",
  },
  {
    num: "VII",
    title: "Code is alchemy",
    body: "Clean, documented, modular. Each function does one thing. Legibility is risk management.",
  },
];

// Research notes — placeholder index of what we publish internally.
export const RESEARCH = [
  {
    date: "2026-04-16",
    title: "Out-of-sample verdict across nine engines",
    kind: "Audit",
    abstract:
      "Three-regime OOS test (360d BEAR, 360d BULL, 360d MIXED baseline) for CITADEL, JUMP, RENAISSANCE, DE SHAW, BRIDGEWATER. Separates edge from calibration artifact.",
  },
  {
    date: "2026-04-16",
    title: "Anti-overfit protocol — five discriminators",
    kind: "Methodology",
    abstract:
      "Mechanism, split, grid, DSR, stop rule. Five gates any sweep must pass before the Sharpe number is reported.",
  },
  {
    date: "2026-04-15",
    title: "Hawkes self-excitation on candle data",
    kind: "Framework note",
    abstract:
      "η never reaches 0.95 on OHLCV-derived intensity. EXO-only is the empirical law. Hawkes becomes a diagnostic, not a signal.",
  },
  {
    date: "2026-04-14",
    title: "Kill-switch layers — velocity, exposure, anomaly",
    kind: "Risk",
    abstract:
      "Three independent circuit breakers. Each fails closed. Capital stops before the thesis does.",
  },
];

// Synthetic equity curves — labelled as illustrative walk-forward representations.
// Shapes match the audited verdict (CITADEL: steady compounding; JUMP: low-DD grind).
export function curve(seed, points = 120, drift = 0.0035, vol = 0.018) {
  const out = [];
  let v = 100;
  let rand = mulberry32(seed);
  for (let i = 0; i < points; i++) {
    const shock = (rand() - 0.5) * vol;
    v = v * (1 + drift + shock);
    out.push({ t: i, v: Number(v.toFixed(2)) });
  }
  return out;
}

function mulberry32(a) {
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
