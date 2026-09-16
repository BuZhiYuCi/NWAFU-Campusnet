#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""界面主题：配色、ttk 样式、徽标与托盘图标。

主色是"有生机的淡绿"：界面底色带一点绿意，主按钮用明亮的草绿，
在线状态用更饱和的绿；离线用柔和的珊瑚红，避免和整体绿调撞色。
"""

import os
import sys

from campusnet.models import STATE_OFFLINE, STATE_ONLINE, STATE_UNKNOWN

APP_NAME = "校园网助手"
FONT = "Microsoft YaHei UI"

# 字号统一在这里定义，避免按钮、标签、表格各说各话：
# Tk 的正数字号单位是"磅"，10 磅在 100% 缩放下约 13px。
FONT_TITLE = (FONT, 17, "bold")     # 状态大字
FONT_SECTION = (FONT, 11, "bold")   # 卡片小标题
FONT_BODY = (FONT, 10)              # 正文
FONT_SMALL = (FONT, 9)              # 说明文字
FONT_BUTTON = (FONT, 11)            # 主操作按钮
FONT_BUTTON_BOLD = (FONT, 11, "bold")
FONT_BUTTON_SMALL = (FONT, 10)      # 次级小按钮

# --------------------------------------------------------------------------
# 调色板
# --------------------------------------------------------------------------
BG = "#EEF7F0"            # 窗口底色：极淡的绿
CARD = "#FFFFFF"          # 卡片
CARD_SOFT = "#F5FBF7"     # 次级卡片 / 斑马纹
BORDER = "#D6E9DC"        # 分隔线与描边

PRIMARY = "#3FB268"       # 主色：明亮的草绿
PRIMARY_DARK = "#2E8B50"  # 主色加深（悬停、标题）
PRIMARY_SOFT = "#DCF2E3"  # 主色淡底（选中、表头）
PRIMARY_TINT = "#EAF8EE"  # 更淡的主色底

TEXT = "#1D2F25"          # 正文：带绿调的深灰
MUTED = "#69806F"         # 次要文字
DISABLED = "#AFC0B4"

ONLINE = "#2FA85C"
OFFLINE = "#E4796F"
UNKNOWN = "#9DB0A4"

STATE_COLORS = {
    STATE_ONLINE: ONLINE,
    STATE_OFFLINE: OFFLINE,
    STATE_UNKNOWN: UNKNOWN,
}

STATE_TEXT = {
    STATE_ONLINE: "已在线",
    STATE_OFFLINE: "未登录",
    STATE_UNKNOWN: "状态未知",
}


def color_for(state):
    return STATE_COLORS.get(state, UNKNOWN)


def text_for(state):
    return STATE_TEXT.get(state, "状态未知")


# --------------------------------------------------------------------------
# 资源（打包后从 sys._MEIPASS 取）
# --------------------------------------------------------------------------
def resource_path(*parts):
    """定位随程序分发的资源文件（源码运行 / PyInstaller 打包都适用）。"""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, *parts)
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    return os.path.join(root, *parts)


def load_image(name, master=None):
    """加载 assets 下的图片为 Tk PhotoImage；缺失时返回 None（界面照常能用）。"""
    path = resource_path("assets", name)
    if not os.path.exists(path):
        return None
    try:
        import tkinter as tk
        return tk.PhotoImage(master=master, file=path)
    except Exception:
        return None


def make_dot_image(color, size=64, border=True):
    """托盘图标：圆点（缺 Pillow 时返回 None）。"""
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


def make_tray_image(state, size=64):
    """托盘图标：徽标 + 右下角状态点（没有徽标时退回纯色圆点）。"""
    color = color_for(state)
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    emblem_path = resource_path("assets", "nwafu-emblem.png")
    if not os.path.exists(emblem_path):
        return make_dot_image(color, size)
    try:
        emblem = Image.open(emblem_path).convert("RGBA")
    except Exception:
        return make_dot_image(color, size)
    emblem = emblem.resize((size, size), Image.LANCZOS)
    dot = int(size * 0.42)
    badge = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    badge.paste(emblem, (0, 0), emblem)
    draw = ImageDraw.Draw(badge)
    x0, y0 = size - dot - 1, size - dot - 1
    draw.ellipse((x0, y0, size - 1, size - 1), fill=color, outline="white",
                 width=max(2, size // 24))
    return badge


# --------------------------------------------------------------------------
# ttk 样式
# --------------------------------------------------------------------------
def apply_style(root):
    """套用整体样式。用 clam 主题，因为只有它能自由改颜色。"""
    from tkinter import ttk
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure(".", background=BG, foreground=TEXT, font=(FONT, 10))
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=CARD)
    style.configure("Toolbar.TFrame", background=BG)

    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Card.TLabel", background=CARD, foreground=TEXT)
    style.configure("Muted.TLabel", background=BG, foreground=MUTED,
                    font=(FONT, 9))
    style.configure("CardMuted.TLabel", background=CARD, foreground=MUTED,
                    font=(FONT, 9))
    style.configure("State.TLabel", background=CARD, foreground=TEXT,
                    font=(FONT, 17, "bold"))
    style.configure("Title.TLabel", background=CARD, foreground=PRIMARY_DARK,
                    font=(FONT, 12, "bold"))
    style.configure("Section.TLabel", background=BG, foreground=PRIMARY_DARK,
                    font=(FONT, 10, "bold"))

    # 按钮：默认浅底描边，主操作用实心绿
    style.configure("TButton", padding=(14, 7), font=(FONT, 10),
                    background=CARD, foreground=TEXT,
                    bordercolor=BORDER, relief="flat", focusthickness=0)
    style.map("TButton",
              background=[("pressed", PRIMARY_SOFT), ("active", PRIMARY_TINT),
                          ("disabled", "#F1F4F2")],
              foreground=[("disabled", DISABLED)],
              bordercolor=[("active", PRIMARY)])

    style.configure("Accent.TButton", background=PRIMARY, foreground="#FFFFFF",
                    font=(FONT, 10, "bold"), bordercolor=PRIMARY)
    style.map("Accent.TButton",
              background=[("pressed", PRIMARY_DARK), ("active", "#37A05D"),
                          ("disabled", "#B8DEC5")],
              foreground=[("disabled", "#FFFFFF")],
              bordercolor=[("active", PRIMARY_DARK)])

    style.configure("Soft.TButton", background=PRIMARY_SOFT,
                    foreground=PRIMARY_DARK, bordercolor=PRIMARY_SOFT)
    style.map("Soft.TButton",
              background=[("active", "#CDEBD8"), ("pressed", "#C2E5CF")])

    style.configure("Ghost.TButton", background=BG, bordercolor=BG,
                    foreground=MUTED)
    style.map("Ghost.TButton",
              background=[("active", PRIMARY_TINT)],
              foreground=[("active", PRIMARY_DARK)])

    # 表格
    style.configure("Treeview", background=CARD, fieldbackground=CARD,
                    foreground=TEXT, rowheight=30, borderwidth=0,
                    font=(FONT, 10))
    style.map("Treeview",
              background=[("selected", PRIMARY_SOFT)],
              foreground=[("selected", TEXT)])
    style.configure("Treeview.Heading", background=PRIMARY_SOFT,
                    foreground=PRIMARY_DARK, font=(FONT, 10, "bold"),
                    relief="flat", padding=(8, 7))
    style.map("Treeview.Heading", background=[("active", "#CDEBD8")])

    style.configure("TLabelframe", background=BG, bordercolor=BORDER,
                    relief="solid", borderwidth=1, padding=10)
    style.configure("TLabelframe.Label", background=BG,
                    foreground=PRIMARY_DARK, font=(FONT, 10, "bold"))

    style.configure("TCheckbutton", background=CARD, foreground=TEXT,
                    focuscolor=CARD, font=(FONT, 9))
    style.configure("Bg.TCheckbutton", background=BG, focuscolor=BG)
    style.configure("TEntry", fieldbackground=CARD, bordercolor=BORDER,
                    lightcolor=BORDER, darkcolor=BORDER, padding=6)
    style.configure("TCombobox", fieldbackground=CARD, background=CARD,
                    bordercolor=BORDER, arrowcolor=PRIMARY_DARK, padding=5)
    style.configure("Vertical.TScrollbar", background=PRIMARY_SOFT,
                    troughcolor=BG, bordercolor=BG, arrowcolor=PRIMARY_DARK)
    style.configure("TSeparator", background=BORDER)
    return style
