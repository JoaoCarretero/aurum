from __future__ import annotations

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
