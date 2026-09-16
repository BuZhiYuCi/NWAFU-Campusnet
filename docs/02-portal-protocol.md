# 深澜（SRun）门户 172.26.8.11 接口与算法分析

本文所有结论来自对门户前端 JS 的静态阅读 + 对服务器的只读 GET 实测。
抓取到的原始文件（可随时从门户重新下载，注意：带 `?v=xxx` 查询串会返回空内容，去掉即可）：

```
http://172.26.8.11/static/themes/pro/js/Portal.js
http://172.26.8.11/static/themes/pro/js/Utils.js
http://172.26.8.11/static/themes/pro/js/main.js
http://172.26.8.11/static/themes/pro/js/creater.js
http://172.26.8.11/static/themes/pro/js/lang.js
http://172.26.8.11/static/themes/pro/lib/all.min.js
```

---

## 1. 接口清单

基地址：http://172.26.8.11
服务器：SRun portal server golang version，sysver 1.01.20210607

| 用途 | 方法 | 路径 | 备注 |
| --- | --- | --- | --- |
| 获取 Token | GET/JSONP | /cgi-bin/get_challenge | 必须带 callback，否则返回纯文本 ok |
| 登录 / 注销 | GET/JSONP | /cgi-bin/srun_portal | action=login / action=logout |
| 在线信息 | GET/JSONP | /cgi-bin/rad_user_info | 不带参数时按请求来源 IP 查询 |
| 在线设备列表 | GET | /v1/srun_portal_online | 需要账号 + md5(密码) |
| 指定设备下线（DM） | GET/JSONP | /cgi-bin/rad_user_dm | 需要签名 |
| AC 多重定向探测 | GET | /v1/srun_portal_detect | 返回 Pc/Mobile/Redirect/CloseLogout |

其它已知但一期不用的接口：/v1/srun_portal_sms、/v1/srun_portal_sso、/v1/srun_wechat_code、
/v1/srun_portal_sign、/v2/srun_portal_message、/v1/srun_portal_log、/v1/srun_portal_agree_new、
/v1/srun_portal_agree_bind、/v1/srun_portal_agrees、/v1/srun_portal_password_code、
/v1/srun_portal_password_reset、/v1/srun_portal_password_forget、/v1/precheck_account。

---

## 2. 获取 Token

请求：

```
GET /cgi-bin/get_challenge?callback=cb&username=<username>&ip=<本机IP>&_=<unix秒>
```

实测响应：

```json
cb({"challenge":"c436b50ea8065baf5e938b4a5c334cc374af9faf952a60aa27f31e647c402d12",
    "client_ip":"10.128.96.98","ecode":0,"error":"ok","error_msg":"",
    "expire":"60","online_ip":"10.128.96.98","res":"ok",
    "srun_ver":"SRunCGIAuthIntfSvr V1.18 B20210607","st":1789486136})
```

要点：

- challenge 即后续所有加密用的 token，**有效期 60 秒**。
- 服务端**不校验 username**（用不存在的号码也能拿到 challenge），只绑定 client_ip。
- client_ip 是服务端看到的请求来源 IP，**应作为登录参数 ip 的唯一来源**（不要盲信网卡枚举结果）。
- **callback 是必需的**，这一点贯穿所有 cgi-bin 接口：
  - `/cgi-bin/get_challenge` 不带 callback 时只返回纯文本 `ok`，拿不到 token；
  - `/cgi-bin/srun_portal` 与 `/cgi-bin/rad_user_dm` 不带 callback 时，服务端会返回一个
    **HTML 调试表单**（`text/html`，正文里还会把服务端解析到的参数原样打印出来），
    请求根本不会被当成认证请求处理。实测证据见 `docs/phase0-report.md`。
- 返回体是 JSONP：外层是 callback 名 + 括号，解析时需剥壳。

---

## 3. 登录 /cgi-bin/srun_portal

### 3.1 参数

