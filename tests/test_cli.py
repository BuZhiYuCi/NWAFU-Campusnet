#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""命令行工具测试：用假门户客户端驱动，不发任何真实请求。"""

import base64
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from campusnet import cli, models  # noqa: E402
from campusnet.portal import PortalUnreachable  # noqa: E402


class FakeCipher(object):
    name = "fake"

    def encrypt(self, plaintext):
        return "fake:" + base64.b64encode(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, token):
        return base64.b64decode(token[len("fake:"):]).decode("utf-8")


class FakeClient(object):
    """可编程的假客户端。"""

    def __init__(self, reachable=True, status=None, devices=None,
                 login_result=None, login_results=None, logout_result=None,
                 kick_result=None):
        self._reachable = reachable
        self._status = status or models.OnlineStatus(
            online=False, error="not_online_error", raw={})
        self._devices = devices or []
        self._login_results = list(login_results) if login_results else None
        self._login_result = login_result
        self._logout_result = (logout_result if logout_result is not None
                               else models.Result(kind=models.NOT_ONLINE,
                                                  raw={"error": "not_online_error"}))
        self._kick_result = (kick_result if kick_result is not None
                             else models.Result(kind=models.SUCCESS,
                                                raw={"error": "ok", "res": "ok"}))
        self.calls = []

    base_url = "http://172.26.8.11"

    def portal_reachable(self):
        return self._reachable

    def user_info(self):
        return self._status

    def local_state(self, username=None, password=None, timeout=None):
        if not self._reachable:
            raise PortalUnreachable("模拟：不在校园网内")
        state = (models.STATE_ONLINE if self._status.online
                 else models.STATE_OFFLINE)
        return state, self._status, list(self._devices)

    def online_devices(self, username, password):
        return list(self._devices)

    def login_and_confirm(self, *args, **kwargs):
        self.calls.append("login")
        if self._login_results:
            return self._login_results.pop(0)
        return self._login_result

    def logout(self, *args, **kwargs):
        self.calls.append("logout")
        return self._logout_result

    def logout_local(self, username, password=None, ip=None, ac_id="1",
                     method="dm", **kwargs):
        self.calls.append(("logout_local", method))
        return self._logout_result

    def kick(self, ip, username, **kwargs):
        self.calls.append(("kick", ip))
        res = self._kick_result
        if res is not None and res.ip is None:
            import dataclasses
            res = dataclasses.replace(res, ip=ip, username=username)
        return res

    def wait_state(self, want, timeout=15, interval=2.0,
                   username=None, password=None):
        # 模拟"成功达到目标状态"
        status = models.OnlineStatus(online=(want == models.STATE_ONLINE),
                                     error="", raw={})
        return want, status, []


def device_list():
    return [
        models.Device.from_dict({"ip": "10.111.147.127", "client_type": "1",
                                 "os_name": "Windows 10",
                                 "add_time": "2026-09-12 21:50:49",
                                 "user_name": "u"}),
        models.Device.from_dict({"ip": "10.128.96.98", "client_type": "1",
                                 "os_name": "Windows 10",
                                 "add_time": "2026-09-16 00:11:26",
                                 "user_name": "u"}),
    ]


ONLINE_STATUS = models.OnlineStatus(
    online=True, error="ok",
    raw={"error": "ok", "online_ip": "10.128.96.98", "user_name": "20230000001",
         "user_mac": "08:8f:c3:e2:37:57", "online_device_total": "2"})


class CliTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="campusnet-cli-")
        self.config_path = os.path.join(self.tmp, "config.json")
        self.cipher = FakeCipher()
        os.environ["CAMPUSNET_CONFIG"] = self.config_path
        os.environ["CAMPUSNET_LOG_DIR"] = os.path.join(self.tmp, "logs")

    def tearDown(self):
        os.environ.pop("CAMPUSNET_CONFIG", None)
        os.environ.pop("CAMPUSNET_LOG_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_credentials(self, username="20230000001", password="pwd-1234"):
        cfg = cli.cfgmod.Config(path=self.config_path, cipher=self.cipher)
        cfg.set_credentials(username, password)
        cfg.save()

    def run_cli(self, argv, client):
        out, err = io.StringIO(), io.StringIO()
        fake_stdin = io.StringIO("")
        real_stdin = sys.stdin
        sys.stdin = fake_stdin          # isatty() -> False，避免触发交互式向导
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = cli.main(argv, make_client=lambda cfg: client,
                                cipher=self.cipher)
        finally:
            sys.stdin = real_stdin
        return code, out.getvalue(), err.getvalue()


class RenderingTest(unittest.TestCase):
    def test_display_width_counts_cjk_as_two(self):
        self.assertEqual(2, cli._w("ab"))
        self.assertEqual(4, cli._w("中文"))
        self.assertEqual(4, cli._w("a中b"))

    def test_render_devices_is_aligned(self):
        text = cli.render_devices(device_list(), my_ip="10.128.96.98")
        lines = text.splitlines()
        self.assertIn("IP", lines[0])
        self.assertIn("10.111.147.127", text)
        self.assertIn("本机", text)
        # 表头与分隔线、以及在排序后最早上线的那台排第一
        self.assertLess(lines[0].index("IP"), len(lines[0]))
        self.assertIn("10.111.147.127", lines[2])
        self.assertIn("10.128.96.98", lines[3])

    def test_render_empty(self):
        self.assertEqual("（没有在线设备）", cli.render_devices([]))

    def test_device_dicts_marks_local_and_sorts(self):
        rows = cli.device_dicts(device_list(), my_ip="10.128.96.98")
        self.assertEqual("10.111.147.127", rows[0]["ip"])
        self.assertFalse(rows[0]["is_local"])
        self.assertTrue(rows[1]["is_local"])
        self.assertIn("online_text", rows[0])


class ParserTest(unittest.TestCase):
    def test_no_command_prints_help(self):
        code, out, _ = self._run([])
        self.assertEqual(cli.EXIT_USAGE, code)
        self.assertIn("status", out)

    def test_unknown_command_exits_two(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                cli.build_parser().parse_args(["nope"])
        self.assertEqual(2, ctx.exception.code)

    def test_kick_requires_ip(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                cli.build_parser().parse_args(["kick"])

    def test_kick_accepts_multiple_ips(self):
        args = cli.build_parser().parse_args(["kick", "1.1.1.1", "2.2.2.2"])
        self.assertEqual(["1.1.1.1", "2.2.2.2"], args.ips)

    def test_version_prints_package_version(self):
        # 打包后的 exe 必须能自报版本，否则用户无法确认装的是哪一版。
        import campusnet
        out = io.StringIO()
        with redirect_stdout(out):
            with self.assertRaises(SystemExit) as ctx:
                cli.build_parser().parse_args(["--version"])
        self.assertEqual(0, ctx.exception.code)
        self.assertIn(campusnet.__version__, out.getvalue())

    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(argv, make_client=lambda cfg: FakeClient(),
                            cipher=FakeCipher())
        return code, out.getvalue(), err.getvalue()


class StatusTest(CliTestBase):
    def test_online_returns_zero(self):
        self.write_credentials()
        client = FakeClient(status=ONLINE_STATUS, devices=device_list())
        code, out, _ = self.run_cli(["status"], client)
        self.assertEqual(cli.EXIT_OK, code)
        self.assertIn("已在线", out)
        self.assertIn("10.111.147.127", out)

    def test_offline_returns_one(self):
        self.write_credentials()
        client = FakeClient()
        code, out, _ = self.run_cli(["status"], client)
        self.assertEqual(cli.EXIT_FAIL, code)
        self.assertIn("未登录", out)

    def test_not_on_campus_returns_one(self):
        self.write_credentials()
        code, _, err = self.run_cli(["status"], FakeClient(reachable=False))
        self.assertEqual(cli.EXIT_FAIL, code)
        self.assertIn("不在校园网", err)

    def test_json_output_is_parseable(self):
        self.write_credentials()
        client = FakeClient(status=ONLINE_STATUS, devices=device_list())
        code, out, _ = self.run_cli(["status", "--json"], client)
        data = json.loads(out)
        self.assertTrue(data["online"])
        self.assertEqual("10.128.96.98", data["ip"])
        self.assertEqual(2, len(data["devices"]))

    def test_status_without_credentials_still_works(self):
        client = FakeClient(status=ONLINE_STATUS)
        code, out, _ = self.run_cli(["status"], client)
        self.assertEqual(cli.EXIT_OK, code)
        self.assertIn("已在线", out)
        self.assertIn("settings", out)   # 提示去设置账号


class LoginTest(CliTestBase):
    def test_login_success(self):
        self.write_credentials()
        ok = models.Result(kind=models.SUCCESS, raw={"ploy_msg": "E0000: ok"},
                           ip="10.128.96.98")
        code, out, err = self.run_cli(["login"], FakeClient(login_result=ok))
        self.assertEqual(cli.EXIT_OK, code)
        self.assertIn("登录成功", out)
        # D-14：登录成功时不能顺带打印"在线数已满需要腾位"
        self.assertNotIn("腾位", err)
        self.assertNotIn("腾位", out)

    def test_login_already_online_is_success(self):
        self.write_credentials()
        res = models.Result(kind=models.ALREADY_ONLINE, raw={})
        code, out, _ = self.run_cli(["login"], FakeClient(login_result=res))
        self.assertEqual(cli.EXIT_OK, code)
        self.assertIn("已经在线", out)

    def test_login_when_not_logged_in_locally_short_circuits(self):
        """本机已在线时不该重复发登录请求。"""
        self.write_credentials()
        client = FakeClient(status=ONLINE_STATUS)
        code, out, _ = self.run_cli(["login"], client)
        self.assertEqual(cli.EXIT_OK, code)
        self.assertIn("已经在线了", out)
        self.assertEqual([], client.calls)

    def test_login_full_noninteractive_refuses_to_kick_blindly(self):
        """非交互环境下不擅自踢设备，明确要求加 --yes。"""
        self.write_credentials()
        res = models.Result(kind=models.FULL,
                            raw={"ecode": "E2621", "error": "full_error"})
        client = FakeClient(login_result=res, devices=device_list())
        code, _, err = self.run_cli(["login"], client)
        self.assertEqual(cli.EXIT_FAIL, code)
        self.assertIn("--yes", err)
        self.assertIn("已取消", err)
        self.assertEqual([], [c for c in client.calls if isinstance(c, tuple)])

    def test_login_full_with_yes_kicks_oldest_then_succeeds(self):
        self.write_credentials()
        full = models.Result(kind=models.FULL, raw={"ecode": "E2621"})
        ok = models.Result(kind=models.SUCCESS, raw={"ploy_msg": "E0000: ok"},
                           ip="10.128.96.98", detail={"confirmed": True})
        client = FakeClient(login_results=[full, ok], devices=device_list())
        code, out, _ = self.run_cli(["login", "--yes"], client)
        self.assertEqual(cli.EXIT_OK, code)
        self.assertIn("已腾出名额", out)
        self.assertIn("10.111.147.127", out)   # 上线最早的那台
        self.assertIn("登录成功", out)

    def test_login_full_with_no_free_declines(self):
        self.write_credentials()
        full = models.Result(kind=models.FULL, raw={"ecode": "E2621"})
        client = FakeClient(login_result=full, devices=device_list())
        code, _, err = self.run_cli(["login", "--no-free"], client)
        self.assertEqual(cli.EXIT_FAIL, code)
        self.assertIn("已取消", err)

    def test_login_rejected_credentials(self):
        self.write_credentials()
        res = models.Result(kind=models.SIGNATURE_ERROR, raw={"error": "sign_error"})
        code, _, err = self.run_cli(["login"], FakeClient(login_result=res))
        self.assertEqual(cli.EXIT_FAIL, code)
        self.assertIn("账号密码", err)

    def test_login_without_credentials_is_usage_error(self):
        code, _, err = self.run_cli(["login"], FakeClient())
        self.assertEqual(cli.EXIT_USAGE, code)
        self.assertIn("settings", err)

    def test_login_when_ip_taken_by_other_account(self):
        self.write_credentials()
        status = models.OnlineStatus(
            online=True, error="ok",
            raw={"error": "ok", "online_ip": "10.0.0.5", "user_name": "someone-else"})
        code, _, err = self.run_cli(["login"], FakeClient(status=status))
        self.assertEqual(cli.EXIT_FAIL, code)
        self.assertIn("其它账号", err)


class LogoutTest(CliTestBase):
    def test_logout_success(self):
        self.write_credentials()
        res = models.Result(kind=models.SUCCESS, raw={"error": "ok", "res": "ok"},
                            detail={"verified": True})
        client = FakeClient(status=ONLINE_STATUS, logout_result=res)
        code, out, _ = self.run_cli(["logout"], client)
        self.assertEqual(cli.EXIT_OK, code)
        self.assertIn("已下线", out)
        self.assertEqual([("logout_local", "dm")], client.calls)

    def test_logout_when_already_offline(self):
        self.write_credentials()
        code, out, _ = self.run_cli(["logout"], FakeClient())
        self.assertEqual(cli.EXIT_OK, code)
        self.assertIn("已经是离线状态", out)

    def test_logout_uses_configured_method(self):
        """默认用 dm（能真正下线）；配置里可以退回 portal。"""
        cfg = cli.cfgmod.Config(path=self.config_path, cipher=self.cipher)
        cfg.set_credentials("20230000001", "pwd-1234")
        cfg.set("behavior.logout_method", "portal")
        cfg.save()
        res = models.Result(kind=models.SUCCESS, raw={},
                            detail={"verified": False, "still_online": True})
        client = FakeClient(logout_result=res)
        code, _, err = self.run_cli(["logout"], client)
        self.assertEqual(cli.EXIT_FAIL, code)
        self.assertIn(("logout_local", "portal"), client.calls)
        self.assertIn("MAC", err)

    def test_logout_not_verified_reports_failure(self):
        self.write_credentials()
        res = models.Result(kind=models.UNKNOWN, raw={},
                            detail={"verified": False, "still_online": True})
        code, _, err = self.run_cli(["logout"], FakeClient(logout_result=res))
        self.assertEqual(cli.EXIT_FAIL, code)
        self.assertIn("仍在设备列表里", err)


class KickTest(CliTestBase):
    def test_kick_multiple(self):
        self.write_credentials()
        res = models.Result(kind=models.SUCCESS, raw={"error": "ok", "res": "ok"})
        client = FakeClient(kick_result=res, devices=device_list())
        code, out, _ = self.run_cli(["kick", "10.1.1.1", "10.2.2.2"], client)
        self.assertEqual(cli.EXIT_OK, code)
        self.assertIn(("kick", "10.1.1.1"), client.calls)
        self.assertIn(("kick", "10.2.2.2"), client.calls)
        self.assertEqual(2, out.count("已下线"))

    def test_kick_failure_returns_one(self):
        self.write_credentials()
        res = models.Result(kind=models.UNKNOWN,
                            raw={"error": "sign_error"})
        code, _, err = self.run_cli(["kick", "10.1.1.1"],
                                    FakeClient(kick_result=res))
        self.assertEqual(cli.EXIT_FAIL, code)
        self.assertIn("失败", err)

    def test_kick_not_online_counts_as_success(self):
        """D-02：目标本来就不在线 = 目标状态已达成，必须算成功。

        否则同一次操作 CLI 报失败、GUI（service 的腾位逻辑）报成功，
        用户没法判断到底成没成。
        """
        self.write_credentials()
        res = models.Result(kind=models.NOT_ONLINE,
                            raw={"error": "not_online_error"})
        code, out, err = self.run_cli(["kick", "10.1.1.1"],
                                      FakeClient(kick_result=res))
        self.assertEqual(cli.EXIT_OK, code)
        self.assertIn("原本就不在线", out)


class SettingsTest(CliTestBase):
    def test_show_without_credentials(self):
        code, out, _ = self.run_cli(["settings", "--show"], FakeClient())
        self.assertEqual(cli.EXIT_OK, code)
        self.assertIn("未设置", out)

    def test_set_via_flags(self):
        code, out, _ = self.run_cli(
            ["settings", "--username", "u123", "--password", "pw-abcdef"], FakeClient())
        self.assertEqual(cli.EXIT_OK, code)
        cfg = cli.cfgmod.Config(path=self.config_path, cipher=self.cipher).load()
        self.assertEqual("u123", cfg.username)
        self.assertEqual("pw-abcdef", cfg.get_password())
        with open(self.config_path, "r", encoding="utf-8") as f:
            self.assertNotIn("pw-abcdef", f.read())

    def test_json_view_never_contains_password(self):
        self.write_credentials(password="top-secret-pw")
        code, out, _ = self.run_cli(["settings", "--json"], FakeClient())
        self.assertEqual(cli.EXIT_OK, code)
        data = json.loads(out)
        self.assertTrue(data["password_saved"])
        self.assertNotIn("top-secret-pw", out)

    def test_clear_password(self):
        self.write_credentials()
        code, out, _ = self.run_cli(["settings", "--clear-password"], FakeClient())
        self.assertEqual(cli.EXIT_OK, code)
        cfg = cli.cfgmod.Config(path=self.config_path, cipher=self.cipher).load()
        self.assertIsNone(cfg.get_password())

    def test_username_change_does_not_silently_wipe_undecryptable_password(self):
        """D-06b：密文解不开时只改账号，不能把密码悄悄清掉还报"已保存"。"""
        self.write_credentials(username="old-user", password="pw-1234")

        class Broken(FakeCipher):
            def decrypt(self, token):
                raise cli.cfgmod.DpapiError("模拟换机器后解不开")

        self.cipher = Broken()
        code, _, err = self.run_cli(["settings", "--username", "new-user"],
                                    FakeClient())
        self.assertEqual(cli.EXIT_FAIL, code)
        self.assertIn("解不开", err)
        cfg = cli.cfgmod.Config(path=self.config_path,
                                cipher=FakeCipher()).load()
        self.assertEqual("old-user", cfg.username, "失败时不应改动任何东西")
        self.assertTrue(cfg.get("portal.password_dpapi"), "密文必须保留")

    def test_empty_password_rejected(self):
        code, _, err = self.run_cli(
            ["settings", "--username", "u", "--password", ""], FakeClient())
        self.assertEqual(cli.EXIT_USAGE, code)
        self.assertIn("清除", err)


class AutostartTest(CliTestBase):
    """开机自启命令（注册表用内存版替换，不碰真实系统设置）。"""

    def setUp(self):
        super(AutostartTest, self).setUp()
        self.reg = {}
        self._orig = (cli.autostart.current_command, cli.autostart.enable,
                      cli.autostart.disable)
        cli.autostart.current_command = lambda: self.reg.get("cmd")
        cli.autostart.enable = lambda silent=False: self.reg.setdefault(
            "cmd", '"pythonw" "run_gui.pyw"%s' % (" --tray" if silent else ""))
        cli.autostart.disable = lambda: (self.reg.pop("cmd", None) is not None)

    def tearDown(self):
        (cli.autostart.current_command, cli.autostart.enable,
         cli.autostart.disable) = self._orig
        super(AutostartTest, self).tearDown()

    def test_status_when_off(self):
        code, out, _ = self.run_cli(["autostart"], FakeClient())
        self.assertEqual(cli.EXIT_OK, code)
        self.assertIn("未开启", out)
        self.assertIn("不会自动认证", out)

    def test_off_reports_failure_when_registry_entry_survives(self):
        """D-12：注册表项没删掉时不能打印"已关闭"。

        用户会以为关掉了，实际下次开机照样自启，而且配置文件里还被写成 false。
        """
        code, _, _ = self.run_cli(["autostart", "on"], FakeClient())
        self.assertEqual(cli.EXIT_OK, code)
        cfg = cli.cfgmod.Config(path=self.config_path, cipher=self.cipher).load()
        self.assertTrue(cfg.get("startup.autostart"))

        cli.autostart.disable = lambda: False      # 删除失败，条目还在
        code, out, err = self.run_cli(["autostart", "off"], FakeClient())
        self.assertEqual(cli.EXIT_FAIL, code)
        self.assertIn("关闭失败", err)
        self.assertNotIn("已关闭开机自启", out)
        cfg = cli.cfgmod.Config(path=self.config_path, cipher=self.cipher).load()
        self.assertTrue(cfg.get("startup.autostart"),
                        "失败时不能把配置写成已关闭")

    def test_on_then_status_then_off(self):
        code, out, _ = self.run_cli(["autostart", "on"], FakeClient())
        self.assertEqual(cli.EXIT_OK, code)
        self.assertIn("已开启", out)
        self.assertIn("run_gui.pyw", out)
        self.assertIn("cmd", self.reg)

        code, out, _ = self.run_cli(["autostart", "status"], FakeClient())
        self.assertIn("已开启", out)

        code, out, _ = self.run_cli(["autostart", "off"], FakeClient())
        self.assertEqual(cli.EXIT_OK, code)
        self.assertIn("已关闭", out)
        self.assertNotIn("cmd", self.reg)

    def test_on_honours_silent_setting(self):
        cfg = cli.cfgmod.Config(path=self.config_path, cipher=self.cipher)
        cfg.set("startup.silent_when_autostart", True)
        cfg.save()
        self.run_cli(["autostart", "on"], FakeClient())
        self.assertIn("--tray", self.reg["cmd"])

    def test_on_records_flag_in_config(self):
        self.run_cli(["autostart", "on"], FakeClient())
        reloaded = cli.cfgmod.Config(path=self.config_path,
                                     cipher=self.cipher).load()
        self.assertTrue(reloaded.get("startup.autostart"))

    def test_unexpected_registry_error_is_reported(self):
        def boom(silent=False):
            raise OSError("拒绝访问")
        cli.autostart.enable = boom
        code, _, err = self.run_cli(["autostart", "on"], FakeClient())
        self.assertEqual(cli.EXIT_FAIL, code)
        self.assertIn("注册表", err)


if __name__ == "__main__":
    unittest.main(verbosity=2)
