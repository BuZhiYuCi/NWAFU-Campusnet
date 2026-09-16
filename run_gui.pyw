#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图形界面启动器（开机自启注册的就是它）。

用 .pyw 扩展名是为了让 pythonw.exe 执行时不弹黑窗口；
这里自己把 src 加进模块搜索路径，所以不依赖 PYTHONPATH。
"""

import os
import sys

if not getattr(sys, "frozen", False):     # 打包后不用也不该改 sys.path
    HERE = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(HERE, "src"))

from campusnet.ui import run  # noqa: E402

if __name__ == "__main__":
    args = sys.argv[1:]
    if "--selftest" in args:
        from campusnet.ui.app import run_selftest
        sys.exit(run_selftest())
    sys.exit(run(start_hidden="--tray" in args))
