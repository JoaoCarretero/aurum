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
_SHADOW_POLLER: object | None = None
_BOOT_ERROR: str | None = None


def get_tunnel_manager() -> "TunnelManager | None":
    """Retorna o TunnelManager ativo (ou None se ainda nao registrado)."""
    return _CURRENT


def set_tunnel_manager(manager: "TunnelManager | None") -> None:
    """Registra o TunnelManager no singleton. Chamado pelo launcher boot."""
    global _CURRENT
    _CURRENT = manager


def get_tunnel_boot_error() -> str | None:
    """Erro do boot do TunnelManager (ex: placeholder em config/keys.json).

    None quando nao ha erro ou quando o manager subiu normalmente. UI le
    esse valor pra mostrar badge especifico em vez de "TUNNEL —" opaco.
    """
    return _BOOT_ERROR


def set_tunnel_boot_error(reason: str | None) -> None:
    """Registra motivo do boot falho. Launcher seta quando rejeita config."""
    global _BOOT_ERROR
    _BOOT_ERROR = reason


def get_shadow_poller() -> object | None:
    """Retorna o ShadowPoller ativo (ou None)."""
    return _SHADOW_POLLER


def set_shadow_poller(poller: object | None) -> None:
    """Registra o ShadowPoller no singleton. Chamado pelo launcher boot."""
    global _SHADOW_POLLER
    _SHADOW_POLLER = poller


def reset_for_tests() -> None:
    """Helper pra tests limparem estado entre runs."""
    global _CURRENT, _SHADOW_POLLER, _BOOT_ERROR
    _CURRENT = None
    _SHADOW_POLLER = None
    _BOOT_ERROR = None
