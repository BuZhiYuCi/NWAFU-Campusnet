package com.nwafu.campusnet.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.nwafu.campusnet.background.AuthForegroundService
import com.nwafu.campusnet.data.AppSettings
import com.nwafu.campusnet.data.ConfigRepository
import com.nwafu.campusnet.net.NetworkBinder
import com.nwafu.campusnet.portal.Device
import com.nwafu.campusnet.portal.NOT_ONLINE
import com.nwafu.campusnet.portal.STATE_OFFLINE
import com.nwafu.campusnet.portal.STATE_ONLINE
import com.nwafu.campusnet.portal.STATE_UNKNOWN
import com.nwafu.campusnet.portal.SrunPortalClient
import com.nwafu.campusnet.service.CampusNetService
import com.nwafu.campusnet.service.Outcome
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class UiState(
    val busy: Boolean = false,
    val busyText: String = "",
    val state: String = STATE_UNKNOWN,
    val statusText: String = "未检测",
    val myIp: String? = null,
    val devices: List<Device> = emptyList(),
    val message: String? = null,
    val settings: AppSettings = AppSettings(),
    val configured: Boolean = false,
    val onWifi: Boolean = true
) {
    val online: Boolean get() = state == STATE_ONLINE
    val offline: Boolean get() = state == STATE_OFFLINE
}

class MainViewModel(app: Application) : AndroidViewModel(app) {

    private val repo = ConfigRepository(app)
    private val _ui = MutableStateFlow(UiState())
    val ui: StateFlow<UiState> = _ui.asStateFlow()

    /** 忙碌期间收到的刷新请求，本轮结束后补跑一次（对应桌面版 D-00 的修复）。 */
    private var refreshPending = false

    /** 前台服务只启动一次，避免每次配置变更都重复 startForeground。 */
    private var serviceStarted = false

    init {
        viewModelScope.launch {
            repo.settings.collect { s ->
                val configured = s.username.isNotBlank() && repo.hasPassword()
                _ui.update {
                    it.copy(
                        settings = s,
                        configured = configured,
                        onWifi = NetworkBinder.isOnWifi(getApplication())
                    )
                }
                // 常驻通知（对应桌面版托盘）：配置好账号后拉起前台服务，
                // 否则 App 退到后台就会被系统回收，开机自启也无从谈起。
                if (configured && !serviceStarted) {
                    serviceStarted = true
                    AuthForegroundService.start(getApplication())
                }
            }
        }
        refresh()
    }

    fun consumeMessage() = _ui.update { it.copy(message = null) }

    // ------------------------------------------------------------------
    // 查询
    // ------------------------------------------------------------------

    fun refresh() {
        if (_ui.value.busy) {
            refreshPending = true
            return
        }
        viewModelScope.launch {
            _ui.update { it.copy(busy = true, busyText = "正在检测…") }
            var text = "检测失败"
            var state = STATE_UNKNOWN
            try {
                val cfg = repo.snapshot()
                if (cfg.username.isBlank() || cfg.password.isNullOrEmpty()) {
                    text = "未配置账号"
                    return@launch
                }
                val result = withContext(Dispatchers.IO) {
                    NetworkBinder.bindToWifi(getApplication())
                    val client = SrunPortalClient(baseUrl = cfg.baseUrl, timeoutMs = 8000)
                    val triple = client.localState(cfg.username, cfg.password)
                    // 协议层的 localState 在"确认在线"后直接返回空设备列表
                    // （桌面版为省一次请求如此设计，CLI 会另外单独查设备）。
                    // 界面必须展示列表，所以这里补一次查询。
                    if (triple.first == STATE_ONLINE && triple.third.isEmpty()) {
                        val devices = try {
                            client.onlineDevices(cfg.username, cfg.password)
                        } catch (e: Exception) {
                            emptyList()
                        }
                        Triple(triple.first, triple.second, devices)
                    } else {
                        triple
                    }
                }
                state = result.first
                val status = result.second
                val devices = result.third
                text = when (state) {
                    STATE_ONLINE -> "已在线"
                    STATE_OFFLINE -> "未登录"
                    else -> if (status.rateLimited) "服务端限流，稍后重试" else "状态未知"
                }
                _ui.update {
                    it.copy(
                        state = state,
                        statusText = text,
                        myIp = status.ip,
                        devices = devices,
                        onWifi = NetworkBinder.isOnWifi(getApplication())
                    )
                }
            } catch (e: Exception) {
                text = "检测失败：${e.message ?: e.javaClass.simpleName}"
                state = STATE_UNKNOWN
            } finally {
                // 无论如何都要把 busy 放掉：这是桌面版"卡在正在检测…"的教训。
                _ui.update { it.copy(busy = false, busyText = "", state = state, statusText = text) }
                if (refreshPending) {
                    refreshPending = false
                    refresh()
                }
            }
        }
    }

