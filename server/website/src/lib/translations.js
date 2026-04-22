/**
 * Translation dictionary — English (source) and Brazilian Portuguese.
 *
 * Keys use dot notation, flat. Falls back to key string if miss.
 * Financial / quant vocabulary in PT-BR follows Brazilian trading desk
 * conventions (keep "backtest", "edge", "signal" as loanwords when the
 * Portuguese equivalent is uncommon).
 *
 * First pass covers: Nav, Footer, Login, Members, language toggle.
 * Section text (Hero/Bento/Thesis/etc) will be extracted in a follow-up
 * pass to avoid conflict with in-flight polish work.
 */

export const translations = {
  en: {
    // Nav
    "nav.thesis": "Thesis",
    "nav.methodology": "Methodology",
    "nav.performance": "Performance",
    "nav.technology": "Technology",
    "nav.research": "Research",
    "nav.login": "Sign in",
    "nav.logout": "Sign out",
    "nav.members": "Members area",
    "nav.requestAccess": "Request access",

    // Footer
    "footer.tagline": "The tape reads itself.",

    // Login
    "login.title": "Members access",
    "login.subtitle": "Restricted terminal. Live signals, in-house research, reports.",
    "login.emailLabel": "Email",
    "login.passwordLabel": "Password",
    "login.submit": "Sign in",
    "login.submitting": "Signing in…",
    "login.back": "← Back to site",
    "login.hint": "Mock implementation in",
    "login.errorInvalidEmail": "Invalid email.",
    "login.errorShortPassword": "Password must be at least 6 characters.",
    "login.errorGeneric": "Sign-in failed.",

    // Members
    "members.eyebrow": "Private terminal",
    "members.welcomeTitle": "Welcome to the desk.",
    "members.welcomeBody":
      "This area is your own laser. While the rest of the market reacts to the feed, AURUM reads its own flow — signals, risk, position, all in one place.",
    "members.card.portfolio.title": "Portfolio Status",
    "members.card.portfolio.desc":
      "Live equity, drawdown, gross and net exposure per engine.",
    "members.card.signals.title": "Signals Feed",
    "members.card.signals.desc":
      "Stream from operational engines — CITADEL, JUMP, MILLENNIUM, JANE STREET.",
    "members.card.research.title": "Research Library",
    "members.card.research.desc":
      "OOS audits, walk-forward, Monte Carlo, archived hypotheses.",
    "members.card.settings.title": "Account Settings",
    "members.card.settings.desc":
      "API keys, Telegram notifications, risk preferences.",
    "members.comingSoon": "Coming soon",
    "members.foot":
      "This panel is a placeholder. Cockpit API integration (/v1/runs, /trading/status) ships next iteration.",

    // Language toggle
    "lang.en": "EN",
    "lang.ptBr": "PT",
    "lang.switchTo": "Switch language",
  },

  "pt-br": {
    // Nav
    "nav.thesis": "Tese",
    "nav.methodology": "Metodologia",
    "nav.performance": "Performance",
    "nav.technology": "Tecnologia",
    "nav.research": "Research",
    "nav.login": "Entrar",
    "nav.logout": "Sair",
    "nav.members": "Área de membros",
    "nav.requestAccess": "Solicitar acesso",

    // Footer
    "footer.tagline": "O disco lê a si mesmo.",

    // Login
    "login.title": "Acesso membros",
    "login.subtitle":
      "Terminal restrito. Sinais ao vivo, research interna, relatórios.",
    "login.emailLabel": "Email",
    "login.passwordLabel": "Senha",
    "login.submit": "Entrar",
    "login.submitting": "Entrando…",
    "login.back": "← Voltar ao site",
    "login.hint": "Mock em",
    "login.errorInvalidEmail": "Email inválido.",
    "login.errorShortPassword": "Senha precisa ter pelo menos 6 caracteres.",
    "login.errorGeneric": "Falha ao entrar.",

    // Members
    "members.eyebrow": "Terminal privado",
    "members.welcomeTitle": "Bem-vindo ao desk.",
    "members.welcomeBody":
      "Esta área é o seu laser. Enquanto o restante do mercado reage ao feed, AURUM lê o próprio fluxo — sinais, risco, posição, tudo em um lugar.",
    "members.card.portfolio.title": "Status do Portfolio",
    "members.card.portfolio.desc":
      "Equity ao vivo, drawdown, exposição bruta e líquida por engine.",
    "members.card.signals.title": "Feed de Sinais",
    "members.card.signals.desc":
      "Stream dos engines operacionais — CITADEL, JUMP, MILLENNIUM, JANE STREET.",
    "members.card.research.title": "Biblioteca de Research",
    "members.card.research.desc":
      "Audits OOS, walk-forward, Monte Carlo, hipóteses arquivadas.",
    "members.card.settings.title": "Configurações da Conta",
    "members.card.settings.desc":
      "API keys, notificações Telegram, preferências de risco.",
    "members.comingSoon": "Em breve",
    "members.foot":
      "Este painel é um placeholder. A integração com o cockpit API (/v1/runs, /trading/status) vem na próxima iteração.",

    // Language toggle
    "lang.en": "EN",
    "lang.ptBr": "PT",
    "lang.switchTo": "Trocar idioma",
  },
};

export const DEFAULT_LANG = "en";
export const SUPPORTED_LANGS = ["en", "pt-br"];
