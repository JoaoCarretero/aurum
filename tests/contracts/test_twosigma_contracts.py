"""Smoke contracts for engines/twosigma.py (TWO SIGMA — ML meta-ensemble).

Per audit 2026-04-25 Lane 4: TWO SIGMA was flagged as having zero tests.
These contracts pin the import-time public surface and the data-leakage
guard, without exercising LightGBM training (which needs trade history).

Each test documents a real-world failure cost that justifies the pin.
"""
from __future__ import annotations

import inspect

import pandas as pd
import pytest


def test_module_imports_and_exports_public_api():
    """Module imports cleanly and exposes the documented entry points.

    Cenário protegido: o assert at-import (FEATURE_COLS sem at-exit data)
    em twosigma.py:145-153 falha silenciosamente se um refactor mover
    FEATURE_COLS pra cima/baixo. Garantir que import passa = invariant
    de no-leakage holds.
    """
    import engines.twosigma as twosigma

    assert callable(getattr(twosigma, "trades_to_features", None)), \
        "trades_to_features removed — feature engineering broken"
    assert callable(getattr(twosigma, "build_target", None)), \
        "build_target removed — labelling broken"
    assert callable(getattr(twosigma, "run_prometeu", None)), \
        "run_prometeu removed — main entry point gone"
    assert getattr(twosigma, "PrometeuEnsemble", None) is not None, \
        "PrometeuEnsemble removed — ML core gone"


def test_feature_cols_excludes_at_exit_data():
    """FEATURE_COLS must not contain any AT-EXIT field.

    Cenário protegido: TWO SIGMA é meta-ensemble walk-forward. Se
    FEATURE_COLS tiver pnl / result / exit_idx, o modelo aprende o
    target e o sharpe walk-forward é inflado artificialmente. Esse
    assert já roda no import, mas pinamos aqui pra surfacing claro
    em CI (em vez de ImportError críptico).
    """
    import engines.twosigma as twosigma

    forbidden = twosigma._FORBIDDEN_FEATURES
    leaked = set(twosigma.FEATURE_COLS) & forbidden
    assert not leaked, (
        f"data leakage in FEATURE_COLS: {leaked} are AT-EXIT fields "
        "— walk-forward sharpe would be artificially inflated"
    )


def test_trades_to_features_excludes_open_trades():
    """Only WIN/LOSS results enter the feature matrix.

    Cenário protegido: PENDING / None trades não tem ground-truth label.
    Inclui-los no matrix injeta NaN no target — LightGBM lida silenciosamente
    (via `objective=multiclass`) e o modelo é treinado com label 0/-1
    ruidoso, decay invisível.
    """
    import engines.twosigma as twosigma

    trades = [
        {"result": "WIN", "score": 0.7, "rsi": 55, "strategy": "GRAVITON",
         "pnl": 100, "timestamp": "2026-01-01"},
        {"result": "LOSS", "score": 0.3, "rsi": 45, "strategy": "GRAVITON",
         "pnl": -50, "timestamp": "2026-01-02"},
        {"result": "PENDING", "score": 0.5, "strategy": "GRAVITON"},
        {"result": None, "score": 0.5, "strategy": "GRAVITON"},
    ]
    df = twosigma.trades_to_features(trades)
    assert len(df) == 2, f"expected 2 closed rows, got {len(df)}"
    assert set(df["result"]) == {"WIN", "LOSS"}


def test_build_target_short_window_emits_minus_one():
    """build_target marks insufficient-window trades as target=-1.

    Cenário protegido: o último trade da série tem janela vazia (não há
    trades futuros). Marcar como -1 (sentinel) é o contrato pra LightGBM
    descartar via `--objective=multiclass` + filter. Mudar pra 0 ou NaN
    e o modelo ganha amostras inválidas.
    """
    import engines.twosigma as twosigma

    df = pd.DataFrame([
        {"strategy": "GRAVITON", "pnl": 10},
        {"strategy": "VENTURI", "pnl": 5},
        {"strategy": "GRAVITON", "pnl": -3},
    ])
    targets = twosigma.build_target(df, lookahead=10)
    assert len(targets) == 2  # one less than df (loop is range(len-1))
    # Last entry has only 2 trades in window (< 3) → -1 sentinel
    assert targets.iloc[-1] == -1


def test_trades_to_features_signature():
    """Public signature: trades_to_features(trades: list[dict]) -> DataFrame."""
    import engines.twosigma as twosigma

    sig = inspect.signature(twosigma.trades_to_features)
    params = list(sig.parameters.keys())
    assert params == ["trades"], f"unexpected params: {params}"


def test_engine_does_not_import_other_engines():
    """MEMORY §9: engines import from core.* and config.*, never each other.

    Cenário protegido: TWO SIGMA é orquestrador (consome trades de outras
    engines via load), mas a ingestão deve ser feita por path/json read,
    nunca por import direto da engine produtora.
    """
    src = (__import__("pathlib").Path(__file__)
           .resolve().parent.parent.parent / "engines" / "twosigma.py").read_text(
        encoding="utf-8"
    )
    forbidden = ["from engines.", "import engines."]
    for marker in forbidden:
        for line_no, line in enumerate(src.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""'):
                continue
            assert marker not in stripped, (
                f"twosigma.py:{line_no} imports another engine "
                f"({stripped!r}) — violates MEMORY §9"
            )
