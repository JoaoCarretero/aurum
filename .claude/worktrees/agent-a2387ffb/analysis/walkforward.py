"""AURUM — Walk-forward validation."""
from config.params import WF_TRAIN, WF_TEST

def walk_forward(trades):
    c = sorted([t for t in trades if t["result"] in ("WIN","LOSS")],
               key=lambda x: x["timestamp"])
    if len(c) < WF_TRAIN+WF_TEST: return []
    windows, i = [], 0
    while i+WF_TRAIN+WF_TEST <= len(c):
        tr = c[i:i+WF_TRAIN]; te = c[i+WF_TRAIN:i+WF_TRAIN+WF_TEST]
        def st(lst):
            w = sum(1 for t in lst if t["result"]=="WIN")
            return {"n":len(lst),"wr":round(w/len(lst)*100,1),"pnl":round(sum(t["pnl"] for t in lst),2)}
        windows.append({"w":i//WF_TEST+1,"train":st(tr),"test":st(te)}); i+=WF_TEST
    return windows

def walk_forward_by_regime(trades: list) -> dict:
    WF_TOL = 15
    results = {}
    for regime in ("BULL", "BEAR", "CHOP"):
        subset = sorted(
            [t for t in trades if t["result"] in ("WIN","LOSS")
             and t.get("macro_bias","CHOP") == regime],
            key=lambda x: x["timestamp"])
        if len(subset) < WF_TRAIN + WF_TEST:
            results[regime] = {"windows": [], "stable_pct": None, "n": len(subset)}
            continue
        windows = []
        i = 0
        while i + WF_TRAIN + WF_TEST <= len(subset):
            tr = subset[i:i+WF_TRAIN]
            te = subset[i+WF_TRAIN:i+WF_TRAIN+WF_TEST]
            wtr = sum(1 for t in tr if t["result"]=="WIN") / len(tr) * 100
            wte = sum(1 for t in te if t["result"]=="WIN") / len(te) * 100
            d   = wte - wtr
            windows.append({"train": round(wtr,1), "test": round(wte,1),
                             "delta": round(d,1), "ok": abs(d) <= WF_TOL})
            i += WF_TEST
        ok_n = sum(1 for w in windows if w["ok"])
        results[regime] = {
            "windows":    windows,
            "n":          len(subset),
            "stable_pct": round(ok_n / len(windows) * 100, 0) if windows else None,
        }
    return results

def print_wf_by_regime(wf_regime: dict):
    icons = {"BULL": "↑", "BEAR": "↓", "CHOP": "↔"}
    for regime, d in wf_regime.items():
        if d["stable_pct"] is None:
            print(f"  {icons.get(regime,'')} {regime:5s}  n={d['n']:>3d}  amostra insuficiente"); continue
        lbl = "✓ ESTÁVEL" if d["stable_pct"] >= 60 else "✗ INSTÁVEL"
        print(f"  {icons.get(regime,'')} {regime:5s}  n={d['n']:>3d}  "
              f"estáveis: {d['stable_pct']:.0f}%  {lbl}")
        for w in d["windows"][-6:]:
            st = "✓" if w["ok"] else "✗"
            print(f"         treino {w['train']:>5.1f}%  fora {w['test']:>5.1f}%  "
                  f"Δ {w['delta']:>+5.1f}%  {st}")

