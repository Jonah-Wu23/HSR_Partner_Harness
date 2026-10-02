/**
 * 手机端 WebSocket 客户端：Sidecar --serve 远程模式的协议封装。
 *
 * 帧格式与桌面 stdio 一致（kind: request/response/event/error），差别有两点：
 * - 配对之后的业务请求在顶层携带 auth: { token }；
 * - remote.pair 是免鉴权方法，手机端凭一次性配对码换取 token。
 *
 * 服务端以 code=unauthorized 拒绝请求时，message 是鉴权失败原因，
 * 客户端进入 auth_failed 并拒绝该请求。
 */

export type MobileConnectionState =
  | "disconnected"
  | "connecting"
  | "connected"
  | "reconnecting"
  | "unreachable"
  | "auth_failed";

/** code=unauthorized 响应的 message 取值（pairing.authorize 的拒绝原因）。 */
export type AuthFailureReason = "missing_token" | "invalid_token" | "revoked_token" | "expired_token";

export interface WireRequest {
  kind: "request";
  id: string;
  method: string;
  params: Record<string, unknown>;
  auth?: { token: string };
}

export interface WireErrorBody {
  code: string;
  message: string;
  /** 结构化附加字段（如 approval_already_resolved 的终态）。 */
  details?: Record<string, unknown>;
}

export type WireResponse<T = unknown> =
  | { kind: "response"; id: string; ok: true; result: T }
  | { kind: "response"; id: string; ok: false; error: WireErrorBody };

export interface WireEvent<T = Record<string, unknown>> {
  kind: "event";
  event: string;
  /** 只发给手机的事件（TTS 分片、转写）不带序号，不参与序号校验。 */
  sequence?: number;
  stream_id: string;
  payload: T;
}

/** 协议层错误：服务端无法解析或校验请求帧时发出，能识别请求 id 时带 id。 */
export interface WireProtocolError {
  kind: "error";
  id?: string;
  error: WireErrorBody;
}

type WireFrame = WireResponse | WireEvent | WireProtocolError;

/** Sidecar 远程命令失败：保留 code 与 details，调用方据 code 分支。 */
export class RemoteCommandError extends Error {
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.name = "RemoteCommandError";
    this.code = code;
    this.details = details;
  }
}

const TOKEN_KEY = "phm.remote.token";
const DEVICE_NAME_KEY = "phm.remote.deviceName";
const WS_URL_KEY = "phm.wsUrl";
const NOTIFICATION_PREFERENCES_KEY = "phm.notificationPreferences.v1";

/** 重连退避序列（毫秒）；用尽后进入 unreachable，等用户手动重试。 */
const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 16000];

/** 鉴权 bootstrap 成功后每 15s 发一次 ping；30s 内没有任何入站消息即判定半开连接，
    立即摘除 socket 并重连。服务端 WebSocketResponse 另开 heartbeat=30s。 */
export const PING_INTERVAL_MS = 15_000;
export const INBOUND_STALE_MS = 30_000;

/** 单个远程命令等待响应的上限。 */
const REQUEST_TIMEOUT_MS = 30_000;

export function getStoredToken(): string | null {
  return window.localStorage.getItem(TOKEN_KEY);
}

export function getStoredDeviceName(): string | null {
  return window.localStorage.getItem(DEVICE_NAME_KEY);
}

export function saveCredentials(token: string, deviceName: string): void {
  window.localStorage.setItem(TOKEN_KEY, token);
  window.localStorage.setItem(DEVICE_NAME_KEY, deviceName);
  syncNativeKeepaliveConfig();
}

export function clearCredentials(): void {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(DEVICE_NAME_KEY);
  syncNativeKeepaliveConfig();
}

/** 已保存的桌面端服务地址（写入前已规范化）；未保存为 null。 */
export function getStoredWsUrl(): string | null {
  return window.localStorage.getItem(WS_URL_KEY);
}

/** 保存规范化后的桌面端服务地址，下一次 connect() 使用它。 */
export function saveWsUrl(url: string): void {
  window.localStorage.setItem(WS_URL_KEY, url);
}

/**
 * Android 壳注入的原生接口：凭据或偏好变更后同步给原生常驻 WS。
 * PWA 没有该接口。
 */
