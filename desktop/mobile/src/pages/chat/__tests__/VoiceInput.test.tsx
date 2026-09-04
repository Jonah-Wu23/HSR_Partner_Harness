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

/** 安装可用的浏览器音频环境桩，供语音交互测试使用。 */
function stubAudioEnvironment(): void {
  const fakeStream = {
    getTracks: () => [{ stop: vi.fn() }],
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

  it("点击语音触发按钮进入面板并发送 voice.mobile_ptt_start", async () => {
    render(<ChatPage conversationId="c1" />);

    fireEvent.click(screen.getByTestId("voice-trigger-btn"));

    await vi.waitFor(() => {
      const frame = findSentFrame("voice.mobile_ptt_start");
      expect(frame).toBeDefined();
      expect(frame?.params).toMatchObject({ conversation_id: "c1" });
    });
  });

  it("服务端返回 session_id 后展示聆听中状态", async () => {
    render(<ChatPage conversationId="c1" />);

    fireEvent.click(screen.getByTestId("voice-trigger-btn"));
    await vi.waitFor(() => expect(findSentFrame("voice.mobile_ptt_start")).toBeDefined());

    const frame = findSentFrame("voice.mobile_ptt_start")!;
    lastInstance().emit({
      kind: "response",
      id: frame.id,
      ok: true,
      result: { session_id: "sess-ui-1" },
    });

    await waitFor(() => {
      expect(screen.getByText(/聆听中/)).toBeInTheDocument();
    });
  });

  it("voice.mobile_transcript partial/final 正确展示转写文本", async () => {
    render(<ChatPage conversationId="c1" />);

    fireEvent.click(screen.getByTestId("voice-trigger-btn"));
    await vi.waitFor(() => expect(findSentFrame("voice.mobile_ptt_start")).toBeDefined());

    // 直接驱动 store 进入 recording，避免在 jsdom 中等待 AudioWorklet 完整启动
    useMobileStore.setState({
      voice: {
        ...useMobileStore.getState().voice,
        capture: { state: "recording", sessionId: "sess-ui-2", error: null },
      },
    });

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
    await vi.waitFor(() => expect(findSentFrame("voice.mobile_ptt_start")).toBeDefined());

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
