import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { ConversationRecord } from "../../contracts/protocol";
import { createMockScenario } from "../../mocks/scenarios";
import { createActionController } from "../../services/actions";
import { MockDesktopBackend } from "../../services/mockDesktopBackend";
import { desktopStore } from "../../stores/desktopStore";
import { TopBar } from "../TopBar";

/** 单项目快照，只把当前聊天替换成绑定角色卡的会话。 */
function hydrateCardConversation(): void {
  const base = createMockScenario("single-project").snapshot;
  const project = base.projects[0];
  const cardConversation: ConversationRecord = {
    ...project.conversations[0],
    conversation_id: "conv-card",
    character_card_id: "card-saved-002",
    binding_id: "card-bind-card-saved-002",
    character_identity: {
      name: "卡芙卡",
      avatar_ref: null,
      avatar_version: null,
      missing: false,
      source: "card",
    },
  };
  desktopStore.setState(desktopStore.getInitialState(), true);
  desktopStore.getState().hydrate({
    ...base,
    projects: [{ ...project, conversations: [cardConversation] }],
    current_conversation_id: "conv-card",
    current_conversation: cardConversation,
  });
  desktopStore.getState().openConversationTab("conv-card");
}

function renderTopBar(): void {
  const controller = createActionController(new MockDesktopBackend());
  render(
    <TopBar
      mode="chat"
      pair={desktopStore.getState().pair!}
      assistantBusy={false}
      connectionStatus="connected"
      onOpenTechDetails={() => undefined}
      onOpenDiagnostics={() => undefined}
      onOpenSettings={() => undefined}
      actions={controller.actions}
    />,
  );
}

describe("TopBar 搭档显示", () => {
  afterEach(() => {
    cleanup();
    desktopStore.setState(desktopStore.getInitialState(), true);
  });

  it("卡会话显示角色卡卡名与绑定的助手名", () => {
    hydrateCardConversation();
    renderTopBar();

    const banner = screen.getByRole("banner");
    expect(banner).toHaveTextContent("卡芙卡");
    expect(banner).toHaveTextContent("神秘的古代机械");
    // 内置搭档的名字不再作为卡会话的角色名出现。
    expect(banner).not.toHaveTextContent("白厄");
  });
});
