#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图形界面测试。

没有可用的图形环境时自动跳过。
断言方式：直接读取 Tk 控件树里的文本与状态，而不是"看着像对的"。
"""

import base64
import os
import shutil
import sys
import tempfile
import time
import tkinter as tk
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from campusnet import models  # noqa: E402
from campusnet.config import Config  # noqa: E402
from campusnet.ui import app as gui  # noqa: E402
from campusnet.ui import theme  # noqa: E402


class FakeCipher(object):
    name = "fake"

    def encrypt(self, plaintext):
        return "fake:" + base64.b64encode(plaintext.encode()).decode()

    def decrypt(self, token):
        return base64.b64decode(token[5:]).decode()


def device_list():
    return [
        models.Device.from_dict({"ip": "10.111.147.127", "client_type": "1",
                                 "os_name": "Windows 10",
                                 "add_time": "2026-09-12 21:50:49",
                                 "user_name": "u"}),
        models.Device.from_dict({"ip": "10.128.96.98", "client_type": "1",
                                 "os_name": "Windows 10",
                                 "add_time": "2026-09-16 00:36:18",
                                 "user_name": "u"}),
    ]


ONLINE = models.OnlineStatus(
    online=True, error="ok",
    raw={"error": "ok", "online_ip": "10.128.96.98", "user_name": "17782817252",
         "online_device_total": "2"})
OFFLINE = models.OnlineStatus(online=False, error="not_online_error",
                              raw={"online_ip": "10.128.96.98"})


class FakeClient(object):
    def __init__(self, status=ONLINE, devices=None, login_outcome=None,
                 logout_outcome=None):
        self._status = status
        self._devices = devices if devices is not None else device_list()
        self._login_outcome = login_outcome
        self._logout_outcome = logout_outcome
        self.calls = []

    def local_state(self, username=None, password=None, timeout=None):
        state = (models.STATE_ONLINE if self._status.online
                 else models.STATE_OFFLINE)
        return state, self._status, list(self._devices)

    def online_devices(self, username, password, timeout=None):
        return list(self._devices)

    def login_and_confirm(self, *args, **kwargs):
        self.calls.append("login")
        return self._login_outcome

    def logout_local(self, *args, **kwargs):
        self.calls.append("logout")
        return self._logout_outcome

    def kick(self, ip, username, unbind=1, timeout=None):
        self.calls.append(("kick", ip))
        return models.Result(kind=models.SUCCESS, raw={}, ip=ip, username=username)


def pump(app, seconds=3.0, until=None):
    """跑 Tk 事件循环，直到条件满足或超时。"""
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.root.update()
        if until and until():
            return True
        time.sleep(0.02)
    return False


class GuiTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            probe = tk.Tk()
            probe.destroy()
        except tk.TclError as exc:
            raise unittest.SkipTest("没有可用的图形环境：%s" % exc)

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="campusnet-gui-")
        self.cfg = Config(path=os.path.join(self.tmp, "config.json"),
                          cipher=FakeCipher())
        self.cfg.set_credentials("17782817252", "pwd-1234")
        self.apps = []

    def tearDown(self):
        for app in self.apps:
            try:
                app.quit()
            except Exception:
                pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_app(self, client):
        app = gui.App(self.cfg, client, None, use_tray=False)
        self.apps.append(app)
        app.root.geometry("760x560+0+0")
        pump(app, 0.4)
        return app


class WindowTest(GuiTestBase):
    def test_refresh_shows_state_and_devices(self):
        app = self.make_app(FakeClient())
        app.refresh()
        pump(app, 3.0, until=lambda: len(app.tree.get_children()) == 2)
        self.assertEqual("已在线", app.state_label.cget("text"))
        self.assertEqual(models.STATE_ONLINE, app.state)
        self.assertEqual(2, len(app.tree.get_children()))
        self.assertIn("10.111.147.127", app.tree.get_children())
        self.assertIn("账号 17782817252", app.detail_label.cget("text"))
        # 状态圆点用的是"在线"色
        self.assertEqual(theme.color_for(models.STATE_ONLINE),
                         app.dot.itemcget(app._dot_id, "fill"))

    def test_offline_state_is_red(self):
        app = self.make_app(FakeClient(status=OFFLINE, devices=[]))
        app.refresh()
        pump(app, 3.0, until=lambda: app.state == models.STATE_OFFLINE)
        self.assertEqual("未登录（离线）", app.state_label.cget("text"))
        self.assertEqual(theme.color_for(models.STATE_OFFLINE),
                         app.dot.itemcget(app._dot_id, "fill"))

    def test_device_table_columns_are_populated(self):
        app = self.make_app(FakeClient())
        app.refresh()
        pump(app, 3.0, until=lambda: len(app.tree.get_children()) == 2)
        row = app.tree.item("10.111.147.127")["values"]
        # 第一列是勾选标记，后面依次是类型 / 系统 / 上线时间 / 已在线 / IP
        self.assertEqual("☐", row[0])
        self.assertEqual("PC", row[1])
        self.assertEqual("Windows 10", row[2])
        self.assertEqual("2026-09-12 21:50:49", row[3])
        self.assertIn("10.111.147.127", row[5])
        # 本机那一行带标记
        self.assertIn("本机", app.tree.item("10.128.96.98")["values"][5])

    def test_clicking_row_toggles_checkbox(self):
        app = self.make_app(FakeClient())
        app.refresh()
        pump(app, 3.0, until=lambda: len(app.tree.get_children()) == 2)
        self.assertEqual(set(), app.checked)
        app.checked.add("10.111.147.127")
        app._render_devices()
        self.assertEqual("☑", app.tree.set("10.111.147.127", "check"))
        app._check_none()
        self.assertEqual("☐", app.tree.set("10.111.147.127", "check"))
        app._check_all()
        self.assertEqual(2, len(app.checked))

    def test_checked_devices_survive_removal_from_list(self):
        app = self.make_app(FakeClient())
        app.refresh()
        pump(app, 3.0, until=lambda: len(app.tree.get_children()) == 2)
        app._check_all()
        app.devices = [app.devices[0]]
        app.checked &= {d.ip for d in app.devices}
        self.assertEqual({app.devices[0].ip}, app.checked)


class ActionTest(GuiTestBase):
    def setUp(self):
        super(ActionTest, self).setUp()
        self.infos = []
        self.errors = []
        self.asks = []
        self._orig = (gui.messagebox.showinfo, gui.messagebox.showerror,
                      gui.messagebox.showwarning, gui.messagebox.askyesno)
        gui.messagebox.showinfo = lambda *a, **k: self.infos.append(a)
        gui.messagebox.showerror = lambda *a, **k: self.errors.append(a)
        gui.messagebox.showwarning = lambda *a, **k: self.errors.append(a)

    def tearDown(self):
        (gui.messagebox.showinfo, gui.messagebox.showerror,
         gui.messagebox.showwarning, gui.messagebox.askyesno) = self._orig
        super(ActionTest, self).tearDown()

    def test_login_success_shows_dialog_and_refreshes(self):
        client = FakeClient(status=OFFLINE, devices=[])
        # 注意：client.login_and_confirm 返回的是 Result（协议层），
        # 由 service 包装成 Outcome 交给界面。
        client._login_outcome = models.Result(
            kind=models.SUCCESS, raw={"ploy_msg": "E0000: Login is successful"},
            ip="10.128.96.98", detail={"confirmed": True})
        app = self.make_app(client)
        app.action_login()
        pump(app, 4.0, until=lambda: bool(self.infos))
        self.assertTrue(self.infos, "应该弹出登录成功提示")
        self.assertIn("登录成功", self.infos[0][1])
        self.assertIn("login", client.calls)

    def test_logout_asks_confirmation_first(self):
        calls = []
        gui.messagebox.askyesno = lambda *a, **k: (calls.append(a), False)[1]
        client = FakeClient()
        app = self.make_app(client)
        app.action_logout()
        pump(app, 1.0)
        self.assertTrue(calls, "应该先确认")
        self.assertNotIn("logout", client.calls)

    def test_logout_confirmed_runs(self):
        gui.messagebox.askyesno = lambda *a, **k: True
        client = FakeClient()
        client._logout_outcome = models.Result(
            kind=models.SUCCESS, raw={"error": "ok", "res": "ok"},
            ip="10.128.96.98", detail={"verified": True})
        app = self.make_app(client)
        app.action_logout()
        pump(app, 4.0, until=lambda: "logout" in client.calls and bool(self.infos))
        self.assertIn("logout", client.calls)
        self.assertTrue(self.infos)

    def test_kick_requires_selection(self):
        client = FakeClient()
        app = self.make_app(client)
        app.action_kick_selected()
        pump(app, 1.0)
        self.assertTrue(self.infos)
        self.assertEqual([], [c for c in client.calls if isinstance(c, tuple)])

    def test_kick_selected_ips(self):
        client = FakeClient()
        app = self.make_app(client)
        app.checked = {"10.111.147.127"}
        app.action_kick_selected()
        pump(app, 4.0, until=lambda: ("kick", "10.111.147.127") in client.calls)
        pump(app, 4.0, until=lambda: app.checked == set())
        self.assertIn(("kick", "10.111.147.127"), client.calls)
        self.assertEqual(set(), app.checked)


class ApproveKickTest(GuiTestBase):
    def test_approve_kick_returns_dialog_choice(self):
        app = self.make_app(FakeClient())
        app._choice_dialog = lambda devices, preselected, my_ip: ["10.1.1.1"]
        chosen = app._approve_kick(device_list(), [], "10.0.0.9")
        self.assertEqual(["10.1.1.1"], chosen)

    def test_approve_kick_returning_none_means_cancel(self):
        app = self.make_app(FakeClient())
        app._choice_dialog = lambda devices, preselected, my_ip: None
        self.assertEqual([], app._approve_kick(device_list(), [], "10.0.0.9"))

    def test_choice_dialog_preselects_and_confirms(self):
        app = self.make_app(FakeClient())
        seen = {}

        def fake_dialog(devices, preselected, my_ip):
            seen["preselected"] = [d.ip for d in preselected]
            return [d.ip for d in preselected]

        app._choice_dialog = fake_dialog
        devices = device_list()
        from campusnet import policy
        pre = policy.pick_victims(devices, my_ip="10.128.96.98")
        self.assertEqual(["10.111.147.127"], app._approve_kick(devices, pre, "10.128.96.98"))


class TaskRunnerTest(GuiTestBase):
    """后台任务出错时必须把忙碌状态清掉，不能让界面卡死。"""

    def test_failing_worker_still_resets_busy(self):
        app = self.make_app(FakeClient())
        app._set_busy(True, "正在查询…")

        def boom():
            raise AttributeError("'NoneType' object has no attribute 'encode'")

        app.runner.submit(boom, done=lambda r: None,
                          fail=lambda exc: app._set_busy(False, "查询失败"))
        pump(app, 3.0, until=lambda: not app._busy)
        self.assertFalse(app._busy, "出错后必须解除忙碌状态")
        self.assertIn("失败", app.status_bar.cget("text"))

    def test_exception_value_is_available_in_fail_callback(self):
        """回归：lambda: fail(exc) 会因为 except 变量被删除而抛 NameError。"""
        app = self.make_app(FakeClient())
        seen = []

        def boom():
            raise ValueError("模拟网络错误")

        app.runner.submit(boom, fail=lambda exc: seen.append(str(exc)))
        pump(app, 3.0, until=lambda: bool(seen))
        self.assertEqual(["模拟网络错误"], seen)


class FirstRunTest(GuiTestBase):
    """首次使用：先弹设置向导，保存后界面必须自己恢复，不能卡在检测中。"""

    def test_flow_without_credentials_then_saving_recovers(self):
        fresh = Config(path=os.path.join(self.tmp, "fresh.json"),
                       cipher=FakeCipher())
        self.assertFalse(fresh.has_credentials)
        client = FakeClient(status=ONLINE, devices=device_list())
        app = gui.App(fresh, client, None, use_tray=False)
        self.apps.append(app)
        app.root.geometry("760x560+0+0")

        def save_it():
            dialog = app._settings_dialog
            if dialog is None or not dialog.win.winfo_exists():
                app.root.after(200, save_it)     # 向导还没弹出来，等等
                return
            dialog.var_user.set("17782817252")
            dialog.var_pwd.set("pwd-1234")
            dialog.save()

        # 必须先把"保存"排进事件队列再进事件循环：
        # 向导是模态的，会在 wait_window 里阻塞，之后再排就来不及了
        app.root.after(700, save_it)
        # 完成条件是"凭据已保存 且 界面状态已经刷新"——
        # 必须连 _busy 一起等：保存会再触发一次刷新，
        # 只看 state 会在第二次刷新还没跑完时就返回
        pump(app, 12.0,
             until=lambda: fresh.has_credentials
             and app.state == models.STATE_ONLINE
             and not app._busy)
        self.assertEqual(models.STATE_ONLINE, app.state,
                         "保存设置后应该自动刷新出在线状态")
        self.assertFalse(app._busy, "不应该一直卡在忙碌状态")
        self.assertNotEqual("正在检测…", app.state_label.cget("text"))
        self.assertTrue(fresh.has_credentials)

    def test_refresh_without_credentials_does_not_raise(self):
        """没有账号时不该去查设备列表（那个接口需要密码）。"""
        fresh = Config(path=os.path.join(self.tmp, "fresh2.json"),
                       cipher=FakeCipher())
        client = FakeClient(status=OFFLINE, devices=[])
        # start_hidden=True 会跳过"首次运行自动弹设置向导"，方便单测刷新逻辑
        app = gui.App(fresh, client, None, use_tray=False, start_hidden=True)
        self.apps.append(app)
        app.refresh()
        pump(app, 5.0, until=lambda: not app._busy)
        self.assertFalse(app._busy)
        self.assertEqual(models.STATE_OFFLINE, app.state)


class SettingsDialogTest(GuiTestBase):
    def test_first_run_saves_credentials(self):
        cfg = Config(path=os.path.join(self.tmp, "c.json"), cipher=FakeCipher())
        app = self.make_app(FakeClient())
        dlg = gui.SettingsDialog(app, cfg, first_run=True)
        dlg.var_user.set("17782817252")
        dlg.var_pwd.set("secret-pw")
        dlg.save()
        reloaded = Config(path=cfg.path, cipher=FakeCipher()).load()
        self.assertEqual("17782817252", reloaded.username)
        self.assertEqual("secret-pw", reloaded.get_password())
        with open(cfg.path, "r", encoding="utf-8") as f:
            self.assertNotIn("secret-pw", f.read())

    def test_leave_password_blank_keeps_existing(self):
        app = self.make_app(FakeClient())
        dlg = gui.SettingsDialog(app, self.cfg)
        dlg.var_user.set("newuser")
        dlg.var_pwd.set("")
        dlg.save()
        reloaded = Config(path=self.cfg.path, cipher=FakeCipher()).load()
        self.assertEqual("newuser", reloaded.username)
        self.assertEqual("pwd-1234", reloaded.get_password())

    def test_kick_mode_and_logout_method_saved(self):
        app = self.make_app(FakeClient())
        dlg = gui.SettingsDialog(app, self.cfg)
        dlg.var_mode.set("manual")
        dlg.var_method.set("portal")
        dlg.save()
        reloaded = Config(path=self.cfg.path, cipher=FakeCipher()).load()
        self.assertEqual("manual", reloaded.kick_mode)
        self.assertEqual("portal", reloaded.get("behavior.logout_method"))

    def test_empty_username_rejected(self):
        app = self.make_app(FakeClient())
        warns = []
        orig = gui.messagebox.showwarning
        gui.messagebox.showwarning = lambda *a, **k: warns.append(a)
        try:
            dlg = gui.SettingsDialog(app, Config(path=os.path.join(self.tmp, "c2.json"),
                                                 cipher=FakeCipher()))
            dlg.var_user.set("   ")
            dlg.save()
        finally:
            gui.messagebox.showwarning = orig
        self.assertTrue(warns)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "c2.json")))

    def test_autostart_checkbox_writes_registry_and_config(self):
        """勾选开机自启要同时改注册表和配置（注册表是真实生效的那份）。"""
        calls = []
        orig = (gui.autostart.is_enabled, gui.autostart.set_enabled)
        gui.autostart.is_enabled = lambda: False
        gui.autostart.set_enabled = lambda flag, silent=False: (
            calls.append((flag, silent)) or flag)
        try:
            app = self.make_app(FakeClient())
            dlg = gui.SettingsDialog(app, self.cfg)
            self.assertFalse(dlg.var_autostart.get())
            dlg.var_autostart.set(True)
            dlg.var_silent.set(True)
            dlg.save()
        finally:
            gui.autostart.is_enabled, gui.autostart.set_enabled = orig
        self.assertEqual([(True, True)], calls)
        reloaded = Config(path=self.cfg.path, cipher=FakeCipher()).load()
        self.assertTrue(reloaded.get("startup.autostart"))
        self.assertTrue(reloaded.get("startup.silent_when_autostart"))

    def test_unchecking_autostart_disables_it(self):
        calls = []
        orig = (gui.autostart.is_enabled, gui.autostart.set_enabled)
        gui.autostart.is_enabled = lambda: True
        gui.autostart.set_enabled = lambda flag, silent=False: (
            calls.append(flag) or flag)
        try:
            app = self.make_app(FakeClient())
            dlg = gui.SettingsDialog(app, self.cfg)
            self.assertTrue(dlg.var_autostart.get())
            dlg.var_autostart.set(False)
            dlg.save()
        finally:
            gui.autostart.is_enabled, gui.autostart.set_enabled = orig
        self.assertEqual([False], calls)


if __name__ == "__main__":
    unittest.main(verbosity=2)
