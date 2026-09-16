#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配置读写与凭据管理。

存放位置：%APPDATA%\\CampusNet\\config.json

- 账号、行为开关、设备别名等都在这里；
- **密码只以 DPAPI 密文形式落盘**，明文绝不写文件；
- 写入用"临时文件 + 原子替换"，避免断电/崩溃写坏配置；
- 配置带 version 字段，未来结构变化时按版本迁移。
"""

import copy
import json
import os
from typing import Any, Dict, Optional

from .dpapi import DpapiCipher, DpapiError, PlaintextCipher, default_cipher

APP_DIR_NAME = "CampusNet"
CONFIG_FILE_NAME = "config.json"

#: 当前配置结构版本
CONFIG_VERSION = 2

#: 默认配置（首次运行时以此为基础）
DEFAULT_CONFIG = {
    "version": CONFIG_VERSION,
    "portal": {
        "base_url": "http://172.26.8.11",
        "ac_id": "1",
        "username": "",
        # DPAPI 密文（Base64）；明文密码永不落盘
        "password_dpapi": "",
        "cipher": "dpapi",
        "os_name": "Windows 10",
        "client_name": "Windows",
        "timeout_sec": 8,
        "login_timeout_sec": 30,
        "confirm_timeout_sec": 90,
    },
    "behavior": {
        "kick_mode": "preselect_oldest",   # preselect_oldest | manual
        # 一键下线用哪种机制：
        #   dm     —— rad_user_dm(unbind=1)，连 MAC 免认证绑定一起解除（实测能真正下线，默认）
        #   portal —— action=logout，只注销会话；若本机 MAC 开了免认证会被立刻拉回
        "logout_method": "dm",
        "confirm_before_kick": True,
        "batch_kick_interval_ms": 800,
        "login_cooldown_sec": 10,
        "max_login_attempts": 3,
    },
    "startup": {
        "autostart": False,
        "open_window_on_start": True,
        "silent_when_autostart": False,
        "auto_login_on_start": False,
    },
    "devices": [],
    "ui": {
        "tray": True,
        "hotkey_login": "Ctrl+Alt+L",
        "hotkey_logout": "Ctrl+Alt+K",
    },
}


def app_dir():
    """配置目录：%APPDATA%\\CampusNet（取不到 APPDATA 时退回用户主目录）。"""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_DIR_NAME)


def default_config_path():
    """配置文件路径，可用环境变量 CAMPUSNET_CONFIG 覆盖（便携使用/测试）。"""
    override = os.environ.get("CAMPUSNET_CONFIG")
    if override:
        return override
    return os.path.join(app_dir(), CONFIG_FILE_NAME)


def default_log_dir():
    override = os.environ.get("CAMPUSNET_LOG_DIR")
    if override:
        return override
    return os.path.join(app_dir(), "logs")


def _deep_merge(base, override):
    """把 override 合并进 base 的副本；只对 dict 递归，列表整体替换。"""
    out = copy.deepcopy(base)
    if not isinstance(override, dict):
        return out
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


class Config(object):
    """配置对象。所有取值都用点号路径访问，例如 ``cfg.get("portal.ac_id")``。"""

    def __init__(self, path=None, cipher=None):
        self.path = path or default_config_path()
        self._cipher = cipher
        self.data = copy.deepcopy(DEFAULT_CONFIG)
        self.loaded = False

    # ------------------------------------------------------------------
    # 读写
    # ------------------------------------------------------------------
    def load(self):
        """读取配置；文件不存在或损坏时回退到默认值并标记 loaded=False。"""
        if not os.path.exists(self.path):
            self.data = copy.deepcopy(DEFAULT_CONFIG)
            self.loaded = False
            return self
        with open(self.path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            raise ValueError("配置文件内容不是 JSON 对象：%s" % self.path)
        self.data = self._migrate(_deep_merge(DEFAULT_CONFIG, raw))
        self.loaded = True
        return self

    def save(self):
        """原子写入：先写临时文件再替换，避免写一半损坏原配置。"""
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        self.data["version"] = CONFIG_VERSION
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
        self.loaded = True
        return self

    def _migrate(self, data):
        """结构升级。目前只需把版本号补齐（默认值合并已经补上新字段）。"""
        data["version"] = CONFIG_VERSION
        return data

    # ------------------------------------------------------------------
    # 点号访问
    # ------------------------------------------------------------------
    def get(self, dotted, default=None):
        node = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, dotted, value):
        parts = dotted.split(".")
        node = self.data
        for part in parts[:-1]:
            if not isinstance(node.get(part), dict):
                node[part] = {}
            node = node[part]
        node[parts[-1]] = value
        return self

    # ------------------------------------------------------------------
    # 凭据
    # ------------------------------------------------------------------
    @property
    def cipher(self):
        if self._cipher is None:
            self._cipher = default_cipher()
        return self._cipher

    @property
    def username(self):
        return self.get("portal.username", "") or ""

    @property
    def has_credentials(self):
        return bool(self.username) and bool(self.get("portal.password_dpapi", ""))

    def set_password(self, plaintext):
        """用 DPAPI 加密后存入配置（只改内存，需再 save()）。"""
        token = self.cipher.encrypt(plaintext)
        self.set("portal.password_dpapi", token)
        self.set("portal.cipher", self.cipher.name)
        return self

    def get_password(self):
        """解出明文密码；没有配置或解密失败返回 None。"""
        token = self.get("portal.password_dpapi", "")
        if not token:
            return None
        try:
            return self.cipher.decrypt(token)
        except DpapiError:
            return None

    def clear_password(self):
        self.set("portal.password_dpapi", "")
        return self

    def set_credentials(self, username, password):
        self.set("portal.username", username or "")
        if password:
            self.set_password(password)
        else:
            self.clear_password()
        return self

    # ------------------------------------------------------------------
    # 便捷属性
    # ------------------------------------------------------------------
    @property
    def ac_id(self):
        return str(self.get("portal.ac_id", "1"))

    @property
    def base_url(self):
        return self.get("portal.base_url", "http://172.26.8.11")

    @property
    def kick_mode(self):
        return self.get("behavior.kick_mode", "preselect_oldest")

    def __repr__(self):
        return "<Config %s loaded=%s user=%s pwd=%s>" % (
            self.path, self.loaded, self.username or "-",
            "***" if self.get("portal.password_dpapi") else "-")


def load_or_create(path=None, cipher=None):
    """读取配置；不存在则创建一个空配置（不落盘，等用户设置账号后 save）。"""
    cfg = Config(path=path, cipher=cipher)
    try:
        cfg.load()
    except (OSError, ValueError):
        cfg.data = copy.deepcopy(DEFAULT_CONFIG)
    return cfg
