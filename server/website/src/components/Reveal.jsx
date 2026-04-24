import { motion } from "framer-motion";
import { ease } from "../lib/tokens";

// Subtle scroll-reveal wrapper. Institutional motion — fades and
// small Y translation. No bounces, no flashes.
export function Reveal({ children, delay = 0, y = 12, className, as = "div" }) {
  const MotionTag = motion[as] || motion.div;
  return (
    <MotionTag
      initial={{ opacity: 0, y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-60px" }}
      transition={{ duration: 0.8, delay, ease }}
      className={className}
    >
      {children}
    </MotionTag>
  );
}
