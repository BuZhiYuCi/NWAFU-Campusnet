#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""由校徽图生成程序图标 assets/campusnet.ico。

源图 assets/nwafu-emblem.png 由 tools/extract_emblem.py 从学校官方
《（2020章程）校徽》PDF 中提取（矢量原件的 600dpi 渲染，圆形外底已抠透明）。

用法:
    python tools/make_icon.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "assets", "nwafu-emblem.png")
OUT = os.path.join(ROOT, "assets", "campusnet.ico")
UI_OUT = os.path.join(ROOT, "assets", "emblem-ui.png")

#: Windows 图标常用尺寸，从大到小都带上，任务栏/资源管理器都清晰
SIZES = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)]


def main():
    try:
        from PIL import Image
    except ImportError:
        print("需要 Pillow：python -m pip install Pillow")
        return 2
    if not os.path.exists(SRC):
        print("找不到校徽图：%s" % SRC)
        print("请先运行：python tools/extract_emblem.py <校徽.pdf>")
        return 2

    src = Image.open(SRC).convert("RGBA")
    if src.width != src.height:
        side = max(src.size)
        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        canvas.paste(src, ((side - src.width) // 2, (side - src.height) // 2), src)
        src = canvas
    src.save(OUT, format="ICO", sizes=SIZES)
    print("已生成 %s（%d 字节，含 %d 种尺寸）"
          % (OUT, os.path.getsize(OUT), len(SIZES)))
    for size in SIZES:
        print("   %dx%d" % size)

    # 界面里显示用（96px，Tk 里 subsample(2) 就是 48px，放大屏也清楚）
    from PIL import Image
    ui = src.resize((96, 96), Image.LANCZOS)
    ui.save(UI_OUT, format="PNG")
    print("已生成 %s（%d 字节）" % (UI_OUT, os.path.getsize(UI_OUT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
