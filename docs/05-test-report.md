# 校园网助手 · 测试执行报告

> 对应计划：`docs/04-test-plan.md`（125 条用例，A 92 / M 25 / S 8）
> 执行时间：2026-10-17
> 被测版本：`a738c6f "better GUI"` + 本轮修复（工作区未提交改动）
> 真实环境：账号 `1778****52`，门户 `http://172.26.8.11`，本机 `10.110.21.18`

---

## 1. 结论摘要

| 项目 | 结果 |
| --- | --- |
| 自动化用例 | **257 条全部通过**（基线 216 → 现 257，+41），`expectedFailure` 归零 |
| 计划用例执行率 | **121 / 125**（TP-REL 组 4 条长期稳定性用例未执行） |
| 缺陷总数 | **16 条**（P0 9 / P1 2 / P2 3 / P3 2） |
| 已修复 | **12 条**（9 条 P0、2 条 P1，另附 1 条 P2） |
| 遗留 | 4 条 P2/P3，均有明确复现路径与修复建议，未改代码 |
| 真实门户破坏性闭环 | **通过**：注销后外网全断、门户仍可达、重登 IP 一致、**未触碰他人设备** |
| 打包产物 | `dist/CampusNet.exe` / `CampusNet-CLI.exe` 各 27.5 MB，自检通过，子系统分别为 GUI/控制台 |

**最初那个"首次配好账号密码后一直卡在检测中"的问题已定位到确切代码行，并用实验证明**（见 §4）。
它不是网络问题，也不是账号问题：**设备列表里只要出现两台 IP 相同的会话，界面第一次渲染就会抛 `TclError`，而那次异常发生在"关闭忙碌态"之前，于是状态标签永远停在"正在检测…"**。

---

## 2. 执行环境与口径

| 维度 | 取值 |
| --- | --- |
| OS | Windows 10.0.22621（x64） |
| Python（GUI/测试） | `D:\SoftWare\Python\3_10_6\python.exe`（**托管 3.13 无 tkinter，不能跑 GUI 用例**） |
| Python（打包） | 同上，PyInstaller 6.22.3 |
| 网络 | 校园网已认证，本机 `10.110.21.18`，MAC `d0:39:57:07:39:f5` |
| 同账号其它在线设备 | `10.111.130.53`（**全程未操作**，`add_time` 始终为 `2026-10-16 07:57:14`） |
| 凭据传递 | 经环境变量注入子进程，命令行与日志中均无明文（红线 R1） |
| 桩服务 | `tests/support/fake_portal.py`（本地 HTTP/1.0，全程不碰真实门户） |

> 口径说明：所有"通过"都来自实际执行输出，不采信代码推断；所有真实门户请求均为本机 IP 相关操作，
> 用户明确要求"不允许踢其他设备"，该约束全程遵守（证据见 §6.3）。

---

## 3. 分层执行总览

| 层 | 手段 | 规模 | 结果 |
| --- | --- | --- | --- |
| L0 静态评审 | 人工读码 + `grep` 全仓扫描 | 13 条候选，执行期补 3 条 | 全部落到具体行号 |
| L1 单元 | `unittest`（crypto/policy/config/theme/widgets/log） | 81 条 | 全绿 |
| L2 协议桩 | `FakePortal` 本地 HTTP 服务 | 22 条（TP-PTL 全覆盖） | 全绿 |
| L3 编排 | 脚本化假客户端（满员→腾位→重试） | 19 条 | 全绿 |
| L4 CLI 进程级 | `subprocess` 真实起进程 + 退出码/管道断言 | 7 条 | 全绿 |
| L5 GUI | Tk 真窗口 + 事件循环驱动 | 30 条 | 全绿 |
| L6 真机 | 真实门户只读 + 破坏性闭环 + 打包产物 | 4 个批次 | 全绿 |

### 3.1 计划用例执行情况

