# 更新日志

本项目的所有重要变更都会记录在此文件。

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本 2.0.0](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [1.1.0] - 2026-10-19

新增安卓客户端，并修复桌面端会导致界面永久卡死的缺陷。

### 新增

**安卓端（全新）**

- Kotlin + Jetpack Compose 原生实现，功能与桌面端对齐。
- `ConnectivityManager.bindProcessToNetwork()` 把进程钉在 Wi-Fi 上，
  解决「校园网无外网 → Android 自动切移动数据 → 认证失败」这一根因问题。
- 密码存入 Android Keystore（AES-256-GCM），不出 TEE。
- 前台服务常驻通知，通知栏可直接登录 / 下线 / 刷新。
- 开机自启（`BOOT_COMPLETED`）。
- 界面沿用桌面端的淡绿视觉体系（配色、层级、按钮分档一一对应）。

**桌面端**

- 命令行版本新增 `status` / `login` / `logout` / `devices` 子命令。
- 托盘状态点随在线状态变色；开机自启；单实例运行。

**工程**

- `tools/check_version.py`：校验三处版本号、CHANGELOG 小节与 `versionCode` 单调递增。
- `tools/package_release.ps1`：一条命令产出发布附件。
- `docs/04-test-plan.md`、`docs/05-test-report.md`：测试计划与执行报告。
- `docs/RELEASING.md`：版本策略、发布清单、签名密钥管理。

### 修复

- 桌面端：设备列表出现重复 IP 时 `Treeview.insert` 抛 `TclError`，
  界面永久卡在「正在检测中」。改为去重 + `try/finally` 释放忙碌态，
  并加 20 秒看门狗兜底。
- 桌面端：5xx 响应被误判为业务错误；E2620 / E6526（已在线）被当作失败。
- 桌面端：下线未验证就报成功；空账号被误判为「已在线」。
- 安卓端：确认在线后设备列表为空（协议层为省一次请求返回空列表）。
- 安卓端：前台服务从未启动（原本只有开机广播会拉起）。
- 安卓端：通知权限被拒时无任何提示，用户以为后台没在守护。
- 安卓端：通知开关检测漏判——权限仍是 granted 但「允许通知」总开关关闭时，
  只查 `checkSelfPermission` 会认为正常。
- 安卓端：拿不到本机 IP 时仍会发 `rad_user_dm` 请求，改为直接返回明确错误。

### 变更

- 发布附件改为带版本号的文件名（`CampusNet-1.1.0-win64.zip`），
  二进制不再进 Git 历史，统一挂在 Releases 下。

## [1.0.0] - 2026-09-16

首个桌面端版本（Windows）。提供一键登录 / 一键下线、在线设备列表、
满员时按策略腾位，以及托盘常驻与命令行版本。

[Unreleased]: https://github.com/BuZhiYuCi/NWAFU-Campusnet/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/BuZhiYuCi/NWAFU-Campusnet/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/BuZhiYuCi/NWAFU-Campusnet/releases/tag/v1.0.0
