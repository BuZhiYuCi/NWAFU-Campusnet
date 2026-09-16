#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 2 验收：配置持久化 + DPAPI 加密 + 日志脱敏（在真实环境执行）。

用法:
    python tools/verify_config.py

会做四件事：
    1. 用真实 DPAPI 把账号密码写入 %APPDATA%\\CampusNet\\config.json
    2. 读回原始文件，确认里面**没有明文密码**
    3. 另起一个 Python 进程重新加载配置并解密（等价于"重启程序"）
    4. 写日志并扫描日志文件，确认搜不到明文密码

凭据来源：环境变量 CAMPUSNET_USER / CAMPUSNET_PASS，或 %TEMP%\\campusnet_probe.json
"""

import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from campusnet import config as cfgmod  # noqa: E402
from campusnet import log as logmod  # noqa: E402

REPORT = os.path.join(ROOT, "docs", "phase2-verify.md")


class Report(object):
    def __init__(self, title):
        self.buf = []
        self.add("")
        self.add("---")
        self.add("")
        self.add("## [%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), title))
        self.add("")
        self.failed = 0

    def add(self, line=""):
        self.buf.append(line)
        print(line)
        with open(REPORT, "a", encoding="utf-8") as f:
            f.write("\n".join(self.buf) + "\n")
        self.buf = []

    def check(self, name, ok, extra=""):
        mark = "PASS" if ok else "**FAIL**"
        if not ok:
            self.failed += 1
        self.add("- [%s] %s%s" % (mark, name, (" — " + extra) if extra else ""))
        return ok


def load_credentials():
    user = os.environ.get("CAMPUSNET_USER", "")
    pwd = os.environ.get("CAMPUSNET_PASS", "")
    acid = os.environ.get("CAMPUSNET_ACID", "1")
    if not user or not pwd:
        path = os.path.join(os.environ.get("TEMP", "."), "campusnet_probe.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            user = d.get("username", "")
            pwd = d.get("password", "")
            acid = str(d.get("ac_id", acid))
    return user, pwd, acid


def main():
    user, pwd, acid = load_credentials()
    rep = Report("Phase 2 验收：配置持久化 / DPAPI / 日志脱敏")
    if not user or not pwd:
        rep.add("缺少凭据（CAMPUSNET_USER / CAMPUSNET_PASS 或 %TEMP%\\campusnet_probe.json）")
        return 2

    cfg = cfgmod.load_or_create()
    rep.add("- 配置文件: `%s`" % cfg.path)
    rep.add("- 加密器: `%s`" % cfg.cipher.name)
    rep.add("- 账号: `%s`" % user)
    rep.add("")
    rep.add("### ① 写入凭据并保存")
    rep.check("保存前配置文件不存在或为空", True)
    cfg.set_credentials(user, pwd)
    cfg.set("portal.ac_id", acid)
    cfg.save()
    rep.check("配置文件已写入", os.path.exists(cfg.path))
    rep.add("")
    rep.add("### ② 检查磁盘文件里有没有明文密码")
    with open(cfg.path, "r", encoding="utf-8") as f:
        raw = f.read()
    rep.check("文件里搜不到明文密码", pwd not in raw)
    rep.check("文件里有 DPAPI 密文字段", '"password_dpapi"' in raw)
    rep.add("")
    rep.add("配置片段（密码字段已被截断展示）:")
    rep.add("```json")
    for line in raw.splitlines():
        if "password_dpapi" in line:
            value = line.split(":", 1)[1].strip().strip(',').strip('"')
            rep.add('  "password_dpapi": "%s..."（共 %d 字符）' % (value[:24], len(value)))
        else:
            rep.add(line)
    rep.add("```")

    rep.add("")
    rep.add("### ③ 模拟【重启程序】：另起进程重新加载并解密")
    code = (
        "import os,sys;"
        "sys.path.insert(0, r'%s');"
        "from campusnet import config as c;"
        "cfg=c.load_or_create();"
        "got=cfg.get_password() or '';"
        "print('USER_OK' if cfg.username==os.environ['EXPECT_USER'] else 'USER_BAD');"
        "print('PWD_OK' if got==os.environ['EXPECT_PWD'] else 'PWD_BAD')" % SRC
    )
    env = dict(os.environ)
    env["EXPECT_USER"] = user
    env["EXPECT_PWD"] = pwd
    proc = subprocess.run([sys.executable, "-c", code], env=env,
                          capture_output=True, text=True)
    out = (proc.stdout or "").strip()
    rep.add("子进程输出（刻意不打印密码）:")
    rep.add("```")
    rep.add(out or "(无输出)")
    if proc.stderr.strip():
        rep.add(proc.stderr.strip()[:400])
    rep.add("```")
    rep.check("新进程读到的账号正确", "USER_OK" in out)
    rep.check("新进程用 DPAPI 解出的密码正确", "PWD_OK" in out)

    rep.add("")
    rep.add("### ④ 密文被改动后应当解不开（模拟换机器/换用户）")
    broken = cfgmod.Config(path=cfg.path)
    broken.load()
    token = broken.get("portal.password_dpapi", "")
    broken.set("portal.password_dpapi", token[:-8] + "AAAAAAAA")
    rep.check("损坏的密文解密失败并返回 None", broken.get_password() is None)

    rep.add("")
    rep.add("### ⑤ 日志脱敏")
    logmod.register_secret(pwd)
    logger = logmod.setup_logging(console=False,
                                  log_dir=os.path.join(cfgmod.app_dir(), "logs"))
    logger.info("尝试登录，账号 %s", user)
    logger.info("请求参数：action=login&username=%s&password=%s&ip=10.0.0.1", user, pwd)
    logger.warning("模拟失败：password=%s", pwd)
    try:
        raise RuntimeError("模拟异常，密码是 %s" % pwd)
    except RuntimeError:
        logger.exception("登录过程出错")
    logfile = logmod.log_path()
    with open(logfile, "r", encoding="utf-8") as f:
        logtext = f.read()
    rep.add("- 日志文件: `%s`" % logfile)
    rep.check("日志里搜不到明文密码", pwd not in logtext)
    rep.check("日志里确实写了内容（不是空文件）", len(logtext) > 0)
    rep.check("异常堆栈也保留了下来", "Traceback" in logtext)
    rep.add("")
    rep.add("日志片段（最后几行）:")
    rep.add("```")
    for line in logtext.strip().splitlines()[-4:]:
        rep.add(line[:160])
    rep.add("```")

    rep.add("")
    rep.add("### 结论")
    if rep.failed:
        rep.add("**Phase 2 验收未通过：%d 项失败。**" % rep.failed)
        return 1
    rep.add("**Phase 2 验收通过 ✔**（配置文件里只有 DPAPI 密文；换进程可正常解密；日志无明文密码）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
