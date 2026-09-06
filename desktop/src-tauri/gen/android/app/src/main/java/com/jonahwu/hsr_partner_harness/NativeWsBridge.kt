package com.jonahwu.hsr_partner_harness

import android.annotation.SuppressLint
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.os.Build
import android.util.Log
import androidx.core.app.NotificationCompat
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.TimeUnit

/**
 * V0.3.8 T1（真机验收 C1）：Kotlin 原生 WS 常驻通道 + 本地通知直投。
 *
 * 真机实证：wry onPause 挂起 WebView 后 JS/WS 事件通道中断，前台服务方案
 * （契约 §9.2 (b)）保住了进程却收不到事件。本通道在前台服务内维持独立 WS
 * 长连接，后台/锁屏期间按通知规则直投本地通知；前台期间不投递（JS 侧
 * NotificationEngine 的「仅后台发送」语义不变），双通道按 Activity 生命周期
 * 互斥，原生侧按 turn 终态 turn_id 记忆最近 32 条去重（契约 §14.5）。
 *
 * 配置来源：MainActivity.onResume 经 WebView evaluateJavascript 读 localStorage
 * （前台可靠），经 [updateConfig] 注入；无配置时不连接、如实记日志。
 *
 * Let It Fail 边界：连接失败/解析失败只记日志并按退避重连，不伪造在线；
 * 偏好读取失败采用与界面相同的默认值，三档提醒映射到独立通知渠道。
 */
object NativeWsBridge {
  private const val TAG = "NativeWs"
  private const val DEDUP_CAPACITY = 32
  private val TURN_TERMINAL_STATUSES = setOf("completed", "failed", "cancelled")

  /** 渠道 id 基础名与 JS 侧 NotificationEngine 完全一致。 */
  private val CHANNEL_IDS = mapOf(
    "taskCompleted" to "phm_task_completed",
    "delegationResult" to "phm_delegation_result",
    "approvalRequested" to "phm_approval_requested",
  )

  data class Config(val wsUrl: String, val token: String, val prefsJson: String?)
  private data class NotificationPreference(val enabled: Boolean, val importance: String)

  @Volatile var backgroundOnly: Boolean = true
  @Volatile private var config: Config? = null
  @Volatile private var appContext: Context? = null
  private var webSocket: WebSocket? = null
  private var connectionGeneration = 0L
  private var reconnectAttempt = 0
  private val reconnectHandler = android.os.Handler(android.os.Looper.getMainLooper())
  private val dedupTurnIds = ArrayBlockingQueue<String>(DEDUP_CAPACITY)
  private val dedupSeen = HashSet<String>()
  private val client: OkHttpClient by lazy {
    OkHttpClient.Builder()
      .pingInterval(20, TimeUnit.SECONDS)
      .connectTimeout(10, TimeUnit.SECONDS)
      .build()
  }

  fun updateConfig(context: Context, next: Config?) {
    val applicationContext = context.applicationContext
    val generation: Long
    synchronized(this) {
      if (config == next && webSocket != null) return
      connectionGeneration += 1
      generation = connectionGeneration
      reconnectAttempt = 0
      reconnectHandler.removeCallbacksAndMessages(null)
      val previousSocket = webSocket
      webSocket = null
      config = next
      appContext = applicationContext
      previousSocket?.close(1000, "config changed")
    }
    if (next != null) connect(applicationContext, generation)
  }

  fun stop() {
    synchronized(this) {
      connectionGeneration += 1
      config = null
      reconnectHandler.removeCallbacksAndMessages(null)
      val previousSocket = webSocket
      webSocket = null
      previousSocket?.close(1000, "stopped")
    }
  }

  private fun connect(context: Context, generation: Long) {
    val cfg = synchronized(this) {
      if (generation != connectionGeneration) return
      config
    } ?: run {
      Log.w(TAG, "无连接配置（尚未经 WebView 桥接），原生通道不连接")
      return
    }
    val request = Request.Builder().url(cfg.wsUrl).build()
    val socket = client.newWebSocket(
      request,
      Listener(context.applicationContext, cfg, generation),
    )
    synchronized(this) {
      if (generation == connectionGeneration) {
        webSocket = socket
      } else {
        socket.close(1000, "stale generation")
      }
    }
  }

