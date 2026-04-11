"""
AURUM Finance — RENAISSANCE: Harmonic Pattern Engine
=====================================================
# RENAISSANCE (formerly HERMES) — Pattern recognition + Bayesian scoring
Bayesian harmonic pattern detection (Gartley, Bat, Butterfly, Crab)
with Shannon entropy, Hurst exponent, and fractal alignment.
Extracted from engines/multistrategy.py.
"""
import math
import numpy as np
from collections import defaultdict

from config.params import *
from core.indicators import indicators, swing_structure
from core.signals import label_trade
from core.portfolio import portfolio_allows, check_aggregate_notional, position_size
from core.htf import prepare_htf, merge_all_htf_to_ltf, HTF_INTERVAL

# ── RENAISSANCE CONFIG (formerly HERMES) ─────────────────────────────────────────────
H_TOL             = 0.10
H_PIVOT_N         = 4
H_FORWARD         = 48
H_STOP_BUFFER     = 0.01
H_TARGET_FIB      = 0.618
H_MIN_SCORE       = 0.05
H_ENTROPY_WINDOW  = 50
H_ENTROPY_BINS    = 10
H_HURST_WINDOW    = 80
H_MIN_RR          = 1.0

H_RULES = {
    "Gartley":   {"ab":(0.618,0.618),"bc":(0.382,0.886),"cd":(1.272,1.618),"ad":(0.786,0.786)},
    "Bat":       {"ab":(0.382,0.500),"bc":(0.382,0.886),"cd":(1.618,2.618),"ad":(0.886,0.886)},
    "Butterfly": {"ab":(0.786,0.786),"bc":(0.382,0.886),"cd":(1.618,2.618),"ad":(1.272,1.272)},
    "Crab":      {"ab":(0.382,0.618),"bc":(0.382,0.886),"cd":(2.618,3.618),"ad":(1.618,1.618)},
}
H_BAYESIAN_PRIOR = {"Gartley":0.65,"Bat":0.55,"Butterfly":0.50,"Crab":0.50}
H_REGIME_RISK    = {"TREND":1.0,"RANGE":0.5,"VOLATILE":0.25}


def _h_pivots(df):
    n=H_PIVOT_N; h=df["high"].values; l=df["low"].values
    ph={}; pl={}
    for i in range(n, len(df)):
        if h[i]==max(h[max(0,i-n):i+1]): ph[i]=h[i]
        if l[i]==min(l[max(0,i-n):i+1]): pl[i]=l[i]
    return ph, pl


def _h_alt_pivots(ph, pl):
    pts=([{"i":i,"p":p,"type":"H"} for i,p in ph.items()]+
         [{"i":i,"p":p,"type":"L"} for i,p in pl.items()])
    pts.sort(key=lambda x: x["i"])
    alt=[]
    for pt in pts:
        if not alt or alt[-1]["type"]!=pt["type"]: alt.append(pt)
        elif pt["type"]=="H" and pt["p"]>alt[-1]["p"]: alt[-1]=pt
        elif pt["type"]=="L" and pt["p"]<alt[-1]["p"]: alt[-1]=pt
    return alt


def _h_check(X, A, B, C, D):
    XA=abs(A["p"]-X["p"]); AB=abs(B["p"]-A["p"])
    BC=abs(C["p"]-B["p"]); CD=abs(D["p"]-C["p"]); AD=abs(D["p"]-A["p"])
    if XA==0 or AB==0 or BC==0: return None,{}
    r={"AB/XA":round(AB/XA,4),"BC/AB":round(BC/AB,4),
       "CD/BC":round(CD/BC,4),"AD/XA":round(AD/XA,4),"XA":round(XA,4),"AD":round(AD,4)}
    def ok(v,lo,hi): return lo*(1-H_TOL)<=v<=hi*(1+H_TOL)
    for name,rule in H_RULES.items():
        if (ok(r["AB/XA"],rule["ab"][0],rule["ab"][1]) and
            ok(r["BC/AB"],rule["bc"][0],rule["bc"][1]) and
            ok(r["CD/BC"],rule["cd"][0],rule["cd"][1]) and
            ok(r["AD/XA"],rule["ad"][0],rule["ad"][1])):
            return name, r
    return None, r


def _h_levels(X, D, direction, XA, AD):
    d=D["p"]; x=X["p"]; buf=XA*H_STOP_BUFFER
    if direction=="BULLISH":
        stop=x-buf; target=d+H_TARGET_FIB*AD
        if target<=d or stop>=d: return None,None
    else:
        stop=x+buf; target=d-H_TARGET_FIB*AD
        if target>=d or stop<=d: return None,None
    return round(target,8), round(stop,4)


