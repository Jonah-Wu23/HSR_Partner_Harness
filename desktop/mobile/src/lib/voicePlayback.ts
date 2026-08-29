/**
 * V0.3.5 手机端语音播放引擎。
 *
 * 消费 mobileStore 的 voice.ttsChunks[messageId]，用 AudioContext 队列播放
 * 24kHz s16le PCM；voice.mobile_tts_end 到达后自然播放到末尾并复位。
 */

import { useEffect, useRef } from "react";
import { useMobileStore } from "./mobileStore";

const TTS_SAMPLE_RATE = 24000;

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

export interface VoicePlaybackEngineOptions {
  onFinished(): void;
}

export interface VoicePlaybackEngine {
  playChunk(base64: string): void;
  stop(): void;
}

/**
 * 创建 TTS 播放引擎。每个 messageId 独立实例，结束或停止时关闭 AudioContext。
 */
export function createVoicePlaybackEngine(options: VoicePlaybackEngineOptions): VoicePlaybackEngine {
  const { onFinished } = options;
  let audioContext: AudioContext | null = null;
  let nextStartTime = 0;
  const sources: AudioBufferSourceNode[] = [];
  let finished = false;

  function ensureContext(): AudioContext | null {
    if (audioContext) return audioContext;
    if (typeof AudioContext === "undefined") return null;
    try {
      audioContext = new AudioContext({ sampleRate: TTS_SAMPLE_RATE });
    } catch {
      // 部分浏览器不支持任意 sampleRate，回退默认采样率（可能音调/速度偏移）
      audioContext = new AudioContext();
    }
    nextStartTime = audioContext.currentTime;
    return audioContext;
  }

  function maybeFinish() {
    if (finished) return;
    const ctx = audioContext;
    if (!ctx) return;
    // 预留一点余量避免最后一个 source 的 onended 还没全部触发
    if (nextStartTime <= ctx.currentTime + 0.05) {
      finished = true;
      sources.length = 0;
      ctx.close().catch(() => {
        // ignore
      });
      audioContext = null;
      onFinished();
    }
  }

  return {
    playChunk(base64) {
      if (finished) return;
      const ctx = ensureContext();
      if (!ctx) return;

      const samples = base64ToInt16Array(base64);
      const buffer = ctx.createBuffer(1, samples.length, ctx.sampleRate);
      const channel = buffer.getChannelData(0);
      for (let i = 0; i < samples.length; i++) {
        channel[i] = samples[i] / 32768;
      }

      const source = ctx.createBufferSource();
      source.buffer = buffer;
      source.connect(ctx.destination);
      const when = Math.max(nextStartTime, ctx.currentTime);
      source.start(when);
      nextStartTime = when + buffer.duration;
      sources.push(source);

      source.onended = () => {
        maybeFinish();
      };
    },

    stop() {
      if (finished) return;
      finished = true;
      sources.forEach((src) => {
        try {
          src.stop();
          src.disconnect();
        } catch {
          // ignore
        }
      });
      sources.length = 0;
      if (audioContext) {
        audioContext.close().catch(() => {
          // ignore
        });
        audioContext = null;
      }
    },
  };
}

/**
 * 订阅 store 中的 TTS 状态并驱动本地播放。
 */
export function useVoicePlayback(_conversationId: string): {
  playingMessageId: string | null;
  playbackState: string;
} {
  const playback = useMobileStore((state) => state.voice.playback);
  const ttsChunks = useMobileStore((state) => state.voice.ttsChunks);
  const stopVoicePlayback = useMobileStore((state) => state.stopVoicePlayback);
  const finishVoicePlayback = useMobileStore((state) => state.finishVoicePlayback);

  const engineRef = useRef<VoicePlaybackEngine | null>(null);
  const playedRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    const messageId = playback.messageId;
    if (!messageId) {
      engineRef.current?.stop();
      engineRef.current = null;
      return;
    }

    if (playback.state === "stopping") {
      engineRef.current?.stop();
      engineRef.current = null;
      return;
    }

    const chunks = ttsChunks[messageId] || [];
    // V0.3.5：如果 mobile_tts_end 到达时对应 messageId 还没有收到任何分片，
    // 播放引擎不会有 source.onended 触发 finish，需要显式复位避免卡在 playing。
    if (playback.state === "playing" && chunks.length === 0) {
      finishVoicePlayback(messageId);
      return;
    }

    if (!engineRef.current) {
      engineRef.current = createVoicePlaybackEngine({
        onFinished: () => {
          finishVoicePlayback(messageId);
          engineRef.current = null;
          playedRef.current.clear();
        },
      });
    }

    for (const chunk of chunks) {
      const key = `${messageId}-${chunk.seq}`;
      if (!playedRef.current.has(key)) {
        engineRef.current.playChunk(chunk.data);
        playedRef.current.add(key);
      }
    }
  }, [playback, ttsChunks, finishVoicePlayback]);

  useEffect(() => {
    return () => {
      engineRef.current?.stop();
      engineRef.current = null;
      if (playback.messageId) {
        stopVoicePlayback(playback.messageId).catch(() => {
          // 卸载时忽略错误，避免未捕获异常
        });
      }
    };
  }, [stopVoicePlayback, playback.messageId]);

  return {
    playingMessageId: playback.messageId,
    playbackState: playback.state,
  };
}
