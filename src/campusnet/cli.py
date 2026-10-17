#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校园网一键登录 / 一键下线 —— 命令行工具。

用法示例：

    python -m campusnet status             查看本机在线状态与在线设备
    python -m campusnet login              一键登录
    python -m campusnet logout             一键下线（真正注销，不是断网）
    python -m campusnet devices            只列在线设备
    python -m campusnet kick 10.1.2.3      踢指定设备下线（可给多个 IP）
    python -m campusnet settings           查看/修改账号密码

账号密码第一次使用时会引导设置，之后自动读取（DPAPI 加密存储）。

退出码：
    0  成功（status 表示"已在线"）
    1  业务失败（不在校园网 / 登录失败 / 操作未生效）
    2  参数错误、缺少配置或用户取消
"""

import argparse
import getpass
import json
import os
import sys
import time
import unicodedata

from . import config as cfgmod
from . import autostart
from . import errors
from . import log as logmod
from . import netprobe
from . import policy
from .service import CampusNetService
from .models import (ALREADY_ONLINE, FULL, NETWORK_ERROR, NOT_ONLINE,
                     SIGNATURE_ERROR, STATE_OFFLINE, STATE_ONLINE,
                     STATE_UNKNOWN, SUCCESS)
from .portal import PortalError, PortalUnreachable, SrunPortalClient

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2


# ===========================================================================
# 输出辅助
# ===========================================================================

def _w(text):
    """终端显示宽度：中文等全角字符按 2 计。"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1
               for ch in str(text))


def _pad(text, width):
    text = str(text)
    return text + " " * max(0, width - _w(text))


def render_devices(devices, my_ip=None):
    """把设备列表渲染成对齐的表格。"""
    if not devices:
        return "（没有在线设备）"
    header = ("#", "设备类型", "操作系统", "上线时间", "已在线", "IP")
    ordered = sorted(devices, key=lambda d: d.add_time)
    rows = []
    for idx, dev in enumerate(ordered, 1):
        mark = "  ← 本机" if my_ip and dev.ip == my_ip else ""
        rows.append((str(idx), dev.client_type_label, dev.os_name,
                     dev.add_time, dev.online_text(), dev.ip + mark))
    widths = [max(_w(r[c]) for r in (rows + [header])) for c in range(len(header))]
    lines = ["  ".join(_pad(h, widths[i]) for i, h in enumerate(header)).rstrip(),
             "  ".join("-" * widths[i] for i in range(len(header)))]
    for row in rows:
        lines.append("  ".join(_pad(row[i], widths[i]) for i in range(len(row))).rstrip())
    return "\n".join(lines)


def device_dicts(devices, my_ip=None):
    return [{"ip": d.ip, "client_type": d.client_type,
             "client_type_label": d.client_type_label, "os_name": d.os_name,
             "add_time": d.add_time, "online_seconds": d.online_seconds(),
             "online_text": d.online_text(), "is_local": bool(my_ip and d.ip == my_ip)}
            for d in sorted(devices, key=lambda d: d.add_time)]


def out(text=""):
    print(text)


def err(text):
    print(text, file=sys.stderr)


def setup_hint():
    """告诉用户怎么设置账号：打包后是双击 exe，跑源码时是命令行。"""
    if getattr(sys, "frozen", False):
        return "请打开 %s 点【设置】填写账号密码。" % os.path.basename(sys.executable)
    return "运行 python -m campusnet settings 设置（或用图形界面点【设置】）。"


# ===========================================================================
# 上下文
# ===========================================================================

class Context(object):
    def __init__(self, cfg, client, logger=None):
        self.cfg = cfg
        self.client = client
        self.logger = logger

    @property
    def username(self):
        return self.cfg.username


def build_client(cfg):
    return SrunPortalClient(base_url=cfg.base_url,
                            timeout=float(cfg.get("portal.timeout_sec", 8)))


# ===========================================================================
# 凭据
# ===========================================================================

def credentials_present(ctx):
    return _cfg_has_credentials(ctx.cfg)


def _cfg_has_credentials(cfg):
    return bool(cfg.username) and bool(cfg.get_password())


