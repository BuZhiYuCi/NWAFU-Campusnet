#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""网络探测小工具。

注意一个坑：**判断"有没有网"不能只看 HTTP 状态码**。
未认证时准入设备会把 HTTP 请求拦下来返回门户页面，状态码常常还是 200。
可靠的判据是直接测 TCP 连接，或者检查返回内容是不是门户页面。
"""

import socket

# 用于判断"校园网以外是否可达"的稳定目标（114 公共 DNS）
PROBE_HOST = "114.114.114.114"
PROBE_PORT = 53


def local_ip():
    """本机在默认路由上的 IP（不发包，只问内核选哪块网卡）。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return ""
    finally:
        sock.close()


def internet_reachable(host=PROBE_HOST, port=PROBE_PORT, timeout=3.0):
    """能不能连到校园网以外的地址。

    用 TCP 而不是 HTTP：未认证时 HTTP 会被门户拦截并返回 200，
    看起来像"能上网"，实际并不能。
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False
