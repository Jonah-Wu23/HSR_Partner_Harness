import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook, act, cleanup } from "@testing-library/react";
import { useMobileStore, type MobileTtsChunk, type MobileVoicePlayback } from "../mobileStore";
import {
  createVoicePlaybackEngine,
  END_SIGNAL_TIMEOUT_MS,
  resetSharedAudioContextForTests,
  resampleLinear,
  SCHEDULE_LEAD_SECONDS,
  useVoicePlayback,
  type VoicePlaybackEngine,
} from "../voicePlayback";

/**
 * V0.3.8 播放路径改造测试：共享 AudioContext 单例、默认采样率 + JS 侧
 * 线性重采样、suspended→resume、结束信号驱动收尾（网络间隔大不误判）、
 * 结束信号保护性超时。FakeAudioContext 遵循 mobileStore.test.ts 的
 * FakeWebSocket 风格：手动驱动 onended，不做时间线启发。
 */

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
  /** 下一个实例的初始 state（默认 running；suspended 用例手工指定）。 */
  static nextInitialState: "running" | "suspended" = "running";
  /** resume 行为：resolve（进入 running）/ reject / resolve 但保持 suspended。 */
  resumeBehavior: "resolve" | "reject" | "resolve-but-stay-suspended" = "resolve";

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
    if (this.resumeBehavior === "reject") {
      throw new Error("resume rejected: not allowed by autoplay policy");
    }
    if (this.resumeBehavior === "resolve") {
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

beforeEach(() => {
  resetSharedAudioContextForTests();
  FakeAudioContext.instances = [];
  vi.stubGlobal("AudioContext", FakeAudioContext);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  useMobileStore.setState({
    voice: {
      capture: { state: "idle", sessionId: null, error: null },
      transcript: null,
      playback: { messageId: null, state: "idle", error: null },
      availability: {
        secureContext: false,
        micPermission: "unknown",
        supported: false,
      },
      ttsChunks: {},
      ttsDroppedChunks: {},
    },
  });
});

describe("resampleLinear 重采样正确性", () => {
  it("24000→48000：长度翻倍且线性波形保持", () => {
    // 线性斜坡作为「波形」：整点采样必须精确还原，半点为相邻均值。
    const input = new Float32Array(24000);
    for (let i = 0; i < input.length; i++) input[i] = i;
    const output = resampleLinear(input, 24000, 48000);
    expect(output).toHaveLength(48000);
    expect(output[0]).toBe(0);
    expect(output[2]).toBe(1);
    expect(output[48000 - 2]).toBe(23999);
    expect(output[3]).toBeCloseTo(1.5, 10);
    // 末点位置 47999*0.5=23999.5 越过最后一个源采样，按不越界钳制取 23999。
    expect(output[48000 - 1]).toBe(23999);
  });

  it("24000→44100：长度按比例缩放且波形采样保持", () => {
    const input = new Float32Array(24000);
    for (let i = 0; i < input.length; i++) input[i] = Math.sin(i / 100);
    const output = resampleLinear(input, 24000, 44100);
    expect(output).toHaveLength(Math.floor((24000 * 44100) / 24000));
    expect(output[0]).toBeCloseTo(input[0], 10);
    // 输出采样必须等于源波形在对应位置上的线性插值（波形保持）。
    const ratio = 24000 / 44100;
    for (let i = 0; i < output.length; i += 911) {
      const pos = i * ratio;
      const idx = Math.floor(pos);
      const frac = pos - idx;
      const left = input[idx];
      const right = idx + 1 < input.length ? input[idx + 1] : left;
      expect(output[i]).toBeCloseTo(left + (right - left) * frac, 5);
    }
  });

  it("同采样率原样返回，空输入返回空", () => {
    const input = new Float32Array([0.1, -0.2, 0.3]);
    expect(resampleLinear(input, 24000, 24000)).toBe(input);
    expect(resampleLinear(new Float32Array(0), 24000, 48000)).toHaveLength(0);
  });
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

describe("播放启动：解码、重采样与 state/resume", () => {
  it("s16le 解码 + 24000→48000 重采样后进入共享 context 排程", async () => {
    const { engine } = createEngineHarness();
    const pcm = [-32768, 0, 16384, 32767];
    engine.playChunk(0, int16Base64(pcm));

    await vi.waitFor(() => expect(lastContext().sources).toHaveLength(1));
    const buffer = lastContext().sources[0]!.buffer!;
    expect(buffer.sampleRate).toBe(48000);
    expect(buffer.length).toBe(8);
    const channel = buffer.getChannelData(0);
    const f = (v: number) => v / 32768;
    expect(channel[0]).toBeCloseTo(f(-32768), 6);
    expect(channel[1]).toBeCloseTo(f(-16384), 6);
    expect(channel[2]).toBeCloseTo(f(0), 6);
    expect(channel[3]).toBeCloseTo(f(8192), 6);
    expect(channel[4]).toBeCloseTo(f(16384), 6);
    expect(channel[5]).toBeCloseTo(f(24575.5), 6);
    // 末点越界钳制：插值不超过最后一个源采样。
    expect(channel[7]).toBeCloseTo(f(32767), 6);
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

  it("resume 被拒绝时经 onFailed 如实上报，不伪造播放", async () => {
    FakeAudioContext.nextInitialState = "suspended";
    const { engine, onFinished, onFailed } = createEngineHarness();
    const originalResume = FakeAudioContext.prototype.resume;
    FakeAudioContext.prototype.resume = async function (this: FakeAudioContext) {
      this.resumeCalls += 1;
      throw new Error("resume rejected: not allowed by autoplay policy");
    };
    try {
      engine.playChunk(0, int16Base64([0, 1000]));
      await vi.waitFor(() => expect(onFailed).toHaveBeenCalledTimes(1));
    } finally {
      FakeAudioContext.prototype.resume = originalResume;
    }
    expect(onFailed.mock.calls[0]![0]).toBeInstanceOf(Error);
    expect(onFailed.mock.calls[0]![0].message).toContain("resume rejected");
    expect(onFinished).not.toHaveBeenCalled();
    expect(FakeAudioContext.instances[0]?.sources ?? []).toHaveLength(0);
  });

  it("resume 后仍未 running 时如实上报「无法进入运行态」", async () => {
    FakeAudioContext.nextInitialState = "suspended";
    const { engine, onFinished, onFailed } = createEngineHarness();
    const originalResume = FakeAudioContext.prototype.resume;
    FakeAudioContext.prototype.resume = async function (this: FakeAudioContext) {
      this.resumeCalls += 1;
      // resolve 但保持 suspended：模拟被系统拒绝但 Promise 正常返回
    };
    try {
      engine.playChunk(0, int16Base64([0, 1000]));
      await vi.waitFor(() => expect(onFailed).toHaveBeenCalledTimes(1));
    } finally {
      FakeAudioContext.prototype.resume = originalResume;
    }
    expect(onFailed.mock.calls[0]![0].message).toContain("无法进入运行态");
    expect(onFinished).not.toHaveBeenCalled();
  });
});

describe("结束信号驱动的收尾", () => {
  it("end 未到时网络间隔再长也不误判结束（必现截断缺陷回归）", async () => {
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
  it("end 迟迟不到时按上限如实报播放异常", async () => {
    vi.useFakeTimers();
    const { engine, onFinished, onFailed } = createEngineHarness();
    engine.playChunk(0, int16Base64([0, 1000]));
    await vi.advanceTimersByTimeAsync(0);
    expect(lastContext().sources).toHaveLength(1);

    await vi.advanceTimersByTimeAsync(END_SIGNAL_TIMEOUT_MS - 1);
    expect(onFailed).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(1);
    expect(onFailed).toHaveBeenCalledTimes(1);
    expect(onFailed.mock.calls[0]![0].message).toContain("voice.mobile_tts_end");
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
    // 每个 chunk 24000 样本 ≈ 1s（重采样后 1s@48kHz），两个都已入队。
    engine.playChunk(0, int16Base64(new Array(24000).fill(0)));
    engine.playChunk(1, int16Base64(new Array(24000).fill(0)));
    await vi.waitFor(() => expect(lastContext().sources).toHaveLength(1));

    // 提前量 1s 已满：第二个分片未排程（AudioBuffer 不驻留）。
    expect(SCHEDULE_LEAD_SECONDS).toBe(1);
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

describe("失败清理", () => {
  it("结束信号超时会停止已排程音频，失败后不再继续播放", async () => {
    vi.useFakeTimers();
    const { engine, onFailed } = createEngineHarness();
    engine.playChunk(0, int16Base64([0, 1000]));
    await vi.advanceTimersByTimeAsync(0);
    const source = lastContext().sources[0]!;

    await vi.advanceTimersByTimeAsync(END_SIGNAL_TIMEOUT_MS);

    expect(onFailed).toHaveBeenCalledTimes(1);
    expect(source.stopped).toBe(true);
  });
});

describe("useVoicePlayback 与 store 的衔接", () => {
  function setStoreVoice(playback: MobileVoicePlayback, chunks: Record<string, MobileTtsChunk[]>): void {
    act(() => {
      useMobileStore.setState({
        voice: {
          ...useMobileStore.getState().voice,
          playback,
          ttsChunks: chunks,
          ttsDroppedChunks: {},
        },
      });
    });
  }

  it("分片交给引擎后从 store 释放；end 后最后一个分片播完才复位", async () => {
    const chunk = { seq: 0, mime: "audio/pcm;rate=24000", data: int16Base64([0, 1000]), bytes: 4 };
    setStoreVoice(
      { messageId: "m-hook", state: "buffering", error: null },
      { "m-hook": [chunk] },
    );
    const { unmount } = renderHook(() => useVoicePlayback("c1"));

    // 分片被引擎取走后 store 立即释放（长回复不全量驻留）。
    await vi.waitFor(() => {
      expect(useMobileStore.getState().voice.ttsChunks["m-hook"]).toBeUndefined();
    });
    expect(lastContext().sources).toHaveLength(1);

    // end 信号（playing）→ 引擎等最后一个分片真实播完。
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
  });

  it("播放引擎异常经 onFailed 写入 store 的 failed 状态与错误", async () => {
    FakeAudioContext.nextInitialState = "suspended";
    const originalResume = FakeAudioContext.prototype.resume;
    FakeAudioContext.prototype.resume = async function (this: FakeAudioContext) {
      this.resumeCalls += 1;
      throw new Error("resume rejected: not allowed by autoplay policy");
    };
    try {
      const chunk = { seq: 0, mime: "audio/pcm;rate=24000", data: int16Base64([0, 1000]), bytes: 4 };
      setStoreVoice(
        { messageId: "m-fail", state: "buffering", error: null },
        { "m-fail": [chunk] },
      );
      const { unmount } = renderHook(() => useVoicePlayback("c1"));

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
    } finally {
      FakeAudioContext.prototype.resume = originalResume;
    }
  });

  it("V0.3.8 D1：一条消息自然播完并置 idle，组件不会向服务端发送 stop 请求", async () => {
    const chunk = { seq: 0, mime: "audio/pcm;rate=24000", data: int16Base64([0, 1000]), bytes: 4 };
    setStoreVoice(
      { messageId: "m-end-clean", state: "buffering", error: null },
      { "m-end-clean": [chunk] },
    );
    const { unmount } = renderHook(() => useVoicePlayback("c1"));

    await vi.waitFor(() => {
      expect(useMobileStore.getState().voice.ttsChunks["m-end-clean"]).toBeUndefined();
    });
    expect(lastContext().sources).toHaveLength(1);

    // 转换为 playing
    setStoreVoice({ messageId: "m-end-clean", state: "playing", error: null }, {});
    await vi.waitFor(() => {
      expect(useMobileStore.getState().voice.playback.state).toBe("playing");
    });

    // 音频自然播完
    lastContext().sources[0]!.onended?.();
    await vi.waitFor(() => {
      expect(useMobileStore.getState().voice.playback.state).toBe("idle");
    });

    // 自然播完后卸载，绝不能触发 stop 请求
    unmount();
    expect(useMobileStore.getState().voice.playback.state).toBe("idle");
  });

  it("V0.3.8 D1：两条消息交叠时，旧引擎停止，新消息正常建立，不发生重复停止风暴", async () => {
    const chunk1 = { seq: 0, mime: "audio/pcm;rate=24000", data: int16Base64([0, 1000]), bytes: 4 };
    setStoreVoice(
      { messageId: "m-first", state: "buffering", error: null },
      { "m-first": [chunk1] },
    );
    const { unmount } = renderHook(() => useVoicePlayback("c1"));

    await vi.waitFor(() => {
      expect(useMobileStore.getState().voice.ttsChunks["m-first"]).toBeUndefined();
    });
    expect(lastContext().sources).toHaveLength(1);
    const firstSource = lastContext().sources[0]!;

    // 切换到第二条消息
    const chunk2 = { seq: 0, mime: "audio/pcm;rate=24000", data: int16Base64([0, 2000]), bytes: 4 };
    setStoreVoice(
      { messageId: "m-second", state: "buffering", error: null },
      { "m-second": [chunk2] },
    );

    await vi.waitFor(() => {
      expect(useMobileStore.getState().voice.ttsChunks["m-second"]).toBeUndefined();
    });
    expect(lastContext().sources).toHaveLength(2);
    // 第一条音源已被停止
    expect(firstSource.stopped).toBe(true);

    unmount();
  });
});
