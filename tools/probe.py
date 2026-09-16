#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深澜（SRun）校园网认证协议探测器 —— Phase 0 一次性验证工具

用法:
    python tools/probe.py selftest          # 本地加密自检（对比官方 JS 向量，不联网）
    python tools/probe.py status            # 只读：本机在线状态 + 在线设备列表
    python tools/probe.py stagea            # 在线探针：保持在线的前提下验证登录算法（不断网）
    python tools/probe.py stageb --yes      # 断网闭环：DM 注销本机 -> 离线查询 -> 重新登录

凭据来源（按优先级）:
    1) 环境变量 CAMPUSNET_USER / CAMPUSNET_PASS / CAMPUSNET_ACID
    2) %TEMP%\\campusnet_probe.json   {"username": "...", "password": "...", "ac_id": 1}

仅使用 Python 标准库；所有请求绕过系统代理。
"""

import base64
import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
TESTS = os.path.join(ROOT, "tests")
REPORT = os.path.join(DOCS, "phase0-report.md")
STAGEA_JSON = os.path.join(TESTS, "stagea-result.json")

BASE_URL = "http://172.26.8.11"
DOMAIN_SUFFIX = "@yx-s-student"
DEFAULT_ACID = "1"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# ============================================================================
# 加密实现（按门户官方 JS 逐行移植）
# ============================================================================

CUSTOM_ALPHA = "LVoJPiCN2R8G90yg+hmFHuacZ1OWMnrsSTXkYpUq/3dlbfKwv6xztjI7DeBE45QA"
STD_ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
B64_TRANS = str.maketrans(STD_ALPHA, CUSTOM_ALPHA)
U32 = 0xFFFFFFFF


def custom_b64_encode(raw):
    """srun 自定义字母表 base64（PHP 插件是逐 byte 映射，不做 UTF-8 转换）。"""
    return base64.b64encode(raw).decode("ascii").translate(B64_TRANS)


def _str2long(s, include_len):
    """对应 JS 的 s(a, b)：小端打包成 32 位字数组。"""
    v = []
    c = len(s)
    for i in range(0, c, 4):
        chunk = s[i:i + 4]
        b = [ord(ch) & 0xFF for ch in chunk]
        while len(b) < 4:
            b.append(0)
        v.append(b[0] | (b[1] << 8) | (b[2] << 16) | (b[3] << 24))
    if include_len:
        v.append(c)
    return v


def _long2str(v, include_len):
    """对应 JS 的 l(a, b)：小端拆回字节串。"""
    out = bytearray()
    for x in v:
        out += bytes((x & 0xFF, (x >> 8) & 0xFF, (x >> 16) & 0xFF, (x >> 24) & 0xFF))
    if include_len:
        c = ((len(v) - 1) << 2) & U32
        m = v[-1]
        if m < c - 3 or m > c:
            raise ValueError("long2str: 长度字段非法")
        return bytes(out[:m])
    return bytes(out)


def xxtea_encode(text, key):
    """对应 Portal.js 里的 encode(str, key)：XXTEA，delta=0x9E3779B9。"""
    v = _str2long(text, True)
    k = _str2long(key, False)
    while len(k) < 4:
        k.append(0)
    n = len(v) - 1
    z = v[n]
    y = v[0]
    c = 0x9E3779B9
    q = 6 + 52 // (n + 1)
    d = 0
    while q > 0:
        q -= 1
        d = (d + c) & U32
        e = (d >> 2) & 3
        for p in range(n):
            y = v[p + 1]
            m = (z >> 5) ^ ((y << 2) & U32)
            m = (m + (((y >> 3) ^ ((z << 4) & U32) ^ (d ^ y)) & U32)) & U32
            m = (m + ((k[(p & 3) ^ e] ^ z) & U32)) & U32
            z = (v[p] + m) & U32
            v[p] = z
        y = v[0]
        m = (z >> 5) ^ ((y << 2) & U32)
        m = (m + (((y >> 3) ^ ((z << 4) & U32) ^ (d ^ y)) & U32)) & U32
        m = (m + ((k[(n & 3) ^ e] ^ z) & U32)) & U32
        z = (v[n] + m) & U32
        v[n] = z
    return _long2str(v, False)


def hmd5_hmac(password, token):
    """官方 JS: md5(password, token) -> HMAC-MD5(key=token, msg=password)。"""
    return hmac.new(token.encode("utf-8"), password.encode("utf-8"), hashlib.md5).hexdigest()


def hmd5_concat(password, token):
    """老版门户写法: md5(password + token)，作为对照。"""
    return hashlib.md5((password + token).encode("utf-8")).hexdigest()


def build_info_json(username, password, ip, acid, enc_ver="srun_bx1"):
    """与 JS 的 JSON.stringify 字段顺序严格一致。"""
    return json.dumps({
        "username": username,
        "password": password,
        "ip": ip,
        "acid": acid,
        "enc_ver": enc_ver,
    }, separators=(",", ":"), ensure_ascii=False)


def build_info(username, password, ip, acid, token, enc_ver="srun_bx1"):
    payload = build_info_json(username, password, ip, acid, enc_ver)
    return "{SRBX1}" + custom_b64_encode(xxtea_encode(payload, token))


def build_chksum(token, username, hmd5, acid, ip, n, typ, info):
    s = (token + username + token + hmd5 + token + str(acid) + token + ip +
         token + str(n) + token + str(typ) + token + info)
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def password_md5(password):
    return hashlib.md5(password.encode("utf-8")).hexdigest()


def js_time_str():
    """模拟 JS 的 Date.parse(new Date())/1000。

    坑点：Date.parse(new Date()) 会先把 Date 转成字符串，而该字符串只精确到秒，
    所以实际得到的是**整数秒**，而不是带毫秒的小数。float 模式保留作为对照。
    """
    return str(int(time.time()))


def js_time_str_float():
    """对照实现：真正的秒 + 毫秒小数（用于验证服务端到底接受哪种）。"""
    s = "%.3f" % time.time()
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


# ============================================================================
# HTTP
# ============================================================================

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """不自动跟随跳转：未认证时准入设备可能把请求 302 到认证页，需要看见它。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
LAST = {}


