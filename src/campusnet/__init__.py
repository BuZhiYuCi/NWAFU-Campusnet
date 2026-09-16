#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校园网一键登录 / 一键下线（西北农林科技大学 深澜 SRun 门户）。

核心库：零第三方依赖，只用 Python 标准库。

>>> from campusnet import SrunPortalClient
>>> client = SrunPortalClient()
>>> client.portal_reachable()          # 是不是在校园网里
True
>>> status = client.user_info()
>>> status.online
True
>>> client.online_devices("账号", "密码")   # 在线设备列表
[Device(...)]
"""

from .crypto import (build_chksum, build_info, custom_b64_encode,
                     dm_signature, hmac_md5, password_md5, xxtea_encode)
from .config import (CONFIG_VERSION, DEFAULT_CONFIG, Config, app_dir,
                     default_config_path, default_log_dir, load_or_create)
from .dpapi import DpapiCipher, DpapiError, PlaintextCipher
from .log import redact, register_secret, setup_logging
from .models import (ALREADY_ONLINE, FULL, NETWORK_ERROR, NOT_ONLINE,
                     SIGNATURE_ERROR, SUCCESS, UNKNOWN, UNPARSED, Challenge,
                     Device, OnlineStatus, Result)
from .portal import (BASE_URL, HttpResponse, PortalError, PortalUnreachable,
                     SrunPortalClient, classify, parse_jsonp)

__version__ = "0.1.0"

__all__ = [
    "BASE_URL", "SrunPortalClient", "PortalError", "PortalUnreachable",
    "HttpResponse", "classify", "parse_jsonp",
    "Device", "OnlineStatus", "Challenge", "Result",
    "SUCCESS", "ALREADY_ONLINE", "FULL", "NOT_ONLINE", "SIGNATURE_ERROR",
    "UNPARSED", "UNKNOWN", "NETWORK_ERROR",
    "custom_b64_encode", "xxtea_encode", "hmac_md5", "password_md5",
    "build_info", "build_chksum", "dm_signature",
    "Config", "load_or_create", "DEFAULT_CONFIG", "CONFIG_VERSION",
    "app_dir", "default_config_path", "default_log_dir",
    "DpapiCipher", "DpapiError", "PlaintextCipher",
    "setup_logging", "redact", "register_secret",
]
