import { motion } from "framer-motion";
import { ease } from "../lib/tokens";
import { SITE } from "../lib/data";

export function Hero() {
  return (
    <section id="top" className="hero">
      <div className="hero__orb hero__orb--a" />
      <div className="hero__orb hero__orb--b" />
      <div className="grid-bg" />

      <div className="hero__inner">
        <motion.div
          className="hero__eyebrow"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, ease }}
        >
          <span className="hero__dot" />
          Systematic quant · Crypto perpetual futures
        </motion.div>

        <motion.h1
          className="hero__title"
          initial={{ opacity: 0, y: 18 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 1.0, delay: 0.1, ease }}
        >
          The tape
          <br />
          <em>reads itself.</em>
        </motion.h1>

        <motion.p
          className="hero__lede"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.9, delay: 0.25, ease }}
        >
          {SITE.description}
        </motion.p>

        <motion.div
          className="hero__meta"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.9, delay: 0.4, ease }}
        >
          <span>Out-of-sample validated</span>
          <span className="hero__meta-sep">·</span>
          <span>Walk-forward tested</span>
          <span className="hero__meta-sep">·</span>
          <span>Kill-switch protected</span>
        </motion.div>

        <motion.div
          className="hero__cta"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.55, ease }}
        >
          <a href="#contact" className="btn btn--primary">
            Request research
          </a>
          <a href="#methodology" className="btn btn--ghost">
            Read the methodology →
          </a>
        </motion.div>
      </div>

      <motion.div
        className="hero__scroll"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 1.2, delay: 1.2, ease }}
      >
        <span>SCROLL</span>
        <div className="hero__scroll-bar" />
      </motion.div>
    </section>
  );
}
