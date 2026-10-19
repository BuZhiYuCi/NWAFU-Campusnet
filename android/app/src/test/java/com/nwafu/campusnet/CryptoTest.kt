package com.nwafu.campusnet

import com.nwafu.campusnet.crypto.Crypto
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 协议层黄金向量校验。
 *
 * 向量文件来自桌面版 `tests/vectors.json`，由门户官方前端 JS 生成。
 * 只要这里的断言全绿，就说明 Kotlin 实现与 Python/JS 逐字节一致——
 * 这是安卓版能安全替换桌面端的唯一依据。
 */
class CryptoTest {

    private fun vectors(): List<JSONObject> {
        val text = javaClass.classLoader!!.getResourceAsStream("vectors.json")!!
            .bufferedReader(Charsets.UTF_8).use { it.readText() }
        val arr = JSONObject(text).getJSONArray("vectors")
        return (0 until arr.length()).map { arr.getJSONObject(it) }
    }

    @Test
    fun vectorFileIsPresent() {
        val vs = vectors()
        assertEquals("黄金向量数量与桌面版不一致", 5, vs.size)
    }

    @Test
    fun buildInfoMatchesGoldenVectors() {
        for (v in vectors()) {
            val info = Crypto.buildInfo(
                username = v.getString("username"),
                password = v.getString("password"),
                ip = v.getString("ip"),
                acid = v.getString("acid"),
                token = v.getString("token"),
                encVer = v.optString("enc_ver", "srun_bx1")
            )
            assertEquals(
                "info 不一致（username=${v.getString("username")}）",
                v.getString("info"), info
            )
        }
    }

    @Test
    fun infoJsonMatchesGoldenVectors() {
        for (v in vectors()) {
            val json = Crypto.buildInfoJson(
                username = v.getString("username"),
                password = v.getString("password"),
                ip = v.getString("ip"),
                acid = v.getString("acid"),
                encVer = v.optString("enc_ver", "srun_bx1")
            )
            assertEquals("info 明文 JSON 不一致", v.getString("json"), json)
        }
    }

    @Test
    fun hmacMd5MatchesGoldenVectors() {
        for (v in vectors()) {
            val got = Crypto.hmacMd5(v.getString("password"), v.getString("token"))
            assertEquals("hmd5 不一致", v.getString("hmd5_hmac"), got)
        }
    }

    /** 证明用的不是 md5(password + token)——那是老版 PHP 门户的算法。 */
    @Test
    fun hmacMd5IsNotPlainConcatMd5() {
        for (v in vectors()) {
            val hmac = Crypto.hmacMd5(v.getString("password"), v.getString("token"))
            val concat = Crypto.md5Hex(v.getString("password") + v.getString("token"))
            assertEquals("拼接 MD5 的期望值来自桌面版", v.getString("hmd5_concat"), concat)
            assertNotEquals("hmac 与拼接 MD5 不应相同", concat, hmac)
        }
    }

    @Test
    fun chksumMatchesGoldenVectors() {
        for (v in vectors()) {
            val hmd5 = Crypto.hmacMd5(v.getString("password"), v.getString("token"))
            val info = Crypto.buildInfo(
                v.getString("username"), v.getString("password"),
                v.getString("ip"), v.getString("acid"), v.getString("token")
            )
            val chksum = Crypto.buildChksum(
                token = v.getString("token"),
                username = v.getString("username"),
                hmd5 = hmd5,
                acid = v.getString("acid"),
                ip = v.getString("ip"),
                n = 200,
                type = 1,
                info = info
            )
            assertEquals("chksum 不一致", v.getString("chksum"), chksum)
        }
    }

    @Test
    fun customBase64RoundTrip() {
        val payloads = listOf("", "a", "ab", "abc", "abcd", "中文密码测试", "{SRBX1}abc+/=")
        for (p in payloads) {
            val raw = p.toByteArray(Charsets.UTF_8)
            val encoded = Crypto.customB64Encode(raw)
            val decoded = Crypto.customB64Decode(encoded)
            assertEquals("自定义 Base64 往返失败：$p", p, String(decoded, Charsets.UTF_8))
        }
    }

    @Test
    fun customAlphabetDiffersFromStandard() {
        // "abc" 标准 Base64 是 YWJj；自定义字母表下必然不同
        val custom = Crypto.customB64Encode("abc".toByteArray(Charsets.UTF_8))
        assertEquals(4, custom.length)
        assertNotEquals("YWJj", custom)
    }

    @Test
    fun xxteaRoundTrip() {
        val key = "c436b50e9f1e4f0d8f4b1a2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60"
        val payloads = listOf(
            "{}",
            "{\"a\":1}",
            "x".repeat(200),
            "{\"username\":\"20230000001\",\"password\":\"p@ss-1234\",\"ip\":\"10.0.0.1\"}"
        )
        for (p in payloads) {
            val enc = Crypto.xxteaEncode(p, key)
            val dec = Crypto.xxteaDecode(enc, key)
            assertEquals("XXTEA 往返失败（len=${p.length}）", p, String(dec, Charsets.UTF_8))
        }
    }

    /**
     * 记录一个**协议本身的特性**，不是移植 bug：
     * 门户 JS 的 `s()` 用 `charCodeAt & 0xFF` 打包，非 ASCII 字符的高位必然丢失。
     * 桌面版 Python 同样如此（`ord(ch) & 0xFF`）。
     * 实际登录载荷（学号、密码、IP、ac_id）全部是 ASCII，因此不受影响。
     */
    @Test
    fun xxteaIsLossyForNonAsciiByDesign() {
        val key = "c436b50e9f1e4f0d8f4b1a2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60"
        val enc = Crypto.xxteaEncode("中文", key)
        val dec = String(Crypto.xxteaDecode(enc, key), Charsets.UTF_8)
        assertNotEquals("非 ASCII 会被截断，这是门户算法的原始行为", "中文", dec)
    }

    @Test
    fun dmSignatureMatchesGoldenVector() {
        val (t, sign) = Crypto.dmSignature(
            username = "20230000001",
            ip = "10.0.0.1",
            unbind = 1,
            nowSeconds = 1_700_000_000L
        )
        assertEquals("1700000000", t)
        assertEquals("900ffc2b3de93f7edb2bebfe3a7096b05559d545", sign)
    }

    @Test
    fun jsTimeStrIsIntegerSeconds() {
        val t = Crypto.jsTimeStr(1_700_000_000L)
        assertEquals("1700000000", t)
        assertTrue("时间戳必须是纯数字", t.all { it.isDigit() })
    }

    @Test
    fun passwordMd5MatchesGoldenValue() {
        assertEquals("380e5dc89564f30713ad54bf06aacea8", Crypto.passwordMd5("test-pass"))
    }

    @Test(expected = IllegalArgumentException::class)
    fun passwordMd5RejectsEmptyPassword() {
        Crypto.passwordMd5("")
    }
}
