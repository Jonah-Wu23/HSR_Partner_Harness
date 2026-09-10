import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DesktopCommand, DesktopEvent } from "../contracts/protocol";
import { createMockScenario } from "../mocks/scenarios";
import { desktopStore } from "../stores/desktopStore";
import type { DesktopBackend } from "./backend";
import { createActionController } from "./actions";

/** 只实现 request 的假后端：记录下发的命令，按用例给定的应答返回。 */
function fakeBackend(
  respond: (command: DesktopCommand) => unknown,
): { backend: DesktopBackend; commands: DesktopCommand[] } {
  const commands: DesktopCommand[] = [];
  const backend = {
    async request<T>(command: DesktopCommand): Promise<T> {
      commands.push(command);
      return respond(command) as T;
    },
    openChatWindow: vi.fn(),
    pickFolder: vi.fn(),
    pickFile: vi.fn(),
    saveFile: vi.fn(),
    subscribe: (_listener: (event: DesktopEvent) => void) => () => {},
    reconnectSidecar: vi.fn(),
  } as unknown as DesktopBackend;
  return { backend, commands };
}

/** 服务端 _memory_payload 的真实形状：扁平五分量，无嵌套 scope。 */
const wireMemory = {
  memory_id: "mem-1",
  account_id: "acc-1",
  project_id: "project-1",
  pair_id: "phainon_ancient_machine",
  character_ref: "builtin:phainon",
  assistant_identity: "ancient_machine",
  status: "active" as const,
  updated_at: "2026-09-10T10:00:00Z",
  content: { text: "用户偏好夜间训练" },
};

describe("长期记忆命令（memory.*）", () => {
  beforeEach(() => {
    desktopStore.setState({
      memories: [],
      memoriesByConversation: {},
      memoryPanel: { conversationId: null, loading: false, error: null, loaded: false },
    });
    desktopStore.getState().hydrate(createMockScenario("single-project").snapshot);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("listMemories 按会话下发并在解码扁平载荷后写入 store", async () => {
    const { backend, commands } = fakeBackend(() => ({ memories: [wireMemory] }));
    const { actions } = createActionController(backend);

    const memories = await actions.listMemories?.();

    expect(commands[0]?.method).toBe("memory.list");
    expect(commands[0]?.params).toEqual({ conversation_id: "conv-1" });
    expect(memories).toHaveLength(1);
    // 扁平五分量 → 嵌套作用域（上下文状态条按 scope 读取）
    expect(memories?.[0]?.scope).toEqual({
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
      throw new Error("记忆读取失败：memory_scope_mismatch");
    });
    const { actions } = createActionController(backend);

    await expect(actions.listMemories?.()).rejects.toThrow("memory_scope_mismatch");
    const panel = desktopStore.getState().memoryPanel;
    expect(panel.loading).toBe(false);
    expect(panel.error).toBe("记忆读取失败：memory_scope_mismatch");
    expect(panel.loaded).toBe(true);
  });

  it("createMemory 只下发 conversation_id 与内容，作用域交由服务端解析", async () => {
    const { backend, commands } = fakeBackend(() => ({ memory: wireMemory }));
    const { actions } = createActionController(backend);

    const created = await actions.createMemory?.({ text: "用户偏好夜间训练" });

    expect(commands[0]?.method).toBe("memory.create");
    expect(commands[0]?.params).toEqual({
      conversation_id: "conv-1",
      content: { text: "用户偏好夜间训练" },
    });
    expect(created?.scope.assistant_identity).toBe("ancient_machine");
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

    await actions.updateMemory?.("mem-1", { text: "改过的内容" });
    expect(commands[0]?.method).toBe("memory.update");
    expect(commands[0]?.params).toEqual({
      conversation_id: "conv-1",
      memory_id: "mem-1",
      content: { text: "改过的内容" },
    });
    expect(desktopStore.getState().memories[0]?.content).toEqual({ text: "改过的内容" });

    const deleted = await actions.deleteMemory?.("mem-1");
    expect(commands[1]?.method).toBe("memory.delete");
    expect(commands[1]?.params).toEqual({ conversation_id: "conv-1", memory_id: "mem-1" });
    expect(deleted?.status).toBe("deleted");
    expect(desktopStore.getState().memories[0]?.status).toBe("deleted");
  });

  it("没有聊天上下文时不发送请求，如实失败", async () => {
    const { backend, commands } = fakeBackend(() => ({ memory: wireMemory }));
    const { actions } = createActionController(backend);
    desktopStore.setState({ activeConversationId: null });
    desktopStore.getState().setMemoriesForConversation("conv-1", []);

    await expect(actions.createMemory?.({ text: "无会话" })).rejects.toThrow(
      "没有当前聊天，无法解析长期记忆作用域",
    );
    expect(commands).toHaveLength(0);
  });
});
