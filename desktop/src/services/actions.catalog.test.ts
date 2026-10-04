import { beforeEach, describe, expect, it } from "vitest";

import type { DesktopCommand } from "../contracts/protocol";
import { createMockScenario } from "../mocks/scenarios";
import { desktopStore } from "../stores/desktopStore";
import { fakeBackend, unexpectedCommand } from "../test/fakeBackend";
import { createActionController } from "./actions";

function paramsOf(commands: readonly DesktopCommand[], method: string): Record<string, unknown>[] {
  return commands.filter((command) => command.method === method).map((command) => command.params);
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
