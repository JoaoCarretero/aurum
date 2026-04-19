import { Reveal } from "../components/Reveal";
import { PRINCIPLES } from "../lib/data";

export function Principles() {
  return (
    <section id="principles" className="section section--principles">
      <div className="section__inner">
        <Reveal>
          <div className="section__head">
            <span className="section__num">§ V</span>
            <h2 className="section__title">
              Seven operating <em>principles.</em>
            </h2>
            <p className="section__sub">
              The mandates the code itself is written against. Each is a
              discriminator — a condition the platform must satisfy before
              any capital moves.
            </p>
          </div>
        </Reveal>

        <div className="principles">
          {PRINCIPLES.map((p, i) => (
            <Reveal key={p.num} delay={i * 0.04}>
              <article className="principle">
                <span className="principle__num">{p.num}</span>
                <h3 className="principle__title">{p.title}</h3>
                <p className="principle__body">{p.body}</p>
              </article>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
