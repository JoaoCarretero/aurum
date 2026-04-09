import sys, math, json, random, logging
import numpy as np
import pandas as pd
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).parent))

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.params import *
from config.params import _tf_params, _TF_MINUTES

from core import (
    fetch_all, validate, indicators, swing_structure, omega,
    detect_macro, build_corr_matrix, portfolio_allows,
    calc_levels, label_trade, position_size,
    prepare_htf, merge_all_htf_to_ltf,
)
from analysis.stats import equity_stats, calc_ratios
from analysis.montecarlo import monte_carlo
from analysis.walkforward import walk_forward, walk_forward_by_regime
from analysis.benchmark import bear_market_analysis, year_by_year_analysis
from analysis.plots import plot_montecarlo, plot_dashboard
from engines.backtest import scan_symbol as azoth_scan, RUN_DIR, RUN_ID, log

# ── FORÇAR GLOBALS PARA O TF CORRECTO ─────────────────────────
import config.params as _params
_tf_correct = _tf_params(ENTRY_TF)
_params.SLOPE_N      = _tf_correct["slope_n"]
_params.PIVOT_N      = _tf_correct["pivot_n"]
_params.MIN_STOP_PCT = _tf_correct["min_stop_pct"]
_params.MAX_HOLD     = _tf_correct["max_hold"]
_params.CHOP_S21     = _tf_correct["chop_s21"]
_params.CHOP_S200    = _tf_correct["chop_s200"]
SLOPE_N = _params.SLOPE_N
PIVOT_N = _params.PIVOT_N

# ── MULTISTRATEGY DIRS ────────────────────────────────────────
from pathlib import Path as _Path
MS_RUN_DIR = _Path(f"data/multistrategy/{RUN_ID}")
(MS_RUN_DIR / "reports").mkdir(parents=True, exist_ok=True)
(MS_RUN_DIR / "logs").mkdir(parents=True, exist_ok=True)
(MS_RUN_DIR / "charts").mkdir(parents=True, exist_ok=True)

# log file exclusivo do multistrategy
_ms_fh = logging.FileHandler(MS_RUN_DIR / "logs" / "multistrategy.log", encoding="utf-8")
_ms_fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s"))
log.addHandler(_ms_fh)

# ── MULTISTRATEGY CONFIG ──────────────────────────────────────
MAX_OPEN_POSITIONS_MS = 5
AZOTH_CAPITAL_WEIGHT  = 0.65
HERMES_CAPITAL_WEIGHT = 0.35
CONFIRM_WINDOW        = 6
CONFIRM_SIZE_MULT     = 1.25
CONFLICT_ACTION       = "skip"

# ── ENSEMBLE WEIGHTING ────────────────────────────────────────
ENSEMBLE_WINDOW    = 30    # trades lookback para scoring rolling
ENSEMBLE_MIN_W     = 0.20  # peso mínimo por estratégia (nunca zera)
ENSEMBLE_MAX_W     = 0.80  # peso máximo por estratégia
ENSEMBLE_STAB_WIN  = 60    # janela longa para penalidade de instabilidade
KILL_SWITCH_SORTINO= -0.5  # Sortino abaixo disto → estratégia pausada (peso=MIN_W)
KILL_SWITCH_WINDOW = 20    # trades recentes para avaliação do kill-switch
CONFIDENCE_N_MIN   = 50    # trades para confiança plena: score × sqrt(n/50)
REGIME_LAG         = 5     # lag artificial: usa regime de 5 trades atrás → quebra feedback loop

# Regime-aware: amplifica pesos baseado no macro actual
# TREND (BULL/BEAR) → AZOTH lidera | RANGE (CHOP) → HERMES lidera
REGIME_BOOST = {
    "BULL": {"AZOTH": 1.25, "HERMES": 0.75},
    "BEAR": {"AZOTH": 1.20, "HERMES": 0.80},
    "CHOP": {"AZOTH": 0.75, "HERMES": 1.25},
}
REGIME_BOOST_WINDOW = 20   # trades para detectar regime actual (probabilístico)
R_CAP_MAX    =  5.0        # R-multiple máximo (evita outlier distorcer score)
R_CAP_MIN    = -3.0        # R-multiple mínimo
DECAY_WINDOW = 20          # trades por sub-janela para detecção de decay
DECAY_PENALTY= 0.80        # score × este factor se decay detectado

# ── STRESS TEST ───────────────────────────────────────────────
STRESS_SIMS      = 500   # simulações por cenário
STRESS_CRISIS_N  = 3     # número de janelas de crise injectadas
STRESS_CRISIS_W  = 20    # duração de cada crise (trades)
STRESS_CRISIS_MUL= 0.30  # PnL durante crise × 0.30
STRESS_SLIP_MIN  = 0.001 # slippage adicional mínimo por trade
STRESS_SLIP_MAX  = 0.004 # slippage adicional máximo por trade
STRESS_MISS_RATE = 0.15  # % trades que não executam (latência)

# ── HERMES CONFIG ─────────────────────────────────────────────
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

SEP = "─"*80

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

def scan_hermes(df, symbol, macro_bias_series, corr, htf_stack_dfs=None):
    df=indicators(df); df=swing_structure(df)
    if MTF_ENABLED and htf_stack_dfs: df=merge_all_htf_to_ltf(df,htf_stack_dfs)
    close_a=df["close"].values; high_a=df["high"].values; low_a=df["low"].values
    open_a=df["open"].values; atr_a=df["atr"].values
    vol_r_a=df["vol_regime"].values; trans_a=df["regime_transition"].values
    slope200_a=df["slope200"].values; slope21_a=df["slope21"].values
    _htfm=df[f"htf{len(HTF_STACK)}_macro"].values if MTF_ENABLED and f"htf{len(HTF_STACK)}_macro" in df.columns else None
    ph, pl=_h_pivots(df); alt=_h_alt_pivots(ph, pl)
    bayes=_BayesWR(); trades=[]; vetos=defaultdict(int)
    account=ACCOUNT_SIZE*HERMES_CAPITAL_WEIGHT
    min_idx=max(200,W_NORM,H_PIVOT_N*3,H_HURST_WINDOW)+5
    open_pos=[]; peak_equity=account; consecutive_losses=0
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
        open_pos=[(ei,s) for ei,s in open_pos if ei>idx]
        active_syms=[s for _,s in open_pos]
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
            account=max(account+pnl,account*0.5)
            bayes.update(pat,result,rr)
            if result=="LOSS":
                consecutive_losses+=1
                for n_l in sorted(STREAK_COOLDOWN.keys(),reverse=True):
                    if consecutive_losses>=n_l: cooldown_until=idx+STREAK_COOLDOWN[n_l]; break
                sym_cooldown_until[symbol]=idx+SYM_LOSS_COOLDOWN
            else: consecutive_losses=0
            open_pos.append((idx+1+duration,symbol))
            ts=df["time"].iloc[idx].strftime("%d/%m %Hh")
            trades.append({
                "symbol":symbol,"time":ts,"timestamp":df["time"].iloc[idx],
                "strategy":"HERMES","pattern":pat,"idx":idx,"entry_idx":idx+1,
                "direction":direction,"macro_bias":macro_b,"vol_regime":vol_r,
                "h_regime":h_regime,"entropy":ent,"hurst":hurst,
                "entry":entry,"stop":stop,"target":target,"exit_p":round(ep,6),
                "rr":rr,"duration":duration,"result":result,"pnl":pnl,
                "size":round(size,4),
                "score":score,"fractal_align":fractal_score,
                "dd_scale":round(dd_scale,2),"corr_mult":round(corr_size_mult,2),
                "in_transition":in_transition,"trans_mult":round(trans_mult,2),
                "ent_w":round(ent_w,2),"hurst_w":round(hurst_w,2),
                "chop_trade":False,"trade_type":"HERMES",
                "struct":"DOWN" if direction=="BEARISH" else "UP",
                "struct_str":0.5,"cascade_n":0,"taker_ma":0.5,"rsi":50.0,
                "dist_ema21":0.5,"omega_struct":0.0,"omega_flow":0.0,
                "omega_cascade":0.0,"omega_momentum":score,"omega_pullback":score,"bb_mid":0.0,
            })
    closed=[t for t in trades if t["result"] in ("WIN","LOSS")]
    w=sum(1 for t in closed if t["result"]=="WIN")
    log.info(f"  HERMES {symbol}: {len(trades)} trades  W={w}  L={len(closed)-w}  PnL=${sum(t['pnl'] for t in closed):+,.0f}")
    return trades, dict(vetos)

# ── ENSEMBLE WEIGHTING ────────────────────────────────────────
def _std(lst):
    if len(lst) < 2: return 0.0
    m = sum(lst)/len(lst)
    return (sum((x-m)**2 for x in lst)/(len(lst)-1))**0.5

def _r_multiple(t):
    """
    R-multiple = pnl / risco_em_$ do trade.
    Remove viés de tamanho de posição e leverage — mede qualidade pura do edge.
    Clamped a [R_CAP_MIN, R_CAP_MAX] para evitar que outliers dominem o score.
    """
    risk_price = abs(t.get("entry", 0) - t.get("stop", 0))
    size       = t.get("size", 0)
    risk_usd   = risk_price * size
    if risk_usd < 1e-8: return 0.0
    r = t["pnl"] / risk_usd
    return max(R_CAP_MIN, min(R_CAP_MAX, r))   # cap: evita +20R distorcer Sortino

