# AURUM Finance — Arbitrage Engine v5.0 (Unified)
# Copyright (c) 2026 AURUM Finance. All rights reserved.
# Proprietary and confidential. Unauthorized distribution prohibited.
# PnL(t) = F(t) + B(t) - C | Multi-venue | Omega scoring | Split execution
# v5.0: +OrderBook Depth +Latency Profiler +Regime Detection +Hedge Monitor
# v5.0: +Fill Probability +Adversarial Detector +OmegaV2 +Dynamic Sizing +Order Flow

import os,sys,json,time,asyncio,logging,signal,math,hmac,hashlib,statistics
import numpy as np
from pathlib import Path
from datetime import datetime,timezone
from urllib.parse import urlencode
from dataclasses import dataclass,field
from typing import Dict,List,Optional,Tuple
from collections import deque

import argparse

def _parse_mode():
    p=argparse.ArgumentParser(add_help=False)
    p.add_argument("--mode",choices=["paper","demo","testnet","live"],default=None)
    p.add_argument("--run-id",default=None,help="override auto-generated run id")
    args,_=p.parse_known_args()
    return args

_ARGS=_parse_mode()
ARB_LIVE=_ARGS.mode=="live"
ARB_DEMO=_ARGS.mode in("demo","testnet")
ARB_TESTNET=_ARGS.mode=="testnet"
ARB_PAPER=_ARGS.mode=="paper" or _ARGS.mode is None
ARB_MODE=_ARGS.mode or "paper"

sys.path.insert(0,str(Path(__file__).parent.parent))
from config.params import safe_input
from bot.telegram import TelegramNotifier

ACCT=5000.0;MAX_POS=5;CROSS_MAX=3;LEV=2;POS_PCT=0.20;MAX_EXPO=3000.0
SPLIT_N=5;SPLIT_DLY=0.5;SCAN_S=30;STATUS_N=3;WS_ON=True
MIN_SPREAD=0.0015;MIN_APR=40.0;MIN_VOL=3_000_000;MAX_PX_SPREAD=0.02
EXIT_H=8;EXIT_DECAY=0.30;MAX_HOLD_H=72;MAX_DD_PCT=0.05;KILL_LOSSES=3
_D=datetime.now().strftime("%Y-%m-%d");_T=datetime.now().strftime("%H%M")
RUN_ID=_ARGS.run_id or f"{_D}_{_T}";DIR=Path(f"data/arbitrage/{RUN_ID}")
for d in("logs","state","reports"):(DIR/d).mkdir(parents=True,exist_ok=True)

fmt=logging.Formatter("%(asctime)s %(levelname)-6s %(message)s",datefmt="%Y-%m-%d %H:%M:%S")
log=logging.getLogger("JANE_STREET")  # JANE STREET (formerly ARBITRAGE/NEUTRINO);log.handlers.clear();log.setLevel(logging.DEBUG);log.propagate=False
sh=logging.StreamHandler();sh.setFormatter(fmt);sh.setLevel(logging.INFO);log.addHandler(sh)
fh=logging.FileHandler(DIR/"logs"/"arb.log",encoding="utf-8");fh.setFormatter(fmt);fh.setLevel(logging.DEBUG);log.addHandler(fh)
tlog=logging.getLogger("a.t");tlog.handlers.clear();tlog.setLevel(logging.INFO);tlog.propagate=False
th=logging.FileHandler(DIR/"logs"/"trades.log",encoding="utf-8");th.setFormatter(fmt);tlog.addHandler(th)

def _keys(v):
    with open(Path(__file__).parent.parent/"config"/"keys.json") as f:c=json.load(f)
    b=c.get(v,{});return b.get("api_key",""),b.get("api_secret","")

async def _http(url,params=None,method="GET",json_body=None,headers=None,retries=3):
    import requests as r
    lp=asyncio.get_event_loop()
    for attempt in range(retries):
        try:
            if method=="POST":
                resp=await lp.run_in_executor(None,lambda:r.post(url,json=json_body,params=params,headers=headers or{},timeout=15))
            else:
                resp=await lp.run_in_executor(None,lambda:r.get(url,params=params,headers=headers or{},timeout=15))
            if resp.status_code==429:
                await asyncio.sleep(1*(attempt+1));continue
            return resp.json()
        except Exception as e:
            if attempt<retries-1:await asyncio.sleep(0.5*(attempt+1));continue
            log.debug(f"_http failed {method} {url}: {e}")
            return{}

class Venue:
    def __init__(s,name,cost,has_spot=False,fund_h=8):
        s.name=name;s.cost=cost;s.has_spot=has_spot;s.fund_h=fund_h
        s.funding={};s.prices={};s.volumes={};s.next_fund={};s.last_fetch=0
        s.step_sizes={};s.min_notional={}
        s._fail_count=0;s._max_fails=3;s._disabled=False
    async def fetch(s):pass
    async def safe_fetch(s):
        """Wrapper com failure tracking — desactiva venues após _max_fails consecutivos."""
        if s._disabled:return
        try:
            await s.fetch()
            s._fail_count=0
        except Exception as e:
            s._fail_count+=1
            if s._fail_count>=s._max_fails:
                s._disabled=True
                log.warning(f"{s.name}: desactivada após {s._fail_count} falhas consecutivas ({e})")
            else:
                log.debug(f"{s.name}: fetch falhou ({s._fail_count}/{s._max_fails}): {e}")
    def next_funding_ts(s,sym):
        if sym in s.next_fund:return s.next_fund[sym]
        now=time.time();interval=s.fund_h*3600
        return now-(now%interval)+interval
    async def place_order(s,sym,side,qty):return{"status":"PAPER"}
    async def close_order(s,sym,side,qty):return{"status":"PAPER"}
    async def set_leverage(s,sym,lev):pass
    def round_qty(s,sym,raw_qty):
        step=s.step_sizes.get(sym,0)
        if step>0:return math.floor(raw_qty/step)*step
        # fallback: generic rounding
        px=s.prices.get(sym,0)
        if px>1000:return round(raw_qty,4)
        elif px>10:return round(raw_qty,2)
        elif px>0.1:return round(raw_qty,0)
        else:return round(raw_qty,-1)

class Binance(Venue):
    def __init__(s):
        super().__init__("binance",0.0006,has_spot=True)
        s.fapi="https://fapi.binance.com";s.sapi="https://api.binance.com"
        s.key,s.sec=("","")
        if ARB_LIVE:s.key,s.sec=_keys("live")
        elif ARB_DEMO:s.key,s.sec=_keys("demo");s.fapi="https://demo-fapi.binance.com"
    async def fetch(s):
        d=await _http(f"{s.fapi}/fapi/v1/premiumIndex")
        if isinstance(d,list):
            for x in d:
                sy=x.get("symbol","")
                if sy.endswith("USDT"):
                    s.funding[sy]=float(x.get("lastFundingRate",0))
                    s.prices[sy]=float(x.get("markPrice",0))
                    nft=int(x.get("nextFundingTime",0))
                    if nft>0:s.next_fund[sy]=nft/1000
        tk=await _http(f"{s.fapi}/fapi/v1/ticker/24hr")
        if isinstance(tk,list):
            for t in tk:s.volumes[t.get("symbol","")]=float(t.get("quoteVolume",0))
        s.last_fetch=time.time()
        # fetch step sizes (once, then cached)
        if not s.step_sizes:
            try:
                ei=await _http(f"{s.fapi}/fapi/v1/exchangeInfo")
                for sym_info in ei.get("symbols",[]):
                    sy=sym_info.get("symbol","")
                    for f in sym_info.get("filters",[]):
                        if f.get("filterType")=="LOT_SIZE":
                            s.step_sizes[sy]=float(f.get("stepSize",0))
                        if f.get("filterType")=="MIN_NOTIONAL":
                            s.min_notional[sy]=float(f.get("notional",0))
            except:log.debug("Binance exchangeInfo failed")
    def _sg(s,p):
        p["timestamp"]=int(time.time()*1000);q=urlencode(p)
        p["signature"]=hmac.new(s.sec.encode(),q.encode(),hashlib.sha256).hexdigest();return p
    async def set_leverage(s,sym,lev):
        if not s.key:return
        try:
            p=s._sg({"symbol":sym,"leverage":int(lev)})
            await _http(f"{s.fapi}/fapi/v1/leverage",params=p,method="POST",headers={"X-MBX-APIKEY":s.key})
        except Exception as e:log.debug(f"Binance set_leverage {sym}: {e}")
    async def get_balance(s)->float:
        if not s.key:return 0
        try:
            p=s._sg({})
            d=await _http(f"{s.fapi}/fapi/v2/balance",params=p,headers={"X-MBX-APIKEY":s.key})
            if isinstance(d,list):
                for b in d:
                    if b.get("asset")=="USDT":return float(b.get("availableBalance",0))
        except Exception as e:
            log.warning("balance fetch failed: %s", e)
        return 0
    async def place_order(s,sym,side,qty):
        if not s.key:return{"status":"PAPER"}
        p=s._sg({"symbol":sym,"side":side,"type":"MARKET","quantity":qty})
        return await _http(f"{s.fapi}/fapi/v1/order",params=p,method="POST",headers={"X-MBX-APIKEY":s.key})
    async def close_order(s,sym,side,qty):
        if not s.key:return{"status":"PAPER"}
        p=s._sg({"symbol":sym,"side":side,"type":"MARKET","quantity":qty,"reduceOnly":"true"})
        return await _http(f"{s.fapi}/fapi/v1/order",params=p,method="POST",headers={"X-MBX-APIKEY":s.key})
    async def spot_order(s,sym,side,qty):
        if not s.key:return{"status":"PAPER"}
        p=s._sg({"symbol":sym,"side":side,"type":"MARKET","quantity":qty})
        return await _http(f"{s.sapi}/api/v3/order",params=p,method="POST",headers={"X-MBX-APIKEY":s.key})
    async def spot_price(s,sym):
        try:return float((await _http(f"{s.sapi}/api/v3/ticker/price",{"symbol":sym})).get("price",0))
        except Exception as e:log.warning("spot_price failed: %s", e);return 0

class Bybit(Venue):
    def __init__(s):
        super().__init__("bybit",0.0008)
        s.base="https://api.bybit.com"
        s.key,s.sec="",""
        try:s.key,s.sec=_keys("bybit")
        except Exception as e:log.warning("bybit keys load failed: %s", e)
    async def fetch(s):
        d=await _http(f"{s.base}/v5/market/tickers",{"category":"linear"})
        for t in d.get("result",{}).get("list",[]):
            sy=t.get("symbol","")
            if sy.endswith("USDT"):
                s.funding[sy]=float(t.get("fundingRate",0))
                s.prices[sy]=float(t.get("lastPrice",0))
                s.volumes[sy]=float(t.get("turnover24h",0))
                nft=int(t.get("nextFundingTime",0))
                if nft>0:s.next_fund[sy]=nft/1000
        s.last_fetch=time.time()
        # fetch step sizes
        if not s.step_sizes:
            try:
                d2=await _http(f"{s.base}/v5/market/instruments-info",{"category":"linear"})
                for x in d2.get("result",{}).get("list",[]):
                    sy=x.get("symbol","")
                    lf=x.get("lotSizeFilter",{})
                    step=float(lf.get("qtyStep",0))
                    if step>0:s.step_sizes[sy]=step
            except:log.debug("Bybit instruments-info failed")
    def _sign(s,params):
        ts=str(int(time.time()*1000))
        ps=ts+s.key+"5000"+urlencode(sorted(params.items()))
        sig=hmac.new(s.sec.encode(),ps.encode(),hashlib.sha256).hexdigest()
        return{"X-BAPI-API-KEY":s.key,"X-BAPI-SIGN":sig,"X-BAPI-TIMESTAMP":ts,"X-BAPI-RECV-WINDOW":"5000","Content-Type":"application/json"}
    async def set_leverage(s,sym,lev):
        if not s.key:return
        try:
            b={"category":"linear","symbol":sym,"buyLeverage":str(int(lev)),"sellLeverage":str(int(lev))}
            await _http(f"{s.base}/v5/position/set-leverage",method="POST",json_body=b,headers=s._sign(b))
        except Exception as e:log.debug(f"Bybit set_leverage {sym}: {e}")
    async def place_order(s,sym,side,qty):
        if not s.key:return{"status":"PAPER"}
        b={"category":"linear","symbol":sym,"side":side.capitalize(),"orderType":"Market","qty":str(qty)}
        return await _http(f"{s.base}/v5/order/create",method="POST",json_body=b,headers=s._sign(b))
    async def close_order(s,sym,side,qty):
        if not s.key:return{"status":"PAPER"}
        b={"category":"linear","symbol":sym,"side":side.capitalize(),"orderType":"Market","qty":str(qty),"reduceOnly":True}
        return await _http(f"{s.base}/v5/order/create",method="POST",json_body=b,headers=s._sign(b))

