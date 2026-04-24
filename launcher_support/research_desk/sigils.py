"""Sigils alquimicos desenhados programaticamente em tk.Canvas.

5 sigils — um por operativo — compartilhando linguagem visual:
  - circulo de conteimento externo
  - glyph central em linha fina (stroke ~2px)
  - ornamento sutil (pequenas marks no frame)
  - cor primaria do agente pro glyph; dim pro frame

RESEARCH  (The Seer)      — olho dentro do circulo + raios
REVIEW    (The Judge)     — balanca + gladius
BUILD     (The Forger)    — martelo + bigorna
CURATE    (The Keeper)    — vassoura + ampulheta
AUDIT     (The Oracle)    — calice com triangulo de veredito + gotas

Por que Canvas e nao SVG: Tkinter nao tem parser SVG stdlib. Adicionar
tksvg/cairosvg/Pillow so pros sigils seria overkill. Canvas desenha
escalavel, limpo, sem dep — e o proprio launcher ja usa esse estilo
(tiles isometricos do MainMenuScreen sao drawn em Canvas).

API:
    sigil = SigilCanvas(parent, agent_key, size=96)
    sigil.pack(...)
"""
from __future__ import annotations

import math
import tkinter as tk

from core.ui.ui_palette import DIM, PANEL
from launcher_support.research_desk.palette import AGENT_COLORS


_DEFAULT_SIZE = 96
_STROKE_MAIN = 2
_STROKE_FRAME = 1


class SigilCanvas:
    """Widget wrapper: tk.Canvas com o sigil de um agente desenhado."""

    def __init__(
        self,
        parent: tk.Misc,
        agent_key: str,
        *,
        size: int = _DEFAULT_SIZE,
        bg: str = PANEL,
    ):
        self.agent_key = agent_key
        self.size = size
        self.bg = bg

        self.canvas = tk.Canvas(
            parent,
            width=size, height=size,
            bg=bg,
            highlightthickness=0, borderwidth=0,
        )

        self.draw()

    # ── Layout passthrough ────────────────────────────────────────

    def pack(self, **opts: object) -> None:
        self.canvas.pack(**opts)

    def grid(self, **opts: object) -> None:
        self.canvas.grid(**opts)

    def place(self, **opts: object) -> None:
        self.canvas.place(**opts)

    # ── Drawing dispatch ──────────────────────────────────────────

    def draw(self) -> None:
        palette = AGENT_COLORS.get(self.agent_key)
        if palette is None:
            # Fallback: desenha so o frame circular
            _draw_frame(self.canvas, self.size, DIM)
            return

        primary = palette.primary
        dim = palette.dim

        # Todos os sigils compartilham o circulo de conteimento + ornamento
        _draw_frame(self.canvas, self.size, dim)

        # Glyph central varia por agente
        drawer = _GLYPH_DISPATCH.get(self.agent_key)
        if drawer is not None:
            drawer(self.canvas, self.size, primary, dim)


# ── Drawing helpers ───────────────────────────────────────────────


def _draw_frame(canvas: tk.Canvas, size: int, color: str) -> None:
    """Circulo externo + 4 marks de compasso (norte/sul/leste/oeste)."""
    pad = 4
    canvas.create_oval(
        pad, pad, size - pad, size - pad,
        outline=color, width=_STROKE_FRAME,
    )
    # 4 pequenas marks no frame (compasso)
    cx, cy = size / 2, size / 2
    r_outer = size / 2 - pad
    r_inner = r_outer - 3
    for angle in (0, 90, 180, 270):
        rad = math.radians(angle)
        x1 = cx + r_outer * math.cos(rad)
        y1 = cy + r_outer * math.sin(rad)
        x2 = cx + r_inner * math.cos(rad)
        y2 = cy + r_inner * math.sin(rad)
        canvas.create_line(x1, y1, x2, y2, fill=color, width=_STROKE_FRAME)


