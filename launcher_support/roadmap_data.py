"""Roadmap dataset — capabilities the cockpit aspires to deliver.

Single source of truth for the ROADMAP screen and for "COMING SOON"
listings inside placeholder screens (RISK console, TERMINAL, etc).

Item shape:
    {
        "id":         stable slug (used for navigation / detail lookup)
        "name":       short display title (~25 chars)
        "sigil":      single glyph (Bloomberg-aesthetic)
        "tier":       1 = institutional table-stakes
                      2 = differentiator
                      3 = cutting-edge / nice-to-have
        "area":       RISK / EXEC / RESEARCH / DATA / OPS / MACRO /
                      COMPLIANCE / REPORT / UX / DEFI / AI
        "status":     PLANNED / SCAFFOLDED / IN_PROGRESS / DONE
        "summary":    one-line description (~70 chars max)
        "detail":     2-4 sentence paragraph with concrete plan
        "reference":  which fund/platform delivers it (label only)
    }

Status semantics:
- PLANNED      = not started, only listed
- SCAFFOLDED   = stub/placeholder code present (e.g. risk_gates)
- IN_PROGRESS  = active work in current/recent sessions
- DONE         = shipped (kept for visibility; counted in "done %")

Curated subset of ~36 items — covers the gap analysis without inflating
the screen. Update here when shipping or descoping.
"""
from __future__ import annotations

from typing import Any


