"""SplashScreen - pilot migration of launcher._splash."""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Any

from core.ui.ui_palette import (
    AMBER, AMBER_B, AMBER_D, BG, BORDER, DIM, DIM2, FONT,
    GREEN, RED, WHITE,
)

from launcher_support.screens.base import Screen
from launcher_support.screens.splash_data import (
    read_engine_roster,
    read_last_session,
    read_macro_brain,
)


class SplashScreen(Screen):
    # Canvas dimensions come from app._SPLASH_DESIGN_W / _H (920×640).

    # Mapa status -> cor do ENGINE ROSTER. Cor e o canal primario de scan
    # visual (row inteira pinta na cor do status), sem emojis.
    _STATUS_COLORS = {
        "OK":  GREEN,    # edges reais (CITADEL, JUMP)
        "BUG": AMBER,    # inflado/bug-suspect (RENAISS, BRIDGEW)
        "NEW": WHITE,    # em validacao OOS (PHI)
        "TUN": AMBER_B,  # em tuning (ORNSTEIN)
        "OFF": DIM,      # fora da bateria (TWOSIGMA, AQR)
        "NO":  RED,      # falhou OOS (DE_SHAW, KEPOS, MEDALLION)
    }

    # Mapa regime_raw do macro_brain -> cor pro valor "REGIME" no tile.
    _REGIME_COLORS = {
        "risk_on":     GREEN,
        "risk_off":    RED,
        "transition":  AMBER,
        "uncertainty": DIM,
    }

    # Top rule + logo (textos do topo removidos: wordmark band, title
    # "OPERATOR DESK", subtitle e tagline foram retirados pra dar mais
    # espaco pros tiles ocuparem a tela). A logo subiu pra y=58.
    _CENTER_X = 460
    _TOP_RULE_Y = 30
    _BOTTOM_RULE_Y = 596
    _RULE_X1 = 48
    _RULE_X2 = 872

    _LOGO_Y = 58              # top logo: 28px abaixo do top rule (y=30)
    _BOTTOM_LOGO_Y = 568      # bottom logo: 28px acima do bottom rule (y=596)
                               # espelhando o LOGO_Y (prompt text removido)

    # Tile grid 2×3 (row 2 has wide tile in slot 2-3)
    _CONTENT_X1 = 48          # = _RULE_X1
    _CONTENT_X2 = 872         # = _RULE_X2
    _TILE_GAP = 16
    _TILE_W_SIMPLE = 264      # (824 - 2*16) / 3
    _TILE_W_WIDE = 544        # 2 simples + 1 gap
    _TILE_H = 180
    _TILE_PAD = 14
    _TILE_LINE_H = 20

    _ROW1_Y1 = 104
    _ROW1_Y2 = _ROW1_Y1 + _TILE_H       # 284
    _ROW2_Y1 = _ROW1_Y2 + _TILE_GAP     # 300
    _ROW2_Y2 = _ROW2_Y1 + _TILE_H       # 480

    # Ticker/news strip entre Row2 e logo inferior (uma linha so).
    _TICKER_Y1 = 500
    _TICKER_Y2 = 536

    def __init__(self, parent: tk.Misc, app: Any, conn: Any, tagline: str):
        super().__init__(parent)
        self.app = app
        self.conn = conn
        self.tagline = tagline
        self.canvas: tk.Canvas | None = None
        self._design_w = app._SPLASH_DESIGN_W
        self._design_h = app._SPLASH_DESIGN_H
        self._render_scale = 1.0
        self._index_path = Path("data/index.json")

    def build(self) -> None:
        """Cria frame + canvas. Todo desenho acontece em on_enter."""
        frame = tk.Frame(self.container, bg=BG)
        frame.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(
            frame,
            bg=BG,
            highlightthickness=0,
            width=self._design_w,
            height=self._design_h,
        )
        self.canvas.pack(fill="both", expand=True)

    def on_enter(self, **kwargs: Any) -> None:
        del kwargs
        app = self.app
        app.h_path.configure(text="")
        app.h_stat.configure(text="READY", fg=AMBER_B)
        app.f_lbl.configure(text="ENTER proceed  |  CLICK proceed  |  Q quit")

        canvas = self.canvas
        if canvas is None:
            return

        canvas.delete("splash")
        # Content was redrawn at design scale — reset tracker so _apply_canvas_scale
        # computes the correct ratio for the next configure event.
        self._render_scale = 1.0
        offline = self._read_offline_data()
        self._draw_offline_tiles(canvas, offline)

        self._bind(canvas, "<Button-1>", lambda e: app._splash_on_click())
        app._bind_global_nav()
        self._after(500, self._pulse_tick)
        self._bind(canvas, "<Configure>", self._render_resize)
        self._render_resize()

    def _read_offline_data(self) -> dict:
        app = self.app
        try:
            st = self.conn.status_summary()
            market_val = st.get("market", "-")
        except Exception:
            market_val = "-"
        try:
            keys = app._load_json("keys.json")
            has_tg = bool(keys.get("telegram", {}).get("bot_token"))
            has_keys = bool(
                keys.get("demo", {}).get("api_key")
                or keys.get("testnet", {}).get("api_key")
            )
        except Exception:
            has_tg = False
            has_keys = False

        market_txt = "● LIVE" if market_val and market_val != "-" else "○ OFFLINE"
        market_col = GREEN if "LIVE" in market_txt else DIM
        conn_txt = "● BINANCE" if has_keys else "○ OFFLINE"
        conn_col = GREEN if has_keys else DIM
        tg_txt = "● ONLINE" if has_tg else "○ OFFLINE"
        tg_col = GREEN if has_tg else DIM

        session = read_last_session(self._index_path)
        roster = read_engine_roster(self._index_path)
        macro = read_macro_brain()

        if macro is None:
            macro_rows = {
                "regime":  ("---",  DIM),
                "why":     ("---",  DIM),
                "thesis":  ("FLAT", DIM),
                "idea":    ("awaiting signal", DIM),
            }
        else:
            regime_col = self._REGIME_COLORS.get(macro["regime_raw"], DIM)
            conf = macro.get("confidence")
            regime_txt = macro["regime"]
            if isinstance(conf, (int, float)):
                regime_txt = f"{regime_txt} {conf:.0%}"
            thesis_txt = macro["thesis"]
            tconf = macro.get("thesis_conf")
            if isinstance(tconf, (int, float)) and thesis_txt != "FLAT":
                thesis_txt = f"{thesis_txt} {tconf:.2f}"
            macro_rows = {
                "regime":  (regime_txt, regime_col),
                "why":     (macro["why"], DIM2),
                "thesis":  (thesis_txt, AMBER_B if thesis_txt != "FLAT" else DIM),
                "idea":    (macro["idea"], WHITE if macro["idea"] != "awaiting signal" else DIM),
            }

        return {
            "status": {
                "market": (market_txt, market_col),
                "conn":   (conn_txt, conn_col),
                "tg":     (tg_txt, tg_col),
                "apilat": ("---", DIM),
            },
            "risk": {
                "killsw":  ("ARMED", RED),
                "ddvel":   ("---", DIM),
                "aggnot":  ("---", DIM),
                "gates":   ("---", DIM),
            },
            "macro": macro_rows,
            "session": session,
            "roster": roster,
        }

    def _draw_offline_tiles(self, canvas: tk.Canvas, data: dict) -> None:
        self._draw_wordmark(canvas)
        gap = self._TILE_GAP
        w = self._TILE_W_SIMPLE

        # Row 1: STATUS | RISK | MACRO BRAIN
        r1_x_starts = [
            self._CONTENT_X1,
            self._CONTENT_X1 + w + gap,
            self._CONTENT_X1 + 2 * (w + gap),
        ]
        self._draw_splash_tile(
            canvas,
            x1=r1_x_starts[0], y1=self._ROW1_Y1,
            x2=r1_x_starts[0] + w, y2=self._ROW1_Y2,
            title="STATUS",
            rows=[
                ("market", "MARKET", *data["status"]["market"]),
                ("conn",   "CONN",   *data["status"]["conn"]),
                ("tg",     "TG",     *data["status"]["tg"]),
                ("apilat", "API LAT", *data["status"]["apilat"]),
            ],
        )
        self._draw_splash_tile(
            canvas,
            x1=r1_x_starts[1], y1=self._ROW1_Y1,
            x2=r1_x_starts[1] + w, y2=self._ROW1_Y2,
            title="RISK",
            rows=[
                ("killsw", "KILL-SW", *data["risk"]["killsw"]),
                ("ddvel",  "DD VEL",  *data["risk"]["ddvel"]),
                ("aggnot", "AGG NOT", *data["risk"]["aggnot"]),
                ("gates",  "GATES",   *data["risk"]["gates"]),
            ],
        )
        self._draw_splash_tile(
            canvas,
            x1=r1_x_starts[2], y1=self._ROW1_Y1,
            x2=r1_x_starts[2] + w, y2=self._ROW1_Y2,
            title="MACRO BRAIN",
            rows=[
                ("regime", "REGIME", *data["macro"]["regime"]),
                ("why",    "WHY",    *data["macro"]["why"]),
                ("thesis", "THESIS", *data["macro"]["thesis"]),
                ("idea",   "IDEA",   *data["macro"]["idea"]),
            ],
        )

        # Row 2: LAST SESSION (simples) | ENGINE ROSTER (wide)
        self._draw_last_session_tile(canvas, x1=self._CONTENT_X1, y1=self._ROW2_Y1, data=data["session"])
        self._draw_roster_tile(
            canvas,
            x1=self._CONTENT_X1 + w + gap,
            y1=self._ROW2_Y1,
            roster=data["roster"],
        )

        # Ticker strip (news/alerts agregando o state do sistema).
        self._draw_ticker_strip(canvas, data)

    def _draw_last_session_tile(self, canvas: tk.Canvas, *, x1: int, y1: int, data: dict | None) -> None:
        x2 = x1 + self._TILE_W_SIMPLE
        y2 = y1 + self._TILE_H
        if data is None:
            self.app._draw_panel(canvas, x1, y1, x2, y2, title="LAST SESSION", accent=AMBER, tag="splash")
            canvas.create_text(
                x1 + self._TILE_W_SIMPLE // 2, y1 + self._TILE_H // 2,
                anchor="center", text="NO SESSION DATA",
                font=(FONT, 9, "bold"), fill=DIM, tags="splash",
            )
            return
        ts_txt = str(data.get("timestamp", "-"))[:19].replace("T", " ")
        trades = int(data.get("n_trades") or 0)
        pnl_val = data.get("pnl")
        if isinstance(pnl_val, (int, float)):
            pnl_txt = f"{pnl_val:+.2f}"
            pnl_col = GREEN if pnl_val >= 0 else RED
        else:
            pnl_txt = "---"
            pnl_col = DIM
        engine_txt = str(data.get("engine", "-")).upper()[:10]
        self._draw_splash_tile(
            canvas,
            x1=x1, y1=y1, x2=x2, y2=y2,
            title="LAST SESSION",
            rows=[
                ("sess_ts",     "WHEN",    ts_txt,     WHITE),
                ("sess_engine", "ENGINE",  engine_txt, AMBER_B),
                ("sess_trades", "TRADES",  str(trades), WHITE),
                ("sess_pnl",    "PNL",     pnl_txt,    pnl_col),
            ],
        )

    def _draw_ticker_strip(self, canvas: tk.Canvas, data: dict) -> None:
        """Desenha a barra de ticker/news entre Row2 e a logo inferior.

        Uma linha so, agregando: ultima run + macro regime + status
        engines (alive/total). Dados vem todos do offline payload ja
        carregado em _read_offline_data, sem I/O adicional aqui.
        """
        x1, x2 = self._CONTENT_X1, self._CONTENT_X2
        y1, y2 = self._TICKER_Y1, self._TICKER_Y2

        # Frame externo com accent amber
        canvas.create_rectangle(
            x1, y1, x2, y2,
            outline=AMBER_D, fill=BG, width=1, tags="splash",
        )
        # LIVE dot + label na esquerda
        pad = 14
        cx = x1 + pad
        canvas.create_text(
            cx, (y1 + y2) // 2, anchor="w",
            text="● SYSTEM",
            font=(FONT, 8, "bold"), fill=AMBER, tags="splash",
        )
        # Pipe divider
        canvas.create_line(
            x1 + 90, y1 + 8, x1 + 90, y2 - 8,
            fill=DIM2, width=1, tags="splash",
        )

        # Compor os "news items" a partir do payload offline
        items: list[tuple[str, str, str]] = []  # (label, value, color)

        sess = data.get("session") or {}
        if sess:
            engine = str(sess.get("engine", "-")).upper()[:10]
            pnl_val = sess.get("pnl")
            if isinstance(pnl_val, (int, float)):
                pnl_txt = f"{pnl_val:+.2f}"
                pnl_col = GREEN if pnl_val >= 0 else RED
            else:
                pnl_txt = "---"
                pnl_col = DIM
            items.append(("LAST RUN", f"{engine} {pnl_txt}", pnl_col))

        # Regime macro (color vem do macro rows)
        macro_rows = data.get("macro") or {}
        regime_pair = macro_rows.get("regime")
        if regime_pair:
            regime_val, regime_col = regime_pair
            items.append(("MACRO", str(regime_val).upper(), regime_col))

        # Roster — conta engines em OK
        roster = data.get("roster") or []
        ok_n = sum(1 for r in roster if r.get("status") == "OK")
        total = len(roster)
        if total:
            items.append(("EDGE", f"{ok_n}/{total} ENGINES", GREEN if ok_n > 0 else DIM))

        # Render os items inline
        cur_x = x1 + 104
        for label, val, col in items:
            canvas.create_text(
                cur_x, (y1 + y2) // 2, anchor="w",
                text=label,
                font=(FONT, 7, "bold"), fill=DIM, tags="splash",
            )
            cur_x += len(label) * 6 + 6
            canvas.create_text(
                cur_x, (y1 + y2) // 2, anchor="w",
                text=val,
                font=(FONT, 8, "bold"), fill=col, tags="splash",
            )
            cur_x += len(val) * 7 + 14
            if cur_x < x2 - 40:
                canvas.create_text(
                    cur_x, (y1 + y2) // 2, anchor="w",
                    text="·",
                    font=(FONT, 8), fill=DIM2, tags="splash",
                )
                cur_x += 12

        # Right-edge chevrons
        canvas.create_text(
            x2 - pad, (y1 + y2) // 2, anchor="e",
            text="◂◂◂",
            font=(FONT, 8, "bold"), fill=AMBER_D, tags="splash",
        )

    def _draw_roster_tile(self, canvas: tk.Canvas, *, x1: int, y1: int, roster: list[dict]) -> None:
        x2 = x1 + self._TILE_W_WIDE
        y2 = y1 + self._TILE_H
        self.app._draw_panel(canvas, x1, y1, x2, y2, title="ENGINE ROSTER", accent=AMBER, tag="splash")

        # 2 colunas × 6 linhas. Grid interno:
        col_w = (self._TILE_W_WIDE - 2 * self._TILE_PAD) // 2
        col_x = [x1 + self._TILE_PAD, x1 + self._TILE_PAD + col_w]
        line_h = 15
        y_start = y1 + 32

        for i, entry in enumerate(roster):
            col = i % 2
            row = i // 2
            x = col_x[col]
            yy = y_start + row * line_h
            name = entry["name"]
            status = entry["status"]
            sh = entry["sharpe"]
            sh_txt = f"{sh:>5.2f}" if isinstance(sh, (int, float)) else "  ---"
            color = self._STATUS_COLORS.get(status, WHITE)
            canvas.create_text(
                x, yy, anchor="w",
                text=f"{name:<9} {status:<4} {sh_txt}",
                font=(FONT, 8, "bold"), fill=color,
                tags=("splash", f"roster-{name.lower()}"),
            )

    def _render_resize(self, _event=None) -> None:
        if self.canvas is None:
            return
        # Previous scale must be tracked across resize events — passing a
        # constant 1.0 compounds the scale on every configure tick, which
        # pushes content off-center as the window resizes.
        _, self._render_scale = self.app._apply_canvas_scale(
            self.canvas, self._design_w, self._design_h, self._render_scale,
        )
        # _apply_canvas_scale aligns bbox top-left to the viewport top-left,
        # which ignores the splash's 48/48 design padding and leaves content
        # visibly left-biased. Re-center the bbox against the live window.
        canvas = self.canvas
        bbox = canvas.bbox("all")
        if not bbox:
            return
        live_w = max(canvas.winfo_width(), 1)
        live_h = max(canvas.winfo_height(), 1)
        bbox_cx = (bbox[0] + bbox[2]) / 2
        bbox_cy = (bbox[1] + bbox[3]) / 2
        canvas.move("all", live_w / 2 - bbox_cx, live_h / 2 - bbox_cy)

    def _pulse_tick(self) -> None:
        canvas = self.canvas
        if canvas is None:
            return
        try:
            current = canvas.itemcget("prompt2", "text")
        except tk.TclError:
            return
        if current.endswith("_"):
            canvas.itemconfigure("prompt2", text=current[:-1] + " ")
        else:
            canvas.itemconfigure("prompt2", text=current[:-1] + "_")
        # Reschedule direto (sem tracking): o tick e self-perpetuating enquanto
        # canvas existir. Evita acumular after_ids no _tracked_after_ids em
        # sessoes longas — o initial call em on_enter ja foi tracked. Cleanup
        # acontece quando o canvas morre (callback early-returns via TclError).
        self.container.after(500, self._pulse_tick)

    def _draw_splash_tile(
        self,
        canvas: tk.Canvas,
        *,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        title: str,
        rows: list[tuple[str, str, str, str]],
    ) -> None:
        """Desenha um tile do splash: panel + linhas kv com tags unicas por valor.

        rows: [(row_key, label, value, color)] — row_key vira tag
        'tile-{row_key}-value' para permitir itemconfigure async.
        """
        self.app._draw_panel(
            canvas, x1, y1, x2, y2,
            title=title, accent=AMBER, tag="splash",
        )
        x_label = x1 + self._TILE_PAD
        x_value = x1 + self._TILE_PAD + 96
        y_start = y1 + 36  # abaixo do title chip
        for i, (row_key, label, value, color) in enumerate(rows):
            yy = y_start + i * self._TILE_LINE_H
            canvas.create_text(
                x_label, yy, anchor="w", text=label,
                font=(FONT, 8), fill=DIM, tags=("splash", f"tile-{row_key}-label"),
            )
            canvas.create_text(
                x_value, yy, anchor="w", text=value,
                font=(FONT, 8, "bold"), fill=color,
                tags=("splash", f"tile-{row_key}-value"),
            )

    def _draw_wordmark(self, canvas: tk.Canvas) -> None:
        """Desenha top rule + top logo + bottom rule + bottom logo.

        Prompt text "[ ENTER TO ACCESS DESK ]_" e divider removidos.
        Em vez disso, logo inferior espelha a superior (mesma escala
        e distancia do respectivo rule) pra fechar a composicao
        simetricamente.
        """
        logo_cx = self._CENTER_X

        # top rule (full width)
        canvas.create_line(
            self._RULE_X1, self._TOP_RULE_Y, self._RULE_X2, self._TOP_RULE_Y,
            fill=AMBER_D, width=1, tags="splash",
        )
        self.app._draw_aurum_logo(canvas, logo_cx, self._LOGO_Y,
                                  scale=18, tag="splash")

        # bottom rule + bottom logo (espelha a superior)
        canvas.create_line(
            self._RULE_X1, self._BOTTOM_RULE_Y, self._RULE_X2, self._BOTTOM_RULE_Y,
            fill=DIM2, width=1, tags="splash",
        )
        self.app._draw_aurum_logo(canvas, logo_cx, self._BOTTOM_LOGO_Y,
                                  scale=18, tag="splash")

