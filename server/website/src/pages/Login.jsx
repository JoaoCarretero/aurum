import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Logo } from "../components/Logo";
import { LanguageToggle } from "../components/LanguageToggle";
import { useAuth } from "../lib/auth";
import { useT } from "../lib/i18n";

export function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const t = useT();
  const redirectTo = location.state?.from || "/members";

  async function onSubmit(e) {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await login(email, password);
      navigate(redirectTo, { replace: true });
    } catch (err) {
      // Surface translated error when the underlying message matches
      // a known mock failure, otherwise show raw message.
      const raw = err.message || "";
      if (raw.toLowerCase().includes("email")) setError(t("login.errorInvalidEmail"));
      else if (raw.toLowerCase().includes("senha") || raw.toLowerCase().includes("character")) {
        setError(t("login.errorShortPassword"));
      } else setError(raw || t("login.errorGeneric"));
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-shell">
      <div className="auth-backdrop" aria-hidden />
      <div className="auth-toggle"><LanguageToggle /></div>
      <motion.div
        className="auth-card"
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
      >
        <Link to="/" className="auth-card__brand" aria-label="AURUM home">
          <Logo size={28} />
          <span>AURUM</span>
        </Link>

        <h1 className="auth-card__title">{t("login.title")}</h1>
        <p className="auth-card__subtitle">{t("login.subtitle")}</p>

        <form className="auth-form" onSubmit={onSubmit} noValidate>
          <label className="auth-field">
            <span>{t("login.emailLabel")}</span>
            <input
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@desk.com"
              required
            />
          </label>

          <label className="auth-field">
            <span>{t("login.passwordLabel")}</span>
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              required
            />
          </label>

          {error && (
            <div role="alert" className="auth-error">
              {error}
            </div>
          )}

          <button type="submit" className="auth-submit" disabled={submitting}>
            {submitting ? t("login.submitting") : t("login.submit")}
          </button>
        </form>

        <div className="auth-card__foot">
          <Link to="/" className="auth-back">{t("login.back")}</Link>
          <span className="auth-hint">
            {t("login.hint")} <code>lib/auth.jsx</code>
          </span>
        </div>
      </motion.div>
    </div>
  );
}