def _draw_research(canvas: tk.Canvas, size: int, primary: str, dim: str) -> None:
    """Olho almondine + 8 raios."""
    cx, cy = size / 2, size / 2
    # Almond eye shape (2 arcs meeting)
    eye_w = size * 0.45
    eye_h = size * 0.22
    # Upper arc
    canvas.create_arc(
        cx - eye_w / 2, cy - eye_h, cx + eye_w / 2, cy + eye_h / 2,
        start=0, extent=180, style="arc",
        outline=primary, width=_STROKE_MAIN,
    )
    # Lower arc (mirrored)
    canvas.create_arc(
        cx - eye_w / 2, cy - eye_h / 2, cx + eye_w / 2, cy + eye_h,
        start=180, extent=180, style="arc",
        outline=primary, width=_STROKE_MAIN,
    )
    # Pupil (circulo cheio)
    pupil_r = size * 0.055
    canvas.create_oval(
        cx - pupil_r, cy - pupil_r, cx + pupil_r, cy + pupil_r,
        fill=primary, outline=primary,
    )
    # Iris ring
    iris_r = size * 0.1
    canvas.create_oval(
        cx - iris_r, cy - iris_r, cx + iris_r, cy + iris_r,
        outline=primary, width=_STROKE_FRAME,
    )

    # 8 raios emanando (NW, N, NE, E, SE, S, SW, W alternados comp/longos)
    r_start = size * 0.30
    r_long = size * 0.38
    r_short = size * 0.34
    for i, deg in enumerate((45, 90, 135, 180, 225, 270, 315, 360)):
        # Offset pra raios nao saem da pupila diretamente
        # Tiny rays, decorative, between inner iris and frame
        pass  # Rays desativados — o olho ja carrega o sigil. Menos e mais.
    # Mas rendering do raio classico de seer: triangulos apontando pra fora
    ray_len = size * 0.08
    r_base = size * 0.2
    for deg in (0, 45, 90, 135, 180, 225, 270, 315):
        rad = math.radians(deg)
        x1 = cx + r_base * math.cos(rad)
        y1 = cy + r_base * math.sin(rad)
        x2 = cx + (r_base + ray_len) * math.cos(rad)
        y2 = cy + (r_base + ray_len) * math.sin(rad)
        canvas.create_line(x1, y1, x2, y2, fill=dim, width=_STROKE_FRAME)


def _draw_review(canvas: tk.Canvas, size: int, primary: str, dim: str) -> None:
    """Gladius vertical + balance beam + 2 pans."""
    cx, cy = size / 2, size / 2
    # Gladius blade (vertical line)
    blade_top = cy - size * 0.25
    blade_bottom = cy + size * 0.32
    canvas.create_line(
        cx, blade_top, cx, blade_bottom,
        fill=primary, width=_STROKE_MAIN,
    )
    # Pomo (bolinha no topo)
    pommel_r = size * 0.04
    canvas.create_oval(
        cx - pommel_r, blade_top - pommel_r * 2, cx + pommel_r, blade_top,
        fill=primary, outline=primary,
    )
    # Ponta (triangulo no fundo)
    canvas.create_polygon(
        cx - size * 0.04, blade_bottom,
        cx + size * 0.04, blade_bottom,
        cx, blade_bottom + size * 0.06,
        fill=primary, outline=primary,
    )
    # Cross-guard horizontal (balance beam)
    beam_y = cy - size * 0.1
    beam_half = size * 0.32
    canvas.create_line(
        cx - beam_half, beam_y, cx + beam_half, beam_y,
        fill=primary, width=_STROKE_MAIN,
    )
    # Chains e pans
    pan_y = beam_y + size * 0.14
    pan_half_w = size * 0.08
    for sign in (-1, 1):
        px = cx + sign * beam_half
        # Chain (linha vertical fina)
        canvas.create_line(
            px, beam_y, px, pan_y,
            fill=dim, width=_STROKE_FRAME,
        )
        # Pan (arc baixo tipo U)
        canvas.create_arc(
            px - pan_half_w, pan_y - size * 0.04,
            px + pan_half_w, pan_y + size * 0.06,
            start=200, extent=140, style="arc",
            outline=primary, width=_STROKE_MAIN,
        )


