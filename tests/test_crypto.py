#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""加密实现回归测试：与门户官方 JS 生成的向量逐字节比对。"""

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from campusnet import crypto  # noqa: E402

VECTORS = os.path.join(ROOT, "tests", "vectors.json")


class CryptoVectorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(VECTORS, "r", encoding="utf-8") as f:
            cls.vectors = json.load(f)["vectors"]

    def test_vectors_available(self):
        self.assertEqual(5, len(self.vectors))
        for c in self.vectors:
            for key in ("token", "username", "password", "ip", "acid",
                        "info", "hmd5_hmac", "hmd5_concat", "chksum"):
                self.assertIn(key, c)

    def test_info_matches_official_js(self):
        """XXTEA + 自定义 Base64 的组合结果必须与官方 JS 完全一致。"""
        for c in self.vectors:
            with self.subTest(user=c["username"]):
                got = crypto.build_info(c["username"], c["password"], c["ip"],
                                        c["acid"], c["token"])
                self.assertEqual(c["info"], got)

    def test_hmd5_uses_hmac_not_concat(self):
        """hmd5 必须是 HMAC-MD5(key=token, msg=password)，而不是 md5(password+token)。"""
        for c in self.vectors:
            with self.subTest(user=c["username"]):
                self.assertEqual(c["hmd5_hmac"],
                                 crypto.hmac_md5(c["password"], c["token"]))
                self.assertNotEqual(c["hmd5_hmac"],
                                    crypto.md5_hex(c["password"] + c["token"]))

    def test_chksum_matches_official_js(self):
        for c in self.vectors:
            with self.subTest(user=c["username"]):
                info = crypto.build_info(c["username"], c["password"], c["ip"],
                                         c["acid"], c["token"])
                hmd5 = crypto.hmac_md5(c["password"], c["token"])
                got = crypto.build_chksum(c["token"], c["username"], hmd5,
                                          c["acid"], c["ip"], 200, 1, info)
                self.assertEqual(c["chksum"], got)

    def test_custom_base64_roundtrip(self):
        for raw in (b"", b"a", b"ab", b"abc", b"\x00\xff\x7f", bytes(range(256))):
            with self.subTest(raw=raw[:8]):
                enc = crypto.custom_b64_encode(raw)
                self.assertEqual(raw, crypto.custom_b64_decode(enc))

    def test_custom_base64_uses_nonstandard_alphabet(self):
        """字母表必须是门户那一套，否则服务端解密失败。"""
        self.assertEqual(64, len(set(crypto.CUSTOM_ALPHA)))
        # 标准表首位是 'A'，门户自定义表首位是 'L'
        self.assertEqual("L", crypto.custom_b64_encode(b"\x00\x00\x00")[0])


class SignatureHelpersTest(unittest.TestCase):
    def test_js_time_is_integer_seconds(self):
        """Date.parse(new Date())/1000 是整数秒（小数会被服务端判 sign_error）。"""
        t = crypto.js_time_str(1789488190.489)
        self.assertEqual("1789488190", t)
        self.assertNotIn(".", t)

    def test_dm_signature_shape(self):
        t, sign = crypto.dm_signature("17782817252", "10.0.0.1", now=1789488190)
        self.assertEqual("1789488190", t)
        self.assertEqual(40, len(sign))
        self.assertEqual(crypto.sha1_hex(t + "17782817252" + "10.0.0.1" + "1" + t),
                         sign)

    def test_build_info_json_field_order(self):
        """字段顺序必须与 JS 的 JSON.stringify 一致，否则密文不同。"""
        s = crypto.build_info_json("u", "p", "1.2.3.4", "1")
        self.assertEqual(
            '{"username":"u","password":"p","ip":"1.2.3.4","acid":"1",'
            '"enc_ver":"srun_bx1"}', s)

    def test_password_md5(self):
        """在线设备接口用的是明文密码的 MD5（32 位小写十六进制）。"""
        self.assertEqual("098f6bcd4621d373cade4e832627b4f6",
                         crypto.password_md5("test"))
        self.assertEqual(32, len(crypto.password_md5("whatever")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
