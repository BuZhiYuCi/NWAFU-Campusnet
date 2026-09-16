#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""系统托盘图标（pystray 封装）。

没装 pystray / Pillow 时自动降级：不报错，只是没有托盘图标，
窗口仍然照常工作。这样"缺依赖"不会让整个程序打不开。
"""

import threading

from . import theme

try:
    import pystray
except ImportError:  # pragma: no cover - 取决于环境
    pystray = None


class TrayIcon(object):
    """托盘图标：显示状态、右键菜单、双击打开窗口。

    所有回调都会先切回 Tk 主线程再执行（见 app.py 传入的 marshal）。
    """

    def __init__(self, on_open, on_login, on_logout, on_quit, marshal=None):
        self._on_open = on_open
        self._on_login = on_login
        self._on_logout = on_logout
        self._on_quit = on_quit
        self._marshal = marshal or (lambda fn: fn)
        self._icon = None
        self._state = None
        self.available = pystray is not None

    # ------------------------------------------------------------------
    def _menu(self):
        return pystray.Menu(
            pystray.MenuItem("打开主窗口", lambda: self._marshal(self._on_open),
                             default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("一键登录", lambda: self._marshal(self._on_login)),
            pystray.MenuItem("一键下线", lambda: self._marshal(self._on_logout)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", lambda: self._marshal(self._on_quit)),
        )

    def start(self, state, tooltip):
        if not self.available:
            return False
        self._state = state
        self._icon = pystray.Icon("campusnet", theme.make_dot_image(
            theme.color_for(state)), tooltip, self._menu())
        threading.Thread(target=self._icon.run, daemon=True).start()
        return True

    def set_state(self, state, tooltip):
        if not self._icon or state == self._state:
            return
        self._state = state
        try:
            self._icon.icon = theme.make_dot_image(theme.color_for(state))
            self._icon.title = tooltip
        except Exception:
            pass

    def notify(self, message, title="校园网助手"):
        if not self._icon:
            return
        try:
            self._icon.notify(message, title)
        except Exception:
            pass

    def stop(self):
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None
