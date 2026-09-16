#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""支持 `python -m campusnet <命令>`。"""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