class Hyperliquid(Venue):
    def __init__(s):super().__init__("hyperliquid",0.0005,fund_h=1);s._c=None
    async def fetch(s):
        d=await _http("https://api.hyperliquid.xyz/info",method="POST",json_body={"type":"metaAndAssetCtxs"})
        if isinstance(d,list) and len(d)>=2:
            m,c=d[0].get("universe",[]),d[1]
            for i,a in enumerate(m):
                if i<len(c):
                    sy=f"{a.get('name','')}USDT"
                    s.funding[sy]=float(c[i].get("funding",0))
                    s.prices[sy]=float(c[i].get("markPx",0))
                    s.volumes[sy]=float(c[i].get("dayNtlVlm",0))
        s.last_fetch=time.time()

class GateIO(Venue):
    def __init__(s):super().__init__("gate",0.0008)
    async def fetch(s):
        try:
            d=await _http("https://api.gateio.ws/api/v4/futures/usdt/contracts")
            if isinstance(d,list):
                for c in d:
                    sy=c.get("name","").replace("_","")
                    if sy.endswith("USDT"):
                        s.funding[sy]=float(c.get("funding_rate",0))
                        s.prices[sy]=float(c.get("last_price",0))
                        s.volumes[sy]=float(c.get("trade_size",0))*float(c.get("last_price",0) or 1)
        except Exception as e:log.debug(f"Gate.io: {e}")
        s.last_fetch=time.time()

class OKX(Venue):
    def __init__(s):super().__init__("okx",0.0007)
    async def fetch(s):
        try:
            d=await _http("https://www.okx.com/api/v5/public/funding-rate")
            for x in d.get("data",[]):
                sy=x.get("instId","").replace("-","")
                if sy.endswith("USDTSWAP"):sy=sy.replace("SWAP","")
                elif sy.endswith("USDT"):pass
                else:continue
                s.funding[sy]=float(x.get("fundingRate",0))
            d2=await _http("https://www.okx.com/api/v5/market/tickers",{"instType":"SWAP"})
            for x in d2.get("data",[]):
                sy=x.get("instId","").replace("-","")
                if sy.endswith("USDTSWAP"):sy=sy.replace("SWAP","")
                elif sy.endswith("USDT"):pass
                else:continue
                s.prices[sy]=float(x.get("last",0))
                s.volumes[sy]=float(x.get("volCcy24h",0))
        except Exception as e:log.debug(f"OKX: {e}")
        s.last_fetch=time.time()

class Bitget(Venue):
    def __init__(s):super().__init__("bitget",0.0008)
    async def fetch(s):
        try:
            d=await _http("https://api.bitget.com/api/v2/mix/market/tickers",{"productType":"USDT-FUTURES"})
            for x in d.get("data",[]):
                sy=x.get("symbol","")
                if sy.endswith("USDT"):
                    s.funding[sy]=float(x.get("fundingRate",0))
                    s.prices[sy]=float(x.get("lastPr",0))
                    s.volumes[sy]=float(x.get("quoteVolume",0))
        except Exception as e:log.debug(f"Bitget: {e}")
        s.last_fetch=time.time()

class MEXC(Venue):
    def __init__(s):super().__init__("mexc",0.0008)
    async def fetch(s):
        try:
            d=await _http("https://contract.mexc.com/api/v1/contract/ticker")
            if isinstance(d,dict):
                for x in d.get("data",[]):
                    sy=x.get("symbol","").replace("_","")
                    if sy.endswith("USDT"):
                        s.funding[sy]=float(x.get("fundingRate",0))
                        s.prices[sy]=float(x.get("lastPrice",0))
                        s.volumes[sy]=float(x.get("volume24",0))*float(x.get("lastPrice",0) or 1)
        except Exception as e:log.debug(f"MEXC: {e}")
        s.last_fetch=time.time()

class BingX(Venue):
    def __init__(s):super().__init__("bingx",0.0008)
    async def fetch(s):
        try:
            d=await _http("https://open-api.bingx.com/openApi/swap/v2/quote/premiumIndex")
            if isinstance(d,dict):
                for x in d.get("data",[]):
                    sy=x.get("symbol","").replace("-","")
                    if sy.endswith("USDT"):
                        s.funding[sy]=float(x.get("lastFundingRate",0))
                        s.prices[sy]=float(x.get("markPrice",0))
                        s.volumes[sy]=float(x.get("volume",0) or 0)
        except Exception as e:log.debug(f"BingX: {e}")
        s.last_fetch=time.time()

class KuCoin(Venue):
    def __init__(s):super().__init__("kucoin",0.0008)
    async def fetch(s):
        try:
            d=await _http("https://api-futures.kucoin.com/api/v1/contracts/active")
            if isinstance(d,dict):
                for x in d.get("data",[]):
                    sy=x.get("symbol","").replace("USDTM","USDT")
                    if not sy.endswith("USDT"):continue
                    fr=float(x.get("fundingFeeRate",0))
                    mk=float(x.get("markPrice",0))
                    s.funding[sy]=fr;s.prices[sy]=mk
                    s.volumes[sy]=float(x.get("turnoverOf24h",0))
        except Exception as e:log.debug(f"KuCoin: {e}")
        s.last_fetch=time.time()

class HTX(Venue):
    def __init__(s):super().__init__("htx",0.0008)
    async def fetch(s):
        try:
            d=await _http("https://api.hbdm.com/linear-swap-api/v1/swap_batch_funding_rate")
            if isinstance(d,dict):
                for x in d.get("data",[]):
                    ct=x.get("contract_code","").replace("-","")
                    if ct.endswith("USDT"):
                        s.funding[ct]=float(x.get("funding_rate",0))
            d2=await _http("https://api.hbdm.com/linear-swap-ex/market/detail/batch_merged")
            if isinstance(d2,dict):
                for x in d2.get("ticks",[]):
                    ct=x.get("contract_code","").replace("-","")
                    if ct.endswith("USDT"):
                        s.prices[ct]=float(x.get("close",0))
                        s.volumes[ct]=float(x.get("trade_turnover",0))
        except Exception as e:log.debug(f"HTX: {e}")
        s.last_fetch=time.time()

class Phemex(Venue):
    def __init__(s):super().__init__("phemex",0.0007,fund_h=4)
    async def fetch(s):
        try:
            d=await _http("https://api.phemex.com/md/v3/ticker/24hr/all")
            if isinstance(d,dict) and d.get("code")==0:
                for x in d.get("data",[]):
                    sy=x.get("symbol","")
                    if not sy.startswith("s") or "USDT" not in sy:continue
                    clean=sy.lstrip("s").replace("rp","")
                    if not clean.endswith("USDT"):continue
                    fr=float(x.get("fundingRate","0") or 0)
                    if fr!=0:fr=fr/1e8
                    mk=float(x.get("markPrice","0") or 0)
                    if mk>1e6:mk=mk/1e4
                    if mk>0:s.funding[clean]=fr;s.prices[clean]=mk
                    s.volumes[clean]=float(x.get("turnover","0") or 0)
        except Exception as e:log.debug(f"Phemex: {e}")
        s.last_fetch=time.time()

class DYDX(Venue):
    def __init__(s):super().__init__("dydx",0.0005,fund_h=1)
    async def fetch(s):
        try:
            d=await _http("https://indexer.dydx.trade/v4/perpetualMarkets")
            if isinstance(d,dict):
                mkts=d.get("markets",{})
                for sym,info in mkts.items():
                    clean=sym.replace("-","")
                    if not clean.endswith("USD"):continue
                    clean=clean.replace("USD","USDT")
                    fr=float(info.get("nextFundingRate",0))
                    px=float(info.get("oraclePrice",0))
                    vol=float(info.get("volume24H",0))
                    if px>0:s.funding[clean]=fr;s.prices[clean]=px;s.volumes[clean]=vol
        except Exception as e:log.debug(f"dYdX: {e}")
        s.last_fetch=time.time()

class Backpack(Venue):
    def __init__(s):super().__init__("backpack",0.0008,fund_h=1);s.base="https://api.backpack.exchange"
    def _sym_to_internal(s,sym):
        # BTC_USDC_PERP → BTCUSDT
        if not sym.endswith("_PERP"):return None
        base=sym.replace("_PERP","").replace("_USDC","").replace("_USDT","")
        return f"{base}USDT"
    async def fetch(s):
        try:
            d=await _http(f"{s.base}/api/v1/markPrices")
            if isinstance(d,list):
                for x in d:
                    sym=x.get("symbol","")
                    internal=s._sym_to_internal(sym)
                    if not internal:continue
                    fr=float(x.get("fundingRate",0) or 0)
                    mk=float(x.get("markPrice",0) or 0)
                    ix=float(x.get("indexPrice",0) or 0)
                    if mk>0:s.funding[internal]=fr;s.prices[internal]=mk
            tk=await _http(f"{s.base}/api/v1/tickers")
            if isinstance(tk,list):
                for x in tk:
                    sym=x.get("symbol","")
                    internal=s._sym_to_internal(sym)
                    if not internal:continue
                    vol=float(x.get("quoteVolume",0) or x.get("volume",0) or 0)
                    if vol>0:s.volumes[internal]=vol
        except Exception as e:log.debug(f"Backpack: {e}")
        s.last_fetch=time.time()

def build_venues():
    return[Binance(),Bybit(),Hyperliquid(),GateIO(),OKX(),Bitget(),MEXC(),BingX(),KuCoin(),HTX(),Phemex(),DYDX(),Backpack()]

@dataclass
class BookLevel:
    price:float;qty:float;cumulative_qty:float=0.0;cumulative_notional:float=0.0

@dataclass
class OrderBook:
    symbol:str;venue:str
    bids:List[BookLevel]=field(default_factory=list)
    asks:List[BookLevel]=field(default_factory=list)
    ts:float=0.0
    @property
    def mid(s)->float:
        return(s.bids[0].price+s.asks[0].price)/2 if s.bids and s.asks else 0.0
    @property
    def spread_bps(s)->float:
        return(s.asks[0].price-s.bids[0].price)/s.mid*10_000 if s.bids and s.asks and s.mid>0 else float('inf')
    def depth_at_pct(s,side:str,pct:float)->float:
        levels=s.bids if side=="bid" else s.asks
        if not levels:return 0.0
        best=levels[0].price;limit=best*(1-pct) if side=="bid" else best*(1+pct)
        total=0.0
        for lv in levels:
            if side=="bid" and lv.price<limit:break
            if side=="ask" and lv.price>limit:break
            total+=lv.price*lv.qty
        return total

class DepthFetcher:
    def __init__(s):s._cache:Dict[str,OrderBook]={};s._cache_ttl=5.0

    def _parse(s,raw:list)->List[BookLevel]:
        levels=[];cum_q=cum_n=0.0
        for p,q,*_ in raw:
            pf,qf=float(p),float(q);cum_q+=qf;cum_n+=pf*qf
            levels.append(BookLevel(pf,qf,cum_q,cum_n))
        return levels

    async def fetch(s,venue:str,symbol:str)->Optional[OrderBook]:
        key=f"{venue}:{symbol}"
        cached=s._cache.get(key)
        if cached and time.time()-cached.ts<s._cache_ttl:return cached
        try:
            book=await s._fetch_venue(venue,symbol)
            if book:s._cache[key]=book
            return book
        except Exception as e:
            log.debug(f"Depth {venue}/{symbol}: {e}");return cached

    async def _fetch_venue(s,venue:str,symbol:str)->Optional[OrderBook]:
        ob=OrderBook(symbol=symbol,venue=venue,ts=time.time())
        if venue=="binance":
            d=await _http("https://fapi.binance.com/fapi/v1/depth",{"symbol":symbol,"limit":10})
            ob.bids=s._parse(d.get("bids",[]));ob.asks=s._parse(d.get("asks",[]))
        elif venue=="bybit":
            d=await _http("https://api.bybit.com/v5/market/orderbook",{"category":"linear","symbol":symbol,"limit":10})
            r=d.get("result",{});ob.bids=s._parse(r.get("b",[]));ob.asks=s._parse(r.get("a",[]))
        elif venue=="hyperliquid":
            coin=symbol.replace("USDT","")
            d=await _http("https://api.hyperliquid.xyz/info",method="POST",json_body={"type":"l2Book","coin":coin})
            lvls=d.get("levels",[[],[]])
            for idx,attr in [(0,"bids"),(1,"asks")]:
                parsed=[];cum_q=cum_n=0.0
                for lv in (lvls[idx] if idx<len(lvls) else []):
                    pf,qf=float(lv.get("px",0)),float(lv.get("sz",0));cum_q+=qf;cum_n+=pf*qf
                    parsed.append(BookLevel(pf,qf,cum_q,cum_n))
                setattr(ob,attr,parsed)
        elif venue=="gate":
            contract=symbol[:-4]+"_USDT"
            d=await _http("https://api.gateio.ws/api/v4/futures/usdt/order_book",{"contract":contract,"limit":10})
            ob.bids=s._parse([[x.get("p",0),x.get("s",0)] for x in d.get("bids",[])])
            ob.asks=s._parse([[x.get("p",0),x.get("s",0)] for x in d.get("asks",[])])
        elif venue=="okx":
            inst=symbol[:-4]+"-USDT-SWAP"
            d=await _http("https://www.okx.com/api/v5/market/books",{"instId":inst,"sz":"10"})
            data=d.get("data",[{}])[0] if d.get("data") else {}
            ob.bids=s._parse(data.get("bids",[]));ob.asks=s._parse(data.get("asks",[]))
        elif venue=="bitget":
            d=await _http("https://api.bitget.com/api/v2/mix/market/depth",{"productType":"USDT-FUTURES","symbol":symbol,"limit":"10"})
            data=d.get("data",{});ob.bids=s._parse(data.get("bids",[]));ob.asks=s._parse(data.get("asks",[]))
        elif venue=="mexc":
            d=await _http(f"https://contract.mexc.com/api/v1/contract/depth/{symbol}",{"limit":10})
            data=d.get("data",{});ob.bids=s._parse(data.get("bids",[]));ob.asks=s._parse(data.get("asks",[]))
        elif venue=="kucoin":
            ksym=symbol.replace("USDT","USDTM")
            d=await _http("https://api-futures.kucoin.com/api/v1/level2/depth20",{"symbol":ksym})
            data=d.get("data",{});ob.bids=s._parse(data.get("bids",[]));ob.asks=s._parse(data.get("asks",[]))
        elif venue=="backpack":
            base=symbol.replace("USDT","");bpsym=f"{base}_USDC_PERP"
            d=await _http(f"https://api.backpack.exchange/api/v1/depth",{"symbol":bpsym})
            if isinstance(d,dict):
                ob.bids=s._parse(d.get("bids",[]));ob.asks=s._parse(d.get("asks",[]))
        else:return None
        return ob if(ob.bids or ob.asks) else None

