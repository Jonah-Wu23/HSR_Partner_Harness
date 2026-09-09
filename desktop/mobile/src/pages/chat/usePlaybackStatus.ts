import { useMemo } from "react";
import { useMobileStore } from "../../lib/mobileStore";

/**
 * V0.3.9 V07（移动）播放抢占与页级播放错误适配层。
 *
 * 待真实接线（mobileStore / 逻辑轨）：
 * 1. `voice.playback_interrupted` 事件：protocol.ts 已冻结事件名，但尚无载荷类型，
 *    store 也还没有对应分支。本适配层按「被打断消息 + 原因 + 时刻」读取，
 *    字段名同时兼容 camel/snake（`messageId|message_id`、`at|interrupted_at`），
 *    缺失一律 null —— 不伪造「已停止」状态，也不在没有事件时不显示提示。
 * 2. 播放错误码：`voice.mobile_tts_failed` 载荷已带 `error_code`（如 pcm_overflow），
 *    但 store 只保留了 `error` 文本，`playback` 里没有 errorCode 字段。
 *    本适配层读取可选字段 `voice.playback.errorCode`（兼容 `error_code`），
 *    未接线时返回 null，页级错误条只展示原始 error 文本，不伪造错误码。
 */

export interface PlaybackInterruptionView {
  /** 被打断 / 已停止的消息 id；无值 null。 */
  messageId: string | null;
  /** 服务端给出的打断原因；缺失 null（不合成「已被新回复打断」以外的结论）。 */
  reason: string | null;
  /** 打断时刻（服务端时间）；缺失 null。 */
  at: string | null;
}

interface PlaybackInterruptionFields {
  messageId?: string | null;
  message_id?: string | null;
  reason?: string | null;
  at?: string | null;
  interrupted_at?: string | null;
}

interface VoiceStoreFields {
  lastInterruption?: PlaybackInterruptionFields | null;
  playbackInterruption?: PlaybackInterruptionFields | null;
}

interface PlaybackErrorCodeFields {
  errorCode?: string | null;
  error_code?: string | null;
}

function toInterruptionView(
  raw: PlaybackInterruptionFields | null | undefined,
): PlaybackInterruptionView | null {
  if (!raw) return null;
  const messageId = raw.messageId ?? raw.message_id ?? null;
  const reason = raw.reason ?? null;
  const at = raw.at ?? raw.interrupted_at ?? null;
  if (messageId === null && reason === null && at === null) return null;
  return { messageId, reason, at };
}

/** 最近一次播放被打断 / 被显式停止的真实事件；未接线或未发生时为 null。 */
export function usePlaybackInterruption(): PlaybackInterruptionView | null {
  const raw = useMobileStore((state) => {
    const voice = state.voice as typeof state.voice & VoiceStoreFields;
    return voice.lastInterruption ?? voice.playbackInterruption ?? null;
  });
  return useMemo(() => toInterruptionView(raw), [raw]);
}

/** 当前播放失败的真实错误码（如 pcm_overflow）；未接线或未失败时为 null。 */
export function usePlaybackErrorCode(): string | null {
  return useMobileStore((state) => {
    const playback = state.voice.playback as typeof state.voice.playback &
      PlaybackErrorCodeFields;
    return playback.errorCode ?? playback.error_code ?? null;
  });
}
