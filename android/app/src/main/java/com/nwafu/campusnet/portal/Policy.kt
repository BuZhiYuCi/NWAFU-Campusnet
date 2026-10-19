package com.nwafu.campusnet.portal

/**
 * 腾位策略：在线数已满时，该踢掉哪一台（或哪几台）。
 *
 * 在线设备列表只给 IP、系统、上线时间，**没有主机名和 MAC**，而 IP 是 DHCP
 * 动态分配的，所以"哪台是哪台"没法可靠自动判断。策略因此分三种：
 * - [PRESELECT_OLDEST]（默认）：预选上线时间最早（在线最久）的那台，用户可改选；
 * - [PRIORITY]：按配置里给设备设的优先级挑，优先级数字大的先出局；
 * - [MANUAL]：不预选，完全由用户勾选。
 */
object Policy {

    const val PRESELECT_OLDEST = "preselect_oldest"
    const val PRIORITY = "priority"
    const val MANUAL = "manual"

    val ALL_MODES = listOf(PRESELECT_OLDEST, PRIORITY, MANUAL)

    /** 按上线时间升序（最早的在最前）。时间缺失的排最后。 */
    fun sortOldestFirst(devices: List<Device>): List<Device> =
        devices.sortedWith(compareBy({ it.addTime.ifEmpty { "9999" } }, { it.ip }))

    /** 可以被踢的设备：排除本机自己。 */
    fun candidates(devices: List<Device>, myIp: String?): List<Device> =
        if (myIp.isNullOrBlank()) devices else devices.filter { it.ip != myIp }

    /**
     * 按策略挑出建议下线的设备列表（不真正执行，仅给 UI 预选）。
     *
     * @param devices 在线设备列表
     * @param myIp 本机 IP，会被排除（自己不用"被踢"）
     * @param mode 见类文档
     * @param count 需要腾出几个名额
     * @param devicePrefs 配置里的设备别名表（用于 priority 模式）
     */
    fun pickVictims(
        devices: List<Device>,
        myIp: String? = null,
        mode: String = PRESELECT_OLDEST,
        count: Int = 1,
        devicePrefs: List<DevicePref> = emptyList()
    ): List<Device> {
        val pool = candidates(devices, myIp)
        if (pool.isEmpty() || mode == MANUAL) return emptyList()
        val n = count.coerceAtLeast(1)
        val ordered = if (mode == PRIORITY) {
            pool.sortedWith(
                compareByDescending<Device> { priorityOf(it, devicePrefs) }
                    .thenBy { it.addTime.ifEmpty { "9999" } }
                    .thenBy { it.ip }
            )
        } else {
            sortOldestFirst(pool)
        }
        return ordered.take(n)
    }

    /** 查设备别名（没有就返回空串）。 */
    fun aliasOf(device: Device, devicePrefs: List<DevicePref>): String =
        devicePrefs.firstOrNull { it.lastIp == device.ip }?.alias ?: ""

    private fun priorityOf(device: Device, devicePrefs: List<DevicePref>): Int =
        devicePrefs.firstOrNull { it.lastIp == device.ip }?.priority ?: 0

    /** 给人看的一句话说明，例如 "10.1.1.1（台式机），已在线 3 天 2 小时"。 */
    fun describeVictims(victims: List<Device>, devicePrefs: List<DevicePref>): String {
        if (victims.isEmpty()) return "（无）"
        return victims.joinToString("；") { dev ->
            val alias = aliasOf(dev, devicePrefs)
            val label = if (alias.isNotEmpty()) "${dev.ip}（$alias）" else dev.ip
            "$label，已在线 ${dev.onlineText()}"
        }
    }
}

/** 配置里记录的设备偏好（别名 / 优先级 / 最近一次见到的 IP）。 */
data class DevicePref(
    val alias: String = "",
    val priority: Int = 0,
    val lastIp: String = ""
)
