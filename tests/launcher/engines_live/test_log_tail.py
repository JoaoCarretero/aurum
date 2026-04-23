"""Unit tests for data/log_tail.py — tail reader + color parse."""
from __future__ import annotations


def test_read_tail_empty_file(tmp_path):
    from launcher_support.engines_live.data.log_tail import read_tail

    path = tmp_path / "empty.log"
    path.write_text("")
    assert read_tail(path, n=10) == []


def test_read_tail_missing_file(tmp_path):
    from launcher_support.engines_live.data.log_tail import read_tail

    assert read_tail(tmp_path / "nope.log", n=10) == []


def test_read_tail_returns_last_n(tmp_path):
    from launcher_support.engines_live.data.log_tail import read_tail

    path = tmp_path / "lines.log"
    path.write_text("\n".join(f"line{i}" for i in range(20)) + "\n")

    tail = read_tail(path, n=5)
    assert tail == ["line15", "line16", "line17", "line18", "line19"]


def test_read_tail_respects_bytes_cap(tmp_path):
    from launcher_support.engines_live.data.log_tail import read_tail

    path = tmp_path / "big.log"
    # 10000 lines
    path.write_text("\n".join(f"line{i:05d}" for i in range(10000)) + "\n")

    tail = read_tail(path, n=5, max_bytes=1024)
    assert len(tail) == 5
    # last line should be preserved
    assert tail[-1] == "line09999"


def test_read_tail_handles_none_path():
    """None path returns empty list (defensive — callers may pass None)."""
    from launcher_support.engines_live.data.log_tail import read_tail
    assert read_tail(None, n=5) == []


def test_classify_info():
    from launcher_support.engines_live.data.log_tail import classify_level
    assert classify_level("2026-04-23 15:35:11 INFO  TICK ok=1 novel=0") == "INFO"


def test_classify_signal():
    from launcher_support.engines_live.data.log_tail import classify_level
    assert classify_level("2026-04-23 15:35:11 INFO  SIGNAL scan novel=1 BNB long") == "SIGNAL"


def test_classify_signal_via_novel_nonzero():
    """'novel=N' where N>=1 also tags SIGNAL."""
    from launcher_support.engines_live.data.log_tail import classify_level
    assert classify_level("16:00:00 INFO  TICK ok=5 novel=1 open=0") == "SIGNAL"


def test_classify_order():
    from launcher_support.engines_live.data.log_tail import classify_level
    assert classify_level("16:02:44 INFO ORDER placed BNBUSDT side=BUY qty=0.8") == "ORDER"


def test_classify_fill():
    from launcher_support.engines_live.data.log_tail import classify_level
    assert classify_level("16:02:45 INFO FILL confirmed BNBUSDT px=625.40") == "FILL"


def test_classify_exit():
    from launcher_support.engines_live.data.log_tail import classify_level
    assert classify_level("16:10:00 INFO EXIT closed BNB +$124.33") == "EXIT"


def test_classify_warn():
    from launcher_support.engines_live.data.log_tail import classify_level
    assert classify_level("2026-04-23 16:00:00 WARNING STALE signal skipped") == "WARN"


def test_classify_error():
    from launcher_support.engines_live.data.log_tail import classify_level
    assert classify_level("2026-04-23 17:00:00 ERROR TICK fail=3 err=TypeError") == "ERROR"


def test_classify_defaults_to_info():
    """Unrecognized lines default to INFO."""
    from launcher_support.engines_live.data.log_tail import classify_level
    assert classify_level("some random log line with no markers") == "INFO"


def test_classify_priority_error_over_warn():
    """ERROR takes priority over WARN even if both keywords appear."""
    from launcher_support.engines_live.data.log_tail import classify_level
    assert classify_level("18:00 ERROR warning: something bad") == "ERROR"
