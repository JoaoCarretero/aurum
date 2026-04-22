import { Reveal } from "../components/Reveal";
import { PRINCIPLES } from "../lib/data";
import { useT } from "../lib/i18n";

export function Principles() {
  const t = useT();
  return (
    <section id="principles" className="section section--principles">
      <div className="section__inner">
        <Reveal>
          <div className="section__head">
            <span className="section__num">{t("principles.eyebrow")}</span>
            <h2 className="section__title">
              {t("principles.titlePre")} <em>{t("principles.titleEm")}</em>
            </h2>
            <p className="section__sub">{t("principles.sub")}</p>
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
