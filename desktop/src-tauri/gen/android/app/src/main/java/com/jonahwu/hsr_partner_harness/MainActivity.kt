package com.jonahwu.hsr_partner_harness

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings
import android.webkit.JavascriptInterface
import android.webkit.WebView
import android.widget.Toast
import androidx.activity.enableEdgeToEdge
import org.json.JSONObject
import org.json.JSONTokener

class MainActivity : TauriActivity() {
  // V0.3.8 T3（真机验收 C5）：渲染进程死亡恢复。wry 的 mWebView 是 private，
  // 通过 onWebViewCreate 钩子保存引用供 onResume 探活；WebViewClient
  // 包装器即时捕获 onRenderProcessGone。
  private var webView: WebView? = null
  private var healthProbePending = false
  private var healthProbeTimeout: Runnable? = null
  private var rendererRecoveryStarted = false
  private val mainHandler = Handler(Looper.getMainLooper())

  // V0.3.8 T1（真机验收 C1）：原生保活通道的配置桥接指纹（避免重复重连）。
  private var bridgedConfigFingerprint: String? = null

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
    maybeGuideBatteryOptimization()
  }

  override fun onWebViewCreate(createdWebView: WebView) {
    super.onWebViewCreate(createdWebView)
    webView = createdWebView
    createdWebView.post {
      attachCrashRecoveryClient(createdWebView)
    }
    createdWebView.addJavascriptInterface(NativeKeepaliveJsBridge(), "PairHarnessNative")
  }

  override fun onResume() {
    super.onResume()
    NativeWsBridge.backgroundOnly = false
    webView?.let { attachCrashRecoveryClient(it) }
    probeRendererHealth()
    bridgeNativeKeepaliveConfig()
  }

  override fun onPause() {
    cancelRendererHealthProbe()
    NativeWsBridge.backgroundOnly = true
    super.onPause()
  }

  /**
   * 即时检测路径：包装 wry WebViewClient 以捕获 onRenderProcessGone。
   * onWebViewCreate 在 wry 完成 WebView 初始化后调用，包装器保留原客户端
   * 已实现的资源拦截、导航和页面加载回调。
   */
  private fun attachCrashRecoveryClient(createdWebView: WebView) {
    // onRenderProcessGone 和 getWebViewClient 均自 API 26 提供。
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
    val currentClient = createdWebView.webViewClient
    if (currentClient is RenderProcessRecoveryClient) return
    // IPC 持有此实例并读取 currentUrl；必须保留原实例的页面回调。
    val originalClient = currentClient as? RustWebViewClient ?: return
    createdWebView.webViewClient = RenderProcessRecoveryClient(
      this,
      originalClient,
    )
  }

  /** 配对、解绑和偏好落盘后由前端调用，避免等到下一次 onResume。 */
  private inner class NativeKeepaliveJsBridge {
    @JavascriptInterface
    fun syncConfig(wsUrl: String, token: String, prefsJson: String) {
      mainHandler.post {
        applyNativeKeepaliveConfig(wsUrl, token, prefsJson.ifEmpty { null })
      }
    }
  }

  /**
   * onResume 时检查页面响应；超时仅说明页面未响应，不能证明进程死亡。
   * 探测只在前台有效，暂停后取消，避免把后台 JS 挂起误判为故障。
   * V0.3.8 D3：放宽超时到 10s 规避锁屏唤醒抖动，避免误杀正常恢复中的 WebView。
   */
  private fun probeRendererHealth() {
    val view = webView ?: return
    if (healthProbePending || rendererRecoveryStarted) return
    healthProbePending = true
    var settled = false
    val recoverIfSilent = Runnable {
      if (settled || !healthProbePending || webView !== view || isDestroyed || isFinishing || isChangingConfigurations) {
        healthProbePending = false
        return@Runnable
      }
      settled = true
      healthProbePending = false
      recoverRenderer(view, "页面探活超时（${RENDER_PROBE_TIMEOUT_MS}ms 无回调）")
    }
    healthProbeTimeout = recoverIfSilent
    mainHandler.postDelayed(recoverIfSilent, RENDER_PROBE_TIMEOUT_MS)
    view.evaluateJavascript("1") { _ ->
      if (settled || healthProbeTimeout !== recoverIfSilent) return@evaluateJavascript
      settled = true
      healthProbePending = false
      mainHandler.removeCallbacks(recoverIfSilent)
      healthProbeTimeout = null
    }
  }

  private fun cancelRendererHealthProbe() {
    healthProbeTimeout?.let { mainHandler.removeCallbacks(it) }
    healthProbeTimeout = null
    healthProbePending = false
  }

  internal fun recoverRenderer(view: WebView, reason: String) {
    if (rendererRecoveryStarted || webView !== view) return
    rendererRecoveryStarted = true
    cancelRendererHealthProbe()
    webView = null
    Logger.error("WebView $reason，清理旧视图并请求重建 Activity（isChangingConfigurations=$isChangingConfigurations）")
    (view.parent as? android.view.ViewGroup)?.removeView(view)
    view.destroy()
    if (isDestroyed || isFinishing || isChangingConfigurations) return
    Toast.makeText(this, "页面未响应，正在恢复…", Toast.LENGTH_LONG).show()
    // Android ActivityThread 的 relaunch 流程在 onDestroy 前设置
    // mChangingConfigurations=true；Wry/Tao 因此保留 native 窗口和
    // WEBVIEW_ATTRIBUTES，WryActivity 保存的 id 用于创建新 WebView。
    recreate()
  }

  override fun onDestroy() {
    cancelRendererHealthProbe()
    webView = null
    super.onDestroy()
  }

  /**
   * V0.3.8 T1：把前端持久化的连接配置桥接给原生保活通道。
   * 只在 onResume（前台）读取——WebView 后台被挂起后 JS 不可靠（C1 根因）；
   * 配置指纹未变化时不重连，避免每次回前台都重建连接。
   */
  private fun bridgeNativeKeepaliveConfig() {
    val view = webView ?: return
    val js =
      "(function(){try{return JSON.stringify({" +
        "wsUrl: localStorage.getItem('phm.wsUrl') || ''," +
        "token: localStorage.getItem('phm.remote.token') || ''," +
        "prefs: localStorage.getItem('phm.notificationPreferences.v1') || ''" +
        "});}catch(e){return '{}';}})()"
    view.evaluateJavascript(js) { result ->
      try {
        // evaluateJavascript 回传的是 JSON 字符串字面量，先解一层引号。
        val decoded = JSONTokener(result).nextValue() as? String ?: return@evaluateJavascript
        val cfg = JSONObject(decoded)
        val wsUrl = cfg.optString("wsUrl")
        val token = cfg.optString("token")
        applyNativeKeepaliveConfig(
          wsUrl,
          token,
          cfg.optString("prefs").ifEmpty { null },
        )
      } catch (e: Exception) {
        Logger.warn("原生保活配置桥接失败（如实保留）: $e")
      }
    }
  }

  private fun applyNativeKeepaliveConfig(wsUrl: String, token: String, prefsJson: String?) {
    if (wsUrl.isEmpty() || token.isEmpty()) {
      bridgedConfigFingerprint = null
      NativeWsBridge.updateConfig(this, null)
      return
    }
    val fingerprint = "$wsUrl|$token|$prefsJson"
    if (fingerprint == bridgedConfigFingerprint) return
    bridgedConfigFingerprint = fingerprint
    val httpUrl = wsUrl.replace("ws://", "http://").replace("wss://", "https://")
    NativeWsBridge.updateConfig(
      this,
      NativeWsBridge.Config(wsUrl = httpUrl, token = token, prefsJson = prefsJson),
    )
  }

  /**
   * V0.3.8 T1：电池优化豁免引导——只引导一次（用户拒绝后不再打扰），
   * MIUI 的激进省电是 C1 后台断连的现实因素之一。
   */
  private fun maybeGuideBatteryOptimization() {
    val prefs = getSharedPreferences(PREFS_NATIVE, Context.MODE_PRIVATE)
    if (prefs.getBoolean(KEY_BATTERY_GUIDE_SHOWN, false)) return
    val powerManager = getSystemService(Context.POWER_SERVICE) as PowerManager
    if (powerManager.isIgnoringBatteryOptimizations(packageName)) return
    try {
      startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
      prefs.edit().putBoolean(KEY_BATTERY_GUIDE_SHOWN, true).apply()
    } catch (e: Exception) {
      Logger.warn("电池优化设置页不可用（如实记录）: $e")
    }
  }

  private companion object {
    const val RENDER_PROBE_TIMEOUT_MS = 10000L
    const val PREFS_NATIVE = "phm_native"
    const val KEY_BATTERY_GUIDE_SHOWN = "battery_guide_shown"
  }
}
