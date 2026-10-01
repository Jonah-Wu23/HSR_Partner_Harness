import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { DesktopCommand, MemoryWirePayload } from "../../../contracts/protocol";
import { createActionController } from "../../../services/actions";
import { DesktopRequestError } from "../../../services/backend";
import { desktopStore } from "../../../stores/desktopStore";
import { fakeBackend, unexpectedCommand } from "../../../test/fakeBackend";
import { MemoryPanel } from "../MemoryPanel";

afterEach(() => {
  cleanup();
  desktopStore.setState(desktopStore.getInitialState(), true);
});

/** 与 Sidecar memory.* 返回体同形的记忆载荷：五分量作用域扁平下发，按会话请求时带 conversation_id。 */
const wire = (overrides: Partial<MemoryWirePayload> = {}): MemoryWirePayload => ({
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
  ...overrides,
});

/**
 * 按 Sidecar 的 memory.* 语义回放：不带 status 的 list 只返回 active 记忆，create 新增一条，
 * update 改内容，delete 软删除为 status=deleted。其他命令直接失败。
 */
function memoryServer(initial: MemoryWirePayload[]) {
  let memories = [...initial];
  const find = (memoryId: unknown) => {
    const found = memories.find((memory) => memory.memory_id === memoryId);
    if (!found) throw new DesktopRequestError("memory_not_found", `'unknown memory_id: ${String(memoryId)}'`);
    return found;
  };
  const replace = (next: MemoryWirePayload) => {
    memories = memories.map((memory) => (memory.memory_id === next.memory_id ? next : memory));
    return { memory: next };
  };
  return (command: DesktopCommand): unknown => {
    const params = command.params;
    switch (command.method) {
      case "memory.list":
        return { memories: memories.filter((memory) => memory.status === (params.status ?? "active")) };
      case "memory.create": {
        const created = wire({ memory_id: `mem-${memories.length + 1}`, content: params.content as Record<string, unknown> });
        memories = [created, ...memories];
        return { memory: created };
      }
      case "memory.update":
        return replace({ ...find(params.memory_id), content: params.content as Record<string, unknown> });
      case "memory.delete":
        return replace({ ...find(params.memory_id), status: "deleted" });
      default:
        return unexpectedCommand(command);
    }
  };
}

/** 渲染记忆面板；openTab 时先打开 conv-1 标签。面板经真实 actions 发命令，respond 给出响应。 */
function renderPanel(respond: (command: DesktopCommand) => unknown, openTab = true) {
  if (openTab) desktopStore.getState().openConversationTab("conv-1");
  const { backend, commands } = fakeBackend(respond);
  const { actions } = createActionController(backend);
  render(<MemoryPanel actions={actions} />);
  return { actions, commands };
}

function paramsOf(commands: DesktopCommand[], method: string) {
  return commands.filter((command) => command.method === method).map((command) => command.params);
}

