#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对 src/campusnet 正式库做真实环境验证（Phase 1 验收）。

用法:
    python tools/verify_library.py            # 只读检查（不断网）
    python tools/verify_library.py --full     # 完整闭环（会短暂断网，建议后台运行）

--full 的流程:
    查在线 -> 踢掉本机会话（= 注销）-> 轮询确认离线 -> 离线查设备列表
    -> 重新登录 -> 轮询确认在线

因为断网期间 AI 会话也会中断，脚本把每一步写入 docs/phase1-verify.md，跑完可离线复盘。
"""

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from campusnet import SrunPortalClient, models  # noqa: E402

REPORT = os.path.join(ROOT, "docs", "phase1-verify.md")


class Report(object):
    def __init__(self, title):
        self.buf = []
        self.add("")
        self.add("---")
        self.add("")
        self.add("## [%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), title))
        self.add("")

    def add(self, line=""):
        self.buf.append(line)
        print(line)
        with open(REPORT, "a", encoding="utf-8") as f:
            f.write("\n".join(self.buf) + "\n")
        self.buf = []

    def kv(self, k, v):
        self.add("- %s: `%s`" % (k, v))

    def step(self, text):
        self.add("")
        self.add("### %s" % text)

    def json(self, label, obj):
        self.add("")
        self.add("%s:" % label)
        self.add("```json")
        self.add(json.dumps(obj, ensure_ascii=False, indent=2, default=str))
        self.add("```")


def load_credentials():
    user = os.environ.get("CAMPUSNET_USER", "")
    pwd = os.environ.get("CAMPUSNET_PASS", "")
    acid = os.environ.get("CAMPUSNET_ACID", "1")
    if not user or not pwd:
        path = os.path.join(os.environ.get("TEMP", "."), "campusnet_probe.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            user = d.get("username", "")
            pwd = d.get("password", "")
            acid = str(d.get("ac_id", acid))
    return user, pwd, acid


def show_devices(rep, devices):
    rows = [{"ip": d.ip, "类型": d.client_type_label, "系统": d.os_name,
             "上线时间": d.add_time, "已在线": d.online_text()} for d in devices]
    rep.json("在线设备", rows)


def main():
    full = "--full" in sys.argv
    user, pwd, acid = load_credentials()
    if not user or not pwd:
        print("缺少凭据（CAMPUSNET_USER / CAMPUSNET_PASS 或 %TEMP%\\campusnet_probe.json）")
        return 2

    client = SrunPortalClient(timeout=8)
    rep = Report("Phase 1 库验证（%s）" % ("完整闭环" if full else "只读检查"))
    rep.kv("账号", user)
    rep.kv("ac_id", acid)

    # ---- 0. 门户可达性 ----
    rep.step("① 门户可达性")
    reachable = client.portal_reachable()
    rep.kv("portal_reachable", reachable)
    if not reachable:
        rep.add("**不在校园网内，终止。**")
        return 3

    # ---- 1. 本机状态 ----
    rep.step("② 本机在线状态")
    status = client.user_info()
    rep.kv("online", status.online)
    rep.kv("online_ip", status.ip)
    rep.kv("user_name", status.user_name)
    rep.kv("online_device_total", status.device_total)
    rep.kv("user_mac", status.mac)
    if not status.online:
        rep.add("**本机当前不在线**（只读检查到此结束）。")
        return 0
    my_ip = status.ip

    # ---- 2. 在线设备列表 ----
    rep.step("③ 在线设备列表")
    devices = client.online_devices(user, pwd)
    show_devices(rep, devices)
    if devices:
        oldest = sorted(devices, key=lambda d: d.add_time)[0]
        rep.kv("默认预选（上线最早）", "%s  上线于 %s  已在线 %s"
               % (oldest.ip, oldest.add_time, oldest.online_text()))

    if not full:
        rep.add("")
        rep.add("只读检查完成，未做任何状态变更。")
        return 0

    # ---- 3. 注销本机（用 DM 踢自己）----
    rep.step("④ 注销本机（kick 自己的 IP）")
    res = client.kick(my_ip, user)
    rep.kv("kind", res.kind)
    rep.kv("message", res.message)
    rep.kv("http_status", res.http_status)
    rep.json("原始响应", res.raw)
    if res.kind == models.SIGNATURE_ERROR:
        rep.add("**签名被拒，终止（不会断网）。**")
        return 1

    # ---- 4. 确认离线 ----
    rep.step("⑤ 轮询确认离线（最多 15 秒）")
    t0 = time.time()
    status = client.wait(False, timeout=15)
    rep.kv("耗时", "%.1fs" % (time.time() - t0))
    rep.kv("online", status.online)
    rep.kv("error", status.error)
    if status.online:
        rep.add("**注销未生效，终止。**")
        return 1

    # ---- 5. 离线状态下查设备列表（核心能力）----
    rep.step("⑥ 离线状态下查询在线设备列表")
    try:
        offline_devices = client.online_devices(user, pwd)
        show_devices(rep, offline_devices)
        still_there = any(d.ip == my_ip for d in offline_devices)
        rep.kv("本机是否仍在列表中", still_there)
        rep.add("**离线查询可用：%s**" % ("是" if offline_devices is not None else "否"))
    except Exception as exc:
        rep.add("离线查询失败: `%s`" % exc)

    # ---- 6. 重新登录 ----
    rep.step("⑦ 重新登录（含超时容忍 + 轮询确认）")
    t0 = time.time()
    res = client.login_and_confirm(user, pwd, ip=my_ip, ac_id=acid,
                                   login_timeout=30, confirm_timeout=90,
                                   progress=lambda m: rep.add("  - %s" % m))
    rep.kv("kind", res.kind)
    rep.kv("message", res.message)
    rep.kv("confirmed", res.detail.get("confirmed"))
    rep.kv("总耗时", "%.1fs" % (time.time() - t0))
    rep.json("原始响应", res.raw)

    # ---- 7. 确认在线 ----
    rep.step("⑧ 独立复核在线状态")
    status = client.user_info()
    rep.kv("online", status.online)
    rep.kv("online_ip", status.ip)
    rep.kv("user_name", status.user_name)

    rep.step("⑨ 最终设备列表")
    try:
        show_devices(rep, client.online_devices(user, pwd))
    except Exception as exc:
        rep.add("查询失败: `%s`" % exc)

    ok = status.online
    rep.add("")
    rep.add("**Phase 1 完整闭环: %s**" % ("通过 ✔" if ok else "失败 ✘"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