export function syncNativeKeepaliveConfig(): void {
  const nativeBridge = (
    globalThis as typeof globalThis & {
      PairHarnessNative?: {
        syncConfig(wsUrl: string, token: string, prefsJson: string): void;
      };
    }
  ).PairHarnessNative;
  if (!nativeBridge) return;
  nativeBridge.syncConfig(
    resolveWsUrl(),
    window.localStorage.getItem(TOKEN_KEY) ?? "",
    window.localStorage.getItem(NOTIFICATION_PREFERENCES_KEY) ?? "",
  );
}

export type WsAddressParseResult =
  | { ok: true; url: string }
  /** 空输入的 error 为 null：不算错误，但也不能保存。 */
  | { ok: false; error: string | null };

/**
 * 解析并规范化桌面端服务地址，输入框校验、扫码与连接共用这一处实现。
 * - 局域网地址写成 ws://<IP>:<端口>/ws，路径必须以 /ws 结尾（Sidecar 远程服务入口）；
 * - 公网隧道可写 wss:// 或 https://，https 映射为 wss，根路径补齐为 /ws；
 * - 去掉二维码带的 code 与 ws 查询参数。
 */
export function parseWsAddress(raw: string): WsAddressParseResult {
  const value = raw.trim();
  if (value.length === 0) return { ok: false, error: null };
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return {
      ok: false,
      error: "地址不完整，请输入形如 ws://192.168.1.50:8765/ws 或 https://xxx.trycloudflare.com 的完整地址",
    };
  }
  if (url.protocol !== "ws:" && url.protocol !== "wss:" && url.protocol !== "https:") {
    return {
      ok: false,
      error: "地址需以 ws://、wss:// 或 https:// 开头（与桌面端二维码中的 ?ws= 地址一致）",
    };
  }
  if (!url.hostname) {
    return { ok: false, error: "地址缺少主机名，请填入公网隧道地址或电脑的局域网 IP" };
  }
  const isRoot = url.pathname === "/" || url.pathname === "";
  if (!url.pathname.endsWith("/ws") && (url.protocol === "ws:" || !isRoot)) {
    return {
      ok: false,
      error: "地址路径需以 /ws 结尾（桌面端远程服务的入口），例如 ws://192.168.1.50:8765/ws",
    };
  }
  const protocol = url.protocol === "ws:" ? "ws:" : "wss:";
  const pathname = isRoot ? "/ws" : url.pathname;
  url.searchParams.delete("code");
  url.searchParams.delete("ws");
  const search = url.searchParams.toString();
  return { ok: true, url: `${protocol}//${url.host}${pathname}${search ? `?${search}` : ""}` };
}

/**
 * WS 地址优先级：?ws= 查询参数（二维码带入）> 已保存地址 > 当前站点 /ws
 * （经 vite proxy 或 Sidecar 静态伺服）。?ws= 保存后从地址栏移除，
 * 之后扫码或手动保存的新地址才能生效；无法解析的 ?ws= 记录错误后不采用。
 */
