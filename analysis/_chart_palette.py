"""AURUM — shared chart palette for analysis/*.

Matplotlib/HTML chart cores. Vivem aqui pra que `plots.py`, `report_html.py`
e `overfit_audit.py` nao redefinam os mesmos hex de forma independente
(drift silencioso se alguem atualizar um arquivo so).

Separado de `core/ui_palette.py` de proposito: UI chrome (launcher, macro
brain, arb desk) usa a paleta HL2/VGUI laranja, enquanto charts precisam
de tons com contraste de legibilidade em fundo escuro. Se un dia forem
unificadas, isso acontece aqui.

`charts.py` usa paleta GitHub-inspirada distinta — nao importa deste
modulo (intencional, estetica diferente).
"""
from __future__ import annotations

# Fundos
BG     = "#0a0a12"   # outer background
PANEL  = "#0f0f1a"   # panel / card background
BORDER = "#1e1e2e"   # spine / divider

# Accents
GOLD   = "#e8b84b"   # amber, primary accent
GREEN  = "#26d47c"   # positive PnL
RED    = "#e85d5d"   # negative PnL
BLUE   = "#4a9eff"   # neutral / secondary line
PURPLE = "#9b7fe8"   # tertiary
TEAL   = "#2dd4bf"   # highlight

# Greys
LGRAY  = "#6b7280"   # soft grey (plots.py)
DGRAY  = "#1f2937"   # dark grey fill
GRAY   = "#9ca3af"   # mid grey (report_html / overfit)
WHITE  = "#f0f0f0"   # near-white text
