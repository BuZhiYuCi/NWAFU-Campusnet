#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""圆角按钮控件的测试。"""

import os
import sys
import tkinter as tk
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from campusnet.ui import theme, widgets  # noqa: E402


class _Event(object):
    def __init__(self, x, y):
        self.x, self.y = x, y


class WidgetTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            probe = tk.Tk()
            probe.destroy()
        except tk.TclError as exc:
            raise unittest.SkipTest("没有可用的图形环境：%s" % exc)

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def make(self, **kwargs):
        params = {"text": "测试", "style": "accent"}
        params.update(kwargs)
        return widgets.RoundedButton(self.root, **params)


class PillImageTest(unittest.TestCase):
    def test_gradient_is_vertical(self):
        image = widgets._pill_image(40, 20, "#FFFFFF", "#000000", 10)
        top = image.getpixel((20, 1))
        bottom = image.getpixel((20, 18))
        self.assertGreater(sum(top[:3]), sum(bottom[:3]),
                           "上边应比下边亮（竖向渐变）")

    def test_corners_are_transparent(self):
        image = widgets._pill_image(40, 20, "#3FB268", "#2E8B50", 10)
        for point in ((0, 0), (39, 0), (0, 19), (39, 19)):
            self.assertEqual(0, image.getpixel(point)[3],
                             "圆角外的像素应当透明：%s" % (point,))

    def test_center_is_opaque(self):
        image = widgets._pill_image(40, 20, "#3FB268", "#2E8B50", 10)
        self.assertEqual(255, image.getpixel((20, 10))[3])


class ButtonTest(WidgetTestBase):
    def test_default_radius_is_a_slight_curve(self):
        """只要一点弧度，不是胶囊（用户明确要求）。"""
        button = self.make(height=36)
        self.assertEqual(9, button._radius)
        self.assertLess(button._radius, 36 / 3)
        self.assertLess(button._radius * 2, 36)

    def test_radius_never_exceeds_one_third_of_height(self):
        short = self.make(height=18, radius=20)
        self.assertLessEqual(short._radius, 18 // 3)

    def test_explicit_radius_is_respected(self):
        button = self.make(height=40, radius=4)
        self.assertEqual(4, button._radius)

    def test_photo_image_is_reused_per_state(self):
        button = self.make()
        first = button._photo_for("normal")
        button._render("hover")
        button._render("normal")
        self.assertIs(first, button._photo_for("normal"))
        self.assertLessEqual(len(button._images), 4)

    def test_invoke_runs_command(self):
        calls = []
        button = self.make(command=lambda: calls.append(1))
        button.invoke()
        self.assertEqual([1], calls)

    def test_disabled_does_not_invoke(self):
        calls = []
        button = self.make(command=lambda: calls.append(1))
        button.configure(state="disabled")
        button.invoke()
        button._on_release(_Event(5, 5))
        self.assertEqual([], calls)
        self.assertEqual("disabled", button.state)

    def test_reenable_after_disable(self):
        calls = []
        button = self.make(command=lambda: calls.append(1))
        button.configure(state="disabled")
        button.configure(state="normal")
        button.invoke()
        self.assertEqual([1], calls)

    def test_click_inside_invokes_release_outside_does_not(self):
        calls = []
        button = self.make(command=lambda: calls.append(1))
        button._on_press(_Event(5, 5))
        button._on_release(_Event(9, 9))
        self.assertEqual([1], calls)
        button._on_release(_Event(999, 999))     # 移出按钮再松手
        self.assertEqual([1], calls)

    def test_text_and_default_width(self):
        short = self.make(text="好")
        long = self.make(text="一键登录")
        self.assertGreater(long._width, short._width,
                           "按钮宽度应随文字变长")

    def test_configure_text_updates_label(self):
        button = self.make(text="旧")
        button.configure(text="新")
        self.assertEqual("新", button._text)
        self.assertEqual("新", button.itemcget(button._label, "text"))

    def test_hover_changes_pixels(self):
        button = self.make(style="accent")
        normal = list(button._pil_for("normal").getdata())
        hover = list(button._pil_for("hover").getdata())
        self.assertNotEqual(normal, hover, "悬停应当是另一种底色")

    def test_styles_have_distinct_colors(self):
        colors = {widgets.STYLES[s]["normal"][0] for s in widgets.STYLES}
        self.assertEqual(3, len(colors), "三种风格应当彼此可区分")

    def test_ghost_style_has_transparent_fill(self):
        button = self.make(style="ghost")
        self.assertIsNone(button._pil_for("normal"),
                          "幽灵按钮常态不画底，只有悬停才出现底")
        self.assertIsNotNone(button._pil_for("hover"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
