import { type MobilePlaybackInterruption, useMobileStore } from "../../lib/mobileStore";

/**
 * 聊天页的朗读状态：打断提示、播放错误与朗读中的消息。
 * 各自只订阅一个原始值，TTS 分片到达时页面不随之重新渲染。
 * 打断记录由 store 处理 voice.playback_interrupted 时写入，下一条朗读开始时清空。
 */

/** 本聊天最近一次朗读被打断的记录；没有发生时为 null。 */
export function usePlaybackInterruption(
  conversationId: string,
): MobilePlaybackInterruption | null {
  return useMobileStore((state) => {
    const interruption = state.voice.lastInterruption;
    return interruption && interruption.conversationId === conversationId ? interruption : null;
  });
}

/** 当前播放失败的错误码（如 pcm_overflow）；未失败时为 null。 */
export function usePlaybackErrorCode(): string | null {
  return useMobileStore((state) => state.voice.playback.errorCode);
}

/** 当前播放失败的错误原文；未失败时为 null。 */
export function usePlaybackError(): string | null {
  return useMobileStore((state) =>
    state.voice.playback.state === "failed" ? state.voice.playback.error : null,
  );
}

/** 当前播放状态所属的消息（包括失败的那条）。 */
export function usePlaybackMessageId(): string | null {
  return useMobileStore((state) => state.voice.playback.messageId);
}

/** 正在朗读的消息；失败不算朗读中，朗读中标记随之退出。 */
export function usePlayingMessageId(): string | null {
  return useMobileStore((state) =>
    state.voice.playback.state === "failed" ? null : state.voice.playback.messageId,
  );
}
