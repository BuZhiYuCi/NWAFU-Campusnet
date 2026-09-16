#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图形界面主程序：主窗口 + 托盘 + 后台任务。

线程模型很简单：所有网络请求都在后台线程执行，
结果通过队列回到 Tk 主线程再更新界面，所以界面不会被网络卡住。
"""

import os
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from .. import config as cfgmod
from .. import log as logmod
from .. import policy
from .. import autostart
from ..models import (NOT_ONLINE, STATE_OFFLINE, STATE_ONLINE, STATE_UNKNOWN,
                      SUCCESS, UNKNOWN, OnlineStatus, Result)
from ..portal import PortalError, PortalUnreachable, SrunPortalClient
from ..service import CampusNetService, Outcome
from . import theme
from .tray import TrayIcon

FONT = "Microsoft YaHei UI"


class TaskRunner(object):
    """在后台线程执行任务，把回调排到 Tk 主线程。"""

    def __init__(self, root, logger=None):
        self.root = root
        self.logger = logger
        self._queue = queue.Queue()
        self._stopped = False
        self._after_id = None
        self._threads = []
        self._pump()

    def stop(self):
        self._stopped = True
        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        # 等后台线程收尾：它们在窗口销毁后还活着的话，
        # Tk 对象可能在错误的线程里被回收（Tcl_AsyncDelete 崩溃）
        for thread in list(self._threads):
            if thread.is_alive():
                thread.join(timeout=2.0)
        self._threads = []

    def _pump(self):
        if self._stopped:
            return
        try:
            while True:
                try:
                    self._queue.get_nowait()()
                except queue.Empty:
                    break
                except Exception as exc:
                    # 回调出错不能把事件泵带崩，但也绝不能静默吞掉——
                    # 静默吞掉会让界面永久卡在"正在检测…"，极难排查。
                    if self.logger:
                        self.logger.exception("GUI 回调出错: %s", exc)
                    else:
                        import traceback
                        traceback.print_exc()
        finally:
            try:  # 窗口已销毁时 after 会抛异常，忽略即可
                self._after_id = self.root.after(50, self._pump)
            except Exception:
                pass

    def post(self, fn):
        """从任意线程把一个函数排到主线程执行。"""
        self._queue.put(fn)

    def submit(self, work, done=None, fail=None):
        def run():
            try:
                result = work()
            except Exception as exc:  # 后台异常不能吞掉，回主线程显示
                # 注意：Python 3 会在 except 块结束时删除 exc，
                # 所以这里必须用默认参数把它绑住，
                # 写成 lambda: fail(exc) 会在真正执行时抛 NameError。
                if fail:
                    self._queue.put(lambda e=exc: fail(e))
            else:
                if done:
                    self._queue.put(lambda r=result: done(r))
        thread = threading.Thread(target=run, daemon=True)
        self._threads.append(thread)
        thread.start()


class App(object):

    def __init__(self, cfg, client, logger=None, use_tray=True,
                 start_hidden=False):
        self.cfg = cfg
        self.client = client
        self.logger = logger
        self.service = CampusNetService(client, cfg, logger)
        self.state = STATE_UNKNOWN
        self.devices = []
        self.checked = set()
        self.my_ip = None
        self._busy = False
        self._closing = False
        self._ui_thread = threading.current_thread()
        self._settings_dialog = None

        self.root = tk.Tk()
        self.root.title("校园网助手")
        self.root.geometry("760x560")
        self.root.minsize(680, 480)
        self.root.configure(bg=theme.BG)
        self.runner = TaskRunner(self.root, logger)

        self._build_ui()

        self.tray = None
        if use_tray:
            self.tray = TrayIcon(self.show_window, self.action_login,
                                 self.action_logout, self.quit,
                                 marshal=self.runner.post)
            if self.tray.start(self.state, self._tooltip()):
                self.logger and self.logger.info("tray started")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        if start_hidden and self.tray and self.tray.available:
            self.root.withdraw()
        self.root.after(150, self.refresh)
        if not cfg.has_credentials and not start_hidden:
            self.root.after(300, lambda: self.open_settings(first_run=True))

    # ------------------------------------------------------------------
    # 界面搭建
    # ------------------------------------------------------------------
    def _build_ui(self):
        header = tk.Frame(self.root, bg=theme.CARD, padx=18, pady=14)
        header.pack(fill=tk.X)

        self.dot = tk.Canvas(header, width=16, height=16, bg=theme.CARD,
                             highlightthickness=0)
        self.dot.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 10))
        self._dot_id = self.dot.create_oval(2, 2, 15, 15,
                                            fill=theme.color_for(STATE_UNKNOWN),
                                            outline="")

        self.state_label = tk.Label(header, text="正在检测…", bg=theme.CARD,
                                    fg=theme.TEXT, font=(FONT, 15, "bold"))
        self.state_label.grid(row=0, column=1, sticky="w")
        self.detail_label = tk.Label(header, text="", bg=theme.CARD,
                                     fg=theme.MUTED, font=(FONT, 9),
                                     justify=tk.LEFT)
        self.detail_label.grid(row=1, column=1, sticky="w", pady=(2, 0))
        header.columnconfigure(1, weight=1)

        bar = tk.Frame(self.root, bg=theme.BG, padx=16, pady=10)
        bar.pack(fill=tk.X)
        self.btn_login = ttk.Button(bar, text="一键登录", command=self.action_login)
        self.btn_login.pack(side=tk.LEFT)
        self.btn_logout = ttk.Button(bar, text="一键下线", command=self.action_logout)
        self.btn_logout.pack(side=tk.LEFT, padx=8)
        self.btn_refresh = ttk.Button(bar, text="刷新", command=self.refresh)
        self.btn_refresh.pack(side=tk.LEFT)
        ttk.Button(bar, text="设置", command=self.open_settings).pack(side=tk.RIGHT)

        box = tk.LabelFrame(self.root, text=" 在线设备 ", bg=theme.BG,
                            fg=theme.TEXT, font=(FONT, 10), padx=10, pady=8)
        box.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 8))

        columns = ("check", "type", "os", "since", "online", "ip")
        self.tree = ttk.Treeview(box, columns=columns, show="headings",
                                 selectmode="none", height=8)
        headings = {"check": "", "type": "设备类型", "os": "操作系统",
                    "since": "上线时间", "online": "已在线", "ip": "IP 地址"}
        widths = {"check": 34, "type": 90, "os": 110, "since": 160,
                  "online": 100, "ip": 160}
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col],
                             anchor="center" if col == "check" else "w",
                             stretch=(col == "os"))
        self.tree.tag_configure("local", background="#eef4ff")
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<Button-1>", self._on_tree_click)

        ops = tk.Frame(box, bg=theme.BG)
        ops.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(ops, text="全选", command=self._check_all).pack(side=tk.LEFT)
        ttk.Button(ops, text="全不选", command=self._check_none).pack(side=tk.LEFT, padx=6)
        self.btn_kick = ttk.Button(ops, text="下线选中设备",
                                   command=self.action_kick_selected)
        self.btn_kick.pack(side=tk.LEFT, padx=6)
        self.hint_label = tk.Label(ops, text="点击行最左侧勾选", bg=theme.BG,
                                   fg=theme.MUTED, font=(FONT, 9))
        self.hint_label.pack(side=tk.LEFT, padx=10)

        self.status_bar = tk.Label(self.root, text="就绪", anchor="w",
                                   bg="#eceff3", fg=theme.MUTED,
                                   font=(FONT, 9), padx=14, pady=6)
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM)

    # ------------------------------------------------------------------
    # 小工具
    # ------------------------------------------------------------------
    def _tooltip(self):
        ips = len(self.devices)
        if self.state == STATE_ONLINE:
            return "校园网助手 · 已在线（本机 %s）" % (self.my_ip or "-")
        if self.state == STATE_OFFLINE:
            return "校园网助手 · 离线"
        return "校园网助手 · 状态未知"

    def _set_state(self, state):
        self.state = state
        self.dot.itemconfigure(self._dot_id, fill=theme.color_for(state))
        self.state_label.configure(text=theme.text_for(state))
        if self.tray:
            self.tray.set_state(state, self._tooltip())

    def _set_busy(self, busy, message=None):
        self._busy = busy
        state = tk.DISABLED if busy else tk.NORMAL
        for btn in (self.btn_login, self.btn_logout, self.btn_refresh,
                    self.btn_kick):
            btn.configure(state=state)
        if message:
            self.status_bar.configure(text=message)

    def _status(self, message):
        self.status_bar.configure(text=message)

    # ------------------------------------------------------------------
    # 设备列表
    # ------------------------------------------------------------------
    def _render_devices(self):
        self.tree.delete(*self.tree.get_children())
        for dev in policy.sort_oldest_first(self.devices):
            checked = "☑" if dev.ip in self.checked else "☐"
            tags = ("local",) if self.my_ip and dev.ip == self.my_ip else ()
            suffix = "  ← 本机" if self.my_ip and dev.ip == self.my_ip else ""
            self.tree.insert("", tk.END, iid=dev.ip, tags=tags, values=(
                checked, dev.client_type_label, dev.os_name, dev.add_time,
                dev.online_text(), dev.ip + suffix))
        local = sum(1 for d in self.devices if d.ip == self.my_ip)
        self.hint_label.configure(
            text="共 %d 台在线%s" % (len(self.devices),
                                    "，含本机" if local else ""))

    def _on_tree_click(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        if self.tree.identify_column(event.x) != "#1":
            return
        item = self.tree.identify_row(event.y)
        if not item:
            return
        if item in self.checked:
            self.checked.discard(item)
        else:
            self.checked.add(item)
        self.tree.set(item, "check", "☑" if item in self.checked else "☐")

    def _check_all(self):
        self.checked = {d.ip for d in self.devices}
        self._render_devices()

    def _check_none(self):
        self.checked = set()
        self._render_devices()

    # ------------------------------------------------------------------
    # 动作
    # ------------------------------------------------------------------
    def refresh(self):
        if self._busy:
            return
        self._set_busy(True, "正在查询…")

        def work():
            state, status, devices = self.service.local_status()
            # 没有账号就别去查设备列表：那个接口要账号+密码，
            # 首次运行时密码还是空的，硬查只会抛异常（踩过）
            if not devices and self.cfg.has_credentials:
                try:
                    devices = self.service.devices()
                except (PortalError, PortalUnreachable, ValueError):
                    devices = []
            return state, status, devices

        def done(result):
            state, status, devices = result
            self.my_ip = status.ip
            self.devices = devices
            self.checked &= {d.ip for d in devices}
            self._render_devices()
            self._set_state(state)
            bits = []
            if self.my_ip:
                bits.append("本机 IP %s" % self.my_ip)
            if status.user_name:
                bits.append("账号 %s" % status.user_name)
            elif self.cfg.username:
                bits.append("账号 %s" % self.cfg.username)
            if status.device_total:
                bits.append("在线设备 %s 台" % status.device_total)
            if state == STATE_UNKNOWN and status.error:
                bits.append("服务端返回：%s" % status.error)
            self.detail_label.configure(text="　".join(bits) or "—")
            self._set_busy(False, "已更新 %s" % _now())

        def fail(exc):
            # 无论界面更新出什么岔子，都必须在最后把忙碌状态清掉，
            # 否则用户会永远卡在"正在检测…"
            try:
                self._set_state(STATE_UNKNOWN)
                self.detail_label.configure(text="查询失败：%s" % exc)
            finally:
                self._set_busy(False, "查询失败")

        self.runner.submit(work, done, fail)

    def action_login(self):
        if self._busy:
            return
        if not self._ensure_credentials():
            return
        self._set_busy(True, "正在登录…")

        def work():
            return self.service.login(approve_kick=self._approve_kick)

        def done(outcome):
            self._set_busy(False, outcome.message)
            if outcome.kicked:
                self._status("已下线 %s，%s" % ("、".join(outcome.kicked),
                                                outcome.message))
            if outcome.ok:
                if outcome.kind == "already_online":
                    messagebox.showinfo("校园网助手", "本机已经在线，无需重复登录。")
                else:
                    messagebox.showinfo("校园网助手", "登录成功。")
                if self.tray:
                    self.tray.notify("已连接校园网")
            elif outcome.kind == "declined":
                messagebox.showinfo("校园网助手", "已取消，没有下线任何设备。")
            elif outcome.kind == "full":
                messagebox.showwarning("校园网助手",
                                       "在线设备数已达上限：%s" % outcome.message)
            else:
                messagebox.showerror("校园网助手", "登录失败：%s" % outcome.message)
            self.refresh()

        def fail(exc):
            self._set_busy(False, "登录失败")
            messagebox.showerror("校园网助手", "登录失败：%s" % exc)

        self.runner.submit(work, done, fail)

    def action_logout(self):
        if self._busy:
            return
        if not self._ensure_credentials():
            return
        if not messagebox.askyesno("校园网助手", "确定要注销本机的校园网登录吗？"):
            return
        self._set_busy(True, "正在注销…")

        def work():
            return self.service.logout()

        def done(outcome):
            self._set_busy(False, outcome.message)
            if outcome.ok:
                if self.tray:
                    self.tray.notify("已断开校园网")
                messagebox.showinfo("校园网助手", outcome.message)
            else:
                messagebox.showerror("校园网助手", "下线失败：%s" % outcome.message)
            self.refresh()

        def fail(exc):
            self._set_busy(False, "下线失败")
            messagebox.showerror("校园网助手", "下线失败：%s" % exc)

        self.runner.submit(work, done, fail)

    def action_kick_selected(self):
        if self._busy:
            return
        if not self._ensure_credentials():
            return
        ips = sorted(self.checked)
        if not ips:
            messagebox.showinfo("校园网助手", "请先勾选要下线的设备。")
            return
        if self.my_ip in ips:
            if not messagebox.askyesno(
                    "校园网助手",
                    "选中的设备里包含本机（%s），下线后本机将断网。\n确定继续吗？"
                    % self.my_ip):
                return
        self._set_busy(True, "正在下线 %d 台设备…" % len(ips))

        def work():
            return self.service.kick(ips)

        def done(results):
            ok = [r.ip for r in results if r.ok]
            bad = [r for r in results if not r.ok]
            self.checked = set()
            self._set_busy(False, "已下线 %d 台" % len(ok))
            if bad:
                messagebox.showwarning(
                    "校园网助手",
                    "成功 %d 台；失败 %d 台：\n%s"
                    % (len(ok), len(bad),
                       "\n".join("%s：%s" % (r.ip, r.message) for r in bad)))
            else:
                messagebox.showinfo("校园网助手", "已下线 %d 台设备。" % len(ok))
            self.refresh()

        def fail(exc):
            self._set_busy(False, "下线失败")
            messagebox.showerror("校园网助手", "下线失败：%s" % exc)

        self.runner.submit(work, done, fail)

    # ------------------------------------------------------------------
    # 腾位选择对话框（供后台线程同步调用）
    # ------------------------------------------------------------------
    def _approve_kick(self, devices, preselected, my_ip):
        """在工作线程里被调用：切到主线程弹模态框，等用户选完再返回。"""
        if self._closing:
            return []
        if threading.current_thread() is self._ui_thread:
            # 已经在 UI 线程：直接弹，否则会把自己等死（队列正是这个线程在跑）
            return self._choice_dialog(devices, preselected, my_ip) or []
        event = threading.Event()
        box = {}

        def show():
            try:
                box["value"] = self._choice_dialog(devices, preselected, my_ip)
            finally:
                event.set()

        self.runner.post(show)
        # 分片等待：窗口正在关闭时立刻放弃，别把线程永久挂在这里
        while not event.wait(0.2):
            if self._closing:
                return []
        return box.get("value") or []

    def _choice_dialog(self, devices, preselected, my_ip):
        win = tk.Toplevel(self.root)
        win.title("在线设备数已达上限")
        win.configure(bg=theme.BG)
        win.transient(self.root)
        win.grab_set()
        win.geometry("620x420")

        tk.Label(win, text="需要先下线一台设备才能登录。", bg=theme.BG,
                 fg=theme.TEXT, font=(FONT, 12, "bold")).pack(anchor="w",
                                                              padx=16, pady=(14, 2))
        tk.Label(win, text="策略：%s（带 ☑ 的是预选，可自行改选）" % self.cfg.kick_mode,
                 bg=theme.BG, fg=theme.MUTED, font=(FONT, 9)).pack(anchor="w",
                                                                    padx=16)

        frame = tk.Frame(win, bg=theme.BG)
        frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=10)
        cols = ("check", "type", "os", "since", "online", "ip")
        tree = ttk.Treeview(frame, columns=cols, show="headings",
                            selectmode="none", height=8)
        heads = {"check": "", "type": "设备类型", "os": "操作系统",
                 "since": "上线时间", "online": "已在线", "ip": "IP 地址"}
        widths = {"check": 34, "type": 84, "os": 96, "since": 150,
                  "online": 92, "ip": 150}
        for col in cols:
            tree.heading(col, text=heads[col])
            tree.column(col, width=widths[col],
                        anchor="center" if col == "check" else "w")
        tree.tag_configure("local", background="#eef4ff")
        tree.pack(fill=tk.BOTH, expand=True)

        checked = {d.ip for d in preselected}

        def render():
            tree.delete(*tree.get_children())
            for dev in policy.sort_oldest_first(devices):
                mark = "☑" if dev.ip in checked else "☐"
                tags = ("local",) if my_ip and dev.ip == my_ip else ()
                tree.insert("", tk.END, iid=dev.ip, tags=tags, values=(
                    mark, dev.client_type_label, dev.os_name, dev.add_time,
                    dev.online_text(), dev.ip))

        def on_click(event):
            if tree.identify_column(event.x) != "#1":
                return
            item = tree.identify_row(event.y)
            if not item:
                return
            if item in checked:
                checked.discard(item)
            else:
                checked.add(item)
            tree.set(item, "check", "☑" if item in checked else "☐")

        tree.bind("<Button-1>", on_click)
        render()

        result = {"ips": None}
        row = tk.Frame(win, bg=theme.BG)
        row.pack(fill=tk.X, padx=16, pady=(0, 14))

        def confirm():
            if not checked:
                messagebox.showinfo("校园网助手", "至少选择一台要下线的设备。",
                                    parent=win)
                return
            result["ips"] = sorted(checked)
            win.destroy()

        ttk.Button(row, text="下线并继续登录", command=confirm).pack(side=tk.LEFT)
        ttk.Button(row, text="取消", command=win.destroy).pack(side=tk.LEFT, padx=8)
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        win.wait_window()
        return result["ips"]

    # ------------------------------------------------------------------
    # 设置
    # ------------------------------------------------------------------
    def open_settings(self, first_run=False, modal=True):
        # 先构造再显示：模态等待会阻塞，如果放在构造函数里，
        # 这个引用要等用户关掉对话框才拿得到（踩过）
        self._settings_dialog = SettingsDialog(self, self.cfg, first_run=first_run)
        if modal:
            self._settings_dialog.show_modal()
        return self._settings_dialog

    def _ensure_credentials(self):
        if self.cfg.has_credentials:
            return True
        if messagebox.askyesno("校园网助手", "还没有设置账号密码，现在设置吗？"):
            self.open_settings(first_run=True)
        return False

    # ------------------------------------------------------------------
    # 窗口/退出
    # ------------------------------------------------------------------
    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _on_close(self):
        if self.tray and self.tray.available:
            self.root.withdraw()
            if self.tray:
                self.tray.notify("程序仍在托盘运行，右键图标可退出")
        else:
            self.quit()

    def quit(self):
        self._closing = True
        self.runner.stop()
        if self.tray:
            self.tray.stop()
        try:
            self.root.destroy()
        except Exception:
            pass

    def mainloop(self):
        self.root.mainloop()


def _now():
    import time
    return time.strftime("%H:%M:%S")


class SettingsDialog(object):
    """账号与行为设置。"""

    def __init__(self, app, cfg, first_run=False):
        self.app = app
        self.cfg = cfg
        self.win = tk.Toplevel(app.root)
        self.win.title("设置")
        self.win.configure(bg=theme.BG)
        self.win.transient(app.root)
        self.win.resizable(False, False)
        self._build(first_run)
        # 打开就聚焦账号框，回车直接保存——少点几下鼠标
        self.entry_user.focus_set()
        self.win.bind("<Return>", lambda event: self.save())
        self.win.bind("<Escape>", lambda event: self.win.destroy())

    def show_modal(self):
        """显示为模态窗口并阻塞到关闭。"""
        self.win.grab_set()
        self.win.wait_window()

    def _row(self, parent, index, label):
        tk.Label(parent, text=label, bg=theme.BG, fg=theme.TEXT,
                 font=(FONT, 9)).grid(row=index, column=0, sticky="w",
                                      padx=(16, 8), pady=6)
        return index + 1

    def _build(self, first_run):
        body = tk.Frame(self.win, bg=theme.BG)
        body.pack(fill=tk.BOTH, expand=True)
        r = 0
        if first_run:
            tk.Label(body, text="第一次使用，请先设置校园网账号",
                     bg=theme.BG, fg=theme.TEXT,
                     font=(FONT, 12, "bold")).grid(row=r, column=0, columnspan=2,
                                                   sticky="w", padx=16, pady=(14, 4))
            r += 1
            tk.Label(body, text="密码会用 Windows DPAPI 加密保存在本机，只有你本人能解开。",
                     bg=theme.BG, fg=theme.MUTED, font=(FONT, 9),
                     wraplength=420, justify=tk.LEFT).grid(
                         row=r, column=0, columnspan=2, sticky="w", padx=16)
            r += 1

        r = self._row(body, r, "账号")
        self.var_user = tk.StringVar(value=self.cfg.username)
        self.entry_user = tk.Entry(body, textvariable=self.var_user, width=32,
                                   font=(FONT, 10))
        self.entry_user.grid(row=r - 1, column=1, sticky="w", pady=6)

        r = self._row(body, r, "密码")
        self.var_pwd = tk.StringVar()
        self.entry_pwd = tk.Entry(body, textvariable=self.var_pwd, width=32,
                                  show="●", font=(FONT, 10))
        self.entry_pwd.grid(row=r - 1, column=1, sticky="w", pady=6)
        tk.Label(body, text="留空表示不修改（已保存：%s）"
                 % ("是" if self.cfg.get_password() else "否"),
                 bg=theme.BG, fg=theme.MUTED, font=(FONT, 8)).grid(
                     row=r - 1, column=2, sticky="w", padx=6)

        r = self._row(body, r, "满员时预选")
        self.var_mode = tk.StringVar(value=self.cfg.kick_mode)
        ttk.Combobox(body, textvariable=self.var_mode, width=28, state="readonly",
                     values=(policy.PRESELECT_OLDEST, policy.PRIORITY,
                             policy.MANUAL)).grid(row=r - 1, column=1, sticky="w")

        r = self._row(body, r, "一键下线方式")
        self.var_method = tk.StringVar(
            value=self.cfg.get("behavior.logout_method", "dm"))
        ttk.Combobox(body, textvariable=self.var_method, width=28, state="readonly",
                     values=("dm", "portal")).grid(row=r - 1, column=1, sticky="w")
        tk.Label(body, text="dm＝真正下线（推荐）；portal＝只注销会话",
                 bg=theme.BG, fg=theme.MUTED, font=(FONT, 8)).grid(
                     row=r - 1, column=2, sticky="w", padx=6)

        r = self._row(body, r, "门户地址")
        self.var_base = tk.StringVar(value=self.cfg.base_url)
        tk.Entry(body, textvariable=self.var_base, width=32,
                 font=(FONT, 10)).grid(row=r - 1, column=1, sticky="w", pady=6)

        r = self._row(body, r, "开机自启")
        start_box = tk.Frame(body, bg=theme.BG)
        start_box.grid(row=r - 1, column=1, columnspan=2, sticky="w")
        try:
            enabled_now = autostart.is_enabled()
        except Exception:
            enabled_now = bool(self.cfg.get("startup.autostart", False))
        self.var_autostart = tk.BooleanVar(value=enabled_now)
        self.var_silent = tk.BooleanVar(
            value=bool(self.cfg.get("startup.silent_when_autostart", False)))
        tk.Checkbutton(start_box, text="开机时自动启动本程序",
                       variable=self.var_autostart, bg=theme.BG, fg=theme.TEXT,
                       font=(FONT, 9), activebackground=theme.BG,
                       selectcolor=theme.CARD).pack(anchor="w")
        tk.Checkbutton(start_box, text="自启时静默启动（只留托盘，不弹窗口）",
                       variable=self.var_silent, bg=theme.BG, fg=theme.MUTED,
                       font=(FONT, 8), activebackground=theme.BG,
                       selectcolor=theme.CARD).pack(anchor="w")
        tk.Label(body, text="开机自启只负责把程序跑起来，不会自动认证。",
                 bg=theme.BG, fg=theme.MUTED, font=(FONT, 8)).grid(
                     row=r, column=1, columnspan=2, sticky="w")

        btns = tk.Frame(body, bg=theme.BG)
        btns.grid(row=r + 2, column=0, columnspan=3, sticky="e",
                  padx=16, pady=14)
        ttk.Button(btns, text="保存", command=self.save).pack(side=tk.RIGHT)
        ttk.Button(btns, text="取消", command=self.win.destroy).pack(
            side=tk.RIGHT, padx=8)

    def save(self):
        username = self.var_user.get().strip()
        if not username:
            messagebox.showwarning("校园网助手", "账号不能为空。", parent=self.win)
            return
        password = self.var_pwd.get()
        self.cfg.set("portal.username", username)
        if password:
            self.cfg.set_password(password)
            logmod.register_secret(password)
        self.cfg.set("behavior.kick_mode", self.var_mode.get())
        self.cfg.set("behavior.logout_method", self.var_method.get())
        self.cfg.set("portal.base_url", self.var_base.get().strip()
                     or "http://172.26.8.11")
        silent = bool(self.var_silent.get())
        want_autostart = bool(self.var_autostart.get())
        self.cfg.set("startup.autostart", want_autostart)
        self.cfg.set("startup.silent_when_autostart", silent)
        try:
            self.cfg.save()
        except OSError as exc:
            messagebox.showerror("校园网助手", "保存失败：%s" % exc, parent=self.win)
            return
        try:
            autostart.set_enabled(want_autostart, silent=silent)
        except autostart.AutostartUnsupported as exc:
            messagebox.showwarning("校园网助手", "开机自启未能设置：%s" % exc,
                                   parent=self.win)
        self.win.destroy()
        if self.app:
            self.app._status("设置已保存")
            self.app.refresh()


def run(cfg=None, use_tray=True, start_hidden=False):
    """启动图形界面。"""
    cfg = cfg or cfgmod.load_or_create()
    logger = logmod.setup_logging(console=False)
    password = cfg.get_password()
    if password:
        logmod.register_secret(password)
    client = SrunPortalClient(base_url=cfg.base_url,
                              timeout=float(cfg.get("portal.timeout_sec", 8)))
    App(cfg, client, logger, use_tray=use_tray,
        start_hidden=start_hidden).mainloop()
    return 0


class _OfflineClient(object):
    """自检用：完全不联网，永远返回"离线"。"""

    def local_state(self, username=None, password=None, timeout=None):
        return (STATE_OFFLINE,
                OnlineStatus(online=False, error="not_online_error",
                             raw={"online_ip": "10.0.0.1"}),
                [])

    def online_devices(self, username, password, timeout=None):
        return []

    def login_and_confirm(self, *args, **kwargs):
        return Result(kind=UNKNOWN, raw={})

    def logout_local(self, *args, **kwargs):
        return Result(kind=NOT_ONLINE, raw={})

    def kick(self, ip, username, **kwargs):
        return Result(kind=SUCCESS, raw={}, ip=ip, username=username)


def run_selftest():
    """图形界面自检：在真实窗口里走一遍"首次设置 → 保存 → 刷新"。

    专治"界面卡在正在检测…"这类问题：结果会写进日志，也弹窗显示，
    不需要联网、不碰正式配置。
    """
    import tempfile
    import time as _time
    from ..dpapi import DpapiCipher

    logger = logmod.setup_logging(console=False)
    cfg = cfgmod.Config(path=os.path.join(tempfile.mkdtemp(prefix="cn-selftest-"),
                                          "config.json"),
                        cipher=DpapiCipher())
    app = App(cfg, _OfflineClient(), logger, use_tray=False)
    outcome = {"ok": False, "note": ""}

    def drive():
        dialog = app._settings_dialog
        if dialog is None or not dialog.win.winfo_exists():
            app.root.after(200, drive)
            return
        dialog.var_user.set("selftest-user")
        dialog.var_pwd.set("selftest-password")
        dialog.save()

    app.root.after(600, drive)
    deadline = _time.time() + 15
    while _time.time() < deadline:
        app.root.update()
        label = app.state_label.cget("text")
        if cfg.has_credentials and not app._busy and label != "正在检测…":
            outcome["ok"] = True
            outcome["note"] = "状态标签=%r 忙碌=%s" % (label, app._busy)
            break
        _time.sleep(0.02)

    if not outcome["ok"]:
        outcome["note"] = ("超时：标签=%r 忙碌=%s 已保存凭据=%s"
                           % (app.state_label.cget("text"), app._busy,
                              cfg.has_credentials))
    logger.info("GUI 自检 %s：%s",
                "通过" if outcome["ok"] else "失败", outcome["note"])
    try:
        # 用自制弹窗而不是 messagebox：messagebox 没法自动关闭，
        # 万一没人点，自检自己反而会一直挂着
        box = tk.Toplevel(app.root)
        box.title("校园网助手 · 自检")
        box.configure(bg=theme.CARD, padx=20, pady=16)
        box.transient(app.root)
        tk.Label(box, text="自检通过 ✔" if outcome["ok"] else "自检失败 ✘",
                 bg=theme.CARD, fg=theme.TEXT,
                 font=(FONT, 13, "bold")).pack(anchor="w")
        tk.Label(box, text=outcome["note"], bg=theme.CARD, fg=theme.MUTED,
                 font=(FONT, 9), wraplength=420,
                 justify=tk.LEFT).pack(anchor="w", pady=(6, 2))
        tk.Label(box, text="详细结果见日志：\n%s" % logmod.log_path(),
                 bg=theme.CARD, fg=theme.MUTED, font=(FONT, 8),
                 wraplength=420, justify=tk.LEFT).pack(anchor="w")
        ttk.Button(box, text="关闭", command=box.destroy).pack(anchor="e",
                                                               pady=(10, 0))
        box.after(10000, lambda: box.winfo_exists() and box.destroy())
        app.root.wait_window(box)
    except Exception:
        pass
    app.quit()
    return 0 if outcome["ok"] else 1
