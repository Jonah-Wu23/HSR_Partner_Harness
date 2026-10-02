import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook, act, cleanup } from "@testing-library/react";
import type { MobileTtsChunk, MobileVoicePlayback } from "../mobileStore";
import { END_SIGNAL_TIMEOUT_MS, type VoicePlaybackEngine } from "../voicePlayback";
import { installFakeWebSocket, latestSocket } from "../../test/fakeWebSocket";

// 共享 AudioContext 是模块级单例：每个用例重新加载模块，拿到新的单例与对应的 store。
let useMobileStore: typeof import("../mobileStore").useMobileStore;
let mobileWsClient: typeof import("../mobileStore").mobileWsClient;
let createVoicePlaybackEngine: typeof import("../voicePlayback").createVoicePlaybackEngine;
let useVoicePlayback: typeof import("../voicePlayback").useVoicePlayback;

// AudioContext 是浏览器音频平台边界，jsdom 没有实现。FakeAudioContext 记录排程的音源，
// 用例手动触发 onended 表示音源播完。

interface FakeAudioBuffer {
  sampleRate: number;
  length: number;
  duration: number;
  channelData: Float32Array[];
  getChannelData(channel: number): Float32Array;
}

class FakeAudioBufferSourceNode {
  buffer: FakeAudioBuffer | null = null;
  onended: (() => void) | null = null;
  startedAt: number | null = null;
  stopped = false;

  start(when?: number): void {
    this.startedAt = when ?? null;
  }

  stop(): void {
    this.stopped = true;
  }

  connect(): void {
    // 测试无需真实音频图
  }

  disconnect(): void {
    // 测试无需真实音频图
  }
}

class FakeAudioContext {
  static instances: FakeAudioContext[] = [];
  /** 下一个实例的初始 state。 */
  static nextInitialState: "running" | "suspended" = "running";
  /** resume 的结果：进入 running、被拒绝，或正常返回但仍停在 suspended。 */
  static resumeBehavior: "resolve" | "reject" | "resolve-but-stay-suspended" = "resolve";

  readonly sampleRate: number;
  state: "running" | "suspended";
  currentTime = 0;
  resumeCalls = 0;
  readonly sources: FakeAudioBufferSourceNode[] = [];
  readonly destination = {};

  constructor() {
    this.sampleRate = 48000;
    this.state = FakeAudioContext.nextInitialState;
    FakeAudioContext.nextInitialState = "running";
    FakeAudioContext.instances.push(this);
  }

  async resume(): Promise<void> {
    this.resumeCalls += 1;
    if (FakeAudioContext.resumeBehavior === "reject") {
      throw new Error("resume rejected: not allowed by autoplay policy");
    }
    if (FakeAudioContext.resumeBehavior === "resolve") {
      this.state = "running";
    }
  }

  createBuffer(channels: number, length: number, sampleRate: number): FakeAudioBuffer {
    return {
      sampleRate,
      length,
      duration: length / sampleRate,
      channelData: Array.from({ length: channels }, () => new Float32Array(length)),
      getChannelData(channel) {
        return this.channelData[channel]!;
      },
    };
  }

  createBufferSource(): FakeAudioBufferSourceNode {
    const source = new FakeAudioBufferSourceNode();
    this.sources.push(source);
    return source;
  }
}

/** s16le PCM 编码为 base64（与服务端 voice.mobile_tts_chunk 一致）。 */
function int16Base64(values: number[]): string {
  const bytes = new Uint8Array(values.length * 2);
  const view = new DataView(bytes.buffer);
  values.forEach((value, i) => view.setInt16(i * 2, value, true));
  return Buffer.from(bytes).toString("base64");
}

interface EngineHarness {
  engine: VoicePlaybackEngine;
  onFinished: ReturnType<typeof vi.fn>;
  onFailed: ReturnType<typeof vi.fn>;
}

function createEngineHarness(): EngineHarness {
  const onFinished = vi.fn();
  const onFailed = vi.fn();
  const engine = createVoicePlaybackEngine({ onFinished, onFailed });
  return { engine, onFinished, onFailed };
}

function lastContext(): FakeAudioContext {
  const instance = FakeAudioContext.instances[FakeAudioContext.instances.length - 1];
  if (!instance) throw new Error("共享 AudioContext 尚未创建");
  return instance;
}