ROADMAP: list[dict[str, Any]] = [
    # =========================================================
    # TIER 1 — institutional table-stakes (fund readiness)
    # =========================================================
    {
        "id": "tca_pretrade",
        "name": "TCA Pre-Trade",
        "sigil": "▲",
        "tier": 1,
        "area": "EXEC",
        "status": "PLANNED",
        "summary": "Slippage / impact / funding cost preview before sending order",
        "detail": (
            "Before any live engine fires, render expected slippage, "
            "market impact, spread paid and funding cost over hold "
            "horizon. Compute from current depth + recent volatility + "
            "engine size. Block dispatch if cost > expected edge."
        ),
        "reference": "Talos · FalconX 360 · CoinRoutes",
    },
    {
        "id": "var_engine",
        "name": "VaR Engine",
        "sigil": "Σ",
        "tier": 1,
        "area": "RISK",
        "status": "PLANNED",
        "summary": "Parametric / historical / Monte Carlo VaR per strategy + portfolio",
        "detail": (
            "Daily and rolling VaR (1d, 5d, 30d horizons). Three "
            "methods: parametric (variance-covariance), historical "
            "simulation, and Monte Carlo. Output exposed in RISK "
            "console with confidence intervals."
        ),
        "reference": "Talos PMS · Two Sigma Venn · Membrane Labs",
    },
    {
        "id": "stress_scenarios",
        "name": "Stress Test Scenarios",
        "sigil": "⚡",
        "tier": 1,
        "area": "RISK",
        "status": "PLANNED",
        "summary": "Named shock scenarios (BTC -30%, funding crash, exchange outage)",
        "detail": (
            "Library of pre-defined shocks: market crash, "
            "alt-correlation spike, liquidity crisis, exchange "
            "outage, stablecoin depeg. Each produces projected P&L "
            "by strategy. Custom shock builder for ad-hoc tests."
        ),
        "reference": "Talos · BarraOne · Amberdata",
    },
    {
        "id": "recon_3way",
        "name": "3-Way Reconciliation",
        "sigil": "≡",
        "tier": 1,
        "area": "COMPLIANCE",
        "status": "PLANNED",
        "summary": "Internal book vs exchange API vs on-chain — break detection",
        "detail": (
            "Compare internal positions, exchange-reported positions "
            "and on-chain wallet balances daily T+0/T+1. Flag breaks "
            "(qty mismatch, missing leg, late fill, fee mismatch) "
            "with workflow: detect → categorize → resolve → close."
        ),
        "reference": "TRES Finance · Cryptoworth · Octav PRO",
    },
    {
        "id": "dsr_haircut",
        "name": "Deflated Sharpe Ratio",
        "sigil": "∇",
        "tier": 1,
        "area": "RESEARCH",
        "status": "PLANNED",
        "summary": "Anti-overfit haircut by n_trials on every backtest report",
        "detail": (
            "Compute DSR = Sharpe haircut by number of trials. Show "
            "alongside raw Sharpe in every backtest report and on "
            "the strategies dashboard. Reject promotion to live if "
            "DSR < 1.0 even when raw Sharpe looks great."
        ),
        "reference": "Lopez de Prado · VectorBT PRO",
    },
    {
        "id": "lp_daily_pnl",
        "name": "LP Daily P&L Statement",
        "sigil": "▦",
        "tier": 1,
        "area": "REPORT",
        "status": "PLANNED",
        "summary": "T+1 NAV + attribution by strategy, ready for LP delivery",
        "detail": (
            "Auto-generated PDF/HTML report with NAV trend, daily "
            "P&L, attribution by strategy, top winners/losers, "
            "exposure snapshot. Delivered 06:30 ET T+1. Foundation "
            "for monthly LP letter and quarterly tearsheet."
        ),
        "reference": "1token · HedgeGuard · institutional standard",
    },
    {
        "id": "promotion_gates",
        "name": "Promotion Gates",
        "sigil": "↑",
        "tier": 1,
        "area": "RESEARCH",
        "status": "PLANNED",
        "summary": "Formal criteria to advance research → paper → live",
        "detail": (
            "Hard gates between lifecycle stages: DSR > 1.0, OOS "
            "Sharpe > 1.5, MC pct_pos > 80%, max DD < 25%. Engine "
            "cannot enter next stage until all gates pass. UI shows "
            "which gates each candidate has cleared."
        ),
        "reference": "QuantConnect Lean · LEAN CLI · Jesse",
    },
    {
        "id": "champion_challenger",
        "name": "Champion / Challenger",
        "sigil": "⚔",
        "tier": 1,
        "area": "RESEARCH",
        "status": "PLANNED",
        "summary": "Run v2 in paper while v1 is live, compare and promote",
        "detail": (
            "When tuning live engine, new version runs in paper mode "
            "alongside the production version on same universe. UI "
            "shows side-by-side performance. Promote challenger only "
            "when it beats champion over min observation window."
        ),
        "reference": "AB testing standard · Numerai · LEAN",
    },
    {
        "id": "audit_export",
        "name": "MiCA Audit Export",
        "sigil": "⎙",
        "tier": 1,
        "area": "COMPLIANCE",
        "status": "SCAFFOLDED",
        "summary": "ESMA-compliant order log export — audit_trail JSONL → schema",
        "detail": (
            "audit_trail.py already writes hash-chained JSONL. Need "
            "exporter that maps to ESMA MiCA schema (ISO-8601 ts, "
            "venue MIC, instrument ISIN/ID, event types) and emits "
            "monthly CSV/JSON for regulators or auditors."
        ),
        "reference": "ESMA MiCA · audit_trail.py existing",
    },

    # =========================================================
    # TIER 2 — differentiators (sets us apart from retail)
    # =========================================================
    {
        "id": "algo_orders",
        "name": "TWAP / VWAP / POV Algos",
        "sigil": "≋",
        "tier": 2,
        "area": "EXEC",
        "status": "PLANNED",
        "summary": "Parent / child orders with execution algorithms",
        "detail": (
            "Add TWAP, VWAP, POV (Percentage of Volume), Iceberg, "
            "Implementation Shortfall as parent order types. Engine "
            "fills with child orders over time, working orders "
            "blotter shows progress and slippage in real time."
        ),
        "reference": "Coinbase Prime · Talos · TT Algo Suite",
    },
    {
        "id": "smart_router",
        "name": "Smart Order Router",
        "sigil": "↳",
        "tier": 2,
        "area": "EXEC",
        "status": "PLANNED",
        "summary": "Multi-venue split routing to minimize slippage",
        "detail": (
            "When order > available depth at best venue, split fills "
            "across N venues to minimize total slippage. Score venues "
            "by depth, fee, latency, reputation. Foundation for true "
            "best-execution evidence."
        ),
        "reference": "CoinRoutes (patented) · Caspian · FalconX",
    },
    {
        "id": "tca_inflight",
        "name": "In-Flight TCA",
        "sigil": "⊿",
        "tier": 2,
        "area": "EXEC",
        "status": "PLANNED",
        "summary": "Tick-by-tick slippage vs benchmark while order works",
        "detail": (
            "While parent order is working, render live arrival-price "
            "and VWAP benchmarks vs realized fills. Operator can "
            "abort or adjust if slippage exceeds threshold mid-flight."
        ),
        "reference": "Talos · TT · Charles River",
    },
    {
        "id": "factor_lens",
        "name": "Factor Lens",
        "sigil": "◈",
        "tier": 2,
        "area": "RESEARCH",
        "status": "PLANNED",
        "summary": "Decompose returns into orthogonal risk factors",
        "detail": (
            "Two Sigma Venn-style 18-factor decomposition adapted to "
            "crypto: BTC beta, alt beta, funding carry, basis carry, "
            "vol risk premium, on-chain flow, regime. Shows what "
            "drives portfolio returns vs what is idiosyncratic alpha."
        ),
        "reference": "Two Sigma Venn · BarraOne",
    },
    {
        "id": "pnl_attribution",
        "name": "P&L Attribution",
        "sigil": "▥",
        "tier": 2,
        "area": "REPORT",
        "status": "PLANNED",
        "summary": "Decompose P&L by strategy / symbol / regime / time-of-day",
        "detail": (
            "Slice realized P&L by strategy, symbol, regime, "
            "time-of-day, venue. Surfaces hidden patterns (e.g. "
            "engine X loses money during NY hours but wins overnight). "
            "Critical for tuning and capacity decisions."
        ),
        "reference": "Talos PMS · institutional standard",
    },
    {
        "id": "capacity_estimation",
        "name": "Capacity Estimation",
        "sigil": "⊞",
        "tier": 2,
        "area": "RESEARCH",
        "status": "PLANNED",
        "summary": "Maximum AUM before market impact erodes edge",
        "detail": (
            "For each engine, simulate ramping size and measure where "
            "expected slippage starts eating projected edge. Output "
            "soft cap (warning) and hard cap (block) per engine. "
            "Required input for fund-level allocation decisions."
        ),
        "reference": "institutional capacity modeling",
    },
    {
        "id": "ablation_studies",
        "name": "Ablation Studies",
        "sigil": "✂",
        "tier": 2,
        "area": "RESEARCH",
        "status": "PLANNED",
        "summary": "Drop-feature / drop-rule and measure delta",
        "detail": (
            "For each engine, systematically disable one signal "
            "component (omega, regime filter, chop check, etc.) and "
            "rerun OOS. Surfaces which components actually carry "
            "edge vs which are placebo. Anti-overfit weapon."
        ),
        "reference": "Lopez de Prado · ML standard",
    },
    {
        "id": "param_sweep_heatmap",
        "name": "Param Sweep Heatmap",
        "sigil": "▩",
        "tier": 2,
        "area": "RESEARCH",
        "status": "PLANNED",
        "summary": "Sensitivity heatmap (Sharpe surface over param grid)",
        "detail": (
            "Full grid over 2 key params, render Sharpe surface as "
            "heatmap. Visualizes whether the chosen tuning sits in a "
            "wide plateau (robust) or a sharp peak (overfit). Numba "
            "or multicore execution; 1k cells in seconds."
        ),
        "reference": "VectorBT PRO · Optuna integration",
    },
    {
        "id": "hyperopt_bayesian",
        "name": "Bayesian Hyperopt",
        "sigil": "∫",
        "tier": 2,
        "area": "RESEARCH",
        "status": "PLANNED",
        "summary": "Optuna / TPE-driven parameter search instead of grid",
        "detail": (
            "Replace manual grid with Bayesian / Tree-structured "
            "Parzen Estimator (TPE) optimization. Converges faster, "
            "explores high-dim spaces. Always paired with DSR + "
            "walk-forward to avoid overfitting the optimizer itself."
        ),
        "reference": "Optuna · Freqtrade Hyperopt",
    },
    {
        "id": "news_sentiment",
        "name": "News Sentiment Signal",
        "sigil": "✎",
        "tier": 2,
        "area": "MACRO",
        "status": "PLANNED",
        "summary": "LLM-classified news → tradable feature for engines",
        "detail": (
            "Pipeline: ingest crypto + macro news (NewsAPI, GDELT, "
            "RSS) → LLM classification (sentiment, NER, event type) "
            "→ time-bucketed feature stream. Macro brain consumes; "
            "engines can subscribe via params.NEWS_FEATURE_KEYS."
        ),
        "reference": "BloombergGPT · Bloomberg Terminal",
    },
    {
        "id": "regime_visualization",
        "name": "Regime Console",
        "sigil": "◐",
        "tier": 2,
        "area": "MACRO",
        "status": "SCAFFOLDED",
        "summary": "HMM regime + GARCH vol + Hurst exposed in UI",
        "detail": (
            "core/chronos.py and macro_brain already compute regime "
            "states, GARCH volatility forecasts and Hurst exponent. "
            "Need a screen that surfaces them with transition probs, "
            "vol cones and rolling Hurst. Currently lives in logs only."
        ),
        "reference": "macro_brain.scoring · core/chronos.py",
    },
    {
        "id": "options_chain",
        "name": "Options Chain + IV Surface",
        "sigil": "◊",
        "tier": 2,
        "area": "DATA",
        "status": "PLANNED",
        "summary": "Deribit chain, IV surface, skew, term structure",
        "detail": (
            "Pull Deribit (and others) options chain, render IV "
            "surface in 3D (strike × tenor × IV), term-structure "
            "and skew curves. Foundation for any vol-trading or "
            "tail-hedging strategy."
        ),
        "reference": "SignalPlus · Paradigm · Deribit",
    },
    {
        "id": "live_arb_inprocess",
        "name": "Live Arb In-Process",
        "sigil": "⇆",
        "tier": 2,
        "area": "EXEC",
        "status": "IN_PROGRESS",
        "summary": "Replace janestreet subprocess fallback with in-process router",
        "detail": (
            "SimpleArbEngine paper mode runs in-process. Live mode "
            "currently shells out to janestreet subprocess. Migrate "
            "live execution to live.py router (same path as engines) "
            "for unified audit / kill-switch / heartbeat."
        ),
        "reference": "internal — engines/live.py router",
    },

    # =========================================================
    # TIER 3 — cutting-edge / nice-to-have
    # =========================================================
    {
        "id": "llm_copilot",
        "name": "LLM Copilot",
        "sigil": "◉",
        "tier": 3,
        "area": "AI",
        "status": "PLANNED",
        "summary": "NL → query, explain trade, suggest hedge, analyze drawdown",
        "detail": (
            "Cockpit-embedded copilot. Operator types 'why did "
            "CITADEL drawdown last week' and gets attribution + "
            "explanation. Or 'hedge this 5 BTC long' and gets a "
            "structured proposal. Anchored to read-only audit data."
        ),
        "reference": "BloombergGPT · Anthropic Claude",
    },
    {
        "id": "replay_mode",
        "name": "Replay Mode",
        "sigil": "↺",
        "tier": 3,
        "area": "RESEARCH",
        "status": "PLANNED",
        "summary": "Rewind orderbook + execution for post-mortem analysis",
        "detail": (
            "After a bad fill or regime miss, scrub a slider to "
            "replay the orderbook, signals, decisions and fills as "
            "they happened. Identify what the engine saw vs what was "
            "actually there. Powerful debugging and education tool."
        ),
        "reference": "Talos · TT post-trade",
    },
    {
        "id": "alert_builder",
        "name": "Visual Alert Builder",
        "sigil": "◮",
        "tier": 3,
        "area": "UX",
        "status": "PLANNED",
        "summary": "Drag-drop condition tree → multi-channel alerts",
        "detail": (
            "Compose alert conditions visually: AND/OR tree over "
            "price, indicator, P&L, exposure thresholds. Route to "
            "Telegram / Slack / email / webhook with severity tiers "
            "and snooze. Today alerts are hardcoded in engine code."
        ),
        "reference": "TradingView · Cryptocurrency Alerting",
    },
    {
        "id": "mev_protection",
        "name": "MEV Protection",
        "sigil": "⛨",
        "tier": 3,
        "area": "DEFI",
        "status": "PLANNED",
        "summary": "Flashbots Protect RPC for any DEX trade",
        "detail": (
            "Route DEX swaps through Flashbots Protect (or similar "
            "private mempool). Avoid sandwich attacks and MEV "
            "extraction. Required before any meaningful on-chain "
            "execution volume."
        ),
        "reference": "Flashbots Protect · 80% of ETH txs",
    },
    {
        "id": "defi_yield",
        "name": "DeFi Yield Engines",
        "sigil": "◍",
        "tier": 3,
        "area": "DEFI",
        "status": "PLANNED",
        "summary": "Pendle PT/YT, Aave loops, Hyperliquid carry",
        "detail": (
            "Cockpit-modeled yield strategies: Pendle principal/yield "
            "tokens, Aave looped lending, Hyperliquid funding carry "
            "with delta-neutral hedge. Risk page shows liquidation "
            "distance, peg risk, and effective APR net of gas."
        ),
        "reference": "Pendle · Aave · Hyperliquid",
    },
    {
        "id": "onchain_fundamentals",
        "name": "On-Chain Fundamentals",
        "sigil": "⛓",
        "tier": 3,
        "area": "DATA",
        "status": "PLANNED",
        "summary": "TVL, fees, holders, whale flows, governance signals",
        "detail": (
            "Per-token fundamental dashboard: TVL, fees, holders, "
            "whale movements, governance vote outcomes, unlock "
            "schedule. Feeds engines as features and operators as "
            "macro context. Pulls from DefiLlama, Nansen, Artemis."
        ),
        "reference": "Nansen · Artemis · DefiLlama",
    },
    {
        "id": "cross_margin",
        "name": "Cross-Margin Engine",
        "sigil": "⊕",
        "tier": 3,
        "area": "RISK",
        "status": "PLANNED",
        "summary": "Net spot + perp + options + OTC margin in one pool",
        "detail": (
            "Aggregate IM/MM requirements across spot, perpetuals, "
            "options and OTC forwards into single margin pool. "
            "Massive capital efficiency gain; standard at prime "
            "brokers like Hidden Road and FalconX."
        ),
        "reference": "Hidden Road · FalconX 360",
    },
    {
        "id": "rbac_2fa",
        "name": "RBAC + 2FA / SSO",
        "sigil": "⚿",
        "tier": 3,
        "area": "COMPLIANCE",
        "status": "PLANNED",
        "summary": "Roles (trader / risk / compliance / admin) + auth",
        "detail": (
            "Multi-user with role-based access control: trader, PM, "
            "risk officer, compliance, ops, read-only. Per-resource "
            "ACL on strategies and accounts. 2FA mandatory; SSO/SAML "
            "for institutional deployments."
        ),
        "reference": "Talos · Charles River · institutional",
    },
    {
        "id": "investor_portal",
        "name": "Investor Portal",
        "sigil": "▤",
        "tier": 3,
        "area": "REPORT",
        "status": "PLANNED",
        "summary": "Read-only LP-facing dashboard (NAV, attribution, exposure)",
        "detail": (
            "Web portal for limited partners: NAV trend, "
            "performance vs benchmark, factor attribution, exposure "
            "snapshot, quarterly tearsheet. No trading surface, "
            "audit-logged access, scoped credentials."
        ),
        "reference": "Talos LP portal · 1token",
    },
    {
        "id": "command_palette",
        "name": "Command Palette",
        "sigil": "⌘",
        "tier": 3,
        "area": "UX",
        "status": "PLANNED",
        "summary": "Bloomberg-style mnemonic ':CITADEL <GO>'",
        "detail": (
            "Press : (or Ctrl+K) anywhere to open command bar. Type "
            "engine / screen / command alias and hit Enter. Operator "
            "navigates 39 screens without mouse. Power-user shortcut "
            "into every cockpit surface."
        ),
        "reference": "Bloomberg Terminal · Linear · Notion",
    },
    {
        "id": "tax_reports",
        "name": "Tax Reports",
        "sigil": "₪",
        "tier": 3,
        "area": "REPORT",
        "status": "PLANNED",
        "summary": "FIFO / LIFO / HIFO / Spec ID + DeFi-specific events",
        "detail": (
            "Cost-basis methods per jurisdiction. Track lots with "
            "acquisition + disposal cost. Handle DeFi specifics: "
            "impermanent loss, staking rewards, airdrops, hard "
            "forks, hard-to-categorize wallet movements."
        ),
        "reference": "CoinLedger · TRES Finance",
    },
    {
        "id": "break_workflow",
        "name": "Break Workflow",
        "sigil": "⊗",
        "tier": 3,
        "area": "COMPLIANCE",
        "status": "PLANNED",
        "summary": "Categorize → assign → resolve reconciliation breaks",
        "detail": (
            "When 3-way recon flags a break, ticket lifecycle: "
            "categorize (qty / price / missing / late / fee), "
            "assign owner, set SLA, track to close. Fuzzy AI "
            "matching reduces false positives."
        ),
        "reference": "TRES Finance · Cryptio",
    },
    {
        "id": "notebook_inline",
        "name": "Notebook Integration",
        "sigil": "▭",
        "tier": 3,
        "area": "RESEARCH",
        "status": "PLANNED",
        "summary": "Jupyter inline for ad-hoc research from cockpit data",
        "detail": (
            "Embed Jupyter (or Marimo) notebook with read-only "
            "access to cockpit data: runs, trades, signals, "
            "market data. Operator prototypes a hypothesis without "
            "leaving the desk; promotes to engine when ready."
        ),
        "reference": "QuantConnect Research · Hummingbot Dashboard",
    },
    {
        "id": "watchlist_sparklines",
        "name": "Watchlist with Sparklines",
        "sigil": "≣",
        "tier": 3,
        "area": "UX",
        "status": "PLANNED",
        "summary": "Compact symbol grid with inline mini charts and quotes",
        "detail": (
            "Configurable symbol watchlists with inline sparkline, "
            "last price, 24h change, funding, OI delta. Multiple "
            "lists (e.g. CITADEL universe, JUMP universe, "
            "macro pairs). Hot-key promote to chart."
        ),
        "reference": "Bloomberg WATCH · TradingView",
    },
    {
        "id": "research_desk_phase2",
        "name": "Research Desk Sprint 2",
        "sigil": "◎",
        "tier": 3,
        "area": "RESEARCH",
        "status": "IN_PROGRESS",
        "summary": "Paperclip live integration, sigils, log streaming, persona editor",
        "detail": (
            "Sprint 1 shipped scaffolding (cards, polling, ticket "
            "form). Sprint 2: live Paperclip server integration, "
            "generative SVG sigils per agent, real-time log stream "
            "for in-flight runs, AGENTS.md persona editor."
        ),
        "reference": "internal — research_desk roadmap",
    },
]


