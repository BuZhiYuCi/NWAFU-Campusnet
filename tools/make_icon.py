#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成程序图标 assets/campusnet.ico。

图案：蓝色圆角底 + 白色信号弧 + 绿色圆点（呼应界面里的三色状态灯）。
纯几何绘制，不依赖字体，任何机器上生成结果都一样。
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "assets")
OUT = os.path.join(OUT_DIR, "campusnet.ico")

BLUE = "#1a73e8"
GREEN = "#2e9e4f"


def draw(size=256):
    from PIL import Image, ImageDraw
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw_ctx = ImageDraw.Draw(image)

    draw_ctx.rounded_rectangle([0, 0, size - 1, size - 1],
                               radius=int(size * 0.22), fill=BLUE)

    # 三段信号弧，圆心在绿点处，向上展开
    cx, cy = size * 0.5, size * 0.72
    width = max(2, int(size * 0.075))
    for radius in (0.26, 0.38, 0.50):
        r = size * radius
        draw_ctx.arc([cx - r, cy - r, cx + r, cy + r],
                     start=205, end=335, fill="#ffffff", width=width)

    r = size * 0.085
    draw_ctx.ellipse([cx - r, cy - r, cx + r, cy + r], fill=GREEN)
    return image


def main():
    try:
        from PIL import Image
    except ImportError:
        print("需要 Pillow：python -m pip install Pillow")
        return 2
    os.makedirs(OUT_DIR, exist_ok=True)
    image = draw(256)
    image.save(OUT, format="ICO",
               sizes=[(256, 256), (128, 128), (64, 64), (48, 48),
                      (32, 32), (16, 16)])
    png = os.path.join(OUT_DIR, "campusnet.png")
    image.save(png, format="PNG")
    print("已生成 %s（%d 字节）" % (OUT, os.path.getsize(OUT)))
    print("已生成 %s（%d 字节）" % (png, os.path.getsize(png)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