def _draw_build(canvas: tk.Canvas, size: int, primary: str, dim: str) -> None:
    """Bigorna (trapezoid + horn) + martelo atravessando em 45deg."""
    cx, cy = size / 2, size / 2

    # Bigorna — trapezoid com horn protruding left
    anvil_top_y = cy + size * 0.08
    anvil_base_y = cy + size * 0.25
    anvil_top_half = size * 0.2
    anvil_base_half = size * 0.28
    # Corpo trapezoidal
    canvas.create_polygon(
        cx - anvil_top_half, anvil_top_y,
        cx + anvil_top_half, anvil_top_y,
        cx + anvil_base_half, anvil_base_y,
        cx - anvil_base_half, anvil_base_y,
        outline=primary, width=_STROKE_MAIN, fill="",
    )
    # Horn (triangulo pra esquerda)
    canvas.create_polygon(
        cx - anvil_top_half, anvil_top_y,
        cx - anvil_top_half - size * 0.1, anvil_top_y + size * 0.04,
        cx - anvil_top_half, anvil_top_y + size * 0.07,
        outline=primary, width=_STROKE_MAIN, fill="",
    )
    # Base pedestal (linha grossa curta no fundo)
    canvas.create_line(
        cx - anvil_base_half * 0.6, anvil_base_y,
        cx + anvil_base_half * 0.6, anvil_base_y,
        fill=primary, width=_STROKE_MAIN + 1,
    )

    # Martelo atravessando em 30deg — handle + head
    # Handle (linha diagonal)
    handle_top_x = cx + size * 0.22
    handle_top_y = cy - size * 0.30
    handle_bot_x = cx - size * 0.1
    handle_bot_y = cy + size * 0.02
    canvas.create_line(
        handle_bot_x, handle_bot_y, handle_top_x, handle_top_y,
        fill=dim, width=_STROKE_MAIN,
    )
    # Head (rectangulo rotacionado — approx com polygon)
    head_size = size * 0.12
    dx = handle_top_x - handle_bot_x
    dy = handle_top_y - handle_bot_y
    length = math.sqrt(dx * dx + dy * dy)
    if length > 0:
        # Perpendicular ao handle
        perp_x = -dy / length
        perp_y = dx / length
        head_half = head_size / 2
        hx, hy = handle_top_x, handle_top_y
        canvas.create_polygon(
            hx + perp_x * head_half - dx / length * head_size * 0.4,
            hy + perp_y * head_half - dy / length * head_size * 0.4,
            hx - perp_x * head_half - dx / length * head_size * 0.4,
            hy - perp_y * head_half - dy / length * head_size * 0.4,
            hx - perp_x * head_half + dx / length * head_size * 0.4,
            hy - perp_y * head_half + dy / length * head_size * 0.4,
            hx + perp_x * head_half + dx / length * head_size * 0.4,
            hy + perp_y * head_half + dy / length * head_size * 0.4,
            fill=primary, outline=primary,
        )


def _draw_curate(canvas: tk.Canvas, size: int, primary: str, dim: str) -> None:
    """Ampulheta no centro + vassoura atras em diagonal."""
    cx, cy = size / 2, size / 2

    # Vassoura (diagonal de NW pra SE, atras da ampulheta)
    broom_top_x = cx - size * 0.28
    broom_top_y = cy - size * 0.28
    broom_bot_x = cx + size * 0.1
    broom_bot_y = cy + size * 0.1
    # Handle
    canvas.create_line(
        broom_top_x, broom_top_y, broom_bot_x, broom_bot_y,
        fill=dim, width=_STROKE_MAIN,
    )
    # Bristles (leque de linhas curtas no fundo do handle)
    dx = broom_bot_x - broom_top_x
    dy = broom_bot_y - broom_top_y
    length = math.sqrt(dx * dx + dy * dy)
    if length > 0:
        # Direcao do handle
        dir_x = dx / length
        dir_y = dy / length
        # Posicao onde bristles comecam (extensao do handle)
        bristle_start_x = broom_bot_x
        bristle_start_y = broom_bot_y
        bristle_len = size * 0.14
        # 5 bristles formando leque
        for spread in (-0.4, -0.2, 0.0, 0.2, 0.4):
            ang = math.atan2(dir_y, dir_x) + spread
            end_x = bristle_start_x + math.cos(ang) * bristle_len
            end_y = bristle_start_y + math.sin(ang) * bristle_len
            canvas.create_line(
                bristle_start_x, bristle_start_y, end_x, end_y,
                fill=dim, width=_STROKE_FRAME,
            )

    # Ampulheta (hourglass) — dois triangulos tocando no centro
    hg_half_w = size * 0.12
    hg_top = cy - size * 0.22
    hg_bot = cy + size * 0.22
    # Triangulo superior (V invertido)
    canvas.create_polygon(
        cx - hg_half_w, hg_top,
        cx + hg_half_w, hg_top,
        cx, cy,
        outline=primary, width=_STROKE_MAIN, fill="",
    )
    # Triangulo inferior (V)
    canvas.create_polygon(
        cx - hg_half_w, hg_bot,
        cx + hg_half_w, hg_bot,
        cx, cy,
        outline=primary, width=_STROKE_MAIN, fill="",
    )
    # Base/topo caps horizontais
    canvas.create_line(
        cx - hg_half_w - 2, hg_top, cx + hg_half_w + 2, hg_top,
        fill=primary, width=_STROKE_MAIN,
    )
    canvas.create_line(
        cx - hg_half_w - 2, hg_bot, cx + hg_half_w + 2, hg_bot,
        fill=primary, width=_STROKE_MAIN,
    )
    # Gota caindo (pequeno circulo no centro — areia passando)
    drop_r = size * 0.025
    canvas.create_oval(
        cx - drop_r, cy - drop_r, cx + drop_r, cy + drop_r,
        fill=primary, outline=primary,
    )


