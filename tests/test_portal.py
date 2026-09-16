#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""协议解析与判定逻辑测试。

用到的响应样本全部是 Phase 0 实测抓到的真实返回（见 docs/phase0-report.md）。
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from campusnet import errors, models, portal  # noqa: E402
from campusnet import netprobe  # noqa: E402
from campusnet.portal import SrunPortalClient, parse_jsonp  # noqa: E402

# --- 实测样本 ---------------------------------------------------------------

LOGIN_ALREADY_ONLINE = (
    'cb({"ServerFlag":0,"ServicesIntfServerIP":"172.26.8.13","ServicesIntfServerPort":"8001",'
    '"access_token":"3d4debf0","checkout_date":0,"client_ip":"10.128.96.98","ecode":0,'
    '"error":"ok","error_msg":"","online_ip":"10.128.96.98","real_name":"","remain_flux":0,'
    '"remain_times":0,"res":"ok","srun_ver":"SRunCGIAuthIntfSvr V1.18 B20210607",'
    '"suc_msg":"ip_already_online_error","sysver":"1.01.20210607",'
    '"username":"17782817252","wallet_balance":0})'
)

LOGIN_SUCCESS = (
    'cb({"ServerFlag":0,"access_token":"53afb5f1","client_ip":"10.128.96.98","ecode":0,'
    '"error":"ok","error_msg":"","online_ip":"10.128.96.98",'
    '"ploy_msg":"E0000: Login is successful","res":"ok","st":1789488192})'
)

DM_SIGN_ERROR = (
    'cb({"client_ip":"10.128.96.98","ecode":0,"error":"sign_error","error_msg":"",'
    '"online_ip":"10.128.96.98","res":"sign_error","st":1789488139})'
)

DM_SUCCESS = (
    'cb({"client_ip":"10.128.96.98","ecode":0,"error":"ok","error_msg":"",'
    '"online_ip":"10.128.96.98","res":"ok","st":1789488189})'
)

USER_INFO_OFFLINE = (
    'cb({"client_ip":"10.128.96.98","ecode":0,"error":"not_online_error","error_msg":"",'
    '"online_ip":"10.128.96.98","res":"not_online_error","st":1789488190})'
)

USER_INFO_ONLINE = (
    'cb({"ServerFlag":4294967040,"add_time":1789488190,"billing_name":"中国电信校园用户",'
    '"domain":"yx-s-student","error":"ok","online_device_total":"2",'
    '"online_ip":"10.128.96.98","online_ip6":"2001:250:1002:6100::dd5c",'
    '"user_mac":"08:8f:c3:e2:37:57","user_name":"17782817252"})'
)

DEVICE_LIST = (
    '{"code":0,"message":"Success","data":['
    '{"add_time":"2026-09-12 21:50:49","client_type":"1","ip":"10.111.147.127",'
    '"os_name":"Windows 10","user_name":"17782817252"},'
    '{"add_time":"2026-09-16 00:03:10","client_type":"2","ip":"10.128.96.98",'
    '"os_name":"Android 13","user_name":"17782817252"}]}'
)

#: 不带 callback 时服务端返回的调试表单（Phase 0 实测）
HTML_DEBUG_FORM = (
    '\n<html><body>\n<form method="POST" action="/cgi-bin/srun_portal">\n'
    'Name: <input type="text" name="username">\n'
    '<input type="hidden" name="action" value="login">\n'
    '</form>\n<p>SRun Auth Interface Server:SRunCGIAuthIntfSvr V1.18 B20210607</p>\n'
    '</body></html>\n'
)


class ParseJsonpTest(unittest.TestCase):
    def test_strips_callback_wrapper(self):
        self.assertEqual({"error": "ok"}, parse_jsonp('cb({"error":"ok"})'))

    def test_accepts_bare_json(self):
        self.assertEqual({"code": 0}, parse_jsonp('{"code":0}'))

    def test_rejects_html(self):
        self.assertIsNone(parse_jsonp(HTML_DEBUG_FORM))
        self.assertIsNone(parse_jsonp("ok"))
        self.assertIsNone(parse_jsonp(""))

    def test_device_list_is_bare_json(self):
        # /v1/srun_portal_online 返回的是普通 JSON，不是 JSONP
        data = parse_jsonp(DEVICE_LIST)
        self.assertEqual(0, data["code"])
        self.assertEqual(2, len(data["data"]))


