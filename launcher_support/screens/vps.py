"""VpsScreen — single dashboard for VPS infra: tunnel, cockpit, host, keys.

Operator-facing VPS pane. Surface all the moving parts that keep the
remote cockpit alive in one place so the operator can diagnose
"engines não aparecem" without bouncing between SSH terminals and log
files. Read-only cards live-refresh every 5s; the LOG TAIL card
streams the most recent ``data/.cockpit_cache/tunnel.log`` entries.

Bloomberg-terminal aesthetic mirrors `engines_live_view`: status
header, two-column card grid (TUNNEL / COCKPIT API / VPS HOST /
KEYS section), log tail at the bottom. Each card has accent stripe +
H2 heading + row list (label / value with semantic color).

Acesso pelo botao 🖧 VPS no header. CONFIG (⚙) ao lado abre o router
de settings gerais (api keys, telegram, risk params, etc).
"""
from __future__ import annotations

import json
import time
import tkinter as tk
import tkinter.scrolledtext as scrolledtext
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from core.ui.ui_palette import (
    AMBER, AMBER_B, AMBER_D, BG, BG2, BG3, BORDER, CYAN, DIM, DIM2,
    FONT, GREEN, PANEL, RED, WHITE,
)
from launcher_support.screens.base import Screen


_ROOT = Path(__file__).resolve().parents[2]
_TUNNEL_LOG = _ROOT / "data" / ".cockpit_cache" / "tunnel.log"
_REFRESH_TICK_MS = 5000


