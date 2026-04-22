import { useI18n } from "../lib/i18n";

/**
 * Compact EN / PT toggle for the nav. Matches Bloomberg-terminal
 * aesthetic — mono font, small caps, amber accent on active side.
 */
export function LanguageToggle() {
  const { lang, setLang, t } = useI18n();
  const isEn = lang === "en";

  return (
    <div className="lang-toggle" role="group" aria-label={t("lang.switchTo")}>
      <button
        type="button"
        className={`lang-toggle__btn ${isEn ? "is-active" : ""}`}
        aria-pressed={isEn}
        onClick={() => setLang("en")}
      >
        {t("lang.en")}
      </button>
      <span className="lang-toggle__sep" aria-hidden>/</span>
      <button
        type="button"
        className={`lang-toggle__btn ${!isEn ? "is-active" : ""}`}
        aria-pressed={!isEn}
        onClick={() => setLang("pt-br")}
      >
        {t("lang.ptBr")}
      </button>
    </div>
  );
}
