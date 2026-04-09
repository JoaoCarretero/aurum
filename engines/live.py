"""
☿ AURUM Finance — Live Engine v1.0
====================================
Paper trading + Live execution para Binance USDT Futures.

Modos:
  PAPER  — websocket real, sem ordens reais (logs completos + slippage tracking)
  LIVE   — execução real (requer API keys em variáveis de ambiente)

Variáveis de ambiente necessárias (LIVE mode):
  BINANCE_API_KEY
  BINANCE_API_SECRET

Variáveis de ambiente para TESTNET (recomendado para validação):
  BINANCE_TESTNET_KEY
  BINANCE_TESTNET_SECRET
  → Registar em https://testnet.binancefuture.com

Estrutura:
  CandleBuffer    — rolling window 400 candles por símbolo
  SignalEngine    — adapta scan_symbol para streaming (1 candle de cada vez)
  OrderManager   — paper ou real (Binance Futures)
  PositionState  — gestão de posições abertas + trailing stop
  RiskEngine     — kill-switch estatístico + DD + slippage tracker
  ExecutionDrift — real R vs expected R por trade
  LiveEngine     — main loop asyncio

Ficheiros de output:
  data/live/{RUN_ID}/
    logs/live.log
    logs/trades.log
    state/positions.json      ← persiste entre reinícios
    state/metrics.json
    reports/session_{date}.json
"""

import os, sys, json, time, asyncio, logging, signal, math, random, requests
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict, deque
from typing import Optional

# ── PATH ──────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))

# Constantes — single source of truth
from config.params import *   # noqa: F401,F403

# Funções do backtest engine
from core import (
    indicators, swing_structure, omega, detect_macro, build_corr_matrix,
    portfolio_allows, position_size, calc_levels, calc_levels_chop,
    prepare_htf, merge_all_htf_to_ltf, fetch_all, validate,
    score_omega, score_chop,
)
from engines.backtest import RUN_ID, log as _bk_log
import engines.backtest as _bk
from bot.telegram import TelegramNotifier

# ── CONFIG ────────────────────────────────────────────────────
LIVE_MODE         = False          # False = PAPER  |  True = LIVE/TESTNET
TESTNET_MODE      = False          # True = Binance Futures Testnet (testnet.binancefuture.com)
DEMO_MODE         = False          # True = Binance Futures Demo    (demo-fapi.binance.com)

# URLs por modo
_WS_BASE   = {
    "paper":   "wss://fstream.binance.com",           # dados reais, sem ordens
    "testnet": "wss://stream.binancefuture.com",       # testnet WS
    "demo":    "wss://dstream.binance.com",            # demo WS (mesmo feed que live)
    "live":    "wss://fstream.binance.com",
}
_REST_BASE = {
    "paper":   None,
    "testnet": "https://testnet.binancefuture.com",
    "demo":    "https://demo-fapi.binance.com",
    "live":    None,
}
PAPER_SLIPPAGE    = 0.0003         # slippage base no paper mode (saída usa variação aleatória)
CANDLE_BUFFER_N   = 600
SIGNAL_COOLDOWN_S = 30
MAX_OPEN_LIVE     = MAX_OPEN_POSITIONS
RECONNECT_DELAY   = 5
HEARTBEAT_EVERY   = 30

# Kill-switch estatístico
KS_WINDOW         = 15             # 15 trades (mais reactivo que 30 em crypto 15m)
KS_MIN_EXPECTANCY = 0.0
KS_MIN_WR         = 0.45
KS_DD_TRIGGER     = 0.12
KS_FAST_DD_N      = 5              # últimas N trades para fast-DD check
KS_FAST_DD_MULT   = 2.0            # se sum(pnl[-5]) < -KS_FAST_DD_MULT * BASE_RISK_USD → stop
KS_DRIFT_TRIGGER  = -0.25

# Execução drift → penalidade de sizing
DRIFT_WINDOW        = 20
DRIFT_SIZE_PENALTY  = -0.15        # se drift_mean < -0.15R → reduz size global 20%

# Filtros de regime de mercado
SPEED_MIN           = 0.002        # range_pct mínimo (mercado lento → sem trades)
SPEED_WINDOW        = 5            # candles para média de speed
SESSION_BLOCK_HOURS = {2, 3, 4, 5} # UTC: Ásia baixa liquidez (02h-06h)
SESSION_BLOCK_ACTIVE= False        # True = activa filtro de horário

# Symbol ranking
SYMBOL_RANK_WINDOW  = 20           # últimos N trades por símbolo para ranking
SYMBOL_BLOCK_THRESH = -50.0        # bloqueia símbolo se PnL últimos 20 trades < -$50

# Telegram dashboard
TG_DASH_EVERY       = 10           # envia dashboard ao Telegram a cada N ticks (N*30s = 5min)

# Corr matrix throttle
CORR_REFRESH_CANDLES = 4           # recalcula corr a cada N candles BTC

# Dirs
_LIVE_DATE = datetime.now().strftime("%Y-%m-%d")
LIVE_RUN_ID  = f"{_LIVE_DATE}_{datetime.now().strftime('%H%M')}"
LIVE_DIR     = Path(f"data/live/{LIVE_RUN_ID}")
(LIVE_DIR / "logs").mkdir(parents=True, exist_ok=True)
(LIVE_DIR / "state").mkdir(parents=True, exist_ok=True)
(LIVE_DIR / "reports").mkdir(parents=True, exist_ok=True)

# ── LOGGING ───────────────────────────────────────────────────
def _load_keys(mode: str) -> tuple[str, str]:
    """
    Lê API keys de config/keys.json.
    Estrutura: {"demo": {"api_key": ..., "api_secret": ...}, "testnet": {...}, "live": {...}}
    """
    config_path = Path(__file__).parent.parent / "config" / "keys.json"
    if not config_path.exists():
        print(f"\n  ⚠  Ficheiro de keys não encontrado: {config_path}")
        print(f"  Cria a pasta config/ e o ficheiro keys.json com a estrutura:")
        print(f'  {{"demo": {{"api_key": "...", "api_secret": "..."}}}}')
        sys.exit(1)
    try:
        with open(config_path, "r") as f:
            cfg = json.load(f)
        block = cfg.get(mode, {})
        key    = block.get("api_key", "")
        secret = block.get("api_secret", "")
        if not key or not secret or "COLE_AQUI" in key:
            print(f"\n  ⚠  Keys para modo '{mode}' não preenchidas em config/keys.json")
            sys.exit(1)
        return key, secret
    except Exception as e:
        print(f"\n  ⚠  Erro ao ler config/keys.json: {e}")
        sys.exit(1)


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s")

    # Desactivar root logger do backtest (evita propagação cruzada)
    logging.getLogger().handlers = [logging.NullHandler()]

    live_logger = logging.getLogger("aurum.live")
    if not live_logger.handlers:  # evita duplicação se chamado mais de uma vez
        handlers = [
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(LIVE_DIR / "logs" / "live.log", encoding="utf-8"),
        ]
        live_logger.setLevel(logging.DEBUG)
        live_logger.propagate = False
        for h in handlers: h.setFormatter(fmt); live_logger.addHandler(h)

    trade_logger = logging.getLogger("aurum.trades")
    if not trade_logger.handlers:
        trade_logger.setLevel(logging.DEBUG)
        trade_logger.propagate = False
        th = logging.FileHandler(LIVE_DIR / "logs" / "trades.log", encoding="utf-8")
        th.setFormatter(fmt); trade_logger.addHandler(th)

    return live_logger, trade_logger

log, tlog = _setup_logging()

