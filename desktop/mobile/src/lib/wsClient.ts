/**
 * V0.3.3 手机端 WebSocket 客户端：Sidecar --serve 远程模式的最小协议封装。
 *
 * 帧格式与桌面 stdio 一致（kind: request/response/event），差别仅两点：
 * - 请求帧顶层可带 auth: { token }；配对之后所有业务请求必须携带；
 * - remote.pair 属未鉴权白名单方法，手机端凭一次性配对码换 token。
 *
 * 鉴权失败（响应 error.code === "unauthorized"）时客户端如实进入
 * auth_failed 并拒绝该请求，不静默重试、不伪造已连接状态。
 */

export type MobileConnectionState =
  | "disconnected"
  | "connecting"
  | "connected"
  | "reconnecting"
  | "unreachable"
  | "auth_failed";

export interface WireRequest {
  kind: "request";
  id: string;
  method: string;
  params: Record<string, unknown>;
  auth?: { token: string };
}

export interface WireResponse<T = unknown> {
  kind: "response";
  id: string;
  ok: boolean;
  result?: T;
  error?: {
    code: string;
    message: string;
    /** V0.3.5 契约 §6：结构化附加字段（如 approval_already_resolved 的真实结果）。 */
    details?: Record<string, unknown>;
  };
}

export interface WireEvent<T = Record<string, unknown>> {
  kind: "event";
  event: string;
  sequence: number;
  stream_id?: string | number;
  payload: T;
}

/** Sidecar 远程命令失败：保留 code，调用方可据 code 分支（如 unauthorized）。 */
export class RemoteCommandError extends Error {
  readonly code: string;
  /** V0.3.5 契约 §6：服务端结构化附加字段（原样透传，无则为空对象）。 */
  readonly details: Record<string, unknown>;

  constructor(
    code: string,
    message: string,
    details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = "RemoteCommandError";
    this.code = code;
    this.details = details ?? {};
  }
}

const TOKEN_KEY = "phm.remote.token";
const DEVICE_NAME_KEY = "phm.remote.deviceName";
const WS_URL_KEY = "phm.wsUrl";
const NOTIFICATION_PREFERENCES_KEY = "phm.notificationPreferences.v1";

/** 重连退避序列（毫秒）；用尽后进入 unreachable，等用户手动重试。 */
const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 16000];

/** V0.3.8 T1（契约 §14.3）：心跳口径——每 15s 发一次 ping；30s（2×周期）
    内未收到任何入站消息即判定半开连接，主动断开走既有重连。服务端
    WebSocketResponse 另开 heartbeat=30s，双侧都能在超时内暴露死链。 */
export const PING_INTERVAL_MS = 15_000;
export const INBOUND_STALE_MS = 30_000;

function storage(): Storage | null {
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null;
  }
}

export function getStoredToken(): string | null {
  return storage()?.getItem(TOKEN_KEY) ?? null;
}

export function getStoredDeviceName(): string | null {
  return storage()?.getItem(DEVICE_NAME_KEY) ?? null;
}

export function saveCredentials(token: string, deviceName: string): void {
  const store = storage();
  if (!store) return;
  store.setItem(TOKEN_KEY, token);
  store.setItem(DEVICE_NAME_KEY, deviceName);
  syncNativeKeepaliveConfig();
}

export function clearCredentials(): void {
  const store = storage();
  if (!store) return;
  store.removeItem(TOKEN_KEY);
  store.removeItem(DEVICE_NAME_KEY);
  syncNativeKeepaliveConfig();
}

/**
 * Android 壳的窄接口：持久化状态变更后立即同步原生常驻 WS。
 * PWA 和测试环境没有该接口，保持无副作用。
 */
export function syncNativeKeepaliveConfig(): void {
  const store = storage();
  const nativeBridge = (
    globalThis as typeof globalThis & {
      PairHarnessNative?: {
        syncConfig(wsUrl: string, token: string, prefsJson: string): void;
      };
    }
  ).PairHarnessNative;
  if (!store || !nativeBridge) return;
  nativeBridge.syncConfig(
    resolveWsUrl(),
    store.getItem(TOKEN_KEY) ?? "",
    store.getItem(NOTIFICATION_PREFERENCES_KEY) ?? "",
  );
}

/**
 * 规范化 WebSocket 服务地址：
 * 支持解析 https:// 与 wss:// 协议（公网隧道场景如 https://xxx.trycloudflare.com），
 * 自动将 https:// 映射为 wss://、http:// 映射为 ws://，并确保路径以 /ws 结尾。
 */
