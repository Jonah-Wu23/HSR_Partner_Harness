import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { Message, PairRecord } from "../../../contracts/protocol";
import type { WorkspaceViewModel } from "../../../contracts/view-models";
import { Workspace } from "../Workspace";

const pair: PairRecord = {
  pair_id: "phainon_ancient_machine",
  character: { id: "phainon", name: "白厄", voice_id: "v-char" },
  assistant: { id: "mech", name: "神秘的古代机械", voice_id: "v-mech" },
  theme: {
    character_text: "#C7D4E3",
    character_primary: "#8AA4D4",
    character_deep: "#3A548C",
    character_active: "#296CE1",
    assistant_primary: "#B08D57",
    assistant_bright: "#C5A059",
    assistant_shadow: "#8C6B3F",
  },
};

function message(overrides: Partial<Message> = {}): Message {
  return {
    message_id: "m-1",
    conversation_id: "conv-1",
    pair_id: "phainon_ancient_machine",
    engine_turn_id: null,
    source: "character",
    kind: "character.speech",
    text: "示例文本",
    payload: {},
    tts_eligible: true,
    created_at: "2026-08-11T00:00:00Z",
    timeline_order: 1,
    ...overrides,
  };
}

function makeWorkspace(messages: Message[] = []): WorkspaceViewModel {
  return {
    mode: "chat",
    character: { conversationId: "conv-1", messages, isStreaming: false, queueItems: [] },
    assistant: {
      conversationId: "conv-1",
      messages: [],
      toolRuns: [],
      items: [],
      busy: false,
      activeTask: null,
    },
    delegation: null,
  };
}

function renderWorkspace(characterName: string, workspace = makeWorkspace()) {
  return render(
    <Workspace
      workspace={workspace}
      pair={pair}
      characterName={characterName}
      onQuickTask={() => undefined}
      onCloseWorkbench={() => undefined}
      onCancelDelegation={() => undefined}
    />,
  );
}

describe("Workspace 角色身份展示", () => {
  afterEach(cleanup);

  it("纯聊天模式下角色区标题、能力提示与空态都用会话身份名", () => {
    renderWorkspace("卡芙卡");

    const pane = screen.getByLabelText("角色区");
    expect(within(pane).getByText("卡芙卡")).toBeInTheDocument();
    expect(within(pane).getByRole("note")).toHaveTextContent("纯聊天 · 卡芙卡 暂时看不到你的项目");
    expect(within(pane).getByText("和 卡芙卡 聊聊吧")).toBeInTheDocument();
    expect(pane).not.toHaveTextContent("白厄");
  });

  it("切换会话身份后角色区显示新卡名，不残留上一个身份", () => {
    const { rerender } = renderWorkspace("卡芙卡");
    rerender(
      <Workspace
        workspace={makeWorkspace()}
        pair={pair}
        characterName="银狼"
        onQuickTask={() => undefined}
        onCloseWorkbench={() => undefined}
        onCancelDelegation={() => undefined}
      />,
    );

    const pane = screen.getByLabelText("角色区");
    expect(pane).toHaveTextContent("银狼");
    expect(pane).not.toHaveTextContent("卡芙卡");
  });

  it("角色消息署名与委派来源都用会话身份名", () => {
    const workspace: WorkspaceViewModel = {
      ...makeWorkspace([message({ message_id: "m-card", text: "本姑娘出马当然拍到啦" })]),
      delegation: {
        delegationId: "d-1",
        fromName: "卡芙卡",
        summary: "读取项目结构",
        status: "running",
      },
    };
    renderWorkspace("卡芙卡", workspace);

    const bubble = screen.getByText("本姑娘出马当然拍到啦").closest(".msg-row");
    expect(bubble).not.toBeNull();
    expect(within(bubble as HTMLElement).getByText("卡芙卡")).toBeInTheDocument();
    expect(screen.getByLabelText("来自卡芙卡的委派")).toBeInTheDocument();
    expect(screen.getByText("来自 卡芙卡 的委派")).toBeInTheDocument();
  });

  it("助手侧仍用基础搭档名，不受角色身份影响", () => {
    renderWorkspace("卡芙卡");

    const workbench = screen.getByLabelText("助手工作台");
    expect(workbench).toHaveTextContent("神秘的古代机械");
    expect(workbench).not.toHaveTextContent("卡芙卡");
  });
});
