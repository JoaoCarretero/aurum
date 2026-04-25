"""Lanca launcher.py via pythonw.exe (mesmo comando do atalho)
e screenshota apos 6s. Prova se pythonw faz diferenca."""
import ctypes
import subprocess
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
pythonw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
launcher = ROOT / "launcher.py"
shot = ROOT / "tools" / "diagnostics" / "pythonw_titlebar.png"

print(f"pythonw: {pythonw} (exists={pythonw.exists()})")
print(f"launcher: {launcher} (exists={launcher.exists()})")

if not pythonw.exists():
    # fallback pra pythonw do sistema
    pythonw = "pythonw"

print(f"Lancando: {pythonw} {launcher}")
proc = subprocess.Popen([str(pythonw), "launcher.py"], cwd=str(ROOT))
print(f"PID {proc.pid}")

user32 = ctypes.windll.user32
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.SetForegroundWindow.argtypes = [wintypes.HWND]


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]

try:
    hwnd = 0
    deadline = time.time() + 30
    while time.time() < deadline:
        hwnd = user32.FindWindowW(None, "AURUM Terminal")
        if hwnd:
            elapsed = 30 - (deadline - time.time())
            print(f"AURUM Terminal apareceu em {elapsed:.1f}s -> 0x{hwnd:x}")
            break
        time.sleep(0.5)

    if not hwnd:
        print("ERRO: janela nao encontrada em 30s")
    else:
        time.sleep(2.0)  # pro DWM aplicar
        rect = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        print(f"Rect: ({rect.left},{rect.top},{rect.right},{rect.bottom})")
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.5)

        from PIL import ImageGrab
        img = ImageGrab.grab(bbox=(rect.left - 4, rect.top - 4,
                                   rect.right + 4, rect.top + 80))
        img.save(str(shot))
        print(f"Screenshot -> {shot}")
finally:
    print(f"Killing PID {proc.pid}")
    proc.kill()
    try:
        proc.wait(timeout=3)
    except Exception:
        pass
