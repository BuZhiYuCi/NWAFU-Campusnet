#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""滚动日志 + 敏感信息脱敏。

规则：日志里**永远不应该出现明文密码**。两层防护：

1. 正则兜底：把 `password=xxx`、`"password":"xxx"`、`{MD5}<hash>` 一律替换成 `***`；
2. 显式登记：程序启动时把当前密码登记进来（register_secret），
   日志里任何位置出现它都会被替换掉——包括异常信息和第三方库打印的内容。
"""

import logging
import logging.handlers
import os
import re

from .config import default_log_dir

MASK = "***"
_MIN_SECRET_LEN = 4

_SECRETS = set()

_PATTERNS = [
    # URL 查询串里的 password=xxx
    re.compile(r"(password=)([^&\s\"']+)", re.I),
    # JSON 里的 "password": "xxx"
    re.compile(r"(\"password\"\s*:\s*\")([^\"]*)(\")", re.I),
    re.compile(r"(\"password_dpapi\"\s*:\s*\")([^\"]*)(\")", re.I),
    # 门户的 {MD5}<32位hash> 形式
    re.compile(r"(\{MD5\})[0-9a-fA-F]{32}"),
]


def register_secret(value):
    """登记一个需要脱敏的敏感值（密码等）。太短的值不登记，避免误伤正常文本。"""
    if value and len(str(value)) >= _MIN_SECRET_LEN:
        _SECRETS.add(str(value))
    return value


def registered_secrets():
    return set(_SECRETS)


def clear_secrets():
    _SECRETS.clear()


def redact(text):
    """把文本里的敏感内容替换成 ***。"""
    if text is None:
        return None
    out = str(text)
    for secret in _SECRETS:
        if secret and secret in out:
            out = out.replace(secret, MASK)
    for pattern in _PATTERNS:
        if pattern.groups == 3:
            out = pattern.sub(lambda m: m.group(1) + MASK + m.group(3), out)
        else:
            out = pattern.sub(lambda m: m.group(1) + MASK, out)
    return out


class RedactingFormatter(logging.Formatter):
    """在格式化之后再脱敏，保证异常栈里的内容也覆盖到。"""

    def format(self, record):
        return redact(super(RedactingFormatter, self).format(record))


def setup_logging(name="campusnet", log_dir=None, level=logging.INFO,
                  console=False, max_bytes=1_000_000, backup_count=5):
    """配置并返回 logger。

    写入 <log_dir>/campusnet.log，单文件超过 max_bytes 自动轮转，保留 backup_count 份。
    """
    log_dir = log_dir or default_log_dir()
    os.makedirs(log_dir, exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

    fmt = RedactingFormatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S")

    file_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "campusnet.log"), maxBytes=max_bytes,
        backupCount=backup_count, encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    if console:
        stream = logging.StreamHandler()
        stream.setFormatter(fmt)
        logger.addHandler(stream)

    return logger


def log_path(log_dir=None):
    return os.path.join(log_dir or default_log_dir(), "campusnet.log")
