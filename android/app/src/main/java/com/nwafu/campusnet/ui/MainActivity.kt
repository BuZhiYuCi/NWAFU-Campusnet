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
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
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
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
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
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Snackbar
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
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
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.nwafu.campusnet.R
import com.nwafu.campusnet.data.AppSettings
import com.nwafu.campusnet.portal.Device
import com.nwafu.campusnet.portal.Policy
import com.nwafu.campusnet.portal.STATE_OFFLINE

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
            MaterialTheme(
                colorScheme = lightColorScheme(
                    primary = Palette.Primary,
                    onPrimary = Color.White,
                    primaryContainer = Palette.PrimarySoft,
                    onPrimaryContainer = Palette.PrimaryDark,
                    background = Palette.Bg,
                    onBackground = Palette.Text,
                    surface = Palette.Card,
                    onSurface = Palette.Text,
                    surfaceVariant = Palette.CardSoft,
                    onSurfaceVariant = Palette.Muted,
                    outline = Palette.Border,
                    error = Palette.Offline
                )
            ) {
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
        containerColor = Palette.Bg,
        snackbarHost = {
            SnackbarHost(snackbar) { data ->
                Snackbar(
                    snackbarData = data,
                    containerColor = Palette.PrimaryDark,
                    contentColor = Color.White,
                    shape = Radius.Button
                )
            }
        },
        topBar = {
            // 桌面端没有独立标题栏，标题用主色加深；这里同样不用色块压顶，
            // 让整屏底色连成一片。
            TopAppBar(
                title = {
                    Text(
                        "校园网认证",
                        fontSize = 18.sp,
                        fontWeight = FontWeight.Bold
                    )
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = Palette.Bg,
                    titleContentColor = Palette.PrimaryDark,
                    actionIconContentColor = Palette.PrimaryDark
                ),
                actions = {
                    IconButton(onClick = { vm.refresh() }, enabled = !ui.busy) {
                        Icon(
                            Icons.Default.Refresh,
                            contentDescription = "刷新",
                            tint = if (ui.busy) Palette.Disabled else Palette.PrimaryDark
                        )
                    }
                    IconButton(onClick = { showSettings = true }) {
                        Icon(
                            Icons.Default.Settings,
                            contentDescription = "设置",
                            tint = Palette.PrimaryDark
                        )
                    }
                }
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(horizontal = 14.dp)
        ) {
            StatusCard(ui)
            Spacer(Modifier.height(12.dp))
            ActionRow(ui, onLogin = vm::login, onLogout = { pendingLogout = true })

            if (!ui.onWifi) {
                Spacer(Modifier.height(10.dp))
                HintCard("当前未连接 Wi-Fi。校园网认证必须连着校园 Wi-Fi，否则请求会走移动数据。")
            }
            if (!notifGranted) {
                Spacer(Modifier.height(10.dp))
                ActionHintCard(
                    text = "通知权限未开启：后台守护仍在运行，但状态栏看不到常驻通知，" +
                        "掉线时也不会收到提示。",
                    action = "去开启",
                    onAction = onRequestNotification
                )
            }

            Spacer(Modifier.height(14.dp))
            DeviceCard(ui, Modifier.weight(1f), onKick = { pendingKick = it })
            Spacer(Modifier.height(10.dp))
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

// ---------------------------------------------------------------------------
// 状态卡：徽标 + 状态灯 + 大字状态 + 明细（对应桌面端 header）
// ---------------------------------------------------------------------------

@Composable
private fun StatusCard(ui: UiState) {
    val accent = when {
        !ui.configured -> Palette.Unknown
        ui.busy -> Palette.Primary
        else -> Palette.stateColor(ui.state)
    }
    val stateText = when {
        !ui.configured -> "未设置账号"
        ui.busy -> ui.busyText.ifBlank { "正在检测…" }
        else -> ui.statusText
    }

    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = Radius.Card,
        colors = CardDefaults.cardColors(containerColor = Palette.Card),
        border = BorderStroke(1.dp, Palette.Border),
        elevation = CardDefaults.cardElevation(defaultElevation = 0.dp)
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Image(
                painter = painterResource(R.drawable.emblem_ui),
                contentDescription = null,
                modifier = Modifier.size(46.dp)
            )
            Spacer(Modifier.width(14.dp))
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(10.dp).background(accent, CircleShape))
                    Spacer(Modifier.width(8.dp))
                    Text(
                        stateText,
                        fontSize = 20.sp,
                        fontWeight = FontWeight.Bold,
                        color = if (ui.configured) accent else Palette.Muted,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                    if (ui.busy) {
                        Spacer(Modifier.width(10.dp))
                        CircularProgressIndicator(
                            modifier = Modifier.size(15.dp),
                            color = accent,
                            strokeWidth = 2.dp
                        )
                    }
                }
                Spacer(Modifier.height(4.dp))
                Text(
                    detailText(ui),
                    fontSize = 12.sp,
                    color = Palette.Muted,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis
                )
            }
        }
    }
}