def setup_wizard(cfg):
    """首次使用时的引导设置。"""
    out("还没有配置校园网账号，先设置一下（只需一次）。")
    out("密码会用 Windows DPAPI 加密后保存在本机，同一台电脑的其它用户也解不开。")
    out("")
    username = ""
    while not username:
        username = input("账号（学号/工号）: ").strip()
        if not username:
            out("账号不能为空。")
    password = getpass.getpass("密码（输入时不显示）: ")
    if not password:
        err("密码不能为空，已取消。")
        return False
    again = getpass.getpass("再输一次确认: ")
    if password != again:
        err("两次输入的密码不一致，已取消。")
        return False
    cfg.set_credentials(username, password)
    cfg.save()
    logmod.register_secret(password)
    out("")
    out("已保存到 %s" % cfg.path)
    return True


def ensure_credentials(ctx, interactive=True):
    """确保有可用凭据；没有就（在交互环境下）引导设置。"""
    if credentials_present(ctx):
        return True
    if interactive and sys.stdin is not None and sys.stdin.isatty():
        if setup_wizard(ctx.cfg):
            return True
        return False
    err("还没有配置账号密码。%s" % setup_hint())
    return False


def configure_logging(cfg, ctx=None):
    logger = logmod.setup_logging(console=False)
    password = cfg.get_password()
    if password:
        logmod.register_secret(password)
    return logger


# ===========================================================================
# 子命令
# ===========================================================================

def cmd_status(args, ctx):
    password = ctx.cfg.get_password() if credentials_present(ctx) else None
    try:
        state, status, devices = ctx.client.local_state(ctx.username or None, password)
    except PortalUnreachable:
        err("✘ 访问不到认证门户 %s —— 当前可能不在校园网内。" % ctx.client.base_url)
        return EXIT_FAIL
    if state == STATE_UNKNOWN and status.rate_limited:
        # 服务端提示"请稍后 10s 重试"，那就等一次再问，别让用户拿到模糊答案。
        # 注意：--json 模式下 stdout 必须只有一段 JSON，诊断信息一律走 stderr，
        # 否则脚本 json.loads 直接失败（见 D-01）。
        note = err if args.json else out
        note("服务端提示：%s" % (errors.message_for(status.raw) or status.error))
        note("等 10 秒后重试一次…")
        time.sleep(10)
        state, status, devices = ctx.client.local_state(ctx.username or None, password)
    if password and not devices:
        try:
            devices = ctx.client.online_devices(ctx.username, password)
        except (PortalError, PortalUnreachable) as exc:
            err("（查询在线设备失败：%s）" % exc)
    my_ip = status.ip

    if args.json:
        out(json.dumps({
            "state": state,
            "online": status.online,
            "ip": my_ip,
            "username": status.user_name,
            "mac": status.mac,
            "device_total": status.device_total,
            "server_error": status.error or None,
            "devices": device_dicts(devices, my_ip),
        }, ensure_ascii=False, indent=2))
        return EXIT_OK if state == STATE_ONLINE else EXIT_FAIL

    if state == STATE_ONLINE:
        out("状态：已在线")
        out("  本机 IP : %s" % my_ip)
        out("  账号    : %s" % (status.user_name or ctx.username or "-"))
        if status.device_total:
            out("  在线设备: %s 台" % status.device_total)
    elif state == STATE_OFFLINE:
        out("状态：未登录（离线）")
    else:
        out("状态：暂时无法确定")
        if status.rate_limited:
            out("  服务端提示：%s（%s）"
                % (errors.message_for(status.raw) or status.error, status.error))
            out("  稍等 10 秒再试即可，这不代表已离线。")
        else:
            out("  服务端返回: %s" % (status.error or "无响应"))
        # 兜底：直接测一下外网可达性，好歹给个明确信号
        reachable = netprobe.internet_reachable()
        out("  直连测试：%s（本机 IP %s）"
            % ("可以访问外网" if reachable else "访问不了外网，多半确实处于离线状态",
               netprobe.local_ip() or "未知"))
    if devices:
        out("")
        out("在线设备列表：")
        out(render_devices(devices, my_ip))
    elif not credentials_present(ctx):
        out("")
        out("（还没设置账号，无法列出在线设备。%s）" % setup_hint())
    return EXIT_OK if state == STATE_ONLINE else EXIT_FAIL


def cmd_devices(args, ctx):
    if not ensure_credentials(ctx):
        return EXIT_USAGE
    if not ctx.client.portal_reachable():
        err("✘ 访问不到认证门户 %s —— 当前可能不在校园网内。" % ctx.client.base_url)
        return EXIT_FAIL
    devices = ctx.client.online_devices(ctx.username, ctx.cfg.get_password())
    try:
        my_ip = ctx.client.user_info().ip
    except PortalUnreachable:
        my_ip = None
    if args.json:
        out(json.dumps(device_dicts(devices, my_ip), ensure_ascii=False, indent=2))
    else:
        out(render_devices(devices, my_ip))
        out("")
        out("共 %d 台在线。" % len(devices))
    return EXIT_OK if devices else EXIT_FAIL