| 参数 | 值 | 说明 |
| --- | --- | --- |
| action | login | |
| username | **<账号>，不带域名后缀** | 实测确认：`17782817252` 直接登录成功；不需要 `@yx-s-student` |
| password | {MD5}<hmd5> | 见 3.2 |
| os | 例 Windows 10 | 设备系统标识 |
| name | 例 Windows | 平台标识 |
| double_stack | 0 | 门户 DoubleStackPC=false，固定 0 |
| chksum | <sha1> | 见 3.3 |
| info | {SRBX1}<base64> | 见 3.4 |
| ac_id | **1** | 实测确认可用（登录成功） |
| ip | <本机IP> | 必须等于服务端看到的来源 IP，否则 E6514 |
| n | 200 | 固定 |
| type | 1 | 固定 |

登录请求还必须带 **`callback=<任意函数名>`**，否则服务端返回 HTML 调试表单（见 §2）。

实测确认可用的完整参数组合（`docs/phase0-report.md` 有原始请求与响应）：

```
callback=cb&action=login&username=17782817252&password={MD5}<hmd5>
&os=Windows 10&name=Windows&double_stack=0&chksum=<sha1>&info={SRBX1}<base64>
&ac_id=1&ip=<本机IP>&n=200&type=1
```

### 3.2 hmd5

官方 JS：`var hmd5 = md5(password, token);`

其中 md5 来自 lib/all.min.js 里的 `//md5 v2.10.0` 库，导出函数签名还原后为：

```js
function A(n, t, r) { return t ? (r ? s(t, n) : C(t, n)) : (r ? m(n) : p(n)); }
```

- 单参数：p(n) = 普通十六进制 MD5 —— 这一点已用 /v1/srun_portal_online 实测通过。
- 双参数：C(t, n) = HMAC（内部函数 l() 使用 0x36363636 / 0x5B6B6B6B，即标准 ipad/opad），
  且 key 取第二个参数、message 取第一个参数。

因此：

```python
hmd5 = hmac.new(token.encode(), password.encode(), hashlib.md5).hexdigest()
# 即 HMAC-MD5(key = token, message = password)
```

注意：网上大量深澜登录脚本写的是 md5(password + token)，那是**老版本 PHP 门户**的算法。
本门户的 JS 明确调用双参数 md5(password, token)，语义为 HMAC-MD5。

**实测结论（Phase 0，已确认）**：HMAC-MD5 正确。
验证方式有两层，互相印证：

1. 用 Node 加载门户的官方 js-md5 库，对 5 组向量计算 `md5(password, token)`，
   结果与 `crypto.createHmac('md5', token).update(password)` **逐字节相同**，
   且与 `md5(password + token)` 不同（见 `tests/vectors.json` 的 `hmac_check_match`）。
2. 用 HMAC 写法向真实服务器发起登录，服务端通过校验并返回业务结果
   （而不是签名/解密错误），见 §3.5。

### 3.3 chksum

```js
var str = token + username;
str += token + hmd5;
str += token + ac_id;
str += token + ip;
str += token + n;        // 200
str += token + type;     // 1
str += token + i;        // info 字段
chksum = sha1(str);      // 小写十六进制
```

注意 ac_id、n、type 是数字，与字符串拼接时按 JS 隐式转换规则取值（"1"、"200"、"1"）。

### 3.4 info：自定义 Base64 + XXTEA

明文结构：

```json
{"username":"<账号>","password":"<明文密码>","ip":"<本机IP>","acid":"1","enc_ver":"srun_bx1"}
```

加密步骤（Portal.js 中 _encodeUserInfo）：

1. JSON.stringify(info) 得到字符串；
2. 用 **token 作为密钥**做 XXTEA 加密；
3. 用**自定义字母表**的 Base64 编码；
4. 前缀 {SRBX1}。

自定义 Base64 字母表（JS 中 setAlpha 的参数，逐字符替换标准表）：

```
LVoJPiCN2R8G90yg+hmFHuacZ1OWMnrsSTXkYpUq/3dlbfKwv6xztjI7DeBE45QA
```

标准表：

```
ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/
```

即按索引一一对应替换（等价于对标准 base64 输出做 str.translate 映射，padding '=' 不变）。

