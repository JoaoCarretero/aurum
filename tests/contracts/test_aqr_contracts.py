"""Smoke contracts for engines/aqr.py (AQR — evolutionary allocation).

Per audit 2026-04-25 Lane 4: AQR was flagged as having zero tests.
These contracts pin the import-time public surface and the
load_engine_trades behavior. simulate_evolution is left unexercised
(heavy: DarwinAllocator + merged trade history + chronological iteration).

Each test documents a real-world failure cost that justifies the pin.
"""
from __future__ import annotations

import inspect
import json


def test_module_imports_and_exports_public_api():
    """Engine module imports without error and exposes documented entrypoints.

    Cenário protegido: o `from config.params import *` em aqr.py:13
    expande dezenas de constantes; uma renomeação em params (ex: ACCOUNT_SIZE
    → ACCOUNT_USD) silenciosamente quebra a import com NameError em runtime.
    """
    import engines.aqr as aqr

    assert callable(getattr(aqr, "load_engine_trades", None)), \
        "load_engine_trades removed — AQR cannot consume backtest reports"
    assert callable(getattr(aqr, "simulate_evolution", None)), \
        "simulate_evolution removed — main pipeline broken"


def test_load_engine_trades_signature():
    """load_engine_trades(data_dir: str = 'data') -> dict[str, list[dict]]."""
    import engines.aqr as aqr

    sig = inspect.signature(aqr.load_engine_trades)
    params = sig.parameters
    assert "data_dir" in params, "data_dir parameter removed"
    assert params["data_dir"].default == "data", \
        f"unexpected default for data_dir: {params['data_dir'].default!r}"


def test_load_engine_trades_returns_plain_dict_not_defaultdict(tmp_path):
    """load_engine_trades converts defaultdict→dict before returning.

    Cenário protegido: callers iterando ou serializando o resultado em JSON
    falham se receberem defaultdict (json.dumps OK, mas semantic difference
    matters em testes de igualdade e em fanout de allocations). O `dict(
    engine_trades)` ao final é o contrato.
    """
    import engines.aqr as aqr

    result = aqr.load_engine_trades(str(tmp_path))
    assert type(result) is dict, f"expected plain dict, got {type(result).__name__}"


def test_load_engine_trades_skips_non_report_files(tmp_path):
    """Non-report JSONs (no 'reports' in path) are silently skipped.

    Cenário protegido: o glob `*.json` é amplo. Sem o filter `'reports' in
    str(report_file)`, AQR ingere config files, audit metas, cockpit caches
    e estatísticas diárias como se fossem trade reports — load_engine_trades
    retorna engines fantasma com trades inválidos.
    """
    import engines.aqr as aqr

    # Create a misleading JSON outside reports/
    decoy = tmp_path / "audit_meta.json"
    decoy.write_text(json.dumps({
        "config": {"engine": "FAKE_ENGINE"},
        "trades": [{"pnl": 100, "result": "WIN"}],
    }), encoding="utf-8")

    result = aqr.load_engine_trades(str(tmp_path))
    assert "FAKE_ENGINE" not in result, \
        "non-reports/ JSON ingested — load_engine_trades filter broken"


def test_load_engine_trades_picks_up_reports_subdir(tmp_path):
    """Reports under any reports/ subdirectory are loaded.

    Cenário protegido: o filter `'reports' in str(report_file)` precisa
    matchear `data/<engine>/<run>/reports/<file>.json`. Se o run dir layout
    mudar (ex: pra `output/`), AQR fica cego pra runs novas sem aviso.
    """
    import engines.aqr as aqr

    rdir = tmp_path / "engine_x" / "2026-04-25_120000" / "reports"
    rdir.mkdir(parents=True)
    payload = {
        "config": {"engine": "ENGINE_X"},
        "trades": [{"pnl": 50, "result": "WIN", "symbol": "BTC"}],
    }
    (rdir / "engine_x_15m_v1.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )

    result = aqr.load_engine_trades(str(tmp_path))
    assert "ENGINE_X" in result, \
        f"expected ENGINE_X key, got: {list(result.keys())}"
    assert len(result["ENGINE_X"]) == 1
    assert result["ENGINE_X"][0]["pnl"] == 50
    assert result["ENGINE_X"][0]["engine"] == "ENGINE_X"  # injected by loader


def test_engine_does_not_import_other_engines():
    """MEMORY §9: engines import from core.* and config.*, never each other.

    Cenário protegido: AQR consome trades produzidos por outras engines via
    JSON read em data/<engine>/.../reports/. Importar engine code direto
    quebra o contrato flat e força ordem de import.
    """
    src = (__import__("pathlib").Path(__file__)
           .resolve().parent.parent.parent / "engines" / "aqr.py").read_text(
        encoding="utf-8"
    )
    forbidden = ["from engines.", "import engines."]
    for marker in forbidden:
        for line_no, line in enumerate(src.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""'):
                continue
            assert marker not in stripped, (
                f"aqr.py:{line_no} imports another engine "
                f"({stripped!r}) — violates MEMORY §9"
            )
