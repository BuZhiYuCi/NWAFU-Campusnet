package com.nwafu.campusnet.data

import android.content.Context
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.longPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.nwafu.campusnet.portal.AppConfig
import com.nwafu.campusnet.portal.DevicePref
import com.nwafu.campusnet.portal.Policy
import com.nwafu.campusnet.portal.SrunPortalClient
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import org.json.JSONArray
import org.json.JSONObject

private val Context.configDataStore by preferencesDataStore(name = "campusnet_config")

private object Keys {
    val BASE_URL = stringPreferencesKey("base_url")
    val AC_ID = stringPreferencesKey("ac_id")
    val USERNAME = stringPreferencesKey("username")
    val OS_NAME = stringPreferencesKey("os_name")
    val CLIENT_NAME = stringPreferencesKey("client_name")
    val KICK_MODE = stringPreferencesKey("kick_mode")
    val LOGOUT_METHOD = stringPreferencesKey("logout_method")
    val BATCH_INTERVAL = longPreferencesKey("batch_interval_ms")
    val LOGIN_TIMEOUT = intPreferencesKey("login_timeout_sec")
    val CONFIRM_TIMEOUT = intPreferencesKey("confirm_timeout_sec")
    val MAX_ATTEMPTS = intPreferencesKey("max_login_attempts")
    val DEVICE_PREFS = stringPreferencesKey("device_prefs")
    val AUTOSTART = booleanPreferencesKey("autostart")
    val AUTO_LOGIN = booleanPreferencesKey("auto_login_on_boot")
    val KEEP_NOTIFICATION = booleanPreferencesKey("keep_notification")
}

/**
 * 完整配置快照。[password] 来自 [CredentialStore]，不落在 DataStore 里。
 */
data class AppSettings(
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
    override val devicePrefs: List<DevicePref> = emptyList(),
    val autostart: Boolean = false,
    val autoLoginOnBoot: Boolean = false,
    val keepNotification: Boolean = true
) : AppConfig {

    val hasCredentials: Boolean get() = username.isNotBlank() && !password.isNullOrEmpty()

    companion object {
        fun from(prefs: Preferences, password: String?): AppSettings = AppSettings(
            baseUrl = prefs[Keys.BASE_URL] ?: SrunPortalClient.DEFAULT_BASE_URL,
            acId = prefs[Keys.AC_ID] ?: SrunPortalClient.DEFAULT_AC_ID,
            username = prefs[Keys.USERNAME] ?: "",
            password = password,
            osName = prefs[Keys.OS_NAME] ?: SrunPortalClient.DEFAULT_OS_NAME,
            clientName = prefs[Keys.CLIENT_NAME] ?: SrunPortalClient.DEFAULT_CLIENT_NAME,
            kickMode = prefs[Keys.KICK_MODE] ?: Policy.PRESELECT_OLDEST,
            logoutMethod = prefs[Keys.LOGOUT_METHOD] ?: "dm",
            batchKickIntervalMs = prefs[Keys.BATCH_INTERVAL] ?: 800L,
            loginTimeoutMs = (prefs[Keys.LOGIN_TIMEOUT] ?: 30) * 1000,
            confirmTimeoutMs = (prefs[Keys.CONFIRM_TIMEOUT] ?: 90) * 1000L,
            maxLoginAttempts = prefs[Keys.MAX_ATTEMPTS] ?: 3,
            devicePrefs = parsePrefs(prefs[Keys.DEVICE_PREFS]),
            autostart = prefs[Keys.AUTOSTART] ?: false,
            autoLoginOnBoot = prefs[Keys.AUTO_LOGIN] ?: false,
            keepNotification = prefs[Keys.KEEP_NOTIFICATION] ?: true
        )

        private fun parsePrefs(json: String?): List<DevicePref> {
            if (json.isNullOrBlank()) return emptyList()
            return try {
                val arr = JSONArray(json)
                (0 until arr.length()).mapNotNull { i ->
                    val o = arr.optJSONObject(i) ?: return@mapNotNull null
                    DevicePref(
                        alias = o.optString("alias", ""),
                        priority = o.optInt("priority", 0),
                        lastIp = o.optString("last_ip", "")
                    )
                }
            } catch (e: Exception) {
                emptyList()
            }
        }

        fun encodePrefs(list: List<DevicePref>): String {
            val arr = JSONArray()
            list.forEach { p ->
                arr.put(
                    JSONObject()
                        .put("alias", p.alias)
                        .put("priority", p.priority)
                        .put("last_ip", p.lastIp)
                )
            }
            return arr.toString()
        }
    }
}

/** DataStore 读写 + Keystore 凭据的组合入口。 */
class ConfigRepository(context: Context) {

    private val appContext = context.applicationContext
    private val credentials = CredentialStore(appContext)

    /** 不含密码的配置流（密码变更不会触发它，避免无谓重组）。 */
    val settings: Flow<AppSettings> = appContext.configDataStore.data.map {
        AppSettings.from(it, null)
    }

    /** 取一份带密码的完整快照，供网络操作使用。 */
    suspend fun snapshot(): AppSettings {
        val base = settings.first()
        return base.copy(password = credentials.loadPassword())
    }

    suspend fun savePortal(baseUrl: String, acId: String) {
        appContext.configDataStore.edit {
            it[Keys.BASE_URL] = normalizeUrl(baseUrl)
            it[Keys.AC_ID] = acId.ifBlank { "1" }
        }
    }

    suspend fun saveCredentials(username: String, password: String?) {
        appContext.configDataStore.edit {
            it[Keys.USERNAME] = username.trim()
        }
        credentials.savePassword(password)
    }

    suspend fun saveBehavior(
        kickMode: String,
        logoutMethod: String,
        batchIntervalMs: Long,
        maxAttempts: Int
    ) {
        appContext.configDataStore.edit {
            it[Keys.KICK_MODE] = kickMode
            it[Keys.LOGOUT_METHOD] = logoutMethod
            it[Keys.BATCH_INTERVAL] = batchIntervalMs
            it[Keys.MAX_ATTEMPTS] = maxAttempts
        }
    }

    suspend fun saveStartup(autostart: Boolean, autoLogin: Boolean, keepNotification: Boolean) {
        appContext.configDataStore.edit {
            it[Keys.AUTOSTART] = autostart
            it[Keys.AUTO_LOGIN] = autoLogin
            it[Keys.KEEP_NOTIFICATION] = keepNotification
        }
    }

    suspend fun clearPassword() {
        credentials.clear()
    }

    fun hasPassword(): Boolean = credentials.hasPassword()

    private fun normalizeUrl(raw: String): String {
        var s = raw.trim()
        if (s.isEmpty()) return SrunPortalClient.DEFAULT_BASE_URL
        if (!s.startsWith("http://") && !s.startsWith("https://")) s = "http://$s"
        return s.trimEnd('/')
    }
}
