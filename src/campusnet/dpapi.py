#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Windows DPAPI 封装：用当前用户凭据加密密码，配置文件里只留密文。

DPAPI（CryptProtectData / CryptUnprotectData）由操作系统保管密钥：

- 默认是**用户级**作用域，只有同一个 Windows 用户能解密；
  换用户、换机器、重装系统都解不开（重装即丢失，需要重新输入密码）。
- 不需要程序自己管理密钥，也就没有"密钥写哪儿"的问题。

非 Windows 平台会直接抛错，避免出现"以为加密了其实没有"的情况。
"""

import base64
import ctypes
import sys

_CRYPTPROTECT_UI_FORBIDDEN = 0x01
_DESCRIPTION = "CampusNet"


class DpapiError(Exception):
    """DPAPI 调用失败。"""


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


class DpapiCipher(object):
    """用户级 DPAPI 加解密，输出 Base64 文本便于放进 JSON。"""

    name = "dpapi"

    def __init__(self):
        if sys.platform != "win32":
            raise DpapiError("DPAPI 仅在 Windows 上可用")
        self._crypt32 = ctypes.windll.crypt32
        self._kernel32 = ctypes.windll.kernel32
        self._crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(_DataBlob), ctypes.c_wchar_p, ctypes.POINTER(_DataBlob),
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
            ctypes.POINTER(_DataBlob)]
        self._crypt32.CryptProtectData.restype = ctypes.c_int
        self._crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(_DataBlob), ctypes.POINTER(ctypes.c_wchar_p),
            ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_uint32, ctypes.POINTER(_DataBlob)]
        self._crypt32.CryptUnprotectData.restype = ctypes.c_int
        self._kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        self._kernel32.LocalFree.restype = ctypes.c_void_p

    # -- 内部 ----------------------------------------------------------
    @staticmethod
    def _to_blob(raw):
        buf = ctypes.create_string_buffer(raw, len(raw))
        return _DataBlob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    def _free(self, blob):
        if blob.pbData:
            # 必须显式转成 void*，否则 64 位指针会被按 int 截断
            self._kernel32.LocalFree(ctypes.cast(blob.pbData, ctypes.c_void_p))

    # -- 对外 ----------------------------------------------------------
    def encrypt(self, plaintext):
        if plaintext is None:
            raise DpapiError("没有可加密的内容")
        raw = plaintext.encode("utf-8")
        blob_in, keep = self._to_blob(raw)
        blob_out = _DataBlob()
        ok = self._crypt32.CryptProtectData(
            ctypes.byref(blob_in), _DESCRIPTION, None, None, None,
            _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
        if not ok:
            raise DpapiError("CryptProtectData 失败（错误码 %d）"
                             % ctypes.get_last_error())
        try:
            data = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            self._free(blob_out)
        del keep  # 保持输入缓冲区存活到调用结束
        return base64.b64encode(data).decode("ascii")

    def decrypt(self, token):
        if not token:
            raise DpapiError("没有可解密的内容")
        try:
            raw = base64.b64decode(token)
        except Exception as exc:
            raise DpapiError("密文不是合法 Base64：%s" % exc)
        blob_in, keep = self._to_blob(raw)
        blob_out = _DataBlob()
        ok = self._crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None,
            _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
        if not ok:
            raise DpapiError(
                "CryptUnprotectData 失败：密文不是当前 Windows 用户加密的，"
                "或配置文件被拷贝到了别的机器")
        try:
            data = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            self._free(blob_out)
        del keep
        return data.decode("utf-8")


class PlaintextCipher(object):
    """只在测试里用的"假加密"，会原样存储。生产代码不要用。"""

    name = "plaintext"

    def encrypt(self, plaintext):
        return "plain:" + (plaintext or "")

    def decrypt(self, token):
        return (token or "")[len("plain:"):]


def default_cipher():
    """按平台返回默认加密器。"""
    if sys.platform == "win32":
        return DpapiCipher()
    raise DpapiError(
        "当前平台（%s）不支持 DPAPI。密码加密依赖 Windows；"
        "如需在其它平台跑测试，请显式传入 PlaintextCipher。" % sys.platform)
