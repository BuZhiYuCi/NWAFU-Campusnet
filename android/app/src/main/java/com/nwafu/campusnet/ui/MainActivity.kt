package com.nwafu.campusnet.ui

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.app.ActivityCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.nwafu.campusnet.data.AppSettings
import com.nwafu.campusnet.portal.Device
import com.nwafu.campusnet.portal.Policy
import com.nwafu.campusnet.portal.STATE_OFFLINE

private val CampusBlue = Color(0xFF0D47A1)
private val CampusBlueLight = Color(0xFF1565C0)
private val OkGreen = Color(0xFF2E7D32)
private val WarnOrange = Color(0xFFEF6C00)
private val MutedGrey = Color(0xFF6B7280)

class MainActivity : ComponentActivity() {

    /**
     * 通知权限是否已授予。
     * 权限被拒时前台服务依然能跑，但常驻通知完全不可见——用户会以为
     * "后台没在守护"，所以必须在界面上把这件事说清楚（见 T-A07）。
     */
    private var notifGranted by mutableStateOf(true)

    /** 是否已经弹过一次系统授权框。用来区分"从没问过"和"问过被永久拒绝"。 */
    private var notifAsked = false

    private val notificationPermission =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            notifGranted = granted
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        notifGranted = hasNotificationPermission()
        requestNotificationPermission()
        setContent {
            MaterialTheme(colorScheme = lightColorScheme(primary = CampusBlue)) {
                val vm: MainViewModel = viewModel()
                MainScreen(
                    vm = vm,
                    notifGranted = notifGranted,
                    onRequestNotification = { onNotifHintClick() }
                )
            }
        }
    }

    override fun onResume() {
        super.onResume()
        // 用户可能刚从系统设置里改了通知开关，回到前台要重新读一次。
        notifGranted = hasNotificationPermission()
    }

    /** 只看运行时权限本身（Android 13 以下恒为 true）。 */
    private fun isRuntimePermissionGranted(): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return true
        return ContextCompat.checkSelfPermission(
            this, Manifest.permission.POST_NOTIFICATIONS
        ) == PackageManager.PERMISSION_GRANTED
    }

    /** 通知最终能不能显示：运行时权限 + 应用级"允许通知"总开关，两个都要过。 */
    private fun hasNotificationPermission(): Boolean {
        if (!isRuntimePermissionGranted()) return false
        // 用户在系统设置里把"允许通知"总开关关掉时，权限本身仍是 granted，
        // 但通知一条都不会显示。只查 checkSelfPermission 会漏判这种情况，
        // 必须再问一次通知管理器（实测见 T-A07）。
        return NotificationManagerCompat.from(this).areNotificationsEnabled()
    }

    /** Android 13+ 通知需要运行时授权，否则常驻通知不显示。 */
    private fun requestNotificationPermission() {
        if (isRuntimePermissionGranted()) return
        notifAsked = true
        notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
    }

    /** 点击"去开启"：还能弹窗就弹窗，弹不出来才跳系统设置。 */
    private fun onNotifHintClick() {
        if (!isRuntimePermissionGranted()) {
            val canPrompt = !notifAsked || ActivityCompat.shouldShowRequestPermissionRationale(
                this, Manifest.permission.POST_NOTIFICATIONS
            )
            if (canPrompt) {
                notifAsked = true
                notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
                return
            }
        }
        // 两种情况只能去设置：权限被"不再询问"永久拒绝，或权限还在但总开关被关。
        openNotificationSettings()
    }

    /** 权限被"不再询问"后只能跳系统设置，这里直接落到本应用的通知页。 */
    private fun openNotificationSettings() {
        val intent = Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
            .putExtra(Settings.EXTRA_APP_PACKAGE, packageName)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        try {
            startActivity(intent)
        } catch (e: Exception) {
            startActivity(
                Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
                    .setData(Uri.fromParts("package", packageName, null))
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MainScreen(
    vm: MainViewModel,
    notifGranted: Boolean = true,
    onRequestNotification: () -> Unit = {}
) {
    val ui by vm.ui.collectAsState()
    val snackbar = remember { SnackbarHostState() }
    var showSettings by remember { mutableStateOf(false) }
    var pendingLogout by remember { mutableStateOf(false) }
    var pendingKick by remember { mutableStateOf<Device?>(null) }

    LaunchedEffect(ui.message) {
        ui.message?.let {
            snackbar.showSnackbar(it)
            vm.consumeMessage()
        }
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = { Text("校园网认证", fontWeight = FontWeight.SemiBold) },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = CampusBlue,
                    titleContentColor = Color.White,
                    actionIconContentColor = Color.White
                ),
                actions = {
                    IconButton(onClick = { vm.refresh() }, enabled = !ui.busy) {
                        Icon(Icons.Default.Refresh, contentDescription = "刷新")
                    }
                    IconButton(onClick = { showSettings = true }) {
                        Icon(Icons.Default.Settings, contentDescription = "设置")
                    }
                }
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(16.dp)
        ) {
            StatusCard(ui)
            Spacer(Modifier.height(16.dp))
            ActionRow(ui, onLogin = vm::login, onLogout = { pendingLogout = true })

            if (!ui.onWifi) {
                Spacer(Modifier.height(12.dp))
                HintCard("当前未连接 Wi-Fi。校园网认证必须连着校园 Wi-Fi，否则请求会走移动数据。")
            }

            if (!notifGranted) {
                Spacer(Modifier.height(12.dp))
                ActionHintCard(
                    text = "通知权限未开启：后台守护仍在运行，但状态栏看不到常驻通知，" +
                        "掉线时也不会收到提示。",
                    action = "去开启",
                    onAction = onRequestNotification
                )
            }

            Spacer(Modifier.height(20.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    "在线设备（${ui.devices.size}）",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold
                )
                if (ui.devices.isEmpty() && !ui.busy) {
                    Text("暂无", color = MutedGrey, fontSize = 13.sp)
                }
            }
            Spacer(Modifier.height(8.dp))

            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                items(ui.devices, key = { it.ip }) { dev ->
                    DeviceRow(
                        device = dev,
                        isLocal = dev.ip == ui.myIp,
                        enabled = !ui.busy,
                        onKick = { pendingKick = dev }
                    )
                }
            }
        }
    }

    if (showSettings) {
        SettingsDialog(
            settings = ui.settings,
            onDismiss = { showSettings = false },
            onSave = { baseUrl, acId, user, pwd, kickMode, logoutMethod, autostart, autoLogin ->
                vm.saveSettings(baseUrl, acId, user, pwd, kickMode, logoutMethod, autostart, autoLogin)
                showSettings = false
            }
        )
    }

    if (pendingLogout) {
        ConfirmDialog(
            title = "确认下线？",
            text = "下线后本机将立即断网，在线名额会被释放。需要重新认证才能上网。",
            confirmText = "立即下线",
            onConfirm = {
                pendingLogout = false
                vm.logout()
            },
            onDismiss = { pendingLogout = false }
        )
    }

    pendingKick?.let { dev ->
        ConfirmDialog(
            title = "下线这台设备？",
            text = "${dev.ip}（${dev.clientTypeLabel}，已在线 ${dev.onlineText()}）将被强制下线。",
            confirmText = "下线",
            onConfirm = {
                pendingKick = null
                vm.kick(dev.ip)
            },
            onDismiss = { pendingKick = null }
        )
    }
}