def _adaptive_window(r_hist):
    """
    Janela adaptativa com transição suave (não binária).
    Vol recente alta → window menor (reactivo). Vol baixa → window maior (estável).
    A suavização usa EMA implícita via ratio contínuo clamped — evita oscilações.
    """
    n = len(r_hist)
    if n < 10: return ENSEMBLE_WINDOW
    # usa janela de 20 para std_recent (mais estável que 10)
    std_recent   = _std(r_hist[-20:]) if n >= 20 else _std(r_hist)
    std_longterm = _std(r_hist)
    if std_longterm < 1e-8: return ENSEMBLE_WINDOW
    # ratio contínuo clamped [0.5, 2.0] → transição suave sem saltos
    vol_ratio = max(0.5, min(std_recent / std_longterm, 2.0))
    w = ENSEMBLE_WINDOW / vol_ratio  # alta vol → window menor
    return max(KILL_SWITCH_WINDOW, min(ENSEMBLE_STAB_WIN, int(w)))

def _regime_confidence_boost(recent_trades):
    """
    Regime-aware boost PROBABILÍSTICO em vez de binário.
    Usa proporção de BULL/BEAR/CHOP nos últimos REGIME_BOOST_WINDOW trades
    como pesos — evita saltos bruscos quando o regime está a mudar.

    Ex: BULL=60%, BEAR=30%, CHOP=10%
        az_boost = 0.6×1.25 + 0.3×1.20 + 0.1×0.75 = 1.185
        he_boost = 0.6×0.75 + 0.3×0.80 + 0.1×1.25 = 0.695
    """
    biases = [t.get("macro_bias","CHOP") for t in recent_trades[-REGIME_BOOST_WINDOW:]
              if t.get("macro_bias")]
    if not biases: return {"AZOTH": 1.0, "HERMES": 1.0}, "CHOP"

    from collections import Counter
    counts = Counter(biases); total = len(biases)
    p = {r: counts.get(r, 0)/total for r in ("BULL","BEAR","CHOP")}
    dominant = max(p, key=p.get)

    az_b = sum(p[r] * REGIME_BOOST[r]["AZOTH"] for r in ("BULL","BEAR","CHOP"))
    he_b = sum(p[r] * REGIME_BOOST[r]["HERMES"] for r in ("BULL","BEAR","CHOP"))
    return {"AZOTH": round(az_b,3), "HERMES": round(he_b,3)}, dominant

def _decay_score(r_hist):
    """
    Detecta decay estrutural via declínio do R-multiple médio.
    Usa FORÇA do declínio (slope normalizado), não só monotonicidade.

    decay_strength = (m1 - m3) / |m1|  — queda relativa ao nível original
    Decay fraco (cíclico): m1≈m3 → score baixo → penalidade mínima
    Decay forte (estrutural): m1>>m3 → score alto → penalidade real
    """
    if len(r_hist) < DECAY_WINDOW * 3: return 0.0
    chunks = [r_hist[-DECAY_WINDOW*3:-DECAY_WINDOW*2],
              r_hist[-DECAY_WINDOW*2:-DECAY_WINDOW],
              r_hist[-DECAY_WINDOW:]]
    means = [sum(c)/len(c) for c in chunks if c]
    if len(means) < 3: return 0.0
    if not (means[0] > means[1] > means[2]): return 0.0   # monotonicidade mínima

    # força do decay: queda normalizada pelo nível inicial
    baseline = max(abs(means[0]), 0.1)   # evita divisão por near-zero
    decay_strength = (means[0] - means[2]) / baseline

    # só penaliza se a queda for significativa (>20% do R original)
    return min(1.0, max(0.0, decay_strength - 0.20))

def _sortino(pnl_hist, window):
    """Sortino rolling — não penaliza volatilidade de lucro."""
    h = pnl_hist[-window:] if len(pnl_hist) >= window else pnl_hist
    if len(h) < 3: return None
    mean = sum(h)/len(h)
    losses = [p for p in h if p < 0]
    down_std = (sum(p**2 for p in losses)/max(len(losses),1))**0.5
    return (mean/down_std) if down_std else (mean * 10 if mean > 0 else 0.0)

def _ensemble_score(r_hist):
    """
    Score composto para ensemble weighting (opera sobre R-multiples capped):
      1. Sortino rolling com janela adaptativa suave
      2. Kill-switch (Sortino curto prazo < KILL_SWITCH_SORTINO)
      3. Penalidade de instabilidade (vol_recente > vol_longo_prazo)
      4. Decay detection (R-mean declina 3 sub-janelas consecutivas)

    Retorna (score: float, killed: bool)
    """
    if len(r_hist) < 3:
        return 0.5, False   # prior neutro no warm-up

    window = _adaptive_window(r_hist)

    # 1. Sortino com janela adaptativa
    s = _sortino(r_hist, window)
    if s is None: return 0.5, False
    score = max(0.0, s)

    # 2. Kill-switch
    s_kill = _sortino(r_hist, KILL_SWITCH_WINDOW)
    killed = (s_kill is not None and s_kill < KILL_SWITCH_SORTINO)
    if killed:
        return 0.0, True

    # 3. Penalidade de instabilidade
    if len(r_hist) >= ENSEMBLE_STAB_WIN:
        recent   = r_hist[-window:]
        longterm = r_hist[-ENSEMBLE_STAB_WIN:-window]
        std_r = _std(recent); std_l = _std(longterm)
        if std_l > 0 and std_r > std_l:
            stability = max(0.3, std_l / std_r)
            score *= stability

    # 4. Decay detection — edge estrutural a morrer lentamente
    decay = _decay_score(r_hist)
    if decay > 0.2:
        score *= max(DECAY_PENALTY, 1.0 - decay * 0.5)

    # 5. Confidence penalty com Bayesian shrinkage
    #    ((n+5)/(N+5))^0.5: prior implícito de 5 trades evita penalidade excessiva no arranque
    #    10 trades→0.50×  25 trades→0.74×  50+ trades→1.0×
    confidence = min(1.0, ((len(r_hist) + 5) / (CONFIDENCE_N_MIN + 5)) ** 0.5)
    score *= confidence

    return max(0.0, score), False

def ensemble_reweight(all_trades):
    """
    Ajusta dinamicamente os pesos AZOTH/HERMES.
    Sem lookahead: cada trade usa apenas performance ANTERIOR.

    Pipeline:
      1. Score via _ensemble_score() sobre R-multiples (não PnL raw)
      2. Normaliza scores → weights [MIN_W, MAX_W]
      3. Kill-switch → peso mínimo + log de evento
      4. Regime-aware boost: macro actual amplifica pesos naturais
      5. Escala PnL: pnl_adj = pnl × (dynamic_w / static_w)
    """
    sorted_t  = sorted(all_trades, key=lambda t: t["timestamp"])
    history   = {"AZOTH": [], "HERMES": []}   # R-multiples, não PnL raw
    kill_log  = {"AZOTH": [], "HERMES": []}
    out       = []

    for idx, t in enumerate(sorted_t):
        strat = t.get("strategy", "AZOTH")

        az_sc, az_killed = _ensemble_score(history["AZOTH"])
        he_sc, he_killed = _ensemble_score(history["HERMES"])

        if az_killed: az_sc = 0.0
        if he_killed: he_sc = 0.0
        total = az_sc + he_sc

        if total < 0.001:
            az_w = AZOTH_CAPITAL_WEIGHT
            he_w = HERMES_CAPITAL_WEIGHT
        else:
            az_w = max(ENSEMBLE_MIN_W, min(ENSEMBLE_MAX_W, az_sc / total))
            he_w = 1.0 - az_w

        if az_killed: az_w = ENSEMBLE_MIN_W; he_w = 1.0 - az_w
        if he_killed: he_w = ENSEMBLE_MIN_W; az_w = 1.0 - he_w

        # penalidade de DD simultâneo — ambas em drawdown ao mesmo tempo
        # indica falha sistémica, não individual → reduz exposição global
        az_dd = max(0.0, 1.0 - (az_sc / max(_ensemble_score(history["AZOTH"][:max(0,len(history["AZOTH"])-ENSEMBLE_WINDOW)])[0], 0.001))) if len(history["AZOTH"]) > ENSEMBLE_WINDOW else 0.0
        he_dd = max(0.0, 1.0 - (he_sc / max(_ensemble_score(history["HERMES"][:max(0,len(history["HERMES"])-ENSEMBLE_WINDOW)])[0], 0.001))) if len(history["HERMES"]) > ENSEMBLE_WINDOW else 0.0
        if az_dd > 0.3 and he_dd > 0.3:   # ambas a degradar simultaneamente
            sim_dd_mult = max(0.70, 1.0 - (az_dd + he_dd) * 0.15)
            az_w *= sim_dd_mult
            he_w *= sim_dd_mult
            # re-normaliza
            total_sim = az_w + he_w
            if total_sim > 0: az_w /= total_sim; he_w /= total_sim

        # regime-aware boost probabilístico com LAG adaptativo
        # lag maior em vol alta (mercado errático) → menos acoplamento
        # lag menor em vol baixa (mercado estável) → mais responsivo
        az_win    = _adaptive_window(history["AZOTH"]) if history["AZOTH"] else ENSEMBLE_WINDOW
        dyn_lag   = int(max(3, min(10, az_win / 10)))
        lag_idx   = max(0, idx - dyn_lag)
        boost, dominant = _regime_confidence_boost(sorted_t[:lag_idx+1])
        az_w_r = az_w * boost["AZOTH"]
        he_w_r = he_w * boost["HERMES"]
        # re-normaliza após boost + clamp
        total_r = az_w_r + he_w_r
        az_w_f  = max(ENSEMBLE_MIN_W, min(ENSEMBLE_MAX_W, az_w_r / total_r))
        he_w_f  = 1.0 - az_w_f

        static_w  = AZOTH_CAPITAL_WEIGHT if strat == "AZOTH" else HERMES_CAPITAL_WEIGHT
        dynamic_w = az_w_f if strat == "AZOTH" else he_w_f
        scale     = dynamic_w / static_w if static_w > 0 else 1.0

        out.append({**t,
            "pnl":               round(t["pnl"] * scale, 2),
            "pnl_pre_ensemble":  t["pnl"],
            "ensemble_w":        round(dynamic_w, 3),
            "az_w":              round(az_w_f, 3),
            "he_w":              round(he_w_f, 3),
            "az_killed":         az_killed,
            "he_killed":         he_killed,
            "regime_at_trade":   dominant,
            "az_decay":          round(_decay_score(history["AZOTH"]), 3),
            "he_decay":          round(_decay_score(history["HERMES"]), 3),
        })

        # log kill-switch
        for s, killed in [("AZOTH", az_killed), ("HERMES", he_killed)]:
            log = kill_log[s]
            if killed and (not log or len(log) % 2 == 0):
                log.append(t["timestamp"])
            elif not killed and log and len(log) % 2 == 1:
                log.append(t["timestamp"])

        if t["result"] in ("WIN", "LOSS"):
            history[strat].append(_r_multiple(t))

    if out: out[-1]["_kill_log"] = kill_log
    return sorted(out, key=lambda t: t["timestamp"])

