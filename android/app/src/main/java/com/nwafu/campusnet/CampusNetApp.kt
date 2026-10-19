package com.nwafu.campusnet

import android.app.Application
import com.nwafu.campusnet.portal.Errors

class CampusNetApp : Application() {
    override fun onCreate() {
        super.onCreate()
        // 错误码文案表随 assets 打包，启动时载入一次
        Errors.loadFromAssets(this)
    }
}