XXTEA 细节（JS 里的常量经还原后都是标准值）：

- c = 0x86014019 | 0x183639A0 → **0x9E3779B9**（标准 delta）
- 掩码 0x8CE0D9BF | 0x731F2640 → **0xFFFFFFFF**
- 掩码 0xEFB8D130 | 0x10472ECF → **0xFFFFFFFF**
- s(str, include_length)：字符串 → 32 位大端字数组，include_length=true 时追加长度
- 密钥 s(key, false)，长度不足 4 补齐到 4

实现方式：**按 JS 逐行移植**，并用官方 JS 生成测试向量做回归测试（见 Phase 1 验收）。

### 3.5 登录返回

实测的三种典型响应（全部 `ecode: 0` + `error: "ok"`，**真正结果要看 `ploy_msg` / `suc_msg`**）：

本机已在线时（算法正确、凭据正确，但 IP 已被自己占用）：

```json
cb({"ServerFlag":0,"ServicesIntfServerIP":"172.26.8.13","ServicesIntfServerPort":"8001",
    "access_token":"...","client_ip":"10.128.96.98","ecode":0,"error":"ok","error_msg":"",
    "online_ip":"10.128.96.98","res":"ok","suc_msg":"ip_already_online_error",
    "srun_ver":"SRunCGIAuthIntfSvr V1.18 B20210607","username":"17782817252"})
```

真实登录成功时（离线状态下发起）：

```json
cb({"...":"...","client_ip":"10.128.96.98","ecode":0,"error":"ok","error_msg":"",
    "online_ip":"10.128.96.98","ploy_msg":"E0000: Login is successful", ...})
```

判定规则（已实测确定）：

| 判定 | 依据 |
| --- | --- |
| 登录成功 | `ploy_msg` 以 `E0000` 开头 |
| 本机已在线 | `suc_msg == "ip_already_online_error"` |
| 在线数已满 | `ecode` / `ploy_msg` 出现 E2620 / E2621 / E6512 |
| 签名或加密错误 | `error` 或 `res` 为 `sign_error` / `chksum` 相关 |

需要注意的失败分支：

| 返回 | 含义 | 处理 |
| --- | --- | --- |
| ecode == "E2620" | 已经在线了 | 本机 IP 已占用 |
| ecode == "E2621" | 已经达到授权人数 | **触发腾位流程** |
| ecode == "E6512" | 在线用户已满 | **触发腾位流程** |
| error_msg == "ip_already_online_error" | 本机 IP 被其它账号占用 | 提示用户 |
| error_msg == "not_online_error" / "no_response_data_error" / "RD000" | 门户会转去查日志 | 记录并提示 |
| error_msg == "user_must_modify_password" | 提示去自助服务改密码 | 直接提示 |
| E2532 | 两次认证间隔太短 | 冷却 10s 重试 |
| E2533 | 密码错误次数超限 | 停止并提示 5 分钟后再试 |

### 3.6 安全的算法验证方法（不中断网络）

开发阶段需要验证 hmd5 / info / chksum 三者的实现是否正确，但真实的"注销 → 登录"会中断本机网络。
利用服务端的校验顺序，可以在**不中断网络**的前提下先把算法验证掉：

本机已经在线时，直接发一次完整的 login 请求，观察返回：

| 返回 | 含义 |
| --- | --- |
| 签名/参数/解密类错误（如 SignError、chksum 相关、参数不合法） | 算法实现错误 → 立即修正重试 |
| 已在线类错误（E2620 / E6526 / ip_already_online_error） | **签名与加密已被服务端接受**，算法正确 |

原理：服务端按"校验签名与加密参数 → 校验凭据 → 检查在线状态"的顺序处理，
算法错误会在前两步就被拒绝，只有算法正确时才会走到"已在线"这一判断。

因此 Phase 0 的建议顺序是：先在**在线状态**下用这个方法把算法钉死，
再做一次真实的"DM 注销本机 → 重新登录"闭环（这一步必然会短暂断网）。

---

## 4. 在线信息 /cgi-bin/rad_user_info

