import { createContext, useContext, useState, useEffect, useCallback } from "react";
import { translations, DEFAULT_LANG, SUPPORTED_LANGS } from "./translations";

const STORAGE_KEY = "aurum_lang";
const I18nContext = createContext(null);

function detectInitialLang() {
  // 1. localStorage override
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved && SUPPORTED_LANGS.includes(saved)) return saved;
  } catch {
    /* fall through */
  }
  // 2. Browser locale — pt / pt-* → pt-br
  if (typeof navigator !== "undefined" && navigator.language) {
    const loc = navigator.language.toLowerCase();
    if (loc.startsWith("pt")) return "pt-br";
  }
  return DEFAULT_LANG;
}

export function I18nProvider({ children }) {
  const [lang, setLangState] = useState(detectInitialLang);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, lang);
    } catch {
      /* storage may be disabled — that's fine */
    }
    if (typeof document !== "undefined") {
      document.documentElement.lang = lang === "pt-br" ? "pt-BR" : "en";
    }
  }, [lang]);

  const setLang = useCallback((next) => {
    if (SUPPORTED_LANGS.includes(next)) setLangState(next);
  }, []);

  const t = useCallback(
    (key) => {
      const table = translations[lang] || translations[DEFAULT_LANG] || {};
      if (key in table) return table[key];
      // Fallback to default lang, then to the key itself
      const fallback = translations[DEFAULT_LANG] || {};
      return fallback[key] !== undefined ? fallback[key] : key;
    },
    [lang],
  );

  const value = { lang, setLang, t, supported: SUPPORTED_LANGS };
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used within <I18nProvider>.");
  return ctx;
}

export function useT() {
  return useI18n().t;
}