    // ------------------------------------------------------------------
    // 登录 / 下线
    // ------------------------------------------------------------------

    fun login() {
        if (_ui.value.busy) return
        viewModelScope.launch {
            _ui.update { it.copy(busy = true, busyText = "正在登录…") }
            try {
                val cfg = repo.snapshot()
                val outcome = withContext(Dispatchers.IO) {
                    NetworkBinder.bindToWifi(getApplication())
                    service(cfg).login()
                }
                _ui.update { it.copy(message = describe(outcome)) }
            } catch (e: Exception) {
                _ui.update { it.copy(message = "登录失败：${e.message}") }
            } finally {
                _ui.update { it.copy(busy = false, busyText = "") }
                refresh()
            }
        }
    }

    fun logout() {
        if (_ui.value.busy) return
        viewModelScope.launch {
            _ui.update { it.copy(busy = true, busyText = "正在下线…") }
            try {
                val cfg = repo.snapshot()
                val outcome = withContext(Dispatchers.IO) {
                    NetworkBinder.bindToWifi(getApplication())
                    service(cfg).logout()
                }
                _ui.update { it.copy(message = describe(outcome)) }
            } catch (e: Exception) {
                _ui.update { it.copy(message = "下线失败：${e.message}") }
            } finally {
                _ui.update { it.copy(busy = false, busyText = "") }
                refresh()
            }
        }
    }

    fun kick(ip: String) {
        if (_ui.value.busy) return
        viewModelScope.launch {
            _ui.update { it.copy(busy = true, busyText = "正在下线设备…") }
            try {
                val cfg = repo.snapshot()
                val results = withContext(Dispatchers.IO) {
                    NetworkBinder.bindToWifi(getApplication())
                    service(cfg).kick(listOf(ip))
                }
                val res = results.firstOrNull()
                val text = when {
                    res == null -> "操作失败"
                    res.ok -> "$ip 已下线"
                    res.kind == NOT_ONLINE -> "$ip 本来就不在线"
                    else -> "$ip 下线失败：${res.message}"
                }
                _ui.update { it.copy(message = text) }
            } catch (e: Exception) {
                _ui.update { it.copy(message = "下线失败：${e.message}") }
            } finally {
                _ui.update { it.copy(busy = false, busyText = "") }
                refresh()
            }
        }
    }

    // ------------------------------------------------------------------
    // 设置
    // ------------------------------------------------------------------

    fun saveSettings(
        baseUrl: String,
        acId: String,
        username: String,
        password: String?,
        kickMode: String,
        logoutMethod: String,
        autostart: Boolean,
        autoLogin: Boolean
    ) {
        viewModelScope.launch {
            repo.savePortal(baseUrl, acId)
            repo.saveCredentials(username, password)
            repo.saveBehavior(kickMode, logoutMethod, 800, 3)
            repo.saveStartup(autostart, autoLogin, true)
            _ui.update { it.copy(message = "设置已保存") }
            refresh()
        }
    }

    private fun service(cfg: AppSettings): CampusNetService =
        CampusNetService(SrunPortalClient(baseUrl = cfg.baseUrl, timeoutMs = 8000), cfg)

    private fun describe(outcome: Outcome): String = buildString {
        append(outcome.message)
        if (outcome.kicked.isNotEmpty()) {
            append("（已下线 ")
            append(outcome.kicked.joinToString("、"))
            append("）")
        }
    }
}
