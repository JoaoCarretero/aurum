# AURUM deploy helpers

## MILLENNIUM shadow — 24h VPS

One-shot install on a fresh VPS (Ubuntu/Debian, Python 3.12+):

```bash
# 1. As root: copy the unit
sudo cp deploy/millennium_shadow.service /etc/systemd/system/

# 2. Adjust User= and WorkingDirectory= inside the unit to match your layout
sudo $EDITOR /etc/systemd/system/millennium_shadow.service

# 3. Reload systemd, enable at boot, start now
sudo systemctl daemon-reload
sudo systemctl enable millennium_shadow.service
sudo systemctl start millennium_shadow.service

# 4. Follow logs (journalctl) — shadow itself also writes to
#    data/millennium_shadow/<RUN_ID>/logs/shadow.log
sudo journalctl -u millennium_shadow.service -f
```

### Stop / restart

```bash
sudo systemctl stop millennium_shadow.service       # graceful (SIGTERM)
sudo systemctl restart millennium_shadow.service
```

Inside the live run you can also drop a kill flag from anywhere:

```bash
touch data/millennium_shadow/<RUN_ID>/.kill
```

The current tick finishes before the loop exits, so the JSONL stays consistent.

### What you get on disk

```
data/millennium_shadow/<RUN_ID>/
├── logs/shadow.log               # human-readable tick-by-tick log
├── reports/shadow_trades.jsonl   # append-only trades (one per line)
└── state/heartbeat.json          # last tick status, counts, error
```

### Hygiene checklist before flipping to real capital

Shadow is paper by design — no keys loaded, no orders. Before deciding to
move a validated shadow window into real-money execution, go back to the
`docs/audits/2026-04-17_millennium_readiness.md` ressalvas and close them:

1. R1 — FROZEN_ENGINES vs OPERATIONAL_ENGINES (governance flag)
2. R2 — sentiment `end_time_ms` for OOS windows (fixed at call-site for
   BRIDGEWATER removal; confirm if you reintroduce it)
3. R3 — legacy ensemble weights in `engines/millennium.py`

Plus: RENAISSANCE and JUMP still need first-class streaming adapters
before the full MILLENNIUM pod can route real orders honestly.
