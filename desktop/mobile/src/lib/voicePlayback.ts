/**
 * V0.3.5 手机端语音播放引擎；V0.3.8 播放路径改造（真机验收 C2）。
 *
 * - 全应用共享一个默认采样率（设备输出采样率）AudioContext，减少逐条
 *   创建和关闭的开销。服务端 24kHz s16le PCM 在 JS 侧线性重采样到
 *   context.sampleRate 后播放；具体设备的稳定性由真机验收确认。
 * - 播放启动前检查 context.state：suspended 则 await resume()；自动收到
 *   的音频不保证处于用户手势链路。resume 被拒绝或仍未 running
 *   时经 onFailed 如实上报，不伪造播放中状态。
 * - 整体结束由服务端 voice.mobile_tts_end 事件驱动（markEnded），废弃
 *   onended 时间线启发式——网络间隔再长都不会中途误判结束；end 迟迟
 *   不到时按保护性超时如实上报播放异常。
 */

import { useEffect, useRef } from "react";
import { TTS_MAX_BUFFERED_PCM_BYTES, useMobileStore } from "./mobileStore";

const TTS_SAMPLE_RATE = 24000;

/** 排程提前量：时间线上最多提前约 1s 排入音频，限制 AudioBuffer 驻留。 */
export const SCHEDULE_LEAD_SECONDS = 1;

/** V0.3.8：结束信号保护性上限，远超正常回复时长；超时如实报异常。 */
export const END_SIGNAL_TIMEOUT_MS = 5 * 60 * 1000;

let sharedAudioContext: AudioContext | null = null;

/** 测试专用：复位共享 AudioContext 单例，隔离用例间的模块级状态。 */
export function resetSharedAudioContextForTests(): void {
  sharedAudioContext = null;
}

function getSharedAudioContext(): AudioContext {
  if (!sharedAudioContext) {
    // 默认采样率（即设备输出采样率），不强设 sampleRate（见文件头说明）。
    sharedAudioContext = new AudioContext();
  }
  return sharedAudioContext;
}

/**
 * 确保共享 context 处于 running：suspended 则 await resume()。resume 被
 * 拒绝或之后仍未 running 都原样抛出，由调用方如实上报。
 */
async function ensureRunningAudioContext(): Promise<AudioContext> {
  const ctx = getSharedAudioContext();
  if (ctx.state !== "running") {
    await ctx.resume();
    // resume() 会改变 state；TS 不知道副作用，显式放宽再比较。
    const stateAfterResume = ctx.state as AudioContextState;
    if (stateAfterResume !== "running") {
      throw new Error(`AudioContext 无法进入运行态（state=${stateAfterResume}）`);
    }
  }
  return ctx;
}

function base64ToInt16Array(base64: string): Int16Array {
  let binary = "";
  if (typeof atob === "function") {
    binary = atob(base64);
  } else {
    // 兜底：Node 测试环境
    binary = Buffer.from(base64, "base64").toString("binary");
  }
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return new Int16Array(bytes.buffer);
}

/**
 * 线性插值重采样（V0.3.8）：服务端 24kHz PCM → context.sampleRate。
 * 输出长度按比例 floor 缩放，采样点在源波形上线性内插，保持波形。
 */
export function resampleLinear(
  input: Float32Array,
  sourceRate: number,
  targetRate: number,
): Float32Array {
  if (sourceRate === targetRate || input.length === 0) return input;
  const ratio = sourceRate / targetRate;
  // 长度用整数运算：input.length * targetRate 对音频分片远小于 2^53，
  // 避免「数学上整除但浮点除法落在整数下方」的差一样本误差。
  const outLength = Math.floor((input.length * targetRate) / sourceRate);
  const output = new Float32Array(outLength);
  for (let i = 0; i < outLength; i++) {
    const pos = i * ratio;
    const idx = Math.floor(pos);
    const frac = pos - idx;
    const left = input[idx];
    const right = idx + 1 < input.length ? input[idx + 1] : left;
    output[i] = left + (right - left) * frac;
  }
  return output;
}

export interface VoicePlaybackEngineOptions {
  /** end 信号后最后一个分片真实播完，整体收尾时回调。 */
  onFinished(): void;
  /**
   * 播放异常（resume 失败/结束信号超时/解码失败/PCM 超限），如实上报给 store。
   * V0.3.9 §6：errorCode 携带真实失败码（pcm_overflow 等），无则为 null。
   */
  onFailed(error: Error, errorCode: string | null): void;
  /** 测试可缩小；生产与 store 共用同一 PCM 缓冲上限。 */
  maxQueuedPcmBytes?: number;
}

export interface VoicePlaybackEngine {
  playChunk(seq: number, base64: string): void;
  /** voice.mobile_tts_end 已到：等在播/待播分片真实播完后收尾。 */
  markEnded(): void;
  stop(): void;
}

