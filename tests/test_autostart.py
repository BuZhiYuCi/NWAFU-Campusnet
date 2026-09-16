#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""开机自启测试。

不碰真实注册表：把 autostart 模块里的三个读写函数换成内存实现。
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from campusnet import autostart  # noqa: E402


class FakeRegistry(object):
    """内存版注册表。"""

    def __init__(self):
        self.values = {}

    def read(self, name=autostart.VALUE_NAME):
        return self.values.get(name)

    def write(self, command, name=autostart.VALUE_NAME):
        self.values[name] = command

    def delete(self, name=autostart.VALUE_NAME):
        if name in self.values:
            del self.values[name]
            return True
        return False


class AutostartTestBase(unittest.TestCase):
    def setUp(self):
        self.reg = FakeRegistry()
        self._orig = (autostart._read_value, autostart._write_value,
                      autostart._delete_value, autostart.sys.platform)
        autostart._read_value = self.reg.read
        autostart._write_value = self.reg.write
        autostart._delete_value = self.reg.delete
        autostart.sys.platform = "win32"

    def tearDown(self):
        (autostart._read_value, autostart._write_value,
         autostart._delete_value, autostart.sys.platform) = self._orig


class CommandTest(unittest.TestCase):
    def test_dev_command_uses_pythonw_and_launcher(self):
        command = autostart.build_command()
        self.assertIn("run_gui.pyw", command)
        self.assertIn(autostart.repo_root(), command)
        self.assertNotIn("--tray", command)

    def test_silent_command_has_tray_flag(self):
        self.assertIn("--tray", autostart.build_command(silent=True))

    def test_command_is_quoted(self):
        command = autostart.build_command()
        self.assertTrue(command.startswith('"'))
        self.assertIn('" "', command)

    def test_frozen_uses_executable(self):
        original = getattr(sys, "frozen", None)
        sys.frozen = True
        try:
            command = autostart.build_command(silent=True)
            self.assertIn(sys.executable, command)
            self.assertTrue(command.endswith("--tray"))
        finally:
            if original is None:
                del sys.frozen
            else:
                sys.frozen = original


class ToggleTest(AutostartTestBase):
    def test_disabled_by_default(self):
        self.assertFalse(autostart.is_enabled())
        self.assertIsNone(autostart.current_command())

    def test_enable_writes_registry(self):
        command = autostart.enable()
        self.assertTrue(autostart.is_enabled())
        self.assertEqual(command, autostart.current_command())
        self.assertEqual(command, self.reg.values[autostart.VALUE_NAME])

    def test_disable_removes_registry(self):
        autostart.enable()
        self.assertTrue(autostart.disable())
        self.assertFalse(autostart.is_enabled())
        self.assertEqual({}, self.reg.values)

    def test_disable_when_absent_is_false(self):
        self.assertFalse(autostart.disable())

    def test_set_enabled_round_trip(self):
        self.assertTrue(autostart.set_enabled(True))
        self.assertTrue(autostart.is_enabled())
        self.assertFalse(autostart.set_enabled(False))
        self.assertFalse(autostart.is_enabled())

    def test_silent_flag_recorded(self):
        autostart.enable(silent=True)
        self.assertIn("--tray", autostart.current_command())
        autostart.enable(silent=False)
        self.assertNotIn("--tray", autostart.current_command())

    def test_unsupported_platform_raises(self):
        autostart.sys.platform = "linux"
        with self.assertRaises(autostart.AutostartUnsupported):
            autostart.enable()
        with self.assertRaises(autostart.AutostartUnsupported):
            autostart.disable()
        self.assertIsNone(autostart.current_command())


if __name__ == "__main__":
    unittest.main(verbosity=2)
