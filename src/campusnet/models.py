#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据模型：在线设备、在线状态、接口调用结果。"""

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# 结果类型常量
# ---------------------------------------------------------------------------

SUCCESS = "success"                  # 操作成功
ALREADY_ONLINE = "already_online"    # 本机 IP 已在线
FULL = "full"                        # 在线数已满
NOT_ONLINE = "not_online"            # 当前不在线
SIGNATURE_ERROR = "signature_error"  # 签名/加密被拒
UNPARSED = "unparsed"                # 响应无法解析（多半是被准入门户拦截）
UNKNOWN = "unknown"                  # 其它业务错误
NETWORK_ERROR = "network_error"      # 请求根本没发出去
#: 服务端 5xx：请求到了，但服务器自己出错了。**不是**业务结论，
#: 不能据此判断"登录失败/在线数已满"，应当重试或用轮询确认（见 D-11）。
SERVER_ERROR = "server_error"

# ---------------------------------------------------------------------------
# 本机在线状态的三种取值（注意：与上面的"接口调用结果"常量是两回事）
#   ONLINE  —— 确定在线
#   OFFLINE —— 确定离线
#   UNKNOWN —— 查不到 / 被限流 / 网络抖动，不能据此判断在线与否
# ---------------------------------------------------------------------------

STATE_ONLINE = "online"
STATE_OFFLINE = "offline"
STATE_UNKNOWN = "unknown"

#: 服务端限流时返回的错误，遇到它要退避而不是当成"离线"
RATE_LIMIT_ERRORS = ("speed_limit_error",)
#: 明确表示"当前没有会话"的错误
OFFLINE_ERRORS = ("not_online_error",)

_KIND_TEXT = {
    SUCCESS: "操作成功",
    ALREADY_ONLINE: "本机已经在线",
    FULL: "在线设备数已达上限",
    NOT_ONLINE: "当前设备不在线",
    SIGNATURE_ERROR: "签名校验失败",
    UNPARSED: "服务端返回无法解析（可能不在校园网内）",
    UNKNOWN: "操作失败",
    NETWORK_ERROR: "网络请求失败",
    SERVER_ERROR: "服务端内部错误（5xx）",
}

#: 门户 client_type 字段含义（取自门户 lang.js）
CLIENT_TYPE_LABELS = {
    "0": "无法判断",
    "1": "PC",
    "2": "移动设备或其他",
    "3": "PC 客户端",
    "4": "移动客户端",
    "5": "IP 表免认证",
    "6": "MAC 认证",
    "7": "小程序直接认证",
    "8": "小程序扫码认证",
    "9": "微信认证",
    "10": "LDAP",
    "11": "钉钉认证",
}


@dataclass
class Device:
    """一台在线设备（来自 /v1/srun_portal_online）。

    注意：门户只提供 IP、系统、上线时间，**没有主机名和 MAC**，且 IP 是 DHCP 动态分配的，
    因此 IP 不能当作设备唯一标识。
    """

    ip: str
    user_name: str = ""
    client_type: str = ""
    os_name: str = ""
    add_time: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d):
        return cls(
            ip=str(d.get("ip", "")),
            user_name=str(d.get("user_name", "")),
            client_type=str(d.get("client_type", "")),
            os_name=str(d.get("os_name", "")),
            add_time=str(d.get("add_time", "")),
            raw=dict(d),
        )

    @property
    def client_type_label(self):
        return CLIENT_TYPE_LABELS.get(self.client_type, "未知(%s)" % self.client_type)

    @property
    def add_time_dt(self):
        """上线时间字符串 → datetime（服务端本地时间，无时区）。"""
        if not self.add_time:
            return None
        try:
            return _dt.datetime.strptime(self.add_time, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None

    def online_seconds(self, now=None):
        """已在线秒数；解析失败时返回 None。"""
        start = self.add_time_dt
        if start is None:
            return None
        now = now or _dt.datetime.now()
        return max(0, int((now - start).total_seconds()))

    def online_text(self, now=None):
        """已在线时长的人类可读文本，例如 '3 天 4 小时'。"""
        sec = self.online_seconds(now)
        if sec is None:
            return "-"
        days, rest = divmod(sec, 86400)
        hours, rest = divmod(rest, 3600)
        minutes = rest // 60
        if days:
            return "%d 天 %d 小时" % (days, hours)
        if hours:
            return "%d 小时 %d 分" % (hours, minutes)
        return "%d 分钟" % minutes

    def __str__(self):
        return "%s  %s  %s  上线于 %s" % (self.ip, self.client_type_label,
                                          self.os_name, self.add_time)


@dataclass
class OnlineStatus:
    """本机在线状态（来自 /cgi-bin/rad_user_info，按请求来源 IP 查询）。"""

    online: bool
    error: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def ip(self):
        return self.raw.get("online_ip")

    @property
    def state(self):
        """三态判定。**不能**用 `online == False` 当作"离线"——
        被限流（speed_limit_error）或网络抖动时同样会 online=False。"""
        if self.online:
            return STATE_ONLINE
        if str(self.error) in OFFLINE_ERRORS:
            return STATE_OFFLINE
        return STATE_UNKNOWN

    @property
    def rate_limited(self):
        return str(self.error) in RATE_LIMIT_ERRORS

    @property
    def ip6(self):
        return self.raw.get("online_ip6")

    @property
    def user_name(self):
        return self.raw.get("user_name")

    @property
    def mac(self):
        return self.raw.get("user_mac")

    @property
    def device_total(self):
        return self.raw.get("online_device_total")

    @property
    def is_me(self):
        """在线且是本账号 → 说明本机 IP 上的会话仍是自己（多半是上次没下线）。"""
        return self.online and bool(self.user_name)


@dataclass
class Challenge:
    """一次认证挑战（token 有效期 60 秒）。"""

    token: str
    client_ip: str = ""
    expire: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Result:
    """一次接口调用的结果。"""

    kind: str
    raw: Dict[str, Any] = field(default_factory=dict)
    http_status: Optional[int] = None
    ip: Optional[str] = None
    username: Optional[str] = None
    detail: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self):
        return self.kind == SUCCESS

    @property
    def message(self):
        from . import errors
        text = errors.message_for(self.raw)
        if text:
            return text
        return _KIND_TEXT.get(self.kind, "操作失败")

    def __bool__(self):
        return self.ok