  private class Listener(
    private val context: Context,
    private val cfg: Config,
    private val generation: Long,
  ) : WebSocketListener() {
    override fun onOpen(webSocket: WebSocket, response: Response) {
      if (!isCurrent(webSocket, generation)) {
        webSocket.close(1000, "stale generation")
        return
      }
      Log.i(TAG, "原生 WS 已连接，发送带 token 的 ping 完成连接鉴权与订阅")
      reconnectAttempt = 0
      // ws_server：未认证连接的首个非白名单命令带合法 token 即完成鉴权并
      // 订阅扇出（remote.pair 是一次性配对码换 token 的流程，原生侧直接
      // 复用 JS 侧已持久化的长期 token）。
      val handshake = JSONObject()
        .put("kind", "request")
        .put("id", "native-auth-1")
        .put("method", "ping")
        .put("params", JSONObject())
        .put("auth", JSONObject().put("token", cfg.token))
      webSocket.send(handshake.toString())
    }

    override fun onMessage(webSocket: WebSocket, text: String) {
      if (!isCurrent(webSocket, generation)) return
      try {
        handleFrame(text)
      } catch (e: Exception) {
        Log.w(TAG, "原生通道帧处理失败（如实保留）: $e")
      }
    }

    override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
      Log.w(TAG, "原生 WS 连接失败: ${t.message}")
      scheduleReconnect(webSocket)
    }