```
GET /cgi-bin/rad_user_info?callback=cb        # 不带参数：按来源 IP 查
```

实测（带 callback）返回完整 JSON，关键字段：

```json
{"user_name":"17782817252","online_ip":"10.128.96.98",
 "online_ip6":"2001:250:1002:6100::dd5c",
 "user_mac":"08:8f:c3:e2:37:57","domain":"yx-s-student",
 "online_device_total":"2","add_time":1789216539,
 "bytes_in":30338832749,"bytes_out":3168452827,
 "all_bytes":54530823273,"sum_bytes":22214615814,"sum_seconds":364609,
 "billing_name":"中国电信校园用户","products_name":"中国电信校园29套餐",
 "keepalive_time":1789486178,"error":"ok"}
```

不带 callback 时返回逗号分隔的裸串（第 9 个字段为 online_ip）：

```
17782817252,1789216539,1789486085,30338832749,3168452827,0,22214615814,364609,10.128.96.98,0,,...
```

用途：判断本机是否在线（比对 online_ip 与本机 IP）、读取已用流量/时长/在线设备总数。

**实测结论（Phase 0 / 0.6，已确认）**：离线状态下返回

```json
cb({"client_ip":"10.128.96.98","ecode":0,"error":"not_online_error","error_msg":"",
    "online_ip":"10.128.96.98","res":"not_online_error",
    "srun_ver":"SRunCGIAuthIntfSvr V1.18 B20210607","st":1789488190})
```

因此统一判定条件为：`error == "ok"` → 在线；`error == "not_online_error"` → 离线。
（注意离线的响应里会多出 `st` 字段，在线响应里没有。）

**重要坑点**：刚登录成功后的极短时间内，rad_user_info 可能仍返回上一次的**陈旧/缓存响应**
（实测：重新登录成功后立刻查询，仍返回 `not_online_error` 且 `st` 与注销时刻完全相同，
但设备列表里新会话已经建立）。因此实现中**必须轮询确认**（间隔 1 秒、最多 5 次），
不能只查一次就下结论。

---

## 5. 在线设备列表 /v1/srun_portal_online

```
GET /v1/srun_portal_online?user_name=<账号>&password=<md5(明文密码)>
```

实测响应：

```json
{"code":0,"message":"Success","data":[
  {"add_time":"2026-09-12 20:35:39","client_type":"1","ip":"10.128.96.98",
   "os_name":"Windows 10","user_name":"17782817252"},
  {"add_time":"2026-09-12 21:50:49","client_type":"1","ip":"10.111.147.127",
   "os_name":"Windows 10","user_name":"17782817252"}
]}
```

要点：

- 密码以**明文 MD5 的十六进制**形式放在 URL 里（门户自身设计），因此只在校园网内调用、不写日志。
- 返回项**没有主机名 / MAC**，只有 IP + 系统 + 上线时间。IP 由 DHCP 分配、会变化。
- client_type 含义（取自 lang.js）：0 无法判断、1 PC、2 移动设备或其他、3 PC 客户端、
  4 移动客户端、5 从 IP 表加载（免认证）、6 MAC 认证、7 小程序直接认证、8 小程序扫码认证、
  9 微信认证、10 LDAP、11 钉钉认证。
- add_time 是服务端本地时间字符串（格式 YYYY-MM-DD HH:MM:SS），可用于 oldest 策略排序。
- **实测结论（Phase 0 / 0.7，已确认）：设备离线时依然可以调用该接口。**
  离线状态下查询，返回的列表正确地少掉了本机那条会话（只剩另一台设备）。
  这一点直接决定"新设备满员时自助腾位"完全可行：
  离线设备 → 查列表 → 踢掉旧会话 → 自己登录，整条链路不需要先上网。

---

## 6. 指定设备下线 /cgi-bin/rad_user_dm

官方 JS（Portal.js 中的 _logoutDm）：

