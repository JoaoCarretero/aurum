from __future__ import annotations

from config.engines import SCRIPT_TO_KEY
from launcher_support.bootstrap import canonical_engine_key


PROC_BY_KEY = {
    "citadel": "backtest",
    "jump": "mercurio",
    "bridgewater": "thoth",
    "deshaw": "newton",
    "millennium": "multi",
    "twosigma": "prometeu",
    "renaissance": "renaissance",
}


def script_to_proc_key(script: str) -> str | None:
    canon_key = canonical_engine_key(SCRIPT_TO_KEY.get(script.replace("\\", "/"), ""))
    return PROC_BY_KEY.get(canon_key)


def strategies_progress_target(clean: str) -> tuple[float, str]:
    low = (clean or "").strip().lower()
    if not low:
        return 0.0, ""
    targets = [
        (("iniciado", "started"), 10.0, "allocating launch package"),
        (("dados", "fetch", "loading"), 24.0, "downloading candle archives"),
        (("sentiment", "funding", "open interest", "long/short"), 40.0, "installing sentiment bundles"),
        (("scan", "scanning"), 58.0, "building route graph and trade cache"),
        (("total:", "resultados", "wr=", "pnl="), 74.0, "compiling execution manifests"),
        (("metricas", "metrics", "sharpe", "sortino"), 86.0, "verifying institutional metrics"),
        (("monte", "walk", "robust", "json"), 94.0, "packing report artifacts"),
        (("backtest complete", "loading results dashboard"), 100.0, "installation complete"),
    ]
    for keys, pct, stage in targets:
        if any(k in low for k in keys):
            return pct, stage
    return 0.0, low[:180]


def is_janestreet_script(script: str) -> bool:
    script_l = (script or "").replace("\\", "/").lower()
    return script_l.endswith("/janestreet.py") or "janestreet" in script_l


def live_launch_plan(script: str, mode_preset: str, cfg: dict | None) -> dict:
    if is_janestreet_script(script):
        arb_mode_map = {"paper": "2", "demo": "3", "live": "4", "testnet": "2"}
        return {
            "script": script,
            "stdin_inputs": [arb_mode_map.get(mode_preset, "1")],
            "cli_args": [],
            "uses_dedicated_runner": True,
        }

    cli_args: list[str] = [mode_preset]
    try:
        lev = float(str((cfg or {}).get("leverage", "")).replace("x", "").strip())
        if 0.1 <= lev <= 125:
            cli_args += ["--leverage", str(lev)]
    except (ValueError, TypeError):
        pass
    return {
        "script": "engines/live.py",
        "stdin_inputs": [],
        "cli_args": cli_args,
        "uses_dedicated_runner": False,
    }
