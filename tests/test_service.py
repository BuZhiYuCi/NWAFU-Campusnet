#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""业务编排测试：满员 → 腾位 → 重试登录 的整条链路（用脚本化的假客户端）。"""

import base64
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from campusnet import policy  # noqa: E402
from campusnet.config import Config  # noqa: E402
from campusnet.models import (ALREADY_ONLINE, FULL, NOT_ONLINE, SIGNATURE_ERROR,
                              STATE_OFFLINE, STATE_ONLINE, SUCCESS, UNKNOWN,
                              Device, OnlineStatus, Result)  # noqa: E402
from campusnet.service import CampusNetService  # noqa: E402


class FakeCipher(object):
    name = "fake"

    def encrypt(self, plaintext):
        return "fake:" + base64.b64encode(plaintext.encode()).decode()

    def decrypt(self, token):
        return base64.b64decode(token[5:]).decode()


def dev(ip, add_time, os_name="Windows 10", ctype="1"):
    return Device(ip=ip, add_time=add_time, os_name=os_name, client_type=ctype)


SELF = dev("10.0.0.9", "2026-09-16 00:10:00")
OLDEST = dev("10.0.0.1", "2026-09-12 21:50:49")
MIDDLE = dev("10.0.0.2", "2026-09-14 08:00:00")
THREE_DEVICES = [SELF, OLDEST, MIDDLE]


class ScriptClient(object):
    """按脚本返回结果的假客户端。"""

    def __init__(self, login_results, devices=None, state=STATE_OFFLINE,
                 my_ip="10.0.0.9", kick_ok=True):
        self._login_results = list(login_results)
        self._devices = list(devices if devices is not None else [])
        self._state = state
        self._my_ip = my_ip
        self._kick_ok = kick_ok
        self.kicked = []
        self.login_calls = 0

    def local_state(self, username=None, password=None, timeout=None):
        status = OnlineStatus(
            online=(self._state == STATE_ONLINE),
            error="ok" if self._state == STATE_ONLINE else "not_online_error",
            raw={"online_ip": self._my_ip,
                 "user_name": "17782817252" if self._state == STATE_ONLINE else None})
        return self._state, status, list(self._devices)

    def online_devices(self, username, password, timeout=None):
        return list(self._devices)

    def login_and_confirm(self, *args, **kwargs):
        self.login_calls += 1
        if not self._login_results:
            return Result(kind=FULL, raw={"ecode": "E2621"})
        return self._login_results.pop(0)

    def kick(self, ip, username, unbind=1, timeout=None):
        self.kicked.append(ip)
        if self._kick_ok:
            # 真下线：设备从列表里消失（服务端行为）
            self._devices = [d for d in self._devices if d.ip != ip]
            return Result(kind=SUCCESS, raw={}, ip=ip, username=username)
        return Result(kind=UNKNOWN, raw={"error": "sign_error"},
                      ip=ip, username=username)


def make_config(tmpdir, **behavior):
    cfg = Config(path=os.path.join(tmpdir, "config.json"), cipher=FakeCipher())
    cfg.set_credentials("17782817252", "pwd-1234")
    for key, value in behavior.items():
        cfg.set("behavior." + key, value)
    return cfg


def ok_result():
    return Result(kind=SUCCESS, raw={"ploy_msg": "E0000: Login is successful"},
                  ip="10.0.0.9", detail={"confirmed": True})


def full_result():
    return Result(kind=FULL, raw={"ecode": "E2621", "error": "full_error"})


class LoginTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp(prefix="campusnet-svc-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def service(self, client, **behavior):
        return CampusNetService(client, make_config(self.tmp, **behavior),
                                sleep=lambda s: None)

    # -- 正常路径 ------------------------------------------------------
    def test_plain_success(self):
        client = ScriptClient([ok_result()])
        outcome = self.service(client).login()
        self.assertTrue(outcome.ok)
        self.assertEqual(SUCCESS, outcome.kind)
        self.assertEqual([], outcome.kicked)

    def test_already_online_short_circuits(self):
        client = ScriptClient([], state=STATE_ONLINE)
        outcome = self.service(client).login()
        self.assertTrue(outcome.ok)
        self.assertEqual(ALREADY_ONLINE, outcome.kind)
        self.assertEqual(0, client.login_calls)

    def test_ip_taken_by_another_account(self):
        client = ScriptClient([], state=STATE_ONLINE)
        client.local_state = lambda *a, **k: (
            STATE_ONLINE,
            OnlineStatus(online=True, error="ok",
                         raw={"online_ip": "10.0.0.9", "user_name": "someone-else"}),
            [])
        outcome = self.service(client).login()
        self.assertFalse(outcome.ok)
        self.assertEqual("ip_taken", outcome.kind)

    # -- 满员腾位 ------------------------------------------------------
    def test_full_then_kick_oldest_then_login_succeeds(self):
        client = ScriptClient([full_result(), ok_result()], devices=THREE_DEVICES)
        outcome = self.service(client).login()
        self.assertTrue(outcome.ok)
        self.assertEqual([OLDEST.ip], outcome.kicked)
        self.assertEqual([OLDEST.ip], client.kicked)
        self.assertEqual(2, client.login_calls)

    def test_self_is_never_preselected(self):
        devices = [dev("10.0.0.9", "2026-09-01 00:00:00"), OLDEST]  # 本机最老
        client = ScriptClient([full_result(), ok_result()], devices=devices)
        outcome = self.service(client).login()
        self.assertEqual([OLDEST.ip], outcome.kicked)

    def test_kicks_multiple_when_needed(self):
        """第一轮腾一台还不够（又报满员），第二轮继续腾。"""
        client = ScriptClient([full_result(), full_result(), ok_result()],
                              devices=THREE_DEVICES)
        outcome = self.service(client).login()
        self.assertTrue(outcome.ok)
        self.assertEqual([OLDEST.ip, MIDDLE.ip], outcome.kicked)

    def test_user_declines(self):
        client = ScriptClient([full_result()], devices=THREE_DEVICES)
        outcome = self.service(client).login(approve_kick=lambda d, p, ip: [])
        self.assertFalse(outcome.ok)
        self.assertEqual("declined", outcome.kind)
        self.assertEqual([], client.kicked)

    def test_approve_callback_can_pick_a_different_device(self):
        client = ScriptClient([full_result(), ok_result()], devices=THREE_DEVICES)
        outcome = self.service(client).login(
            approve_kick=lambda devices, preselected, my_ip: [MIDDLE.ip])
        self.assertTrue(outcome.ok)
        self.assertEqual([MIDDLE.ip], outcome.kicked)

    def test_approve_callback_receives_preselect_and_my_ip(self):
        seen = {}

        def approve(devices, preselected, my_ip):
            seen["devices"] = [d.ip for d in devices]
            seen["preselected"] = [d.ip for d in preselected]
            seen["my_ip"] = my_ip
            return [preselected[0].ip]

        client = ScriptClient([full_result(), ok_result()], devices=THREE_DEVICES)
        self.service(client).login(approve_kick=approve)
        self.assertEqual(3, len(seen["devices"]))
        self.assertEqual([OLDEST.ip], seen["preselected"])
        self.assertEqual("10.0.0.9", seen["my_ip"])

    def test_kick_failure_is_reported(self):
        client = ScriptClient([full_result()], devices=THREE_DEVICES, kick_ok=False)
        outcome = self.service(client).login()
        self.assertFalse(outcome.ok)
        self.assertEqual("kick_failed", outcome.kind)

    def test_no_devices_to_kick(self):
        client = ScriptClient([full_result()], devices=[])
        outcome = self.service(client).login()
        self.assertFalse(outcome.ok)
        self.assertEqual(FULL, outcome.kind)

    def test_gives_up_after_max_rounds(self):
        client = ScriptClient([full_result()] * 5, devices=THREE_DEVICES)
        outcome = self.service(client).login(max_rounds=2)
        self.assertFalse(outcome.ok)
        self.assertEqual(FULL, outcome.kind)
        self.assertEqual(2, client.login_calls)

    def test_priority_mode_used_when_configured(self):
        cfg_extra = {
            "kick_mode": policy.PRIORITY,
            "devices": [{"alias": "台式机", "priority": 1, "last_ip": OLDEST.ip},
                        {"alias": "备用机", "priority": 3, "last_ip": MIDDLE.ip}],
        }
        client = ScriptClient([full_result(), ok_result()], devices=THREE_DEVICES)
        cfg = make_config(self.tmp)
        cfg.set("behavior.kick_mode", cfg_extra["kick_mode"])
        cfg.set("devices", cfg_extra["devices"])
        outcome = CampusNetService(client, cfg, sleep=lambda s: None).login()
        self.assertEqual([MIDDLE.ip], outcome.kicked)

    def test_signature_error_stops_immediately(self):
        bad = Result(kind=SIGNATURE_ERROR, raw={"error": "sign_error"})
        client = ScriptClient([bad], devices=THREE_DEVICES)
        outcome = self.service(client).login()
        self.assertFalse(outcome.ok)
        self.assertEqual(SIGNATURE_ERROR, outcome.kind)
        self.assertEqual([], client.kicked)
        self.assertEqual(1, client.login_calls)


class LogoutServiceTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp(prefix="campusnet-svc-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    class _Client(object):
        def __init__(self, kind, detail):
            self._kind = kind
            self._detail = detail
            self.calls = []

        def logout_local(self, username, password=None, ip=None, ac_id="1",
                         method="dm", **kwargs):
            self.calls.append(method)
            return Result(kind=self._kind, raw={}, ip="10.0.0.9",
                          username=username, detail=self._detail)

    def test_verified_logout(self):
        client = self._Client(SUCCESS, {"verified": True})
        outcome = CampusNetService(client, make_config(self.tmp), sleep=lambda s: None).logout()
        self.assertTrue(outcome.ok)
        self.assertEqual(["dm"], client.calls)

    def test_already_offline(self):
        client = self._Client(NOT_ONLINE, {})
        outcome = CampusNetService(client, make_config(self.tmp), sleep=lambda s: None).logout()
        self.assertTrue(outcome.ok)
        self.assertEqual(NOT_ONLINE, outcome.kind)

    def test_still_online_is_failure(self):
        client = self._Client(SUCCESS, {"verified": False, "still_online": True})
        outcome = CampusNetService(client, make_config(self.tmp), sleep=lambda s: None).logout()
        self.assertFalse(outcome.ok)
        self.assertIn("又上线", outcome.message)


if __name__ == "__main__":
    unittest.main(verbosity=2)
