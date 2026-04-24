"""
AURUM Finance — MT5 Data Bridge
================================
Connects to MetaTrader 5 via RPyC (Docker container) and returns DataFrames
compatible with the AURUM pipeline (indicators -> signals -> backtest).

Architecture:
    Docker (Wine + MT5 + RPyC server)  <--port 8001-->  AURUM (this module)

The tbb column is synthetic (50% of tick volume) because forex/CFD markets
have no taker buy aggression data. This makes omega_flow neutral (~0.50),
which is intentional: forex edge comes from struct/cascade/momentum/pullback,
not order flow.

Usage:
    from core.mt5 import MT5Bridge
    mt5 = MT5Bridge(host="localhost", port=8001)
    mt5.connect(login=12345678, password="xxx", server="ICMarketsSC-Demo")
    df = mt5.fetch("EURUSD", timeframe="1h", n_candles=5000)
    # df has columns: time, open, high, low, close, vol, tbb
    # -> ready for indicators(df)
"""
import logging
import pandas as pd
from datetime import datetime, timezone

log = logging.getLogger("AURUM.MT5")

# Timeframe mapping: AURUM string -> MT5 integer constants
# These match MetaTrader5.TIMEFRAME_* values
_TF_MAP = {
    "1m": 1, "3m": 2, "5m": 5, "15m": 15, "30m": 30,
    "1h": 16385, "2h": 16386, "4h": 16388,
    "1d": 16408, "1w": 32769, "1M": 49153,
}