```js
var time = Date.parse(new Date()) / 1000;   // 秒 + 毫秒小数，例如 1789486192.345
var unbind = 1;
params = {
  ip: <目标设备IP>,
  username: <账号>,
  time: time,
  unbind: unbind,
  sign: sha1(time + username + ip + unbind + time)   // 注意 time 出现两次
};
GET /cgi-bin/rad_user_dm?ip=..&username=..&time=..&unbind=..&sign=..
```

要点：

- sign 拼串顺序：time + username + ip + unbind + time。
- username 用**裸账号**（不带 `@域名`），与登录参数不同——这是官方 JS 里
  `_logoutDm` 用 `userInfo.username` 而登录用 `username + domain` 的区别。
- unbind = 1 表示强制解绑/下线。
- 成功后门户提示 LogoutOK（lang.js：DM下线成功）。
- **实测结论（Phase 0 / 0.5，已确认）：`time` 必须是整数秒。**
  传带毫秒的小数（如 `1789488140.489`）服务端直接返回
  `{"ecode":0,"error":"sign_error","res":"sign_error"}`；
  传整数秒（如 `1789488190`）立即返回 `{"ecode":0,"error":"ok","res":"ok"}` 并成功注销。

  原因在官方 JS 的一个隐蔽行为：`Date.parse(new Date())` 中的 `new Date()` 会先被转换成字符串，
  而该字符串只精确到秒，因此 `Date.parse(...)/1000` 得到的是**整数秒**而不是带毫秒的小数。
  门户口诀：不要照抄字面，要看 JS 的实际求值结果。
- 该接口同样**必须带 `callback`**，否则返回 HTML 调试表单。
- 误差超过 2 小时会被服务端拒绝（E6522）。
- 这一接口是"踢任意一台在线设备"的唯一手段，也是腾位流程的关键。
- 该接口与登录接口同源，官方 JS 从登录页调用它，说明离线设备也能调用。

实测确认的完整请求形态：

```
callback=cb&ip=<目标IP>&username=<裸账号>&time=<整数秒>&unbind=1
&sign=sha1("<整数秒><裸账号><目标IP>1<整数秒>")
```

### 6.1 批量下线

接口本身一次只能注销一个 IP。批量操作由客户端串行循环完成：

```
for ip in 用户勾选的设备:
    调用 rad_user_dm(ip)
    记录结果（成功 / 失败原因）
    sleep(batch_kick_interval_ms，默认 800ms)
刷新一次在线设备列表，确认名额已释放
```

安全性说明：注销与踢人接口都是**按 账号 + IP 双重匹配**定位会话的
（`username` 与 `ip` 同时作为参数和签名的组成），因此即使某个 IP 后来被 DHCP
分给了别人，也不会误踢其它账号的会话——最坏情况是返回"当前设备不在线"。
这一点决定了"批量下线"不会造成误伤，但仍建议每次操作后刷新列表确认结果。

### 6.2 与"断开网络"的区别

`rad_user_dm` / `action=logout` 是**通知认证服务器释放在线会话**；
禁用网卡、断开 WiFi、关机都只是让客户端不再发包，服务端的会话会继续保留
（实测：2026-09-12 建立的会话到 2026-09-15 仍在）。这是本工具存在的核心原因。

---

## 7. 注销（本机）/cgi-bin/srun_portal

```js
params = { action: 'logout', username: <账号>, ip: <本机IP>, ac_id: <ac_id> };
```

- 注销成功后 rad_user_info 会报未在线。
- E6504：注销成功，请等 1 分钟后登录（服务端有冷却，实现时需容错）。
- 门户的 _logoutNormal 会串行发送请求并轮询等待结果，实现时可简化：发一次请求 + 轮询确认。

---

## 8. 门户配置常量（来自页面 CONFIG 与 creater.js）

```json
{
  "page": "account",
  "ip": "10.128.96.98",
  "nas": "", "mac": "", "url": "", "lang": "zh-CN", "isIPV6": false,
  "portal": {
    "AuthIP": "", "AuthIP6": "",
    "ServiceIP": "https://service.nwafu.edu.cn",
    "DoubleStackPC": false, "DoubleStackMobile": false,
    "AuthMode": false, "CloseLogout": false, "MacAuth": false,
    "RedirectUrl": true, "OtherPCStack": "IPV4", "OtherMobileStack": "IPV4",
    "MsgApi": "new", "PublicSuccessPages": false, "TrafficCarry": 1000,
    "UserAgreeSwitch": false, "DialSwitch": false
  },
  "onlineInfo": ["username","usedFlow","usedTime","balance","ipv4"]
}
```