interface QueuedChunk {
  seq: number;
  samples: Int16Array;
}

/**
 * 创建 TTS 播放引擎。每个播放会话独立实例；AudioContext 全应用共享
 * （见文件头），结束或停止都不关闭。
 */
export function createVoicePlaybackEngine(options: VoicePlaybackEngineOptions): VoicePlaybackEngine {
  const {
    onFinished,
    onFailed,
    maxQueuedPcmBytes = TTS_MAX_BUFFERED_PCM_BYTES,
  } = options;
  const queue: QueuedChunk[] = [];
  const activeSources = new Set<AudioBufferSourceNode>();
  let queuedPcmBytes = 0;
  let nextStartTime = 0;
  let ended = false;
  let finished = false;
  let pumping = false;
  let endTimer: ReturnType<typeof setTimeout> | null = null;

  function clearEndTimer(): void {
    if (endTimer !== null) {
      clearTimeout(endTimer);
      endTimer = null;
    }
  }

  function fail(error: Error, errorCode: string | null = null): void {
    if (finished) return;
    finished = true;
    clearEndTimer();
    queue.length = 0;
    queuedPcmBytes = 0;
    stopActiveSources();
    onFailed(error, errorCode);
  }

  function stopActiveSources(): void {
    for (const source of activeSources) {
      try {
        source.stop();
      } catch {
        // 已结束音源与失败清理并发时会抛 InvalidStateError。
      }
    }
    activeSources.clear();
  }

  function checkFinish(): void {
    if (finished || !ended) return;
    // 只由 end 信号驱动收尾；end 未到时哪怕队列暂空也不收尾（网络间隔
    // 再长都不误判），由保护性超时兜底如实报异常。
    if (queue.length > 0 || activeSources.size > 0) return;
    finished = true;
    clearEndTimer();
    onFinished();
  }

  function scheduleChunk(ctx: AudioContext, chunk: QueuedChunk): void {
    const pcm = new Float32Array(chunk.samples.length);
    for (let i = 0; i < chunk.samples.length; i++) {
      pcm[i] = chunk.samples[i] / 32768;
    }
    const samples = resampleLinear(pcm, TTS_SAMPLE_RATE, ctx.sampleRate);
    if (samples.length === 0) return;
    const buffer = ctx.createBuffer(1, samples.length, ctx.sampleRate);
    buffer.getChannelData(0).set(samples);
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);
    const when = Math.max(nextStartTime, ctx.currentTime);
    source.start(when);
    nextStartTime = when + samples.length / ctx.sampleRate;
    activeSources.add(source);
    source.onended = () => {
      activeSources.delete(source);
      if (finished) return;
      pump();
      checkFinish();
    };
  }

  function pump(): void {
    if (pumping || finished) return;
    pumping = true;
    void (async () => {
      try {
        while (queue.length > 0 && !finished) {
          const ctx = await ensureRunningAudioContext();
          if (finished) return;
          // 排程提前量已满则暂停，等 onended 再继续（控制内存驻留）。
          if (nextStartTime - ctx.currentTime >= SCHEDULE_LEAD_SECONDS) break;
          const chunk = queue.shift()!;
          queuedPcmBytes -= chunk.samples.byteLength;
          scheduleChunk(ctx, chunk);
        }
        checkFinish();
      } catch (error) {
        fail(error instanceof Error ? error : new Error(String(error)));
      } finally {
        pumping = false;
      }
    })();
  }

  return {
    playChunk(seq, base64) {
      if (finished) return;
      let samples: Int16Array;
      try {
        samples = base64ToInt16Array(base64);
      } catch (error) {
        fail(error instanceof Error ? error : new Error(String(error)));
        return;
      }
      if (queuedPcmBytes + samples.byteLength > maxQueuedPcmBytes) {
        // V0.3.9 §6：整条播放真实失败（error_code=pcm_overflow），
        // 清空队列与在途音源，不丢旧片段后继续播放。
        fail(
          new Error(
            "播放待播队列超过内存上限：" +
              (queuedPcmBytes + samples.byteLength) +
              " > " +
              maxQueuedPcmBytes +
              " 字节",
          ),
          "pcm_overflow",
        );
        return;
      }
      queue.push({ seq, samples });
      queuedPcmBytes += samples.byteLength;
      if (endTimer === null) {
        endTimer = setTimeout(() => {
          endTimer = null;
          if (!finished && !ended) {
            fail(new Error(
              `播放结束信号超时：${END_SIGNAL_TIMEOUT_MS / 1000} 秒未收到 voice.mobile_tts_end，已中止播放`,
            ));
          }
        }, END_SIGNAL_TIMEOUT_MS);
      }
      pump();
    },

    markEnded() {
      if (finished) return;
      ended = true;
      clearEndTimer();
      pump();
      checkFinish();
    },

    stop() {
      if (finished) return;
      finished = true;
      clearEndTimer();
      queue.length = 0;
      queuedPcmBytes = 0;
      // 共享 context 不关闭（全应用单例）；只停本会话已排程的 source。
      stopActiveSources();
    },
  };
}