class MT5Bridge:
    """Data bridge between MT5 (Docker) and the AURUM pipeline."""

    def __init__(self, host: str = "localhost", port: int = 8001):
        self.host = host
        self.port = port
        self.mt5 = None
        self._connected = False

    def connect(self, login: int = None, password: str = None,
                server: str = None) -> bool:
        """
        Initialize connection to MT5 via RPyC.
        If login/password/server provided, logs into that account.
        Otherwise uses the account already logged in on the terminal.
        """
        try:
            from mt5linux import MetaTrader5
            self.mt5 = MetaTrader5(host=self.host, port=self.port)

            if not self.mt5.initialize():
                err = self.mt5.last_error()
                log.error(f"MT5 initialize() failed: {err}")
                return False

            if login and password and server:
                if not self.mt5.login(login=login, password=password, server=server):
                    err = self.mt5.last_error()
                    log.error(f"MT5 login() failed: {err}")
                    return False

            info = self.mt5.terminal_info()
            ver = self.mt5.version()
            log.info(f"MT5 connected — version {ver}, company: {info.company}")
            self._connected = True
            return True

        except ImportError:
            log.error("mt5linux not installed. Run: pip install mt5linux")
            return False
        except ConnectionRefusedError:
            log.error(f"MT5 RPyC server not reachable at {self.host}:{self.port}. "
                      "Is the Docker container running? (docker compose up -d)")
            return False
        except Exception as e:
            log.error(f"MT5 connection error: {e}")
            return False

    def disconnect(self):
        if self.mt5:
            try:
                self.mt5.shutdown()
            except Exception:
                pass
            self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def account_info(self) -> dict | None:
        """Return account info: balance, equity, margin, etc."""
        if not self._connected:
            return None
        info = self.mt5.account_info()
        if info is None:
            return None
        return {
            "login": info.login,
            "server": info.server,
            "balance": info.balance,
            "equity": info.equity,
            "margin": info.margin,
            "free_margin": info.margin_free,
            "leverage": info.leverage,
            "currency": info.currency,
            "company": info.company,
        }

    def symbols(self, group: str = None) -> list[str]:
        """List available symbols. group: e.g. '*USD*', 'Forex*'."""
        if not self._connected:
            return []
        if group:
            syms = self.mt5.symbols_get(group=group)
        else:
            syms = self.mt5.symbols_get()
        return [s.name for s in (syms or [])]

    def fetch(self, symbol: str, timeframe: str = "1h",
              n_candles: int = 5000) -> pd.DataFrame | None:
        """
        Fetch OHLCV from MT5 and return AURUM-compatible DataFrame.

        Columns: time, open, high, low, close, vol, tbb
        - vol = tick_volume (standard for forex, more representative than real_volume)
        - tbb = 50% of vol (neutral estimate — MT5 has no taker buy data)

        The tbb field is synthetic because MT5/forex has no taker aggression.
        Indicators depending on tbb (taker_ratio, omega_flow, CVD) will produce
        neutral values -> omega_flow ~ 0.50 always.
        This is INTENTIONAL: for forex, edge comes from struct/momentum/cascade,
        not order flow (which doesn't exist in decentralized FX markets).
        """
        if not self._connected:
            log.error("MT5 not connected")
            return None

        tf_val = _TF_MAP.get(timeframe)
        if tf_val is None:
            log.error(f"Timeframe '{timeframe}' not supported. "
                      f"Valid: {', '.join(_TF_MAP.keys())}")
            return None

        utc_now = datetime.now(timezone.utc)
        rates = self.mt5.copy_rates_from(symbol, tf_val, utc_now, n_candles)

        if rates is None or len(rates) == 0:
            err = self.mt5.last_error()
            log.warning(f"[{symbol}] no MT5 data: {err}")
            return None

        df = pd.DataFrame(rates)
        # MT5 returns: time, open, high, low, close, tick_volume, spread, real_volume
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.rename(columns={"tick_volume": "vol"})

        # Synthetic tbb: 50% of volume (neutral)
        # omega_flow will be ~0.50 (neutral), CVD flat, imbalance neutral.
        # Correct for forex — no taker aggression data exists in decentralized FX.
        df["tbb"] = df["vol"] * 0.50

        df = df[["time", "open", "high", "low", "close", "vol", "tbb"]].copy()

        for c in ["open", "high", "low", "close", "vol", "tbb"]:
            df[c] = df[c].astype(float)

        df = df.drop_duplicates("time").sort_values("time").reset_index(drop=True)

        if len(df) < 300:
            log.warning(f"[{symbol}] only {len(df)} candles (min: 300)")
            return None

        log.info(f"[{symbol}] {len(df)} candles  "
                 f"{df['time'].iloc[0].strftime('%Y-%m-%d')} -> "
                 f"{df['time'].iloc[-1].strftime('%Y-%m-%d')}")
        return df

    def fetch_all(self, symbols: list, timeframe: str = "1h",
                  n_candles: int = 5000) -> dict:
        """Fetch multiple symbols. Returns {symbol: DataFrame}."""
        results = {}
        for sym in symbols:
            df = self.fetch(sym, timeframe, n_candles)
            if df is not None:
                results[sym] = df
        return results

    def fetch_ticks(self, symbol: str, n_ticks: int = 10000) -> pd.DataFrame | None:
        """Fetch tick data (bid/ask/last). Useful for spread analysis."""
        if not self._connected:
            return None
        utc_now = datetime.now(timezone.utc)
        ticks = self.mt5.copy_ticks_from(symbol, utc_now, n_ticks, 0)  # 0 = COPY_TICKS_ALL
        if ticks is None or len(ticks) == 0:
            return None
        df = pd.DataFrame(ticks)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        return df

    def symbol_info(self, symbol: str) -> dict | None:
        """Symbol info: spread, digits, trade sizes, etc."""
        if not self._connected:
            return None
        info = self.mt5.symbol_info(symbol)
        if info is None:
            return None
        return {
            "name": info.name,
            "description": info.description,
            "spread": info.spread,
            "digits": info.digits,
            "point": info.point,
            "trade_contract_size": info.trade_contract_size,
            "volume_min": info.volume_min,
            "volume_max": info.volume_max,
            "volume_step": info.volume_step,
            "currency_base": info.currency_base,
            "currency_profit": info.currency_profit,
        }
