import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { ComposerViewModel, VoiceViewModel } from "../../contracts/view-models";
import { createActionController } from "../../services/actions";
import { DesktopRequestError } from "../../services/backend";
import { MockDesktopBackend } from "../../services/mockDesktopBackend";
import { desktopStore } from "../../stores/desktopStore";
import { fakeBackend, unexpectedCommand } from "../../test/fakeBackend";
import { Composer } from "../composer/Composer";

const composer: ComposerViewModel = {
  target: "character",
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

const VOICE_BUTTONS = ["VAD", "按键说话", "停止播报"];
const RIGHT_ALT = { code: "AltRight", key: "Alt", location: 2 };

afterEach(() => {
  cleanup();
  desktopStore.setState(desktopStore.getInitialState(), true);
});

/** 启动 single-project 场景（活动聊天 conv-1），返回 MockDesktopBackend 与真实 actions。 */
async function connectMockBackend() {
  const backend = new MockDesktopBackend("single-project");
  const controller = createActionController(backend);
  await controller.loadBootstrap();
  return { backend, actions: controller.actions };
}

/** 启动快照之后输入区发出的命令。 */
function composerCommands(backend: MockDesktopBackend) {
  return backend.recordedRequests
    .filter((command) => command.method !== "app.bootstrap")
    .map(({ method, params }) => ({ method, params }));
}

describe("Composer 语音按钮组", () => {
  it.each([
    { enabled: true, label: "显示", visible: VOICE_BUTTONS },
    { enabled: false, label: "整体隐藏", visible: [] },
  ])("voice.enabled=$enabled 时语音按钮组$label", ({ enabled, visible }) => {
    const { actions } = createActionController(new MockDesktopBackend("single-project"));
    render(<Composer composer={composer} voice={{ ...voice, enabled }} mode="chat" actions={actions} />);

    expect(VOICE_BUTTONS.filter((name) => screen.queryByRole("button", { name }))).toEqual(visible);
  });

  it("点击 VAD 下发开启 VAD，点击按键说话依次下发开始与结束聆听", async () => {
    const { backend, actions } = await connectMockBackend();
    render(<Composer composer={composer} voice={voice} mode="chat" actions={actions} />);

    fireEvent.click(screen.getByRole("button", { name: "VAD" }));
    const ptt = screen.getByRole("button", { name: "按键说话" });
    fireEvent.click(ptt);
    expect(ptt).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(ptt);
    expect(ptt).toHaveAttribute("aria-pressed", "false");

    expect(composerCommands(backend)).toEqual([
      { method: "voice.vad_set", params: { enabled: true } },
      { method: "voice.ptt_start", params: { target: "character", conversation_id: "conv-1" } },
      { method: "voice.ptt_stop", params: {} },
    ]);
  });

  it("右 Alt 按下切换聆听，松开不结束", async () => {
    const { backend, actions } = await connectMockBackend();
    render(<Composer composer={composer} voice={voice} mode="chat" actions={actions} />);

    fireEvent.keyDown(window, RIGHT_ALT);
    fireEvent.keyUp(window, RIGHT_ALT);
    expect(composerCommands(backend)).toEqual([
      { method: "voice.ptt_start", params: { target: "character", conversation_id: "conv-1" } },
    ]);

    fireEvent.keyDown(window, RIGHT_ALT);
    expect(composerCommands(backend).map(({ method }) => method)).toEqual([
      "voice.ptt_start",
      "voice.ptt_stop",
    ]);
  });
});

describe("Composer 发送", () => {
  it("请求失败时保留输入文字并显示错误原文", async () => {
    const { backend } = fakeBackend((command) => {
      if (command.method !== "chat.submit") return unexpectedCommand(command);
      throw new DesktopRequestError("no_active_conversation", "请先创建或选择项目");
    });
    render(
      <Composer
        composer={composer}
        voice={voice}
        mode="chat"
        actions={createActionController(backend).actions}
      />,
    );

    const textarea = screen.getByLabelText("消息输入");
    fireEvent.change(textarea, { target: { value: "这句话不能丢" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("请先创建或选择项目");
    expect(textarea).toHaveValue("这句话不能丢");
  });

  it("后端接收消息后清空草稿", async () => {
    const { backend, actions } = await connectMockBackend();
    render(<Composer composer={composer} voice={voice} mode="chat" actions={actions} />);

    const textarea = screen.getByLabelText("消息输入");
    fireEvent.change(textarea, { target: { value: "发送成功" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => expect(textarea).toHaveValue(""));
    expect(composerCommands(backend)).toEqual([
      {
        method: "chat.submit",
        params: { conversation_id: "conv-1", target: "character", text: "发送成功" },
      },
    ]);
  });
});
