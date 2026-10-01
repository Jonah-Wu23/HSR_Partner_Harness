import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ConversationRecord } from "@shared/contracts/protocol";
import { mobileWsClient, useMobileStore } from "../../../lib/mobileStore";
import { installFakeWebSocket, latestSocket, type SentFrame } from "../../../test/fakeWebSocket";
import { ChatPage } from "../ChatPage";

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

/** 等某个方法发出第 n 个请求帧（n 从 1 起）并返回它。 */
async function nthFrame(method: string, n = 1): Promise<SentFrame> {
  const socket = latestSocket();
  await vi.waitFor(() => expect(socket.sentFrames(method).length).toBeGreaterThanOrEqual(n));
  return socket.sentFrames(method)[n - 1];
}

function sentCount(method: string): number {
  return latestSocket().sentFrames(method).length;
}

/** 按发送顺序取出全部请求 method，用于断言 stop 先于 start 这类顺序。 */
function sentMethods(): string[] {
  return latestSocket()
    .sentFrames()
    .map((frame) => frame.method);
}

function respondStarted(frame: SentFrame, sessionId: string): void {
  latestSocket().respond(frame, { session_id: sessionId, conversation_id: "c1" });
}

/** voice.mobile_ptt_stop 只在转写非空时成功，结果带最终转写全文。 */
function respondStopped(frame: SentFrame, transcript: string): void {
  latestSocket().respond(frame, {
    session_id: frame.params.session_id,
    conversation_id: "c1",
    transcript,
  });
}

/** 转写事件只发给手机，不带序号。 */
function emitTranscript(sessionId: string, text: string, isFinal: boolean): void {
  latestSocket().emit({
    kind: "event",
    event: "voice.mobile_transcript",
    payload: { conversation_id: "c1", session_id: sessionId, text, is_final: isFinal },
  });
}

function capture() {
  return useMobileStore.getState().voice.capture;
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

/** 麦克风轨道桩：停止采集时会被 stop，用于断言本地采集是否已停。 */
type FakeStreamTrack = { stop: ReturnType<typeof vi.fn> };
let lastStreamTrack: FakeStreamTrack | null = null;

interface PlatformOptions {
  secureContext?: boolean;
  micPermission?: PermissionState;
  microphone?: boolean;
}

/**
 * 浏览器平台桩：安全上下文、麦克风授权查询与 getUserMedia。jsdom 没有这些接口，
 * store 的 refreshVoiceAvailability 在聊天页挂载时据此计算语音入口是否可用。
 */
function stubPlatform({
  secureContext = true,
  micPermission = "granted",
  microphone = true,
}: PlatformOptions = {}): void {
  const track: FakeStreamTrack = { stop: vi.fn() };
  lastStreamTrack = track;
  vi.stubGlobal("isSecureContext", secureContext);
  vi.stubGlobal("navigator", {
    ...globalThis.navigator,
    mediaDevices: microphone
      ? { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [track] }) }
      : undefined,
    permissions: { query: vi.fn().mockResolvedValue({ state: micPermission }) },
  });
}

/** Web Audio 平台桩：采集引擎需要 AudioContext、AudioWorkletNode 与 Blob URL。 */
function stubAudioEngine(): void {
  lastWorkletNode = null;
  vi.stubGlobal(
    "AudioContext",
    class {
      sampleRate: number;
      state = "running";
      destination = {};
      audioWorklet = { addModule: vi.fn().mockResolvedValue(undefined) };
      resume = vi.fn().mockResolvedValue(undefined);
      close = vi.fn().mockResolvedValue(undefined);
      createMediaStreamSource = vi.fn().mockReturnValue({ connect: vi.fn(), disconnect: vi.fn() });
      constructor(options?: { sampleRate?: number }) {
        this.sampleRate = options?.sampleRate ?? 48000;
      }
    },
  );
  vi.stubGlobal(
    "AudioWorkletNode",
    class {
      port = {
        onmessage: null as ((event: { data: unknown }) => void) | null,
        // 与真实 Worklet 一致：收到 flush 交回尾部样本后回 flushed（测试里没有尾部样本）。
        postMessage: vi.fn((message: unknown) => {
          if ((message as { type?: string }).type === "flush") {
            queueMicrotask(() => this.port.onmessage?.({ data: { type: "flushed" } }));
          }
        }),
      };
      connect = vi.fn();
      disconnect = vi.fn();
      constructor() {
        lastWorkletNode = this;
      }
    },
  );
  // jsdom 没有 Blob URL，采集引擎用它加载 Worklet 模块。
  vi.stubGlobal(
    "URL",
    Object.assign(class extends URL {}, {
      createObjectURL: () => "blob:voice-capture-processor",
      revokeObjectURL: () => {},
    }),
  );
}

