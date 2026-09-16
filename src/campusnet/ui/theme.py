#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""界面配色与图标生成。"""

from campusnet.models import STATE_OFFLINE, STATE_ONLINE, STATE_UNKNOWN

# 三态颜色：绿=已在线 / 红=已离线 / 灰=不在校园网或状态未知
STATE_COLORS = {
    STATE_ONLINE: "#2e9e4f",
    STATE_OFFLINE: "#c0392b",
    STATE_UNKNOWN: "#8a8a8a",
}

STATE_TEXT = {
    STATE_ONLINE: "已在线",
    STATE_OFFLINE: "未登录（离线）",
    STATE_UNKNOWN: "状态未知",
}

TEXT = "#1f2328"
MUTED = "#6b7280"
BG = "#f6f7f9"
CARD = "#ffffff"


def color_for(state):
    return STATE_COLORS.get(state, STATE_COLORS[STATE_UNKNOWN])


def text_for(state):
    return STATE_TEXT.get(state, "状态未知")


def make_dot_image(color, size=64, border=True):
    """生成托盘用的圆点图标（没装 Pillow 时返回 None）。"""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    pad = max(2, size // 8)
    draw.ellipse((pad, pad, size - pad, size - pad), fill=color,
                 outline="#ffffff" if border else None,
                 width=max(1, size // 16))
    return image
