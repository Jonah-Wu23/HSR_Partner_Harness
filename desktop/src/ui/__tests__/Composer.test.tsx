import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { HarnessActions } from "../../contracts/actions";
import type { ComposerViewModel, VoiceViewModel } from "../../contracts/view-models";
import { Composer } from "../composer/Composer";

const composer: ComposerViewModel = {
  target: "character",
  draft: "",
  enabled: true,
  approvalMode: "request_approval",
  reasoningEffort: "low",
  asrPartial: "",
};

const voice: VoiceViewModel = {
  supported: true,
  enabled: true,
  assistant_voice_enabled: false,
  vad: "idle",
  vad_enabled: false,
  ptt: false,
  tts: "idle",
  asr_partial: "",
  error: null,
  speech_queue_len: 0,
  canPushToTalk: true,
};

function stubActions(): HarnessActions {
  return {
    submitMessage: vi.fn(),
    setVadEnabled: vi.fn(),
    startPushToTalk: vi.fn(),
    stopPushToTalk: vi.fn(),
    stopSpeech: vi.fn(),
    skipSpeech: vi.fn(),
    setReasoningEffort: vi.fn(),
  } as unknown as HarnessActions;
}

afterEach(cleanup);

describe("Composer 语音按钮组", () => {
  it("voice.enabled=true 时显示 VAD/按键说话/停止播报与状态", () => {
    render(<Composer composer={composer} voice={voice} mode="chat" actions={stubActions()} />);
    expect(screen.getByRole("button", { name: "VAD" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "按键说话" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "停止播报" })).toBeInTheDocument();
  });

  it("voice.enabled=false 时语音按钮组整体隐藏", () => {
    render(
      <Composer
        composer={composer}
        voice={{ ...voice, enabled: false }}
        mode="chat"
        actions={stubActions()}
      />,
    );
    expect(screen.queryByRole("button", { name: "VAD" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "按键说话" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "停止播报" })).not.toBeInTheDocument();
  });

  it("VAD 按钮切换，PTT 点击开始/结束聆听", () => {
    const actions = stubActions();
    render(<Composer composer={composer} voice={voice} mode="chat" actions={actions} />);
    fireEvent.click(screen.getByRole("button", { name: "VAD" }));
    expect(actions.setVadEnabled).toHaveBeenCalledWith(true);

    const ptt = screen.getByRole("button", { name: "按键说话" });
    fireEvent.click(ptt);
    expect(actions.startPushToTalk).toHaveBeenCalledWith("character");
    fireEvent.click(ptt);
    expect(actions.stopPushToTalk).toHaveBeenCalled();
  });

  it("右 Alt 作为默认 PTT 键位，按下切换，松开不结束", () => {
    const actions = stubActions();
    render(<Composer composer={composer} voice={voice} mode="chat" actions={actions} />);

    fireEvent.keyDown(window, { code: "AltRight", key: "Alt", location: 2 });
    expect(actions.startPushToTalk).toHaveBeenCalledWith("character");
    fireEvent.keyUp(window, { code: "AltRight", key: "Alt", location: 2 });
    expect(actions.stopPushToTalk).not.toHaveBeenCalled();
    fireEvent.keyDown(window, { code: "AltRight", key: "Alt", location: 2 });
    expect(actions.stopPushToTalk).toHaveBeenCalled();
  });
});
