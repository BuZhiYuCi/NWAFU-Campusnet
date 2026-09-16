# 校园网助手

西北农林科技大学 深澜（SRun）校园网的一键登录 / 一键下线工具，Windows 平台。

解决的实际问题：学校限制同时在线设备数，而手动**断开 WiFi 或关机并不会自动释放名额**，且校园网登录页面的注销功能绕不开MAC免认证，无法真正下线，服务端会话会一直挂着（实测能挂 3 天以上）。想要真正腾出名额，必须调用门户的注销接口。

本工具把这些操作变成一次点击，并且能自动完成"满员 → 踢掉一台 → 重新登录"。

---

## 快速开始

### 用打包好的程序

1. 双击 `CampusNet.exe`，主窗口出现。
2. 第一次运行会弹出设置，填入学号和密码，保存。
3. 之后连好网线或 WiFi，点【一键登录】即可；点【一键下线】真正注销。

命令行版（给脚本用）：`CampusNet-CLI.exe status`

### 从源码运行（开发）

```powershell
python -m pip install -r requirements.txt

.\campusnet.cmd gui          # 图形界面
.\campusnet.cmd status       # 看本机在线状态与在线设备
.\campusnet.cmd settings     # 设置账号密码
```

---

## 命令一览

```
status          查看本机在线状态与在线设备（--json 输出 JSON）
login           一键登录；在线数已满时引导腾位
                  -y/--yes  直接按策略腾位，不再询问
                  --no-free 即使满员也不下线任何设备
logout          一键下线（真正注销，释放名额）
devices         只列在线设备（--json）
kick <IP>...    踢指定设备下线，可一次给多个
settings        查看/修改账号密码（--show --json --password-stdin ...）
autostart       开机自启开关：on / off / status
gui             打开图形界面（--no-tray 不带托盘）
```

退出码：`0` 成功；`1` 业务失败（不在校园网、登录失败、限流等）；`2` 参数或配置问题。

---

## 几个必须知道的事实

这些是实机验证出来的，决定了程序的很多行为（详见 `docs/`）。

**1. 断网 ≠ 下线。**
禁用网卡、断开 WiFi、关机都不会释放名额，只有调用注销接口才会。

**2. "一键下线"默认用的是 `rad_user_dm`，不是网页上的"注销"。**
实测：这台设备的 MAC 开通了校园网免认证，用网页那套 `action=logout` 注销后，
准入设备会**在同一秒**用 MAC 把设备重新认证上线——外网一秒钟都没断。
换成 `rad_user_dm`（带 `unbind=1`，会连 MAC 绑定一起解除）才能真正离线，
实测 67 秒全程保持离线。

配置项 `behavior.logout_method` 可以切回 `portal`，但那样下线不持久。

**3. 满员时需要你确认踢哪台，程序不会擅自踢。**
在线设备列表里只有 IP、系统、上线时间，**没有主机名和 MAC**，而 IP 是 DHCP 动态分配的，
所以没法可靠地自动识别"哪台是哪台"。默认策略是**预选上线时间最早（在线最久）的那台**，
由你确认或改选。脚本等非交互场景必须显式加 `--yes` 才允许自动腾位。

**4. 服务端有限流。**
`rad_user_info` 请求过密会返回 `speed_limit_error`（"认证请求太频繁，请稍后10s重试"）。
**这不代表离线**。程序会自动改用不受限的"在线设备列表"来判定状态，
并在限流期间退避 60 秒，避免轮询把自己打成限流。

**5. 判断"有没有网"不能只看 HTTP 状态码。**
未认证时准入设备会把 HTTP 请求拦下来返回门户页面，状态码常常还是 200。
程序用 TCP 直连测试作为兜底判据。

---

## 安全与隐私

- 密码用 **Windows DPAPI**（当前用户级）加密后存进
  `%APPDATA%\CampusNet\config.json`，文件里**没有明文密码**。
- 换 Windows 用户、换机器、重装系统后密文解不开，需要重新输入密码——这是设计如此。
- 日志走统一脱敏：`password=xxx`、`"password":"xxx"`、`{MD5}<hash>` 一律替换成 `***`，
  连异常堆栈里的也不会漏。
- 日志文件：`%APPDATA%\CampusNet\logs\campusnet.log`，单文件超 1MB 自动轮转保留 5 份。
- 仓库里不含任何真实凭据；`config.json` / 日志 / 打包产物都在 `.gitignore` 里。

