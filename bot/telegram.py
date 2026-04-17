"""
☿ AURUM Finance — Telegram Bot v1.0
=====================================
Notificações e comandos para o Live Engine.

Comandos:
  /status  — dashboard resumido
  /trades  — últimas trades
  /kill    — estado do kill-switch
  /pos     — posições abertas
  /help    — lista comandos

Config em config/keys.json:
  "telegram": {
      "bot_token": "123456:ABC-DEF...",
      "chat_id":   "987654321",
      "allowed_user_ids": ["987654321"]   # optional — defaults to [chat_id]
  }

Authorization model:
  * chat_id identifies the conversation where we *send* notifications.
  * allowed_user_ids is the allowlist of Telegram user IDs that may
    *issue commands*. In DMs they coincide, but in groups chat_id is
    the group's id while any member has their own user id — so the
    two concepts must not be conflated.
"""

import asyncio, json, logging, time
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from core.failure_policy import BEST_EFFORT, DEGRADE_AND_LOG
from core.health import runtime_health
from core.transport import RequestSpec, TransportClient

if TYPE_CHECKING:
    from engines.live import LiveEngine

log = logging.getLogger("aurum.telegram")

# ── CONFIG ────────────────────────────────────────────────────
_KEYS_PATH = Path(__file__).parent.parent / "config" / "keys.json"
_API = "https://api.telegram.org/bot{token}/{method}"
_POLL_INTERVAL = 2          # segundos entre polls de updates
_MAX_MSG_LEN   = 4000       # Telegram limit ~4096


def _load_telegram_config() -> tuple[str, str, frozenset[str]]:
    """Retorna (bot_token, chat_id, allowed_user_ids).

    allowed_user_ids defaults to {chat_id} when the key is absent — preserves
    the prior DM-only behavior without requiring existing configs to change.
    Returns ('', '', frozenset()) when telegram is not configured.
    """
    try:
        with open(_KEYS_PATH) as f:
            cfg = json.load(f)
        tg = cfg.get("telegram", {})
        token = tg.get("bot_token", "")
        chat  = str(tg.get("chat_id", ""))
        raw_ids = tg.get("allowed_user_ids")
        if raw_ids is None:
            allowed = frozenset({chat}) if chat else frozenset()
        else:
            allowed = frozenset(str(x) for x in raw_ids if str(x))
        return token, chat, allowed
    except Exception:
        runtime_health.record("telegram.config_load_failure")
        return "", "", frozenset()