/** 明细行：与桌面端 `detail_label` 的拼法一致（本机 IP / 账号 / 在线设备）。 */
private fun detailText(ui: UiState): String {
    if (!ui.configured) return "点右上角设置填写学号和密码"
    val bits = mutableListOf<String>()
    ui.myIp?.takeIf { it.isNotBlank() }?.let { bits += "本机 IP $it" }
    ui.settings.username.takeIf { it.isNotBlank() }?.let { bits += "账号 $it" }
    if (ui.devices.isNotEmpty()) bits += "在线设备 ${ui.devices.size} 台"
    return bits.joinToString(" · ").ifEmpty { "—" }
}

// ---------------------------------------------------------------------------
// 操作按钮：accent（实心绿）+ soft（淡绿底）两档，对应桌面端按钮风格
// ---------------------------------------------------------------------------

@Composable
private fun ActionRow(ui: UiState, onLogin: () -> Unit, onLogout: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        Button(
            onClick = onLogin,
            // 未连 Wi-Fi 时禁止认证：请求会走移动数据，源 IP 不是校园网 IP，
            // 结果要么失败，要么误操作到别人的会话上（实测踩过）。
            enabled = !ui.busy && ui.configured && ui.onWifi && !ui.online,
            modifier = Modifier
                .weight(1f)
                .height(46.dp),
            shape = Radius.Button,
            colors = ButtonDefaults.buttonColors(
                containerColor = Palette.Primary,
                contentColor = Color.White,
                disabledContainerColor = Color(0xFFB8DEC5),
                disabledContentColor = Color.White
            ),
            elevation = ButtonDefaults.buttonElevation(
                defaultElevation = 0.dp,
                pressedElevation = 0.dp,
                disabledElevation = 0.dp
            )
        ) {
            Text("一键登录", fontSize = 15.sp, fontWeight = FontWeight.Bold)
        }

        Button(
            onClick = onLogout,
            enabled = !ui.busy && ui.configured && ui.onWifi && ui.state != STATE_OFFLINE,
            modifier = Modifier
                .weight(1f)
                .height(46.dp),
            shape = Radius.Button,
            colors = ButtonDefaults.buttonColors(
                containerColor = Palette.PrimarySoft,
                contentColor = Palette.PrimaryDark,
                disabledContainerColor = Palette.CardSoft,
                disabledContentColor = Palette.Disabled
            ),
            elevation = ButtonDefaults.buttonElevation(
                defaultElevation = 0.dp,
                pressedElevation = 0.dp,
                disabledElevation = 0.dp
            )
        ) {
            Text("一键下线", fontSize = 15.sp)
        }
    }
}

// ---------------------------------------------------------------------------
// 设备卡：白卡 + 小标题 + 分隔线 + 斑马纹（对应桌面端 Treeview 卡片）
// ---------------------------------------------------------------------------