---

## 开机自启

```powershell
CampusNet-CLI.exe autostart on     # 开启
CampusNet-CLI.exe autostart off    # 关闭
CampusNet-CLI.exe autostart        # 查看状态
```

也可以在图形界面的设置里勾选。实现上只写
`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`，**只影响当前用户，不需要管理员权限**。

**开机自启只把程序启动起来，不会自动认证**——设备既有 WiFi 也有网线，网络环境不一致，
由你自己连好网后再点【一键登录】。默认是**关闭**的。

设置里还有"自启时静默启动"，勾上以后开机只留托盘图标，不弹主窗口。

---

## 目录结构

```
src/campusnet/
  crypto.py     加密（XXTEA + 自定义 Base64 + HMAC-MD5），按门户官方 JS 逐行移植
  portal.py     门户客户端：token / 登录 / 注销 / 在线设备 / 踢人
  service.py    业务编排：登录、下线、满员腾位
  policy.py     腾位策略（踢谁）
  models.py     数据模型     errors.py   错误码 → 中文提示
  config.py     配置读写 + DPAPI        log.py  滚动日志 + 脱敏
  autostart.py  开机自启                netprobe.py  网络探测
  cli.py        命令行                  ui/          图形界面
docs/           设计文档、协议分析、实测记录
tests/          182 项测试（unittest，pytest 也能跑）
tools/          一次性验证脚本与打包脚本
```

## 界面与图标

界面用"有生机的淡绿"作主色：窗口底色是很淡的绿，主按钮是实心草绿，
在线状态用饱和绿、离线用柔和珊瑚红、未知用灰绿——
三种状态在任何背景下一眼可分。

程序图标与界面里的徽标来自**学校官方发布的校徽矢量图**：

1. 取自学校官网「校标识 → 校徽」页面的附件《（2020章程）校徽》；
2. 该 PDF 是纯矢量（无点阵图），由 `tools/extract_emblem.py` 提取：
   - `assets/nwafu-emblem.svg`　矢量版（viewBox 已裁到徽标本体）
   - `assets/nwafu-emblem.png`　600dpi 渲染，圆形外底已抠成透明
3. `tools/make_icon.py` 由它生成多尺寸 `assets/campusnet.ico`（16–256px）
   和界面用的 `assets/emblem-ui.png`。

> 校徽是学校的标识，版权归学校所有。本程序只是个人自用的校园网工具，
> 在此按官方发布件使用；如果你要再分发或用于其它用途，请先确认学校的使用规定。

跑测试：

```powershell
python -m unittest discover -s tests
```

---

## 打包

```powershell
powershell -ExecutionPolicy Bypass -File tools/build.ps1
```

产出 `dist\CampusNet.exe`（图形界面，无控制台）和 `dist\CampusNet-CLI.exe`（命令行）。

脚本会自动挑一个装了 PyInstaller 的解释器——注意 `powershell -File` 不加载你的 profile，
直接用 `python` 可能落到另一个 Python 上，所以有 `-Python <路径>` 参数可以显式指定。

---

## 常见问题

**提示"访问不到认证门户"**
不在校园网内。先连好网线或 WiFi；在校外需要先连学校 VPN 或用学校的其他入口。

**提示"状态：暂时无法确定"**
服务端限流了，等 10 秒重试即可，**不代表已离线**。程序会同时给出 TCP 直连测试的结果作为参考。

**界面卡在"正在检测…"不动**
跑一下界面自检，它会在真实窗口里离线走一遍"首次设置 → 保存 → 刷新"，
结果会写进日志并弹窗显示：

```
CampusNet.exe --selftest
```

日志位置：`%APPDATA%\CampusNet\logs\campusnet.log`

**登录成功但设备列表里没有我**
服务端会话建立有延迟，程序会轮询确认；也可以手动刷新一次。

**满员时踢不掉某台设备**
那台设备的 MAC 也开了免认证，或者它正在使用中。可以换一台踢，
或者直接在那台设备上点【一键下线】。

**提示"本机 IP 已被其它账号占用"**
DHCP 把你之前用过的 IP 分给了别人。等一会儿或重连网络换个 IP。

---

## 说明

本工具只调用门户网页自己也在使用的公开接口，不修改、不绕过学校的认证与计费系统，
也不会共享账号。它自动化的是"你自己本来就要做的操作"。