| 用例组 | 计划 | 已执行 | 未执行 | 备注 |
| --- | --- | --- | --- | --- |
| TP-CFG 配置与凭据 | 12 | 12 | 0 | 含损坏配置抢救、跨进程解密 |
| TP-CRY 加密与签名 | 10 | 10 | 0 | 另用真实 token 做了一次一致性校验 |
| TP-PTL 协议层 | 14 | 14 | 0 | 全部走本地桩，不发真实请求 |
| TP-STS 三态判定 | 10 | 10 | 0 | 含限流冷却、设备列表兜底 |
| TP-LGN 登录 | 12 | 12 | 0 | 含满员腾位全链路 |
| TP-LGO 注销 | 8 | 8 | 0 | 含真实注销 2 轮 |
| TP-CLI 命令行 | 12 | 12 | 0 | 含 `--json` 纯净性、退出码矩阵 |
| TP-GUI 界面 | 15 | 15 | 0 | 含看门狗、重复 IP、渲染失败 |
| TP-AUT 开机自启 | 6 | 6 | 0 | 含真实注册表读写还原 |
| TP-LOG 日志脱敏 | 6 | 6 | 0 | — |
| TP-PKG 打包 | 8 | 8 | 0 | 含 PE 子系统、资源内嵌校验 |
| TP-SEC 凭据泄露 | 6 | 6 | 0 | 258 文件明文扫描 |
| TP-REL 可靠性 | 6 | **2** | **4** | 见 §8 |
| **合计** | **125** | **121** | **4** | — |

---

## 4. 核心问题：为什么会卡在"正在检测…"

### 4.1 根因

`src/campusnet/ui/app.py` 里三件事叠在一起：

1. 状态标签的初值写死为 `text="正在检测…"`，全程序**只有 `_set_state()` 会改写它**；
2. 首次保存账号后触发的 `refresh()` 在 `done()` 回调里**先** `_render_devices()`、**后** `_set_state()` / `_set_busy(False)`，且**没有 try/finally**；
3. `_render_devices()` 用 `tree.insert(..., iid=dev.ip, ...)` 把 **IP 当作 Treeview 的行 ID**。

当账号下有两台会话的 IP 相同（IPv4/IPv6 双栈、或上次没退干净的残留会话），第二次 `insert` 抛：

```
_tkinter.TclError: Item 10.111.147.127 already exists
```

异常从回调里冒出去 → 后面的 `_set_state()` 和 `_set_busy(False)` **一行都没执行** → 标签永远停在"正在检测…"、按钮永远灰着。

### 4.2 实验证据（修复前 / 修复后，同一场景）

用 HEAD 版 `app.py` + 含重复 IP 的设备列表走一遍"首次设置 → 保存 → 刷新"：

| | 修复前 | 修复后 |
| --- | --- | --- |
| 异常 | `TclError: Item 10.111.147.127 already exists` | 无 |
| 状态标签 | `正在检测…` | `已在线` |
| 忙碌标志 | `True`（按钮全灰） | `False` |
| 设备行数 | 1（只插进去一台） | 2 |

### 4.3 为什么"只有别人"会踩到

作者的账号恰好是两台**不同 IP** 的设备，`iid` 永不冲突，所以本地怎么点都正常。
任何出现"同 IP 双会话"的账号，第一次渲染就必崩——而"第一次渲染"恰好就是新用户配好账号后的那次刷新。
这解释了"发给别人后首次使用必卡"的全部现象。

### 4.4 修复要点（`app.py`，+173/−30）

- `_render_devices()` 的行 ID 改为序号，并按 IP 去重、丢弃空 IP；渲染包在自己的 `try` 里，失败只记日志不影响状态刷新。
- `refresh()` 引入序号 `_refresh_seq`：迟到的结果直接作废，不会把新一轮的忙碌态清掉。
- 新增 **20 秒看门狗**：worker 卡死也会在超时后解除忙碌态并给出提示，界面不再有"永久假死"的可能。
- `done()` / `fail()` 都走 `finally: self._finish_refresh(...)`，异常路径也一定收尾。
- 忙碌期间的刷新请求不再被静默丢弃，记 `_refresh_pending`，收尾后补跑。
- 启动时区分"有凭据 → 刷新"与"无凭据 → 提示未配置并直接弹设置窗"。

---

## 5. 缺陷清单

### 5.1 已修复（12 条）

