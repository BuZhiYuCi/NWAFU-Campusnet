package com.nwafu.campusnet.crypto

import java.security.MessageDigest
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * 深澜（SRun）门户加密实现，与桌面版 `src/campusnet/crypto.py` 逐行对齐。
 *
 * 三个必须守住的细节（桌面版已经踩过的坑）：
 * 1. 自定义 Base64 字母表是**逐字节**映射，不做 UTF-8 转换；
 * 2. XXTEA 的打包是**小端**（`c0 | c1<<8 | c2<<16 | c3<<24`），不是网络序；
 * 3. hmd5 是 HMAC-MD5(key=token, message=password)，
 *    不是网上大量脚本写的 md5(password + token)。
 *
 * 这里刻意不依赖 android.util.Base64，自己实现标准 Base64，
 * 好处是同一份代码能在 JVM 单元测试里跑（minSdk 24 也没有 java.util.Base64）。
 */
object Crypto {

    /** 门户自定义 Base64 字母表（jquery-base64 的 _ALPHA） */
    const val CUSTOM_ALPHA = "LVoJPiCN2R8G90yg+hmFHuacZ1OWMnrsSTXkYpUq/3dlbfKwv6xztjI7DeBE45QA"

    /** 标准 Base64 字母表 */
    private const val STD_ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"

    /** XXTEA 的 delta 常量（JS 里写成 0x86014019 | 0x183639A0） */
    private const val DELTA = 0x9E3779B9.toInt()

    /** 标准字母表 → 自定义字母表的逐字节映射；'=' 填充保持原样 */
    private val B64_MAP = CharArray(128) { it.toChar() }.also { map ->
        for (i in STD_ALPHA.indices) {
            map[STD_ALPHA[i].code] = CUSTOM_ALPHA[i]
        }
    }

    // ------------------------------------------------------------------
    // Base64
    // ------------------------------------------------------------------

    private fun stdBase64Encode(data: ByteArray): String {
        val sb = StringBuilder(((data.size + 2) / 3) * 4)
        var i = 0
        while (i + 2 < data.size) {
            val n = ((data[i].toInt() and 0xFF) shl 16) or
                    ((data[i + 1].toInt() and 0xFF) shl 8) or
                    (data[i + 2].toInt() and 0xFF)
            sb.append(STD_ALPHA[(n ushr 18) and 63])
            sb.append(STD_ALPHA[(n ushr 12) and 63])
            sb.append(STD_ALPHA[(n ushr 6) and 63])
            sb.append(STD_ALPHA[n and 63])
            i += 3
        }
        when (data.size - i) {
            1 -> {
                val n = (data[i].toInt() and 0xFF) shl 16
                sb.append(STD_ALPHA[(n ushr 18) and 63])
                sb.append(STD_ALPHA[(n ushr 12) and 63])
                sb.append("==")
            }
            2 -> {
                val n = ((data[i].toInt() and 0xFF) shl 16) or
                        ((data[i + 1].toInt() and 0xFF) shl 8)
                sb.append(STD_ALPHA[(n ushr 18) and 63])
                sb.append(STD_ALPHA[(n ushr 12) and 63])
                sb.append(STD_ALPHA[(n ushr 6) and 63])
                sb.append('=')
            }
        }
        return sb.toString()
    }

    /** 按门户自定义字母表编码 Base64。 */
    fun customB64Encode(raw: ByteArray): String {
        val std = stdBase64Encode(raw)
        val sb = StringBuilder(std.length)
        for (c in std) {
            sb.append(if (c.code < 128) B64_MAP[c.code] else c)
        }
        return sb.toString()
    }

    /** 按门户自定义字母表解码 Base64（调试与测试用）。 */
    fun customB64Decode(text: String): ByteArray {
        val reverse = CharArray(128) { it.toChar() }.also { map ->
            for (i in CUSTOM_ALPHA.indices) {
                map[CUSTOM_ALPHA[i].code] = STD_ALPHA[i]
            }
        }
        val std = StringBuilder(text.length)
        for (c in text) {
            std.append(if (c.code < 128) reverse[c.code] else c)
        }
        return stdBase64Decode(std.toString())
    }

    private fun stdBase64Decode(text: String): ByteArray {
        val clean = text.filter { it != '=' }
        val out = java.io.ByteArrayOutputStream()
        var buffer = 0
        var bits = 0
        for (c in clean) {
            val v = STD_ALPHA.indexOf(c)
            if (v < 0) continue
            buffer = (buffer shl 6) or v
            bits += 6
            if (bits >= 8) {
                bits -= 8
                out.write((buffer ushr bits) and 0xFF)
            }
        }
        return out.toByteArray()
    }

