"""Smoke contracts for engines/renaissance.py (RENAISSANCE — harmonic patterns).

Per audit 2026-04-25 Lane 4: RENAISSANCE was flagged as having zero tests
despite being live in the engine registry. These contracts pin the
import-time public surface without exercising the backtest pipeline (which
needs ~30 days of OHLCV cache).

Each test documents a real-world failure cost that justifies the pin.
"""
from __future__ import annotations

import inspect

import pytest


def test_module_imports_and_exports_public_api():
    """Engine must import without error and expose the documented entry points.

    Cenário protegido: a refactor de imports dropped uma função pública
    (closed_trade_stats, export_json) silenciosamente. CI ainda passa porque
    o resto do módulo importa, mas o reporting da run quebra em runtime.
    """
    import engines.renaissance as renaissance

    assert callable(getattr(renaissance, "closed_trade_stats", None)), \
        "closed_trade_stats removed — RENAISSANCE reports break"
    assert callable(getattr(renaissance, "export_json", None)), \
        "export_json removed — run artifacts not persisted"
    assert callable(getattr(renaissance, "main", None)), \
        "main removed — CLI entry broken"


def test_closed_trade_stats_signature():
    """closed_trade_stats(all_trades) returns a 5-tuple.

    Cenário protegido: RENAISSANCE.export_json depends on the exact 5-tuple
    shape (closed, win, loss, flat, win_rate). Drop a field and the JSON
    payload silently emits None for win_rate / flat_count.
    """
    import engines.renaissance as renaissance

    sig = inspect.signature(renaissance.closed_trade_stats)
    params = list(sig.parameters.keys())
    assert params == ["all_trades"], f"unexpected params: {params}"

    result = renaissance.closed_trade_stats([])
    assert isinstance(result, tuple)
    assert len(result) == 5, f"expected 5-tuple, got {len(result)}"
    closed, win, loss, flat, win_rate = result
    assert closed == []
    assert win == 0 and loss == 0 and flat == 0
    assert win_rate == 0.0


def test_closed_trade_stats_filters_only_win_loss():
    """Only WIN/LOSS results count as closed; PENDING/FLAT/None excluded.

    Cenário protegido: se a lógica do filter mudar pra incluir PENDING,
    o win_rate fica diluído com trades em aberto e o reporting mente.
    """
    import engines.renaissance as renaissance

    trades = [
        {"result": "WIN", "pnl": 100},
        {"result": "LOSS", "pnl": -50},
        {"result": "PENDING", "pnl": 0},
        {"result": None, "pnl": 0},
    ]
    closed, win, loss, flat, win_rate = renaissance.closed_trade_stats(trades)
    assert len(closed) == 2  # PENDING and None excluded
    assert win == 1
    assert loss == 1
    assert win_rate == pytest.approx(50.0)


def test_engine_does_not_import_other_engines():
    """MEMORY §9: engines import from core.* and config.params, never each other.

    Cenário protegido: a engine virar dependência transitiva de outra
    quebra o contrato flat de arquitetura e cria ordem-de-import que
    leak para sys.modules em testes paralelos.
    """
    src = (__import__("pathlib").Path(__file__)
           .resolve().parent.parent.parent / "engines" / "renaissance.py").read_text(
        encoding="utf-8"
    )
    forbidden = ["from engines.", "import engines."]
    for marker in forbidden:
        # Tolerate the package boilerplate `from engines import` if present
        # only as a docstring/comment; reject real imports.
        for line_no, line in enumerate(src.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""'):
                continue
            assert marker not in stripped, (
                f"renaissance.py:{line_no} imports another engine "
                f"({stripped!r}) — violates MEMORY §9"
            )


def test_renaissance_uses_calibrated_interval_from_engine_intervals():
    """RENAISSANCE INTERVAL is overridden from ENGINE_INTERVALS dict.

    Cenário protegido: longrun battery 2026-04-14 picked 15m bluechip = 6/6
    overfit PASS. If someone resets INTERVAL to the global default, the
    calibration is silently invalidated and engine reverts to 1h/whatever.
    """
    import engines.renaissance as renaissance
    from config.params import ENGINE_INTERVALS

    expected = ENGINE_INTERVALS.get("RENAISSANCE")
    assert expected is not None, \
        "ENGINE_INTERVALS.RENAISSANCE missing — calibration unpinned"
    assert renaissance.INTERVAL == expected, (
        f"renaissance.INTERVAL={renaissance.INTERVAL} ≠ "
        f"ENGINE_INTERVALS.RENAISSANCE={expected} — calibration drift"
    )
