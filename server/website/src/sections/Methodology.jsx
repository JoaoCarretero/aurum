import { Reveal } from "../components/Reveal";
import { ANTI_OVERFIT, ARCHIVED } from "../lib/data";

export function Methodology() {
  return (
    <section id="methodology" className="section section--methodology">
      <div className="section__inner">
        <Reveal>
          <div className="section__head">
            <span className="section__num">§ II</span>
            <h2 className="section__title">
              The anti-overfit <em>protocol.</em>
            </h2>
            <p className="section__sub">
              Five gates every sweep must pass before a Sharpe number is
              reported. No exceptions. Archival is the default outcome, not
              the failure.
            </p>
          </div>
        </Reveal>

        <div className="protocol">
          {ANTI_OVERFIT.map((p, i) => (
            <Reveal key={p.num} delay={i * 0.06}>
              <article className="protocol__item">
                <span className="protocol__num">{p.num}</span>
                <div className="protocol__body">
                  <h3>{p.title}</h3>
                  <p>{p.body}</p>
                </div>
              </article>
            </Reveal>
          ))}
        </div>

        <Reveal delay={0.2}>
          <div className="graveyard">
            <div className="graveyard__head">
              <h3 className="graveyard__title">
                The graveyard is <em>methodology.</em>
              </h3>
              <p className="graveyard__sub">
                {ARCHIVED.length} engines developed, tested out-of-sample,
                and archived. Discipline requires killing. The engines that
                remain survive because the ones that failed were not kept.
              </p>
            </div>

            <ul className="graveyard__list">
              {ARCHIVED.map((e) => (
                <li key={e.name} className="graveyard__item">
                  <span className="graveyard__name">{e.name}</span>
                  <span className="graveyard__reason">{e.reason}</span>
                </li>
              ))}
            </ul>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
