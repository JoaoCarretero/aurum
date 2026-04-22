"""SplashScreen - pilot migration of launcher._splash."""
from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from typing import Any

from core.ui.ui_palette import (
    AMBER, AMBER_B, AMBER_D, BG, BORDER, DIM, DIM2, FONT,
    GREEN, RED, WHITE,
)

from launcher_support.screens.base import Screen
from launcher_support.screens.splash_data import (
    ENGINE_ROSTER_LAYOUT,
    load_splash_cache,
    read_engine_roster,
    read_last_session,
    save_splash_cache,
)


class SplashScreen(Screen):
    # Canvas dimensions come from app._SPLASH_DESIGN_W / _H (920×640).

    # Top band + wordmark
    _CENTER_X = 460
    _TOP_RULE_Y = 30
    _BOTTOM_RULE_Y = 596
    _RULE_X1 = 48
    _RULE_X2 = 872

    _WORDMARK_BAND_Y = 46
    _WORDMARK_BAND_GAP = 78
    _LOGO_Y = 96
    _TITLE_Y = 132
    _SUBTITLE_Y = 152
    _TAGLINE_Y = 174
    _TAGLINE_DIVIDER_HALF = 170

    # Tile grid 2×3 (row 2 has wide tile in slot 2-3)
    _CONTENT_X1 = 48          # = _RULE_X1
    _CONTENT_X2 = 872         # = _RULE_X2
    _TILE_GAP = 16
    _TILE_W_SIMPLE = 264      # (824 - 2*16) / 3
    _TILE_W_WIDE = 544        # 2 simples + 1 gap
    _TILE_H = 150
    _TILE_PAD = 14
    _TILE_LINE_H = 19

    _ROW1_Y1 = 190
    _ROW1_Y2 = _ROW1_Y1 + _TILE_H       # 340
    _ROW2_Y1 = _ROW1_Y2 + _TILE_GAP     # 356
    _ROW2_Y2 = _ROW2_Y1 + _TILE_H       # 506

    _PROMPT_DIVIDER_Y = 530
    _PROMPT_Y = 552

    def __init__(self, parent: tk.Misc, app: Any, conn: Any, tagline: str):
        super().__init__(parent)
        self.app = app
        self.conn = conn
        self.tagline = tagline
        self.canvas: tk.Canvas | None = None
        self._design_w = app._SPLASH_DESIGN_W
        self._design_h = app._SPLASH_DESIGN_H
        self._cancel_event: threading.Event | None = None
        self._index_path = Path("data/index.json")
        self._cache_path = Path("data/splash_cache.json")

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
        offline = self._read_offline_data()
        self._draw_offline_tiles(canvas, offline)

        self._bind(canvas, "<Button-1>", lambda e: app._splash_on_click())
        app._bind_global_nav()
        self._after(500, self._pulse_tick)
        self._bind(canvas, "<Configure>", self._render_resize)
        self._render_resize()
        self._kick_async_fetch()

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
        cache = load_splash_cache(self._cache_path)

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
            "pulse": {
                "btc":  (cache.get("btc",  "---"), cache.get("btc_col",  DIM)),
                "eth":  (cache.get("eth",  "---"), cache.get("eth_col",  DIM)),
                "reg":  (cache.get("reg",  "---"), cache.get("reg_col",  DIM)),
                "fund": (cache.get("fund", "---"), cache.get("fund_col", DIM)),
            },
            "session": session,
            "roster": roster,
        }

    def _fetch_market_pulse(self) -> dict:
        """Bloqueante. Pode levantar. Retorna dict com chaves btc/eth/reg/fund."""
        from core.data.market_data import MarketDataFetcher
        fetcher = MarketDataFetcher(["BTCUSDT", "ETHUSDT"])
        fetcher.fetch_all()  # timeout interno 5s
        tickers = fetcher.tickers
        fund = fetcher.funding_avg()
        out: dict[str, tuple[str, str]] = {}
        for sym, key in (("BTCUSDT", "btc"), ("ETHUSDT", "eth")):
            t = tickers.get(sym)
            if not t:
                out[key] = ("---", DIM)
                continue
            price = t["price"]
            pct = t["pct"]
            arrow = "▲" if pct >= 0 else "▼"
            col = GREEN if pct >= 0 else RED
            out[key] = (f"{price:>8,.0f} {pct:+5.2f}% {arrow}", col)
        if fund is not None:
            fund_pct = fund * 100.0
            out["fund"] = (f"{fund_pct:+.3f}% /8h", WHITE)
        else:
            out["fund"] = ("---", DIM)
        out["reg"] = ("---", DIM)  # v1: sem regime macro; v1.1 pode adicionar
        return out

    def _apply_live_data(self, data: dict) -> None:
        """UI-thread callback. Atualiza valores por tag."""
        if self._cancel_event is not None and self._cancel_event.is_set():
            return
        canvas = self.canvas
        if canvas is None:
            return
        for key, (text, color) in data.items():
            tag = f"tile-{key}-value"
            try:
                canvas.itemconfigure(tag, text=text, fill=color)
            except tk.TclError:
                return  # canvas destruído

    def _draw_offline_tiles(self, canvas: tk.Canvas, data: dict) -> None:
        self._draw_wordmark(canvas)
        gap = self._TILE_GAP
        w = self._TILE_W_SIMPLE

        # Row 1: STATUS | RISK | MARKET PULSE
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
            title="MARKET PULSE",
            rows=[
                ("btc",  "BTC",  *data["pulse"]["btc"]),
                ("eth",  "ETH",  *data["pulse"]["eth"]),
                ("reg",  "REG",  *data["pulse"]["reg"]),
                ("fund", "FUND", *data["pulse"]["fund"]),
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

        # Prompt
        canvas.create_line(
            self._RULE_X1, self._PROMPT_DIVIDER_Y, self._RULE_X2, self._PROMPT_DIVIDER_Y,
            fill=DIM2, width=1, tags="splash",
        )
        canvas.create_text(
            self._CENTER_X, self._PROMPT_Y,
            anchor="center", text="[ ENTER TO ACCESS DESK ]_",
            font=(FONT, 11, "bold"), fill=AMBER_B, tags=("splash", "prompt2"),
        )

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
            sh_txt = f"{sh:>5.2f}" if isinstance(sh, (int, float)) else "  —  "
            canvas.create_text(
                x, yy, anchor="w",
                text=f"{name:<8} {status}  {sh_txt}",
                font=(FONT, 8, "bold"), fill=WHITE, tags=("splash", f"roster-{name.lower()}"),
            )

    def _render_resize(self, _event=None) -> None:
        if self.canvas is None:
            return
        self.app._apply_canvas_scale(
            self.canvas, self._design_w, self._design_h, 1.0,
        )

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
        self._after(500, self._pulse_tick)

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
        logo_cx, logo_cy = self._CENTER_X, self._LOGO_Y
        band_gap = self._WORDMARK_BAND_GAP

        # top rule (full width)
        canvas.create_line(
            self._RULE_X1, self._TOP_RULE_Y, self._RULE_X2, self._TOP_RULE_Y,
            fill=AMBER_D, width=1, tags="splash",
        )
        # AURUM FINANCE wordmark band
        canvas.create_line(
            self._RULE_X1, self._WORDMARK_BAND_Y,
            self._CENTER_X - band_gap, self._WORDMARK_BAND_Y,
            fill=AMBER_D, width=1, tags="splash",
        )
        canvas.create_line(
            self._CENTER_X + band_gap, self._WORDMARK_BAND_Y,
            self._RULE_X2, self._WORDMARK_BAND_Y,
            fill=AMBER_D, width=1, tags="splash",
        )
        canvas.create_text(
            self._CENTER_X, self._WORDMARK_BAND_Y,
            anchor="center", text="AURUM FINANCE",
            font=(FONT, 7, "bold"), fill=AMBER, tags="splash",
        )

        self.app._draw_aurum_logo(canvas, logo_cx, logo_cy, scale=18, tag="splash")

        canvas.create_text(
            logo_cx, self._TITLE_Y, anchor="center", text="OPERATOR DESK",
            font=(FONT, 18, "bold"), fill=WHITE, tags="splash",
        )
        canvas.create_text(
            logo_cx, self._SUBTITLE_Y, anchor="center",
            text="Quant operations console",
            font=(FONT, 9), fill=DIM2, tags="splash",
        )
        canvas.create_line(
            logo_cx - self._TAGLINE_DIVIDER_HALF, self._TAGLINE_Y - 8,
            logo_cx + self._TAGLINE_DIVIDER_HALF, self._TAGLINE_Y - 8,
            fill=BORDER, width=1, tags="splash",
        )
        canvas.create_text(
            logo_cx, self._TAGLINE_Y, anchor="center", text=self.tagline,
            font=(FONT, 8), fill=DIM, tags="splash",
        )

        # bottom rule
        canvas.create_line(
            self._RULE_X1, self._BOTTOM_RULE_Y, self._RULE_X2, self._BOTTOM_RULE_Y,
            fill=DIM2, width=1, tags="splash",
        )

    def _kick_async_fetch(self) -> None:
        """Stub: async fetch lands in Task 9. Por enquanto no-op."""
        pass
