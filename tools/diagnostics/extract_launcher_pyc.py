"""Extrai launcher.pyc do AURUM.exe e disassembla pra confirmar fix DWM."""
import dis
import marshal
import sys
import tempfile
from pathlib import Path

EXE = Path("C:/Users/Joao/projects/aurum.finance/dist/AURUM.exe")
out = Path(tempfile.gettempdir()) / "aurum_launcher_extracted"
out.mkdir(exist_ok=True)

# pyinstaller archive viewer programmatic API
from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader

car = CArchiveReader(str(EXE))
toc = car.toc  # dict: name -> (dpos, dlen, ulen, flag, typcd)
print(f"CArchive toc entries: {len(toc)}")
sample_name = next(iter(toc))
print(f"Sample: {sample_name!r} -> {toc[sample_name]}")

# acha PYZ por nome
pyz_name = None
for name, entry in toc.items():
    typcd = entry[4]
    if typcd == "z" or "PYZ" in str(name):
        pyz_name = name
        print(f"PYZ: name={name!r} typcd={typcd!r} dlen={entry[1]}")
        break

if not pyz_name:
    print("Nao achei PYZ")
    sys.exit(1)

pyz_bytes = car.extract(pyz_name)
if isinstance(pyz_bytes, tuple):
    pyz_bytes = pyz_bytes[1]
pyz_path = out / "PYZ-extracted"
pyz_path.write_bytes(pyz_bytes)
print(f"PYZ extraido -> {pyz_path} ({len(pyz_bytes)} bytes)")

# le PYZ
zlib_arch = ZlibArchiveReader(str(pyz_path))
print(f"PYZ tem {len(zlib_arch.toc)} entries")
print(f"PYZ sample: {next(iter(zlib_arch.toc))!r}")

# acha launcher
if "launcher" in zlib_arch.toc:
    result = zlib_arch.extract("launcher")
    print(f"launcher extract result type: {type(result)}")
    if isinstance(result, tuple):
        typ, code_obj = result
    else:
        code_obj = result
    print(f"code_obj type: {type(code_obj)}")
    if isinstance(code_obj, bytes):
        code_obj = marshal.loads(code_obj)
    # extrai os nomes definidos no nivel de modulo
    names = code_obj.co_names
    print(f"Module-level names ({len(names)}): {sorted(set(names))[:50]}...")

    # procura nas constantes (functions are nested code objects)
    found_titlebar = False
    found_apply_dwm = False
    for const in code_obj.co_consts:
        if hasattr(const, "co_name"):
            if "titlebar" in const.co_name.lower():
                found_titlebar = True
                print(f"  FOUND nested code: {const.co_name}")
            if "apply_titlebar_dwm" in const.co_name:
                found_apply_dwm = True
                print(f"  FOUND nested code: {const.co_name}")

    # busca em sub-codes (classe App)
    def walk(co, depth=0):
        for c in co.co_consts:
            if hasattr(c, "co_name"):
                if "titlebar" in c.co_name.lower() or "apply_dwm" in c.co_name.lower():
                    print(f"  {'  '*depth}FOUND: {c.co_name} (qualname={c.co_qualname})")
                walk(c, depth + 1)

    walk(code_obj)
else:
    print("launcher NAO esta no PYZ")
