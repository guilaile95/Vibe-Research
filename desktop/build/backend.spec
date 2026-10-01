# PyInstaller executes this file with its build API in scope.
# Only a sanitized staging directory is accepted; never collect the checkout.
import ast
import importlib.util
import os
from pathlib import Path
import sys
import sysconfig
from PyInstaller.utils.hooks import collect_all, collect_submodules

source = Path(os.environ["VR_DESKTOP_STAGE_SOURCE"]).resolve()
backend = source / "backend"
local_modules = {p.stem for p in backend.glob("*.py")}
hidden = {"backports.tarfile", "uvicorn", "uvicorn.logging", "uvicorn.loops.asyncio", "uvicorn.protocols.http.h11_impl",
          "uvicorn.protocols.websockets.websockets_impl", "uvicorn.lifespan.on"}
external_roots = set()
for path in backend.glob("*.py"):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        names = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                 else [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module else [])
        for name in names:
            root = name.split(".")[0]
            if root in local_modules or root == "__future__":
                continue
            if importlib.util.find_spec(root) is None:
                continue  # Optional providers retain their existing unavailable behavior.
            hidden.add(name)
            if root not in sys.stdlib_module_names:
                external_roots.add(root)

datas = [(str(p), str(p.parent.relative_to(source))) for p in source.rglob("*") if p.is_file()]
python_license = next((p for p in [Path(sysconfig.get_path("stdlib")) / "LICENSE.txt",
                                      Path(sys.base_prefix) / "LICENSE.txt"] if p.is_file()), None)
if python_license is None:
    raise RuntimeError("Python distribution LICENSE.txt is required for redistribution")
datas.append((str(python_license), "licenses/python"))
binaries = []
for package in sorted(external_roots):
    data, binary, imports = collect_all(package, filter_submodules=lambda name: not ({"tests", "test", "cli"} & set(name.split("."))))
    datas += data
    binaries += binary
    hidden.update(imports)
hidden.update(collect_submodules("uvicorn"))
a = Analysis([str(Path(SPECPATH) / "backend_entry.py")], pathex=[], binaries=binaries,
             datas=datas, hiddenimports=sorted(hidden), hookspath=[], hooksconfig={},
             runtime_hooks=[], excludes=["pytest", "IPython", "tkinter"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="vibe-backend", debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="vibe-backend")