| ID | 级别 | 位置 | 问题 | 修复 | 回归用例 |
| --- | --- | --- | --- | --- | --- |
| D-00 | **P0** | `ui/app.py` | 重复 IP 导致渲染抛异常，界面永久卡在"正在检测…" | 行 ID 去 IP 化 + try/finally + 看门狗 + 序号作废 | `test_gui.RefreshRobustnessTest` / `RecoveryTest`（7 条） |
| D-01 | **P0** | `cli.py:194-198` | 限流分支先 `print` 人类文本再输出 JSON，`status --json` 被污染 | 诊断信息在 `--json` 时改走 stderr | `test_status_json_stays_pure_under_rate_limit` |
| D-02 | **P1** | `cli.py:423` + `portal.py:classify` | 踢一台已下线设备被判失败：`E6527`「当前设备不在线」被归为 UNKNOWN，而 `service` 那边算成功 | 补齐"不在线"错误码族（`E6503/E6527/E6528/NotOnlineError/YouAreNotOnline`）→ `NOT_ONLINE`；`cmd_kick` 视其为成功 | `test_kick_already_offline_is_treated_as_success` / `test_kick_not_online_counts_as_success` |
| D-03 | **P0** | `service.py:146` | `state=online` 但 `user_name` 为空（限流期合成状态）时直接报"已经在线"，真正的登录被跳过 | 仅当 `user_name` 非空才短路；否则继续走真实登录 | `test_online_state_without_username_still_attempts_login` |
| D-05 | **P0** | `portal.py:332,377` | 限流冷却 60s 内合成状态冒充服务端结论；登录成功后不重置冷却 | 合成状态打 `synthetic` 标记并对齐 `online`；登录确认在线即清零冷却 | `test_synthetic_status_is_marked` / `test_successful_login_resets_rate_limit_cooldown` |
| D-06a | **P0** | `config.py:load_or_create` | 配置损坏时静默回退默认值，下次 `save()` 覆盖原文件 → **凭据永久丢失** | 先复制 `<config>.broken-<时间戳>` 备份，并记 `load_error`；CLI 启动时明确提示 | `BrokenFileTest`（3 条） |
| D-06b | **P0** | `cli.py:cmd_settings` | 密文解不开时只改账号 → 密码被静默清空，仍打印"已保存" | 检测"有密文但解不开"，拒绝保存并提示重新输入 | `test_username_change_does_not_silently_wipe_undecryptable_password` |
| D-07 | **P0** | `service.py:94` | 注销时 `NOT_ONLINE` 未经状态验证也算成功，名额可能没释放 | 要求 `verified` 为真；否则如实报"无法确认" | `test_not_online_without_verification_is_not_success` |
| D-11 | **P0** | `portal.py:classify` / `user_info` | 完全不看 HTTP 状态码；`E2620`「已经在线了」被判成"在线数已满" | 新增 `SERVER_ERROR` 归 5xx；`E2620`/`E6526` → `ALREADY_ONLINE` | `test_5xx_is_classified_as_server_error` / `test_e2620_is_already_online_not_full` / `test_e2621_and_e6512_are_full` |
| D-12 | **P1** | `cli.py:cmd_autostart` | 注册表删除失败被吞，仍打印"已关闭"并把配置写成 `false` | 删除后复查 `current_command()`，仍在则报失败且不改配置 | `test_off_reports_failure_when_registry_entry_survives` |
| D-13 | **P0** | `tests/stagea-result.json` + **全仓 9 个文件** | 真实学号（40 处）、内网 IP、`access_token` 散落在测试夹具、文档示例和加密向量里，与 README"不含真实凭据"矛盾 | ①`stagea-result.json` 脱敏；②全仓学号统一替换为 `20230000001`；③`vectors.json` 的 `info/hmd5/chksum` 按新账号**重算**（否则向量对不上）；④`tools/probe.py` 输出改名 `.local.json` 并加入 `.gitignore` | 全仓扫描：学号 **0 命中**、`access_token` **0 命中**；257 条用例仍全绿 |
| D-14 | P2 | `cli.py:_make_approve_callback` | 非交互终端下**无条件**打印"在线数已满需要腾位"，一次完全成功的登录也会带上这句告警 | 三行提示移入回调内部，只在服务端真的回满员时才打印 | `test_login_success` 增加"不含腾位字样"断言 |

> D-11 的 `E2620` 是本轮最危险的一条：它被判成 FULL 后，上层会进入"腾位"流程，
> **去踢掉一台在线设备**——而此刻真正在线的很可能就是用户自己的机器。

### 5.2 遗留（4 条，均为 P2/P3，已记录未改）