- 自助服务地址：https://service.nwafu.edu.cn （用户手动处理绑定/改密码时的入口）。
- UserAgreeSwitch: false → 无需处理"用户协议"前置流程。
- TrafficCarry: 1000 → 流量按 1000 进位（仅显示用）。
- MacAuth: false → 本次登录走普通账号认证，不走 MAC 认证分支。
- 页面上不存在 #domain 下拉框 → 门户 JS 取到的 domain 为空串（除非 info 接口回填）。

---

## 9. 错误码表（节选，完整表见门户 lang.js 的 translate["zh-CN"]）

| 码 | 中文含义 | 本程序处理 |
| --- | --- | --- |
| E0000 | 登录成功 | 成功 |
| E2532 | 两次认证间隔太短，请等 10 秒 | 冷却重试 |
| E2533 | 密码错误次数超限，请 5 分钟后重试 | 熔断，停止 |
| E2536 | 授权已过期 | 提示 |
| E2553 | 帐号或密码错误 | 熔断计数 |
| E2611 | 使用的设备非账号绑定设备 | 引导去自助服务 |
| E2614 | MAC 地址绑定错误 | 引导去自助服务 |
| E2620 | 已经在线了 | 提示/幂等 |
| E2621 | 已经达到授权人数 | **触发腾位** |
| E6512 | 在线用户已满，请稍后再试 | **触发腾位** |
| E6514 | IP 与认证地址不符（可能经过小路由器） | 提示网络结构问题 |
| E6516 / E6517 | 流量/时长已用尽 | 提示 |
| E6522 | 客户端时间不正确 | 校时后重试 |
| E6526 | 您的 IP 已经在线，可直接上网 | 视为已在线 |
| E6527 | 当前设备不在线 | 下线流程的正常结果 |
| E6528 | 已被服务器强制下线 | 提示 |
| LogoutOK | DM 下线成功 | 踢人成功 |
| SignError | 签名错误 | 实现 bug，需修 |
| ChallengeExpireError | Token 过期 | 重新取 token 重试一次 |
| UserMustModifyPassword | 密码过简单或长期未改 | 引导去自助服务 |

完整 zh-CN 映射表可直接从门户 lang.js 的 translate["zh-CN"] 移植到 errors.py
（该表同时包含 E2xxx/E3000/E4000/E6xxx 等全部服务端错误码，约 200 条）。

---

## 10. Phase 0 实测结论（全部结清）

| 编号 | 未知项 | 实测结论 |
| --- | --- | --- |
| 0.1 | 登录 username 是否带 @yx-s-student | **不需要**，裸账号直接成功 |
| 0.2 | hmd5 是 HMAC-MD5 还是 MD5 拼接 | **HMAC-MD5(key=token, msg=password)** |
| 0.3 | XXTEA / 自定义 Base64 移植正确性 | **正确**（5 组向量与官方 JS 完全一致 + 真实登录成功） |
| 0.4 | ac_id 取值 | **1** |
| 0.5 | DM 下线 time 的精度 | **整数秒**；带小数会被拒为 sign_error |
| 0.6 | 离线时 rad_user_info 的返回形态 | `error/res = "not_online_error"`（且带 `st` 字段） |
| 0.7 | 离线时在线设备接口是否可用 | **可用**，自助腾位链路成立 |
| 0.8 | 同一 IP 会话残留时再登录的行为 | 返回 `ecode=0 + suc_msg=ip_already_online_error`，不报错 |

额外发现（原计划外，但对实现很关键）：

