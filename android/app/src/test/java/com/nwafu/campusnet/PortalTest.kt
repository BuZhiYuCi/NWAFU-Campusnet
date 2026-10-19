package com.nwafu.campusnet

import com.nwafu.campusnet.portal.ALREADY_ONLINE
import com.nwafu.campusnet.portal.Device
import com.nwafu.campusnet.portal.FULL
import com.nwafu.campusnet.portal.NOT_ONLINE
import com.nwafu.campusnet.portal.SERVER_ERROR
import com.nwafu.campusnet.portal.SIGNATURE_ERROR
import com.nwafu.campusnet.portal.STATE_OFFLINE
import com.nwafu.campusnet.portal.STATE_ONLINE
import com.nwafu.campusnet.portal.STATE_UNKNOWN
import com.nwafu.campusnet.portal.SUCCESS
import com.nwafu.campusnet.portal.SrunPortalClient
import com.nwafu.campusnet.portal.UNPARSED
import com.nwafu.campusnet.portal.classify
import com.nwafu.campusnet.portal.parseJsonp
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * 协议层行为测试，全部打到本地桩，不发任何真实校园网请求。
 */
class PortalTest {

    private lateinit var portal: FakePortal

    @Before
    fun setUp() {
        portal = FakePortal().start()
    }

    @After
    fun tearDown() {
        portal.stop()
    }

    private fun client(timeoutMs: Int = 2000) =
        SrunPortalClient(baseUrl = portal.baseUrl, timeoutMs = timeoutMs)

    // ------------------------------------------------------------------
    // JSONP 解析
    // ------------------------------------------------------------------

    @Test
    fun jsonpBodyIsParsed() {
        val v = parseJsonp("cb({\"error\":\"ok\"})")
        assertTrue(v is JSONObject)
        assertEquals("ok", (v as JSONObject).getString("error"))
    }

    @Test
    fun jsonpWithTrailingSemicolonIsParsed() {
        val v = parseJsonp("cb({\"a\":1});")
        assertTrue(v is JSONObject)
        assertEquals(1, (v as JSONObject).getInt("a"))
    }

    @Test
    fun plainJsonBodyIsParsed() {
        val v = parseJsonp("{\"code\":\"0\"}")
        assertTrue(v is JSONObject)
        assertEquals("0", (v as JSONObject).getString("code"))
    }

    @Test
    fun htmlBodyFallsBackToNull() {
        assertNull(parseJsonp("<html><body>portal</body></html>"))
    }

    @Test
    fun emptyBodyFallsBackToNull() {
        assertNull(parseJsonp(""))
        assertNull(parseJsonp("   "))
        assertNull(parseJsonp(null))
    }

    @Test
    fun bomPrefixedBodyFallsBackToNull() {
        assertNull(parseJsonp("\uFEFFcb({\"error\":\"ok\"})"))
    }

    @Test
    fun tryWrappedJsonpFallsBackToNull() {
        assertNull(parseJsonp("try{cb({\"error\":\"ok\"})}catch(e){}"))
    }

    // ------------------------------------------------------------------
    // 结果归类
    // ------------------------------------------------------------------

    @Test
    fun classifySuccess() {
        assertEquals(SUCCESS, classify(JSONObject("{\"ecode\":\"0\",\"error\":\"ok\",\"ploy_msg\":\"E0000: 成功\"}")))
        assertEquals(SUCCESS, classify(JSONObject("{\"ploy_msg\":\"E0000: 登录成功\"}")))
    }

    @Test
    fun classifyE2620IsAlreadyOnlineNotFull() {
        // 误判成 FULL 会触发腾位流程去踢设备，而此刻在线的可能就是用户自己
        assertEquals(ALREADY_ONLINE, classify(JSONObject("{\"ecode\":\"E2620\",\"ploy_msg\":\"E2620: 已经在线了\"}")))
        assertEquals(ALREADY_ONLINE, classify(JSONObject("{\"ecode\":\"E6526\",\"ploy_msg\":\"您的IP已经在线\"}")))
        assertEquals(ALREADY_ONLINE, classify(JSONObject("{\"error\":\"already_online\"}")))
    }

    @Test
    fun classifyFull() {
        assertEquals(FULL, classify(JSONObject("{\"ecode\":\"E2621\",\"ploy_msg\":\"E2621: 已达授权人数\"}")))
        assertEquals(FULL, classify(JSONObject("{\"ecode\":\"E6512\",\"ploy_msg\":\"E6512: 在线用户已满\"}")))
    }

    @Test
    fun classifyNotOnlineFamily() {
        assertEquals(NOT_ONLINE, classify(JSONObject("{\"error\":\"not_online_error\"}")))
        assertEquals(NOT_ONLINE, classify(JSONObject("{\"ecode\":\"E6503\",\"ploy_msg\":\"E6503: 不在线\"}")))
        assertEquals(NOT_ONLINE, classify(JSONObject("{\"ploy_msg\":\"you_are_not_online\"}")))
    }

