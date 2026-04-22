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

    // Hero
    "hero.eyebrowPrimary": "Systematic quant · crypto perpetual futures",
    "hero.eyebrowPill": "Invitation only",
    "hero.titlePre": "The tape reads",
    "hero.titleEm": "itself.",
    "hero.ledeStrong": "A sovereign quantitative fund for crypto perpetual futures.",
    "hero.ledeBody":
      "Nine engines read the market across five dimensions. Ensemble signal, deterministic sizing, three-layer kill-switch. We don't predict — we measure.",
    "hero.ctaPrimary": "Request research",
    "hero.ctaSecondary": "Read the methodology",
    "hero.metricsEngines": "Engines tested",
    "hero.metricsSharpeBear": "Sharpe · OOS bear",
    "hero.metricsJumpSharpe": "JUMP Sharpe · OOS",
    "hero.metricsLayers": "Risk layers",
    "hero.metricsMaxDd": "Max DD · OOS · %",

    // Pillars strip
    "pillars.systematic.num": "01",
    "pillars.systematic.title": "Systematic",
    "pillars.systematic.body":
      "Every trade is the output of a pipeline. Data → indicators → Ω fractal → regime → signal → portfolio → size → notional cap → kill-switch. No single human decides.",
    "pillars.sovereign.num": "02",
    "pillars.sovereign.title": "Sovereign",
    "pillars.sovereign.body":
      "Data, signal, sizing, risk, execution — every critical path is in-house. No vendor ML model, no third-party signal. If the cloud dies, the laser still reads the tape.",
    "pillars.survived.num": "03",
    "pillars.survived.title": "Survived",
    "pillars.survived.body":
      "Five of nine engines passed honest out-of-sample in the 2022 bear and 2024–25 cycles. DSR-adjusted. Four were archived. We report what we couldn't break.",

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

    // Hero
    "hero.eyebrowPrimary": "Quant sistemático · crypto perpetual futures",
    "hero.eyebrowPill": "Acesso por convite",
    "hero.titlePre": "O disco lê",
    "hero.titleEm": "a si mesmo.",
    "hero.ledeStrong":
      "Um fundo quantitativo soberano para crypto perpetual futures.",
    "hero.ledeBody":
      "Nove engines lêem o mercado em cinco dimensões. Sinal de ensemble, sizing determinístico, kill-switch em três camadas. A gente não prevê — a gente mede.",
    "hero.ctaPrimary": "Solicitar research",
    "hero.ctaSecondary": "Ler a metodologia",
    "hero.metricsEngines": "Engines testadas",
    "hero.metricsSharpeBear": "Sharpe · OOS bear",
    "hero.metricsJumpSharpe": "Sharpe · JUMP OOS",
    "hero.metricsLayers": "Camadas de risco",
    "hero.metricsMaxDd": "Max DD · OOS · %",

    // Pillars strip
    "pillars.systematic.num": "01",
    "pillars.systematic.title": "Sistemático",
    "pillars.systematic.body":
      "Todo trade é o output de um pipeline. Dados → indicadores → Ω fractal → regime → sinal → portfolio → sizing → notional cap → kill-switch. Nenhum humano decide sozinho.",
    "pillars.sovereign.num": "02",
    "pillars.sovereign.title": "Soberano",
    "pillars.sovereign.body":
      "Dados, sinal, sizing, risco, execução — cada caminho crítico é in-house. Nenhum modelo ML de vendor, nenhum sinal terceirizado. Se a nuvem cai, o laser continua lendo o tape.",
    "pillars.survived.num": "03",
    "pillars.survived.title": "Sobreviveu",
    "pillars.survived.body":
      "Cinco de nove engines passaram OOS honesto no bear de 2022 e nos ciclos 2024–25. Com haircut DSR. Quatro foram arquivadas. A gente reporta o que não conseguiu quebrar.",

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
