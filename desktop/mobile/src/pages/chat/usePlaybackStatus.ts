import { type MobilePlaybackInterruption, useMobileStore } from "../../lib/mobileStore";

/**
 * 聊天页的朗读打断提示与页级播放错误码。
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
