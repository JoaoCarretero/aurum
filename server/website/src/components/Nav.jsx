import { useEffect, useState } from "react";
import { Logo } from "./Logo";
import { SITE } from "../lib/data";

const LINKS = [
  { href: "#thesis", label: "Thesis" },
  { href: "#methodology", label: "Methodology" },
  { href: "#performance", label: "Performance" },
  { href: "#technology", label: "Technology" },
  { href: "#research", label: "Research" },
];

export function Nav() {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <nav className={`nav ${scrolled ? "nav--scrolled" : ""}`}>
      <div className="nav__inner">
        <a href="#top" className="nav__brand" aria-label="AURUM home">
          <Logo size={24} />
          <span className="nav__brand-text">
            {SITE.name}
            <span className="nav__brand-mark">{SITE.version}</span>
          </span>
        </a>
        <ul className="nav__links">
          {LINKS.map((l) => (
            <li key={l.href}>
              <a href={l.href}>{l.label}</a>
            </li>
          ))}
        </ul>
        <a href="#contact" className="nav__cta">
          Request access
        </a>
      </div>
    </nav>
  );
}
