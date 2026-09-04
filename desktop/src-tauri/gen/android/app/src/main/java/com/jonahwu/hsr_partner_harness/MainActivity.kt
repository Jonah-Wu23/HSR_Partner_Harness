package com.jonahwu.hsr_partner_harness

import android.os.Bundle
import androidx.activity.enableEdgeToEdge

class MainActivity : TauriActivity() {
  override fun onCreate(savedInstanceState: Bundle?) {
    enableEdgeToEdge()
    super.onCreate(savedInstanceState)
  }

  override fun onStart() {
    super.onStart()
    // L12 前台保活（契约 §9.2）：应用启动即常驻，通知栏「保持连接中」可被用户
    // 一键停止；服务死活与连接真实性解耦——断连由前端 ConnectionBanner 如实呈现。
    // Android 13+ 未授权 POST_NOTIFICATIONS 时 startForeground 仍合法（常驻条目
    // 在授权后才可见），L13 通知发送由前端按授权状态把关。
    WsForegroundService.start(this)
  }
}