export function normalizeWsUrl(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed) return "";
  try {
    const url = new URL(trimmed);
    let protocol = url.protocol;
    if (protocol === "https:") {
      protocol = "wss:";
    } else if (protocol === "http:") {
      protocol = "ws:";
    }
    if (protocol !== "ws:" && protocol !== "wss:") {
      return trimmed;
    }
    let pathname = url.pathname;
    if (!pathname || pathname === "/") {
      pathname = "/ws";
    } else if (!pathname.endsWith("/ws")) {
      pathname = `${pathname.replace(/\/+$/, "")}/ws`;
    }
    const searchParams = new URLSearchParams(url.search);
    searchParams.delete("code");
    searchParams.delete("ws");
    const search = searchParams.toString();
    return `${protocol}//${url.host}${pathname}${search ? `?${search}` : ""}`;
  } catch {
    return trimmed;
  }
}

/**
 * WS 地址解析优先级：?ws= 查询参数（二维码带入）> localStorage 缓存 >
 * 当前站点 /ws（经 vite proxy 或反向代理到 Sidecar）。
 */
export function resolveWsUrl(): string {
  if (typeof window === "undefined") return "ws://127.0.0.1:8765/ws";
  const query = new URLSearchParams(window.location.search).get("ws");
  if (query && query.length > 0) {
    const normalized = normalizeWsUrl(query);
    storage()?.setItem(WS_URL_KEY, normalized);
    return normalized;
  }
  const stored = storage()?.getItem(WS_URL_KEY);
  if (stored && stored.length > 0) return normalizeWsUrl(stored);
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws`;
}

interface PendingEntry {
  resolve: (result: unknown) => void;
  reject: (error: Error) => void;
}

export class MobileWsClient {
  private ws: WebSocket | null = null;
  private state: MobileConnectionState = "disconnected";
  private authFailureCode: string | null = null;
  private nextId = 1;
  private readonly pending = new Map<string, PendingEntry>();
  private readonly eventListeners = new Set<(event: WireEvent) => void>();
  private readonly stateListeners = new Set<(state: MobileConnectionState) => void>();
  private reconnectAttempt = 0;
  private reconnectTimer: number | null = null;
  private manualClose = false;
  private heartbeatTimer: number | null = null;
  private lastInboundAt = 0;

  getState(): MobileConnectionState {
    return this.state;
  }

  getAuthFailureCode(): string | null {
    return this.authFailureCode;
  }

  onEvent(listener: (event: WireEvent) => void): () => void {
    this.eventListeners.add(listener);
    return () => {
      this.eventListeners.delete(listener);
    };
  }

  onStateChange(listener: (state: MobileConnectionState) => void): () => void {
    this.stateListeners.add(listener);
    return () => {
      this.stateListeners.delete(listener);
    };
  }

  /** 幂等：已连接或连接中时直接返回。 */
  connect(): void {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }
    if (this.reconnectTimer !== null && typeof window !== "undefined") {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.manualClose = false;
    this.setState(this.reconnectAttempt > 0 ? "reconnecting" : "connecting");
    const ws = new WebSocket(resolveWsUrl());
    this.ws = ws;
    ws.onopen = () => {
      if (this.ws !== ws) return;
      this.reconnectAttempt = 0;
      this.lastInboundAt = Date.now();
      this.startHeartbeat();
      this.setState("connected");
    };
    ws.onmessage = (message: MessageEvent<string>) => {
      if (this.ws !== ws) return;
      this.lastInboundAt = Date.now();
      this.handleMessage(String(message.data));
    };
    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.stopHeartbeat();
      this.ws = null;
      this.failAllPending(new Error("WebSocket 连接已关闭"));
      if (this.manualClose) {
        this.setState("disconnected");
        return;
      }
      this.scheduleReconnect();
    };
    // onerror 不单独置状态：失败随后必有 onclose，由 onclose 统一处理。
  }

  disconnect(): void {
    this.manualClose = true;
    this.stopHeartbeat();
    if (this.reconnectTimer !== null && typeof window !== "undefined") {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.ws?.close();
    this.ws = null;
    this.failAllPending(new Error("客户端主动断开"));
    this.setState("disconnected");
  }

  /** 底层 WebSocket 是否物理处于 OPEN 状态。 */
  isSocketConnected(): boolean {
    return Boolean(this.ws && this.ws.readyState === WebSocket.OPEN);
  }

  /** 调用方已收到携带新凭证的业务成功响应后，恢复鉴权连接状态。 */
  confirmAuthenticated(): void {
    this.authFailureCode = null;
    if (this.state === "auth_failed" && this.isSocketConnected()) {
      this.setState("connected");
    }
  }

  /**
   * 发起远程命令。连接未就绪时如实拒绝，由调用方决定何时重试。
   * opts.skipAuth 仅用于 remote.pair 这类未鉴权白名单方法。
   */
  request<T>(
    method: string,
    params: Record<string, unknown> = {},
    opts?: { skipAuth?: boolean },
  ): Promise<T> {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      return Promise.reject(new Error("WebSocket 未连接"));
    }
    const id = `m-${this.nextId}`;
    this.nextId += 1;
    const frame: WireRequest = { kind: "request", id, method, params };
    const token = getStoredToken();
    if (!opts?.skipAuth && token) frame.auth = { token };
    const ws = this.ws;
    return new Promise<T>((resolve, reject) => {
      let timeoutTimer: number | null = null;
      if (typeof window !== "undefined") {
        timeoutTimer = window.setTimeout(() => {
          if (this.pending.has(id)) {
            this.pending.delete(id);
            reject(
              new RemoteCommandError(
                "request_timeout",
                `远程命令超时（${method}，30s 未收到响应）`,
              ),
            );
          }
        }, 30_000);
      }
      this.pending.set(id, {
        resolve: (result: unknown) => {
          if (timeoutTimer !== null) clearTimeout(timeoutTimer);
          (resolve as (val: unknown) => void)(result);
        },
        reject: (error: unknown) => {
          if (timeoutTimer !== null) clearTimeout(timeoutTimer);
          reject(error);
        },
      });
      ws.send(JSON.stringify(frame));
    });
  }

  private handleMessage(raw: string): void {
    let frame: unknown;
    try {
      frame = JSON.parse(raw);
    } catch {
      return;
    }
    if (!frame || typeof frame !== "object") return;
    const kind = (frame as { kind?: unknown }).kind;
    if (kind === "response") {
      this.handleResponse(frame as WireResponse);
      return;
    }
    if (kind === "event") {
      const event = frame as WireEvent;
      this.eventListeners.forEach((listener) => listener(event));
    }
  }

  /** 测试后门：直接向已注册监听器分发一条 wire 事件（等同收到 WS 帧）。 */
  emitTestEvent(event: WireEvent): void {
    this.eventListeners.forEach((listener) => listener(event));
  }

  private handleResponse(frame: WireResponse): void {
    const entry = this.pending.get(frame.id);
    if (!entry) return;
    this.pending.delete(frame.id);
    if (frame.ok) {
      entry.resolve(frame.result);
      return;
    }
    const code = frame.error?.code ?? "unknown";
    const message = frame.error?.message ?? "远程命令失败";
    const isAuthFailure =
      code === "unauthorized" ||
      code === "expired_token" ||
      code === "token_expired" ||
      code === "token_revoked" ||
      code === "revoked_token" ||
      code === "auth_failed" ||
      message === "expired_token" ||
      message === "auth_failed: expired_token" ||
      message.includes("expired_token");

    if (isAuthFailure) {
      if (
        code === "expired_token" ||
        code === "token_expired" ||
        message === "expired_token" ||
        message === "auth_failed: expired_token" ||
        message.includes("expired_token")
      ) {
        this.authFailureCode = "expired_token";
        clearCredentials();
      } else if (
        code === "token_revoked" ||
        code === "revoked_token" ||
        message === "revoked_token" ||
        message === "token_revoked"
      ) {
        this.authFailureCode = "token_revoked";
      } else {
        this.authFailureCode = code !== "unknown" ? code : message;
      }
      // 如实暴露鉴权失败：UI 引导重新配对，不在网络层静默换状态。
      this.setState("auth_failed");
    }
    entry.reject(
      new RemoteCommandError(code, message, frame.error?.details),
    );
  }

  private startHeartbeat(): void {
    if (typeof window === "undefined") return;
    this.stopHeartbeat();
    this.heartbeatTimer = window.setInterval(() => {
      if (Date.now() - this.lastInboundAt >= INBOUND_STALE_MS) {
        // 半开连接：TCP 未断但服务端/网络已死——主动断开，onclose 统一走重连。
        console.warn("WS 心跳超时（30s 无入站消息），判定半开连接并重连");
        this.stopHeartbeat();
        this.ws?.close();
        return;
      }
      this.request("ping", {}).catch((error) => {
        // 发送失败/被拒由 onclose 或错误响应（auth_failed）驱动状态，这里留痕。
        console.warn("WS ping 发送失败", error);
      });
    }, PING_INTERVAL_MS);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer !== null && typeof window !== "undefined") {
      window.clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  /** V0.3.8 T1（契约 §14.4）：回前台重同步分派——unreachable 终态复位重连
      （不得永久停摆）；connected 返回 resync 由调用方重新 bootstrap 补拉；
      connecting/reconnecting 维持既有流程。 */
  notifyAppForeground(): "resync" | "reconnecting" | "none" {
    if (this.state === "unreachable") {
      this.reconnectAttempt = 0;
      this.connect();
      return "reconnecting";
    }
    if (this.state === "connected") return "resync";
    return "none";
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempt >= RECONNECT_DELAYS.length) {
      this.setState("unreachable");
      return;
    }
    const delay = RECONNECT_DELAYS[this.reconnectAttempt];
    this.reconnectAttempt += 1;
    this.setState("reconnecting");
    if (typeof window === "undefined") {
      this.setState("unreachable");
      return;
    }
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  private failAllPending(error: Error): void {
    this.pending.forEach((entry) => entry.reject(error));
    this.pending.clear();
  }

  private setState(next: MobileConnectionState): void {
    if (this.state === next) return;
    this.state = next;
    this.stateListeners.forEach((listener) => listener(next));
  }
}
