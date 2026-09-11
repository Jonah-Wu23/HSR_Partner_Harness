import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { HarnessActions } from "../../../contracts/actions";
import { pairMemoryFromPayload, type MemoryWirePayload, type PairMemory } from "../../../contracts/protocol";
import { desktopStore, type MemoryPanelState } from "../../../stores/desktopStore";
import { MemoryPanel } from "../MemoryPanel";

afterEach(cleanup);

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
  ...overrides,
});

function record(overrides: Partial<MemoryWirePayload> = {}): PairMemory {
  return pairMemoryFromPayload(wire(overrides));
}

function seedStore(options: {
  conversationId?: string | null;
  memories?: PairMemory[];
  panel?: Partial<MemoryPanelState>;
} = {}) {
  const conversationId =
    options.conversationId === undefined ? "conv-1" : options.conversationId;
  const memories = options.memories ?? [];
  desktopStore.setState({
    activeConversationId: conversationId,
    memories,
    memoriesByConversation: conversationId ? { [conversationId]: memories } : {},
    memoryPanel: {
      conversationId: null,
      loading: false,
      error: null,
      loaded: false,
      ...options.panel,
    },
  });
}

function memoryActions(overrides: Partial<HarnessActions> = {}): HarnessActions {
  return {
    listMemories: vi.fn().mockResolvedValue([]),
    createMemory: vi.fn().mockResolvedValue(record()),
    updateMemory: vi.fn().mockResolvedValue(record()),
    deleteMemory: vi.fn().mockResolvedValue(record({ status: "deleted" })),
    ...overrides,
  } as unknown as HarnessActions;
}

