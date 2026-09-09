import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ConversationSummary, PairMemory } from "@shared/contracts/protocol";
import { ContextStatusStrip } from "./ContextStatusStrip";

afterEach(cleanup);

function summary(overrides: Partial<ConversationSummary> = {}): ConversationSummary {
  return {
    summary_id: "s1",
    conversation_id: "c1",
    status: "running",
    covers_from_message_id: "m1",
    covers_to_message_id: "m80",
    covers_message_count: 80,
    content: null,
    provider: "deepseek",
    model: "deepseek-v4.1-flash",
    error_code: null,
    error: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:10Z",
    ...overrides,
  };
}

function memory(id: string, status: PairMemory["status"]): PairMemory {
  return {
    memory_id: id,
    scope: {
      account_id: "acc-1",
      project_id: "p1",
      pair_id: "pair-1",
      character_ref: "builtin:phainon",
      assistant_identity: "fourth_mirror",
    },
    content: { text: "记住用户偏好" },
    status,
    updated_at: "2026-01-01T00:00:00Z",
  };
}

describe("ContextStatusStrip（V0.3.9 V02 移动压缩 / 记忆非消息状态条）", () => {
  it("无数据（null）时不渲染状态条，不显示伪造零指标", () => {
    render(<ContextStatusStrip summary={null} memories={null} />);
    expect(screen.queryByTestId("context-status-strip")).toBeNull();
    expect(screen.queryByTestId("memory-status-row")).toBeNull();
  });

  it("缺省 props 等同于无数据，整体不渲染", () => {
    render(<ContextStatusStrip />);
    expect(screen.queryByTestId("context-status-strip")).toBeNull();
  });

  it("压缩中：展示进行态文案与已覆盖条数", () => {
    render(<ContextStatusStrip summary={summary({ status: "running" })} />);
    const strip = screen.getByTestId("context-status-strip");
    expect(strip).toHaveAttribute("data-summary-status", "running");
    expect(strip.className).toContain("is-running");
    expect(screen.getByTestId("summary-status-text")).toHaveTextContent("正在压缩长对话…");
    expect(screen.getByTestId("summary-covered-count")).toHaveTextContent("已覆盖 80 条");
    // 未失败不提供错误展开入口
    expect(screen.queryByTestId("summary-error-toggle")).toBeNull();
  });

  it("压缩完成：展示完成态与覆盖条数", () => {
    render(<ContextStatusStrip summary={summary({ status: "completed" })} />);
    expect(screen.getByTestId("summary-status-text")).toHaveTextContent("已完成压缩");
    expect(screen.getByTestId("context-status-strip").className).toContain("is-completed");
  });

  it("压缩失败：默认折叠，展开后展示 error_code 与原始错误原文", () => {
    render(
      <ContextStatusStrip
        summary={summary({
          status: "failed",
          error_code: "summary_timeout",
          error: "provider timeout",
        })}
      />,
    );
    expect(screen.getByTestId("summary-status-text")).toHaveTextContent("压缩失败");
    expect(screen.queryByTestId("summary-error-detail")).toBeNull();

    fireEvent.click(screen.getByTestId("summary-error-toggle"));
    expect(screen.getByTestId("summary-error-code")).toHaveTextContent("summary_timeout");
    expect(screen.getByTestId("summary-error-text")).toHaveTextContent("provider timeout");
    expect(screen.getByTestId("summary-error-detail")).toHaveTextContent("deepseek / deepseek-v4.1-flash");
  });

  it("失败但服务端未给 error 原文时如实说明缺失，不合成空结果", () => {
    render(
      <ContextStatusStrip summary={summary({ status: "failed", error_code: null, error: null })} />,
    );
    fireEvent.click(screen.getByTestId("summary-error-toggle"));
    expect(screen.getByTestId("summary-error-text")).toHaveTextContent("服务端未提供 error 原文");
    // error_code 缺失时不渲染该行，也不显示 null 字符串
    expect(screen.queryByTestId("summary-error-code")).toBeNull();
  });

  it("恢复按钮：没有真实 onRegenerate 时不渲染", () => {
    render(<ContextStatusStrip summary={summary({ status: "failed", error: "x" })} />);
    expect(screen.queryByTestId("summary-regenerate")).toBeNull();
  });

  it("恢复按钮：失败记录 + 真实回调时渲染，点击传真实 summary_id", () => {
    const onRegenerate = vi.fn();
    render(
      <ContextStatusStrip
        summary={summary({ status: "failed", error: "x" })}
        onRegenerate={onRegenerate}
      />,
    );
    fireEvent.click(screen.getByTestId("summary-regenerate"));
    expect(onRegenerate).toHaveBeenCalledWith("s1");
  });

  it("恢复按钮：completed 状态不渲染，除非用户显式请求", () => {
    const onRegenerate = vi.fn();
    const { unmount } = render(
      <ContextStatusStrip
        summary={summary({ status: "completed" })}
        onRegenerate={onRegenerate}
      />,
    );
    expect(screen.queryByTestId("summary-regenerate")).toBeNull();
    unmount();

    render(
      <ContextStatusStrip
        summary={summary({ status: "completed" })}
        onRegenerate={onRegenerate}
        regenerateRequested
      />,
    );
    expect(screen.getByTestId("summary-regenerate")).toBeInTheDocument();
  });

  it("恢复提交中禁用按钮；恢复失败展示原始错误", () => {
    render(
      <ContextStatusStrip
        summary={summary({ status: "failed", error: "x" })}
        onRegenerate={vi.fn()}
        regenerating
        regenerateError="summary_provider_error：provider 不可用"
      />,
    );
    expect(screen.getByTestId("summary-regenerate")).toBeDisabled();
    expect(screen.getByTestId("summary-regenerate")).toHaveTextContent("恢复中…");
    expect(screen.getByTestId("summary-regenerate-error")).toHaveTextContent(
      "summary_provider_error：provider 不可用",
    );
  });

  it("记忆：零条是真实零值，与无数据区分", () => {
    render(<ContextStatusStrip summary={null} memories={[]} />);
    const strip = screen.getByTestId("context-status-strip");
    expect(strip).toHaveAttribute("data-memory-count", "0");
    expect(screen.getByTestId("memory-status-text")).toHaveTextContent("长期记忆暂无记录");
  });

  it("记忆：统计 active 条数并单列已删除条数", () => {
    render(
      <ContextStatusStrip
        summary={null}
        memories={[memory("mem-1", "active"), memory("mem-2", "active"), memory("mem-3", "deleted")]}
      />,
    );
    expect(screen.getByTestId("context-status-strip")).toHaveAttribute("data-memory-count", "2");
    expect(screen.getByTestId("memory-status-text")).toHaveTextContent("长期记忆 2 条");
    expect(screen.getByTestId("memory-status-row")).toHaveTextContent("已删除 1 条");
  });

  it("记忆作用域不可用时展示服务端给出的真实原因", () => {
    render(
      <ContextStatusStrip
        summary={null}
        memories={[]}
        memoryScopeNote="当前聊天没有绑定项目，不读写长期记忆。"
      />,
    );
    expect(screen.getByTestId("memory-scope-note")).toHaveTextContent(
      "当前聊天没有绑定项目，不读写长期记忆。",
    );
  });
});