beforeEach(async () => {
  FakeAudioContext.instances = [];
  FakeAudioContext.nextInitialState = "running";
  FakeAudioContext.resumeBehavior = "resolve";
  vi.stubGlobal("AudioContext", FakeAudioContext);
  vi.resetModules();
  ({ useMobileStore, mobileWsClient } = await import("../mobileStore"));
  ({ createVoicePlaybackEngine, useVoicePlayback } = await import("../voicePlayback"));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("共享 AudioContext 单例", () => {
  it("两条连续消息复用同一 context，不新建", async () => {
    const first = createEngineHarness();
    first.engine.playChunk(0, int16Base64([0, 1000]));
    await vi.waitFor(() => expect(lastContext().sources).toHaveLength(1));

    const second = createEngineHarness();
    second.engine.playChunk(0, int16Base64([0, 1000]));
    await vi.waitFor(() => expect(lastContext().sources).toHaveLength(2));

    // 两个引擎实例、两次播放会话，AudioContext 只构造一次。
    expect(FakeAudioContext.instances).toHaveLength(1);
  });
});

describe("播放启动：解码与 state/resume", () => {
  it("24kHz s16le 分片解码为同采样率的单声道 AudioBuffer，满幅采样落在 [-1, 1]", async () => {
    const { engine } = createEngineHarness();
    engine.playChunk(0, int16Base64([-32768, 0, 16384, 32767]));

    await vi.waitFor(() => expect(lastContext().sources).toHaveLength(1));
    const buffer = lastContext().sources[0]!.buffer!;
    expect(buffer.sampleRate).toBe(24000);
    expect(buffer.length).toBe(4);
    const channel = buffer.getChannelData(0);
    expect(channel[0]).toBe(-1);
    expect(channel[3]).toBeCloseTo(1, 4);
  });

  it("suspended 时先 resume 再排程播放", async () => {
    FakeAudioContext.nextInitialState = "suspended";
    const { engine, onFailed } = createEngineHarness();
    engine.playChunk(0, int16Base64([0, 1000]));

    await vi.waitFor(() => {
      expect(lastContext().resumeCalls).toBe(1);
      expect(lastContext().state).toBe("running");
      expect(lastContext().sources).toHaveLength(1);
    });
    expect(onFailed).not.toHaveBeenCalled();
  });

  it("resume 被拒绝时经 onFailed 上报原始错误，不排程音频", async () => {
    FakeAudioContext.nextInitialState = "suspended";
    FakeAudioContext.resumeBehavior = "reject";
    const { engine, onFinished, onFailed } = createEngineHarness();
    engine.playChunk(0, int16Base64([0, 1000]));

    await vi.waitFor(() => expect(onFailed).toHaveBeenCalledTimes(1));
    expect(onFailed.mock.calls[0]![0].message).toContain("resume rejected");
    expect(onFinished).not.toHaveBeenCalled();
    expect(lastContext().sources).toHaveLength(0);
  });

  it("resume 后仍未 running 时上报「无法进入运行态」", async () => {
    FakeAudioContext.nextInitialState = "suspended";
    FakeAudioContext.resumeBehavior = "resolve-but-stay-suspended";
    const { engine, onFinished, onFailed } = createEngineHarness();
    engine.playChunk(0, int16Base64([0, 1000]));

    await vi.waitFor(() => expect(onFailed).toHaveBeenCalledTimes(1));
    expect(onFailed.mock.calls[0]![0].message).toContain("无法进入运行态");
    expect(onFinished).not.toHaveBeenCalled();
  });
});

describe("结束信号驱动的收尾", () => {
  it("end 未到时分片间隔再长也不收尾，迟到的分片照常播放", async () => {
    const { engine, onFinished, onFailed } = createEngineHarness();
    engine.playChunk(0, int16Base64([0, 1000]));
    await vi.waitFor(() => expect(lastContext().sources).toHaveLength(1));

    // 第一个分片真实播完，此后网络长时间无新分片：不得收尾。
    lastContext().sources[0]!.onended?.();
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(onFinished).not.toHaveBeenCalled();

    // 迟到的后续分片必须照常播放，不被静默丢弃。
    engine.playChunk(1, int16Base64([0, 500]));
    await vi.waitFor(() => expect(lastContext().sources).toHaveLength(2));
    expect(onFailed).not.toHaveBeenCalled();

    // end 到达后等最后一个分片真实播完才收尾。
    engine.markEnded();
    expect(onFinished).not.toHaveBeenCalled();
    lastContext().sources[1]!.onended?.();
    expect(onFinished).toHaveBeenCalledTimes(1);
  });

  it("markEnded 时无在播/待播分片则立即收尾（空音频）", () => {
    const { engine, onFinished } = createEngineHarness();
    engine.markEnded();
    expect(onFinished).toHaveBeenCalledTimes(1);
  });

  it("stop 后 finished：后续分片忽略，不触发收尾回调", async () => {
    const { engine, onFinished } = createEngineHarness();
    engine.playChunk(0, int16Base64([0, 1000]));
    await vi.waitFor(() => expect(lastContext().sources).toHaveLength(1));
    engine.stop();
    engine.playChunk(1, int16Base64([0, 1000]));
    lastContext().sources[0]!.onended?.();
    expect(onFinished).not.toHaveBeenCalled();
    expect(lastContext().sources).toHaveLength(1);
  });
});

describe("结束信号保护性超时", () => {
  it("end 迟迟不到时按上限上报播放失败并停止已排程音频", async () => {
    vi.useFakeTimers();
    const { engine, onFinished, onFailed } = createEngineHarness();
    engine.playChunk(0, int16Base64([0, 1000]));
    await vi.advanceTimersByTimeAsync(0);
    expect(lastContext().sources).toHaveLength(1);
    const source = lastContext().sources[0]!;

    await vi.advanceTimersByTimeAsync(END_SIGNAL_TIMEOUT_MS - 1);
    expect(onFailed).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(1);
    expect(onFailed).toHaveBeenCalledTimes(1);
    expect(onFailed.mock.calls[0]![0].message).toContain("voice.mobile_tts_end");
    expect(source.stopped).toBe(true);
    expect(onFinished).not.toHaveBeenCalled();
  });

  it("end 到达后保护性超时被清除，不再误报", async () => {
    vi.useFakeTimers();
    const { engine, onFinished, onFailed } = createEngineHarness();
    engine.playChunk(0, int16Base64([0, 1000]));
    await vi.advanceTimersByTimeAsync(0);
    engine.markEnded();
    await vi.advanceTimersByTimeAsync(END_SIGNAL_TIMEOUT_MS * 2);
    expect(onFailed).not.toHaveBeenCalled();
    lastContext().sources[0]!.onended?.();
    expect(onFinished).toHaveBeenCalledTimes(1);
  });
});

describe("排程提前量（内存驻留控制）", () => {
  it("提前量已满时分片留在队列，onended 后继续排程", async () => {
    const { engine } = createEngineHarness();
    // 每个分片 24000 个采样，即 1 秒音频。
    engine.playChunk(0, int16Base64(new Array(24000).fill(0)));
    engine.playChunk(1, int16Base64(new Array(24000).fill(0)));
    await vi.waitFor(() => expect(lastContext().sources).toHaveLength(1));

    // 时间线上已排入 1 秒音频，提前量已满，后续分片不建 AudioBuffer。
    engine.playChunk(2, int16Base64(new Array(24000).fill(0)));
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(lastContext().sources).toHaveLength(1);

    // 播放推进后提前量打开，队列里的分片继续排程。
    lastContext().currentTime = 0.5;
    lastContext().sources[0]!.onended?.();
    await vi.waitFor(() => expect(lastContext().sources).toHaveLength(2));
  });

  it("实际待播队列超过 PCM 上限时失败并停止已排程音频", async () => {
    const onFinished = vi.fn();
    const onFailed = vi.fn();
    const engine = createVoicePlaybackEngine({
      onFinished,
      onFailed,
      maxQueuedPcmBytes: 8,
    });
    engine.playChunk(0, int16Base64([0, 1, 2, 3]));
    await vi.waitFor(() => expect(lastContext().sources).toHaveLength(1));

    // 先把排程时间线填满，后续分片进入引擎内部待播队列。
    engine.playChunk(1, int16Base64([0, 1, 2, 3]));
    engine.playChunk(2, int16Base64([0, 1, 2, 3]));

    await vi.waitFor(() => expect(onFailed).toHaveBeenCalledTimes(1));
    expect(onFailed.mock.calls[0]![0].message).toContain("待播队列超过内存上限");
    expect(lastContext().sources[0]!.stopped).toBe(true);
    expect(onFinished).not.toHaveBeenCalled();
  });
});

describe("useVoicePlayback 与 store 的衔接", () => {
  function setStoreVoice(
    playback: Omit<MobileVoicePlayback, "errorCode">,
    chunks: Record<string, MobileTtsChunk[]>,
  ): void {
    act(() => {
      useMobileStore.setState({
        voice: {
          ...useMobileStore.getState().voice,
          playback: { ...playback, errorCode: null },
          ttsChunks: chunks,
        },
      });
    });
  }

  it("分片交给引擎后从 store 释放；end 后最后一个分片播完才复位，之后卸载不再请求停止", async () => {
    installFakeWebSocket();
    mobileWsClient.connect();
    latestSocket().open();
    const chunk ={ seq: 0, mime: "audio/pcm;rate=24000", data: int16Base64([0, 1000]), bytes: 4 };
    setStoreVoice(
      { messageId: "m-hook", state: "buffering", error: null },
      { "m-hook": [chunk] },
    );
    const { unmount } = renderHook(() => useVoicePlayback());

    // 分片被引擎取走后 store 立即释放，长回复不整段驻留。
    await vi.waitFor(() => {
      expect(useMobileStore.getState().voice.ttsChunks["m-hook"]).toBeUndefined();
    });
    expect(lastContext().sources).toHaveLength(1);

    // end 信号到达（playing）后，引擎等最后一个分片真实播完。
    setStoreVoice({ messageId: "m-hook", state: "playing", error: null }, {});
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(useMobileStore.getState().voice.playback.state).toBe("playing");

    lastContext().sources[0]!.onended?.();
    await vi.waitFor(() => {
      expect(useMobileStore.getState().voice.playback).toMatchObject({
        messageId: null,
        state: "idle",
      });
    });

    unmount();
    expect(latestSocket().sentFrames("voice.mobile_tts_stop")).toEqual([]);
  });

  it("播放引擎异常经 onFailed 写入 store 的 failed 状态与错误", async () => {
    FakeAudioContext.nextInitialState = "suspended";
    FakeAudioContext.resumeBehavior = "reject";
    const chunk = { seq: 0, mime: "audio/pcm;rate=24000", data: int16Base64([0, 1000]), bytes: 4 };
    setStoreVoice(
      { messageId: "m-fail", state: "buffering", error: null },
      { "m-fail": [chunk] },
    );
    const { unmount } = renderHook(() => useVoicePlayback());

    await vi.waitFor(() => {
      expect(useMobileStore.getState().voice.playback).toMatchObject({
        messageId: "m-fail",
        state: "failed",
      });
    });
    expect(useMobileStore.getState().voice.playback.error).toContain("resume rejected");
    // 失败消息的分片一并清理，不再驻留。
    expect(useMobileStore.getState().voice.ttsChunks["m-fail"]).toBeUndefined();
    unmount();
  });

  it("换到下一条朗读时停止旧消息的音源并为新消息排程", async () => {
    const chunk1 = { seq: 0, mime: "audio/pcm;rate=24000", data: int16Base64([0, 1000]), bytes: 4 };
    setStoreVoice(
      { messageId: "m-first", state: "buffering", error: null },
      { "m-first": [chunk1] },
    );
    const { unmount } = renderHook(() => useVoicePlayback());

    await vi.waitFor(() => {
      expect(useMobileStore.getState().voice.ttsChunks["m-first"]).toBeUndefined();
    });
    expect(lastContext().sources).toHaveLength(1);
    const firstSource = lastContext().sources[0]!;

    const chunk2 = { seq: 0, mime: "audio/pcm;rate=24000", data: int16Base64([0, 2000]), bytes: 4 };
    setStoreVoice(
      { messageId: "m-second", state: "buffering", error: null },
      { "m-second": [chunk2] },
    );

    await vi.waitFor(() => {
      expect(useMobileStore.getState().voice.ttsChunks["m-second"]).toBeUndefined();
    });
    expect(lastContext().sources).toHaveLength(2);
    expect(firstSource.stopped).toBe(true);

    unmount();
  });
});