class ExecutionSimulator:
    @staticmethod
    def simulate_fill(book:OrderBook,side:str,notional_usd:float)->dict:
        levels=book.asks if side=="BUY" else book.bids
        if not levels:
            return{"avg_price":0,"slippage_bps":float('inf'),"filled_usd":0,"filled_qty":0,"levels_consumed":0,"unfilled_usd":notional_usd}
        best=levels[0].price;remaining=notional_usd;total_qty=total_cost=0.0;consumed=0
        for lv in levels:
            avail=lv.price*lv.qty;take=min(remaining,avail);qty=take/lv.price
            total_qty+=qty;total_cost+=take;remaining-=take;consumed+=1
            if remaining<=0.001:break
        if total_qty==0:
            return{"avg_price":0,"slippage_bps":float('inf'),"filled_usd":0,"filled_qty":0,"levels_consumed":0,"unfilled_usd":notional_usd}
        avg_px=total_cost/total_qty;slip=abs(avg_px-best)/best*10_000
        return{"avg_price":round(avg_px,8),"slippage_bps":round(slip,2),"filled_usd":round(total_cost,2),
               "filled_qty":round(total_qty,8),"levels_consumed":consumed,"unfilled_usd":round(remaining,2)}

    @staticmethod
    def simulate_arb_pair(book_a:OrderBook,book_b:OrderBook,notional_usd:float,side_a:str="SELL",side_b:str="BUY")->dict:
        fill_a=ExecutionSimulator.simulate_fill(book_a,side_a,notional_usd)
        fill_b=ExecutionSimulator.simulate_fill(book_b,side_b,notional_usd)
        total_slip=fill_a["slippage_bps"]+fill_b["slippage_bps"]
        worst_fill=max(fill_a["unfilled_usd"],fill_b["unfilled_usd"])
        return{"leg_a":fill_a,"leg_b":fill_b,"total_slippage_bps":round(total_slip,2),
               "feasible":worst_fill<notional_usd*0.05,
               "effective_notional":min(fill_a["filled_usd"],fill_b["filled_usd"])}

@dataclass
class LatencySample:
    venue:str;phase:str;ms:float;ts:float=field(default_factory=time.time)

class LatencyProfiler:
    def __init__(s,window:int=200):
        s._window=window;s._samples:Dict[str,deque]={};s._leg_imbalance:deque=deque(maxlen=window)
    def record(s,venue:str,phase:str,ms:float):
        key=f"{venue}:{phase}"
        if key not in s._samples:s._samples[key]=deque(maxlen=s._window)
        s._samples[key].append(LatencySample(venue,phase,ms))
    def record_leg_imbalance(s,ms_diff:float):s._leg_imbalance.append(ms_diff)
    def stats(s,venue:str,phase:str)->dict:
        key=f"{venue}:{phase}";samples=s._samples.get(key,deque())
        if not samples:return{"p50":0,"p95":0,"p99":0,"mean":0,"n":0}
        vals=[x.ms for x in samples]
        return{"p50":round(np.percentile(vals,50),1),"p95":round(np.percentile(vals,95),1),
               "p99":round(np.percentile(vals,99),1),"mean":round(statistics.mean(vals),1),"n":len(vals)}
    def venue_summary(s,venue:str)->dict:
        return{p:s.stats(venue,p) for p in("fetch","signal","order","fill","round_trip") if f"{venue}:{p}" in s._samples}
    def all_summaries(s)->dict:
        venues=set(k.split(":")[0] for k in s._samples)
        return{v:s.venue_summary(v) for v in sorted(venues)}
    def leg_imbalance_stats(s)->dict:
        if not s._leg_imbalance:return{"p50":0,"p95":0,"max":0,"n":0}
        vals=list(s._leg_imbalance)
        return{"p50":round(np.percentile(vals,50),1),"p95":round(np.percentile(vals,95),1),"max":round(max(vals),1),"n":len(vals)}
    def is_venue_slow(s,venue:str,threshold_ms:float=2000)->bool:
        st=s.stats(venue,"round_trip");return st["p95"]>threshold_ms if st["n"]>=5 else False

class LatencyTimer:
    def __init__(s,profiler:LatencyProfiler,venue:str,phase:str):
        s._p=profiler;s._v=venue;s._ph=phase;s._start=0.0
    def __enter__(s):s._start=time.monotonic();return s
    def __exit__(s,*_):s._p.record(s._v,s._ph,(time.monotonic()-s._start)*1000)
    @property
    def elapsed_ms(s)->float:return(time.monotonic()-s._start)*1000

class MarketRegime:
    REGIMES={
        "TRENDING":  {"spread_mult":1.5,"omega_floor":40,"split_delay":0.3,"max_hold_mult":0.5},
        "VOLATILE":  {"spread_mult":2.0,"omega_floor":60,"split_delay":0.2,"max_hold_mult":0.3},
        "LOW_LIQ":   {"spread_mult":1.0,"omega_floor":80,"split_delay":1.0,"max_hold_mult":0.7},
        "CALM":      {"spread_mult":1.0,"omega_floor":20,"split_delay":0.5,"max_hold_mult":1.0},
    }
    def __init__(s,lookback:int=120,vol_window:int=30):
        s._lookback=lookback;s._vol_window=vol_window
        s._prices:Dict[str,deque]={};s._spreads:Dict[str,deque]={}
        s._current:Dict[str,str]={};s._global="CALM"
        s.vol_high=0.015;s.trend_threshold=0.02;s.liq_spread_bps=30
    def update_price(s,symbol:str,price:float,ts:float=None):
        ts=ts or time.time()
        if symbol not in s._prices:s._prices[symbol]=deque(maxlen=s._lookback)
        s._prices[symbol].append((ts,price))
    def update_spread(s,symbol:str,spread_bps:float):
        if symbol not in s._spreads:s._spreads[symbol]=deque(maxlen=s._lookback)
        s._spreads[symbol].append(spread_bps)
    def classify(s,symbol:str)->str:
        prices=s._prices.get(symbol,deque());spreads=s._spreads.get(symbol,deque())
        if spreads and len(spreads)>=5:
            if statistics.mean(list(spreads)[-5:])>s.liq_spread_bps:
                s._current[symbol]="LOW_LIQ";return"LOW_LIQ"
        if len(prices)<s._vol_window:s._current[symbol]="CALM";return"CALM"
        recent=list(prices)[-s._vol_window:];px=[p for _,p in recent]
        rets=np.diff(np.log(px));rvol=float(np.std(rets))
        if rvol>s.vol_high:s._current[symbol]="VOLATILE";return"VOLATILE"
        total_ret=(px[-1]-px[0])/px[0]
        if abs(total_ret)>s.trend_threshold:s._current[symbol]="TRENDING";return"TRENDING"
        s._current[symbol]="CALM";return"CALM"
    def classify_global(s,symbols:List[str]=None)->str:
        syms=symbols or list(s._current.keys())
        if not syms:return"CALM"
        counts={}
        for sym in syms:r=s._current.get(sym,s.classify(sym));counts[r]=counts.get(r,0)+1
        for r in("VOLATILE","LOW_LIQ","TRENDING","CALM"):
            if counts.get(r,0)/len(syms)>0.3:s._global=r;return r
        s._global="CALM";return"CALM"
    def get_params(s,symbol:str=None)->dict:
        regime=s._current.get(symbol,s._global) if symbol else s._global
        return s.REGIMES.get(regime,s.REGIMES["CALM"])
    def dashboard_str(s)->str:
        counts={}
        for r in s._current.values():counts[r]=counts.get(r,0)+1
        return f"Global={s._global} | {' '.join(f'{r}:{n}' for r,n in sorted(counts.items()))}"

@dataclass
class HedgeState:
    symbol:str;v_a:str;v_b:str;target_qty:float;qty_a:float;qty_b:float
    px_a:float=0.0;px_b:float=0.0;last_check:float=0.0;rehedge_count:int=0
    divergence_history:deque=field(default_factory=lambda:deque(maxlen=60))
    @property
    def imbalance_pct(s)->float:return abs(s.qty_a-s.qty_b)/s.target_qty*100 if s.target_qty else 0.0
    @property
    def px_divergence_pct(s)->float:
        return abs(s.px_a-s.px_b)/((s.px_a+s.px_b)/2)*100 if s.px_a>0 and s.px_b>0 else 0.0
    @property
    def net_exposure_usd(s)->float:
        mid=(s.px_a+s.px_b)/2 if s.px_a>0 and s.px_b>0 else 1
        return abs(s.qty_a-s.qty_b)*mid

