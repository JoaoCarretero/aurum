import { Logo } from "./Logo";
import { SITE } from "../lib/data";

export function Footer() {
  return (
    <footer className="footer">
      <div className="footer__grid">
        <div className="footer__brand">
          <div className="footer__logo">
            <Logo size={22} />
            <span>{SITE.name}</span>
          </div>
          <p className="footer__tagline">{SITE.tagline}</p>
        </div>

        <div className="footer__col">
          <h5>Platform</h5>
          <a href="#thesis">Thesis</a>
          <a href="#methodology">Methodology</a>
          <a href="#performance">Performance</a>
          <a href="#technology">Technology</a>
        </div>

        <div className="footer__col">
          <h5>Research</h5>
          <a href="#research">Notes</a>
          <a href="#principles">Principles</a>
          <a href="#contact">Contact</a>
        </div>

        <div className="footer__col footer__disclaimer">
          <h5>Disclaimer</h5>
          <p>
            Performance figures are out-of-sample walk-forward tests on
            historical data. Past performance is not indicative of future
            results. AURUM is an invitation-only systematic platform.
            Allocation capacity is constrained by strategy capacity, not
            demand.
          </p>
        </div>
      </div>

      <div className="footer__rule" />

      <div className="footer__meta">
        <span>© {SITE.year} {SITE.name} — All rights reserved.</span>
        <span className="footer__meta-right">
          <code>{SITE.version}</code> · built by the laser
        </span>
      </div>
    </footer>
  );
}
