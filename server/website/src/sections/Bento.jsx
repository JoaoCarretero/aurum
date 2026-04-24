import { Reveal } from "../components/Reveal";

// Bento-style feature grid. Asymmetric cards, each surfacing one
// aspect of the platform without relying on text density alone.
export function Bento() {
  return (
    <section id="platform" className="section section--bento">
      <div className="section__inner">
        <Reveal>
          <div className="section__head">
            <span className="section__num">§ II</span>
            <h2 className="section__title">
              What the platform <em>actually does.</em>
            </h2>
            <p className="section__sub">
              AURUM reads perpetual futures markets at four timeframes simultaneously,
              filters noise through ensembles, sizes under risk gates, and kills
              itself before capital kills us.
            </p>
          </div>
        </Reveal>

        <div className="bento">
          <Reveal>
            <article className="bento__card bento__card--lead">
              <div className="bento__ornament bento__ornament--gold" />
              <div className="bento__content">
                <span className="bento__tag">signal core</span>
                <h3 className="bento__title">
                  Ω fractal — <em>five-dimensional</em> regime read
                </h3>
                <p className="bento__body">
                  Every bar is scored across five dimensions — trend, vol regime,
                  structure, momentum, drift. The signal only fires when four
                  concentric filters agree. Noise is the adversary, not a feature.
                </p>
                <div className="bento__chips">
                  <span className="chip">trend</span>
                  <span className="chip">vol-regime</span>
                  <span className="chip">structure</span>
                  <span className="chip">momentum</span>
                  <span className="chip chip--gold">drift</span>
                </div>
              </div>
            </article>
          </Reveal>

          <Reveal delay={0.08}>
            <article className="bento__card bento__card--risk">
              <div className="bento__content">
                <span className="bento__tag tag--good">kill-switch armed</span>
                <h3 className="bento__title">
                  Three risk layers. <em>Fail-closed.</em>
                </h3>
                <ul className="bento__list">
                  <li>
                    <span className="bento__list-num">L1</span>
                    Drawdown velocity — halts before the slide
                  </li>
                  <li>
                    <span className="bento__list-num">L2</span>
                    Aggregate notional cap at portfolio level
                  </li>
                  <li>
                    <span className="bento__list-num">L3</span>
                    Anomaly detection on tick integrity
                  </li>
                </ul>
              </div>
            </article>
          </Reveal>

          <Reveal delay={0.16}>
            <article className="bento__card bento__card--oos">
              <div className="bento__content">
                <span className="bento__tag">out-of-sample</span>
                <h3 className="bento__title">
                  Honest walk-forward. <em>No leak.</em>
                </h3>
                <p className="bento__body">
                  Train, test, and holdout dates hardcoded at the top of every
                  engine. DSR haircut before any Sharpe leaves the committee
                  slide. Failed engines are archived — not re-tuned.
                </p>
                <div className="bento__stat">
                  <span className="bento__stat-num">5/9</span>
                  <span className="bento__stat-label">survived OOS</span>
                </div>
              </div>
            </article>
          </Reveal>

          <Reveal delay={0.24}>
            <article className="bento__card bento__card--stack">
              <div className="bento__content">
                <span className="bento__tag">pipeline</span>
                <h3 className="bento__title">
                  Deterministic. <em>Replayable.</em>
                </h3>
                <div className="stack-pipe">
                  {[
                    "DATA",
                    "INDICATORS",
                    "HTF MERGE",
                    "REGIME",
                    "SIGNAL",
                    "PORTFOLIO",
                    "SIZE",
                    "NOTIONAL CAP",
                    "KILL-SWITCH",
                  ].map((s, i) => (
                    <div key={s} className="stack-pipe__step">
                      <span className="stack-pipe__num">{String(i + 1).padStart(2, "0")}</span>
                      <span className="stack-pipe__label">{s}</span>
                    </div>
                  ))}
                </div>
              </div>
            </article>
          </Reveal>

          <Reveal delay={0.32}>
            <article className="bento__card bento__card--sovereign">
              <div className="bento__content">
                <span className="bento__tag">sovereignty</span>
                <h3 className="bento__title">
                  Our own <em>laser.</em>
                </h3>
                <p className="bento__body">
                  Data, signal, sizing, risk, execution — every critical path
                  is internal. No external black-box dependency. If a vendor
                  disappears, the platform still reads the tape.
                </p>
              </div>
            </article>
          </Reveal>
        </div>
      </div>
    </section>
  );
}
