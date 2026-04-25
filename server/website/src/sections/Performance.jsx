import { Reveal } from "../components/Reveal";
import { Metric } from "../components/Metric";
import { EquityCurve } from "../components/charts/EquityCurve";
import { IridescentCard } from "../components/IridescentCard";
import { ENGINES, curve } from "../lib/data";

const EQUITY_CITADEL = curve(1, 120, 0.0055, 0.014);
const EQUITY_JUMP = curve(7, 120, 0.0038, 0.009);

export function Performance() {
  const citadel = ENGINES.find((e) => e.name === "CITADEL");
  const jump = ENGINES.find((e) => e.name === "JUMP");
  const renaissance = ENGINES.find((e) => e.name === "RENAISSANCE");

  return (
    <section id="performance" className="section section--performance">
      <div className="section__inner">
        <Reveal>
          <div className="section__head">
            <span className="section__num">§ IV</span>
            <h2 className="section__title">
              Performance, <em>out-of-sample.</em>
            </h2>
            <p className="section__sub">
              All figures below are walk-forward tests on windows
              <em> before</em> any calibration occurred. Reported alongside
              in-sample claims where relevant. Numbers degrade the honest
              way.
            </p>
          </div>
        </Reveal>

        <div className="perf-grid">
          <Reveal>
            <IridescentCard className="engine-card engine-card--lead">
              <header className="engine-card__head">
                <div>
                  <h3 className="engine-card__name">{citadel.name}</h3>
                  <p className="engine-card__tag">{citadel.tag} · {citadel.interval}</p>
                </div>
                <span className="verdict verdict--good">{citadel.verdict}</span>
              </header>

              <EquityCurve id="cit" data={EQUITY_CITADEL} height={200} />

              <div className="engine-card__metrics">
                <Metric value={citadel.metrics.sharpe_oos} label="Sharpe · OOS BEAR 2022" accent />
                <Metric value={citadel.metrics.sharpe_oos_alt} label="Sharpe · OOS BULL 2021" />
                <Metric value={citadel.metrics.sharpe_baseline} label="Sharpe · 360d baseline" />
                <Metric
                  value={citadel.metrics.winrate_oos * 100}
                  label="Win rate · OOS"
                  suffix="%"
                  decimals={1}
                />
              </div>

              <p className="engine-card__note">
                Positive Sharpe across three disjoint regime windows. Edge
                does not depend on the calibration period.
              </p>
            </IridescentCard>
          </Reveal>

          <Reveal delay={0.1}>
            <IridescentCard className="engine-card">
              <header className="engine-card__head">
                <div>
                  <h3 className="engine-card__name">{jump.name}</h3>
                  <p className="engine-card__tag">{jump.tag} · {jump.interval}</p>
                </div>
                <span className="verdict verdict--good">{jump.verdict}</span>
              </header>

              <EquityCurve id="jmp" data={EQUITY_JUMP} height={160} />

              <div className="engine-card__metrics engine-card__metrics--tight">
                <Metric value={jump.metrics.sharpe_oos} label="Sharpe · OOS" accent />
                <Metric value={jump.metrics.sortino_oos} label="Sortino · OOS" />
                <Metric
                  value={jump.metrics.maxdd_oos * 100}
                  label="Max DD · OOS"
                  suffix="%"
                  decimals={2}
                />
              </div>

              <p className="engine-card__note">
                OOS surpassed in-sample. Max drawdown held below 2% in a
                360-day BEAR window.
              </p>
            </IridescentCard>
          </Reveal>

          <Reveal delay={0.15}>
            <IridescentCard className="engine-card engine-card--moderate">
              <header className="engine-card__head">
                <div>
                  <h3 className="engine-card__name">{renaissance.name}</h3>
                  <p className="engine-card__tag">{renaissance.tag} · {renaissance.interval}</p>
                </div>
                <span className="verdict verdict--warn">{renaissance.verdict}</span>
              </header>

              <div className="engine-card__metrics engine-card__metrics--tight">
                <Metric value={renaissance.metrics.sharpe_oos} label="Sharpe · OOS (honest)" accent />
                <Metric value={renaissance.metrics.sharpe_claimed} label="Sharpe · in-sample claim" />
                <Metric
                  value={renaissance.metrics.winrate_oos * 100}
                  label="Win rate · OOS"
                  suffix="%"
                  decimals={1}
                />
              </div>

              <p className="engine-card__note">
                In-sample claim was inflated ≈57%. Engine still carries
                moderate edge at honest Sharpe. Reporting the gap is part
                of the protocol.
              </p>
            </IridescentCard>
          </Reveal>
        </div>

        <Reveal delay={0.2}>
          <div className="perf-table">
            <div className="perf-table__head">
              <h4>Cross-engine OOS summary</h4>
              <span className="perf-table__stamp">
                Window: 2022-01-01 → 2023-01-01 (360d BEAR)
              </span>
            </div>
            <table>
              <thead>
                <tr>
                  <th>Engine</th>
                  <th>Interval</th>
                  <th className="num">Sharpe</th>
                  <th className="num">Sortino</th>
                  <th className="num">Max DD</th>
                  <th className="num">Trades</th>
                  <th className="num">Win rate</th>
                  <th>Verdict</th>
                </tr>
              </thead>
              <tbody>
                {[citadel, jump, renaissance].map((e) => (
                  <tr key={e.name}>
                    <td className="name">{e.name}</td>
                    <td>{e.interval}</td>
                    <td className="num">{e.metrics.sharpe_oos.toFixed(3)}</td>
                    <td className="num">{e.metrics.sortino_oos?.toFixed(3) ?? "—"}</td>
                    <td className="num">{(e.metrics.maxdd_oos * 100).toFixed(2)}%</td>
                    <td className="num">{e.metrics.trades_oos ?? "—"}</td>
                    <td className="num">{(e.metrics.winrate_oos * 100).toFixed(1)}%</td>
                    <td>
                      <span
                        className={`verdict verdict--small ${
                          e.verdict === "EDGE REAL" || e.verdict === "ROBUSTO"
                            ? "verdict--good"
                            : "verdict--warn"
                        }`}
                      >
                        {e.verdict}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="perf-table__foot">
              All metrics net of slippage, spread, commission and funding.
              Position sizing under Kelly × convex × drawdown-scale × Ω-risk
              with aggregate notional cap at the portfolio level.
            </p>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