    // ------------------------------------------------------------------
    // XXTEA
    // ------------------------------------------------------------------

    /** 对应 JS 的 s(a, b)：字符串 → 32 位字数组，小端打包。 */
    private fun str2long(s: String, includeLen: Boolean): IntArray {
        val words = ArrayList<Int>(s.length / 4 + 2)
        var i = 0
        while (i < s.length) {
            var c0 = 0
            var c1 = 0
            var c2 = 0
            var c3 = 0
            c0 = s[i].code and 0xFF
            if (i + 1 < s.length) c1 = s[i + 1].code and 0xFF
            if (i + 2 < s.length) c2 = s[i + 2].code and 0xFF
            if (i + 3 < s.length) c3 = s[i + 3].code and 0xFF
            words.add(c0 or (c1 shl 8) or (c2 shl 16) or (c3 shl 24))
            i += 4
        }
        if (includeLen) words.add(s.length)
        return words.toIntArray()
    }

    /** 对应 JS 的 l(a, b)：32 位字数组 → 字节串，小端拆包。 */
    private fun long2bytes(words: IntArray): ByteArray {
        val out = ByteArray(words.size * 4)
        for (i in words.indices) {
            val w = words[i]
            out[i * 4] = (w and 0xFF).toByte()
            out[i * 4 + 1] = ((w ushr 8) and 0xFF).toByte()
            out[i * 4 + 2] = ((w ushr 16) and 0xFF).toByte()
            out[i * 4 + 3] = ((w ushr 24) and 0xFF).toByte()
        }
        return out
    }

    /** 对应 Portal.js 里的 encode(str, key)。 */
    fun xxteaEncode(text: String, key: String): ByteArray {
        val v = str2long(text, true)
        var k = str2long(key, false)
        if (k.size < 4) k = k.copyOf(4)
        val n = v.size - 1
        var z = v[n]
        var y = v[0]
        var q = 6 + 52 / (n + 1)
        var d = 0
        while (q > 0) {
            q--
            d += DELTA
            val e = (d ushr 2) and 3
            var p = 0
            while (p < n) {
                y = v[p + 1]
                var m = (z ushr 5) xor (y shl 2)
                m += ((y ushr 3) xor (z shl 4) xor (d xor y))
                m += (k[(p and 3) xor e] xor z)
                z = v[p] + m
                v[p] = z
                p++
            }
            y = v[0]
            var m = (z ushr 5) xor (y shl 2)
            m += ((y ushr 3) xor (z shl 4) xor (d xor y))
            m += (k[(n and 3) xor e] xor z)
            z = v[n] + m
            v[n] = z
        }
        return long2bytes(v)
    }

    /** XXTEA 解密（门户不要求，仅用于自校验）。 */
    fun xxteaDecode(data: ByteArray, key: String): ByteArray {
        if (data.size < 4) return data
        val v = IntArray(data.size / 4) { i ->
            (data[i * 4].toInt() and 0xFF) or
                    ((data[i * 4 + 1].toInt() and 0xFF) shl 8) or
                    ((data[i * 4 + 2].toInt() and 0xFF) shl 16) or
                    ((data[i * 4 + 3].toInt() and 0xFF) shl 24)
        }
        var k = str2long(key, false)
        if (k.size < 4) k = k.copyOf(4)
        val n = v.size - 1
        var y = v[0]
        var q = 6 + 52 / (n + 1)
        var d = q * DELTA
        var z: Int
        while (d != 0) {
            val e = (d ushr 2) and 3
            var p = n
            while (p > 0) {
                z = v[p - 1]
                var m = (z ushr 5) xor (y shl 2)
                m += ((y ushr 3) xor (z shl 4) xor (d xor y))
                m += (k[(p and 3) xor e] xor z)
                y = v[p] - m
                v[p] = y
                p--
            }
            z = v[n]
            var m = (z ushr 5) xor (y shl 2)
            m += ((y ushr 3) xor (z shl 4) xor (d xor y))
            m += (k[e] xor z)
            y = v[0] - m
            v[0] = y
            d -= DELTA
        }
        val bytes = long2bytes(v)
        val declared = v[n]
        return if (declared in 0..bytes.size) bytes.copyOf(declared) else bytes
    }

