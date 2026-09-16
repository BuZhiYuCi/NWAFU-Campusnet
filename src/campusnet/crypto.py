#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""深澜（SRun）门户加密实现。

全部按门户官方前端 JS 逐行移植，并用官方 JS 生成的测试向量验证过
（见 tests/vectors.json 与 tests/test_crypto.py，20/20 逐字节一致）。

三个容易踩的坑，这里都已经处理：

1. 自定义 Base64 字母表是**逐字节**映射，不做 UTF-8 转换
   （门户的 jquery-base64 插件用 charCodeAt 直接取字节，>255 会抛异常）。
2. XXTEA 的 `s()` 是**小端**打包（`c0 | c1<<8 | c2<<16 | c3<<24`），
   不是常见的网络序。
3. hmd5 是 **HMAC-MD5(key=token, message=password)**，
   不是网上大量脚本写的 md5(password + token)（那是老版 PHP 门户的算法）。
"""

import base64
import hashlib
import hmac
import json
import time

#: 门户自定义 Base64 字母表（jquery-base64 的 _ALPHA）
CUSTOM_ALPHA = "LVoJPiCN2R8G90yg+hmFHuacZ1OWMnrsSTXkYpUq/3dlbfKwv6xztjI7DeBE45QA"

#: 标准 Base64 字母表
STD_ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"

_B64_TRANS = str.maketrans(STD_ALPHA, CUSTOM_ALPHA)
_U32 = 0xFFFFFFFF

#: XXTEA 的 delta 常量（JS 里写成 0x86014019 | 0x183639A0）
DELTA = 0x9E3779B9


def custom_b64_encode(raw):
    """按门户自定义字母表编码 Base64。"""
    return base64.b64encode(raw).decode("ascii").translate(_B64_TRANS)


def custom_b64_decode(text):
    """按门户自定义字母表解码 Base64（调试/测试用）。"""
    return base64.b64decode(text.translate(str.maketrans(CUSTOM_ALPHA, STD_ALPHA)))


def _str2long(s, include_len):
    """对应 JS 的 s(a, b)：字符串 → 32 位字数组，小端打包。"""
    words = []
    size = len(s)
    for i in range(0, size, 4):
        chunk = [ord(ch) & 0xFF for ch in s[i:i + 4]]
        while len(chunk) < 4:
            chunk.append(0)
        words.append(chunk[0] | (chunk[1] << 8) | (chunk[2] << 16) | (chunk[3] << 24))
    if include_len:
        words.append(size)
    return words


def _long2str(words, include_len):
    """对应 JS 的 l(a, b)：32 位字数组 → 字节串，小端拆包。"""
    out = bytearray()
    for w in words:
        out += bytes((w & 0xFF, (w >> 8) & 0xFF, (w >> 16) & 0xFF, (w >> 24) & 0xFF))
    if include_len:
        total = ((len(words) - 1) << 2) & _U32
        declared = words[-1]
        if declared < total - 3 or declared > total:
            raise ValueError("XXTEA 长度字段非法")
        return bytes(out[:declared])
    return bytes(out)


def xxtea_encode(text, key):
    """对应 Portal.js 里的 encode(str, key)。"""
    v = _str2long(text, True)
    k = _str2long(key, False)
    while len(k) < 4:
        k.append(0)
    n = len(v) - 1
    z = v[n]
    y = v[0]
    q = 6 + 52 // (n + 1)
    d = 0
    while q > 0:
        q -= 1
        d = (d + DELTA) & _U32
        e = (d >> 2) & 3
        for p in range(n):
            y = v[p + 1]
            m = (z >> 5) ^ ((y << 2) & _U32)
            m = (m + (((y >> 3) ^ ((z << 4) & _U32) ^ (d ^ y)) & _U32)) & _U32
            m = (m + ((k[(p & 3) ^ e] ^ z) & _U32)) & _U32
            z = (v[p] + m) & _U32
            v[p] = z
        y = v[0]
        m = (z >> 5) ^ ((y << 2) & _U32)
        m = (m + (((y >> 3) ^ ((z << 4) & _U32) ^ (d ^ y)) & _U32)) & _U32
        m = (m + ((k[(n & 3) ^ e] ^ z) & _U32)) & _U32
        z = (v[n] + m) & _U32
        v[n] = z
    return _long2str(v, False)


def hmac_md5(password, token):
    """门户的 md5(password, token) —— 双参数即 HMAC。"""
    return hmac.new(token.encode("utf-8"), password.encode("utf-8"),
                    hashlib.md5).hexdigest()


def md5_hex(text):
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def sha1_hex(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def password_md5(password):
    """在线设备查询接口需要的明文密码 MD5。

    密码为空时直接报错，而不是抛 AttributeError——首次运行时密码还没设置，
    调用方应当先判断有没有凭据（踩过这个坑）。
    """
    if not password:
        raise ValueError("缺少密码，无法计算密码摘要")
    return md5_hex(password)


def build_info_json(username, password, ip, acid, enc_ver="srun_bx1"):
    """字段顺序必须与 JS 的 JSON.stringify 完全一致，否则密文不同。"""
    return json.dumps({
        "username": username,
        "password": password,
        "ip": ip,
        "acid": acid,
        "enc_ver": enc_ver,
    }, separators=(",", ":"), ensure_ascii=False)


def build_info(username, password, ip, acid, token, enc_ver="srun_bx1"):
    """生成登录参数里的 info 字段：{SRBX1} + 自定义Base64(XXTEA(json, token))。"""
    payload = build_info_json(username, password, ip, acid, enc_ver)
    return "{SRBX1}" + custom_b64_encode(xxtea_encode(payload, token))


def build_chksum(token, username, hmd5, acid, ip, n, type_, info):
    """生成登录参数里的 chksum 字段。"""
    joined = (token + username + token + hmd5 + token + str(acid) + token + ip +
              token + str(n) + token + str(type_) + token + info)
    return sha1_hex(joined)


def js_time_str(now=None):
    """对应 JS 的 Date.parse(new Date()) / 1000 —— 结果是**整数秒**。

    坑点：Date.parse() 期望字符串，传入 Date 时会先 ToString，
    而 String(new Date()) 只精确到秒，所以毫秒部分永远是 0。
    传小数会让门户返回 sign_error（实测）。
    """
    return str(int(now if now is not None else time.time()))


def dm_signature(username, ip, unbind=1, now=None):
    """生成 rad_user_dm 的 (time, sign)。

    sign = sha1(time + username + ip + unbind + time)，注意 time 出现两次。
    username 用**裸账号**（不带 @域名）。
    """
    t = js_time_str(now)
    sign = sha1_hex(t + username + ip + str(unbind) + t)
    return t, sign