    @Test
    fun classifySignatureError() {
        assertEquals(SIGNATURE_ERROR, classify(JSONObject("{\"error\":\"sign_error\"}")))
        assertEquals(SIGNATURE_ERROR, classify(JSONObject("{\"error_msg\":\"chksum error\"}")))
    }

    @Test
    fun classifyNonObjectIsUnparsed() {
        assertEquals(UNPARSED, classify(null))
        assertEquals(UNPARSED, classify("plain text"))
    }

    // ------------------------------------------------------------------
    // 本机状态
    // ------------------------------------------------------------------

    @Test
    fun userInfoOnline() {
        portal.jsonp("/cgi-bin/rad_user_info",
            "{\"error\":\"ok\",\"online_ip\":\"10.0.0.5\",\"user_name\":\"20230000001\"}")
        val status = client().userInfo()
        assertTrue(status.online)
        assertEquals(STATE_ONLINE, status.state)
        assertEquals("10.0.0.5", status.ip)
        assertEquals("20230000001", status.userName)
        assertTrue(status.isMe)
    }

    @Test
    fun userInfoOffline() {
        portal.jsonp("/cgi-bin/rad_user_info", "{\"error\":\"not_online_error\"}")
        val status = client().userInfo()
        assertFalse(status.online)
        assertEquals(STATE_OFFLINE, status.state)
    }

    @Test
    fun rateLimitedIsUnknownNotOffline() {
        portal.jsonp("/cgi-bin/rad_user_info", "{\"error\":\"speed_limit_error\"}")
        val status = client().userInfo()
        assertEquals(STATE_UNKNOWN, status.state)
        assertTrue(status.rateLimited)
    }

    @Test
    fun http5xxWithOkBodyIsServerErrorNotOnline() {
        portal.json("/cgi-bin/rad_user_info", "{\"error\":\"ok\",\"online_ip\":\"10.0.0.5\"}", status = 500)
        val status = client().userInfo()
        assertFalse("5xx 时不能采信 body 里的 error=ok", status.online)
        assertEquals(SERVER_ERROR, status.error)
    }

    @Test
    fun htmlInterceptionIsNotReachable() {
        portal.html("/cgi-bin/rad_user_info")
        assertFalse(client().portalReachable())
    }

    @Test
    fun htmlInterceptionIsUnparsed() {
        portal.html("/cgi-bin/rad_user_info")
        val status = client().userInfo()
        assertEquals(UNPARSED, status.error)
        assertEquals(STATE_UNKNOWN, status.state)
    }

    // ------------------------------------------------------------------
    // 设备列表
    // ------------------------------------------------------------------

    @Test
    fun onlineDevicesAreParsed() {
        portal.json("/v1/srun_portal_online",
            "{\"code\":\"0\",\"data\":[" +
                    "{\"ip\":\"10.0.0.5\",\"user_name\":\"20230000001\",\"client_type\":\"4\"," +
                    "\"os_name\":\"Android\",\"add_time\":\"2026-10-19 08:00:00\"}," +
                    "{\"ip\":\"10.0.0.9\",\"client_type\":\"1\",\"add_time\":\"2026-10-18 07:00:00\"}" +
                    "]}")
        val devices = client().onlineDevices("20230000001", "pwd")
        assertEquals(2, devices.size)
        assertEquals("10.0.0.5", devices[0].ip)
        assertEquals("移动客户端", devices[0].clientTypeLabel)
        assertEquals("PC", devices[1].clientTypeLabel)
    }

    @Test(expected = Exception::class)
    fun onlineDevicesNonZeroCodeThrows() {
        portal.json("/v1/srun_portal_online", "{\"code\":\"1\",\"error\":\"E2606\"}")
        client().onlineDevices("20230000001", "pwd")
    }

    @Test
    fun localStateOnlineFromUserInfo() {
        portal.jsonp("/cgi-bin/rad_user_info",
            "{\"error\":\"ok\",\"online_ip\":\"10.0.0.5\",\"user_name\":\"20230000001\"}")
        val (state, _, _) = client().localState("20230000001", "pwd")
        assertEquals(STATE_ONLINE, state)
    }

    @Test
    fun localStateOfflineFromUserInfo() {
        portal.jsonp("/cgi-bin/rad_user_info", "{\"error\":\"not_online_error\"}")
        val (state, _, _) = client().localState("20230000001", "pwd")
        assertEquals(STATE_OFFLINE, state)
    }

    // ------------------------------------------------------------------
    // 登录参数
    // ------------------------------------------------------------------

