#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主题与图标的测试：配色、托盘图标、资源定位。"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from campusnet import models  # noqa: E402
from campusnet.ui import theme  # noqa: E402


class PaletteTest(unittest.TestCase):
    def test_state_colors_are_distinct(self):
        colors = {theme.color_for(s) for s in (models.STATE_ONLINE,
                                               models.STATE_OFFLINE,
                                               models.STATE_UNKNOWN)}
        self.assertEqual(3, len(colors), "三种状态必须有不同颜色")

    def test_online_is_green(self):
        r, g, b = (int(theme.ONLINE[i:i + 2], 16) for i in (1, 3, 5))
        self.assertGreater(g, r)
        self.assertGreater(g, b)

    def test_background_is_light_green(self):
        """底色应当是很淡的绿：偏亮，且绿色分量最大。"""
        r, g, b = (int(theme.BG[i:i + 2], 16) for i in (1, 3, 5))
        self.assertGreater(g, r)
        self.assertGreater(g, b)
        self.assertGreater(min(r, g, b), 200, "底色要够淡")

    def test_primary_is_vivid_green(self):
        r, g, b = (int(theme.PRIMARY[i:i + 2], 16) for i in (1, 3, 5))
        self.assertGreater(g, r + 40)
        self.assertGreater(g, b + 20)

    def test_state_text(self):
        self.assertEqual("已在线", theme.text_for(models.STATE_ONLINE))
        self.assertEqual("未登录", theme.text_for(models.STATE_OFFLINE))


class AssetTest(unittest.TestCase):
    def test_emblem_assets_exist(self):
        for name in ("nwafu-emblem.png", "emblem-ui.png", "campusnet.ico"):
            path = theme.resource_path("assets", name)
            self.assertTrue(os.path.exists(path), "缺少资源：%s" % name)

    def test_emblem_png_is_square_with_transparency(self):
        from PIL import Image
        with Image.open(theme.resource_path("assets", "nwafu-emblem.png")) as raw:
            im = raw.convert("RGBA")
        self.assertEqual(im.width, im.height)
        rgba = im
        alphas = [p[3] for p in rgba.getdata()]
        transparent = sum(1 for a in alphas if a == 0)
        self.assertGreater(transparent, len(alphas) * 0.15,
                           "圆角/圆形外底应当是透明的")
        self.assertLess(transparent, len(alphas) * 0.45)

    def test_ico_has_standard_sizes(self):
        from PIL import Image
        with Image.open(theme.resource_path("assets", "campusnet.ico")) as raw:
            sizes = set(raw.info.get("sizes", []))
        for size in ((16, 16), (32, 32), (48, 48), (256, 256)):
            self.assertIn(size, sizes)

    def test_resource_path_uses_meipass_when_frozen(self):
        original = getattr(sys, "_MEIPASS", None)
        sys._MEIPASS = os.path.join(os.sep, "fake-bundle")
        try:
            path = theme.resource_path("assets", "campusnet.ico")
            self.assertTrue(path.startswith(os.path.join(os.sep, "fake-bundle")))
        finally:
            if original is None:
                del sys._MEIPASS
            else:
                sys._MEIPASS = original


class TrayImageTest(unittest.TestCase):
    def test_tray_image_contains_emblem_and_state_dot(self):
        """托盘图标 = 校徽 + 右下角状态点。"""
        from PIL import Image
        img = theme.make_tray_image(models.STATE_ONLINE, 64)
        self.assertIsNotNone(img)
        self.assertEqual((64, 64), img.size)
        pixels = list(img.convert("RGBA").getdata())
        self.assertTrue(any(p[3] == 0 for p in pixels), "角落应保留透明")
        target = (int(theme.ONLINE[1:3], 16), int(theme.ONLINE[3:5], 16),
                  int(theme.ONLINE[5:7], 16))

        def near(p, t, tol=28):
            return all(abs(p[i] - t[i]) <= tol for i in range(3))

        green = sum(1 for p in pixels if p[3] > 200 and near(p, target))
        self.assertGreater(green, 40, "右下角应有状态点")
        # 左下角应是校徽（而非状态点）
        bottom_left = [img.getpixel((x, 60)) for x in range(2, 12)]
        self.assertFalse(all(near(p, target) for p in bottom_left))

    def test_tray_image_differs_per_state(self):
        online = theme.make_tray_image(models.STATE_ONLINE, 64)
        offline = theme.make_tray_image(models.STATE_OFFLINE, 64)
        self.assertNotEqual(list(online.getdata()), list(offline.getdata()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
