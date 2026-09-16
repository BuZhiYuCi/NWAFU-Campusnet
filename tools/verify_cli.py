#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 3 验收：用真实的命令行入口跑一遍完整流程。

    python tools/verify_cli.py            # 只读检查（status / devices / settings）
    python tools/verify_cli.py --full     # 加上 logout -> login 闭环（会短暂断网）

脚本通过 subprocess 调用 `python -m campusnet <命令>`，验证的是真正的命令行入口，
而不是直接调库。配置文件写在临时目录（CAMPUSNET_CONFIG），不影响正式配置。

因为断网期间 AI 会话会中断，结果会写入 docs/phase3-verify.md。
"""

import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
REPORT = os.path.join(ROOT, "docs", "phase3-verify.md")
sys.path.insert(0, SRC)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from campusnet import SrunPortalClient  # noqa: E402


class Report(object):
    def __init__(self, title):
        self.failed = 0
        self._add("")
        self._add("---")
        self._add("")
        self._add("## [%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), title))
        self._add("")

    def _add(self, line=""):
        print(line)
        with open(REPORT, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def step(self, text):
        self._add("")
        self._add("### %s" % text)

    def block(self, text, limit=1200):
        self._add("```")
        for line in (text or "").rstrip().splitlines()[:40]:
            self._add(line[:160])
        self._add("```")

    def check(self, name, ok, extra=""):
        if not ok:
            self.failed += 1
        self._add("- [%s] %s%s" % ("PASS" if ok else "**FAIL**", name,
                                   (" — " + extra) if extra else ""))
        return ok


def load_credentials():
    user = os.environ.get("CAMPUSNET_USER", "")
    pwd = os.environ.get("CAMPUSNET_PASS", "")
    if not user or not pwd:
        path = os.path.join(os.environ.get("TEMP", "."), "campusnet_probe.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            user = d.get("username", "")
            pwd = d.get("password", "")
    return user, pwd


def run_cli(args, config_path, log_dir, stdin_text=None):
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC
    env["CAMPUSNET_CONFIG"] = config_path
    env["CAMPUSNET_LOG_DIR"] = log_dir
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run([sys.executable, "-m", "campusnet"] + args,
                          env=env, input=stdin_text, capture_output=True,
                          text=True, encoding="utf-8")
    return proc.returncode, (proc.stdout or ""), (proc.stderr or "")


def main():
    full = "--full" in sys.argv
    user, pwd = load_credentials()
    rep = Report("Phase 3 验收：命令行工具（%s）" % ("完整闭环" if full else "只读检查"))
    if not user or not pwd:
        rep._add("缺少凭据")
        return 2

    tmp = tempfile.mkdtemp(prefix="campusnet-cli-verify-")
    config_path = os.path.join(tmp, "config.json")
    log_dir = os.path.join(tmp, "logs")
    rep._add("- 临时配置: `%s`" % config_path)
    rep._add("- 玩法: 通过 subprocess 调用 `python -m campusnet <命令>`")

    # ---- 0. 记一下当前是否处于限流状态 ----
    rep.step("⓪ 服务端状态自检")
    st = SrunPortalClient(timeout=8).user_info()
    rep._add("- rad_user_info: `%s`（%s）" % (st.error or "ok",
                                              "限流中" if st.rate_limited else "正常"))
    rep._add("- 说明：rad_user_info 会被限流，产品在限流期间会改用"
             "**在线设备列表**判定状态（设备列表接口不受该限流影响）")

    # ---- 1. 首次使用：应提示未设置账号 ----
    rep.step("① 首次使用：settings --show")
    code, out, err = run_cli(["settings", "--show"], config_path, log_dir)
    rep.block(out or err)
    rep.check("settings --show 退出码为 0", code == 0, "code=%d" % code)
    rep.check("提示尚未设置账号", "未设置" in out)

    # ---- 2. 没凭据时 status 仍可用 ----
    rep.step("② 未设置账号时 status")
    code, out, err = run_cli(["status"], config_path, log_dir)
    rep.block(out or err)
    rep.check("提示去设置账号", "settings" in out)
    if code == 0:
        rep.check("未设账号时也能确认在线", True, "code=0")
    elif "无法确定" in out or "限流" in out:
        # 没有账号就拿不到设备列表，被限流时只能如实报告——这是正确行为
        rep.check("未设账号 + 限流时如实报告无法确定", True, "code=%d" % code)
    else:
        rep.check("未设账号时也能确认在线", False, "code=%d" % code)

    # ---- 3. 设置账号 ----
    rep.step("③ 设置账号（密码经 stdin 传入）")
    code, out, err = run_cli(["settings", "--username", user, "--password-stdin"],
                             config_path, log_dir, stdin_text=pwd + "\n")
    rep.block(out or err)
    rep.check("保存成功", code == 0 and "已保存" in out, "code=%d" % code)
    with open(config_path, "r", encoding="utf-8") as f:
        raw = f.read()
    rep.check("配置文件里没有明文密码", pwd not in raw)
    rep.check("配置文件里有 DPAPI 密文", '"password_dpapi": "AQ' in raw)

    # ---- 4. 各查询命令 ----
    rep.step("④ status / devices / settings --json")
    code, out, err = run_cli(["status"], config_path, log_dir)
    rep.block(out or err)
    rep.check("status 显示在线设备表", code == 0 and "在线设备列表" in out, "code=%d" % code)

    code, out, err = run_cli(["devices", "--json"], config_path, log_dir)
    try:
        devices = json.loads(out)
        rep.check("devices --json 可解析", True, "%d 台" % len(devices))
    except ValueError:
        devices = []
        rep.check("devices --json 可解析", False, out[:200])
    rep.block(json.dumps(devices, ensure_ascii=False, indent=2))

    code, out, err = run_cli(["settings", "--json"], config_path, log_dir)
    rep.check("settings --json 不含密码", pwd not in out, "code=%d" % code)

    if not full:
        rep.step("结论")
        rep._add("只读检查完成，未做状态变更。")
        return 0 if not rep.failed else 1

    # ---- 5. 一键下线 ----
    rep.step("⑤ 一键下线：logout（走 action=logout，Phase 1 没测过这条路径）")
    t0 = time.time()
    code, out, err = run_cli(["logout"], config_path, log_dir)
    rep.block(out or err)
    rep.check("logout 退出码 0", code == 0, "code=%d，耗时 %.1fs" % (code, time.time() - t0))
    rep.check("提示已下线", "已下线" in out)

    code, out, err = run_cli(["status"], config_path, log_dir)
    rep.block(out or err)
    rep.check("下线后 status 退出码 1（离线）", code == 1, "code=%d" % code)
    rep.check("状态显示未登录", "未登录" in out)

    # ---- 6. 一键登录 ----
    rep.step("⑥ 一键登录：login")
    t0 = time.time()
    code, out, err = run_cli(["login"], config_path, log_dir)
    rep.block(out or err)
    rep.check("login 退出码 0", code == 0, "code=%d，耗时 %.1fs" % (code, time.time() - t0))
    rep.check("提示登录成功", "登录成功" in out)

    code, out, err = run_cli(["status"], config_path, log_dir)
    rep.block(out or err)
    rep.check("登录后 status 退出码 0", code == 0, "code=%d" % code)

    # ---- 7. 幂等性 ----
    rep.step("⑦ 幂等性：已在线时再点登录")
    code, out, err = run_cli(["login"], config_path, log_dir)
    rep.check("重复登录不报错", code == 0 and "已经在线" in out, "code=%d" % code)

    rep.step("结论")
    if rep.failed:
        rep._add("**Phase 3 验收未通过：%d 项失败。**" % rep.failed)
        return 1
    rep._add("**Phase 3 验收通过 ✔**（命令行入口 + 一键下线 + 一键登录 + 幂等）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
