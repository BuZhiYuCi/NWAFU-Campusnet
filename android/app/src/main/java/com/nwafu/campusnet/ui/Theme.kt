package com.nwafu.campusnet.ui

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.nwafu.campusnet.portal.STATE_OFFLINE
import com.nwafu.campusnet.portal.STATE_ONLINE

/**
 * 配色与桌面端 `src/campusnet/ui/theme.py` 一一对应。
 *
 * 桌面端定的是"有生机的淡绿"：底色带绿意、主操作用明亮草绿、在线用更饱和的绿、
 * 离线用柔和珊瑚红。移动端沿用同一套色值，两端看起来才是同一个产品，
 * 而不是两个各自为政的 App。
 */
object Palette {
    // 底色与卡片
    val Bg = Color(0xFFEEF7F0)          // 页面底色：极淡的绿
    val Card = Color(0xFFFFFFFF)        // 卡片
    val CardSoft = Color(0xFFF5FBF7)    // 次级卡片 / 斑马纹
    val Border = Color(0xFFD6E9DC)      // 分隔线与描边

    // 主色
    val Primary = Color(0xFF3FB268)     // 明亮的草绿
    val PrimaryDark = Color(0xFF2E8B50) // 加深（标题、次级按钮文字）
    val PrimarySoft = Color(0xFFDCF2E3) // 淡底（次级按钮、表头）
    val PrimaryTint = Color(0xFFEAF8EE) // 更淡的底（本机行、悬停）

    // 文字
    val Text = Color(0xFF1D2F25)        // 带绿调的深灰
    val Muted = Color(0xFF69806F)
    val Disabled = Color(0xFFAFC0B4)

    // 状态
    val Online = Color(0xFF2FA85C)
    val Offline = Color(0xFFE4796F)
    val Unknown = Color(0xFF9DB0A4)

    // 提示卡：桌面端没有独立警示色，这里取 OFFLINE 同族的淡底，
    // 免得在一个绿调界面里突然冒出一块橙色。
    val WarnBg = Color(0xFFFDEDEB)
    val WarnBorder = Color(0xFFF5D2CD)
    val WarnText = Color(0xFFB4453B)

    fun stateColor(state: String): Color = when (state) {
        STATE_ONLINE -> Online
        STATE_OFFLINE -> Offline
        else -> Unknown
    }
}

/** 圆角与桌面端保持一致：按钮"只要一点弧度"，最多不超过高度的三分之一。 */
object Radius {
    val Card = RoundedCornerShape(14.dp)
    val Button = RoundedCornerShape(10.dp)
    val Chip = RoundedCornerShape(8.dp)
    val Badge = RoundedCornerShape(5.dp)
}
