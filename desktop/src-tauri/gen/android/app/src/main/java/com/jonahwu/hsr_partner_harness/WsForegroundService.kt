package com.jonahwu.hsr_partner_harness

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import androidx.core.app.NotificationCompat

/**
 * V0.3.7 L12 前台服务（契约 §9.2 方案 (b)：自建最小 Kotlin 服务，未引入社区插件）。
 *
 * 作用：壳进入后台/锁屏时保住进程与 WebView 存活，维持与桌面端 --serve 的 WS 长连接，
 * 使锁屏期间审批请求 / 任务完成通知（L13，JS 侧 tauri-plugin-notification）能真实送达。
 * 通知栏常驻「保持连接中」条目；用户经通知的「停止保活」动作（或系统通知设置）关闭，
 * 关闭后系统可随时回收进程——断连由壳内 ConnectionBanner 如实呈现，不伪造在线。
 *
 * 实现注意：
 * - foregroundServiceType=dataSync（targetSdk 34+ 必需，manifest 同步声明）；
 * - PARTIAL_WAKE_LOCK 防止浅 Doze 期间 CPU 休眠断连（30 分钟验收窗口在浅 Doze 范围内）；
 * - stopWithTask=false：划掉任务不停止服务（连接由用户显式停止或系统杀进程终止）。
 */
class WsForegroundService : Service() {

  companion object {
    const val CHANNEL_ID = "phm_foreground_service"
    const val NOTIFICATION_ID = 1001
    const val ACTION_STOP = "com.jonahwu.hsr_partner_harness.action.STOP_KEEPALIVE"

    fun start(context: Context) {
      val intent = Intent(context, WsForegroundService::class.java)
      context.startForegroundService(intent)
    }

    fun stop(context: Context) {
      context.stopService(Intent(context, WsForegroundService::class.java))
    }
  }

  private var wakeLock: PowerManager.WakeLock? = null

  override fun onCreate() {
    super.onCreate()
    createChannel()
  }

  override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
    if (intent?.action == ACTION_STOP) {
      stopSelf()
      return START_NOT_STICKY
    }
    startInForeground()
    acquireWakeLock()
    return START_STICKY
  }

  override fun onDestroy() {
    wakeLock?.let { if (it.isHeld) it.release() }
    wakeLock = null
    super.onDestroy()
  }

  override fun onBind(intent: Intent?): IBinder? = null

  private fun createChannel() {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
    val manager = getSystemService(NotificationManager::class.java)
    val channel = NotificationChannel(
      CHANNEL_ID,
      getString(R.string.ws_service_channel_name),
      NotificationManager.IMPORTANCE_LOW,
    ).apply {
      description = getString(R.string.ws_service_channel_description)
      setShowBadge(false)
    }
    manager.createNotificationChannel(channel)
  }

  private fun buildNotification(): Notification {
    val openIntent = PendingIntent.getActivity(
      this,
      0,
      Intent(this, MainActivity::class.java),
      PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
    )
    val stopIntent = PendingIntent.getService(
      this,
      1,
      Intent(this, WsForegroundService::class.java).setAction(ACTION_STOP),
      PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
    )
    return NotificationCompat.Builder(this, CHANNEL_ID)
      .setSmallIcon(R.mipmap.ic_launcher)
      .setContentTitle(getString(R.string.ws_service_notification_title))
      .setContentText(getString(R.string.ws_service_notification_text))
      .setOngoing(true)
      .setContentIntent(openIntent)
      .addAction(0, getString(R.string.ws_service_stop_action), stopIntent)
      .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
      .build()
  }

  private fun startInForeground() {
    val notification = buildNotification()
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
      ServiceCompat_startForeground(notification)
    } else {
      startForeground(NOTIFICATION_ID, notification)
    }
  }

  private fun ServiceCompat_startForeground(notification: Notification) {
    // androidx.core 三参重载在 targetSdk 34+ 必须带 foregroundServiceType。
    androidx.core.app.ServiceCompat.startForeground(
      this,
      NOTIFICATION_ID,
      notification,
      ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC,
    )
  }

  private fun acquireWakeLock() {
    if (wakeLock?.isHeld == true) return
    val powerManager = getSystemService(PowerManager::class.java)
    wakeLock = powerManager.newWakeLock(
      PowerManager.PARTIAL_WAKE_LOCK,
      "hsr_partner_harness:ws_keepalive",
    ).apply {
      setReferenceCounted(false)
      // 30 分钟验收窗口之外不无限持有：超时释放后由前台服务本身兜底进程存活。
      acquire(30 * 60 * 1000L)
    }
  }
}
