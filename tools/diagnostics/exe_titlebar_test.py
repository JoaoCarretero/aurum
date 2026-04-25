"""Roda dist/AURUM.exe e screenshota a title bar.
Mostra definitivo se o exe rebuildado tem o fix DWM."""
import ctypes
import subprocess
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
exe = ROOT / "dist" / "AURUM.exe"
shot = ROOT / "tools" / "diagnostics" / "exe_titlebar.png"

user32 = ctypes.windll.user32
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]


def main() -> None:
    print(f"Lancando {exe}")
    proc = subprocess.Popen([str(exe)], cwd=str(ROOT))
    print(f"PID {proc.pid}")

    try:
        # poll por ate 60s
        hwnd = 0
        deadline = time.time() + 60
        while time.time() < deadline:
            hwnd = user32.FindWindowW(None, "AURUM Terminal")
            if hwnd:
                elapsed = 60 - (deadline - time.time())
                print(f"Janela apareceu apos {elapsed:.1f}s -> 0x{hwnd:x}")
                break
            time.sleep(0.5)

        if not hwnd:
            print("Nao achei 'AURUM Terminal' em 60s. Listando TODAS top-level visiveis com 'aurum' no titulo:")
            EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

            def cb(h, _):
                if not user32.IsWindowVisible(h):
                    return True
                buf = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(h, buf, 256)
                title = buf.value
                if "aurum" in title.lower() or "AURUM" in title:
                    pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
                    print(f"  HWND=0x{h:x} pid={pid.value} title={title!r}")
                return True

            user32.EnumWindows(EnumProc(cb), 0)
            return

        # da uma respirada pro DWM aplicar (after_idle + after(200))
        time.sleep(2.0)

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
        print(f"Kill PID {proc.pid}")
        proc.kill()
        try:
            proc.wait(timeout=3)
        except Exception:
            pass


if __name__ == "__main__":
    main()
