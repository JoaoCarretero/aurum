import { Reveal } from "../components/Reveal";
import { ANTI_OVERFIT, ARCHIVED } from "../lib/data";
import { useT } from "../lib/i18n";

export function Methodology() {
  const t = useT();
  return (
    <section id="methodology" className="section section--methodology">
      <div className="section__inner">
        <Reveal>
          <div className="section__head">
            <span className="section__num">{t("methodology.eyebrow")}</span>
            <h2 className="section__title">
              {t("methodology.titlePre")} <em>{t("methodology.titleEm")}</em>
            </h2>
            <p className="section__sub">{t("methodology.sub")}</p>
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
                {t("methodology.graveyard.title")}{" "}
                <em>{t("methodology.graveyard.titleEm")}</em>
              </h3>
              <p className="graveyard__sub">
                {ARCHIVED.length} {t("methodology.graveyard.body")}
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
