package com.nwafu.campusnet.portal

import android.content.Context
import org.json.JSONObject

/**
 * 门户错误码 → 中文提示。
 *
 * 文案表来自门户自身的 lang.js（translate["zh-CN"]），由桌面版的
 * tools/extract_error_codes.py 提取为 data/error_codes.json，
 * 这里原样放到 assets/error_codes.json，所以提示语与学校网页上看到的完全一致。
 */
object Errors {

    /** 服务端返回的下划线命名错误 → 文案表里的驼峰键 */
    private val NAMED_ALIASES = mapOf(
        "sign_error" to "SignError",
        "not_online_error" to "NotOnlineError",
        "ip_already_online_error" to "IpAlreadyOnlineError",
        "no_response_data_error" to "NoResponseDataError",
        "user_must_modify_password" to "UserMustModifyPassword",
        "challenge_expire_error" to "ChallengeExpireError",
        "speed_limit_error" to "SpeedLimitError",
        "srun_portal_server_error" to "SrunPortalServerError",
        "auth_resault_timeout_err" to "AuthResaultTimeoutErr",
        "auth_info_error" to "AuthInfoError",
        "token_error" to "TokenError",
        "memory_db_error" to "MemoryDbError",
        "vcode_error" to "VcodeError"
    )

    /** 响应里可能承载结果的字段，按优先级排列 */
    private val CANDIDATE_KEYS = listOf("ecode", "error", "res", "suc_msg", "ploy_msg", "error_msg")

    private val CODE_RE = Regex("(E\\d{4})")

    @Volatile
    private var table: Map<String, String> = emptyMap()

    val loaded: Boolean get() = table.isNotEmpty()
    val size: Int get() = table.size

    /** 从 assets 载入文案表（App 启动时调用一次）。 */
    fun loadFromAssets(context: Context) {
        if (loaded) return
        try {
            val text = context.assets.open("error_codes.json")
                .bufferedReader(Charsets.UTF_8).use { it.readText() }
            loadFromJson(text)
        } catch (e: Exception) {
            // 文案表缺失时降级为通用文案，不影响功能
            table = emptyMap()
        }
    }

    /** 从 JSON 文本载入（单元测试用）。 */
    fun loadFromJson(json: String) {
        val obj = JSONObject(json)
        val map = HashMap<String, String>(obj.length() * 2)
        val it = obj.keys()
        while (it.hasNext()) {
            val k = it.next()
            map[k] = obj.optString(k, "")
        }
        table = map
    }

    /** 从 'E2620: xxx' 或 'E2620' 里取出错误码。 */
    fun extractCode(text: String?): String? {
        if (text.isNullOrEmpty()) return null
        return CODE_RE.find(text)?.groupValues?.get(1)
    }

    /** 按错误码或文案表的键取中文。 */
    fun translate(key: String?, default: String? = null): String? {
        if (key.isNullOrBlank()) return default
        val k = key.trim()
        table[k]?.let { return it }
        extractCode(k)?.let { code -> table[code]?.let { return it } }
        NAMED_ALIASES[k.lowercase()]?.let { camel -> table[camel]?.let { return it } }
        return default
    }

    /** 从接口响应里挑出最合适的一句中文提示；挑不出来返回 null。 */
    fun messageFor(raw: JSONObject?): String? {
        if (raw == null) return null
        for (key in CANDIDATE_KEYS) {
            val value = raw.opt(key) ?: continue
            if (value == JSONObject.NULL) continue
            val text = value.toString().trim()
            if (text.isEmpty() || text == "0") continue
            val hit = translate(text) ?: continue
            val code = extractCode(text)
            return if (code != null && text.length > code.length) "$hit（$code）" else hit
        }
        return null
    }
}
