package com.nwafu.campusnet.portal

import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

// ---------------------------------------------------------------------------
// 接口调用结果类型（与桌面版 models.py 一一对应）
// ---------------------------------------------------------------------------

const val SUCCESS = "success"                  // 操作成功
const val ALREADY_ONLINE = "already_online"    // 本机 IP 已在线
const val FULL = "full"                        // 在线数已满
const val NOT_ONLINE = "not_online"            // 当前不在线
const val SIGNATURE_ERROR = "signature_error"  // 签名/加密被拒
const val UNPARSED = "unparsed"                // 响应无法解析（多半被准入门户拦截）
const val UNKNOWN = "unknown"                  // 其它业务错误
const val NETWORK_ERROR = "network_error"      // 请求根本没发出去
const val SERVER_ERROR = "server_error"        // 服务端 5xx，不是业务结论

// ---------------------------------------------------------------------------
// 本机在线状态三态
// ---------------------------------------------------------------------------

const val STATE_ONLINE = "online"
const val STATE_OFFLINE = "offline"
const val STATE_UNKNOWN = "unknown"

/** 服务端限流时返回的错误，遇到它要退避而不是当成"离线" */
val RATE_LIMIT_ERRORS = setOf("speed_limit_error")

/** 明确表示"当前没有会话"的错误 */
val OFFLINE_ERRORS = setOf("not_online_error")

private val KIND_TEXT = mapOf(
    SUCCESS to "操作成功",
    ALREADY_ONLINE to "本机已经在线",
    FULL to "在线设备数已达上限",
    NOT_ONLINE to "当前设备不在线",
    SIGNATURE_ERROR to "签名校验失败",
    UNPARSED to "服务端返回无法解析（可能不在校园网内）",
    UNKNOWN to "操作失败",
    NETWORK_ERROR to "网络请求失败",
    SERVER_ERROR to "服务端内部错误（5xx）"
)

/** 门户 client_type 字段含义（取自门户 lang.js） */
val CLIENT_TYPE_LABELS = mapOf(
    "0" to "无法判断",
    "1" to "PC",
    "2" to "移动设备或其他",
    "3" to "PC 客户端",
    "4" to "移动客户端",
    "5" to "IP 表免认证",
    "6" to "MAC 认证",
    "7" to "小程序直接认证",
    "8" to "小程序扫码认证",
    "9" to "微信认证",
    "10" to "LDAP",
    "11" to "钉钉认证"
)

/**
 * 一台在线设备（来自 /v1/srun_portal_online）。
 *
 * 门户只提供 IP、系统、上线时间，**没有主机名和 MAC**，且 IP 是 DHCP 动态分配的，
 * 因此 IP 不能当作设备唯一标识。
 */
data class Device(
    val ip: String,
    val userName: String = "",
    val clientType: String = "",
    val osName: String = "",
    val addTime: String = "",
    val raw: JSONObject = JSONObject()
) {
    val clientTypeLabel: String
        get() = CLIENT_TYPE_LABELS[clientType] ?: "未知($clientType)"

    private fun addTimeDate(): Date? {
        if (addTime.isBlank()) return null
        return try {
            SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).parse(addTime)
        } catch (e: Exception) {
            null
        }
    }

    /** 已在线秒数；解析失败返回 null。 */
    fun onlineSeconds(now: Long = System.currentTimeMillis()): Long? {
        val start = addTimeDate() ?: return null
        return ((now - start.time) / 1000).coerceAtLeast(0)
    }

    /** 已在线时长的人类可读文本，例如 "3 天 4 小时"。 */
    fun onlineText(now: Long = System.currentTimeMillis()): String {
        val sec = onlineSeconds(now) ?: return "-"
        val days = sec / 86400
        val hours = (sec % 86400) / 3600
        val minutes = (sec % 3600) / 60
        return when {
            days > 0 -> "$days 天 $hours 小时"
            hours > 0 -> "$hours 小时 $minutes 分"
            else -> "$minutes 分钟"
        }
    }

    companion object {
        fun fromJson(d: JSONObject): Device = Device(
            ip = d.optString("ip", ""),
            userName = d.optString("user_name", ""),
            clientType = d.optString("client_type", ""),
            osName = d.optString("os_name", ""),
            addTime = d.optString("add_time", ""),
            raw = d
        )
    }
}

/**
 * 本机在线状态（来自 /cgi-bin/rad_user_info，按请求来源 IP 查询）。
 *
 * **不能**用 `online == false` 当作"离线"——被限流或网络抖动时同样会是 false。
 */
data class OnlineStatus(
    val online: Boolean,
    val error: String = "",
    val raw: JSONObject = JSONObject()
) {
    val ip: String? get() = raw.optString("online_ip").ifBlank { null }
    val ip6: String? get() = raw.optString("online_ip6").ifBlank { null }
    val userName: String? get() = raw.optString("user_name").ifBlank { null }
    val mac: String? get() = raw.optString("user_mac").ifBlank { null }
    val deviceTotal: String? get() = raw.optString("online_device_total").ifBlank { null }

    val state: String
        get() = when {
            online -> STATE_ONLINE
            error in OFFLINE_ERRORS -> STATE_OFFLINE
            else -> STATE_UNKNOWN
        }

    val rateLimited: Boolean get() = error in RATE_LIMIT_ERRORS

    /** 在线且是本账号 → 说明本机 IP 上的会话仍是自己（多半是上次没下线）。 */
    val isMe: Boolean get() = online && !userName.isNullOrBlank()

    /** 该状态是否由设备列表推断而来（不是服务端原话）。 */
    val synthetic: Boolean get() = raw.optBoolean("synthetic", false)
}

/** 一次认证挑战（token 有效期 60 秒）。 */
data class Challenge(
    val token: String,
    val clientIp: String = "",
    val expire: String = "",
    val raw: JSONObject = JSONObject()
)

/** 一次接口调用的结果。 */
data class PortalResult(
    var kind: String,
    val raw: JSONObject = JSONObject(),
    val httpStatus: Int? = null,
    var ip: String? = null,
    val username: String? = null,
    val detail: MutableMap<String, Any?> = mutableMapOf()
) {
    val ok: Boolean get() = kind == SUCCESS

    val message: String
        get() = Errors.messageFor(raw) ?: KIND_TEXT[kind] ?: "操作失败"
}
