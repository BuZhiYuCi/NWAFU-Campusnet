# 校园网认证 · Android 客户端

NWAFU 深澜（SRun）校园网门户的安卓客户端。协议实现与桌面版**逐字节对齐**，
用桌面版的 `tests/vectors.json` 作为跨语言黄金向量校验。

## 与桌面版的关系

不是「把 tkinter 界面搬到手机」，而是**新写一个客户端，共享协议实现**——
桌面版 4359 行代码里，能在 Android 上原样复用的只有纯协议层。

| 桌面版模块 | 行数 | 安卓对应 | 复用方式 |
| --- | --- | --- | --- |
| `crypto.py` | 173 | `crypto/Crypto.kt` | 逻辑 1:1 移植，黄金向量校验 |
| `portal.py` | 514 | `portal/PortalClient.kt` | 逻辑 1:1 移植 |
| `models.py` / `errors.py` / `policy.py` | 399 | `portal/*.kt` + `assets/error_codes.json` | 逻辑照搬 |
| `service.py` | 220 | `service/CampusNetService.kt` | 逻辑照搬 |
| `config.py` | 278 | `data/ConfigRepository.kt`（DataStore） | 重写 |
| `dpapi.py` | 127 | `data/CredentialStore.kt`（Keystore） | 重写 |
| `autostart.py` | 117 | `background/BootReceiver.kt` | 重写 |
| `ui/app.py` + `tray.py` | 1708 | `ui/MainActivity.kt` + `background/AuthForegroundService.kt` | 重写 |

## 模块结构

```
app/src/main/java/com/nwafu/campusnet/
├── crypto/Crypto.kt              XXTEA / 自定义 Base64 / HMAC-MD5 / chksum / dm 签名
├── portal/
│   ├── Models.kt                 结果类型、三态、Device、OnlineStatus
│   ├── PortalClient.kt           HTTP 传输、JSONP 解析、classify、六个接口
│   ├── Errors.kt                 错误码 → 中文文案
│   ├── Policy.kt                 满员腾位策略
│   └── AppConfig.kt              配置视图接口（供 JVM 测试注入）
├── service/CampusNetService.kt   登录 / 下线 / 腾位编排
├── data/
│   ├── ConfigRepository.kt       DataStore 读写
│   └── CredentialStore.kt        Android Keystore + AES-GCM
├── net/NetworkBinder.kt          把进程绑定到 Wi-Fi（关键，见下）
├── background/
│   ├── AuthForegroundService.kt  常驻通知 + 快捷登录/下线
│   └── BootReceiver.kt           开机自启
└── ui/
    ├── Theme.kt                  配色与圆角（与桌面端 theme.py 一一对应）
    ├── MainActivity.kt           Compose 界面
    └── MainViewModel.kt          状态与操作编排
```

## 四个安卓特有的设计决策

### 1. 把进程绑定到 Wi-Fi（`NetworkBinder`）

**这是最容易漏掉、后果最严重的一处。**

Android 连上「无法访问互联网」的 Wi-Fi（校园网正是如此）时，会保持 Wi-Fi 连接
但把默认路由切回移动数据。此时发认证请求，源 IP 是 4G 的出口地址，门户认不出是谁，
认证必然失败——而且报错信息看起来像"账号密码错"。

`ConnectivityManager.bindProcessToNetwork(wifiNetwork)` 把进程的 socket 钉在 Wi-Fi 上，
从根上解决。每次网络操作前调用一次。

### 2. 明文 HTTP 白名单（`network_security_config.xml`）

Android 9+ 默认禁止 cleartext HTTP，门户是 `http://`，不放行则所有请求直接失败。
门户地址由用户配置，无法预先枚举域名，只能全局放行——App 本身只向用户填写的地址发请求。

### 3. 密码存 Keystore 而非文件

对应桌面版的 DPAPI。密钥生成后不离开 TEE/StrongBox，App 只能请求加解密。
密文格式 `Base64(IV[12] + ciphertext+tag)`，AES-256-GCM。
密钥失效（换机、恢复出厂）时自动清除脏数据并返回 null，不会静默丢密码。

### 4. 前台服务 + 开机广播

对应桌面版的托盘常驻和注册表自启。Android 8+ 后台进程会被回收，
必须有前台服务（常驻通知）才能维持；开机自启靠 `BOOT_COMPLETED` 广播。

## 界面设计：与桌面端对齐

移动端沿用桌面端 `src/campusnet/ui/theme.py` 的整套视觉语言，色值一一对应
（见 `ui/Theme.kt` 的 `Palette`）。桌面端定的是「有生机的淡绿」，移动端不做二次创作。

| 用途 | 色值 | 说明 |
| --- | --- | --- |
| 页面底色 | `#EEF7F0` | 极淡的绿，整屏连通 |
| 卡片 / 次级卡片 | `#FFFFFF` / `#F5FBF7` | 斑马纹用后者 |
| 描边 | `#D6E9DC` | 卡片用 1dp 描边代替阴影 |
| 主色 / 加深 / 淡底 / 更淡 | `#3FB268` / `#2E8B50` / `#DCF2E3` / `#EAF8EE` | 主按钮、标题、次级按钮、本机行 |
| 正文 / 次要 | `#1D2F25` / `#69806F` | |
| 在线 / 离线 / 未知 | `#2FA85C` / `#E4796F` / `#9DB0A4` | 状态灯与大字的颜色 |

