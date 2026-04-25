"""Contract tests for engines/citadel.py (CITADEL — systematic momentum).

CITADEL is the flagship live engine (EDGE_DE_REGIME per MEMORY §4).
Audit 2026-04-25 Lane 4 finding: only 1 contract test existed (logging
plumbing). These additions pin the behaviors that, if silently broken,
would cause CITADEL to load, run, and emit "successful" runs whose
trade signals or risk parameters were wrong.

Heavy paths (scan_symbol, run_backtest) require OHLCV cache + macro
state — left to integration tests. Smoke contracts only here.
"""
from __future__ import annotations

import inspect
import logging
from pathlib import Path


def test_setup_run_replaces_handlers_between_runs(tmp_path, monkeypatch):
    import engines.citadel as citadel

    run_dirs = [tmp_path / "run_a", tmp_path / "run_b"]
    for d in run_dirs:
        d.mkdir(parents=True)

    created = []

    def _fake_create_run_dir(engine_name: str):
        idx = len(created)
        created.append(engine_name)
        return f"{engine_name}_{idx}", run_dirs[idx]

    monkeypatch.setattr("core.run_manager.create_run_dir", _fake_create_run_dir)

    root = logging.getLogger()
    old_root_handlers = list(root.handlers)
    old_trade_handlers = list(citadel._tl.handlers)
    old_validation_handlers = list(citadel._vl.handlers)
    try:
        citadel.setup_run("citadel")
        first_trade_path = Path(citadel._tl.handlers[0].baseFilename)
        first_validation_path = Path(citadel._vl.handlers[0].baseFilename)

        citadel.setup_run("citadel")
        second_trade_path = Path(citadel._tl.handlers[0].baseFilename)
        second_validation_path = Path(citadel._vl.handlers[0].baseFilename)

        assert second_trade_path.parent == run_dirs[1]
        assert second_validation_path.parent == run_dirs[1]
        assert first_trade_path != second_trade_path
        assert first_validation_path != second_validation_path
        assert len(citadel._tl.handlers) == 1
        assert len(citadel._vl.handlers) == 1
    finally:
        for handler in list(root.handlers):
            try:
                handler.close()
            except Exception:
                pass
        root.handlers[:] = old_root_handlers
        citadel._tl.handlers[:] = old_trade_handlers
        citadel._vl.handlers[:] = old_validation_handlers


# ────────────────────────────────────────────────────────────
# Module-level invariants
# Audit 2026-04-25 Lane 4 backfill — CITADEL had only 1 test.
# ────────────────────────────────────────────────────────────


def test_module_imports_and_exports_public_api():
    """CITADEL imports cleanly and exposes documented entry points.

    Cenário protegido: a refactor `from core.signals import ...` em
    citadel.py:36-40 quebra silenciosamente se signals dropar uma
    função (decide_direction, calc_levels, label_trade) — Python
    levanta ImportError no import-time, mas só visível em runtime se
    ninguém roda smoke. Pin garante que CI captura.
    """
    import engines.citadel as citadel

    assert callable(getattr(citadel, "scan_symbol", None)), \
        "scan_symbol removed — CITADEL signal pipeline broken"
    assert callable(getattr(citadel, "setup_run", None)), \
        "setup_run removed — engine cannot initialize"


def test_interval_calibrated_from_engine_intervals():
    """CITADEL.INTERVAL is overridden from ENGINE_INTERVALS dict.

    Cenário protegido: a longrun battery 2026-04-14 confirmou 15m default
    como sweet spot pra CITADEL. Reverter pra global INTERVAL silently
    degrada a edge — engine continua rodando, mas o regime classifier
    e o omega scoring miram a TF errada.
    """
    import engines.citadel as citadel
    from config.params import ENGINE_INTERVALS

    expected = ENGINE_INTERVALS.get("CITADEL")
    assert expected is not None, \
        "ENGINE_INTERVALS.CITADEL missing — calibration unpinned"
    assert citadel.INTERVAL == expected, (
        f"citadel.INTERVAL={citadel.INTERVAL} ≠ "
        f"ENGINE_INTERVALS.CITADEL={expected} — calibration drift"
    )