    @Test
    fun loginSendsExpectedParameters() {
        portal.jsonp("/cgi-bin/get_challenge",
            "{\"challenge\":\"c436b50e9f1e4f0d8f4b1a2c3d4e5f60" +
                    "718293a4b5c6d7e8f90a1b2c3d4e5f60\",\"client_ip\":\"10.0.0.5\",\"expire\":\"60\"}")
        portal.jsonp("/cgi-bin/srun_portal",
            "{\"ecode\":\"0\",\"error\":\"ok\",\"ploy_msg\":\"E0000: 登录成功\"}")

        val res = client().login("20230000001", "pwd")
        assertEquals(SUCCESS, res.kind)
        assertEquals(200, res.httpStatus)
        assertEquals("10.0.0.5", res.ip)

        val req = portal.requests.last { it.path == "/cgi-bin/srun_portal" }
        assertEquals("login", req.params["action"])
        assertEquals("20230000001", req.params["username"])
        assertTrue("password 必须是 {MD5} 前缀", req.params["password"]!!.startsWith("{MD5}"))
        // "{MD5}" 是 5 个字符，加 32 位十六进制摘要 = 37
        assertEquals(37, req.params["password"]!!.length)
        assertTrue("info 必须是 {SRBX1} 前缀", req.params["info"]!!.startsWith("{SRBX1}"))
        assertEquals("10.0.0.5", req.params["ip"])
        assertEquals("200", req.params["n"])
        assertEquals("1", req.params["type"])
        assertEquals(40, req.params["chksum"]!!.length)
    }

    @Test
    fun login5xxIsServerError() {
        portal.jsonp("/cgi-bin/get_challenge",
            "{\"challenge\":\"abc123\",\"client_ip\":\"10.0.0.5\"}")
        portal.json("/cgi-bin/srun_portal", "{\"ecode\":\"E2621\",\"error\":\"full_error\"}", status = 502)
        val res = client().login("20230000001", "pwd")
        assertEquals(SERVER_ERROR, res.kind)
        assertEquals(502, res.httpStatus)
    }

    @Test
    fun challengeFailureRaises() {
        portal.html("/cgi-bin/get_challenge")
        try {
            client().login("20230000001", "pwd")
            throw AssertionError("应当抛出异常")
        } catch (e: Exception) {
            assertTrue(e.message!!.contains("challenge"))
        }
    }

    // ------------------------------------------------------------------
    // 注销
    // ------------------------------------------------------------------

    @Test
    fun logoutLocalVerifiesOffline() {
        portal.jsonp("/cgi-bin/get_challenge",
            "{\"challenge\":\"abc123\",\"client_ip\":\"10.0.0.5\"}")
        portal.jsonp("/cgi-bin/rad_user_dm", "{\"error\":\"ok\",\"ploy_msg\":\"E0000: 成功\"}")
        portal.jsonp("/cgi-bin/rad_user_info", "{\"error\":\"not_online_error\"}")

        val res = client().logoutLocal("20230000001", password = "pwd", verifyTimeoutMs = 1500)
        assertEquals(SUCCESS, res.kind)
        assertEquals(true, res.detail["verified"])
        assertEquals("dm", res.detail["mechanism"])

        val req = portal.requests.first { it.path == "/cgi-bin/rad_user_dm" }
        assertEquals("10.0.0.5", req.params["ip"])
        assertEquals("1", req.params["unbind"])
        assertEquals(40, req.params["sign"]!!.length)
    }

    @Test
    fun logoutLocalStillOnlineIsNotSuccess() {
        portal.jsonp("/cgi-bin/get_challenge",
            "{\"challenge\":\"abc123\",\"client_ip\":\"10.0.0.5\"}")
        portal.jsonp("/cgi-bin/rad_user_dm", "{\"error\":\"ok\"}")
        // 注销后立刻又被拉回在线
        portal.jsonp("/cgi-bin/rad_user_info",
            "{\"error\":\"ok\",\"online_ip\":\"10.0.0.5\",\"user_name\":\"20230000001\"}")

        val res = client().logoutLocal("20230000001", password = "pwd", verifyTimeoutMs = 800)
        assertFalse("未确认离线时不能报成功", res.kind == SUCCESS)
        assertEquals(true, res.detail["still_online"])
    }

    // ------------------------------------------------------------------
    // 设备模型
    // ------------------------------------------------------------------

    @Test
    fun deviceOnlineTextIsHumanReadable() {
        val dev = Device(ip = "10.0.0.5", addTime = "2026-10-16 08:00:00")
        val now = java.text.SimpleDateFormat("yyyy-MM-dd HH:mm:ss", java.util.Locale.US)
            .parse("2026-10-19 10:00:00")!!.time
        assertEquals("3 天 2 小时", dev.onlineText(now))
        assertEquals("3 天 2 小时", dev.onlineText(now))
    }

    @Test
    fun deviceMissingAddTimeIsDash() {
        assertEquals("-", Device(ip = "10.0.0.5").onlineText())
    }

    @Test
    fun deviceUnknownClientType() {
        assertEquals("未知(99)", Device(ip = "x", clientType = "99").clientTypeLabel)
    }
}
