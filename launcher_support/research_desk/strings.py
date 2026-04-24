"""Strings UI do Research Desk, em portugues BR.

Single source of truth — nao hardcode texto em outros modulos.
"""
from __future__ import annotations


# ── Header / navigation ───────────────────────────────────────────
TITLE = "RESEARCH DESK"
SUBTITLE_FMT = "{n} operativos  |  paperclip {state}  |  budget {used}/{cap}"
PATH_LABEL = "> RESEARCH > DESK"
STATUS_LABEL = "DESK"
FOOTER_KEYS = "ESC voltar  |  N novo ticket  |  R refresh  |  S start/stop paperclip"

# ── Paperclip server states ───────────────────────────────────────
STATE_ONLINE = "ONLINE"
STATE_OFFLINE = "OFFLINE"
STATE_STARTING = "STARTING"
STATE_UNKNOWN = "UNKNOWN"

# ── Panel titles ──────────────────────────────────────────────────
PANEL_AGENTS = "OPERATIVOS"
PANEL_PIPELINE = "ACTIVE PIPELINE"
PANEL_ARTIFACTS = "RECENT ARTIFACTS"

# ── Buttons ───────────────────────────────────────────────────────
BTN_START_PAPERCLIP = "INICIAR PAPERCLIP"
BTN_STOP_PAPERCLIP = "PARAR PAPERCLIP"
BTN_NEW_TICKET = "NOVO TICKET"
BTN_REFRESH = "REFRESH"
BTN_ASSIGN = "ATRIBUIR"
BTN_CONFIGURE = "CONFIGURAR"
BTN_HISTORY = "HISTORICO"

# ── Placeholders / empty states ───────────────────────────────────
EMPTY_PIPELINE = "sem tickets ativos no momento."
EMPTY_ARTIFACTS = "nenhum artefato indexado ainda."
OFFLINE_BANNER = "paperclip server offline — inicie pra habilitar acoes."
LOADING = "carregando..."

# ── Error messages ────────────────────────────────────────────────
ERR_HEALTH_FAIL = "health check falhou"
ERR_API_TIMEOUT = "timeout na api"
ERR_PROCESS_SPAWN = "falha ao iniciar paperclip"
