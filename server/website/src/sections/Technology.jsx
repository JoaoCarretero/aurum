import { Reveal } from "../components/Reveal";
import { ENGINES } from "../lib/data";

const PIPELINE = [
  { step: "Data", detail: "Binance Futures OHLCV + true bull/bear pressure, validated." },
  { step: "Indicators", detail: "EMA, RSI, ATR, Bollinger, swing structure, Ω fractal 5D." },
  { step: "HTF merge", detail: "Multi-timeframe alignment — 15m/1h/4h/1D." },
  { step: "Regime", detail: "BTC slope200 → BULL / BEAR / CHOP macro classification." },
  { step: "Signal", detail: "decide_direction with regime + chop + vol + fractal filters." },
  { step: "Levels", detail: "Entry next-bar open, swing-stop, RR-target." },
  { step: "Portfolio", detail: "Correlation hard/soft gates, max open positions." },
  { step: "Size", detail: "Kelly × convex × drawdown-scale × Ω-risk." },
  { step: "Notional cap", detail: "L6 — aggregate portfolio notional capped." },
  { step: "Kill-switch", detail: "L7 — drawdown velocity, exposure, anomaly detection." },
];

export function Technology() {
  return (
    <section id="technology" className="section section--technology">
      <div className="section__inner">
        <Reveal>
          <div className="section__head">
            <span className="section__num">§ IV</span>
            <h2 className="section__title">
              Nine engines. One <em>orchestrator.</em>
            </h2>
            <p className="section__sub">
              Each engine carries an institutional inspiration, a single
              mechanism, and its own out-of-sample verdict. MILLENNIUM
              allocates capital across the survivors under correlation and
              drawdown constraints.
            </p>
          </div>
        </Reveal>

        <div className="engine-stack">
          {ENGINES.map((e, i) => (
            <Reveal key={e.name} delay={i * 0.05}>
              <article className={`engine-row engine-row--${e.status}`}>
                <div className="engine-row__left">
                  <h3 className="engine-row__name">{e.name}</h3>
                  <span className="engine-row__inspo">after {e.inspiration}</span>
                </div>
                <div className="engine-row__mid">
                  <div className="engine-row__tag">{e.tag}</div>
                  <div className="engine-row__concept">{e.concept}</div>
                </div>
                <div className="engine-row__right">
                  <span className="engine-row__interval">{e.interval}</span>
                  <span
                    className={`verdict verdict--small verdict--${
                      ["active", "orchestrator"].includes(e.status)
                        ? "good"
                        : e.status === "active-arb"
                        ? "neutral"
                        : "warn"
                    }`}
                  >
                    {e.verdict}
                  </span>
                </div>
              </article>
            </Reveal>
          ))}
        </div>

        <Reveal delay={0.2}>
          <div className="pipeline">
            <div className="pipeline__head">
              <h3>Signal pipeline</h3>
              <p>Deterministic, observable at every step, replayable from disk.</p>
            </div>
            <ol className="pipeline__list">
              {PIPELINE.map((p, i) => (
                <li key={p.step} className="pipeline__step">
                  <span className="pipeline__num">{String(i + 1).padStart(2, "0")}</span>
                  <div>
                    <span className="pipeline__step-name">{p.step}</span>
                    <span className="pipeline__step-detail">{p.detail}</span>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
