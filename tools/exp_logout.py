#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对照实验：action=logout（标准注销）之后，本机真的离线了吗？

背景：Phase 3 验收时发现 logout 之后设备列表里立刻多出一条
      client_type=6 / os_name="MAC auth" 的会话（本机 IP），
      疑似被准入设备的"MAC 免认证"重新拉上线。

本实验每隔 2 秒记录一次：rad_user_info 的返回、本机 IP 在设备列表里的
条目（含 client_type）、以及访问外网的结果，持续 24 秒，最后重新登录。
"""

import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from campusnet import SrunPortalClient  # noqa: E402

REPORT = os.path.join(ROOT, "docs", "phase3-verify.md")
CLIENT_TYPES = {"0": "无法判断", "1": "PC", "2": "移动设备", "5": "IP表免认证",
                "6": "MAC认证"}


def log(line=""):
    print(line)
    with open(REPORT, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def credentials():
    path = os.path.join(os.environ.get("TEMP", "."), "campusnet_probe.json")
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    return d["username"], d["password"], str(d.get("ac_id", "1"))


def tcp_ok(host="114.114.114.114", port=53, timeout=3):
    """能不能连到校园网以外的地址（比 HTTP 更直接）。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def http_probe(timeout=4):
    req = urllib.request.Request("http://www.baidu.com",
                                 headers={"User-Agent": "probe"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as r:
            body = r.read(400).decode("utf-8", "replace")
            return r.status, ("baidu" in body.lower())
    except urllib.error.HTTPError as e:
        return e.code, False
    except Exception as e:
        return type(e).__name__, False


def main():
    user, pwd, acid = credentials()
    client = SrunPortalClient(timeout=8)
    mode = (sys.argv[1] if len(sys.argv) > 1 else "logout").lower()

    log("")
    log("---")
    log("")
    log("## [%s] 对照实验：%s 之后的真实状态"
        % (time.strftime("%Y-%m-%d %H:%M:%S"),
           "rad_user_dm 踢自己" if mode == "kick" else "action=logout"))
    log("")
    st = client.user_info()
    my_ip = st.ip
    log("- 本机 IP: `%s`（实验前 online=%s）" % (my_ip, st.online))
    log("- 外网 TCP 可连: `%s`" % tcp_ok())

    log("")
    if mode == "kick":
        log("### ① 发起 rad_user_dm（踢本机 IP）")
        res = client.kick(my_ip, user)
    else:
        log("### ① 发起标准注销 action=logout")
        res = client.logout(user, ac_id=acid)
    log("- 服务端响应: `%s`（kind=%s）" % (json.dumps(res.raw, ensure_ascii=False), res.kind))

    log("")
    log("### ② 之后每 2 秒观察一次（共 24 秒）")
    log("")
    log("| t(s) | rad_user_info | 本机在设备列表里 | 外网 TCP | baidu HTTP |")
    log("| --- | --- | --- | --- | --- |")
    t0 = time.time()
    for i in range(13):
        st = client.user_info()
        try:
            devs = client.online_devices(user, pwd)
            mine = [d for d in devs if d.ip == my_ip]
        except Exception as exc:
            mine = None
            log("（设备列表查询失败：%s）" % exc)
        if mine:
            d = mine[0]
            entry = "%s / %s（%s）" % (CLIENT_TYPES.get(d.client_type, d.client_type),
                                      d.os_name, d.add_time)
        else:
            entry = "不在列表"
        code, is_baidu = http_probe()
        log("| %.0f | %s | %s | %s | %s |"
            % (time.time() - t0, st.error or ("在线" if st.online else "-"),
               entry, "✓" if tcp_ok() else "✗", "%s%s" % (code, " (真百度)" if is_baidu else "")))
        time.sleep(2)

    log("")
    log("### ③ 重新登录")
    res = client.login_and_confirm(user, pwd, ac_id=acid, confirm_timeout=60)
    log("- kind=%s message=%s confirmed=%s"
        % (res.kind, res.message, res.detail.get("confirmed")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