| ID | 级别 | 位置 | 问题 | 建议 |
| --- | --- | --- | --- | --- |
| D-04 | P2 | `service.py:181-205` | 满员且设备列表为空时 `break`，最终提示"腾位后仍然登录失败"，语义误导 | 单独分支提示"服务端说满员但查不到设备，稍后重试" |
| D-08 | P3 | `cli.py:19` vs `cli.py:299` | 头注释称"用户取消=2"，实际返回 1 | 改注释，或统一为 2 |
| D-09 | P3 | `service.py:190-197` | 跨轮踢同一 IP 会重复计入 `kicked`，提示里出现重复 IP | `kicked` 去重后再拼接 |
| D-10 | P2 | `cli.py:415` / `service.py:109` | `batch_kick_interval_ms` 非法值直接 `float()`，未捕获 → 裸 traceback | 读配置时校验并回落默认值 |

> **残留**：内网 IP（`10.x`）仍留在文档示例与测试夹具里。它们是校园 DHCP 的临时地址、
> 不指向具体人，脱敏收益低而改动面大（会牵连 `vectors.json` 的签名重算与多处断言），
> 本轮保留。若要彻底清理，建议统一换成 `10.0.0.x` 后重算向量。

---

## 6. 真实门户测试记录

### 6.1 只读批次（B）

| 项 | 观测值 |
| --- | --- |
| `status` 耗时 | 0.27 – 0.46 s |
| `status --json` | 纯 JSON，stderr 长度 **0**（D-01 修复后） |
| `devices --json` | 合法数组，2 条，`is_local` 正确 |
| `get_challenge` | token 长度 64，`client_ip 10.110.21.18`，`expire 60` |
| 加密自洽 | `hmd5` 32 hex、`info` 以 `{SRBX1}` 开头（长 147）、`chksum` sha1 40 hex |
| 本地加解密 | `dm_signature` 可复现、自定义 base64 往返一致、字母表与标准表不同 |
| 配置/DPAPI | 密文落盘、明文不在文件、**跨进程解密成功** |

### 6.2 破坏性闭环（C）

用户约束：只测本机、必须自动恢复。

```
C1 快照      state=online  ip=10.110.21.18  设备=2
C2 logout    EXIT=0  2.30 s  「✔ 已下线，在线名额已释放」
C2-a 复查    state=offline  本机已从设备列表消失
C3 login     EXIT=0  2.52 s  第 1 次尝试即恢复，无需冷却等待
C3-a 校验    state=online  ip 与快照一致
```

### 6.3 "真的断网了吗"——三路探针矩阵

> 说明：沙箱内的 HTTP 会被代理改写（注销**前**就返回 403），因此本组探针在无沙箱环境下执行，
> 否则"断网"结论不可信。这是本轮唯一一处需要提升权限的测试。

| 时点 | ICMP 223.5.5.5 | TCP 223.5.5.5:53 | TCP 114.114.114.114:53 | HTTP baidu | TCP 门户:80 |
| --- | --- | --- | --- | --- | --- |
| 注销前 | ✅ | ✅ | ✅ | ✅ | ✅ |
| 注销后 #1 | ❌ | ❌ | ❌ | ❌ | ✅ |
| 注销后 #2 | ❌ | ❌ | ❌ | ❌ | ✅ |
| 注销后 #3 | ❌ | ❌ | ❌ | ❌ | ✅ |
| 重登后 | ✅ | ✅ | ✅ | ✅ | ✅ |

结论：注销确实切断了外网，门户仍可达（局域网免认证），重登后全部恢复。
**他人设备 `10.111.130.53` 的 `add_time` 全程未变，在线时长从「1 天 3 小时」连续增长到「1 天 4 小时」——从未被踢。**

### 6.4 GUI 端到端（C4）

真实 `SrunPortalClient` + 真实门户，驱动真窗口：

```
0.08s  初始标签='正在检测…' 忙碌=False
0.24s  忙碌=True 行数=0
0.38s  标签='已在线' 忙碌=False 行数=2      ← 首次刷新 0.30 s
0.45s  第二次刷新 0.07 s，行数仍为 2（无重复插入）
```

### 6.5 打包产物（B6）

