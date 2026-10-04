import { beforeEach, describe, expect, it } from "vitest";

import type { DesktopCommand, PairOption } from "../contracts/protocol";
import { MOCK_PAIR_OPTIONS, createMockScenario } from "../mocks/scenarios";
import { desktopStore } from "../stores/desktopStore";
import { fakeBackend, unexpectedCommand } from "../test/fakeBackend";
import { createActionController } from "./actions";

function paramsOf(commands: readonly DesktopCommand[], method: string): Record<string, unknown>[] {
  return commands.filter((command) => command.method === method).map((command) => command.params);
}

/** 配对目录里的卡绑定项（与 mock 后端的绑定 id 同形）。 */
const CARD_BINDING_ID = "card-bind-card-saved-002";
const CARD_OPTION: PairOption = {
  binding_id: CARD_BINDING_ID,
  pair_id: MOCK_PAIR_OPTIONS[0].pair_id,
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

/** 多项目窗口：本窗口标签停在项目 2 的聊天，Sidecar 全局当前项目仍是项目 1。 */
function hydrateWindowOnOtherProject(includeCard: boolean) {
  const snapshot = createMockScenario("many-projects").snapshot;
  desktopStore
    .getState()
    .hydrate({ ...snapshot, pairs: includeCard ? [...snapshot.pairs, CARD_OPTION] : snapshot.pairs });
  desktopStore.getState().openConversationTab("project-2-conversation-1");
}

/** 角色卡入口附带的下游请求（select_active 与角色库刷新），与用例无关，按协议形状回应。 */
function respondToCardSideEffects(command: DesktopCommand): unknown {
  if (command.method === "card.select_active") return { card_id: "card-saved-002" };
  if (command.method === "card.list") return { cards: [] };
  return unexpectedCommand(command);
}

beforeEach(() => {
  desktopStore.setState(desktopStore.getInitialState(), true);
  desktopStore.getState().hydrate(createMockScenario("single-project").snapshot);
});

describe("createConversation 的绑定参数", () => {
  it("下发 binding_id 与 reuse_active，不再下发 pair_id", async () => {
    const { backend, commands } = fakeBackend((command) =>
      command.method === "conversation.create"
        ? createMockScenario("single-project").snapshot
        : unexpectedCommand(command),
    );
    const { actions } = createActionController(backend);

    await actions.createConversation("project-1", "新聊天", "builtin:firefly_sam", {
      reuseActive: true,
    });

    expect(paramsOf(commands, "conversation.create")).toEqual([
      {
        project_id: "project-1",
        title: "新聊天",
        binding_id: "builtin:firefly_sam",
        reuse_active: true,
      },
    ]);
    expect(paramsOf(commands, "conversation.create")[0]).not.toHaveProperty("pair_id");
  });
});

describe("startConversationWithCard 的目录查找", () => {
  it("目录里找不到该卡的绑定项时如实报错，不发会话创建与角色切换请求", async () => {
    const { backend, commands } = fakeBackend((command) =>
      command.method === "pair.list" ? { pairs: [], catalog_version: 3 } : unexpectedCommand(command),
    );
    const { actions } = createActionController(backend);

    await expect(actions.startConversationWithCard("card-draft-001")).rejects.toThrow(
      "该角色卡当前不在可选搭档目录中（草稿、已归档或绑定尚未生效），无法开始对话",
    );

    // 本地目录里没有该卡时按权威目录再确认一次，确认后仍失败。
    expect(paramsOf(commands, "pair.list")).toEqual([{}]);
    expect(paramsOf(commands, "conversation.create")).toEqual([]);
    expect(paramsOf(commands, "card.select_active")).toEqual([]);
  });
});

describe("startConversationWithCard 的项目上下文", () => {
  it("新会话建在本窗口标签所属项目，即便后端全局停在别的项目", async () => {
    const { backend, commands } = fakeBackend((command) =>
      command.method === "conversation.create"
        ? createMockScenario("many-projects").snapshot
        : respondToCardSideEffects(command),
    );
    const { actions } = createActionController(backend);
    hydrateWindowOnOtherProject(true);
    expect(desktopStore.getState().activeConversationId).toBe("project-2-conversation-1");
    expect(desktopStore.getState().currentProjectId).toBe("project-1");

    await actions.startConversationWithCard("card-saved-002");

    expect(paramsOf(commands, "conversation.create")).toEqual([
      { project_id: "project-2", binding_id: CARD_BINDING_ID, reuse_active: true },
    ]);
  });

  it("目录重取期间后端全局项目漂移，仍用捕获时的窗口项目", async () => {
    const { backend, commands } = fakeBackend((command) => {
      if (command.method === "pair.list") {
        // 目录请求在途时另一个窗口把后端全局切到项目 3。
        desktopStore.setState({ currentProjectId: "project-3" });
        return { pairs: [...MOCK_PAIR_OPTIONS, CARD_OPTION], catalog_version: 99 };
      }
      if (command.method === "conversation.create")
        return createMockScenario("many-projects").snapshot;
      return respondToCardSideEffects(command);
    });
    const { actions } = createActionController(backend);
    hydrateWindowOnOtherProject(false);

    await actions.startConversationWithCard("card-saved-002");

    expect(paramsOf(commands, "pair.list")).toHaveLength(1);
    expect(paramsOf(commands, "conversation.create")).toEqual([
      { project_id: "project-2", binding_id: CARD_BINDING_ID, reuse_active: true },
    ]);
  });

  it("窗口没有打开任何聊天时退回导航态当前项目", async () => {
    const { backend, commands } = fakeBackend((command) =>
      command.method === "conversation.create"
        ? createMockScenario("many-projects").snapshot
        : respondToCardSideEffects(command),
    );
    const { actions } = createActionController(backend);
    hydrateWindowOnOtherProject(true);
    // 关掉本窗口所有标签：没有会话可归属，回退到导航态的当前项目。
    desktopStore.getState().closeConversationTab("project-2-conversation-1");
    desktopStore.getState().closeConversationTab("project-1-conversation-1");
    expect(desktopStore.getState().activeConversationId).toBeNull();

    await actions.startConversationWithCard("card-saved-002");

    expect(paramsOf(commands, "conversation.create")).toEqual([
      { project_id: "project-1", binding_id: CARD_BINDING_ID, reuse_active: true },
    ]);
  });

  it("本窗口没有会话也没有当前项目时如实报错，不发任何请求", async () => {
    const { backend, commands } = fakeBackend((command) => unexpectedCommand(command));
    const { actions } = createActionController(backend);
    // 清掉本窗口的会话与导航态项目：既没有会话所属项目，也没有可回退的当前项目。
    desktopStore.setState({
      currentProjectId: "",
      activeConversationId: null,
      activeProjectId: null,
      openConversationIds: [],
    });

    await expect(actions.startConversationWithCard("card-saved-002")).rejects.toThrow(
      "当前窗口没有项目上下文，无法开始对话",
    );

    expect(commands).toEqual([]);
  });
});

describe("fetchCardAvatar 缓存", () => {
  it("缓存键包含 avatarVersion：同版本命中缓存，版本变化后重新请求", async () => {
    let calls = 0;
    const { backend, commands } = fakeBackend((command) => {
      if (command.method !== "card.avatar") return unexpectedCommand(command);
      calls += 1;
      return { avatar: { mime_type: "image/png", data_base64: `data-${calls}` } };
    });
    const { actions } = createActionController(backend);

    const first = await actions.fetchCardAvatar("card-avatar-cache-1", "v1");
    expect(first).toBe("data:image/png;base64,data-1");
    expect(await actions.fetchCardAvatar("card-avatar-cache-1", "v1")).toBe(first);
    expect(paramsOf(commands, "card.avatar")).toHaveLength(1);

    // 头像版本推进后旧条目不再命中，重新请求同一张卡。
    const bumped = await actions.fetchCardAvatar("card-avatar-cache-1", "v2");
    expect(bumped).toBe("data:image/png;base64,data-2");
    expect(paramsOf(commands, "card.avatar")).toEqual([
      { card_id: "card-avatar-cache-1" },
      { card_id: "card-avatar-cache-1" },
    ]);
  });
});
