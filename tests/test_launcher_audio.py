from __future__ import annotations

from types import SimpleNamespace


def test_audio_enabled_respects_env(monkeypatch):
    from launcher_support.audio import audio_enabled

    monkeypatch.setenv("AURUM_AUDIO", "0")
    assert audio_enabled() is False

    monkeypatch.setenv("AURUM_AUDIO", "1")
    assert audio_enabled() is True


def test_notify_uses_winsound_when_available(monkeypatch):
    import launcher_support.audio as audio

    calls: list[int] = []

    fake_winsound = SimpleNamespace(
        MB_ICONHAND=16,
        MB_OK=0,
        MessageBeep=lambda tone: calls.append(tone),
    )
    monkeypatch.setattr(audio, "winsound", fake_winsound)
    monkeypatch.setattr(audio, "audio_enabled", lambda: True)

    assert audio.notify(error=True) is True
    assert calls == [16]


def test_notify_falls_back_to_widget_bell(monkeypatch):
    import launcher_support.audio as audio

    class FakeWidget:
        def __init__(self):
            self.called = 0

        def bell(self):
            self.called += 1

    widget = FakeWidget()
    monkeypatch.setattr(audio, "winsound", None)
    monkeypatch.setattr(audio, "audio_enabled", lambda: True)

    assert audio.notify(widget, error=False) is True
    assert widget.called == 1


def test_notify_returns_false_when_disabled(monkeypatch):
    import launcher_support.audio as audio

    monkeypatch.setattr(audio, "audio_enabled", lambda: False)
    assert audio.notify() is False
