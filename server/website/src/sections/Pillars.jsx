import { Reveal } from "../components/Reveal";
import { useT } from "../lib/i18n";

// Institutional pillar strip — three words that define the fund.
// Systematic · Sovereign · Survived. Sits between Hero and Bento as
// the first thing the eye lands on after the fold.
export function Pillars() {
  const t = useT();
  const items = [
    { key: "systematic" },
    { key: "sovereign" },
    { key: "survived" },
  ];
  return (
    <section className="section section--pillars" aria-label="Pillars">
      <div className="section__inner">
        <div className="pillars-strip">
          {items.map((it, i) => (
            <Reveal key={it.key} delay={0.08 * i}>
              <article className="pstrip-item">
                <div className="pstrip-item__num">{t(`pillars.${it.key}.num`)}</div>
                <h3 className="pstrip-item__title">{t(`pillars.${it.key}.title`)}</h3>
                <p className="pstrip-item__body">{t(`pillars.${it.key}.body`)}</p>
              </article>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
