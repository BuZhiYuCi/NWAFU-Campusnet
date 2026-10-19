package com.nwafu.campusnet.net

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Network

/**
 * 把本进程的网络绑定到 Wi-Fi。
 *
 * **这是安卓版最关键的一处架构决定。**
 *
 * Android 在连上「无法访问互联网」的 Wi-Fi（校园网正是如此）时，会保持 Wi-Fi
 * 连接但把默认路由切回移动数据。此时如果直接发认证请求：
 * - 请求从 4G 出口发出，源 IP 不是校园网 IP，门户根本认不出是谁；
 * - 即使侥幸到达，认证的也只是一台无关的移动设备。
 *
 * `bindProcessToNetwork()` 把整个进程的 socket 固定到 Wi-Fi 网络，
 * 从根上避免这个问题。桌面版不存在这个问题（Windows 不会自动切换默认路由）。
 *
 * 返回 false 表示当前没有可用的 Wi-Fi（用户可能用的是流量），
 * 此时不做绑定，走系统默认路由。
 */
object NetworkBinder {

    fun bindToWifi(context: Context): Boolean {
        val cm = context.getSystemService(ConnectivityManager::class.java) ?: return false
        val wifi = findWifi(cm) ?: return false
        return try {
            cm.bindProcessToNetwork(wifi)
        } catch (e: Exception) {
            false
        }
    }

    /** 解除绑定，恢复系统默认路由。 */
    fun unbind(context: Context) {
        try {
            context.getSystemService(ConnectivityManager::class.java)
                ?.bindProcessToNetwork(null)
        } catch (e: Exception) {
            // ignore
        }
    }

    fun currentWifi(context: Context): Network? {
        val cm = context.getSystemService(ConnectivityManager::class.java) ?: return null
        return findWifi(cm)
    }

    /** 当前是否连着 Wi-Fi。 */
    fun isOnWifi(context: Context): Boolean = currentWifi(context) != null

    private fun findWifi(cm: ConnectivityManager): Network? =
        cm.allNetworks.firstOrNull { network ->
            val caps: NetworkCapabilities = cm.getNetworkCapabilities(network) ?: return@firstOrNull false
            caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
        }
}
