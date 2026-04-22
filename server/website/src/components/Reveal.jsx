import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { ease } from "../lib/tokens";

/**
 * Subtle scroll-reveal wrapper — institutional motion. Fades and small Y translation.
 *
 * Defensive implementation (2026-04-22 fix):
 * Previous version used framer-motion's `whileInView` with
 * `viewport: { once: true, margin: "-60px" }`. In some environments — rapid
 * scroll on mobile, engines that throttle IO callbacks, sections taller than
 * the viewport so they never reach the intersection threshold — the reveal
 * could silently fail to fire and the content stayed permanently at opacity 0.
 * Symptom: user scrolls down, nothing else appears.
 *
 * New design uses a native IntersectionObserver with layered safeguards:
 *   1. threshold 0 + rootMargin shrinking from the bottom → fires slightly
 *      before the element enters the viewport
 *   2. synchronous getBoundingClientRect on mount → if already visible,
 *      reveal next frame instead of waiting for async IO
 *   3. 1.4s hard-safety timeout → if anything slips, content still appears
 *   4. fallback to "always visible" on browsers without IO (server-side
 *      renders, very old browsers)
 */
export function Reveal({ children, delay = 0, y = 12, className, as = "div" }) {
  const ref = useRef(null);
  const [visible, setVisible] = useState(false);
  const MotionTag = motion[as] || motion.div;

  useEffect(() => {
    if (visible) return undefined;
    const node = ref.current;
    if (!node) return undefined;

    // Fallback for environments without IntersectionObserver.
    if (typeof IntersectionObserver === "undefined") {
      setVisible(true);
      return undefined;
    }

    // 1. Sync initial check — reveal immediately if already in view.
    const rect = node.getBoundingClientRect();
    const viewportH = window.innerHeight || document.documentElement.clientHeight;
    if (rect.top < viewportH && rect.bottom > 0) {
      const raf = requestAnimationFrame(() => setVisible(true));
      return () => cancelAnimationFrame(raf);
    }

    // 2. IntersectionObserver — threshold 0 + negative bottom margin so
    //    we fire a hair before the element actually enters view.
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setVisible(true);
            io.disconnect();
            break;
          }
        }
      },
      { threshold: 0, rootMargin: "0px 0px -60px 0px" },
    );
    io.observe(node);

    // 3. Hard-safety timeout. If everything else silently fails, this
    //    ensures content surfaces within 1.4s of mount instead of
    //    leaving the user staring at blank space.
    const safety = window.setTimeout(() => setVisible(true), 1400);

    return () => {
      io.disconnect();
      window.clearTimeout(safety);
    };
  }, [visible]);

  return (
    <MotionTag
      ref={ref}
      initial={{ opacity: 0, y }}
      animate={visible ? { opacity: 1, y: 0 } : { opacity: 0, y }}
      transition={{ duration: 0.8, delay, ease }}
      className={className}
      style={{ willChange: visible ? "auto" : "opacity, transform" }}
    >
      {children}
    </MotionTag>
  );
}