class ClassifyTest(unittest.TestCase):
    def test_login_success(self):
        self.assertEqual(models.SUCCESS, portal.classify(parse_jsonp(LOGIN_SUCCESS)))

    def test_login_already_online(self):
        """ecode=0 且 error=ok，但 suc_msg 说明是"已在线"——不能当成登录成功。"""
        raw = parse_jsonp(LOGIN_ALREADY_ONLINE)
        self.assertEqual(0, raw["ecode"])
        self.assertEqual("ok", raw["error"])
        self.assertEqual(models.ALREADY_ONLINE, portal.classify(raw))

    def test_dm_sign_error(self):
        self.assertEqual(models.SIGNATURE_ERROR,
                         portal.classify(parse_jsonp(DM_SIGN_ERROR)))

    def test_dm_success(self):
        self.assertEqual(models.SUCCESS, portal.classify(parse_jsonp(DM_SUCCESS)))

    def test_offline(self):
        self.assertEqual(models.NOT_ONLINE,
                         portal.classify(parse_jsonp(USER_INFO_OFFLINE)))

    def test_html_form_is_unparsed(self):
        self.assertEqual(models.UNPARSED, portal.classify(parse_jsonp(HTML_DEBUG_FORM)))

    def test_none_is_unparsed(self):
        self.assertEqual(models.UNPARSED, portal.classify(None))


class OnlineStatusTest(unittest.TestCase):
    def test_online(self):
        raw = parse_jsonp(USER_INFO_ONLINE)
        status = models.OnlineStatus(online=raw["error"] == "ok", error=raw["error"], raw=raw)
        self.assertTrue(status.online)
        self.assertEqual("10.128.96.98", status.ip)
        self.assertEqual("17782817252", status.user_name)
        self.assertEqual("2", status.device_total)
        self.assertTrue(status.is_me)

    def test_offline(self):
        raw = parse_jsonp(USER_INFO_OFFLINE)
        status = models.OnlineStatus(online=False, error=raw["error"], raw=raw)
        self.assertFalse(status.online)
        self.assertFalse(status.is_me)
        self.assertEqual("not_online_error", status.error)

    def test_state_is_tri_state_not_boolean(self):
        """online=False 不等于离线：被限流时同样是 False，但状态是"未知"。"""
        ok = models.OnlineStatus(online=True, error="ok", raw={})
        off = models.OnlineStatus(online=False, error="not_online_error", raw={})
        limited = models.OnlineStatus(online=False, error="speed_limit_error",
                                      raw={"online_ip": "10.0.0.1"})
        broken = models.OnlineStatus(online=False, error="network_error", raw={})
        self.assertEqual(models.STATE_ONLINE, ok.state)
        self.assertEqual(models.STATE_OFFLINE, off.state)
        self.assertEqual(models.STATE_UNKNOWN, limited.state)
        self.assertEqual(models.STATE_UNKNOWN, broken.state)
        self.assertTrue(limited.rate_limited)
        self.assertFalse(off.rate_limited)

    def test_ip_available_even_in_error_response(self):
        """限流/离线的响应里依然带 online_ip，可以据此判断"我"是谁。"""
        limited = models.OnlineStatus(online=False, error="speed_limit_error",
                                      raw={"online_ip": "10.128.96.98"})
        self.assertEqual("10.128.96.98", limited.ip)


class _StateClient(SrunPortalClient):
    """只替换网络方法，用来测 local_state 的三态兜底逻辑。"""

    def __init__(self, status, devices=None, unreachable=False):
        super().__init__("http://127.0.0.1:9", timeout=0.2)
        self._status = status
        self._devices = devices if devices is not None else []
        self._unreachable = unreachable

    def user_info(self, timeout=None):
        if self._unreachable:
            raise portal.PortalUnreachable("模拟：不在校园网内")
        return self._status

    def online_devices(self, username, password, timeout=None):
        return list(self._devices)


