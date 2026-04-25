"""Probe diagnostico — investiga porque DwmSetWindowAttribute nao
pinta a title bar do launcher AURUM.

Roda standalone com `python tools/diagnostics/titlebar_probe.py`.
Imprime:
  - Versao do Windows
  - HWND retornado por winfo_id() vs wm_frame() vs GetParent()
  - HRESULT de cada DwmSetWindowAttribute
  - Aparencia visual: abre uma janela tk simples e tenta pintar
    a title bar com BG=#2A2A2A. Se a janela aparecer com title
    bar dark, DWM funciona neste sistema. Se aparecer branca,
    o problema nao eh launcher-especifico.
"""
from __future__ import annotations

import ctypes
import sys
import tkinter as tk
from ctypes import wintypes


BG = "#2A2A2A"
WHITE = "#D6C99A"
BORDER = "#565656"


def hex_to_colorref(hex_str: str) -> int:
    h = hex_str.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (b << 16) | (g << 8) | r


def get_windows_build() -> str:
    try:
        ver = sys.getwindowsversion()
        return f"major={ver.major} minor={ver.minor} build={ver.build}"
    except Exception as e:
        return f"unknown ({e})"


def probe(root: tk.Tk) -> None:
    print("=" * 60)
    print("TITLEBAR PROBE — AURUM")
    print("=" * 60)
    print(f"Python: {sys.version}")
    print(f"Tk version: {tk.TkVersion}  Tcl: {tk.TclVersion}")
    print(f"Windows: {get_windows_build()}")
    print(f"Platform: {sys.platform}")
    print(f"Architecture: {ctypes.sizeof(ctypes.c_void_p) * 8}-bit")
    print("-" * 60)

    # Forca window a aparecer pra HWND existir.
    root.update()

    winfo_hwnd = root.winfo_id()
    print(f"winfo_id():           {winfo_hwnd}  (0x{winfo_hwnd:x})")

    try:
        wm_frame_str = root.wm_frame()
        print(f"wm_frame() raw:       {wm_frame_str!r}")
        wm_frame_hwnd = int(wm_frame_str, 16) if isinstance(wm_frame_str, str) else int(wm_frame_str)
        print(f"wm_frame() parsed:    {wm_frame_hwnd}  (0x{wm_frame_hwnd:x})")
    except Exception as e:
        wm_frame_hwnd = 0
        print(f"wm_frame() FAILED:    {e}")

    user32 = ctypes.windll.user32
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND
    try:
        parent_hwnd = user32.GetParent(wintypes.HWND(winfo_hwnd))
        parent_hwnd = parent_hwnd if parent_hwnd is not None else 0
        print(f"GetParent(winfo_id()): {parent_hwnd}  (0x{parent_hwnd:x})")
    except Exception as e:
        parent_hwnd = 0
        print(f"GetParent FAILED:     {e}")

    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    try:
        # GA_ROOT = 2
        root_hwnd = user32.GetAncestor(wintypes.HWND(winfo_hwnd), 2)
        root_hwnd = root_hwnd if root_hwnd is not None else 0
        print(f"GetAncestor(GA_ROOT):  {root_hwnd}  (0x{root_hwnd:x})")
    except Exception as e:
        root_hwnd = 0
        print(f"GetAncestor FAILED:   {e}")

    # GetWindowText pra confirmar qual janela é qual
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    for name, h in [
        ("winfo_id", winfo_hwnd),
        ("wm_frame", wm_frame_hwnd),
        ("GetParent(winfo)", parent_hwnd),
        ("GetAncestor", root_hwnd),
    ]:
        if not h:
            continue
        buf = ctypes.create_unicode_buffer(256)
        try:
            user32.GetWindowTextW(wintypes.HWND(h), buf, 256)
            print(f"  {name} title: {buf.value!r}")
        except Exception as e:
            print(f"  {name} title FAILED: {e}")

    print("-" * 60)
    print("APLICANDO DWM ATTRIBUTES")
    print("-" * 60)

    dwm = ctypes.windll.dwmapi
    dwm.DwmSetWindowAttribute.argtypes = [
        wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD
    ]
    dwm.DwmSetWindowAttribute.restype = ctypes.c_long  # HRESULT

    # Tenta cada HWND candidato pra ver qual responde
    candidates = [
        ("winfo_id", winfo_hwnd),
        ("wm_frame", wm_frame_hwnd),
        ("GetParent(winfo)", parent_hwnd),
        ("GetAncestor(GA_ROOT)", root_hwnd),
    ]

    for label, hwnd_int in candidates:
        if not hwnd_int:
            print(f"  [{label}] HWND vazio — pula")
            continue
        hwnd = wintypes.HWND(hwnd_int)
        print(f"\n  [{label}] HWND=0x{hwnd_int:x}")

        # DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        dark = ctypes.c_int(1)
        hr = dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark), ctypes.sizeof(dark))
        print(f"    DWMWA_USE_IMMERSIVE_DARK_MODE (20) -> HRESULT 0x{hr & 0xFFFFFFFF:08x}")

        # DWMWA_CAPTION_COLOR = 35  (Win11 22000+)
        color = ctypes.c_uint32(hex_to_colorref(BG))
        hr = dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(color), ctypes.sizeof(color))
        print(f"    DWMWA_CAPTION_COLOR     (35) -> HRESULT 0x{hr & 0xFFFFFFFF:08x}  color=#{BG[1:]}")

        # DWMWA_TEXT_COLOR = 36
        color = ctypes.c_uint32(hex_to_colorref(WHITE))
        hr = dwm.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(color), ctypes.sizeof(color))
        print(f"    DWMWA_TEXT_COLOR        (36) -> HRESULT 0x{hr & 0xFFFFFFFF:08x}  color=#{WHITE[1:]}")

        # DWMWA_BORDER_COLOR = 34
        color = ctypes.c_uint32(hex_to_colorref(BORDER))
        hr = dwm.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(color), ctypes.sizeof(color))
        print(f"    DWMWA_BORDER_COLOR      (34) -> HRESULT 0x{hr & 0xFFFFFFFF:08x}  color=#{BORDER[1:]}")

        # Force redraw
        SWP_FLAGS = 0x0002 | 0x0001 | 0x0004 | 0x0020
        user32.SetWindowPos.argtypes = [
            wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, wintypes.UINT,
        ]
        user32.SetWindowPos.restype = wintypes.BOOL
        ok = user32.SetWindowPos(hwnd, wintypes.HWND(0), 0, 0, 0, 0, SWP_FLAGS)
        print(f"    SetWindowPos(SWP_FRAMECHANGED) -> {'OK' if ok else 'FAIL'}")

    print("-" * 60)
    print("Janela tk aberta — confira visualmente:")
    print("  - Title bar deveria ficar charcoal (#2A2A2A) com texto cream")
    print("  - Se algum candidato funcionou, o HRESULT acima foi 0x00000000")
    print("  - Feche a janela (X) pra sair")
    print("=" * 60)