@Composable
private fun StatusCard(ui: UiState) {
    val accent = when {
        ui.online -> OkGreen
        ui.offline -> MutedGrey
        ui.busy -> CampusBlueLight
        else -> WarnOrange
    }
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = Color.White),
        elevation = CardDefaults.cardElevation(defaultElevation = 2.dp)
    ) {
        Column(Modifier.padding(20.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    Modifier
                        .size(10.dp)
                        .background(accent, CircleShape)
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    if (ui.busy) ui.busyText else ui.statusText,
                    fontSize = 20.sp,
                    fontWeight = FontWeight.Bold,
                    color = accent
                )
                if (ui.busy) {
                    Spacer(Modifier.width(12.dp))
                    CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp)
                }
            }
            Spacer(Modifier.height(10.dp))
            HorizontalDivider(color = Color(0xFFEEEEEE))
            Spacer(Modifier.height(10.dp))
            InfoLine("本机 IP", ui.myIp ?: "-")
            InfoLine("在线设备", "${ui.devices.size} 台")
            if (!ui.configured) {
                Spacer(Modifier.height(6.dp))
                Text("尚未设置账号密码，点右上角齿轮配置。", color = WarnOrange, fontSize = 13.sp)
            }
        }
    }
}

@Composable
private fun InfoLine(label: String, value: String) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 2.dp),
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(label, color = MutedGrey, fontSize = 13.sp)
        Text(value, fontSize = 13.sp, fontWeight = FontWeight.Medium)
    }
}

