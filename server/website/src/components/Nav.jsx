import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Logo } from "./Logo";
import { LanguageToggle } from "./LanguageToggle";
import { SITE } from "../lib/data";
import { useAuth } from "../lib/auth";
import { useT } from "../lib/i18n";

const LINKS = [
  { href: "#thesis", key: "nav.thesis" },
  { href: "#methodology", key: "nav.methodology" },
  { href: "#performance", key: "nav.performance" },
  { href: "#technology", key: "nav.technology" },
  { href: "#research", key: "nav.research" },
];

export function Nav() {
  const [scrolled, setScrolled] = useState(false);
  const { user, isAuthenticated, logout } = useAuth();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const t = useT();

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const showLinks = pathname === "/";

  return (
    <nav className={`nav ${scrolled ? "nav--scrolled" : ""}`}>
      <div className="nav__inner">
        <Link to="/" className="nav__brand" aria-label="AURUM home">
          <Logo size={24} />
          <span className="nav__brand-text">
            {SITE.name}
            <span className="nav__brand-mark">{SITE.version}</span>
          </span>
        </Link>
        {showLinks && (
          <ul className="nav__links">
            {LINKS.map((l) => (
              <li key={l.href}>
                <a href={l.href}>{t(l.key)}</a>
              </li>
            ))}
          </ul>
        )}
        <div className="nav__end">
          <LanguageToggle />
          {isAuthenticated ? (
            <div className="nav__auth">
              <button
                type="button"
                className="nav__members"
                onClick={() => navigate("/members")}
                title={user.email}
              >
                <span className="nav__members-dot" aria-hidden />
                <span className="nav__members-label">{t("nav.members")}</span>
              </button>
              <button type="button" className="nav__logout" onClick={logout}>
                {t("nav.logout")}
              </button>
            </div>
          ) : (
            <Link to="/login" className="nav__cta">
              {t("nav.login")}
            </Link>
          )}
        </div>
      </div>
    </nav>
  );
}