| 项 | 结果 |
| --- | --- |
| 构建耗时 | 60 s（PyInstaller 6.22.3） |
| 产物 | `CampusNet.exe` 27.46 MB / `CampusNet-CLI.exe` 27.47 MB |
| PE 子系统 | GUI = `2`（无控制台）/ CLI = `3`（有控制台） |
| 资源内嵌 | `error_codes.json`、`nwafu-emblem.png`、`campusnet.ico` 均命中；tkinter/PIL/pystray hook 生效 |
| 冷启动 | `--help` 2.69 s / 2.76 s（onefile 解包 27 MB，属预期） |
| `CampusNet.exe --selftest` | EXIT=0，日志：`GUI 自检 通过：状态标签='未登录' 忙碌=False` |
| 打包版 CLI 连真实门户 | `EXIT_JSON_OK state=online ip=10.110.21.18 devices=2`，stderr 为空 |

---

## 7. 代码改动清单

```
 .gitignore                 |   3 +        屏蔽 *.local.json（探测产物）
 docs/01-project-design.md  |   4 +-       D-13 学号脱敏
 docs/02-portal-protocol.md |  18 +--       D-13 学号脱敏（示例）
 src/campusnet/cli.py       |  66 ++++---   D-01/D-02/D-06b/D-12/D-14
 src/campusnet/config.py    |  39 +++++-    D-06a 备份 + load_error
 src/campusnet/models.py    |   4 +        SERVER_ERROR 结果类型
 src/campusnet/portal.py    |  63 ++++--    D-02/D-05/D-11
 src/campusnet/service.py   |  19 +++-     D-03/D-07
 src/campusnet/ui/app.py    | 213 ++++++---  D-00 卡死（上一阶段）
 tests/stagea-result.json   |  14 +--      D-13 脱敏
 tests/test_cli.py          |  66 ++++-     +4 条
 tests/test_config.py       |  43 +++++-    +3 条
 tests/test_crypto.py       |   4 +-       D-13 夹具脱敏
 tests/test_gui.py          | 142 ++++++     +7 条
 tests/test_portal.py       |  10 +--      D-13 夹具脱敏
 tests/test_service.py      |  35 ++++-    +2 条
 tests/vectors.json         |  16 +--      D-13 脱敏 + 派生值重算
 tools/js_reference.js      |   4 +-       D-13 脱敏
 tools/probe.py             |   4 +-       输出改 .local.json
 19 files changed, 652 insertions(+), 115 deletions(-)
 新增：docs/04-test-plan.md、docs/05-test-report.md、
       tests/support/fake_portal.py、tests/test_portal_http.py、tests/test_cli_process.py
```

所有新增/修改都带中文注释说明"为什么这么改"，并标注对应缺陷编号。

---

## 8. 未执行与不可测项（诚实清单）

| 项 | 原因 |
| --- | --- |
| TP-REL 的 4 条（24h 稳定性、断网重连风暴、休眠唤醒、多网卡切换） | 单次会话内无法完成；需长时间挂机 + 物理拔插网络 |
| 非 Windows 平台 | DPAPI、注册表自启、`%APPDATA%` 路径均为 Windows 专有，其它平台跑不起来 |
| 服务端真限流（`speed_limit_error`） | 需要主动打高频请求触发，风险不可控；已用桩服务覆盖 |
| 满员场景（E2621/E6512）真实触发 | 需要账号同时在线数打满，会牵连他人设备，与"不允许踢其他设备"冲突；已用桩 + 单测覆盖 |
| 托盘图标交互（右键菜单、双击还原） | 无自动化手段，只能人工点；本轮只验证了"托盘能启动" |
| 高 DPI / 多显示器 / 深色模式 | 需多套显示配置，本轮环境只有单屏 100% |

---

## 9. 建议

**交付前必须做**：把 §5.2 的 D-04、D-10 补掉（都会误导用户判断），D-08/D-09 顺手改。
**发给别人之前**：让对方先跑一次 `CampusNet.exe --selftest`（10 秒，不联网、不碰正式配置），
自检窗口能弹出来就说明界面链路是通的——这正是为"卡在正在检测"这类问题准备的自证手段。
**下一轮**：给 `_render_devices` 补一条"设备数为 0 / IP 为空 / 超长 IP 列表"的桩用例；
把 `wait_state` 的退避策略做成可配置，便于现场调参。