# Convenience helpers ----------------------------------------------------

def by_tier(tier: int) -> list[dict[str, Any]]:
    """Return roadmap items in given tier (1, 2 or 3), preserving order."""
    return [item for item in ROADMAP if item.get("tier") == tier]


def by_area(area: str) -> list[dict[str, Any]]:
    """Return roadmap items for a given functional area."""
    return [item for item in ROADMAP if item.get("area") == area.upper()]


def by_status(status: str) -> list[dict[str, Any]]:
    """Return roadmap items with a given status."""
    return [item for item in ROADMAP if item.get("status") == status.upper()]


def counters() -> dict[str, int]:
    """Aggregate counts: per tier, per status, total."""
    out: dict[str, int] = {
        "total": len(ROADMAP),
        "tier1": len(by_tier(1)),
        "tier2": len(by_tier(2)),
        "tier3": len(by_tier(3)),
        "planned": len(by_status("PLANNED")),
        "scaffolded": len(by_status("SCAFFOLDED")),
        "in_progress": len(by_status("IN_PROGRESS")),
        "done": len(by_status("DONE")),
    }
    return out


def status_color_key(status: str) -> str:
    """Map status to semantic color name (consumed by UI palette).

    Returns one of: 'amber' (planned), 'cyan' (scaffolded),
    'green' (done), 'amber_b' (in_progress).
    """
    mapping = {
        "PLANNED":     "amber",
        "SCAFFOLDED":  "cyan",
        "IN_PROGRESS": "amber_b",
        "DONE":        "green",
    }
    return mapping.get(status.upper(), "dim")
