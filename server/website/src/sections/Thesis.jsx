import { Reveal } from "../components/Reveal";

const PILLARS = [
  {
    num: "01",
    title: "Discrimination over prediction",
    body:
      "We do not forecast price. We filter noise from information — ensembles, regime gates, fractal validation. The signal must survive four concentric filters before it becomes a trade.",
  },
  {
    num: "02",
    title: "Honest out-of-sample",
    body:
      "Every engine carries hardcoded train/test/holdout dates at the top of its source. Sharpes without a Deflated-Sharpe haircut are disguised fiction. If a sweep fails the gate, the engine is archived.",
  },
  {
    num: "03",
    title: "Risk-first sizing",
    body:
      "Position size is Kelly × convex × drawdown-scale × Ω-risk, capped by aggregate portfolio notional. Three independent circuit breakers fail closed. Capital stops before the thesis does.",
  },
];

export function Thesis() {
  return (
    <section id="thesis" className="section section--thesis">
      <div className="section__inner">
        <Reveal>
          <div className="section__head">
            <span className="section__num">§ I</span>
            <h2 className="section__title">
              Information, <em>not matter.</em>
            </h2>
          </div>
        </Reveal>

        <Reveal delay={0.1}>
          <div className="thesis__lede">
            <p>
              The market encodes information — price and volume as a spiral,
              signal mixed with noise. Most participants are being read.
              AURUM runs its own laser. The task is discrimination, not
              prediction; process, not outcome.
            </p>
            <p className="thesis__lede-secondary">
              The platform is engineered around a single inversion: we build
              the reader before we build the strategy. Data validation,
              regime detection, and kill-switch logic predate any engine in
              the system. Every sharpe number reported passes a Deflated
              Sharpe Ratio haircut for trial multiplicity before it reaches
              a committee slide.
            </p>
          </div>
        </Reveal>

        <div className="pillars">
          {PILLARS.map((p, i) => (
            <Reveal key={p.num} delay={0.15 + i * 0.1}>
              <article className="pillar">
                <span className="pillar__num">{p.num}</span>
                <h3 className="pillar__title">{p.title}</h3>
                <p className="pillar__body">{p.body}</p>
              </article>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
