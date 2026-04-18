"""Background poller pro cockpit API shadow run.

Problema que isto resolve: se o launcher faz HTTP sync no UI thread,
um timeout de 5s congela a TkInter mainloop. Solucao padrao: roda o
HTTP numa thread de background, cacheia o resultado, UI le o cache
instantaneo.

Uso tipico (wire pelo launcher boot):

    from launcher_support.shadow_poller import ShadowPoller
    from launcher_support.engines_live_view import _get_cockpit_client

    poller = ShadowPoller(
        client_factory=_get_cockpit_client,
        engine="millennium",
        poll_sec=5.0,
    )
    poller.start()
    ...
    # UI thread:
    cached = poller.get_cached()  # (Path, heartbeat) or None, instantaneo
    trades = poller.get_trades_cached()  # list[dict]
    ...
    # shutdown:
    poller.stop()
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class _ShadowSnapshot:
    """Estado completo de um poll bem-sucedido.

    virtual_dir encode o run_id (remote://<id>) pra manter compat com
    consumers existentes que tratam Path. heartbeat e o payload de
    /v1/runs/{id}/heartbeat. trades e a ultima janela de sinais de
    /v1/runs/{id}/trades?limit=N (lista vazia se o endpoint falhar).
    """

    virtual_dir: Path
    heartbeat: dict
    trades: list[dict] = field(default_factory=list)


@dataclass
class ShadowPoller:
    """Polls cockpit API `latest_run` + `get_heartbeat` em thread daemon.

    Campos:
        client_factory: callable que retorna um cockpit_client (ou None)
        engine: nome do engine pra query (default 'millennium')
        poll_sec: intervalo entre pools (default 5s)
        trades_limit: quantos sinais pegar por ciclo (default 20)

    O client_factory e chamado a cada poll pra pegar o client atual
    (caso tenha sido re-configurado no launcher rodando).
    """

    client_factory: Callable[[], object | None]
    engine: str = "millennium"
    poll_sec: float = 5.0
    trades_limit: int = 20

    _lock: threading.Lock = field(default_factory=threading.Lock)
    _cache: _ShadowSnapshot | None = None
    _last_poll_at: float = 0.0
    _last_error: str | None = None
    _thread: threading.Thread | None = None
    _stop_event: threading.Event = field(default_factory=threading.Event)

    # ─── Public API ────────────────────────────────────────────────

    def start(self) -> None:
        """Inicia o thread daemon. Idempotente (no-op se ja rodando)."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="aurum-shadow-poller",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout_sec: float = 2.0) -> None:
        """Sinaliza parada e aguarda thread. Idempotente."""
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout_sec)

    def get_cached(self) -> tuple[Path, dict] | None:
        """Le o ultimo (virtual_dir, heartbeat) conhecido. Nunca bloqueia.

        Mantido como tuple pra backward-compat com consumers existentes
        (engines_live_view._find_latest_shadow_run). Pra trades, usar
        get_trades_cached().
        """
        with self._lock:
            snap = self._cache
        if snap is None:
            return None
        return (snap.virtual_dir, snap.heartbeat)

    def get_trades_cached(self) -> list[dict]:
        """Le a ultima janela de sinais conhecida. Lista vazia se nada."""
        with self._lock:
            snap = self._cache
        if snap is None:
            return []
        # Retorna copia rasa pra isolar o caller do cache compartilhado.
        return list(snap.trades)

    def get_snapshot(self) -> _ShadowSnapshot | None:
        """Snapshot completo (virtual_dir + heartbeat + trades)."""
        with self._lock:
            return self._cache

    def last_poll_age_sec(self) -> float:
        """Tempo desde o ultimo poll bem-sucedido ou fail (s)."""
        with self._lock:
            if self._last_poll_at == 0.0:
                return float("inf")
            return time.time() - self._last_poll_at

    @property
    def last_error(self) -> str | None:
        with self._lock:
            return self._last_error

    # ─── Internals ─────────────────────────────────────────────────

    def _poll_once(self) -> None:
        """Uma iteracao do poll: fetch latest_run + heartbeat, atualiza cache."""
        try:
            client = self.client_factory()
        except Exception as exc:  # noqa: BLE001
            self._record_error(f"client_factory raised: {exc}")
            return
        if client is None:
            # Config ausente — cache permanece None.
            with self._lock:
                self._cache = None
                self._last_poll_at = time.time()
                self._last_error = None
            return
        try:
            run = client.latest_run(engine=self.engine)
        except Exception as exc:  # noqa: BLE001
            self._record_error(f"latest_run failed: {type(exc).__name__}")
            return
        if not run:
            # API respondeu OK mas sem runs — cache zera.
            with self._lock:
                self._cache = None
                self._last_poll_at = time.time()
                self._last_error = None
            return
        run_id = run.get("run_id")
        if not run_id:
            self._record_error("latest_run missing run_id")
            return
        virtual_dir = Path(f"remote://{run_id}")
        try:
            hb = client.get_heartbeat(run_id)
        except Exception as exc:  # noqa: BLE001
            # latest_run OK mas heartbeat falhou — mantem badge REMOTE
            # com stub, igual comportamento ja existente em
            # _find_latest_shadow_run. Sem heartbeat nao faz sentido
            # tentar trades, entao lista vazia.
            hb = {
                "run_id": run_id,
                "status": run.get("status", "unknown"),
                "ticks_ok": 0,
                "ticks_fail": 0,
                "novel_total": run.get("novel_total", 0),
                "last_tick_at": run.get("last_tick_at"),
                "last_error": f"heartbeat fetch failed: {type(exc).__name__}",
                "tick_sec": 0,
            }
            with self._lock:
                self._cache = _ShadowSnapshot(
                    virtual_dir=virtual_dir, heartbeat=hb, trades=[])
                self._last_poll_at = time.time()
                self._last_error = f"heartbeat failed: {type(exc).__name__}"
            return
        # Trades sao bonus — falha nao invalida o heartbeat recem-colhido.
        trades: list[dict] = []
        try:
            trades_resp = client.get_trades(run_id, limit=self.trades_limit)
            raw_trades = (trades_resp or {}).get("trades") or []
            if isinstance(raw_trades, list):
                trades = [t for t in raw_trades if isinstance(t, dict)]
        except Exception as exc:  # noqa: BLE001
            # Nao perde o heartbeat — so loga. Cache com trades=[] e
            # suficiente pra UI mostrar "(sem sinais ainda)".
            logger.debug("shadow poller: get_trades failed: %s",
                         type(exc).__name__)
        with self._lock:
            self._cache = _ShadowSnapshot(
                virtual_dir=virtual_dir, heartbeat=hb, trades=trades)
            self._last_poll_at = time.time()
            self._last_error = None

    def _record_error(self, msg: str) -> None:
        with self._lock:
            self._last_error = msg
            self._last_poll_at = time.time()
        logger.debug("shadow poller: %s", msg)

    def _loop(self) -> None:
        """Main loop da thread daemon. Ate _stop_event ser setado."""
        # Primeiro poll imediato pra popular o cache o mais rapido possivel.
        self._poll_once()
        while not self._stop_event.is_set():
            if self._stop_event.wait(timeout=self.poll_sec):
                return
            try:
                self._poll_once()
            except Exception as exc:  # noqa: BLE001
                # Nao deixa a thread morrer — loga e continua.
                logger.error("shadow poller loop crashed: %s", exc)
                self._record_error(f"loop crash: {exc}")
