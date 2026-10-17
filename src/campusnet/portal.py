#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""深澜（SRun）校园网门户客户端。

只封装门户官方网页自己在用的那四个接口：
    - /cgi-bin/get_challenge     取 token
    - /cgi-bin/srun_portal       action=login / action=logout
    - /cgi-bin/rad_user_info     查本机在线状态
    - /v1/srun_portal_online     查本账号在线设备列表
    - /cgi-bin/rad_user_dm       踢指定设备下线（含"踢自己"= 等于注销）

协议细节与实测依据见 docs/02-portal-protocol.md。
"""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from . import crypto
from .models import (ALREADY_ONLINE, FULL, NETWORK_ERROR, NOT_ONLINE,
                     SERVER_ERROR, SIGNATURE_ERROR, STATE_OFFLINE, STATE_ONLINE,
                     STATE_UNKNOWN, SUCCESS, UNKNOWN, UNPARSED, Challenge,
                     Device, OnlineStatus, Result)

BASE_URL = "http://172.26.8.11"
DEFAULT_AC_ID = "1"
DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

_JSONP_RE = re.compile(r"^[A-Za-z_$][\w$.]*\s*\((.*)\)\s*;?$", re.S)


class PortalError(Exception):
    """门户交互相关的异常基类。"""


class PortalUnreachable(PortalError):
    """门户根本连不上（多半是不在校园网内）。"""


@dataclass
class HttpResponse:
    text: str
    status: Optional[int]
    location: Optional[str]
    url: str
    parsed: Optional[Dict[str, Any]]

    @property
    def is_html(self):
        return (self.text or "").lstrip()[:1] == "<"


def parse_jsonp(text):
    """剥掉 JSONP 外壳；不是 JSONP 就返回 None。"""
    t = (text or "").strip()
    if not t:
        return None
    if t[0] in "{[":
        try:
            return json.loads(t)
        except ValueError:
            return None
    m = _JSONP_RE.match(t)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except ValueError:
        return None


def classify(raw):
    """把接口响应归类成 models 里的结果常量。

    实测得到的判定顺序（docs/02-portal-protocol.md §3.5）：
    真正结果看 ploy_msg / suc_msg，而不是只看 ecode（成功和"已在线"都是 ecode=0）。
    """
    if not isinstance(raw, dict):
        return UNPARSED
    err = str(raw.get("error", "")).strip()
    res = str(raw.get("res", "")).strip()
    ecode = str(raw.get("ecode", "")).strip()
    suc = str(raw.get("suc_msg", "")).strip()
    ploy = str(raw.get("ploy_msg", "")).strip()
    emsg = str(raw.get("error_msg", "")).strip()
    text = " ".join((err, res, ecode, suc, ploy, emsg)).lower()

    if "sign_error" in text or "chksum" in text or "timeout" == emsg.lower():
        return SIGNATURE_ERROR
    if "already_online" in text:
        return ALREADY_ONLINE
    # E2620「已经在线了」是良性的，绝不能当成"在线数已满"——
    # 一旦误判成 FULL，上层就会走"腾位"流程去踢一台设备，
    # 而此刻真正在线的可能就是用户自己的机器（见 D-11）。
    if "e2620" in text:
        return ALREADY_ONLINE
    if "e6526" in text:          # 您的 IP 已经在线，可以直接上网
        return ALREADY_ONLINE
    if any(c in text for c in ("e2621", "e6512")):
        return FULL
    if "not_online" in text:
        return NOT_ONLINE
    # 深澜的"不在线"有一整族错误码/字样，中文文案里没有 not_online 这个词。
    # 漏掉它们会让"踢一台已经下线的设备"被当成失败（见 D-02）。
    if any(c in text for c in ("e6503", "e6527", "e6528",
                               "notonlineerror", "youarenotonline")):
        return NOT_ONLINE
    if ploy.upper().startswith("E0000"):
        return SUCCESS
    if err == "ok" and ecode in ("0", ""):
        return SUCCESS
    return UNKNOWN


def classify_response(resp):
    """在 ``classify`` 之外先看 HTTP 状态码。

    门户前面有反向代理和准入门户，5xx 时经常仍返回一段**看起来像 JSON 的**错误页
    （有时还带 ecode/ploy_msg），只按响应体分类会把它当成业务结论。
    这里把 5xx 单独归为 SERVER_ERROR：调用方据此重试或改用轮询确认，
    而不是立刻告诉用户"登录失败"甚至"在线数已满"。
    """
    status = getattr(resp, "status", None)
    if isinstance(status, int) and status >= 500:
        return SERVER_ERROR
    return classify(getattr(resp, "parsed", None))


class SrunPortalClient(object):
    """门户客户端。所有方法同步、带超时；不打印任何东西、不依赖 UI。"""

    def __init__(self, base_url=BASE_URL, timeout=8.0, user_agent=DEFAULT_UA):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.user_agent = user_agent
        # 门户在校园网内网，明确绕开系统代理
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        # rad_user_info 的限流冷却截止时间（见 local_state）
        self._rate_limited_until = 0.0

    # ------------------------------------------------------------------
    # 底层请求
    # ------------------------------------------------------------------
    def _request(self, path, params=None, timeout=None):
        params = dict(params or {})
        qs = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
        url = self.base_url + path + (("?" + qs) if qs else "")
        req = urllib.request.Request(url, headers={
            "User-Agent": self.user_agent,
            "Accept": "*/*",
            "Referer": self.base_url + "/srun_portal_pc?ac_id=1&theme=pro",
        })
        try:
            with self._opener.open(req, timeout=timeout or self.timeout) as resp:
                body = resp.read()
                status = getattr(resp, "status", None) or resp.getcode()
                location = resp.headers.get("Location")
        except urllib.error.HTTPError as exc:
            body = exc.read()
            status = exc.code
            location = exc.headers.get("Location") if exc.headers else None
        except Exception as exc:  # URLError / socket.timeout / OSError ...
            raise PortalUnreachable(str(exc))
        text = body.decode("utf-8", "replace")
        return HttpResponse(text=text, status=status, location=location,
                            url=url, parsed=parse_jsonp(text))

    # ------------------------------------------------------------------
    # 门户状态
    # ------------------------------------------------------------------
    def portal_reachable(self, timeout=3.0):
        """门户是否可达（用于判断"是不是在校园网里"）。"""
        try:
            resp = self._request("/cgi-bin/rad_user_info",
                                 {"callback": "cb", "_": _ts()}, timeout)
        except PortalUnreachable:
            return False
        return resp.parsed is not None

    def ac_detect(self):
        resp = self._request("/v1/srun_portal_detect", timeout=self.timeout)
        return resp.parsed or {}

    # ------------------------------------------------------------------
    # Token / 本机 IP
    # ------------------------------------------------------------------
    def get_challenge(self, username="", ip="", timeout=None):
        resp = self._request("/cgi-bin/get_challenge", {
            "callback": "cb", "username": username, "ip": ip, "_": _ts(),
        }, timeout)
        data = resp.parsed or {}
        token = data.get("challenge")
        if not token:
            raise PortalError("获取 challenge 失败：%s" % (resp.text.strip()[:200],))
        return Challenge(token=token, client_ip=data.get("client_ip", ""),
                         expire=str(data.get("expire", "")), raw=data)

    def detect_ip(self, username="", timeout=None):
        """服务端看到的本机 IP（登录参数 ip 的唯一可信来源）。"""
        return self.get_challenge(username=username, timeout=timeout).client_ip

    def local_ip(self, username="", timeout=None):
        """取本机在服务端眼里的 IP。

        rad_user_info 被限流时也要能拿到，所以走 get_challenge 的 client_ip。
        """
        return self.detect_ip(username=username, timeout=timeout)

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------
    def user_info(self, timeout=None):
        resp = self._request("/cgi-bin/rad_user_info",
                             {"callback": "cb", "_": _ts()}, timeout)
        data = resp.parsed
        # 5xx 时网关常常仍返回一段带 "error":"ok" 的 JSON，直接采信会把
        # "服务端挂了"读成"你在线"（见 D-11）。
        if isinstance(resp.status, int) and resp.status >= 500:
            return OnlineStatus(online=False, error=SERVER_ERROR,
                                raw=data if isinstance(data, dict) else {})
        if not isinstance(data, dict):
            return OnlineStatus(online=False, error=UNPARSED, raw={})
        online = str(data.get("error", "")) == "ok"
        return OnlineStatus(online=online, error=str(data.get("error", "")), raw=data)

    def online_devices(self, username, password, timeout=None):
        """查询本账号的在线设备列表（**离线状态下同样可用**，实测确认）。"""
        resp = self._request("/v1/srun_portal_online", {
            "user_name": username,
            "password": crypto.password_md5(password),
        }, timeout)
        data = resp.parsed or {}
        if str(data.get("code")) != "0":
            raise PortalError(errors_message(data) or "查询在线设备失败")
        return [Device.from_dict(x) for x in (data.get("data") or [])]

    # ------------------------------------------------------------------
    # 登录 / 注销 / 踢人
    # ------------------------------------------------------------------
    def login(self, username, password, ip=None, ac_id=DEFAULT_AC_ID,
              os_name="Windows 10", client_name="Windows", timeout=None):
        ip = ip or self.detect_ip(username, timeout=timeout)
        challenge = self.get_challenge(username=username, ip=ip, timeout=timeout)
        token = challenge.token
        ip = challenge.client_ip or ip
        hmd5 = crypto.hmac_md5(password, token)
        info = crypto.build_info(username, password, ip, ac_id, token)
        chksum = crypto.build_chksum(token, username, hmd5, ac_id, ip, 200, 1, info)
        resp = self._request("/cgi-bin/srun_portal", {
            "callback": "cb",
            "action": "login",
            "username": username,
            "password": "{MD5}" + hmd5,
            "os": os_name,
            "name": client_name,
            "double_stack": 0,
            "chksum": chksum,
            "info": info,
            "ac_id": ac_id,
            "ip": ip,
            "n": 200,
            "type": 1,
        }, timeout)
        return Result(kind=classify_response(resp), raw=resp.parsed or {},
                      http_status=resp.status, ip=ip, username=username,
                      detail={"token": token, "chksum": chksum})

    def logout(self, username, ip=None, ac_id=DEFAULT_AC_ID, timeout=None):
        """注销本机（服务端按 账号+IP 定位会话）。

        这里**不做**"先查在线状态再决定要不要注销"的前置判断：
        rad_user_info 可能被限流，那样会误判成离线而什么都不做。
        直接发请求、由服务端回答；"当前不在线"会归类成 NOT_ONLINE，
        对调用方来说是幂等的正常结果。
        """
        target_ip = ip or self.local_ip(username, timeout=timeout)
        resp = self._request("/cgi-bin/srun_portal", {
            "callback": "cb",
            "action": "logout",
            "username": username,
            "ip": target_ip,
            "ac_id": ac_id,
        }, timeout)
        return Result(kind=classify_response(resp), raw=resp.parsed or {},
                      http_status=resp.status, ip=target_ip, username=username)

    def kick(self, ip, username, unbind=1, timeout=None):
        """把指定 IP 的设备踢下线（对自己用就等于注销）。"""
        t, sign = crypto.dm_signature(username, ip, unbind)
        resp = self._request("/cgi-bin/rad_user_dm", {
            "callback": "cb",
            "ip": ip,
            "username": username,
            "time": t,
            "unbind": unbind,
            "sign": sign,
        }, timeout)
        return Result(kind=classify_response(resp), raw=resp.parsed or {},
                      http_status=resp.status, ip=ip, username=username,
                      detail={"time": t, "sign": sign})

    def logout_local(self, username, password=None, ip=None,
                     ac_id=DEFAULT_AC_ID, method="dm", timeout=None,
                     verify_timeout=8.0):
        """把**本机**真正下线，并确认结果。

        两种机制的实测差异（原始记录见 docs/03-logout-mechanisms.md）：

        - `action=logout`：只注销 RADIUS 会话。如果这台设备的 MAC 开通过
          "免认证"，准入设备会**在同一秒**用 MAC 把它重新认证上线——
          实测外网一秒都没断，设备列表里立刻变成 `client_type=6 MAC认证`。
        - `rad_user_dm`（unbind=1）：连 MAC 绑定一起解除。实测 60 秒以上
          都保持离线，外网 TCP 直接不通。

        所以默认用 `dm`；`method="portal"` 才退回 action=logout。
        """
        target_ip = ip or self.local_ip(username, timeout=timeout)
        if method == "portal":
            res = self.logout(username, ip=target_ip, ac_id=ac_id, timeout=timeout)
        else:
            res = self.kick(target_ip, username, unbind=1, timeout=timeout)

        state, status, devices = self.wait_state(
            STATE_OFFLINE, timeout=verify_timeout,
            username=username, password=password)
        res.detail["state"] = state
        res.detail["verified"] = (state == STATE_OFFLINE)
        res.detail["mechanism"] = "portal" if method == "portal" else "dm"
        if state == STATE_OFFLINE:
            res.kind = SUCCESS
        elif res.kind == SUCCESS:
            res.kind = UNKNOWN
            res.detail["still_online"] = True
        return res

    # ------------------------------------------------------------------
    # 状态判定与轮询
    # ------------------------------------------------------------------
    def local_state(self, username=None, password=None, timeout=None):
        """三态判定本机状态，返回 ``(state, status, devices)``。

        为什么要三态：`rad_user_info` 在请求过密时会返回 `speed_limit_error`
        （实测踩到过），它**不代表离线**。把"查不到"当成离线，
        会导致明明登录成功了却报告失败——这正是第一次跑 CLI 闭环时踩的坑。

        判定规则：

        - `error == "ok"`              → 在线
        - `error == "not_online_error"`→ 离线
        - 其它错误 / 网络异常           → 未知；此时用**在线设备列表**兜底判断
          （设备列表不受该限流影响，且能直接看到本机 IP 在不在里面）

        另外这里自己做了限流冷却：一旦撞到 `speed_limit_error`，接下来 60 秒内
        不再请求 `rad_user_info`，直接用设备列表判定——否则轮询本身会让限流
        一直续期，永远等不到解除（实测踩过这个坑）。
        """
        if time.time() < self._rate_limited_until and username and password:
            return self._state_from_devices(username, password, None, timeout)
        try:
            status = self.user_info(timeout=timeout)
        except PortalUnreachable:
            return STATE_UNKNOWN, OnlineStatus(online=False,
                                               error=NETWORK_ERROR, raw={}), []
        if status.state in (STATE_ONLINE, STATE_OFFLINE):
            return status.state, status, []

        if status.rate_limited:
            self._rate_limited_until = time.time() + 60
            if username and password:
                return self._state_from_devices(username, password, status, timeout)

        my_ip = status.ip
        if username and password and my_ip:
            try:
                devices = self.online_devices(username, password, timeout=timeout)
            except (PortalError, PortalUnreachable):
                return STATE_UNKNOWN, status, []
            state = (STATE_ONLINE if any(d.ip == my_ip for d in devices)
                     else STATE_OFFLINE)
            return state, status, devices
        return STATE_UNKNOWN, status, []

    def _state_from_devices(self, username, password, status, timeout=None):
        """用在线设备列表判定本机状态（设备列表接口不受 rad_user_info 限流影响）。"""
        try:
            devices = self.online_devices(username, password, timeout=timeout)
        except (PortalError, PortalUnreachable):
            return STATE_UNKNOWN, status or OnlineStatus(
                online=False, error="unknown", raw={}), []
        my_ip = (status.ip if status is not None else None)
        if not my_ip:
            try:
                my_ip = self.local_ip(username, timeout=timeout)
            except PortalError:
                return STATE_UNKNOWN, status or OnlineStatus(
                    online=False, error="unknown", raw={}), devices
        if not my_ip:
            return STATE_UNKNOWN, status or OnlineStatus(
                online=False, error="unknown", raw={}), devices
        state = (STATE_ONLINE if any(d.ip == my_ip for d in devices)
                 else STATE_OFFLINE)
        if status is None:
            status = OnlineStatus(online=(state == STATE_ONLINE),
                                  error="ok" if state == STATE_ONLINE
                                  else "not_online_error",
                                  raw={"online_ip": my_ip})
        else:
            # 状态是"推断"出来的，把 online 对齐到推断结果，
            # 否则会出现 state=online 而 status.online=False 的自相矛盾输出。
            # 注意必须新建对象：传进来的 status 可能被调用方复用，
            # 就地改属性会污染下一次判定（实测踩过：模块级共享的 OnlineStatus
            # 被上一个用例改成 online=True，下一个用例直接误判在线）。
            status = OnlineStatus(online=(state == STATE_ONLINE),
                                  error=status.error, raw=dict(status.raw))
        # 打上标记：这是合成状态，不是服务端原话，user_name/mac 必然为空。
        # 上层不能把它当成"确认在线且是本账号"，否则会误报 already_online（见 D-03/D-05）。
        status.raw.setdefault("online_ip", my_ip)
        status.raw["source"] = "device_list"
        status.raw["synthetic"] = True
        return state, status, devices

    def wait_state(self, want, timeout=15.0, interval=2.0,
                   username=None, password=None):
        """轮询直到本机状态变成 ``want``（STATE_ONLINE / STATE_OFFLINE）。

        必须轮询：实测发现刚登录成功后的极短时间内，rad_user_info 可能仍返回
        上一次的陈旧响应（docs/02-portal-protocol.md §4）。
        另外遇到限流要退避（服务端提示"请稍后 10s 重试"），
        否则轮询本身就会把自己打成限流。
        """
        deadline = time.time() + timeout
        delay = interval
        while True:
            state, status, devices = self.local_state(username, password)
            if state == want:
                return state, status, devices
            if time.time() >= deadline:
                return state, status, devices
            time.sleep(delay)
            delay = 10.0 if status.rate_limited else interval

    # ------------------------------------------------------------------
    # 登录 + 确认（推荐入口）
    # ------------------------------------------------------------------
    def login_and_confirm(self, username, password, ip=None, ac_id=DEFAULT_AC_ID,
                          login_timeout=30.0, confirm_timeout=90.0, progress=None):
        """登录并轮询确认会话真的建立了。

        为什么不能只看 login() 的返回：

        实测发现，注销后紧接着从同一个 IP 再登录时，服务端会**把请求挂起约 60 秒**
        （对应错误码 E6504「注销成功，请等1分钟后登录」），期间 HTTP 连接一直不返回。
        客户端若用较短的超时（如 8 秒）就会超时，但登录最终仍然成功——
        此时若把超时当成失败并提示用户，就是误报。

        因此本方法把"响应"和"实际结果"分开：
        先拿响应做快速判断，再轮询本机在线状态作为最终依据。
        """
        result = None
        try:
            result = self.login(username, password, ip=ip, ac_id=ac_id,
                                timeout=login_timeout)
        except PortalUnreachable as exc:
            result = Result(kind=NETWORK_ERROR, raw={}, detail={"exception": str(exc)})

        # 明确的业务失败（密码错、签名错、在线数满）不需要等
        if result.raw and result.kind in (FULL, SIGNATURE_ERROR, UNKNOWN):
            result.detail["confirmed"] = False
            return result

        if progress:
            progress("已发出登录请求（%s），等待服务端确认…" % result.kind)
        state, status, devices = self.wait_state(
            STATE_ONLINE, timeout=confirm_timeout, interval=2.0,
            username=username, password=password)
        result.detail["state"] = state
        result.detail["status"] = status
        result.detail["devices"] = devices
        result.detail["confirmed"] = (state == STATE_ONLINE)
        if state == STATE_ONLINE:
            # 会话已经建立，之前撞上的 rad_user_info 限流冷却必须立刻作废：
            # 否则接下来 60 秒内所有查询都会走"设备列表兜底"的合成状态，
            # 刚登录成功却可能被判成离线（见 D-05）。
            self._rate_limited_until = 0.0
            if result.kind in (NETWORK_ERROR, UNKNOWN, SERVER_ERROR):
                # 请求超时/响应丢失/服务端 5xx，但会话确实建立起来了
                result.kind = SUCCESS
            if ip is None:
                result.ip = status.ip
        elif state == STATE_OFFLINE and result.kind in (SUCCESS, ALREADY_ONLINE):
            # 服务端说成功，但没确认到在线——以实际状态为准
            result.kind = UNKNOWN
            result.detail["inconsistent"] = True
        elif result.kind in (SUCCESS, ALREADY_ONLINE):
            # 状态未知（多半是被限流）：请求本身成功，但无法确认，
            # 如实标注出来，让调用方提示用户复查
            result.detail["unconfirmed"] = True
        return result


def _ts():
    """jQuery 的 cache-buster 时间戳。"""
    return int(time.time() * 1000)


def errors_message(data):
    from . import errors
    return errors.message_for(data)