布局层级也照搬桌面端：

1. **状态卡**（白卡 + 描边）：校徽 + 状态灯 + 大字状态 + 明细行
   （`本机 IP x · 账号 y · 在线设备 N 台`，与桌面端 `detail_label` 拼法一致）
2. **操作区**：`一键登录`（实心绿 accent）+ `一键下线`（淡绿底 soft），
   对应桌面端的 `Accent.TButton` / `Soft.TButton`
3. **设备卡**：小标题用主色加深、表头分隔线、斑马纹、本机行淡绿底 +「本机」徽章，
   行内 `下线` 用 soft 小胶囊（对应 `Soft.TButton`），本机行不给下线入口
4. 顶部标题用主色加深放在底色上，不用色块压顶——桌面端也没有标题栏

刻意保留的差异：

- 桌面端用表格多列展示（设备类型 / 系统 / 上线时间 / 已在线 / IP），
  手机宽度放不下，改成两行式：第一行 IP + 徽章，第二行 `类型 · 系统 · 已在线时长`。
- 桌面端有 `全选 / 全不选 / 下线选中设备`，移动端改为每行独立的 `下线` 按钮——
  触屏上勾选再批量操作反而更麻烦。
- 提示卡用 `#FDEDEB` 淡红底。桌面端没有独立警示色，取离线色的同族淡底，
  免得在绿调界面里突然冒出一块橙色。
- 系统状态栏用主色加深 `#2E8B50` + 白图标；导航栏在 API 27+ 用页面底色 + 深图标。

## 构建

环境要求：JDK 17+（实测 21）、Android SDK（platform 36 + build-tools 36.0.0）。

```bash
# 1. 写 SDK 路径
echo "sdk.dir=D:/SoftWare/AndroidSDK/Sdk" > android/local.properties

# 2. 单元测试（47 条，含 5 组黄金向量）
gradle :app:testDebugUnitTest

# 3. 打 debug APK
gradle :app:assembleDebug
# 产物：app/build/outputs/apk/debug/app-debug.apk
```

依赖走腾讯云镜像（`settings.gradle.kts`），实测 1.3MB/s；直连 `dl.google.com` 只有 220KB/s。

## 测试

`app/src/test/` 下 47 条 JVM 单元测试，**不发任何真实校园网请求**：

- `CryptoTest`（14 条）：5 组黄金向量逐字节比对 `info` / `json` / `hmd5` / `chksum`，
  Base64 与 XXTEA 往返，dm 签名固定向量
- `PortalTest`（33 条）：JSONP 解析（含 BOM、`try{}catch` 包裹、HTML 拦截）、
  结果归类（E2620 vs E2621、not_online 家族、5xx）、三态判定、限流、登录参数、
  注销验证、设备列表

本地桩 `FakePortal` 用 `ServerSocket` 手写，不用 `com.sun.net.httpserver`
（后者在 Android 单元测试 classpath 下可能取不到）。

## 已知限制

1. **国产 ROM 自启动**：MIUI / EMUI / ColorOS 等默认拦截后台自启，
   用户需在系统「自启动管理」里手动放行，App 无法自行绕过。
2. **XXTEA 对非 ASCII 有损**：门户 JS 用 `charCodeAt & 0xFF` 打包，这是协议本身的特性，
   桌面版同样如此。登录载荷（学号/密码/IP/ac_id）全是 ASCII，实际不受影响。
3. **`os` / `name` 字段**默认发 `Android`，桌面版发 `Windows 10`。
   门户不校验这两个字段，但如果某校区有基于客户端的策略，需要改配置。
4. **设备列表的 `client_type` 不可信**：门户按自己的 DHCP/MAC 指纹判定客户端类型，
   与登录时上报的 `os`/`name` 无关。实测同一台手机在不同次认证后会被标成
   「移动设备或其他 · Android」或「PC · Windows 10」。因此「本机」标记**必须**用
   IP 与 `client_ip` 比对，不能依赖这个标签。
5. **通知权限被关时后台仍工作但无感知**：前台服务不依赖通知权限也能运行，
   但常驻通知不会显示。界面会给出提示并引导到系统设置（见下方 T-A07）。

## 真机验证（vivo V2207A / Android 14 / SDK 34）

| 项目 | 结果 |
| --- | --- |
| 安装 / 冷启动 | `Success`；`Displayed +1s95ms`，无 FATAL |
| 状态检测 | 「已在线」，IP `10.110.96.109`，设备列表 2 台 |
| 本机标记 | 按 IP 命中，正确标出「本机」 |
| 一键登录 | 「已在线」，通知正文同步为 `已在线 · <IP>` |
| 下线 | 确认弹窗 → 「未登录」，**且仅终止本机会话**（同时段电脑会话不受影响） |
| `bindProcessToNetwork` | 手机默认路由切到移动数据后，App 仍能访问门户 → 绑定生效 |
| 常驻通知 | 标题「校园网认证」、正文「已在线 · IP」、动作「下线」「刷新」均渲染 |
| 通知「刷新」动作 | 触发真实请求（logcat `Posix_connect :80`）并重发通知 |
| 前台服务 | `isForeground=true`，channel `campusnet_status`，`types=00000001` |
| 通知权限被拒（T-A07） | 界面显示提示卡 +「去开启」，跳转到本应用通知设置页 |