def print_ensemble_stats(original, reweighted):
    """Compara métricas antes e depois do ensemble reweighting."""
    def _m(trades):
        c = [t for t in trades if t["result"] in ("WIN","LOSS")]
        if not c: return {}
        pnls = [t["pnl"] for t in c]
        eq, _, mdd, _ = equity_stats(pnls)
        r = calc_ratios(pnls, n_days=SCAN_DAYS)
        return {"n": len(c), "wr": sum(1 for t in c if t["result"]=="WIN")/len(c)*100,
                "roi": r["ret"], "mdd": mdd, "sharpe": r["sharpe"], "final": eq[-1]}

    mo = _m(original); mr = _m(reweighted)
    if not mo or not mr: return

    rows = [("ROI",    f"{mo['roi']:+.2f}%",     f"{mr['roi']:+.2f}%",     f"{mr['roi']-mo['roi']:+.2f}pp"),
            ("MaxDD",  f"{mo['mdd']:.2f}%",      f"{mr['mdd']:.2f}%",      f"{mr['mdd']-mo['mdd']:+.2f}pp"),
            ("Sharpe", str(mo['sharpe'] or '—'),  str(mr['sharpe'] or '—'), ""),
            ("WR",     f"{mo['wr']:.1f}%",        f"{mr['wr']:.1f}%",       f"{mr['wr']-mo['wr']:+.1f}pp"),
            ("$Final", f"${mo['final']:,.0f}",    f"${mr['final']:,.0f}",   f"${mr['final']-mo['final']:+,.0f}")]

    print(f"\n{SEP}\n  ENSEMBLE WEIGHTING — Estático vs Adaptativo\n{SEP}")
    print(f"  Score    : Sortino(R-multiple capped [{R_CAP_MIN},{R_CAP_MAX}], window adaptativo) + instabilidade + decay")
    print(f"  Regime   : boost probabilístico BULL/BEAR/CHOP × proporção real (window={REGIME_BOOST_WINDOW})")
    print(f"  Kill-sw  : Sortino({KILL_SWITCH_WINDOW}) < {KILL_SWITCH_SORTINO} → peso mínimo {ENSEMBLE_MIN_W:.0%}")
    print(f"  Decay    : R-mean declinante 3 sub-janelas consecutivas → score × {DECAY_PENALTY}")
    print(f"  {'─'*76}")
    print(f"  {'Métrica':12s}  {'Estático':>12s}  {'Adaptativo':>12s}  {'Δ':>10s}")
    print(f"  {'─'*52}")
    for row in rows:
        better = ""
        if row[0]=="ROI" and mr['roi']>mo['roi']: better=" ✓"
        elif row[0]=="MaxDD" and mr['mdd']<mo['mdd']: better=" ✓"
        elif row[0]=="$Final" and mr['final']>mo['final']: better=" ✓"
        print(f"  {row[0]:12s}  {row[1]:>12s}  {row[2]:>12s}  {row[3]:>10s}{better}")

    # distribuição de regime nos trades reweighted
    regimes = [t.get("regime_at_trade","?") for t in reweighted if "regime_at_trade" in t]
    if regimes:
        from collections import Counter
        rc = Counter(regimes)
        total_r = len(regimes)
        regime_str = "  ".join(f"{k}:{v/total_r*100:.0f}%" for k,v in sorted(rc.items()))
        print(f"\n  Regimes detectados: {regime_str}")

    # kill-switch events
    kill_log = {}
    for t in reversed(reweighted):
        if "_kill_log" in t: kill_log = t["_kill_log"]; break

    print(f"\n  Kill-switch eventos:")
    any_kill = False
    for strat, events in kill_log.items():
        if events:
            any_kill = True
            pairs = [(events[i], events[i+1] if i+1<len(events) else "ainda pausado")
                     for i in range(0, len(events), 2)]
            for start, end in pairs:
                end_s = str(end)[:16] if end != "ainda pausado" else end
                print(f"    {strat:8s}  pausado {str(start)[:16]}  →  recuperado {end_s}")
    if not any_kill:
        print(f"    Nenhum — Sortino(R) manteve-se > {KILL_SWITCH_SORTINO} durante todo o período")

    # decay events
    decay_events = {"AZOTH": [], "HERMES": []}
    for t in reweighted:
        if t.get("strategy") == "AZOTH" and t.get("az_decay", 0) > 0.2:
            decay_events["AZOTH"].append((t["timestamp"], round(t["az_decay"],2)))
        if t.get("strategy") == "HERMES" and t.get("he_decay", 0) > 0.2:
            decay_events["HERMES"].append((t["timestamp"], round(t["he_decay"],2)))

    print(f"\n  Decay detection (R-mean declinante):")
    any_decay = False
    for strat, evs in decay_events.items():
        if evs:
            any_decay = True
            max_decay = max(e[1] for e in evs)
            print(f"    {strat:8s}  {len(evs)} trades em decay  |  máx decay score: {max_decay:.2f}")
    if not any_decay:
        print(f"    Nenhum — edge estrutural manteve-se estável em ambas as estratégias")

