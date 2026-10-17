#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""业务编排：把协议层的动作串成"一键"能用的操作。

这一层不打印任何东西、不依赖 UI，只返回 Outcome；
CLI 和将来的图形界面都调用它，行为保持一致。
"""

import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from . import policy
from .models import (ALREADY_ONLINE, FULL, NOT_ONLINE, STATE_OFFLINE,
                     STATE_ONLINE, STATE_UNKNOWN, SUCCESS, UNKNOWN, Device,
                     OnlineStatus, Result)


@dataclass
class Outcome:
    """一次业务操作的结果。"""

    ok: bool
    kind: str
    message: str
    kicked: List[str] = field(default_factory=list)
    devices: List[Device] = field(default_factory=list)
    victims: List[Device] = field(default_factory=list)
    result: Optional[Result] = None
    my_ip: Optional[str] = None

    def __bool__(self):
        return self.ok


# 决定踢谁的回调：收到 (全部设备, 预选设备, 本机 IP)，返回要下线的 IP 列表；
# 返回空列表或 None 表示放弃。
ApproveKick = Callable[[List[Device], List[Device], Optional[str]],
                       Optional[List[str]]]


class CampusNetService(object):
    """登录 / 下线 / 腾位 的编排。"""

    def __init__(self, client, config, logger=None, sleep=time.sleep):
        self.client = client
        self.cfg = config
        self.logger = logger
        self._sleep = sleep

    # ------------------------------------------------------------------
    # 配置快捷方式
    # ------------------------------------------------------------------
    @property
    def username(self):
        return self.cfg.username

    def password(self):
        return self.cfg.get_password()

    def ac_id(self):
        return self.cfg.ac_id

    def kick_mode(self):
        return self.cfg.get("behavior.kick_mode", policy.PRESELECT_OLDEST)

    def logout_method(self):
        return self.cfg.get("behavior.logout_method", "dm")

    def device_prefs(self):
        return self.cfg.get("devices", []) or []

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def local_status(self):
        return self.client.local_state(self.username or None, self.password())

    def devices(self):
        return self.client.online_devices(self.username, self.password())

    # ------------------------------------------------------------------
    # 下线
    # ------------------------------------------------------------------
    def logout(self):
        password = self.password()
        res = self.client.logout_local(self.username, password=password,
                                       ac_id=self.ac_id(),
                                       method=self.logout_method())
        if self.logger:
            self.logger.info("logout method=%s kind=%s state=%s",
                             self.logout_method(), res.kind,
                             res.detail.get("state"))
        # 必须先确认"真的下线了"再报成功：状态查不出来（限流/抖动）时
        # 只知道服务端回了个 not_online，不代表在线名额已经释放（见 D-07）。
        verified = bool(res.detail.get("verified"))
        if verified and res.kind == NOT_ONLINE:
            return Outcome(True, NOT_ONLINE, "当前已经是离线状态", result=res)
        if verified:
            return Outcome(True, SUCCESS, "已下线，在线名额已释放", result=res)
        if res.detail.get("still_online"):
            return Outcome(False, "still_online",
                           "下线请求已被接受，但本机紧接着又上线了", result=res)
        return Outcome(False, UNKNOWN, "无法确认下线结果（%s）" % res.message,
                       result=res)

    # ------------------------------------------------------------------
    # 踢指定设备
    # ------------------------------------------------------------------
    def kick(self, ips):
        """串行把指定 IP 的设备踢下线，返回逐条结果。"""
        interval = float(self.cfg.get("behavior.batch_kick_interval_ms", 800)) / 1000.0
        results = []
        for idx, ip in enumerate(ips):
            if idx:
                self._sleep(interval)
            res = self.client.kick(ip, self.username, unbind=1)
            if self.logger:
                self.logger.info("kick ip=%s kind=%s", ip, res.kind)
            results.append(res)
        return results

    # ------------------------------------------------------------------
    # 登录（含满员腾位）
    # ------------------------------------------------------------------
    def choose_victims(self, devices, my_ip, approve_kick=None, count=1):
        """挑出建议下线的设备；有 approve_kick 时交给调用方定夺。"""
        preselected = policy.pick_victims(
            devices, my_ip=my_ip, mode=self.kick_mode(),
            count=count, device_prefs=self.device_prefs())
        if approve_kick is None:
            return preselected, preselected
        approved = approve_kick(devices, preselected, my_ip)
        if not approved:
            return preselected, []
        wanted = set(approved)
        return preselected, [d for d in devices if d.ip in wanted]

    def login(self, approve_kick=None, max_rounds=3):
        """登录；如果提示在线数已满，就腾位后重试。

        :param approve_kick: 决定踢谁的回调；None 表示按策略直接执行
        :param max_rounds: 最多尝试几轮（每轮最多腾一次位）
        """
        password = self.password()
        state, status, devices = self.local_status()
        my_ip = status.ip
        if state == STATE_ONLINE:
            if status.user_name and status.user_name != self.username:
                return Outcome(False, "ip_taken",
                               "本机 IP（%s）已被其它账号 %s 占用"
                               % (my_ip, status.user_name),
                               devices=devices, my_ip=my_ip)
            if status.user_name:
                return Outcome(True, ALREADY_ONLINE, "本机已经在线",
                               devices=devices, my_ip=my_ip)
            # user_name 为空：这不是 rad_user_info 的原话，而是限流期间
            # 用设备列表兜底合成出来的状态（raw.synthetic）。据此断言
            # "已经在线"会让真正的登录被跳过，用户以为连上了其实没有（见 D-03）。
            # 继续往下走，让服务端自己给结论（真在线会回 E2620 → ALREADY_ONLINE）。
            if self.logger:
                self.logger.info("state=online 但 user_name 缺失（synthetic=%s），"
                                 "改为实际登录确认", status.raw.get("synthetic"))

        kicked = []
        result = None
        for round_no in range(max(1, int(max_rounds))):
            result = self.client.login_and_confirm(
                self.username, password, ac_id=self.ac_id(),
                login_timeout=float(self.cfg.get("portal.login_timeout_sec", 30)),
                confirm_timeout=float(self.cfg.get("portal.confirm_timeout_sec", 90)))
            if self.logger:
                self.logger.info("login round=%d kind=%s confirmed=%s",
                                 round_no + 1, result.kind,
                                 result.detail.get("confirmed"))
            if result.ok:
                return Outcome(True, SUCCESS, "登录成功", kicked=kicked,
                               devices=devices, result=result, my_ip=my_ip)
            if result.kind == ALREADY_ONLINE:
                return Outcome(True, ALREADY_ONLINE, "本机已经在线", kicked=kicked,
                               devices=devices, result=result, my_ip=my_ip)
            if result.kind != FULL:
                break

            # --- 在线数已满：先腾位 ---
            try:
                devices = self.devices()
            except Exception as exc:  # 拿不到列表就没法腾位
                return Outcome(False, FULL,
                               "在线数已满，且查询设备列表失败：%s" % exc,
                               kicked=kicked, result=result, my_ip=my_ip)
            if not devices:
                break
            _, victims = self.choose_victims(devices, my_ip, approve_kick)
            if not victims:
                return Outcome(False, "declined", "没有选择要下线的设备，已取消",
                               devices=devices, result=result, my_ip=my_ip)
            if self.logger:
                self.logger.info("free slots: %s",
                                 ", ".join(v.ip for v in victims))
            results = self.kick([v.ip for v in victims])
            freed = [r.ip for r in results if r.ok or r.kind == NOT_ONLINE]
            kicked.extend(freed)
            if not freed:
                return Outcome(False, "kick_failed", "腾位失败，未能下线任何设备",
                               kicked=kicked, devices=devices, victims=victims,
                               result=result, my_ip=my_ip)
            self._sleep(1.0)

        # 注意：Result 定义了 __bool__（失败的 Result 是假值），
        # 这里必须用 `is not None` 判断，不能写成 `if result`。
        kind = result.kind if result is not None else UNKNOWN
        if kind == FULL:
            return Outcome(False, FULL, "在线数已满，腾位后仍然登录失败",
                           kicked=kicked, devices=devices, result=result,
                           my_ip=my_ip)
        return Outcome(False, kind,
                       result.message if result is not None else "登录失败",
                       kicked=kicked, devices=devices, result=result,
                       my_ip=my_ip)
