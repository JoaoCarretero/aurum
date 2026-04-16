"""
AURUM — Design tokens da UI desktop (paleta HL2 / CS 1.6 VGUI).

Pegada nostálgica Valve: charcoal + HL2 orange + creme quente Source Engine.
Este é o single source of truth para toda a UI Tkinter do software.

Consumido por:
  - launcher.py                    (namespace AMBER_*)
  - core/alchemy_ui.py             (namespace HEV_*)
  - macro_brain/dashboard_view.py  (namespace AMBER_*)
  - core/engine_picker.py          (namespace AMBER_*)
  - code_viewer.py                 (namespace AMBER_*)
  - analysis/results_gui.py        (namespace AMBER_*, complementa chart pal)

Mude aqui → todo o software adota na próxima execução.
"""

# ── Paleta canônica (valores brutos) ──────────────────────────────
# Source Engine VGUI (HL2 2004 / CS 1.6 MOTD).
_BG         = "#2A2A2A"   # charcoal HL2 — fundo janelas
_BG2        = "#333333"   # cinza um passo acima (tabs inativos)
_BG3        = "#4C4C4C"   # cinza hover / botões
_PANEL      = "#3A3A3A"   # painel interno (tiles)
_BORDER     = "#565656"   # borda padrão
_BORDER2    = "#8A7545"   # borda hover — dourado envelhecido
_GLOW       = "#1F1F1F"   # glow escuro (engine picker track)

_SILVER     = "#D08F36"   # acento primário — laranja menu HL2
_SILVER_D   = "#8F7A45"   # acento dim
_SILVER_B   = "#F0A847"   # acento bright hover
_SILVER_DD  = "#565656"   # = BORDER

_WHITE      = "#D6C99A"   # texto primário — creme quente Source Engine
_DIM        = "#8F8F8F"   # metadado
_DIM2       = "#B0A17F"   # metadado secundário (cream dim)

_GREEN      = "#7FA84A"   # sinal positivo — barra de HP HL2
_RED        = "#C44535"   # sinal negativo — dano HL2
_CYAN       = "#7FA0B0"   # secundário interativo — aço / pipe
_HAZARD     = "#E8C87A"   # alerta — yellow warning
_BLOOD      = "#7A4535"   # drawdown profundo

# ── Launcher / dashboard_view / engine_picker / code_viewer ──────
# Nomenclatura AMBER_* é histórica (era amber Bloomberg) — hoje
# aponta pro laranja HL2. Nome preservado pra não quebrar imports.
BG       = _BG
BG2      = _BG2
BG3      = _BG3
PANEL    = _PANEL
BORDER   = _BORDER
BORDER_H = _BORDER2
AMBER    = _SILVER
AMBER_D  = _SILVER_D
AMBER_B  = _SILVER_B
AMBER_H  = _SILVER_B        # alias dashboard_view (H de "hover/high")
WHITE    = _WHITE
DIM      = _DIM
DIM2     = _DIM2
GREEN    = _GREEN
RED      = _RED
CYAN     = _CYAN
GLOW     = _GLOW

# ── Alchemy UI (nomenclatura HEV_* do Half-Life HEV suit) ────────
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

# ── Tile accents (launcher main menu) — espectro HL2 ─────────────
# Quatro tons distintos mas todos dentro da paleta Source Engine,
# pra categorização do menu principal continuar scan-able sem
# romper a coesão visual.
TILE_MARKETS    = "#7FA0B0"   # STEEL BLUE   — quote + dash
TILE_EXECUTE    = "#7FA84A"   # HP GREEN     — strategies + arb + risk
TILE_RESEARCH   = "#D08F36"   # HL2 ORANGE   — terminal + data
TILE_CONTROL    = "#C9B584"   # AGED CREAM   — connections + command + settings
TILE_DIM_FACTOR = 0.35

FONT = "Consolas"
