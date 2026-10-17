#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配置与凭据管理测试（使用临时目录 + 假加密器，不碰真实配置）。"""

import json
import base64
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from campusnet import config as cfgmod  # noqa: E402

FAKE_PASSWORD = "unit-test-password-123"


class Base64FakeCipher(object):
    """测试用假加密器：可逆、可跨进程解密，但明文中不含原始密码。

    （真实的 DpapiCipher 在 Windows 上由操作系统保管密钥，行为见 dpapi.py。）
    """

    name = "fake"

    def encrypt(self, plaintext):
        return "fake:" + base64.b64encode(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, token):
        return base64.b64decode(token[len("fake:"):]).decode("utf-8")


class ConfigTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="campusnet-test-")
        self.path = os.path.join(self.tmp, "config.json")
        self.cipher = Base64FakeCipher()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make(self):
        return cfgmod.Config(path=self.path, cipher=self.cipher)


class DefaultsTest(ConfigTestBase):
    def test_defaults_present_without_file(self):
        cfg = self.make().load()
        self.assertFalse(cfg.loaded)
        self.assertEqual("http://172.26.8.11", cfg.base_url)
        self.assertEqual("1", cfg.ac_id)
        self.assertEqual("preselect_oldest", cfg.kick_mode)
        self.assertFalse(cfg.get("startup.autostart"))
        self.assertTrue(cfg.get("startup.open_window_on_start"))
        self.assertEqual([], cfg.get("devices"))

    def test_missing_file_is_not_an_error(self):
        cfg = cfgmod.load_or_create(path=self.path, cipher=self.cipher)
        self.assertFalse(os.path.exists(self.path))
        self.assertFalse(cfg.loaded)


class RoundTripTest(ConfigTestBase):
    def test_save_and_reload(self):
        cfg = self.make().load()
        cfg.set("portal.username", "20230000001")
        cfg.set("behavior.kick_mode", "manual")
        cfg.set("startup.autostart", True)
        cfg.save()

        again = self.make().load()
        self.assertTrue(again.loaded)
        self.assertEqual("20230000001", again.username)
        self.assertEqual("manual", again.kick_mode)
        self.assertTrue(again.get("startup.autostart"))

    def test_new_keys_get_defaults_on_upgrade(self):
        """老配置缺少新字段时，应当自动补上默认值而不是报错。"""
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "portal": {"username": "u1"}}, f)
        cfg = self.make().load()
        self.assertEqual("u1", cfg.username)
        self.assertEqual("http://172.26.8.11", cfg.base_url)
        self.assertEqual(cfgmod.CONFIG_VERSION, cfg.data["version"])
        self.assertFalse(cfg.get("startup.autostart"))

    def test_corrupt_file_raises_then_load_or_create_recovers(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{ this is not json")
        with self.assertRaises(ValueError):
            self.make().load()
        cfg = cfgmod.load_or_create(path=self.path, cipher=self.cipher)
        self.assertFalse(cfg.loaded)
        self.assertEqual("http://172.26.8.11", cfg.base_url)

    def test_save_is_atomic_and_leaves_no_temp_file(self):
        cfg = self.make().load().save()
        self.assertTrue(os.path.exists(self.path))
        self.assertFalse(os.path.exists(self.path + ".tmp"))
        with open(self.path, "r", encoding="utf-8") as f:
            json.load(f)  # 必须是合法 JSON

    def test_dotted_access(self):
        cfg = self.make().load()
        cfg.set("a.b.c", 1)
        self.assertEqual(1, cfg.get("a.b.c"))
        self.assertIsNone(cfg.get("a.b.missing"))
        self.assertEqual("fallback", cfg.get("nope.nope", "fallback"))


class CredentialsTest(ConfigTestBase):
    def test_password_roundtrip(self):
        cfg = self.make().load()
        cfg.set_credentials("20230000001", FAKE_PASSWORD)
        cfg.save()
        again = self.make().load()
        self.assertTrue(again.has_credentials)
        self.assertEqual("20230000001", again.username)
        self.assertEqual(FAKE_PASSWORD, again.get_password())

    def test_plaintext_password_is_not_written_to_disk(self):
        cfg = self.make().load()
        cfg.set_credentials("20230000001", FAKE_PASSWORD)
        cfg.save()
        with open(self.path, "r", encoding="utf-8") as f:
            raw = f.read()
        self.assertNotIn(FAKE_PASSWORD, raw)
        self.assertIn("password_dpapi", raw)

    def test_change_password_replaces_old_one(self):
        cfg = self.make().load()
        cfg.set_credentials("u", "old-password")
        cfg.save()
        cfg2 = self.make().load()
        cfg2.set_credentials("u", "new-password")
        cfg2.save()
        again = self.make().load()
        self.assertEqual("new-password", again.get_password())
        self.assertNotEqual("old-password", again.get_password())

    def test_clear_password(self):
        cfg = self.make().load()
        cfg.set_credentials("u", FAKE_PASSWORD)
        cfg.clear_password()
        cfg.save()
        again = self.make().load()
        self.assertFalse(again.has_credentials)
        self.assertIsNone(again.get_password())

    def test_missing_password_returns_none(self):
        cfg = self.make().load()
        self.assertIsNone(cfg.get_password())
        self.assertFalse(cfg.has_credentials)

    def test_undecryptable_password_returns_none(self):
        """密文被换机器/换用户后就该解不开——此时返回 None 而不是抛异常。"""
        cfg = self.make().load()
        cfg.set("portal.password_dpapi", "fake:d2hhdGV2ZXI=")
        cfg._cipher = _FailingCipher()
        self.assertIsNone(cfg.get_password())

    def test_repr_never_shows_password(self):
        cfg = self.make().load()
        cfg.set_credentials("20230000001", FAKE_PASSWORD)
        text = repr(cfg)
        self.assertNotIn(FAKE_PASSWORD, text)
        self.assertIn("20230000001", text)


class BrokenFileTest(ConfigTestBase):
    """配置文件读不动时的抢救行为（D-06a）。"""

    def test_broken_json_is_backed_up_and_reported(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write('{"portal": {"username": "20230000001", "passw')
        cfg = cfgmod.load_or_create(path=self.path, cipher=self.cipher)
        self.assertFalse(cfg.loaded)
        self.assertIsNotNone(cfg.load_error, "必须把失败原因记下来")
        self.assertTrue(cfg.backup_path, "必须留下备份路径")
        self.assertTrue(os.path.exists(cfg.backup_path), "备份文件要真的存在")
        # 原文件不能被默认值覆盖：里面可能还有能手工抢救的密文
        with open(self.path, "r", encoding="utf-8") as f:
            self.assertIn("20230000001", f.read())

    def test_missing_file_is_not_an_error(self):
        cfg = cfgmod.load_or_create(path=self.path, cipher=self.cipher)
        self.assertIsNone(cfg.load_error)
        self.assertIsNone(cfg.backup_path)
        self.assertFalse(cfg.loaded)

    def test_non_object_json_is_treated_as_broken(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("[1, 2, 3]")
        cfg = cfgmod.load_or_create(path=self.path, cipher=self.cipher)
        self.assertIsNotNone(cfg.load_error)
        self.assertTrue(os.path.exists(cfg.backup_path))


class _FailingCipher(object):
    name = "failing"

    def encrypt(self, plaintext):
        raise AssertionError("不应被调用")

    def decrypt(self, token):
        from campusnet.dpapi import DpapiError
        raise DpapiError("模拟解密失败")


if __name__ == "__main__":
    unittest.main(verbosity=2)