@Composable
private fun ActionRow(ui: UiState, onLogin: () -> Unit, onLogout: () -> Unit) {
    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Button(
            onClick = onLogin,
            // 未连 Wi-Fi 时禁止认证：请求会走移动数据，源 IP 不是校园网 IP，
            // 结果要么失败，要么误操作到别人的会话上（实测踩过）。
            enabled = !ui.busy && ui.configured && ui.onWifi && !ui.online,
            modifier = Modifier
                .weight(1f)
                .height(48.dp),
            shape = RoundedCornerShape(12.dp)
        ) {
            Text("一键登录", fontSize = 16.sp)
        }
        OutlinedButton(
            onClick = onLogout,
            enabled = !ui.busy && ui.configured && ui.onWifi && ui.state != STATE_OFFLINE,
            modifier = Modifier
                .weight(1f)
                .height(48.dp),
            shape = RoundedCornerShape(12.dp),
            colors = ButtonDefaults.outlinedButtonColors(contentColor = Color(0xFFC62828))
        ) {
            Text("下线", fontSize = 16.sp)
        }
    }
}

@Composable
private fun HintCard(text: String) {
    Card(
        colors = CardDefaults.cardColors(containerColor = Color(0xFFFFF3E0)),
        shape = RoundedCornerShape(12.dp)
    ) {
        Text(
            text,
            modifier = Modifier.padding(14.dp),
            fontSize = 13.sp,
            color = Color(0xFF8D6E63)
        )
    }
}

/** 带一个跳转动作的提示卡：用于"通知权限没开"这类需要用户去处理的问题。 */
@Composable
private fun ActionHintCard(text: String, action: String, onAction: () -> Unit) {
    Card(
        colors = CardDefaults.cardColors(containerColor = Color(0xFFFFF3E0)),
        shape = RoundedCornerShape(12.dp)
    ) {
        Column(Modifier.padding(start = 14.dp, end = 6.dp, top = 14.dp, bottom = 6.dp)) {
            Text(text, fontSize = 13.sp, color = Color(0xFF8D6E63))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                TextButton(onClick = onAction) {
                    Text(action, fontSize = 13.sp, color = CampusBlue, fontWeight = FontWeight.Medium)
                }
            }
        }
    }
}

@Composable
private fun DeviceRow(device: Device, isLocal: Boolean, enabled: Boolean, onKick: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(containerColor = Color.White),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp)
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 14.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(device.ip, fontWeight = FontWeight.SemiBold, fontSize = 15.sp)
                    if (isLocal) {
                        Spacer(Modifier.width(6.dp))
                        Box(
                            Modifier
                                .background(Color(0xFFE3F2FD), RoundedCornerShape(4.dp))
                                .padding(horizontal = 6.dp, vertical = 2.dp)
                        ) {
                            Text("本机", fontSize = 11.sp, color = CampusBlue)
                        }
                    }
                }
                Spacer(Modifier.height(3.dp))
                Text(
                    "${device.clientTypeLabel} · ${device.osName.ifBlank { "未知系统" }} · 已在线 ${device.onlineText()}",
                    fontSize = 12.sp,
                    color = MutedGrey
                )
            }
            if (!isLocal) {
                TextButton(onClick = onKick, enabled = enabled) {
                    Text("下线", color = Color(0xFFC62828), fontSize = 13.sp)
                }
            }
        }
    }
}

