/**
 * 手机端朗读播放引擎。
 *
 * - 全应用共享一个设备输出采样率的 AudioContext。服务端下发 24kHz s16le PCM，
 *   每个分片建成 24kHz 的 AudioBuffer，由 AudioBufferSourceNode 重采样到设备采样率。
 * - 排程前检查 context.state：suspended 则 await resume()，自动收到的音频不一定处在
 *   用户手势链路里；resume 被拒或仍未 running 时经 onFailed 上报。
 * - 整体结束由服务端 voice.mobile_tts_end 驱动（markEnded），分片间隔再长也不会提前收尾；
 *   结束信号迟迟不到时按保护性超时上报失败。
 */

import { useEffect, useRef } from "react";
import { TTS_MAX_BUFFERED_PCM_BYTES, TTS_SAMPLE_RATE, useMobileStore } from "./mobileStore";

/** 排程提前量：时间线上最多提前约 1s 排入音频，限制 AudioBuffer 驻留。 */
export const SCHEDULE_LEAD_SECONDS = 1;

/** 结束信号的保护性上限，远超正常回复时长。 */
export const END_SIGNAL_TIMEOUT_MS = 5 * 60 * 1000;

let sharedAudioContext: AudioContext | null = null;

function getSharedAudioContext(): AudioContext {
  // 使用设备输出采样率，PCM 的重采样交给 AudioBufferSourceNode。
  sharedAudioContext ??= new AudioContext();
  return sharedAudioContext;
}

/**
 * 确保共享 context 处于 running：suspended 则 await resume()。resume 被拒绝
 * 或之后仍未 running 时抛出，由调用方经 onFailed 上报。
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

/** base64 编码的 s16le PCM 解码为采样数组。 */
function base64ToInt16Array(base64: string): Int16Array {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return new Int16Array(bytes.buffer);
}

export interface VoicePlaybackEngineOptions {
  /** 结束信号到达后最后一个分片播完时回调。 */
  onFinished(): void;
  /** 播放失败（resume 失败、结束信号超时、解码失败、PCM 超限）；errorCode 如 pcm_overflow，没有时为 null。 */
  onFailed(error: Error, errorCode: string | null): void;
  /** 待播 PCM 字节上限，默认与 store 的缓冲上限相同。 */
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
    // 集合里的音源都已 start()，对已播完的音源调用 stop() 不会抛错。
    for (const source of activeSources) source.stop();
    activeSources.clear();
  }

  function checkFinish(): void {
    // 只由结束信号驱动收尾：信号未到时队列暂空也继续等待，由保护性超时上报失败。
    if (finished || !ended) return;
    if (queue.length > 0 || activeSources.size > 0) return;
    finished = true;
    clearEndTimer();
    onFinished();
  }

  function scheduleChunk(ctx: AudioContext, chunk: QueuedChunk): void {
    if (chunk.samples.length === 0) return;
    // 24kHz 的 AudioBuffer 播放时由 AudioBufferSourceNode 重采样到 context 采样率。
    const buffer = ctx.createBuffer(1, chunk.samples.length, TTS_SAMPLE_RATE);
    const channel = buffer.getChannelData(0);
    for (let i = 0; i < chunk.samples.length; i++) {
      channel[i] = chunk.samples[i] / 32768;
    }
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);
    const when = Math.max(nextStartTime, ctx.currentTime);
    source.start(when);
    nextStartTime = when + buffer.duration;
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
        // 整条播放失败并清空队列与在途音源。
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
      // 共享 context 不关闭，只停本次播放已排程的音源。
      stopActiveSources();
    },
  };
}

/**
 * 订阅 store 中的朗读状态与 TTS 分片并驱动本地播放。分片每次到达都会触发它，
 * 调用方把它放在只负责播放的组件里，页面与时间线经各自的选择器读取播放状态。
 */
export function useVoicePlayback(): void {
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
        // 结束信号先于任何分片（空音频）且引擎从未建立：直接复位，避免停在 playing。
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
      // 分片已交给引擎排程，store 不再保留，长回复不会整段驻留内存。
      releaseTtsChunksUpTo(messageId, maxSeq);
    }
    if (playback.state === "playing") {
      engine.markEnded();
    }
  }, [playback, ttsChunks, finishVoicePlayback, releaseTtsChunksUpTo, failVoicePlayback]);

  // 只在组件卸载时清理。依赖里不能有 playback.messageId，否则每次换消息都会先用旧 id
  // 触发清理，形成停止请求风暴。
  useEffect(() => {
    return () => {
      engineRef.current?.stop();
      engineRef.current = null;
      currentMessageIdRef.current = null;
      const current = latestPlaybackRef.current;
      if (current.messageId && (current.state === "playing" || current.state === "buffering")) {
        const messageId = current.messageId;
        // 停止失败已写入 store 的 playback 状态，这里补一条日志。
        stopVoicePlayback(messageId).catch((error: unknown) => {
          console.error("离开聊天页时停止朗读失败", messageId, error);
        });
      }
    };
  }, [stopVoicePlayback]);
}
