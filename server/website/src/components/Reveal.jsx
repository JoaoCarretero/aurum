import { useEffect, useRef, useState, createElement } from "react";

// Subtle scroll-reveal wrapper. Institutional motion — fades and
// small Y translation. No bounces, no flashes.
//
// Plain React + IntersectionObserver + CSS transitions (no framer-motion).
// Honors prefers-reduced-motion via styles.css.
export function Reveal({ children, delay = 0, y = 12, className, as = "div" }) {
  const ref = useRef(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (typeof IntersectionObserver === "undefined") {
      // SSR / very old browsers — show immediately.
      setVisible(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setVisible(true);
            observer.disconnect();
            break;
          }
        }
      },
      { rootMargin: "0px 0px -60px 0px" }
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const classes = ["reveal", className, visible ? "is-visible" : ""]
    .filter(Boolean)
    .join(" ");

  const style = {
    "--reveal-delay": `${delay * 1000}ms`,
    "--reveal-y": `${y}px`,
  };

  return createElement(as, { ref, className: classes, style }, children);
}