describe("MemoryPanel 长期记忆增删改", () => {
  it("挂载时读取当前聊天的记忆，展示服务端下发的五分量作用域与状态", async () => {
    const { commands } = renderPanel(memoryServer([wire()]));

    const scope = await screen.findByTestId("memory-scope-mem-1");
    expect(paramsOf(commands, "memory.list")).toEqual([{ conversation_id: "conv-1" }]);
    expect(scope).toHaveTextContent("acc-1");
    expect(scope).toHaveTextContent("project-1");
    expect(scope).toHaveTextContent("phainon_ancient_machine");
    expect(scope).toHaveTextContent("builtin:phainon");
    expect(scope).toHaveTextContent("ancient_machine");
    expect(screen.getByTestId("memory-status-mem-1")).toHaveTextContent("生效中");
  });

  it("读取返回前显示尚未读取，读取到零条后才说暂无记录", async () => {
    let answerList: (result: unknown) => void = () => undefined;
    renderPanel((command) =>
      command.method === "memory.list"
        ? new Promise((resolve) => {
            answerList = resolve;
          })
        : unexpectedCommand(command),
    );

    expect(screen.getByText("尚未读取。")).toBeInTheDocument();
    expect(screen.getByText("正在读取长期记忆…")).toBeInTheDocument();
    expect(screen.queryByTestId("memory-empty")).not.toBeInTheDocument();

    answerList({ memories: [] });
    expect(await screen.findByTestId("memory-empty")).toHaveTextContent("暂无记忆记录");
    expect(screen.queryByText("尚未读取。")).not.toBeInTheDocument();
  });

  it("读取失败时原样显示后端错误，重试后恢复列表", async () => {
    const server = memoryServer([wire()]);
    let listCalls = 0;
    const { actions } = renderPanel((command) => {
      // 挂载后的第二次读取失败，其余按正常响应。
      if (command.method === "memory.list" && ++listCalls === 2) {
        throw new DesktopRequestError("conversation_not_found", "会话不存在：conv-1");
      }
      return server(command);
    });
    await screen.findByTestId("memory-scope-mem-1");

    // 由测试发起这次失败的读取并接住它的拒绝，面板只从 store 读取失败状态。
    await act(async () => {
      await expect(actions.listMemories({ conversationId: "conv-1" })).rejects.toThrow("会话不存在：conv-1");
    });
    expect(screen.getByTestId("memory-list-error")).toHaveTextContent("会话不存在：conv-1");

    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    await waitFor(() => expect(screen.queryByTestId("memory-list-error")).not.toBeInTheDocument());
    expect(screen.getByTestId("memory-scope-mem-1")).toBeInTheDocument();
  });

  it("新增：内容不是 JSON 对象时禁用提交并显示解析错误", async () => {
    renderPanel(memoryServer([]));
    await screen.findByTestId("memory-empty");

    const submit = screen.getByTestId("memory-create-submit");
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByTestId("memory-create-content"), {
      target: { value: "[1,2]" },
    });
    expect(screen.getByTestId("memory-create-content-status")).toHaveTextContent(
      "记忆内容必须是 JSON 对象",
    );
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByTestId("memory-create-content"), {
      target: { value: "{ not json" },
    });
    expect(screen.getByTestId("memory-create-content-status")).toHaveTextContent(
      "内容不是合法 JSON",
    );
  });

  it("新增：提交合法 JSON 对象发 memory.create，清空输入并重新读取", async () => {
    const { commands } = renderPanel(memoryServer([]));
    await screen.findByTestId("memory-empty");

    const editor = screen.getByTestId("memory-create-content");
    fireEvent.change(editor, { target: { value: '{"text":"新的记忆"}' } });
    fireEvent.click(screen.getByTestId("memory-create-submit"));

    expect(await screen.findByTestId("memory-content-mem-1")).toHaveTextContent("新的记忆");
    expect(editor).toHaveValue("");
    expect(paramsOf(commands, "memory.create")).toEqual([
      { conversation_id: "conv-1", content: { text: "新的记忆" } },
    ]);
    expect(paramsOf(commands, "memory.list")).toHaveLength(2);
  });

  it("新增失败时就地显示后端错误原文并保留输入", async () => {
    const server = memoryServer([]);
    renderPanel((command) => {
      if (command.method === "memory.create") {
        throw new DesktopRequestError("memory_invalid", "日常聊天（无项目）不读写长期记忆");
      }
      return server(command);
    });
    await screen.findByTestId("memory-empty");

    const editor = screen.getByTestId("memory-create-content");
    fireEvent.change(editor, { target: { value: '{"text":"新的记忆"}' } });
    fireEvent.click(screen.getByTestId("memory-create-submit"));

    expect(await screen.findByTestId("memory-create-error")).toHaveTextContent(
      "日常聊天（无项目）不读写长期记忆",
    );
    expect(editor).toHaveValue('{"text":"新的记忆"}');
  });

  it("删除需二次确认，确认后发 memory.delete，重新读取后该条不再列出", async () => {
    const { commands } = renderPanel(memoryServer([wire()]));
    await screen.findByTestId("memory-scope-mem-1");

    fireEvent.click(screen.getByRole("button", { name: "删除" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent("确认删除这条记忆？");
    expect(paramsOf(commands, "memory.delete")).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "确认删除" }));

    expect(await screen.findByTestId("memory-empty")).toBeInTheDocument();
    expect(paramsOf(commands, "memory.delete")).toEqual([{ conversation_id: "conv-1", memory_id: "mem-1" }]);
    expect(paramsOf(commands, "memory.list")).toEqual([{ conversation_id: "conv-1" }, { conversation_id: "conv-1" }]);
  });

  it("编辑以当前内容为初值，保存发 memory.update 并显示新内容", async () => {
    const { commands } = renderPanel(memoryServer([wire()]));
    await screen.findByTestId("memory-scope-mem-1");

    fireEvent.click(screen.getByRole("button", { name: "编辑" }));
    const editor = screen.getByTestId("memory-edit-mem-1");
    expect(editor).toHaveValue(JSON.stringify({ text: "用户偏好夜间训练" }, null, 2));

    fireEvent.change(editor, { target: { value: '{"text":"改过的内容"}' } });
    fireEvent.click(screen.getByRole("button", { name: "保存修改" }));

    expect(await screen.findByTestId("memory-content-mem-1")).toHaveTextContent("改过的内容");
    expect(paramsOf(commands, "memory.update")).toEqual([
      { conversation_id: "conv-1", memory_id: "mem-1", content: { text: "改过的内容" } },
    ]);
  });

  it("修改失败时就地显示后端错误原文", async () => {
    const server = memoryServer([wire()]);
    renderPanel((command) => {
      if (command.method === "memory.update") {
        throw new DesktopRequestError("memory_not_found", "'memory_scope_mismatch: mem-1'");
      }
      return server(command);
    });
    await screen.findByTestId("memory-scope-mem-1");

    fireEvent.click(screen.getByRole("button", { name: "编辑" }));
    fireEvent.click(screen.getByRole("button", { name: "保存修改" }));

    expect(await screen.findByTestId("memory-write-error")).toHaveTextContent(
      "'memory_scope_mismatch: mem-1'",
    );
  });

  it("没有打开的聊天时如实说明，不发记忆命令", () => {
    const { commands } = renderPanel(unexpectedCommand, false);
    expect(screen.getByTestId("memory-panel")).toHaveTextContent("没有打开的聊天");
    expect(commands).toEqual([]);
  });
});
