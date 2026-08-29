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

/** 重连退避序列（毫秒）；用尽后进入 unreachable，等用户手动重试。 */
const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 16000];

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
}

export function clearCredentials(): void {
  const store = storage();
  if (!store) return;
  store.removeItem(TOKEN_KEY);
  store.removeItem(DEVICE_NAME_KEY);
}

/**
 * WS 地址解析优先级：?ws= 查询参数（二维码带入）> localStorage 缓存 >
 * 当前站点 /ws（经 vite proxy 或反向代理到 Sidecar）。
 */
export function resolveWsUrl(): string {
  if (typeof window === "undefined") return "ws://127.0.0.1:8765/ws";
  const query = new URLSearchParams(window.location.search).get("ws");
  if (query && query.length > 0) {
    storage()?.setItem(WS_URL_KEY, query);
    return query;
  }
  const stored = storage()?.getItem(WS_URL_KEY);
  if (stored && stored.length > 0) return stored;
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
  private nextId = 1;
  private readonly pending = new Map<string, PendingEntry>();
  private readonly eventListeners = new Set<(event: WireEvent) => void>();
  private readonly stateListeners = new Set<(state: MobileConnectionState) => void>();
  private reconnectAttempt = 0;
  private reconnectTimer: number | null = null;
  private manualClose = false;

  getState(): MobileConnectionState {
    return this.state;
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
      this.reconnectAttempt = 0;
      this.setState("connected");
    };
    ws.onmessage = (message: MessageEvent<string>) => {
      this.handleMessage(String(message.data));
    };
    ws.onclose = () => {
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
    if (this.reconnectTimer !== null && typeof window !== "undefined") {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.ws?.close();
    this.ws = null;
    this.failAllPending(new Error("客户端主动断开"));
    this.setState("disconnected");
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
      this.pending.set(id, {
        resolve: resolve as (result: unknown) => void,
        reject,
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
    if (code === "unauthorized") {
      // 如实暴露鉴权失败：UI 引导重新配对，不在网络层静默换状态。
      this.setState("auth_failed");
    }
    entry.reject(
      new RemoteCommandError(code, message, frame.error?.details),
    );
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
