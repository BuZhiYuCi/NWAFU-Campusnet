#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""开机自启：写/删注册表 HKCU 的 Run 项。

只影响当前用户，**不需要管理员权限**，也不碰系统级设置。
用户随时可以在设置里关掉。

注册的命令分两种情况：

- 开发环境（跑源码）：用 pythonw.exe 执行仓库根目录的 run_gui.pyw，
  这样既不弹黑窗口，也不依赖 PYTHONPATH。
- 打包之后（PyInstaller）：直接用 exe 本身。
"""

import os
import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "CampusNet"


class AutostartUnsupported(Exception):
    """当前平台不支持（非 Windows）。"""


def repo_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def build_command(silent=False):
    """生成要写进注册表的命令行。"""
    silent_arg = " --tray" if silent else ""
    if getattr(sys, "frozen", False):           # PyInstaller 打包后
        return '"%s"%s' % (sys.executable, silent_arg)
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = sys.executable
    launcher = os.path.join(repo_root(), "run_gui.pyw")
    return '"%s" "%s"%s' % (pythonw, launcher, silent_arg)


# ---------------------------------------------------------------------------
# 注册表读写（测试里可以替换这三个函数）
# ---------------------------------------------------------------------------

def _read_value(name=VALUE_NAME):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, name)
            return value
    except FileNotFoundError:
        return None
    except OSError:
        return None


def _write_value(command, name=VALUE_NAME):
    import winreg
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, command)


def _delete_value(name=VALUE_NAME):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, name)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------

def current_command():
    """当前注册的命令；没开启返回 None。"""
    if sys.platform != "win32":
        return None
    value = _read_value()
    return value or None


def is_enabled():
    return current_command() is not None


def enable(silent=False):
    """开启开机自启，返回写进去的命令。"""
    if sys.platform != "win32":
        raise AutostartUnsupported("开机自启依赖 Windows 注册表")
    command = build_command(silent=silent)
    _write_value(command)
    return command


def disable():
    """关闭开机自启；返回是否真的删掉了条目。"""
    if sys.platform != "win32":
        raise AutostartUnsupported("开机自启依赖 Windows 注册表")
    return _delete_value()


def set_enabled(flag, silent=False):
    """打开或关闭，返回最终状态。"""
    if flag:
        enable(silent=silent)
    else:
        disable()
    return is_enabled()
