# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec —— 主程序 mercari.exe（FastAPI + uvicorn，同端口提供 API 与前端）。

输出单文件 mercari.exe。前端 webside/dist 不打进 exe，由 pyinstaller.bat 复制到 exe 旁的
webside/dist 目录（main.py 冻结后从 exe 同级目录读取）。

环境变量 BUNDLE_OCR=1 时额外打入 easyocr/torch（体积巨大）；默认不打，OCR 端点会优雅提示未安装。
"""
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files

BACKEND = os.path.join(os.path.abspath(os.getcwd()), "backend")

datas = []
binaries = []
hiddenimports = []


def add_pkg(name):
    """尽力收集一个包（数据/二进制/隐藏导入）；包不存在则跳过，不让构建失败。"""
    try:
        d, b, h = collect_all(name)
    except Exception as exc:  # noqa: BLE001
        print(f"[mercari.spec] 跳过 {name}: {exc}")
        return
    datas.extend(d)
    binaries.extend(b)
    hiddenimports.extend(h)
    print(f"[mercari.spec] 已收集 {name}: {len(d)} datas / {len(b)} binaries")


# 动态导入 / 含数据文件 / 二进制扩展的依赖
for pkg in ("uvicorn", "mitmproxy", "mitmproxy_rs", "playwright", "zxingcpp",
            "cryptography", "PIL", "multipart"):
    add_pkg(pkg)

# uvicorn[standard] 的可选协议实现
hiddenimports += [
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "websockets.legacy",
    "httptools",
]

# 业务源码（backend/src）整体打入，覆盖函数内的延迟 import
hiddenimports += collect_submodules("src")
hiddenimports = list(dict.fromkeys(hiddenimports))  # 去重

# src 下可能存在的非 .py 配置/数据文件
try:
    datas += collect_data_files(
        "src",
        includes=["**/*.json", "**/*.txt", "**/*.ini", "**/*.yaml", "**/*.yml", "**/*.pem"],
    )
except Exception as exc:  # noqa: BLE001
    print(f"[mercari.spec] collect_data_files(src) 跳过: {exc}")

# mitm_addon.py 需以「磁盘文件」形式存在，供子进程 mitmdump -s <addon> 加载
datas.append((
    os.path.join(BACKEND, "src", "ssl_mitm_proxy", "mitm_addon.py"),
    os.path.join("src", "ssl_mitm_proxy"),
))

# 可选：打入 OCR（torch 体系，约 2GB，启动变慢）
if os.environ.get("BUNDLE_OCR", "0").strip() == "1":
    for pkg in ("easyocr", "torch", "torchvision", "cv2", "skimage",
                "scipy", "numpy", "shapely", "pyclipper"):
        add_pkg(pkg)


a = Analysis(
    [os.path.join("backend", "main.py")],
    pathex=["backend"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[] if os.environ.get("BUNDLE_OCR", "0").strip() == "1"
    else ["easyocr", "torch", "torchvision", "cv2", "skimage", "scipy"],
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
    name="mercari",
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
