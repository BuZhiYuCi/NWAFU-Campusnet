#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门户错误码 → 中文提示。

文案表来自门户自身的 lang.js（translate["zh-CN"]），由
tools/extract_error_codes.py 提取生成 data/error_codes.json，
所以提示语与学校网页上看到的完全一致。
"""

import json
import os
import re

_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "data", "error_codes.json")

try:
    with open(_DATA_PATH, "r", encoding="utf-8") as _f:
        TABLE = json.load(_f)
except (OSError, ValueError):  # pragma: no cover - 数据文件缺失时降级
    TABLE = {}

#: 服务端返回的下划线命名错误 → 文案表里的驼峰键
NAMED_ALIASES = {
    "sign_error": "SignError",
    "not_online_error": "NotOnlineError",
    "ip_already_online_error": "IpAlreadyOnlineError",
    "no_response_data_error": "NoResponseDataError",
    "user_must_modify_password": "UserMustModifyPassword",
    "challenge_expire_error": "ChallengeExpireError",
    "speed_limit_error": "SpeedLimitError",
    "srun_portal_server_error": "SrunPortalServerError",
    "auth_resault_timeout_err": "AuthResaultTimeoutErr",
    "auth_info_error": "AuthInfoError",
    "token_error": "TokenError",
    "memory_db_error": "MemoryDbError",
    "vcode_error": "VcodeError",
}

#: 响应里可能承载结果的字段，按优先级排列
_CANDIDATE_KEYS = ("ecode", "error", "res", "suc_msg", "ploy_msg", "error_msg")

_CODE_RE = re.compile(r"(E\d{4})")


def extract_code(text):
    """从 'E2620: xxx' 或 'E2620' 里取出错误码。"""
    if not text:
        return None
    m = _CODE_RE.search(str(text))
    return m.group(1) if m else None


def translate(key, default=None):
    """按错误码或文案表的键取中文。"""
    if not key:
        return default
    key = str(key).strip()
    if key in TABLE:
        return TABLE[key]
    code = extract_code(key)
    if code and code in TABLE:
        return TABLE[code]
    camel = NAMED_ALIASES.get(key.lower())
    if camel and camel in TABLE:
        return TABLE[camel]
    return default


def message_for(raw):
    """从接口响应里挑出最合适的一句中文提示；挑不出来返回 None。"""
    if not isinstance(raw, dict):
        return None
    for key in _CANDIDATE_KEYS:
        value = raw.get(key)
        if value in (None, "", 0, "0"):
            continue
        text = str(value).strip()
        hit = translate(text)
        if hit:
            code = extract_code(text)
            if code and len(text) > len(code):
                return "%s（%s）" % (hit, code)
            return hit
    return None


def all_codes():
    """返回全部 E 码，便于测试与排查。"""
    return {k: v for k, v in TABLE.items()
            if k.startswith("E") and k[1:].isdigit()}