class VpsScreen(Screen):
    """Dashboard de infra VPS: tunnel SSH, cockpit API, host, keys section.

    Diagnostico fast-path: sem precisar SSH manual nem tail de log,
    operador ve em uma tela so se a infra ta viva. Reduz tempo de
    detecção de "tunnel down" / "key wipe" / "VPS unreachable".
    """

    def __init__(self, parent: tk.Misc, app: Any):
        super().__init__(parent)
        self.app = app
        # Cards labels/values — atualizados via _refresh_cards. Chaves sao
        # ("card-id", "row-label") -> tk.Label do valor, pra update_in_place
        # sem destruir/recriar widgets a cada tick.
        self._row_values: dict[tuple[str, str], tk.Label] = {}
        self._log_box: tk.Text | None = None
        # Single thread pool pra fetches que possam bloquear (cockpit
        # health, ssh ping). 2 workers e suficiente — fetches sao raros
        # (5s tick) e curtos.
        self._pool = ThreadPoolExecutor(max_workers=2,
                                        thread_name_prefix="vps-screen-")
        self._latest_metrics: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Build (called once)
    # ------------------------------------------------------------------
    def build(self) -> None:
        outer = tk.Frame(self.container, bg=BG)
        outer.pack(fill="both", expand=True, padx=20, pady=14)

        # HEADER --------------------------------------------------------
        head = tk.Frame(outer, bg=BG)
        head.pack(fill="x")
        strip = tk.Frame(head, bg=BG)
        strip.pack(fill="x")
        tk.Frame(strip, bg=AMBER, width=4, height=22).pack(side="left", padx=(0, 8))
        title_wrap = tk.Frame(strip, bg=BG)
        title_wrap.pack(side="left", fill="x", expand=True)
        tk.Label(title_wrap, text="VPS · INFRA",
                 font=(FONT, 11, "bold"), fg=AMBER, bg=BG, anchor="w"
                 ).pack(anchor="w")
        tk.Label(title_wrap,
                 text="Tunnel SSH · Cockpit API · Host · keys.json — "
                      "leitura ao vivo, refresh 5s",
                 font=(FONT, 7), fg=DIM, bg=BG, anchor="w"
                 ).pack(anchor="w", pady=(3, 0))
        tk.Frame(outer, bg=DIM2, height=1).pack(fill="x", pady=(8, 8))

        # CARDS GRID 2x2 ------------------------------------------------
        grid = tk.Frame(outer, bg=BG)
        grid.pack(fill="x")
        for col in range(2):
            grid.grid_columnconfigure(col, weight=1, uniform="cards")

        self._build_tunnel_card(grid, row=0, col=0)
        self._build_cockpit_card(grid, row=0, col=1)
        self._build_vps_card(grid, row=1, col=0)
        self._build_keys_card(grid, row=1, col=1)

        # LOG TAIL ------------------------------------------------------
        tk.Frame(outer, bg=BORDER, height=1).pack(fill="x", pady=(10, 6))
        log_head = tk.Frame(outer, bg=BG)
        log_head.pack(fill="x")
        tk.Label(log_head, text="TUNNEL LOG TAIL",
                 font=(FONT, 8, "bold"), fg=AMBER_D, bg=BG, anchor="w"
                 ).pack(side="left")
        tk.Label(log_head,
                 text=f"  ·  {_TUNNEL_LOG.name}  ·  last 30 lines",
                 font=(FONT, 7), fg=DIM, bg=BG, anchor="w"
                 ).pack(side="left")
        log_box = scrolledtext.ScrolledText(
            outer, bg=BG2, fg=WHITE, font=(FONT, 7),
            height=12, wrap="none", borderwidth=0,
            highlightbackground=BORDER, highlightthickness=1,
        )
        log_box.pack(fill="both", expand=True, pady=(4, 0))
        log_box.configure(state="disabled")
        # Tags pra colorir niveis de log
        log_box.tag_configure("err", foreground=RED)
        log_box.tag_configure("warn", foreground=AMBER_B)
        log_box.tag_configure("ok", foreground=GREEN)
        log_box.tag_configure("dim", foreground=DIM)
        self._log_box = log_box

    # ------------------------------------------------------------------
    # Card builders
    # ------------------------------------------------------------------
    def _build_card_shell(self, parent: tk.Widget, *, row: int, col: int,
                          accent: str, title: str) -> tk.Frame:
        wrap = tk.Frame(parent, bg=PANEL,
                        highlightbackground=BORDER, highlightthickness=1)
        # padx=(left, right): alterna pra colar as bordas no centro do grid
        padx = (0, 4) if col == 0 else (4, 0)
        wrap.grid(row=row, column=col, sticky="nsew", padx=padx, pady=4)
        tk.Frame(wrap, bg=accent, width=3).pack(side="left", fill="y")
        body = tk.Frame(wrap, bg=PANEL)
        body.pack(side="left", fill="both", expand=True, padx=8, pady=6)
        tk.Label(body, text=title, font=(FONT, 8, "bold"),
                 fg=accent, bg=PANEL, anchor="w").pack(anchor="w")
        tk.Frame(body, bg=BORDER, height=1).pack(fill="x", pady=(3, 6))
        return body

    def _add_row(self, body: tk.Frame, *, card_id: str, label: str,
                 initial: str = "—", color: str = DIM2) -> None:
        row = tk.Frame(body, bg=PANEL)
        row.pack(fill="x", pady=0)
        tk.Label(row, text=label, font=(FONT, 7),
                 fg=DIM, bg=PANEL, anchor="w", width=14).pack(side="left")
        val = tk.Label(row, text=initial, font=(FONT, 7, "bold"),
                       fg=color, bg=PANEL, anchor="w")
        val.pack(side="left", fill="x", expand=True)
        self._row_values[(card_id, label)] = val

    def _build_tunnel_card(self, parent: tk.Widget, *, row: int, col: int) -> None:
        body = self._build_card_shell(parent, row=row, col=col,
                                      accent=AMBER, title="TUNNEL SSH")
        self._add_row(body, card_id="tunnel", label="status")
        self._add_row(body, card_id="tunnel", label="port")
        self._add_row(body, card_id="tunnel", label="pid")
        self._add_row(body, card_id="tunnel", label="last_error")
        # Action row
        actions = tk.Frame(body, bg=PANEL)
        actions.pack(fill="x", pady=(6, 0))
        self._mk_action_btn(actions, "OPEN LOG", self._open_tunnel_log)

    def _build_cockpit_card(self, parent: tk.Widget, *, row: int, col: int) -> None:
        body = self._build_card_shell(parent, row=row, col=col,
                                      accent=CYAN, title="COCKPIT API")
        self._add_row(body, card_id="cockpit", label="endpoint")
        self._add_row(body, card_id="cockpit", label="health")
        self._add_row(body, card_id="cockpit", label="latency")
        self._add_row(body, card_id="cockpit", label="runs total")
        self._add_row(body, card_id="cockpit", label="running")

    def _build_vps_card(self, parent: tk.Widget, *, row: int, col: int) -> None:
        body = self._build_card_shell(parent, row=row, col=col,
                                      accent=GREEN, title="VPS")
        self._add_row(body, card_id="vps", label="host")
        self._add_row(body, card_id="vps", label="user")
        self._add_row(body, card_id="vps", label="ssh port")
        self._add_row(body, card_id="vps", label="reachable")
        self._add_row(body, card_id="vps", label="services")

    def _build_keys_card(self, parent: tk.Widget, *, row: int, col: int) -> None:
        body = self._build_card_shell(parent, row=row, col=col,
                                      accent=AMBER_B, title="KEYS.JSON")
        self._add_row(body, card_id="keys", label="path")
        self._add_row(body, card_id="keys", label="integrity")
        self._add_row(body, card_id="keys", label="binance")
        self._add_row(body, card_id="keys", label="telegram")
        self._add_row(body, card_id="keys", label="cockpit api")
        self._add_row(body, card_id="keys", label="vps_ssh")

    def _mk_action_btn(self, parent: tk.Widget, label: str, cmd) -> tk.Label:
        btn = tk.Label(parent, text=f" {label} ",
                       font=(FONT, 7, "bold"),
                       fg=BG, bg=AMBER, padx=6, pady=2,
                       cursor="hand2")
        btn.pack(side="left", padx=(0, 4))
        btn.bind("<Button-1>", lambda _e: cmd())
        btn.bind("<Enter>", lambda _e: btn.configure(bg=AMBER_B))
        btn.bind("<Leave>", lambda _e: btn.configure(bg=AMBER))
        return btn

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def on_enter(self, **kwargs: Any) -> None:
        del kwargs
        app = self.app
        if hasattr(app, "h_path"):
            app.h_path.configure(text="> VPS · INFRA")
        if hasattr(app, "h_stat"):
            app.h_stat.configure(text="LIVE", fg=AMBER_D)
        if hasattr(app, "f_lbl"):
            app.f_lbl.configure(
                text="ESC voltar  |  refresh 5s  |  click OPEN LOG pra tunnel.log",
            )
        if hasattr(app, "_kb"):
            app._kb("<Escape>", lambda: app._menu("main"))
        self._refresh_all()
        self._after(_REFRESH_TICK_MS, self._tick)

    def on_exit(self) -> None:
        super().on_exit()
        # ThreadPool persiste — daemon threads, custo zero. Reusa em
        # next on_enter sem setup overhead.

    def _tick(self) -> None:
        self._refresh_all()
        self._after(_REFRESH_TICK_MS, self._tick)

    # ------------------------------------------------------------------
    # Refresh — collect + paint
    # ------------------------------------------------------------------
    def _refresh_all(self) -> None:
        # Le keys.json uma vez por tick e compartilha entre cards (3
        # consumers — keys, vps, cockpit fetch). Sem isso cada card lia
        # do disco — pequeno mas evitavel.
        try:
            self._cached_keys = self._read_keys_json()
        except Exception:
            self._cached_keys = {}
        # Sync (cheap) data: tunnel status, keys.json, log tail
        self._refresh_tunnel_card()
        self._refresh_keys_card()
        self._refresh_vps_card_static()
        self._refresh_log_tail()
        # Async (network) data: cockpit health
        self._pool.submit(self._fetch_cockpit_async)

    def _set(self, card: str, label: str, text: str, color: str = WHITE) -> None:
        w = self._row_values.get((card, label))
        if w is None:
            return
        try:
            w.configure(text=text, fg=color)
        except Exception:
            pass

    # --- TUNNEL --------------------------------------------------------
    def _refresh_tunnel_card(self) -> None:
        try:
            from launcher_support.tunnel_registry import (
                get_tunnel_manager, get_tunnel_boot_error,
            )
            tm = get_tunnel_manager()
            boot_err = get_tunnel_boot_error()
        except Exception:
            tm = None
            boot_err = None

        if tm is None:
            self._set("tunnel", "status",
                     "CFG ERR" if boot_err else "—",
                     RED if boot_err else DIM2)
            self._set("tunnel", "port", "—", DIM2)
            self._set("tunnel", "pid", "—", DIM2)
            self._set("tunnel", "last_error",
                     str(boot_err)[:60] if boot_err else "—",
                     RED if boot_err else DIM2)
            return

        status_obj = getattr(tm, "status", None)
        status_val = (str(status_obj.value).upper() if status_obj is not None
                      else "—")
        color_map = {
            "UP": GREEN, "STARTING": AMBER_B, "RECONNECTING": AMBER_B,
            "OFFLINE": RED, "STOPPING": DIM2, "IDLE": DIM2, "DISABLED": DIM2,
        }
        self._set("tunnel", "status", status_val,
                 color_map.get(status_val, DIM2))

        # port from config
        cfg = getattr(tm, "_config", None)
        port = str(cfg.local_port) if cfg is not None else "—"
        self._set("tunnel", "port", port, WHITE)

        # pid from running ssh proc
        proc = getattr(tm, "_proc", None)
        pid = str(getattr(proc, "pid", "—")) if proc is not None else "—"
        self._set("tunnel", "pid", pid, WHITE if pid != "—" else DIM2)

        last_err = getattr(tm, "last_error", None)
        if last_err:
            self._set("tunnel", "last_error", str(last_err)[:60], RED)
        else:
            self._set("tunnel", "last_error", "—", GREEN if status_val == "UP" else DIM2)

    def _open_tunnel_log(self) -> None:
        try:
            import os
            os.startfile(str(_TUNNEL_LOG))
        except Exception:
            pass

    # --- VPS (static config from keys.json) ----------------------------
    def _refresh_vps_card_static(self) -> None:
        data = getattr(self, "_cached_keys", None) or {}
        vps = (data or {}).get("vps_ssh") or {}
        host = str(vps.get("host") or "—")
        user = str(vps.get("user") or "—")
        ssh_port = str(vps.get("ssh_port") or "—")
        is_placeholder = "cole_aqui" in host.lower() or "<paste" in host.lower()
        host_color = RED if is_placeholder else (WHITE if host != "—" else DIM2)
        self._set("vps", "host", host, host_color)
        self._set("vps", "user", user, WHITE if user != "—" else DIM2)
        self._set("vps", "ssh port", ssh_port, WHITE if ssh_port != "—" else DIM2)
        # `reachable` e `services` vem do cockpit fetch async.

    # --- COCKPIT (async) -----------------------------------------------
    def _fetch_cockpit_async(self) -> None:
        """Worker thread: ping /v1/runs e mede latency."""
        endpoint = "—"
        health = "—"
        latency_ms: float | None = None
        runs_total: int | None = None
        running_count: int | None = None
        try:
            import urllib.request
            keys = self._read_keys_json()
            cockpit = (keys or {}).get("cockpit_api") or {}
            base = str(cockpit.get("base_url") or "http://127.0.0.1:8787")
            token = str(cockpit.get("read_token") or "")
            timeout = float(cockpit.get("timeout_sec") or 5.0)
            endpoint = base
            req = urllib.request.Request(
                f"{base}/v1/runs?limit=300",
                headers={"Authorization": f"Bearer {token}"},
            )
            t0 = time.monotonic()
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read())
            latency_ms = (time.monotonic() - t0) * 1000.0
            if isinstance(payload, list):
                runs_total = len(payload)
                running_count = sum(
                    1 for r in payload
                    if isinstance(r, dict)
                    and str(r.get("status") or "").lower() == "running"
                )
            health = "UP"
        except Exception as exc:  # noqa: BLE001
            health = f"DOWN ({type(exc).__name__})"
        # Marshal de volta pro main thread
        metrics = dict(
            endpoint=endpoint, health=health, latency_ms=latency_ms,
            runs_total=runs_total, running_count=running_count,
        )
        try:
            self.container.after(0, lambda: self._apply_cockpit_metrics(metrics))
        except Exception:
            pass

    def _apply_cockpit_metrics(self, m: dict) -> None:
        self._set("cockpit", "endpoint", m["endpoint"][:48], WHITE)
        is_up = m["health"] == "UP"
        self._set("cockpit", "health", m["health"], GREEN if is_up else RED)
        if m["latency_ms"] is not None:
            self._set("cockpit", "latency", f"{m['latency_ms']:.0f}ms",
                     GREEN if m["latency_ms"] < 500 else AMBER_B)
        else:
            self._set("cockpit", "latency", "—", DIM2)
        if m["runs_total"] is not None:
            self._set("cockpit", "runs total", str(m["runs_total"]), WHITE)
        else:
            self._set("cockpit", "runs total", "—", DIM2)
        if m["running_count"] is not None:
            self._set("cockpit", "running", str(m["running_count"]),
                     GREEN if m["running_count"] > 0 else DIM2)
        else:
            self._set("cockpit", "running", "—", DIM2)
        # Cockpit health implica VPS reachable (cockpit_api roda no VPS).
        self._set("vps", "reachable", "yes" if is_up else "no",
                 GREEN if is_up else RED)
        # Services count = runs unicas via systemctl seria mais correto, mas
        # como proxy usamos count de engines distintos com runs running.
        if m["running_count"] is not None and is_up:
            self._set("vps", "services", f"{m['running_count']} runners",
                     GREEN if m["running_count"] > 0 else DIM2)
        else:
            self._set("vps", "services", "—", DIM2)

    # --- KEYS.JSON -----------------------------------------------------
    def _read_keys_json(self) -> dict:
        path = _ROOT / "config" / "keys.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _refresh_keys_card(self) -> None:
        path = _ROOT / "config" / "keys.json"
        self._set("keys", "path", str(path).replace(str(_ROOT), "."),
                 WHITE if path.exists() else RED)
        if not path.exists():
            self._set("keys", "integrity", "MISSING", RED)
            for k in ("binance", "telegram", "cockpit api", "vps_ssh"):
                self._set("keys", k, "—", DIM2)
            return
        data = getattr(self, "_cached_keys", None) or self._read_keys_json()
        # Per-section status — feito inline pra evitar spawn de subprocess
        # (verify_keys_intact.py custava ~500ms-1s no Windows a cada 5s
        # tick e travava Tk main loop). Mesma logica de detection
        # (cole_aqui / <paste / <your) feita aqui.
        b_state = self._key_status((data or {}).get("binance") or {})
        t_state = self._key_status((data or {}).get("telegram") or {})
        c_state = self._key_status(
            (data or {}).get("cockpit_api") or {},
            expected_keys=("read_token", "admin_token"),
        )
        v_state = self._key_status(
            (data or {}).get("vps_ssh") or {},
            expected_keys=("host", "key_path"),
        )
        self._set("keys", "binance", b_state[0], b_state[1])
        self._set("keys", "telegram", t_state[0], t_state[1])
        self._set("keys", "cockpit api", c_state[0], c_state[1])
        self._set("keys", "vps_ssh", v_state[0], v_state[1])
        # Integrity = OK se todas as 4 secoes principais nao tem
        # placeholder e tem expected keys.
        any_placeholder = any(
            "placeholder" in s[0]
            for s in (b_state, t_state, c_state, v_state)
        )
        any_missing = any(
            "missing" in s[0]
            for s in (b_state, t_state, c_state, v_state)
        )
        if any_placeholder:
            self._set("keys", "integrity", "PLACEHOLDER", RED)
        elif any_missing:
            self._set("keys", "integrity", "PARTIAL", AMBER_B)
        else:
            self._set("keys", "integrity", "OK", GREEN)

    def _key_status(self, section: dict,
                    expected_keys: tuple[str, ...] = ()) -> tuple[str, str]:
        if not section:
            return ("missing", DIM2)
        # Detect placeholder values (cole_aqui_*, <paste, etc) — recursivo
        # pra subdicts (vps_ssh tem keypath aninhado, etc).
        def _has_placeholder(obj) -> bool:
            if isinstance(obj, str):
                low = obj.lower()
                return any(m in low for m in ("cole_aqui", "<paste", "<your"))
            if isinstance(obj, dict):
                return any(_has_placeholder(v) for v in obj.values())
            if isinstance(obj, list):
                return any(_has_placeholder(v) for v in obj)
            return False
        if _has_placeholder(section):
            return ("placeholder", RED)
        if expected_keys:
            missing = [k for k in expected_keys if not section.get(k)]
            if missing:
                return (f"missing {','.join(missing)}", AMBER_B)
        return ("configured", GREEN)

    # --- LOG TAIL ------------------------------------------------------
    def _refresh_log_tail(self) -> None:
        if self._log_box is None:
            return
        lines = self._read_log_tail(_TUNNEL_LOG, n=30)
        try:
            self._log_box.configure(state="normal")
            self._log_box.delete("1.0", "end")
            for ln in lines:
                tag = self._classify_log(ln)
                self._log_box.insert("end", ln + "\n", tag)
            self._log_box.configure(state="disabled")
            self._log_box.see("end")
        except Exception:
            pass

    @staticmethod
    def _read_log_tail(path: Path, *, n: int = 30,
                       max_bytes: int = 16384) -> list[str]:
        try:
            size = path.stat().st_size
        except OSError:
            return []
        try:
            with path.open("rb") as f:
                if size > max_bytes:
                    f.seek(size - max_bytes)
                    f.readline()
                chunk = f.read().decode("utf-8", errors="replace")
        except OSError:
            return []
        return [ln for ln in chunk.splitlines()[-n:] if ln.strip()]

    @staticmethod
    def _classify_log(line: str) -> str:
        low = line.lower()
        if "bad permissions" in low or "denied" in low or "fatal" in low:
            return "err"
        if "error" in low or "failed" in low or "refused" in low:
            return "err"
        if "warning" in low or "reconnect" in low or "retry" in low:
            return "warn"
        if "ssh2_msg" in low or "[ok]" in low or "established" in low:
            return "ok"
        if low.startswith("debug") or "ssh-keygen" in low:
            return "dim"
        return "dim"
