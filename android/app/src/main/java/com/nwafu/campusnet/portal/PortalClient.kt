package com.nwafu.campusnet.portal

import com.nwafu.campusnet.crypto.Crypto
import org.json.JSONArray
import org.json.JSONObject
import org.json.JSONTokener
import java.io.IOException
import java.net.HttpURLConnection
import java.net.Proxy
import java.net.URL

/** 门户交互相关的异常基类。 */
open class PortalException(message: String) : Exception(message)

/** 门户根本连不上（多半是不在校园网内）。 */
class PortalUnreachableException(message: String) : PortalException(message)

/** 一次 HTTP 响应。 */
data class HttpResponse(
    val text: String,
    val status: Int?,
    val location: String?,
    val url: String,
    val parsed: Any?
) {
    val isHtml: Boolean get() = text.trimStart().startsWith("<")
}

/** HTTP 传输抽象，便于在单元测试里替换成真实本地桩服务。 */
interface HttpTransport {
    fun get(url: String, timeoutMs: Int, userAgent: String, referer: String): HttpResponse
}

/**
 * 基于 HttpURLConnection 的实现。
 *
 * 刻意显式传 `Proxy.NO_PROXY`：门户在校园网内网，走系统代理只会失败
 * （桌面版同样用 ProxyHandler({}) 绕开）。
 */
class UrlConnectionTransport : HttpTransport {
    override fun get(
        url: String,
        timeoutMs: Int,
        userAgent: String,
        referer: String
    ): HttpResponse {
        val conn = try {
            URL(url).openConnection(Proxy.NO_PROXY) as HttpURLConnection
        } catch (e: Exception) {
            throw PortalUnreachableException(e.message ?: e.javaClass.simpleName)
        }
        try {
            conn.requestMethod = "GET"
            conn.connectTimeout = timeoutMs
            conn.readTimeout = timeoutMs
            conn.instanceFollowRedirects = true
            conn.useCaches = false
            conn.setRequestProperty("User-Agent", userAgent)
            conn.setRequestProperty("Accept", "*/*")
            conn.setRequestProperty("Referer", referer)

            val status = conn.responseCode
            val stream = if (status >= 400) conn.errorStream else conn.inputStream
            val body = stream?.use { it.readBytes() } ?: ByteArray(0)
            val text = String(body, Charsets.UTF_8)
            val location = conn.getHeaderField("Location")
            return HttpResponse(
                text = text,
                status = status,
                location = location,
                url = url,
                parsed = parseJsonp(text)
            )
        } catch (e: PortalUnreachableException) {
            throw e
        } catch (e: IOException) {
            throw PortalUnreachableException(e.message ?: e.javaClass.simpleName)
        } catch (e: Exception) {
            throw PortalUnreachableException(e.message ?: e.javaClass.simpleName)
        } finally {
            conn.disconnect()
        }
    }
}

private val JSONP_RE = Regex("^[A-Za-z_$][\\w$.]*\\s*\\((.*)\\)\\s*;?$", RegexOption.DOT_MATCHES_ALL)

/** 剥掉 JSONP 外壳；不是 JSONP 就返回 null。 */
fun parseJsonp(text: String?): Any? {
    val t = text?.trim().orEmpty()
    if (t.isEmpty()) return null
    val body = when (t[0]) {
        '{', '[' -> t
        else -> JSONP_RE.matchEntire(t)?.groupValues?.get(1) ?: return null
    }
    return try {
        JSONTokener(body).nextValue()
    } catch (e: Exception) {
        null
    }
}

private fun str(raw: JSONObject, key: String): String {
    val v = raw.opt(key) ?: return ""
    if (v == JSONObject.NULL) return ""
    return v.toString().trim()
}

/**
 * 把接口响应归类成结果常量。
 *
 * 判定顺序照搬桌面版（docs/02-portal-protocol.md §3.5）：
 * 真正结果看 ploy_msg / suc_msg，而不是只看 ecode（成功和"已在线"都是 ecode=0）。
 */
