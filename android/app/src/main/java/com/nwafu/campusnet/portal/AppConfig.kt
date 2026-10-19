package com.nwafu.campusnet.portal

/**
 * 业务层需要的配置视图。
 *
 * 定义成接口而不是直接传 DataStore，是为了让 [com.nwafu.campusnet.service.CampusNetService]
 * 能在 JVM 单元测试里用一份内存实现跑起来，不依赖 Android 框架。
 */
interface AppConfig {
    val baseUrl: String
    val acId: String
    val username: String
    val password: String?
    val osName: String
    val clientName: String
    val kickMode: String
    val logoutMethod: String
    val batchKickIntervalMs: Long
    val loginTimeoutMs: Int
    val confirmTimeoutMs: Long
    val maxLoginAttempts: Int
    val devicePrefs: List<DevicePref>
}

/** 内存实现，用于单元测试与默认值兜底。 */
data class SimpleConfig(
    override val baseUrl: String = SrunPortalClient.DEFAULT_BASE_URL,
    override val acId: String = SrunPortalClient.DEFAULT_AC_ID,
    override val username: String = "",
    override val password: String? = null,
    override val osName: String = SrunPortalClient.DEFAULT_OS_NAME,
    override val clientName: String = SrunPortalClient.DEFAULT_CLIENT_NAME,
    override val kickMode: String = Policy.PRESELECT_OLDEST,
    override val logoutMethod: String = "dm",
    override val batchKickIntervalMs: Long = 800,
    override val loginTimeoutMs: Int = 30_000,
    override val confirmTimeoutMs: Long = 90_000,
    override val maxLoginAttempts: Int = 3,
    override val devicePrefs: List<DevicePref> = emptyList()
) : AppConfig
