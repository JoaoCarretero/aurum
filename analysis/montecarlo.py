"""AURUM — Monte Carlo simulation (block bootstrap)."""
import random
import numpy as np
from config.params import ACCOUNT_SIZE, MC_N, MC_BLOCK

def monte_carlo(pnl_list, seed=None):
    # seed=None keeps the legacy stochastic behavior; pass an int to make
    # walk-forward/robustness audits reproducible run-to-run.
    if len(pnl_list) < MC_BLOCK*2: return None
    rng = random.Random(seed) if seed is not None else random
    n, finals, dds, paths, pos = len(pnl_list), [], [], [], 0
    for sim in range(MC_N):
        sh = []
        while len(sh) < n:
            s = rng.randint(0, n-MC_BLOCK); sh.extend(pnl_list[s:s+MC_BLOCK])
        sh  = sh[:n]; eq = [ACCOUNT_SIZE]
        for p in sh: eq.append(eq[-1]+p)
        finals.append(eq[-1])
        if eq[-1] > ACCOUNT_SIZE: pos += 1
        pk = ACCOUNT_SIZE; dd = 0.0
        for e in eq:
            if e > pk: pk = e
            if pk: dd = max(dd, (pk-e)/pk*100)
        dds.append(dd)
        if sim < 200: paths.append(eq)
    finals.sort()
    ror = sum(1 for f in finals if f < ACCOUNT_SIZE*0.80)/MC_N*100
    return {"pct_pos":round(pos/MC_N*100,1),
            "median":round(finals[MC_N//2],2),
            "p5":round(finals[int(MC_N*0.05)],2),
            "p95":round(finals[int(MC_N*0.95)],2),
            "avg_dd":round(sum(dds)/len(dds),2),
            "worst_dd":round(max(dds),2),
            "ror":round(ror,2),"finals":finals,"paths":paths,"dds":dds}

