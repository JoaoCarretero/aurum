import { Reveal } from "../components/Reveal";
import { RESEARCH } from "../lib/data";
import { useT } from "../lib/i18n";

export function Research() {
  const t = useT();
  return (
    <section id="research" className="section section--research">
      <div className="section__inner">
        <Reveal>
          <div className="section__head">
            <span className="section__num">{t("research.eyebrow")}</span>
            <h2 className="section__title">
              {t("research.titlePre")} <em>{t("research.titleEm")}</em>
            </h2>
            <p className="section__sub">{t("research.sub")}</p>
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
                  {t("research.requestFull")}
                </a>
              </article>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
