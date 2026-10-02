import { vi } from "vitest";
import type { WireRequest } from "../lib/wsClient";

export type SentFrame = WireRequest;

/**
 * 按 JSONL 协议回放的 WebSocket 夹具：服务端帧经 emit 注入，sent 记录客户端发出的原始帧。
 * autoResults 登记的方法收到请求后，在下一个微任务回放成功响应。
 */
export class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static readonly autoResults = new Map<string, unknown>();
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  readyState = FakeWebSocket.CONNECTING;
  readonly sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(readonly url: string) {
    FakeWebSocket.instances.push(this);
  }

  open(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }

  close(): void {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.();
  }

  send(data: string): void {
    this.sent.push(data);
    const frame = JSON.parse(data) as SentFrame;
    if (frame.kind === "request" && FakeWebSocket.autoResults.has(frame.method)) {
      const result = FakeWebSocket.autoResults.get(frame.method);
      queueMicrotask(() => this.respond(frame, result));
    }
  }

  /** 注入一帧服务端消息；真实协议的事件都带 stream_id，用例未指定时补上当前代次。 */
  emit(frame: unknown): void {
    const wire =
      (frame as { kind?: string }).kind === "event"
        ? { stream_id: "stream-current", ...(frame as object) }
        : frame;
    this.onmessage?.({ data: JSON.stringify(wire) });
  }

  /** 客户端发出的请求帧，按发送顺序；传 method 时只取该方法。 */
  sentFrames(method?: string): SentFrame[] {
    const frames = this.sent.map((raw) => JSON.parse(raw) as SentFrame);
    return method === undefined ? frames : frames.filter((frame) => frame.method === method);
  }

  /** 该方法最近一次请求帧；没有发出过时抛错。 */
  lastFrame(method: string): SentFrame {
    const frame = this.sentFrames(method).at(-1);
    if (!frame) throw new Error(`客户端尚未发出 ${method}`);
    return frame;
  }

  respond(frame: { id: string }, result: unknown): void {
    this.emit({ kind: "response", id: frame.id, ok: true, result });
  }

  respondError(frame: { id: string }, code: string, message: string): void {
    this.emit({ kind: "response", id: frame.id, ok: false, error: { code, message } });
  }
}

/** 清空实例与自动响应登记，并用夹具替换全局 WebSocket；配合 vi.unstubAllGlobals 还原。 */
export function installFakeWebSocket(): void {
  FakeWebSocket.instances = [];
  FakeWebSocket.autoResults.clear();
  vi.stubGlobal("WebSocket", FakeWebSocket);
}

export function latestSocket(): FakeWebSocket {
  const instance = FakeWebSocket.instances.at(-1);
  if (!instance) throw new Error("没有 FakeWebSocket 实例");
  return instance;
}