LIMITED = models.OnlineStatus(online=False, error="speed_limit_error",
                              raw={"online_ip": "10.128.96.98"})
DEVICES_WITH_ME = [models.Device(ip="10.128.96.98"), models.Device(ip="10.1.1.1")]
DEVICES_WITHOUT_ME = [models.Device(ip="10.1.1.1")]


class LocalStateTest(unittest.TestCase):
    def test_online_from_user_info(self):
        st = models.OnlineStatus(online=True, error="ok", raw={"online_ip": "1.1.1.1"})
        state, status, devices = _StateClient(st).local_state("u", "p")
        self.assertEqual(models.STATE_ONLINE, state)
        self.assertEqual([], devices)

    def test_offline_from_user_info(self):
        st = models.OnlineStatus(online=False, error="not_online_error",
                                 raw={"online_ip": "1.1.1.1"})
        state, _, _ = _StateClient(st).local_state("u", "p")
        self.assertEqual(models.STATE_OFFLINE, state)

    def test_rate_limited_falls_back_to_device_list_online(self):
        """被限流时用设备列表兜底：本机 IP 在列表里 → 在线。"""
        client = _StateClient(LIMITED, DEVICES_WITH_ME)
        state, status, devices = client.local_state("u", "p")
        self.assertEqual(models.STATE_ONLINE, state)
        self.assertEqual(2, len(devices))

    def test_rate_limited_falls_back_to_device_list_offline(self):
        client = _StateClient(LIMITED, DEVICES_WITHOUT_ME)
        state, _, _ = client.local_state("u", "p")
        self.assertEqual(models.STATE_OFFLINE, state)

    def test_rate_limited_without_credentials_stays_unknown(self):
        state, status, _ = _StateClient(LIMITED, DEVICES_WITH_ME).local_state()
        self.assertEqual(models.STATE_UNKNOWN, state)
        self.assertTrue(status.rate_limited)

    def test_unreachable_portal_is_unknown(self):
        state, status, _ = _StateClient(LIMITED, unreachable=True).local_state("u", "p")
        self.assertEqual(models.STATE_UNKNOWN, state)
        self.assertEqual(models.NETWORK_ERROR, status.error)


class _LogoutClient(SrunPortalClient):
    """测 logout_local 的机制选择与结果确认。"""

    def __init__(self, state_after, kick_kind=models.SUCCESS,
                 portal_kind=models.SUCCESS):
        super().__init__("http://127.0.0.1:9", timeout=0.2)
        self._state_after = state_after
        self._kick_kind = kick_kind
        self._portal_kind = portal_kind
        self.calls = []

    def local_ip(self, username="", timeout=None):
        return "10.128.96.98"

    def kick(self, ip, username, unbind=1, timeout=None):
        self.calls.append(("kick", ip, unbind))
        return models.Result(kind=self._kick_kind, raw={"error": "ok", "res": "ok"},
                             ip=ip, username=username)

    def logout(self, username, ip=None, ac_id="1", timeout=None):
        self.calls.append(("logout", ip))
        return models.Result(kind=self._portal_kind, raw={"error": "ok", "res": "ok"},
                             ip=ip, username=username)

    def wait_state(self, want, timeout=15.0, interval=2.0,
                   username=None, password=None):
        status = models.OnlineStatus(
            online=(self._state_after == models.STATE_ONLINE),
            error="ok" if self._state_after == models.STATE_ONLINE else "not_online_error",
            raw={})
        return self._state_after, status, []