class HedgeMonitor:
    def __init__(s,imbalance_warn_pct:float=5.0,imbalance_rehedge_pct:float=15.0,
                 px_diverge_warn_pct:float=1.0,px_diverge_emergency_pct:float=3.0,
                 max_rehedge_per_pos:int=3):
        s.imb_warn=imbalance_warn_pct;s.imb_rehedge=imbalance_rehedge_pct
        s.px_warn=px_diverge_warn_pct;s.px_emergency=px_diverge_emergency_pct
        s.max_rehedge=max_rehedge_per_pos
        s._states:Dict[str,HedgeState]={};s._alerts:deque=deque(maxlen=200)
    def register(s,symbol:str,v_a:str,v_b:str,qty:float):
        s._states[symbol]=HedgeState(symbol=symbol,v_a=v_a,v_b=v_b,target_qty=qty,qty_a=qty,qty_b=qty)
        log.info(f"  Hedge monitor: registered {symbol} {v_a}↔{v_b} qty={qty}")
    def unregister(s,symbol:str):s._states.pop(symbol,None)
    def update_prices(s,symbol:str,px_a:float,px_b:float):
        st=s._states.get(symbol)
        if st:st.px_a=px_a;st.px_b=px_b;st.divergence_history.append((time.time(),st.px_divergence_pct));st.last_check=time.time()
    def update_quantities(s,symbol:str,qty_a:float,qty_b:float):
        st=s._states.get(symbol)
        if st:st.qty_a=qty_a;st.qty_b=qty_b

    async def check_all(s,venues:dict,exec_fn=None,close_fn=None)->List[dict]:
        actions=[]
        for sym,state in list(s._states.items()):
            act=await s._check_one(state,venues,exec_fn,close_fn)
            if act:actions.append(act)
        return actions

    async def _check_one(s,st:HedgeState,venues,exec_fn,close_fn)->Optional[dict]:
        div=st.px_divergence_pct
        if div>s.px_emergency:
            alert={"type":"EMERGENCY_CLOSE","symbol":st.symbol,"reason":f"px divergence {div:.2f}% > {s.px_emergency}%","px_a":st.px_a,"px_b":st.px_b}
            s._alerts.append(alert);log.warning(f"  🚨 HEDGE EMERGENCY {st.symbol}: px div {div:.2f}%");return alert
        if div>s.px_warn:
            log.warning(f"  ⚠️ HEDGE WARN {st.symbol}: px div {div:.2f}%")
            s._alerts.append({"type":"PX_WARN","symbol":st.symbol,"div_pct":div})
        imb=st.imbalance_pct
        if imb>s.imb_rehedge:
            if st.rehedge_count>=s.max_rehedge:
                alert={"type":"FORCE_CLOSE","symbol":st.symbol,"reason":f"max re-hedges ({s.max_rehedge}), imb {imb:.1f}%"}
                s._alerts.append(alert);log.warning(f"  🚨 FORCE CLOSE {st.symbol}: max re-hedges");return alert
            diff=st.qty_a-st.qty_b
            if abs(diff)>0 and exec_fn:
                venue,side,qty=(st.v_b,"BUY",abs(diff)) if diff>0 else (st.v_a,"SELL",abs(diff))
                log.info(f"  🔄 RE-HEDGE {st.symbol}: {side} {qty:.4f} @ {venue} (imb {imb:.1f}%)")
                try:
                    await exec_fn(venue,st.symbol,side,qty);st.rehedge_count+=1
                    if diff>0:st.qty_b+=qty
                    else:st.qty_a+=qty
                except Exception as e:log.error(f"  Re-hedge failed {st.symbol}: {e}")
                return{"type":"REHEDGE","symbol":st.symbol,"side":side,"venue":venue,"qty":qty,"imbalance_before":imb}
        elif imb>s.imb_warn:
            log.info(f"  ⚠️ Hedge drift {st.symbol}: imb {imb:.1f}%")
        return None

    def status_all(s)->List[dict]:
        out=[]
        for sym,st in s._states.items():
            out.append({"symbol":sym,"venue_a":st.v_a,"venue_b":st.v_b,"qty_a":st.qty_a,"qty_b":st.qty_b,
                "imbalance_pct":round(st.imbalance_pct,2),"px_divergence_pct":round(st.px_divergence_pct,4),
                "net_exposure_usd":round(st.net_exposure_usd,2),"rehedge_count":st.rehedge_count,
                "status":"🟢" if st.imbalance_pct<s.imb_warn else "🟡" if st.imbalance_pct<s.imb_rehedge else "🔴"})
        return out
    def recent_alerts(s,n:int=10)->List[dict]:return list(s._alerts)[-n:]

@dataclass
class FillRecord:
    venue:str;symbol:str;side:str;requested_qty:float;filled_qty:float
    slippage_bps:float;latency_ms:float;ts:float=field(default_factory=time.time)
    @property
    def fill_rate(s)->float:return s.filled_qty/s.requested_qty if s.requested_qty>0 else 0.0

class FillProbabilityModel:
    def __init__(s,window:int=500):s._history:Dict[str,deque]={};s._window=window;s._half_life=50
    def record_fill(s,rec:FillRecord):
        key=rec.venue
        if key not in s._history:s._history[key]=deque(maxlen=s._window)
        s._history[key].append(rec)

    def estimate(s,venue:str,symbol:str,side:str,notional_usd:float,
                 book_depth_usd:float,spread_bps:float,latency_p95_ms:float,
                 spread_volatility:float=0.0)->dict:
        # P_depth: book absorption (sigmoid)
        if book_depth_usd<=0:p_depth=0.0
        else:
            cr=min(notional_usd/book_depth_usd,10.0)
            p_depth=1.0/(1.0+math.exp(min(3.0*(cr-0.5),500)))
        # P_speed: latency risk (Poisson model)
        if latency_p95_ms<=0:p_speed=0.95
        else:
            update_rate=10.0;window_sec=latency_p95_ms/1000.0
            p_adverse=1.0-math.exp(-update_rate*window_sec*0.3)
            spread_buffer=min(spread_bps/20.0,1.0)
            p_speed=max(0.01,min(1.0,1.0-p_adverse*(1.0-spread_buffer*0.5)))
        # P_hist: empirical fill rate (exponentially weighted)
        records=s._history.get(venue,deque())
        if len(records)<5:p_hist=0.85;confidence=0.2
        else:
            rates,weights=[],[]
            for i,rec in enumerate(reversed(records)):
                w=math.exp(-i/s._half_life);rates.append(rec.fill_rate);weights.append(w)
            p_hist=sum(r*w for r,w in zip(rates,weights))/sum(weights)
            confidence=min(1.0,len(records)/100.0)
        # combine (geometric mean)
        p_fill=(p_depth*p_speed*p_hist)**(1.0/3.0)
        if spread_volatility>0:p_fill*=1.0/(1.0+spread_volatility*100)
        p_fill=max(0.0,min(1.0,p_fill))
        rec="GO" if p_fill>=0.75 else "REDUCE" if p_fill>=0.50 else "SKIP"
        return{"p_fill":round(p_fill,4),"p_depth":round(p_depth,4),"p_speed":round(p_speed,4),
               "p_hist":round(p_hist,4),"confidence":round(confidence if 'confidence' in dir() else 0.2,2),"recommendation":rec}
    def venue_stats(s)->dict:
        out={}
        for venue,records in s._history.items():
            if not records:continue
            rates=[r.fill_rate for r in records];slips=[r.slippage_bps for r in records]
            out[venue]={"n":len(records),"fill_rate_mean":round(statistics.mean(rates),4),
                "slippage_mean_bps":round(statistics.mean(slips),2),"slippage_p95_bps":round(np.percentile(slips,95),2)}
        return out

@dataclass
class SpreadSnapshot:
    spread:float;ts:float

class AdversarialDetector:
    def __init__(s,lookback:int=200):
        s._spread_history:Dict[str,deque]={};s._half_lives:Dict[str,deque]={}
        s._fill_failures:Dict[str,deque]={};s._lookback=lookback
        s.half_life_danger_s=30.0;s.half_life_caution_s=120.0;s.failure_spike_threshold=3

    def update_spread(s,symbol:str,v_a:str,v_b:str,spread:float):
        key=f"{symbol}:{v_a}:{v_b}"
        if key not in s._spread_history:s._spread_history[key]=deque(maxlen=s._lookback)
        s._spread_history[key].append(SpreadSnapshot(spread,time.time()))
        if len(s._spread_history[key])>=10:s._measure_half_life(symbol,s._spread_history[key])

    def _measure_half_life(s,symbol:str,history:deque):
        snaps=list(history);peak_idx=-1;peak_val=0
        for i in range(len(snaps)-2,0,-1):
            if snaps[i].spread>snaps[i-1].spread and snaps[i].spread>snaps[i+1].spread:
                if snaps[i].spread>peak_val:peak_idx=i;peak_val=snaps[i].spread
                break
        if peak_idx<0 or peak_val<=0:return
        half_target=peak_val*0.5
        for j in range(peak_idx+1,len(snaps)):
            if snaps[j].spread<=half_target:
                hl=snaps[j].ts-snaps[peak_idx].ts
                if hl>0:
                    if symbol not in s._half_lives:s._half_lives[symbol]=deque(maxlen=50)
                    s._half_lives[symbol].append(hl)
                return

    def record_fill_failure(s,venue:str):
        if venue not in s._fill_failures:s._fill_failures[venue]=deque(maxlen=100)
        s._fill_failures[venue].append(time.time())

    def assess(s,symbol:str,v_a:str,v_b:str)->dict:
        hl_data=s._half_lives.get(symbol,deque())
        median_hl=float(np.median(list(hl_data))) if len(hl_data)>=3 else None
        now=time.time();front_run=False
        for venue in(v_a,v_b):
            fails=s._fill_failures.get(venue,deque())
            if sum(1 for t in fails if now-t<60)>=s.failure_spike_threshold:front_run=True
        # spread compression speed
        key=f"{symbol}:{v_a}:{v_b}";history=s._spread_history.get(key,deque());compression_rate=0.0
        if len(history)>=5:
            recent=list(history)[-5:]
            if recent[0].spread>0:
                elapsed=recent[-1].ts-recent[0].ts
                if elapsed>0:compression_rate=(recent[0].spread-recent[-1].spread)/recent[0].spread/elapsed
        if front_run:level="EXTREME";size_mult=0.0
        elif median_hl is not None and median_hl<s.half_life_danger_s:level="HIGH";size_mult=0.25
        elif median_hl is not None and median_hl<s.half_life_caution_s:level="MEDIUM";size_mult=0.60
        elif compression_rate>0.01:level="MEDIUM";size_mult=0.60
        else:level="LOW";size_mult=1.0
        return{"competition_level":level,"half_life_s":round(median_hl,1) if median_hl else None,
               "front_run_risk":front_run,"compression_rate":round(compression_rate,6),
               "size_multiplier":size_mult,"n_samples":len(hl_data)}

    def dashboard_str(s)->str:
        parts=[]
        for sym,hls in s._half_lives.items():
            if hls:parts.append(f"{sym.replace('USDT','')}:{np.median(list(hls)):.0f}s")
        return "HL: "+" | ".join(parts[:8]) if parts else "HL: (collecting...)"

class OmegaV2:
    def __init__(s,leverage:float=2.0):s.leverage=leverage
    def score(s,spread:float,cost_a:float,cost_b:float,vol_a:float,vol_b:float,
              slippage_bps:float=0.0,p_fill:float=1.0,competition_mult:float=1.0,
              latency_cost_bps:float=0.0,regime_spread_mult:float=1.0,spread_vol:float=0.0,
              px_spread:float=0.0,min_vol:float=3_000_000)->dict:
        if spread<=0:return{"omega":0,"components":{},"go":False}
        spread=min(spread,0.02);total_fees=(cost_a+cost_b)*2
        slip_cost=slippage_bps/10_000;lat_cost=latency_cost_bps/10_000
        gross=spread*regime_spread_mult;net=gross-slip_cost-lat_cost
        if net<=0:return{"omega":0,"components":{"net":net},"go":False}
        be=total_fees/net
        if be>12:return{"omega":0,"components":{"be":be},"go":False}
        hold=max(be*2.5,3);fee_pp=total_fees/hold;net_pp=net-fee_pp
        if net_pp<=0:return{"omega":0,"components":{"net_pp":net_pp},"go":False}
        raw_apr=min(net_pp*3*365*100,500);lev_apr=raw_apr*s.leverage
        mv=min(vol_a,vol_b)
        if mv<min_vol:return{"omega":0,"components":{"vol":mv},"go":False}
        liq=min(math.sqrt(mv/1e6),10.0);exec_pen=1.0+px_spread*50
        stability=1.0/(1.0+spread_vol*200) if spread_vol>0 else 1.0
        omega=round(max(0,lev_apr*liq*p_fill*competition_mult*stability/exec_pen),1)
        e_daily=net_pp*3*1000*s.leverage
        return{"omega":omega,"components":{"raw_apr":round(raw_apr,1),"lev_apr":round(lev_apr,1),
            "net_pp":round(net_pp,6),"be":round(be,1),"p_fill":round(p_fill,3),
            "competition":round(competition_mult,2),"stability":round(stability,3),
            "liq":round(liq,2),"slip_bps":round(slippage_bps,2),"lat_bps":round(latency_cost_bps,2),
            "e_daily_1k":round(e_daily,4)},"go":omega>0 and p_fill>=0.15}

class DynamicSizer:
    def __init__(s,max_pct:float=0.25,max_heat:float=0.80,kelly_frac:float=0.5,
                 min_size:float=50.0,max_size:float=3000.0):
        s.max_pct=max_pct;s.max_heat=max_heat;s.kelly_frac=kelly_frac
        s.min_size=min_size;s.max_size=max_size
        s._wins:deque=deque(maxlen=200);s._losses:deque=deque(maxlen=200)
    def record_trade(s,pnl:float):
        if pnl>=0:s._wins.append(pnl)
        else:s._losses.append(abs(pnl))
    def _kelly(s)->float:
        if len(s._wins)<5 or len(s._losses)<3:return s.kelly_frac
        p=len(s._wins)/(len(s._wins)+len(s._losses))
        avg_w=statistics.mean(s._wins) if s._wins else 1
        avg_l=statistics.mean(s._losses) if s._losses else 1
        b=avg_w/max(avg_l,0.001);q=1-p
        kelly=(p*b-q)/max(b,0.001)
        return max(0,min(kelly,0.5))*s.kelly_frac
    def size(s,capital:float,current_exposure:float,p_fill:float=1.0,competition_mult:float=1.0,
             omega:float=100.0,regime:str="CALM",current_dd_pct:float=0.0,max_dd_pct:float=0.05)->dict:
        if capital<=0:return{"size_usd":0,"reason":"no capital"}
        heat_avail=capital*s.max_heat-current_exposure
        if heat_avail<=s.min_size:return{"size_usd":0,"reason":"heat maxed"}
        kelly_f=s._kelly();base=capital*kelly_f
        omega_sc=min(omega/500,1.5);fill_adj=max(0.3,p_fill);comp_adj=max(0.1,competition_mult)
        regime_adj={"CALM":1.0,"TRENDING":0.7,"VOLATILE":0.4,"LOW_LIQ":0.3}.get(regime,0.5)
        dd_ratio=current_dd_pct/max(max_dd_pct,0.001);dd_adj=max(0.1,1.0-dd_ratio*0.8)
        total=omega_sc*fill_adj*comp_adj*regime_adj*dd_adj
        sized=min(base*total,capital*s.max_pct,heat_avail,s.max_size);sized=max(0,sized)
        if sized<s.min_size:return{"size_usd":0,"kelly_f":kelly_f,"reason":"below min"}
        return{"size_usd":round(sized,2),"kelly_f":round(kelly_f,4),"total_mult":round(total,4),
               "adj":{"omega":round(omega_sc,3),"fill":round(fill_adj,3),"comp":round(comp_adj,3),
                      "regime":regime_adj,"dd":round(dd_adj,3)}}

