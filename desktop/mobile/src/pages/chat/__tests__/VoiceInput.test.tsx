import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ConversationRecord } from "@shared/contracts/protocol";
import { mobileWsClient, useMobileStore } from "../../../lib/mobileStore";
import { ChatPage } from "../ChatPage";

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;

  readyState = FakeWebSocket.CONNECTING;
  readonly url: string;
  readonly sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  open(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }

  close(): void {
    this.readyState = 3;
    this.onclose?.();
  }

  send(data: string): void {
    this.sent.push(data);
  }

  emit(frame: unknown): void {
    this.onmessage?.({ data: JSON.stringify(frame) });
  }
}

const CONVERSATION: ConversationRecord = {
  conversation_id: "c1",
  project_id: "p1",
  pair_id: "pair-1",
  title: "语音测试",
  last_mode: "chat",
  archived: false,
  created_at: "2026-08-20T00:00:00Z",
  updated_at: "2026-08-20T00:00:00Z",
};

function lastInstance(): FakeWebSocket {
  const instance = FakeWebSocket.instances[FakeWebSocket.instances.length - 1];
  if (!instance) throw new Error("没有 FakeWebSocket 实例");
  return instance;
}

function findSentFrame(method: string): Record<string, unknown> | undefined {
  return lastInstance()
    .sent.map((raw) => JSON.parse(raw) as Record<string, unknown>)
    .find((frame) => frame.method === method);
}

/** 按发送顺序取出某个 method 的全部请求帧。 */
function sentFrames(method: string): Record<string, unknown>[] {
  return lastInstance()
    .sent.map((raw) => JSON.parse(raw) as Record<string, unknown>)
    .filter((frame) => frame.method === method);
}

/** 按发送顺序取出全部请求 method，用于断言 stop 先于 start 这类顺序。 */
function sentMethods(): string[] {
  return lastInstance().sent.map(
    (raw) => (JSON.parse(raw) as { method?: string }).method ?? "",
  );
}

/** 回应一个成功响应帧。 */
function respond(frame: Record<string, unknown>, result: unknown): void {
  lastInstance().emit({ kind: "response", id: frame.id, ok: true, result });
}

/** 回应一个失败响应帧（结构与 wsClient.handleResponse 读取的一致）。 */
function respondError(
  frame: Record<string, unknown>,
  code: string,
  message: string,
): void {
  lastInstance().emit({ kind: "response", id: frame.id, ok: false, error: { code, message } });
}

/**
 * 发送一条 wire 事件，序号取 store 当前 lastSequence + 1。
 * 写死序号会被 store 的缺口守卫判成「需要重新同步」而丢弃事件，读实时值才稳。
 */
function emitEvent(event: string, payload: unknown): void {
  const sequence = useMobileStore.getState().lastSequence + 1;
  lastInstance().emit({ kind: "event", event, sequence, payload });
}

/** 跑完已排队的微任务/宏任务，用于「不应发出请求」这类否定断言。 */
async function flushTasks(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

/** 采集 Worklet 节点的最小形状：测试要靠它驱动一个真实的上行分片。 */
type FakeWorkletNode = {
  port: {
    onmessage: ((event: { data: unknown }) => void) | null;
    postMessage: (message: unknown) => void;
  };
};

/** 最近一次创建的采集 Worklet 节点（引擎 start 时才会建）。 */
let lastWorkletNode: FakeWorkletNode | null = null;

/** 麦克风轨道桩：停止采集引擎时会被 stop，用于断言本地采集是否已停。 */
type FakeStreamTrack = { stop: ReturnType<typeof vi.fn> };
let lastStreamTrack: FakeStreamTrack | null = null;

/** 安装可用的浏览器音频环境桩，供语音交互测试使用。 */
function stubAudioEnvironment(): void {
  lastWorkletNode = null;
  const fakeTrack: FakeStreamTrack = { stop: vi.fn() };
  lastStreamTrack = fakeTrack;
  const fakeStream = {
    getTracks: () => [fakeTrack],
  } as unknown as MediaStream;

  vi.stubGlobal("navigator", {
    ...globalThis.navigator,
    mediaDevices: {
      getUserMedia: vi.fn().mockResolvedValue(fakeStream),
    },
    permissions: {
      query: vi.fn().mockResolvedValue({ state: "granted" }),
    },
  });

  vi.stubGlobal(
    "AudioContext",
    class {
      sampleRate = 48000;
      state = "running";
      destination = {};
      audioWorklet = {
        addModule: vi.fn().mockResolvedValue(undefined),
      };
      resume = vi.fn().mockResolvedValue(undefined);
      close = vi.fn().mockResolvedValue(undefined);
      createMediaStreamSource = vi.fn().mockReturnValue({
        connect: vi.fn(),
        disconnect: vi.fn(),
      });
      createBuffer = vi.fn().mockReturnValue({
        duration: 0.1,
        getChannelData: vi.fn().mockReturnValue(new Float32Array(10)),
      });
      createBufferSource = vi.fn().mockReturnValue({
        buffer: null,
        connect: vi.fn(),
        disconnect: vi.fn(),
        start: vi.fn(),
        stop: vi.fn(),
        onended: null,
      });
    },
  );

  vi.stubGlobal(
    "AudioWorkletNode",
    class {
      port = {
        onmessage: null as ((event: { data: unknown }) => void) | null,
        postMessage: vi.fn(),
      };
      connect = vi.fn();
      disconnect = vi.fn();
      constructor() {
        lastWorkletNode = this;
      }
    },
  );

  // URL.createObjectURL 在 jsdom 中可用，但留一个稳定桩避免意外。
  if (!URL.createObjectURL) {
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: vi.fn().mockReturnValue("blob:fake"),
      revokeObjectURL: vi.fn(),
    });
  }
}

