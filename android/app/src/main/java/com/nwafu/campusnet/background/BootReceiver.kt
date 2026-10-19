package com.nwafu.campusnet.background

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.nwafu.campusnet.data.ConfigRepository
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking

/**
 * 开机自启：对应桌面版写 HKCU\...\Run 注册表项。
 *
 * Android 上必须由 BOOT_COMPLETED 广播触发，且系统只给约 10 秒执行时间，
 * 所以这里只做「读配置 → 起前台服务」，真正的网络请求交给 Service。
 *
 * 注意：国产 ROM（MIUI/EMUI/ColorOS 等）默认会拦截自启动，用户需要在
 * 系统的「自启动管理」里手动放行，这一点无法由 App 自己绕过。
 */
class BootReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        val action = intent.action
        if (action != Intent.ACTION_BOOT_COMPLETED &&
            action != "android.intent.action.QUICKBOOT_POWERON"
        ) {
            return
        }

        val pending = goAsync()
        try {
            val repo = ConfigRepository(context)
            // 广播里没有协程作用域，只能短阻塞读一次配置
            val settings = runBlocking { repo.settings.first() }
            if (!settings.autostart) return

            AuthForegroundService.start(context)
            if (settings.autoLoginOnBoot) {
                AuthForegroundService.start(context, AuthForegroundService.ACTION_LOGIN)
            }
        } catch (e: Exception) {
            // 开机流程里抛异常会拖慢系统，吞掉即可
        } finally {
            pending.finish()
        }
    }
}