@dataclass
class TradeEvent:
    price:float;qty:float;side:str;ts:float  # side = "BUY"/"SELL" (aggressor)
@dataclass
class BookDelta:
    bid_depth_usd:float;ask_depth_usd:float;ts:float

class OrderFlowAnalyzer:
    def __init__(s,window:int=500,bucket_vol:float=10000.0):
        s._trades:Dict[str,deque]={};s._books:Dict[str,deque]={};s._window=window;s._bucket_vol=bucket_vol
    def add_trade(s,symbol:str,event:TradeEvent):
        if symbol not in s._trades:s._trades[symbol]=deque(maxlen=s._window)
        s._trades[symbol].append(event)
    def add_book_snapshot(s,symbol:str,delta:BookDelta):
        if symbol not in s._books:s._books[symbol]=deque(maxlen=200)
        s._books[symbol].append(delta)

    def trade_imbalance(s,symbol:str,lookback_s:float=60.0)->float:
        trades=s._trades.get(symbol,deque())
        if not trades:return 0.0
        now=time.time();buy_vol=sell_vol=0.0
        for t in reversed(trades):
            if now-t.ts>lookback_s:break
            n=t.price*t.qty
            if t.side=="BUY":buy_vol+=n
            else:sell_vol+=n
        total=buy_vol+sell_vol
        return(buy_vol-sell_vol)/total if total>0 else 0.0

    def book_imbalance(s,symbol:str)->float:
        snaps=s._books.get(symbol,deque())
        if not snaps:return 0.0
        latest=snaps[-1];total=latest.bid_depth_usd+latest.ask_depth_usd
        return(latest.bid_depth_usd-latest.ask_depth_usd)/total if total>0 else 0.0

    def vpin_lite(s,symbol:str,n_buckets:int=20)->float:
        trades=list(s._trades.get(symbol,deque()))
        if len(trades)<20:return 0.5+0.3*(1-min(len(trades)/20,1))  # bias toward "uncertain=risky" with few samples
        buckets=[];cb=cs=ct=0.0
        for t in trades:
            n=t.price*t.qty
            if t.side=="BUY":cb+=n
            else:cs+=n
            ct+=n
            if ct>=s._bucket_vol:
                buckets.append(abs(cb-cs)/max(ct,1));cb=cs=ct=0.0
        if not buckets:return 0.5
        recent=buckets[-n_buckets:] if len(buckets)>=n_buckets else buckets
        return round(statistics.mean(recent),4)

    def flow_momentum(s,symbol:str,periods:int=10,period_s:float=10.0)->float:
        trades=list(s._trades.get(symbol,deque()))
        if len(trades)<10:return 0.0
        now=time.time();buckets=[{"bv":0.0,"sv":0.0} for _ in range(periods)]
        for t in trades:
            age=now-t.ts;idx=int(age/period_s)
            if 0<=idx<periods:
                n=t.price*t.qty
                if t.side=="BUY":buckets[idx]["bv"]+=n
                else:buckets[idx]["sv"]+=n
        imbalances=[]
        for b in buckets:
            total=b["bv"]+b["sv"]
            if total>0:imbalances.append((b["bv"]-b["sv"])/total)
        if not imbalances:return 0.0
        alpha=2.0/(len(imbalances)+1);ema=imbalances[0]
        for val in imbalances[1:]:ema=alpha*val+(1-alpha)*ema
        return round(ema,4)

    def analyze(s,symbol:str,regime:str="CALM")->dict:
        tir=s.trade_imbalance(symbol);bi=s.book_imbalance(symbol)
        vpin=s.vpin_lite(symbol);mom=s.flow_momentum(symbol)
        # regime-adaptive weights
        w={"VOLATILE":(0.2,0.1,0.7),"TRENDING":(0.3,0.1,0.6),"LOW_LIQ":(0.3,0.5,0.2),"CALM":(0.4,0.2,0.4)}.get(regime,(0.4,0.2,0.4))
        composite=tir*w[0]+bi*w[1]+mom*w[2]
        toxicity="HIGH" if vpin>0.7 else "MEDIUM" if vpin>0.5 else "LOW"
        return{"trade_imbalance":round(tir,4),"book_imbalance":round(bi,4),"vpin":vpin,
               "flow_momentum":mom,"composite":round(composite,4),"toxicity":toxicity,
               "short_safe":composite<0.3 and toxicity!="HIGH",
               "long_safe":composite>-0.3 and toxicity!="HIGH"}

    def dashboard_str(s,symbols:List[str]=None)->str:
        syms=symbols or list(s._trades.keys())
        if not syms:return "Flow: (no data)"
        parts=[]
        for sym in syms[:6]:
            a=s.analyze(sym);parts.append(f"{sym.replace('USDT','')}:TIR={a['trade_imbalance']:+.2f}")
        return " | ".join(parts)

class BinanceWS:
    def __init__(s):s.url="wss://fstream.binance.com/ws/!markPrice@arr@1s";s.data={};s.running=False;s._task=None;s.last=0
    async def start(s):
        s.running=True;s._task=asyncio.create_task(s._loop())
        log.info("WS: connecting")
    async def _loop(s):
        try:import websockets
        except:log.warning("WS: pip install websockets");s.running=False;return
        while s.running:
            try:
                async with websockets.connect(s.url,ping_interval=20,ping_timeout=10) as ws:
                    log.info("WS: connected")
                    while s.running:
                        msg=await asyncio.wait_for(ws.recv(),timeout=5)
                        arr=json.loads(msg)
                        if isinstance(arr,list):
                            for d in arr:
                                sy=d.get("s","")
                                if sy.endswith("USDT"):s.data[sy]={"fr":float(d.get("r",0)),"mk":float(d.get("P",0) or d.get("p",0)),"ix":float(d.get("i",0)),"ts":time.time()}
                            s.last=time.time()
            except asyncio.CancelledError:break
            except:await asyncio.sleep(3)
    def fresh(s):return time.time()-s.last<10
    def fr(s,sy):d=s.data.get(sy);return d["fr"] if d and time.time()-d["ts"]<10 else None
    def mk(s,sy):d=s.data.get(sy);return d["mk"] if d and time.time()-d["ts"]<10 else None

def omega_score(spread,vol_a,vol_b,cost_a,cost_b,px_spread=0):
    if spread<=0:return 0
    spread=min(spread,0.02)
    total_cost=(cost_a+cost_b)*2
    slip_buffer=spread*0.2;latency_pen=spread*0.1
    net_per_period=spread-slip_buffer-latency_pen
    if net_per_period<=0:return 0
    be_periods=total_cost/net_per_period
    if be_periods>12:return 0
    hold_periods=max(be_periods*3,3)
    cost_per_period=total_cost/hold_periods
    net=net_per_period-cost_per_period
    if net<=0:return 0
    decay=0.75;apr=min(net*decay*3*365*100,500);lev_apr=apr*LEV
    min_vol=min(vol_a,vol_b)
    if min_vol<MIN_VOL:return 0
    liq=math.sqrt(min_vol/1e6);exec_penalty=1+px_spread*50
    omega=lev_apr*liq/exec_penalty
    return round(omega,1)

async def scan_all(venues):
    active_venues=[v for v in venues if not v._disabled]
    log.info(f"Scanning {len(active_venues)} venues...")
    tasks=[v.safe_fetch() for v in active_venues]
    await asyncio.gather(*tasks,return_exceptions=True)
    active=[v for v in active_venues if v.funding]
    log.info(f"  Active: {', '.join(v.name for v in active)} ({sum(len(v.funding) for v in active)} total pairs)")

    all_syms=set()
    for v in active:all_syms.update(v.funding.keys())
    opps=[]
    for sy in all_syms:
        if not sy.endswith("USDT"):continue
        venue_data=[]
        for v in active:
            if sy in v.funding:venue_data.append({"v":v,"fr":v.funding[sy],"px":v.prices.get(sy,0),"vol":v.volumes.get(sy,0)})
        if not venue_data:continue

        # ── INTERNAL ──
        for vd in venue_data:
            if vd["v"].has_spot and vd["fr"]>0.0003 and vd["vol"]>MIN_VOL:
                sp=omega_score(vd["fr"],vd["vol"],vd["vol"],vd["v"].cost,vd["v"].cost)
                if sp>0:
                    apr=(vd["fr"]-vd["v"].cost*4/24)*1095*100
                    opps.append({"sym":sy,"type":"INTERNAL","v_a":vd["v"].name,"v_b":vd["v"].name,
                        "fr_a":vd["fr"],"fr_b":0,"spread":vd["fr"],"px_spread":0,
                        "apr":apr,"lev_apr":apr*LEV,"omega":sp,
                        "edge":f"SHORT perp + BUY spot @ {vd['v'].name}","vol":vd["vol"]})

        # ── CROSS: perp-perp ──
        if len(venue_data)>=2:
            vds=sorted(venue_data,key=lambda x:x["fr"])
            long_d=vds[0];short_d=vds[-1]
            if short_d["v"].name!=long_d["v"].name:
                sp=short_d["fr"]-long_d["fr"]
                if sp>=MIN_SPREAD:
                    px_s=abs(short_d["px"]-long_d["px"])/max(short_d["px"],1) if short_d["px"]>0 and long_d["px"]>0 else 0
                    if px_s<MAX_PX_SPREAD:
                        sc=omega_score(sp,short_d["vol"],long_d["vol"],short_d["v"].cost,long_d["v"].cost,px_s)
                        if sc>0:
                            tc=(short_d["v"].cost+long_d["v"].cost)*2
                            net_pp=sp*0.7-sp*0.3;be=tc/max(net_pp,1e-8);hold=max(be*3,3)
                            apr_pp=min((net_pp-tc/hold)*0.75*1095*100,500)
                            opps.append({"sym":sy,"type":"PERP_PERP","v_a":short_d["v"].name,"v_b":long_d["v"].name,
                                "fr_a":short_d["fr"],"fr_b":long_d["fr"],"spread":sp,"px_spread":px_s,
                                "apr":apr_pp,"lev_apr":apr_pp*LEV,"omega":sc*1.5,
                                "edge":f"SHORT@{short_d['v'].name} LONG@{long_d['v'].name}","vol":min(short_d["vol"],long_d["vol"])})

        # ── PRICE ARB (only real transferable tokens, not synthetic indices) ──
        _SYNTH={"SPX500","NASDAQ","DJI","FTSE","DAX","NIKKEI","GOLD","SILVER","OIL","WTI","BRENT","NATGAS","EURUSD","GBPUSD","USDJPY","XAUUSD","XAGUSD"}
        base=sy.replace("USDT","")
        if len(venue_data)>=2 and base not in _SYNTH and not any(c.isdigit() and len(base)>8 for c in base):
            pxs=sorted([vd for vd in venue_data if vd["px"]>0],key=lambda x:x["px"])
            if len(pxs)>=2:
                lo,hi=pxs[0],pxs[-1]
                if lo["v"].name!=hi["v"].name:
                    diff=(hi["px"]-lo["px"])/lo["px"]
                    if 0.002<diff<MAX_PX_SPREAD:
                        tc=(lo["v"].cost+hi["v"].cost)*2;net_p=diff-tc
                        if net_p>0.0005:
                            mv=min(lo["vol"],hi["vol"])
                            sc=min(diff,0.02)*math.sqrt(mv/1e6)*1e4 if mv>0 else 0
                            opps.append({"sym":sy,"type":"PRICE_ARB","v_a":lo["v"].name,"v_b":hi["v"].name,
                                "fr_a":lo["fr"] if "fr" in lo else 0,"fr_b":hi["fr"] if "fr" in hi else 0,
                                "spread":0,"px_spread":diff,"apr":net_p*100*365,"lev_apr":net_p*100*365*LEV,"omega":sc,
                                "edge":f"BUY@{lo['v'].name} ${lo['px']:.4f} → SELL@{hi['v'].name} ${hi['px']:.4f}","vol":mv})

        # ── SPOT-PERP CROSS ──
        binance_v=next((vd for vd in venue_data if vd["v"].has_spot),None)
        if binance_v and len(venue_data)>=2:
            for vd in venue_data:
                if vd["v"].name==binance_v["v"].name:continue
                if vd["fr"]>0.0003 and vd["vol"]>MIN_VOL:
                    tc=(binance_v["v"].cost+vd["v"].cost)*2;net=(vd["fr"]-tc/24)*1095*100
                    if net>MIN_APR:
                        sc=omega_score(vd["fr"],binance_v["vol"],vd["vol"],binance_v["v"].cost,vd["v"].cost)
                        opps.append({"sym":sy,"type":"SPOT_PERP","v_a":vd["v"].name,"v_b":binance_v["v"].name,
                            "fr_a":vd["fr"],"fr_b":binance_v["fr"] if "fr" in binance_v else 0,"spread":vd["fr"],
                            "px_spread":0,"apr":net,"lev_apr":net*LEV,"omega":sc*1.2,
                            "edge":f"SHORT perp@{vd['v'].name} + BUY spot@{binance_v['v'].name}","vol":min(binance_v["vol"],vd["vol"])})

    for o in opps:
        o["apr"]=min(o["apr"],500);o["lev_apr"]=min(o["lev_apr"],500*LEV)
        if o["spread"]>0.02:o["omega"]*=0.1
    opps=[o for o in opps if o.get("omega",0)>0]
    opps.sort(key=lambda o:o.get("omega",0),reverse=True)
    return opps,active