def cmd_login(args, ctx):
    if not ensure_credentials(ctx):
        return EXIT_USAGE
    if not ctx.client.portal_reachable():
        err("✘ 访问不到认证门户 %s —— 请先连好网线或 WiFi。" % ctx.client.base_url)
        return EXIT_FAIL

    service = CampusNetService(ctx.client, ctx.cfg, ctx.logger)
    approve = _make_approve_callback(args, ctx)
    out("正在登录（账号 %s）…" % ctx.username)
    outcome = service.login(approve_kick=approve)

    if outcome.kicked:
        out("已腾出名额：下线 %s" % "、".join(outcome.kicked))
    if outcome.ok:
        if outcome.kind == "already_online":
            out("已经在线了（IP %s），无需重复登录。" % (outcome.my_ip or "-"))
        else:
            res = outcome.result
            if res is not None and res.detail.get("unconfirmed"):
                out("登录请求已被服务端接受，但暂时无法确认状态（可能被限流）。")
                out("请稍后重新查询状态复查。")
            else:
                out("✔ 登录成功，本机 IP %s" % (outcome.my_ip or
                                                (res.ip if res else "-")))
        return EXIT_OK

    if outcome.kind == "declined":
        err("已取消：没有选择要下线的设备，名额没有腾出，登录未完成。")
        return EXIT_FAIL
    if outcome.kind == FULL:
        err("✘ 在线设备数已达上限，且腾位没成功：%s" % outcome.message)
        if outcome.devices:
            err("")
            err("当前在线设备：")
            err(render_devices(outcome.devices, outcome.my_ip))
        return EXIT_FAIL
    if outcome.kind == "ip_taken":
        err("✘ %s，请稍后重试或重连网络换 IP。" % outcome.message)
        return EXIT_FAIL
    if outcome.kind == SIGNATURE_ERROR:
        err("✘ 认证请求被服务端拒绝（%s）。请确认账号密码是否正确。" % outcome.message)
        return EXIT_FAIL
    err("✘ 登录失败：%s" % outcome.message)
    return EXIT_FAIL


def _make_approve_callback(args, ctx):
    """构造"决定踢谁"的回调。

    - --no-free：永不踢，直接放弃；
    - --yes：按策略预选直接执行，不再问；
    - 交互式终端：给出列表让你确认或改选；
    - 其它（脚本、重定向）：不擅自踢设备，明确要求加 --yes。
    """
    if getattr(args, "no_free", False):
        return lambda devices, preselected, my_ip: []
    if getattr(args, "yes", False):
        return None
    if sys.stdin is not None and sys.stdin.isatty():
        return lambda devices, preselected, my_ip: _interactive_choose(
            devices, preselected, my_ip, ctx)
    # 注意：这几行提示必须放在回调**里面**。放在外面会在构造回调时就打印，
    # 于是一次完全成功的登录也会附上"在线数已满需要腾位"的告警，
    # 让用户以为要踢人（实测复现，见 D-14）。
    def _decline(devices, preselected, my_ip):
        err("提示：在线数已满需要腾位，但当前不是交互终端。")
        err("      确认要下线哪台设备后，请加 --yes 让程序按策略自动腾位，")
        err("      或先看看在线设备列表。")
        return []

    return _decline


def _interactive_choose(devices, preselected, my_ip, ctx):
    """让用户在终端里确认或改选要下线的设备。"""
    preselect_ips = {d.ip for d in preselected}
    ordered = policy.sort_oldest_first(devices)
    out("")
    out("在线设备数已达上限，需要先下线一台才能登录。")
    out("（策略：%s；带 * 的是预选）" % ctx.cfg.kick_mode())
    out("")
    out("  #   设备类型  操作系统    上线时间             已在线       IP")
    out("  --  --------  ----------  -------------------  -----------  ------------------")
    for idx, dev in enumerate(ordered, 1):
        mark = "*" if dev.ip in preselect_ips else " "
        local = "  ← 本机" if my_ip and dev.ip == my_ip else ""
        out("  %s%d  %s  %s  %s  %s  %s%s"
            % (mark, idx, _pad(dev.client_type_label, 8), _pad(dev.os_name, 10),
               dev.add_time, _pad(dev.online_text(), 11), dev.ip, local))
    out("")
    while True:
        answer = input("回车＝按预选下线；输入编号（空格分隔）改选；n＝放弃：").strip()
        if answer.lower() in ("n", "no", "q"):
            return []
        if not answer:
            return [d.ip for d in preselected]
        picked = []
        for token in answer.replace(",", " ").split():
            if not token.isdigit():
                err("请输入编号、回车或 n。")
                picked = None
                break
            idx = int(token)
            if not 1 <= idx <= len(ordered):
                err("编号超出范围。")
                picked = None
                break
            picked.append(ordered[idx - 1].ip)
        if picked is not None and picked:
            return picked