# ── STRESS TEST ───────────────────────────────────────────────
def stress_test(pnl_list):
    """
    3 cenários de stress sobre a distribuição de PnL histórica.
    Testa resiliência do sistema a condições que o backtest não captura:

    1. Regime shift   — injecto N janelas de crise (PnL × 0.3)
    2. Slippage shock — custo adicional aleatório por trade
    3. Miss rate      — 15% dos trades não executam (latência/liquidez)
    """
    if len(pnl_list) < 10:
        print("  Stress test: amostra insuficiente."); return

    n = len(pnl_list)
    scenarios = {"Regime Shift": [], "Slippage Shock": [], "Miss Rate (15%)": [],
                 "Regime Flip (20%)": [], "Corr Shock": []}

    for _ in range(STRESS_SIMS):
        # 1. Regime shift (amplitude)
        p = list(pnl_list)
        for _ in range(STRESS_CRISIS_N):
            s = random.randint(0, max(0, n - STRESS_CRISIS_W))
            for i in range(s, min(s + STRESS_CRISIS_W, n)):
                p[i] *= STRESS_CRISIS_MUL
        eq = ACCOUNT_SIZE
        for x in p: eq += x
        scenarios["Regime Shift"].append(eq)

        # 2. Slippage shock
        p = [x - abs(x) * random.uniform(STRESS_SLIP_MIN, STRESS_SLIP_MAX)
             for x in pnl_list]
        eq = ACCOUNT_SIZE
        for x in p: eq += x
        scenarios["Slippage Shock"].append(eq)

        # 3. Miss rate
        p = [x if random.random() > STRESS_MISS_RATE else 0.0 for x in pnl_list]
        eq = ACCOUNT_SIZE
        for x in p: eq += x
        scenarios["Miss Rate (15%)"].append(eq)

        # 4. Regime flip — inverte sinal de 20% dos trades aleatoriamente
        #    simula edge desaparecendo / regime invertendo estruturalmente
        p = [(-x if random.random() < 0.20 else x) for x in pnl_list]
        eq = ACCOUNT_SIZE
        for x in p: eq += x
        scenarios["Regime Flip (20%)"].append(eq)

        # 5. Correlation shock — 30% de probabilidade de todos os trades
        #    correrem juntos (crise: diversificação colapsa)
        if random.random() < 0.30:
            shock_mult = random.uniform(0.50, 0.80)
            p = [x * shock_mult for x in pnl_list]
        else:
            p = list(pnl_list)
        eq = ACCOUNT_SIZE
        for x in p: eq += x
        scenarios["Corr Shock"].append(eq)

    print(f"\n{SEP}\n  STRESS TEST   {STRESS_SIMS}× simulações por cenário\n{SEP}")
    print(f"  {'Cenário':22s}  {'Median $':>10s}  {'p5 $':>10s}  {'% Pos':>7s}  {'RoR':>6s}  {'vs Base':>8s}")
    print(f"  {'─'*72}")

    base_median = sorted(pnl_list)  # referência simples
    base_final  = ACCOUNT_SIZE + sum(pnl_list)

    for name, finals in scenarios.items():
        finals_s = sorted(finals)
        median   = finals_s[STRESS_SIMS // 2]
        p5       = finals_s[int(STRESS_SIMS * 0.05)]
        pct_pos  = sum(1 for f in finals if f > ACCOUNT_SIZE) / STRESS_SIMS * 100
        ror      = sum(1 for f in finals if f < ACCOUNT_SIZE * 0.80) / STRESS_SIMS * 100
        delta    = median - base_final
        icon     = "ok" if pct_pos >= 70 and ror < 5 else "~~" if pct_pos >= 50 else "xx"
        print(f"  {icon} {name:20s}  ${median:>9,.0f}  ${p5:>9,.0f}  {pct_pos:>6.1f}%  {ror:>5.1f}%  ${delta:>+8,.0f}")

    print(f"\n  Base (sem stress)  ${base_final:>9,.0f}  (referência)")
    print(f"\n  Regime Shift    — 3 crises de 20 trades onde PnL × 0.3  (flash crash / estrutura quebrada)")
    print(f"  Slippage Shock  — custo adicional aleatório por trade    (mercado ilíquido)")
    print(f"  Miss Rate (15%) — 15% dos trades não executam            (latência / fills parciais)")
    print(f"  Regime Flip     — 20% dos trades com sinal invertido     (edge reverte estruturalmente)")
    print(f"  Corr Shock      — 30% prob. todos os activos caem juntos (crise de correlação)")

def cross_divergence_multiplier(azoth_trades, hermes_trades):
    """
    Cross-strategy divergence: taxa de conflitos AZOTH×HERMES como proxy
    de instabilidade de regime. Quando os dois modelos discordam muito,
    o mercado está em transição → reduzir risco global.

    Retorna multiplicador [0.5, 1.0]:
      conflito_rate < 20% → mult = 1.0 (normal)
      conflito_rate > 50% → mult = 0.5 (máx redução)
    """
    if not azoth_trades or not hermes_trades: return 1.0

    by_sym_az = defaultdict(list)
    by_sym_he = defaultdict(list)
    for t in azoth_trades: by_sym_az[t["symbol"]].append(t)
    for t in hermes_trades: by_sym_he[t["symbol"]].append(t)

    conflicts = 0; overlaps = 0
    for sym in set(by_sym_az) & set(by_sym_he):
        for ta in by_sym_az[sym]:
            for th in by_sym_he[sym]:
                dt = abs((ta["timestamp"] - th["timestamp"]).total_seconds() / 900)
                if dt <= CONFIRM_WINDOW:
                    overlaps += 1
                    if ta["direction"] != th["direction"]: conflicts += 1

    if overlaps < 5: return 1.0   # amostra insuficiente
    conflict_rate = conflicts / overlaps
    mult = max(0.5, 1.0 - conflict_rate)
    return round(mult, 3)

def auto_diagnostic(all_trades, n_windows=10):
    """
    Auto-diagnóstico sistémico: analisa Sharpe rolling do portfólio GLOBAL
    em janelas cronológicas. Detecta degradação sistémica que o monitoramento
    por estratégia não vê (ambas a falhar simultaneamente).

    Saídas:
      - health_score [0.0, 1.0]: fracção de janelas com Sharpe > 0
      - flag: SAUDAVEL / ATENCAO / CRITICO
      - trend: MELHORANDO / ESTAVEL / DEGRADANDO
    """
    closed = sorted([t for t in all_trades if t["result"] in ("WIN","LOSS")],
                    key=lambda t: t["timestamp"])
    if len(closed) < n_windows * 5: return None

    chunk = len(closed) // n_windows
    window_sharpes = []
    for i in range(n_windows):
        w = closed[i*chunk:(i+1)*chunk]
        pnls = [t["pnl"] for t in w]
        if len(pnls) < 3: continue
        mean = sum(pnls)/len(pnls)
        std  = _std(pnls)
        window_sharpes.append(mean/std if std else (1.0 if mean > 0 else -1.0))

    if not window_sharpes: return None

    health_score = sum(1 for s in window_sharpes if s > 0) / len(window_sharpes)

    # trend: compara primeira metade vs segunda metade
    mid = len(window_sharpes) // 2
    first_half  = sum(window_sharpes[:mid]) / max(mid, 1)
    second_half = sum(window_sharpes[mid:]) / max(len(window_sharpes)-mid, 1)
    if second_half > first_half + 0.1:   trend = "MELHORANDO"
    elif second_half < first_half - 0.1: trend = "DEGRADANDO"
    else:                                trend = "ESTAVEL"

    if health_score >= 0.80:   flag = "SAUDAVEL"
    elif health_score >= 0.60: flag = "ATENCAO"
    else:                      flag = "CRITICO"

    return {"health_score": round(health_score, 2), "flag": flag, "trend": trend,
            "window_sharpes": [round(s, 2) for s in window_sharpes],
            "n_windows": len(window_sharpes)}

def print_auto_diagnostic(diag, conflict_mult):
    """Display auto-diagnostic results."""
    print(f"\n{SEP}\n  AUTO-DIAGNÓSTICO — Saúde Sistémica\n{SEP}")
    if diag is None:
        print("  Amostra insuficiente para diagnóstico sistémico."); return

    icons = {"SAUDAVEL": "ok", "ATENCAO": "~~", "CRITICO": "xx"}
    icon = icons.get(diag["flag"], "~~")
    print(f"  {icon} Estado global   : {diag['flag']}  (health score {diag['health_score']:.0%})")
    print(f"  {'  ' if diag['trend']=='MELHORANDO' else '  '} Tendência       : {diag['trend']}")
    print(f"     Divergência AZ×HE : mult={conflict_mult:.2f}  {'(regime estável)' if conflict_mult > 0.85 else '(instabilidade detectada — risco reduzido)' if conflict_mult > 0.65 else '(regime muito instável)'}")

    # sparkline de Sharpe por janela
    spark = ""
    for s in diag["window_sharpes"]:
        if   s >  1.0: spark += "█"
        elif s >  0.3: spark += "▓"
        elif s >  0.0: spark += "░"
        else:          spark += "·"
    print(f"     Sharpe por janela  : [{spark}]  ({diag['n_windows']} janelas)")

    if diag["flag"] == "CRITICO":
        print(f"\n  ⚠  SISTEMA DEGRADADO — considerar pausa antes do testnet")
    elif diag["flag"] == "ATENCAO":
        print(f"\n  ~  Atenção — validar com período mais longo antes de aumentar capital")

def robustness_test(pnl_list, n_sim=200):
    """
    Suite de robustez pré-testnet — 3 testes + análise de sensibilidade.

    Testes:
      A. Noise test    — ±5% ruído nos PnLs (simula imprecisão de indicadores)
      B. Block shuffle — baralha blocos de 10 trades (testa dependência de ordem)
      C. Drop 10%      — remove aleatoriamente 10% dos trades (testa estabilidade amostral)

    Sensibilidade:
      D. R-cap: [-2,+4] vs [-3,+5] vs [-4,+6]  (impacto do capping)
      E. MC block: 15 vs 25 vs 40               (impacto da janela de autocorr)

    Interpretação:
      CV (coef. variação) < 15% → sistema robusto
      CV 15–30%            → atenção — sensível a parâmetros
      CV > 30%             → risco de overfitting
    """
    if len(pnl_list) < 20:
        print("  Robustness test: amostra insuficiente."); return

    def _run(pnls):
        if not pnls: return None
        eq = [ACCOUNT_SIZE]
        for p in pnls: eq.append(eq[-1]+p)
        n = len(pnls); mean = sum(pnls)/n
        std  = _std(pnls)
        losses = [p for p in pnls if p < 0]
        down_std = (sum(p**2 for p in losses)/max(len(losses),1))**0.5
        ret = (eq[-1]-ACCOUNT_SIZE)/ACCOUNT_SIZE*100
        pk = ACCOUNT_SIZE; mdd = 0.0
        for e in eq:
            if e>pk: pk=e
            if pk: mdd=max(mdd,(pk-e)/pk*100)
        sortino = (mean/down_std) if down_std else 0.0
        return {"roi": round(ret,2), "mdd": round(mdd,2),
                "sortino": round(sortino,3), "final": round(eq[-1],2)}

    def _stats(vals):
        if not vals: return {}
        m = sum(vals)/len(vals)
        s = _std(vals)
        cv = abs(s/m*100) if m else 0
        return {"mean": round(m,2), "std": round(s,2), "cv": round(cv,1),
                "p5": round(sorted(vals)[int(len(vals)*0.05)],2),
                "p95": round(sorted(vals)[int(len(vals)*0.95)],2)}

    n = len(pnl_list)
    results = {}

    # A. Noise ±5%
    noise_rois = []
    for _ in range(n_sim):
        p = [x * (1 + random.gauss(0, 0.05)) for x in pnl_list]
        r = _run(p)
        if r: noise_rois.append(r["roi"])
    results["Noise ±5%"] = _stats(noise_rois)

    # B. Block shuffle (blocos de 10) — mede MaxDD (sensível à ordem), não ROI (invariante)
    bsize = 10
    blocks = [pnl_list[i:i+bsize] for i in range(0, n, bsize)]
    shuffle_mdds = []
    for _ in range(n_sim):
        shuffled_blocks = blocks[:]
        random.shuffle(shuffled_blocks)
        p = [x for b in shuffled_blocks for x in b]
        r = _run(p)
        if r: shuffle_mdds.append(r["mdd"])
    results["Block Shuffle (MaxDD)"] = _stats(shuffle_mdds)

    # C. Drop 10%
    drop_rois = []
    for _ in range(n_sim):
        p = [x for x in pnl_list if random.random() > 0.10]
        r = _run(p)
        if r: drop_rois.append(r["roi"])
    results["Drop 10%"] = _stats(drop_rois)

    base_roi = _run(pnl_list)["roi"] if pnl_list else 0

    print(f"\n{SEP}\n  ROBUSTNESS TEST   {n_sim}× simulações por teste\n{SEP}")
    print(f"  Base ROI: {base_roi:+.2f}%  |  CV < 15% = robusto  |  CV > 30% = risco overfitting")
    print(f"  {'─'*74}")
    print(f"  {'Teste':20s}  {'Métrica':>8s}  {'Médio':>10s}  {'p5':>8s}  {'p95':>8s}  {'CV%':>6s}  {'Status':>8s}")
    print(f"  {'─'*74}")
    metrics_map = {"Noise ±5%": "roi", "Block Shuffle (MaxDD)": "mdd", "Drop 10%": "roi"}
    labels_map  = {"Noise ±5%": "ROI", "Block Shuffle (MaxDD)": "MaxDD", "Drop 10%": "ROI"}
    for name, st in results.items():
        if not st: continue
        cv = st["cv"]; metric = labels_map.get(name, "ROI")
        # para MaxDD: CV alto é instabilidade de path; para ROI: CV alto é fragilidade
        status = "ROBUSTO" if cv < 15 else "ATENCAO" if cv < 30 else "FRAGIL"
        icon   = "ok" if cv < 15 else "~~" if cv < 30 else "xx"
        sign   = "" if metric == "MaxDD" else "+"
        print(f"  {icon} {name:18s}  {metric:>8s}  {st['mean']:>{9}}  {st['p5']:>{8}}  {st['p95']:>{8}}  {cv:>5.1f}%  {status:>8s}")

    # D. Sensibilidade ROI a parâmetros
    print(f"\n  {'─'*74}")
    print(f"  SENSIBILIDADE DE PARÂMETROS  (impacto no ROI base)")
    print(f"  {'─'*74}")

    # D1. Slippage ×2
    slip_pnls = [x * 0.97 for x in pnl_list]  # extra 3% custo (≈ slip×2)
    r_slip = _run(slip_pnls)
    delta_slip = r_slip["roi"] - base_roi if r_slip else 0
    print(f"  Slippage ×2          ROI {r_slip['roi']:>+.2f}%   Δ {delta_slip:>+.2f}pp")

    # D2. Drop top 5% trades (remove melhores)
    sorted_pnls = sorted(enumerate(pnl_list), key=lambda x: x[1], reverse=True)
    n_drop = max(1, int(n * 0.05))
    drop_idx = set(i for i,_ in sorted_pnls[:n_drop])
    pnl_no_top = [x for i,x in enumerate(pnl_list) if i not in drop_idx]
    r_notop = _run(pnl_no_top)
    delta_notop = r_notop["roi"] - base_roi if r_notop else 0
    print(f"  Sem top 5% trades    ROI {r_notop['roi']:>+.2f}%   Δ {delta_notop:>+.2f}pp  {'ok' if abs(delta_notop) < 20 else '⚠ dependência de outliers'}")

    # D3. Latência simulada: atrasa 2 candles (miss 5% das entradas → usa close pior)
    lat_pnls = [x * 0.98 if random.random() < 0.05 else x for x in pnl_list]
    r_lat = _run(lat_pnls)
    delta_lat = r_lat["roi"] - base_roi if r_lat else 0
    print(f"  Latência 5% fills    ROI {r_lat['roi']:>+.2f}%   Δ {delta_lat:>+.2f}pp")

    print(f"\n  Interpretação: Δ < 10pp = robusto  |  Δ 10-25pp = atenção  |  Δ > 25pp = frágil")

def aggregate_signals(azoth_trades, hermes_trades):
    all_t=sorted(azoth_trades+hermes_trades, key=lambda t: t["timestamp"])
    by_sym=defaultdict(list)
    for t in all_t: by_sym[t["symbol"]].append(t)
    confirmed=[]; conflicts=0; confirmations=0
    for sym, ts in by_sym.items():
        used=set()
        for i,t1 in enumerate(ts):
            if i in used: continue
            matched=False
            for j,t2 in enumerate(ts):
                if j<=i or j in used: continue
                if t1["strategy"]==t2["strategy"]: continue
                dt=abs((t1["timestamp"]-t2["timestamp"]).total_seconds()/900)
                if dt>CONFIRM_WINDOW: continue
                if t1["direction"]==t2["direction"]:
                    t1_adj={**t1,"confirmed":True,"conf_partner":t2["strategy"],"pnl":round(t1["pnl"]*CONFIRM_SIZE_MULT,2)}
                    t2_adj={**t2,"confirmed":True,"conf_partner":t1["strategy"],"pnl":round(t2["pnl"]*CONFIRM_SIZE_MULT,2)}
                    confirmed.append(t1_adj); confirmed.append(t2_adj)
                    used.add(i); used.add(j); matched=True; confirmations+=1; break
                else:
                    if CONFLICT_ACTION=="skip":
                        used.add(i); used.add(j); matched=True; conflicts+=1; break
                    t1_adj={**t1,"confirmed":False,"conflict":True,"pnl":round(t1["pnl"]*0.5,2)}
                    confirmed.append(t1_adj); used.add(i); used.add(j); matched=True; conflicts+=1; break
            if not matched and i not in used:
                confirmed.append({**t1,"confirmed":False})
    conflict_mult = cross_divergence_multiplier(azoth_trades, hermes_trades)
    log.info(f"  Aggregator: {confirmations} confirmacoes  {conflicts} conflitos  {len(confirmed)} trades finais  div_mult={conflict_mult:.2f}")
    result = sorted(confirmed, key=lambda t: t["timestamp"])
    if result: result[0] = {**result[0], "_conflict_mult": conflict_mult}
    return result

def metrics_by_strategy(all_trades):
    by_s={"AZOTH":[],"HERMES":[],"CONFIRMED":[]}
    for t in all_trades:
        s=t.get("strategy","AZOTH"); by_s[s].append(t)
        if t.get("confirmed"): by_s["CONFIRMED"].append(t)
    print(f"\n{SEP}\n  PERFORMANCE POR ESTRATEGIA\n{SEP}")
    print(f"  {'Estrategia':12s}  {'N':>4s}  {'WR':>6s}  {'Sharpe':>7s}  {'MaxDD':>6s}  {'ROI':>7s}  {'PnL':>12s}")
    print(f"  {'─'*72}")
    for name,ts in [("AZOTH",by_s["AZOTH"]),("HERMES",by_s["HERMES"]),("CONFIRMADOS",by_s["CONFIRMED"])]:
        closed=[t for t in ts if t["result"] in ("WIN","LOSS")]
        if not closed: print(f"  {name:12s}  sem trades"); continue
        w=sum(1 for t in closed if t["result"]=="WIN"); wr=w/len(closed)*100
        pnl_s=[t["pnl"] for t in closed]
        r=calc_ratios(pnl_s,n_days=SCAN_DAYS); _,_,mdd,_=equity_stats(pnl_s)
        print(f"  {name:12s}  {len(closed):>4d}  {wr:>5.1f}%  {str(r['sharpe'] or '—'):>7s}  {mdd:>5.1f}%  {r['ret']:>+6.1f}%  ${sum(pnl_s):>+10,.0f}")

def metrics_confirmations(all_trades):
    conf=[t for t in all_trades if t.get("confirmed") and t["result"] in ("WIN","LOSS")]
    norm=[t for t in all_trades if not t.get("confirmed") and t["result"] in ("WIN","LOSS")]
    if not conf: print(f"\n  Confirmacoes: 0 trades"); return
    cw=sum(1 for t in conf if t["result"]=="WIN")
    nw=sum(1 for t in norm if t["result"]=="WIN")
    print(f"\n  CONFIRMACOES AZOTH+HERMES")
    print(f"  Confirmados: {len(conf)} trades  WR {cw/len(conf)*100:.1f}%  PnL ${sum(t['pnl'] for t in conf):+,.0f}")
    if norm: print(f"  Individuais: {len(norm)} trades  WR {nw/len(norm)*100:.1f}%")
    by_pat=defaultdict(list)
    for t in conf:
        if t["strategy"]=="HERMES" and "pattern" in t: by_pat[t["pattern"]].append(t)
    if by_pat:
        print(f"  Confirmacoes por padrao HERMES:")
        for pat,ts in sorted(by_pat.items()):
            w2=sum(1 for t in ts if t["result"]=="WIN")
            print(f"    {pat:12s}  n={len(ts)}  WR={w2/len(ts)*100:.0f}%  PnL=${sum(t['pnl'] for t in ts):+,.0f}")

def print_hermes_patterns(all_trades):
    ht=[t for t in all_trades if t.get("strategy")=="HERMES" and t["result"] in ("WIN","LOSS")]
    if not ht: print(f"\n  HERMES: sem trades gerados"); return
    by_pat=defaultdict(list)
    for t in ht: by_pat[t.get("pattern","?")].append(t)
    print(f"\n  HERMES — PADROES HARMONICOS")
    print(f"  {'Padrao':12s}  {'N':>3s}  {'WR':>6s}  {'RR_med':>6s}  {'PnL':>10s}")
    print(f"  {'─'*50}")
    for pat in ["Gartley","Bat","Butterfly","Crab"]:
        ts=by_pat.get(pat,[])
        if not ts: print(f"  {pat:12s}  —"); continue
        w=sum(1 for t in ts if t["result"]=="WIN"); wr=w/len(ts)*100
        rr_m=sum(t["rr"] for t in ts)/len(ts); pnl=sum(t["pnl"] for t in ts)
        print(f"  {'ok' if wr>=50 and pnl>0 else '~' if pnl>0 else 'xx'} {pat:12s}  {len(ts):>3d}  {wr:>5.1f}%  {rr_m:>5.2f}x  ${pnl:>+8,.0f}")

def print_veredito_ms(all_trades, eq, mdd_pct, mc, wf, ratios, wf_regime=None):
    closed=[t for t in all_trades if t["result"] in ("WIN","LOSS")]
    wr=sum(1 for t in closed if t["result"]=="WIN")/max(len(closed),1)*100
    exp=sum(t["pnl"] for t in closed)/max(len(closed),1)
    bear_stab=(wf_regime or {}).get("BEAR",{}).get("stable_pct")
    wf_ok=bear_stab>=60 if bear_stab else False
    wf_label=f"BEAR {bear_stab:.0f}%" if bear_stab else "global"
    checks=[
        ("Trades suficientes (>=50)",len(closed)>=50),
        ("Win Rate >= 50%",wr>=50),
        ("Expectativa positiva",exp>0),
        ("MaxDD < 20%",mdd_pct<20),
        ("Sharpe >= 1.0",ratios["sharpe"] and ratios["sharpe"]>=1.0),
        ("Monte Carlo >= 70% positivo",mc and mc["pct_pos"]>=70),
        (f"Walk-Forward estavel ({wf_label})",wf_ok),
        ("HERMES tem trades",any(t.get("strategy")=="HERMES" for t in closed)),
    ]
    passou=sum(1 for _,v in checks if v)
    print(f"\n{SEP}\n  VEREDITO\n{SEP}")
    for nome,ok in checks: print(f"  {'✓' if ok else '✗'}  {nome}")
    verdict=("EDGE CONFIRMADO" if passou>=7 else
             "PROMISSOR" if passou>=5 else
             "FRAGIL")
    print(f"\n  {passou}/8  ·  {verdict}\n{SEP}\n")
    log.info(f"MS Veredito: {passou}/8  ROI={ratios['ret']:.2f}%  WR={wr:.1f}%  MaxDD={mdd_pct:.1f}%")

def export_ms_json(all_trades, eq, mc, ratios):
    closed=[t for t in all_trades if t["result"] in ("WIN","LOSS")]
    wr=sum(1 for t in closed if t["result"]=="WIN")/max(len(closed),1)*100
    azoth_t=[t for t in closed if t.get("strategy")=="AZOTH"]
    hermes_t=[t for t in closed if t.get("strategy")=="HERMES"]
    confirmed_t=[t for t in closed if t.get("confirmed")]
    payload={
        "version":"multistrategy-1.0","run_id":RUN_ID,
        "timestamp":datetime.now().isoformat(),
        "config":{"azoth_weight":AZOTH_CAPITAL_WEIGHT,"hermes_weight":HERMES_CAPITAL_WEIGHT,
                  "max_open_ms":MAX_OPEN_POSITIONS_MS,"confirm_window":CONFIRM_WINDOW,
                  "confirm_size_mult":CONFIRM_SIZE_MULT,"h_tol":H_TOL,
                  "h_min_score":H_MIN_SCORE,"h_min_rr":H_MIN_RR},
        "summary":{"total":len(closed),"azoth_n":len(azoth_t),"hermes_n":len(hermes_t),
                   "confirmed_n":len(confirmed_t),"win_rate":round(wr,2),
                   "total_pnl":round(sum(t["pnl"] for t in closed),2),
                   "final_equity":round(eq[-1],2),
                   **{k:ratios.get(k) for k in ("sharpe","sortino","calmar","ret")}},
        "by_strategy":{
            "AZOTH":{"n":len(azoth_t),"wr":round(sum(1 for t in azoth_t if t["result"]=="WIN")/max(len(azoth_t),1)*100,1),"pnl":round(sum(t["pnl"] for t in azoth_t),2)},
            "HERMES":{"n":len(hermes_t),"wr":round(sum(1 for t in hermes_t if t["result"]=="WIN")/max(len(hermes_t),1)*100,1),"pnl":round(sum(t["pnl"] for t in hermes_t),2)},
        },
        "monte_carlo":{k:v for k,v in (mc or {}).items() if k not in ("paths","finals","dds")},
        "trades":[{k:(str(v) if k=="timestamp" else v) for k,v in t.items()} for t in all_trades],
        "equity":eq,
    }
    fname=str(MS_RUN_DIR/"reports"/f"multistrategy_{INTERVAL}_v1.json")
    with open(fname,"w",encoding="utf-8") as f: json.dump(payload,f,ensure_ascii=False,indent=2,default=str)
    print(f"  JSON -> {fname}")
    # Auto-persist to DB
    try:
        from core.db import save_run
        save_run("multi", fname)
        print(f"  DB: run persistido")
    except Exception as _e:
        print(f"  DB: {_e}")

def _ask_periodo():
    global SCAN_DAYS, N_CANDLES, HTF_N_CANDLES_MAP
    import backtest as _bt
    v=input(f"\n  Periodo em dias [{SCAN_DAYS}] > ").strip()
    if v.isdigit() and 7<=int(v)<=1500:
        d=int(v)
        _bt.SCAN_DAYS=d; _bt.N_CANDLES=d*24*4
        _bt.HTF_N_CANDLES_MAP={"1h":d*24+200,"4h":d*6+100,"1d":d+100}
        SCAN_DAYS=d; N_CANDLES=d*24*4
        HTF_N_CANDLES_MAP={"1h":d*24+200,"4h":d*6+100,"1d":d+100}
        return d
    return SCAN_DAYS

def _ask_config():
    """Pergunta conta, leverage e risk. Actualiza globals do backtest e do módulo."""
    global ACCOUNT_SIZE, LEVERAGE, BASE_RISK, MAX_RISK, CONVEX_ALPHA
    import backtest as _bt

    # Conta
    v = input(f"  Tamanho da conta USD [{int(_bt.ACCOUNT_SIZE):,}] > ").strip().replace(",","").replace("$","")
    if v.replace(".","").isdigit() and float(v) >= 100:
        _bt.ACCOUNT_SIZE = float(v)

    # Leverage
    print(f"\n  Alavancagem  (1× = sem leverage  |  3× recomendado  |  max seguro ~5×)")
    print(f"  MaxDD escala linearmente: {_bt.ACCOUNT_SIZE:,.0f} × leverage × 4.2% ≈ MaxDD estimado")
    lv = input(f"  Leverage [1] > ").strip()
    leverage = 1.0
    if lv.replace(".","").isdigit():
        leverage = max(1.0, min(float(lv), 20.0))
    _bt.LEVERAGE = leverage

    # Risk (opcional — avançado)
    print(f"\n  Risk por trade  (BASE={_bt.BASE_RISK*100:.1f}%  MAX={_bt.MAX_RISK*100:.1f}%)  [Enter = manter]")
    br = input(f"  BASE_RISK % [{_bt.BASE_RISK*100:.1f}] > ").strip()
    mr = input(f"  MAX_RISK  % [{_bt.MAX_RISK*100:.1f}] > ").strip()
    if br.replace(".","").isdigit(): _bt.BASE_RISK = max(0.001, min(float(br)/100, 0.05))
    if mr.replace(".","").isdigit(): _bt.MAX_RISK  = max(_bt.BASE_RISK, min(float(mr)/100, 0.10))

    # Convex sizing
    print(f"\n  Convex sizing  (quebra proporcionalidade DD/ROI com leverage)")
    print(f"  0.0 = desligado  |  0.5 = suave  |  1.0 = linear  |  2.0 = agressivo")
    cv = input(f"  CONVEX_ALPHA [{_bt.CONVEX_ALPHA}] > ").strip()
    if cv.replace(".","").isdigit(): _bt.CONVEX_ALPHA = max(0.0, min(float(cv), 3.0))

    # Sync module-level globals for _load_dados, _metricas_e_export, etc.
    ACCOUNT_SIZE = _bt.ACCOUNT_SIZE; LEVERAGE = _bt.LEVERAGE
    BASE_RISK = _bt.BASE_RISK; MAX_RISK = _bt.MAX_RISK
    CONVEX_ALPHA = _bt.CONVEX_ALPHA

    return _bt.ACCOUNT_SIZE, _bt.LEVERAGE, _bt.BASE_RISK, _bt.MAX_RISK, _bt.CONVEX_ALPHA

def _ask_plots():
    return input("  Gerar graficos? [s/N] > ").strip().lower() in ("s","sim","y")

def _load_dados(generate_plots):
    global GENERATE_PLOTS
    GENERATE_PLOTS=generate_plots
    print(f"\n{SEP}\n  DADOS   {INTERVAL}   {N_CANDLES:,} candles\n{SEP}")
    _fetch_syms=list(SYMBOLS)
    if MACRO_SYMBOL not in _fetch_syms: _fetch_syms.insert(0,MACRO_SYMBOL)
    all_dfs=fetch_all(_fetch_syms)
    for sym,df in all_dfs.items(): validate(df,sym)
    if not all_dfs: print("  Sem dados."); sys.exit(1)
    htf_stack_by_sym={}
    if MTF_ENABLED:
        for tf in HTF_STACK:
            nc=HTF_N_CANDLES_MAP.get(tf,300)
            print(f"\n{SEP}\n  HTF   {tf}   {nc:,} candles\n{SEP}")
            tf_dfs=fetch_all(list(all_dfs.keys()),interval=tf,n_candles=nc)
            for sym,df_h in tf_dfs.items():
                df_h=prepare_htf(df_h,htf_interval=tf)
                htf_stack_by_sym.setdefault(sym,{})[tf]=df_h
    print(f"\n{SEP}\n  PRE-PROCESSAMENTO\n{SEP}")
    macro_series=detect_macro(all_dfs)
    if macro_series is not None:
        bull_n=(macro_series=="BULL").sum(); bear_n=(macro_series=="BEAR").sum(); chop_n=(macro_series=="CHOP").sum()
        total=bull_n+bear_n+chop_n
        print(f"  Macro ({MACRO_SYMBOL})    BULL {bull_n}c ({bull_n/total*100:.0f}%)   BEAR {bear_n}c ({bear_n/total*100:.0f}%)   CHOP {chop_n}c ({chop_n/total*100:.0f}%)")
    corr=build_corr_matrix(all_dfs)
    return all_dfs, htf_stack_by_sym, macro_series, corr

def _scan_azoth(all_dfs, htf_stack_by_sym, macro_series, corr):
    print(f"\n{SEP}\n  SCAN AZOTH (trend-following fractal)\n{SEP}")
    azoth_all=[]; azoth_vetos=defaultdict(int)
    for sym,df in all_dfs.items():
        if sym not in SYMBOLS: continue
        trades,vetos=azoth_scan(df,sym,macro_series,corr,htf_stack_by_sym.get(sym) if MTF_ENABLED else None)
        for t in trades: t["strategy"]="AZOTH"; t.setdefault("confirmed",False)
        azoth_all.extend(trades)
        for k,v in vetos.items(): azoth_vetos[k]+=v
        closed=[t for t in trades if t["result"] in ("WIN","LOSS")]
        w=sum(1 for t in closed if t["result"]=="WIN")
        chop_n=sum(1 for t in trades if t.get("chop_trade"))
        print(f"  AZOTH  {sym:12s}  n={len(trades):>4d}  WR={w/max(len(closed),1)*100:>5.1f}%  PnL=${sum(t['pnl'] for t in closed):>+9,.0f}" + (f"  [MR:{chop_n}]" if chop_n else ""))
    return azoth_all, azoth_vetos

def _scan_hermes_all(all_dfs, htf_stack_by_sym, macro_series, corr):
    print(f"\n{SEP}\n  SCAN HERMES (harmonicos XABCD — Gartley/Bat/Butterfly/Crab)\n{SEP}")
    hermes_all=[]; hermes_vetos=defaultdict(int)
    for sym,df in all_dfs.items():
        if sym not in SYMBOLS: continue
        trades,vetos=scan_hermes(df,sym,macro_series,corr,htf_stack_by_sym.get(sym) if MTF_ENABLED else None)
        hermes_all.extend(trades)
        for k,v in vetos.items(): hermes_vetos[k]+=v
        closed=[t for t in trades if t["result"] in ("WIN","LOSS")]
        w=sum(1 for t in closed if t["result"]=="WIN")
        by_pat=defaultdict(int)
        for t in trades: by_pat[t.get("pattern","?")]+=1
        pat_str="  ".join(f"{k}:{v}" for k,v in sorted(by_pat.items()) if v)
        print(f"  HERMES {sym:12s}  n={len(trades):>4d}  WR={w/max(len(closed),1)*100:>5.1f}%  PnL=${sum(t['pnl'] for t in closed):>+9,.0f}" + (f"  [{pat_str}]" if pat_str else ""))
    print(f"\n{SEP}\n  FILTROS HERMES\n{SEP}")
    tv=sum(hermes_vetos.values())
    for k,n in sorted(hermes_vetos.items(),key=lambda x:-x[1])[:12]:
        bar="░"*min(int(n/max(tv,1)*30),30)
        print(f"  {k:40s}  {n:>6d}  {n/max(tv,1)*100:>4.1f}%  {bar}")
    return hermes_all, hermes_vetos

def _metricas_e_export(all_trades, label="AZOTH + HERMES"):
    closed=[t for t in all_trades if t["result"] in ("WIN","LOSS")]
    if not closed: print("  Sem trades fechados."); return
    pnl_s=[t["pnl"] for t in closed]; eq,mdd,mdd_pct,ms=equity_stats(pnl_s)
    ratios=calc_ratios(pnl_s,n_days=SCAN_DAYS)
    print(f"\n{SEP}\n  METRICAS DE PORTFOLIO ({label})\n{SEP}")
    print(f"  Sharpe   {str(ratios['sharpe'] or '—'):>7s}     Sortino  {str(ratios['sortino'] or '—'):>7s}     Calmar  {str(ratios['calmar'] or '—'):>7s}")
    print(f"  Sharpe diário {str(ratios.get('sharpe_daily') or '—'):>5s}  (benchmark-comparable, ann. 252d)")
    print(f"  ROI      {ratios['ret']:>6.2f}%     MaxDD    {mdd_pct:>6.2f}%     Streak  {ms:>5d} perdas")
    print(f"  Capital  ${ACCOUNT_SIZE:>8,.0f}  ->  ${eq[-1]:>10,.0f}   (+${eq[-1]-ACCOUNT_SIZE:,.0f})")
    if label!="AZOTH":
        metrics_by_strategy(all_trades); metrics_confirmations(all_trades); print_hermes_patterns(all_trades)
    mc=monte_carlo(pnl_s)
    print(f"\n{SEP}\n  MONTE CARLO   {MC_N}x   bloco={MC_BLOCK}\n{SEP}")
    if mc:
        rlb="SEGURO" if mc["ror"]<1 else "ATENCAO" if mc["ror"]<5 else "RISCO"
        print(f"  Positivos {mc['pct_pos']:>5.1f}%   p5 ${mc['p5']:>9,.0f}   Mediana ${mc['median']:>9,.0f}   p95 ${mc['p95']:>9,.0f}")
        print(f"  RoR       {mc['ror']:>5.1f}%   [{rlb}]   DD medio {mc['avg_dd']:.1f}%   pior {mc['worst_dd']:.1f}%")
    wf=walk_forward(all_trades)
    print(f"\n{SEP}\n  WALK-FORWARD GLOBAL   {len(wf)} janelas\n{SEP}")
    if wf:
        ok=sum(1 for w in wf if abs(w["test"]["wr"]-w["train"]["wr"])<=15); pct=ok/len(wf)*100
        print(f"  {ok}/{len(wf)} estaveis ({pct:.0f}%)   {'ESTAVEL' if pct>=60 else 'INSTAVEL'}")
        for w in wf[-10:]:
            d=w["test"]["wr"]-w["train"]["wr"]
            print(f"  {w['w']:>3d}  treino {w['train']['wr']:>5.1f}%  fora {w['test']['wr']:>5.1f}%  D {d:>+5.1f}%  {'ok' if abs(d)<=15 else 'xx'}")
    wf_regime=walk_forward_by_regime(all_trades)
    print(f"\n{SEP}\n  WALK-FORWARD POR REGIME\n{SEP}")
    for regime,d in wf_regime.items():
        if d["stable_pct"] is None: print(f"  {regime:5s}  n={d['n']:>3d}  insuficiente"); continue
        print(f"  {regime:5s}  n={d['n']:>3d}  estaveis: {d['stable_pct']:.0f}%  {'ESTAVEL' if d['stable_pct']>=60 else 'INSTAVEL'}")
    yy=year_by_year_analysis(all_trades)
    if len([yr for yr,d in yy.items() if d])>=2:
        print(f"\n{SEP}\n  PERFORMANCE ANO A ANO\n{SEP}")
        for yr in sorted(yy.keys()):
            d=yy[yr]
            if not d: continue
            yr_trades=[t for t in closed if t.get("timestamp") and t["timestamp"].year==yr]
            az_n=sum(1 for t in yr_trades if t.get("strategy")=="AZOTH")
            he_n=sum(1 for t in yr_trades if t.get("strategy")=="HERMES")
            print(f"  {yr}  {d['n']:>4d}  {d['wr']:>5.1f}%  {d['roi']:>+6.1f}%  ${d['pnl']:>+8,.0f}  {d['mdd']:>5.1f}%  AZ:{az_n}  HE:{he_n}")

    # ── ROBUSTNESS TEST ───────────────────────────────────────
    robustness_test(pnl_s)

    # ── AUTO-DIAGNÓSTICO ─────────────────────────────────────
    diag = auto_diagnostic(all_trades)
    conflict_mult = all_trades[0].get("_conflict_mult", 1.0) if all_trades else 1.0
    print_auto_diagnostic(diag, conflict_mult)

    # ── ENSEMBLE WEIGHTING ────────────────────────────────────
    if label not in ("AZOTH", "HERMES"):
        rew = ensemble_reweight(all_trades)
        print_ensemble_stats(all_trades, rew)

    # ── STRESS TEST ───────────────────────────────────────────
    stress_test(pnl_s)

    print_veredito_ms(all_trades,eq,mdd_pct,mc,wf,ratios,wf_regime)
    export_ms_json(all_trades,eq,mc,ratios)

    # ── CHARTS ────────────────────────────────────────────────
    if GENERATE_PLOTS:
        try:
            import matplotlib
            matplotlib.rcParams["text.usetex"] = False
            import matplotlib.pyplot as plt

            # equity curve
            fig, ax = plt.subplots(figsize=(14,5))
            ax.plot(eq, linewidth=1.5, color="#00c8a0")
            ax.fill_between(range(len(eq)), eq, eq[0], alpha=0.15, color="#00c8a0")
            ax.axhline(eq[0], color="#888", linewidth=0.8, linestyle="--")
            ax.set_title(f"AZOTH × HERMES — Equity Curve ({label})", fontsize=13)
            ax.set_xlabel("Trade #"); ax.set_ylabel("Capital $")
            ax.grid(True, alpha=0.2)
            fname_eq = str(MS_RUN_DIR / "charts" / f"equity_{INTERVAL}.png")
            fig.savefig(fname_eq, dpi=130, bbox_inches="tight"); plt.close(fig)
            print(f"  Chart → {fname_eq}")

            # monte carlo
            if mc:
                plot_montecarlo(mc, eq, run_dir=MS_RUN_DIR)
                print(f"  Chart → {MS_RUN_DIR / 'charts' / f'montecarlo_{INTERVAL}.png'}")
        except Exception as _e:
            log.warning(f"Charts error: {_e}")

    print(f"\n{SEP}\n  output  ·  {MS_RUN_DIR}/\n{SEP}\n")

def _resultados_por_simbolo(all_trades, show_he=True):
    print(f"\n{SEP}\n  RESULTADOS POR SIMBOLO\n{SEP}")
    hdr="  {:12s}  {:>4s}  {:>4s}  {:>4s}  {:>6s}  {:>12s}".format("ATIVO","N","AZ","HE","WR","PnL") if show_he else \
        "  {:12s}  {:>4s}  {:>6s}  {:>12s}".format("ATIVO","N","WR","PnL")
    print(hdr)
    by_sym=defaultdict(list)
    for t in all_trades: by_sym[t["symbol"]].append(t)
    for sym in sorted(by_sym):
        ts=by_sym[sym]; c=[t for t in ts if t["result"] in ("WIN","LOSS")]
        if not c: continue
        w=sum(1 for t in c if t["result"]=="WIN"); wr=w/len(c)*100
        if show_he:
            az=sum(1 for t in c if t.get("strategy")=="AZOTH")
            he=sum(1 for t in c if t.get("strategy")=="HERMES")
            print(f"  {sym:12s}  {len(c):>4d}  {az:>4d}  {he:>4d}  {wr:>5.1f}%  ${sum(t['pnl'] for t in c):>+10,.0f}")
        else:
            print(f"  {sym:12s}  {len(c):>4d}  {wr:>5.1f}%  ${sum(t['pnl'] for t in c):>+10,.0f}")

def _menu():
    W = 50
    print(f"\n  {'─'*W}")
    print(f"  HADRON  ·  Multistrategy Backtest")
    print(f"  {'─'*W}")
    while True:
        print()
        print(f"  [1]  GRAVITON + PHOTON")
        print(f"  [2]  GRAVITON")
        print(f"  [3]  PHOTON")
        print(f"  [4]  NEWTON")
        print(f"  [5]  MERCURIO")
        print(f"  [6]  THOTH")
        print(f"  [7]  ALL")
        print(f"  [8]  PROMETEU (ML)")
        print(f"  [0]  Sair")
        print()
        op = input("  > ").strip()
        if op == "0": sys.exit(0)
        if op in ("1","2","3","4","5","6","7","8"): return op
        print("  opcao invalida")

if __name__ == "__main__":
    op = _menu()
    LABELS = {
        "1":"GRAVITON + PHOTON", "2":"GRAVITON", "3":"PHOTON",
        "4":"NEWTON", "5":"MERCURIO", "6":"THOTH",
        "7":"ALL", "8":"PROMETEU (ML)",
    }
    days = _ask_periodo()
    acct, lev, base_r, max_r, convex = _ask_config()
    plots = _ask_plots()

    print(f"\n{SEP}")
    print(f"  {LABELS[op]}  ·  {days}d  ·  {len(SYMBOLS)} ativos  ·  {INTERVAL}")
    print(f"  ${acct:,.0f}  ·  {lev:.0f}x  ·  risk {base_r*100:.1f}–{max_r*100:.1f}%  ·  convex {convex:.1f}")
    if plots: print(f"  charts on")
    print(f"  {MS_RUN_DIR}/")
    print(SEP)
    input("\n  enter para iniciar... ")
    log.info(f"AURUM op={LABELS[op]} dias={days} — {RUN_ID}")
    all_dfs, htf_stack_by_sym, macro_series, corr = _load_dados(plots)

    if op == "2":
        azoth_all, _ = _scan_azoth(all_dfs, htf_stack_by_sym, macro_series, corr)
        if not azoth_all: print("  Sem trades."); sys.exit(1)
        _resultados_por_simbolo(azoth_all, show_he=False)
        _metricas_e_export(azoth_all, label="GRAVITON")

    elif op == "3":
        hermes_all, _ = _scan_hermes_all(all_dfs, htf_stack_by_sym, macro_series, corr)
        if not hermes_all: print("  Sem trades."); sys.exit(1)
        _resultados_por_simbolo(hermes_all, show_he=False)
        _metricas_e_export(hermes_all, label="PHOTON")

    elif op == "4":
        from engines.newton import find_cointegrated_pairs, scan_pair
        print(f"\n{SEP}\n  COINTEGRATION ANALYSIS\n{SEP}")
        pairs = find_cointegrated_pairs(all_dfs)
        newton_all = []
        for pair in pairs:
            df_a = all_dfs.get(pair["sym_a"])
            df_b = all_dfs.get(pair["sym_b"])
            if df_a is None or df_b is None: continue
            trades, _ = scan_pair(df_a.copy(), df_b, pair["sym_a"], pair["sym_b"],
                                  pair, macro_series, corr)
            newton_all.extend(trades)
        newton_all.sort(key=lambda t: t["timestamp"])
        if not newton_all: print("  Sem trades."); sys.exit(1)
        _resultados_por_simbolo(newton_all, show_he=False)
        _metricas_e_export(newton_all, label="NEWTON")

    elif op == "5":
        from engines.mercurio import scan_mercurio
        mercurio_all = []
        for sym, df in all_dfs.items():
            trades, _ = scan_mercurio(df.copy(), sym, macro_series, corr)
            mercurio_all.extend(trades)
        mercurio_all.sort(key=lambda t: t["timestamp"])
        if not mercurio_all: print("  Sem trades."); sys.exit(1)
        _resultados_por_simbolo(mercurio_all, show_he=False)
        _metricas_e_export(mercurio_all, label="MERCURIO")

    elif op == "6":
        from engines.thoth import scan_thoth, collect_sentiment
        print(f"\n{SEP}\n  SENTIMENT DATA\n{SEP}")
        sentiment_data = collect_sentiment(list(all_dfs.keys()))
        thoth_all = []
        for sym, df in all_dfs.items():
            trades, _ = scan_thoth(df.copy(), sym, macro_series, corr,
                                   sentiment_data=sentiment_data)
            thoth_all.extend(trades)
        thoth_all.sort(key=lambda t: t["timestamp"])
        if not thoth_all: print("  Sem trades."); sys.exit(1)
        _resultados_por_simbolo(thoth_all, show_he=False)
        _metricas_e_export(thoth_all, label="THOTH")

    elif op == "7":
        # ALL engines
        engine_trades = {}

        azoth_all, _ = _scan_azoth(all_dfs, htf_stack_by_sym, macro_series, corr)
        engine_trades["GRAVITON"] = azoth_all

        hermes_all, _ = _scan_hermes_all(all_dfs, htf_stack_by_sym, macro_series, corr)
        engine_trades["PHOTON"] = hermes_all

        from engines.newton import find_cointegrated_pairs, scan_pair
        pairs = find_cointegrated_pairs(all_dfs)
        newton_all = []
        for pair in pairs:
            df_a = all_dfs.get(pair["sym_a"])
            df_b = all_dfs.get(pair["sym_b"])
            if df_a is None or df_b is None: continue
            trades, _ = scan_pair(df_a.copy(), df_b, pair["sym_a"], pair["sym_b"],
                                  pair, macro_series, corr)
            newton_all.extend(trades)
        engine_trades["NEWTON"] = newton_all

        from engines.mercurio import scan_mercurio
        mercurio_all = []
        for sym, df in all_dfs.items():
            trades, _ = scan_mercurio(df.copy(), sym, macro_series, corr)
            mercurio_all.extend(trades)
        engine_trades["MERCURIO"] = mercurio_all

        from engines.thoth import scan_thoth, collect_sentiment
        sentiment_data = collect_sentiment(list(all_dfs.keys()))
        thoth_all = []
        for sym, df in all_dfs.items():
            trades, _ = scan_thoth(df.copy(), sym, macro_series, corr,
                                   sentiment_data=sentiment_data)
            thoth_all.extend(trades)
        engine_trades["THOTH"] = thoth_all

        # merge all
        all_trades = []
        for eng, trades in engine_trades.items():
            for t in trades:
                t = t.copy()
                if "strategy" not in t: t["strategy"] = eng
                all_trades.append(t)
        all_trades.sort(key=lambda t: t["timestamp"])

        if not all_trades: print("  Sem trades."); sys.exit(1)

        # summary per engine
        print(f"\n{SEP}\n  RESULTADOS POR ENGINE\n{SEP}")
        for eng in ["GRAVITON", "PHOTON", "NEWTON", "MERCURIO", "THOTH"]:
            ts = [t for t in all_trades if t.get("strategy") == eng and t["result"] in ("WIN","LOSS")]
            if not ts: print(f"  {eng:12s}  sem trades"); continue
            w = sum(1 for t in ts if t["result"] == "WIN")
            pnl = sum(t["pnl"] for t in ts)
            print(f"  {eng:12s}  n={len(ts):>4d}  WR={w/len(ts)*100:>5.1f}%  ${pnl:>+10,.0f}")

        _metricas_e_export(all_trades, label="ALL ENGINES")

    elif op == "8":
        # PROMETEU (ML ensemble)
        engine_trades = {}

        azoth_all, _ = _scan_azoth(all_dfs, htf_stack_by_sym, macro_series, corr)
        engine_trades["GRAVITON"] = azoth_all

        hermes_all, _ = _scan_hermes_all(all_dfs, htf_stack_by_sym, macro_series, corr)
        engine_trades["PHOTON"] = hermes_all

        from engines.newton import find_cointegrated_pairs, scan_pair
        pairs = find_cointegrated_pairs(all_dfs)
        newton_all = []
        for pair in pairs:
            df_a = all_dfs.get(pair["sym_a"])
            df_b = all_dfs.get(pair["sym_b"])
            if df_a is None or df_b is None: continue
            trades, _ = scan_pair(df_a.copy(), df_b, pair["sym_a"], pair["sym_b"],
                                  pair, macro_series, corr)
            newton_all.extend(trades)
        engine_trades["NEWTON"] = newton_all

        from engines.mercurio import scan_mercurio
        mercurio_all = []
        for sym, df in all_dfs.items():
            trades, _ = scan_mercurio(df.copy(), sym, macro_series, corr)
            mercurio_all.extend(trades)
        engine_trades["MERCURIO"] = mercurio_all

        from engines.thoth import scan_thoth, collect_sentiment
        sentiment_data = collect_sentiment(list(all_dfs.keys()))
        thoth_all = []
        for sym, df in all_dfs.items():
            trades, _ = scan_thoth(df.copy(), sym, macro_series, corr,
                                   sentiment_data=sentiment_data)
            thoth_all.extend(trades)
        engine_trades["THOTH"] = thoth_all

        from engines.prometeu import run_prometeu
        all_trades = run_prometeu(engine_trades)

        if not all_trades: print("  Sem trades."); sys.exit(1)
        _metricas_e_export(all_trades, label="PROMETEU ML")

    else:
        # op == "1" — original GRAVITON + PHOTON
        azoth_all, _ = _scan_azoth(all_dfs, htf_stack_by_sym, macro_series, corr)
        hermes_all, _ = _scan_hermes_all(all_dfs, htf_stack_by_sym, macro_series, corr)
        print(f"\n{SEP}\n  SIGNAL AGGREGATOR\n{SEP}")
        all_trades = aggregate_signals(azoth_all, hermes_all)
        if not all_trades: print("  Sem trades."); sys.exit(1)
        _resultados_por_simbolo(all_trades, show_he=True)
        _metricas_e_export(all_trades, label="GRAVITON + PHOTON")