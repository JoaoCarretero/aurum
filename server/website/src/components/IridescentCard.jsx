import { useEffect, useRef } from "react";

// Iridescent surface — metallic amber sheen reacting to cursor position.
// Restricted to the AURUM amber/cream palette (no rainbow). All cursor
// state flows through CSS variables updated inside a single rAF loop.
// Respects prefers-reduced-motion and degrades gracefully on touch.
export function IridescentCard({
  children,
  className = "",
  as: Tag = "article",
  ...rest
}) {
  const ref = useRef(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const reduced =
      typeof window !== "undefined" &&
      window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) return;

    let raf = 0;
    let active = false;
    const target = { mx: 50, my: 50, rx: 0, ry: 0, ang: 0 };
    const current = { mx: 50, my: 50, rx: 0, ry: 0, ang: 0 };

    const tick = () => {
      const k = 0.18;
      current.mx += (target.mx - current.mx) * k;
      current.my += (target.my - current.my) * k;
      current.rx += (target.rx - current.rx) * k;
      current.ry += (target.ry - current.ry) * k;
      current.ang += (target.ang - current.ang) * k;
      el.style.setProperty("--mx", current.mx.toFixed(2) + "%");
      el.style.setProperty("--my", current.my.toFixed(2) + "%");
      el.style.setProperty("--rx", current.rx.toFixed(2) + "deg");
      el.style.setProperty("--ry", current.ry.toFixed(2) + "deg");
      el.style.setProperty("--ang", current.ang.toFixed(2) + "deg");

      const settled =
        Math.abs(target.mx - current.mx) < 0.05 &&
        Math.abs(target.my - current.my) < 0.05 &&
        Math.abs(target.rx - current.rx) < 0.02 &&
        Math.abs(target.ry - current.ry) < 0.02;

      if (active || !settled) {
        raf = requestAnimationFrame(tick);
      } else {
        raf = 0;
      }
    };

    const start = () => {
      if (!raf) raf = requestAnimationFrame(tick);
    };

    const onMove = (e) => {
      const rect = el.getBoundingClientRect();
      const x = (e.clientX - rect.left) / rect.width;
      const y = (e.clientY - rect.top) / rect.height;
      target.mx = x * 100;
      target.my = y * 100;
      target.ry = (x - 0.5) * 7;
      target.rx = -(y - 0.5) * 5;
      target.ang = (x - 0.5) * 90;
      active = true;
      start();
    };

    const onLeave = () => {
      target.mx = 50;
      target.my = 50;
      target.rx = 0;
      target.ry = 0;
      target.ang = 0;
      active = false;
      start();
    };

    const onEnter = () => {
      active = true;
      start();
    };

    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerleave", onLeave);
    el.addEventListener("pointerenter", onEnter);
    return () => {
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerleave", onLeave);
      el.removeEventListener("pointerenter", onEnter);
      if (raf) cancelAnimationFrame(raf);
    };
  }, []);

  return (
    <Tag
      ref={ref}
      className={`iridescent ${className}`.trim()}
      {...rest}
    >
      <span className="iridescent__sheen" aria-hidden="true" />
      <span className="iridescent__glow" aria-hidden="true" />
      <span className="iridescent__noise" aria-hidden="true" />
      <span className="iridescent__edge" aria-hidden="true" />
      {children}
    </Tag>
  );
}