def test_run_globals_have_defaults_before_setup_run(monkeypatch):
    """RUN_ID/RUN_DIR have safe defaults before setup_run() is called.

    Cenário protegido: caller que importa citadel e lê RUN_DIR sem antes
    chamar setup_run() não deve ver None ou raise. Path('.') é o
    contrato — testa-se que RUN_DIR é pelo menos um Path-like.
    """
    import engines.citadel as citadel

    # Don't actually call setup_run in this test — pin the pre-init state.
    # If a previous test left state, that's fine for this assertion;
    # we just verify the types exist and are usable.
    assert isinstance(citadel.RUN_DIR, Path), \
        f"RUN_DIR type drift: {type(citadel.RUN_DIR).__name__}"
    assert isinstance(citadel.RUN_ID, str), \
        f"RUN_ID type drift: {type(citadel.RUN_ID).__name__}"
    assert isinstance(citadel.RUN_DATE, str)
    assert isinstance(citadel.RUN_TIME, str)


def test_regime_analysis_safe_swallows_exceptions(monkeypatch):
    """_regime_analysis_safe wraps regime_analysis so a failure never
    breaks the export.

    Cenário protegido: regime_analysis (HMM-based) pode raise em datasets
    com poucos trades ou regimes degenerados. Sem o wrapper, export_json
    quebra mid-write e a run inteira não persiste — operator perde o
    relatório do backtest. Contract: NUNCA propaga exception.
    """
    import engines.citadel as citadel

    def boom(_trades):
        raise RuntimeError("HMM convergence failed")

    monkeypatch.setattr(citadel, "_hmm_regime_analysis", boom)
    result = citadel._regime_analysis_safe([{"pnl": 10}])
    assert isinstance(result, dict)
    assert result == {}


def test_scan_symbol_signature():
    """scan_symbol public signature pins the contract for downstream callers.

    Cenário protegido: launcher / live engine assumem positional args
    (df, symbol, macro_bias_series, corr) + kwargs (htf_stack_dfs,
    live_mode, live_tail_bars). Reordering breaks every caller.
    """
    import engines.citadel as citadel

    sig = inspect.signature(citadel.scan_symbol)
    params = list(sig.parameters.keys())
    expected = ["df", "symbol", "macro_bias_series", "corr",
                "htf_stack_dfs", "live_mode", "live_tail_bars"]
    assert params == expected, (
        f"scan_symbol signature drift: got {params}, expected {expected}"
    )

    # Returns tuple[list, dict] per docstring
    ret = sig.return_annotation
    if ret is not inspect.Signature.empty:
        # Annotation may be `tuple[list, dict]` literal or `Tuple[...]`
        ret_str = str(ret)
        assert "list" in ret_str and "dict" in ret_str, \
            f"return annotation drift: {ret_str}"


def test_engine_does_not_import_other_engines():
    """MEMORY §9: engines/citadel.py imports only core.* and config.*.

    Cenário protegido: CITADEL é referência (EDGE_DE_REGIME). Se virar
    dependência de outra engine, vira centralidade e cross-import. Outros
    engines também o importavam ad-hoc — millennium documenta a exceção;
    citadel em si não pode importar nenhum.
    """
    src = (Path(__file__).resolve().parent.parent.parent
           / "engines" / "citadel.py").read_text(encoding="utf-8")
    forbidden = ["from engines.", "import engines."]
    for marker in forbidden:
        for line_no, line in enumerate(src.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""'):
                continue
            assert marker not in stripped, (
                f"citadel.py:{line_no} imports another engine "
                f"({stripped!r}) — violates MEMORY §9"
            )
