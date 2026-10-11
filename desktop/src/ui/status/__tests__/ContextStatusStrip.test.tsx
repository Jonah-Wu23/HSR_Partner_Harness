import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ConversationSummary, PairMemory } from "../../../contracts/protocol";
import type { SummaryRegenerateTarget } from "../../../contracts/view-models";
import { ContextStatusStrip } from "../ContextStatusStrip";

afterEach(cleanup);

function summaryRecord(overrides: Partial<ConversationSummary> = {}): ConversationSummary {
  return {
    summary_id: "s1",
    conversation_id: "c1",
    status: "running",
    covers_from_message_id: "m1",
    covers_to_message_id: "m80",
    covers_message_count: 80,
    content: null,
    provider: "deepseek",
    model: "deepseek-v4-flash",
    error_code: null,
    error: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:10Z",
    ...overrides,
  };
}

function memoryRecord(overrides: Partial<PairMemory> = {}): PairMemory {
  return {
    memory_id: "mem1",
    scope: {
      account_id: "acct-1",
      project_id: "proj-1",
      pair_id: "pair-1",
      character_ref: "card:card-1",
      assistant_identity: "ancient-machine",
    },
    content: { note: "用户喜欢先看结论" },
    status: "active",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

const failedSummary = summaryRecord({
  status: "failed",
  error_code: "summary_timeout",
  error: "provider timeout",
});

describe("ContextStatusStrip", () => {
  it("无摘要也无记忆数据时不渲染", () => {
    const { container } = render(<ContextStatusStrip summaries={null} memories={null} />);
    expect(container.firstChild).toBeNull();
  });

  it("idle 摘要不渲染，running 摘要显示状态", () => {
    render(
      <ContextStatusStrip
        summaries={[summaryRecord({ summary_id: "idle-1", status: "idle" }), summaryRecord()]}
      />,
    );

    expect(screen.getByTestId("context-status-strip")).toBeInTheDocument();
    expect(screen.getByTestId("context-strip-status-s1")).toHaveTextContent("正在压缩上下文…");
    expect(screen.queryByTestId("context-strip-summary-idle-1")).not.toBeInTheDocument();
  });

  it("压缩失败行可展开与收起 error_code 和原始 error", () => {
    render(<ContextStatusStrip summaries={[failedSummary]} />);

    expect(screen.getByTestId("context-strip-status-s1")).toHaveTextContent("压缩失败");
    expect(screen.queryByTestId("context-strip-error-s1")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("context-strip-expand-s1"));
    const errorBox = screen.getByTestId("context-strip-error-s1");
    expect(errorBox).toHaveTextContent("summary_timeout");
    expect(errorBox).toHaveTextContent("provider timeout");

    fireEvent.click(screen.getByTestId("context-strip-expand-s1"));
    expect(screen.queryByTestId("context-strip-error-s1")).not.toBeInTheDocument();
  });

  it.each([
    ["失败摘要没有重新生成目标", failedSummary, null],
    ["已完成摘要即使有重新生成目标", summaryRecord({ status: "completed" }), { summary_id: "s1", conversation_id: "c1" }],
  ])("%s时不显示重新生成按钮", (_name, summary, regenerate) => {
    render(
      <ContextStatusStrip summaries={[summary]} regenerate={regenerate} onRegenerate={() => {}} />,
    );
    expect(screen.queryByRole("button", { name: "重新生成摘要" })).not.toBeInTheDocument();
  });

  it("失败摘要有重新生成目标时显示按钮，请求失败原文显示为告警", async () => {
    const target: SummaryRegenerateTarget = {
      summary_id: "s1",
      conversation_id: "c1",
    };
    const onRegenerate = vi
      .fn()
      .mockRejectedValue(new Error("summary_provider_error: provider 返回 500"));
    render(
      <ContextStatusStrip
        summaries={[failedSummary]}
        regenerate={target}
        onRegenerate={onRegenerate}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "重新生成摘要" }));
    expect(onRegenerate).toHaveBeenCalledWith(target);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "重新生成失败：summary_provider_error: provider 返回 500",
    );
  });

  it("记忆空数组是真实零条，显示 0 条生效", () => {
    render(<ContextStatusStrip summaries={null} memories={[]} />);
    expect(screen.getByTestId("context-strip-memory-count")).toHaveTextContent("0 条生效");
  });

  it("记忆行展示服务端下发的作用域五个分量与配对共享说明", () => {
    render(<ContextStatusStrip summaries={null} memories={[memoryRecord()]} />);
    const scope = screen.getByTestId("context-strip-memory-scope");
    for (const part of ["acct-1", "proj-1", "pair-1", "card:card-1", "ancient-machine"]) {
      expect(scope).toHaveTextContent(part);
    }
    // 作用域分量是运行配置 id，标签不写成「搭档」，避免读成角色名
    expect(scope).toHaveTextContent("配对配置");
    expect(scope).not.toHaveTextContent("搭档");
    expect(screen.getByTestId("context-strip-memory-scope-pair")).toHaveTextContent("pair-1");
    const memoryRow = screen.getByTestId("context-strip-memory");
    expect(memoryRow).toHaveTextContent("配对共享");
    expect(memoryRow).toHaveTextContent("作用域由服务端解析，客户端只传 conversation_id");
  });

  it("角色与助手身份显示可读名，服务端原始 id 留在 title", () => {
    render(
      <ContextStatusStrip
        summaries={null}
        memories={[memoryRecord()]}
        characterName="白厄"
        assistantName="神秘的古代机械"
      />,
    );
    const character = screen.getByTestId("context-strip-memory-scope-character");
    expect(character).toHaveTextContent("白厄");
    expect(character).toHaveAttribute("title", "card:card-1");
    const assistant = screen.getByTestId("context-strip-memory-scope-assistant");
    expect(assistant).toHaveTextContent("神秘的古代机械");
    expect(assistant).toHaveAttribute("title", "ancient-machine");
    // 配对配置是真实作用域分量，保持原始 id
    expect(screen.getByTestId("context-strip-memory-scope-pair")).toHaveTextContent("pair-1");
  });

  it.each([
    ["角色身份缺失", { characterName: null, assistantName: "神秘的古代机械" }, "card:card-1", "神秘的古代机械"],
    ["助手名未解析", { characterName: "白厄", assistantName: null }, "白厄", "ancient-machine"],
    ["名字是空白", { characterName: "  ", assistantName: "" }, "card:card-1", "ancient-machine"],
  ])("%s时回退服务端原始 id", (_name, names, characterText, assistantText) => {
    render(<ContextStatusStrip summaries={null} memories={[memoryRecord()]} {...names} />);
    expect(screen.getByTestId("context-strip-memory-scope-character")).toHaveTextContent(characterText);
    expect(screen.getByTestId("context-strip-memory-scope-assistant")).toHaveTextContent(assistantText);
  });

  it.each([
    [
      "部分记忆已删除",
      [memoryRecord(), memoryRecord({ memory_id: "mem2", status: "deleted" })],
      "1 条生效 · 共 2 条记录（含已删除）",
    ],
    ["全部记忆已删除", [memoryRecord({ status: "deleted" })], "0 条生效 · 共 1 条记录（含已删除）"],
  ])("%s：已删除记忆不计入生效条数，记录总数与作用域照常展示", (_name, memories, countText) => {
    render(<ContextStatusStrip summaries={null} memories={memories} />);
    expect(screen.getByTestId("context-strip-memory-count")).toHaveTextContent(countText);
    expect(screen.getByTestId("context-strip-memory-scope")).toHaveTextContent("card:card-1");
  });

  it("日常聊天（无项目）说明不读写长期记忆", () => {
    render(<ContextStatusStrip summaries={null} memories={null} projectId={null} />);
    expect(screen.getByTestId("context-strip-memory-disabled")).toHaveTextContent(
      "日常聊天（无项目）不读写长期记忆",
    );
  });

  it("摘要覆盖条数带消息范围提示", () => {
    render(
      <ContextStatusStrip
        summaries={[
          summaryRecord({
            covers_from_message_id: "msg-start",
            covers_to_message_id: "msg-end",
            covers_message_count: 80,
          }),
        ]}
      />,
    );
    const valueEl = screen.getByText(/已覆盖 80 条/);
    expect(valueEl).toHaveAttribute("title", "覆盖范围：msg-start 至 msg-end");
  });
});
