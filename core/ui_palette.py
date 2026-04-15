"""
AURUM — Design tokens da UI desktop (paleta neutra silver/graphite/black).

SSOT consumida por launcher.py e core/alchemy_ui.py. Expoe duas nomenclaturas
(legada AMBER_* do launcher e HEV_* do alchemy) apontando para os mesmos
valores canonicos — evita drift entre os dois cockpits.
"""

# ── Paleta canonica (valores brutos) ─────────────────────────────
_BG        = "#080808"
_BG2       = "#101010"
_BG3       = "#181818"
_PANEL     = "#0C0C0C"
_BORDER    = "#242424"
_BORDER2   = "#5A5A5A"
_SILVER    = "#C8C8C8"   # primary accent
_SILVER_D  = "#6A6A6A"   # dim
_SILVER_B  = "#F0F0F0"   # bright hover
_SILVER_DD = "#242424"   # double-dim (= BORDER)
_WHITE     = "#E6E6E6"
_DIM       = "#707070"
_DIM2      = "#2A2A2A"
_GREEN     = "#00D26A"
_RED       = "#FF4D4F"
_HAZARD    = "#D8D1A8"
_BLOOD     = "#7A6262"

# ── Launcher (nomenclatura legada AMBER_*) ──────────────────────
# AMBER e derivados sao nomes historicos (era amber Bloomberg); agora
# apontam para o silver do silver/graphite redesign.
BG      = _BG
BG2     = _BG2
BG3     = _BG3
PANEL   = _PANEL
BORDER  = _BORDER
AMBER   = _SILVER
AMBER_D = _SILVER_D
AMBER_B = _SILVER_B
WHITE   = _WHITE
DIM     = _DIM
DIM2    = _DIM2
GREEN   = _GREEN
RED     = _RED

# ── Alchemy UI (nomenclatura HEV_*) ─────────────────────────────
HEV_BG       = _BG
HEV_PANEL    = _PANEL
HEV_BORDER   = _BORDER
HEV_BORDER2  = _BORDER2
HEV_AMBER    = _SILVER
HEV_AMBER_B  = _SILVER_B
HEV_AMBER_D  = _SILVER_D
HEV_AMBER_DD = _SILVER_DD
HEV_WHITE    = _WHITE
HEV_DIM      = _DIM
HEV_GREEN    = _GREEN
HEV_RED      = _RED
HEV_HAZARD   = _HAZARD
HEV_BLOOD    = _BLOOD

# ── Tile accents (launcher main menu) ───────────────────────────
TILE_MARKETS    = "#6EB2E8"   # SOFT CYAN  — quote + dash
TILE_EXECUTE    = "#6ADB8A"   # MUTED MINT — strategies + arb + risk
TILE_RESEARCH   = "#E6C86A"   # WARM AMBER — terminal + data
TILE_CONTROL    = "#D88EC8"   # DUSTY ROSE — connections + command + settings
TILE_DIM_FACTOR = 0.35

FONT = "Consolas"
