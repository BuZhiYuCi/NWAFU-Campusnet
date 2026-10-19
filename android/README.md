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

## 构建

环境要求：JDK 17+（实测 21）、Android SDK（platform 36 + build-tools 36.0.0）。

```bash
# 1. 写 SDK 路径
echo "sdk.dir=D:/SoftWare/AndroidSDK/Sdk" > android/local.properties

# 2. 单元测试（45 条，含 5 组黄金向量）
gradle :app:testDebugUnitTest

# 3. 打 debug APK
gradle :app:assembleDebug
# 产物：app/build/outputs/apk/debug/app-debug.apk
```

依赖走腾讯云镜像（`settings.gradle.kts`），实测 1.3MB/s；直连 `dl.google.com` 只有 220KB/s。

## 测试

`app/src/test/` 下 45 条 JVM 单元测试，**不发任何真实校园网请求**：

- `CryptoTest`（14 条）：5 组黄金向量逐字节比对 `info` / `json` / `hmd5` / `chksum`，
  Base64 与 XXTEA 往返，dm 签名固定向量
- `PortalTest`（31 条）：JSONP 解析（含 BOM、`try{}catch` 包裹、HTML 拦截）、
  结果归类（E2620 vs E2621、not_online 家族、5xx）、三态判定、限流、登录参数、
  注销验证、设备列表

本地桩 `FakePortal` 用 `ServerSocket` 手写，不用 `com.sun.net.httpserver`
（后者在 Android 单元测试 classpath 下可能取不到）。

## 已知限制

1. **未做真机验证**：构建环境没有连接设备也没有模拟器。编译、单元测试、
   APK 签名均已通过，但真实联网认证需要在手机上验证。
2. **国产 ROM 自启动**：MIUI / EMUI / ColorOS 等默认拦截后台自启，
   用户需在系统「自启动管理」里手动放行，App 无法自行绕过。
3. **XXTEA 对非 ASCII 有损**：门户 JS 用 `charCodeAt & 0xFF` 打包，这是协议本身的特性，
   桌面版同样如此。登录载荷（学号/密码/IP/ac_id）全是 ASCII，实际不受影响。
4. **`os` / `name` 字段**默认发 `Android`，桌面版发 `Windows 10`。
   门户不校验这两个字段，但如果某校区有基于客户端的策略，需要改配置。
