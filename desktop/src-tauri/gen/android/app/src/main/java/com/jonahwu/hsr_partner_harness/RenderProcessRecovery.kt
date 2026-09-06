package com.jonahwu.hsr_partner_harness

import android.graphics.Bitmap
import android.webkit.RenderProcessGoneDetail
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient

/**
 * 在不丢失 wry 资源拦截和导航行为的前提下处理渲染进程退出。
 *
 * Android 把 onRenderProcessGone 定义在 WebViewClient 上。wry 的
 * RustWebViewClient 是 final，因而这里采用委托包装。
 */
class RenderProcessRecoveryClient(
  private val mainActivity: MainActivity,
  private val delegate: RustWebViewClient,
) : WebViewClient() {
  override fun shouldInterceptRequest(
    view: WebView,
    request: WebResourceRequest,
  ): WebResourceResponse? = delegate.shouldInterceptRequest(view, request)

  override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean =
    delegate.shouldOverrideUrlLoading(view, request)

  override fun onPageStarted(view: WebView, url: String, favicon: Bitmap?) =
    delegate.onPageStarted(view, url, favicon)

  override fun onPageFinished(view: WebView, url: String) =
    delegate.onPageFinished(view, url)

  override fun onReceivedError(
    view: WebView,
    request: WebResourceRequest,
    error: WebResourceError,
  ) = delegate.onReceivedError(view, request, error)

  override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail): Boolean {
    val reason = if (detail.didCrash()) "渲染进程崩溃" else "渲染进程被系统回收"
    mainActivity.recoverRenderer(view, "$reason（onRenderProcessGone）")
    return true
  }
}