def cmd_logout(args, ctx):
    if not ensure_credentials(ctx):
        return EXIT_USAGE
    if not ctx.client.portal_reachable():
        err("✘ 访问不到认证门户 %s —— 当前可能不在校园网内。" % ctx.client.base_url)
        return EXIT_FAIL
    password = ctx.cfg.get_password()
    out("正在注销（账号 %s）…" % ctx.username)
    method = ctx.cfg.get("behavior.logout_method", "dm")
    res = ctx.client.logout_local(ctx.username, password=password,
                                  ac_id=ctx.cfg.ac_id, method=method)
    if ctx.logger:
        ctx.logger.info("logout method=%s result=%s ip=%s state=%s",
                        method, res.kind, res.ip, res.detail.get("state"))
    if res.kind == NOT_ONLINE:
        out("当前已经是离线状态，无需下线。")
        return EXIT_OK
    if res.detail.get("verified"):
        out("✔ 已下线，在线名额已释放。")
        return EXIT_OK
    if res.detail.get("still_online"):
        if method == "portal":
            err("✘ 注销请求已被接受，但本机紧接着又被自动认证上线了——")
            err("  这台设备的 MAC 开通了校园网免认证，action=logout 会被它抵消。")
            err("  请把 behavior.logout_method 改为 dm（默认值），或直接用 kick 命令。")
        else:
            err("✘ 下线请求已被接受，但本机仍在设备列表里，请稍后复查。")
        return EXIT_FAIL
    err("无法确认下线结果（%s）。请稍后用 status 复查。" % res.message)
    return EXIT_FAIL


def cmd_kick(args, ctx):
    if not ensure_credentials(ctx):
        return EXIT_USAGE
    if not ctx.client.portal_reachable():
        err("✘ 访问不到认证门户 %s —— 当前可能不在校园网内。" % ctx.client.base_url)
        return EXIT_FAIL
    interval = float(ctx.cfg.get("behavior.batch_kick_interval_ms", 800)) / 1000.0
    failed = 0
    for idx, ip in enumerate(args.ips):
        if idx:
            time.sleep(interval)
        res = ctx.client.kick(ip, ctx.username)
        if ctx.logger:
            ctx.logger.info("kick ip=%s result=%s", ip, res.kind)
        # NOT_ONLINE 说明目标本来就不在线，目标状态已经达成 —— 算成功。
        # 这里必须和 service.py 里"腾位"的判定保持一致，否则同一次操作
        # CLI 报失败、GUI 报成功，用户没法判断到底成没成（见 D-02）。
        if res.ok or res.kind == NOT_ONLINE:
            out("✔ %s 已下线%s" % (ip, "（原本就不在线）"
                                    if res.kind == NOT_ONLINE else ""))
        else:
            failed += 1
            err("✘ %s 下线失败：%s" % (ip, res.message))
    if failed:
        return EXIT_FAIL
    out("")
    out("当前在线设备：")
    try:
        devices = ctx.client.online_devices(ctx.username, ctx.cfg.get_password())
        out(render_devices(devices))
    except (PortalError, PortalUnreachable) as exc:
        err("（刷新列表失败：%s）" % exc)
    return EXIT_OK


def _show_settings(cfg):
    out("配置文件：%s" % cfg.path)
    out("  账号    : %s" % (cfg.username or "（未设置）"))
    out("  密码    : %s" % ("已保存（DPAPI 加密）" if cfg.get_password() else "（未设置）"))
    out("  加密方式: %s" % cfg.get("portal.cipher", "dpapi"))
    out("  ac_id   : %s" % cfg.ac_id)
    out("  门户地址: %s" % cfg.base_url)
    out("  踢人策略: %s" % cfg.kick_mode)
    out("  开机自启: %s" % ("开" if cfg.get("startup.autostart") else "关"))


