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

    // Section heads — Thesis
    "thesis.eyebrow": "§ I",
    "thesis.titlePre": "Information,",
    "thesis.titleEm": "not matter.",
    "thesis.ledePrimary":
      "The market encodes information — price and volume as a spiral, signal mixed with noise. Most participants are being read. AURUM runs its own laser. The task is discrimination, not prediction; process, not outcome.",
    "thesis.ledeSecondary":
      "The platform is engineered around a single inversion: we build the reader before we build the strategy. Data validation, regime detection, and kill-switch logic predate any engine in the system. Every Sharpe number reported passes a Deflated Sharpe Ratio haircut for trial multiplicity before it reaches a committee slide.",

    // Section heads — Methodology
    "methodology.eyebrow": "§ III",
    "methodology.titlePre": "The anti-overfit",
    "methodology.titleEm": "protocol.",
    "methodology.sub":
      "Five gates every sweep must pass before a Sharpe number is reported. No exceptions. Archival is the default outcome, not the failure.",
    "methodology.graveyard.title": "The graveyard is",
    "methodology.graveyard.titleEm": "methodology.",
    "methodology.graveyard.body":
      "engines developed, tested out-of-sample, and archived. Discipline requires killing. The engines that remain survive because the ones that failed were not kept.",

    // Section heads — Performance
    "performance.eyebrow": "§ IV",
    "performance.titlePre": "Performance,",
    "performance.titleEm": "out-of-sample.",
    "performance.sub":
      "All figures below are walk-forward tests on windows before any calibration occurred. Reported alongside in-sample claims where relevant. Numbers degrade the honest way.",
    "performance.table.heading": "Cross-engine OOS summary",
    "performance.table.stamp": "Window: 2022-01-01 → 2023-01-01 (360d BEAR)",
    "performance.table.foot":
      "All metrics net of slippage, spread, commission and funding. Position sizing under Kelly × convex × drawdown-scale × Ω-risk with aggregate notional cap at the portfolio level.",

    // Section heads — CodeShowcase
    "code.eyebrow": "§ V",
    "code.titlePre": "Readable alchemy —",
    "code.titleEm": "one function, one job.",
    "code.sub":
      "The platform is written to be audited line-by-line. Signal, risk, and sizing each live in a single pure function. No hidden state, no global side-effects, no ternary magic.",

    // Section heads — Technology
    "technology.eyebrow": "§ VI",
    "technology.titlePre": "Nine engines. One",
    "technology.titleEm": "orchestrator.",
    "technology.sub":
      "Each engine carries an institutional inspiration, a single mechanism, and its own out-of-sample verdict. MILLENNIUM allocates capital across the survivors under correlation and drawdown constraints.",
    "technology.pipeline.title": "Signal pipeline",
    "technology.pipeline.body":
      "Deterministic, observable at every step, replayable from disk.",

    // Section heads — Principles
    "principles.eyebrow": "§ VII",
    "principles.titlePre": "Seven operating",
    "principles.titleEm": "principles.",
    "principles.sub":
      "The mandates the code itself is written against. Each is a discriminator — a condition the platform must satisfy before any capital moves.",

    // Section heads — Research
    "research.eyebrow": "§ VIII",
    "research.titlePre": "Research",
    "research.titleEm": "notes.",
    "research.sub":
      "Selected internal research published to prospective partners. The full archive — engine postmortems, audit logs, methodology revisions — is available under NDA.",
    "research.requestFull": "Request full note →",

    // Section heads — Contact
    "contact.eyebrow": "§ IX",
    "contact.titlePre": "Invitation only. Limited",
    "contact.titleEm": "capacity.",
    "contact.sub":
      "AURUM allocates under a strategy-capacity constraint, not a demand constraint. Reach out for research access or to discuss allocation under NDA.",
    "contact.form.nameLabel": "Name",
    "contact.form.emailLabel": "Email",
    "contact.form.orgLabel": "Organisation",
    "contact.form.noteLabel": "Context",
    "contact.form.namePh": "Jane Investor",
    "contact.form.emailPh": "jane@family-office.com",
    "contact.form.orgPh": "Optional",
    "contact.form.notePh":
      "What would you like to discuss — research notes, allocation timeline, technical diligence?",
    "contact.form.send": "Send request",
    "contact.form.sent": "Opened your mail client",
    "contact.form.or": "Or write directly to",

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

    // Section heads — Thesis
    "thesis.eyebrow": "§ I",
    "thesis.titlePre": "Informação,",
    "thesis.titleEm": "não matéria.",
    "thesis.ledePrimary":
      "O mercado codifica informação — preço e volume em espiral, sinal misturado com ruído. A maioria dos participantes está sendo lida. AURUM tem seu próprio laser. A tarefa é discriminar, não prever; processo, não resultado.",
    "thesis.ledeSecondary":
      "A plataforma é desenhada em torno de uma inversão: construímos o leitor antes de construir a estratégia. Validação de dados, detecção de regime e lógica de kill-switch precedem qualquer engine no sistema. Todo Sharpe reportado passa por haircut DSR por multiplicidade de testes antes de virar slide de comitê.",

    // Section heads — Methodology
    "methodology.eyebrow": "§ III",
    "methodology.titlePre": "O protocolo",
    "methodology.titleEm": "anti-overfit.",
    "methodology.sub":
      "Cinco portões que todo sweep precisa atravessar antes de reportar um Sharpe. Sem exceção. Arquivamento é o resultado padrão, não o fracasso.",
    "methodology.graveyard.title": "O cemitério é",
    "methodology.graveyard.titleEm": "metodologia.",
    "methodology.graveyard.body":
      "engines desenvolvidas, testadas fora da amostra e arquivadas. Disciplina exige matar. As engines que restam sobrevivem porque as que falharam não foram mantidas.",

    // Section heads — Performance
    "performance.eyebrow": "§ IV",
    "performance.titlePre": "Performance,",
    "performance.titleEm": "out-of-sample.",
    "performance.sub":
      "Todas as métricas abaixo são walk-forward em janelas anteriores a qualquer calibração. Reportadas ao lado dos claims in-sample quando relevante. Os números caem do jeito honesto.",
    "performance.table.heading": "Resumo OOS por engine",
    "performance.table.stamp": "Janela: 2022-01-01 → 2023-01-01 (360d BEAR)",
    "performance.table.foot":
      "Todas as métricas líquidas de slippage, spread, commission e funding. Sizing sob Kelly × convex × drawdown-scale × Ω-risk com cap de notional agregado no nível do portfolio.",

    // Section heads — CodeShowcase
    "code.eyebrow": "§ V",
    "code.titlePre": "Alquimia legível —",
    "code.titleEm": "uma função, uma missão.",
    "code.sub":
      "A plataforma é escrita pra ser auditada linha por linha. Sinal, risco e sizing vivem cada um em uma função pura. Sem estado oculto, sem side-effects globais, sem ternário mágico.",

    // Section heads — Technology
    "technology.eyebrow": "§ VI",
    "technology.titlePre": "Nove engines. Um",
    "technology.titleEm": "orquestrador.",
    "technology.sub":
      "Cada engine carrega uma inspiração institucional, um mecanismo único e um veredito OOS próprio. MILLENNIUM aloca capital entre as sobreviventes sob restrições de correlação e drawdown.",
    "technology.pipeline.title": "Pipeline de sinal",
    "technology.pipeline.body":
      "Determinístico, observável em cada passo, replayable a partir do disco.",

    // Section heads — Principles
    "principles.eyebrow": "§ VII",
    "principles.titlePre": "Sete princípios",
    "principles.titleEm": "operacionais.",
    "principles.sub":
      "Os mandamentos contra os quais o próprio código é escrito. Cada um é um discriminador — uma condição que a plataforma precisa satisfazer antes de qualquer capital se mover.",

    // Section heads — Research
    "research.eyebrow": "§ VIII",
    "research.titlePre": "Notas de",
    "research.titleEm": "research.",
    "research.sub":
      "Research interna selecionada publicada pra partners. O arquivo completo — postmortems de engine, logs de audit, revisões de metodologia — está disponível sob NDA.",
    "research.requestFull": "Solicitar nota completa →",

    // Section heads — Contact
    "contact.eyebrow": "§ IX",
    "contact.titlePre": "Acesso por convite. Capacidade",
    "contact.titleEm": "limitada.",
    "contact.sub":
      "AURUM aloca sob restrição de capacidade de estratégia, não de demanda. Entre em contato pra acesso à research ou pra discutir alocação sob NDA.",
    "contact.form.nameLabel": "Nome",
    "contact.form.emailLabel": "Email",
    "contact.form.orgLabel": "Organização",
    "contact.form.noteLabel": "Contexto",
    "contact.form.namePh": "Jane Investor",
    "contact.form.emailPh": "jane@family-office.com",
    "contact.form.orgPh": "Opcional",
    "contact.form.notePh":
      "O que gostaria de discutir — notas de research, cronograma de alocação, due-diligence técnico?",
    "contact.form.send": "Enviar solicitação",
    "contact.form.sent": "Cliente de e-mail aberto",
    "contact.form.or": "Ou escreva direto pra",

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
