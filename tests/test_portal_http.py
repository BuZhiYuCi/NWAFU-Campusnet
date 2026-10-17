#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""协议层 HTTP 交互测试（本地桩门户，不发任何真实请求）。

对应测试计划 docs/04-test-plan.md 的 TP-PTL-01 ~ TP-PTL-14。
这是本轮补强重点：此前 `_request` / 超时 / HTTPError / 非 JSONP 降级全无覆盖。
"""

import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tests", "support"))

from campusnet import models  # noqa: E402
from campusnet.portal import (SrunPortalClient, PortalUnreachable,  # noqa: E402
                              classify, parse_jsonp)
from fake_portal import FakePortal  # noqa: E402

USER_INFO = "/cgi-bin/rad_user_info"
ONLINE = "/v1/srun_portal_online"
CHALLENGE = "/cgi-bin/get_challenge"
LOGIN = "/cgi-bin/srun_portal"


class PortalHttpTest(unittest.TestCase):
    def setUp(self):
        self.portal = FakePortal().start()
        self.addCleanup(self.portal.stop)
        self._env_backup = {k: os.environ.get(k) for k in
                            ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        for key, value in self._env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def client(self, timeout=0.5):
        return SrunPortalClient(base_url=self.portal.base_url, timeout=timeout)

    def _prepare_login(self, payload, status=200):
        """给 login() 铺好前置：token 接口 + 登录接口的固定应答。"""
        self.portal.jsonp(CHALLENGE, {"challenge": "a" * 64,
                                      "client_ip": "10.0.0.9", "expire": "60"})
        self.portal.jsonp(LOGIN, payload, status=status)
        return self

    # -- 解析 ----------------------------------------------------------
    def test_jsonp_body_is_parsed(self):
        """TP-PTL-01：标准 cb({...}) 能被解析。"""
        self.portal.scenario_online(ip="10.0.0.7")
        status = self.client().user_info()
        self.assertTrue(status.online)
        self.assertEqual("10.0.0.7", status.ip)
        self.assertEqual(models.STATE_ONLINE, status.state)

    def test_plain_json_body_is_parsed(self):
        """TP-PTL-02：裸 JSON 也能解析（设备列表接口就是裸 JSON）。"""
        self.portal.json(ONLINE, {"code": 0, "data": [
            {"ip": "10.0.0.8", "add_time": "2026-09-12 20:35:39"}]})
        devices = self.client().online_devices("20230000001", "pwd")
        self.assertEqual(["10.0.0.8"], [d.ip for d in devices])

    def test_html_body_falls_back_to_unparsed(self):
        """TP-PTL-03：门户拦截返回 HTML 时判 UNPARSED，不抛异常。"""
        self.portal.raw(USER_INFO, "<!DOCTYPE html><html>login</html>")
        status = self.client().user_info()
        self.assertFalse(status.online)
        self.assertEqual(models.UNPARSED, status.error)

    def test_bom_prefixed_body_falls_back_to_unparsed(self):
        """TP-PTL-04：带 BOM 的 JSONP 解析不了（已知限制 D-14，P3）。"""
        self.portal.raw(USER_INFO, '\ufeffcb({"error":"ok","online_ip":"10.0.0.9"})')
        self.assertIsNone(parse_jsonp('\ufeffcb({"a":1})'))
        self.assertEqual(models.UNPARSED, self.client().user_info().error)

    def test_try_wrapped_jsonp_falls_back_to_unparsed(self):
        """TP-PTL-05：try{cb(...)}catch{} 包裹解析不了（已知限制 D-14，P3）。"""
        body = 'try{cb({"error":"ok"})}catch(e){}'
        self.portal.raw(USER_INFO, body)
        self.assertIsNone(parse_jsonp(body))
        self.assertEqual(models.UNPARSED, self.client().user_info().error)

    def test_empty_body_falls_back_to_unparsed(self):
        """TP-PTL-11：空响应体不抛异常。"""
        self.portal.set(USER_INFO, "")
        self.assertEqual(models.UNPARSED, self.client().user_info().error)

    def test_non_utf8_body_does_not_crash(self):
        """TP-PTL-13：GBK 等非 UTF-8 响应不会崩在解码上。"""
        self.portal.raw(USER_INFO, "中文门户".encode("gbk"))
        self.assertEqual(models.UNPARSED, self.client().user_info().error)

    def test_large_html_body_does_not_crash(self):
        """TP-PTL-12：1MB HTML 也能被安全丢弃。"""
        self.portal.raw(USER_INFO, "<html>" + "x" * (1024 * 1024) + "</html>")
        self.assertEqual(models.UNPARSED, self.client().user_info().error)

    # -- HTTP 语义 ------------------------------------------------------
    def test_http_403_body_is_read_without_raising(self):
        """HTTPError 分支：4xx 也要把 body 读出来，供错误码解析。"""
        self.portal.raw(USER_INFO, 'cb({"error":"E2620"})', status=403)
        resp = self.client()._request(USER_INFO)
        self.assertEqual(403, resp.status)
        self.assertEqual("E2620", resp.parsed["error"])

    def test_http_5xx_with_json_body_is_not_treated_as_business_result(self):
        """TP-PTL-06 / D-11：5xx 响应体长得像正常 JSON，也不能当成在线。"""
        self.portal.json(USER_INFO, {"error": "ok", "online_ip": "10.0.0.10"},
                         status=500)
        status = self.client().user_info()
        self.assertNotEqual(models.STATE_ONLINE, status.state)

    def test_5xx_is_classified_as_server_error(self):
        """D-11：5xx 单独归类为 SERVER_ERROR，而不是"登录失败/在线数已满"。"""
        self._prepare_login({"ecode": "E2621", "error": "full_error"}, status=502)
        res = self.client().login("20230000001", "pwd", ip="10.0.0.9")
        self.assertEqual(models.SERVER_ERROR, res.kind)
        self.assertEqual(502, res.http_status)

    def test_e2620_is_already_online_not_full(self):
        """D-11：「已经在线了」必须归为 ALREADY_ONLINE。

        误判成 FULL 会触发上层"腾位"流程，去踢掉一台设备——
        而此刻真正在线的很可能就是用户自己的机器。
        """
        self._prepare_login({"ecode": "E2620", "ploy_msg": "E2620: 已经在线了"})
        res = self.client().login("20230000001", "pwd", ip="10.0.0.9")
        self.assertEqual(models.ALREADY_ONLINE, res.kind)

    def test_e2621_and_e6512_are_full(self):
        """E2621「已达授权人数」/ E6512「在线用户已满」才是真的满员。"""
        for code in ("E2621", "E6512"):
            self._prepare_login({"ploy_msg": "%s: 满员" % code})
            res = self.client().login("20230000001", "pwd", ip="10.0.0.9")
            self.assertEqual(models.FULL, res.kind, code)

    def test_redirect_is_followed(self):
        """TP-PTL-07：302 能被跟随到最终 JSONP。"""
        self.portal.set(USER_INFO, "", status=302,
                        headers={"Location": "/portal/login"})
        self.portal.jsonp("/portal/login", {"error": "ok", "online_ip": "10.0.0.11"})
        self.assertTrue(self.client().user_info().online)
        self.assertTrue(self.portal.hits("/portal/login"))

    # -- 超时 ----------------------------------------------------------
    def test_slow_response_raises_portal_unreachable(self):
        """TP-PTL-08：超过客户端超时必须抛 PortalUnreachable，且不拖太久。"""
        self.portal.jsonp(USER_INFO, {"error": "ok"}, delay=1.5)
        started = time.time()
        with self.assertRaises(PortalUnreachable):
            self.client(timeout=0.3).user_info()
        self.assertLess(time.time() - started, 1.2, "超时没有生效")

    def test_timeout_zero_falls_back_to_client_timeout(self):
        """TP-PTL-08b：`timeout or self.timeout` 让 0 退化成默认值（记录该语义）。"""
        self.portal.jsonp(USER_INFO, {"error": "ok"}, delay=0.6)
        resp = self.client(timeout=2.0)._request(USER_INFO, timeout=0)
        self.assertIsNotNone(resp.parsed, "timeout=0 应回退到 self.timeout 而非立即超时")

    # -- 网络环境 ------------------------------------------------------
    def test_proxy_env_is_ignored(self):
        """TP-PTL-10：门户在内网，必须绕过系统代理。"""
        os.environ["http_proxy"] = "http://127.0.0.1:1"
        os.environ["HTTP_PROXY"] = "http://127.0.0.1:1"
        self.portal.jsonp(USER_INFO, {"error": "ok", "online_ip": "10.0.0.12"})
        self.assertTrue(self.client().user_info().online)

    def test_portal_reachable_false_for_html(self):
        """TP-PTL-03b：返回 HTML 时 portal_reachable() 必须为 False。"""
        self.portal.raw(USER_INFO, "<html>portal</html>")
        self.assertFalse(self.client().portal_reachable())

    # -- 限流 ----------------------------------------------------------
    def test_rate_limited_response_enters_cooldown(self):
        """TP-STS-03：限流响应必须进入冷却，且改用设备列表兜底。"""
        self.portal.scenario_rate_limited(ip="10.0.0.13")
        self.portal.json(ONLINE, {"code": 0, "data": [
            {"ip": "10.0.0.13", "add_time": "2026-09-12 20:35:39"}]})
        client = self.client()
        state, status, devices = client.local_state("20230000001", "pwd")
        self.assertGreater(client._rate_limited_until, 0, "限流后应设置冷却")
        self.assertEqual(models.STATE_ONLINE, state, "冷却期应改用设备列表判定")
        self.assertEqual(1, len(devices))

    def test_synthetic_status_is_marked(self):
        """D-05：设备列表兜底推断出的状态必须打 synthetic 标记。

        没有这个标记，上层就无法区分"服务端说在线"和"我们从设备列表猜在线"，
        会把猜出来的状态当成事实，进而误报"已经在线"跳过真正的登录。
        """
        self.portal.scenario_rate_limited(ip="10.0.0.13")
        self.portal.json(ONLINE, {"code": 0, "data": [
            {"ip": "10.0.0.13", "add_time": "2026-09-12 20:35:39"}]})
        state, status, _ = self.client().local_state("20230000001", "pwd")
        self.assertEqual(models.STATE_ONLINE, state)
        self.assertTrue(status.raw.get("synthetic"), "必须标记为合成状态")
        self.assertEqual("device_list", status.raw.get("source"))
        self.assertTrue(status.online, "online 应与推断出的 state 一致")

    def test_successful_login_resets_rate_limit_cooldown(self):
        """D-05：登录成功必须作废限流冷却，否则刚上线就可能被判离线。"""
        self.portal.jsonp(CHALLENGE, {"challenge": "a" * 64,
                                      "client_ip": "10.0.0.9", "expire": "60"})
        self.portal.jsonp(LOGIN, {"ecode": "0", "error": "ok",
                                  "suc_msg": "login_success"})
        self.portal.jsonp(USER_INFO, {"error": "ok", "online_ip": "10.0.0.9",
                                      "user_name": "20230000001"})
        self.portal.json(ONLINE, {"code": 0, "data": [
            {"ip": "10.0.0.9", "add_time": "2026-09-12 20:35:39"}]})
        client = self.client()
        client._rate_limited_until = time.time() + 60      # 模拟之前撞上的限流
        res = client.login_and_confirm("20230000001", "pwd", ip="10.0.0.9",
                                       confirm_timeout=3.0)
        self.assertEqual(0.0, client._rate_limited_until, "冷却必须被重置")
        self.assertEqual(models.SUCCESS, res.kind)

    def test_classify_ignores_http_status(self):
        """D-11 记录：classify 只看 body，不看 HTTP 状态码。"""
        self.assertEqual(models.SUCCESS, classify({"error": "ok", "ecode": "0"}))


if __name__ == "__main__":
    unittest.main()
