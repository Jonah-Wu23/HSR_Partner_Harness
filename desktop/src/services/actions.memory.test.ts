import { beforeEach, describe, expect, it } from "vitest";

import type { DesktopCommand, MemoryWirePayload } from "../contracts/protocol";
import { createMockScenario } from "../mocks/scenarios";
import { desktopStore } from "../stores/desktopStore";
import { fakeBackend } from "../test/fakeBackend";
import { DesktopRequestError } from "./backend";
import { createActionController } from "./actions";

/** 服务端 _memory_payload 的真实形状：扁平五分量，按会话下发时带 conversation_id。 */
const wireMemory: MemoryWirePayload = {
  memory_id: "mem-1",
  account_id: "acc-1",
  project_id: "project-1",
  pair_id: "phainon_ancient_machine",
  character_ref: "builtin:phainon",
  assistant_identity: "ancient_machine",
  status: "active",
  updated_at: "2026-09-10T10:00:00Z",
  content: { text: "用户偏好夜间训练" },
  conversation_id: "conv-1",
};

const sent = (commands: DesktopCommand[]) =>
  commands.map(({ method, params }) => ({ method, params }));

describe("长期记忆命令（memory.*）", () => {
  beforeEach(() => {
    desktopStore.setState(desktopStore.getInitialState(), true);
    desktopStore.getState().hydrate(createMockScenario("single-project").snapshot);
  });

  it("listMemories 按会话下发并在解码扁平载荷后写入 store", async () => {
    const { backend, commands } = fakeBackend(() => ({ memories: [wireMemory] }));
    const { actions } = createActionController(backend);

    const memories = await actions.listMemories();

    expect(sent(commands)).toEqual([
      { method: "memory.list", params: { conversation_id: "conv-1" } },
    ]);
    expect(memories).toHaveLength(1);
    // 扁平五分量解码为嵌套作用域（上下文状态条按 scope 读取）
    expect(memories[0].scope).toEqual({
      account_id: "acc-1",
      project_id: "project-1",
      pair_id: "phainon_ancient_machine",
      character_ref: "builtin:phainon",
      assistant_identity: "ancient_machine",
    });
    const state = desktopStore.getState();
    expect(state.memories).toEqual(memories);
    expect(state.memoriesByConversation["conv-1"]).toEqual(memories);
    expect(state.memoryPanel).toEqual({
      conversationId: "conv-1",
      loading: false,
      error: null,
      loaded: true,
    });
  });

  it("listMemories 失败时如实记录原文并继续抛错，不合成空成功", async () => {
    const { backend } = fakeBackend(() => {
      throw new DesktopRequestError("memory_scope_mismatch", "记忆作用域与会话不一致");
    });
    const { actions } = createActionController(backend);

    await expect(actions.listMemories()).rejects.toMatchObject({ code: "memory_scope_mismatch" });
    expect(desktopStore.getState().memoryPanel).toEqual({
      conversationId: "conv-1",
      loading: false,
      error: "记忆作用域与会话不一致",
      loaded: true,
    });
  });

  it("createMemory 只下发 conversation_id 与内容，作用域交由服务端解析", async () => {
    const { backend, commands } = fakeBackend(() => ({ memory: wireMemory }));
    const { actions } = createActionController(backend);

    const created = await actions.createMemory({ text: "用户偏好夜间训练" });

    expect(sent(commands)).toEqual([
      {
        method: "memory.create",
        params: { conversation_id: "conv-1", content: { text: "用户偏好夜间训练" } },
      },
    ]);
    expect(created.scope.assistant_identity).toBe("ancient_machine");
    expect(desktopStore.getState().memoriesByConversation["conv-1"]).toHaveLength(1);
  });

  it("updateMemory / deleteMemory 下发 memory_id 并落库服务端返回的记录", async () => {
    const { backend, commands } = fakeBackend((command) => ({
      memory: {
        ...wireMemory,
        content: { text: "改过的内容" },
        status: command.method === "memory.delete" ? "deleted" : "active",
      },
    }));
    const { actions } = createActionController(backend);

    await actions.updateMemory("mem-1", { text: "改过的内容" });
    expect(desktopStore.getState().memories[0]?.content).toEqual({ text: "改过的内容" });

    const deleted = await actions.deleteMemory("mem-1");
    expect(sent(commands)).toEqual([
      {
        method: "memory.update",
        params: { conversation_id: "conv-1", memory_id: "mem-1", content: { text: "改过的内容" } },
      },
      { method: "memory.delete", params: { conversation_id: "conv-1", memory_id: "mem-1" } },
    ]);
    expect(deleted.status).toBe("deleted");
    expect(desktopStore.getState().memories[0]?.status).toBe("deleted");
  });

  it("没有聊天上下文时不发送请求，如实失败", async () => {
    const { backend, commands } = fakeBackend(() => ({ memory: wireMemory }));
    const { actions } = createActionController(backend);
    desktopStore.getState().closeConversationTab("conv-1");

    await expect(actions.createMemory({ text: "无会话" })).rejects.toThrow(
      "没有当前聊天，无法解析长期记忆作用域",
    );
    expect(commands).toHaveLength(0);
  });
});
