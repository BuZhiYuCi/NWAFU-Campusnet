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
from .widgets import RoundedButton
from .tray import TrayIcon

FONT = "Microsoft YaHei UI"

#: 刷新看门狗：超过这个时间 worker 还没收尾，就强制把界面救回来
REFRESH_WATCHDOG_MS = 20000


class TaskRunner(object):
    """在后台线程执行任务，把回调排到 Tk 主线程。"""

    def __init__(self, root, logger=None, on_error=None):
        self.root = root
        self.logger = logger
        self.on_error = on_error
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
                    # 只写日志等于让界面无声卡死：必须回到界面上告诉用户
                    if self.on_error:
                        try:
                            self.on_error(exc)
                        except Exception:
                            pass
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
        self._refresh_pending = False   # 忙碌期间被挡下的刷新请求，收尾后补跑
        self._refresh_seq = 0           # 刷新序号，用来丢弃被看门狗判死的迟到结果
        self._watchdog_id = None        # 刷新看门狗，防止 worker 卡死不收尾
        self._error_shown = False       # 回调异常只弹一次，避免刷屏
        self._ui_thread = threading.current_thread()
        self._settings_dialog = None

        self.root = tk.Tk()
        self.root.title("校园网助手")
        self.root.geometry("820x600")
        self.root.minsize(720, 520)
        self.root.configure(bg=theme.BG)
        theme.apply_style(self.root)
        window_icon = theme.load_image("emblem-ui.png", master=self.root)
        if window_icon:
            self._window_icon = window_icon      # 必须留引用，否则会被回收
            try:
                self.root.iconphoto(True, window_icon)
            except Exception:
                pass
        self.runner = TaskRunner(self.root, logger, on_error=self._on_ui_error)

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
        if cfg.has_credentials:
            self.root.after(150, self.refresh)
        else:
            # 没有账号时那次刷新毫无意义：它只会占住 _busy，
            # 让"向导保存后触发的那次刷新"被 if self._busy 直接丢弃（首次使用卡死的根源之一）
            self._show_unconfigured()
            if not start_hidden:
                self.root.after(300, lambda: self.open_settings(first_run=True))

    # ------------------------------------------------------------------
    # 界面搭建
    # ------------------------------------------------------------------
    def _build_ui(self):
        # ---- 顶部状态卡：徽标 + 状态灯 + 大字状态 + 明细 ----
        header = tk.Frame(self.root, bg=theme.CARD)
        header.pack(fill=tk.X, padx=12, pady=(12, 6))
        inner = tk.Frame(header, bg=theme.CARD)
        inner.pack(fill=tk.X, padx=18, pady=16)

        emblem = theme.load_image("emblem-ui.png", master=self.root)
        if emblem:
            self._emblem_img = emblem
            if emblem.width() > 64:                 # 96px 源图缩到 48px
                emblem = emblem.subsample(2, 2)
                self._emblem_img_small = emblem
            tk.Label(inner, image=emblem, bg=theme.CARD).grid(
                row=0, column=0, rowspan=2, padx=(0, 16))

        self.dot = tk.Canvas(inner, width=14, height=14, bg=theme.CARD,
                             highlightthickness=0)
        self.dot.grid(row=0, column=1, sticky="w", padx=(0, 8))
        self._dot_id = self.dot.create_oval(1, 1, 13, 13,
                                            fill=theme.color_for(STATE_UNKNOWN),
                                            outline="")
        self.state_label = tk.Label(inner, text="正在检测…", bg=theme.CARD,
                                    fg=theme.TEXT, font=theme.FONT_TITLE)
        self.state_label.grid(row=0, column=2, sticky="w")
        self.detail_label = tk.Label(inner, text="", bg=theme.CARD,
                                     fg=theme.MUTED, font=theme.FONT_SMALL,
                                     justify=tk.LEFT)
        self.detail_label.grid(row=1, column=1, columnspan=2, sticky="w",
                               pady=(4, 0))
        inner.columnconfigure(2, weight=1)

        # ---- 操作按钮 ----
        bar = tk.Frame(self.root, bg=theme.BG)
        bar.pack(fill=tk.X, padx=16, pady=(6, 10))
        self.btn_login = RoundedButton(bar, text="一键登录", style="accent",
                                       command=self.action_login, height=36,
                                       font=theme.FONT_BUTTON_BOLD)
        self.btn_login.pack(side=tk.LEFT)
        self.btn_logout = RoundedButton(bar, text="一键下线", style="soft",
                                        command=self.action_logout, height=36,
                                        font=theme.FONT_BUTTON)
        self.btn_logout.pack(side=tk.LEFT, padx=10)
        self.btn_refresh = RoundedButton(bar, text="刷新", style="ghost",
                                         command=self.refresh, height=36,
                                         font=theme.FONT_BUTTON)
        self.btn_refresh.pack(side=tk.LEFT)
        RoundedButton(bar, text="设置", style="ghost",
                      command=self.open_settings, height=36,
                      font=theme.FONT_BUTTON).pack(side=tk.RIGHT)

        # ---- 在线设备 ----
        card = tk.Frame(self.root, bg=theme.CARD)
        card.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 6))

        head = tk.Frame(card, bg=theme.CARD)
        head.pack(fill=tk.X, padx=18, pady=(12, 6))
        self.section_label = tk.Label(head, text="在线设备", bg=theme.CARD,
                                      fg=theme.PRIMARY_DARK,
                                      font=theme.FONT_SECTION)
        self.section_label.pack(side=tk.LEFT)
        self.hint_label = tk.Label(head, text="点击行最左侧勾选", bg=theme.CARD,
                                   fg=theme.MUTED, font=theme.FONT_SMALL)
        self.hint_label.pack(side=tk.LEFT, padx=12)

        columns = ("check", "type", "os", "since", "online", "ip")
        self.tree = ttk.Treeview(card, columns=columns, show="headings",
                                 selectmode="none", height=8)
        headings = {"check": "", "type": "设备类型", "os": "操作系统",
                    "since": "上线时间", "online": "已在线", "ip": "IP 地址"}
        widths = {"check": 38, "type": 96, "os": 120, "since": 170,
                  "online": 106, "ip": 170}
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col],
                             anchor="center" if col in ("check", "online") else "w",
                             stretch=(col == "os"))
        self.tree.tag_configure("odd", background=theme.CARD)
        self.tree.tag_configure("even", background=theme.CARD_SOFT)
        self.tree.tag_configure("local", background=theme.PRIMARY_TINT)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=12)
        self.tree.bind("<Button-1>", self._on_tree_click)

        ops = tk.Frame(card, bg=theme.CARD)
        ops.pack(fill=tk.X, padx=18, pady=12)
        RoundedButton(ops, text="全选", style="soft", height=30,
                      parent_bg=theme.CARD, font=theme.FONT_BUTTON_SMALL,
                      command=self._check_all).pack(side=tk.LEFT)
        RoundedButton(ops, text="全不选", style="soft", height=30,
                      parent_bg=theme.CARD, font=theme.FONT_BUTTON_SMALL,
                      command=self._check_none).pack(side=tk.LEFT, padx=8)
        self.btn_kick = RoundedButton(ops, text="下线选中设备", style="soft",
                                      height=30, parent_bg=theme.CARD,
                                      font=theme.FONT_BUTTON_SMALL,
                                      command=self.action_kick_selected)
        self.btn_kick.pack(side=tk.LEFT)

        # ---- 状态栏 ----
        self.status_bar = tk.Label(self.root, text="就绪", anchor="w",
                                   bg=theme.PRIMARY_SOFT, fg=theme.PRIMARY_DARK,
                                   font=theme.FONT_SMALL, padx=16, pady=7)
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

    def _show_unconfigured(self):
        """没有账号时的占位提示。

        不能只靠"正在检测…"这个初始文本——它会让用户以为程序在工作，
        实际是在等一个永远不会发生的刷新。
        """
        self._set_state(STATE_UNKNOWN)
        self.state_label.configure(text="未设置账号")
        self.detail_label.configure(text="请点右上角【设置】填写学号和密码")

    def _on_ui_error(self, exc):
        """主线程回调抛异常时的兜底：解除忙碌 + 让用户看得见。"""
        try:
            self._set_busy(False, "界面更新出错")
        except Exception:
            self._busy = False
        label = getattr(self, "detail_label", None)
        if label is not None:
            try:
                label.configure(text="界面更新出错：%s" % exc)
            except Exception:
                pass
        if self._error_shown or self._closing:
            return
        self._error_shown = True
        if self._settings_dialog is not None:
            return          # 模态窗口开着时弹框容易抢焦点，先只写在界面上
        try:
            messagebox.showerror(
                "校园网助手",
                "界面更新出错，操作已恢复。\n\n%s\n\n详细日志：%s"
                % (exc, logmod.log_path()))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 刷新收尾：状态文字与忙碌标记必须无条件更新
    # ------------------------------------------------------------------
    def _arm_watchdog(self):
        self._disarm_watchdog()
        try:
            self._watchdog_id = self.root.after(REFRESH_WATCHDOG_MS,
                                                self._on_watchdog)
        except Exception:
            self._watchdog_id = None

    def _disarm_watchdog(self):
        if self._watchdog_id is None:
            return
        try:
            self.root.after_cancel(self._watchdog_id)
        except Exception:
            pass
        self._watchdog_id = None

    def _on_watchdog(self):
        """worker 卡死时也要把界面救回来，不能让"正在检测…"永久挂着。"""
        self._watchdog_id = None
        if not self._busy:
            return
        if self.logger:
            self.logger.warning("刷新超过 %d 秒未收尾，强制解除忙碌状态",
                                REFRESH_WATCHDOG_MS // 1000)
        self._set_state(STATE_UNKNOWN)
        self.detail_label.configure(
            text="查询超过 %d 秒仍未返回，请检查网络后点【刷新】重试"
                 % (REFRESH_WATCHDOG_MS // 1000))
        self._finish_refresh("查询超时")

    def _finish_refresh(self, message, seq=None):
        if seq is not None and seq != self._refresh_seq:
            # 这次刷新已被看门狗判超时、或已被更新的刷新取代，别再去动界面
            return
        self._disarm_watchdog()
        self._set_busy(False, message)
        if self._refresh_pending and not self._closing:
            self._refresh_pending = False
            try:
                self.root.after(0, self.refresh)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 设备列表
    # ------------------------------------------------------------------
    def _visible_devices(self):
        """渲染/勾选用的设备列表：丢掉没有 IP 的脏行，同一 IP 只留一条。

        同一 IP 出现多条会话（双栈各一条、或服务端残留旧会话）是实测可能发生的；
        而 Treeview 的 iid 必须唯一，重复时 insert 会抛
        ``TclError: Item 10.x.x.x already exists``——这正是"卡在正在检测…"的元凶之一。
        """
        out, seen = [], set()
        for dev in policy.sort_oldest_first(self.devices or []):
            ip = getattr(dev, "ip", "") or ""
            if not ip or ip in seen:
                continue
            seen.add(ip)
            out.append(dev)
        return out

    def _render_devices(self):
        self.tree.delete(*self.tree.get_children())
        visible = self._visible_devices()
        for index, dev in enumerate(visible):
            checked = "☑" if dev.ip in self.checked else "☐"
            if self.my_ip and dev.ip == self.my_ip:
                tags = ("local",)
            else:
                tags = ("even",) if index % 2 else ("odd",)
            suffix = "  ← 本机" if self.my_ip and dev.ip == self.my_ip else ""
            self.tree.insert("", tk.END, iid=dev.ip, tags=tags, values=(
                checked, dev.client_type_label, dev.os_name, dev.add_time,
                dev.online_text(), dev.ip + suffix))
        self.section_label.configure(
            text="在线设备（%d）" % len(visible))
        self.hint_label.configure(text="点击行最左侧勾选")

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
        self.checked = {d.ip for d in self._visible_devices()}
        self._render_devices()

    def _check_none(self):
        self.checked = set()
        self._render_devices()

    # ------------------------------------------------------------------
    # 动作
    # ------------------------------------------------------------------
    def refresh(self):
        if self._busy:
            # 忙的时候不能静默丢弃：首次使用时"保存后刷新"正是在这里被丢掉的，
            # 结果只能等那次早于保存发出的刷新来更新界面，一旦它出错就永久卡住
            self._refresh_pending = True
            self._status("正在查询，完成后自动刷新…")
            return
        self._set_busy(True, "正在查询…")
        self._arm_watchdog()
        self._refresh_seq += 1
        seq = self._refresh_seq

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
            message = "查询失败"
            try:
                if seq != self._refresh_seq:
                    return          # 迟到的结果，已经超时作废
                message = self._apply_refresh(*result)
            except Exception as exc:
                # 界面更新出错也绝不能把忙碌状态留在 True
                self._on_ui_error(exc)
                try:
                    self._set_state(STATE_UNKNOWN)
                    self.detail_label.configure(text="刷新失败：%s" % exc)
                except Exception:
                    pass
            finally:
                self._finish_refresh(message, seq)

        def fail(exc):
            try:
                if seq != self._refresh_seq:
                    return
                self._set_state(STATE_UNKNOWN)
                self.detail_label.configure(text="查询失败：%s" % exc)
            finally:
                self._finish_refresh("查询失败", seq)

        self.runner.submit(work, done, fail)

    def _apply_refresh(self, state, status, devices):
        """把查询结果落到界面上；返回状态栏文案。

        渲染设备列表放在独立的 try 里：列表渲染失败只影响列表，
        不能连带把状态文字和忙碌标记一起拖死（这就是"永久卡在正在检测…"的成因）。
        """
        self.my_ip = getattr(status, "ip", None)
        self.devices = list(devices or [])
        self.checked &= {d.ip for d in self.devices if getattr(d, "ip", "")}
        try:
            self._render_devices()
        except Exception as exc:
            if self.logger:
                self.logger.exception("渲染设备列表失败: %s", exc)
            self.section_label.configure(text="在线设备（列表渲染失败）")
            self.hint_label.configure(text="设备列表无法显示，状态与登录仍可正常使用")
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
        return "已更新 %s" % _now()

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
        win.geometry("660x460")

        card = tk.Frame(win, bg=theme.CARD)
        card.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        head = tk.Frame(card, bg=theme.CARD)
        head.pack(fill=tk.X, padx=18, pady=(16, 4))
        tk.Label(head, text="需要先下线一台设备才能登录", bg=theme.CARD,
                 fg=theme.TEXT, font=theme.FONT_SECTION).pack(anchor="w")
        tk.Label(head, text="策略：%s　带 ☑ 的是预选，可自行改选"
                 % self.cfg.kick_mode, bg=theme.CARD, fg=theme.MUTED,
                 font=theme.FONT_SMALL).pack(anchor="w", pady=(3, 0))

        frame = tk.Frame(card, bg=theme.CARD)
        frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=8)
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
        tree.tag_configure("odd", background=theme.CARD)
        tree.tag_configure("even", background=theme.CARD_SOFT)
        tree.tag_configure("local", background=theme.PRIMARY_TINT)
        tree.pack(fill=tk.BOTH, expand=True)

        checked = {d.ip for d in preselected}

        def render():
            tree.delete(*tree.get_children())
            for index, dev in enumerate(policy.sort_oldest_first(devices)):
                mark = "☑" if dev.ip in checked else "☐"
                if my_ip and dev.ip == my_ip:
                    tags = ("local",)
                else:
                    tags = ("even",) if index % 2 else ("odd",)
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
        footer = tk.Frame(card, bg=theme.PRIMARY_TINT)
        footer.pack(fill=tk.X, side=tk.BOTTOM)
        row = tk.Frame(footer, bg=theme.PRIMARY_TINT)
        row.pack(fill=tk.X, padx=16, pady=12)

        def confirm():
            if not checked:
                messagebox.showinfo("校园网助手", "至少选择一台要下线的设备。",
                                    parent=win)
                return
            result["ips"] = sorted(checked)
            win.destroy()

        RoundedButton(row, text="取消", style="soft", height=36,
                      parent_bg=theme.PRIMARY_TINT, font=theme.FONT_BUTTON,
                      command=win.destroy).pack(side=tk.RIGHT)
        RoundedButton(row, text="下线并继续登录", style="accent", height=36,
                      parent_bg=theme.PRIMARY_TINT,
                      font=theme.FONT_BUTTON_BOLD,
                      command=confirm).pack(side=tk.RIGHT, padx=10)
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
        self._disarm_watchdog()
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
        tk.Label(parent, text=label, bg=theme.CARD, fg=theme.MUTED,
                 font=theme.FONT_SMALL).grid(row=index, column=0, sticky="w",
                                      padx=(20, 10), pady=7)
        return index + 1

    def _build(self, first_run):
        shell = tk.Frame(self.win, bg=theme.BG)
        shell.pack(fill=tk.BOTH, expand=True)
        card = tk.Frame(shell, bg=theme.CARD)
        card.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        body = card
        r = 0
        if first_run:
            head = tk.Frame(body, bg=theme.CARD)
            head.grid(row=r, column=0, columnspan=3, sticky="w",
                      padx=20, pady=(18, 2))
            emblem = theme.load_image("emblem-ui.png", master=self.win)
            if emblem:
                self._emblem_img = emblem
                if emblem.width() > 64:
                    emblem = emblem.subsample(2, 2)
                    self._emblem_img_small = emblem
                tk.Label(head, image=emblem, bg=theme.CARD).pack(side=tk.LEFT,
                                                                 padx=(0, 12))
            title = tk.Frame(head, bg=theme.CARD)
            title.pack(side=tk.LEFT)
            tk.Label(title, text="欢迎使用校园网助手", bg=theme.CARD,
                     fg=theme.TEXT, font=theme.FONT_SECTION).pack(anchor="w")
            tk.Label(title, text="第一次使用，先填一下校园网账号",
                     bg=theme.CARD, fg=theme.MUTED,
                     font=theme.FONT_SMALL).pack(anchor="w", pady=(2, 0))
            r += 1
            tk.Label(body, text="密码会用 Windows DPAPI 加密保存在本机，只有你本人能解开。",
                     bg=theme.CARD, fg=theme.MUTED, font=theme.FONT_SMALL,
                     wraplength=460, justify=tk.LEFT).grid(
                         row=r, column=0, columnspan=3, sticky="w",
                         padx=20, pady=(0, 6))
            r += 1

        r = self._row(body, r, "账号")
        self.var_user = tk.StringVar(value=self.cfg.username)
        self.entry_user = ttk.Entry(body, textvariable=self.var_user, width=30,
                                    font=theme.FONT_BODY)
        self.entry_user.grid(row=r - 1, column=1, sticky="w", pady=6)

        r = self._row(body, r, "密码")
        self.var_pwd = tk.StringVar()
        self.entry_pwd = ttk.Entry(body, textvariable=self.var_pwd, width=30,
                                   show="●", font=theme.FONT_BODY)
        self.entry_pwd.grid(row=r - 1, column=1, sticky="w", pady=6)
        tk.Label(body, text="留空表示不修改（已保存：%s）"
                 % ("是" if self.cfg.get_password() else "否"),
                 bg=theme.CARD, fg=theme.MUTED, font=theme.FONT_SMALL).grid(
                     row=r - 1, column=2, sticky="w", padx=(10, 20))

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
                 bg=theme.CARD, fg=theme.MUTED, font=theme.FONT_SMALL).grid(
                     row=r - 1, column=2, sticky="w", padx=(10, 20))

        r = self._row(body, r, "门户地址")
        self.var_base = tk.StringVar(value=self.cfg.base_url)
        ttk.Entry(body, textvariable=self.var_base, width=30,
                  font=theme.FONT_BODY).grid(row=r - 1, column=1, sticky="w", pady=6)

        r = self._row(body, r, "开机自启")
        start_box = tk.Frame(body, bg=theme.CARD)
        start_box.grid(row=r - 1, column=1, columnspan=2, sticky="w")
        try:
            enabled_now = autostart.is_enabled()
        except Exception:
            enabled_now = bool(self.cfg.get("startup.autostart", False))
        self.var_autostart = tk.BooleanVar(value=enabled_now)
        self.var_silent = tk.BooleanVar(
            value=bool(self.cfg.get("startup.silent_when_autostart", False)))
        ttk.Checkbutton(start_box, text="开机时自动启动本程序",
                        variable=self.var_autostart,
                        style="TCheckbutton").pack(anchor="w")
        ttk.Checkbutton(start_box, text="自启时静默启动（只留托盘，不弹窗口）",
                        variable=self.var_silent,
                        style="TCheckbutton").pack(anchor="w")
        tk.Label(body, text="开机自启只负责把程序跑起来，不会自动认证。",
                 bg=theme.CARD, fg=theme.MUTED, font=theme.FONT_SMALL).grid(
                     row=r, column=1, columnspan=2, sticky="w", pady=(2, 0))

        bar = tk.Frame(card, bg=theme.PRIMARY_TINT)
        bar.grid(row=r + 2, column=0, columnspan=3, sticky="ew")
        btns = tk.Frame(bar, bg=theme.PRIMARY_TINT)
        btns.pack(side=tk.RIGHT, padx=16, pady=12)
        RoundedButton(btns, text="取消", style="soft", height=36,
                      parent_bg=theme.PRIMARY_TINT, font=theme.FONT_BUTTON,
                      command=self.win.destroy).pack(side=tk.RIGHT)
        RoundedButton(btns, text="保存", style="accent", height=36,
                      parent_bg=theme.PRIMARY_TINT,
                      font=theme.FONT_BUTTON_BOLD,
                      command=self.save).pack(side=tk.RIGHT, padx=10)

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
        except Exception as exc:
            # 不能只接 AutostartUnsupported：注册表被拒、路径异常等都会抛别的异常，
            # 而在窗口程序里 Tk 会把它打到 stderr（用户根本看不到），
            # 结果就是"勾了却没生效"——必须显式告诉用户。
            if self.app and self.app.logger:
                self.app.logger.exception("设置开机自启失败")
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
                 font=theme.FONT_SECTION).pack(anchor="w")
        tk.Label(box, text=outcome["note"], bg=theme.CARD, fg=theme.MUTED,
                 font=theme.FONT_SMALL, wraplength=420,
                 justify=tk.LEFT).pack(anchor="w", pady=(6, 2))
        tk.Label(box, text="详细结果见日志：\n%s" % logmod.log_path(),
                 bg=theme.CARD, fg=theme.MUTED, font=theme.FONT_SMALL,
                 wraplength=420, justify=tk.LEFT).pack(anchor="w")
        RoundedButton(box, text="关闭", style="soft", height=34,
                      parent_bg=theme.CARD, font=theme.FONT_BUTTON,
                      command=box.destroy).pack(anchor="e", pady=(12, 0))
        box.after(10000, lambda: box.winfo_exists() and box.destroy())
        app.root.wait_window(box)
    except Exception:
        pass
    app.quit()
    return 0 if outcome["ok"] else 1