@Composable
private fun DeviceCard(ui: UiState, modifier: Modifier, onKick: (Device) -> Unit) {
    Card(
        modifier = modifier.fillMaxWidth(),
        shape = Radius.Card,
        colors = CardDefaults.cardColors(containerColor = Palette.Card),
        border = BorderStroke(1.dp, Palette.Border),
        elevation = CardDefaults.cardElevation(defaultElevation = 0.dp)
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(start = 16.dp, end = 16.dp, top = 13.dp, bottom = 11.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                "在线设备（${ui.devices.size}）",
                fontSize = 14.sp,
                fontWeight = FontWeight.Bold,
                color = Palette.PrimaryDark
            )
            Text(
                if (ui.devices.isEmpty()) "暂无" else "共 ${ui.devices.size} 台",
                fontSize = 12.sp,
                color = Palette.Muted
            )
        }
        HorizontalDivider(color = Palette.Border)

        if (ui.devices.isEmpty()) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f),
                contentAlignment = Alignment.Center
            ) {
                Text(
                    if (ui.busy) "正在获取…" else "当前没有在线设备",
                    fontSize = 13.sp,
                    color = Palette.Muted
                )
            }
        } else {
            LazyColumn(Modifier.weight(1f)) {
                itemsIndexed(ui.devices, key = { _, d -> d.ip }) { index, dev ->
                    DeviceRow(
                        device = dev,
                        isLocal = dev.ip == ui.myIp,
                        zebra = index % 2 == 1,
                        enabled = !ui.busy,
                        onKick = { onKick(dev) }
                    )
                    if (index != ui.devices.lastIndex) {
                        HorizontalDivider(color = Palette.Border)
                    }
                }
            }
        }
    }
}

@Composable
private fun DeviceRow(
    device: Device,
    isLocal: Boolean,
    zebra: Boolean,
    enabled: Boolean,
    onKick: () -> Unit
) {
    val bg = when {
        isLocal -> Palette.PrimaryTint
        zebra -> Palette.CardSoft
        else -> Palette.Card
    }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(bg)
            .padding(horizontal = 16.dp, vertical = 11.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    device.ip,
                    fontSize = 15.sp,
                    fontWeight = FontWeight.SemiBold,
                    color = Palette.Text
                )
                if (isLocal) {
                    Spacer(Modifier.width(6.dp))
                    Badge("本机")
                }
            }
            Spacer(Modifier.height(3.dp))
            Text(
                "${device.clientTypeLabel} · ${device.osName.ifBlank { "未知系统" }}" +
                    " · 已在线 ${device.onlineText()}",
                fontSize = 12.sp,
                color = Palette.Muted,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
        }
        // 本机不给"下线"入口：避免手滑把自己踢掉（桌面端同样只允许勾选他人）。
        if (!isLocal) {
            SoftChip("下线", enabled, onKick)
        }
    }
}

@Composable
private fun Badge(text: String) {
    Box(
        modifier = Modifier
            .background(Palette.PrimarySoft, Radius.Badge)
            .padding(horizontal = 6.dp, vertical = 1.dp)
    ) {
        Text(text, fontSize = 10.sp, color = Palette.PrimaryDark, fontWeight = FontWeight.Medium)
    }
}

@Composable
private fun SoftChip(text: String, enabled: Boolean, onClick: () -> Unit) {
    Surface(
        onClick = onClick,
        enabled = enabled,
        shape = Radius.Chip,
        color = if (enabled) Palette.PrimarySoft else Palette.CardSoft,
        border = BorderStroke(1.dp, Palette.Border),
        modifier = Modifier.height(32.dp)
    ) {
        Box(
            modifier = Modifier.padding(horizontal = 14.dp),
            contentAlignment = Alignment.Center
        ) {
            Text(
                text,
                fontSize = 13.sp,
                color = if (enabled) Palette.PrimaryDark else Palette.Disabled
            )
        }
    }
}

// ---------------------------------------------------------------------------
// 提示卡
// ---------------------------------------------------------------------------

@Composable
private fun HintCard(text: String) {
    Card(
        colors = CardDefaults.cardColors(containerColor = Palette.WarnBg),
        shape = Radius.Card,
        border = BorderStroke(1.dp, Palette.WarnBorder),
        elevation = CardDefaults.cardElevation(defaultElevation = 0.dp)
    ) {
        Text(
            text,
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 11.dp),
            fontSize = 12.sp,
            color = Palette.WarnText
        )
    }
}