def http_get(base, path, params=None, timeout=8):
    params = params or {}
    qs = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    url = base + path + (("?" + qs) if qs else "")
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "*/*",
        "Referer": base + "/srun_portal_pc?ac_id=1&theme=pro",
    })
    status, loc = None, None
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            raw = resp.read()
            status = getattr(resp, "status", None) or resp.getcode()
            loc = resp.headers.get("Location")
    except urllib.error.HTTPError as e:
        raw = e.read()
        status = e.code
        loc = e.headers.get("Location") if e.headers else None
    LAST.clear()
    LAST.update({"path": path, "status": status, "location": loc})
    return raw.decode("utf-8", "replace"), url


def http_trace():
    if not LAST:
        return "-"
    s = "HTTP %s %s" % (LAST.get("status"), LAST.get("path"))
    if LAST.get("location"):
        s += " -> Location: %s" % LAST["location"][:120]
    return s


def parse_jsonp(text):
    t = (text or "").strip()
    if not t:
        return None
    if t[0] in "{[":
        try:
            return json.loads(t)
        except ValueError:
            pass
    m = re.match(r"^[A-Za-z_$][\w$.]*\s*\((.*)\)\s*;?$", t, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except ValueError:
            pass
    return None


def redact(url):
    return re.sub(r"(password=)[^&]*", r"\1***", url or "")


# ============================================================================
# 门户接口
# ============================================================================

def api_challenge(username, ip, timeout=8):
    data, url = http_get(BASE_URL, "/cgi-bin/get_challenge", {
        "callback": "cb", "username": username, "ip": ip,
        "_": int(time.time() * 1000),
    }, timeout)
    return parse_jsonp(data), data, url


def api_user_info(timeout=8):
    data, url = http_get(BASE_URL, "/cgi-bin/rad_user_info", {
        "callback": "cb", "_": int(time.time() * 1000),
    }, timeout)
    return parse_jsonp(data), data, url


def api_online_devices(username, password, timeout=8):
    data, url = http_get(BASE_URL, "/v1/srun_portal_online", {
        "user_name": username, "password": password_md5(password),
    }, timeout)
    return parse_jsonp(data), data, url


def api_login(username, password, ip, acid, timeout=8, algo="hmac",
              os_name="Windows 10", client_name="Windows"):
    cj, craw, curl = api_challenge(username, ip, timeout)
    if not isinstance(cj, dict) or not cj.get("challenge"):
        return None, craw, curl, {"error": "challenge_failed"}
    token = cj["challenge"]
    server_ip = cj.get("client_ip") or ip
    hmd5 = hmd5_hmac(password, token) if algo == "hmac" else hmd5_concat(password, token)
    info = build_info(username, password, server_ip, acid, token)
    chksum = build_chksum(token, username, hmd5, acid, server_ip, 200, 1, info)
    params = {
        "callback": "cb",
        "action": "login", "username": username, "password": "{MD5}" + hmd5,
        "os": os_name, "name": client_name, "double_stack": 0,
        "chksum": chksum, "info": info, "ac_id": acid, "ip": server_ip,
        "n": 200, "type": 1,
    }
    data, url = http_get(BASE_URL, "/cgi-bin/srun_portal", params, timeout)
    meta = {"token": token, "server_ip": server_ip, "hmd5": hmd5,
            "chksum": chksum, "info": info, "algo": algo, "username": username,
            "acid": acid}
    return parse_jsonp(data), data, url, meta


def api_logout(username, ip, acid, timeout=8):
    data, url = http_get(BASE_URL, "/cgi-bin/srun_portal", {
        "callback": "cb",
        "action": "logout", "username": username, "ip": ip, "ac_id": acid,
    }, timeout)
    return parse_jsonp(data), data, url


def api_dm_logout(username, ip, timeout=8, time_mode="float"):
    t = js_time_str() if time_mode == "int" else js_time_str_float()
    sign = hashlib.sha1((t + username + ip + "1" + t).encode("utf-8")).hexdigest()
    data, url = http_get(BASE_URL, "/cgi-bin/rad_user_dm", {
        "callback": "cb",
        "ip": ip, "username": username, "time": t, "unbind": 1, "sign": sign,
    }, timeout)
    return parse_jsonp(data), data, url, {"time": t, "sign": sign, "time_mode": time_mode}


# ============================================================================
# 分类与输出
# ============================================================================

ALREADY_CODES = {"E2620", "E2626", "E2621", "E6512", "E6526"}


def classify_login(res):
    if not isinstance(res, dict):
        return "unparsed"
    ecode = str(res.get("ecode", "")).strip()
    err = str(res.get("error", "")).strip()
    emsg = str(res.get("error_msg", "")).strip()
    suc = str(res.get("suc_msg", "")).strip()
    low = (err + " " + emsg + " " + suc).lower()
    if "already_online" in low or ecode in ALREADY_CODES:
        return "already_online"
    if err == "ok" and ecode in ("0", ""):
        return "success"
    if any(k in low for k in ("chksum", "sign", "encrypt", "decrypt", "info_error")):
        return "signature_error"
    return "other"


class Reporter(object):
    def __init__(self, title):
        self.title = title
        self.lines = []
        os.makedirs(DOCS, exist_ok=True)
        self.add("")
        self.add("---")
        self.add("")
        self.add("## [%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), title))
        self.add("")

    def add(self, line=""):
        self.lines.append(line)
        print(line)
        self.flush()

    def flush(self):
        try:
            with open(REPORT, "a", encoding="utf-8") as f:
                f.write("\n".join(self.lines) + "\n")
            self.lines = []
        except OSError as e:
            print("!! 写报告失败: %s" % e)

    def kv(self, k, v):
        self.add("- %s: `%s`" % (k, v))

    def json_block(self, label, obj):
        self.add("")
        self.add("%s:" % label)
        self.add("```json")
        self.add(json.dumps(obj, ensure_ascii=False, indent=2))
        self.add("```")


# ============================================================================
# 凭据
# ============================================================================

def load_config():
    cfg = {
        "base_url": BASE_URL,
        "username": os.environ.get("CAMPUSNET_USER", ""),
        "password": os.environ.get("CAMPUSNET_PASS", ""),
        "acid": os.environ.get("CAMPUSNET_ACID", DEFAULT_ACID),
        "timeout": 8,
    }
    if not cfg["username"] or not cfg["password"]:
        path = os.path.join(os.environ.get("TEMP", "."), "campusnet_probe.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            cfg["username"] = d.get("username", cfg["username"])
            cfg["password"] = d.get("password", cfg["password"])
            cfg["acid"] = str(d.get("ac_id", cfg["acid"]))
    return cfg


def require_credentials(cfg):
    if not cfg["username"] or not cfg["password"]:
        print("缺少凭据：请设置 CAMPUSNET_USER / CAMPUSNET_PASS 环境变量，")
        print("或写入 %TEMP%\\campusnet_probe.json")
        return False
    return True


# ============================================================================
# 子命令
# ============================================================================

def cmd_selftest():
    path = os.path.join(TESTS, "vectors.json")
    if not os.path.exists(path):
        print("缺少 %s，请先运行: node tools/js_reference.js <all.min.js>" % path)
        return 2
    with open(path, "r", encoding="utf-8") as f:
        vectors = json.load(f)["vectors"]
    ok = 0
    bad = []
    for i, c in enumerate(vectors):
        checks = [
            ("info", build_info(c["username"], c["password"], c["ip"], c["acid"], c["token"])),
            ("hmd5_hmac", hmd5_hmac(c["password"], c["token"])),
            ("hmd5_concat", hmd5_concat(c["password"], c["token"])),
        ]
        info = checks[0][1]
        chk = build_chksum(c["token"], c["username"], checks[1][1], c["acid"], c["ip"], 200, 1, info)
        checks.append(("chksum", chk))
        for name, got in checks:
            if got == c[name]:
                ok += 1
                print("  [OK]   case%d %-12s %s" % (i, name, got[:48]))
            else:
                bad.append((i, name, c[name], got))
                print("  [FAIL] case%d %-12s" % (i, name))
                print("         期望: %s" % c[name])
                print("         实际: %s" % got)
    print("")
    print("自检结果: %d 通过, %d 失败" % (ok, len(bad)))
    return 0 if not bad else 1


def cmd_status(cfg):
    rep = Reporter("status 只读查询")
    rep.kv("base_url", cfg["base_url"])
    rep.kv("username", cfg["username"])

    info, raw, url = api_user_info(cfg["timeout"])
    rep.add("")
    rep.add("rad_user_info 原始返回: `%s`" % raw.strip()[:400])
    if isinstance(info, dict):
        rep.add("")
        rep.add("| 字段 | 值 |")
        rep.add("| --- | --- |")
        for k in ("user_name", "online_ip", "online_ip6", "user_mac", "domain",
                  "online_device_total", "billing_name", "products_name", "error"):
            if k in info:
                rep.add("| %s | %s |" % (k, info.get(k)))
        online = info.get("error") == "ok"
        rep.add("")
        rep.add("**本机在线判定: %s**" % ("在线" if online else "离线"))

    dev, draw, durl = api_online_devices(cfg["username"], cfg["password"], cfg["timeout"])
    rep.json_block("在线设备列表", dev)
    return 0


VARIANT_LABELS = {
    ("hmac", ""): "A) HMAC-MD5(token,password) + 无域名后缀",
    ("hmac", DOMAIN_SUFFIX): "B) HMAC-MD5(token,password) + 带域名后缀",
    ("concat", ""): "C) MD5(password+token) + 无域名后缀",
    ("concat", DOMAIN_SUFFIX): "D) MD5(password+token) + 带域名后缀",
}


def cmd_stagea(cfg):
    rep = Reporter("stageA 在线探针（不断网）")
    rep.add("目的：在本机保持在线的前提下，用登录接口的返回码反推算法是否正确。")
    rep.add("原理：服务端先校验签名/加密，再校验凭据，最后判断在线状态；")
    rep.add("      因此算法错误会返回签名类错误，算法正确才会走到\"已在线\"。")
    rep.kv("username", cfg["username"])
    rep.kv("ac_id", cfg["acid"])

    info, raw, _ = api_user_info(cfg["timeout"])
    if not isinstance(info, dict) or info.get("error") != "ok":
        rep.add("")
        rep.add("**本机当前不在线，stageA 无法工作**（需要在线状态做探针）。")
        return 3
    myip = info.get("online_ip")
    rep.kv("本机在线 IP", myip)

    results = []
    winner = None
    order = [("hmac", ""), ("hmac", DOMAIN_SUFFIX), ("concat", ""), ("concat", DOMAIN_SUFFIX)]
    for idx, (algo, suffix) in enumerate(order):
        label = VARIANT_LABELS[(algo, suffix)]
        username = cfg["username"] + suffix
        rep.add("")
        rep.add("### 尝试 %s" % label)
        try:
            res, craw, url, meta = api_login(username, cfg["password"], myip, cfg["acid"],
                                             cfg["timeout"], algo=algo)
        except Exception as e:
            rep.add("请求异常: `%s`" % e)
            results.append({"algo": algo, "suffix": suffix, "verdict": "exception",
                            "error": str(e)})
            continue
        verdict = classify_login(res)
        rep.kv("username", username)
        rep.kv("token", meta.get("token", "")[:24] + "...")
        rep.kv("返回", craw.strip()[:300])
        rep.kv("判定", verdict)
        results.append({"algo": algo, "suffix": suffix, "verdict": verdict,
                        "raw": craw.strip(), "res": res, "username": username})
        if verdict in ("success", "already_online"):
            winner = (algo, suffix)
            rep.add("")
            rep.add("**算法已被服务端接受：%s**" % label)
            break
        if idx < len(order) - 1:
            rep.add("等待 12 秒（规避 E2532 认证间隔限制）...")
            time.sleep(12)

    os.makedirs(TESTS, exist_ok=True)
    with open(STAGEA_JSON, "w", encoding="utf-8") as f:
        json.dump({"winner": winner and {"algo": winner[0], "suffix": winner[1]},
                   "my_ip": myip, "results": results}, f, ensure_ascii=False, indent=2)
    rep.add("")
    rep.add("**stageA 结论: %s**" % ("算法确认 = " + VARIANT_LABELS[winner] if winner
                                    else "未确认，需要进一步分析返回码"))
    return 0 if winner else 1


def cmd_stageb(cfg, confirmed):
    if not confirmed:
        print("stageB 会真实注销本机（短暂断网）。确认请加 --yes")
        return 2

    algo, suffix = "hmac", ""
    if os.path.exists(STAGEA_JSON):
        with open(STAGEA_JSON, "r", encoding="utf-8") as f:
            d = json.load(f)
        if d.get("winner"):
            algo = d["winner"]["algo"]
            suffix = d["winner"]["suffix"]
    else:
        print("!! 未找到 stageA 结论，将使用默认算法 hmac / 无后缀")

    rep = Reporter("stageB 断网闭环验证")
    rep.add("算法: `%s`，域名后缀: `%s`" % (algo, suffix or "(无)"))
    rep.add("流程: DM 注销本机 -> 确认离线 -> 离线查列表 -> 重新登录 -> 确认恢复")

    info, raw, _ = api_user_info(cfg["timeout"])
    if not isinstance(info, dict) or info.get("error") != "ok":
        rep.add("**前置检查失败：本机当前不在线，终止。**")
        return 3
    myip = info.get("online_ip")
    rep.kv("本机 IP", myip)
    rep.kv("本机 MAC", info.get("user_mac"))

    dev, draw, durl = api_online_devices(cfg["username"], cfg["password"], cfg["timeout"])
    rep.json_block("① 注销前的在线设备列表", dev)
    before = [x.get("ip") for x in (dev or {}).get("data", []) or []]
    rep.kv("注销前在线 IP", ", ".join(before))

    rep.add("")
    rep.add("### ② DM 注销本机（验证 rad_user_dm 签名算法）")
    dm_ok = False
    for mode in ("int", "float"):
        try:
            res, craw, url, meta = api_dm_logout(cfg["username"], myip, cfg["timeout"],
                                                 time_mode=mode)
            rep.kv("time_mode=%s" % mode, meta["time"])
            rep.kv("HTTP", http_trace())
            rep.kv("sign", meta["sign"])
            rep.kv("返回", craw.strip()[:300])
            verdict = classify_login(res) if isinstance(res, dict) else "unparsed"
            rep.kv("判定", verdict)
            if verdict != "signature_error":
                dm_ok = True
                rep.add("**DM 注销请求已被服务端接受（time_mode=%s）**" % mode)
                break
        except Exception as e:
            rep.add("异常: `%s`（%s）" % (e, http_trace()))
        if mode == "int":
            rep.add("等待 3 秒后尝试另一种 time 格式...")
            time.sleep(3)

    rep.add("")
    rep.add("### ③ 轮询确认是否离线（最多 15 秒）")
    offline = False
    for i in range(15):
        try:
            i2, r2, _ = api_user_info(cfg["timeout"])
            state = (isinstance(i2, dict) and i2.get("error") == "ok")
            rep.add("- t+%ds: %s | error=%s" % (
                i, http_trace(),
                (i2 or {}).get("error") if isinstance(i2, dict) else r2.strip()[:60]))
            if not state:
                offline = True
                break
        except Exception as e:
            rep.add("- t+%ds: 请求异常 `%s`（%s）" % (i, e, http_trace()))
            offline = True
            break
        time.sleep(1)
    rep.add("**离线确认: %s**" % offline)

    rep.add("")
    rep.add("### ④ 离线状态下查询接口（验证 0.6 / 0.7）")
    try:
        dev2, draw2, _ = api_online_devices(cfg["username"], cfg["password"], cfg["timeout"])
        rep.json_block("离线时的 rad_user_info", api_user_info(cfg["timeout"])[0])
        rep.json_block("离线时的在线设备列表（关键：能否查到）", dev2)
    except Exception as e:
        rep.add("离线时查询异常: `%s`" % e)

    rep.add("")
    rep.add("### ⑤ 重新登录（验证 login 全流程）")
    username = cfg["username"] + suffix
    logged_in = False
    for attempt in range(1, 4):
        try:
            res, craw, url, meta = api_login(username, cfg["password"], myip, cfg["acid"],
                                             cfg["timeout"], algo=algo)
        except Exception as e:
            rep.add("第 %d 次登录异常: `%s`" % (attempt, e))
            time.sleep(3)
            continue
        verdict = classify_login(res)
        rep.kv("HTTP", http_trace())
        rep.kv("第 %d 次尝试返回" % attempt, craw.strip()[:300])
        rep.kv("判定", verdict)
        if verdict in ("success", "already_online"):
            logged_in = True
            break
        if "E6504" in craw or "请等1分钟" in craw:
            rep.add("命中注销冷却（E6504），等待 60 秒后重试...")
            time.sleep(60)
        else:
            time.sleep(5)

    rep.add("")
    rep.add("### ⑥ 最终状态确认")
    try:
        final, fran, _ = api_user_info(cfg["timeout"])
        rep.json_block("最终 rad_user_info", final)
        rep.add("**最终在线判定: %s**" % ("在线 ✔" if isinstance(final, dict)
                                          and final.get("error") == "ok" else "离线 ✘"))
    except Exception as e:
        rep.add("最终确认异常: `%s`" % e)

    return 0 if logged_in else 1


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1].lower()
    if cmd == "selftest":
        return cmd_selftest()
    cfg = load_config()
    if cmd in ("status", "devices"):
        if not require_credentials(cfg):
            return 2
        return cmd_status(cfg)
    if cmd == "stagea":
        if not require_credentials(cfg):
            return 2
        return cmd_stagea(cfg)
    if cmd == "stageb":
        if not require_credentials(cfg):
            return 2
        return cmd_stageb(cfg, "--yes" in sys.argv)
    print("未知命令: %s" % cmd)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
