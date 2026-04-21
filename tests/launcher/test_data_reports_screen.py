from __future__ import annotations

import tkinter as tk

from launcher_support.screens.data_reports import DataReportsScreen


class _FakeApp:
    pass


def test_collect_reports_uses_ttl_cache(tmp_path, monkeypatch):
    root_path = tmp_path
    data_dir = root_path / "data" / "runs" / "alpha"
    data_dir.mkdir(parents=True)
    first_report = data_dir / "one.json"
    first_report.write_text("{}", encoding="utf-8")

    root = tk.Tk()
    root.withdraw()
    try:
        screen = DataReportsScreen(root, _FakeApp(), root_path)
        first = screen._collect_reports()

        second_report = data_dir / "two.json"
        second_report.write_text("{}", encoding="utf-8")
        second = screen._collect_reports()

        assert [p.name for p, _, _ in first] == ["one.json"]
        assert [p.name for p, _, _ in second] == ["one.json"]
    finally:
        root.destroy()
