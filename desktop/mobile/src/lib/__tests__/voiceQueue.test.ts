import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { mobileWsClient, resetVoiceTerminalStateForTests, useMobileStore } from "../mobileStore";

let sequence = 0;
function emit(event: string, messageId: string) {
  mobileWsClient.emitTestEvent({ kind: "event", event, sequence: ++sequence,
    payload: { message_id: messageId, seq: sequence, data: "ZAA=", error: "synthesis failed" } });
}
const chunk = (id: string) => emit("voice.mobile_tts_chunk", id);
const end = (id: string) => emit("voice.mobile_tts_end", id);

beforeEach(() => {
  resetVoiceTerminalStateForTests();
  vi.spyOn(mobileWsClient, "connect").mockImplementation(() => {});
  useMobileStore.getState().start();
  sequence = 0;
  useMobileStore.setState({ lastSequence: 0, streamId: null, bootstrapped: false,
    voice: { ...useMobileStore.getState().voice,
      playback: { messageId: null, state: "idle", error: null }, ttsChunks: {}, ttsDroppedChunks: {} } });
});
afterEach(() => vi.restoreAllMocks());

it("A 播放期间新回复 B 分片到达，旧回复 A 立即被截断并由 B 抢占播放", () => {
  chunk("queue-a");
  expect(useMobileStore.getState().voice.playback).toMatchObject({ messageId: "queue-a", state: "buffering" });
  chunk("queue-b");
  expect(useMobileStore.getState().voice.playback).toMatchObject({ messageId: "queue-b", state: "buffering" });
  expect(useMobileStore.getState().voice.ttsChunks["queue-a"]).toBeUndefined();
  end("queue-b");
  expect(useMobileStore.getState().voice.playback).toMatchObject({ messageId: "queue-b", state: "playing" });
  useMobileStore.getState().finishVoicePlayback("queue-b");
  expect(useMobileStore.getState().voice.playback.state).toBe("idle");
  expect(useMobileStore.getState().voice.ttsChunks).toEqual({});
});

it("A 播放期间新角色回复 message.created 出现，旧回复 A 立即被打断", () => {
  chunk("queue-a");
  expect(useMobileStore.getState().voice.playback).toMatchObject({ messageId: "queue-a", state: "buffering" });
  useMobileStore.setState({ activeConversationId: "conv-1" });
  mobileWsClient.emitTestEvent({
    kind: "event",
    event: "message.created",
    sequence: ++sequence,
    payload: {
      conversation_id: "conv-1",
      message: {
        message_id: "msg-b",
        conversation_id: "conv-1",
        source: "character",
        tts_ready: true,
        text: "下一条消息的回答",
      },
    },
  });
  expect(useMobileStore.getState().voice.playback.state).toBe("idle");
  expect(useMobileStore.getState().voice.ttsChunks["queue-a"]).toBeUndefined();
  chunk("msg-b");
  expect(useMobileStore.getState().voice.playback).toMatchObject({ messageId: "msg-b", state: "buffering" });
});

it("旧消息迟到的失败不能停止新消息", () => {
  chunk("old-failure"); end("old-failure");
  useMobileStore.getState().finishVoicePlayback("old-failure");
  chunk("new-after-old");
  emit("voice.mobile_tts_failed", "old-failure");
  expect(useMobileStore.getState().voice.playback).toMatchObject({ messageId: "new-after-old", state: "buffering" });
});

it("一次播放失败后下一条消息仍能启动", () => {
  chunk("failed-a");
  useMobileStore.getState().failVoicePlayback("failed-a", "resume denied");
  chunk("after-failed-a");
  expect(useMobileStore.getState().voice.playback).toMatchObject({ messageId: "after-failed-a", state: "buffering" });
});

it("未到达分片的其他消息合成失败只清理自身，正在播放的 A 不受影响", () => {
  chunk("active-before-failure");
  emit("voice.mobile_tts_failed", "other-failure");
  expect(useMobileStore.getState().voice.playback.messageId).toBe("active-before-failure");
  expect(useMobileStore.getState().voice.ttsChunks["other-failure"]).toBeUndefined();
});

it("停止请求未返回时收到完整 B，停止回执后保留 B", async () => {
  let resolveStop!: (value: unknown) => void;
  vi.spyOn(mobileWsClient, "request").mockImplementation(() => new Promise(resolve => { resolveStop = resolve; }));
  chunk("stop-queue-a");
  const stop = useMobileStore.getState().stopVoicePlayback("stop-queue-a");
  chunk("stop-queue-b"); end("stop-queue-b");
  resolveStop({ stopped: true });
  await stop;
  expect(useMobileStore.getState().voice.playback).toMatchObject({ messageId: "stop-queue-b", state: "playing" });
});