# ── ESTADO DE POSIÇÃO ─────────────────────────────────────────
class Position:
    """Uma posição aberta com trailing stop inteligente."""
    def __init__(self, symbol, direction, entry, stop, target, size,
                 score, macro_bias, signal_ts, order_id=None):
        self.symbol    = symbol
        self.direction = direction
        self.entry     = entry
        self.stop      = stop
        self.target    = target
        self.size      = size
        self.score     = score
        self.macro_bias= macro_bias
        self.signal_ts = signal_ts
        self.order_id  = order_id
        self.open_ts   = datetime.now(timezone.utc)
        self.risk      = abs(entry - stop)
        self.be_done   = False
        self.trail_done= False
        self.cur_stop  = stop
        self.expected_r= TARGET_RR        # R esperado no backtest
        self.peak_fav  = entry            # preço mais favorável atingido

    def update_trailing(self, high: float, low: float) -> Optional[str]:
        """Actualiza trailing stop. Retorna 'WIN'/'LOSS' se fechar, None caso contrário.
        trail_mult: score alto (≥0.65) usa 0.7× risco de trail → segura winners mais tempo.
        """
        trail_mult = 0.7 if self.score >= 0.65 else 0.5
        if self.direction == "BULLISH":
            self.peak_fav = max(self.peak_fav, high)
            if not self.be_done and high >= self.entry + self.risk:
                self.cur_stop = self.entry; self.be_done = True
                log.debug(f"  {self.symbol} BE atingido @ {high:.6f}")
            if self.be_done and high >= self.entry + 1.5 * self.risk:
                self.cur_stop = max(self.cur_stop, high - trail_mult * self.risk)
                self.trail_done = True
            elif self.trail_done:
                self.cur_stop = max(self.cur_stop, high - trail_mult * self.risk)
            if low <= self.cur_stop:
                return "WIN" if self.cur_stop >= self.entry else "LOSS"
            if high >= self.target:
                return "WIN"
        else:
            self.peak_fav = min(self.peak_fav, low)
            if not self.be_done and low <= self.entry - self.risk:
                self.cur_stop = self.entry; self.be_done = True
                log.debug(f"  {self.symbol} BE atingido @ {low:.6f}")
            if self.be_done and low <= self.entry - 1.5 * self.risk:
                self.cur_stop = min(self.cur_stop, low + trail_mult * self.risk)
                self.trail_done = True
            elif self.trail_done:
                self.cur_stop = min(self.cur_stop, low + trail_mult * self.risk)
            if high >= self.cur_stop:
                return "WIN" if self.cur_stop <= self.entry else "LOSS"
            if low <= self.target:
                return "WIN"
        return None

    def to_dict(self):
        return {k: str(v) if isinstance(v, datetime) else v
                for k, v in self.__dict__.items()}

# ── KILL-SWITCH ───────────────────────────────────────────────
class KillSwitch:
    """
    Kill-switch estatístico de 3 camadas:
      1. Expectância rolling < 0  (edge morreu)
      2. WR rolling < 45%         (edge deteriorou)
      3. DD actual > 12%          (capital em risco)
    """
    def __init__(self):
        self.trade_history: list = []
        self.account = ACCOUNT_SIZE
        self.peak    = ACCOUNT_SIZE
        self.active  = False
        self.reason  = ""

    def record(self, pnl: float, result: str):
        self.account += pnl
        self.peak = max(self.peak, self.account)
        self.trade_history.append({"pnl": pnl, "result": result,
                                   "ts": datetime.now().isoformat()})

    def check(self) -> tuple[bool, str]:
        """Retorna (triggered, reason). Se triggered → reduzir/pausar trading."""
        if len(self.trade_history) < 5:
            return False, ""

        # fast-DD: últimas KS_FAST_DD_N trades com perda acelerada
        fast = self.trade_history[-KS_FAST_DD_N:]
        fast_sum = sum(t["pnl"] for t in fast)
        fast_threshold = -KS_FAST_DD_MULT * ACCOUNT_SIZE * BASE_RISK
        if fast_sum < fast_threshold:
            return True, f"Fast-DD {fast_sum:.2f} em {KS_FAST_DD_N} trades"

        if len(self.trade_history) < 10:
            return False, ""

        recent = self.trade_history[-KS_WINDOW:]
        pnls   = [t["pnl"] for t in recent]
        wins   = sum(1 for t in recent if t["result"] == "WIN")

        exp = sum(pnls) / len(pnls)
        wr  = wins / len(recent)
        dd  = (self.peak - self.account) / self.peak if self.peak > 0 else 0.0

        if dd >= KS_DD_TRIGGER:
            return True, f"DD {dd*100:.1f}% >= {KS_DD_TRIGGER*100:.0f}%"
        if exp < KS_MIN_EXPECTANCY and len(recent) >= KS_WINDOW:
            return True, f"Expectância {exp:.2f} < {KS_MIN_EXPECTANCY}"
        if wr < KS_MIN_WR and len(recent) >= KS_WINDOW:
            return True, f"WR {wr*100:.1f}% < {KS_MIN_WR*100:.0f}%"
        return False, ""

    def status(self) -> dict:
        recent = self.trade_history[-KS_WINDOW:]
        if not recent: return {"ok": True}
        pnls = [t["pnl"] for t in recent]
        wins = sum(1 for t in recent if t["result"] == "WIN")
        dd   = (self.peak - self.account) / self.peak * 100 if self.peak > 0 else 0.0
        return {
            "ok":          not self.active,
            "exp":         round(sum(pnls)/len(pnls), 2) if pnls else 0,
            "wr":          round(wins/len(recent)*100, 1) if recent else 0,
            "dd_pct":      round(dd, 2),
            "n_trades":    len(self.trade_history),
            "account":     round(self.account, 2),
        }

# ── EXECUTION DRIFT ───────────────────────────────────────────
class ExecutionDrift:
    """
    Compara R-multiple real vs esperado por trade.
    Detecta slippage oculto, fees inesperadas, latência de execução.
    ALERT se drift_médio < KS_DRIFT_TRIGGER (-0.25R).
    """
    def __init__(self):
        self.records: list = []

    def record(self, symbol, expected_r: float, real_r: float,
               expected_entry: float, real_entry: float):
        drift = real_r - expected_r
        slip  = abs(real_entry - expected_entry) / max(expected_entry, 1e-8)
        self.records.append({
            "symbol": symbol, "ts": datetime.now().isoformat(),
            "expected_r": round(expected_r, 4),
            "real_r":     round(real_r, 4),
            "drift":      round(drift, 4),
            "slip_pct":   round(slip * 100, 4),
        })

    def summary(self) -> dict:
        if not self.records: return {}
        recent = self.records[-DRIFT_WINDOW:]
        drifts = [r["drift"] for r in recent]
        slips  = [r["slip_pct"] for r in recent]
        mean_d = sum(drifts) / len(drifts)
        alert  = mean_d < KS_DRIFT_TRIGGER
        return {
            "n":           len(self.records),
            "drift_mean":  round(mean_d, 4),
            "drift_std":   round((sum((d-mean_d)**2 for d in drifts)/max(len(drifts)-1,1))**0.5, 4),
            "slip_mean_pct": round(sum(slips)/len(slips), 4),
            "alert":       alert,
            "alert_msg":   f"Execution drift {mean_d:.3f}R < {KS_DRIFT_TRIGGER}R — EDGE DEGRADADO" if alert else "",
        }

