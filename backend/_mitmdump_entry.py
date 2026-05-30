# -*- coding: utf-8 -*-
"""PyInstaller 入口：把 mitmdump 打成独立 exe。

runner.py 以子进程方式调用 `<exe目录>/Scripts/mitmdump.exe`，本文件即该 exe 的入口。
打包后 `import src...`（mitm_addon.py 里用到）从本 exe 内置的归档解析，无需磁盘上的源码。
"""
from __future__ import annotations

import sys

from mitmproxy.tools.main import mitmdump

if __name__ == "__main__":
    sys.exit(mitmdump())