def _h_entropy(df, idx):
    if idx<H_ENTROPY_WINDOW: return "STRUCTURED"
    prices=df["close"].iloc[idx-H_ENTROPY_WINDOW:idx].values
    rets=[prices[i]/prices[i-1]-1 for i in range(1,len(prices)) if prices[i-1]>0]
    if len(rets)<H_ENTROPY_BINS: return "STRUCTURED"
    mn,mx=min(rets),max(rets)
    if mx==mn: return "STRUCTURED"
    bw=(mx-mn)/H_ENTROPY_BINS; counts=[0]*H_ENTROPY_BINS
    for r in rets: counts[min(int((r-mn)/bw),H_ENTROPY_BINS-1)]+=1
    n=len(rets); probs=[c/n for c in counts if c>0]
    H=-sum(p*math.log(p) for p in probs)
    norm=H/math.log(H_ENTROPY_BINS)
    if norm>0.92: return "RANDOM"
    if norm<0.50: return "STRUCTURED"
    return "TRANSITION"


def _h_hurst(df, idx):
    if idx<H_HURST_WINDOW+1: return "UNKNOWN"
    prices=list(df["close"].iloc[idx-H_HURST_WINDOW:idx].values)
    n=len(prices)
    lags=[max(4,n//k) for k in range(2,min(8,n//4))]; lags=sorted(set(lags))
    rs_vals=[]
    for lag in lags:
        rs_sub=[]
        for start in range(0,n-lag,lag):
            sub=prices[start:start+lag]; m=sum(sub)/lag
            dev=[s-m for s in sub]; cum=[sum(dev[:i+1]) for i in range(lag)]
            R=max(cum)-min(cum); S=(sum((s-m)**2 for s in sub)/lag)**0.5
            if S>0: rs_sub.append(R/S)
        if rs_sub: rs_vals.append(sum(rs_sub)/len(rs_sub))
    if len(rs_vals)<2: return "UNKNOWN"
    log_lags=[math.log(l) for l in lags[:len(rs_vals)]]
    log_rs=[math.log(r) for r in rs_vals if r>0]
    n2=min(len(log_lags),len(log_rs))
    if n2<2: return "UNKNOWN"
    lx=log_lags[:n2]; ly=log_rs[:n2]
    mx=sum(lx)/n2; my=sum(ly)/n2
    num=sum((lx[i]-mx)*(ly[i]-my) for i in range(n2))
    den=sum((lx[i]-mx)**2 for i in range(n2))
    if den==0: return "UNKNOWN"
    H=num/den
    if H<0.45: return "MEAN_REVERTING"
    if H>0.55: return "TRENDING"
    return "RANDOM_WALK"


class _BayesWR:
    def __init__(self):
        self.d={pat:{"a":p*10,"b":(1-p)*10} for pat,p in H_BAYESIAN_PRIOR.items()}
    def update(self, pat, result, rr=1.0):
        if pat not in self.d: self.d[pat]={"a":5.0,"b":5.0}
        w=min(rr,3.0)
        if result=="WIN": self.d[pat]["a"]+=w
        else: self.d[pat]["b"]+=w
    def p_win(self, pat):
        d=self.d.get(pat,{"a":5.0,"b":5.0})
        return d["a"]/(d["a"]+d["b"])
    def score(self, rr, pat, regime):
        pw=self.p_win(pat); rw=H_REGIME_RISK.get(regime,1.0)
        edge=pw*rr-(1-pw)
        return round(max(0,edge)*rw,4)


def scan_hermes(df, symbol, macro_bias_series, corr, htf_stack_dfs=None,
                capital_weight=0.35, log=None):
    """
    Scan a single symbol for harmonic patterns (Gartley, Bat, Butterfly, Crab).

    Parameters
    ----------
    capital_weight : float
        Fraction of ACCOUNT_SIZE allocated to Hermes.
    log : logging.Logger or None
        Logger to use for output.
    """
    import logging as _logging
    if log is None:
        log = _logging.getLogger("RENAISSANCE")  # RENAISSANCE (formerly HERMES)

    df=indicators(df); df=swing_structure(df)
    if MTF_ENABLED and htf_stack_dfs: df=merge_all_htf_to_ltf(df,htf_stack_dfs)
    close_a=df["close"].values; high_a=df["high"].values; low_a=df["low"].values
    open_a=df["open"].values; atr_a=df["atr"].values
    vol_r_a=df["vol_regime"].values; trans_a=df["regime_transition"].values
    slope200_a=df["slope200"].values; slope21_a=df["slope21"].values
    _htfm=df[f"htf{len(HTF_STACK)}_macro"].values if MTF_ENABLED and f"htf{len(HTF_STACK)}_macro" in df.columns else None
    ph, pl=_h_pivots(df); alt=_h_alt_pivots(ph, pl)
    bayes=_BayesWR(); trades=[]; vetos=defaultdict(int)
    account=ACCOUNT_SIZE*capital_weight
    min_idx=max(200,W_NORM,H_PIVOT_N*3,H_HURST_WINDOW)+5
    # (exit_idx, symbol, size, entry) — size/entry needed for L6 cap
    open_pos: list[tuple[int, str, float, float]] = []
    peak_equity=account; consecutive_losses=0
    cooldown_until=-1; sym_cooldown_until={}
    patterns_at=defaultdict(list)
    for k in range(len(alt)-4):
        X,A,B,C,D=alt[k],alt[k+1],alt[k+2],alt[k+3],alt[k+4]
        if D["i"]<min_idx or D["i"]>=len(df)-H_FORWARD-2: continue
        pat,ratios=_h_check(X,A,B,C,D)
        if not pat: continue
        direction="BEARISH" if D["type"]=="H" else "BULLISH"
        target,stop=_h_levels(X,D,direction,ratios["XA"],ratios["AD"])
        if target is None: continue
        rr=abs(target-D["p"])/abs(stop-D["p"]) if abs(stop-D["p"])>0 else 0
        if rr<H_MIN_RR: continue
        patterns_at[D["i"]].append({"pattern":pat,"direction":direction,
            "X":X,"A":A,"D":D,"target":target,"stop":stop,"rr":round(rr,2),"ratios":ratios})
    for idx in range(min_idx, len(df)-H_FORWARD-2):
        if idx not in patterns_at: continue
        open_pos=[(ei,s,sz,en) for ei,s,sz,en in open_pos if ei>idx]
        active_syms=[s for _,s,_,_ in open_pos]
        macro_b="CHOP"
        if MTF_ENABLED and _htfm is not None: macro_b=str(_htfm[idx])
        elif macro_bias_series is not None: macro_b=macro_bias_series.iloc[min(idx,len(macro_bias_series)-1)]
        peak_equity=max(peak_equity,account)
        current_dd=(peak_equity-account)/peak_equity if peak_equity>0 else 0.0
        dd_scale=1.0
        for th in sorted(DD_RISK_SCALE.keys(),reverse=True):
            if current_dd>=th: dd_scale=DD_RISK_SCALE[th]; break
        if dd_scale==0.0: vetos["dd_pause"]+=1; continue
        in_transition=bool(trans_a[idx]); trans_mult=REGIME_TRANS_SIZE_MULT if in_transition else 1.0
        if idx<=cooldown_until: vetos["streak_cooldown"]+=1; continue
        if idx<=sym_cooldown_until.get(symbol,-1): vetos["sym_cooldown"]+=1; continue
        vol_r=vol_r_a[idx]
        if VOL_RISK_SCALE.get(vol_r,1.0)==0.0: vetos["vol_extreme"]+=1; continue
        ok,motivo_p,corr_size_mult=portfolio_allows(symbol,active_syms,corr)
        if not ok: vetos[motivo_p]+=1; continue
        for sig in patterns_at[idx]:
            direction=sig["direction"]; pat=sig["pattern"]
            target=sig["target"]; stop=sig["stop"]; rr=sig["rr"]
            if macro_b=="BEAR" and direction=="BULLISH": vetos["macro_bear_veto_long"]+=1; continue
            if macro_b=="BULL" and direction=="BEARISH": vetos["macro_bull_veto_short"]+=1; continue
            fractal_score=1.0
            if MTF_ENABLED and "htf1_struct" in df.columns:
                n_htf=len(HTF_STACK); aligned=0
                struct_map={"BULLISH":"UP","BEARISH":"DOWN"}
                tgt_struct=struct_map.get(direction,"UP")
                for i in range(1,n_htf+1):
                    htf_s=str(df[f"htf{i}_struct"].iloc[idx])
                    htf_str=float(df[f"htf{i}_strength"].iloc[idx] or 0)
                    if htf_str>=0.35 and htf_s==tgt_struct: aligned+=1
                fractal_score=round(aligned/n_htf,2) if n_htf>0 else 1.0
                if aligned==0: vetos["hermes_fractal_misalign"]+=1; continue
            ent=_h_entropy(df,idx)
            if ent=="RANDOM": vetos["hermes_entropy_random"]+=1; continue
            hurst=_h_hurst(df,idx)
            ent_w=1.2 if ent=="STRUCTURED" else 0.8
            hurst_w=1.15 if hurst=="MEAN_REVERTING" else (0.85 if hurst=="TRENDING" else 1.0)
            atr_now=float(atr_a[idx]) if not np.isnan(atr_a[idx]) else 0
            past_atr=[float(atr_a[j]) for j in range(max(0,idx-14),idx) if not np.isnan(atr_a[j])]
            atr_avg=sum(past_atr)/len(past_atr) if past_atr else atr_now
            atr_std=(sum((a-atr_avg)**2 for a in past_atr)/len(past_atr))**0.5 if len(past_atr)>1 else 0
            atr_z=(atr_now-atr_avg)/atr_std if atr_std>0 else 0
            s21=float(slope21_a[idx])
            if atr_z>2.0: h_regime="VOLATILE"
            elif abs(s21)>0.3: h_regime="TREND"
            else: h_regime="RANGE"
            score_raw=bayes.score(rr,pat,h_regime)
            score=round(score_raw*ent_w*hurst_w,4)
            if score<H_MIN_SCORE: vetos["hermes_score_baixo"]+=1; continue
            if idx+1>=len(df): continue
            slip=SLIPPAGE+SPREAD
            raw=float(open_a[idx+1])
            entry=raw*(1+slip) if direction=="BULLISH" else raw*(1-slip)
            entry=round(entry,8)
            if direction=="BULLISH" and (stop>=entry or target<=entry): vetos["hermes_niveis"]+=1; continue
            if direction=="BEARISH" and (stop<=entry or target>=entry): vetos["hermes_niveis"]+=1; continue
            result,duration,exit_p=label_trade(df,idx+1,direction,entry,stop,target)
            if result=="OPEN": continue
            size=position_size(account,entry,stop,max(score,SCORE_THRESHOLD),macro_b,direction,vol_r,dd_scale,False,peak_equity=peak_equity)
            size=round(size*corr_size_mult*trans_mult*fractal_score,4)
            # [L6] Aggregate notional cap across concurrently open positions.
            if size > 0:
                ok_agg, motivo_agg = check_aggregate_notional(
                    size * entry, open_pos, account, LEVERAGE)
                if not ok_agg:
                    vetos[motivo_agg] += 1
                    continue
            ep=float(exit_p)
            slip_exit=SLIPPAGE+SPREAD
            if direction=="BULLISH":
                entry_cost=entry*(1+COMMISSION)
                ep_net=ep*(1-COMMISSION-slip_exit)
                pnl=size*(ep_net-entry_cost)-(size*entry*FUNDING_PER_8H*duration/32)
            else:
                entry_cost=entry*(1-COMMISSION)
                ep_net=ep*(1+COMMISSION+slip_exit)
                pnl=size*(entry_cost-ep_net)+(size*entry*FUNDING_PER_8H*duration/32)
            pnl=round(pnl*LEVERAGE, 2)
            # Apply real PnL. The previous `max(account+pnl, account*0.5)`
            # silently clamped per-trade losses at 50% of pre-trade account,
            # inflating sharpe / maxDD / final equity. Mirror of the fix
            # already applied in mercurio/newton/thoth/backtest.
            account=account+pnl
            bayes.update(pat,result,rr)
            if result=="LOSS":
                consecutive_losses+=1
                for n_l in sorted(STREAK_COOLDOWN.keys(),reverse=True):
                    if consecutive_losses>=n_l: cooldown_until=idx+STREAK_COOLDOWN[n_l]; break
                sym_cooldown_until[symbol]=idx+SYM_LOSS_COOLDOWN
            else: consecutive_losses=0
            open_pos.append((idx+1+duration,symbol,size,entry))
            ts=df["time"].iloc[idx].strftime("%d/%m %Hh")
            trades.append({
                "symbol":symbol,"time":ts,"timestamp":df["time"].iloc[idx],
                "strategy":"RENAISSANCE","pattern":pat,"idx":idx,"entry_idx":idx+1,
                "direction":direction,"macro_bias":macro_b,"vol_regime":vol_r,
                "h_regime":h_regime,"entropy":ent,"hurst":hurst,
                "entry":entry,"stop":stop,"target":target,"exit_p":round(ep,6),
                "rr":rr,"duration":duration,"result":result,"pnl":pnl,
                "size":round(size,4),
                "score":score,"fractal_align":fractal_score,
                "dd_scale":round(dd_scale,2),"corr_mult":round(corr_size_mult,2),
                "in_transition":in_transition,"trans_mult":round(trans_mult,2),
                "ent_w":round(ent_w,2),"hurst_w":round(hurst_w,2),
                "chop_trade":False,"trade_type":"RENAISSANCE",
                "struct":"DOWN" if direction=="BEARISH" else "UP",
                "struct_str":0.5,"cascade_n":0,"taker_ma":0.5,"rsi":50.0,
                "dist_ema21":0.5,"omega_struct":0.0,"omega_flow":0.0,
                "omega_cascade":0.0,"omega_momentum":score,"omega_pullback":score,"bb_mid":0.0,
            })
    closed=[t for t in trades if t["result"] in ("WIN","LOSS")]
    w=sum(1 for t in closed if t["result"]=="WIN")
    log.info(f"  RENAISSANCE {symbol}: {len(trades)} trades  W={w}  L={len(closed)-w}  PnL=${sum(t['pnl'] for t in closed):+,.0f}")
    return trades, dict(vetos)
