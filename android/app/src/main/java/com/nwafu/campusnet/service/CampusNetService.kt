package com.nwafu.campusnet.service

import com.nwafu.campusnet.portal.ALREADY_ONLINE
import com.nwafu.campusnet.portal.AppConfig
import com.nwafu.campusnet.portal.Device
import com.nwafu.campusnet.portal.FULL
import com.nwafu.campusnet.portal.NOT_ONLINE
import com.nwafu.campusnet.portal.OnlineStatus
import com.nwafu.campusnet.portal.PortalResult
import com.nwafu.campusnet.portal.STATE_ONLINE
import com.nwafu.campusnet.portal.SUCCESS
import com.nwafu.campusnet.portal.SrunPortalClient
import com.nwafu.campusnet.portal.UNKNOWN

/** 一次业务操作的结果。 */
data class Outcome(
    val ok: Boolean,
    val kind: String,
    val message: String,
    val kicked: List<String> = emptyList(),
    val devices: List<Device> = emptyList(),
    val victims: List<Device> = emptyList(),
    val result: PortalResult? = null,
    val myIp: String? = null
)

/**
 * 决定踢谁的回调：收到 (全部设备, 预选设备, 本机 IP)，返回要下线的 IP 列表；
 * 返回空列表或 null 表示放弃。
 */
typealias ApproveKick = (List<Device>, List<Device>, String?) -> List<String>?

/**
 * 登录 / 下线 / 腾位 的编排，与桌面版 `service.py` 行为一致。
 *
 * 这一层不打印任何东西、不依赖 UI，只返回 [Outcome]。
 */
