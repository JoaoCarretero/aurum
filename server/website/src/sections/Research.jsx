import { Reveal } from "../components/Reveal";
import { RESEARCH } from "../lib/data";

export function Research() {
  return (
    <section id="research" className="section section--research">
      <div className="section__inner">
        <Reveal>
          <div className="section__head">
            <span className="section__num">§ VIII</span>
            <h2 className="section__title">
              Research <em>notes.</em>
            </h2>
            <p className="section__sub">
              Selected internal research published to prospective partners.
              The full archive — engine postmortems, audit logs,
              methodology revisions — is available under NDA.
            </p>
          </div>
        </Reveal>

        <div className="research">
          {RESEARCH.map((r, i) => (
            <Reveal key={r.title} delay={i * 0.06}>
              <article className="research-card">
                <header className="research-card__head">
                  <span className="research-card__kind">{r.kind}</span>
                  <span className="research-card__date">{r.date}</span>
                </header>
                <h3 className="research-card__title">{r.title}</h3>
                <p className="research-card__abstract">{r.abstract}</p>
                <a className="research-card__link" href="#contact">
                  Request full note →
                </a>
              </article>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