def cmd_settings(args, cfg):
    if args.clear_password:
        cfg.clear_password()
        cfg.save()
        out("已清除保存的密码。")
        return EXIT_OK

    password = args.password
    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\r\n")

    if args.username or password is not None:
        username = args.username or cfg.username
        if not username:
            err("✘ 必须同时提供账号。")
            return EXIT_USAGE
        if password == "":
            err("✘ 密码不能为空；如要清除请用 --clear-password。")
            return EXIT_USAGE
        keep = cfg.get_password()
        if password is None:
            # 只改账号、不提供密码时沿用旧密码。但"沿用"必须真的拿到明文：
            # 密文存在却解不开（换了 Windows 账户 / 配置被拷到别的机器）时，
            # 原来的 set_credentials(username, None) 会把密码清空还打印"已保存"，
            # 用户的密码就这么没了（见 D-06b）。
            if not keep and cfg.get("portal.password_dpapi"):
                err("✘ 保存的密码解不开（通常是换了 Windows 账户，或配置文件被拷到了别的机器）。")
                err("  为避免把密码悄悄清空，本次没有保存任何东西。")
                err("  请重新输入密码：campusnet settings --password-stdin")
                return EXIT_FAIL
            password = keep
        cfg.set_credentials(username, password)
        cfg.save()
        logmod.register_secret(password)
        out("✔ 已保存（账号 %s），下次运行直接生效。" % username)
        return EXIT_OK

    if args.show or args.json or not sys.stdin.isatty():
        if args.json:
            out(json.dumps({
                "config_path": cfg.path,
                "username": cfg.username,
                "password_saved": bool(cfg.get_password()),
                "ac_id": cfg.ac_id,
                "base_url": cfg.base_url,
                "kick_mode": cfg.kick_mode,
                "autostart": bool(cfg.get("startup.autostart")),
                "silent_when_autostart": bool(
                    cfg.get("startup.silent_when_autostart")),
            }, ensure_ascii=False, indent=2))
        else:
            _show_settings(cfg)
        return EXIT_OK

    # 交互式
    if not _cfg_has_credentials(cfg):
        return EXIT_OK if setup_wizard(cfg) else EXIT_USAGE
    _show_settings(cfg)
    out("")
    if input("要修改账号或密码吗？(y/N) ").strip().lower() not in ("y", "yes"):
        out("未做修改。")
        return EXIT_OK
    username = input("新账号（直接回车保持不变：%s）: " % cfg.username).strip()
    username = username or cfg.username
    password = getpass.getpass("新密码（直接回车保持不变）: ")
    if password:
        again = getpass.getpass("再输一次确认: ")
        if password != again:
            err("两次输入的密码不一致，未做修改。")
            return EXIT_USAGE
    cfg.set_credentials(username, password or cfg.get_password())
    cfg.save()
    if password:
        logmod.register_secret(password)
    out("✔ 已保存。")
    return EXIT_OK


def cmd_autostart(args, cfg):
    """开机自启开关（写/删 HKCU 的 Run 项，不需要管理员权限）。"""
    action = args.action
    try:
        if action == "on":
            silent = bool(cfg.get("startup.silent_when_autostart", False))
            command = autostart.enable(silent=silent)
            cfg.set("startup.autostart", True)
            cfg.save()
            out("✔ 已开启开机自启。")
            out("  注册的命令: %s" % command)
            out("  启动形态: %s" % ("静默（只留托盘）" if silent else "弹出主窗口"))
        elif action == "off":
            removed = autostart.disable()
            # 不能只看 disable() 的返回值就宣布成功：注册表项没删掉时
            # 用户以为关了，实际下次开机照样自启（见 D-12）。
            still = autostart.current_command()
            if still:
                err("✘ 关闭失败：开机自启项仍在注册表里（%s）" % still)
                err("  请手动删除 HKCU\\%s 下的 %s"
                    % (autostart.RUN_KEY, autostart.VALUE_NAME))
                return EXIT_FAIL
            cfg.set("startup.autostart", False)
            cfg.save()
            out("✔ 已关闭开机自启。" if removed else "开机自启本来就是关闭状态。")
        else:
            command = autostart.current_command()
            out("开机自启：%s" % ("已开启" if command else "未开启"))
            if command:
                out("  注册的命令: %s" % command)
            out("  启动形态: %s" % ("静默（只留托盘）"
                                    if cfg.get("startup.silent_when_autostart")
                                    else "弹出主窗口"))
        out("  说明：开机自启只把程序跑起来，不会自动认证。")
        return EXIT_OK
    except autostart.AutostartUnsupported as exc:
        err("✘ %s" % exc)
        return EXIT_USAGE
    except OSError as exc:
        err("✘ 读写注册表失败：%s" % exc)
        return EXIT_FAIL


