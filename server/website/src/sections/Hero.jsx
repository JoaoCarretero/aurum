import { motion, useScroll, useTransform } from "framer-motion";
import { useRef } from "react";
import { ease } from "../lib/tokens";
import { Terminal } from "../components/Terminal";
import { Metric } from "../components/Metric";
import { useT } from "../lib/i18n";

export function Hero() {
  const ref = useRef(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end start"] });
  // Parallax apenas nos orbs — conteúdo NÃO fade-out. (bug anterior: content sumia ao rolar)
  const yOrbA = useTransform(scrollYProgress, [0, 1], [0, -140]);
  const yOrbB = useTransform(scrollYProgress, [0, 1], [0, -80]);
  const t = useT();

  return (
    <section id="top" className="hero" ref={ref}>
      <motion.div className="hero__orb hero__orb--a" style={{ y: yOrbA }} />
      <motion.div className="hero__orb hero__orb--b" style={{ y: yOrbB }} />
      <div className="grid-bg" />
      <div className="scanline" />

      <div className="hero__inner">
        <motion.div
          className="hero__eyebrow"
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease }}
        >
          <span className="hero__dot" />
          <span>{t("hero.eyebrowPrimary")}</span>
          <span className="hero__eyebrow-sep">·</span>
          <span className="hero__eyebrow-pill">{t("hero.eyebrowPill")}</span>
        </motion.div>

        <motion.h1
          className="hero__title"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.9, delay: 0.08, ease }}
        >
          {t("hero.titlePre")} <span className="hero__title-em">{t("hero.titleEm")}</span>
        </motion.h1>

        <motion.p
          className="hero__lede"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.2, ease }}
        >
          <span className="hero__lede-strong">{t("hero.ledeStrong")}</span>
          <br />
          {t("hero.ledeBody")}
        </motion.p>

        <motion.div
          className="hero__cta"
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.32, ease }}
        >
          <a href="#contact" className="btn btn--primary">
            <span>{t("hero.ctaPrimary")}</span>
            <span className="btn__arrow">→</span>
          </a>
          <a href="#methodology" className="btn btn--ghost">
            {t("hero.ctaSecondary")}
          </a>
        </motion.div>

        <div className="hero__metrics">
          <Metric value={9} label={t("hero.metricsEngines")} decimals={0} />
          <Metric value={5.68} label={t("hero.metricsSharpeBear")} accent />
          <Metric value={3.15} label={t("hero.metricsJumpSharpe")} />
          <Metric value={3} label={t("hero.metricsLayers")} decimals={0} />
          <Metric value={1.65} label={t("hero.metricsMaxDd")} suffix="%" decimals={2} />
        </div>

        <Terminal />
      </div>
    </section>
  );
}