class LogoutLocalTest(unittest.TestCase):
    """实测依据（docs/03-logout-mechanisms.md）：
    action=logout 会被 MAC 免认证立刻抵消；rad_user_dm(unbind=1) 才能真正下线。"""

    def test_default_uses_dm_with_unbind(self):
        client = _LogoutClient(models.STATE_OFFLINE)
        res = client.logout_local("u", password="p")
        self.assertEqual([("kick", "10.128.96.98", 1)], client.calls)
        self.assertEqual(models.SUCCESS, res.kind)
        self.assertTrue(res.detail["verified"])
        self.assertEqual("dm", res.detail["mechanism"])

    def test_portal_method_uses_action_logout(self):
        client = _LogoutClient(models.STATE_OFFLINE)
        res = client.logout_local("u", password="p", method="portal")
        self.assertEqual([("logout", "10.128.96.98")], client.calls)
        self.assertEqual("portal", res.detail["mechanism"])
        self.assertTrue(res.detail["verified"])

    def test_still_online_is_reported_as_unknown(self):
        client = _LogoutClient(models.STATE_ONLINE)
        res = client.logout_local("u", password="p", method="portal")
        self.assertEqual(models.UNKNOWN, res.kind)
        self.assertFalse(res.detail["verified"])
        self.assertTrue(res.detail["still_online"])

    def test_unknown_state_is_not_reported_as_success(self):
        client = _LogoutClient(models.STATE_UNKNOWN)
        res = client.logout_local("u", password="p")
        self.assertEqual(models.UNKNOWN, res.kind)
        self.assertFalse(res.detail["verified"])


class DeviceTest(unittest.TestCase):
    def setUp(self):
        self.devices = [models.Device.from_dict(x)
                        for x in parse_jsonp(DEVICE_LIST)["data"]]

    def test_fields(self):
        d = self.devices[0]
        self.assertEqual("10.111.147.127", d.ip)
        self.assertEqual("PC", d.client_type_label)
        self.assertEqual("Windows 10", d.os_name)

    def test_client_type_label(self):
        self.assertEqual("移动设备或其他", self.devices[1].client_type_label)

    def test_online_seconds_and_text(self):
        import datetime as dt
        d = self.devices[0]
        now = dt.datetime(2026, 9, 16, 0, 3, 10)
        self.assertEqual(3 * 86400 + 2 * 3600 + 12 * 60 + 21, d.online_seconds(now))
        self.assertEqual("3 天 2 小时", d.online_text(now))

    def test_sort_by_add_time_puts_oldest_first(self):
        """满员腾位的默认策略：打勾上线时间最早（= 在线最久）的那台。"""
        ordered = sorted(self.devices, key=lambda d: d.add_time)
        self.assertEqual("10.111.147.127", ordered[0].ip)

    def test_missing_add_time_is_safe(self):
        d = models.Device(ip="1.2.3.4")
        self.assertIsNone(d.online_seconds())
        self.assertEqual("-", d.online_text())


class ErrorsTest(unittest.TestCase):
    def test_table_loaded_from_lang_js(self):
        self.assertGreater(len(errors.TABLE), 200)
        self.assertGreater(len(errors.all_codes()), 100)

    def test_code_lookup(self):
        self.assertEqual("已经在线了", errors.translate("E2620"))
        self.assertEqual("已经达到授权人数", errors.translate("E2621"))
        self.assertIn("间隔太短", errors.translate("E2532"))

    def test_code_with_message_prefix(self):
        self.assertEqual("登录成功", errors.translate("E0000: Login is successful"))

    def test_named_error_lookup(self):
        self.assertEqual("签名错误", errors.translate("sign_error"))
        self.assertEqual("当前设备不在线", errors.translate("not_online_error"))
        self.assertEqual("本机IP已经使用其他账号登陆在线了",
                         errors.translate("ip_already_online_error"))

    def test_message_for_response(self):
        self.assertEqual("签名错误", errors.message_for(parse_jsonp(DM_SIGN_ERROR)))
        self.assertEqual("登录成功（E0000）",
                         errors.message_for(parse_jsonp(LOGIN_SUCCESS)))
        self.assertEqual("当前设备不在线",
                         errors.message_for(parse_jsonp(USER_INFO_OFFLINE)))

    def test_unknown_returns_none(self):
        self.assertIsNone(errors.message_for({"foo": "bar"}))
        self.assertIsNone(errors.message_for(None))