class CampusNetService(
    private val client: SrunPortalClient,
    private val config: AppConfig,
    private val logger: ((String) -> Unit)? = null,
    private val sleep: (Long) -> Unit = { ms -> Thread.sleep(ms) }
) {

    // ------------------------------------------------------------------
    // 查询
    // ------------------------------------------------------------------

    fun localStatus(): Triple<String, OnlineStatus, List<Device>> =
        client.localState(config.username.ifBlank { null }, config.password)

    fun devices(): List<Device> = client.onlineDevices(config.username, config.password)

    // ------------------------------------------------------------------
    // 下线
    // ------------------------------------------------------------------

    fun logout(): Outcome {
        val password = config.password
        val res = client.logoutLocal(
            username = config.username,
            password = password,
            acId = config.acId,
            method = config.logoutMethod
        )
        logger?.invoke("logout method=${config.logoutMethod} kind=${res.kind} state=${res.detail["state"]}")
        // 必须先确认"真的下线了"再报成功：状态查不出来（限流/抖动）时
        // 只知道服务端回了个 not_online，不代表在线名额已经释放（见 D-07）。
        val verified = res.detail["verified"] == true
        if (verified && res.kind == NOT_ONLINE) {
            return Outcome(true, NOT_ONLINE, "当前已经是离线状态", result = res)
        }
        if (verified) {
            return Outcome(true, SUCCESS, "已下线，在线名额已释放", result = res)
        }
        if (res.detail["still_online"] == true) {
            return Outcome(false, "still_online", "下线请求已被接受，但本机紧接着又上线了", result = res)
        }
        return Outcome(false, UNKNOWN, "无法确认下线结果（${res.message}）", result = res)
    }

    // ------------------------------------------------------------------
    // 踢指定设备
    // ------------------------------------------------------------------

    /** 串行把指定 IP 的设备踢下线，返回逐条结果。 */
    fun kick(ips: List<String>): List<PortalResult> {
        val interval = config.batchKickIntervalMs.coerceAtLeast(0)
        val results = ArrayList<PortalResult>(ips.size)
        ips.forEachIndexed { idx, ip ->
            if (idx > 0) sleep(interval)
            val res = client.kick(ip, config.username, unbind = 1)
            logger?.invoke("kick ip=$ip kind=${res.kind}")
            results.add(res)
        }
        return results
    }

    // ------------------------------------------------------------------
    // 登录（含满员腾位）
    // ------------------------------------------------------------------

    /**
     * 挑出建议下线的设备；有 [approveKick] 时交给调用方定夺。
     *
     * @return (预选设备, 实际要踢的设备)
     */
    fun chooseVictims(
        devices: List<Device>,
        myIp: String?,
        approveKick: ApproveKick? = null,
        count: Int = 1
    ): Pair<List<Device>, List<Device>> {
        val preselected = com.nwafu.campusnet.portal.Policy.pickVictims(
            devices = devices,
            myIp = myIp,
            mode = config.kickMode,
            count = count,
            devicePrefs = config.devicePrefs
        )
        if (approveKick == null) return preselected to preselected
        val approved = approveKick(devices, preselected, myIp)
        if (approved.isNullOrEmpty()) return preselected to emptyList()
        val wanted = approved.toSet()
        return preselected to devices.filter { it.ip in wanted }
    }

    /**
     * 登录；如果提示在线数已满，就腾位后重试。
     *
     * @param approveKick 决定踢谁的回调；null 表示按策略直接执行
     * @param maxRounds 最多尝试几轮（每轮最多腾一次位）
     */
    fun login(approveKick: ApproveKick? = null, maxRounds: Int = config.maxLoginAttempts): Outcome {
        val password = config.password
        val (state, status, devices0) = localStatus()
        var devices = devices0
        val myIp = status.ip
        if (state == STATE_ONLINE) {
            if (!status.userName.isNullOrBlank() && status.userName != config.username) {
                return Outcome(
                    ok = false,
                    kind = "ip_taken",
                    message = "本机 IP（$myIp）已被其它账号 ${status.userName} 占用",
                    devices = devices,
                    myIp = myIp
                )
            }
            if (!status.userName.isNullOrBlank()) {
                return Outcome(
                    ok = true,
                    kind = ALREADY_ONLINE,
                    message = "本机已经在线",
                    devices = devices,
                    myIp = myIp
                )
            }
            // user_name 为空：这不是 rad_user_info 的原话，而是限流期间用设备列表
            // 兜底合成出来的状态（raw.synthetic）。据此断言"已经在线"会让真正的
            // 登录被跳过，用户以为连上了其实没有（见 D-03）。
            logger?.invoke("state=online 但 user_name 缺失（synthetic=${status.synthetic}），改为实际登录确认")
        }

        val kicked = ArrayList<String>()
        var result: PortalResult? = null
        var victims: List<Device> = emptyList()
        for (round in 0 until maxRounds.coerceAtLeast(1)) {
            result = client.loginAndConfirm(
                username = config.username,
                password = password ?: "",
                acId = config.acId,
                loginTimeoutMs = config.loginTimeoutMs,
                confirmTimeoutMs = config.confirmTimeoutMs,
                osName = config.osName,
                clientName = config.clientName
            )
            logger?.invoke("login round=${round + 1} kind=${result.kind} confirmed=${result.detail["confirmed"]}")
            if (result.ok) {
                return Outcome(true, SUCCESS, "登录成功", kicked, devices, emptyList(), result, myIp)
            }
            if (result.kind == ALREADY_ONLINE) {
                return Outcome(true, ALREADY_ONLINE, "本机已经在线", kicked, devices, emptyList(), result, myIp)
            }
            if (result.kind != FULL) break

            // --- 在线数已满：先腾位 ---
            devices = try {
                devices()
            } catch (e: Exception) {
                return Outcome(
                    false, FULL, "在线数已满，且查询设备列表失败：${e.message}",
                    kicked, devices, emptyList(), result, myIp
                )
            }
            if (devices.isEmpty()) break
            val (_, picked) = chooseVictims(devices, myIp, approveKick)
            victims = picked
            if (picked.isEmpty()) {
                return Outcome(
                    false, "declined", "没有选择要下线的设备，已取消",
                    kicked, devices, emptyList(), result, myIp
                )
            }
            logger?.invoke("free slots: ${picked.joinToString(", ") { it.ip }}")
            val results = kick(picked.map { it.ip })
            val freed = results.filter { it.ok || it.kind == NOT_ONLINE }.mapNotNull { it.ip }
            kicked.addAll(freed)
            if (freed.isEmpty()) {
                return Outcome(
                    false, "kick_failed", "腾位失败，未能下线任何设备",
                    kicked, devices, picked, result, myIp
                )
            }
            sleep(1000)
        }

        val kind = result?.kind ?: UNKNOWN
        if (kind == FULL) {
            return Outcome(
                false, FULL, "在线数已满，腾位后仍然登录失败",
                kicked, devices, victims, result, myIp
            )
        }
        return Outcome(
            false, kind, result?.message ?: "登录失败",
            kicked, devices, victims, result, myIp
        )
    }
}