class TelegramNotifier:
    """
    Envia mensagens e escuta comandos via Telegram Bot API (long-polling).
    Usa apenas requests/asyncio — sem dependências externas.
    """

    def __init__(self, engine: "LiveEngine"):
        self.engine = engine
        self.token, self.chat_id, self.allowed_user_ids = _load_telegram_config()
        self.enabled = bool(self.token and self.chat_id)
        self._offset = 0
        self._session = None      # aiohttp ou None
        self._running = False

        if not self.enabled:
            log.warning("Telegram não configurado — notificações desactivadas. "
                        "Adiciona 'telegram' a config/keys.json")

    # ── HTTP helpers (usa requests síncrono em thread) ────────
    def _url(self, method: str) -> str:
        return _API.format(token=self.token, method=method)

    async def _post(self, method: str, data: dict) -> dict:
        """POST assíncrono via thread pool (evita instalar aiohttp).

        Returns the parsed JSON response on success. On transport failure,
        non-2xx status, non-JSON body, or a Telegram ``ok=false`` payload we
        return ``{}`` but record a health event and log the reason — the old
        behavior silently swallowed 403s / rate limits so the operator never
        noticed when the bot stopped reaching the chat.
        """
        loop = asyncio.get_event_loop()
        try:
            client = TransportClient()
            resp = await loop.run_in_executor(
                None,
                lambda: client.request(
                    RequestSpec(
                        method="POST",
                        url=self._url(method),
                        json=data,
                        timeout=10,
                    )
                ),
            )
        except Exception as e:
            runtime_health.record("telegram.api_post_failure")
            log.log(
                logging.DEBUG if BEST_EFFORT.log_level == "debug" else logging.WARNING,
                f"Telegram API error ({method}): {e}",
            )
            return {}

        try:
            payload = resp.json()
        except ValueError:
            runtime_health.record("telegram.api_non_json")
            log.warning(f"Telegram {method} returned non-JSON body")
            return {}

        if isinstance(payload, dict) and payload.get("ok") is False:
            runtime_health.record("telegram.api_ok_false")
            log.warning(
                f"Telegram {method} ok=false "
                f"code={payload.get('error_code')} desc={payload.get('description', '')[:120]}"
            )
            return {}
        return payload

    # ── SEND ──────────────────────────────────────────────────
    async def send(self, text: str, parse_mode: str = "HTML"):
        """Envia mensagem ao chat configurado."""
        if not self.enabled:
            return
        # truncate se necessário
        if len(text) > _MAX_MSG_LEN:
            text = text[:_MAX_MSG_LEN - 20] + "\n\n(truncado...)"
        await self._post("sendMessage", {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        })

    # ── NOTIFICAÇÕES PRÉ-FORMATADAS ──────────────────────────
    async def notify_open(self, sig: dict, fill_price: float):
        """Notificação de abertura de posição."""
        arrow = "🟢 LONG" if sig["direction"] == "BULLISH" else "🔴 SHORT"
        msg = (
            f"<b>{arrow}  {sig['symbol']}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Entry:  <code>{fill_price:.6f}</code>\n"
            f"Stop:   <code>{sig['stop']:.6f}</code>\n"
            f"Target: <code>{sig['target']:.6f}</code>\n"
            f"Size:   <code>{sig['size']}</code>\n"
            f"Score:  <code>{sig['score']:.3f}</code>  |  RR: <code>{sig['rr']:.2f}</code>\n"
            f"Macro:  {sig.get('macro', '?')}"
        )
        await self.send(msg)

    async def notify_close(self, trade: dict):
        """Notificação de fecho de posição."""
        icon = "✅ WIN" if trade["result"] == "WIN" else "❌ LOSS"
        pnl = trade["pnl"]
        msg = (
            f"<b>{icon}  {trade['symbol']}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"PnL:     <code>${pnl:+.2f}</code>\n"
            f"R real:  <code>{trade['real_r']:+.3f}</code>  "
            f"(drift: <code>{trade['drift_r']:+.3f}</code>)\n"
            f"Entry:   <code>{trade['entry']:.6f}</code>\n"
            f"Exit:    <code>{trade['exit']:.6f}</code>\n"
            f"Account: <code>${trade['account']:,.2f}</code>"
        )
        await self.send(msg)

    async def notify_killswitch(self, reason: str):
        """Alerta kill-switch."""
        msg = (
            f"🚨 <b>KILL-SWITCH TRIGGERED</b> 🚨\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Motivo: {reason}\n"
            f"Engine pausada — trades bloqueadas."
        )
        await self.send(msg)

    async def notify_startup(self, mode: str, symbols: list):
        """Notificação de arranque."""
        from config.params import ACCOUNT_SIZE, MAX_OPEN_POSITIONS, INTERVAL, MACRO_SYMBOL, SYMBOLS
        from engines.live import LIVE_RUN_ID
        msg = (
            f"☿ <b>AURUM Finance · Live Engine v1.0</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Mode:      <b>{mode}</b>\n"
            f"Symbols:   {len(symbols)} ({', '.join(s[:4] for s in symbols)})\n"
            f"Timeframe: {INTERVAL}  ·  Macro: {MACRO_SYMBOL}\n"
            f"Account:   <code>${ACCOUNT_SIZE:,.0f}</code>  ·  Max pos: {MAX_OPEN_POSITIONS}\n"
            f"Run ID:    <code>{LIVE_RUN_ID}</code>\n"
            f"Start:     {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Dashboard a cada 5min · /help para comandos"
        )
        await self.send(msg)

    async def notify_shutdown(self):
        """Notificação de encerramento."""
        n = len(self.engine.closed_trades)
        pnl = sum(t["pnl"] for t in self.engine.closed_trades)
        wins = sum(1 for t in self.engine.closed_trades if t["result"] == "WIN")
        wr = f"{wins/n*100:.0f}%" if n else "—"
        msg = (
            f"⏹ <b>AURUM Engine encerrado</b>\n"
            f"Trades: {n}  |  WR: {wr}  |  PnL: ${pnl:+.2f}"
        )
        await self.send(msg)

    # ── COMMAND HANDLERS ──────────────────────────────────────
    def _cmd_status(self) -> str:
        """Dashboard resumido."""
        e = self.engine
        n = len(e.closed_trades)
        wins = sum(1 for t in e.closed_trades if t["result"] == "WIN")
        wr = f"{wins/n*100:.0f}%" if n else "—"
        pnl = sum(t["pnl"] for t in e.closed_trades)
        ks = e.kill_sw.status()

        from config.params import MACRO_SYMBOL, SYMBOLS
        from engines.live import LIVE_MODE, TESTNET_MODE, DEMO_MODE
        mode = "DEMO" if DEMO_MODE else "TESTNET" if TESTNET_MODE else "LIVE" if LIVE_MODE else "PAPER"

        # macro
        btc_st = e._symbol_state(MACRO_SYMBOL)
        s200 = btc_st.get("s200", 0)
        from config.params import MACRO_SLOPE_BULL, MACRO_SLOPE_BEAR
        macro = "BULL ↑" if s200 > MACRO_SLOPE_BULL else "BEAR ↓" if s200 < MACRO_SLOPE_BEAR else "CHOP ↔"

        # tempo próximo candle
        now_s = time.time()
        rem = int(15*60 - now_s % (15*60))
        mm, ss = divmod(rem, 60)

        lines = [
            f"☿ <b>AURUM {mode}</b>  |  {datetime.now().strftime('%H:%M:%S')}",
            f"Próx candle: {mm:02d}:{ss:02d}",
            f"Macro BTC: <b>{macro}</b> (s200={s200:+.4f})",
            f"",
            f"Trades: {n}  |  WR: {wr}  |  PnL: <code>${pnl:+.2f}</code>",
            f"DD: {ks.get('dd_pct',0):.1f}%  |  KS: {'✅ OK' if ks.get('ok') else '🚨 TRIGGERED'}",
            f"Account: <code>${e.account:,.2f}</code>",
        ]

        if e.positions:
            lines.append(f"\n<b>Posições abertas:</b>")
            for p in e.positions:
                dur = int((datetime.now(timezone.utc) - p.open_ts).seconds / 60)
                df_p = e.buffer.to_df(p.symbol)
                curr = float(df_p["close"].iloc[-1]) if df_p is not None else p.entry
                unrl = (curr - p.entry) * p.size if p.direction == "BULLISH" else (p.entry - curr) * p.size
                arrow = "🟢" if p.direction == "BULLISH" else "🔴"
                lines.append(f"  {arrow} {p.symbol}  ${unrl:+.2f}  {dur}min")

        return "\n".join(lines)

    def _cmd_trades(self) -> str:
        """Últimas 10 trades."""
        trades = self.engine.closed_trades[-10:]
        if not trades:
            return "Nenhuma trade fechada nesta sessão."
        lines = [f"<b>Últimas {len(trades)} trades:</b>\n"]
        for t in reversed(trades):
            icon = "✅" if t["result"] == "WIN" else "❌"
            lines.append(f"{icon} {t['symbol']:12s}  <code>${t['pnl']:>+8.2f}</code>  R={t['real_r']:+.2f}")
        total = sum(t["pnl"] for t in trades)
        lines.append(f"\nTotal: <code>${total:+.2f}</code>")
        return "\n".join(lines)

    def _cmd_kill(self) -> str:
        """Estado do kill-switch."""
        ks = self.engine.kill_sw.status()
        ok = "✅ OK" if ks.get("ok") else "🚨 TRIGGERED"
        lines = [
            f"<b>Kill-Switch: {ok}</b>\n",
            f"DD:         {ks.get('dd_pct', 0):.1f}%",
            f"WR:         {ks.get('wr', 0)*100:.0f}%",
            f"Expectancy: {ks.get('expectancy', 0):.3f}",
            f"N trades:   {ks.get('n', 0)}",
        ]
        if not ks.get("ok"):
            lines.append(f"\nMotivo: {ks.get('reason', '?')}")
        return "\n".join(lines)

    def _cmd_pos(self) -> str:
        """Posições abertas detalhadas."""
        if not self.engine.positions:
            return "Sem posições abertas."
        lines = [f"<b>Posições abertas ({len(self.engine.positions)}):</b>\n"]
        for p in self.engine.positions:
            dur = int((datetime.now(timezone.utc) - p.open_ts).seconds / 60)
            df_p = self.engine.buffer.to_df(p.symbol)
            curr = float(df_p["close"].iloc[-1]) if df_p is not None else p.entry
            unrl = (curr - p.entry) * p.size if p.direction == "BULLISH" else (p.entry - curr) * p.size
            arrow = "🟢 LONG" if p.direction == "BULLISH" else "🔴 SHORT"
            be = " (BE)" if p.be_done else ""
            lines.append(
                f"{arrow}  <b>{p.symbol}</b>{be}\n"
                f"  Entry: <code>{p.entry:.6f}</code>  Now: <code>{curr:.6f}</code>\n"
                f"  Stop:  <code>{p.cur_stop:.6f}</code>  Target: <code>{p.target:.6f}</code>\n"
                f"  Unreal: <code>${unrl:+.2f}</code>  |  {dur}min\n"
            )
        return "\n".join(lines)

    def _cmd_help(self) -> str:
        return (
            "☿ <b>AURUM Telegram Commands</b>\n\n"
            "/status — dashboard resumido\n"
            "/trades — últimas trades\n"
            "/pos    — posições abertas\n"
            "/kill   — estado do kill-switch\n"
            "/help   — esta mensagem"
        )

    _COMMANDS = {
        "/status": "_cmd_status",
        "/trades": "_cmd_trades",
        "/kill":   "_cmd_kill",
        "/pos":    "_cmd_pos",
        "/help":   "_cmd_help",
        "/start":  "_cmd_help",
    }
    _last_cmd_time = 0.0
    _CMD_COOLDOWN  = 3.0  # seconds between commands

    # ── POLLING LOOP ──────────────────────────────────────────
    async def _poll_updates(self):
        """Long-polling loop para receber comandos."""
        while self._running:
            try:
                result = await self._post("getUpdates", {
                    "offset": self._offset,
                    "timeout": 10,
                    "allowed_updates": ["message"],
                })
                updates = result.get("result", [])
                for upd in updates:
                    self._offset = upd["update_id"] + 1
                    msg = upd.get("message", {})
                    chat_id = str(msg.get("chat", {}).get("id", ""))
                    text = msg.get("text", "").strip()

                    # só responde no chat configurado
                    if chat_id != self.chat_id:
                        continue

                    # user auth: sender id must be in the explicit allowlist.
                    # In a group, chat_id is the group — any member would pass
                    # a chat-id-only check, so we require per-user authorization.
                    from_id = str(msg.get("from", {}).get("id", ""))
                    if not self.allowed_user_ids or from_id not in self.allowed_user_ids:
                        log.warning(
                            f"Telegram command from unauthorized user id={from_id} "
                            f"(chat_id={chat_id}) — rejected"
                        )
                        continue

                    # rate limiting
                    import time as _time
                    now = _time.time()
                    if now - self._last_cmd_time < self._CMD_COOLDOWN:
                        continue
                    self._last_cmd_time = now

                    cmd = text.split()[0].lower() if text else ""
                    # remove @botname se presente
                    cmd = cmd.split("@")[0]

                    handler_name = self._COMMANDS.get(cmd)
                    if handler_name:
                        response = getattr(self, handler_name)()
                        await self.send(response)
                    elif text.startswith("/"):
                        await self.send(f"Comando desconhecido: {cmd}\n\nUsa /help para ver comandos.")

            except Exception as e:
                runtime_health.record("telegram.poll_failure")
                log.log(
                    logging.WARNING if DEGRADE_AND_LOG.log_level == "warning" else logging.DEBUG,
                    f"Telegram poll error: {e}",
                )
                await asyncio.sleep(5)

            await asyncio.sleep(_POLL_INTERVAL)

    async def start(self):
        """Inicia o polling loop."""
        if not self.enabled:
            return
        self._running = True
        log.info("Telegram bot activo — a aguardar comandos")
        await self._poll_updates()

    def stop(self):
        """Para o polling."""
        self._running = False