/** 渲染聊天页，等可用性刷新出语音入口后打开语音面板。 */
async function openVoicePanel(): Promise<ReturnType<typeof render>> {
  const view = render(<ChatPage conversationId="c1" />);
  fireEvent.click(await screen.findByTestId("voice-trigger-btn"));
  return view;
}

/** 点自动检测并回放 voice.mobile_ptt_start 的响应。 */
async function startAuto(sessionId: string): Promise<void> {
  fireEvent.click(screen.getByTestId("voice-auto-toggle-btn"));
  respondStarted(await nthFrame("voice.mobile_ptt_start"), sessionId);
  await waitFor(() => expect(capture().sessionId).toBe(sessionId));
}

beforeEach(async () => {
  installFakeWebSocket();
  window.localStorage.clear();
  // disconnect 把会话级状态复位到初值；会话记录在生产中由 app.bootstrap 快照写入，这里作为前置条件。
  await useMobileStore.getState().disconnect();
  useMobileStore.setState({ conversationsById: { c1: CONVERSATION } });
  useMobileStore.getState().start();
  mobileWsClient.connect();
  latestSocket().open();
});

afterEach(async () => {
  cleanup();
  // 卸载触发的停止链路在平台桩撤掉之前跑完：断开连接让在途请求失败，再等它们收尾。
  await flushTasks();
  mobileWsClient.disconnect();
  await flushTasks();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("语音入口可用性", () => {
  it.each([
    {
      // 浏览器在非安全上下文不提供 navigator.mediaDevices。
      condition: "局域网 HTTP 页面不是安全上下文",
      platform: { secureContext: false, microphone: false },
      reason: /HTTP 局域网连接.*Tailscale/,
    },
    {
      condition: "麦克风权限被拒绝",
      platform: { micPermission: "denied" as const },
      reason: /麦克风权限被拒绝/,
    },
    {
      condition: "浏览器没有麦克风接口",
      platform: { microphone: false },
      reason: /不支持麦克风采集/,
    },
  ])("$condition 时语音入口禁用并说明原因", async ({ platform, reason }) => {
    stubPlatform(platform);
    render(<ChatPage conversationId="c1" />);

    await waitFor(() => {
      expect(screen.getByTestId("voice-disabled-reason")).toHaveTextContent(reason);
    });
    expect(screen.queryByTestId("voice-trigger-btn")).toBeNull();
  });

  it("与桌面端断开后语音入口禁用并说明原因", async () => {
    stubPlatform();
    render(<ChatPage conversationId="c1" />);
    await screen.findByTestId("voice-trigger-btn");

    mobileWsClient.disconnect();

    await waitFor(() => {
      expect(screen.getByTestId("voice-disabled-reason")).toHaveTextContent(/连接已断开/);
    });
  });
});

describe("语音面板与自动检测", () => {
  beforeEach(() => {
    stubPlatform();
    stubAudioEngine();
  });

  it("打开语音面板只展示按住说话与自动检测入口，不发起语音会话", async () => {
    await openVoicePanel();

    expect(screen.getByTestId("voice-hold-btn")).toBeInTheDocument();
    expect(screen.getByTestId("voice-auto-toggle-btn")).toBeInTheDocument();
    await flushTasks();
    expect(sentCount("voice.mobile_ptt_start")).toBe(0);
    expect(capture().state).toBe("idle");
  });

  it("自动检测发出 voice.mobile_ptt_start，会话建立后显示聆听中", async () => {
    await openVoicePanel();
    fireEvent.click(screen.getByTestId("voice-auto-toggle-btn"));

    const start = await nthFrame("voice.mobile_ptt_start");
    expect(start.params).toEqual({ conversation_id: "c1" });
    respondStarted(start, "sess-auto");

    // 大按钮录音时也显示「聆听中…」，用自动检测那一行的完整文案定位。
    expect(await screen.findByText(/检测到静音自动停止/)).toBeInTheDocument();
  });

  it("voice.mobile_transcript 的中间与最终转写依次展示", async () => {
    await openVoicePanel();
    await startAuto("sess-transcript");

    emitTranscript("sess-transcript", "你好", false);
    await waitFor(() => {
      expect(screen.getByTestId("voice-transcript")).toHaveTextContent("转写中：你好");
    });

    emitTranscript("sess-transcript", "你好角色", true);
    await waitFor(() => {
      expect(screen.getByTestId("voice-transcript")).toHaveTextContent("转写完成：你好角色");
    });
  });

  it("服务端放弃转写（voice.mobile_asr_failed）时展示错误原文与重试入口", async () => {
    await openVoicePanel();
    await startAuto("sess-timeout");

    latestSocket().emit({
      kind: "event",
      event: "voice.mobile_asr_failed",
      payload: {
        conversation_id: "c1",
        session_id: "sess-timeout",
        code: "voice_session_timeout",
        error: "录音超过 60 秒未结束，本次转写已取消",
      },
    });

    await waitFor(() => {
      expect(screen.getByTestId("voice-capture-error")).toHaveTextContent(
        "录音超过 60 秒未结束，本次转写已取消",
      );
      expect(screen.getByTestId("voice-retry-btn")).toBeInTheDocument();
    });
    expect(capture().state).toBe("idle");
  });

  it.each([
    { moment: "录音中", respondBeforeUnmount: true },
    { moment: "会话建立前", respondBeforeUnmount: false },
  ])("$moment卸载页面，仍向服务端会话补发 voice.mobile_ptt_stop", async ({ respondBeforeUnmount }) => {
    const { unmount } = await openVoicePanel();
    fireEvent.click(screen.getByTestId("voice-auto-toggle-btn"));
    const start = await nthFrame("voice.mobile_ptt_start");

    if (respondBeforeUnmount) {
      respondStarted(start, "sess-unmount");
      await waitFor(() => expect(capture().sessionId).toBe("sess-unmount"));
      unmount();
    } else {
      unmount();
      respondStarted(start, "sess-unmount");
    }

    expect((await nthFrame("voice.mobile_ptt_stop")).params).toEqual({ session_id: "sess-unmount" });
  });
});

describe("按住说话", () => {
  beforeEach(() => {
    stubPlatform();
    stubAudioEngine();
  });

  /** 按下「按住说话」并回放 voice.mobile_ptt_start 的响应，返回按钮。 */
  async function startHold(sessionId: string, pointerId: number): Promise<HTMLElement> {
    const holdBtn = screen.getByTestId("voice-hold-btn");
    const n = sentCount("voice.mobile_ptt_start") + 1;
    fireEvent.pointerDown(holdBtn, { pointerId });
    respondStarted(await nthFrame("voice.mobile_ptt_start", n), sessionId);
    await waitFor(() => expect(capture().sessionId).toBe(sessionId));
    return holdBtn;
  }

  it.each(["pointerUp", "pointerCancel"] as const)(
    "pointerdown 开始采集，%s 结束并发出 voice.mobile_ptt_stop",
    async (release) => {
      await openVoicePanel();
      const holdBtn = await startHold("sess-hold", 1);

      fireEvent[release](holdBtn, { pointerId: 1 });

      expect((await nthFrame("voice.mobile_ptt_stop")).params).toEqual({ session_id: "sess-hold" });
    },
  );

  it("点击（没有按压）按住说话按钮不启动采集", async () => {
    await openVoicePanel();

    fireEvent.click(screen.getByTestId("voice-hold-btn"));
    await flushTasks();

    expect(sentCount("voice.mobile_ptt_start")).toBe(0);
  });

  it("自动检测录音中按下按住说话：先停旧会话，再启动新会话", async () => {
    await openVoicePanel();
    await startAuto("sess-auto");

    fireEvent.pointerDown(screen.getByTestId("voice-hold-btn"), { pointerId: 2 });

    const stop = await nthFrame("voice.mobile_ptt_stop");
    expect(stop.params).toEqual({ session_id: "sess-auto" });
    respondStopped(stop, "自动检测的一段");

    const start = await nthFrame("voice.mobile_ptt_start", 2);
    const methods = sentMethods();
    expect(methods.indexOf("voice.mobile_ptt_stop")).toBeLessThan(
      methods.lastIndexOf("voice.mobile_ptt_start"),
    );
    respondStarted(start, "sess-hold");
    await waitFor(() => expect(capture().sessionId).toBe("sess-hold"));
  });

  it("停止响应携带最终转写即复位，不依赖 is_final 事件，随后可立即再次开始", async () => {
    await openVoicePanel();
    const holdBtn = await startHold("sess-reset", 5);
    fireEvent.pointerUp(holdBtn, { pointerId: 5 });

    respondStopped(await nthFrame("voice.mobile_ptt_stop"), "今天天气不错");

    await waitFor(() => {
      const voice = useMobileStore.getState().voice;
      expect(voice.capture.state).toBe("idle");
      expect(voice.capture.sessionId).toBeNull();
      expect(voice.transcript).toEqual({ sessionId: "sess-reset", text: "今天天气不错", isFinal: true });
    });
    expect(screen.getByTestId("voice-transcript")).toHaveTextContent("今天天气不错");

    fireEvent.pointerDown(holdBtn, { pointerId: 6 });
    await nthFrame("voice.mobile_ptt_start", 2);
  });

  it("按住说话的状态行依次显示准备中与聆听中", async () => {
    await openVoicePanel();
    fireEvent.pointerDown(screen.getByTestId("voice-hold-btn"), { pointerId: 7 });

    await waitFor(() => {
      expect(screen.getByTestId("voice-hold-status")).toHaveTextContent("准备中…");
    });
    respondStarted(await nthFrame("voice.mobile_ptt_start"), "sess-status");

    await waitFor(() => {
      expect(screen.getByTestId("voice-hold-status")).toHaveTextContent("聆听中，抬起发送");
    });
  });

  it("按住说话启动失败：面板保持打开并展示错误原文，重试方式是再次按住", async () => {
    await openVoicePanel();
    fireEvent.pointerDown(screen.getByTestId("voice-hold-btn"), { pointerId: 8 });

    latestSocket().respondError(
      await nthFrame("voice.mobile_ptt_start"),
      "voice_not_configured",
      "请先在语音页保存 DashScope API Key，再使用手机语音",
    );

    await waitFor(() => {
      expect(screen.getByTestId("voice-capture-error")).toHaveTextContent(
        "请先在语音页保存 DashScope API Key，再使用手机语音",
      );
    });
    expect(screen.getByTestId("voice-hold-btn")).toBeInTheDocument();
    expect(screen.getByTestId("voice-close-btn")).toBeInTheDocument();
    expect(screen.queryByTestId("voice-retry-btn")).toBeNull();
    expect(screen.getByTestId("voice-hold-retry-hint")).toHaveTextContent("请再次按住说话重试");
  });

  it("会话建立前抬起：建立后补发停止，服务端 voice_transcript_empty 的原文如实展示", async () => {
    await openVoicePanel();
    const holdBtn = screen.getByTestId("voice-hold-btn");
    fireEvent.pointerDown(holdBtn, { pointerId: 9 });
    const start = await nthFrame("voice.mobile_ptt_start");

    fireEvent.pointerUp(holdBtn, { pointerId: 9 });
    await flushTasks();
    expect(sentCount("voice.mobile_ptt_stop")).toBe(0);

    respondStarted(start, "sess-short");
    const stop = await nthFrame("voice.mobile_ptt_stop");
    expect(stop.params).toEqual({ session_id: "sess-short" });
    latestSocket().respondError(stop, "voice_transcript_empty", "未识别到语音内容");

    await waitFor(() => {
      expect(screen.getByTestId("voice-capture-error")).toHaveTextContent("未识别到语音内容");
    });
  });

  it("上一段停止仍在途时按下：等旧会话停稳后再启动，这次按压不丢失", async () => {
    await openVoicePanel();
    const holdBtn = await startHold("sess-old", 11);
    fireEvent.pointerUp(holdBtn, { pointerId: 11 });

    // 停止请求不回应，store 停在 stopping。
    const stop = await nthFrame("voice.mobile_ptt_stop");
    await waitFor(() => expect(capture().state).toBe("stopping"));

    fireEvent.pointerDown(holdBtn, { pointerId: 12 });
    await flushTasks();
    expect(sentCount("voice.mobile_ptt_start")).toBe(1);
    expect(capture().error).toBeNull();

    respondStopped(stop, "第一段");

    const start = await nthFrame("voice.mobile_ptt_start", 2);
    const methods = sentMethods();
    expect(methods.indexOf("voice.mobile_ptt_stop")).toBeLessThan(
      methods.lastIndexOf("voice.mobile_ptt_start"),
    );
    respondStarted(start, "sess-new");
    await waitFor(() => expect(capture().sessionId).toBe("sess-new"));
  });

  it("自动检测启动失败后仍提供重试按钮，点击重新发起采集", async () => {
    await openVoicePanel();
    fireEvent.click(screen.getByTestId("voice-auto-toggle-btn"));

    latestSocket().respondError(
      await nthFrame("voice.mobile_ptt_start"),
      "voice_not_configured",
      "请先在语音页保存 DashScope API Key，再使用手机语音",
    );

    // 失败后 capture 回 idle、模式收回 off，重试入口按最近一次尝试的模式给出。
    await waitFor(() => {
      expect(capture().state).toBe("idle");
      expect(screen.getByTestId("voice-retry-btn")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("voice-retry-btn"));
    await nthFrame("voice.mobile_ptt_start", 2);
  });

  it.each([
    { order: "停止响应先到", finalEventFirst: false },
    { order: "is_final 事件先于停止响应", finalEventFirst: true },
  ])("上行分片被拒的错误在会话收尾后仍然可见（$order）", async ({ finalEventFirst }) => {
    await openVoicePanel();
    await startHold("sess-chunk", 13);
    // 采集引擎启动后才有 Worklet 节点。
    await waitFor(() => expect(lastWorkletNode).not.toBeNull());

    lastWorkletNode!.port.onmessage?.({
      data: { type: "chunk", samples: new Int16Array([1, 2, 3]).buffer },
    });
    const chunk = await nthFrame("voice.mobile_audio_chunk");
    expect(chunk.params).toMatchObject({ session_id: "sess-chunk", seq: 0 });
    latestSocket().respondError(chunk, "voice_audio_seq_gap", "音频分片序号跳号：期望 1，实际 0");

    // 分片失败经采集引擎的 onError 触发停止。
    const stop = await nthFrame("voice.mobile_ptt_stop");
    if (finalEventFirst) {
      emitTranscript("sess-chunk", "部分转写", true);
      await waitFor(() => expect(capture().state).toBe("idle"));
    }
    respondStopped(stop, "部分转写");
    await waitFor(() => expect(capture().state).toBe("idle"));
    await flushTasks();

    expect(capture().error).toContain("音频分片序号跳号");
    expect(screen.getByTestId("voice-capture-error")).toHaveTextContent("音频分片序号跳号");
  });

  it("stopVoiceCapture 按显式 sessionId 发出停止，响应不改写 store 里的其他会话", async () => {
    // 新会话已在录音，旧会话的停止由显式 sessionId 指定。
    useMobileStore.setState({
      voice: {
        ...useMobileStore.getState().voice,
        capture: { state: "recording", sessionId: "sess-current", error: null },
        transcript: null,
      },
    });

    const stopping = useMobileStore.getState().stopVoiceCapture("sess-previous");
    const stop = await nthFrame("voice.mobile_ptt_stop");
    expect(stop.params).toEqual({ session_id: "sess-previous" });
    respondStopped(stop, "会话收尾");
    await stopping;

    expect(capture()).toEqual({ state: "recording", sessionId: "sess-current", error: null });
    expect(useMobileStore.getState().voice.transcript).toBeNull();
  });

  it("is_final 事件先到、旧会话的停止响应后到时，不改写新会话，新会话的停止照常发出", async () => {
    await openVoicePanel();
    const holdA = await startHold("sess-a", 14);
    fireEvent.pointerUp(holdA, { pointerId: 14 });
    const stopA = await nthFrame("voice.mobile_ptt_stop");

    // 服务端结束会话时先发 is_final 事件，再返回停止响应。
    emitTranscript("sess-a", "第一段", true);
    await waitFor(() => expect(capture().sessionId).toBeNull());

    // 停止响应还没到，用户已经按下第二段并建立会话 B。
    const holdB = await startHold("sess-b", 15);

    respondStopped(stopA, "第一段");
    await flushTasks();
    expect(capture()).toEqual({ state: "recording", sessionId: "sess-b", error: null });

    fireEvent.pointerUp(holdB, { pointerId: 15 });
    expect((await nthFrame("voice.mobile_ptt_stop", 2)).params).toEqual({ session_id: "sess-b" });
  });

  it("旧会话的停止仍在途时抬起新会话：本地采集立即停止，新会话的停止排在旧停止之后发出", async () => {
    await openVoicePanel();
    const holdA = await startHold("sess-a", 16);
    fireEvent.pointerUp(holdA, { pointerId: 16 });
    const stopA = await nthFrame("voice.mobile_ptt_stop");

    emitTranscript("sess-a", "第一段", true);
    await waitFor(() => expect(capture().sessionId).toBeNull());

    const holdB = await startHold("sess-b", 17);
    const track = lastStreamTrack as FakeStreamTrack;
    track.stop.mockClear();

    // A 的停止不回应。
    fireEvent.pointerUp(holdB, { pointerId: 17 });
    await flushTasks();

    expect(track.stop).toHaveBeenCalled();
    expect(sentCount("voice.mobile_ptt_stop")).toBe(1);

    respondStopped(stopA, "第一段");
    expect((await nthFrame("voice.mobile_ptt_stop", 2)).params).toEqual({ session_id: "sess-b" });
  });
});