export function resolveWsUrl(): string {
  const params = new URLSearchParams(window.location.search);
  const query = params.get("ws");
  if (query !== null) {
    params.delete("ws");
    const search = params.toString();
    window.history.replaceState(
      window.history.state,
      "",
      `${window.location.pathname}${search ? `?${search}` : ""}${window.location.hash}`,
    );
    const parsed = parseWsAddress(query);
    if (parsed.ok) {
      saveWsUrl(parsed.url);
      return parsed.url;
    }
    console.error("地址栏 ?ws= 不是有效的桌面端地址，已忽略", query, parsed.error);
  }
  const stored = getStoredWsUrl();
  if (stored) return stored;
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
  private authFailureReason: AuthFailureReason | null = null;
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

  getAuthFailureReason(): AuthFailureReason | null {
    return this.authFailureReason;
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
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.manualClose = false;
    this.authFailureReason = null;
    this.setState(this.reconnectAttempt > 0 ? "reconnecting" : "connecting");
    const ws = new WebSocket(resolveWsUrl());
    this.ws = ws;
    ws.onopen = () => {
      if (this.ws !== ws) return;
      this.reconnectAttempt = 0;
      this.lastInboundAt = Date.now();
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

  /** 主动断开并复位退避计数，之后的 connect() 从第一档退避重新开始。 */
  disconnect(): void {
    this.manualClose = true;
    this.stopHeartbeat();
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.reconnectAttempt = 0;
    this.ws?.close();
    this.ws = null;
    this.failAllPending(new Error("客户端主动断开"));
    this.setState("disconnected");
  }

  /** 底层 WebSocket 是否物理处于 OPEN 状态。 */
  isSocketConnected(): boolean {
    return Boolean(this.ws && this.ws.readyState === WebSocket.OPEN);
  }

  /**
   * 发起远程命令。连接未就绪时直接拒绝，由调用方决定何时重试。
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
      const timeoutTimer = window.setTimeout(() => {
        this.pending.delete(id);
        reject(
          new RemoteCommandError(
            "request_timeout",
            `远程命令超时（${method}，${REQUEST_TIMEOUT_MS / 1000}s 未收到响应）`,
          ),
        );
      }, REQUEST_TIMEOUT_MS);
      this.pending.set(id, {
        resolve: (result: unknown) => {
          window.clearTimeout(timeoutTimer);
          resolve(result as T);
        },
        reject: (error: Error) => {
          window.clearTimeout(timeoutTimer);
          reject(error);
        },
      });
      ws.send(JSON.stringify(frame));
    });
  }

  private handleMessage(raw: string): void {
    let frame: WireFrame;
    try {
      frame = JSON.parse(raw) as WireFrame;
    } catch (error) {
      // 无法关联到请求或事件序号；丢掉的事件由下一条事件的序号缺口触发重新同步。
      console.error("WS 收到无法解析的帧", raw, error);
      return;
    }
    switch (frame.kind) {
      case "response":
        this.handleResponse(frame);
        return;
      case "event":
        this.eventListeners.forEach((listener) => listener(frame));
        return;
      case "error":
        this.handleProtocolError(frame);
        return;
      default:
        console.error("WS 收到未知 kind 的帧", frame);
    }
  }

  /** 协议层错误：带 id 时拒绝对应请求，不带 id 时只能记录。 */
  private handleProtocolError(frame: WireProtocolError): void {
    const { id, error } = frame;
    const entry = id === undefined ? undefined : this.pending.get(id);
    if (id === undefined || entry === undefined) {
      console.error("WS 协议错误", error.code, error.message);
      return;
    }
    this.pending.delete(id);
    entry.reject(new RemoteCommandError(error.code, error.message));
  }

  private handleResponse(frame: WireResponse): void {
    const entry = this.pending.get(frame.id);
    if (!entry) {
      // 请求已超时或连接已重建，迟到的响应没有等待方。
      console.warn("WS 收到没有等待方的响应", frame.id);
      return;
    }
    this.pending.delete(frame.id);
    if (frame.ok) {
      entry.resolve(frame.result);
      return;
    }
    const { code, message, details } = frame.error;
    if (code === "unauthorized") {
      this.authFailureReason = message as AuthFailureReason;
      if (this.authFailureReason === "expired_token") clearCredentials();
      // 凭据失效后心跳只会反复被拒，随之停止；界面引导重新配对。
      this.stopHeartbeat();
      this.setState("auth_failed");
    }
    entry.reject(new RemoteCommandError(code, message, details));
  }

  /** 鉴权 bootstrap 成功后由调用方启动心跳；已在运行时保持不变，连接关闭或鉴权失败时停止。 */
  startHeartbeat(): void {
    if (this.heartbeatTimer !== null) return;
    this.heartbeatTimer = window.setInterval(() => {
      if (Date.now() - this.lastInboundAt >= INBOUND_STALE_MS) {
        console.warn("WS 心跳超时（30s 无入站消息），判定半开连接并重连");
        this.abandonSocket();
        return;
      }
      this.request("ping").catch((error: unknown) => {
        // 连接关闭与鉴权失败分别由 onclose 和错误响应驱动状态。
        console.warn("WS ping 失败", error);
      });
    }, PING_INTERVAL_MS);
  }

  /**
   * 半开连接：浏览器关闭握手可能等待约 60s，这里立即摘除 socket、
   * 拒绝在途请求并进入重连，旧 socket 的迟到回调按 this.ws 比对忽略。
   */
  private abandonSocket(): void {
    const ws = this.ws;
    this.stopHeartbeat();
    this.ws = null;
    ws?.close();
    this.failAllPending(new Error("WebSocket 心跳超时，连接已摘除"));
    this.scheduleReconnect();
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer !== null) {
      window.clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  /** 回前台分派：unreachable 复位退避后重连；connected 返回 resync，
      由调用方重新 bootstrap；connecting/reconnecting 维持现有流程。 */
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