fun classify(raw: Any?): String {
    if (raw !is JSONObject) return UNPARSED
    val err = str(raw, "error")
    val res = str(raw, "res")
    val ecode = str(raw, "ecode")
    val suc = str(raw, "suc_msg")
    val ploy = str(raw, "ploy_msg")
    val emsg = str(raw, "error_msg")
    val text = listOf(err, res, ecode, suc, ploy, emsg).joinToString(" ").lowercase()

    if ("sign_error" in text || "chksum" in text || emsg.lowercase() == "timeout") {
        return SIGNATURE_ERROR
    }
    if ("already_online" in text) return ALREADY_ONLINE
    // E2620「已经在线了」是良性的，绝不能当成"在线数已满"——
    // 一旦误判成 FULL，上层就会走"腾位"流程去踢一台设备，
    // 而此刻真正在线的可能就是用户自己的机器（见 D-11）。
    if ("e2620" in text) return ALREADY_ONLINE
    if ("e6526" in text) return ALREADY_ONLINE   // 您的 IP 已经在线，可以直接上网
    if ("e2621" in text || "e6512" in text) return FULL
    if ("not_online" in text) return NOT_ONLINE
    // 深澜的"不在线"有一整族错误码/字样，中文文案里没有 not_online 这个词。
    // 漏掉它们会让"踢一台已经下线的设备"被当成失败（见 D-02）。
    if (listOf("e6503", "e6527", "e6528", "notonlineerror", "youarenotonline")
            .any { it in text }
    ) {
        return NOT_ONLINE
    }
    if (ploy.uppercase().startsWith("E0000")) return SUCCESS
    if (err == "ok" && (ecode == "0" || ecode.isEmpty())) return SUCCESS
    return UNKNOWN
}

/**
 * 在 [classify] 之外先看 HTTP 状态码。
 *
 * 门户前面有反向代理和准入门户，5xx 时经常仍返回一段**看起来像 JSON 的**错误页，
 * 只按响应体分类会把它当成业务结论。这里把 5xx 单独归为 SERVER_ERROR。
 */
fun classifyResponse(resp: HttpResponse): String {
    val status = resp.status
    if (status != null && status >= 500) return SERVER_ERROR
    return classify(resp.parsed)
}

/**
 * 深澜（SRun）校园网门户客户端。
 *
 * 所有方法同步阻塞、带超时；不打印任何东西、不依赖 Android 框架，
 * 因此可以在 JVM 单元测试里直接跑。
 */
