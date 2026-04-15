"""
JANE STREET — runtime-tunable parameter defaults.

SSOT para os 9 parametros que o engine aceita ajustar em tempo de execucao
via config/alchemy_params.json (com reload flag). O engine (engines/janestreet.py)
le estes defaults no boot, e o dashboard (core/alchemy_state.py) os usa como
fallback quando alchemy_params.json nao existe.

Evita drift entre o engine e o state reader — ambos importam dqui.
"""

# Thresholds para abrir posicao
MIN_SPREAD  = 0.0015   # spread minimo (fracao decimal, ex: 0.0015 = 0.15%)
MIN_APR     = 40.0     # APR anualizado minimo (%)

# Sizing e exposure
MAX_POS     = 5        # posicoes abertas simultaneas
POS_PCT     = 0.20     # fracao do capital por posicao
LEV         = 2        # alavancagem (x)

# Timing
SCAN_S      = 30       # intervalo entre scans (segundos)
EXIT_H      = 8        # horas ate checar decaimento do spread

# Risk gates
MAX_DD_PCT  = 0.05     # drawdown maximo antes do kill switch (fracao)
KILL_LOSSES = 3        # losses consecutivos antes do kill switch


DEFAULTS = {
    "MIN_SPREAD": MIN_SPREAD,
    "MIN_APR": MIN_APR,
    "MAX_POS": MAX_POS,
    "POS_PCT": POS_PCT,
    "LEV": LEV,
    "SCAN_S": SCAN_S,
    "EXIT_H": EXIT_H,
    "MAX_DD_PCT": MAX_DD_PCT,
    "KILL_LOSSES": KILL_LOSSES,
}