# ===========================================================================
# 入口
# ===========================================================================

def build_parser():
    parser = argparse.ArgumentParser(
        prog="campusnet",
        description="校园网一键登录 / 一键下线（深澜 SRun 门户）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="退出码：0 成功 / 1 业务失败 / 2 参数或配置问题")
    sub = parser.add_subparsers(dest="command", metavar="<命令>")

    p = sub.add_parser("status", help="查看本机在线状态与在线设备")
    p.add_argument("--json", action="store_true", help="以 JSON 输出")

    p = sub.add_parser("login", help="一键登录（本机）")
    p.add_argument("-y", "--yes", action="store_true",
                   help="在线数已满时，直接按策略腾位，不再询问")
    p.add_argument("--no-free", action="store_true",
                   help="即使满员也不下线任何设备")

    p = sub.add_parser("logout", help="一键下线（注销本机）")

    p = sub.add_parser("devices", help="列出在线设备")
    p.add_argument("--json", action="store_true", help="以 JSON 输出")

    p = sub.add_parser("kick", help="踢指定设备下线（可给多个 IP）")
    p.add_argument("ips", nargs="+", metavar="IP", help="要下线的设备 IP")

    p = sub.add_parser("settings", help="查看/修改账号密码")
    p.add_argument("--show", action="store_true", help="只显示当前设置")
    p.add_argument("--json", action="store_true", help="以 JSON 输出当前设置")
    p.add_argument("--username", help="设置账号")
    p.add_argument("--password", help="设置密码（注意会出现在命令历史里）")
    p.add_argument("--password-stdin", action="store_true",
                   help="从标准输入读取密码（更安全）")
    p.add_argument("--clear-password", action="store_true", help="清除已保存的密码")

    p = sub.add_parser("gui", help="打开图形界面（主窗口 + 托盘图标）")
    p.add_argument("--no-tray", action="store_true", help="不启用托盘图标")
    p.add_argument("--selftest", action="store_true",
                   help="界面自检：走一遍首次设置流程，验证界面不会卡死（离线运行）")

    p = sub.add_parser("autostart", help="开机自启开关")
    p.add_argument("action", nargs="?", default="status",
                   choices=("on", "off", "status"),
                   help="on=开启 / off=关闭 / status=查看（默认）")

    return parser


def main(argv=None, make_client=build_client, cipher=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return EXIT_USAGE

    cfg = cfgmod.load_or_create(cipher=cipher)
    if cfg.load_error:
        # 配置读不动时不能装作没事：用户会以为"密码没了"，其实是文件坏了。
        # 走 stderr，避免污染 --json 的 stdout。
        err("⚠ 配置文件读不动：%s" % cfg.load_error)
        if cfg.backup_path:
            err("  原文件已备份到：%s" % cfg.backup_path)
        err("  本次按默认设置启动；重新设置一次账号密码即可恢复"
            "（campusnet settings）。")
    if args.command == "gui":
        if args.selftest:
            from .ui.app import run_selftest
            return run_selftest()
        from .ui import run as run_gui
        return run_gui(cfg, use_tray=not args.no_tray)
    if args.command == "autostart":
        return cmd_autostart(args, cfg)
    if args.command == "settings":
        try:
            return cmd_settings(args, cfg)
        except (KeyboardInterrupt, EOFError):
            err("\n已取消。")
            return EXIT_USAGE

    client = make_client(cfg)
    logger = configure_logging(cfg)
    ctx = Context(cfg, client, logger)
    try:
        handler = {
            "status": cmd_status,
            "devices": cmd_devices,
            "login": cmd_login,
            "logout": cmd_logout,
            "kick": cmd_kick,
        }[args.command]
        return handler(args, ctx)
    except PortalUnreachable as exc:
        err("✘ 网络请求失败：%s" % exc)
        return EXIT_FAIL
    except PortalError as exc:
        err("✘ 门户返回错误：%s" % exc)
        return EXIT_FAIL
    except KeyboardInterrupt:
        err("\n已取消。")
        return EXIT_USAGE
    except (EOFError, OSError) as exc:
        err("✘ 操作失败：%s" % exc)
        return EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
