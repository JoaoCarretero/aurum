import { Reveal } from "../components/Reveal";

const SIGNAL_CODE = `# engines/citadel.py  —  decision node
def decide_direction(bar, htf, regime, vol_regime):
    """Ω 5D fractal — only fires when 4 filters agree."""
    if regime == "CHOP" and vol_regime > 0.85:
        return None
    omega = score_omega(bar, htf)
    chop = score_chop(bar)
    if omega < THRESH_BY_REGIME[regime]:
        return None
    if abs(chop) > CHOP_VETO:
        return None
    return "LONG" if omega > 0 else "SHORT"`;

const RISK_CODE = `# core/risk/gates.py  —  three-layer kill-switch
def check_gates(state: RiskState) -> GateDecision:
    if state.dd_velocity > DD_VEL_LIMIT:
        return halt("drawdown velocity breach")
    if state.aggregate_notional > NOTIONAL_CAP:
        return halt("aggregate notional cap")
    if state.anomaly_score > ANOMALY_LIMIT:
        return halt("tick anomaly detected")
    return GateDecision.OK`;

const SIZING_CODE = `# core/portfolio.py  —  position_size
size = (
    kelly_fraction(edge, variance)
    * convex_scale(equity / peak)
    * drawdown_scale(current_dd)
    * omega_risk(signal_strength)
)
return min(size, aggregate_cap_remaining())`;

export function CodeShowcase() {
  return (
    <section id="code" className="section section--code">
      <div className="section__inner">
        <Reveal>
          <div className="section__head">
            <span className="section__num">§ V</span>
            <h2 className="section__title">
              Readable alchemy — <em>one function, one job.</em>
            </h2>
            <p className="section__sub">
              The platform is written to be audited line-by-line. Signal,
              risk, and sizing each live in a single pure function. No hidden
              state, no global side-effects, no ternary magic.
            </p>
          </div>
        </Reveal>

        <div className="code-grid">
          <Reveal>
            <CodeCard
              id="sig"
              file="engines/citadel.py"
              fn="decide_direction()"
              tag="signal"
              body={SIGNAL_CODE}
            />
          </Reveal>
          <Reveal delay={0.1}>
            <CodeCard
              id="risk"
              file="core/risk/gates.py"
              fn="check_gates()"
              tag="kill-switch"
              body={RISK_CODE}
              good
            />
          </Reveal>
          <Reveal delay={0.2}>
            <CodeCard
              id="size"
              file="core/portfolio.py"
              fn="position_size()"
              tag="sizing"
              body={SIZING_CODE}
            />
          </Reveal>
        </div>
      </div>
    </section>
  );
}

function CodeCard({ id, file, fn, tag, body, good }) {
  return (
    <article className={`code-card ${good ? "code-card--good" : ""}`}>
      <header className="code-card__head">
        <div className="code-card__path">
          <span className="code-card__file">{file}</span>
          <span className="code-card__fn">{fn}</span>
        </div>
        <span className={`chip ${good ? "chip--good" : "chip--gold"}`}>{tag}</span>
      </header>
      <pre className="code-card__body">
        <code>{highlight(body)}</code>
      </pre>
    </article>
  );
}

// Minimal hand-rolled syntax tinting — kept small to avoid heavy deps.
function highlight(src) {
  const lines = src.split("\n");
  return lines.map((line, i) => (
    <span key={i} className="code-card__line">
      {tintLine(line)}
      {"\n"}
    </span>
  ));
}

function tintLine(line) {
  if (/^\s*#/.test(line)) {
    return <span className="tok-comment">{line}</span>;
  }
  const tokens = [];
  const re = /("[^"]*"|'[^']*'|\b(?:def|return|if|else|elif|and|or|not|in|None|True|False|import|from|as)\b|\b[A-Z_]{2,}\b|\b\d+\.?\d*\b|\b[a-zA-Z_][a-zA-Z0-9_]*(?=\()|#.*$)/g;
  let last = 0;
  let m;
  let key = 0;
  while ((m = re.exec(line)) !== null) {
    if (m.index > last) {
      tokens.push(<span key={key++}>{line.slice(last, m.index)}</span>);
    }
    const t = m[0];
    if (/^#/.test(t)) tokens.push(<span key={key++} className="tok-comment">{t}</span>);
    else if (/^["']/.test(t)) tokens.push(<span key={key++} className="tok-string">{t}</span>);
    else if (/^(def|return|if|else|elif|and|or|not|in|None|True|False|import|from|as)$/.test(t))
      tokens.push(<span key={key++} className="tok-keyword">{t}</span>);
    else if (/^[A-Z_]{2,}$/.test(t)) tokens.push(<span key={key++} className="tok-const">{t}</span>);
    else if (/^\d/.test(t)) tokens.push(<span key={key++} className="tok-number">{t}</span>);
    else tokens.push(<span key={key++} className="tok-fn">{t}</span>);
    last = re.lastIndex;
  }
  if (last < line.length) tokens.push(<span key={key++}>{line.slice(last)}</span>);
  return tokens;
}