/** 带一个跳转动作的提示卡：用于"通知权限没开"这类需要用户去处理的问题。 */
@Composable
private fun ActionHintCard(text: String, action: String, onAction: () -> Unit) {
    Card(
        colors = CardDefaults.cardColors(containerColor = Palette.WarnBg),
        shape = Radius.Card,
        border = BorderStroke(1.dp, Palette.WarnBorder),
        elevation = CardDefaults.cardElevation(defaultElevation = 0.dp)
    ) {
        Column(Modifier.padding(start = 14.dp, end = 6.dp, top = 11.dp, bottom = 4.dp)) {
            Text(text, fontSize = 12.sp, color = Palette.WarnText)
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                TextButton(onClick = onAction) {
                    Text(
                        action,
                        fontSize = 13.sp,
                        color = Palette.PrimaryDark,
                        fontWeight = FontWeight.Medium
                    )
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// 对话框
// ---------------------------------------------------------------------------

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
        containerColor = Palette.Card,
        shape = Radius.Card,
        title = {
            Text(title, fontSize = 17.sp, fontWeight = FontWeight.Bold, color = Palette.Text)
        },
        text = { Text(text, fontSize = 14.sp, color = Palette.Muted) },
        confirmButton = {
            TextButton(onClick = onConfirm) {
                Text(confirmText, color = Palette.Offline, fontWeight = FontWeight.Medium)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("取消", color = Palette.Muted) }
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

    val fieldColors = OutlinedTextFieldDefaults.colors(
        focusedBorderColor = Palette.Primary,
        unfocusedBorderColor = Palette.Border,
        focusedLabelColor = Palette.PrimaryDark,
        unfocusedLabelColor = Palette.Muted,
        cursorColor = Palette.Primary,
        focusedTextColor = Palette.Text,
        unfocusedTextColor = Palette.Text
    )

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = Palette.Card,
        shape = Radius.Card,
        title = {
            Text("设置", fontSize = 17.sp, fontWeight = FontWeight.Bold, color = Palette.Text)
        },
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
                    shape = Radius.Chip,
                    colors = fieldColors,
                    modifier = Modifier.fillMaxWidth()
                )
                OutlinedTextField(
                    value = acId,
                    onValueChange = { acId = it },
                    label = { Text("ac_id") },
                    singleLine = true,
                    shape = Radius.Chip,
                    colors = fieldColors,
                    modifier = Modifier.fillMaxWidth()
                )
                OutlinedTextField(
                    value = username,
                    onValueChange = { username = it },
                    label = { Text("学号 / 账号") },
                    singleLine = true,
                    shape = Radius.Chip,
                    colors = fieldColors,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    modifier = Modifier.fillMaxWidth()
                )
                OutlinedTextField(
                    value = password,
                    onValueChange = { password = it },
                    label = {
                        Text(if (settings.password.isNullOrEmpty()) "密码" else "密码（留空则不修改）")
                    },
                    singleLine = true,
                    shape = Radius.Chip,
                    colors = fieldColors,
                    visualTransformation = PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                    modifier = Modifier.fillMaxWidth()
                )

                SectionLabel("下线方式")
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    ModeChip("dm（推荐）", logoutMethod == "dm") { logoutMethod = "dm" }
                    ModeChip("portal", logoutMethod == "portal") { logoutMethod = "portal" }
                }

                SectionLabel("满员时预选哪台设备下线")
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
            }) { Text("保存", color = Palette.PrimaryDark, fontWeight = FontWeight.Bold) }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("取消", color = Palette.Muted) }
        }
    )
}

@Composable
private fun SectionLabel(text: String) {
    Text(
        text,
        fontSize = 12.sp,
        color = Palette.PrimaryDark,
        fontWeight = FontWeight.Medium
    )
}

@Composable
private fun ModeChip(label: String, selected: Boolean, onClick: () -> Unit) {
    Surface(
        onClick = onClick,
        shape = Radius.Chip,
        color = if (selected) Palette.Primary else Palette.PrimaryTint,
        border = BorderStroke(1.dp, if (selected) Palette.Primary else Palette.Border),
        modifier = Modifier.height(34.dp)
    ) {
        Box(
            modifier = Modifier.padding(horizontal = 14.dp),
            contentAlignment = Alignment.Center
        ) {
            Text(
                label,
                fontSize = 13.sp,
                color = if (selected) Color.White else Palette.PrimaryDark,
                fontWeight = if (selected) FontWeight.Medium else FontWeight.Normal
            )
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
        Text(label, fontSize = 14.sp, color = Palette.Text)
        Switch(
            checked = checked,
            onCheckedChange = onChange,
            colors = SwitchDefaults.colors(
                checkedThumbColor = Color.White,
                checkedTrackColor = Palette.Primary,
                checkedBorderColor = Palette.Primary,
                uncheckedThumbColor = Color.White,
                uncheckedTrackColor = Palette.Disabled,
                uncheckedBorderColor = Palette.Disabled
            )
        )
    }
}
