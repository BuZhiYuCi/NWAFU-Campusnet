#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""命令行进程级测试：用真实子进程 + 本地桩门户跑一遍 CLI 契约。

与 test_cli.py 的区别：那些用例是在进程内直接调 cmd_*，这里验证的是
**用户真正拿到的东西**——stdout 是否可被脚本解析、退出码是否正确、编码是否正常。
对应测试计划 TP-CLI-01 ~ TP-CLI-12。
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tests", "support"))

from campusnet.config import Config  # noqa: E402
from campusnet.dpapi import DpapiCipher  # noqa: E402
from fake_portal import FakePortal  # noqa: E402

RUN_CLI = os.path.join(ROOT, "run_cli.py")
USER_INFO = "/cgi-bin/rad_user_info"
ONLINE = "/v1/srun_portal_online"
DM = "/cgi-bin/rad_user_dm"


class CliProcessTest(unittest.TestCase):
    def setUp(self):
        self.portal = FakePortal().start()
        self.addCleanup(self.portal.stop)
        self.tmp = tempfile.mkdtemp(prefix="campusnet-cli-proc-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def make_config(self, username="20230000001", password="pwd-1234"):
        cfg = Config(path=os.path.join(self.tmp, "config.json"),
                     cipher=DpapiCipher())
        if username:
            cfg.set_credentials(username, password)
        cfg.set("portal.base_url", self.portal.base_url)
        cfg.set("portal.timeout_sec", 2)
        cfg.save()
        return cfg.path

    def run_cli(self, *args):
        env = dict(os.environ)
        env.update({
            "CAMPUSNET_CONFIG": os.path.join(self.tmp, "config.json"),
            "CAMPUSNET_LOG_DIR": os.path.join(self.tmp, "logs"),
            "PYTHONIOENCODING": "utf-8",
        })
        return subprocess.run(
            [sys.executable, RUN_CLI] + list(args),
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=60, env=env,
        )

    # -- status --------------------------------------------------------
    def test_status_json_is_parseable(self):
        """TP-CLI-02：status --json 必须能被 json.loads 解析。"""
        self.make_config()
        self.portal.scenario_online(ip="10.0.0.21")
        proc = self.run_cli("status", "--json")
        self.assertEqual(0, proc.returncode, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual("online", data["state"])
        self.assertEqual("10.0.0.21", data["ip"])

    def test_status_json_stays_pure_under_rate_limit(self):
        """TP-CLI-03 / D-01：限流时 stdout 仍必须是纯 JSON（D-02 回归）。

        触发条件比预想的窄：只有在**未配置账号**时，local_state 才会因为限流
        返回 STATE_UNKNOWN 并进入 cmd_status 的"打印提示 + 睡 10 秒"分支；
        有账号时会改用设备列表兜底，走不到这里。
        """
        self.make_config(username="")
        self.portal.scenario_rate_limited(ip="10.0.0.22")
        proc = self.run_cli("status", "--json")
        data = json.loads(proc.stdout)   # 诊断信息必须走 stderr，stdout 只能是 JSON
        self.assertIn("state", data)

    def test_status_offline_exit_code_is_1(self):
        """TP-CLI-05：离线时退出码为 1（业务失败）。"""
        self.make_config()
        self.portal.scenario_offline(ip="10.0.0.23")
        self.portal.json(ONLINE, {"code": 0, "data": []})
        proc = self.run_cli("status")
        self.assertEqual(1, proc.returncode, proc.stdout + proc.stderr)

    # -- 凭据 ----------------------------------------------------------
    def test_status_without_credentials_exit_code_is_1(self):
        """TP-CLI-05b：status 在无凭据时返回 1，与 devices/login 的 2 不一致（记录，P3）。"""
        self.make_config(username="")
        self.portal.jsonp(USER_INFO, {"error": "not_online_error"})
        proc = self.run_cli("status")
        self.assertEqual(1, proc.returncode, proc.stdout + proc.stderr)
        self.assertIn("还没设置账号", proc.stdout)

    def test_devices_without_credentials_exit_code_is_2(self):
        """TP-CLI-05c：devices 在无凭据时属于用法问题，退出码 2。"""
        self.make_config(username="")
        proc = self.run_cli("devices")
        self.assertEqual(2, proc.returncode, proc.stdout + proc.stderr)

    # -- devices -------------------------------------------------------
    def test_devices_json_is_array(self):
        """TP-CLI-04：devices --json 输出裸数组。"""
        self.make_config()
        self.portal.jsonp(USER_INFO, {"error": "ok", "online_ip": "10.0.0.24"})
        self.portal.json(ONLINE, {"code": 0, "data": [
            {"ip": "10.0.0.24", "add_time": "2026-09-12 20:35:39",
             "client_type": "1", "os_name": "Windows 10"},
        ]})
        proc = self.run_cli("devices", "--json")
        self.assertEqual(0, proc.returncode, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertIsInstance(data, list)
        self.assertEqual("10.0.0.24", data[0]["ip"])

    # -- kick ----------------------------------------------------------
    def test_kick_already_offline_is_treated_as_success(self):
        """TP-CLI-08 / D-02：踢一台本来就不在线的设备应视为成功（D-02 回归）。"""
        self.make_config()
        self.portal.jsonp(USER_INFO, {"error": "ok", "online_ip": "10.0.0.25"})
        self.portal.jsonp(DM, {"error": "E6527", "error_msg": "当前设备不在线"})
        proc = self.run_cli("kick", "10.0.0.99")
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