# ── CANDLE BUFFER ─────────────────────────────────────────────
class CandleBuffer:
    """Rolling window de candles por símbolo. Thread-safe via asyncio."""
    def __init__(self):
        self._data: dict[str, list] = defaultdict(list)  # symbol → list of OHLCV dicts

    def seed(self, symbol: str, df: pd.DataFrame):
        """Inicializa com dados históricos do REST."""
        recs = df.to_dict("records")
        self._data[symbol] = recs[-CANDLE_BUFFER_N:]

    def push(self, symbol: str, candle: dict):
        """Adiciona candle fechado. Mantém rolling window."""
        buf = self._data[symbol]
        buf.append(candle)
        if len(buf) > CANDLE_BUFFER_N:
            buf.pop(0)

    def to_df(self, symbol: str) -> Optional[pd.DataFrame]:
        buf = self._data.get(symbol, [])
        if len(buf) < 100: return None
        df = pd.DataFrame(buf)
        df["time"] = pd.to_datetime(df["time"])
        for col in ("open","high","low","close","vol","tbb"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df.sort_values("time").reset_index(drop=True)

    def ready(self, symbol: str) -> bool:
        return len(self._data.get(symbol, [])) >= 300

# ── ORDER MANAGER ─────────────────────────────────────────────
class OrderManager:
    """
    Paper mode: simula fills com slippage realista.
    Testnet: Binance Futures Testnet (testnet.binancefuture.com)
    Demo:    Binance Futures Demo    (demo-fapi.binance.com)
    Live:    execução real Binance Futures mainnet
    """
    def __init__(self, paper: bool = True):
        self.paper  = paper
        self.client = None
        if not paper:
            self._init_client()

    def _mode(self) -> str:
        if DEMO_MODE:    return "demo"
        if TESTNET_MODE: return "testnet"
        if LIVE_MODE:    return "live"
        return "paper"

    def _init_client(self):
        try:
            from binance.client import Client
            mode = self._mode()

            if mode == "testnet":
                api_key, api_secret = _load_keys("testnet")
                self.client = Client(api_key, api_secret, testnet=True)
                log.info("Binance client — TESTNET (testnet.binancefuture.com)")

            elif mode == "demo":
                api_key, api_secret = _load_keys("demo")
                self.client = Client(api_key, api_secret, testnet=False)
                # Override futures URL para o endpoint demo (base_url não suportado na versão actual)
                self.client.FUTURES_URL        = "https://demo-fapi.binance.com/fapi/v1"
                self.client.FUTURES_DATA_URL   = "https://demo-fapi.binance.com/futures/data"
                self.client.FUTURES_COIN_URL   = "https://demo-fapi.binance.com/dapi/v1"
                log.info("Binance client — DEMO (demo-fapi.binance.com, capital simulado)")

            else:  # live
                api_key, api_secret = _load_keys("live")
                self.client = Client(api_key, api_secret, testnet=False)
                log.info("Binance client — LIVE (capital real)")

        except SystemExit:
            raise
        except Exception as e:
            log.error(f"Falha ao inicializar Binance client: {e}")
            raise

    async def place_order(self, symbol: str, direction: str,
                          signal_price: float, size: float,
                          stop: float, target: float) -> dict:
        """
        Coloca ordem de mercado. Retorna fill_price, order_id, slippage.
        Paper: usa signal_price + slippage simulado.
        Live: executa via Binance Futures.
        """
        side = "BUY" if direction == "BULLISH" else "SELL"
        slip = PAPER_SLIPPAGE if self.paper else 0.0  # live usa fill real

        if self.paper:
            fill_price = signal_price * (1 + slip if direction == "BULLISH" else 1 - slip)
            fill_price = round(fill_price, 8)
            log.info(f"  PAPER {side} {symbol}  size={size}  fill={fill_price:.6f}  "
                     f"(signal={signal_price:.6f}  slip={slip*100:.3f}%)")
            return {"fill_price": fill_price, "order_id": f"PAPER_{int(time.time())}",
                    "slippage": slip, "status": "FILLED"}
        else:
            try:
                # precision do símbolo (simplificado — idealmente via exchangeInfo)
                qty = round(size, 3)
                order = self.client.futures_create_order(
                    symbol=symbol, side=side, type="MARKET", quantity=qty,
                    reduceOnly=False
                )
                fill_price = float(order.get("avgPrice", signal_price))
                real_slip  = abs(fill_price - signal_price) / signal_price
                log.info(f"  LIVE {side} {symbol}  qty={qty}  fill={fill_price:.6f}  "
                         f"slip={real_slip*100:.4f}%  order_id={order['orderId']}")
                return {"fill_price": fill_price, "order_id": str(order["orderId"]),
                        "slippage": real_slip, "status": order.get("status","?")}
            except Exception as e:
                log.error(f"  Order failed {symbol}: {e}")
                return {"fill_price": signal_price, "order_id": "FAILED",
                        "slippage": 0, "status": "FAILED"}

    async def close_position(self, pos: "Position", exit_price: float) -> dict:
        """Fecha posição. Retorna fill_price real."""
        side = "SELL" if pos.direction == "BULLISH" else "BUY"
        slip = PAPER_SLIPPAGE if self.paper else 0.0

        if self.paper:
            fill = exit_price * (1 - slip if pos.direction == "BULLISH" else 1 + slip)
            log.info(f"  PAPER CLOSE {side} {pos.symbol}  fill={fill:.6f}")
            return {"fill_price": round(fill, 8), "status": "FILLED"}
        else:
            try:
                qty   = round(pos.size, 3)
                order = self.client.futures_create_order(
                    symbol=pos.symbol, side=side, type="MARKET",
                    quantity=qty, reduceOnly=True
                )
                fill = float(order.get("avgPrice", exit_price))
                return {"fill_price": fill, "status": order.get("status","?")}
            except Exception as e:
                log.error(f"  Close failed {pos.symbol}: {e}")
                return {"fill_price": exit_price, "status": "FAILED"}

# ── SIGNAL ENGINE ─────────────────────────────────────────────
class SignalEngine:
    """
    Adapta a lógica do scan_symbol para streaming (1 candle de cada vez).
    Near-miss tracking: regista último motivo de rejeição por símbolo.
    """
    def __init__(self, buffer: CandleBuffer):
        self.buffer    = buffer
        self.cooldown: dict[str, float] = {}
        self.last_veto: dict[str, dict] = {}   # symbol → último veto

    def _build_df(self, symbol: str, htf_dfs: dict = None):
        df = self.buffer.to_df(symbol)
        if df is None: return None
        df = indicators(df); df = swing_structure(df); df = omega(df)
        if htf_dfs and MTF_ENABLED:
            df = merge_all_htf_to_ltf(df, htf_dfs)
        return df

    def _veto(self, symbol: str, reason: str, score: float = 0.0,
              thresh: float = 0.0, extra: str = "") -> None:
        near = score >= thresh * 0.90 and thresh > 0
        self.last_veto[symbol] = {
            "reason": reason, "score": round(score,3),
            "thresh": round(thresh,3), "near": near,
            "extra": extra, "ts": datetime.now().strftime("%H:%M:%S"),
        }
        if near:
            log.info(f"  ~ NEAR-MISS {symbol:12s}  score={score:.3f} (thresh={thresh:.3f})  {reason}  {extra}")

    def check_signal(self, symbol: str, macro_series, corr: dict,
                     open_positions: list, htf_dfs: dict = None,
                     account: float = ACCOUNT_SIZE, peak_equity: float = None):
        now = time.time()
        is_chop_trade = False
        chop_bb_mid   = None
        if now - self.cooldown.get(symbol, 0) < SIGNAL_COOLDOWN_S:
            return None
        df = self._build_df(symbol, htf_dfs)
        if df is None or len(df) < 200: return None
        idx = len(df) - 2
        if idx < 200: return None
        row = df.iloc[idx]

        # ── ESTRUTURA E DIRECÇÃO ──────────────────────────────
        struct     = str(row.get("trend_struct", "NEUTRAL"))
        struct_str = float(row.get("struct_strength", 0))
        if struct_str < REGIME_MIN_STRENGTH:
            self._veto(symbol, "struct_fraca", 0, 0, f"sstr={struct_str:.2f}"); return None

        rsi  = float(row.get("rsi", 50))
        s21  = float(row.get("slope21",  0) or 0)
        s200 = float(row.get("slope200", 0) or 0)

        # fix #3 — CHOP detection idêntico ao decide_direction() do backtest
        is_chop_market = abs(s21) < CHOP_S21 and abs(s200) < CHOP_S200 and struct_str <= 0.70

        if is_chop_market:
            # fix #2 — CHOP MR path: score_chop() → calc_levels_chop()
            chop_dir, chop_score, chop_info = score_chop(row)
            if chop_dir is None or chop_score < 0.30:
                self._veto(symbol, "chop_sem_extremo", 0, 0,
                           f"s21={s21:.3f} s200={s200:.3f}"); return None

            direction     = chop_dir
            is_chop_trade = True
            score         = chop_score
            chop_bb_mid   = chop_info.get("bb_mid")
            self._veto(symbol, "", 0, 0)   # limpa veto — pode entrar
        else:
            is_chop_trade = False
            chop_bb_mid   = None
            if struct == "UP" and rsi > 50:      direction = "BULLISH"
            elif struct == "DOWN" and rsi < 50:  direction = "BEARISH"
            else:
                self._veto(symbol, "direcao_indefinida", 0, 0,
                           f"struct={struct} rsi={rsi:.1f}"); return None

        # score_omega() — só para trades de tendência (não CHOP)
        if not is_chop_trade:
            score, comps = score_omega(row, direction)
            weak = [k for k,v in comps.items() if v < OMEGA_MIN_COMPONENT]
            if len(weak) >= 3:
                self._veto(symbol, "comp_fraco", score, 0, f"weak={weak}"); return None

        macro_b = "CHOP"
        if macro_series is not None and idx < len(macro_series):
            macro_b = macro_series.iloc[idx]

        # ── FILTRO DE VELOCIDADE DE MERCADO ──────────────────
        # mercado lento (range_pct médio < SPEED_MIN) → sem edge direcional
        if "high" in df.columns and "low" in df.columns:
            range_pct = ((df["high"] - df["low"]) / df["close"]).rolling(SPEED_WINDOW).mean()
            speed = float(range_pct.iloc[idx]) if not pd.isna(range_pct.iloc[idx]) else 1.0
            if speed < SPEED_MIN:
                self._veto(symbol, "mercado_lento", score, 0, f"speed={speed:.4f}<{SPEED_MIN}"); return None

        # ── FILTRO DE SESSÃO (horário UTC) ───────────────────
        if SESSION_BLOCK_ACTIVE:
            utc_hour = datetime.now(timezone.utc).hour
            if utc_hour in SESSION_BLOCK_HOURS:
                self._veto(symbol, "sessao_baixa_liquidez", score, 0,
                           f"hora={utc_hour}h UTC"); return None

        # fix #2a — VOL HIGH +0.05 threshold
        vol_r = str(row.get("vol_regime", "NORMAL"))
        base_thresh = SCORE_BY_REGIME.get(macro_b, SCORE_THRESHOLD)
        thresh = base_thresh + 0.05 if vol_r == "HIGH" else base_thresh

        if score < thresh:
            self._veto(symbol, "score_baixo", score, thresh, f"macro={macro_b} vol={vol_r}"); return None

        if macro_b == "BEAR" and direction == "BULLISH":
            self._veto(symbol, "macro_bear_veto_long", score, thresh); return None
        if macro_b == "BULL" and direction == "BEARISH":
            self._veto(symbol, "macro_bull_veto_short", score, thresh); return None

        # fix #1a — pullback mínimo em BULL long
        if macro_b == "BULL" and direction == "BULLISH":
            dist = float(row.get("dist_ema21", 0) or 0)
            if dist < BULL_LONG_MIN_PULLBACK_ATR:
                self._veto(symbol, "bull_no_pullback", score, thresh,
                           f"dist={dist:.3f}<{BULL_LONG_MIN_PULLBACK_ATR}"); return None

        if VOL_RISK_SCALE.get(vol_r, 1.0) == 0.0:
            self._veto(symbol, "vol_extreme", score, thresh, f"vol={vol_r}"); return None

        active_syms = [p.symbol for p in open_positions]
        ok_port, motivo, corr_mult = portfolio_allows(symbol, active_syms, corr)
        if not ok_port:
            self._veto(symbol, "corr_block", score, thresh, f"motivo={motivo}"); return None

        if len(open_positions) >= MAX_OPEN_LIVE:
            self._veto(symbol, "max_posicoes", score, thresh,
                       f"{len(open_positions)}/{MAX_OPEN_LIVE}"); return None

        # níveis — CHOP usa alvo BB mid, stop mais apertado
        if is_chop_trade:
            levels = calc_levels_chop(df, idx, direction, chop_bb_mid)
        else:
            levels = calc_levels(df, idx, direction)
        if levels is None:
            self._veto(symbol, "niveis_invalidos", score, thresh); return None
        entry_signal, stop, target, rr = levels
        if rr < 1.5:
            self._veto(symbol, "rr_baixo", score, thresh, f"rr={rr:.2f}"); return None

        # entry com slippage
        entry_price = float(df["close"].iloc[idx])
        slip = SLIPPAGE + SPREAD
        entry_price *= (1 + slip if direction == "BULLISH" else 1 - slip)

        # fix #3a — dd_scale dinâmico
        pk = peak_equity if peak_equity else account
        current_dd = (pk - account) / pk if pk > 0 else 0.0
        dd_scale = 1.0
        for dd_thresh in sorted(DD_RISK_SCALE.keys(), reverse=True):
            if current_dd >= dd_thresh:
                dd_scale = DD_RISK_SCALE[dd_thresh]; break
        if dd_scale == 0.0:
            self._veto(symbol, "dd_pause", score, thresh, f"dd={current_dd:.1%}"); return None

        # fix #3c — trans_mult
        trans = bool(row.get("regime_transition", False))
        trans_mult = REGIME_TRANS_SIZE_MULT if trans else 1.0

        # fix #3b+3d — account real + peak_equity
        size = position_size(account, entry_price, stop, score,
                             macro_b, direction, vol_r, dd_scale,
                             is_chop_trade=is_chop_trade, peak_equity=peak_equity)
        size = round(size * corr_mult * trans_mult, 4)
        if size <= 0:
            self._veto(symbol, "size_zero", score, thresh); return None

        return size, score, direction, entry_price, stop, target, rr, macro_b, vol_r, corr_mult, struct, is_chop_trade

    def build_signal_dict(self, symbol, size, score, direction, entry_price,
                          stop, target, rr, macro_b, vol_r, corr_mult, struct,
                          symbol_pnl: dict, drift_summary: dict,
                          is_chop_trade: bool = False) -> Optional[dict]:
        """Aplica symbol rank block e drift size penalty, devolve sinal final."""
        # symbol rank block — bloqueia símbolo com histórico recente negativo
        recent_pnl = symbol_pnl.get(symbol, [])[-SYMBOL_RANK_WINDOW:]
        if len(recent_pnl) >= 10 and sum(recent_pnl) < SYMBOL_BLOCK_THRESH:
            self._veto(symbol, "symbol_rank_block", score, 0,
                       f"pnl_{len(recent_pnl)}t={sum(recent_pnl):.1f}")
            return None

        # drift size penalty — execução a degradar o edge
        drift_mult = 1.0
        if drift_summary.get("n", 0) >= 10:
            dm = drift_summary.get("drift_mean", 0)
            if dm < DRIFT_SIZE_PENALTY:
                drift_mult = 0.80
                log.debug(f"  drift penalty {symbol}: drift_mean={dm:.3f} → size × 0.80")

        final_size = round(size * drift_mult, 4)
        if final_size <= 0:
            self._veto(symbol, "size_zero_after_penalty", score, 0); return None

        return {
            "symbol":    symbol,
            "direction": direction,
            "entry":     round(entry_price, 8),
            "stop":      round(stop, 8),
            "target":    round(target, 8),
            "size":      final_size,
            "score":     round(score, 4),
            "rr":        round(rr, 3),
            "macro":     macro_b,
            "vol_regime":vol_r,
            "corr_mult": round(corr_mult, 3),
            "struct":    struct,
            "is_chop":   is_chop_trade,
            "signal_ts": datetime.now(timezone.utc).isoformat(),
        }

# ── LIVE ENGINE ───────────────────────────────────────────────
class LiveEngine:
    """
    Main loop:
      1. Seed candles via REST
      2. WebSocket para updates em tempo real
      3. A cada candle fechado: check signal + update posições + risk
      4. Dashboard e logs contínuos
    """
    def __init__(self):
        self.buffer    = CandleBuffer()
        self.signal_e  = SignalEngine(self.buffer)
        self.orders    = OrderManager(paper=(not LIVE_MODE and not TESTNET_MODE and not DEMO_MODE))
        self.kill_sw   = KillSwitch()
        self.drift     = ExecutionDrift()
        self.positions: list[Position] = []
        self.closed_trades: list = []
        self.macro_series: Optional[pd.Series] = None
        self.corr: dict = {}
        self.htf_dfs: dict = {}
        self.running   = False
        self._last_hb  = time.time()
        self._ws_tasks: list = []
        # ── tracking para paridade com backtest ──────────────────────
        self.account            = ACCOUNT_SIZE    # actualizado a cada close
        self.peak_equity        = ACCOUNT_SIZE    # para CONVEX_ALPHA
        self.consecutive_losses = 0
        self.streak_cooldown_until: float = 0
        self.sym_loss_ts: dict[str, float] = {}
        self._btc_candle_count  = 0                    # throttle para corr refresh
        self._symbol_pnl: dict[str, list] = {}         # symbol → lista de PnLs recentes
        _mode_lbl = "DEMO" if DEMO_MODE else "TESTNET" if TESTNET_MODE else "LIVE" if LIVE_MODE else "PAPER"
        log.info(f"LiveEngine init — {_mode_lbl} mode — {LIVE_RUN_ID}")
        self.telegram = TelegramNotifier(self)
        self._tg_tick = 0

    # ── SEED ──────────────────────────────────────────────────
    async def seed(self):
        """Carrega dados históricos para todos os símbolos."""

        # ── verifica conexão com Binance API (DEMO/TESTNET/LIVE) ──────
        if not self.orders.paper:
            await self._verify_api_connection()

        log.info("Seeding candles via REST...")
        fetch_syms = list(SYMBOLS)
        if MACRO_SYMBOL not in fetch_syms: fetch_syms.insert(0, MACRO_SYMBOL)

        use_futures_feed = (DEMO_MODE or TESTNET_MODE or LIVE_MODE)
        all_dfs = fetch_all(fetch_syms, n_candles=CANDLE_BUFFER_N + 50,
                            futures=use_futures_feed)
        feed_label = "fapi (perp futures)" if use_futures_feed else "api (spot)"
        log.info(f"Feed de dados: {feed_label}")
        for sym, df in all_dfs.items():
            validate(df, sym)
            self.buffer.seed(sym, df)
            log.info(f"  {sym:12s}  {len(df)} candles  "
                     f"{df['time'].iloc[0].date()} → {df['time'].iloc[-1].date()}")

        # HTF seed
        if MTF_ENABLED:
            for tf in HTF_STACK:
                nc = HTF_N_CANDLES_MAP.get(tf, 300)
                htf_raw = fetch_all(list(all_dfs.keys()), interval=tf, n_candles=nc)
                for sym, df_h in htf_raw.items():
                    df_h = prepare_htf(df_h, htf_interval=tf)
                    self.htf_dfs.setdefault(sym, {})[tf] = df_h

        # Macro + correlação
        self.macro_series = detect_macro(all_dfs)
        self.corr         = build_corr_matrix(all_dfs)
        log.info(f"Seed completo — {len(all_dfs)} símbolos")

    async def _verify_api_connection(self):
        """Verifica conexão com Binance API e mostra saldo da conta."""
        import hmac, hashlib
        mode = self.orders._mode()
        sep  = "─" * 60

        base_url = {
            "demo":    "https://demo-fapi.binance.com",
            "testnet": "https://testnet.binancefuture.com",
            "live":    "https://fapi.binance.com",
        }.get(mode, "https://fapi.binance.com")

        try:
            api_key, api_secret = _load_keys(mode)
            loop = asyncio.get_running_loop()

            def _call():
                ts     = int(time.time() * 1000)
                params = f"timestamp={ts}"
                sig    = hmac.new(
                    api_secret.encode(), params.encode(), hashlib.sha256
                ).hexdigest()
                url = f"{base_url}/fapi/v2/balance?{params}&signature={sig}"
                r   = requests.get(url, headers={"X-MBX-APIKEY": api_key}, timeout=10)
                return r.json()

            data = await loop.run_in_executor(None, _call)

            # server time lag
            def _ping():
                r = requests.get(f"{base_url}/fapi/v1/time", timeout=5)
                return r.json()
            st   = await loop.run_in_executor(None, _ping)
            lag  = int(time.time() * 1000) - st.get("serverTime", int(time.time()*1000))

            usdt = next((b for b in data if isinstance(b, dict) and b.get("asset") == "USDT"), None)

            print(f"\n  {sep}")
            print(f"  ✓ API Binance conectada  [{mode.upper()}]")
            print(f"  Endpoint        : {base_url}")
            print(f"  Server time lag : {lag:+d} ms")
            if usdt:
                balance = float(usdt.get("balance", 0))
                avail   = float(usdt.get("availableBalance", balance))
                unrl    = float(usdt.get("crossUnPnl", 0))
                print(f"  {'─'*40}")
                print(f"  Saldo USDT      : ${balance:>12,.2f}")
                print(f"  Disponível      : ${avail:>12,.2f}")
                if unrl != 0:
                    print(f"  Unrealized PnL  : ${unrl:>+12,.2f}")

                # sincroniza ACCOUNT_SIZE com saldo real — position_size() usa este valor
                if balance > 0:
                    import backtest as _bk_sync
                    _bk_sync.ACCOUNT_SIZE = balance
                    self.account      = balance
                    self.peak_equity  = balance
                    self.kill_sw.account = balance
                    self.kill_sw.peak    = balance
                    print(f"  Conta ajustada  : ${balance:>12,.2f}  ← position sizing sincronizado")
                    log.info(f"API OK [{mode.upper()}] lag={lag:+d}ms  saldo=${balance:,.2f} USDT  "
                             f"[ACCOUNT_SIZE sincronizado]")
                else:
                    log.info(f"API OK [{mode.upper()}] lag={lag:+d}ms  saldo=$0 (verifica margem)")
            elif isinstance(data, dict) and data.get("code"):
                print(f"  ⚠  API respondeu: {data}")
                log.warning(f"API respondeu com erro: {data}")
            else:
                print(f"  Saldo USDT não encontrado — verifica permissões da key")
            print(f"  {sep}\n")

        except Exception as e:
            print(f"\n  {sep}")
            print(f"  ⚠  Falha na verificação de API [{mode.upper()}]: {e}")
            print(f"  Verifica se a key tem permissão 'Enable Futures'")
            print(f"  {sep}\n")
            log.warning(f"API verify falhou: {e}")

    # ── POSIÇÕES ──────────────────────────────────────────────
    async def _open_position(self, sig: dict):
        """Abre posição a partir de sinal."""
        fill = await self.orders.place_order(
            sig["symbol"], sig["direction"],
            sig["entry"], sig["size"],
            sig["stop"], sig["target"]
        )
        if fill["status"] == "FAILED": return

        real_entry = fill["fill_price"]
        pos = Position(
            symbol    = sig["symbol"],
            direction = sig["direction"],
            entry     = real_entry,
            stop      = sig["stop"],
            target    = sig["target"],
            size      = sig["size"],
            score     = sig["score"],
            macro_bias= sig["macro"],
            signal_ts = sig["signal_ts"],
            order_id  = fill["order_id"],
        )
        self.positions.append(pos)

        # regista slippage de entrada — real_r será actualizado no _close_position
        self.drift.record(
            sig["symbol"],
            expected_r     = sig["rr"],
            real_r         = 0.0,           # placeholder — actualizado no close
            expected_entry = sig["entry"],
            real_entry     = real_entry,
        )
        tlog.info(f"OPEN  {sig['direction']:8s} {sig['symbol']:12s}  "
                  f"entry={real_entry:.6f}  stop={sig['stop']:.6f}  "
                  f"target={sig['target']:.6f}  size={sig['size']}  "
                  f"score={sig['score']:.3f}  rr={sig['rr']:.2f}")
        await self.telegram.notify_open(sig, real_entry)

    async def _close_position(self, pos: Position, result: str, exit_price: float):
        """Fecha posição, calcula PnL real, actualiza kill-switch e drift."""
        fill = await self.orders.close_position(pos, exit_price)
        real_exit = fill["fill_price"]

        slip_exit = (random.uniform(0.5, 1.2) * PAPER_SLIPPAGE
                     if not LIVE_MODE and not TESTNET_MODE
                     else abs(real_exit - exit_price) / max(exit_price, 1e-8))
        if pos.direction == "BULLISH":
            entry_c = pos.entry * (1 + COMMISSION)
            exit_c  = real_exit * (1 - COMMISSION - slip_exit)
            funding = -(pos.size * pos.entry * FUNDING_PER_8H *
                        (datetime.now(timezone.utc) - pos.open_ts).total_seconds() / 3600 / 8)
            pnl = round((pos.size * (exit_c - entry_c) + funding) * LEVERAGE, 2)
        else:
            entry_c = pos.entry * (1 - COMMISSION)
            exit_c  = real_exit * (1 + COMMISSION + slip_exit)
            funding = +(pos.size * pos.entry * FUNDING_PER_8H *
                        (datetime.now(timezone.utc) - pos.open_ts).total_seconds() / 3600 / 8)
            pnl = round((pos.size * (entry_c - exit_c) + funding) * LEVERAGE, 2)

        # R-multiple real
        risk_usd  = abs(pos.entry - pos.stop) * pos.size
        real_r    = pnl / risk_usd if risk_usd > 0 else 0.0

        self.kill_sw.record(pnl, result)

        # actualiza account e peak_equity (para dd_scale e CONVEX_ALPHA)
        self.account    += pnl
        self.peak_equity = max(self.peak_equity, self.account)

        # streak / sym_loss cooldown
        if result == "LOSS":
            self.consecutive_losses += 1
            self.sym_loss_ts[pos.symbol] = time.time()
            candle_dur = 15 * 60
            for n_loss in sorted(STREAK_COOLDOWN.keys(), reverse=True):
                if self.consecutive_losses >= n_loss:
                    cd_candles = STREAK_COOLDOWN[n_loss]
                    self.streak_cooldown_until = time.time() + cd_candles * candle_dur
                    log.warning(f"  STREAK {self.consecutive_losses} losses → cooldown {cd_candles} candles")
                    break
        else:
            self.consecutive_losses = 0

        # symbol PnL rolling (para symbol rank block)
        self._symbol_pnl.setdefault(pos.symbol, []).append(pnl)
        if len(self._symbol_pnl[pos.symbol]) > SYMBOL_RANK_WINDOW * 2:
            self._symbol_pnl[pos.symbol] = self._symbol_pnl[pos.symbol][-SYMBOL_RANK_WINDOW:]

        trade = {
            "symbol":    pos.symbol, "direction": pos.direction,
            "entry":     pos.entry,  "exit":      real_exit,
            "stop":      pos.stop,   "target":    pos.target,
            "size":      pos.size,   "score":     pos.score,
            "result":    result,     "pnl":       pnl,
            "real_r":    round(real_r, 3),
            "expected_r":round(pos.expected_r, 3),
            "drift_r":   round(real_r - pos.expected_r, 3),
            "account":   round(self.account, 2),
            "open_ts":   pos.open_ts.isoformat(),
            "close_ts":  datetime.now(timezone.utc).isoformat(),
        }
        self.closed_trades.append(trade)

        icon = "WIN  ✓" if result == "WIN" else "LOSS ✗"
        tlog.info(f"{icon} {pos.symbol:12s}  pnl=${pnl:>+8.2f}  "
                  f"R={real_r:>+5.2f}  drift={real_r - pos.expected_r:>+5.2f}R  "
                  f"account=${self.account:,.2f}")

        self.positions = [p for p in self.positions if p is not pos]

        # actualiza drift record com R-multiple real (corrige o placeholder da abertura)
        for rec in reversed(self.drift.records):
            if rec["symbol"] == pos.symbol and rec.get("real_r") == 0.0:
                rec["real_r"] = round(real_r, 4)
                rec["drift"]  = round(real_r - pos.expected_r, 4)
                break
        self._save_state()
        await self.telegram.notify_close(trade)

        # alerta de drift
        drift_sum = self.drift.summary()
        if drift_sum.get("alert"):
            log.warning(f"  ⚠ {drift_sum['alert_msg']}")

        return trade

    # ── CANDLE HANDLER ────────────────────────────────────────
    async def on_candle_close(self, symbol: str, candle: dict):
        """Processa candle fechado: actualiza posições + verifica sinal."""
        self.buffer.push(symbol, candle)

        # recalcula macro a cada candle BTC; corr só a cada CORR_REFRESH_CANDLES
        if symbol == MACRO_SYMBOL:
            self._btc_candle_count += 1
            try:
                all_dfs_now = {s: self.buffer.to_df(s)
                               for s in [MACRO_SYMBOL] + list(SYMBOLS)
                               if self.buffer.to_df(s) is not None}
                self.macro_series = detect_macro(all_dfs_now)
                if self._btc_candle_count % CORR_REFRESH_CANDLES == 0:
                    self.corr = build_corr_matrix(all_dfs_now)
            except Exception as e:
                log.debug(f"  macro refresh erro: {e}")

        # 1. Update posições abertas com trailing stop
        high = candle["high"]; low = candle["low"]
        for pos in list(self.positions):
            if pos.symbol != symbol: continue
            result = pos.update_trailing(high, low)
            if result:
                exit_p = pos.cur_stop if result == "LOSS" else (
                    candle["high"] if pos.direction == "BULLISH" else candle["low"])
                await self._close_position(pos, result, exit_p)

        # 2. Kill-switch check
        ks_triggered, ks_reason = self.kill_sw.check()
        if ks_triggered:
            log.warning(f"  KILL-SWITCH: {ks_reason} — novos sinais bloqueados")
            await self.telegram.notify_killswitch(ks_reason)
            return

        # 3. Streak / sym_loss cooldown
        now_ts = time.time()
        if now_ts < self.streak_cooldown_until:
            remaining = int(self.streak_cooldown_until - now_ts) // 60
            self.signal_e._veto(symbol, f"streak_cooldown ({remaining}min restantes)")
            return
        if symbol in self.sym_loss_ts:
            candles_since = (now_ts - self.sym_loss_ts[symbol]) / (15*60)
            if candles_since < SYM_LOSS_COOLDOWN:
                self.signal_e._veto(symbol, f"sym_loss_cooldown ({SYM_LOSS_COOLDOWN - int(candles_since)}c restantes)")
                return

        # 4. Verifica sinal para este símbolo
        if not self.buffer.ready(symbol): return

        result_tuple = self.signal_e.check_signal(
            symbol, self.macro_series, self.corr,
            self.positions, self.htf_dfs.get(symbol),
            account=self.account, peak_equity=self.peak_equity,
        )
        if result_tuple:
            size, score, direction, entry_price, stop, target, rr, macro_b, vol_r, corr_mult, struct, is_chop = result_tuple
            sig = self.signal_e.build_signal_dict(
                symbol, size, score, direction, entry_price,
                stop, target, rr, macro_b, vol_r, corr_mult, struct,
                self._symbol_pnl, self.drift.summary(),
                is_chop_trade=is_chop,
            )
            if sig:
                self.signal_e.cooldown[symbol] = time.time()
                self.signal_e.last_veto.pop(symbol, None)
                await self._open_position(sig)

        # 5. Heartbeat
        if time.time() - self._last_hb > HEARTBEAT_EVERY:
            self._heartbeat()

    # ── DASHBOARD ─────────────────────────────────────────────
    def _symbol_state(self, symbol: str) -> dict:
        """Calcula estado actual completo de um símbolo a partir do buffer."""
        try:
            df = self.buffer.to_df(symbol)
            if df is None or len(df) < 50: return {}
            df = indicators(df); df = swing_structure(df); df = omega(df)
            row = df.iloc[-1]
            score = float(row.get("omega_score", 0) if "omega_score" in df.columns else
                          row.get("omega_struct",0) + row.get("omega_flow",0))
            return {
                "close":   float(df["close"].iloc[-1]),
                "rsi":     float(row.get("rsi", 0) or 0),
                "struct":  str(row.get("trend_struct", "?")),
                "sstr":    float(row.get("struct_strength", 0) or 0),
                "s200":    float(row.get("slope200", 0) or 0),
                "s21":     float(row.get("slope21", 0) or 0),
                "vol":     str(row.get("vol_regime", "?")),
                "score":   score,
                "taker":   float(row.get("taker_ma", 0.5) or 0.5),
                "casc_up": int(row.get("casc_up", 0) or 0),
                "casc_dn": int(row.get("casc_down", 0) or 0),
                "dist21":  float(row.get("dist_ema21", 0) or 0),
                "atr_pct": float(row.get("atr_pct", 0) or 0),
            }
        except Exception:
            return {}

    async def _status_ticker(self):
        """Dashboard ao vivo: macro + por símbolo + posições a cada 30s."""
        SEP = "─" * 76
        while self.running:
            await asyncio.sleep(30)
            if not self.running: break

            # tempo até próximo candle 15m
            now_s     = time.time()
            remaining = int(15*60 - now_s % (15*60))
            mm, ss    = divmod(remaining, 60)
            now_str   = datetime.now().strftime("%H:%M:%S")

            # sessão
            n_done  = len(self.closed_trades)
            wins    = sum(1 for t in self.closed_trades if t["result"] == "WIN")
            wr_str  = f"{wins/n_done*100:.0f}%" if n_done else "—"
            pnl     = sum(t["pnl"] for t in self.closed_trades)
            ks      = self.kill_sw.status()
            ks_str  = "OK ✓" if ks.get("ok") else "⚠ TRIGGERED"
            dd_str  = f"{ks.get('dd_pct',0):.1f}%"
            mode    = ("DEMO" if DEMO_MODE else "TESTNET" if TESTNET_MODE else
                       "LIVE" if LIVE_MODE else "PAPER")

            # macro BTC
            btc_state = self._symbol_state(MACRO_SYMBOL)
            s200_btc  = btc_state.get("s200", 0)
            macro_lbl = ("BULL ↑" if s200_btc > MACRO_SLOPE_BULL else
                         "BEAR ↓" if s200_btc < MACRO_SLOPE_BEAR else "CHOP ↔")

            lines = [
                f"",
                f"  {'═'*92}",
                f"  ☿ AURUM {mode}  |  {now_str}  |  próximo candle: {mm:02d}:{ss:02d}",
                f"  Macro BTC: {macro_lbl} (slope200={s200_btc:+.4f})  |  "
                f"trades={n_done}  WR={wr_str}  PnL=${pnl:+.2f}  DD={dd_str}  KS={ks_str}",
                f"  {'─'*92}",
                f"  {'Símbolo':12s}  {'Close':>10s}  {'RSI':>5s}  {'Struct':>9s}  "
                f"{'S200':>7s}  {'Vol':>6s}  {'Taker':>5s}  {'Casc':>4s}  {'Score':>6s}  Sinal / Veto",
                f"  {'─'*92}",
            ]

            for sym in SYMBOLS:
                st = self._symbol_state(sym)
                if not st:
                    lines.append(f"  {sym:12s}  (aguardando dados...)")
                    continue

                rsi_arrow  = "↑" if st["rsi"] > 55 else "↓" if st["rsi"] < 45 else "→"
                struct_str = f"{st['struct'][:4]:4s} {st['sstr']:.2f}"
                taker_str  = f"{st['taker']:.2f}"
                casc_str   = f"{st['casc_up']}↑" if st["struct"] == "UP" else f"{st['casc_dn']}↓"
                score_str  = f"{st['score']:.3f}" if st["score"] > 0.45 else "  —  "
                vol_str    = st["vol"][:6]

                thresh = SCORE_BY_REGIME.get("BEAR" if s200_btc < MACRO_SLOPE_BEAR else
                                             "BULL" if s200_btc > MACRO_SLOPE_BULL else "CHOP",
                                             SCORE_THRESHOLD)
                # sinal flag
                if st["score"] >= thresh:
                    sinal = f" ◄◄ SINAL {st['score']:.3f}≥{thresh:.3f}"
                elif st["score"] >= thresh * 0.95:
                    sinal = f" ~ {st['score']:.3f} (≥{thresh:.3f} falta {thresh-st['score']:.3f})"
                else:
                    # mostrar último veto
                    v = self.signal_e.last_veto.get(sym, {})
                    if v:
                        near_tag = " ~NEAR" if v.get("near") else ""
                        sinal = f" [{v['ts']}]{near_tag} {v['reason']} {v.get('extra','')}"
                    else:
                        sinal = ""

                # posição aberta?
                open_pos = next((p for p in self.positions if p.symbol == sym), None)
                if open_pos:
                    dur  = int((datetime.now(timezone.utc) - open_pos.open_ts).seconds / 60)
                    sinal = f" [POS {open_pos.direction[0]} {dur}min stop={open_pos.cur_stop:.4f}]"

                lines.append(
                    f"  {sym:12s}  {st['close']:>10.4f}  "
                    f"{st['rsi']:>4.1f}{rsi_arrow}  {struct_str:>9s}  "
                    f"{st['s200']:>+7.3f}  {vol_str:>6s}  {taker_str:>5s}  "
                    f"{casc_str:>4s}  {score_str:>6s}{sinal}"
                )

            lines.append(f"  {'─'*92}")

            # near-misses recentes
            nears = [(s,v) for s,v in self.signal_e.last_veto.items() if v.get("near")]
            if nears:
                lines.append(f"  NEAR-MISSES:")
                for s,v in nears:
                    gap = v['thresh'] - v['score']
                    lines.append(f"    {s:12s}  score={v['score']:.3f}  thresh={v['thresh']:.3f}  "
                                 f"falta={gap:.3f}  motivo={v['reason']}  {v.get('extra','')}  @ {v['ts']}")
                lines.append(f"  {'─'*92}")

            # posições abertas detalhadas
            if self.positions:
                lines.append(f"  POSIÇÕES ABERTAS:")
                for p in self.positions:
                    dur = int((datetime.now(timezone.utc) - p.open_ts).seconds / 60)
                    df_p = self.buffer.to_df(p.symbol)
                    curr = float(df_p["close"].iloc[-1]) if df_p is not None else p.entry
                    unrl = (curr - p.entry) * p.size if p.direction == "BULLISH" else \
                           (p.entry - curr) * p.size
                    be   = "✓BE" if p.be_done else ""
                    lines.append(f"    {p.symbol:12s}  {p.direction[0]}  entry={p.entry:.4f}  "
                                 f"now={curr:.4f}  stop={p.cur_stop:.4f}  "
                                 f"unreal=${unrl:+.2f}  {dur}min  {be}")
                lines.append(f"  {'─'*92}")

            print("\n".join(lines))

            # ── Telegram dashboard mirror ─────────────────────
            self._tg_tick += 1
            if self._tg_tick % TG_DASH_EVERY == 0 and self.telegram.enabled:
                tg_lines = [
                    f"☿ <b>AURUM {mode}</b>  {now_str}  candle: {mm:02d}:{ss:02d}",
                    f"BTC: <b>{macro_lbl}</b> (s200={s200_btc:+.4f})",
                    f"Trades: {n_done}  WR: {wr_str}  PnL: <code>${pnl:+.2f}</code>",
                    f"DD: {dd_str}  KS: {'✅' if ks.get('ok') else '🚨 TRIGGERED'}",
                    f"Account: <code>${self.account:,.2f}</code>",
                    f"",
                ]
                # tabela de símbolos em monospace
                tg_sym = []
                for sym in SYMBOLS:
                    st = self._symbol_state(sym)
                    if not st: continue
                    rsi_a = "↑" if st["rsi"] > 55 else "↓" if st["rsi"] < 45 else "→"
                    sc = f"{st['score']:.2f}" if st['score'] > 0.45 else " — "
                    tag = ""
                    op = next((p for p in self.positions if p.symbol == sym), None)
                    if op:
                        tag = f" [POS {op.direction[0]}]"
                    elif st["score"] >= SCORE_THRESHOLD:
                        tag = " ◄◄"
                    tg_sym.append(f"{sym[:8]:8s} {st['close']:>9.4f} {st['rsi']:4.1f}{rsi_a} {st['struct'][:4]:4s} {sc}{tag}")
                if tg_sym:
                    tg_lines.append("<pre>" + "\n".join(tg_sym) + "</pre>")

                # posições
                if self.positions:
                    tg_lines.append(f"\n<b>Posições:</b>")
                    for p in self.positions:
                        dur = int((datetime.now(timezone.utc) - p.open_ts).seconds / 60)
                        df_p = self.buffer.to_df(p.symbol)
                        curr = float(df_p["close"].iloc[-1]) if df_p is not None else p.entry
                        unrl = (curr - p.entry) * p.size if p.direction == "BULLISH" else (p.entry - curr) * p.size
                        ar = "🟢" if p.direction == "BULLISH" else "🔴"
                        tg_lines.append(f"{ar} {p.symbol}  <code>${unrl:+.2f}</code>  {dur}min")

                # near misses
                if nears:
                    tg_lines.append(f"\n⚡ <b>Near-misses:</b>")
                    for s, v in nears:
                        tg_lines.append(f"  {s}  score={v['score']:.3f}  falta={v['thresh']-v['score']:.3f}")

                await self.telegram.send("\n".join(tg_lines))

    async def _ws_listen(self, symbol: str):
        """WebSocket para 1 símbolo. Auto-reconecta."""
        import websockets
        mode_key = "demo" if DEMO_MODE else "testnet" if TESTNET_MODE else "live" if LIVE_MODE else "paper"
        ws_base  = _WS_BASE[mode_key]
        url = f"{ws_base}/ws/{symbol.lower()}@kline_{INTERVAL}"
        while self.running:
            try:
                async with websockets.connect(url, ping_interval=20) as ws:
                    log.debug(f"WS conectado: {symbol}")
                    async for msg in ws:
                        if not self.running: break
                        data = json.loads(msg)
                        k = data.get("k", {})
                        if not k.get("x", False): continue  # só candles fechados
                        candle = {
                            "time":  datetime.fromtimestamp(k["t"]/1000, tz=timezone.utc),
                            "open":  float(k["o"]), "high":  float(k["h"]),
                            "low":   float(k["l"]), "close": float(k["c"]),
                            "vol":   float(k["v"]), "tbb":   float(k.get("Q", 0)),
                        }
                        ts_str = candle["time"].strftime("%H:%M")
                        log.info(f"  ┤ {symbol:12s} {ts_str}  close={candle['close']:.4f}  vol={candle['vol']:.0f}")
                        await self.on_candle_close(symbol, candle)
            except Exception as e:
                log.warning(f"WS {symbol} erro: {e} — reconectando em {RECONNECT_DELAY}s")
                await asyncio.sleep(RECONNECT_DELAY)

    # ── HEARTBEAT ─────────────────────────────────────────────
    def _heartbeat(self):
        self._last_hb = time.time()
        ks = self.kill_sw.status()
        drift = self.drift.summary()
        open_syms = [p.symbol for p in self.positions]
        n = len(self.closed_trades)
        wins = sum(1 for t in self.closed_trades if t["result"] == "WIN")
        wr = wins/n*100 if n > 0 else 0.0
        pnl_total = sum(t["pnl"] for t in self.closed_trades)

        log.info(
            f"HEARTBEAT  mode={'PAPER' if not LIVE_MODE else 'LIVE'}  "
            f"trades={n}  WR={wr:.1f}%  PnL=${pnl_total:+,.2f}  "
            f"DD={ks.get('dd_pct',0):.1f}%  "
            f"open=[{','.join(open_syms) or 'none'}]  "
            f"drift_R={drift.get('drift_mean','?')}  "
            f"KS={'ON' if ks.get('ok') else 'TRIGGERED'}"
        )

    # ── STATE PERSISTENCE ─────────────────────────────────────
    def _save_state(self):
        state = {
            "run_id":   LIVE_RUN_ID,
            "ts":       datetime.now(timezone.utc).isoformat(),
            "mode":     "PAPER" if not LIVE_MODE else "LIVE",
            "positions":[p.to_dict() for p in self.positions],
            "kill_switch": self.kill_sw.status(),
            "drift":    self.drift.summary(),
            "n_trades": len(self.closed_trades),
            "total_pnl":round(sum(t["pnl"] for t in self.closed_trades), 2),
        }
        with open(LIVE_DIR / "state" / "positions.json", "w") as f:
            json.dump(state, f, indent=2, default=str)

    def _save_report(self):
        if not self.closed_trades: return
        report = {
            "run_id":  LIVE_RUN_ID,
            "mode":    "PAPER" if not LIVE_MODE else "LIVE",
            "start":   LIVE_RUN_ID,
            "end":     datetime.now(timezone.utc).isoformat(),
            "n_trades":len(self.closed_trades),
            "metrics": self.kill_sw.status(),
            "drift":   self.drift.summary(),
            "trades":  self.closed_trades,
        }
        fname = LIVE_DIR / "reports" / f"session_{_LIVE_DATE}.json"
        with open(fname, "w") as f:
            json.dump(report, f, indent=2, default=str)
        log.info(f"Report → {fname}")

    # ── MAIN ──────────────────────────────────────────────────
    async def run(self):
        """Entry point: seed → WebSocket → loop."""
        self.running = True

        # SIGINT graceful shutdown — só dispara uma vez
        _shutdown_done = False
        def _shutdown(sig, frame):
            nonlocal _shutdown_done
            if _shutdown_done: return
            _shutdown_done = True
            log.info("SIGINT — a guardar estado e encerrar...")
            self.running = False
            for t in self._ws_tasks: t.cancel()
        signal.signal(signal.SIGINT, _shutdown)

        # Seed REST data
        await self.seed()

        # Lança WebSocket por símbolo
        tasks = [asyncio.create_task(self._ws_listen(sym)) for sym in SYMBOLS]
        tasks.append(asyncio.create_task(self._status_ticker()))
        tasks.append(asyncio.create_task(self.telegram.start()))
        self._ws_tasks = tasks

        _run_mode = "DEMO" if DEMO_MODE else "TESTNET" if TESTNET_MODE else "LIVE" if LIVE_MODE else "PAPER"
        log.info(f"Live engine iniciado — {len(SYMBOLS)} símbolos  mode={_run_mode}")
        self._print_banner()
        await self.telegram.notify_startup(_run_mode, SYMBOLS)

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass
        finally:
            self.running = False
            self.telegram.stop()
            for t in tasks: t.cancel()
            self._save_state()
            self._save_report()
            await self.telegram.notify_shutdown()
            log.info("LiveEngine encerrado.")

    def _print_banner(self):
        W = 66
        mode_str = ("PAPER TRADING (sem ordens reais)"          if not LIVE_MODE and not TESTNET_MODE and not DEMO_MODE else
                    "DEMO — demo-fapi.binance.com"               if DEMO_MODE else
                    "TESTNET — testnet.binancefuture.com"        if TESTNET_MODE else
                    "⚠ LIVE TRADING — capital real")
        print(f"\n  {'─'*50}")
        print(f"  GRAVITON Live  ·  {mode_str}")
        print(f"  {len(SYMBOLS)} ativos  ·  {INTERVAL}  ·  ${ACCOUNT_SIZE:,.0f}  ·  max {MAX_OPEN_LIVE} pos")
        print(f"  {LIVE_DIR}/")
        print(f"  {'─'*50}\n")


# ── INTERACTIVE MENU ──────────────────────────────────────────
def _menu() -> str:
    print(f"\n  {'─'*40}")
    print(f"  GRAVITON  ·  Live Engine")
    print(f"  {'─'*40}")
    print()
    print(f"  [1]  Paper")
    print(f"  [2]  Demo")
    print(f"  [3]  Testnet")
    print(f"  [4]  Live")
    print(f"  [5]  Diagnostico")
    print(f"  [0]  Sair")
    print()
    _map = {"1": "paper", "2": "demo", "3": "testnet", "4": "live", "5": "diag", "0": "exit"}
    op = input("  > ").strip()
    return _map.get(op, "exit")


async def _run_diagnostic():
    """Testa conexão REST, seed, e indicadores sem entrar no loop live."""
    log.info("Modo diagnóstico — a testar seed e indicadores...")
    engine = LiveEngine()
    await engine.seed()

    for sym in SYMBOLS[:3]:
        df = engine.buffer.to_df(sym)
        if df is None: log.warning(f"  {sym}: buffer vazio"); continue
        df = indicators(df)
        df = swing_structure(df)
        df = omega(df)
        last = df.iloc[-1]
        log.info(f"  {sym:12s}  struct={last.get('trend_struct','?')}  "
                 f"rsi={last.get('rsi',0):.1f}  "
                 f"slope200={last.get('slope200',0):.3f}  "
                 f"vol={last.get('vol_regime','?')}")

    ks_status = engine.kill_sw.status()
    log.info(f"Kill-switch status: {ks_status}")

    # Telegram connectivity test
    from bot.telegram import TelegramNotifier
    tg = TelegramNotifier(engine)
    if tg.enabled:
        await tg.send("🔧 <b>AURUM Diagnóstico</b> — Telegram OK ✓")
        log.info("Telegram: conexão OK ✓")
    else:
        log.warning("Telegram: não configurado (adiciona 'telegram' a config/keys.json)")

    log.info("Diagnóstico completo — sistema OK para trading")


def _launch(mode: str, leverage: float = 1.0, no_telegram: bool = False):
    """Lança o engine com o modo especificado."""
    global LIVE_MODE, TESTNET_MODE, DEMO_MODE

    if mode == "live":
        print(f"\n  ⚠  LIVE MODE — capital real será utilizado")
        confirm = input("  Confirmas? (escreve 'SIM' para continuar) > ").strip()
        if confirm != "SIM":
            print("  Cancelado."); sys.exit(0)
        import backtest as _bk2
        _bk2.LEVERAGE = leverage

    LIVE_MODE    = (mode == "live")
    DEMO_MODE    = (mode == "demo")
    TESTNET_MODE = (mode == "testnet")

    engine = LiveEngine()

    if no_telegram:
        engine.telegram.enabled = False
        log.info("Telegram desactivado via --no-telegram")

    asyncio.run(engine.run())


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="☿ AURUM Finance — Live Engine v1.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python live.py                   # menu interactivo
  python live.py paper             # paper trading directo
  python live.py demo              # demo Binance Futures
  python live.py live --leverage 2 # live com leverage 2x
  python live.py diag              # diagnóstico rápido
  python live.py paper --no-telegram  # sem notificações Telegram
        """,
    )
    ap.add_argument(
        "mode", nargs="?",
        choices=["paper", "demo", "testnet", "live", "diag"],
        help="Modo de execução (omitir para menu interactivo)",
    )
    ap.add_argument("--leverage", type=float, default=1.0, help="Leverage para LIVE mode (default: 1)")
    ap.add_argument("--no-telegram", action="store_true", help="Desactiva notificações Telegram")

    args = ap.parse_args()

    # Se sem argumentos → menu interactivo
    if args.mode is None:
        args.mode = _menu()

    if args.mode == "exit":
        print("\n  Ate logo.\n")
        sys.exit(0)

    elif args.mode == "diag":
        asyncio.run(_run_diagnostic())

    else:
        _launch(args.mode, args.leverage, args.no_telegram)