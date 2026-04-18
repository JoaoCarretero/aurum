"""Singleton registry pro TunnelManager gerenciado pelo launcher.

Mora em launcher_support/ (nao em launcher.py) pra escapar do problema
__main__-vs-launcher: quando o usuario roda `python launcher.py`, o
modulo vira `__main__` em sys.modules, e `from launcher import X` de
outro modulo carrega launcher.py de novo como um modulo separado com
variaveis globais zeradas. Mantendo o singleton aqui, tanto launcher
(como __main__) quanto launcher_support.engines_live_view leem a
mesma instancia.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from launcher_support.ssh_tunnel import TunnelManager


_CURRENT: "TunnelManager | None" = None


def get_tunnel_manager() -> "TunnelManager | None":
    """Retorna o TunnelManager ativo (ou None se ainda nao registrado)."""
    return _CURRENT


def set_tunnel_manager(manager: "TunnelManager | None") -> None:
    """Registra o TunnelManager no singleton. Chamado pelo launcher boot."""
    global _CURRENT
    _CURRENT = manager


def reset_for_tests() -> None:
    """Helper pra tests limparem estado entre runs."""
    global _CURRENT
    _CURRENT = None
