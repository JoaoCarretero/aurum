import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { ease } from "../lib/tokens";

// Institutional "fake terminal" snippet — conveys the platform is
// operational without selling shell commands as a feature.
const LINES = [
  { t: "cmd", text: "$ aurum status" },
  { t: "out", text: "Loading millennium orchestrator..." },
  { t: "out", text: "  ✓ CITADEL       15m   edge_real     sharpe 5.68" },
  { t: "out", text: "  ✓ JUMP          1h    robusto       sharpe 3.15" },
  { t: "out", text: "  ⚠ RENAISSANCE   15m   edge_moderado sharpe 2.42" },
  { t: "out", text: "  ● JANE_STREET   1m    arb           delta-neutral" },
  { t: "out", text: "" },
  { t: "out", text: "risk layers      3/3 armed" },
  { t: "out", text: "kill-switch      fail-closed" },
  { t: "out", text: "uptime           continuous" },
  { t: "cmd", text: "$ _" },
];

export function Terminal() {
  const [line, setLine] = useState(0);
  useEffect(() => {
    const id = setInterval(() => {
      setLine((n) => (n < LINES.length ? n + 1 : n));
    }, 260);
    return () => clearInterval(id);
  }, []);

  return (
    <motion.div
      className="terminal"
      initial={{ opacity: 0, y: 20, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 1.1, delay: 0.8, ease }}
    >
      <div className="terminal__head">
        <span className="terminal__dot terminal__dot--r" />
        <span className="terminal__dot terminal__dot--y" />
        <span className="terminal__dot terminal__dot--g" />
        <span className="terminal__title">aurum — status</span>
        <span className="terminal__badge">LIVE</span>
      </div>
      <div className="terminal__body">
        {LINES.slice(0, line).map((l, i) => (
          <div
            key={i}
            className={`terminal__line terminal__line--${l.t}`}
            style={{ animationDelay: `${i * 30}ms` }}
          >
            {l.text || "\u00a0"}
          </div>
        ))}
      </div>
    </motion.div>
  );
}