/**
 * 订阅 store 中的 TTS 状态并驱动本地播放。
 */
export function useVoicePlayback(_conversationId: string): {
  playingMessageId: string | null;
  playbackMessageId: string;
  playbackState: string;
  playbackError: string | null;
  /** V0.3.9 §6：真实失败码（pcm_overflow 等）；非失败状态为 null。 */
  playbackErrorCode: string | null;
} {
  const playback = useMobileStore((state) => state.voice.playback);
  const ttsChunks = useMobileStore((state) => state.voice.ttsChunks);
  const stopVoicePlayback = useMobileStore((state) => state.stopVoicePlayback);
  const finishVoicePlayback = useMobileStore((state) => state.finishVoicePlayback);
  const releaseTtsChunksUpTo = useMobileStore((state) => state.releaseTtsChunksUpTo);
  const failVoicePlayback = useMobileStore((state) => state.failVoicePlayback);

  const engineRef = useRef<VoicePlaybackEngine | null>(null);
  const currentMessageIdRef = useRef<string | null>(null);
  const latestPlaybackRef = useRef(playback);
  latestPlaybackRef.current = playback;

  useEffect(() => {
    const messageId = playback.messageId;
    if (!messageId) {
      engineRef.current?.stop();
      engineRef.current = null;
      currentMessageIdRef.current = null;
      return;
    }

    if (playback.state === "stopping" || playback.state === "failed" || playback.state === "idle") {
      engineRef.current?.stop();
      engineRef.current = null;
      currentMessageIdRef.current = null;
      return;
    }

    // 换消息时释放旧引擎
    if (engineRef.current && currentMessageIdRef.current !== messageId) {
      engineRef.current.stop();
      engineRef.current = null;
      currentMessageIdRef.current = null;
    }

    const chunks = ttsChunks[messageId] || [];
    if (!engineRef.current) {
      if (playback.state === "playing" && chunks.length === 0) {
        // V0.3.8：end 先于任何分片（空音频）且引擎从未建立时直接复位，
        // 避免卡在 playing；引擎已建立时由 markEnded 等真实播完再收尾。
        finishVoicePlayback(messageId);
        return;
      }
      currentMessageIdRef.current = messageId;
      engineRef.current = createVoicePlaybackEngine({
        onFinished: () => {
          if (currentMessageIdRef.current === messageId) {
            finishVoicePlayback(messageId);
            engineRef.current = null;
            currentMessageIdRef.current = null;
          }
        },
        onFailed: (error, errorCode) => {
          if (currentMessageIdRef.current === messageId) {
            failVoicePlayback(messageId, error.message, errorCode);
            engineRef.current = null;
            currentMessageIdRef.current = null;
          }
        },
      });
    }
    const engine = engineRef.current;

    let maxSeq = -1;
    for (const chunk of chunks) {
      engine.playChunk(chunk.seq, chunk.data);
      maxSeq = Math.max(maxSeq, chunk.seq);
    }
    if (maxSeq >= 0) {
      // 分片已解码交给引擎（排程队列/音频图内），store 不再留底，
      // 长回复不再全量驻留内存。
      releaseTtsChunksUpTo(messageId, maxSeq);
    }
    if (playback.state === "playing") {
      engine.markEnded();
    }
  }, [playback, ttsChunks, finishVoicePlayback, releaseTtsChunksUpTo, failVoicePlayback]);

  // 组件卸载时清理：必须且仅在组件真正 unmount 时触发，绝不能以 playback.messageId
  // 为依赖，否则每次 messageId 变化都会先用旧 ID 触发 cleanup 导致停止风暴死循环。
  useEffect(() => {
    return () => {
      engineRef.current?.stop();
      engineRef.current = null;
      currentMessageIdRef.current = null;
      const current = latestPlaybackRef.current;
      if (current.messageId && (current.state === "playing" || current.state === "buffering")) {
        stopVoicePlayback(current.messageId).catch(() => {
          // 卸载时忽略错误，避免未捕获异常
        });
      }
    };
  }, [stopVoicePlayback]);

  return {
    // 失败不是播放中：朗读中标记必须退出，错误经 playbackError 呈现。
    playingMessageId: playback.state === "failed" ? null : playback.messageId,
    playbackMessageId: playback.messageId ?? "",
    playbackState: playback.state,
    playbackError: playback.state === "failed" ? playback.error : null,
    playbackErrorCode: playback.state === "failed" ? (playback.errorCode ?? null) : null,
  };
}
