import { Navigate, Link } from "react-router-dom";
import { motion } from "framer-motion";
import { Logo } from "../components/Logo";
import { LanguageToggle } from "../components/LanguageToggle";
import { useAuth } from "../lib/auth";
import { useT } from "../lib/i18n";

const CARD_KEYS = [
  {
    titleKey: "members.card.portfolio.title",
    descKey: "members.card.portfolio.desc",
  },
  {
    titleKey: "members.card.signals.title",
    descKey: "members.card.signals.desc",
  },
  {
    titleKey: "members.card.research.title",
    descKey: "members.card.research.desc",
  },
  {
    titleKey: "members.card.settings.title",
    descKey: "members.card.settings.desc",
  },
];

export function Members() {
  const { user, isAuthenticated, logout } = useAuth();
  const t = useT();

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: "/members" }} />;
  }

  return (
    <div className="members-shell">
      <header className="members-header">
        <Link to="/" className="members-header__brand" aria-label="AURUM home">
          <Logo size={22} />
          <span>AURUM · {t("nav.members").toUpperCase()}</span>
        </Link>
        <div className="members-header__user">
          <LanguageToggle />
          <span className="members-header__email" title={user.email}>{user.email}</span>
          <button type="button" className="members-logout" onClick={logout}>
            {t("nav.logout")}
          </button>
        </div>
      </header>

      <main className="members-main">
        <motion.section
          className="members-hero"
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
        >
          <div className="members-hero__eyebrow">{t("members.eyebrow")}</div>
          <h1 className="members-hero__title">{t("members.welcomeTitle")}</h1>
          <p className="members-hero__subtitle">{t("members.welcomeBody")}</p>
        </motion.section>

        <section className="members-grid" aria-label={t("members.eyebrow")}>
          {CARD_KEYS.map((c, i) => (
            <motion.article
              key={c.titleKey}
              className="members-card"
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.05 * i, ease: [0.22, 1, 0.36, 1] }}
            >
              <div className="members-card__title">{t(c.titleKey)}</div>
              <p className="members-card__desc">{t(c.descKey)}</p>
              <button type="button" className="members-card__cta" disabled>
                {t("members.comingSoon")}
              </button>
            </motion.article>
          ))}
        </section>

        <footer className="members-foot">
          <span>{t("members.foot")}</span>
        </footer>
      </main>
    </div>
  );
}