def print_dashboard(opps,active,regime=None,latency=None,hedge_mon=None):
    W=145;now=datetime.now(timezone.utc)
    next_f=8-now.hour%8;next_m=60-now.minute;next_str=f"{next_f-1}h{next_m}m" if next_m<60 else f"{next_f}h0m"
    n_internal=sum(1 for o in opps if o["type"]=="INTERNAL")
    n_perp=sum(1 for o in opps if o["type"]=="PERP_PERP")
    n_px=sum(1 for o in opps if o["type"]=="PRICE_ARB")
    n_sp=sum(1 for o in opps if o["type"]=="SPOT_PERP")
    total_pairs=len(set(o["sym"] for o in opps))
    print(f"\n  {'─'*W}")
    print(f"  NEUTRINO v5.0  ·  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ·  funding {next_str}  ·  {LEV}x")
    print(f"  {len(active)} venues  ·  {total_pairs} pairs  ·  {len(opps)} opps  "
          f"[INT:{n_internal}  PP:{n_perp}  PX:{n_px}  SP:{n_sp}]")
    if regime:print(f"  regime  ·  {regime.dashboard_str()}")
    print(f"  {'─'*W}")

    print(f"\n  ┌─ TOP OPPORTUNITIES {'─'*(W-22)}┐")
    print(f"  │ {'Ω':>5s}  {'Type':10s}  {'Symbol':12s}  {'Short@':>10s}  {'Long@':>10s}  "
          f"{'FR_S':>9s}  {'FR_L':>9s}  {'Spread':>8s}  {'PxSprd':>7s}  {'APR':>6s}  {'LevAPR':>7s}  Edge")
    print(f"  │ {'─'*(W-4)}")
    for o in opps[:25]:
        if o.get("omega",0)<=0:continue
        t=o["type"];tc={"INTERNAL":"🟢","PERP_PERP":"🔵","PRICE_ARB":"🟡","SPOT_PERP":"🟠"}.get(t,"⚪")
        print(f"  │ {o['omega']:>5.0f}  {tc}{t:9s}  {o['sym']:12s}  {o['v_a']:>10s}  {o['v_b']:>10s}  "
              f"{o['fr_a']:>+9.5f}  {o['fr_b']:>+9.5f}  {o['spread']:>+8.5f}  {o['px_spread']:>7.4f}  "
              f"{o['apr']:>5.0f}%  {o['lev_apr']:>6.0f}%  {o['edge']}")
    print(f"  └{'─'*(W-1)}┘")

    print(f"\n  ┌─ VENUE MATRIX {'─'*(60-16)}┐")
    for v in active:
        n=len(v.funding);avg=np.mean(list(v.funding.values())) if v.funding else 0
        pos=sum(1 for r in v.funding.values() if r>0);neg=sum(1 for r in v.funding.values() if r<0)
        sp="SPOT+PERP" if v.has_spot else "PERP"
        bar_pos="█"*min(pos//10,20);bar_neg="░"*min(neg//10,20)
        print(f"  │ {v.name:>12s}  {n:>4d} pairs  avg={avg:+.6f}  +{pos:>3d} {bar_pos}")
        print(f"  │ {'':>12s}  cost={v.cost*100:.2f}%  [{sp:>9s}]  -{neg:>3d} {bar_neg}")
    print(f"  └{'─'*59}┘")

    print(f"\n  ┌─ FUNDING HEATMAP (top 5 per venue) {'─'*(W-38)}┐")
    for v in active:
        if not v.funding:continue
        top5=sorted(v.funding.items(),key=lambda x:abs(x[1]),reverse=True)[:5]
        tokens=" | ".join(f"{s.replace('USDT',''):>6s}:{r:+.4f}" for s,r in top5)
        print(f"  │ {v.name:>12s}  {tokens}")
    print(f"  └{'─'*(W-1)}┘")

    print(f"\n  ┌─ CROSS-VENUE SPREAD PAIRS {'─'*(60-28)}┐")
    pair_counts={}
    for o in opps:
        if o["type"]=="PERP_PERP":
            k=f"{o['v_a']}×{o['v_b']}";pair_counts[k]=pair_counts.get(k,0)+1
    for pair,cnt in sorted(pair_counts.items(),key=lambda x:-x[1])[:8]:
        avg_sp=np.mean([o["spread"] for o in opps if o["type"]=="PERP_PERP" and f"{o['v_a']}×{o['v_b']}"==pair])
        print(f"  │ {pair:>25s}  {cnt:>3d} opps  avg_spread={avg_sp:+.5f}")
    if not pair_counts:print(f"  │ (no cross-venue pairs found)")
    print(f"  └{'─'*59}┘")

    # ── LATENCY PANEL (new v5.0) ──
    if latency:
        lat=latency.all_summaries()
        if lat:
            print(f"\n  ┌─ LATENCY (ms) {'─'*(60-16)}┐")
            print(f"  │ {'Venue':>12s}  {'Phase':>10s}  {'p50':>6s}  {'p95':>6s}  {'p99':>6s}  {'n':>4s}")
            for venue,phases in lat.items():
                for phase,st in phases.items():
                    if st["n"]>0:
                        print(f"  │ {venue:>12s}  {phase:>10s}  {st['p50']:>6.0f}  {st['p95']:>6.0f}  {st['p99']:>6.0f}  {st['n']:>4d}")
            leg=latency.leg_imbalance_stats()
            if leg["n"]>0:print(f"  │ Leg imbalance: p50={leg['p50']:.0f}ms p95={leg['p95']:.0f}ms max={leg['max']:.0f}ms")
            print(f"  └{'─'*59}┘")

    # ── HEDGE PANEL (new v5.0) ──
    if hedge_mon:
        hedges=hedge_mon.status_all()
        if hedges:
            print(f"\n  ┌─ HEDGE MONITOR {'─'*(60-17)}┐")
            print(f"  │ {'':>2s} {'Symbol':12s} {'A→B':>20s} {'Imb%':>6s} {'PxDiv%':>7s} {'$Exp':>8s} {'#RH':>4s}")
            for h in hedges:
                print(f"  │ {h['status']} {h['symbol']:12s} {h['venue_a']}→{h['venue_b']:>10s} "
                      f"{h['imbalance_pct']:>6.2f} {h['px_divergence_pct']:>7.4f} "
                      f"${h['net_exposure_usd']:>7.2f} {h['rehedge_count']:>4d}")
            print(f"  └{'─'*59}┘")
        alerts=hedge_mon.recent_alerts(5)
        if alerts:
            print(f"\n  ┌─ ALERTS {'─'*(60-10)}┐")
            for a in alerts:print(f"  │ {a.get('type','?'):16s} {a.get('symbol',''):12s} {a.get('reason','')}")
            print(f"  └{'─'*59}┘")

    if opps:
        top=opps[0];cap_needed=ACCT*POS_PCT*2
        edge=top["spread"] if top["spread"]>0 else top.get("px_spread",0)
        daily_est=edge*3*cap_needed*LEV if edge>0 else 0
        print(f"\n  ┌─ EXECUTION ESTIMATE (top opportunity) {'─'*(60-41)}┐")
        print(f"  │ Symbol:   {top['sym']}")
        print(f"  │ Type:     {top['type']}  ({top['edge']})")
        print(f"  │ Edge:     {edge:+.5f}  ({edge*100:.3f}%)")
        print(f"  │ Capital:  ${cap_needed:,.0f} per side × {LEV}x = ${cap_needed*LEV:,.0f} notional")
        print(f"  │ Est daily: ${daily_est:.2f}/day  (${daily_est*30:.0f}/month)")
        print(f"  │ Ω score:  {top['omega']:.0f}")
        print(f"  └{'─'*59}┘")
    print(f"\n  {'═'*W}\n")

class Position:
    def __init__(s,sym,type_,v_a,v_b,qty,size_usd,spread,edge,entry_px_a=0,entry_px_b=0):
        s.symbol=sym;s.type=type_;s.v_a=v_a;s.v_b=v_b
        s.qty=qty;s.size_usd=size_usd;s.spread=spread;s.edge=edge
        s.entry_px_a=entry_px_a;s.entry_px_b=entry_px_b
        s.open_ts=datetime.now(timezone.utc);s.funding_collected=0.0
        s.funding_payments=0;s.last_funding_ts=0.0
    def hours_open(s):return(datetime.now(timezone.utc)-s.open_ts).total_seconds()/3600
    def mtm_pnl(s,px_a,px_b):
        """Mark-to-market PnL from price movement (short leg_a, long leg_b)."""
        if s.entry_px_a<=0 or s.entry_px_b<=0:return 0.0
        # short a: profit when price drops; long b: profit when price rises
        pnl_a=(s.entry_px_a-px_a)*s.qty if px_a>0 else 0
        pnl_b=(px_b-s.entry_px_b)*s.qty if px_b>0 and s.type!="INTERNAL" else 0
        return pnl_a+pnl_b

class Engine:
    def __init__(s,venues):
        s.venues={v.name:v for v in venues};s.ws=BinanceWS() if WS_ON else None
        s.positions=[];s.closed=[];s.account=ACCT;s.peak=ACCT;s.running=False;s._sc=0
        s.killed=False;s.consecutive_losses=0
        s.tg_tk,s.tg_ch="",""
        try:
            from bot.telegram import _load_telegram_config
            s.tg_tk,s.tg_ch=_load_telegram_config()
        except Exception as e:log.warning("telegram config load failed: %s", e)
        # ── v5.0 modules ──
        s.depth=DepthFetcher()
        s.latency=LatencyProfiler(window=200)
        s.regime=MarketRegime()
        s.hedge_mon=HedgeMonitor()
        # ── v5.0 modules ──
        s.fill_model=FillProbabilityModel(window=500)
        s.adversarial=AdversarialDetector(lookback=200)
        s.omega_v2=OmegaV2(leverage=LEV)
        s.sizer=DynamicSizer(max_pct=POS_PCT,max_heat=0.80,kelly_frac=0.5,min_size=50,max_size=MAX_EXPO/LEV)
        s.flow=OrderFlowAnalyzer(window=500)
        log.info(f"Engine 5.0 | {'LIVE' if ARB_LIVE else 'DEMO' if ARB_DEMO else 'PAPER'} | {len(venues)} venues | {RUN_ID}")
        s._state_file=DIR/"state"/"positions.json"
        s._load_state()

    def _save_state(s):
        try:
            data={"account":s.account,"peak":s.peak,"killed":s.killed,"consecutive_losses":s.consecutive_losses,
                "positions":[{"symbol":p.symbol,"type":p.type,"v_a":p.v_a,"v_b":p.v_b,"qty":p.qty,
                    "size_usd":p.size_usd,"spread":p.spread,"edge":p.edge,"entry_px_a":p.entry_px_a,
                    "entry_px_b":p.entry_px_b,"open_ts":p.open_ts.isoformat(),"funding_collected":p.funding_collected,
                    "funding_payments":p.funding_payments} for p in s.positions],
                "closed":s.closed,"ts":datetime.now(timezone.utc).isoformat()}
            with open(s._state_file,"w") as f:json.dump(data,f,indent=2,default=str)
        except Exception as e:log.debug(f"Save state: {e}")

    def _load_state(s):
        if not s._state_file.exists():return
        try:
            with open(s._state_file) as f:data=json.load(f)
            s.account=data.get("account",ACCT);s.peak=data.get("peak",ACCT)
            s.killed=data.get("killed",False);s.consecutive_losses=data.get("consecutive_losses",0)
            s.closed=data.get("closed",[])
            for pd in data.get("positions",[]):
                p=Position(pd["symbol"],pd["type"],pd["v_a"],pd["v_b"],pd["qty"],pd["size_usd"],
                    pd["spread"],pd["edge"],pd.get("entry_px_a",0),pd.get("entry_px_b",0))
                p.open_ts=datetime.fromisoformat(pd["open_ts"])
                p.funding_collected=pd.get("funding_collected",0);p.funding_payments=pd.get("funding_payments",0)
                s.positions.append(p)
                s.hedge_mon.register(p.symbol,p.v_a,p.v_b,p.qty)
            if s.positions:log.info(f"  Restored {len(s.positions)} positions from state")
        except Exception as e:log.warning(f"Load state failed: {e}")

    async def _tg(s,txt):
        if not(s.tg_tk and s.tg_ch):return
        import requests as r
        try:await asyncio.get_event_loop().run_in_executor(None,lambda:r.post(f"https://api.telegram.org/bot{s.tg_tk}/sendMessage",json={"chat_id":s.tg_ch,"text":txt,"parse_mode":"HTML"},timeout=10))
        except Exception as e:log.warning("telegram send failed: %s", e)

    def _avail(s):return max(0,s.account-sum(p.size_usd for p in s.positions))

    async def _split_exec(s,venue,sym,side,qty):
        v=s.venues.get(venue)
        if not v:return 0
        qty=v.round_qty(sym,qty)
        if qty<=0:return 0
        chunk=v.round_qty(sym,qty/SPLIT_N);filled=0
        delay=s.regime.get_params(sym).get("split_delay",SPLIT_DLY)
        for i in range(SPLIT_N):
            q=chunk if i<SPLIT_N-1 else v.round_qty(sym,qty-filled)
            if q<=0:break
            actual_fill=q  # default for paper
            with LatencyTimer(s.latency,venue,"order"):
                if ARB_LIVE or ARB_DEMO:
                    r=await v.place_order(sym,side,q)
                    if isinstance(r,dict):
                        if r.get("code") or r.get("retCode"):
                            log.error(f"    Split {i+1} FAILED: {r}");break
                        # parse actual executed qty from response
                        actual_fill=float(r.get("executedQty",0) or r.get("cumExecQty",0)
                            or r.get("result",{}).get("cumExecQty",0) or q)
                    else:
                        log.error(f"    Split {i+1} unexpected response: {r}");break
            log.info(f"    [{venue}] {side} {actual_fill:.6f}/{q:.6f} ({i+1}/{SPLIT_N})")
            filled+=actual_fill
            if i<SPLIT_N-1:await asyncio.sleep(delay)
        return filled

    async def _open(s,opp):
        sym=opp["sym"]

        # ── [M3] REGIME GATE ──
        regime=s.regime.classify(sym)
        params=s.regime.get_params(sym)

        # ── [M1] DEPTH + EXECUTION SIM ──
        notional=min(s._avail()*POS_PCT*LEV,MAX_EXPO)
        with LatencyTimer(s.latency,opp["v_a"],"fetch"):
            book_a=await s.depth.fetch(opp["v_a"],sym)
        with LatencyTimer(s.latency,opp["v_b"],"fetch"):
            book_b=await s.depth.fetch(opp["v_b"],sym)

        slippage_bps=0.0;book_a_depth=notional*2;book_b_depth=notional*2;spread_bps_a=10.0
        if book_a and book_b:
            sim=ExecutionSimulator.simulate_arb_pair(book_a,book_b,notional)
            slippage_bps=sim["total_slippage_bps"]
            book_a_depth=book_a.depth_at_pct("ask" if "SELL" in opp.get("edge","") else "bid",0.001)
            book_b_depth=book_b.depth_at_pct("bid",0.001)
            spread_bps_a=book_a.spread_bps
            s.regime.update_spread(sym,spread_bps_a)
            # [M9] feed book to flow analyzer
            s.flow.add_book_snapshot(sym,BookDelta(
                book_a.depth_at_pct("bid",0.005),book_a.depth_at_pct("ask",0.005),time.time()))

        # ── [M2] LATENCY STATS ──
        lat_a=s.latency.stats(opp["v_a"],"fetch").get("p95",500)
        lat_b=s.latency.stats(opp["v_b"],"fetch").get("p95",500)

        # ── [M6] ADVERSARIAL ──
        s.adversarial.update_spread(sym,opp["v_a"],opp["v_b"],opp["spread"])
        comp=s.adversarial.assess(sym,opp["v_a"],opp["v_b"])

        # ── [M5] FILL PROBABILITY ──
        fp_a=s.fill_model.estimate(opp["v_a"],sym,"SELL",notional,book_a_depth,spread_bps_a,lat_a)
        fp_b=s.fill_model.estimate(opp["v_b"],sym,"BUY",notional,book_b_depth,spread_bps_a,lat_b)
        p_fill=fp_a["p_fill"]*fp_b["p_fill"]

        # ── [M9] FLOW CHECK ──
        flow_analysis=s.flow.analyze(sym,regime)
        flow_ok=flow_analysis["short_safe"] and flow_analysis["toxicity"]!="HIGH"

        # ── [M7] OMEGA V2 ──
        v_a_obj=s.venues.get(opp["v_a"]);v_b_obj=s.venues.get(opp["v_b"])
        cost_a=v_a_obj.cost if v_a_obj else 0.001;cost_b=v_b_obj.cost if v_b_obj else 0.001
        lat_cost_bps=(lat_a+lat_b)/2000*0.5
        omega_r=s.omega_v2.score(
            spread=opp["spread"],cost_a=cost_a,cost_b=cost_b,
            vol_a=opp.get("vol",MIN_VOL),vol_b=opp.get("vol",MIN_VOL),
            slippage_bps=slippage_bps,p_fill=p_fill,competition_mult=comp["size_multiplier"],
            latency_cost_bps=lat_cost_bps,regime_spread_mult=params["spread_mult"],
            px_spread=opp.get("px_spread",0))
        if not omega_r["go"]:
            log.info(f"  Skip {sym}: Ωv2={omega_r['omega']:.0f} p_fill={p_fill:.2f} comp={comp['competition_level']}");return
        if p_fill<0.01:
            log.info(f"  Skip {sym}: p_fill too low ({p_fill:.4f})");return
        if not flow_ok:
            log.info(f"  Skip {sym}: adverse flow (composite={flow_analysis['composite']:+.2f} tox={flow_analysis['toxicity']})");return

        # ── [M8] DYNAMIC SIZING ──
        dd_pct=(s.peak-s.account)/s.peak if s.peak>0 else 0
        sz=s.sizer.size(capital=s.account,current_exposure=sum(p.size_usd for p in s.positions),
            p_fill=p_fill,competition_mult=comp["size_multiplier"],omega=omega_r["omega"],
            regime=regime,current_dd_pct=dd_pct)
        own=sz.get("size_usd",0)
        if own<50:
            log.info(f"  Skip {sym}: sizer reject ({sz.get('reason','small')})");return
        lev_size=own*LEV

        # ── QUANTITY CALC ──
        if not v_a_obj or not v_b_obj:return
        px=v_a_obj.prices.get(sym,0) or v_b_obj.prices.get(sym,0)
        if px<=0:return
        raw_qty=lev_size/px
        qty=v_a_obj.round_qty(sym,raw_qty)
        if qty<=0:return

        # ── EXECUTION ──
        # [BUG5 FIX] set leverage before trading
        if ARB_LIVE or ARB_DEMO:
            await v_a_obj.set_leverage(sym,LEV)
            if v_b_obj.name!=v_a_obj.name:await v_b_obj.set_leverage(sym,LEV)
        t0=time.monotonic()
        if opp["type"]=="INTERNAL":
            log.info(f"  OPEN {sym} INTERNAL@{opp['v_a']} ${lev_size:.0f} Ωv2={omega_r['omega']:.0f} Pf={p_fill:.2f}")
            if ARB_LIVE or ARB_DEMO:
                f1=await s._split_exec(opp["v_a"],sym,"SELL",qty)
                if f1<qty*0.5:
                    log.error(f"  INTERNAL perp short underfill {f1:.4f}/{qty:.4f} — ABORT")
                    if f1>0:await s._split_exec(opp["v_a"],sym,"BUY",f1)
                    return
                if isinstance(v_a_obj,Binance):
                    spot_r=await v_a_obj.spot_order(sym,"BUY",v_a_obj.round_qty(sym,f1))
                    spot_fill=float(spot_r.get("executedQty",0)) if isinstance(spot_r,dict) else 0
                    if spot_fill<f1*0.5:
                        log.error(f"  INTERNAL spot buy failed {spot_fill:.4f}/{f1:.4f} — ROLLBACK perp")
                        await s._split_exec(opp["v_a"],sym,"BUY",f1)
                        return
                    qty=min(f1,spot_fill)
            else:log.info(f"    [P] SHORT perp {qty:.4f} + BUY spot {qty:.4f}")
        elif opp["type"]=="PERP_PERP":
            log.info(f"  OPEN {sym} PERP_PERP SHORT@{opp['v_a']} LONG@{opp['v_b']} ${lev_size:.0f} Ωv2={omega_r['omega']:.0f} Pf={p_fill:.2f} {comp['competition_level']}")
            if ARB_LIVE or ARB_DEMO:
                t_leg1=time.monotonic()
                f1=await s._split_exec(opp["v_a"],sym,"SELL",qty)
                t_leg1_done=time.monotonic()
                if f1<qty*0.5:
                    log.error(f"  LEG1 underfill {f1:.4f}/{qty:.4f} — ABORT")
                    s.adversarial.record_fill_failure(opp["v_a"])
                    if f1>0:await s._split_exec(opp["v_a"],sym,"BUY",f1)
                    return
                f2=await s._split_exec(opp["v_b"],sym,"BUY",f1)
                t_leg2_done=time.monotonic()
                s.latency.record_leg_imbalance((t_leg2_done-t_leg1_done)*1000)
                imbalance=abs(f1-f2)/max(f1,1)
                if imbalance>0.2:
                    log.error(f"  HEDGE BREAK: {f1:.4f} vs {f2:.4f} ({imbalance:.0%}) — EMERGENCY ROLLBACK")
                    s.adversarial.record_fill_failure(opp["v_b"])
                    await s._split_exec(opp["v_a"],sym,"BUY",f1)
                    if f2>0:await s._split_exec(opp["v_b"],sym,"SELL",f2)
                    await s._tg(f"🚨 HEDGE BREAK {sym}: {f1:.4f} vs {f2:.4f}. Rolled back.")
                    return
                qty=min(f1,f2)
                # [M5] record fills
                s.fill_model.record_fill(FillRecord(opp["v_a"],sym,"SELL",qty,f1,slippage_bps/2,(t_leg1_done-t_leg1)*1000))
                s.fill_model.record_fill(FillRecord(opp["v_b"],sym,"BUY",qty,f2,slippage_bps/2,(t_leg2_done-t_leg1_done)*1000))
            else:
                log.info(f"    [P] LEG1 SHORT@{opp['v_a']} {qty:.4f} ({SPLIT_N} parts)")
                log.info(f"    [P] LEG2 LONG@{opp['v_b']}  {qty:.4f} ({SPLIT_N} parts)")
        else:return

        s.latency.record(opp["v_a"],"round_trip",(time.monotonic()-t0)*1000)
        px_a=v_a_obj.prices.get(sym,0);px_b=v_b_obj.prices.get(sym,0)
        pos=Position(sym,opp["type"],opp["v_a"],opp["v_b"],qty,own,opp["spread"],opp["edge"],px_a,px_b)
        s.positions.append(pos)
        s.hedge_mon.register(pos.symbol,pos.v_a,pos.v_b,pos.qty)
        tlog.info(f"OPEN {sym:12s} {opp['type']:10s} {opp['edge']} ${lev_size:.0f} Ωv2={omega_r['omega']:.0f} Pf={p_fill:.2f} {comp['competition_level']}")
        await s._tg(f"<b>OPEN {sym}</b>\n{opp['type']} Ωv2={omega_r['omega']:.0f} Pf={p_fill:.2f}\n{comp['competition_level']} {opp['edge']}\n${lev_size:.0f}")

    async def _close(s,pos,reason):
        if ARB_LIVE or ARB_DEMO:
            if pos.type=="INTERNAL":
                await s._split_exec(pos.v_a,pos.symbol,"BUY",pos.qty)
                v=s.venues.get(pos.v_a)
                if isinstance(v,Binance):await v.spot_order(pos.symbol,"SELL",pos.qty)
            elif pos.type=="PERP_PERP":
                await s._split_exec(pos.v_a,pos.symbol,"BUY",pos.qty)
                await s._split_exec(pos.v_b,pos.symbol,"SELL",pos.qty)
        else:log.info(f"  [P] CLOSE {pos.symbol} {pos.type} {reason}")
        ca=s.venues.get(pos.v_a);cb=s.venues.get(pos.v_b)
        cost=(ca.cost if ca else 0.001)+(cb.cost if cb else 0.001)
        cost*=2*pos.qty*(ca.prices.get(pos.symbol,0) or 1)
        # mark-to-market: price movement PnL
        exit_px_a=ca.prices.get(pos.symbol,0) if ca else 0
        exit_px_b=cb.prices.get(pos.symbol,0) if cb else 0
        mtm=pos.mtm_pnl(exit_px_a,exit_px_b)
        pnl=pos.funding_collected+mtm-cost
        s.closed.append({"symbol":pos.symbol,"type":pos.type,"pnl":round(pnl,4),"hours":round(pos.hours_open(),1),"reason":reason})
        s.account+=pnl;s.positions=[p for p in s.positions if p is not pos]
        s.peak=max(s.peak,s.account)

        # [M4] unregister hedge
        s.hedge_mon.unregister(pos.symbol)
        # [M8] feed sizer
        s.sizer.record_trade(pnl)

        if pnl<0:s.consecutive_losses+=1
        else:s.consecutive_losses=0
        if s.consecutive_losses>=KILL_LOSSES:
            s.killed=True;log.warning(f"  KILL SWITCH: {KILL_LOSSES} consecutive losses")
            await s._tg(f"🚨 KILL SWITCH: {KILL_LOSSES} consecutive losses. Halting new entries.")
        if(s.peak-s.account)/s.peak>MAX_DD_PCT:
            s.killed=True;log.warning(f"  KILL SWITCH: drawdown {(s.peak-s.account)/s.peak*100:.1f}% > {MAX_DD_PCT*100:.0f}%")
            await s._tg(f"🚨 KILL SWITCH: max drawdown exceeded")
        tlog.info(f"CLOSE {pos.symbol:12s} F=${pos.funding_collected:+.4f} MTM=${mtm:+.4f} PnL=${pnl:+.4f} {reason}")
        await s._tg(f"<b>CLOSE {pos.symbol}</b>\nPnL=${pnl:+.4f} {reason}")

    async def _collect(s):
        now=time.time()
        for p in s.positions:
            ref=p.last_funding_ts if p.last_funding_ts>0 else p.open_ts.timestamp()
            va=s.venues.get(p.v_a);vb=s.venues.get(p.v_b)
            per_a=per_b=0
            if va:
                interval_a=va.fund_h*3600;bd=ref-(ref%interval_a)+interval_a
                while bd<=now:per_a+=1;bd+=interval_a
            if vb and p.type!="INTERNAL":
                interval_b=vb.fund_h*3600;bd=ref-(ref%interval_b)+interval_b
                while bd<=now:per_b+=1;bd+=interval_b
            if per_a<1 and per_b<1:continue
            fr_a=va.funding.get(p.symbol,0) if va else 0
            fr_b=vb.funding.get(p.symbol,0) if vb else 0
            mk_a=va.prices.get(p.symbol,0) if va else 0
            mk_b=vb.prices.get(p.symbol,0) if vb else 0
            mk=(mk_a+mk_b)/2 if mk_a>0 and mk_b>0 else mk_a or mk_b or 1
            if p.type=="INTERNAL":pay=fr_a*p.qty*mk*per_a
            else:pay=fr_a*p.qty*mk*per_a+(-fr_b*p.qty*mk*per_b)
            p.funding_collected+=pay;p.funding_payments+=max(per_a,per_b);p.last_funding_ts=now

    async def _cycle(s):
        s._sc+=1;await s._collect()

        # ══════ v5.0: MODULE CYCLE ══════
        # [M3] update regime prices from all venues
        for v in s.venues.values():
            for sym,px in v.prices.items():
                if px>0:s.regime.update_price(sym,px)
        s.regime.classify_global([p.symbol for p in s.positions])

        # [M6] update adversarial spread tracking for open positions
        for p in s.positions:
            va=s.venues.get(p.v_a);vb=s.venues.get(p.v_b)
            if va and vb:
                fr_a=va.funding.get(p.symbol,0);fr_b=vb.funding.get(p.symbol,0)
                cur_sp=fr_a-fr_b if p.type!="INTERNAL" else fr_a
                s.adversarial.update_spread(p.symbol,p.v_a,p.v_b,cur_sp)

        # [M4] hedge monitor — update prices + check
        for p in s.positions:
            va=s.venues.get(p.v_a);vb=s.venues.get(p.v_b)
            if va and vb:
                s.hedge_mon.update_prices(p.symbol,va.prices.get(p.symbol,0),vb.prices.get(p.symbol,0))
        actions=await s.hedge_mon.check_all(s.venues,exec_fn=s._split_exec,close_fn=s._close)
        for act in actions:
            if act["type"] in("EMERGENCY_CLOSE","FORCE_CLOSE"):
                for p in list(s.positions):
                    if p.symbol==act["symbol"]:
                        await s._close(p,act["reason"]);break
        # ══════ end module cycle ══════

        # [BUG4 FIX] periodic balance reconciliation
        if (ARB_LIVE or ARB_DEMO) and s._sc%10==0:
            for v in s.venues.values():
                if hasattr(v,"get_balance"):
                    try:
                        real_bal=await v.get_balance()
                        if real_bal>0 and abs(real_bal-s.account)/max(s.account,1)>0.20:
                            log.warning(f"  ⚠️ BALANCE DRIFT {v.name}: real=${real_bal:.2f} vs internal=${s.account:.2f}")
                            await s._tg(f"⚠️ Balance drift {v.name}: ${real_bal:.2f} vs ${s.account:.2f}")
                    except Exception as e:log.warning("balance check failed: %s", e)

        for p in list(s.positions):
            h=p.hours_open()
            va=s.venues.get(p.v_a);vb=s.venues.get(p.v_b)
            fr_a=va.funding.get(p.symbol,0) if va else 0
            fr_b=vb.funding.get(p.symbol,0) if vb else 0
            cur_sp=fr_a-fr_b if p.type!="INTERNAL" else fr_a
            # [M3] regime-adjusted max hold
            max_h=MAX_HOLD_H*s.regime.get_params(p.symbol).get("max_hold_mult",1.0)
            if h>=EXIT_H and abs(cur_sp)<abs(p.spread)*EXIT_DECAY:await s._close(p,"decay");continue
            if h>=EXIT_H and cur_sp<0 and p.spread>0:await s._close(p,"flip");continue
            if h>max_h:await s._close(p,"max_hold");continue

        if s.killed:log.info(f"  Kill switch active — no new entries");return
        if len(s.positions)>=MAX_POS:return
        opps,_=await scan_all(list(s.venues.values()))
        open_syms={p.symbol for p in s.positions}
        for o in opps:
            if o["sym"] in open_syms:continue
            if o["omega"]<20:continue
            if o.get("vol",0)<MIN_VOL:continue
            if len(s.positions)>=MAX_POS:break
            await s._open(o)
        log.info(f"  Cycle #{s._sc}: opps={len(opps)} open={len(s.positions)}/{MAX_POS} regime={s.regime._global} kelly={s.sizer._kelly():.3f}")
        s._save_state()

    async def run(s):
        s.running=True
        if s.ws:await s.ws.start();await asyncio.sleep(2)
        mode="LIVE" if ARB_LIVE else "DEMO" if ARB_DEMO else "PAPER"
        await s._tg(f"<b>AURUM v5.0</b>\n{mode} | {len(s.venues)} venues | {RUN_ID}")
        W=70
        print(f"\n  {'═'*W}\n  AURUM Finance | Arbitrage Engine v5.0\n  Mode: {mode} | WS: {'ON' if s.ws and s.ws.running else 'OFF'}\n  {'═'*W}")
        print(f"  Capital: ${ACCT:,.0f} | Lev: {LEV}x | Venues: {', '.join(s.venues.keys())}")
        print(f"  Modules: Depth+Latency+Regime+Hedge | FillProb+Adversarial+ΩV2+Kelly+OrderFlow")
        print(f"  Scan: {SCAN_S}s | Split: {SPLIT_N} parts | Ctrl+C to stop\n  {'═'*W}\n")
        try:
            while s.running:
                try:await s._cycle()
                except Exception as e:log.error(f"Cycle:{e}",exc_info=True)
                if s._sc%STATUS_N==0:
                    tp=sum(t["pnl"] for t in s.closed)
                    print(f"\n  {'═'*80}\n  #{s._sc} | {datetime.now().strftime('%H:%M:%S')} | Open:{len(s.positions)}/{MAX_POS} | PnL:${tp:+.4f} | {s.regime._global}\n  {'─'*80}")
                    for p in s.positions:
                        va=s.venues.get(p.v_a);vb=s.venues.get(p.v_b)
                        mtm=p.mtm_pnl(va.prices.get(p.symbol,0) if va else 0,vb.prices.get(p.symbol,0) if vb else 0)
                        print(f"  {p.symbol:12s} {p.type:10s} {p.v_a}→{p.v_b} F=${p.funding_collected:+.4f} MTM=${mtm:+.4f} {p.hours_open():.0f}h")
                    if not s.positions:print("  (scanning...)")
                    # [M4] hedge status inline
                    for h in s.hedge_mon.status_all():
                        print(f"  {h['status']} hedge {h['symbol']:12s} imb={h['imbalance_pct']:.1f}% pxDiv={h['px_divergence_pct']:.3f}% rh={h['rehedge_count']}")
                    # [M2] latency inline
                    for venue,phases in s.latency.all_summaries().items():
                        rt=phases.get("round_trip",phases.get("fetch",{}))
                        if rt.get("n",0)>0:print(f"  ⏱ {venue}: p50={rt['p50']:.0f}ms p95={rt['p95']:.0f}ms (n={rt['n']})")
                    # [v5] adversarial + flow + sizer
                    print(f"  {s.adversarial.dashboard_str()}")
                    print(f"  {s.flow.dashboard_str([p.symbol for p in s.positions])}")
                    fvs=s.fill_model.venue_stats()
                    if fvs:
                        for v,st in fvs.items():print(f"  📊 {v}: fill={st['fill_rate_mean']:.1%} slip_p95={st['slippage_p95_bps']:.1f}bps (n={st['n']})")
                    print(f"  Kelly f*={s.sizer._kelly():.3f} | DD={(s.peak-s.account)/s.peak*100:.1f}%")
                    print(f"  {'═'*80}")
                try:await asyncio.sleep(SCAN_S)
                except asyncio.CancelledError:break
        except KeyboardInterrupt:print("\n  Shutting down...")
        finally:
            s.running=False
            if s.ws and s.ws._task:s.ws._task.cancel()
            with open(DIR/"reports"/f"session_{_D}.json","w") as f:
                json.dump({"trades":s.closed,"pnl":sum(t["pnl"] for t in s.closed),
                           "latency":s.latency.all_summaries(),
                           "regime_final":s.regime._global,
                           "fill_stats":s.fill_model.venue_stats(),
                           "kelly_f":s.sizer._kelly(),
                           "wins":len(s.sizer._wins),"losses":len(s.sizer._losses)},f,indent=2,default=str)
            await s._tg(f"Stopped. {len(s.closed)} trades PnL:${sum(t['pnl'] for t in s.closed):+.4f}")
            log.info("Engine stopped.")

def _menu():
    W=70
    print(f"\n  {'═'*W}\n  AURUM Finance | Arbitrage Engine v5.0\n  13 venues | Ω scoring | split execution\n  +Depth +Latency +Regime +Hedge +FillProb +Adversarial +ΩV2 +Kelly +Flow\n  {'═'*W}")
    print(f"  [1] DASHBOARD — scan all venues, show opportunities")
    print(f"  [2] PAPER  [3] DEMO  [4] LIVE  [0] Exit\n  {'═'*W}")
    return{"1":"scan","2":"paper","3":"demo","4":"live","0":"exit"}.get(safe_input("\n  > ").strip(),"exit")

if __name__=="__main__":
    _run_mode=ARB_MODE
    if _ARGS.mode is None:
        _run_mode=_menu()
        if _run_mode=="exit":sys.exit(0)
    else:
        log.info(f"Mode fixed via CLI: {ARB_MODE}")
    if _run_mode=="scan":
        venues=build_venues()
        async def _s():
            o,a=await scan_all(venues);print_dashboard(o,a)
        asyncio.run(_s())
    elif _run_mode in("paper","demo","testnet","live"):
        if _run_mode=="live":
            if safe_input("  LIVE. Type YES > ").strip()!="YES":sys.exit(0)
        venues=build_venues()
        asyncio.run(Engine(venues).run())