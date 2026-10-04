import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { ConversationRecord, DesktopSnapshot, PairOption } from "../../../contracts/protocol";
import { MOCK_PAIR_OPTIONS, createMockScenario } from "../../../mocks/scenarios";
import { presentAppShell } from "../../../presenters/presenters";
import { createActionController } from "../../../services/actions";
import { MockDesktopBackend } from "../../../services/mockDesktopBackend";
import { desktopStore } from "../../../stores/desktopStore";
import { ChatColumn } from "../ChatColumn";

/** mock 里已保存的卡芙卡对应的搭档目录项。 */
const CARD_OPTION: PairOption = {
  binding_id: "card-bind-card-saved-002",
  pair_id: "phainon_ancient_machine",
  character_card_id: "card-saved-002",
  source: "card",
  character: {
    id: "card-saved-002",
    name: "卡芙卡",
    voice_id: "",
    avatar_ref: null,
    avatar_version: null,
    missing: false,
  },
  assistant: { ...MOCK_PAIR_OPTIONS[0].assistant },
  theme: { ...MOCK_PAIR_OPTIONS[0].theme },
};

function cardConversation(overrides: Partial<ConversationRecord> = {}): ConversationRecord {
  return {
    conversation_id: "conv-card",
    project_id: "project-1",
    pair_id: "phainon_ancient_machine",
    title: "和卡芙卡的聊天",
    last_mode: "chat",
    archived: false,
    created_at: "2026-08-11T00:00:00+00:00",
    updated_at: "2026-08-11T00:00:00+00:00",
    character_card_id: "card-saved-002",
    binding_id: CARD_OPTION.binding_id,
    character_identity: {
      name: "卡芙卡",
      avatar_ref: null,
      avatar_version: null,
      missing: false,
      source: "card",
    },
    ...overrides,
  };
}

/** 单项目快照，只替换会话列表与搭档目录。 */
function snapshotWith(
  conversations: ConversationRecord[],
  pairs: PairOption[],
): DesktopSnapshot {
  const base = createMockScenario("single-project").snapshot;
  const project = base.projects[0];
  return {
    ...base,
    projects: [{ ...project, conversations }],
    current_conversation_id: conversations[0]?.conversation_id ?? "",
    current_conversation: conversations[0] ?? base.current_conversation,
    pairs,
    catalog_version: 4,
  };
}

function hydrate(snapshot: DesktopSnapshot): void {
  desktopStore.setState(desktopStore.getInitialState(), true);
  desktopStore.getState().hydrate(snapshot);
}

function renderColumn(backend = new MockDesktopBackend()) {
  const controller = createActionController(backend);
  render(
    <ChatColumn
      navigation={presentAppShell(desktopStore.getState()).navigation!}
      theme="dark"
      actions={controller.actions}
      onCollapse={() => undefined}
    />,
  );
  return { backend };
}

function paramsOf(backend: MockDesktopBackend, method: string) {
  return backend.recordedRequests
    .filter((request) => request.method === method)
    .map((request) => request.params);
}

describe("ChatColumn 新建菜单与搭档芯片", () => {
  afterEach(() => {
    cleanup();
    desktopStore.setState(desktopStore.getInitialState(), true);
  });

  it("新建菜单按两段渲染：内置搭档在前，分隔项后接角色卡绑定项", async () => {
    hydrate(snapshotWith([cardConversation()], [...MOCK_PAIR_OPTIONS, CARD_OPTION]));
    renderColumn();

    fireEvent.click(screen.getByRole("button", { name: /新建聊天/ }));
    const menu = await screen.findByRole("menu", { name: "选择搭档新建聊天" });
    const items = within(menu).getAllByRole("menuitem");

    expect(items.map((item) => item.textContent)).toEqual([
      "白厄 × 神秘的古代机械",
      "流萤 × 萨姆",
      "三月七 × 第四面镜",
      "",
      "卡芙卡 × 神秘的古代机械",
    ]);
    // 分隔项不可点击，两段之间的角色卡项正常可选。
    expect(items[3]).toBeDisabled();
    expect(items[4]).not.toBeDisabled();
  });

  it("点击角色卡项以该卡的绑定 id 提交 conversation.create", async () => {
    hydrate(snapshotWith([cardConversation()], [...MOCK_PAIR_OPTIONS, CARD_OPTION]));
    const { backend } = renderColumn();

    fireEvent.click(screen.getByRole("button", { name: /新建聊天/ }));
    const menu = await screen.findByRole("menu", { name: "选择搭档新建聊天" });
    fireEvent.click(within(menu).getByRole("menuitem", { name: "卡芙卡 × 神秘的古代机械" }));

    expect(paramsOf(backend, "conversation.create")).toEqual([
      { project_id: "project-1", binding_id: CARD_OPTION.binding_id },
    ]);
    expect(paramsOf(backend, "conversation.create")[0]).not.toHaveProperty("pair_id");
  });

  it("会话行芯片在 character_identity 来自角色卡时显示卡名与助手名", () => {
    hydrate(snapshotWith([cardConversation()], [...MOCK_PAIR_OPTIONS, CARD_OPTION]));
    renderColumn();

    const chip = screen.getByTitle("卡芙卡 × 神秘的古代机械");
    expect(chip).toHaveTextContent("卡芙卡 × 神秘的古代机械");
  });

  it("角色卡已缺失时会话行芯片退回内置搭档渲染，也不请求卡头像", () => {
    // 卡已删除：目录里没有对应绑定项，身份标记 missing 且不带名字。
    hydrate(
      snapshotWith(
        [
          cardConversation({
            character_card_id: "card-deleted",
            binding_id: "card-bind-card-deleted",
            character_identity: {
              name: "",
              avatar_ref: null,
              avatar_version: null,
              missing: true,
              source: "card",
            },
          }),
        ],
        MOCK_PAIR_OPTIONS,
      ),
    );
    const { backend } = renderColumn();

    expect(screen.getByTitle("白厄 × 神秘的古代机械")).toHaveTextContent(
      "白厄 × 神秘的古代机械",
    );
    expect(paramsOf(backend, "card.avatar")).toEqual([]);
  });
});
