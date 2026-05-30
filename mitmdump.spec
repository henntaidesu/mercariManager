# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec —— 独立 mitmdump.exe（放到 mercari.exe 同级的 Scripts/ 目录）。

runner.py 通过子进程调用 `<exe目录>/Scripts/mitmdump.exe` 启动 MITM 代理，并以
`-s mitm_addon.py` 加载插件；插件内 `import src.ssl_mitm_proxy.capture_config`，因此
本 exe 必须内置整个 backend/src（纯 Python）。
"""
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = []
binaries = []
hiddenimports = []


def add_pkg(name):
    try:
        d, b, h = collect_all(name)
    except Exception as exc:  # noqa: BLE001
        print(f"[mitmdump.spec] 跳过 {name}: {exc}")
        return
    datas.extend(d)
    binaries.extend(b)
    hiddenimports.extend(h)
    print(f"[mitmdump.spec] 已收集 {name}: {len(d)} datas / {len(b)} binaries")


for pkg in ("mitmproxy", "mitmproxy_rs", "cryptography"):
    add_pkg(pkg)

# 插件运行时会 import src.*，整体打入业务源码
hiddenimports += collect_submodules("src")
hiddenimports = list(dict.fromkeys(hiddenimports))


a = Analysis(
    [os.path.join("backend", "_mitmdump_entry.py")],
    pathex=["backend"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["torch", "easyocr", "torchvision", "playwright"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="mitmdump",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
