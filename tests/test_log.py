#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日志脱敏测试。"""

import logging
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from campusnet import log as logmod  # noqa: E402

SECRET = "my-secret-password"


class RedactTest(unittest.TestCase):
    def setUp(self):
        logmod.clear_secrets()

    def tearDown(self):
        logmod.clear_secrets()

    def test_registered_secret_is_masked(self):
        logmod.register_secret(SECRET)
        out = logmod.redact("登录失败 password=%s 结束" % SECRET)
        self.assertNotIn(SECRET, out)
        self.assertIn(logmod.MASK, out)

    def test_query_string_pattern(self):
        out = logmod.redact("GET /cgi-bin/srun_portal?action=login&password=abc123&ip=1.2.3.4")
        self.assertNotIn("abc123", out)
        self.assertIn("password=***", out)
        self.assertIn("ip=1.2.3.4", out)  # 其它参数不受影响

    def test_json_pattern(self):
        out = logmod.redact('{"username":"u","password":"hunter2","ip":"1.2.3.4"}')
        self.assertNotIn("hunter2", out)
        self.assertIn('"password":"***"', out)

    def test_md5_prefixed_hash_pattern(self):
        out = logmod.redact("凭据 cred={MD5}0123456789abcdef0123456789abcdef 已提交")
        self.assertNotIn("0123456789abcdef0123456789abcdef", out)
        self.assertIn("{MD5}***", out)

    def test_password_query_is_masked_even_with_md5_value(self):
        """password= 后面无论是什么，整段值都要被盖掉。"""
        out = logmod.redact("password={MD5}0123456789abcdef0123456789abcdef&ip=1.2.3.4")
        self.assertNotIn("0123456789abcdef", out)
        self.assertIn("password=***", out)

    def test_dpapi_ciphertext_pattern(self):
        out = logmod.redact('"password_dpapi": "AQAAANCMnd8BFdERjHoA=="')
        self.assertNotIn("AQAAANCMnd8BFdERjHoA==", out)

    def test_short_secret_is_not_registered(self):
        """太短的值不登记，避免把正常文本也替换掉。"""
        logmod.register_secret("ab")
        self.assertEqual("ab cd", logmod.redact("ab cd"))

    def test_none_passthrough(self):
        self.assertIsNone(logmod.redact(None))

    def test_plain_text_untouched(self):
        text = "登录成功，当前在线设备 2 台"
        self.assertEqual(text, logmod.redact(text))


class LoggingSetupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="campusnet-log-")
        logmod.clear_secrets()

    def tearDown(self):
        logmod.clear_secrets()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def read_log(self):
        path = logmod.log_path(self.tmp)
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def test_writes_and_rotates(self):
        logger = logmod.setup_logging(name="t1", log_dir=self.tmp, console=False,
                                      max_bytes=200, backup_count=2)
        for i in range(40):
            logger.info("第 %d 行填充内容 padding padding padding", i)
        handler = logger.handlers[0]
        self.assertEqual(2, handler.backupCount)
        self.assertTrue(os.path.exists(logmod.log_path(self.tmp)))
        self.assertTrue(os.path.exists(logmod.log_path(self.tmp) + ".1"))

    def test_password_never_reaches_the_file(self):
        logger = logmod.setup_logging(name="t2", log_dir=self.tmp, console=False)
        logmod.register_secret(SECRET)
        logger.info("正在登录，password=%s", SECRET)
        logger.warning("请求失败：password=%s&ip=1.2.3.4", SECRET)
        try:
            raise RuntimeError("认证异常，密码是 %s" % SECRET)
        except RuntimeError:
            logger.exception("登录过程出错")
        text = self.read_log()
        self.assertNotIn(SECRET, text)
        self.assertIn(logmod.MASK, text)
        self.assertIn("登录过程出错", text)

    def test_exception_traceback_is_kept_but_scrubbed(self):
        logger = logmod.setup_logging(name="t3", log_dir=self.tmp, console=False)
        logmod.register_secret(SECRET)
        try:
            raise ValueError("bad password=%s" % SECRET)
        except ValueError:
            logger.exception("boom")
        text = self.read_log()
        self.assertIn("Traceback", text)
        self.assertNotIn(SECRET, text)

    def test_repeated_setup_does_not_duplicate_handlers(self):
        logmod.setup_logging(name="t4", log_dir=self.tmp, console=False)
        logger = logmod.setup_logging(name="t5", log_dir=self.tmp, console=False)
        logger2 = logmod.setup_logging(name="t5", log_dir=self.tmp, console=False)
        self.assertIs(logger, logger2)
        self.assertEqual(1, len(logger2.handlers))


if __name__ == "__main__":
    unittest.main(verbosity=2)
