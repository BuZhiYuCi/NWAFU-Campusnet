#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""命令行启动器（打包成带控制台的 exe 时用这个入口）。"""

import os
import sys

if not getattr(sys, "frozen", False):
    HERE = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(HERE, "src"))

from campusnet.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
