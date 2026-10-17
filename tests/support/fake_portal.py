#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地 HTTP 桩门户：在 127.0.0.1 上起一个可编程的假门户。

为什么需要它：现有 216 条测试里，真实 HTTP 交互覆盖为 0——`_request`、
HTTPError 分支、超时语义、非 JSONP 降级全都没测过，而线上故障最容易出在这一层。
桩服务器不碰真实校园网，也不会消耗门户的限流配额。

用法::

    with FakePortal() as fp:
        fp.jsonp("/cgi-bin/rad_user_info", {"error": "ok", "online_ip": "10.0.0.1"})
        client = SrunPortalClient(base_url=fp.base_url, timeout=0.5)
        state, status, _ = client.local_state()

刻意用 HTTP/1.0（响应即断开），避免 keep-alive 与 Content-Length 的干扰。
"""

import json
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

JSONP_TYPE = "application/javascript; charset=utf-8"
JSON_TYPE = "application/json; charset=utf-8"
HTML_TYPE = "text/html; charset=utf-8"


class Route(object):
    """一条路由的响应定义。"""

    __slots__ = ("status", "body", "headers", "delay", "content_type")

    def __init__(self, status=200, body="", headers=None, delay=0.0,
                 content_type=JSONP_TYPE):
        self.status = status
        self.body = body
        self.headers = dict(headers or {})
        self.delay = delay
        self.content_type = content_type

    @property
    def raw(self):
        if isinstance(self.body, bytes):
            return self.body
        return str(self.body).encode("utf-8")


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    server_version = "FakeSrunPortal/1.0"

    def log_message(self, fmt, *args):      # 静音，别把测试输出刷满
        pass

    def do_GET(self):
        portal = self.server.portal
        parts = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
        portal.requests.append({
            "path": parts.path,
            "query": {k: v[0] for k, v in query.items()},
            "headers": dict(self.headers),
            "at": time.time(),
        })
        route = portal.routes.get(parts.path)
        if route is None:
            route = portal.fallback
        if route.delay:
            time.sleep(route.delay)
        body = route.raw
        try:
            self.send_response(route.status)
            self.send_header("Content-Type", route.content_type)
            self.send_header("Content-Length", str(len(body)))
            for key, value in route.headers.items():
                self.send_header(key, value)
            self.end_headers()
            if body:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, OSError):
            # 客户端已经超时断开，属预期
            pass


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class FakePortal(object):
    """可编程的假门户。所有请求都会被记录在 ``requests`` 里。"""

    def __init__(self, host="127.0.0.1", port=0):
        self.routes = {}
        self.requests = []
        self.fallback = Route(404, "not found", content_type="text/plain")
        self._server = _Server((host, port), _Handler)
        self._server.portal = self
        self.host, self.port = self._server.server_address[:2]
        self._thread = None

    # -- 生命周期 ------------------------------------------------------
    def start(self):
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        kwargs={"poll_interval": 0.02},
                                        daemon=True)
        self._thread.start()
        return self

    def stop(self):
        try:
            self._server.shutdown()
        except Exception:
            pass
        try:
            self._server.server_close()
        except Exception:
            pass
        if self._thread:
            self._thread.join(timeout=3.0)
            self._thread = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
        return False

    # -- 地址 ----------------------------------------------------------
    @property
    def base_url(self):
        return "http://%s:%d" % (self.host, self.port)

    # -- 路由配置 ------------------------------------------------------
    def set(self, path, body="", status=200, delay=0.0,
            content_type=JSONP_TYPE, headers=None):
        self.routes[path] = Route(status=status, body=body, delay=delay,
                                  content_type=content_type, headers=headers)
        return self

    def jsonp(self, path, payload, callback="cb", status=200, delay=0.0):
        """返回 ``cb({...})`` 形式的响应（深澜门户的默认格式）。"""
        text = "%s(%s)" % (callback, json.dumps(payload, ensure_ascii=False))
        return self.set(path, text, status=status, delay=delay)

    def json(self, path, payload, status=200, delay=0.0):
        return self.set(path, json.dumps(payload, ensure_ascii=False),
                        status=status, delay=delay, content_type=JSON_TYPE)

    def raw(self, path, body, status=200, delay=0.0,
            content_type=HTML_TYPE):
        return self.set(path, body, status=status, delay=delay,
                        content_type=content_type)

    # -- 观测 ----------------------------------------------------------
    def hits(self, path=None):
        if path is None:
            return list(self.requests)
        return [r for r in self.requests if r["path"] == path]

    def reset(self):
        self.requests = []

    # -- 常用剧本 ------------------------------------------------------
    def scenario_online(self, ip="10.0.0.1", devices=None):
        """本机在线 + 设备列表。"""
        self.jsonp("/cgi-bin/rad_user_info", {
            "error": "ok", "online_ip": ip, "online_device_total": "1",
            "user_name": "20230000001",
        })
        self.json("/v1/srun_portal_online", {
            "code": 0, "message": "Success", "data": devices or [
                {"add_time": "2026-09-12 20:35:39", "client_type": "1",
                 "ip": ip, "os_name": "Windows 10", "user_name": "20230000001"},
            ],
        })
        return self

    def scenario_offline(self, ip="10.0.0.1"):
        self.jsonp("/cgi-bin/rad_user_info", {
            "error": "not_online_error", "online_ip": ip,
        })
        return self

    def scenario_rate_limited(self, ip="10.0.0.1"):
        self.jsonp("/cgi-bin/rad_user_info", {
            "error": "speed_limit_error", "online_ip": ip,
            "error_msg": "认证请求太频繁，请稍后10s重试",
        })
        return self