class SrunPortalClient(
    baseUrl: String = DEFAULT_BASE_URL,
    private val timeoutMs: Int = 8000,
    private val userAgent: String = DEFAULT_UA,
    private val transport: HttpTransport = UrlConnectionTransport()
) {
    val baseUrl: String = baseUrl.trimEnd('/')

    /** rad_user_info 的限流冷却截止时间（毫秒） */
    @Volatile
    private var rateLimitedUntil: Long = 0L

    // ------------------------------------------------------------------
    // 底层请求
    // ------------------------------------------------------------------

    private fun percentEncode(s: String): String {
        val sb = StringBuilder(s.length * 3)
        for (b in s.toByteArray(Charsets.UTF_8)) {
            val c = b.toInt() and 0xFF
            val ch = c.toChar()
            val safe = (ch in 'A'..'Z') || (ch in 'a'..'z') || (ch in '0'..'9') ||
                    ch == '_' || ch == '.' || ch == '-' || ch == '~' || ch == '/'
            if (safe) {
                sb.append(ch)
            } else {
                sb.append('%')
                sb.append(HEX_UPPER[c ushr 4])
                sb.append(HEX_UPPER[c and 0x0F])
            }
        }
        return sb.toString()
    }

    private fun request(
        path: String,
        params: Map<String, String>? = null,
        timeoutMs: Int? = null
    ): HttpResponse {
        val qs = (params ?: emptyMap())
            .map { (k, v) -> percentEncode(k) + "=" + percentEncode(v) }
            .joinToString("&")
        val url = baseUrl + path + if (qs.isEmpty()) "" else "?$qs"
        return transport.get(
            url = url,
            timeoutMs = timeoutMs ?: this.timeoutMs,
            userAgent = userAgent,
            referer = "$baseUrl/srun_portal_pc?ac_id=1&theme=pro"
        )
    }

    // ------------------------------------------------------------------
    // 门户状态
    // ------------------------------------------------------------------

    /** 门户是否可达（用于判断"是不是在校园网里"）。 */
    fun portalReachable(timeoutMs: Int = 3000): Boolean {
        return try {
            val resp = request("/cgi-bin/rad_user_info", mapOf("callback" to "cb", "_" to ts()), timeoutMs)
            resp.parsed != null
        } catch (e: PortalUnreachableException) {
            false
        }
    }

    fun acDetect(): JSONObject {
        val resp = request("/v1/srun_portal_detect")
        return resp.parsed as? JSONObject ?: JSONObject()
    }

    // ------------------------------------------------------------------
    // Token / 本机 IP
    // ------------------------------------------------------------------

    fun getChallenge(
        username: String = "",
        ip: String = "",
        timeoutMs: Int? = null
    ): Challenge {
        val resp = request(
            "/cgi-bin/get_challenge",
            mapOf("callback" to "cb", "username" to username, "ip" to ip, "_" to ts()),
            timeoutMs
        )
        val data = resp.parsed as? JSONObject ?: JSONObject()
        val token = data.optString("challenge", "")
        if (token.isBlank()) {
            throw PortalException("获取 challenge 失败：${resp.text.trim().take(200)}")
        }
        return Challenge(
            token = token,
            clientIp = data.optString("client_ip", ""),
            expire = data.optString("expire", ""),
            raw = data
        )
    }

    /** 服务端看到的本机 IP（登录参数 ip 的唯一可信来源）。 */
    fun detectIp(username: String = "", timeoutMs: Int? = null): String =
        getChallenge(username = username, timeoutMs = timeoutMs).clientIp

    /** rad_user_info 被限流时也要能拿到，所以走 get_challenge 的 client_ip。 */
    fun localIp(username: String = "", timeoutMs: Int? = null): String =
        detectIp(username = username, timeoutMs = timeoutMs)

    // ------------------------------------------------------------------
    // 状态查询
    // ------------------------------------------------------------------

    fun userInfo(timeoutMs: Int? = null): OnlineStatus {
        val resp = request("/cgi-bin/rad_user_info", mapOf("callback" to "cb", "_" to ts()), timeoutMs)
        val status = resp.status
        val data = resp.parsed as? JSONObject
        // 5xx 时网关常常仍返回一段带 "error":"ok" 的 JSON，直接采信会把
        // "服务端挂了"读成"你在线"（见 D-11）。
        if (status != null && status >= 500) {
            return OnlineStatus(online = false, error = SERVER_ERROR, raw = data ?: JSONObject())
        }
        if (data == null) {
            return OnlineStatus(online = false, error = UNPARSED, raw = JSONObject())
        }
        val online = data.optString("error", "") == "ok"
        return OnlineStatus(online = online, error = data.optString("error", ""), raw = data)
    }

    /** 查询本账号的在线设备列表（**离线状态下同样可用**）。 */
    fun onlineDevices(username: String, password: String?, timeoutMs: Int? = null): List<Device> {
        val resp = request(
            "/v1/srun_portal_online",
            mapOf("user_name" to username, "password" to Crypto.passwordMd5(password)),
            timeoutMs
        )
        val data = resp.parsed as? JSONObject ?: JSONObject()
        if (data.optString("code") != "0") {
            throw PortalException(Errors.messageFor(data) ?: "查询在线设备失败")
        }
        val arr = data.optJSONArray("data") ?: JSONArray()
        val out = ArrayList<Device>(arr.length())
        for (i in 0 until arr.length()) {
            arr.optJSONObject(i)?.let { out.add(Device.fromJson(it)) }
        }
        return out
    }

    // ------------------------------------------------------------------
    // 登录 / 注销 / 踢人
    // ------------------------------------------------------------------

    fun login(
        username: String,
        password: String,
        ip: String? = null,
        acId: String = DEFAULT_AC_ID,
        osName: String = DEFAULT_OS_NAME,
        clientName: String = DEFAULT_CLIENT_NAME,
        timeoutMs: Int? = null
    ): PortalResult {
        var targetIp = ip ?: detectIp(username, timeoutMs)
        val challenge = getChallenge(username = username, ip = targetIp, timeoutMs = timeoutMs)
        val token = challenge.token
        if (challenge.clientIp.isNotBlank()) targetIp = challenge.clientIp
        val hmd5 = Crypto.hmacMd5(password, token)
        val info = Crypto.buildInfo(username, password, targetIp, acId, token)
        val chksum = Crypto.buildChksum(token, username, hmd5, acId, targetIp, 200, 1, info)
        val resp = request(
            "/cgi-bin/srun_portal",
            linkedMapOf(
                "callback" to "cb",
                "action" to "login",
                "username" to username,
                "password" to "{MD5}$hmd5",
                "os" to osName,
                "name" to clientName,
                "double_stack" to "0",
                "chksum" to chksum,
                "info" to info,
                "ac_id" to acId,
                "ip" to targetIp,
                "n" to "200",
                "type" to "1"
            ),
            timeoutMs
        )
        return PortalResult(
            kind = classifyResponse(resp),
            raw = resp.parsed as? JSONObject ?: JSONObject(),
            httpStatus = resp.status,
            ip = targetIp,
            username = username,
            detail = mutableMapOf("token" to token, "chksum" to chksum)
        )
    }

    /**
     * 注销本机（服务端按 账号+IP 定位会话）。
     *
     * 这里**不做**"先查在线状态再决定要不要注销"的前置判断：
     * rad_user_info 可能被限流，那样会误判成离线而什么都不做。
     */
    fun logout(
        username: String,
        ip: String? = null,
        acId: String = DEFAULT_AC_ID,
        timeoutMs: Int? = null
    ): PortalResult {
        val targetIp = ip ?: localIp(username, timeoutMs)
        val resp = request(
            "/cgi-bin/srun_portal",
            linkedMapOf(
                "callback" to "cb",
                "action" to "logout",
                "username" to username,
                "ip" to targetIp,
                "ac_id" to acId
            ),
            timeoutMs
        )
        return PortalResult(
            kind = classifyResponse(resp),
            raw = resp.parsed as? JSONObject ?: JSONObject(),
            httpStatus = resp.status,
            ip = targetIp,
            username = username
        )
    }

    /** 把指定 IP 的设备踢下线（对自己用就等于注销）。 */
    fun kick(
        ip: String,
        username: String,
        unbind: Int = 1,
        timeoutMs: Int? = null
    ): PortalResult {
        val (t, sign) = Crypto.dmSignature(username, ip, unbind)
        val resp = request(
            "/cgi-bin/rad_user_dm",
            linkedMapOf(
                "callback" to "cb",
                "ip" to ip,
                "username" to username,
                "time" to t,
                "unbind" to unbind.toString(),
                "sign" to sign
            ),
            timeoutMs
        )
        return PortalResult(
            kind = classifyResponse(resp),
            raw = resp.parsed as? JSONObject ?: JSONObject(),
            httpStatus = resp.status,
            ip = ip,
            username = username,
            detail = mutableMapOf("time" to t, "sign" to sign)
        )
    }

    /**
     * 把**本机**真正下线，并确认结果。
     *
     * 两种机制的实测差异（见桌面版 docs/03-logout-mechanisms.md）：
     * - `action=logout`：只注销 RADIUS 会话，若本机 MAC 开了免认证会被立刻拉回；
     * - `rad_user_dm`（unbind=1）：连 MAC 绑定一起解除，实测能真正保持离线。
     */
    fun logoutLocal(
        username: String,
        password: String? = null,
        ip: String? = null,
        acId: String = DEFAULT_AC_ID,
        method: String = "dm",
        timeoutMs: Int? = null,
        verifyTimeoutMs: Long = 8000
    ): PortalResult {
        val targetIp = (ip ?: localIp(username, timeoutMs)).trim()
        // dm 接口是按 ip 定向踢人的。拿不到本机 IP 时如果继续发请求，
        // 服务端只会回一条看不懂的失败，反而掩盖了"其实没连上校园网"这个真实原因；
        // 更危险的是，任何"猜一个 IP 兜底"的写法都可能误踢别人（见 D-19）。
        if (targetIp.isEmpty()) {
            return PortalResult(
                kind = UNKNOWN,
                detail = mutableMapOf(
                    "state" to STATE_UNKNOWN,
                    "verified" to false,
                    "reason" to "no_local_ip"
                )
            )
        }
        val res = if (method == "portal") {
            logout(username, ip = targetIp, acId = acId, timeoutMs = timeoutMs)
        } else {
            kick(targetIp, username, unbind = 1, timeoutMs = timeoutMs)
        }
        val (state, _, _) = waitState(
            want = STATE_OFFLINE,
            timeoutMs = verifyTimeoutMs,
            username = username,
            password = password
        )
        res.detail["state"] = state
        res.detail["verified"] = (state == STATE_OFFLINE)
        res.detail["mechanism"] = if (method == "portal") "portal" else "dm"
        if (state == STATE_OFFLINE) {
            res.kind = SUCCESS
        } else if (res.kind == SUCCESS) {
            res.kind = UNKNOWN
            res.detail["still_online"] = true
        }
        return res
    }

    // ------------------------------------------------------------------
    // 状态判定与轮询
    // ------------------------------------------------------------------

    /**
     * 三态判定本机状态。
     *
     * 为什么要三态：`rad_user_info` 在请求过密时会返回 `speed_limit_error`，
     * 它**不代表离线**。把"查不到"当成离线，会导致明明登录成功了却报告失败。
     *
     * 另外这里自己做了限流冷却：一旦撞到 `speed_limit_error`，接下来 60 秒内
     * 不再请求 `rad_user_info`，直接用设备列表判定——否则轮询本身会让限流
     * 一直续期，永远等不到解除。
     */
    fun localState(
        username: String? = null,
        password: String? = null,
        timeoutMs: Int? = null
    ): Triple<String, OnlineStatus, List<Device>> {
        val hasCreds = !username.isNullOrBlank() && !password.isNullOrEmpty()
        if (System.currentTimeMillis() < rateLimitedUntil && hasCreds) {
            return stateFromDevices(username!!, password!!, null, timeoutMs)
        }
        val status = try {
            userInfo(timeoutMs)
        } catch (e: PortalUnreachableException) {
            return Triple(
                STATE_UNKNOWN,
                OnlineStatus(online = false, error = NETWORK_ERROR),
                emptyList()
            )
        }
        if (status.state == STATE_ONLINE || status.state == STATE_OFFLINE) {
            return Triple(status.state, status, emptyList())
        }

        if (status.rateLimited) {
            rateLimitedUntil = System.currentTimeMillis() + 60_000
            if (hasCreds) {
                return stateFromDevices(username!!, password!!, status, timeoutMs)
            }
        }

        val myIp = status.ip
        if (hasCreds && myIp != null) {
            val devices = try {
                onlineDevices(username!!, password, timeoutMs)
            } catch (e: PortalException) {
                return Triple(STATE_UNKNOWN, status, emptyList())
            }
            val state = if (devices.any { it.ip == myIp }) STATE_ONLINE else STATE_OFFLINE
            return Triple(state, status, devices)
        }
        return Triple(STATE_UNKNOWN, status, emptyList())
    }

    /** 用在线设备列表判定本机状态（设备列表接口不受 rad_user_info 限流影响）。 */
    private fun stateFromDevices(
        username: String,
        password: String,
        status: OnlineStatus?,
        timeoutMs: Int?
    ): Triple<String, OnlineStatus, List<Device>> {
        val devices = try {
            onlineDevices(username, password, timeoutMs)
        } catch (e: PortalException) {
            return Triple(
                STATE_UNKNOWN,
                status ?: OnlineStatus(online = false, error = "unknown"),
                emptyList()
            )
        }
        var myIp = status?.ip
        if (myIp.isNullOrBlank()) {
            myIp = try {
                localIp(username, timeoutMs)
            } catch (e: PortalException) {
                return Triple(
                    STATE_UNKNOWN,
                    status ?: OnlineStatus(online = false, error = "unknown"),
                    devices
                )
            }
        }
        if (myIp.isNullOrBlank()) {
            return Triple(
                STATE_UNKNOWN,
                status ?: OnlineStatus(online = false, error = "unknown"),
                devices
            )
        }
        val state = if (devices.any { it.ip == myIp }) STATE_ONLINE else STATE_OFFLINE
        // 打上标记：这是合成状态，不是服务端原话，userName/mac 必然为空。
        // 上层不能把它当成"确认在线且是本账号"，否则会误报 already_online（见 D-03/D-05）。
        val raw = JSONObject(status?.raw?.toString() ?: "{}")
        if (!raw.has("online_ip")) raw.put("online_ip", myIp)
        raw.put("source", "device_list")
        raw.put("synthetic", true)
        val merged = OnlineStatus(
            online = state == STATE_ONLINE,
            error = status?.error ?: if (state == STATE_ONLINE) "ok" else "not_online_error",
            raw = raw
        )
        return Triple(state, merged, devices)
    }

    /** 轮询直到本机状态变成 [want]。 */
    fun waitState(
        want: String,
        timeoutMs: Long = 15_000,
        intervalMs: Long = 2000,
        username: String? = null,
        password: String? = null
    ): Triple<String, OnlineStatus, List<Device>> {
        val deadline = System.currentTimeMillis() + timeoutMs
        var delay = intervalMs
        while (true) {
            val result = localState(username, password)
            val state = result.first
            val status = result.second
            if (state == want) return result
            if (System.currentTimeMillis() >= deadline) return result
            try {
                Thread.sleep(delay)
            } catch (e: InterruptedException) {
                Thread.currentThread().interrupt()
                return result
            }
            delay = if (status.rateLimited) 10_000 else intervalMs
        }
    }

    // ------------------------------------------------------------------
    // 登录 + 确认（推荐入口）
    // ------------------------------------------------------------------

    /**
     * 登录并轮询确认会话真的建立了。
     *
     * 实测发现，注销后紧接着从同一个 IP 再登录时，服务端会**把请求挂起约 60 秒**
     * （对应 E6504「注销成功，请等1分钟后登录」），期间 HTTP 连接一直不返回。
     * 客户端若用较短超时就会超时，但登录最终仍然成功——此时若把超时当成失败
     * 并提示用户，就是误报。因此本方法把"响应"和"实际结果"分开。
     */
    fun loginAndConfirm(
        username: String,
        password: String,
        ip: String? = null,
        acId: String = DEFAULT_AC_ID,
        loginTimeoutMs: Int = 30_000,
        confirmTimeoutMs: Long = 90_000,
        osName: String = DEFAULT_OS_NAME,
        clientName: String = DEFAULT_CLIENT_NAME,
        progress: ((String) -> Unit)? = null
    ): PortalResult {
        val result = try {
            login(username, password, ip = ip, acId = acId,
                osName = osName, clientName = clientName, timeoutMs = loginTimeoutMs)
        } catch (e: PortalUnreachableException) {
            PortalResult(kind = NETWORK_ERROR, detail = mutableMapOf("exception" to e.message))
        }

        // 明确的业务失败（密码错、签名错、在线数满）不需要等
        if (result.raw.length() > 0 && result.kind in setOf(FULL, SIGNATURE_ERROR, UNKNOWN)) {
            result.detail["confirmed"] = false
            return result
        }

        progress?.invoke("已发出登录请求（${result.kind}），等待服务端确认…")
        val (state, status, devices) = waitState(
            want = STATE_ONLINE,
            timeoutMs = confirmTimeoutMs,
            intervalMs = 2000,
            username = username,
            password = password
        )
        result.detail["state"] = state
        result.detail["status"] = status
        result.detail["devices"] = devices
        result.detail["confirmed"] = (state == STATE_ONLINE)
        if (state == STATE_ONLINE) {
            // 会话已经建立，之前撞上的限流冷却必须立刻作废（见 D-05）。
            rateLimitedUntil = 0L
            if (result.kind in setOf(NETWORK_ERROR, UNKNOWN, SERVER_ERROR)) {
                result.kind = SUCCESS
            }
            if (ip == null && status.ip != null) result.ip = status.ip
        } else if (state == STATE_OFFLINE && result.kind in setOf(SUCCESS, ALREADY_ONLINE)) {
            // 服务端说成功，但没确认到在线——以实际状态为准
            result.kind = UNKNOWN
            result.detail["inconsistent"] = true
        } else if (result.kind in setOf(SUCCESS, ALREADY_ONLINE)) {
            // 状态未知（多半是被限流）：请求本身成功，但无法确认，如实标注
            result.detail["unconfirmed"] = true
        }
        return result
    }

    private fun ts(): String = System.currentTimeMillis().toString()

    companion object {
        const val DEFAULT_BASE_URL = "http://172.26.8.11"
        const val DEFAULT_AC_ID = "1"
        const val DEFAULT_OS_NAME = "Android"
        const val DEFAULT_CLIENT_NAME = "Android"
        const val DEFAULT_UA =
            "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 " +
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"

        private val HEX_UPPER = "0123456789ABCDEF".toCharArray()
    }
}