beforeEach(() => {
  vi.stubGlobal("WebSocket", FakeWebSocket);
  mobileWsClient.disconnect();
  FakeWebSocket.instances = [];
  window.localStorage.clear();

  useMobileStore.setState({
    connection: "connected",
    deviceName: "测试设备",
    projects: [],
    conversationsById: { c1: CONVERSATION },
    activeConversationId: null,
    messages: [],
    toolRuns: [],
    approvals: [],
    pair: null,
    activeTask: null,
    lastSequence: 10,
    bootstrapped: true,
    voice: {
      capture: { state: "idle", sessionId: null, error: null },
      transcript: null,
      playback: { messageId: null, state: "idle", error: null },
      availability: {
        secureContext: true,
        micPermission: "unknown",
        supported: true,
      },
      ttsChunks: {},
      ttsDroppedChunks: {},
    },
  });

  useMobileStore.getState().start();
  mobileWsClient.connect();
  lastInstance().open();

  // 避免 mount 时 refreshVoiceAvailability 用 jsdom 环境覆盖手动设置的可用性状态
  useMobileStore.setState({ refreshVoiceAvailability: async () => {} });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("ChatPage V0.3.5 语音入口可用性矩阵", () => {
  it("连接断开时语音入口禁用并说明原因", () => {
    useMobileStore.setState({
      connection: "disconnected",
      voice: {
        ...useMobileStore.getState().voice,
        availability: { supported: true, secureContext: true, micPermission: "granted" },
      },
    });
    render(<ChatPage conversationId="c1" />);

    expect(screen.getByTestId("voice-disabled-reason")).toHaveTextContent(/连接已断开/);
  });

  it("非 HTTPS（非 secure context）时禁用并指向 Tailscale 文档", () => {
    useMobileStore.setState({
      voice: {
        ...useMobileStore.getState().voice,
        availability: { supported: true, secureContext: false, micPermission: "granted" },
      },
    });
    render(<ChatPage conversationId="c1" />);

    expect(screen.getByTestId("voice-disabled-reason")).toHaveTextContent(/HTTP/);
    expect(screen.getByTestId("voice-disabled-reason")).toHaveTextContent(/Tailscale/);
  });

  it("麦克风权限被拒时禁用并提示去授权", () => {
    useMobileStore.setState({
      voice: {
        ...useMobileStore.getState().voice,
        availability: { supported: true, secureContext: true, micPermission: "denied" },
      },
    });
    render(<ChatPage conversationId="c1" />);

    expect(screen.getByTestId("voice-disabled-reason")).toHaveTextContent(/麦克风权限被拒绝/);
  });

  it("浏览器不支持麦克风时禁用", () => {
    useMobileStore.setState({
      voice: {
        ...useMobileStore.getState().voice,
        availability: { supported: false, secureContext: true, micPermission: "unknown" },
      },
    });
    render(<ChatPage conversationId="c1" />);

    expect(screen.getByTestId("voice-disabled-reason")).toHaveTextContent(/不支持麦克风/);
  });

  it("全部条件满足时显示语音触发按钮", () => {
    useMobileStore.setState({
      voice: {
        ...useMobileStore.getState().voice,
        availability: { supported: true, secureContext: true, micPermission: "granted" },
      },
    });
    render(<ChatPage conversationId="c1" />);

    expect(screen.getByTestId("voice-trigger-btn")).toBeInTheDocument();
    expect(screen.queryByTestId("voice-disabled-reason")).toBeNull();
  });
});

describe("ChatPage V0.3.5 语音交互", () => {
  beforeEach(() => {
    stubAudioEnvironment();
    useMobileStore.setState({
      voice: {
        ...useMobileStore.getState().voice,
        availability: { supported: true, secureContext: true, micPermission: "granted" },
      },
    });
  });

  it("点击语音触发按钮只打开面板，不隐式开始采集", async () => {
    render(<ChatPage conversationId="c1" />);

    fireEvent.click(screen.getByTestId("voice-trigger-btn"));

    // 面板内是两个互斥操作：按住说话 + 自动检测
    expect(screen.getByTestId("voice-hold-btn")).toBeInTheDocument();
    expect(screen.getByTestId("voice-auto-toggle-btn")).toBeInTheDocument();

    // V0.3.9 P1：触发器只负责开面板，不再顺带发起服务端语音会话
    await flushTasks();
    expect(sentFrames("voice.mobile_ptt_start")).toHaveLength(0);
    expect(useMobileStore.getState().voice.capture.state).toBe("idle");
  });

  it("点击自动检测按钮后服务端返回 session_id 展示聆听中状态", async () => {
    render(<ChatPage conversationId="c1" />);

    fireEvent.click(screen.getByTestId("voice-trigger-btn"));
    fireEvent.click(screen.getByTestId("voice-auto-toggle-btn"));
    await vi.waitFor(() => expect(findSentFrame("voice.mobile_ptt_start")).toBeDefined());

    const frame = findSentFrame("voice.mobile_ptt_start")!;
    expect(frame.params).toMatchObject({ conversation_id: "c1" });
    lastInstance().emit({
      kind: "response",
      id: frame.id,
      ok: true,
      result: { session_id: "sess-ui-1" },
    });

    await waitFor(() => {
      // 用自动检测那一行的完整文案定位：大按钮在 recording 时也显示「聆听中…」，
      // 只匹配 /聆听中/ 会同时命中两处。
      expect(screen.getByText(/检测到静音自动停止/)).toBeInTheDocument();
    });
  });

  it("voice.mobile_transcript partial/final 正确展示转写文本", async () => {
    render(<ChatPage conversationId="c1" />);

    fireEvent.click(screen.getByTestId("voice-trigger-btn"));
    fireEvent.click(screen.getByTestId("voice-auto-toggle-btn"));
    await vi.waitFor(() => expect(findSentFrame("voice.mobile_ptt_start")).toBeDefined());

    // 走真实入口建立会话（jsdom 里不等待 AudioWorklet 完整启动，直接给响应）
    respond(findSentFrame("voice.mobile_ptt_start")!, { session_id: "sess-ui-2" });
    await waitFor(() =>
      expect(useMobileStore.getState().voice.capture.sessionId).toBe("sess-ui-2"),
    );

    lastInstance().emit({
      kind: "event",
      event: "voice.mobile_transcript",
      sequence: 11,
      payload: { session_id: "sess-ui-2", text: "你好", is_final: false },
    });

    await waitFor(() => {
      expect(screen.getByTestId("voice-transcript")).toHaveTextContent(/转写中/);
      expect(screen.getByTestId("voice-transcript")).toHaveTextContent(/你好/);
    });

    lastInstance().emit({
      kind: "event",
      event: "voice.mobile_transcript",
      sequence: 12,
      payload: { session_id: "sess-ui-2", text: "你好角色", is_final: true },
    });

    await waitFor(() => {
      expect(screen.getByTestId("voice-transcript")).toHaveTextContent(/转写完成/);
      expect(screen.getByTestId("voice-transcript")).toHaveTextContent(/你好角色/);
    });
  });

  it("转写失败时如实展示错误与重试入口", async () => {
    render(<ChatPage conversationId="c1" />);

    fireEvent.click(screen.getByTestId("voice-trigger-btn"));
    fireEvent.click(screen.getByTestId("voice-auto-toggle-btn"));
    await vi.waitFor(() => expect(findSentFrame("voice.mobile_ptt_start")).toBeDefined());

    // 录制中收到转写失败：capture 仍在 recording，错误如实写入 store
    useMobileStore.setState({
      voice: {
        ...useMobileStore.getState().voice,
        capture: { state: "recording", sessionId: "sess-ui-3", error: "未能识别到语音内容" },
      },
    });

    await waitFor(() => {
      expect(screen.getByTestId("voice-capture-error")).toHaveTextContent(/未能识别到语音内容/);
      expect(screen.getByTestId("voice-retry-btn")).toBeInTheDocument();
    });
  });

  it("V0.3.7 V9 收尾：录制中卸载页面补发 voice.mobile_ptt_stop，不泄漏服务端会话", async () => {
    const { unmount } = render(<ChatPage conversationId="c1" />);

    fireEvent.click(screen.getByTestId("voice-trigger-btn"));
    fireEvent.click(screen.getByTestId("voice-auto-toggle-btn"));
    await vi.waitFor(() => expect(findSentFrame("voice.mobile_ptt_start")).toBeDefined());

    const startFrame = findSentFrame("voice.mobile_ptt_start")!;
    lastInstance().emit({
      kind: "response",
      id: startFrame.id,
      ok: true,
      result: { session_id: "sess-unmount-1" },
    });
    await waitFor(() => {
      expect(useMobileStore.getState().voice.capture.sessionId).toBe("sess-unmount-1");
    });

    unmount();

    await vi.waitFor(() => {
      const stopFrame = findSentFrame("voice.mobile_ptt_stop");
      expect(stopFrame).toBeDefined();
      expect(stopFrame?.params).toMatchObject({ session_id: "sess-unmount-1" });
    });
  });

  it("V0.3.7 V9 收尾：启动中卸载页面，服务端会话建立后仍补发停止", async () => {
    const { unmount } = render(<ChatPage conversationId="c1" />);

    fireEvent.click(screen.getByTestId("voice-trigger-btn"));
    fireEvent.click(screen.getByTestId("voice-auto-toggle-btn"));
    await vi.waitFor(() => expect(findSentFrame("voice.mobile_ptt_start")).toBeDefined());

    // 卸载发生在 voice.mobile_ptt_start 仍在途时
    const startFrame = findSentFrame("voice.mobile_ptt_start")!;
    unmount();

    // 服务端此刻才确认会话建立
    lastInstance().emit({
      kind: "response",
      id: startFrame.id,
      ok: true,
      result: { session_id: "sess-unmount-race" },
    });

    await vi.waitFor(() => {
      const stopFrame = findSentFrame("voice.mobile_ptt_stop");
      expect(stopFrame).toBeDefined();
      expect(stopFrame?.params).toMatchObject({ session_id: "sess-unmount-race" });
    });
  });
});

describe("ChatPage V0.3.9 P1 按住说话（PTT）", () => {
  beforeEach(() => {
    stubAudioEnvironment();
    useMobileStore.setState({
      voice: {
        ...useMobileStore.getState().voice,
        availability: { supported: true, secureContext: true, micPermission: "granted" },
      },
    });
  });

  /** 打开面板并按下「按住说话」，返回会话建立后的 session_id。 */
  async function startHold(sessionId: string, pointerId: number): Promise<HTMLElement> {
    const holdBtn = screen.getByTestId("voice-hold-btn");
    fireEvent.pointerDown(holdBtn, { pointerId });
    await vi.waitFor(() => expect(findSentFrame("voice.mobile_ptt_start")).toBeDefined());
    respond(sentFrames("voice.mobile_ptt_start").at(-1)!, { session_id: sessionId });
    await waitFor(() =>
      expect(useMobileStore.getState().voice.capture.sessionId).toBe(sessionId),
    );
    return holdBtn;
  }

  it("pointerdown 起采、pointerup 停止，click 不触发启动", async () => {
    render(<ChatPage conversationId="c1" />);
    fireEvent.click(screen.getByTestId("voice-trigger-btn"));

    const holdBtn = await startHold("sess-ptt-1", 1);
    expect(sentFrames("voice.mobile_ptt_start")).toHaveLength(1);

    fireEvent.pointerUp(holdBtn, { pointerId: 1 });

    await vi.waitFor(() => {
      const stopFrame = findSentFrame("voice.mobile_ptt_stop");
      expect(stopFrame).toBeDefined();
      expect(stopFrame?.params).toMatchObject({ session_id: "sess-ptt-1" });
    });

    // click 不是按住说话的语义，不得再启动一次采集
    fireEvent.click(holdBtn);
    await flushTasks();
    expect(sentFrames("voice.mobile_ptt_start")).toHaveLength(1);
  });

  it("R1 回归：自动检测录制中按下按住说话，先停旧会话再真实启动新会话", async () => {
    render(<ChatPage conversationId="c1" />);
    fireEvent.click(screen.getByTestId("voice-trigger-btn"));

    // 用户打开面板后先点了自动检测（旧实现在这一步之后所有启动都被静默拦截）
    fireEvent.click(screen.getByTestId("voice-auto-toggle-btn"));
    await vi.waitFor(() => expect(findSentFrame("voice.mobile_ptt_start")).toBeDefined());
    respond(sentFrames("voice.mobile_ptt_start")[0]!, { session_id: "sess-auto" });
    await waitFor(() =>
      expect(useMobileStore.getState().voice.capture.state).toBe("recording"),
    );

    fireEvent.pointerDown(screen.getByTestId("voice-hold-btn"), { pointerId: 2 });

    // 接替旧会话：先发 stop
    await vi.waitFor(() => {
      expect(sentFrames("voice.mobile_ptt_stop")[0]?.params).toMatchObject({
        session_id: "sess-auto",
      });
    });

    // 旧会话停止成功后，新的 start 必须真的发出
    respond(sentFrames("voice.mobile_ptt_stop")[0]!, {
      session_id: "sess-auto",
      transcript: "",
      conversation_id: "c1",
    });
    await vi.waitFor(() => expect(sentFrames("voice.mobile_ptt_start")).toHaveLength(2));

    const methods = sentMethods();
    expect(methods.indexOf("voice.mobile_ptt_stop")).toBeLessThan(
      methods.lastIndexOf("voice.mobile_ptt_start"),
    );

    respond(sentFrames("voice.mobile_ptt_start")[1]!, { session_id: "sess-hold" });
    await waitFor(() =>
      expect(useMobileStore.getState().voice.capture.sessionId).toBe("sess-hold"),
    );
  });

  it("启动在途抬起：会话建立后补发停止，不泄漏服务端会话", async () => {
    render(<ChatPage conversationId="c1" />);
    fireEvent.click(screen.getByTestId("voice-trigger-btn"));

    const holdBtn = screen.getByTestId("voice-hold-btn");
    fireEvent.pointerDown(holdBtn, { pointerId: 3 });
    await vi.waitFor(() => expect(findSentFrame("voice.mobile_ptt_start")).toBeDefined());

    // 语音会话仍在途（服务端还没回 session_id）时抬起
    expect(sentFrames("voice.mobile_ptt_stop")).toHaveLength(0);
    fireEvent.pointerUp(holdBtn, { pointerId: 3 });
    await flushTasks();
    expect(sentFrames("voice.mobile_ptt_stop")).toHaveLength(0);

    // 服务端此刻才确认会话建立
    respond(sentFrames("voice.mobile_ptt_start")[0]!, { session_id: "sess-race" });

    await vi.waitFor(() => {
      const stopFrame = findSentFrame("voice.mobile_ptt_stop");
      expect(stopFrame).toBeDefined();
      expect(stopFrame?.params).toMatchObject({ session_id: "sess-race" });
    });
  });

  it("pointercancel 同样结束采集并发 voice.mobile_ptt_stop", async () => {
    render(<ChatPage conversationId="c1" />);
    fireEvent.click(screen.getByTestId("voice-trigger-btn"));

    const holdBtn = await startHold("sess-cancel", 4);

    fireEvent.pointerCancel(holdBtn, { pointerId: 4 });

    await vi.waitFor(() => {
      expect(findSentFrame("voice.mobile_ptt_stop")?.params).toMatchObject({
        session_id: "sess-cancel",
      });
    });
  });

  it("停止响应落地即复位：capture 回 idle、最终转写写入、可立即再次开始", async () => {
    render(<ChatPage conversationId="c1" />);
    fireEvent.click(screen.getByTestId("voice-trigger-btn"));

    const holdBtn = await startHold("sess-reset", 5);
    fireEvent.pointerUp(holdBtn, { pointerId: 5 });

    await vi.waitFor(() => expect(findSentFrame("voice.mobile_ptt_stop")).toBeDefined());
    respond(sentFrames("voice.mobile_ptt_stop")[0]!, {
      session_id: "sess-reset",
      transcript: "今天天气不错",
      conversation_id: "c1",
    });

    // 关键：不依赖 voice.mobile_transcript(is_final) 事件也要复位
    await waitFor(() => {
      const voice = useMobileStore.getState().voice;
      expect(voice.capture.state).toBe("idle");
      expect(voice.capture.sessionId).toBeNull();
      expect(voice.transcript).toEqual({
        sessionId: "sess-reset",
        text: "今天天气不错",
        isFinal: true,
      });
    });
    expect(screen.getByTestId("voice-transcript")).toHaveTextContent("今天天气不错");

    // 复位后立刻能开始下一段采集（旧实现会永久卡在 stopping）
    fireEvent.pointerDown(holdBtn, { pointerId: 6 });
    await vi.waitFor(() => expect(sentFrames("voice.mobile_ptt_start")).toHaveLength(2));
  });

  it("按住说话状态行：准备中… / 聆听中，抬起发送", async () => {
    render(<ChatPage conversationId="c1" />);
    fireEvent.click(screen.getByTestId("voice-trigger-btn"));

    fireEvent.pointerDown(screen.getByTestId("voice-hold-btn"), { pointerId: 7 });

    await waitFor(() => {
      expect(screen.getByTestId("voice-hold-status")).toHaveTextContent("准备中…");
    });

    respond(sentFrames("voice.mobile_ptt_start")[0]!, { session_id: "sess-status" });

    await waitFor(() => {
      expect(screen.getByTestId("voice-hold-status")).toHaveTextContent("聆听中，抬起发送");
    });
  });

  it("按住说话启动失败：面板保持打开、如实显示错误，不给 click 重试入口", async () => {
    render(<ChatPage conversationId="c1" />);
    fireEvent.click(screen.getByTestId("voice-trigger-btn"));

    fireEvent.pointerDown(screen.getByTestId("voice-hold-btn"), { pointerId: 8 });
    await vi.waitFor(() => expect(findSentFrame("voice.mobile_ptt_start")).toBeDefined());
    respondError(sentFrames("voice.mobile_ptt_start")[0]!, "voice_unavailable", "语音服务不可用");

    await waitFor(() => {
      expect(screen.getByTestId("voice-capture-error")).toHaveTextContent("语音服务不可用");
    });
    // 旧实现里错误路径会把 mode 复位成 off 并连带关掉面板，错误提示随面板消失
    expect(screen.getByTestId("voice-hold-btn")).toBeInTheDocument();
    expect(screen.getByTestId("voice-close-btn")).toBeInTheDocument();
    // 按住说话是按压语义：重试就是再按一次大按钮，不给 click 重试按钮
    expect(screen.queryByTestId("voice-retry-btn")).toBeNull();
    expect(screen.getByTestId("voice-hold-retry-hint")).toHaveTextContent(
      "请再次按住说话重试",
    );
  });

  it("短按即抬起：服务端 voice_transcript_empty 时如实显示未识别到语音内容", async () => {
    render(<ChatPage conversationId="c1" />);
    fireEvent.click(screen.getByTestId("voice-trigger-btn"));

    const holdBtn = screen.getByTestId("voice-hold-btn");
    fireEvent.pointerDown(holdBtn, { pointerId: 9 });
    await vi.waitFor(() => expect(findSentFrame("voice.mobile_ptt_start")).toBeDefined());

    // 抬起发生在会话建立之前
    fireEvent.pointerUp(holdBtn, { pointerId: 9 });
    respond(sentFrames("voice.mobile_ptt_start")[0]!, { session_id: "sess-short" });

    await vi.waitFor(() => expect(findSentFrame("voice.mobile_ptt_stop")).toBeDefined());
    respondError(
      sentFrames("voice.mobile_ptt_stop")[0]!,
      "voice_transcript_empty",
      "未识别到语音内容",
    );

    await waitFor(() => {
      expect(screen.getByTestId("voice-capture-error")).toHaveTextContent("未识别到语音内容");
    });
  });

  it("F1 回归：上一段停止仍在途时按下，按压不被丢弃（等旧会话停稳后再启动）", async () => {
    render(<ChatPage conversationId="c1" />);
    fireEvent.click(screen.getByTestId("voice-trigger-btn"));

    const holdBtn = await startHold("sess-old", 11);
    fireEvent.pointerUp(holdBtn, { pointerId: 11 });

    // 第一段 stop 在途：不回应，store 停在 stopping（服务端最坏约 5s 尾超时）
    await vi.waitFor(() => expect(sentFrames("voice.mobile_ptt_stop")).toHaveLength(1));
    await waitFor(() =>
      expect(useMobileStore.getState().voice.capture.state).toBe("stopping"),
    );

    // 这个窗口里马上再按一次
    fireEvent.pointerDown(holdBtn, { pointerId: 12 });
    await flushTasks();

    // 旧会话没停稳之前不启动，但也不是静默丢弃：等它停稳后必须真的发出新 start
    expect(sentFrames("voice.mobile_ptt_start")).toHaveLength(1);
    expect(useMobileStore.getState().voice.capture.error).toBeNull();

    respond(sentFrames("voice.mobile_ptt_stop")[0]!, {
      session_id: "sess-old",
      transcript: "第一段",
      conversation_id: "c1",
    });

    await vi.waitFor(() => expect(sentFrames("voice.mobile_ptt_start")).toHaveLength(2));
    const methods = sentMethods();
    expect(methods.indexOf("voice.mobile_ptt_stop")).toBeLessThan(
      methods.lastIndexOf("voice.mobile_ptt_start"),
    );

    respond(sentFrames("voice.mobile_ptt_start")[1]!, { session_id: "sess-new" });
    await waitFor(() =>
      expect(useMobileStore.getState().voice.capture.sessionId).toBe("sess-new"),
    );
  });

  it("F2 回归：自动检测启动失败后重试按钮可达，点击重新发起采集", async () => {
    render(<ChatPage conversationId="c1" />);
    fireEvent.click(screen.getByTestId("voice-trigger-btn"));
    fireEvent.click(screen.getByTestId("voice-auto-toggle-btn"));

    await vi.waitFor(() => expect(findSentFrame("voice.mobile_ptt_start")).toBeDefined());
    respondError(sentFrames("voice.mobile_ptt_start")[0]!, "voice_unavailable", "语音服务不可用");

    // 启动失败后 capture 回 idle，复位 effect 会把 mode 收回 off——
    // 重试入口必须还在（按最近一次尝试的模式给，而不是按当前 mode）
    await waitFor(() => {
      expect(useMobileStore.getState().voice.capture.state).toBe("idle");
      expect(screen.getByTestId("voice-retry-btn")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("voice-retry-btn"));
    await vi.waitFor(() => expect(sentFrames("voice.mobile_ptt_start")).toHaveLength(2));
  });

  it("F4 回归：上行分片失败留下的错误不被停止成功复位冲掉", async () => {
    render(<ChatPage conversationId="c1" />);
    fireEvent.click(screen.getByTestId("voice-trigger-btn"));

    await startHold("sess-chunk", 13);
    // 采集引擎 start 之后才会有 Worklet 节点
    await waitFor(() => {
      if (!lastWorkletNode) throw new Error("采集引擎尚未创建 AudioWorkletNode");
    });
    const worklet = lastWorkletNode as FakeWorkletNode;

    // 驱动一个真实的上行分片，并让服务端拒绝它
    worklet.port.onmessage?.({
      data: { type: "chunk", samples: new Int16Array([1, 2, 3]).buffer },
    });
    await vi.waitFor(() => expect(sentFrames("voice.mobile_audio_chunk")).toHaveLength(1));
    respondError(
      sentFrames("voice.mobile_audio_chunk")[0]!,
      "voice_audio_seq_gap",
      "音频分片序号不连续",
    );

    // 分片失败会经引擎 onError 触发停止
    await vi.waitFor(() => expect(sentFrames("voice.mobile_ptt_stop")).toHaveLength(1));
    respond(sentFrames("voice.mobile_ptt_stop")[0]!, {
      session_id: "sess-chunk",
      transcript: "",
      conversation_id: "c1",
    });

    await waitFor(() => {
      expect(useMobileStore.getState().voice.capture.state).toBe("idle");
      expect(useMobileStore.getState().voice.capture.error).toContain("音频分片序号不连续");
    });
    expect(screen.getByTestId("voice-capture-error")).toHaveTextContent("音频分片序号不连续");
  });

  it("F4 生产时序版：is_final 事件先到也不清掉上行分片失败留下的错误", async () => {
    render(<ChatPage conversationId="c1" />);
    fireEvent.click(screen.getByTestId("voice-trigger-btn"));

    await startHold("sess-chunk-prod", 18);
    await waitFor(() => {
      if (!lastWorkletNode) throw new Error("采集引擎尚未创建 AudioWorkletNode");
    });
    const worklet = lastWorkletNode as FakeWorkletNode;

    worklet.port.onmessage?.({
      data: { type: "chunk", samples: new Int16Array([1, 2, 3]).buffer },
    });
    await vi.waitFor(() => expect(sentFrames("voice.mobile_audio_chunk")).toHaveLength(1));
    respondError(
      sentFrames("voice.mobile_audio_chunk")[0]!,
      "voice_audio_seq_gap",
      "音频分片序号不连续",
    );

    // 分片失败会经引擎 onError 触发停止
    await vi.waitFor(() => expect(sentFrames("voice.mobile_ptt_stop")).toHaveLength(1));

    // 生产时序：服务端 end_session 先回调 is_final 事件，stop 响应后到
    emitEvent("voice.mobile_transcript", {
      session_id: "sess-chunk-prod",
      text: "",
      is_final: true,
    });
    await waitFor(() =>
      expect(useMobileStore.getState().voice.capture.state).toBe("idle"),
    );
    expect(useMobileStore.getState().voice.capture.error).toContain("音频分片序号不连续");

    respond(sentFrames("voice.mobile_ptt_stop")[0]!, {
      session_id: "sess-chunk-prod",
      transcript: "",
      conversation_id: "c1",
    });
    await flushTasks();

    // 事件与停响应都落地之后，真实错误仍在、且界面可见
    expect(useMobileStore.getState().voice.capture.error).toContain("音频分片序号不连续");
    expect(screen.getByTestId("voice-capture-error")).toHaveTextContent("音频分片序号不连续");
  });

  it("F3：stopVoiceCapture 显式 sessionId 覆盖 store 现值，且不覆写已接管的会话", async () => {
    // store 层断言：目标会话取自显式入参，而不是 store 现值。
    // 这个夹具同时就是 G1 的形态（store 已被新会话接管），所以响应落地时
    // 只发请求、不写 capture，也不写 transcript。
    useMobileStore.setState({
      voice: {
        ...useMobileStore.getState().voice,
        capture: { state: "recording", sessionId: "sess-store", error: null },
        transcript: null,
      },
    });

    const stopping = useMobileStore.getState().stopVoiceCapture("sess-explicit");

    await vi.waitFor(() => {
      expect(sentFrames("voice.mobile_ptt_stop")[0]?.params).toEqual({
        session_id: "sess-explicit",
      });
    });
    expect(useMobileStore.getState().voice.capture).toEqual({
      state: "recording",
      sessionId: "sess-store",
      error: null,
    });

    respond(sentFrames("voice.mobile_ptt_stop")[0]!, {
      session_id: "sess-explicit",
      transcript: "会话收尾",
      conversation_id: "c1",
    });
    await stopping;

    // 迟到响应不得覆写已接管的新会话，也不得把旧会话转写盖上去
    expect(useMobileStore.getState().voice.capture).toEqual({
      state: "recording",
      sessionId: "sess-store",
      error: null,
    });
    expect(useMobileStore.getState().voice.transcript).toBeNull();
  });

  it("G1 回归：final 事件先到、stop 响应后到时，新会话不被旧停止抹掉", async () => {
    render(<ChatPage conversationId="c1" />);
    fireEvent.click(screen.getByTestId("voice-trigger-btn"));

    const holdA = await startHold("sess-a", 14);
    fireEvent.pointerUp(holdA, { pointerId: 14 });
    await vi.waitFor(() => expect(sentFrames("voice.mobile_ptt_stop")).toHaveLength(1));

    // 服务端 end_session 先回调 is_final（mobile_audio.py:221）：store 被事件置 idle
    emitEvent("voice.mobile_transcript", {
      session_id: "sess-a",
      text: "第一段",
      is_final: true,
    });
    await waitFor(() =>
      expect(useMobileStore.getState().voice.capture.sessionId).toBeNull(),
    );

    // 停止响应还没到，用户已经按下第二段并建起会话 B
    const holdB = screen.getByTestId("voice-hold-btn");
    fireEvent.pointerDown(holdB, { pointerId: 15 });
    await vi.waitFor(() => expect(sentFrames("voice.mobile_ptt_start")).toHaveLength(2));
    respond(sentFrames("voice.mobile_ptt_start")[1]!, { session_id: "sess-b" });
    await waitFor(() =>
      expect(useMobileStore.getState().voice.capture.sessionId).toBe("sess-b"),
    );

    // 旧会话 A 的 stop 响应此刻才到：不得覆写 B 的前端状态
    respond(sentFrames("voice.mobile_ptt_stop")[0]!, {
      session_id: "sess-a",
      transcript: "第一段",
      conversation_id: "c1",
    });
    await flushTasks();
    expect(useMobileStore.getState().voice.capture).toEqual({
      state: "recording",
      sessionId: "sess-b",
      error: null,
    });

    // 抬起后 B 的停止必须真实发出：既不能被 A 的在途停止吞掉，也不能漏发
    fireEvent.pointerUp(holdB, { pointerId: 15 });
    await vi.waitFor(() => expect(sentFrames("voice.mobile_ptt_stop")).toHaveLength(2));
    expect(sentFrames("voice.mobile_ptt_stop")[1]?.params).toEqual({
      session_id: "sess-b",
    });
  });

  it("G1：在途停止属于别的会话时不复用，本地采集立即停、新会话的停止仍发出", async () => {
    render(<ChatPage conversationId="c1" />);
    fireEvent.click(screen.getByTestId("voice-trigger-btn"));

    const holdA = await startHold("sess-a2", 16);
    fireEvent.pointerUp(holdA, { pointerId: 16 });
    await vi.waitFor(() => expect(sentFrames("voice.mobile_ptt_stop")).toHaveLength(1));

    emitEvent("voice.mobile_transcript", {
      session_id: "sess-a2",
      text: "第一段",
      is_final: true,
    });
    await waitFor(() =>
      expect(useMobileStore.getState().voice.capture.sessionId).toBeNull(),
    );

    const holdB = screen.getByTestId("voice-hold-btn");
    fireEvent.pointerDown(holdB, { pointerId: 17 });
    await vi.waitFor(() => expect(sentFrames("voice.mobile_ptt_start")).toHaveLength(2));
    respond(sentFrames("voice.mobile_ptt_start")[1]!, { session_id: "sess-b2" });
    await waitFor(() =>
      expect(useMobileStore.getState().voice.capture.sessionId).toBe("sess-b2"),
    );

    // 第二段的本地采集已经跑起来：标记后抬起
    const track = lastStreamTrack as FakeStreamTrack;
    track.stop.mockClear();

    // A 的停止仍在途（刻意不回应）
    fireEvent.pointerUp(holdB, { pointerId: 17 });
    await flushTasks();

    // 本地采集立即停：别人的在途停止不能当作「本地也停了」
    expect(track.stop).toHaveBeenCalled();
    // B 的停止已排队但还没发出（串在 A 之后），绝不能被 A 的在途 Promise 吞掉
    expect(sentFrames("voice.mobile_ptt_stop")).toHaveLength(1);

    respond(sentFrames("voice.mobile_ptt_stop")[0]!, {
      session_id: "sess-a2",
      transcript: "第一段",
      conversation_id: "c1",
    });

    await vi.waitFor(() => expect(sentFrames("voice.mobile_ptt_stop")).toHaveLength(2));
    expect(sentFrames("voice.mobile_ptt_stop")[1]?.params).toEqual({
      session_id: "sess-b2",
    });
  });
});
