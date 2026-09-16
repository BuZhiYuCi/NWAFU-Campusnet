#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""腾位策略：在线数已满时，该踢掉哪一台（或哪几台）。

背景（docs/01-project-design.md §4.4）：
在线设备列表只给 IP、系统、上线时间，**没有主机名和 MAC**，而 IP 是 DHCP 动态分配的，
所以"哪台是哪台"没法可靠自动判断。策略因此分三种：

- `preselect_oldest`（默认）：预选**上线时间最早**（在线最久）的那台，用户可改选；
- `priority`：按配置里给设备设的优先级挑，优先级数字大的先出局；
- `manual`：不预选，完全由用户勾选。
"""

#: 策略名
PRESELECT_OLDEST = "preselect_oldest"
PRIORITY = "priority"
MANUAL = "manual"

ALL_MODES = (PRESELECT_OLDEST, PRIORITY, MANUAL)


def sort_oldest_first(devices):
    """按上线时间升序（最早的在最前）。时间缺失的排最后。"""
    return sorted(devices, key=lambda d: (d.add_time or "9999", d.ip))


def sort_newest_first(devices):
    return sorted(devices, key=lambda d: (d.add_time or "", d.ip), reverse=True)


def _priority_of(device, device_prefs):
    """在配置的设备别名表里查这台设备的优先级。

    匹配依据是"最近一次记录到的 IP"（程序在自己登录成功时会记录），
    查不到就返回 0（视为未知，排在最不容易被踢的位置）。
    """
    for item in device_prefs or []:
        if item.get("last_ip") and item["last_ip"] == device.ip:
            try:
                return int(item.get("priority", 0))
            except (TypeError, ValueError):
                return 0
    return 0


def alias_of(device, device_prefs):
    """查设备别名（没有就返回空串）。"""
    for item in device_prefs or []:
        if item.get("last_ip") and item["last_ip"] == device.ip:
            return item.get("alias", "")
    return ""


def candidates(devices, my_ip=None):
    """可以被踢的设备：排除本机自己。"""
    return [d for d in devices if not my_ip or d.ip != my_ip]


def pick_victims(devices, my_ip=None, mode=PRESELECT_OLDEST, count=1,
                 device_prefs=None):
    """按策略挑出建议下线的设备列表（不真正执行，仅给 UI 预选）。

    :param devices: 在线设备列表
    :param my_ip: 本机 IP，会被排除（自己不用"被踢"）
    :param mode: 见模块文档
    :param count: 需要腾出几个名额
    :param device_prefs: 配置里的设备别名表（用于 priority 模式）
    :returns: 建议下线的 Device 列表；manual 模式返回空列表
    """
    pool = candidates(devices, my_ip)
    if not pool or mode == MANUAL:
        return []
    count = max(1, int(count or 1))
    if mode == PRIORITY:
        ordered = sorted(pool, key=lambda d: (-_priority_of(d, device_prefs),
                                              d.add_time or "9999", d.ip))
    else:
        ordered = sort_oldest_first(pool)
    return ordered[:count]


def describe_victims(victims, device_prefs=None, now=None):
    """给人看的一句话说明，例如 "10.1.1.1（台式机，已在线 3 天 2 小时）"。"""
    parts = []
    for dev in victims:
        alias = alias_of(dev, device_prefs)
        label = "%s（%s）" % (dev.ip, alias) if alias else dev.ip
        parts.append("%s，已在线 %s" % (label, dev.online_text(now)))
    return "；".join(parts) if parts else "（无）"