def main() -> None:
    # Escreve log em arquivo pra escapar buffering / pythonw.
    import io
    log_path = "tools/diagnostics/titlebar_probe.log"
    log_buf = io.StringIO()
    real_stdout = sys.stdout
    sys.stdout = log_buf

    try:
        root = tk.Tk()
        root.title("AURUM TITLEBAR PROBE")
        root.geometry("520x180")
        root.configure(bg=BG)
        tk.Label(
            root,
            text="Olha a title bar acima.\n\nDeve ficar charcoal/cream se DWM funciona.",
            font=("Consolas", 10),
            bg=BG,
            fg=WHITE,
            justify="left",
            padx=20,
            pady=20,
        ).pack(fill="both", expand=True)

        probe(root)

        # Spin event loop por 2s pra DWM aplicar / repintar
        import time
        t0 = time.time()
        while time.time() - t0 < 2.0:
            root.update()
            time.sleep(0.05)

        # Captura screenshot da janela
        try:
            from PIL import ImageGrab
            x = root.winfo_rootx() - 8
            y = root.winfo_rooty() - 40
            w = root.winfo_width() + 16
            h = root.winfo_height() + 48
            img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
            img.save("tools/diagnostics/titlebar_probe.png")
            print(f"\nScreenshot salvo em tools/diagnostics/titlebar_probe.png")
            print(f"  bbox: ({x},{y},{x+w},{y+h})  size: {w}x{h}")
        except Exception as e:
            print(f"\nScreenshot FAILED: {e}")

        root.destroy()
    finally:
        sys.stdout = real_stdout
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(log_buf.getvalue())
        print(f"Log -> {log_path}")


if __name__ == "__main__":
    main()
