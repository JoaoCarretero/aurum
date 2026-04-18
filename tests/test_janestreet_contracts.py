"""Safety contract tests for engines/janestreet.py.

Cada teste documenta um cenário do mundo real cuja violação causa dano:
default acidentalmente live, hedge dessimétrico nao detectado, omega
recompensando arb perdedor, gates de live frouxos como paper.
"""
from __future__ import annotations

import pytest


def test_parse_mode_default_is_paper(monkeypatch):
    """Cenário protegido: usuario invoca janestreet sem --mode (default
    de UI/launcher). NAO pode cair em live por omissao."""
    import sys
    monkeypatch.setattr(sys, "argv", ["janestreet.py"])  # zero flags

    import engines.janestreet as js
    args = js._parse_mode()

    assert args.mode is None, f"Default deve ser None, foi {args.mode!r}"
    # No carregamento real (line 41-45), None vira ARB_PAPER=True
    derived_paper = args.mode == "paper" or args.mode is None
    derived_live = args.mode == "live"
    assert derived_paper is True
    assert derived_live is False
