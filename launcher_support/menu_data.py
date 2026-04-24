from __future__ import annotations


MAIN_MENU = [
    ("MARKETS", "markets", "Seleccionar mercado activo"),
    ("CONNECTIONS", "connections", "Contas & exchanges"),
    ("TERMINAL", "terminal", "Charts, macro, research"),
    ("DATA", "data", "Backtests · engine logs · reports"),
    ("STRATEGIES", "strategies", "Backtest & live engines"),
    ("ARBITRAGE", "alchemy", "CEX·CEX execution + DEX·DEX / CEX·DEX scanner"),
    ("MACRO BRAIN", "macro_brain", "Autonomous CIO · regime → thesis → paper positions"),
    ("RISK", "risk", "Portfolio & risk console"),
    ("COMMAND CENTER", "command", "Site, servers, admin panel"),
    ("SETTINGS", "settings", "Config, keys, Telegram"),
]


def markets_children(markets: dict) -> list[tuple[str, str]]:
    out = []
    for market_key in markets:
        out.append((markets[market_key]["label"], f"_market_{market_key}"))
    return out


def main_groups(markets: dict, tile_markets: str, tile_execute: str, tile_research: str, tile_control: str):
    return [
        ("MARKETS", "1", tile_markets, markets_children(markets)),
        ("EXECUTE", "2", tile_execute, [
            ("BACKTEST", "_strategies_backtest"),
            ("ENGINES LIVE", "_strategies_live"),
            ("ARBITRAGE", "_arbitrage_hub"),
            ("RISK", "_risk_menu"),
        ]),
        ("RESEARCH", "3", tile_research, [
            ("TERMINAL", "_terminal"),
            ("DATA", "_data_center"),
            ("MACRO BRAIN", "_macro_brain_menu"),
            ("RESEARCH DESK", "_research_desk"),
        ]),
        ("CONTROL", "4", tile_control, [
            ("CONNECTIONS", "_connections"),
            ("COMMAND", "_command_center"),
            ("SETTINGS", "_config"),
        ]),
    ]


BLOCK_DESCRIPTIONS = {
    "_markets": "quotes, universe e mercado ativo",
    "_crypto_dashboard": "snapshot visual do cripto book",
    "_market_crypto_futures": "Binance · Bybit · OKX · Hyperliquid · Gate",
    "_market_crypto_spot": "Binance · Coinbase · Kraken (em breve)",
    "_market_forex": "Forex / CFDs via MetaTrader 5 (em breve)",
    "_market_equities": "Equities via IB / Alpaca (em breve)",
    "_market_commodities": "Gold · Oil · Nat Gas (em breve)",
    "_market_indices": "S&P · NASDAQ · DXY (em breve)",
    "_market_onchain": "DeFi · DEX data · on-chain (em breve)",
    "_strategies": "engines · backtest · live",
    "_strategies_backtest": "engines históricas · walkforward · MC",
    "_strategies_live": "engines ao vivo · demo · testnet",
    "_arbitrage_hub": "cex/cex, dex/dex e cex/dex routes",
    "_macro_brain_menu": "cio autonomo, regime e thesis",
    "_risk_menu": "portfolio, limites e kill-switch",
    "_terminal": "charts, macro e research terminal",
    "_data_center": "backtests, logs e reports",
    "_research_desk": "mesa ai: scryer, arbiter, artifex, curator",
    "_connections": "exchanges, contas e credenciais",
    "_command_center": "site, servers e operacao",
    "_config": "settings, keys e telegram",
}


COMMAND_ROADMAPS = {
    "DEPLOY": [
        "Git push (origin/main, tags)",
        "Vercel / Netlify deploy hooks",
        "Docker build + registry push",
        "VPS rsync + systemctl restart",
    ],
    "SERVERS": [
        "VPS list (Hetzner / Vultr / Linode)",
        "Inline SSH terminal",
        "Status monitor (uptime, load, disk)",
        "Tail journalctl / nginx logs",
    ],
    "DATABASES": [
        "SQLite browser (read-only schema + query)",
        "PostgreSQL connect via DSN",
        "Backup / restore snapshots",
        "Migration runner",
    ],
    "SERVICES": [
        "systemd unit list + start/stop",
        "PM2 process tree",
        "Docker containers (ps / logs / restart)",
        "Cron / scheduled tasks viewer",
    ],
    "SYSTEM": [
        "CPU / RAM / disk via psutil",
        "Network interfaces & throughput",
        "Uptime + load average",
        "Top processes",
    ],
}