@Composable
private fun ConfirmDialog(
    title: String,
    text: String,
    confirmText: String,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = { Text(text) },
        confirmButton = {
            TextButton(onClick = onConfirm) {
                Text(confirmText, color = Color(0xFFC62828))
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("取消") }
        }
    )
}

@Composable
private fun SettingsDialog(
    settings: AppSettings,
    onDismiss: () -> Unit,
    onSave: (String, String, String, String?, String, String, Boolean, Boolean) -> Unit
) {
    var baseUrl by remember { mutableStateOf(settings.baseUrl) }
    var acId by remember { mutableStateOf(settings.acId) }
    var username by remember { mutableStateOf(settings.username) }
    var password by remember { mutableStateOf("") }
    var kickMode by remember { mutableStateOf(settings.kickMode) }
    var logoutMethod by remember { mutableStateOf(settings.logoutMethod) }
    var autostart by remember { mutableStateOf(settings.autostart) }
    var autoLogin by remember { mutableStateOf(settings.autoLoginOnBoot) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("设置") },
        text = {
            Column(
                Modifier
                    .fillMaxWidth()
                    .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                OutlinedTextField(
                    value = baseUrl,
                    onValueChange = { baseUrl = it },
                    label = { Text("门户地址") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
                OutlinedTextField(
                    value = acId,
                    onValueChange = { acId = it },
                    label = { Text("ac_id") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
                OutlinedTextField(
                    value = username,
                    onValueChange = { username = it },
                    label = { Text("学号 / 账号") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    modifier = Modifier.fillMaxWidth()
                )
                OutlinedTextField(
                    value = password,
                    onValueChange = { password = it },
                    label = { Text(if (settings.password.isNullOrEmpty()) "密码" else "密码（留空则不修改）") },
                    singleLine = true,
                    visualTransformation = PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                    modifier = Modifier.fillMaxWidth()
                )

                Text("下线方式", fontSize = 13.sp, color = MutedGrey)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    ModeChip("dm（推荐）", logoutMethod == "dm") { logoutMethod = "dm" }
                    ModeChip("portal", logoutMethod == "portal") { logoutMethod = "portal" }
                }

                Text("满员时预选哪台设备下线", fontSize = 13.sp, color = MutedGrey)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    ModeChip("最久的一台", kickMode == Policy.PRESELECT_OLDEST) {
                        kickMode = Policy.PRESELECT_OLDEST
                    }
                    ModeChip("手动选择", kickMode == Policy.MANUAL) { kickMode = Policy.MANUAL }
                }

                SwitchRow("开机自动认证", autostart) { autostart = it }
                SwitchRow("启动后自动登录", autoLogin) { autoLogin = it }
            }
        },
        confirmButton = {
            TextButton(onClick = {
                onSave(
                    baseUrl, acId, username,
                    password.ifEmpty { null },
                    kickMode, logoutMethod, autostart, autoLogin
                )
            }) { Text("保存") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } }
    )
}

@Composable
private fun ModeChip(label: String, selected: Boolean, onClick: () -> Unit) {
    if (selected) {
        Button(onClick = onClick, shape = RoundedCornerShape(8.dp)) {
            Text(label, fontSize = 13.sp)
        }
    } else {
        OutlinedButton(onClick = onClick, shape = RoundedCornerShape(8.dp)) {
            Text(label, fontSize = 13.sp)
        }
    }
}

@Composable
private fun SwitchRow(label: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(label, fontSize = 14.sp)
        Switch(checked = checked, onCheckedChange = onChange)
    }
}

/** 用 [collectAsState] 直接订阅，无需额外依赖。 */
