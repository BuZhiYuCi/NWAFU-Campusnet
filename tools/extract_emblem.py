#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从学校官方校徽 PDF 提取矢量 SVG 与高清 PNG（一次性步骤，需要 pymupdf）。

来源：西北农林科技大学 校徽（2020 章程）
      https://www.nwafu.edu.cn/xxgk/xxbz/xh/
      附件「（2020章程）校徽.cdr / .pdf」——PDF 里是**纯矢量**，没有点阵图。

产出：
    assets/nwafu-emblem.png   512x512，圆形徽标，四周透明（可直接做图标）
    assets/nwafu-emblem.svg   矢量版，viewBox 已裁到徽标本体

用法:
    python tools/extract_emblem.py <校徽.pdf 路径>
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
OUT_PNG = os.path.join(ASSETS, "nwafu-emblem.png")
OUT_SVG = os.path.join(ASSETS, "nwafu-emblem.svg")

#: 用来标记"徽标外部"的哨兵色，徽标里不会用到
SENTINEL = (255, 0, 255)


def ink_bbox(image, alpha_only=False):
    """返回非白（或非透明）像素的包围盒。"""
    width, height = image.size
    px = image.load()
    min_x, min_y, max_x, max_y = width, height, -1, -1
    for y in range(height):
        for x in range(width):
            if alpha_only:
                hit = px[x, y][3] > 8
            else:
                r, g, b = px[x, y][:3]
                hit = r < 245 or g < 245 or b < 245
            if hit:
                if x < min_x:
                    min_x = x
                if y < min_y:
                    min_y = y
                if x > max_x:
                    max_x = x
                if y > max_y:
                    max_y = y
    if max_x < 0:
        return None
    return min_x, min_y, max_x, max_y


def cut_out_background(image):
    """把徽标外部的白底变成透明（只从四角泛洪，内部白色细节保留）。"""
    from PIL import ImageDraw
    rgb = image.convert("RGB")
    width, height = rgb.size
    for seed in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
        try:
            ImageDraw.floodfill(rgb, seed, SENTINEL, thresh=170)
        except Exception:
            pass
    out = image.convert("RGBA")
    src, dst = rgb.load(), out.load()
    for y in range(height):
        for x in range(width):
            if src[x, y] == SENTINEL:
                dst[x, y] = (0, 0, 0, 0)
    return out


def square_pad(image, size, margin_ratio=0.02):
    """裁到内容、加边距、居中成正方形，再缩放到 size。"""
    from PIL import Image
    box = ink_bbox(image, alpha_only=True)
    if not box:
        raise ValueError("图像是空的")
    cropped = image.crop((box[0], box[1], box[2] + 1, box[3] + 1))
    side = max(cropped.size)
    side = int(side * (1 + margin_ratio * 2))
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(cropped, ((side - cropped.width) // 2,
                           (side - cropped.height) // 2), cropped)
    return canvas.resize((size, size), Image.LANCZOS)


def crop_svg(svg_text, box, pad=2.0):
    """把整页 SVG 的 viewBox 改到徽标本体，得到"就是徽标"的矢量文件。"""
    x0, y0, x1, y1 = box
    width = x1 - x0 + pad * 2
    height = y1 - y0 + pad * 2
    new_view = "%.2f %.2f %.2f %.2f" % (x0 - pad, y0 - pad, width, height)
    text = re.sub(r'viewBox="[^"]*"', 'viewBox="%s"' % new_view, svg_text, count=1)
    text = re.sub(r'width="[^"]*"', 'width="%.2f"' % width, text, count=1)
    text = re.sub(r'height="[^"]*"', 'height="%.2f"' % height, text, count=1)
    return text


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    pdf_path = sys.argv[1]
    if not os.path.exists(pdf_path):
        print("找不到 PDF：%s" % pdf_path)
        return 2
    try:
        import pymupdf
    except ImportError:
        print("需要 pymupdf：python -m pip install pymupdf")
        return 2
    from PIL import Image
    import io

    os.makedirs(ASSETS, exist_ok=True)
    doc = pymupdf.open(pdf_path)
    page = doc[0]                       # 第 1 页 = 彩色校徽本体

    # --- 高清 PNG ---
    dpi = 600
    pix = page.get_pixmap(dpi=dpi)
    raw = Image.open(io.BytesIO(pix.tobytes("png")))
    print("原始渲染: %dx%d" % raw.size)
    transparent = cut_out_background(raw)
    icon = square_pad(transparent, 512)
    icon.save(OUT_PNG, format="PNG")
    print("已生成 %s（%d 字节）" % (OUT_PNG, os.path.getsize(OUT_PNG)))

    # --- 矢量 SVG：算内容包围盒（换算回 PDF 点） ---
    scale = dpi / 72.0
    box_px = ink_bbox(raw)
    box_pt = tuple(v / scale for v in box_px)
    svg = page.get_svg_image()
    svg = crop_svg(svg, box_pt)
    with open(OUT_SVG, "w", encoding="utf-8") as f:
        f.write(svg)
    print("已生成 %s（%d 字节，viewBox=%s）"
          % (OUT_SVG, os.path.getsize(OUT_SVG),
             re.search(r'viewBox="([^"]*)"', svg).group(1)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
