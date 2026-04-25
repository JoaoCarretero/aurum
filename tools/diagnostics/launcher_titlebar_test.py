"""Importa App() do launcher real, abre por 3s, screenshot.
Se title bar ficar dark aqui, o problema é o exe (PyInstaller).
Se ficar branca aqui, o problema é o launcher.py em si."""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import launcher  # importa App

app = launcher.App()
app.update()
# spin loop por 3s pra after_idle e after(200ms) dispararem
t0 = time.time()
while time.time() - t0 < 3.0:
    app.update()
    time.sleep(0.05)

try:
    from PIL import ImageGrab
    x = app.winfo_rootx() - 12
    y = app.winfo_rooty() - 48
    w = app.winfo_width() + 24
    h = 80  # so a title bar
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    img.save(str(ROOT / "tools" / "diagnostics" / "launcher_titlebar.png"))
    print(f"OK  bbox=({x},{y},{x+w},{y+h})")
except Exception as e:
    print(f"SCREENSHOT FAIL: {e}")

app.destroy()