    // ------------------------------------------------------------------
    // 摘要
    // ------------------------------------------------------------------

    private fun hex(bytes: ByteArray): String {
        val sb = StringBuilder(bytes.size * 2)
        for (b in bytes) {
            val v = b.toInt() and 0xFF
            sb.append(HEX[v ushr 4])
            sb.append(HEX[v and 0x0F])
        }
        return sb.toString()
    }

    private val HEX = "0123456789abcdef".toCharArray()

    /** 门户的 md5(password, token) —— 双参数即 HMAC。 */
    fun hmacMd5(password: String, token: String): String {
        val mac = Mac.getInstance("HmacMD5")
        mac.init(SecretKeySpec(token.toByteArray(Charsets.UTF_8), "HmacMD5"))
        return hex(mac.doFinal(password.toByteArray(Charsets.UTF_8)))
    }

    fun md5Hex(text: String): String =
        hex(MessageDigest.getInstance("MD5").digest(text.toByteArray(Charsets.UTF_8)))

    fun sha1Hex(text: String): String =
        hex(MessageDigest.getInstance("SHA-1").digest(text.toByteArray(Charsets.UTF_8)))

    /** 在线设备查询接口需要的明文密码 MD5。 */
    fun passwordMd5(password: String?): String {
        if (password.isNullOrEmpty()) {
            throw IllegalArgumentException("缺少密码，无法计算密码摘要")
        }
        return md5Hex(password)
    }

    // ------------------------------------------------------------------
    // 登录参数
    // ------------------------------------------------------------------

    private fun jsonEscape(s: String): String {
        val sb = StringBuilder(s.length + 2)
        sb.append('"')
        for (c in s) {
            when (c) {
                '"' -> sb.append("\\\"")
                '\\' -> sb.append("\\\\")
                '\n' -> sb.append("\\n")
                '\r' -> sb.append("\\r")
                '\t' -> sb.append("\\t")
                '\b' -> sb.append("\\b")
                '\u000C' -> sb.append("\\f")
                else ->
                    if (c.code < 0x20) {
                        sb.append("\\u")
                        sb.append(String.format("%04x", c.code))
                    } else {
                        sb.append(c)
                    }
            }
        }
        sb.append('"')
        return sb.toString()
    }

    /** 字段顺序必须与 JS 的 JSON.stringify 完全一致，否则密文不同。 */
    fun buildInfoJson(
        username: String,
        password: String,
        ip: String,
        acid: String,
        encVer: String = "srun_bx1"
    ): String = buildString {
        append("{\"username\":").append(jsonEscape(username))
        append(",\"password\":").append(jsonEscape(password))
        append(",\"ip\":").append(jsonEscape(ip))
        append(",\"acid\":").append(jsonEscape(acid))
        append(",\"enc_ver\":").append(jsonEscape(encVer))
        append('}')
    }

    /** 生成登录参数里的 info 字段：{SRBX1} + 自定义Base64(XXTEA(json, token))。 */
    fun buildInfo(
        username: String,
        password: String,
        ip: String,
        acid: String,
        token: String,
        encVer: String = "srun_bx1"
    ): String {
        val payload = buildInfoJson(username, password, ip, acid, encVer)
        return "{SRBX1}" + customB64Encode(xxteaEncode(payload, token))
    }

    /** 生成登录参数里的 chksum 字段。 */
    fun buildChksum(
        token: String,
        username: String,
        hmd5: String,
        acid: String,
        ip: String,
        n: Int,
        type: Int,
        info: String
    ): String {
        val joined = token + username + token + hmd5 + token + acid + token + ip +
                token + n.toString() + token + type.toString() + token + info
        return sha1Hex(joined)
    }

    /**
     * 对应 JS 的 `Date.parse(new Date()) / 1000` —— 结果是**整数秒**。
     * 传小数会让门户返回 sign_error（桌面版实测）。
     */
    fun jsTimeStr(nowSeconds: Long = System.currentTimeMillis() / 1000): String =
        nowSeconds.toString()

    /**
     * 生成 rad_user_dm 的 (time, sign)。
     * sign = sha1(time + username + ip + unbind + time)，注意 time 出现两次。
     */
    fun dmSignature(
        username: String,
        ip: String,
        unbind: Int = 1,
        nowSeconds: Long = System.currentTimeMillis() / 1000
    ): Pair<String, String> {
        val t = jsTimeStr(nowSeconds)
        val sign = sha1Hex(t + username + ip + unbind.toString() + t)
        return t to sign
    }
}
