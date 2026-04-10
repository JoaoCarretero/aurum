"""AURUM — Data fetching & validation."""
import time, logging, requests
import numpy as np
import pandas as pd
from config.params import *
from config.params import _TF_MINUTES

log = logging.getLogger("CITADEL")
_vl = logging.getLogger("CITADEL.val")

def fetch(symbol: str, interval: str | None = None,
          n_candles: int | None = None,
          futures: bool = False) -> pd.DataFrame | None:
    _iv  = interval  or INTERVAL
    _nc  = n_candles or N_CANDLES
    # futures klines têm preço perp (mais próximo do que vai ser executado)
    base = "https://fapi.binance.com/fapi/v1" if futures else "https://api.binance.com/api/v3"
    url, frames, end_time = f"{base}/klines", [], None
    remaining = _nc
    while remaining > 0:
        limit  = min(1000, remaining)
        params = {"symbol": symbol, "interval": _iv, "limit": limit}
        if end_time:
            params["endTime"] = end_time
        try:
            r = requests.get(url, params=params, timeout=20)
            if r.status_code == 429:
                _retries = getattr(fetch_klines, '_429_count', 0) + 1
                if _retries > 5:
                    log.warning(f"[{symbol}] max retries on HTTP 429"); break
                fetch_klines._429_count = _retries
                time.sleep(2.0); continue
            if r.status_code != 200: break
            data = r.json()
            if not data: break
            frames.insert(0, data)
            end_time   = data[0][0] - 1
            remaining -= len(data)
            log.debug(f"[{symbol}] page {len(frames)}: got {len(data)} candles, remaining={remaining}")
            if len(data) < limit:
                log.debug(f"[{symbol}] API returned fewer than requested — end of available history")
                break
            time.sleep(0.08)
        except Exception as e:
            log.warning(f"[{symbol}] fetch error: {e}"); break
    if not frames: return None
    flat = [c for f in frames for c in f]
    df   = pd.DataFrame(flat, columns=[
        "time","open","high","low","close","vol",
        "ct","qvol","tr","tbb","tbq","ign"])
    df   = df[["time","open","high","low","close","vol","tbb"]].copy()
    for c in ["open","high","low","close","vol","tbb"]:
        df[c] = df[c].astype(float)
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    return df.drop_duplicates("time").sort_values("time").reset_index(drop=True)

def fetch_all(symbols: list, interval: str | None = None,
              n_candles: int | None = None,
              label: str = "", workers: int = 6,
              futures: bool = False,
              on_progress=None) -> dict:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    _iv = interval or INTERVAL
    _nc = n_candles or N_CANDLES
    results: dict = {}
    futures_map: dict = {}
    total = len(symbols)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for sym in symbols:
            futures_map[ex.submit(fetch, sym, _iv, _nc, futures)] = sym
        done = 0
        for fut in as_completed(futures_map):
            sym = futures_map[fut]
            done += 1
            try:
                df = fut.result()
            except Exception as e:
                df = None
                log.warning(f"[{sym}] {e}")
            ok = df is not None and len(df) >= 300
            if ok:
                results[sym] = df
            if on_progress:
                on_progress(sym, done, total, ok)
            else:
                if ok:
                    span = (f"{df['time'].iloc[0].strftime('%Y-%m-%d')} → "
                            f"{df['time'].iloc[-1].strftime('%Y-%m-%d')}")
                    print(f"  [{sym:12s}]  ✓  {len(df)}c   {span}", flush=True)
                else:
                    print(f"  [{sym:12s}]  ✗ sem dados", flush=True)
    return results

def validate(df: pd.DataFrame, symbol: str) -> bool:
    issues = []
    if len(df) < 300: issues.append(f"SHORT_SERIES:{len(df)}")
    if df.duplicated("time").sum(): issues.append("DUPLICATES")
    tk = df["tbb"] / df["vol"].replace(0, np.nan)
    if ((tk > 1.01) | (tk < -0.01)).sum(): issues.append("TAKER_INVALID")
    m = tk.mean()
    if m > 0.70 or m < 0.30: issues.append(f"TAKER_BIASED:{m:.3f}")
    ok = not issues
    _vl.info(f"{symbol:12s}  {'OK' if ok else 'WARN'}  n={len(df)}"
             + (f"  {';'.join(issues)}" if issues else ""))
    return ok


def fetch_mt5(symbol: str, timeframe: str = "1h",
              n_candles: int = 5000,
              host: str = "localhost", port: int = 8001) -> pd.DataFrame | None:
    """Convenience wrapper for fetch via MT5 bridge."""
    from core.mt5 import MT5Bridge
    bridge = MT5Bridge(host=host, port=port)
    if not bridge.connect():
        return None
    df = bridge.fetch(symbol, timeframe, n_candles)
    bridge.disconnect()
    return df

