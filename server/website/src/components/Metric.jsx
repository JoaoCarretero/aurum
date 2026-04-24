import { motion, useInView, useMotionValue, useSpring, useTransform } from "framer-motion";
import { useEffect, useRef } from "react";

// Number-counter that animates in on scroll. Institutional — no bounce.
export function Metric({ value, label, prefix = "", suffix = "", decimals = 2, accent = false }) {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-40px" });
  const mv = useMotionValue(0);
  const spring = useSpring(mv, { stiffness: 90, damping: 24, mass: 0.8 });
  const display = useTransform(spring, (latest) => {
    const n = Number(latest);
    return prefix + n.toFixed(decimals) + suffix;
  });

  useEffect(() => {
    if (inView) mv.set(value);
  }, [inView, value, mv]);

  return (
    <div ref={ref} className={`metric ${accent ? "metric--accent" : ""}`}>
      <motion.div className="metric__value">{display}</motion.div>
      <div className="metric__label">{label}</div>
    </div>
  );
}