| 发现 | 说明 |
| --- | --- |
| callback 必需 | `/cgi-bin/srun_portal`、`/cgi-bin/rad_user_dm` 不带 callback 会返回 HTML 调试表单 |
| 结果字段是 ploy_msg | 登录成功的标志是 `ploy_msg: "E0000: Login is successful"`，不是 `suc_msg` |
| rad_user_info 会短暂陈旧 | 登录成功后立即查询可能仍返回离线，必须轮询确认 |
| logout 与 DM 的区别 | `action=logout` 只能注销自己；`rad_user_dm` 可注销任意 IP（含自己） |

原始证据见 `docs/phase0-report.md`；加密向量见 `tests/vectors.json`。

---

## 11. 复现这次分析的命令（只读，PowerShell）

```powershell
# 1. 门户存活与跳转
Invoke-WebRequest http://172.26.8.11/ -MaximumRedirection 0 -UseBasicParsing

# 2. 登录页（含 CONFIG）
Invoke-WebRequest 'http://172.26.8.11/srun_portal_pc?ac_id=1&theme=pro' -UseBasicParsing

# 3. 拿 token（注意必须带 callback）
Invoke-WebRequest 'http://172.26.8.11/cgi-bin/get_challenge?callback=cb&username=17782817252&ip=<本机IP>' -UseBasicParsing

# 4. 本机在线信息
Invoke-WebRequest 'http://172.26.8.11/cgi-bin/rad_user_info?callback=cb' -UseBasicParsing

# 5. 在线设备列表（password 为 md5(明文密码) 的十六进制）
Invoke-WebRequest 'http://172.26.8.11/v1/srun_portal_online?user_name=17782817252&password=<md5>' -UseBasicParsing

# 6. 前端脚本（注意：加 ?v=xxx 会返回空内容）
Invoke-WebRequest 'http://172.26.8.11/static/themes/pro/js/Portal.js' -UseBasicParsing
```

---

## 12. 客户端实现的三条硬性约定

这三条都是 Phase 0/1 实测踩出来的，写在这里避免以后重犯。

### 12.1 所有 cgi-bin 接口都必须带 `callback`

不带 callback 时：

- `get_challenge` 返回纯文本 `ok`，拿不到 token；
- `srun_portal`（含 login / logout）与 `rad_user_dm` 返回 **HTML 调试表单**，
  请求根本不会被当作认证请求处理，而且响应是 `text/html` 而不是 `application/json`。

判断依据：响应正文是否以 `<` 开头，或者 `parse_jsonp()` 是否返回 None。

### 12.2 登录结果必须以"轮询确认到的状态"为准，不能只看响应

实测发现：注销后紧接着从**同一个 IP** 再登录时，服务端会**把请求挂起约 60 秒**
（对应 E6504「注销成功，请等1分钟后登录」），期间 HTTP 连接一直不返回。
客户端若用较短的超时（8 秒）就会超时，但登录**最终仍然成功**——
实测中会话的上线时间戳正好是注销后 61 秒。

同一操作在另外两次实测中又是 1~2 秒就返回 `suc_msg: login_ok`，说明这是服务端竞态，
不是稳定的固定延时。

因此客户端的做法是（见 `portal.SrunPortalClient.login_and_confirm`）：

1. 发出登录请求，给一个较宽的超时（默认 30 秒）；
2. 无论响应是成功、超时还是无法解析，**都轮询 `rad_user_info` 确认是否真的上线**；
3. 以轮询结果作为最终结论；响应超时但会话已建立时，按成功处理。

反之，如果响应说成功但轮询一直查不到在线，也要判为失败并提示用户。

登录成功的两种响应特征（都已实测到）：

| 字段 | 值 |
| --- | --- |
| `ploy_msg` | `E0000: Login is successful.` |
| `suc_msg` | `login_ok` |

### 12.3 注销/踢人之后必须轮询，不能只查一次

刚完成状态变更的极短时间内，`rad_user_info` 可能仍返回**上一次的陈旧响应**
（实测：重新登录成功后立刻查询仍返回 `not_online_error`，且 `st` 与注销时刻完全相同）。

统一做法：间隔 1 秒轮询，最多 15 秒，以状态真正翻转为准。