class ClientTest(unittest.TestCase):
    def test_base_url_normalised(self):
        client = SrunPortalClient("http://172.26.8.11/")
        self.assertEqual("http://172.26.8.11", client.base_url)

    def test_unreachable_host_returns_false_not_exception(self):
        client = SrunPortalClient("http://127.0.0.1:9", timeout=0.5)
        self.assertFalse(client.portal_reachable(timeout=0.5))

    def test_result_bool_and_message(self):
        ok = models.Result(kind=models.SUCCESS, raw={"error": "ok", "res": "ok"})
        self.assertTrue(ok)
        self.assertTrue(ok.ok)
        bad = models.Result(kind=models.SIGNATURE_ERROR,
                            raw=parse_jsonp(DM_SIGN_ERROR))
        self.assertFalse(bad)
        self.assertEqual("签名错误", bad.message)


class NetProbeTest(unittest.TestCase):
    def test_local_ip_shape(self):
        ip = netprobe.local_ip()
        self.assertIsInstance(ip, str)
        if ip:
            self.assertEqual(4, len(ip.split(".")))

    def test_unreachable_address_returns_false_not_exception(self):
        # 127.0.0.1 上几乎不可能有服务在监听 9 端口
        self.assertFalse(netprobe.internet_reachable("127.0.0.1", 9, timeout=0.5))


class _FakeClient(SrunPortalClient):
    """把网络层替换成固定结果，用来测 login_and_confirm 的判定逻辑。"""

    def __init__(self, login_result, online_after):
        super().__init__("http://127.0.0.1:9", timeout=0.2)
        self._login_result = login_result
        self._online_after = online_after
        self.wait_calls = 0

    def login(self, *args, **kwargs):
        if isinstance(self._login_result, Exception):
            raise self._login_result
        return self._login_result

    def local_state(self, username=None, password=None, timeout=None):
        state = models.STATE_ONLINE if self._online_after else models.STATE_OFFLINE
        status = models.OnlineStatus(
            online=self._online_after,
            error="ok" if self._online_after else "not_online_error",
            raw={"error": "ok", "online_ip": "1.2.3.4"} if self._online_after else {})
        return state, status, []

    def wait_state(self, want, timeout=15.0, interval=2.0,
                   username=None, password=None):
        self.wait_calls += 1
        return self.local_state()


class LoginAndConfirmTest(unittest.TestCase):
    """登录结果必须以"轮询确认到的实际状态"为准，而不是只看响应。

    实测依据：注销后紧接着从同一 IP 登录时，服务端可能把请求挂起约 60 秒
    （E6504），客户端超时但登录最终成功。
    """

    def test_timeout_but_session_established_becomes_success(self):
        client = _FakeClient(portal.PortalUnreachable("timed out"), online_after=True)
        res = client.login_and_confirm("u", "p")
        self.assertEqual(models.SUCCESS, res.kind)
        self.assertTrue(res.detail["confirmed"])

    def test_success_but_not_online_becomes_unknown(self):
        client = _FakeClient(
            models.Result(kind=models.SUCCESS, raw=parse_jsonp(LOGIN_SUCCESS)),
            online_after=False)
        res = client.login_and_confirm("u", "p")
        self.assertEqual(models.UNKNOWN, res.kind)
        self.assertFalse(res.detail["confirmed"])
        self.assertTrue(res.detail["inconsistent"])

    def test_full_returns_immediately_without_waiting(self):
        full = models.Result(kind=models.FULL,
                             raw={"ecode": "E2621", "error": "full_error"})
        client = _FakeClient(full, online_after=True)
        res = client.login_and_confirm("u", "p")
        self.assertEqual(models.FULL, res.kind)
        self.assertEqual(0, client.wait_calls)

    def test_signature_error_returns_immediately(self):
        bad = models.Result(kind=models.SIGNATURE_ERROR,
                            raw=parse_jsonp(DM_SIGN_ERROR))
        client = _FakeClient(bad, online_after=False)
        res = client.login_and_confirm("u", "p")
        self.assertEqual(models.SIGNATURE_ERROR, res.kind)
        self.assertEqual(0, client.wait_calls)

    def test_success_and_confirmed(self):
        ok = models.Result(kind=models.SUCCESS, raw=parse_jsonp(LOGIN_SUCCESS))
        client = _FakeClient(ok, online_after=True)
        res = client.login_and_confirm("u", "p")
        self.assertTrue(res.ok)
        self.assertTrue(res.detail["confirmed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