describe("MemoryPanel（V039-S4-003 长期记忆增删改入口）", () => {
  beforeEach(() => {
    seedStore();
  });

  it("按服务端下发的五分量作用域展示记录，并在挂载时读取当前聊天", async () => {
    const actions = memoryActions();
    seedStore({
      memories: [
        record(),
        record({ memory_id: "mem-2", status: "deleted", content: { text: "旧记录" } }),
      ],
      panel: { loaded: true, conversationId: "conv-1" },
    });

    render(<MemoryPanel actions={actions} />);

    await waitFor(() =>
      expect(actions.listMemories).toHaveBeenCalledWith({ conversationId: "conv-1" }),
    );
    const scope = screen.getByTestId("memory-scope-mem-1");
    expect(scope).toHaveTextContent("acc-1");
    expect(scope).toHaveTextContent("project-1");
    expect(scope).toHaveTextContent("phainon_ancient_machine");
    expect(scope).toHaveTextContent("builtin:phainon");
    expect(scope).toHaveTextContent("ancient_machine");
    expect(screen.getByTestId("memory-status-mem-1")).toHaveTextContent("生效中");
    expect(screen.getByTestId("memory-status-mem-2")).toHaveTextContent("已删除");
    // 已删除的记录不再提供删除按钮
    expect(screen.getAllByRole("button", { name: "删除" })).toHaveLength(1);
  });

  it("读取完成后真实零条与尚未读取分开呈现，不把未读取说成 0 条", () => {
    render(<MemoryPanel actions={memoryActions()} />);
    expect(screen.getByText("尚未读取。")).toBeInTheDocument();
    expect(screen.queryByTestId("memory-empty")).not.toBeInTheDocument();

    seedStore({ panel: { loaded: true, conversationId: "conv-1" } });
    cleanup();
    render(<MemoryPanel actions={memoryActions()} />);
    expect(screen.getByTestId("memory-empty")).toHaveTextContent("暂无记忆记录");
  });

  it("读取失败时原样显示后端错误，并可重试", async () => {
    const listMemories = vi.fn().mockRejectedValue(new Error("memory_scope_mismatch"));
    seedStore({ panel: { loaded: true, conversationId: "conv-1", error: "memory_scope_mismatch" } });

    render(<MemoryPanel actions={memoryActions({ listMemories })} />);

    expect(screen.getByTestId("memory-list-error")).toHaveTextContent("memory_scope_mismatch");
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    await waitFor(() => expect(listMemories).toHaveBeenCalledTimes(2));
  });

  it("新增：内容不是 JSON 对象时禁用提交并显示真实解析错误", () => {
    render(<MemoryPanel actions={memoryActions()} />);

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

  it("新增：提交合法 JSON 对象调用 memory.create 并清空输入", async () => {
    const createMemory = vi.fn().mockResolvedValue(record());
    render(<MemoryPanel actions={memoryActions({ createMemory })} />);

    const editor = screen.getByTestId("memory-create-content");
    fireEvent.change(editor, { target: { value: '{"text":"新的记忆"}' } });
    fireEvent.click(screen.getByTestId("memory-create-submit"));

    await waitFor(() =>
      expect(createMemory).toHaveBeenCalledWith(
        { text: "新的记忆" },
        { conversationId: "conv-1" },
      ),
    );
    await waitFor(() => expect(editor).toHaveValue(""));
  });

  it("新增失败时上屏后端真实错误（如 memory.create 未实现）", async () => {
    const createMemory = vi
      .fn()
      .mockRejectedValue(new Error("未知桌面命令：memory.create"));
    render(<MemoryPanel actions={memoryActions({ createMemory })} />);

    fireEvent.change(screen.getByTestId("memory-create-content"), {
      target: { value: '{"text":"新的记忆"}' },
    });
    fireEvent.click(screen.getByTestId("memory-create-submit"));

    await waitFor(() =>
      expect(screen.getByTestId("memory-create-error")).toHaveTextContent(
        "未知桌面命令：memory.create",
      ),
    );
  });

  it("删除需二次确认，确认后调用 memory.delete 并重新读取", async () => {
    const deleteMemory = vi.fn().mockResolvedValue(record({ status: "deleted" }));
    const listMemories = vi.fn().mockResolvedValue([]);
    seedStore({
      memories: [record()],
      panel: { loaded: true, conversationId: "conv-1" },
    });

    render(<MemoryPanel actions={memoryActions({ deleteMemory, listMemories })} />);

    fireEvent.click(screen.getByRole("button", { name: "删除" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent("确认删除这条记忆？");
    fireEvent.click(screen.getByRole("button", { name: "确认删除" }));

    await waitFor(() =>
      expect(deleteMemory).toHaveBeenCalledWith("mem-1", { conversationId: "conv-1" }),
    );
    await waitFor(() => expect(listMemories).toHaveBeenCalledTimes(2));
  });

  it("编辑保存调用 memory.update 并带修改后的内容", async () => {
    const updateMemory = vi.fn().mockResolvedValue(record());
    seedStore({
      memories: [record()],
      panel: { loaded: true, conversationId: "conv-1" },
    });

    render(<MemoryPanel actions={memoryActions({ updateMemory })} />);

    fireEvent.click(screen.getByRole("button", { name: "编辑" }));
    const editor = screen.getByTestId("memory-edit-mem-1");
    expect(editor).toHaveValue(JSON.stringify({ text: "用户偏好夜间训练" }, null, 2));

    fireEvent.change(editor, { target: { value: '{"text":"改过的内容"}' } });
    fireEvent.click(screen.getByRole("button", { name: "保存修改" }));

    await waitFor(() =>
      expect(updateMemory).toHaveBeenCalledWith(
        "mem-1",
        { text: "改过的内容" },
        { conversationId: "conv-1" },
      ),
    );
  });

  it("修改失败时的真实错误上屏", async () => {
    const updateMemory = vi.fn().mockRejectedValue(new Error("记忆不存在：mem-1"));
    seedStore({
      memories: [record()],
      panel: { loaded: true, conversationId: "conv-1" },
    });

    render(<MemoryPanel actions={memoryActions({ updateMemory })} />);

    fireEvent.click(screen.getByRole("button", { name: "编辑" }));
    fireEvent.click(screen.getByRole("button", { name: "保存修改" }));

    await waitFor(() =>
      expect(screen.getByTestId("memory-write-error")).toHaveTextContent("记忆不存在：mem-1"),
    );
  });

  it("未接入记忆命令与没有打开的聊天分别如实说明", () => {
    render(<MemoryPanel />);
    expect(screen.getByTestId("memory-panel")).toHaveTextContent("未接入记忆命令");

    cleanup();
    seedStore({ conversationId: null });
    render(<MemoryPanel actions={memoryActions()} />);
    expect(screen.getByTestId("memory-panel")).toHaveTextContent("没有打开的聊天");
  });
});