    override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
      Log.i(TAG, "原生 WS 关闭（code=$code）")
      scheduleReconnect(webSocket)
    }

    private fun scheduleReconnect(socket: WebSocket) {
      if (!isCurrent(socket, generation)) return
      val attempt = reconnectAttempt++
      val delayMs = (1000L shl attempt.coerceAtMost(6)).coerceAtMost(60_000L)
      reconnectHandler.postDelayed(
        {
          if (!isCurrent(socket, generation)) return@postDelayed
          synchronized(NativeWsBridge) {
            if (NativeWsBridge.webSocket === socket) {
              NativeWsBridge.webSocket = null
            }
          }
          connect(context, generation)
        },
        delayMs,
      )
    }
  }

  private fun handleFrame(text: String) {
    val frame = JSONObject(text)
    when (frame.optString("kind")) {
      "response" -> {
        // remote.pair 的回执：失败如实记日志（token 失效时原生通道收不到事件）。
        if (frame.optBoolean("ok") != true) {
          Log.w(TAG, "原生通道鉴权失败：${frame.optJSONObject("error")}")
        }
      }
      "event" -> handleEvent(frame)
      else -> Log.d(TAG, "忽略帧 kind=${frame.optString("kind")}")
    }
  }

  private fun handleEvent(frame: JSONObject) {
    val name = frame.optString("event")
    val payload = frame.optJSONObject("payload") ?: return
    when (name) {
      "turn.status_changed" -> handleTurnStatus(payload)
      "approval.requested" -> handleApprovalRequested(payload)
      else -> return
    }
  }

  private fun handleTurnStatus(payload: JSONObject) {
    val turn = payload.optJSONObject("turn") ?: return
    val status = turn.optString("status")
    if (status !in TURN_TERMINAL_STATUSES) return
    val turnId = turn.optString("turn_id")
    if (turnId.isNotEmpty() && !markTurnNotified(turnId)) return
    val type = if (turn.optString("target") == "assistant") "delegationResult" else "taskCompleted"
    val conversationId = turn.optString("conversation_id")
    postNotification(
      type,
      title = if (type == "delegationResult") "委派任务结束" else "任务完成",
      body = if (status == "completed") "回复已送达，点按查看" else "回合以 $status 结束",
      conversationId = conversationId,
      deduped = turnId.isNotEmpty(),
    )
  }

  private fun handleApprovalRequested(payload: JSONObject) {
    val operation = payload.optJSONObject("operation")
    val summary = operation?.optString("summary") ?: ""
    val reason = payload.optString("reason")
    val body = listOf(summary, reason).firstOrNull { it.isNotBlank() } ?: "等待裁决"
    postNotification(
      "approvalRequested",
      title = "等待审批",
      body = body,
      conversationId = payload.optString("conversation_id"),
      deduped = false,
    )
  }

  /** 契约 §14.5：同一 turn 终态只投递一次（最近 32 条记忆）。返回是否首次。 */
  private fun markTurnNotified(turnId: String): Boolean {
    synchronized(dedupSeen) {
      if (!dedupSeen.add(turnId)) return false
      if (dedupTurnIds.size >= DEDUP_CAPACITY) {
        dedupSeen.remove(dedupTurnIds.poll())
      }
      dedupTurnIds.offer(turnId)
      return true
    }
  }

  @SuppressLint("ObsoleteSdkInt")
  private fun postNotification(
    typeKey: String,
    title: String,
    body: String,
    conversationId: String,
    deduped: Boolean,
  ) {
    if (!backgroundOnly) {
      Log.d(TAG, "应用在前台，原生通道不投递（JS 引擎负责）")
      return
    }
    val preference = notificationPreference(typeKey)
    if (!preference.enabled) {
      Log.d(TAG, "通知偏好关闭：$typeKey 跳过")
      return
    }
    val context = appContext ?: return
    val manager =
      context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
    if (!manager.areNotificationsEnabled()) {
      Log.i(TAG, "通知权限未授权，原生通道跳过投递")
      return
    }
    val channelId = "${CHANNEL_IDS[typeKey] ?: return}_${preference.importance}"
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O &&
      manager.getNotificationChannel(channelId) == null
    ) {
      val importance = when (preference.importance) {
        "high" -> NotificationManager.IMPORTANCE_HIGH
        "silent" -> NotificationManager.IMPORTANCE_LOW
        else -> NotificationManager.IMPORTANCE_DEFAULT
      }
      val channel = NotificationChannel(channelId, channelId, importance)
      if (preference.importance == "silent") channel.setSound(null, null)
      manager.createNotificationChannel(channel)
    }
    val priority = when (preference.importance) {
      "high" -> NotificationCompat.PRIORITY_HIGH
      "silent" -> NotificationCompat.PRIORITY_LOW
      else -> NotificationCompat.PRIORITY_DEFAULT
    }
    val notification = NotificationCompat.Builder(context, channelId)
      .setSmallIcon(android.R.drawable.stat_notify_chat)
      .setContentTitle(title)
      .setContentText(body)
      .setPriority(priority)
      .setAutoCancel(true)
      .build()
    manager.notify(("native-$typeKey-$conversationId").hashCode(), notification)
    Log.i(TAG, "原生通道投递通知：$typeKey turn 去重=$deduped")
  }

  private fun defaultPreference(typeKey: String): NotificationPreference =
    NotificationPreference(
      enabled = true,
      importance = if (typeKey == "approvalRequested") "high" else "default",
    )

  private fun notificationPreference(typeKey: String): NotificationPreference {
    val fallback = defaultPreference(typeKey)
    val prefsJson = config?.prefsJson ?: return fallback
    return try {
      val prefs = JSONObject(prefsJson)
      val entry = prefs.optJSONObject(typeKey) ?: return fallback
      val importance = entry.optString("importance", fallback.importance)
      if (importance !in setOf("high", "default", "silent")) return fallback
      NotificationPreference(entry.optBoolean("enabled", true), importance)
    } catch (e: Exception) {
      Log.w(TAG, "通知偏好解析失败，按界面默认值处理: $e")
      fallback
    }
  }

  private fun isCurrent(socket: WebSocket, generation: Long): Boolean =
    synchronized(this) {
      generation == connectionGeneration && webSocket === socket && config != null
    }
}
