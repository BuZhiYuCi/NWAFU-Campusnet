package com.nwafu.campusnet.background

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import com.nwafu.campusnet.R
import com.nwafu.campusnet.data.ConfigRepository
import com.nwafu.campusnet.net.NetworkBinder
import com.nwafu.campusnet.portal.STATE_ONLINE
import com.nwafu.campusnet.portal.SrunPortalClient
import com.nwafu.campusnet.service.CampusNetService
import com.nwafu.campusnet.ui.MainActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/**
 * 常驻前台服务：对应桌面版的托盘常驻。
 *
 * Android 8+ 的后台限制决定了「开机自动认证 / 常驻监听」必须有前台服务，
 * 否则进程会被系统回收。通知栏同时充当桌面版的托盘菜单入口。
 */
class AuthForegroundService : Service() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private lateinit var repo: ConfigRepository

    override fun onCreate() {
        super.onCreate()
        repo = ConfigRepository(this)
        createChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForeground(NOTIFICATION_ID, buildNotification("正在检查状态…", null))
        when (intent?.action) {
            ACTION_LOGIN -> runLogin()
            ACTION_LOGOUT -> runLogout()
            else -> runRefresh()
        }
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    // ------------------------------------------------------------------

    private fun runRefresh() {
        scope.launch {
            val cfg = repo.snapshot()
            if (!cfg.hasCredentials) {
                updateNotification("未配置账号", null)
                return@launch
            }
            try {
                NetworkBinder.bindToWifi(this@AuthForegroundService)
                val (state, status, _) = SrunPortalClient(cfg.baseUrl).localState(cfg.username, cfg.password)
                val text = when (state) {
                    STATE_ONLINE -> "已在线 · ${status.ip ?: "-"}"
                    "offline" -> "未登录"
                    else -> "状态未知"
                }
                updateNotification(text, state)
            } catch (e: Exception) {
                updateNotification("检测失败：${e.message}", null)
            }
        }
    }

    private fun runLogin() {
        scope.launch {
            val cfg = repo.snapshot()
            if (!cfg.hasCredentials) {
                updateNotification("未配置账号", null)
                return@launch
            }
            updateNotification("正在登录…", null)
            try {
                NetworkBinder.bindToWifi(this@AuthForegroundService)
                val outcome = CampusNetService(SrunPortalClient(cfg.baseUrl), cfg).login()
                updateNotification(if (outcome.ok) "已在线" else "登录失败：${outcome.message}",
                    if (outcome.ok) STATE_ONLINE else null)
            } catch (e: Exception) {
                updateNotification("登录失败：${e.message}", null)
            }
        }
    }

    private fun runLogout() {
        scope.launch {
            val cfg = repo.snapshot()
            if (!cfg.hasCredentials) {
                updateNotification("未配置账号", null)
                return@launch
            }
            updateNotification("正在下线…", null)
            try {
                NetworkBinder.bindToWifi(this@AuthForegroundService)
                val outcome = CampusNetService(SrunPortalClient(cfg.baseUrl), cfg).logout()
                updateNotification(if (outcome.ok) "已下线" else "下线未确认：${outcome.message}", null)
            } catch (e: Exception) {
                updateNotification("下线失败：${e.message}", null)
            }
        }
    }

    // ------------------------------------------------------------------
    // 通知
    // ------------------------------------------------------------------

    private fun createChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val mgr = getSystemService(NotificationManager::class.java)
        if (mgr.getNotificationChannel(CHANNEL_ID) != null) return
        val channel = NotificationChannel(
            CHANNEL_ID, "校园网认证状态", NotificationManager.IMPORTANCE_LOW
        ).apply {
            description = "显示当前认证状态，并提供快捷登录/下线"
            setShowBadge(false)
        }
        mgr.createNotificationChannel(channel)
    }

    private fun buildNotification(text: String, state: String?): Notification {
        val openIntent = PendingIntent.getActivity(
            this, 0,
            Intent(this, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )

        val builder = NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("校园网认证")
            .setContentText(text)
            .setSmallIcon(R.drawable.ic_stat_campus)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setContentIntent(openIntent)
            .setPriority(NotificationCompat.PRIORITY_LOW)

        if (state == STATE_ONLINE) {
            builder.addAction(0, "下线", servicePendingIntent(ACTION_LOGOUT, 1))
        } else {
            builder.addAction(0, "登录", servicePendingIntent(ACTION_LOGIN, 2))
        }
        builder.addAction(0, "刷新", servicePendingIntent(ACTION_REFRESH, 3))
        return builder.build()
    }

    private fun servicePendingIntent(action: String, requestCode: Int): PendingIntent =
        PendingIntent.getService(
            this, requestCode,
            Intent(this, AuthForegroundService::class.java).setAction(action),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )

    private fun updateNotification(text: String, state: String?) {
        val mgr = getSystemService(NotificationManager::class.java)
        mgr.notify(NOTIFICATION_ID, buildNotification(text, state))
    }

    companion object {
        const val CHANNEL_ID = "campusnet_status"
        const val NOTIFICATION_ID = 1001
        const val ACTION_LOGIN = "com.nwafu.campusnet.LOGIN"
        const val ACTION_LOGOUT = "com.nwafu.campusnet.LOGOUT"
        const val ACTION_REFRESH = "com.nwafu.campusnet.REFRESH"

        fun start(context: Context, action: String? = null) {
            val intent = Intent(context, AuthForegroundService::class.java)
            if (action != null) intent.action = action
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, AuthForegroundService::class.java))
        }
    }
}
