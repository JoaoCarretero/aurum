// Live-style ticker at the top — institutional marquee with data slugs.
// Conveys "the platform is running" without selling uptime as a feature.
// CSS animation (not framer) for the marquee — keyframes-on-transform-x
// in framer-motion 12.38 throws "a is not a function" in the mixer.
const ITEMS = [
  "MILLENNIUM v4.0 · orchestrator live",
  "CITADEL · EDGE_REAL · Sharpe 5.68 OOS",
  "JUMP · ROBUSTO · OOS > in-sample",
  "RENAISSANCE · EDGE_MODERADO · inflation reported",
  "JANE STREET · delta-neutral arb",
  "kill-switch · 3 layers · fail-closed",
  "Ω fractal 5D · walk-forward permanent",
  "DSR · deflated Sharpe · trial-multiplicity adjusted",
];

export function StatusTicker() {
  const loop = [...ITEMS, ...ITEMS];
  return (
    <div className="ticker" role="status" aria-label="live platform status">
      <div className="ticker__label">
        <span className="ticker__dot" />
        LIVE
      </div>
      <div className="ticker__viewport">
        <div className="ticker__track">
          {loop.map((item, i) => (
            <span key={i} className="ticker__item">
              <span className="ticker__bullet">◆</span>
              {item}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