def _draw_audit(canvas: tk.Canvas, size: int, primary: str, dim: str) -> None:
    """Calice (chalice) com triangulo de veredito + 3 gotas.

    AUDIT emite vereditos numericos/finais — o calice ritual acima do
    triangulo (representacao alquimica de fogo/sublimacao) evoca
    destilacao e julgamento final. Tres gotas abaixo = PASS/FAIL/
    CONDITIONAL.
    """
    cx, cy = size / 2, size / 2

    # Triangulo de veredito (fogo alquimico — apex para cima) no topo
    tri_half_w = size * 0.18
    tri_top_y = cy - size * 0.32
    tri_base_y = cy - size * 0.08
    canvas.create_polygon(
        cx, tri_top_y,
        cx - tri_half_w, tri_base_y,
        cx + tri_half_w, tri_base_y,
        outline=primary, width=_STROKE_MAIN, fill="",
    )
    # Linha horizontal dividindo o triangulo — marca de "perfeicao"
    line_y = tri_top_y + (tri_base_y - tri_top_y) * 0.65
    line_half = tri_half_w * 0.55
    canvas.create_line(
        cx - line_half, line_y, cx + line_half, line_y,
        fill=primary, width=_STROKE_FRAME,
    )

    # Calice (chalice) central — stem + bowl
    stem_top_y = tri_base_y + size * 0.04
    stem_bot_y = stem_top_y + size * 0.12
    canvas.create_line(
        cx, stem_top_y, cx, stem_bot_y,
        fill=primary, width=_STROKE_MAIN,
    )
    bowl_half_w = size * 0.16
    bowl_bot_y = stem_bot_y + size * 0.10
    canvas.create_arc(
        cx - bowl_half_w, stem_bot_y - size * 0.02,
        cx + bowl_half_w, bowl_bot_y,
        start=180, extent=180, style="arc",
        outline=primary, width=_STROKE_MAIN,
    )
    base_half = bowl_half_w * 0.75
    canvas.create_line(
        cx - base_half, bowl_bot_y, cx + base_half, bowl_bot_y,
        fill=primary, width=_STROKE_MAIN,
    )

    # 3 gotas caindo abaixo (decorativas, dim) — PASS/FAIL/CONDITIONAL
    drop_r = size * 0.022
    drop_y = bowl_bot_y + size * 0.10
    for offset in (-size * 0.09, 0, size * 0.09):
        canvas.create_oval(
            cx + offset - drop_r, drop_y - drop_r,
            cx + offset + drop_r, drop_y + drop_r,
            fill=dim, outline=dim,
        )


_GLYPH_DISPATCH = {
    "RESEARCH": _draw_research,
    "REVIEW": _draw_review,
    "BUILD": _draw_build,
    "CURATE": _draw_curate,
    "AUDIT": _draw_audit,
}
