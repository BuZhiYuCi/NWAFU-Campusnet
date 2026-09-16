#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自定义控件：圆角按钮。

tk 自带按钮在 Windows 上是直角硬边、悬停只有生硬的高亮，
这里用 Pillow 先把圆角背景（带轻微渐变和描边）画好、抗锯齿缩到目标尺寸，
再贴到 Canvas 上，自己接管悬停 / 按下 / 禁用三种状态。
"""

import tkinter as tk
import tkinter.font as tkfont

from . import theme

try:
    from PIL import Image, ImageDraw, ImageTk
    _HAS_PIL = True
except ImportError:      # 没有 Pillow 时退回 Canvas 多边形画法
    _HAS_PIL = False

#: 每种风格的配色：(常态, 悬停, 按下, 禁用, 文字色, 禁用文字色, 是否有描边)
STYLES = {
    "accent": {
        "normal": ("#4CBB74", "#38A75F"),
        "hover": ("#57C57E", "#41B268"),
        "press": ("#37A05D", "#2E8B50"),
        "disabled": ("#B8DEC5", "#AFD3BC"),
        "fg": "#FFFFFF",
        "fg_disabled": "#F0F7F2",
        "border": "#2E8B50",
    },
    "soft": {
        "normal": ("#E4F5E9", "#DCF2E3"),
        "hover": ("#D6EFDF", "#CDEBD8"),
        "press": ("#C8E7D3", "#C2E5CF"),
        "disabled": ("#F1F5F2", "#EDF2EF"),
        "fg": "#2E8B50",
        "fg_disabled": "#AFC0B4",
        "border": "#C8E7D3",
    },
    "ghost": {
        "normal": (None, None),
        "hover": ("#E4F5E9", "#DCF2E3"),
        "press": ("#D6EFDF", "#CDEBD8"),
        "disabled": (None, None),
        "fg": "#69806F",
        "fg_disabled": "#B6C4BA",
        "border": None,
    },
}

# 缓存的是与解释器无关的 PIL 图像；PhotoImage 必须每个按钮自己建，
# 因为 Tk 的图像是绑定到具体解释器的，放进全局缓存会在窗口重建后失效。
_PIL_CACHE = {}


def _hex_to_rgb(value):
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


def _pill_image(width, height, top, bottom, radius, border=None, scale=4):
    """画一个圆角矩形（竖向渐变），4 倍超采样后缩小，得到平滑边缘。"""
    w, h = width * scale, height * scale
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    top_rgb, bottom_rgb = _hex_to_rgb(top), _hex_to_rgb(bottom)
    grad = Image.new("RGBA", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        grad.putpixel((0, y), (
            round(top_rgb[0] + (bottom_rgb[0] - top_rgb[0]) * t),
            round(top_rgb[1] + (bottom_rgb[1] - top_rgb[1]) * t),
            round(top_rgb[2] + (bottom_rgb[2] - top_rgb[2]) * t),
            255))
    grad = grad.resize((w, h))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1),
                                           radius=radius * scale, fill=255)
    img.paste(grad, (0, 0), mask)
    if border:
        ImageDraw.Draw(img).rounded_rectangle(
            (0, 0, w - 1, h - 1), radius=radius * scale,
            outline=_hex_to_rgb(border) + (255,), width=max(1, scale // 2))
    return img.resize((width, height), Image.LANCZOS)


class RoundedButton(tk.Canvas):
    """圆角按钮。接口尽量贴近 tk.Button：configure(state=/text=)、invoke()。"""

    def __init__(self, master, text="", command=None, style="soft",
                 width=None, height=36, radius=None, font=None,
                 padx=20, parent_bg=None):
        self._style = style
        self._command = command
        self._text = text
        self._font = font or (theme.FONT, 10)
        self._height = height
        # 只要"一点弧度"：默认 9px 圆角，最多不超过高度的三分之一
        self._radius = min(radius if radius is not None else 9, height // 3)
        self._bg = parent_bg or theme.BG
        self._state = "normal"

        measure = tkfont.Font(font=self._font)
        self._text_w = measure.measure(text)
        self._text_h = measure.metrics("linespace")
        self._width = width or (self._text_w + padx * 2)

        super().__init__(master, width=self._width, height=height,
                         highlightthickness=0, bd=0, bg=self._bg)
        self._images = {}
        self._shape = None
        self._label = None
        self._render()
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Destroy>", self._on_destroy)
        self.configure(cursor="hand2")

    # ------------------------------------------------------------------
    def _palette(self, state):
        spec = STYLES[self._style]
        key = "disabled" if self._state == "disabled" else state
        top, bottom = spec[key]
        fg = spec["fg_disabled"] if self._state == "disabled" else spec["fg"]
        return top, bottom, fg, spec["border"]

    def _pil_for(self, state):
        key = (self._style, state, self._state == "disabled",
               self._width, self._height)
        if key in _PIL_CACHE:
            return _PIL_CACHE[key]
        top, bottom, _fg, border = self._palette(state)
        if not _HAS_PIL or top is None:
            _PIL_CACHE[key] = None
            return None
        image = _pill_image(self._width, self._height, top, bottom,
                            self._radius, border)
        _PIL_CACHE[key] = image
        return image

    def _render(self, state="normal"):
        self.delete("all")
        top, bottom, fg, border = self._palette(state)
        photo = self._photo_for(state)
        if photo is not None:
            self.create_image(0, 0, anchor="nw", image=photo)
        else:
            r = self._radius
            x1, y1 = 0, 0
            x2, y2 = self._width - 1, self._height - 1
            pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r,
                   x2, y2, x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r,
                   x1, y1 + r, x1, y1]
            fill = top or self._bg
            self.create_polygon(pts, smooth=True, fill=fill,
                                outline=border or fill)
        # 中文在行框里整体略偏下，上移 1px 视觉更居中
        self._label = self.create_text(self._width // 2, self._height // 2 - 1,
                                       text=self._text, fill=fg,
                                       font=self._font)

    def _photo_for(self, state):
        """每个状态只建一次 PhotoImage 并复用。

        每次都新建的话，窗口销毁后这些对象会被 GC，而 PhotoImage.__del__
        还要去调用已经没了的 Tk 解释器，于是刷一屏 "main thread is not in main loop"。
        """
        if state in self._images:
            return self._images[state]
        pil_image = self._pil_for(state)
        if pil_image is None:
            return None
        photo = ImageTk.PhotoImage(pil_image)
        self._images[state] = photo
        return photo

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------
    def _on_enter(self, _event):
        if self._state != "disabled":
            self._render("hover")

    def _on_leave(self, _event):
        if self._state != "disabled":
            self._render("normal")

    def _on_press(self, _event):
        if self._state != "disabled":
            self._render("press")

    def _on_release(self, event):
        if self._state == "disabled":
            return
        self._render("hover" if self._inside(event) else "normal")
        if self._inside(event) and self._command:
            self._command()

    def _inside(self, event):
        return 0 <= event.x <= self._width and 0 <= event.y <= self._height

    def _on_destroy(self, event):
        if event.widget is self:
            # 在解释器还活着的时候主动放掉图片引用
            self._images.clear()

    # ------------------------------------------------------------------
    # 兼容 tk.Button 的接口
    # ------------------------------------------------------------------
    def invoke(self):
        if self._state != "disabled" and self._command:
            self._command()

    def configure(self, **kwargs):
        redraw = False
        if "state" in kwargs:
            self._state = str(kwargs.pop("state"))
            redraw = True
        if "text" in kwargs:
            self._text = kwargs.pop("text")
            redraw = True
        if "command" in kwargs:
            self._command = kwargs.pop("command")
        if kwargs:
            super().configure(**kwargs)
        if redraw:
            self.configure(cursor="hand2" if self._state != "disabled"
                           else "arrow")
            self._render("normal")
        return self

    config = configure

    @property
    def state(self):
        return self._state

    def set_bg(self, color):
        """父容器背景变了要跟着改（幽灵按钮用）。"""
        self._bg = color
        self.configure(bg=color)
        self._render("normal")
